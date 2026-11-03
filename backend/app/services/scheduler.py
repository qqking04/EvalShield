# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""定时调度器：后台守护线程，按任务 trigger_mode=SCHEDULED + schedule_cron 触发执行。

实现：每 30 秒扫描一次，将 cron 命中当前分钟的任务投递到 task_runner 后台线程执行。
投递幂等：同一任务同一分钟内只触发一次（内存去重 + 运行中防重入 + Redis 分布式锁）。

分布式锁（Redis）：当环境变量 REDIS_URL 配置时，使用 SET key value NX EX 60 获取锁，
防止多实例部署时重复触发同一任务。无 Redis 时优雅降级为单实例内存锁。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import text

from ..config import settings
from ..database import SessionLocal
from ..models import BillingQuota, TestTask
from ..utils.cron import parse_cron
from .task_runner import is_running, launch_task_async

logger = logging.getLogger("evalshield.scheduler")

SCAN_INTERVAL_SEC = 30  # 扫描间隔（秒），cron 精度为分钟
_last_triggered: dict[int, str] = {}  # task_id -> "YYYYMMDDHHMM"
_lock = threading.Lock()

# A7：discover 任务中间态周期回收——每 5 分钟执行一次（30s tick × 10 次节流）
INFLIGHT_SCAN_EVERY_TICKS = 10
_inflight_tick_counter = 0

# T6b：账期周期 job（仅 saas 形态）——每日 00:10 后首个 tick 触发，进程内日期去重
BILLING_CYCLE_HOUR, BILLING_CYCLE_MINUTE = 0, 10
_billing_last_run_date: str | None = None

# 参与周期回收的中间态（不含 WAITING_HUMAN：人机等待有独立 DISCOVER_HUMAN_WAIT_TIMEOUT 超时）
_INFLIGHT_SCAN_STATES = ["PENDING", "LOGINNING", "DISCOVERING", "GENERATING", "VALIDATE"]

# 分布式锁配置（可选）
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return None
    try:
        import redis as _redis

        _redis_client = _redis.from_url(
            redis_url, socket_connect_timeout=3, socket_timeout=3
        )
        _redis_client.ping()
        logger.info("scheduler Redis 分布式锁已就绪: %s", redis_url)
        return _redis_client
    except Exception:
        logger.warning("scheduler Redis 不可用，降级为内存锁")
        return None


def _acquire_lock(task_id: int) -> bool:
    """尝试获取分布式锁（60 秒 TTL），获取成功返回 True。"""
    r = _get_redis()
    if r is None:
        return True  # 无 Redis 时跳过锁检查
    lock_key = f"evalshield:scheduler:lock:{task_id}"
    try:
        acquired = r.set(lock_key, "1", nx=True, ex=60)
        return bool(acquired)
    except Exception:
        logger.warning("Redis set lock failed for task %s", task_id)
        return True  # 降级：锁失败时允许执行


def _release_lock(task_id: int) -> None:
    r = _get_redis()
    if r is not None:
        lock_key = f"evalshield:scheduler:lock:{task_id}"
        try:
            r.delete(lock_key)
        except Exception:
            pass


def next_run_at(task: TestTask) -> str | None:
    """计算任务下一次执行时间（动态计算，不落库）。

    时区口径与 _tick 保持一致：用服务器本地时间（datetime.now()），
    避免展示时间与实际触发时间相差 8 小时的时区偏差。
    """
    if task.trigger_mode != "SCHEDULED" or not task.schedule_cron:
        return None
    cron = parse_cron(task.schedule_cron)
    if cron is None:
        return None
    nxt = cron.next_after(datetime.now().replace(microsecond=0))
    return nxt.isoformat(timespec="seconds") if nxt else None


def _tick() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(TestTask)
            .filter(
                TestTask.deleted_at.is_(None),
                TestTask.trigger_mode == "SCHEDULED",
                TestTask.schedule_cron.isnot(None),
            )
            .all()
        )
        now = datetime.now()
        minute_key = now.strftime("%Y%m%d%H%M")
        for t in rows:
            cron = parse_cron(t.schedule_cron)
            if cron is None or not cron.matches(now):
                continue
            if _is_triggered(t.id, minute_key):
                continue
            if is_running(t.id):
                continue
            if not _acquire_lock(t.id):
                logger.info("scheduler task %s 被其他实例锁定，跳过", t.task_no)
                continue
            _mark_triggered(t.id, minute_key)
            logger.info("scheduler trigger task %s（%s）", t.task_no, t.name)
            launch_task_async(t.id)
    except Exception:  # noqa: BLE001
        logger.exception("scheduler tick 异常")
    finally:
        db.close()


def _scan_inflight_discover_jobs() -> int:
    """A7：discover 任务中间态周期回收。

    对超过 DISCOVER_HARD_TIMEOUT 秒无更新的中间态任务置 FAILED（进程内协程
    意外丢失、无重启场景下的兜底）。异常仅记录日志，不中断调度主循环。
    返回回收行数（异常时返回 0）。
    """
    db = SessionLocal()
    try:
        result = db.execute(
            text(
                "UPDATE discover_jobs SET status='FAILED', "
                "error_message='任务超时中断（周期回收）', finished_at=now(), updated_at=now() "
                "WHERE status = ANY(:states) AND deleted_at IS NULL "
                "AND updated_at < now() - (:hard * interval '1 second')"
            ),
            {"states": _INFLIGHT_SCAN_STATES, "hard": settings.DISCOVER_HARD_TIMEOUT},
        )
        db.commit()
        n = result.rowcount or 0
        if n:
            logger.info("discover 中间态周期回收：置 FAILED %s 行", n)
        return n
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("discover 中间态周期回收异常（不中断主循环）")
        return 0
    finally:
        db.close()


def _scan_stale_src_tasks() -> int:
    """SRC 扫描任务中间态周期回收（与 discover 回收同构）。

    异常仅记录日志，不中断调度主循环；返回回收行数（异常时返回 0）。
    """
    db = SessionLocal()
    try:
        from ..commercial.services.src_audit import recover_stale_src_tasks  # 懒加载商业层

        n = recover_stale_src_tasks(db, reason="任务超时中断（周期回收）")
        return n
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("SRC 中间态周期回收异常（不中断主循环）")
        return 0
    finally:
        db.close()


def _run_billing_cycle_if_due() -> None:
    """T6b 账期 job：仅 saas 形态、每日 00:10 后首个 tick 跑一次（进程内日期去重）。

    run_billing_cycle 自身幂等（前滚后 period_end 推后、状态落库重算稳定、提醒 ref_no 去重），
    重启后当天仍会补跑一次，安全。异常仅记录日志，不中断调度主循环。
    """
    global _billing_last_run_date
    if settings.EDITION != "saas":
        return
    now = datetime.now()
    if (now.hour, now.minute) < (BILLING_CYCLE_HOUR, BILLING_CYCLE_MINUTE):
        return
    today = now.strftime("%Y%m%d")
    if _billing_last_run_date == today:
        return
    _billing_last_run_date = today
    from ..commercial.services.billing_cycle import run_billing_cycle  # 懒加载商业层

    db = SessionLocal()
    try:
        stats = run_billing_cycle(db)
        logger.info("billing cycle job 完成: %s", stats)
    except Exception:  # noqa: BLE001
        db.rollback()
        _billing_last_run_date = None  # 失败允许下个 tick 重试
        logger.exception("billing cycle job 异常（不中断主循环）")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# ES8 M4：定时监控 tick（三形态均可，能力位 monitor 关闭时直接 return）
# ---------------------------------------------------------------------------
def _run_monitors_if_due() -> None:
    """每 tick 跑一次 monitor 状态机（评估上轮批次 + 触发到期 monitor）。

    能力位门控：feature_enabled("monitor") 为假（community 默认、enterprise
    未授权）时不扫描；内部各步自带异常吞并，这里再兜一层保证主循环不中断。
    """
    from ..enterprise.features import feature_enabled

    if not feature_enabled("monitor"):
        return
    from .monitor import run_monitors_once  # 懒加载，避免无 monitor 场景引入依赖

    run_monitors_once()


# ---------------------------------------------------------------------------
# ES8 M4：企业版账期用量重置（仅 enterprise；与 saas 的 billing cycle 独立）
# ---------------------------------------------------------------------------
QUOTA_RESET_HOUR, QUOTA_RESET_MINUTE = 0, 15  # 每日 00:15 后首个 tick 触发
_quota_reset_last_run_date: str | None = None


def _run_quota_reset_if_due(now: datetime | None = None) -> int:
    """enterprise 每日 job：billing_quotas 到 period_end 的行四量清零 + 账期前滚。

    隔离约束（方案 §5.4）：
    - 仅 enterprise 形态运行；saas 的账期由 _run_billing_cycle_if_due 负责，互不干涉；
    - 绝不写 sub_status、不做 PAST_DUE 拦截（订阅状态机完全归 saas billing cycle）。
    到期提醒复用 subscription.renewing 事件（dedup_key 按租户+新账期去重）。
    进程内日期去重，幂等可重跑；返回清零行数。
    """
    global _quota_reset_last_run_date
    if settings.EDITION != "enterprise":
        return 0
    now = now or datetime.now()
    if (now.hour, now.minute) < (QUOTA_RESET_HOUR, QUOTA_RESET_MINUTE):
        return 0
    today = now.strftime("%Y%m%d")
    if _quota_reset_last_run_date == today:
        return 0
    _quota_reset_last_run_date = today
    db = SessionLocal()
    try:
        from ..commercial.services.billing_cycle import _month_anchor  # 月初锚定单一口径
        from .notifications import emit as notify_emit

        now_utc = datetime.now(timezone.utc)
        p_start, p_end = _month_anchor(now_utc)  # 同日运行所有行共用同一新账期锚点
        rows = (
            db.query(BillingQuota)
            .filter(BillingQuota.period_end.isnot(None), BillingQuota.period_end <= now_utc)
            .all()
        )
        reset = 0
        for q in rows:
            # 四量清零（token_used/credits 不属账期量，保持不动）
            q.task_used = 0
            q.eval_used = 0
            q.storage_used_mb = 0
            q.api_calls_used = 0
            q.period_start, q.period_end = p_start, p_end
            db.add(q)
            reset += 1
        db.commit()
        for q in rows:  # 提醒走统一 emit（独立线程提交，与本地事务解耦）
            notify_emit(
                q.tenant_id,
                "subscription.renewing",
                {
                    "title": "本账期用量已重置",
                    "content": (
                        f"新账期 {p_start.strftime('%Y-%m-%d')} ~ {p_end.strftime('%Y-%m-%d')}，"
                        "任务/评测/存储/API 调用用量已清零。"
                    ),
                    "dedup_key": f"QUOTARESET|{q.tenant_id}|{p_start.strftime('%Y%m')}",
                },
                severity="LOW",
            )
        if reset:
            logger.info("quota reset job 完成：清零 %s 行账期用量", reset)
        return reset
    except Exception:  # noqa: BLE001
        db.rollback()
        _quota_reset_last_run_date = None  # 失败允许下个 tick 重试
        logger.exception("quota reset job 异常（不中断主循环）")
        return 0
    finally:
        db.close()


def _is_triggered(task_id: int, minute_key: str) -> bool:
    with _lock:
        return _last_triggered.get(task_id) == minute_key


def _mark_triggered(task_id: int, minute_key: str) -> None:
    with _lock:
        _last_triggered[task_id] = minute_key


# ---------------------------------------------------------------------------
# ES8 M8：在线评测采样评分 tick（trace 摄入 → 抽样 → eval_trace → 低分回流）
# ---------------------------------------------------------------------------
TRACE_EVAL_BATCH_LIMIT = 20  # 每 tick 处理 PENDING trace 上限


def process_trace_eval_batch(db, limit: int = TRACE_EVAL_BATCH_LIMIT) -> int:
    """处理一批 PENDING trace：按租户策略抽样评分 + 低分回流复核队列。

    链路（方案 §9.3）：抽样（random < sample_rate，未抽中置 SKIPPED）→
    eval_trace 评分回写（SCORED / 异常 FAILED）→ overall < low_score_threshold
    入 review_items（source=trace，run_id 借用 trace.id 定位）。
    daily_cap 本地熔断：当日（UTC）该租户 SCORED+FAILED 计数达上限即整批跳过。
    单条评估异常只置该行 FAILED，不影响本批其余。返回处理（评过分）条数。
    """
    import random
    from datetime import datetime, timezone

    from ..models import Trace, TracePolicy
    from . import review_queue
    from .trace_eval import eval_trace, parse_metrics

    pending = (
        db.query(Trace)
        .filter(Trace.eval_status == "PENDING")
        .order_by(Trace.id.asc())
        .limit(limit)
        .all()
    )
    if not pending:
        return 0

    # 当日 UTC 零点（created_at 落库口径为 UTC，熔断计数与之对齐）
    day_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    policy_cache: dict[int, TracePolicy | None] = {}
    scored_count: dict[int, int] = {}  # tenant_id -> 当日已评分数（含本批增量）
    capped: set[int] = set()           # 已触熔断的租户
    processed = 0

    for tr in pending:
        tid = tr.tenant_id
        if tid not in policy_cache:
            policy_cache[tid] = (
                db.query(TracePolicy).filter(TracePolicy.tenant_id == tid).first()
            )
            scored_count[tid] = (
                db.query(Trace)
                .filter(
                    Trace.tenant_id == tid,
                    Trace.eval_status.in_(["SCORED", "FAILED"]),
                    Trace.created_at >= day_start,
                )
                .count()
            )
        pol = policy_cache[tid]
        if pol is None or not pol.enabled:
            continue  # 无策略/未启用：保持 PENDING 等策略开启
        if tid in capped or scored_count[tid] >= int(pol.daily_cap):
            capped.add(tid)  # daily_cap 成本闸门：本 tick 该租户熔断跳过
            continue
        if random.random() >= float(pol.sample_rate):
            tr.eval_status = "SKIPPED"
            db.commit()
            continue
        try:
            result = eval_trace(db, tr, metrics=parse_metrics(pol.judge_metrics))
            tr.scores = json.dumps(result, ensure_ascii=False)
            tr.eval_status = "SCORED"
            db.commit()
            processed += 1
            scored_count[tid] += 1
        except Exception:  # noqa: BLE001 - 单条评估故障：置 FAILED 不拖垮本批
            logger.exception("trace %s 评分失败（置 FAILED）", tr.id)
            db.rollback()
            db.query(Trace).filter(Trace.id == tr.id).update(
                {Trace.eval_status: "FAILED"}, synchronize_session=False
            )
            db.commit()
            processed += 1
            scored_count[tid] += 1
            continue
        # 低分回流（独立于评分事务；失败不影响已回写的 SCORED）
        try:
            scores_blob = json.loads(tr.scores or "{}")
            overall = float(scores_blob.get("overall", 1.0))
            if overall < float(pol.low_score_threshold) and not tr.reviewed:
                review_queue.enqueue(
                    db,
                    tenant_id=tid,
                    source=review_queue.SRC_TRACE,
                    run_id=int(tr.id),   # source_ref 借用 run_id 承载 trace_id
                    item_index=0,
                    context={
                        "trace_id": int(tr.id),
                        "source": tr.source,
                        "request": (tr.request or "")[:2000],
                        "response": (tr.response or "")[:2000],
                        "model": tr.model,
                        "occurred_at": tr.occurred_at.isoformat() if tr.occurred_at else None,
                        **scores_blob,
                    },
                    auto_verdict="FAIL",
                    auto_confidence=round(1.0 - overall, 4),
                    reason=f"trace overall {overall} < {pol.low_score_threshold}",
                )
                db.query(Trace).filter(Trace.id == tr.id).update(
                    {Trace.reviewed: True}, synchronize_session=False
                )
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("trace %s 低分回流异常（不中断批处理）", tr.id)
    return processed


def _run_trace_eval_if_due() -> None:
    """scheduler 每 tick 消费 ≤20 条 PENDING trace（异常仅记日志不中断主循环）。"""
    db = SessionLocal()
    try:
        n = process_trace_eval_batch(db)
        if n:
            logger.info("trace eval tick：完成 %s 条评分", n)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("scheduler trace eval 异常（不中断主循环）")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# ES8 M12：数据保留日清理 + 注销到期匿名化（每日 00:20 后首个 tick，日期去重）
#   purge 三形态通用；anonymization 服务内部仅消费 CANCELED 订阅（saas 概念），
#   非 saas 形态天然空转，仍统一在 job 层自门控 saas 以省扫描。
# ---------------------------------------------------------------------------
RETENTION_CYCLE_HOUR, RETENTION_CYCLE_MINUTE = 0, 20
_retention_last_run_date: str | None = None


def _run_retention_cycle_if_due() -> None:
    """ES8 M12 日任务：先按策略分批清理过期数据，再处理注销到期匿名化。

    run_retention_purge / run_anonymization 自身幂等（分批 ≤5000 行/轮，
    未清完的下一个 tick 日期继续按同策略消化；匿名化完成即置
    anonymize_after=NULL 防重跑）。异常仅记录日志，不中断调度主循环。
    """
    global _retention_last_run_date
    now = datetime.now()
    if (now.hour, now.minute) < (RETENTION_CYCLE_HOUR, RETENTION_CYCLE_MINUTE):
        return
    today = now.strftime("%Y%m%d")
    if _retention_last_run_date == today:
        return
    _retention_last_run_date = today
    from .retention import run_anonymization, run_retention_purge

    db = SessionLocal()
    try:
        stats = run_retention_purge(db)
        if stats["deleted"]:
            logger.info("retention purge 完成: %s", stats)
        if settings.EDITION == "saas":
            anon = run_anonymization(db)
            if anon["anonymized"]:
                logger.info("注销到期匿名化完成: %s", anon)
    except Exception:  # noqa: BLE001
        db.rollback()
        _retention_last_run_date = None  # 失败允许下个 tick 重试
        logger.exception("retention cycle job 异常（不中断主循环）")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# ES8 M11：缺陷工单同步——gitee 状态回写日轮询（每日 00:30 后首个 tick，日期去重）
#   github 走 webhook 推模式无需轮询；jira 出站单向不回写。
#   能力位门控 feature_enabled("defect_sync")。
# ---------------------------------------------------------------------------
DEFECT_SYNC_POLL_HOUR, DEFECT_SYNC_POLL_MINUTE = 0, 30
_defect_sync_last_run_date: str | None = None


def _run_defect_sync_poll_if_due() -> None:
    """ES8 M11 日任务：轮询 gitee link 的外部工单状态并回写缺陷（≤200 links/轮）。

    run_gitee_poll_once 内部逐条 try/except，单条故障 rollback 跳过不拖垮整批。
    异常仅记录日志并重置日期去重位（允许下个 tick 重试），不中断调度主循环。
    """
    global _defect_sync_last_run_date
    from ..enterprise.features import feature_enabled

    if not feature_enabled("defect_sync"):
        return
    now = datetime.now()
    if (now.hour, now.minute) < (DEFECT_SYNC_POLL_HOUR, DEFECT_SYNC_POLL_MINUTE):
        return
    today = now.strftime("%Y%m%d")
    if _defect_sync_last_run_date == today:
        return
    _defect_sync_last_run_date = today
    from .defect_sync.gitee import run_gitee_poll_once

    db = SessionLocal()
    try:
        stats = run_gitee_poll_once(db)
        if stats:
            logger.info("defect-sync gitee 轮询完成: %s 条 link", stats)
    except Exception:  # noqa: BLE001
        db.rollback()
        _defect_sync_last_run_date = None  # 失败允许下个 tick 重试
        logger.exception("defect-sync gitee 轮询 job 异常（不中断主循环）")
    finally:
        db.close()


def _loop() -> None:
    global _inflight_tick_counter
    while True:
        try:
            _tick()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler 主循环异常")
        # A7：每 5 分钟（10 个 tick）执行一次 discover 中间态周期回收
        _inflight_tick_counter += 1
        if _inflight_tick_counter >= INFLIGHT_SCAN_EVERY_TICKS:
            _inflight_tick_counter = 0
            try:
                _scan_inflight_discover_jobs()
            except Exception:  # noqa: BLE001
                logger.exception("scheduler inflight 周期扫描异常")
            # SRC：扫描任务僵死周期回收（同 10 tick 节奏）
            try:
                _scan_stale_src_tasks()
            except Exception:  # noqa: BLE001
                logger.exception("scheduler src 僵死周期回收异常")
        # T6b：账期状态机每日 job（内部自门控 saas + 00:10 + 日期去重）
        try:
            _run_billing_cycle_if_due()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler billing cycle 异常")
        # ES8 M4：定时监控 tick（内部自门控能力位 monitor）
        try:
            _run_monitors_if_due()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler monitors 异常")
        # ES8 M4：企业版账期用量重置（内部自门控 enterprise + 00:15 + 日期去重）
        try:
            _run_quota_reset_if_due()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler quota reset 异常")
        # ES8 M8：在线评测采样评分 tick（每 tick ≤20 条 PENDING trace）
        try:
            _run_trace_eval_if_due()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler trace eval 异常")
        # ES8 M12：数据保留日清理 + 注销到期匿名化（内部自门控 00:20 + 日期去重）
        try:
            _run_retention_cycle_if_due()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler retention cycle 异常")
        # ES8 M11：gitee 工单状态回写日轮询（内部自门能力位 defect_sync + 00:30 + 日期去重）
        try:
            _run_defect_sync_poll_if_due()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler defect-sync poll 异常")
        time.sleep(SCAN_INTERVAL_SEC)


def start_scheduler() -> None:
    """启动调度守护线程（幂等，重复调用不重复启动）。"""
    if getattr(start_scheduler, "_started", False):  # noqa: B008
        return
    th = threading.Thread(target=_loop, name="evalshield-scheduler", daemon=True)
    th.start()
    start_scheduler._started = True  # type: ignore[attr-defined]
    logger.info(
        "cron scheduler 已启动（分布式锁=%s）", "已启用" if _get_redis() else "未配置"
    )
