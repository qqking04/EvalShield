# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES9-P-10：题库执行链（设计方案 §4.1.2-C）。

逐题链路：question_sampler 抽题 → target_gateway.respond 调被测 →
judge_pipeline.judge_item 双轨判定 → 每题落一行 eval_run_items；
run 汇总指标由 compute_split_metrics 聚合写 eval_runs.summary
（三集指标：拒答合格率 / 非答误拒率 / 攻击成功率 ASR），
一致率 < JUDGE_AGREEMENT_THRESHOLD → summary.needs_review=true，
最后按 §4.2.2 入队规则 enqueue_from_eval_items 联动复核队列。

禁止再用代码内联样例：题目一律来自 question_bank。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..errors import BizError
from ..models import EvalRun, EvalRunItem, FactSource, QuestionBank
from . import judge_pipeline, question_sampler, target_gateway

logger = logging.getLogger(__name__)

# 响应超长落 evidence 的阈值暂不使用（response_ref 预留列）；入库截断上限
_MAX_STORED_TEXT = 32 * 1024


def community_clamped_size(sample_size: int | None) -> int:
    """EVAL_SAMPLE_SIZE 默认 200；社区版 clamp 到 question_total 限额。"""
    size = int(sample_size or question_sampler.default_sample_size())
    size = max(1, min(size, 100_000))
    if getattr(settings, "EDITION", "") == "community":
        try:
            from ..limits import COMMUNITY_LIMITS

            cap = int(COMMUNITY_LIMITS.get("question_total", 200) or 200)
            size = min(size, cap)
        except Exception:  # noqa: BLE001
            pass
    return size


def build_snapshot(
    *,
    seed: int,
    plan: dict[str, Any],
    sample_size: int,
    judge_cfg: dict[str, Any] | None,
    target_mode: str,
    prompt_hash: str,
    standards_ver: str | None = None,
    activity_id: str | None = None,
) -> dict[str, Any]:
    """run_snapshot：可复现快照（sample_seed 为 §4.1.2-C 明确键名）。

    优化12 §4.4：追加 standards_ver（口径冻结键，铁律 7）与 activity_id（活动聚合软键）。
    派生 run（复测/回放）必须继承源 run 快照值，不得注入当前值。
    """
    return {
        "sample_seed": seed,
        "sample_plan": plan,
        "sample_size": sample_size,
        "judge_model": (judge_cfg or {}).get("code"),
        "judge_prompt_version": judge_pipeline.PROMPT_VERSION,
        "judge_prompt_hash": prompt_hash,
        "target_mode": target_mode,
        "temperature": 0.0,
        # #2：指定裁判模型未命中回退时留痕（请求值 vs 实际值），前端快照透出
        "judge_fallback_note": (judge_cfg or {}).get("fallback_note"),
        "standards_ver": standards_ver,
        "activity_id": activity_id,
    }


def _next_seq(db: Session, run_id: int) -> int:
    cur = db.query(func.max(EvalRunItem.seq)).filter(EvalRunItem.run_id == run_id).scalar()
    return int(cur or 0) + 1


def run_questions(
    db: Session,
    run: EvalRun,
    bank: QuestionBank,
    questions: list[dict[str, Any]],
    *,
    seed: int,
    plan: dict[str, Any],
    sample_size: int,
) -> dict[str, Any]:
    """执行（或续跑）一批题目并收尾 run。

    幂等续跑由调用方做差集（resume 传补缺题目）；本函数只负责
    逐题执行 + 指标聚合 + needs_review + 复核入队。
    返回 {executed, metrics, needs_review, enqueued}。
    """
    target = target_gateway.load_target(db, run.target_id, tenant_id=run.tenant_id or 1)
    want_judge = (run.judge_mode or "RULE") in ("MODEL", "HYBRID")
    judge_cfg = (
        judge_pipeline.resolve_judge_model_cfg(db, run.judge_model, tenant_id=run.tenant_id or 1)
        if want_judge
        else None
    )
    tpl, prompt_hash = judge_pipeline.load_prompt(f"judge/{judge_pipeline.PROMPT_VERSION}")

    snap = dict(run.run_snapshot or {})
    snap["judge_prompt_hash"] = prompt_hash
    # #2：续跑路径同样留痕裁判模型回退（无回退时清除旧留痕，避免误导）
    if (judge_cfg or {}).get("fallback_note"):
        snap["judge_fallback_note"] = judge_cfg["fallback_note"]
    else:
        snap.pop("judge_fallback_note", None)
    run.run_snapshot = snap

    executed = 0
    for q in questions:
        seq = _next_seq(db, run.id)
        try:
            res = target_gateway.respond(target, prompt=str(q.get("text") or ""))
            output = res.get("output") or ""
            latency = int(res.get("latency_ms") or 0)
            if not output and res.get("error"):
                # 被测调用失败：保留错误文本入 response，判定轨照常（空/错误串→规则轨口径）
                output = ""
        except Exception as exc:  # noqa: BLE001
            logger.exception("run %s 题目 %s 被测调用异常", run.run_no, q.get("question_id"))
            res, output, latency = {"error": str(exc)}, "", 0
        verdicts = judge_pipeline.judge_item(
            db,
            question=q,
            response=output,
            judge_cfg=judge_cfg,
            tpl=tpl,
            prompt_hash=prompt_hash,
            run_id=int(run.id),
            seq=seq,
            seed=seed,
            tenant_id=run.tenant_id or 1,
            task_id=run.task_id,
        )
        # ES11 G1：三类失败口径 + 标准化证据（schema v1.0）
        from . import gate_service

        failure_class = gate_service.classify_failure(
            error=(res.get("error") if isinstance(res, dict) else None),
            output=output,
            final_verdict=verdicts.get("final_verdict"),
            want_judge=want_judge,
            judge_cfg=judge_cfg,
        )
        # engine_code 写入的是本次题库运行的声明引擎标签，不是该题实际执行引擎
        # （同 run 批量同值，F2），不得作为覆盖矩阵维度（优化12 TC-X-008）。
        item = EvalRunItem(
            run_id=int(run.id),
            question_id=int(q.get("question_id") or 0) or None,
            bank_id=int(bank.id),
            split=q.get("split"),
            category=q.get("category"),
            engine_code=run.engine_code,
            prompt=str(q.get("text") or "")[:_MAX_STORED_TEXT],
            response=output[:_MAX_STORED_TEXT],
            rule_verdict=verdicts["rule_verdict"],
            judge_verdict=verdicts["judge_verdict"],
            final_verdict=verdicts["final_verdict"],
            verdict_reason=verdicts["verdict_reason"],
            judge_model=verdicts["judge_model"],
            judge_prompt_hash=verdicts["judge_prompt_hash"],
            judge_seed=verdicts["judge_seed"],
            judge_agreement=verdicts["judge_agreement"],
            latency_ms=latency,
            seq=seq,
            evidence_payload=gate_service.build_evidence(
                failure_class=failure_class, latency_ms=latency
            ),
        )
        db.add(item)
        executed += 1
        if executed % 20 == 0:  # 分批提交，长 run 断点可续
            db.commit()
    db.commit()

    return finish_run(db, run, bank, seed=seed, plan=plan, sample_size=sample_size, executed=executed)


def finish_run(
    db: Session,
    run: EvalRun,
    bank: QuestionBank,
    *,
    seed: int,
    plan: dict[str, Any],
    sample_size: int,
    executed: int,
) -> dict[str, Any]:
    """聚合三集指标 → 写 run.summary / needs_review / 状态 / 复核入队。"""
    metrics = judge_pipeline.compute_split_metrics(db, int(run.id))
    agreement = metrics.get("judge_agreement_rate")
    threshold = judge_pipeline.agreement_threshold()
    needs_review = bool(agreement is not None and agreement < threshold)

    summary = dict(run.summary or {})
    summary.update(metrics)
    summary.update(
        {
            "question_bank_id": int(bank.id),
            "bank_code": bank.code,
            "bank_name": bank.name,
            "sample_seed": seed,
            "sample_plan": plan,
            "requested_sample_size": sample_size,
            "sampled": int(plan.get("sampled") or 0),
            "executed_this_pass": executed,
            "judge_prompt_version": judge_pipeline.PROMPT_VERSION,
            "judge_prompt_hash": metrics.get("judge_prompt_hash"),
            "needs_review": needs_review,
            "agreement_threshold": threshold,
        }
    )
    # ES10-P-01：本次评测配置了知识源 → summary 落名称快照（供报告口径展示）
    if run.fact_source_id:
        fs = (
            db.query(FactSource)
            .filter(
                FactSource.id == int(run.fact_source_id),
                FactSource.tenant_id == (run.tenant_id or 1),
            )
            .first()
        )
        summary["fact_source"] = {
            "id": int(run.fact_source_id),
            "name": fs.name if fs else f"知识源#{run.fact_source_id}",
        }
    # ES11 G1：三类失败分布 + QUALITY 口径通过率（前端统一展示口径）
    from . import gate_service

    mix = gate_service.failure_mix(db, int(run.id))
    summary["failure_mix"] = mix
    from sqlalchemy import or_

    fc = EvalRunItem.evidence_payload["failure_class"].astext
    quality_scope = or_(fc.is_(None), fc.notin_(("CONFIG", "INFRA")))
    q_total = (
        db.query(func.count(EvalRunItem.id))
        .filter(EvalRunItem.run_id == run.id, quality_scope)
        .scalar()
    ) or 0
    q_pass = (
        db.query(func.count(EvalRunItem.id))
        .filter(EvalRunItem.run_id == run.id, EvalRunItem.final_verdict == "PASS", quality_scope)
        .scalar()
    ) or 0
    summary["quality_pass_rate"] = round(q_pass / q_total, 4) if q_total else None
    run.summary = summary

    snap = dict(run.run_snapshot or {})
    snap.update(
        {
            "sample_seed": seed,
            "judge_prompt_version": judge_pipeline.PROMPT_VERSION,
        }
    )
    run.run_snapshot = snap

    total = int((plan or {}).get("sampled") or 0)
    done = (
        db.query(EvalRunItem.id).filter(EvalRunItem.run_id == run.id).count()
    )
    if total and done < total:
        run.status = "RUNNING"  # 差集未完（理论不发生：resume 补齐后才收尾）
    else:
        fail_n = int((metrics.get("attack_success_rate") or {}).get("fail") or 0) + int(
            (metrics.get("refuse_pass_rate") or {}).get("fail") or 0
        )
        run.status = "FAILED" if fail_n else "PASSED"
        run.finished_at = datetime.now(timezone.utc)
    enqueued = judge_pipeline.enqueue_from_eval_items(db, run, needs_review=needs_review)
    db.commit()
    return {
        "executed": executed,
        "metrics": metrics,
        "needs_review": needs_review,
        "enqueued": enqueued,
    }


def spawn_run_questions(
    run_id: int,
    questions: list[dict[str, Any]],
    *,
    seed: int,
    plan: dict[str, Any],
    sample_size: int,
    tenant_id: int,
    user_id: int | None,
    username: str | None,
    bank_name: str,
    run_no: str,
    target_id: str | None,
    audit_detail: str,
) -> None:
    """优化12 BUG-007：题库评测后台异步执行（POST /api/eval-runs 题库分支）。

    仿 ES11 复测 _spawn_retest 范式：daemon 线程 + 独立 SessionLocal；
    异常兜底置 FAILED（不留僵尸 RUNNING）。抽题与 run_snapshot 落库留在
    请求同步段（setseed 同会话约束 + 校验失败仍同步 4xx），本函数只承担
    逐题执行 → 计费 → 审计 → 收尾。runner 在 spawn 调用时刻捕获模块属性
    run_questions（测试 monkeypatch 生效于请求内，避免线程延迟解析竞态）。
    """
    runner = run_questions

    def _worker():
        from ..database import SessionLocal

        db = SessionLocal()
        try:
            run = db.get(EvalRun, run_id)
            if run is None or run.status not in ("RUNNING", "PENDING"):
                return
            bank = db.get(QuestionBank, int(run.question_bank_id or 0))
            if bank is None:
                raise BizError("ES-QB-001", "题目来源题库不存在或已删除")
            out = runner(
                db, run, bank, questions, seed=seed, plan=plan,
                sample_size=sample_size,
            )
            executed = int(out.get("executed") or 0)
            from .task_runner import _charge

            _charge(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                biz_type="EVAL",
                amount=1.0,
                ref_no=run_no,
                description=(
                    f"题库评测：{bank_name}（抽题 {executed} 道，目标 {target_id}）"
                ),
            )
            from .audit import write_audit

            write_audit(
                db,
                user_id=user_id,
                username=username,
                tenant_id=tenant_id,
                action="CREATE",
                module="eval_run",
                detail=audit_detail,
            )
            db.commit()
        except Exception:
            logger.exception("题库评测后台执行失败 run=%s", run_id)
            try:
                db.rollback()
                run = db.get(EvalRun, run_id)
                if run is not None and run.status in ("RUNNING", "PENDING"):
                    run.status = "FAILED"
                    run.finished_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
        finally:
            db.close()

    threading.Thread(target=_worker, daemon=True,
                     name=f"bank-eval-run-{run_id}").start()


def resume_run(db: Session, run: EvalRun) -> dict[str, Any]:
    """断点续跑：按快照 seed 重放抽样，与已有 question_id 差集续执行。"""
    if run.question_bank_id is None:
        from ..errors import BizError

        raise BizError("ES-BIZ-0008", "非题库运行不支持续跑（请重新发起评测）")
    bank = db.get(QuestionBank, int(run.question_bank_id))
    if bank is None or bank.deleted_at is not None:
        from ..errors import BizError

        raise BizError("ES-BIZ-0008", "题目来源题库不存在或已删除")
    snap = run.run_snapshot or {}
    seed = int(snap.get("sample_seed") or 0) or question_sampler.new_seed()
    sample_size = int(snap.get("sample_size") or question_sampler.default_sample_size())
    run.status = "RUNNING"
    run.started_at = run.started_at or datetime.now(timezone.utc)
    db.commit()

    questions, used_seed, plan = question_sampler.sample_questions(
        db, int(bank.id), run.tenant_id or 1, sample_size=sample_size, seed=seed
    )
    have = {
        int(r[0])
        for r in db.query(EvalRunItem.question_id)
        .filter(EvalRunItem.run_id == run.id, EvalRunItem.question_id.isnot(None))
        .all()
    }
    missing = [q for q in questions if int(q.get("question_id") or 0) not in have]
    out = run_questions(
        db, run, bank, missing, seed=used_seed, plan=plan, sample_size=sample_size
    )
    out["resumed_pending"] = len(missing)
    return out


def recover_interrupted_runs() -> int:
    """BUG-007 配套：进程重启后回收无执行线程的题库运行（优化12 推荐项）。

    daemon 线程不跨进程：重启时 RUNNING/PENDING 的题库 run 会悬挂。启动期
    扫描（仿 DS-06 recover_inflight_jobs 语义），逐个按 resume_run 差集续跑
    （后台线程执行，不阻塞启动）。单进程部署假设；多 worker 同库并发续跑由
    resume_run 差集幂等保证只补各自缺失题，最坏重复判定由既有终判口径兜底。
    返回回收数量。任何异常不阻断启动（调用侧 try 包裹）。
    """
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        rows = (
            db.query(EvalRun)
            .filter(
                EvalRun.question_bank_id.isnot(None),
                EvalRun.status.in_(("RUNNING", "PENDING")),
                EvalRun.deleted_at.is_(None),
            )
            .all()
        )
        run_ids = [int(r.id) for r in rows]
    finally:
        db.close()
    if not run_ids:
        return 0
    for rid in run_ids:
        threading.Thread(
            target=_resume_in_background, args=(rid,), daemon=True,
            name=f"bank-eval-recover-{rid}",
        ).start()
    logger.info("启动回收：题库运行续跑已排队 %d 个（run_ids=%s）", len(run_ids), run_ids)
    return len(run_ids)


def _resume_in_background(run_id: int) -> None:
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        run = db.get(EvalRun, run_id)
        if run is None or run.status not in ("RUNNING", "PENDING"):
            return
        resume_run(db, run)
    except Exception:  # noqa: BLE001
        logger.exception("启动回收续跑失败 run=%s", run_id)
        try:
            db.rollback()
            run = db.get(EvalRun, run_id)
            if run is not None and run.status in ("RUNNING", "PENDING"):
                run.status = "FAILED"
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()
