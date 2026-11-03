# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""后台任务执行器：把任务引擎链执行放入独立线程，主线程（HTTP 请求）立即返回。

设计要点：
- 每个任务使用独立 DB 会话（SessionLocal），不依赖请求级会话，避免线程安全与生命周期问题。
- 引擎链执行逻辑与同步模式保持一致（创建 TaskStep → 执行 → 汇总 → 报告 → 计费 → 逾期检查）。
- 提供取消检查点：步骤间检测任务状态，若 CANCELLED 则终止后续步骤。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..engines import EngineContext, engine_registry, run_engine_step
from ..engines.registry import discover_engines
from ..models import (
    BillingQuota,
    BillingRecord,
    Defect,
    DiscoverJob,
    EvalRun,
    ProjectVersion,
    Report,
    TaskStep,
    TestCase,
    TestEnvironment,
    TestTask,
)
from .report_sections import STAMP_LABEL
from .notifications import emit as notify_emit
from ..utils.no import gen_no

logger = logging.getLogger("evalshield.runner")

# 运行中的任务集合（用于取消与防重入）
_running: set[int] = set()
_lock = threading.Lock()

# 版本隔离 B9（方案 §2-B9）：商业服务包存在性探测。
# OSS 发布树中 app/commercial/ 物理不存在 → 探测为 False，
# 报告生成中的合规对齐/合规结论分支跳过（该能力为商业版专属），
# 保证核心包 import 干净、不因 B1 搬迁产生运行时 ImportError。
_COMMERCIAL_OK: bool | None = None


def _commercial_available() -> bool:
    global _COMMERCIAL_OK
    if _COMMERCIAL_OK is None:
        try:
            import app.commercial.services.src_audit  # noqa: F401
            _COMMERCIAL_OK = True
        except ImportError:
            _COMMERCIAL_OK = False
    return _COMMERCIAL_OK


def is_running(task_id: int) -> bool:
    with _lock:
        return task_id in _running


def _charge(
    db: Session,
    *,
    tenant_id: int,
    user_id: int | None,
    biz_type: str,
    amount: float = 1.0,
    ref_no: str | None = None,
    description: str = "",
) -> None:
    """计费记账：累加配额用量 + 写流水（配额记录不存在时自动创建默认配额）。

    版本隔离 B6（方案 §2-B6 双保险之二）：saas 形态在计费时点复核
    BillingQuota.expires_at——已排队的长任务订阅到期后，raise 使任务置 FAILED
    （由 launch_task_async._worker 兜底回写），流水记 ES-SUB-0001，防止白跑。
    """
    from ..config import settings
    from ..errors import BizError

    if settings.EDITION == "saas":
        now = datetime.now(timezone.utc)
        sub = db.query(BillingQuota).filter(BillingQuota.tenant_id == tenant_id).first()
        if sub is None or sub.expires_at is None or sub.expires_at < now:
            db.add(
                BillingRecord(
                    record_no=gen_no("BL"),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    biz_type=biz_type,
                    ref_no=ref_no,
                    amount=0.0,
                    unit="COUNT",
                    description="ES-SUB-0001 订阅已到期，任务中止",
                )
            )
            db.commit()  # 流水独立落库，不随上层 rollback 丢失
            raise BizError("ES-SUB-0001", "订阅已到期，续费后立即恢复", http_status=403)
    quota = db.query(BillingQuota).filter(BillingQuota.tenant_id == tenant_id).first()
    if quota is None:
        quota = BillingQuota(tenant_id=tenant_id)
        db.add(quota)
        db.flush()
    if biz_type == "TASK":
        quota.task_used = (quota.task_used or 0) + int(amount)
    elif biz_type == "EVAL":
        quota.eval_used = (quota.eval_used or 0) + int(amount)
    elif biz_type == "API":
        quota.api_calls_used = (quota.api_calls_used or 0) + int(amount)
    db.add(
        BillingRecord(
            record_no=gen_no("BL"),
            tenant_id=tenant_id,
            user_id=user_id,
            biz_type=biz_type,
            ref_no=ref_no,
            amount=float(amount),
            unit="COUNT",
            description=description,
        )
    )


def _save_generated_cases(
    db: Session, task: TestTask, engine_code: str, report_payload: dict[str, Any]
) -> int:
    """CASE_GEN 闭环：把引擎生成的用例自动落库到 test_cases（source=AI_GEN）。"""
    if engine_code != "CASE_GEN":
        return 0
    payload = report_payload or {}
    cases = payload.get("generated_cases") or []
    saved = 0
    for c in cases:
        db.add(
            TestCase(
                case_no=c.get("case_no") or gen_no("C"),
                project_id=task.project_id,
                title=c.get("title") or "AI 生成用例",
                category=c.get("category") or "API",
                source="AI_GEN",
                severity=c.get("severity", "P2"),
                priority=c.get("priority", "MEDIUM"),
                steps=c.get("steps") or [],
                expected=c.get("expected"),
                # ---- 测试用例功能优化：新五段式字段（默认空，向后兼容） ----
                content_schema=c.get("content_schema"),
                preconditions=c.get("preconditions") or [],
                test_data=c.get("test_data") or [],
                assertions=c.get("assertions") or [],
                extract_vars=c.get("extract_vars") or {},
                post_cleanup=c.get("post_cleanup") or [],
                requirement_id=c.get("requirement_id"),
                creator="CASE_GEN",
                tenant_id=task.tenant_id,
            )
        )
        saved += 1
    return saved


def _auto_create_defects(
    db: Session, task: TestTask, engine_code: str, report_payload: dict[str, Any]
) -> int:
    """P2-06：执行链中失败且 source='AGENT_GEN' 的用例自动建缺陷（幂等：同 task+case 不重复）。"""
    created = 0
    try:
        for r in (report_payload or {}).get("results") or []:
            if not isinstance(r, dict):
                continue
            if str(r.get("result") or "").upper() != "FAIL":
                continue
            case_id = r.get("case_id")
            if not case_id:
                continue
            tc = db.get(TestCase, case_id)
            if tc is None or tc.deleted_at is not None or (tc.source or "") != "AGENT_GEN":
                continue
            exists = (
                db.query(Defect.id)
                .filter(
                    Defect.task_id == task.id,
                    Defect.case_id == case_id,
                    Defect.deleted_at.is_(None),
                )
                .first()
            )
            if exists:
                continue
            failures = [str(x) for x in (r.get("failures") or [])][:10]
            detail = "; ".join(failures[:5]) or "断言未通过"
            db.add(
                Defect(
                    defect_no=gen_no("BUG"),
                    project_id=task.project_id,
                    task_id=task.id,
                    case_id=case_id,
                    title=f"[{tc.case_no}] {tc.title} 执行失败",
                    severity=tc.severity or "P2",
                    priority=tc.priority or "MEDIUM",
                    module=tc.module,
                    status="NEW",
                    actual=detail[:2000],
                    expected=tc.expected,
                    evidence=[{"engine": engine_code, "failures": failures}],
                    category="ASSERT",
                    ai_reason=f"任务 {task.task_no} 执行 {engine_code} 引擎失败自动建单",
                    reproduce_steps=tc.steps or [],
                    tenant_id=task.tenant_id,
                    created_by=task.created_by,
                    created_by_name=task.created_by_name,
                )
            )
            created += 1
        if created:
            db.commit()
            logger.info("task %s 自动建缺陷 %d 条（引擎 %s）", task.task_no, created, engine_code)
            # ES8 M3：defect.created 埋点（旁挂 try/except，不影响建单主流程）
            try:
                notify_emit(
                    task.tenant_id,
                    "defect.created",
                    {
                        "task_id": task.id,
                        "task_no": task.task_no,
                        "project_id": task.project_id,
                        "suite_id": task.suite_id,
                        "defect_count": created,
                        "title": f"任务 {task.task_no} 自动创建 {created} 条缺陷",
                    },
                    severity="MEDIUM",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("defect.created 埋点失败（忽略）: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("task %s 自动建缺陷失败（不影响主流程）: %s", task.task_no, exc)
        db.rollback()
    return created


# ---------------------------------------------------------------------------
# T11 / §4.5：EngineResult → EvalRun 回填映射（§3.2 契约，F3 修复）
# ---------------------------------------------------------------------------

_HYBRID_ENGINES = {"RAG_TEST", "HALLUCINATION_TEST"}


def _item_score(engine_code: str, item: dict[str, Any], verdict: str) -> Any:
    """按引擎取条目得分（0~1 或 None）。"""
    if engine_code == "HALLUCINATION_TEST":
        return item.get("score")
    if engine_code == "ETHICS_TEST":
        return item.get("compliance_score")
    if engine_code == "RAG_TEST":
        ragas = item.get("ragas") or {}
        return ragas.get("score") if isinstance(ragas, dict) else None
    if engine_code == "PROMPT_INJECTION":
        scores = item.get("scores") or {}
        return scores.get("combined") if isinstance(scores, dict) else None
    if engine_code in ("JAILBREAK", "PII_LEAK"):
        # P0 安全引擎：SAFE=通过，BYPASSED/LEAK=失败
        return 1 if verdict == "SAFE" else 0
    return 1 if verdict == "PASS" else 0


def _normalize_item_results(engine_code: str, report_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """§3.2：把引擎 report_payload.items/sessions 归一化为 {no,prompt,verdict,score,detail}。

    5 引擎取 payload["items"]；MULTI_TURN_TEST 取 payload["sessions"]（会话级摘要行）。
    任何异常/缺字段返回 []，绝不抛出（F3 健壮性底线）。
    """
    try:
        payload = report_payload if isinstance(report_payload, dict) else {}
        rows: list[dict[str, Any]] = []
        if engine_code == "MULTI_TURN_TEST":
            for i, s in enumerate(payload.get("sessions") or [], 1):
                if not isinstance(s, dict):
                    continue
                rows.append({
                    "no": s.get("session_no") or f"MT-{i:03d}",
                    "prompt": s.get("topic") or "",
                    "verdict": s.get("status") or "SKIP",
                    "score": s.get("consistency_score"),
                    "detail": s,
                })
            return rows
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        for i, it in enumerate(items, 1):
            if not isinstance(it, dict):
                continue
            verdict = str(it.get("verdict") or "SKIP")
            rows.append({
                "no": it.get("item_no") or it.get("no") or f"{i:03d}",
                "prompt": it.get("prompt") or it.get("question") or "",
                "verdict": verdict,
                "score": _item_score(engine_code, it, verdict),
                "detail": it,
            })
        return rows
    except Exception:  # noqa: BLE001
        return []


def _summarize_ragas(report_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """RAG 汇总：优先 payload 顶层 ragas；否则从 items 均值派生；无则 None。"""
    try:
        payload = report_payload if isinstance(report_payload, dict) else {}
        r = payload.get("ragas")
        if isinstance(r, dict) and r:
            return r
        scores = [
            (it.get("ragas") or {}).get("score")
            for it in (payload.get("items") or [])
            if isinstance(it, dict) and isinstance(it.get("ragas"), dict)
        ]
        scores = [float(s) for s in scores if s is not None]
        if not scores:
            return None
        return {"score": round(sum(scores) / len(scores), 4), "grade": None, "breakdown": None}
    except Exception:  # noqa: BLE001
        return None


def _infer_judge_mode(engine_code: str, cfg: dict[str, Any] | None) -> str:
    """§3.2：有 judge_model→MODEL；RAG/幻觉语义→HYBRID；否则 RULE。"""
    cfg = cfg or {}
    if cfg.get("judge_model"):
        return "MODEL"
    if engine_code in _HYBRID_ENGINES:
        return "HYBRID"
    return "RULE"


def _infer_target_type(engine_code: str, cfg: dict[str, Any] | None) -> str:
    """§4.5：有 target_code→按引擎映射（RAG/AGENT/API）；无→MODEL（内置演示）。"""
    cfg = cfg or {}
    if cfg.get("target_code"):
        if engine_code == "RAG_TEST":
            return "RAG"
        if engine_code == "MULTI_TURN_TEST":
            return "AGENT"
        return "API"
    return "MODEL"


def _build_run_snapshot(
    *,
    engine_code: str | None = None,
    engine_version: str | None = None,
    judge_model_code: str | None = None,
    target_mode: str | None = None,
    dataset_code: str | None = None,
    dataset_version: str | None = None,
    temperature: Any = None,
    seed: Any = None,
    activity_id: str | None = None,
) -> dict[str, Any]:
    """§4.6：可复现快照 8 键 + 优化12 §4.1a 活动聚合键 activity_id（恒含键，None 即不属于活动）。"""
    return {
        "engine_code": engine_code,
        "engine_version": engine_version,
        "judge_model_code": judge_model_code,
        "target_mode": target_mode,
        "dataset_code": dataset_code,
        "dataset_version": dataset_version,
        "temperature": temperature,
        "seed": seed,
        "activity_id": activity_id,
    }


def _overall_score(summary: dict[str, Any] | None) -> float | None:
    """§3.2：overall_score 取 pass_rate → avg_ragas → avg_compliance 第一个非空（×100）。"""
    s = summary or {}
    for k in ("pass_rate", "avg_ragas", "avg_compliance"):
        v = s.get(k)
        if v is not None:
            try:
                return round(float(v) * 100, 2)
            except (TypeError, ValueError):
                return None
    return None


def _estimate_run_cost(db: Session, engine_code: str, judge_model: str | None, calls: int) -> float | None:
    """§4.4 成本估算：engine_batch 缺失时降级 None（尽力而为，不抛异常）。"""
    if not judge_model or calls <= 0:
        return None
    try:
        from .engine_batch import estimate_cost  # noqa: PLC0415

        return estimate_cost(db, judge_model, calls, 800, 300)
    except Exception:  # noqa: BLE001
        return None


def _calls_for_engine(engine_code: str, item_count: int) -> int:
    """估算 LLM 调用次数：RAG≈item*3、幻觉≈item*2、其余≈item。"""
    if engine_code == "RAG_TEST":
        return item_count * 3
    if engine_code == "HALLUCINATION_TEST":
        return item_count * 2
    return item_count


def _actual_cost_for_step(db: Session, step_id: int | None) -> float | None:
    """§4.4：gateway_records 按 step 汇总实际成本；无记录/异常→None。"""
    if step_id is None:
        return None
    try:
        from ..models import ModelGatewayRecord

        rows = (
            db.query(ModelGatewayRecord.total_cost)
            .filter(ModelGatewayRecord.step_id == step_id)
            .all()
        )
        if not rows:
            return None
        return round(sum(float(r[0] or 0) for r in rows), 6)
    except Exception:  # noqa: BLE001
        return None


def execute_task_chain(
    db: Session,
    task: TestTask,
    *,
    engines: list[str] | None = None,
    config: dict[str, Any] | None = None,
    case_ids: list[int] | None = None,
) -> tuple[bool, str | None]:
    """执行任务引擎链（同步，在任何线程内调用）。

    返回 (是否成功, 错误信息)。成功与否由 error_msg 判断，与 task.status 一致。
    """
    discover_engines()
    engine_list = engines or (task.engines or [])
    cfg = config or (task.config or {})

    # 引擎开关校验：链中任一引擎被停用（test_engines.status=DISABLED）则拒绝启动
    from ..models import TestEngine
    disabled = (
        db.query(TestEngine.engine_code)
        .filter(TestEngine.engine_code.in_(engine_list), TestEngine.status == "DISABLED")
        .all()
    )
    if disabled:
        codes = "、".join(r[0] for r in disabled)
        task.status = "FAILED"
        task.error_msg = f"引擎已停用，无法执行：{codes}（请在 系统管理-引擎管理 中启用）"
        task.finished_at = datetime.now(timezone.utc)
        db.commit()
        return False, task.error_msg

    # ========== P0-1：环境解析钩子 ==========
    # 若 cfg 带 env_id，则从 TestEnvironment 解析 base_url + auth 注入 cfg；
    # 失败（环境不存在/已软删/无 base_url）则回退原 config，不阻断执行
    cfg = _resolve_env_config(db, cfg, task)

    # 启动前检查点：任务已被取消则不再执行
    db.refresh(task)
    if task.status in ("CANCELLED", "CANCELING"):
        task.status = "CANCELLED"
        task.finished_at = task.finished_at or datetime.now(timezone.utc)
        db.commit()
        return False, "任务已取消，未启动执行"

    task.status = "RUNNING"
    task.progress = 0
    task.started_at = datetime.now(timezone.utc)
    task.finished_at = None
    task.error_msg = None
    task.current_step = engine_list[0] if engine_list else None
    db.commit()

    # 清理旧步骤（保留历史结果为步骤表重建）
    db.query(TaskStep).filter(TaskStep.task_id == task.id).delete()
    db.flush()

    step_total = len(engine_list)
    aggr = {"total": 0, "passed": 0, "failed": 0}
    step_results: list[dict[str, Any]] = []
    error_msg: str | None = None
    risk_msg: str | None = None  # v2.0 P1：质量门禁未达标（非系统故障）
    risk_conclusion: str | None = None  # v2.0 P1：业务结论，写入 task.conclusion
    task_threshold: float | None = None  # BUG-07：引擎质量阈值，回写 summary.threshold 供前端筛选
    cancelled = False

    for idx, engine_code in enumerate(engine_list, 1):
        # 取消检查点（支持 CANCELING 中间态）
        db.expire(task, ["status"])
        db.refresh(task)
        if task.status in ("CANCELLED", "CANCELING"):
            cancelled = True
            break
        engine = engine_registry.get(engine_code)
        if engine is None:
            error_msg = f"引擎 {engine_code} 未注册"
            task.status = "FAILED"
            break
        # W1：按引擎嵌套段合并（对齐 promptfoo per-assertion 配置，子段优先于顶层）
        _eng_overlays = (cfg or {}).get("engines") or {}
        _overlay = _eng_overlays.get(engine_code) or {}
        cfg_eff = {k: v for k, v in (cfg or {}).items() if k != "engines"} | _overlay
        step = TaskStep(
            step_no=gen_no("STP"),
            task_id=task.id,
            seq=idx,
            engine_code=engine_code,
            engine_name=engine.engine_name,
            status="RUNNING",
            config=cfg_eff,
            executor=getattr(task, 'executor', None),  # P2-7: 步骤执行人 = 任务执行人
        )
        db.add(step)
        db.flush()
        ctx = EngineContext(
            task_id=task.id,
            task_no=task.task_no,
            step_id=step.id,
            step_no=step.step_no,
            project_id=task.project_id,
            engine_code=engine_code,
            config=cfg_eff,
            db=db,
            extra={
                "tenant_id": task.tenant_id,
                "case_ids": case_ids or (task.config or {}).get("case_ids"),
            },
        )
        try:
            result, duration = run_engine_step(engine, ctx)
            step.status = (
                "SUCCESS"
                if result.status == "SUCCESS"
                else "SKIPPED"
                if result.status == "SKIPPED"
                else "FAILED"
            )
            step.duration_ms = duration
            step.finished_at = datetime.now(timezone.utc)
            step.result_summary = result.summary
            step.error_msg = result.error
            db.commit()

            # === R2-13: AI 评测引擎自动创建 EvalRun，打通任务侧与评测中心双入口 ===
            # T11/§4.5：回填 item_results/engine_code/dataset_version/run_snapshot/成本（F3 修复）
            if getattr(engine, "engine_type", "") == "AI" and result.status in ("SUCCESS", "FAILED"):
                try:
                    payload = result.report_payload or {}
                    es_id = None
                    es_code = None
                    dataset_version = None
                    item_count = 0
                    if cfg.get("eval_set_id"):
                        es_id = int(cfg["eval_set_id"])
                        from ..models import EvalSet

                        es = db.get(EvalSet, es_id)
                        if es:
                            es_code = es.code
                            dataset_version = es.version
                            item_count = es.item_count or 0
                    item_rows = _normalize_item_results(engine_code, payload)
                    if not item_count:
                        item_count = len(item_rows)
                    # 快照：优先引擎 §4.6 顶层 snapshot，缺失则按 cfg/模型配置组装
                    snap_payload = payload.get("snapshot")
                    judge_model = cfg.get("judge_model")
                    temperature = None
                    seed = None
                    model_note = snap_payload.get("model_fallback_note") if isinstance(snap_payload, dict) else None
                    if isinstance(snap_payload, dict) and snap_payload:
                        judge_model = snap_payload.get("judge_model_code") or judge_model
                        dataset_version = snap_payload.get("dataset_version") or dataset_version
                        temperature = snap_payload.get("temperature")
                        seed = snap_payload.get("seed")
                    else:
                        try:
                            from .engine_llm import resolve_model_config

                            mc = resolve_model_config(db, cfg, tenant_id=task.tenant_id)
                            if mc:
                                judge_model = mc.get("code") or judge_model
                                temperature = mc.get("temperature")
                                seed = mc.get("seed")
                                model_note = mc.get("fallback_note")
                        except Exception:  # noqa: BLE001
                            pass
                    target_mode = payload.get("target_mode") or (
                        "API" if cfg.get("target_code") else "INTERNAL_DEMO"
                    )
                    run_snapshot = (
                        snap_payload
                        if isinstance(snap_payload, dict) and snap_payload
                        else _build_run_snapshot(
                            engine_code=engine_code,
                            engine_version=getattr(engine, "version", None),
                            judge_model_code=judge_model,
                            target_mode=target_mode,
                            dataset_code=es_code,
                            dataset_version=dataset_version,
                            temperature=temperature,
                            seed=seed,
                            activity_id=cfg.get("activity_id"),
                        )
                    )
                    # #1/#3：把环境/模型静默回退留痕补进顶层快照（前端 Popover 透出）
                    if model_note:
                        run_snapshot.setdefault("model_fallback_note", model_note)
                    env_note = cfg.get("_env_fallback_note")
                    if env_note:
                        run_snapshot.setdefault("env_fallback_note", env_note)
                    run = EvalRun(
                        run_no=gen_no("EV"),
                        task_id=task.id,
                        eval_set_id=es_id or 0,
                        eval_set_code=es_code,
                        target_type=_infer_target_type(engine_code, cfg),
                        target_id=str(task.id),
                        model_gateway=cfg.get("model_gateway"),
                        judge_mode=_infer_judge_mode(engine_code, cfg),
                        judge_model=judge_model,
                        status=("SUCCESS" if result.status == "SUCCESS" else "FAILED"),
                        item_results=item_rows,
                        overall_score=_overall_score(result.summary),
                        verdict=("PASS" if result.status == "SUCCESS" else "FAIL"),
                        summary={
                            "source": "TASK_AUTO",
                            "task_no": task.task_no,
                            "engine_code": engine_code,
                            "target_mode": target_mode,
                            # A5：RAG 顶层 ragas 对象持久化，供 eval-runs 详情端点提取
                            "ragas": payload.get("ragas"),
                            "task_summary": result.summary,
                        },
                        started_at=step.started_at,
                        finished_at=step.finished_at,
                        duration_ms=step.duration_ms,
                        engine_code=engine_code,
                        dataset_version=dataset_version,
                        run_snapshot=run_snapshot,
                        estimated_cost=_estimate_run_cost(
                            db, engine_code, judge_model,
                            _calls_for_engine(engine_code, item_count),
                        ),
                        actual_cost=_actual_cost_for_step(db, step.id),
                        created_by=task.created_by,
                        tenant_id=task.tenant_id,
                        # ES10-P-01：任务级暂无知识源配置入口，显式 None 保持列语义完整
                        fact_source_id=None,
                        # ES10-P-02：透传任务的项目版本归因列
                        project_version_id=task.project_version_id,
                    )
                    db.add(run)
                    db.commit()
                    logger.info(
                        "task %s AI引擎 %s 自动创建 EvalRun %s (task_id=%d)",
                        task.task_no, engine_code, run.run_no, task.id,
                    )
                except Exception as _er_exc:  # noqa: BLE001
                    logger.warning(
                        "task %s EvalRun 自动创建失败（不影响主流程）: %s",
                        task.task_no, _er_exc,
                    )
                    db.rollback()

            # CASE_GEN 闭环：生成用例落库
            saved = _save_generated_cases(db, task, engine_code, result.report_payload)
            if saved:
                logger.info("task %s CASE_GEN 落库 %d 条用例", task.task_no, saved)
            db.commit()

            # P2-06 闭环：执行失败的 AGENT_GEN 用例自动建缺陷（幂等，不影响主流程）
            _auto_create_defects(db, task, engine_code, result.report_payload)

            aggr["total"] += result.total or 0
            aggr["passed"] += result.passed or 0
            aggr["failed"] += result.failed or 0
            step_results.append(
                {
                    "engine": engine_code,
                    "status": result.status,
                    "summary": result.summary,
                    "conclusion": result.report_payload.get("conclusion", ""),
                    # v2.0 P3：被测模式（API/INTERNAL_DEMO），供报告横幅与 PDF 水印判定
                    "target_mode": result.report_payload.get("target_mode")
                    or ("API" if cfg.get("target_code") else "INTERNAL_DEMO"),
                    "details": _json_safe(result.report_payload),
                }
            )
            if result.status == "FAILED":
                # v2.0 P1：AI引擎返回FAILED且带评测结果（total>0），视为质量门禁未达标而非执行失败
                _is_ai = getattr(engine, "engine_type", "") == "AI"
                _has_result = _is_ai and (result.total or 0) > 0
                if _has_result:
                    _thr = (result.summary or {}).get("threshold", 0.8)
                    _rate = (result.summary or {}).get("pass_rate", 0.0)
                    if task_threshold is None:
                        task_threshold = float(_thr)
                    risk_msg = risk_msg or f"引擎 {engine_code} 质量未达标"
                    risk_conclusion = risk_conclusion or (
                        result.report_payload.get("conclusion")
                        or f"质量未达标：通过率 {_rate} < 阈值 {_thr}"
                    )
                else:
                    error_msg = error_msg or f"引擎 {engine_code} 执行失败"
        except Exception as exc:  # noqa: BLE001
            import traceback as _tb
            step.status = "FAILED"
            tb = _tb.format_exc()
            step.error_msg = f"{exc.__class__.__name__}: {exc}\n---\n{tb}"
            step.finished_at = datetime.now(timezone.utc)
            # 异常分支也要写入结构化 summary，避免报告图表全空
            step.result_summary = {"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0, "exception": f"{exc.__class__.__name__}: {exc}"}
            aggr["failed"] += 1  # 引擎异常也算一次失败
            step_results.append(
                {
                    "engine": engine_code,
                    "status": "FAILED",
                    "summary": step.result_summary,
                    "conclusion": f"引擎 {engine_code} 异常，未产生任何判定",
                    "details": {"exception": f"{exc.__class__.__name__}: {exc}", "results": []},
                }
            )
            db.commit()
            error_msg = f"引擎 {engine_code} 异常: {exc}"
            break
        task.progress = int(idx / step_total * 90) if step_total else 90
        task.current_step = engine_list[idx] if idx < step_total else None
        db.commit()

    if cancelled:
        task.progress = 100
        task.status = "CANCELLED"
        task.finished_at = datetime.now(timezone.utc)
        task.duration_ms = int(
            (task.finished_at - task.started_at).total_seconds() * 1000
        )
        db.commit()
        return False, "任务已取消"

    # 汇总与报告
    task.progress = 100
    task.summary = {
        "step_results": step_results,
        "total": aggr["total"],
        "passed": aggr["passed"],
        "failed": aggr["failed"],
        "pass_rate": round(aggr["passed"] / aggr["total"], 4) if aggr["total"] else 0.0,
    }
    # BUG-07：回写质量阈值，供列表按 pass_rate < threshold 筛选
    if task_threshold is not None:
        task.summary["threshold"] = task_threshold
    # v2.0 P1：执行成功但质量未达标 → COMPLETED_WITH_RISK（非 FAILED）
    if error_msg:
        task.status = "FAILED"
    elif risk_msg:
        task.status = "COMPLETED_WITH_RISK"
    else:
        task.status = "SUCCESS"
    task.error_msg = error_msg
    task.conclusion = risk_conclusion
    task.finished_at = datetime.now(timezone.utc)
    task.duration_ms = int((task.finished_at - task.started_at).total_seconds() * 1000)
    db.commit()

    # 计费：任务整链执行计 1 次（含失败，属资源消耗）
    _charge(
        db,
        tenant_id=task.tenant_id,
        user_id=task.created_by,
        biz_type="TASK",
        amount=1.0,
        ref_no=task.task_no,
        description=f"任务执行：{task.name}",
    )
    db.commit()

    # BE-8：回写用例执行统计（run_count / pass_rate），让资产列表数据真实可信
    _writeback_case_stats(db, task, step_results)

    # 生成报告
    build_report(db, task)

    # ES8 M3：任务终态埋点（旁挂 try/except，仿 _auto_create_defects 不影响主流程）
    try:
        _failed = task.status == "FAILED"
        notify_emit(
            task.tenant_id,
            "task.failed" if _failed else "task.completed",
            {
                "task_id": task.id,
                "task_no": task.task_no,
                "project_id": task.project_id,
                "suite_id": task.suite_id,
                "task_status": task.status,
                "duration_ms": task.duration_ms,
                "summary": task.summary,
                "error_msg": error_msg,
                "title": f"任务 {task.task_no}（{task.name}）{'执行失败' if _failed else '执行完成'}",
            },
            severity="HIGH" if _failed else "LOW",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("task 终态埋点失败（忽略）: %s", exc)

    # ES8 M5：质量门禁评估（gate_rules 非空才评估；同位置旁挂 try/except 不影响主流程）
    try:
        from .quality_gate import VERDICT_FAILED, evaluate_gate

        gate = evaluate_gate(db, task)
        if gate is not None:
            _fails = [c for c in gate["checks"] if c.get("ok") is False]
            if gate["verdict"] == VERDICT_FAILED:
                _gate_content = "；".join(
                    f"{c['metric']}={c['actual']} 未满足 {c['op']} {c['threshold']}"
                    for c in _fails
                )
            else:
                _gate_content = f"门禁结论：{gate['verdict']}"
            notify_emit(
                task.tenant_id,
                "gate.verdict",
                {
                    "task_id": task.id,
                    "task_no": task.task_no,
                    "project_id": task.project_id,
                    "suite_id": task.suite_id,
                    "verdict": gate["verdict"],
                    "checks": gate["checks"],
                    "title": f"任务 {task.task_no}（{task.name}）质量门禁 {gate['verdict']}",
                    "content": _gate_content,
                    "dedup_key": f"GATE|{task.id}|{task.finished_at.isoformat() if task.finished_at else ''}",
                },
                severity="HIGH" if gate["verdict"] == VERDICT_FAILED else "LOW",
            )
            # ES8 M5 可选增强：GitHub Checks 回写（GITHUB_APP_* 缺配置自动跳过，内部吞异常）
            from .github_checks import publish_gate_check

            publish_gate_check(task, gate)
    except Exception as exc:  # noqa: BLE001
        logger.warning("task 门禁评估失败（忽略）: %s", exc)

    # ES8 M6：低置信逐项入复核队列（同位置旁挂 try/except，不影响主流程；
    # 幂等由 OPEN 态部分唯一索引兜底，DONE 不回写 run 表）
    try:
        from .review_queue import enqueue_from_run

        for _run in db.query(EvalRun).filter(EvalRun.task_id == task.id).all():
            enqueue_from_run(db, _run)
    except Exception as exc:  # noqa: BLE001
        logger.warning("task 复核队列入队失败（忽略）: %s", exc)
    return error_msg is None, error_msg


def _writeback_case_stats(
    db: Session, task: TestTask, step_results: list[dict[str, Any]]
) -> None:
    """BE-8：任务执行完成后回写用例执行统计（run_count / pass_rate / last_actual）。

    从各引擎 step 的 results 中提取每个 case 的判定，做增量加权回写，
    让用例列表「执行次数/通过率」随任务执行真实递增，而非恒为 0。
    同时回填 last_actual（断言实际值摘要，最多 50 条）供前端详情展示。
    """
    try:
        # 汇总各 case 本次判定：{case_id: 'PASS' | 'FAIL'}（全 SKIP 不计）
        verdict: dict[int, str] = {}
        # 汇总各 case 本次断言实际值摘要：{case_id: {step1: {...}, step2: {...}}}
        actuals: dict[int, dict[str, Any]] = {}
        for sr in step_results or []:
            details = sr.get("details") or {}
            for r in details.get("results") or []:
                cid = r.get("case_id")
                if cid is None:
                    continue
                res = (r.get("result") or "").upper()
                if res == "FAIL":
                    verdict[cid] = "FAIL"
                elif res == "PASS" and verdict.get(cid) != "FAIL":
                    verdict[cid] = "PASS"
                # 提取断言明细里的 actual 值（兼容 step_details / items / assertions 三种字段名）
                step_details = (
                    r.get("step_details")
                    or r.get("items")
                    or r.get("assertion_details")
                    or details.get("step_details")
                    or []
                )
                snap = actuals.setdefault(cid, {})
                for i, d in enumerate((step_details or [])[:50]):
                    if isinstance(d, dict) and d.get("actual") is not None:
                        snap[f"step{i+1}"] = {
                            "path": d.get("path"),
                            "op": d.get("op"),
                            "expected": d.get("expected"),
                            "actual": d.get("actual"),
                            "passed": d.get("passed"),
                        }
                # P1-3 fallback: 若嵌套结构为空（API引擎返回扁平单次HTTP断言），
                # 直接把 r 本身当作一条扁平断言结构写进 last_actual
                if not snap and isinstance(r, dict):
                    _mop = {"GET": "eq", "POST": "eq", "PUT": "eq", "DELETE": "eq", "HEAD": "eq"}
                    _rval = (r.get("result") or "").upper()
                    snap["step1"] = {
                        "path": r.get("path") or r.get("title") or "",
                        "op": _mop.get(r.get("method", "GET"), "eq"),
                        "expected": r.get("expected_status") or None,
                        "actual": r.get("status_code") or None,
                        "passed": _rval == "PASS",
                    }
        for cid, res in verdict.items():
            tc = db.get(TestCase, cid)
            if tc is None or tc.deleted_at is not None:
                continue
            old_cnt = int(tc.run_count or 0)
            old_rate = float(tc.pass_rate or 0.0)
            new_cnt = old_cnt + 1
            step_score = 1.0 if res == "PASS" else 0.0
            tc.run_count = new_cnt
            tc.pass_rate = round((old_rate * old_cnt + step_score) / new_cnt, 4)
            # P1-3：回填 last_actual（本次执行断言实际值摘要）
            snap = actuals.get(cid)
            if snap:
                tc.last_actual = snap
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "任务 %s 用例执行统计回写失败（不影响主流程）: %s", task.task_no, exc
        )
        db.rollback()


def _json_safe(obj: Any) -> Any:
    """递归把非 JSON 可序列化对象转换为字符串，保证 report content 落 JSONB 不报错。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return str(obj)


def _resolve_env_config(db: Session, cfg: dict[str, Any], task: TestTask) -> dict[str, Any]:
    """P0-1 环境解析钩子：按 cfg.env_id 查 TestEnvironment 取 base_url+auth 注入 cfg。

    - 有 env_id：查询 TestEnvironment，取 base_url（必需）与 auth（可选），覆盖 cfg 中对应键
    - 失败（环境不存在/已软删/跨租户/base_url 空）：logger.warning，**回退原 cfg，不阻断执行**
    - 无 env_id：原样返回 cfg（旧任务兼容）

    #1 契约说明：三条失败路径"静默回退原 cfg"为**已锁定行为**（断言见
    tests/test_es9_coverage_batch_e.py::TestResolveEnvConfig），不得改为阻断执行。
    留痕方式：回退时向 cfg 注入 ``_env_fallback_note``（请求 env_id vs 原因），
    由 run_task 写入 EvalRun.summary 供报告侧透出。
    """
    env_id = cfg.get("env_id")
    if not env_id:
        return cfg
    try:
        env: TestEnvironment | None = (
            db.query(TestEnvironment)
            .filter(TestEnvironment.id == env_id, TestEnvironment.deleted_at.is_(None))
            .first()
        )
        if env is None:
            logger.warning("任务 %s 引用的环境 env_id=%s 不存在或已软删，回退原 config", task.id, env_id)
            cfg["_env_fallback_note"] = f"环境 env_id={env_id} 不存在或已删除，本次执行使用任务内联配置"
            return cfg
        # 跨租户防御：只允许本租户环境注入
        if env.tenant_id != task.tenant_id:
            logger.warning(
                "任务 %s (tenant=%s) 引用的环境 env_id=%s 属于 tenant=%s，拒绝注入，回退原 config",
                task.id, task.tenant_id, env_id, env.tenant_id,
            )
            cfg["_env_fallback_note"] = f"环境 env_id={env_id} 属其他租户，已拒绝注入，使用任务内联配置"
            return cfg
        if not env.base_url:
            logger.warning("任务 %s 环境 env_id=%s base_url 为空，回退原 config", task.id, env_id)
            cfg["_env_fallback_note"] = f"环境 env_id={env_id} base_url 为空，使用任务内联配置"
            return cfg
        # 注入：base_url 覆盖，auth 合并（cfg 中已有 auth 键则保留原 auth 作更高层覆盖）
        cfg["base_url"] = env.base_url
        if env.auth and not cfg.get("auth"):
            cfg["auth"] = env.auth
        # 同时把 base_url 同步到各引擎专属参数（与前端旧逻辑对齐）
        for eng_cfg_key in ("config__UI_TEST__base_url", "config__API_TEST__base_url", "config__DATAFLOW_TEST__base_url"):
            if eng_cfg_key not in cfg:
                cfg[eng_cfg_key] = env.base_url
        logger.info("任务 %s 环境 env_id=%s 解析成功，注入 base_url=%s", task.id, env_id, env.base_url)
    except Exception as _exc:  # noqa: BLE001
        logger.warning("任务 %s 环境解析异常（回退原 config）: %s", task.id, _exc)
        cfg["_env_fallback_note"] = f"环境 env_id={env_id} 解析异常（{_exc}），使用任务内联配置"
    return cfg


def _ai_quality_metrics(db: Session, t: TestTask) -> dict[str, Any]:
    """P2-09：AI 生成质量指标（ai_confidence / ai_case_count / ai_skip_count）。

    ai_case_count/ai_confidence 复用 report_generator.build_ai_probe_summary（A14/PO-09 统一实现）；
    ai_skip_count 取本项目最近一次探测任务 preview_payload 未回放（UNVERIFIED）用例数。
    """
    from .report_generator import build_ai_probe_summary

    metrics: dict[str, Any] = {"ai_skip_count": 0}
    metrics.update(build_ai_probe_summary(db, t.project_id))
    metrics.setdefault("ai_confidence", None)
    metrics.setdefault("ai_case_count", 0)
    try:
        job = (
            db.query(DiscoverJob)
            .filter(DiscoverJob.project_id == t.project_id, DiscoverJob.deleted_at.is_(None))
            .order_by(DiscoverJob.id.desc())
            .first()
        )
        payload = job.preview_payload if job and isinstance(job.preview_payload, dict) else {}
        if payload:
            metrics["ai_skip_count"] = sum(
                1
                for c in (payload.get("cases") or [])
                if isinstance(c, dict) and c.get("replay_status") == "UNVERIFIED"
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("报告 AI 跳过数统计失败（不影响主流程）: %s", exc)
        db.rollback()
    return metrics


def _dimension_stats(step_results: list[dict]) -> dict[str, Any]:
    """P1-15：六维度统计（功能/UI/性能/安全/数据流/兼容性）+ 性能指标 + 安全扫描结果。

    按 step 引擎归入维度桶，聚合 total/passed/failed/pass_rate；
    性能维度额外汇总 p50/p95/p99/qps/error_rate（取各引擎 summary 中已有指标）；
    安全维度额外汇总 OWASP 各项检测结论。
    """
    # 引擎 → 维度映射（功能=API 接口，数据流=DATAFLOW，UI/兼容性/性能/安全按引擎归类）
    _DIM_OF_ENGINE = {
        "API_TEST": "功能测试",
        "EVAL_ENGINE": "功能测试",
        "DATAFLOW_TEST": "数据流",
        "UI_TEST": "UI 测试",
        "PERF_TEST": "性能测试",
        "LOCUST_PERF": "性能测试",
        "SECURITY_TEST": "安全测试",
        "REDTEAM_TEST": "安全测试",
        "PRIVILEGE_ESCALATION": "安全测试",
        "PROMPT_INJECTION": "安全测试",
    }
    dims: dict[str, dict[str, Any]] = {}
    perf: dict[str, Any] = {}
    sec_items: list[dict] = []
    for sr in step_results or []:
        if not isinstance(sr, dict):
            continue
        engine = str(sr.get("engine") or "")
        dim = _DIM_OF_ENGINE.get(engine, "功能测试")
        s = sr.get("summary") or {}
        bucket = dims.setdefault(dim, {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "engines": []})
        bucket["total"] += int(s.get("total") or 0)
        bucket["passed"] += int(s.get("passed") or 0)
        bucket["failed"] += int(s.get("failed") or 0)
        bucket["skipped"] += int(s.get("skipped") or 0)
        if engine and engine not in bucket["engines"]:
            bucket["engines"].append(engine)
        # 性能指标：直接取引擎 summary 已产出的分位/吞吐
        if dim == "性能测试":
            for k in ("p50_ms", "p95_ms", "p99_ms", "avg_latency_ms", "qps", "rps", "error_rate"):
                if s.get(k) is not None:
                    perf[k] = s.get(k)
        # 安全扫描结果：从 report_payload.results 收集 owasp_id + result
        if dim == "安全测试":
            for r in (sr.get("details") or {}).get("results") or []:
                if isinstance(r, dict) and r.get("owasp_id"):
                    sec_items.append({
                        "owasp_id": r.get("owasp_id"),
                        "attack_type": r.get("attack_type") or r.get("op_type"),
                        "title": r.get("title"),
                        "result": r.get("result"),
                        "status_code": r.get("status_code"),
                    })
    judged = {
        d: {**b, "pass_rate": round(b["passed"] / max(b["total"] - b["skipped"], 1), 4)}
        for d, b in dims.items()
    }
    return {"dimension_stats": judged, "perf_metrics": perf, "security_findings": sec_items}


def _confidence_note(total: int, pass_rate: float) -> str:
    """v2.0 P2：样本量置信度标注（<30 提示不足；≥30 给出 95% 置信区间）."""
    if total <= 0:
        return ""
    if total < 30:
        return f"样本量{total}条<30，结果仅供参考，建议扩充至≥100条"
    z = 1.96
    margin = z * math.sqrt(max(0.0, min(1.0, pass_rate)) * (1 - max(0.0, min(1.0, pass_rate))) / total)
    lower = max(0.0, pass_rate - margin)
    upper = min(1.0, pass_rate + margin)
    return f"95%置信区间：[{lower:.2%}, {upper:.2%}]"


def _build_compliance_conclusion(
    db: Session, t: TestTask, step_details: list[dict]
) -> dict[str, Any] | None:
    """P1：合规结论章节。

    收集 ETHICS/JAILBREAK/PII_LEAK 步骤的违规项，映射中文法规条文，
    计算风险等级并给出整改建议；无安全/AI 步骤时返回 None。

    版本隔离 B9：compliance_mapper 属商业服务（B1 已迁 app/commercial/services/），
    社区形态（OSS 树无该包）直接返回 None——该能力为商业版专属。
    """
    if not _commercial_available():
        return None
    from ..commercial.services.compliance_mapper import risk_category_cn

    related = {"ETHICS_TEST", "JAILBREAK", "PII_LEAK", "REDTEAM_TEST"}
    steps = [
        s for s in step_details
        if isinstance(s, dict) and (s.get("engine") or s.get("engine_code")) in related
    ]
    if not steps:
        return None

    violations: list[dict] = []
    for s in steps:
        code = s.get("engine") or s.get("engine_code")
        details = s.get("details") or {}
        items = details.get("items") or s.get("items") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            verdict = str(it.get("verdict") or "")
            if code == "ETHICS_TEST":
                for v in it.get("violations") or []:
                    if isinstance(v, dict):
                        violations.append({
                            "source_engine": code,
                            "item_no": it.get("item_no"),
                            "severity": v.get("severity", "MINOR"),
                            "description": v.get("reason") or v.get("clause_text") or "",
                            "risk_category": v.get("risk_category"),
                        })
            elif code == "JAILBREAK":
                if verdict == "BYPASSED":
                    violations.append({
                        "source_engine": code, "item_no": it.get("item_no"),
                        "severity": "CRITICAL",
                        "description": f"越狱绕过成功：{it.get('attack_vector') or it.get('prompt') or ''}",
                        "risk_category": "JAILBREAK_BYPASS",
                    })
            elif code == "PII_LEAK":
                if verdict == "LEAK":
                    for h in (it.get("hits") or [])[:20]:
                        if isinstance(h, dict):
                            violations.append({
                                "source_engine": code, "item_no": it.get("item_no"),
                                "severity": h.get("severity", "HIGH"),
                                "description": f"PII 泄露：{h.get('pii_type_cn') or h.get('pii_type') or ''}",
                                "risk_category": "SENSITIVE_PII",
                            })

    # 已有 risk_category 的直接映射，其余按文本归类
    if violations:
        from ..commercial.services.compliance_mapper import classify_risk, get_regulations_for_risk

        cache: dict[str, list[dict]] = {}
        for v in violations:
            cat = v.get("risk_category") or classify_risk(v.get("description", ""), v.get("severity"))
            v["risk_category"] = cat
            v["risk_category_cn"] = risk_category_cn(cat)
            if cat not in cache:
                cache[cat] = get_regulations_for_risk(db, cat, t.tenant_id or 1)
            v["regulations"] = cache[cat]

    sev_rank = {"CRITICAL": 4, "MAJOR": 3, "HIGH": 3, "MODERATE": 2, "MEDIUM": 2, "MINOR": 1}
    worst = max((sev_rank.get(str(v.get("severity", "MINOR")).upper(), 1) for v in violations), default=0)
    risk_level = "HIGH" if worst >= 3 else ("MEDIUM" if worst == 2 else ("LOW" if worst == 1 else "NONE"))

    suggestions: list[str] = []
    if any(v["risk_category"] == "SENSITIVE_PII" for v in violations):
        suggestions.append("对输出中的个人敏感信息启用字段级脱敏，并核查训练/检索数据源是否混入真实 PII。")
    if any(v["risk_category"] == "JAILBREAK_BYPASS" for v in violations):
        suggestions.append("针对越狱样本命中的攻击向量加固系统提示与输入过滤，并在回归集中持续复测。")
    if any(v["risk_category"] in ("POLITICAL", "PORNOGRAPHY", "VIOLENCE", "HATE_SPEECH", "MINOR") for v in violations):
        suggestions.append("接入内容安全审核模型对违法不良信息拦截，按《生成式人工智能服务管理暂行办法》履行处置与报告义务。")
    if not violations:
        suggestions.append("未发现合规违规项，维持现有安全策略并定期回归。")

    return {
        "risk_level": risk_level,
        "violation_count": len(violations),
        "violations": violations,
        "regulations": [
            r for v in violations for r in v.get("regulations") or []
        ],
        "remediation_suggestions": suggestions,
        "signature": {
            "prepared_by": t.created_by_name or "",
            "reviewed_by": t.executor or "",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "stamp": STAMP_LABEL,
        },
    }


def build_report(db: Session, t: TestTask) -> Report:
    """根据任务结果生成结构化报告（存库 + JSON 落盘）。

    报告 content 包含：
    - 基础信息（report_no/task_no/summary...）
    - step_details：各引擎步骤 case 级明细（results / items / cleanup_warnings），
      供前端按 用例/数据分组/断言 三级展开
    - compliance_alignment：各条款的对齐结果（引擎显式对齐 + 引擎级兜底）
    - v2.0：environment 环境指纹（BUG-002）、risk_level/risk_basis 风险等级（BUG-012）、
      报告 JSON 落盘（BUG-015）
    """
    report_no = gen_no("RPT")
    # P2-09：报告闭环增强，summary 增加 AI 生成质量指标
    summary = dict(t.summary or {})
    summary.update(_ai_quality_metrics(db, t))
    # P1-15：六维度统计 + 性能指标 + 安全扫描结果并入 summary，供报告页展示
    try:
        summary.update(_dimension_stats((t.summary or {}).get("step_results") or []))
    except Exception as exc:  # noqa: BLE001
        logger.warning("报告六维度统计失败（不影响主流程）: %s", exc)
    payload = {
        "report_no": report_no,
        "task_no": t.task_no,
        "task_name": t.name,
        "project_code": t.project_code,
        "summary": summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    # ES10-P-01/P-02：报告口径统一注入「事实基准」与「项目版本」
    try:
        _fs = None
        _run = (
            db.query(EvalRun)
            .filter(EvalRun.task_id == t.id, EvalRun.deleted_at.is_(None))
            .order_by(EvalRun.id.desc())
            .first()
        )
        if _run is not None and isinstance(_run.summary, dict):
            _fs = _run.summary.get("fact_source")
        if _fs:
            payload["fact_source"] = _fs
        if t.project_version_id:
            _pv = db.get(ProjectVersion, t.project_version_id)
            if _pv is not None:
                payload["project_version"] = {
                    "id": _pv.id,
                    "version_no": _pv.version_no,
                    "is_baseline": bool(_pv.is_baseline),
                }
        elif t.task_version:
            payload["project_version"] = {"id": None, "version_no": t.task_version, "is_baseline": False}
    except Exception as exc:  # noqa: BLE001
        logger.warning("报告版本/知识源注入失败（不影响主流程）: %s", exc)
    # v2.0 P2：置信度标注（任务级 + 各 AI 引擎步骤级）
    _note = _confidence_note(int(summary.get("total") or 0), float(summary.get("pass_rate") or 0.0))
    if _note:
        payload["confidence_note"] = _note
        summary["confidence_note"] = _note
    for sr in payload.get("summary", {}).get("step_results") or []:
        _s = sr.get("summary") or {}
        _n = _confidence_note(int(_s.get("total") or 0), float(_s.get("pass_rate") or 0.0))
        if _n:
            sr["confidence_note"] = _n
    # v2.0 P3：演示模式标记（任一 AI 步骤 target_mode=INTERNAL_DEMO）
    _demo = any(
        sr.get("target_mode") == "INTERNAL_DEMO"
        for sr in (t.summary or {}).get("step_results") or []
    )
    payload["demo_mode"] = _demo
    summary["demo_mode"] = _demo
    # case 级明细：各步骤 report_payload（用例/数据分组/断言失败/清理告警）持久化
    payload["step_details"] = _json_safe((t.summary or {}).get("step_results") or [])
    # 合规对齐：从任务步骤结果提取并合并
    # 版本隔离 B9：compliance 属商业服务（B1 已迁 app/commercial/services/）。
    # steps 查询为通用逻辑独立执行；社区形态跳过对齐——该能力为商业版专属。
    steps = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == t.id)
        .order_by(TaskStep.seq)
        .all()
    )
    save_report_alignments = None
    if _commercial_available():
        try:
            from ..commercial.services.compliance import (
                merge_compliance_alignments,
                save_report_alignments,
            )

            payload["compliance_alignment"] = merge_compliance_alignments(db, steps)
        except Exception:  # noqa: BLE001
            payload["compliance_alignment"] = []
            save_report_alignments = None
    else:
        payload["compliance_alignment"] = []

    # P1：合规结论章节（违规项 → 中文法规映射 + 风险等级 + 整改建议 + 落款）
    try:
        payload["compliance_conclusion"] = _build_compliance_conclusion(
            db, t, payload.get("step_details") or []
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("合规结论章节生成失败（不影响主流程）: %s", exc)
        payload["compliance_conclusion"] = None

    # ES8 M9：红队专节数据注入（能力位点亮才注入；渲染层纯消费 payload 不查库，
    # 报告四链路与 /api/redteam/coverage、guardrail-package 同源同口径）
    try:
        from ..enterprise.features import feature_enabled

        if feature_enabled("generative_redteam"):
            payload["redteam_enabled"] = True
            _run = (
                db.query(EvalRun)
                .filter(
                    EvalRun.task_id == t.id,
                    EvalRun.engine_code == "JAILBREAK",
                    EvalRun.deleted_at.is_(None),
                )
                .order_by(EvalRun.id.desc())
                .first()
            )
            if _run is not None:
                # 延迟 import：routers 层依赖 database/deps，避免模块级循环
                from ..routers.redteam import build_guardrail_package, coverage_data

                payload["redteam_coverage"] = coverage_data(db, _run)
                payload["redteam_guardrail"] = build_guardrail_package(
                    db, run=_run, tenant_id=t.tenant_id
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("红队专节数据生成失败（不影响主流程）: %s", exc)

    # ---- v2.0 BUG-002：环境指纹采集 ----
    env_dict = _collect_environment(db, t, steps)
    payload["environment"] = env_dict

    # ---- v2.0 BUG-012：风险等级计算（缺陷取本任务已建单的真实严重度）----
    from .risk import compute_risk_level

    blocked = _detect_blocked(steps)
    defect_items: list[dict[str, Any]] = []
    try:
        for d in (
            db.query(Defect)
            .filter(Defect.task_id == t.id, Defect.deleted_at.is_(None))
            .all()
        ):
            defect_items.append({"severity": d.severity, "defect_no": d.defect_no})
    except Exception:  # noqa: BLE001
        defect_items = payload.get("defects") or []
    risk_level, risk_basis = compute_risk_level(
        defect_items,
        int(summary.get("total") or 0),
        int(summary.get("passed") or 0),
        blocked=blocked,
    )

    r = Report(
        report_no=report_no,
        task_id=t.id,
        task_no=t.task_no,
        project_id=t.project_id,
        title=f"{t.name} 测试报告",
        report_type="FULL",
        format="json",
        status="DONE",
        content=payload,
        summary=summary,
        environment=env_dict,
        risk_level=risk_level,
        risk_basis=risk_basis,
        performance_metrics={
            "rt_p50": summary.get("p50_ms"),
            "rt_p95": summary.get("p95_ms"),
            "rt_p99": summary.get("p99_ms"),
            "tps": summary.get("qps") or summary.get("rps"),
            "error_rate": summary.get("error_rate"),
        } if any(summary.get(k) is not None for k in ("p50_ms", "p95_ms", "p99_ms", "qps", "rps", "error_rate")) else None,
        generated_by=t.created_by_name,
        generated_at=datetime.now(timezone.utc),
        tenant_id=t.tenant_id,
        created_by=t.created_by,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    # ---- ES11 E2E 修复：回填本任务产出的 EvalRun.report_id（G4 delivery-readiness
    # 依赖 run→report 关联；此前任务链生成报告后关联恒空）----
    try:
        db.query(EvalRun).filter(
            EvalRun.task_id == t.id,
            EvalRun.report_id.is_(None),
            EvalRun.deleted_at.is_(None),
        ).update({EvalRun.report_id: int(r.id)}, synchronize_session=False)
        db.commit()
    except Exception as _lk_exc:  # noqa: BLE001
        logger.warning("task %s 报告关联回填失败（不影响主流程）: %s", t.task_no, _lk_exc)
        db.rollback()
    # ---- v2.0 BUG-015：报告 JSON 落盘（E 盘 REPORT_DIR）----
    try:
        import json as _json
        from pathlib import Path

        from ..config import settings

        report_json_path = Path(settings.REPORT_DIR) / f"{report_no}.json"
        report_json_path.parent.mkdir(parents=True, exist_ok=True)
        full_report = {
            "report_id": r.id,
            "report_no": report_no,
            "task_id": t.task_no,
            "project_id": t.project_id,
            "title": r.title,
            "report_type": r.report_type,
            "status": r.status,
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
            "environment": env_dict,
            "risk_level": risk_level,
            "risk_basis": risk_basis,
            "content": payload,
            "summary": summary,
        }
        with open(report_json_path, "w", encoding="utf-8") as f:
            _json.dump(full_report, f, ensure_ascii=False, indent=2)
        r.file_path = str(report_json_path)
        r.file_size = report_json_path.stat().st_size
        db.add(r)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("报告 JSON 落盘失败（不影响主流程）: %s", exc)
        db.rollback()
    # 回填 TaskStep.report_ids（前端"报告关联"消费；之前恒为空数组；存整数报告ID）
    try:
        for s in (
            db.query(TaskStep)
            .filter(TaskStep.task_id == t.id)
            .order_by(TaskStep.seq)
            .all()
        ):
            s.report_ids = list(dict.fromkeys((s.report_ids or []) + [r.id]))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    # 合规对齐结果写关联表（前端"报告对齐"详情）
    try:
        if payload.get("compliance_alignment") and save_report_alignments is not None:
            save_report_alignments(db, r, payload["compliance_alignment"])
    except Exception:  # noqa: BLE001
        db.rollback()
    # ---- 版本隔离 B14（方案 §2-B14）：社区版报告 7 天留存（惰性清理，不依赖 scheduler）。
    # 每次新报告产生时删除超 7 天的旧报告（记录 + 磁盘产物）；best-effort，失败不阻塞。
    # 商业 / saas 形态不执行——报告永久留存是付费点。
    from ..config import settings as _st

    if _st.EDITION == "community":
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            stale = db.query(Report).filter(Report.created_at < cutoff).all()
            for old in stale:
                _purge_report_files(old)
            if stale:
                db.query(Report).filter(Report.created_at < cutoff).delete(
                    synchronize_session=False
                )
                db.commit()
                logger.info("社区版报告惰性清理：删除 %d 份超 7 天旧报告", len(stale))
        except Exception as exc:  # noqa: BLE001
            logger.warning("社区版报告惰性清理失败（不阻塞报告生成）: %s", exc)
            db.rollback()
    return r


def _purge_report_files(r: Report) -> None:
    """B14：删除报告磁盘产物（当前唯一产物为 build_report 落盘的 JSON）。

    仅在 file_path 指向已不存在的目录外文件时按路径删除；任何 IO 异常吞掉。
    """
    fp = str(getattr(r, "file_path", None) or "").strip()
    if not fp:
        return
    try:
        from pathlib import Path

        p = Path(fp)
        if p.is_file():
            p.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def _detect_blocked(steps: list[TaskStep]) -> bool:
    """v2.0 BUG-012：阻断检测——某步骤 FAILED 且其后仍有 SKIPPED 步骤 → 视为阻断。"""
    seen_failed = False
    for s in steps or []:
        st = str(getattr(s, "status", "") or "").upper()
        if st == "FAILED":
            seen_failed = True
        elif st == "SKIPPED" and seen_failed:
            return True
    return False


def _collect_environment(db: Session, t: TestTask, steps: list[TaskStep]) -> dict[str, Any]:
    """v2.0 BUG-002：采集报告环境指纹。

    字段：sut_version / sut_branch / sut_commit / sut_url / os / browser /
    browser_version / viewport / dependencies / started_at / finished_at / duration_sec
    采集不到的字段如实留空（前端显示"未采集"），绝不编造。
    """
    import platform

    cfg = dict(t.config or {})
    # 环境地址：优先 env_id 解析出的 TestEnvironment.base_url，兜底 cfg.base_url
    sut_url = cfg.get("base_url") or ""
    env_id = cfg.get("env_id")
    if env_id:
        try:
            env_row = (
                db.query(TestEnvironment)
                .filter(TestEnvironment.id == env_id, TestEnvironment.deleted_at.is_(None))
                .first()
            )
            if env_row and env_row.base_url:
                sut_url = env_row.base_url
        except Exception:  # noqa: BLE001
            pass

    # 浏览器：执行链含 UI 引擎时记录 Playwright Chromium
    browser = ""
    browser_version = ""
    engines_used = {str(getattr(s, "engine_code", "") or "") for s in steps or []}
    if any("UI" in e.upper() for e in engines_used):
        browser = "Chromium (Playwright)"
        try:
            from importlib.metadata import version as _pw_version

            browser_version = _pw_version("playwright")
        except Exception:  # noqa: BLE001
            pass

    viewport = ""
    vp = cfg.get("viewport") or cfg.get("config__UI_TEST__viewport")
    if isinstance(vp, dict) and vp.get("width") and vp.get("height"):
        viewport = f"{vp['width']}x{vp['height']}"
    elif isinstance(vp, str):
        viewport = vp

    # 依赖版本（如实采集已安装的关键依赖）
    deps: list[dict[str, str]] = []
    try:
        from importlib.metadata import version as _pkg_version

        for pkg in ("fastapi", "sqlalchemy", "playwright", "celery", "redis"):
            try:
                deps.append({"name": pkg, "version": _pkg_version(pkg)})
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass

    duration_sec = None
    if t.duration_ms is not None:
        duration_sec = round(int(t.duration_ms) / 1000, 1)

    # ---- 安全报告补全 P2：检测上下文（授权声明 / 检测账号 / 检测方法）----
    # 授权声明：任务配置显式声明优先，否则按平台默认合规声明（自有系统获授权）
    authorization = cfg.get("authorization") or (
        "已确认被测系统属用户自有并获授权检测（EvalShield 平台授权条款）"
    )

    # 检测账号：任务配置 accounts 优先；否则从环境 auth 提取用户名（不采集密码，脱敏如实）
    test_accounts: list[dict[str, str]] = []
    raw_accounts = cfg.get("test_accounts") or cfg.get("accounts")
    if isinstance(raw_accounts, list):
        for a in raw_accounts:
            if isinstance(a, dict) and a.get("username"):
                test_accounts.append({
                    "username": str(a.get("username")),
                    "display_name": str(a.get("display_name") or ""),
                    "role": str(a.get("role") or ""),
                })
    if not test_accounts and env_id:
        try:
            env_row2 = (
                db.query(TestEnvironment)
                .filter(TestEnvironment.id == env_id, TestEnvironment.deleted_at.is_(None))
                .first()
            )
            env_auth = (env_row2.auth or {}) if env_row2 else {}
            basic_user = (env_auth.get("basic") or {}).get("username") if isinstance(env_auth.get("basic"), dict) else None
            if basic_user:
                test_accounts.append({"username": str(basic_user), "display_name": "", "role": "basic"})
        except Exception:  # noqa: BLE001
            pass

    # 检测方法：按实际执行引擎集合推导（如实描述，不编造）
    methods: list[str] = []
    if any(e in {"HTTP_SECURITY_HEADERS", "TLS_CHECK", "STATIC_SECRET_SCAN", "SECURITY_TEST",
                 "API_TEST", "RBAC_TEST", "DATAFLOW_TEST"} for e in engines_used):
        methods.append("HTTP 请求探测")
    if any(e in {"UI_TEST", "CREDENTIAL_STORAGE_TEST", "RECORDING"} or "UI" in e.upper() for e in engines_used):
        methods.append("浏览器自动化")
    if any(e in {"PROMPT_INJECTION", "REDTEAM_TEST", "PRIVILEGE_ESCALATION", "HALLUCINATION_TEST",
                 "MEMORY_LEAKAGE", "RAG_TEST", "MULTI_TURN_TEST", "ETHICS_TEST"} for e in engines_used):
        methods.append("AI 行为对抗判定")
    if any(e in {"STATIC_SECRET_SCAN"} for e in engines_used):
        methods.append("静态资源分析")
    if any(e in {"RBAC_TEST", "PRIVILEGE_ESCALATION"} for e in engines_used):
        methods.append("API 鉴权探测")
    test_method = cfg.get("test_method") or (" + ".join(methods) if methods else "引擎自动执行")

    # 时间统一按东八区展示，避免 started_at(+08:00) 与 finished_at(UTC) 相差 8 小时
    _CST = timezone(timedelta(hours=8))

    def _fmt(dt) -> str:
        if not dt:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_CST)
        return dt.astimezone(_CST).strftime("%Y-%m-%d %H:%M:%S")

    return {
        "sut_version": cfg.get("sut_version") or t.task_version or "",
        "sut_branch": cfg.get("sut_branch") or "",
        "sut_commit": cfg.get("sut_commit") or "",
        "sut_url": sut_url,
        "os": f"{platform.system()} {platform.release()}",
        "browser": browser,
        "browser_version": browser_version,
        "viewport": viewport,
        "dependencies": deps,
        "authorization": authorization,
        "test_accounts": test_accounts,
        "test_method": test_method,
        "started_at": _fmt(t.started_at),
        "finished_at": _fmt(t.finished_at),
        "duration_sec": duration_sec,
    }


def launch_task_async(
    task_id: int, engines: list[str] | None = None, config: dict[str, Any] | None = None
) -> None:
    """把任务放入后台线程执行（幂等：同一任务正在运行时不重复启动）。"""
    with _lock:
        if task_id in _running:
            return
        _running.add(task_id)

    def _worker() -> None:
        db: Session | None = None
        try:
            db = SessionLocal()
            task = db.get(TestTask, task_id)
            if task is None or task.deleted_at is not None:
                return
            execute_task_chain(db, task, engines=engines, config=config)
        except Exception as exc:  # noqa: BLE001
            logger.exception("后台任务 %s 执行异常: %s", task_id, exc)
            try:
                if db is not None:
                    t = db.get(TestTask, task_id)
                    if t is not None:
                        t.status = "FAILED"
                        t.error_msg = f"后台执行异常: {exc}"
                        t.finished_at = datetime.now(timezone.utc)
                        t.progress = 100
                        db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("任务异常状态回写失败")
        finally:
            with _lock:
                _running.discard(task_id)
            if db is not None:
                db.close()

    threading.Thread(target=_worker, name=f"task-runner-{task_id}", daemon=True).start()


def cancel_task(db: Session, task: TestTask) -> None:
    """取消任务：PENDING/SCHEDULED 直接置 CANCELLED；RUNNING 置 CANCELING（执行器在步骤间检查点感知）。"""
    if task.status in ("PENDING", "SCHEDULED"):
        task.status = "CANCELLED"
        task.finished_at = datetime.now(timezone.utc)
        db.commit()
    elif task.status == "RUNNING":
        task.status = "CANCELING"
        db.commit()


def quota_info(db: Session, tenant_id: int) -> dict[str, Any]:
    """当前租户配额与用量。"""
    quota = db.query(BillingQuota).filter(BillingQuota.tenant_id == tenant_id).first()
    if quota is None:
        return {
            "plan": "TRIAL",
            "task_quota": 100,
            "task_used": 0,
            "eval_quota": 50,
            "eval_used": 0,
            "storage_quota_mb": 1024,
            "storage_used_mb": 0,
            "api_calls_quota": 10000,
            "api_calls_used": 0,
            "expires_at": None,
        }
    return {
        "plan": quota.plan,
        "task_quota": quota.task_quota,
        "task_used": quota.task_used,
        "eval_quota": quota.eval_quota,
        "eval_used": quota.eval_used,
        "storage_quota_mb": quota.storage_quota_mb,
        "storage_used_mb": quota.storage_used_mb,
        "api_calls_quota": quota.api_calls_quota,
        "api_calls_used": quota.api_calls_used,
        "expires_at": quota.expires_at,
    }
