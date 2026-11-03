# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M6 人工复核队列路由（§7.2）：items CRUD + 状态机 + 统计 + 校准 + 回流建集。

ES9-P-10 增量（优化9设计方案 §4.2）：
- GET  /queue                 复核工作台队列（分页 + 按 run/category 聚合计数）
- POST /items/{id}/decision   {verdict, note, promote_rule} → 完成复核 +
                              approved 时回写 eval_run_items.review_status +
                              规则回流（D-12：rejected 不回写，仅留复核台账）
- POST /items/{id}/batch      批量 approve/reject（单事务）

守卫范式照 monitors.py：require_permission("review", read/manage)
（section 45 已种子权限点）；租户隔离：非超管一律按 auth.tenant_id 过滤。
状态机与入队逻辑全部收敛在 services/review_queue.py，本层只做参数校验与审计。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, cast, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import AuthContext, require_permission
from ..errors import BizError, NotFoundError
from ..models import EvalRun, EvalRunItem, ReviewItem
from ..services import dataset_io, judge_pipeline
from ..services.audit import write_audit
from ..services.calibration import calibration_report
from ..services.review_queue import (
    ST_DONE,
    TERMINAL_STATES,
    assign_item,
    complete_item,
    discard_item,
    enqueue_from_report_mark,
)

router = APIRouter()

# 评测集类别白名单（与 evals_core VALID_CASE_CATEGORIES 同口径，避免循环导入另立常量）
_VALID_SET_CATEGORIES = {"EVAL", "SEC", "RAG", "AGENT", "MULTI_TURN", "KB"}


# ---------------------------------------------------------------- 请求体 ----

class ReviewItemCreate(BaseModel):
    """手工入队：按 run_id + item_index 取快照（与「判分不对」标记同链路）。"""

    run_id: int
    item_index: int = Field(..., ge=0)
    note: str | None = Field(None, max_length=500)


class ReviewMarkFromReport(BaseModel):
    """报告详情「标记判分不对」：body = run_id + item_index（+ 可选备注）。"""

    run_id: int
    item_index: int = Field(..., ge=0)
    note: str | None = Field(None, max_length=500)


class ReviewItemUpdate(BaseModel):
    """指派（assignee_id → ASSIGNED）或提交结论（human_verdict → DONE）。"""

    assignee_id: int | None = None
    human_verdict: str | None = Field(None, max_length=24)
    human_note: str | None = Field(None, max_length=2000)


class PackageAsEvalSet(BaseModel):
    """勾选 DONE 项打包建集（source=FROM_REVIEW）。"""

    item_ids: list[int] = Field(..., min_length=1, max_length=1000)
    name: str = Field(..., min_length=1, max_length=128)
    category: str = Field("EVAL", max_length=16)


class ReviewDecision(BaseModel):
    """ES9 复核结论：approve/reject（维持/改判语义映射）+ 可选规则回流。"""

    verdict: str = Field(..., min_length=1, max_length=24)
    note: str | None = Field(None, max_length=2000)
    promote_rule: bool = False
    keywords: list[str] = Field(default_factory=list, max_length=20)


class ReviewBatch(BaseModel):
    """ES9 批量结论（单事务）：verdict 同 decision 口径，不做规则回流。"""

    item_ids: list[int] = Field(..., min_length=1, max_length=200)
    verdict: str = Field(..., min_length=1, max_length=24)
    note: str | None = Field(None, max_length=2000)


# ------------------------------------------------------------------ 工具 ----

def _get_item(db: Session, item_id: int, auth: AuthContext) -> ReviewItem:
    q = db.query(ReviewItem).filter(ReviewItem.id == item_id)
    if not auth.is_super_admin:
        q = q.filter(ReviewItem.tenant_id == auth.tenant_id)
    item = q.first()
    if item is None:
        raise NotFoundError("ES-M6-0005", "复核项不存在或不属于当前租户")
    return item


def _get_run_for_auth(db: Session, run_id: int, auth: AuthContext) -> EvalRun:
    q = db.query(EvalRun).filter(EvalRun.id == run_id)
    if not auth.is_super_admin:
        q = q.filter(EvalRun.tenant_id == auth.tenant_id)
    run = q.first()
    if run is None:
        raise NotFoundError("ES-M6-0006", "评测运行不存在或不属于当前租户")
    return run


def _item_out(it: ReviewItem) -> dict:
    try:
        ctx = json.loads(it.context or "{}")
    except (TypeError, ValueError):
        ctx = {}
    return {
        "id": it.id,
        "tenant_id": it.tenant_id,
        "source": it.source,
        "source_ref": it.source_ref,
        "context": ctx,
        "auto_verdict": it.auto_verdict,
        "auto_confidence": it.auto_confidence,
        "status": it.status,
        "assignee_id": it.assignee_id,
        "human_verdict": it.human_verdict,
        "human_note": it.human_note,
        "judge_prompt_hash": it.judge_prompt_hash,
        "judge_model": it.judge_model,
        "run_item_id": it.run_item_id,
        "priority": it.priority,
        "created_at": it.created_at,
        "updated_at": it.updated_at,
    }


_APPROVE_WORDS = {"approve", "approved", "pass", "keep", "维持"}
_REJECT_WORDS = {"reject", "rejected", "fail", "退回", "改判"}


def _norm_decision(verdict: str) -> str:
    """decision/batch 的 verdict 归一：approve | reject（其余 422）。"""
    v = (verdict or "").strip().lower()
    if v in _APPROVE_WORDS:
        return "approve"
    if v in _REJECT_WORDS:
        return "reject"
    raise BizError(
        "ES-M9-0001",
        f"非法复核结论 {verdict!r}（合法：approve/reject 及其同义词）",
        http_status=422,
    )


def _writeback_run_item(
    db: Session, item: ReviewItem, *, review_status: str, reviewer_id: int
) -> None:
    """复核结论回写 eval_run_items（软引用优先，缺失按 source_ref 兼容）。"""
    from datetime import datetime, timezone

    it_row = None
    try:
        ref = json.loads(item.source_ref or "{}")
    except (TypeError, ValueError):
        ref = {}
    run_id = ref.get("run_id") if isinstance(ref, dict) else None
    item_index = ref.get("item_index") if isinstance(ref, dict) else None
    if item.run_item_id is not None:
        it_row = db.get(EvalRunItem, item.run_item_id)
    if it_row is None and run_id is not None and item_index is not None:
        it_row = (
            db.query(EvalRunItem)
            .filter(
                EvalRunItem.run_id == int(run_id), EvalRunItem.seq == int(item_index)
            )
            .first()
        )
    if it_row is None:
        return
    # eval_run_items 无 tenant_id 列（section 67 DDL），租户校验经所属 run 行
    run_row = db.get(EvalRun, it_row.run_id)
    if run_row is not None and run_row.tenant_id != item.tenant_id:
        return
    it_row.review_status = review_status
    it_row.reviewer_id = reviewer_id
    it_row.reviewed_at = datetime.now(timezone.utc)
    db.add(it_row)


def _apply_decision(
    db: Session,
    item: ReviewItem,
    *,
    verdict: str,
    note: str | None,
    promote_keywords: list[str] | None = None,
    reviewer_id: int,
) -> str | None:
    """单条结论落库：complete_item +（仅通过侧）run_item 回写 +（可选）规则回流。

    D-12 定稿（优化9测试方案 §13）：rejected 不回写 eval_run_items 三列，
    仅保留复核台账（ReviewItem）留痕；返回 run_item 侧最终 review_status
    （rejected 或无关联条目时为 None）。
    """
    decision = _norm_decision(verdict)
    # human_verdict 落校准桶口径（calibration._BUCKET_MAP：PASS/FAIL 可入混淆矩阵）
    human_verdict = "PASS" if decision == "approve" else "FAIL"
    item = complete_item(db, item, human_verdict, note)
    if decision != "approve":
        db.commit()
        return None
    review_status = "approved"
    if promote_keywords:
        it_row = db.get(EvalRunItem, item.run_item_id) if item.run_item_id else None
        if it_row is not None and judge_pipeline.promote_rule_to_question(
            db, it_row, promote_keywords
        ):
            review_status = "promoted"
    _writeback_run_item(
        db, item, review_status=review_status, reviewer_id=reviewer_id
    )
    db.commit()
    return review_status


# ---------------------------------------------------------------- 端点 ----

@router.get("/items", response_model=dict)
async def list_items(
    status: str | None = Query(None, pattern="^(OPEN|ASSIGNED|DONE|DISCARDED)$"),
    assignee_id: int | None = Query(None, ge=1),
    source: str | None = Query(None, max_length=16),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("review", "read")),
):
    """队列列表：status / assignee_id / source 过滤 + 分页（新入队优先）。"""
    q = db.query(ReviewItem)
    if not auth.is_super_admin:
        q = q.filter(ReviewItem.tenant_id == auth.tenant_id)
    if status:
        q = q.filter(ReviewItem.status == status)
    if assignee_id is not None:
        q = q.filter(ReviewItem.assignee_id == assignee_id)
    if source:
        q = q.filter(ReviewItem.source == source)
    total = q.count()
    rows = (
        q.order_by(ReviewItem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": [_item_out(r) for r in rows], "total": total},
    }


@router.get("/stats", response_model=dict)
async def review_stats(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("review", "read")),
):
    """各状态计数（复核台角标与队列健康度）。"""
    q = db.query(ReviewItem.status, func.count(ReviewItem.id))
    if not auth.is_super_admin:
        q = q.filter(ReviewItem.tenant_id == auth.tenant_id)
    counts = {s: int(n) for s, n in q.group_by(ReviewItem.status).all()}
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "open": counts.get("OPEN", 0),
            "assigned": counts.get("ASSIGNED", 0),
            "done": counts.get("DONE", 0),
            "discarded": counts.get("DISCARDED", 0),
            "total": sum(counts.values()),
        },
    }


@router.get("/calibration", response_model=dict)
async def review_calibration(
    weeks: int = Query(12, ge=1, le=104),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("review", "read")),
):
    """judge 校准报告：按 ISO 周聚合 DONE 项的混淆矩阵 + Cohen's Kappa。"""
    tenant = None if auth.is_super_admin else auth.tenant_id
    return {"code": 0, "message": "ok", "data": calibration_report(db, tenant, weeks)}


@router.post("/items", response_model=dict)
async def create_item(
    body: ReviewItemCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("review", "manage")),
):
    """手工入队（复核员从队列页直接补录低置信之外的可疑项）。"""
    run = _get_run_for_auth(db, body.run_id, auth)
    item = enqueue_from_report_mark(db, run, body.item_index, body.note)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="review.enqueue", module="review", request=request,
        detail=f"id={item.id} run={run.id} idx={body.item_index}",
    )
    return {"code": 0, "message": "ok", "data": _item_out(item)}


@router.post("/items/from-report", response_model=dict)
async def mark_from_report(
    body: ReviewMarkFromReport,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("review", "manage")),
):
    """报告详情「标记判分不对」入队（幂等：OPEN 态重复标记返回既有在队项）。"""
    run = _get_run_for_auth(db, body.run_id, auth)
    item = enqueue_from_report_mark(db, run, body.item_index, body.note)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="review.mark_from_report", module="review", request=request,
        detail=f"id={item.id} run={run.id} idx={body.item_index}",
    )
    return {"code": 0, "message": "ok", "data": _item_out(item)}


@router.put("/items/{item_id}", response_model=dict)
async def update_item(
    item_id: int,
    body: ReviewItemUpdate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("review", "manage")),
):
    """状态机：指派（→ASSIGNED + emit review.assigned）或提交结论（→DONE）。"""
    item = _get_item(db, item_id, auth)
    if body.human_verdict is not None and str(body.human_verdict).strip():
        item = complete_item(db, item, body.human_verdict, body.human_note)
        action = "review.done"
    elif body.assignee_id is not None:
        # 复核员须与本租户有归属（超管不限）
        from ..models import SystemUser

        uq = db.query(SystemUser).filter(
            SystemUser.id == body.assignee_id, SystemUser.deleted_at.is_(None)
        )
        if not auth.is_super_admin:
            uq = uq.filter(SystemUser.tenant_id == auth.tenant_id)
        if uq.first() is None:
            raise BizError("ES-M6-0007", "复核员不存在或不属于当前租户")
        item = assign_item(db, item, body.assignee_id)
        action = "review.assign"
    else:
        raise BizError("ES-M6-0008", "需提交 assignee_id（指派）或 human_verdict（完成复核）")
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action=action, module="review", request=request, detail=f"id={item.id}",
    )
    return {"code": 0, "message": "ok", "data": _item_out(item)}


@router.post("/items/{item_id}/discard", response_model=dict)
async def discard(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("review", "manage")),
):
    """废弃复核项 → DISCARDED（终态，释放幂等位）。"""
    item = _get_item(db, item_id, auth)
    item = discard_item(db, item)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="review.discard", module="review", request=request, detail=f"id={item.id}",
    )
    return {"code": 0, "message": "ok", "data": _item_out(item)}


@router.post("/package-as-evalset", response_model=dict)
async def package_as_evalset(
    body: PackageAsEvalSet,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("review", "manage")),
):
    """勾选 DONE 项 → 打包建评测集（source=FROM_REVIEW，数据回流闭环）。"""
    category = (body.category or "EVAL").upper()
    if category not in _VALID_SET_CATEGORIES:
        raise BizError(
            "ES-M6-0009",
            f"非法评测集类别 {category!r}（合法：{sorted(_VALID_SET_CATEGORIES)}）",
        )
    q = db.query(ReviewItem).filter(
        ReviewItem.id.in_(body.item_ids), ReviewItem.status == ST_DONE
    )
    if not auth.is_super_admin:
        q = q.filter(ReviewItem.tenant_id == auth.tenant_id)
    items = q.order_by(ReviewItem.id.asc()).all()
    if not items:
        raise BizError("ES-M6-0010", "所选复核项中没有可回流的 DONE 项")

    entries: list[dict] = []
    for it in items:
        try:
            ctx = json.loads(it.context or "{}")
        except (TypeError, ValueError):
            ctx = {}
        entry = {
            "no": f"REV-{it.id:06d}",
            "prompt": str(ctx.get("prompt") or ""),
            "expected": it.human_verdict or "",
            "tags": ["from_review", it.source, str(ctx.get("no") or "")],
        }
        entries.append(entry)
    normed = dataset_io.items_from_review(entries)
    es = dataset_io.build_imported_set(
        db,
        name=body.name,
        category=category,
        items=normed,
        source="FROM_REVIEW",
        user_id=auth.user_id,
        tenant_id=auth.tenant_id,
        meta_extra={
            "via": "review_queue",
            "review_ids": [it.id for it in items],
            "skipped_not_done": len(body.item_ids) - len(items),
        },
    )
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="review.package", module="review", request=request,
        detail=f"set={es.code} items={len(normed)}",
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "id": es.id, "eval_set_no": es.code,
            "item_count": es.item_count, "source": es.source,
        },
    }


# --------------------------------------------------- ES9-P-10 增量端点 ----

@router.get("/queue", response_model=dict)
async def review_queue(
    status: str | None = Query("OPEN", pattern="^(OPEN|ASSIGNED|DONE|DISCARDED)$"),
    priority: str | None = Query(None, pattern="^(P0|P1|P2)$"),
    category: str | None = Query(None, max_length=64),
    run_id: int | None = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("review", "read")),
):
    """复核工作台队列（§4.2）：P0>P1>P2 定级排序 + 按 run/category 聚合计数。

    category/run_id 过滤作用在 context JSONB 快照上（入队时复制的字段）。
    """
    def _build_q():
        q = db.query(ReviewItem)
        if not auth.is_super_admin:
            q = q.filter(ReviewItem.tenant_id == auth.tenant_id)
        if status:
            q = q.filter(ReviewItem.status == status)
        if priority:
            q = q.filter(ReviewItem.priority == priority)
        if category:
            q = q.filter(cast(ReviewItem.context, JSONB).contains({"category": category}))
        if run_id is not None:
            q = q.filter(cast(ReviewItem.context, JSONB).contains({"run_id": int(run_id)}))
        return q

    total = _build_q().count()
    prio_order = case(
        (ReviewItem.priority == "P0", 0),
        (ReviewItem.priority == "P1", 1),
        (ReviewItem.priority == "P2", 2),
        else_=3,
    )
    rows = (
        _build_q()
        .order_by(prio_order.asc(), ReviewItem.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    # 聚合计数（不受 category/run_id 过滤影响，供左栏分组角标）
    agg_base = db.query(ReviewItem)
    if not auth.is_super_admin:
        agg_base = agg_base.filter(ReviewItem.tenant_id == auth.tenant_id)
    if status:
        agg_base = agg_base.filter(ReviewItem.status == status)
    by_run: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for it in agg_base.with_entities(ReviewItem.context).all():
        try:
            c = json.loads(it[0] or "{}")
        except (TypeError, ValueError):
            c = {}
        rk = str(c.get("run_id") or c.get("run_no") or "")
        ck = str(c.get("category") or "未分类")
        if rk:
            by_run[rk] = by_run.get(rk, 0) + 1
        by_category[ck] = by_category.get(ck, 0) + 1
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [_item_out(r) for r in rows],
            "total": total,
            "by_run": by_run,
            "by_category": by_category,
        },
    }


@router.post("/items/{item_id}/decision", response_model=dict)
async def submit_decision(
    item_id: int,
    body: ReviewDecision,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("review", "manage")),
):
    """单条复核结论（approve/reject + 可选 promote_rule 规则回流）。

    promote_rule=true：把 keywords 写入全局拒答规则库 global_refusal_rules
    （judge_pipeline.promote_rule_to_question，D-13 定稿，keyword 去重幂等），
    run_item 侧 review_status 落 'promoted'。
    """
    item = _get_item(db, item_id, auth)
    if item.status in TERMINAL_STATES:
        raise BizError("ES-M9-0002", "复核项已是终态，无法提交结论")
    kws = [str(k).strip() for k in (body.keywords or []) if str(k).strip()][:20]
    review_status = _apply_decision(
        db, item,
        verdict=body.verdict, note=body.note,
        promote_keywords=(kws if body.promote_rule else None),
        reviewer_id=auth.user_id or 0,
    )
    db.refresh(item)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="review.decision", module="review", request=request,
        detail=(
            f"id={item.id} verdict={_norm_decision(body.verdict)} "
            f"promote={'y' if body.promote_rule else 'n'} run_item={review_status}"
        ),
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {**_item_out(item), "run_item_review_status": review_status},
    }


@router.post("/items/{item_id}/batch", response_model=dict)
async def batch_decision(
    item_id: int,
    body: ReviewBatch,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("review", "manage")),
):
    """批量 approve/reject（单事务，规格 §4.2 路径含 {id} 便于工作台复用）。

    item_ids 中与 {item_id} 同队列的项逐一提交；任一项非法/终态则整体回滚 422。
    批量不做规则回流（promote 仅单条 decision 支持）。
    """
    _norm_decision(body.verdict)  # 先校验 verdict，非法即 422 不动数据
    ids = list(dict.fromkeys([item_id, *body.item_ids]))
    q = db.query(ReviewItem).filter(ReviewItem.id.in_(ids))
    if not auth.is_super_admin:
        q = q.filter(ReviewItem.tenant_id == auth.tenant_id)
    items = q.order_by(ReviewItem.id.asc()).all()
    found = {it.id for it in items}
    missing = [i for i in ids if i not in found]
    if missing:
        raise NotFoundError("ES-M9-0003", f"复核项不存在或不属于当前租户：{missing}")
    blockers = [it.id for it in items if it.status in TERMINAL_STATES]
    if blockers:
        raise BizError(
            "ES-M9-0004", f"以下复核项已是终态，批量中止：{blockers}", http_status=422
        )
    human_verdict = "PASS" if _norm_decision(body.verdict) == "approve" else "FAIL"
    # 单事务：不用 complete_item 的逐项 commit，全部脏化后一次提交
    # D-12：rejected 不回写 eval_run_items 三列，仅留复核台账
    for it in items:
        it.human_verdict = human_verdict
        it.human_note = (body.note or None) and str(body.note)[:2000]
        it.status = ST_DONE
        db.add(it)
        if human_verdict == "PASS":
            _writeback_run_item(
                db, it, review_status="approved", reviewer_id=auth.user_id or 0
            )
    db.commit()
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="review.batch", module="review", request=request,
        detail=f"ids={ids} verdict={human_verdict}",
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {"processed": len(items), "verdict": human_verdict},
    }
