# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""ES11：Trace 回流闭环路由（开发方案 §3.5，4 接口）。

promote-question / create-defect / launch-regression / lineage；
写操作幂等：同一 Trace 重复转缺陷返回既有缺陷；promote 记录 source_trace_id。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends
from sqlalchemy import cast, func, text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import AuthContext, authenticate_request, ensure_data_scope
from ..errors import BizError, NotFoundError
from ..models import Defect, EvalRun, EvalRunItem, Question, QuestionBank, ReviewItem, Trace
from ..utils.no import gen_no

logger = logging.getLogger(__name__)
router = APIRouter()


def _load_trace(db: Session, trace_id: int, auth: AuthContext) -> Trace:
    t = db.get(Trace, trace_id)
    if t is None:
        raise NotFoundError("ES-BIZ-TRACE-0001", "Trace 不存在")
    return t


async def _trace_in_scope(db: Session, trace_id: int, auth: AuthContext) -> Trace:
    t = _load_trace(db, trace_id, auth)
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    return t


def _mask_text(text: str, tenant_id: int, db: Session) -> str:
    """自动脱敏：复用 PII 正则规则库（命中值替换为掩码），失败原样返回。"""
    if not text:
        return text
    try:
        from ..commercial.engines.pii_leak import PIILeakEngine
        from ..models import PIIRule

        rows = (
            db.query(PIIRule)
            .filter(PIIRule.tenant_id.in_([tenant_id, 1]), PIIRule.is_active.is_(True),
                    PIIRule.deleted_at.is_(None))
            .all()
        )
        rules = []
        for r in rows:
            try:
                rules.append({"pii_type": r.pii_type, "rule_name": r.rule_name,
                              "pattern": re.compile(r.regex_pattern),
                              "severity": r.severity,
                              "context_keywords": [str(k).lower() for k in (r.context_keywords or [])]})
            except re.error:
                continue
        eng = PIILeakEngine()
        hits = eng._regex_scan(text, rules) if rules else []
        return eng._mask_text(text, hits) if hits else text
    except Exception:  # noqa: BLE001 — 脱敏组件缺席（community 构建）不阻断回流
        return text


# ---------------------------------------------------------- promote-question


@router.post("/traces/{trace_id}/promote-question", response_model=dict)
async def promote_question(
    trace_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """转候选题（§3.5）：自动脱敏 → 题库候选题（默认 HOLDOUT 分层）→ 人工确认预期后入库。"""
    t = await _trace_in_scope(db, trace_id, auth)
    bank_id = int(body.get("question_bank_id") or 0)
    if bank_id <= 0:
        raise BizError("ES-BIZ-TRACE-0002", "必须指定目标题库 question_bank_id")
    bank = db.get(QuestionBank, bank_id)
    if bank is None or bank.deleted_at is not None or bank.tenant_id != t.tenant_id:
        raise NotFoundError("ES-QB-001", "题库不存在")
    if bank.is_builtin:
        raise BizError("ES-QB-006", "内置题库不可直接添加题目（请复制后编辑）")
    text = _mask_text(t.request or "", t.tenant_id, db)
    if not text.strip():
        raise BizError("ES-BIZ-TRACE-0002", "Trace 请求文本为空，无法转候选题")
    category = str(body.get("category") or "TRACE_REFLOW").strip()
    # 幂等：同库同类同文（脱敏后）已存在则返回既有题
    exist = (
        db.query(Question)
        .filter(Question.bank_id == bank_id, Question.category == category,
                Question.deleted_at.is_(None), Question.text == text)
        .first()
    )
    if exist is not None:
        return {"code": 0, "message": "ok", "data": {
            "question_id": int(exist.id), "deduped": True,
            "split": exist.split, "expected_behavior": exist.expected_behavior,
        }}
    split = str(body.get("split") or "HOLDOUT").upper()
    behavior = str(body.get("expected_behavior") or "").strip() or (
        "REFUSE" if split == "REFUSE" else "ANSWER" if split == "ANSWER" else "REFUSE"
    )
    seq = int(db.execute(
        sa_text("SELECT COALESCE(MAX(seq), 0) FROM question WHERE bank_id = :b"),
        {"b": bank_id},
    ).scalar() or 0) + 1
    row = Question(
        tenant_id=t.tenant_id, bank_id=bank_id, seq=seq,
        category=category, sub_category=None, attack_vector=None,
        split=split, expected_behavior=behavior,
        expected_answer=body.get("expected_answer"),
        language="zh-CN", source="trace_reflow", sensitivity="internal",
        tags=body.get("tags") or ["trace_reflow"],
        meta={"source_trace_id": int(t.id), "promoted_by": auth.user_id,
              "promoted_at": datetime.now(timezone.utc).isoformat(),
              "confirm_required": not body.get("confirmed", False)},
        text=text,
    )
    db.add(row)
    db.flush()
    db.execute(
        sa_text(
            "UPDATE question_bank SET question_count = "
            "(SELECT COUNT(*) FROM question WHERE bank_id = :b AND deleted_at IS NULL) "
            "WHERE id = :b"
        ),
        {"b": bank_id},
    )
    db.commit()
    return {"code": 0, "message": "ok", "data": {
        "question_id": int(row.id), "deduped": False,
        "split": row.split, "expected_behavior": row.expected_behavior,
        "source_trace_id": int(t.id),
    }}


# ----------------------------------------------------------- create-defect


@router.post("/traces/{trace_id}/create-defect", response_model=dict)
async def create_defect_from_trace(
    trace_id: int,
    body: dict | None = Body(default=None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """转缺陷（§3.5）：origin_type=TRACE；幂等——已转过返回既有缺陷。"""
    t = await _trace_in_scope(db, trace_id, auth)
    exist = (
        db.query(Defect)
        .filter(Defect.origin_type == "TRACE", Defect.origin_id == int(t.id),
                Defect.tenant_id == t.tenant_id, Defect.deleted_at.is_(None))
        .first()
    )
    if exist is not None:
        return {"code": 0, "message": "ok", "data": {
            "defect_id": int(exist.id), "defect_no": exist.defect_no, "deduped": True,
        }}
    b = body or {}
    scores = {}
    try:
        scores = json.loads(t.scores or "{}").get("scores", {})
    except (ValueError, TypeError):
        pass
    d = Defect(
        defect_no=gen_no("BUG"),
        project_id=int(b.get("project_id") or t.project_id or 0),
        title=str(b.get("title") or f"线上 Trace 低分回流：{(t.request or '')[:60]}"),
        severity=str(b.get("severity") or "P2").upper(),
        status="NEW",
        actual=(t.response or "")[:2000],
        expected=b.get("expected"),
        evidence=[{"type": "trace", "trace_id": int(t.id), "scores": scores}],
        tenant_id=t.tenant_id,
        created_by=auth.user_id, created_by_name=auth.username,
        origin_type="TRACE", origin_id=int(t.id),
    )
    db.add(d)
    db.flush()
    from ..services import defect_events

    defect_events.append(
        db, defect_id=int(d.id), event_type="CREATED",
        actor_id=auth.user_id, actor_name=auth.username, tenant_id=t.tenant_id,
        status_to="NEW", note=f"Trace #{t.id} 回流转缺陷",
        evidence={"trace_id": int(t.id), "scores": scores},
    )
    db.commit()
    return {"code": 0, "message": "ok", "data": {
        "defect_id": int(d.id), "defect_no": d.defect_no, "deduped": False,
    }}


# -------------------------------------------------------- launch-regression


@router.post("/traces/{trace_id}/launch-regression", response_model=dict)
async def launch_regression(
    trace_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """发起回流回归（§3.5）：以 Trace 关联题库样本跑 run_purpose=TRACE_REPLAY。"""
    t = await _trace_in_scope(db, trace_id, auth)
    q_ids = [int(x) for x in (body.get("question_ids") or [])]
    if not q_ids:
        # 默认取由该 Trace 回流生成的题目
        rows = (
            db.query(Question.id)
            .filter(Question.tenant_id == t.tenant_id, Question.deleted_at.is_(None),
                    func.cast(Question.meta["source_trace_id"], func) == str(t.id))
            .all()
        )
        q_ids = [int(r[0]) for r in rows]
    if not q_ids:
        raise BizError("ES-BIZ-TRACE-0003", "该 Trace 无关联题库样本，无法发起回归")
    questions = []
    bank_id = None
    for qid in q_ids:
        qq = db.get(Question, qid)
        if qq is None or qq.deleted_at is not None:
            raise BizError("ES-BIZ-TRACE-0003", f"题目 {qid} 不存在或已删除")
        bank_id = int(qq.bank_id)
        questions.append({
            "question_id": int(qq.id), "bank_id": bank_id, "seq": qq.seq,
            "text": qq.text, "category": qq.category, "sub_category": qq.sub_category,
            "attack_vector": qq.attack_vector, "split": qq.split,
            "expected_behavior": qq.expected_behavior,
            "expected_answer": qq.expected_answer, "language": qq.language,
            "meta": qq.meta if isinstance(qq.meta, dict) else {},
        })
    bank = db.get(QuestionBank, int(bank_id))
    if bank is None or bank.deleted_at is not None:
        raise NotFoundError("ES-QB-001", "题库不存在")

    from ..services import bank_executor, judge_pipeline, target_gateway
    from ..models import EvalRun as _ER

    target_code = str(body.get("target_id") or "")
    run = _ER(
        run_no=gen_no("EV"), eval_set_id=0, question_bank_id=int(bank.id),
        target_type=str(body.get("target_type") or "MODEL"), target_id=target_code,
        judge_mode=str(body.get("judge_mode") or "RULE"),
        judge_model=body.get("judge_model"),
        status="RUNNING", started_at=datetime.now(timezone.utc),
        created_by=auth.user_id, tenant_id=t.tenant_id,
        run_purpose="TRACE_REPLAY", project_version_id=body.get("project_version_id"),
    )
    if not target_code:
        raise BizError("ES-BIZ-TRACE-0003", "回归必须指定被测系统 target_id")
    db.add(run)
    db.flush()
    target = target_gateway.load_target(db, target_code, tenant_id=t.tenant_id)
    judge_cfg = (
        judge_pipeline.resolve_judge_model_cfg(db, run.judge_model, tenant_id=t.tenant_id)
        if (run.judge_mode or "RULE") in ("MODEL", "HYBRID") else None
    )
    _, prompt_hash = judge_pipeline.load_prompt(f"judge/{judge_pipeline.PROMPT_VERSION}")
    plan = {"sampled": len(questions), "strata": [], "trace_replay_for": int(t.id)}
    # 优化12 §4.4 铁律7：回放 run 继承被回放源 run 快照的 standards_ver（请求未携带源 run / 旧 run 无键 → None 视为旧口径）；
    # activity_id 按请求透传（回放默认不加入活动，除非请求显式携带）
    src_run = db.get(_ER, int(body["parent_run_id"])) if body.get("parent_run_id") else None
    run.run_snapshot = bank_executor.build_snapshot(
        seed=int(t.id), plan=plan, sample_size=len(questions), judge_cfg=judge_cfg,
        target_mode="API" if target else "INTERNAL_DEMO", prompt_hash=prompt_hash,
        standards_ver=(src_run.run_snapshot or {}).get("standards_ver") if src_run else None,
        activity_id=body.get("activity_id"),
    )
    db.commit()
    out = bank_executor.run_questions(
        db, run, bank, questions, seed=int(t.id), plan=plan, sample_size=len(questions)
    )
    db.refresh(run)
    return {"code": 0, "message": "ok", "data": {
        "run": {"id": run.id, "run_no": run.run_no, "status": run.status,
                "run_purpose": run.run_purpose, "verdict": run.verdict},
        "executed": out.get("executed"), "summary": run.summary,
    }}


# ----------------------------------------------------------------- lineage


@router.get("/traces/{trace_id}/lineage", response_model=dict)
async def trace_lineage(
    trace_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """全链路引用（§3.5）：Trace → 复核项 / 题库样本 / 缺陷 / 回归运行。"""
    t = await _trace_in_scope(db, trace_id, auth)
    reviews = (
        db.query(ReviewItem.id, ReviewItem.status, ReviewItem.source)
        .filter(ReviewItem.source == "trace",
                cast(ReviewItem.source_ref, JSONB).contains({"trace_id": int(t.id)}))
        .all()
    )
    questions = (
        db.query(Question.id, Question.split)
        .filter(Question.tenant_id == t.tenant_id, Question.deleted_at.is_(None),
                Question.meta["source_trace_id"].astext == str(t.id))
        .all()
    )
    defects = (
        db.query(Defect.id, Defect.defect_no, Defect.status)
        .filter(Defect.origin_type == "TRACE", Defect.origin_id == int(t.id),
                Defect.tenant_id == t.tenant_id, Defect.deleted_at.is_(None))
        .all()
    )
    replay_runs = (
        db.query(EvalRun.id, EvalRun.run_no, EvalRun.status, EvalRun.verdict)
        .filter(EvalRun.tenant_id == t.tenant_id, EvalRun.deleted_at.is_(None),
                EvalRun.run_purpose == "TRACE_REPLAY",
                EvalRun.run_snapshot["trace_replay_for"].astext == str(t.id))
        .all()
    )
    closed_defect = bool(defects and all(r[2] == "CLOSED" for r in defects))
    return {"code": 0, "message": "ok", "data": {
        "trace": {"id": t.id, "reviewed": t.reviewed, "eval_status": t.eval_status,
                  "project_id": t.project_id, "session_id": t.session_id},
        "review_items": [{"id": r[0], "status": r[1]} for r in reviews],
        "questions": [{"id": r[0], "split": r[1]} for r in questions],
        "defects": [{"id": r[0], "defect_no": r[1], "status": r[2]} for r in defects],
        "replay_runs": [{"id": r[0], "run_no": r[1], "status": r[2], "verdict": r[3]}
                        for r in replay_runs],
        "loop_closed": closed_defect,
    }}
