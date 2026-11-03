# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""评测集 / 评测运行路由（自 cases_core.py 拆分，BUG-006 纯重构：路由 URL 与 openapi 完全不变）。

包含：评测集 CRUD 与批量导入、评测运行创建/成本预估/对比（router），
以及详情/编辑/删除/批量删除补充段（extra_router，cases_core.py 原位聚合）。
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import cast, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    AuthContext,
    authenticate_request,
    ensure_data_scope,
    require_permission,
)
from ..engines import EngineContext, run_engine_step
from ..engines.registry import discover_engines
from ..errors import BizError, EvalError, NotFoundError
from ..limits import check_limit, check_upload_bytes
from ..models import (
    Defect,
    EvalRun,
    EvalRunItem,
    EvalSet,
    EvalSetRevision,
    FactSource,
    Project,
    ProjectVersion,
    QuestionBank,
    Report,
    ReviewItem,
    SystemUser,
    TestTask,
)
from ..schemas import (
    EvalRunCreate,
    EvalRunOut,
    EvalSetCreate,
    VALID_CASE_CATEGORIES,
)
from ..services import bank_executor, dataset_io, judge_pipeline, question_sampler, standards
from ..services.audit import write_audit
from ..utils.no import gen_no


router = APIRouter()
extra_router = APIRouter()
from ._business_common import *  # noqa: F401,F403
# ---------------------------------------------------------------------------
# 评测集 / 评测运行
# ---------------------------------------------------------------------------
@router.get("/eval-sets", response_model=dict)
async def list_eval_sets(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    category: str | None = None,
    project_id: int | None = None,
    source: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    q = db.query(EvalSet).filter(EvalSet.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(EvalSet.tenant_id == auth.tenant_id)
    if category:
        q = q.filter(EvalSet.category == category)
    if project_id:
        q = q.filter(EvalSet.project_id == project_id)
    if source:
        q = q.filter(EvalSet.source == source)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(EvalSet.name.ilike(like) | EvalSet.code.ilike(like))
    total = q.count()
    rows = (
        q.order_by(EvalSet.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [
                {
                    "id": s.id,
                    "code": s.code,
                    "name": s.name,
                    "category": s.category,
                    "project_id": s.project_id,
                    "item_count": s.item_count,
                    "version": s.version or "v1",
                    "content_schema": s.content_schema,
                    "source": s.source,
                    "visibility": s.visibility,
                    "meta": s.meta,
                    "created_at": s.created_at,
                }
                for s in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@router.post("/eval-sets", response_model=dict)
async def create_eval_set(
    body: EvalSetCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    if body.category not in VALID_CASE_CATEGORIES:
        raise BizError(
            "ES-BIZ-0016",
            f"非法评测集类别 {body.category!r}（合法：{sorted(VALID_CASE_CATEGORIES)}）",
        )
    # D-4：若指定 project_id，校验项目存在性
    if body.project_id is not None:
        proj = db.query(Project).filter(
            Project.id == body.project_id, Project.deleted_at.is_(None)
        ).first()
        if proj is None:
            raise NotFoundError("ES-BIZ-0010", "关联的项目不存在")

    s = EvalSet(
        code=gen_no("EVS"),
        name=body.name,
        category=body.category,
        project_id=body.project_id,
        items=body.items,
        item_count=len(body.items or []),
        content_schema=body.content_schema,
        source=body.source,
        meta=body.meta,
        visibility=body.visibility,
        created_by=auth.user_id,
        tenant_id=auth.tenant_id,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "id": s.id,
            "code": s.code,
            "name": s.name,
            "items": s.items,
            "item_count": s.item_count,
        },
    }


@router.post("/eval-sets/import", response_model=dict)
async def import_eval_set(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(None),
    category_form: str | None = Form(None, alias="category"),
    category_query: str | None = Query(None, alias="category"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("eval_set", "create")),
):
    """v2.0 P2：评测集批量导入（JSON/CSV）。category 支持 Form 或 Query 传参。

    JSON：[{"no":"HC-001","prompt":"...","references":["..."],"tags":["事实"]}, ...]
    CSV ：表头 no,prompt,references,tags（references 用 | 分隔，tags 用 , 分隔）；
          其余列（threat/threat_type/topic/rounds/contexts/ground_truth 等）原样透传。
    """
    category = category_form or category_query
    # B5：社区版附件上限（Content-Length 快速拒绝）
    check_limit("upload_size_mb", db, auth, request=request)
    if category not in _IMPORT_EVAL_SET_CATEGORIES:
        raise BizError(
            "ES-COMMON-0001",
            f"非法导入类别 {category!r}（合法：{sorted(_IMPORT_EVAL_SET_CATEGORIES)}）",
        )
    filename = (file.filename or "").lower()
    if not (filename.endswith(".json") or filename.endswith(".csv")):
        raise BizError("ES-COMMON-0002", "不支持的文件格式，仅支持 JSON/CSV")
    raw = await file.read()
    check_upload_bytes(len(raw))  # B5：落盘前二次校验实际字节数
    if not raw:
        raise BizError("ES-COMMON-0004", "文件内容为空")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BizError("ES-COMMON-0005", "文件编码须为 UTF-8")

    items: list[dict] = []
    if filename.endswith(".json"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BizError("ES-COMMON-0006", f"JSON 解析失败：{exc}")
        if not isinstance(data, list):
            raise BizError("ES-COMMON-0007", "JSON 须为数组格式")
        for it in data:
            if isinstance(it, dict):
                items.append(it)
    else:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            item: dict = {}
            for k, v in row.items():
                if k is None or v is None:
                    continue
                k = k.strip()
                if not k:
                    continue
                if k in ("references", "tags", "contexts", "fact_slots"):
                    sep = "|" if k == "references" else ","
                    item[k] = [s.strip() for s in str(v).split(sep) if s.strip()]
                elif k == "rounds":
                    try:
                        item[k] = int(str(v).strip())
                    except ValueError:
                        item[k] = str(v).strip()
                else:
                    item[k] = v.strip()
            if item:
                items.append(item)

    # 校验：样本量与必填字段
    if len(items) < 10:
        raise BizError("ES-COMMON-0003", f"样本量不足：{len(items)}条，建议≥100条")
    for idx, it in enumerate(items, 1):
        if not (it.get("prompt") or it.get("session") or it.get("topic")):
            raise BizError("ES-COMMON-0008", f"第{idx}条缺少 prompt/session/topic 字段")
        if "no" not in it:
            it["no"] = f"IMP-{idx:04d}"

    s = EvalSet(
        code=gen_no("EVS"),
        name=name or (file.filename or "imported").rsplit(".", 1)[0][:128],
        category=category,
        items=items,
        item_count=len(items),
        source="IMPORT",
        visibility="INTERNAL",
        version="v1",
        created_by=auth.user_id,
        tenant_id=auth.tenant_id,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="CREATE",
        module="eval_set",
        detail=f"批量导入评测集 {s.code}（{len(items)} 条）",
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {"id": s.id, "eval_set_no": s.code, "item_count": s.item_count},
    }


# ---------------------------------------------------------------------------
# ES8 M7：数据集版本化与批量导入（方案 §8）
#   精确路径全部挂 router 段，天然先于 extra_router 的 /eval-sets/{set_id} 匹配
# ---------------------------------------------------------------------------
def _get_eval_set_or_404(db: Session, set_id: int) -> EvalSet:
    es = db.get(EvalSet, set_id)
    if es is None or es.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0008", "评测集不存在")
    return es


@router.get("/eval-sets/{set_id}/revisions", response_model=dict)
async def list_eval_set_revisions(
    set_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """ES8 M7：版本历史列表（按版本号倒序，含 diff_stats 摘要，不含整文快照）。"""
    es = _get_eval_set_or_404(db, set_id)
    await ensure_data_scope(auth, resource_tenant_id=es.tenant_id)
    q = db.query(EvalSetRevision).filter(EvalSetRevision.eval_set_id == set_id)
    total = q.count()
    rows = (
        q.order_by(EvalSetRevision.version.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "current_version": es.version or "v1",
            "items": [
                {
                    "version": f"v{r.version}",
                    "diff_stats": json.loads(r.diff_stats) if r.diff_stats else None,
                    "item_count": len(json.loads(r.content or "[]")),
                    "created_by": r.created_by,
                    "created_at": r.created_at,
                }
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@router.get("/eval-sets/{set_id}/revisions/{version}", response_model=dict)
async def get_eval_set_revision(
    set_id: int,
    version: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """ES8 M7：单版本快照详情（vN / N 均接受，返回整文 items 供前端 diff）。"""
    es = _get_eval_set_or_404(db, set_id)
    await ensure_data_scope(auth, resource_tenant_id=es.tenant_id)
    n = version.lstrip("vV")
    try:
        nv = int(n)
    except ValueError:
        raise BizError("ES-M7-0016", f"非法版本号 {version!r}（期望 vN 或 N）")
    rev = (
        db.query(EvalSetRevision)
        .filter(
            EvalSetRevision.eval_set_id == set_id, EvalSetRevision.version == nv
        )
        .first()
    )
    if rev is None:
        raise NotFoundError("ES-M7-0017", f"版本快照 v{nv} 不存在")
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "eval_set_id": set_id,
            "version": f"v{rev.version}",
            "items": json.loads(rev.content or "[]"),
            "diff_stats": json.loads(rev.diff_stats) if rev.diff_stats else None,
            "created_by": rev.created_by,
            "created_at": rev.created_at,
        },
    }


@router.post("/eval-sets/import-preview", response_model=dict)
async def import_preview_eval_set(
    body: dict = Body(...),
    auth: AuthContext = Depends(require_permission("eval_set", "create")),
):
    """ES8 M7：CSV/JSONL 无状态预览。

    body: {"filename": "x.csv", "content_b64": "<文件字节 base64>", "mapping": 可选列映射}
    返回表头、行数、映射（猜测或指定）与前 20 行预览；确认建集走 import-confirm（携带 all_items）。
    """
    import base64 as _b64

    filename = str(body.get("filename") or "")
    content_b64 = body.get("content_b64")
    if not content_b64:
        raise BizError("ES-M7-0018", "缺少 content_b64（文件内容 base64）")
    try:
        raw = _b64.b64decode(str(content_b64))
    except Exception:
        raise BizError("ES-M7-0019", "content_b64 不是合法 base64")
    check_upload_bytes(len(raw))  # B5：复用社区版附件字节上限
    mapping = body.get("mapping") if isinstance(body.get("mapping"), dict) else None
    return {"code": 0, "message": "ok", "data": dataset_io.preview_result(filename, raw, mapping=mapping)}


@router.post("/eval-sets/import-confirm", response_model=dict)
async def import_confirm_eval_set(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("eval_set", "create")),
):
    """ES8 M7：预览确认后建集（无状态二次提交，items 由前端回传）。source=IMPORT。"""
    name = str(body.get("name") or "").strip()
    category = str(body.get("category") or "EVAL").upper()
    if category not in VALID_CASE_CATEGORIES:
        raise BizError(
            "ES-BIZ-0016",
            f"非法评测集类别 {category!r}（合法：{sorted(VALID_CASE_CATEGORIES)}）",
        )
    raw_items = body.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise BizError("ES-M7-0020", "items 不能为空（预览结果原样回传）")
    # 归一化：补 no、校验 prompt（与 from-review 共用同一入口校验）
    items = dataset_io.items_from_review(raw_items)
    s = dataset_io.build_imported_set(
        db,
        name=name or "批量导入评测集",
        category=category,
        items=items,
        source="IMPORT",
        user_id=auth.user_id,
        tenant_id=auth.tenant_id,
        meta_extra={"via": "import_confirm", "mapping": body.get("mapping")},
    )
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="CREATE",
        module="eval_set",
        detail=f"ES8-M7 向导导入评测集 {s.code}（{len(items)} 条）",
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {"id": s.id, "eval_set_no": s.code, "item_count": s.item_count, "version": s.version},
    }


@router.post("/eval-sets/from-run", response_model=dict)
async def create_eval_set_from_run(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("eval_set", "create")),
):
    """ES8 M7：从评测运行的失败用例（grade==FAIL）建集。source=FROM_RUN，带血缘。"""
    run_id = body.get("run_id")
    if run_id is None:
        raise BizError("ES-M7-0021", "缺少 run_id")
    run = db.get(EvalRun, int(run_id))
    if run is None or run.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0009", "评测运行不存在")
    await ensure_data_scope(auth, resource_tenant_id=run.tenant_id)
    items = dataset_io.fail_items_from_run(run)
    if not items:
        raise BizError("ES-M7-0022", "该运行无失败用例（grade=FAIL），未建集")
    src_es = db.get(EvalSet, run.eval_set_id)
    s = dataset_io.build_imported_set(
        db,
        name=str(body.get("name") or "").strip()
        or f"{(src_es.name if src_es else run.run_no)}-失败用例-{run.run_no}",
        category=str(body.get("category") or (src_es.category if src_es else "EVAL")),
        items=items,
        source="FROM_RUN",
        user_id=auth.user_id,
        tenant_id=auth.tenant_id,
        parent_set_id=run.eval_set_id,
        meta_extra={
            "run_id": run.id,
            "run_no": run.run_no,
            "run_dataset_version": run.dataset_version,
        },
    )
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="CREATE",
        module="eval_set",
        detail=f"ES8-M7 失败用例派生评测集 {s.code}（run={run.run_no}，{len(items)} 条）",
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {"id": s.id, "eval_set_no": s.code, "item_count": s.item_count, "source": s.source},
    }


@router.post("/eval-sets/from-review", response_model=dict)
async def create_eval_set_from_review(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("eval_set", "create")),
):
    """ES8 M7：评审队列回流建集（M6 未开发，仅预留 API 面：条目数组直接建集）。

    body: {"name", "category", "items": [{no?, prompt, expected?, tags?, ...}]}
    """
    name = str(body.get("name") or "").strip()
    category = str(body.get("category") or "EVAL").upper()
    if category not in VALID_CASE_CATEGORIES:
        raise BizError(
            "ES-BIZ-0016",
            f"非法评测集类别 {category!r}（合法：{sorted(VALID_CASE_CATEGORIES)}）",
        )
    items = dataset_io.items_from_review(body.get("items") or [])
    s = dataset_io.build_imported_set(
        db,
        name=name or "评审回流评测集",
        category=category,
        items=items,
        source="FROM_REVIEW",
        user_id=auth.user_id,
        tenant_id=auth.tenant_id,
        meta_extra={"via": "review", "review_source": body.get("review_source")},
    )
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="CREATE",
        module="eval_set",
        detail=f"ES8-M7 评审回流评测集 {s.code}（{len(items)} 条）",
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {"id": s.id, "eval_set_no": s.code, "item_count": s.item_count, "source": s.source},
    }


def _enrich_eval_runs(
    db: Session, items: list[dict], runs: list[EvalRun]
) -> None:
    """ES11 P2：活动列表批量富化（防 N+1，全部按当页 id 分组聚合）。

    附加字段（与 /eval-runs/{id}/workspace 同口径）：
    - g0_readiness：run_snapshot.readiness 摘要（PASS/BLOCKED/UNKNOWN）
    - is_baseline：run_snapshot.is_baseline 标记
    - review_pending：ReviewItem(source=run_item) 未 DONE/DISCARDED 数（G2）
    - open_p0p1：租户级未闭环 P0/P1 缺陷数（G3，与 workspace 同口径）
    - frozen：关联报告 summary._freeze 冻结标记（含 frozen_at）
    - bank_code/bank_version：题库编号与版本
    - version_no：项目版本归因
    - owner_name：负责人（created_by → SystemUser.display_name）
    """
    if not items:
        return
    run_ids = [int(it["id"]) for it in items]
    runs_by_id = {int(r.id): r for r in runs}
    tenant_ids = {int(r.tenant_id or 1) for r in runs}

    # review_pending：context TEXT 存 JSON，cast 后按 run_id 分组
    ctx = cast(ReviewItem.context, JSONB)
    pending_rows = (
        db.query(ctx["run_id"].astext, func.count(ReviewItem.id))
        .filter(
            ReviewItem.source == "run_item",
            ReviewItem.status.notin_(("DONE", "DISCARDED")),
            ctx["run_id"].astext.in_([str(i) for i in run_ids]),
        )
        .group_by(ctx["run_id"].astext)
        .all()
    )
    pending_map = {int(k): int(n) for k, n in pending_rows}

    # open_p0p1：按租户聚合（缺陷表无 run_id 列，与 workspace 同租户口径）
    p0p1_rows = (
        db.query(Defect.tenant_id, func.count(Defect.id))
        .filter(
            Defect.tenant_id.in_(tenant_ids),
            Defect.deleted_at.is_(None),
            Defect.severity.in_(("P0", "P1")),
            Defect.status.in_(("NEW", "OPEN", "FIXED", "VERIFYING", "REOPENED")),
        )
        .group_by(Defect.tenant_id)
        .all()
    )
    p0p1_map = {int(k): int(n) for k, n in p0p1_rows}

    # frozen：report_id → summary._freeze
    report_ids = [int(r.report_id) for r in runs if r.report_id]
    freeze_map: dict[int, dict] = {}
    if report_ids:
        for rep in db.query(Report).filter(Report.id.in_(report_ids)).all():
            fz = (rep.summary or {}).get("_freeze")
            if fz:
                freeze_map[int(rep.id)] = fz

    # 题库 / 版本 / 负责人
    bank_ids = {int(r.question_bank_id) for r in runs if r.question_bank_id}
    bank_map: dict[int, tuple] = {}
    if bank_ids:
        for b in db.query(QuestionBank).filter(QuestionBank.id.in_(bank_ids)).all():
            bank_map[int(b.id)] = (b.code, b.bank_version)
    version_ids = {int(r.project_version_id) for r in runs if r.project_version_id}
    version_map: dict[int, str] = {}
    if version_ids:
        for v in db.query(ProjectVersion).filter(
            ProjectVersion.id.in_(version_ids)
        ).all():
            version_map[int(v.id)] = v.version_no
    user_ids = {int(r.created_by) for r in runs if r.created_by}
    user_map: dict[int, str] = {}
    if user_ids:
        for u in db.query(SystemUser).filter(SystemUser.id.in_(user_ids)).all():
            user_map[int(u.id)] = u.display_name or u.username

    for it in items:
        run = runs_by_id.get(int(it["id"]))
        if run is None:
            continue
        snap = run.run_snapshot or {}
        readiness = snap.get("readiness")
        it["g0_readiness"] = (
            "UNKNOWN" if readiness is None
            else ("PASS" if readiness.get("ready") else "BLOCKED")
        )
        it["is_baseline"] = bool(snap.get("is_baseline"))
        it["review_pending"] = pending_map.get(int(run.id), 0)
        it["open_p0p1"] = p0p1_map.get(int(run.tenant_id or 1), 0)
        fz = freeze_map.get(int(run.report_id)) if run.report_id else None
        it["frozen"] = bool(fz)
        it["frozen_at"] = (fz or {}).get("frozen_at")
        bank = bank_map.get(int(run.question_bank_id)) if run.question_bank_id else None
        it["bank_code"] = bank[0] if bank else None
        it["bank_version"] = bank[1] if bank else None
        it["version_no"] = version_map.get(int(run.project_version_id)) if run.project_version_id else None
        it["owner_name"] = user_map.get(int(run.created_by)) if run.created_by else None
        it["run_purpose"] = run.run_purpose


@router.get("/eval-runs", response_model=dict)
def list_eval_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    task_id: int | None = Query(None, description="可选：按关联任务过滤"),
    eval_set_id: int | None = Query(None, description="可选：按评测集过滤"),
    project_id: int | None = Query(None, description="可选：按评测集所属项目过滤"),
    status: str | None = Query(None, description="可选：按运行状态过滤"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    # 所属项目：优先评测集所属项目；任务自动创建的运行（无评测集）回退任务所属项目
    q = (
        db.query(
            EvalRun,
            func.coalesce(EvalSet.project_id, TestTask.project_id).label("project_id"),
        )
        .outerjoin(EvalSet, EvalRun.eval_set_id == EvalSet.id)
        .outerjoin(TestTask, EvalRun.task_id == TestTask.id)
        .filter(EvalRun.deleted_at.is_(None))
    )
    if task_id is not None:
        q = q.filter(EvalRun.task_id == task_id)
    if eval_set_id is not None:
        q = q.filter(EvalRun.eval_set_id == eval_set_id)
    if project_id:
        q = q.filter(
            func.coalesce(EvalSet.project_id, TestTask.project_id) == project_id
        )
    if status:
        q = q.filter(EvalRun.status == status)
    if not auth.is_super_admin:
        q = q.filter(EvalRun.tenant_id == auth.tenant_id)
    total = q.count()
    rows = (
        q.order_by(EvalRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        # A6/§8：列表补 engine_code（EvalRunOut 未含该列，此处手工附加）
        # 补 project_id（来自所属评测集，供前端"所属项目"列与筛选）
        # ES8 M7：补 dataset_version（运行时的评测集版本快照，供 UI 展示"本运行用的是 vN"）
        {
            **EvalRunOut.model_validate(r).model_dump(),
            "engine_code": r.engine_code,
            "dataset_version": r.dataset_version,
            "project_id": run_project_id,
        }
        for r, run_project_id in rows
    ]
    # ES11 P2：门禁/复核/冻结/基线/负责人等列表富化（批量聚合，防 N+1）
    _enrich_eval_runs(db, items, [r for r, _pid in rows])
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@router.post("/eval-runs", response_model=dict)
async def create_eval_run(
    body: EvalRunCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    # ES9-P-10：题库执行分支（question_bank_id + eval_set_id=0）——
    # 抽题→逐题调被测→双轨判定→eval_run_items 落库→summary 聚合。
    if int(getattr(body, "question_bank_id", 0) or 0) > 0:
        return await _create_bank_eval_run(body, db, auth)

    # BUG-006（D-08/RUN-02）：无题库旧参数在一个迭代周期内 422 拒绝，
    # detail.breaking_change 给迁移口径；周期后是否下线另行决策
    # （设计方案 §13 D-08 定稿）。下方 legacy 执行体保留不删。
    raise EvalError(
        "ES-RUN-LEGACY",
        "评测运行必须绑定题库（question_bank_id 必填）",
        http_status=422,
        detail={
            "breaking_change": (
                "自 ES9 起 POST /api/eval-runs 不再接受无题库的 EvalSet 直连旧参数；"
                "请携带 question_bank_id（可选 sample_size）改为题库执行。"
                "本兼容窗口为一个迭代周期，周期后旧参数下线另行决策。"
            )
        },
    )

    es = db.get(EvalSet, body.eval_set_id)
    if es is None or es.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0008", "评测集不存在")
    await ensure_data_scope(auth, resource_tenant_id=es.tenant_id)

    # 预扣 EVAL 配额（配额不足直接拒绝）
    from ..services.task_runner import _charge, quota_info

    quota = quota_info(db, tenant_id=auth.tenant_id)
    if quota["eval_used"] >= quota["eval_quota"]:
        raise BizError("ES-BIZ-0014", "评测配额已用尽，请联系管理员升级额度")

    # judge_mode 校验：枚举 + MODEL/HYBRID 必须携带 judge_model
    if body.judge_mode not in ("RULE", "MODEL", "HYBRID"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="judge_mode 必须是 RULE / MODEL / HYBRID",
        )
    if body.judge_mode in ("MODEL", "HYBRID") and not body.judge_model:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="judge_mode 为 MODEL 或 HYBRID 时，judge_model 必填",
        )

    run = EvalRun(
        run_no=gen_no("EV"),
        eval_set_id=es.id,
        eval_set_code=es.code,
        target_type=body.target_type,
        target_id=body.target_id,
        model_gateway=body.model_gateway,
        judge_mode=body.judge_mode,
        judge_model=body.judge_model,
        status="RUNNING",
        # A6：engine_code 透传（EvalRunCreate 未含该字段时 getattr 返回 None，尽力而为）
        engine_code=getattr(body, "engine_code", None),
        created_by=auth.user_id,
        tenant_id=auth.tenant_id,
    )
    db.add(run)
    db.flush()

    # A6：创建时尽力估算成本（engine_batch 缺失/价格缺失 → None，不阻断）
    try:
        from ..services.task_runner import _calls_for_engine, _estimate_run_cost

        _ec = getattr(body, "engine_code", None)
        if _ec:
            run.estimated_cost = _estimate_run_cost(
                db, _ec, body.judge_model, _calls_for_engine(_ec, es.item_count or 0)
            )
    except Exception:  # noqa: BLE001
        pass

    # 同步执行评测（复用 EVAL_ENGINE 规则模式）—— Evaluator 为商业引擎，社区剥离版优雅拒绝
    try:
        from ..commercial.engines.eval_engine import EvalEngine
    except ImportError:
        raise BizError("ES-LIMIT-0005", "评测执行引擎为商业版专属能力", http_status=403)

    discover_engines()
    engine = EvalEngine()
    ctx = EngineContext(
        task_id=0,
        task_no=run.run_no,
        step_id=run.id,
        step_no=run.run_no,
        project_id=0,
        engine_code="EVAL_ENGINE",
        config={
            "items": es.items or [],
            "judge_mode": body.judge_mode,
            "threshold": 0.7,
        },
        db=db,
        extra={"eval_items": es.items or [], "judge_mode": body.judge_mode},
    )
    result, duration = run_engine_step(engine, ctx)
    run.item_results = result.report_payload.get("items", [])
    run.overall_score = result.summary.get("overall_score")
    run.verdict = (
        "PASS"
        if result.status == "SUCCESS"
        else "SKIP"
        if result.status == "SKIPPED"
        else "FAIL"
    )
    run.summary = result.summary
    run.status = (
        "SUCCESS"
        if result.status == "SUCCESS"
        else "SKIPPED"
        if result.status == "SKIPPED"
        else "FAILED"
    )
    run.started_at = datetime.now(timezone.utc)
    run.finished_at = datetime.now(timezone.utc)
    run.duration_ms = duration
    _charge(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        biz_type="EVAL",
        amount=1.0,
        ref_no=run.run_no,
        description=f"评测运行：{es.name}（目标 {body.target_id}）",
    )
    db.commit()
    db.refresh(run)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            **EvalRunOut.model_validate(run).model_dump(),
            "engine_code": run.engine_code,
            "estimated_cost": run.estimated_cost,
        },
    }


async def _create_bank_eval_run(
    body: EvalRunCreate, db: Session, auth: AuthContext
):
    """ES9-P-10：题库评测运行（question_bank_id 分支，§4.1.2-C 执行链）。

    抽题（分层抽样+seed 快照）→ 逐题调被测 → 双轨判定 → eval_run_items 落库
    → 三集指标聚合写 summary → needs_review 联动复核入队。
    """
    from ..services.task_runner import quota_info

    # ES10-P-01：事实基准知识源校验（软引用，租户匹配 + 未删除）
    if body.fact_source_id:
        fs_q = db.query(FactSource).filter(
            FactSource.id == body.fact_source_id,
            FactSource.deleted_at.is_(None),
        )
        if not auth.is_super_admin:
            fs_q = fs_q.filter(FactSource.tenant_id == auth.tenant_id)
        if fs_q.first() is None:
            raise EvalError("ES-RUN-FS-404", "事实基准知识源不存在", http_status=400)

    bank = (
        db.query(QuestionBank)
        .filter(QuestionBank.id == int(body.question_bank_id), QuestionBank.deleted_at.is_(None))
        .first()
    )
    if bank is None:
        raise NotFoundError("ES-QB-001", "题库不存在")
    if not auth.is_super_admin and bank.tenant_id != auth.tenant_id:
        raise NotFoundError("ES-QB-001", "题库不存在")
    if bank.status == "archived":
        raise BizError("ES-QB-012", "题库已归档，不能发起评测")

    quota = quota_info(db, tenant_id=auth.tenant_id)
    if quota["eval_used"] >= quota["eval_quota"]:
        raise BizError("ES-BIZ-0014", "评测配额已用尽，请联系管理员升级额度")

    if body.judge_mode not in ("RULE", "MODEL", "HYBRID"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="judge_mode 必须是 RULE / MODEL / HYBRID",
        )
    if body.judge_mode in ("MODEL", "HYBRID") and not body.judge_model:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="judge_mode 为 MODEL 或 HYBRID 时，judge_model 必填",
        )

    size = bank_executor.community_clamped_size(body.sample_size)

    # ES11 G0：服务端准备度复校验（不信任前端预检；BLOCK 抛 ES-BIZ-READY-0001）
    from ..services import gate_service

    readiness = gate_service.revalidate_blocks(
        db,
        {
            "target_id": body.target_id,
            "question_bank_id": int(body.question_bank_id),
            "sample_size": size,
            "judge_mode": body.judge_mode,
            "judge_model": body.judge_model,
            "fact_source_id": body.fact_source_id,
            "project_version_id": body.project_version_id,
            "engine_code": body.engine_code,
            # 优化12 §4.3：G0 新校验入参补键（ENGINE_CODE_VALID / ENGINE_CATEGORY_MATCH）
            "activity_id": body.activity_id,
            "category_quotas": body.category_quotas,
            # 优化12 §8.1a：档位预检 SCREENING 豁免入参
            "run_purpose": body.run_purpose,
        },
        auth,
    )

    run = EvalRun(
        run_no=gen_no("EV"),
        eval_set_id=int(body.eval_set_id or 0),
        eval_set_code=None,
        question_bank_id=int(bank.id),
        fact_source_id=body.fact_source_id,
        target_type=body.target_type,
        target_id=body.target_id,
        model_gateway=body.model_gateway,
        judge_mode=body.judge_mode,
        judge_model=body.judge_model,
        status="RUNNING",
        engine_code=getattr(body, "engine_code", None),
        started_at=datetime.now(timezone.utc),
        created_by=auth.user_id,
        tenant_id=auth.tenant_id,
        # ES11：活动目的与血缘
        run_purpose=body.run_purpose,
        parent_run_id=body.parent_run_id,
        baseline_run_id=body.baseline_run_id,
        project_version_id=body.project_version_id,
    )
    db.add(run)
    db.flush()

    # 尽力估算成本（价格缺失 → None，不阻断）
    try:
        from ..services.engine_batch import estimate_cost as _est

        run.estimated_cost = _est(db, body.judge_model, size, 600, 200)
    except Exception:  # noqa: BLE001
        pass

    questions, used_seed, plan = question_sampler.sample_questions(
        db, int(bank.id), auth.tenant_id, sample_size=size,
        category_quotas=body.category_quotas,
    )
    if not questions:
        raise BizError("ES-QB-013", "题库无可用题目，请先导入题目后发起评测")

    from ..services import target_gateway

    target = target_gateway.load_target(db, body.target_id, tenant_id=auth.tenant_id)
    judge_cfg = (
        judge_pipeline.resolve_judge_model_cfg(db, body.judge_model, tenant_id=auth.tenant_id)
        if body.judge_mode in ("MODEL", "HYBRID")
        else None
    )
    _, prompt_hash = judge_pipeline.load_prompt(
        f"judge/{judge_pipeline.PROMPT_VERSION}"
    )
    run.run_snapshot = bank_executor.build_snapshot(
        seed=used_seed,
        plan=plan,
        sample_size=len(questions) if body.category_quotas else size,
        judge_cfg=judge_cfg,
        target_mode="API" if target else "INTERNAL_DEMO",
        prompt_hash=prompt_hash,
        # 优化12 §4.4：正常创建路径注入当前标准口径版本与活动聚合键
        standards_ver=standards.standards_version(),
        activity_id=body.activity_id,
    )
    # ES11：readiness 固化进快照（workspace G0 展示依据）
    snap = dict(run.run_snapshot or {})
    snap["readiness"] = readiness
    run.run_snapshot = snap
    db.commit()
    db.refresh(run)

    # 优化12 BUG-007 正解：逐题执行转后台（daemon 线程 + 独立 Session，
    # 仿 ES11 复测 _spawn_retest 范式）；抽题/校验保持同步段，失败仍 4xx。
    # 计费与审计随后台收尾（铁律8 审计链自开 session 不破坏）。
    bank_executor.spawn_run_questions(
        int(run.id), questions,
        seed=used_seed, plan=plan, sample_size=size,
        tenant_id=auth.tenant_id, user_id=auth.user_id, username=auth.username,
        bank_name=bank.name, run_no=run.run_no, target_id=body.target_id,
        audit_detail=(
            f"题库评测 {bank.code}（run {run.run_no}，抽样 {len(questions)}）"
        ),
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {
            **EvalRunOut.model_validate(run).model_dump(),
            "engine_code": run.engine_code,
            "estimated_cost": run.estimated_cost,
            "summary": run.summary,
            "async": True,
        },
    }


@router.post("/eval-runs/{run_id}/resume", response_model=dict)
async def resume_eval_run(
    run_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """ES9-P-10：断点续跑（§4.1.2-C）。

    仅题库运行支持；按 run_snapshot.sample_seed 重放抽样，
    与已落库 question_id 做差集，只补缺失题目。
    状态机：FAILED（中断）→ RUNNING → PASSED/FAILED。
    """
    run = db.get(EvalRun, run_id)
    if run is None or run.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0009", "评测运行不存在")
    if not auth.is_super_admin and run.tenant_id != auth.tenant_id:
        raise NotFoundError("ES-BIZ-0009", "评测运行不存在")
    if run.question_bank_id is None:
        raise BizError("ES-BIZ-0008", "非题库运行不支持续跑（请重新发起评测）")
    if run.status not in ("FAILED", "RUNNING", "PENDING"):
        raise BizError(
            "ES-BIZ-0010", f"当前状态 {run.status} 不可续跑（仅中断的运行支持）"
        )
    out = bank_executor.resume_run(db, run)
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="UPDATE",
        module="eval_run",
        detail=f"续跑评测 {run.run_no}（补执行 {out.get('resumed_pending')} 题）",
    )
    db.commit()
    db.refresh(run)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "run_id": int(run.id),
            "status": run.status,
            "resumed_pending": out.get("resumed_pending"),
            "executed": out.get("executed"),
            "needs_review": out.get("needs_review"),
            "enqueued": out.get("enqueued"),
            "summary": run.summary,
        },
    }


@router.post("/eval-runs/{run_id}/rerun-judgment", response_model=dict)
async def rerun_eval_judgment(
    run_id: int,
    body: dict | None = Body(default=None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """ES9-P-11：判定重放（§4.2）。

    用 run_snapshot 固化参数（judge_prompt 版本 / seed / 裁判模型）重放裁判轨，
    不调被测系统；重聚合三集指标并回写 summary。返回判定翻转统计供对账。
    BUG-006（D-11/JD-04）：快照 hash 漂移默认 409 ES-JD-PROMPT-DRIFT；
    body.override_judge_prompt=true 显式放行且新 hash 记入 rerun 台账。
    """
    run = db.get(EvalRun, run_id)
    if run is None or run.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0009", "评测运行不存在")
    if not auth.is_super_admin and run.tenant_id != auth.tenant_id:
        raise NotFoundError("ES-BIZ-0009", "评测运行不存在")
    override = bool((body or {}).get("override_judge_prompt", False))
    out = judge_pipeline.rerun_judgment(db, run, override_prompt_hash=override)
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="UPDATE",
        module="eval_run",
        detail=f"判定重放 {run.run_no}（重判 {out.get('rejudged')}，翻转 {out.get('verdict_flipped')}）",
    )
    db.commit()
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "run_id": int(run.id),
            **out,
            # ES11 §3.4：判分重放隔离声明
            "notice": "重新判分不重新调用被测系统，结果不能作为缺陷验证证据（验证仅认 run_purpose=RETEST 的真实复测）",
        },
    }


def _estimate_bank_eval(body: dict, db: Session, auth: AuthContext) -> dict:
    """ES9-P-10：题库评测成本预估（§4.1.2-C line 706 契约）。"""
    from ..services.engine_batch import estimate_cost as _est

    bank = (
        db.query(QuestionBank)
        .filter(
            QuestionBank.id == int(body["question_bank_id"]),
            QuestionBank.deleted_at.is_(None),
        )
        .first()
    )
    if bank is None:
        raise NotFoundError("ES-QB-001", "题库不存在")
    if not auth.is_super_admin and bank.tenant_id != auth.tenant_id:
        raise NotFoundError("ES-QB-001", "题库不存在")

    size = bank_executor.community_clamped_size(body.get("sample_size"))
    available = question_sampler.count_bank_questions(db, int(bank.id))
    n_q = min(size, available)

    # 题面平均长度（字符→token 粗估 /4）；单轮回答按 200 token 计
    avg_chars = question_sampler.avg_question_len(db, int(bank.id)) if n_q else 0
    est_prompt_tokens = n_q * (max(avg_chars // 4, 50) + 50)
    est_completion_tokens = n_q * 200

    target_model = str(body.get("target_model") or body.get("target_id") or "") or None
    est_cost_cny = _est(
        db, target_model, n_q, est_prompt_tokens // n_q if n_q else 0, 200
    )
    judge_model = body.get("judge_model")
    judge_cost_cny = None
    if str(body.get("judge_mode") or "RULE") in ("MODEL", "HYBRID"):
        # 裁判轨：每题一次判定调用，输入≈题面+回答+模板开销
        judge_cost_cny = _est(
            db, judge_model, n_q,
            (est_prompt_tokens // n_q if n_q else 0) + 400, 60,
        )
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "questions": n_q,
            "est_prompt_tokens": est_prompt_tokens,
            "est_completion_tokens": est_completion_tokens,
            "est_cost_cny": est_cost_cny,
            "judge_cost_cny": judge_cost_cny,
        },
    }


@router.post("/eval-runs/estimate", response_model=dict)
async def estimate_eval_run(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """A7/§4.4：发起评测前的成本预估。

    入参 {engine_code, eval_set_id?, eval_set_code?, judge_model?}；
    按评测集 item_count 估调用数（RAG≈item*3、幻觉≈item*2、其余≈item），
    engine_batch 不可用或价格缺失时 estimated_cost=None 降级。
    注意：本路由必须注册在任何 /eval-runs/{run_id} 路径参数路由之前。

    ES9-P-10：入参含 question_bank_id 时走题库口径（§4.1.2-C line 706）——
    返回 {questions, est_prompt_tokens, est_completion_tokens,
    est_cost_cny, judge_cost_cny}，单价取 model_configs，缺失降级 None。
    """
    if int(body.get("question_bank_id") or 0) > 0:
        return _estimate_bank_eval(body, db, auth)

    from ..services.task_runner import _calls_for_engine, _estimate_run_cost

    engine_code = str(body.get("engine_code") or "")
    if not engine_code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="engine_code 必填",
        )
    es = None
    if body.get("eval_set_id"):
        es = db.get(EvalSet, int(body["eval_set_id"]))
    elif body.get("eval_set_code"):
        es = (
            db.query(EvalSet)
            .filter(EvalSet.code == str(body["eval_set_code"]), EvalSet.deleted_at.is_(None))
            .first()
        )
    item_count = int(es.item_count or 0) if es else 0
    calls = _calls_for_engine(engine_code, item_count)
    # v2.0 P6：judge_model 缺省时回退默认模型（与引擎运行时 resolve_model_config 行为一致）
    judge_model = body.get("judge_model")
    if not judge_model:
        from ..services.engine_llm import resolve_model_config

        _default = resolve_model_config(db, {}, tenant_id=auth.tenant_id)
        judge_model = (_default or {}).get("code")
    estimated_cost = _estimate_run_cost(db, engine_code, judge_model, calls)
    # v2.0 P6：预估时长（每次调用约2秒，按并发折算）
    conc = max(1, int(body.get("concurrency") or 2))
    duration_min = round(calls * 2 / conc / 60, 1)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "item_count": item_count,
            "calls": calls,
            "estimated_cost": estimated_cost,
            "estimated_minutes": duration_min,
        },
    }


@router.get("/eval-sets/{set_id}/compare", response_model=dict)
async def compare_eval_runs(
    set_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """评测集运行对比：同一评测集多次运行的得分趋势与差异。"""
    es = db.get(EvalSet, set_id)
    if es is None or es.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0008", "评测集不存在")
    await ensure_data_scope(auth, resource_tenant_id=es.tenant_id)
    runs = (
        db.query(EvalRun)
        .filter(EvalRun.eval_set_id == set_id, EvalRun.deleted_at.is_(None))
        .order_by(EvalRun.id.asc())
        .all()
    )
    trend = []
    for r in runs:
        if r.overall_score is None:
            continue
        trend.append(
            {
                "run_no": r.run_no,
                "target_id": r.target_id,
                "score": r.overall_score,
                "verdict": r.verdict,
                "duration_ms": r.duration_ms,
                "created_at": r.created_at,
            }
        )
    scores = [t["score"] for t in trend]
    stats = {}
    if scores:
        stats = {
            "count": len(scores),
            "latest": scores[-1],
            "avg": round(sum(scores) / len(scores), 4),
            "max": max(scores),
            "min": min(scores),
            "delta": round(scores[-1] - scores[0], 4) if len(scores) > 1 else 0.0,
            "trend": "UP"
            if len(scores) > 1 and scores[-1] >= scores[0]
            else "DOWN"
            if len(scores) > 1
            else "FLAT",
        }
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "eval_set": {"id": es.id, "code": es.code, "name": es.name},
            "stats": stats,
            "trend": trend,
        },
    }
# ---------------------------------------------------------------------------
# 评测集（补：详情 / 编辑 / 删除）
# ---------------------------------------------------------------------------
@extra_router.get("/eval-sets/{set_id}", response_model=dict)
async def get_eval_set(
    set_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    es = db.get(EvalSet, set_id)
    if es is None or es.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0008", "评测集不存在")
    await ensure_data_scope(auth, resource_tenant_id=es.tenant_id)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "id": es.id,
            "code": es.code,
            "name": es.name,
            "category": es.category,
            "project_id": es.project_id,
            "items": es.items,
            "item_count": es.item_count,
            "version": es.version or "v1",
            "content_schema": es.content_schema,
            "source": es.source,
            "meta": es.meta,
            "visibility": es.visibility,
            "created_at": es.created_at,
            "updated_at": es.updated_at,
        },
    }


@extra_router.put("/eval-sets/{set_id}", response_model=dict)
async def update_eval_set(
    set_id: int,
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    es = db.get(EvalSet, set_id)
    if es is None or es.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0008", "评测集不存在")
    await ensure_data_scope(auth, resource_tenant_id=es.tenant_id)
    updatable = ("name", "category", "project_id", "items", "visibility", "content_schema")
    changed = False
    items_changed = body.get("items") is not None and list(body.get("items") or []) != list(es.items or [])
    # ES8 M7：内容有变 → 升版前捕获旧 items 深拷贝（setattr 后 es.items 即被替换）
    old_items = json.loads(json.dumps(es.items or [])) if items_changed else None
    for k in updatable:
        v = body.get(k)
        if v is not None:
            setattr(es, k, v)
            changed = True
    if body.get("items") is not None:
        es.item_count = len(body.get("items") or [])
        changed = True
    # A8/T3：items 实际变化 → version 自动递增并写 meta.version_history
    if items_changed:
        # ES8 M7：编辑即升版——旧内容整文快照进 eval_set_revisions（含行级 diff_stats）
        dataset_io.snapshot_revision(
            db, es, old_items or [], list(es.items or []), auth.user_id
        )
        _bump_eval_set_version(es)
    if changed:
        es.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(es)
    return await get_eval_set(set_id, db, auth)


@extra_router.delete("/eval-sets/{set_id}", response_model=dict)
async def delete_eval_set(
    set_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    es = db.get(EvalSet, set_id)
    if es is None or es.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0008", "评测集不存在")
    await ensure_data_scope(auth, resource_tenant_id=es.tenant_id)
    es.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@extra_router.post("/eval-sets/batch-delete", response_model=dict)
async def batch_delete_eval_sets(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """D-DEL-05：批量删除评测集（软删）。"""
    ids = [int(x) for x in (body.get("ids") or [])]
    if not ids:
        return {"code": 0, "message": "ok", "data": {"deleted": 0, "skipped": 0, "not_found": []}}
    now = datetime.now(timezone.utc)
    deleted = skipped = 0
    not_found: list[int] = []
    for sid in ids:
        es = db.get(EvalSet, sid)
        if es is None or es.deleted_at is not None:
            not_found.append(sid); continue
        if es.tenant_id != auth.tenant_id:
            skipped += 1; continue
        es.deleted_at = now; deleted += 1
    db.commit()
    return {"code": 0, "message": "ok",
            "data": {"deleted": deleted, "skipped": skipped, "not_found": not_found}}


# ---------------------------------------------------------------------------
# 评测运行（补：详情含 item_results）
# ---------------------------------------------------------------------------
@extra_router.get("/eval-runs/{run_id}", response_model=dict)
async def get_eval_run(
    run_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    r = db.get(EvalRun, run_id)
    if r is None or r.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0018", "评测运行不存在")
    await ensure_data_scope(auth, resource_tenant_id=r.tenant_id)

    # 补所属项目：优先评测集所属项目；任务自动创建的运行（无评测集）回退任务所属项目
    project_id = None
    if r.eval_set_id:
        es = db.get(EvalSet, r.eval_set_id)
        if es:
            project_id = es.project_id
    task_no = None
    if r.task_id:
        t = db.get(TestTask, r.task_id)
        if t:
            task_no = t.task_no
            if project_id is None:
                project_id = t.project_id
    project_name = None
    if project_id:
        pj = db.get(Project, project_id)
        if pj:
            project_name = f"{pj.code} - {pj.name}"

    # A5/§8：ragas 从 item_results 的 detail 或 summary 提取（非 RAG 运行为 None）
    ragas = None
    if r.engine_code == "RAG_TEST" or (r.item_results and any(
        isinstance(row, dict)
        and isinstance(row.get("detail"), dict)
        and isinstance(row["detail"].get("ragas"), dict)
        for row in r.item_results
    )):
        try:
            from ..services.task_runner import _summarize_ragas

            payload = {
                "ragas": (r.summary or {}).get("ragas") if isinstance(r.summary, dict) else None,
                "items": [
                    row.get("detail")
                    for row in (r.item_results or [])
                    if isinstance(row, dict) and isinstance(row.get("detail"), dict)
                ],
            }
            ragas = _summarize_ragas(payload)
        except Exception:  # noqa: BLE001
            ragas = None

    # ES10-E2E-01：题库 run 的 item_results 列为空，逐题明细在 eval_run_items
    # sidecar（单一事实源）——详情接口从 sidecar 重建，前端契约与引擎 run 对齐。
    item_results = r.item_results
    if r.question_bank_id and not item_results:
        sidecar_rows = (
            db.query(EvalRunItem)
            .filter(EvalRunItem.run_id == r.id)
            .order_by(EvalRunItem.seq, EvalRunItem.id)
            .all()
        )
        item_results = [
            {
                # seq 在未提交的分批内可能重复（_next_seq 依赖已提交行），
                # 展示序号按枚举序重编，避免前端"序号"列出现重复值。
                "no": idx,
                "prompt": it.prompt,
                "response": it.response,
                "verdict": it.final_verdict,
                "reason": it.verdict_reason,
                "split": it.split,
                "category": it.category,
                "latency_ms": it.latency_ms,
            }
            for idx, it in enumerate(sidecar_rows, start=1)
        ]

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "id": r.id,
            "run_no": r.run_no,
            "task_id": r.task_id,
            "task_no": task_no,
            "eval_set_id": r.eval_set_id,
            "eval_set_code": r.eval_set_code,
            "project_id": project_id,
            "project_name": project_name,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "model_gateway": r.model_gateway,
            "judge_mode": r.judge_mode,
            "judge_model": r.judge_model,
            "status": r.status,
            "item_results": item_results,
            "overall_score": r.overall_score,
            "verdict": r.verdict,
            "summary": r.summary,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "duration_ms": r.duration_ms,
            "created_at": r.created_at,
            # A5/§8 扩展字段（旧数据为 None，前端走兜底渲染）
            "engine_code": r.engine_code,
            "dataset_version": r.dataset_version,
            "run_snapshot": r.run_snapshot,
            "estimated_cost": r.estimated_cost,
            "actual_cost": r.actual_cost,
            "ragas": ragas,
            # ES10-P-02 §9.2.2：运行详情透出事实基准与项目版本归因
            "fact_source": (r.summary or {}).get("fact_source") if isinstance(r.summary, dict) else None,
            # ES10-E2E-01：题库 run 回显题库名
            "bank_name": (r.summary or {}).get("bank_name") if isinstance(r.summary, dict) else None,
            "project_version_id": r.project_version_id,
        },
    }


@extra_router.delete("/eval-runs/{run_id}", response_model=dict)
async def delete_eval_run(
    run_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """D-DEL-06：删除评测运行（软删）—— eval-run 此前无单删端点。"""
    er = db.get(EvalRun, run_id)
    if er is None or er.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0018", "评测运行不存在")
    await ensure_data_scope(auth, resource_tenant_id=er.tenant_id)
    er.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@extra_router.post("/eval-runs/batch-delete", response_model=dict)
async def batch_delete_eval_runs(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """D-DEL-06b：批量删除评测运行（软删）。"""
    ids = [int(x) for x in (body.get("ids") or [])]
    if not ids:
        return {"code": 0, "message": "ok", "data": {"deleted": 0, "skipped": 0, "not_found": []}}
    now = datetime.now(timezone.utc)
    deleted = skipped = 0
    not_found: list[int] = []
    for rid in ids:
        er = db.get(EvalRun, rid)
        if er is None or er.deleted_at is not None:
            not_found.append(rid); continue
        if er.tenant_id != auth.tenant_id:
            skipped += 1; continue
        er.deleted_at = now; deleted += 1
    db.commit()
    return {"code": 0, "message": "ok",
            "data": {"deleted": deleted, "skipped": skipped, "not_found": not_found}}
