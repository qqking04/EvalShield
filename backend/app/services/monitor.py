# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M4：定时监控与回归告警（Watchdog）执行逻辑（方案 §5.3）。

状态机（不阻塞 tick）：
1. 触发：扫 enabled 且 next_fire_at<=now 的 monitors，条件 UPDATE 抢占
   （last_checked_at/next_fire_at 同句推进，rowcount=1 者胜出，模拟 FOR UPDATE
   SKIP LOCKED 防并发重复触发）→ launch_suite 克隆批次 → 逐任务 launch_task_async
   → 记 last_run_id（批次代表任务 id）。
2. 评估：套件异步执行时，后续 tick 检查批次是否全部进入终态；终态后取批次指标
   逐条 alert_conditions 判定：
   - 越阈值且同 monitor+metric 无未收敛 FIRING → 建 FIRING 告警 + emit('monitor.alert', HIGH)；
   - 已 FIRING 再越阈 → 收敛不重复建；指标回阈值内 → 回填 resolved_at + RESOLVED；
   - 评估完成后把指标快照写入 baseline_metrics（含 run_id 幂等标记，防重复评估）。

时间口径：monitors 全部使用带时区 UTC 时间（next_fire_at/last_checked_at 均为 TIMESTAMPTZ）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from ..database import SessionLocal
from ..deps import AuthContext
from ..errors import BizError
from ..models import Monitor, MonitorAlert, TestTask
from ..utils.cron import next_fire
from .notifications import emit
from .suite_exec import launch_suite
from .task_runner import launch_task_async

logger = logging.getLogger("evalshield.monitor")

# 任务终态集合（与 task_runner 状态机一致；其余视为执行中，下个 tick 再查）
TERMINAL_STATUSES = {"SUCCESS", "FAILED", "COMPLETED_WITH_RISK", "CANCELLED"}

# 支持的告警指标（方案 §5.4：前端下拉与此一致）
# - pass_rate：批次 Σpassed/Σtotal（任务 summary）
# - injection_success_rate：prompt_injection 引擎安全率（summary.key=prompt_injection_safe_rate）
# - hallucination_rate：1 - 幻觉引擎非幻觉通过率（summary.key=hallucination_score）
ALERT_METRICS = ("pass_rate", "injection_success_rate", "hallucination_rate")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    """DB 读出的 timestamptz 在部分驱动/测试栈下可能为 naive，统一补 UTC。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# 触发段
# ---------------------------------------------------------------------------
def _monitor_auth(m: Monitor) -> AuthContext:
    """monitor 触发用的合成身份（租户=monitor 所属租户，user 取创建人）。"""
    return AuthContext(
        user_id=int(m.created_by or 0),
        username="monitor",
        tenant_id=int(m.tenant_id),
    )


def _preempt(db, m: Monitor, now: datetime) -> bool:
    """条件 UPDATE 抢占：仅 enabled 且仍到期的行能把 last_checked_at/next_fire_at 一起推进。

    rowcount=1 才算胜出（并发 tick / 多实例下只有一个执行方触发），
    next_fire_at 同步推进到 cron 的下一个命中点。
    """
    nxt = next_fire(m.cron, now)
    if nxt is None:
        # 异常表达式或 400 天内不可能命中：置远期防止每 tick 空转
        nxt = now
    res = db.execute(
        text(
            "UPDATE monitors SET last_checked_at=:now, next_fire_at=:nxt, updated_at=:now "
            "WHERE id=:id AND enabled=TRUE AND next_fire_at<=:now"
        ),
        {"now": now, "nxt": nxt, "id": m.id},
    )
    db.commit()
    return (res.rowcount or 0) == 1


def fire_monitor(db, m: Monitor) -> list[int]:
    """立即触发一个 monitor（tick 到期与 run-now 共用）。

    返回批次任务 id 列表；社区版限额（check_limit→BizError）等异常向上抛出，
    由调用方决定吞或与调度解耦。
    """
    result = launch_suite(db, int(m.suite_id), _monitor_auth(m))
    ids: list[int] = list(result.get("created_task_ids") or [])
    if not ids:
        logger.warning("monitor %s 触发但套件无可克隆任务", m.id)
        return []
    # 批次代表任务 id 落库（评估段按 suite_id + created_at 归批）
    db.execute(
        text("UPDATE monitors SET last_run_id=:rid, updated_at=:now WHERE id=:id"),
        {"rid": ids[0], "now": _utcnow(), "id": m.id},
    )
    db.commit()
    for tid in ids:
        launch_task_async(tid)
    logger.info("monitor %s（%s）触发批次：%s", m.id, m.name, ids)
    return ids


def _process_due(db, now: datetime) -> int:
    """扫描到期 monitor 并触发，返回本轮触发数。"""
    rows = (
        db.query(Monitor)
        .filter(Monitor.enabled.is_(True), Monitor.next_fire_at.isnot(None), Monitor.next_fire_at <= now)
        .all()
    )
    fired = 0
    for m in rows:
        if not _preempt(db, m, now):
            continue  # 被并发执行方抢占，跳过
        try:
            fire_monitor(db, m)
            fired += 1
        except BizError as exc:
            # 商业限额拒绝（社区版 scheduler 关闭等）：不重试刷屏，记日志
            logger.warning("monitor %s 触发被拒：%s", m.id, exc)
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("monitor %s 触发异常（不中断本轮）", m.id)
    return fired


# ---------------------------------------------------------------------------
# 评估段
# ---------------------------------------------------------------------------
def _batch_tasks(db, m: Monitor) -> list[TestTask]:
    """取 monitor 最近批次的全部克隆任务（suite_id 相同且 created_at 与代表任务一致）。"""
    if not m.last_run_id:
        return []
    rep = (
        db.query(TestTask)
        .filter(TestTask.id == m.last_run_id, TestTask.deleted_at.is_(None))
        .first()
    )
    if rep is None:
        return []
    return (
        db.query(TestTask)
        .filter(
            TestTask.suite_id == rep.suite_id,
            TestTask.created_at == rep.created_at,
            TestTask.deleted_at.is_(None),
        )
        .all()
    )


def _batch_metrics(tasks: list[TestTask]) -> dict[str, float]:
    """批次级指标汇总。

    - pass_rate：Σpassed/Σtotal（各任务 summary）；
    - injection_success_rate / hallucination_rate：从各任务 summary.step_results[*].summary
      按引擎 key 匹配取值后求均值（多任务多次出现时）。
      口径映射：injection_success_rate = prompt_injection_safe_rate 的 pass_rate 原值；
                hallucination_rate = 1 - hallucination_score 的 pass_rate 值。
    """
    total = passed = 0
    inj_vals: list[float] = []
    hal_vals: list[float] = []
    for t in tasks:
        s = t.summary if isinstance(t.summary, dict) else {}
        total += int(s.get("total") or 0)
        passed += int(s.get("passed") or 0)
        for sr in s.get("step_results") or []:
            es = (sr or {}).get("summary") or {}
            key = es.get("key")
            val = es.get("pass_rate")
            if val is None:
                continue
            if key == "prompt_injection_safe_rate":
                inj_vals.append(float(val))
            elif key == "hallucination_score":
                # 引擎产出为非幻觉通过率，幻觉率取反
                hal_vals.append(round(1.0 - float(val), 4))
    metrics: dict[str, float] = {}
    if total > 0:
        metrics["pass_rate"] = round(passed / total, 4)
    if inj_vals:
        metrics["injection_success_rate"] = round(sum(inj_vals) / len(inj_vals), 4)
    if hal_vals:
        metrics["hallucination_rate"] = round(sum(hal_vals) / len(hal_vals), 4)
    return metrics


def _breached(op: str, value: float, threshold: float) -> bool:
    if op == "lt":
        return value < threshold
    if op == "gt":
        return value > threshold
    return False


def _conditions(m: Monitor) -> list[dict]:
    try:
        conds = json.loads(m.alert_conditions or "[]")
    except (TypeError, ValueError):
        return []
    return [c for c in conds if isinstance(c, dict) and c.get("metric") in ALERT_METRICS]


def _evaluate_one(db, m: Monitor, now: datetime) -> None:
    """评估一个 monitor 的最近批次：未跑完跳过；已评估（run_id 标记）跳过；终态则判定告警。"""
    tasks = _batch_tasks(db, m)
    if not tasks:
        return
    if any(t.status not in TERMINAL_STATUSES for t in tasks):
        return  # 批次仍有非终态任务：下个 tick 再查
    metrics = _batch_metrics(tasks)
    # 幂等标记：baseline_metrics 里记录已评估的 run_id，防重复评估/重复告警
    try:
        baseline = json.loads(m.baseline_metrics or "{}")
        if not isinstance(baseline, dict):
            baseline = {}
    except (TypeError, ValueError):
        baseline = {}
    if baseline.get("run_id") == m.last_run_id and metrics:
        return

    for cond in _conditions(m):
        metric, op = str(cond["metric"]), str(cond.get("op") or "lt")
        try:
            threshold = float(cond.get("threshold"))
        except (TypeError, ValueError):
            continue
        value = metrics.get(metric)
        if value is None:
            continue  # 本批次未产出该指标：不判定也不恢复
        firing = (
            db.query(MonitorAlert)
            .filter(
                MonitorAlert.monitor_id == m.id,
                MonitorAlert.metric == metric,
                MonitorAlert.state == "FIRING",
                MonitorAlert.resolved_at.is_(None),
            )
            .order_by(MonitorAlert.fired_at.desc())
            .first()
        )
        if _breached(op, value, threshold):
            if firing is not None:
                continue  # 同 monitor+metric 收敛：FIRING 中不重复建
            alert = MonitorAlert(
                monitor_id=m.id,
                run_id=m.last_run_id,
                metric=metric,
                value=value,
                threshold=threshold,
                op=op,
                state="FIRING",
                fired_at=now,
                notified=False,
            )
            db.add(alert)
            db.flush()
            alert.notified = True
            db.commit()
            emit(
                int(m.tenant_id),
                m.notify_rule_event or "monitor.alert",
                {
                    "title": f"[监控告警] {m.name} · {metric}",
                    "content": (
                        f"指标 {metric} = {value} 越过阈值 {op} {threshold}，"
                        f"套件批次 {m.last_run_id} 回归异常。"
                    ),
                    "dedup_key": f"MONALERT|{m.id}|{alert.id}",
                    "monitor_id": m.id,
                    "alert_id": alert.id,
                },
                severity="HIGH",
            )
            logger.info("monitor %s 告警 FIRING：%s %s %s（值 %s）", m.id, metric, op, threshold, value)
            # ES8 M6 旁挂：告警批次最低分样本入复核队列（吞异常，不影响告警主流程）
            try:
                from .review_queue import enqueue_from_monitor_batch

                enqueue_from_monitor_batch(db, m.last_run_id, int(m.tenant_id))
            except Exception as exc:  # noqa: BLE001
                logger.warning("monitor %s 复核入队失败（忽略）: %s", m.id, exc)
        else:
            if firing is not None:
                firing.state = "RESOLVED"
                firing.resolved_at = now
                db.add(firing)
                db.commit()
                logger.info("monitor %s 告警恢复：%s（值 %s 回到 %s %s 内）", m.id, metric, value, op, threshold)

    # 指标快照 + 已评估标记写回 baseline_metrics（LAST_RUN 基线语义）
    baseline.update(metrics)
    baseline["run_id"] = m.last_run_id
    m.baseline_metrics = json.dumps(baseline, ensure_ascii=False)
    db.add(m)
    db.commit()


def _evaluate_pending(db, now: datetime) -> int:
    """扫描所有有 pending 批次的 monitor 并评估，返回评估完成批次数。"""
    rows = db.query(Monitor).filter(Monitor.last_run_id.isnot(None)).all()
    done = 0
    for m in rows:
        try:
            before = m.baseline_metrics
            _evaluate_one(db, m, now)
            db.refresh(m)
            if m.baseline_metrics != before:
                done += 1
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("monitor %s 评估异常（不中断本轮）", m.id)
    return done


# ---------------------------------------------------------------------------
# tick 入口（scheduler 每轮调用）
# ---------------------------------------------------------------------------
def run_monitors_once(now: datetime | None = None) -> dict[str, int]:
    """一个完整 tick：先评估上轮批次，再触发到期 monitor。返回统计。"""
    now = now or _utcnow()
    db = SessionLocal()
    try:
        evaluated = _evaluate_pending(db, now)
        fired = _process_due(db, now)
        return {"fired": fired, "evaluated": evaluated}
    finally:
        db.close()
