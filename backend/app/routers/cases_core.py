# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""业务路由：项目、任务（创建/执行/取消/进度）、用例、数据集、场景、评测、报告、模型网关、通知、仪表盘。

任务执行采用同步模拟调度：创建 TaskStep → EngineRegistry 执行 → 汇总 summary → 生成报告。
（真实异步执行器可在 scripts/ 中扩展为后台 worker。）
"""

from __future__ import annotations

import hashlib
import json
import csv
import io
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO

logger = logging.getLogger(__name__)

# FE-02/FE-05：需要非空 base_url 才能执行的 HTTP 类引擎（后端空串兜底校验）
_HTTP_BASED_ENGINES = {
    "API_TEST",
    "UI_TEST",
    "DATAFLOW_TEST",
    "PERF_TEST",
    "LOCUST_PERF",
    "PRIVILEGE_ESCALATION",
    "SELF_HEAL",
}

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import String, case, cast, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    AuthContext,
    authenticate_request,
    ensure_data_scope,
    require_permission,
)
from ..engines import EngineContext, engine_registry, run_engine_step
from ..engines.registry import discover_engines
from ..errors import BizError, NotFoundError
from ..limits import check_limit, check_upload_bytes
from ..services.audit import write_audit
from ..services.report_sections import compliance_conclusion
from ..models import (
    AuditLog,
    BillingPlan,
    BillingQuota,
    BillingTopUp,
    ComplianceClause,
    DataDict,
    DictItem,
    EvalRun,
    EvalSet,
    ModelConfig,
    ModelGatewayRecord,
    Notification,
    Project,
    ProjectMembers,
    Report,
    ReportComplianceAlignment,
    Scenario,
    SystemUser,
    TaskArtifact,
    TaskStep,
    TestCase,
    TestDataset,
    TestEngine,
    TestTask,
)
from ..schemas import (
    CaseCreate,
    CaseOut,
    CaseUpdate,
    DatasetCreate,
    DatasetGenerateRequest,
    DatasetOut,
    EvalRunCreate,
    EvalRunOut,
    EvalSetCreate,
    EngineOut,
    ModelConfigCreate,
    ModelConfigTestRequest,
    ModelConfigUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    ScenarioCreate,
    StepOut,
    TaskCreate,
    TaskOut,
    TaskRunRequest,
    VALID_CASE_CATEGORIES,
)
from ..services.llm_client import test_connection as llm_test_connection
from ..services.scheduler import next_run_at
from ..services.task_runner import is_running, launch_task_async
from ..utils.compat import run_cmd
from ..utils.cron import parse_cron
from ..utils.no import gen_no


router = APIRouter()
from . import evals_core
from ._business_common import *  # noqa: F401,F403

# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------
@router.get("/cases", response_model=dict)
async def list_cases(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    project_id: int | None = None,
    category: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    module: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    q = db.query(TestCase).filter(TestCase.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(TestCase.tenant_id == auth.tenant_id)
    if project_id:
        q = q.filter(TestCase.project_id == project_id)
    if category:
        q = q.filter(TestCase.category == category)
    if severity:
        q = q.filter(TestCase.severity == severity)
    if status:
        q = q.filter(TestCase.status == status)
    if module:
        q = q.filter(TestCase.module == module)
    if keyword:
        q = q.filter(TestCase.title.ilike(f"%{keyword}%"))
    total = q.count()
    rows = (
        q.order_by(TestCase.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [CaseOut.model_validate(c).model_dump() for c in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@router.post("/cases", response_model=dict)
async def create_case(
    body: CaseCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("case", "create")),
):
    p = db.get(Project, body.project_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")
    if body.category not in VALID_CASE_CATEGORIES:
        raise BizError(
            "ES-BIZ-0016",
            f"非法用例类别 {body.category!r}（合法：{sorted(VALID_CASE_CATEGORIES)}）",
        )
    check_limit("cases_total", db, auth, n=1)  # B5 社区版用例总量
    c = TestCase(
        case_no=gen_no("C"),
        project_id=body.project_id,
        dataset_id=body.dataset_id,
        title=body.title,
        module=body.module,
        category=body.category,
        source=body.source,
        severity=body.severity,
        priority=body.priority,
        precondition=body.precondition,
        steps=body.steps,
        expected=body.expected,
        request_spec=body.request_spec,
        tags=body.tags,
        content_schema=_plain_json(body.content_schema),
        preconditions=_plain_json(body.preconditions),
        test_data=_plain_json(body.test_data),
        assertions=_plain_json(body.assertions),
        extract_vars=_plain_json(body.extract_vars),
        post_cleanup=_plain_json(body.post_cleanup),
        requirement_id=body.requirement_id,
        owner_id=auth.user_id,
        creator=auth.username,
        tenant_id=auth.tenant_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"code": 0, "message": "ok", "data": CaseOut.model_validate(c).model_dump()}


@router.get("/cases/{case_id}", response_model=dict)
async def get_case(
    case_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """获取单条测试用例详情（Assets 页编辑时调用）。"""
    c = db.get(TestCase, case_id)
    if c is None or c.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0006", "用例不存在")
    await ensure_data_scope(auth, resource_tenant_id=c.tenant_id)
    return {"code": 0, "message": "ok", "data": CaseOut.model_validate(c).model_dump()}


@router.put("/cases/{case_id}", response_model=dict)
async def update_case(
    case_id: int,
    body: CaseUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    c = db.get(TestCase, case_id)
    if c is None or c.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0006", "用例不存在")
    await ensure_data_scope(auth, resource_tenant_id=c.tenant_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, _plain_json(v))
    c.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.delete("/cases/{case_id}", response_model=dict)
async def delete_case(
    case_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    c = db.get(TestCase, case_id)
    if c is None or c.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0006", "用例不存在")
    await ensure_data_scope(auth, resource_tenant_id=c.tenant_id)
    c.deleted_at = datetime.now(timezone.utc)
    c.status = "ARCHIVED"
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.post("/cases/batch-delete", response_model=dict)
async def batch_delete_cases(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """D-DEL-02：批量删除用例（软删 + 置 ARCHIVED）。"""
    ids = [int(x) for x in (body.get("ids") or [])]
    if not ids:
        return {"code": 0, "message": "ok", "data": {"deleted": 0, "skipped": 0, "not_found": []}}
    now = datetime.now(timezone.utc)
    deleted = skipped = 0
    not_found: list[int] = []
    for cid in ids:
        c = db.get(TestCase, cid)
        if c is None or c.deleted_at is not None:
            not_found.append(cid); continue
        if c.tenant_id != auth.tenant_id:
            skipped += 1; continue
        c.deleted_at = now; c.status = "ARCHIVED"; deleted += 1
    db.commit()
    return {"code": 0, "message": "ok",
            "data": {"deleted": deleted, "skipped": skipped, "not_found": not_found}}


# ---------------------------------------------------------------------------
# 资产中心统计（合计 / 按类别分布）与用例批量导入
# ---------------------------------------------------------------------------
@router.get("/assets/stats", response_model=dict)
async def asset_center_stats(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """资产中心概览：用例/数据集/场景总数 + 用例按类别分布（受租户范围约束）。"""
    q_case = db.query(TestCase).filter(TestCase.deleted_at.is_(None))
    q_dataset = db.query(TestDataset).filter(TestDataset.deleted_at.is_(None))
    q_scenario = db.query(Scenario).filter(Scenario.deleted_at.is_(None))
    q_eval_set = db.query(EvalSet).filter(EvalSet.deleted_at.is_(None))
    q_cat = db.query(TestCase.category, func.count(TestCase.id)).filter(TestCase.deleted_at.is_(None))
    if not auth.is_super_admin:
        q_case = q_case.filter(TestCase.tenant_id == auth.tenant_id)
        q_dataset = q_dataset.filter(TestDataset.tenant_id == auth.tenant_id)
        q_scenario = q_scenario.filter(Scenario.tenant_id == auth.tenant_id)
        q_eval_set = q_eval_set.filter(EvalSet.tenant_id == auth.tenant_id)
        q_cat = q_cat.filter(TestCase.tenant_id == auth.tenant_id)
    by_category = {k: v for k, v in q_cat.group_by(TestCase.category).all()}
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "cases": {"total": q_case.count(), "by_category": by_category},
            "datasets": {"total": q_dataset.count()},
            "scenarios": {"total": q_scenario.count()},
            "eval_sets": {"total": q_eval_set.count()},
        },
    }


@router.get("/assets/coverage", response_model=dict)
async def asset_coverage(
    project_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """AI 测试优化 B9：测试人员视角的功能覆盖矩阵。

    按 module 聚合用例/数据集/场景/评测集数量与用例通过率；
    模块同时拥有 用例≥1 且 数据集≥1 且 场景≥1 判定为 covered，否则进入 uncovered。
    """
    tc = db.query(TestCase).filter(TestCase.project_id == project_id, TestCase.deleted_at.is_(None))
    td = db.query(TestDataset).filter(TestDataset.project_id == project_id, TestDataset.deleted_at.is_(None))
    sc = db.query(Scenario).filter(Scenario.project_id == project_id, Scenario.deleted_at.is_(None))
    es = db.query(EvalSet).filter(EvalSet.project_id == project_id, EvalSet.deleted_at.is_(None))
    if not auth.is_super_admin:
        tc = tc.filter(TestCase.tenant_id == auth.tenant_id)
        td = td.filter(TestDataset.tenant_id == auth.tenant_id)
        sc = sc.filter(Scenario.tenant_id == auth.tenant_id)
        es = es.filter(EvalSet.tenant_id == auth.tenant_id)

    agg: dict[str, dict] = {}
    for c in tc.all():
        m = c.module or "未分类"
        row = agg.setdefault(m, _cov_row(m))
        row["case_count"] += 1
        row["run_count"] += c.run_count or 0
        row["pass_rate"] += (c.pass_rate or 0.0)
    # 数据集无 module 列，按名称尝试对齐已生成的模块（否则归入未分类）
    module_names = [a for a in agg]
    for d in td.all():
        m = _dataset_module_from_name(d.name or "", module_names)
        agg.setdefault(m, _cov_row(m))["dataset_count"] += 1
    for s in sc.all():
        m = s.module or "未分类"
        agg.setdefault(m, _cov_row(m))["scenario_count"] += 1
    for e in es.all():
        m = e.module or "未分类"
        agg.setdefault(m, _cov_row(m))["eval_set_count"] += 1
    modules = [r for r in agg.values()]
    for r in modules:
        if r["case_count"]:
            r["pass_rate"] = round(r["pass_rate"] / r["case_count"], 4)
        r["covered"] = r["case_count"] >= 1 and r["dataset_count"] >= 1 and r["scenario_count"] >= 1
    uncovered = [r for r in modules if not r["covered"]]
    return {"code": 0, "message": "ok", "data": {"modules": modules, "uncovered": uncovered}}


@router.post("/scenarios/{scenario_id}/run", response_model=dict)
async def run_scenario(
    scenario_id: int,
    body: dict | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("task", "create")),
):
    """AI 测试优化 B14：场景独立执行入口（DATAFLOW_TEST 引擎）。

    把场景步骤（request/extract/assert/delay/db_query）映射为引擎可识别的
    HTTP 步骤链（http/sleep），附于 config.scenario_steps 供引擎直接读取，
    从而避免依赖任务运行器对 scenario_ids 的转发（运行器暂未实现该转发）。
    """
    s = db.get(Scenario, scenario_id)
    if s is None or s.deleted_at is not None:
        raise NotFoundError("ES-COMMON-0004", "场景不存在")
    if s.tenant_id != auth.tenant_id and not auth.is_super_admin:
        raise BizError("ES-DATA-0001", "无权操作该场景")
    from ..models import TestTask, TestEnvironment
    base_url = (body or {}).get("base_url")
    if not base_url:
        env = db.query(TestEnvironment).filter(
            TestEnvironment.project_id == s.project_id, TestEnvironment.is_default.is_(True)
        ).first()
        base_url = env.base_url if env else ""
    # FE-05：base_url 空串兜底（前端必填 + 后端兜底校验）
    if not str(base_url or "").strip():
        raise BizError("ES-BIZ-0014", "被测系统地址（base_url）不能为空，请先配置默认被测环境或手动填写")
    engine_steps = _scenario_steps_to_engine(s.steps)
    # B5 社区版单任务被测系统上限（场景数即目标数）
    check_limit("targets_per_task", db, auth, scenario_targets=1)
    task = TestTask(
        task_no=gen_no("TSK"),
        project_id=s.project_id,
        name=f"场景执行 {s.name}",
        task_type="数据流",
        engines=["DATAFLOW_TEST"],
        config={
            "base_url": base_url,
            "scenario_ids": [s.id],
            "scenario_steps": engine_steps,
            "variables": s.variables or {},
        },
        status="PENDING",
        trigger_mode="MANUAL",
        created_by=auth.user_id,
        tenant_id=auth.tenant_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    from ..services.task_runner import launch_task_async
    launch_task_async(task.id, engines=["DATAFLOW_TEST"], config=task.config)
    return {"code": 0, "message": "ok", "data": {"task_no": task.task_no, "task_id": task.id}}


@router.post("/cases/bulk", response_model=dict)
async def bulk_create_cases(
    body: _CaseBulkCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """用例批量导入：一次创建多条用例（跳过非法行并生成编号）。"""
    check_limit("cases_total", db, auth, n=len(body.items or []))  # B5 社区版用例总量
    created = []
    failures = []
    for idx, ci in enumerate(body.items or []):
        p = db.get(Project, ci.project_id)
        if p is None or p.deleted_at is not None:
            failures.append({"index": idx, "title": ci.title, "reason": "项目不存在"})
            continue
        if ci.category not in VALID_CASE_CATEGORIES:
            failures.append({"index": idx, "title": ci.title, "reason": f"非法类别 {ci.category!r}（合法：{sorted(VALID_CASE_CATEGORIES)}）"})
            continue
        c = TestCase(
            case_no=gen_no("C"),
            project_id=ci.project_id,
            dataset_id=ci.dataset_id,
            title=ci.title,
            module=ci.module,
            category=ci.category,
            source=ci.source,
            severity=ci.severity,
            priority=ci.priority,
            precondition=ci.precondition,
            steps=ci.steps,
            expected=ci.expected,
            request_spec=ci.request_spec,
            tags=ci.tags,
            content_schema=_plain_json(ci.content_schema),
            preconditions=_plain_json(ci.preconditions),
            test_data=_plain_json(ci.test_data),
            assertions=_plain_json(ci.assertions),
            extract_vars=_plain_json(ci.extract_vars),
            post_cleanup=_plain_json(ci.post_cleanup),
            requirement_id=ci.requirement_id,
            owner_id=auth.user_id,
            creator=auth.username,
            tenant_id=auth.tenant_id,
        )
        created.append(c)
    if created:
        db.add_all(created)
        db.commit()
        for c in created:
            db.refresh(c)
    # 若有失败条目，返回 code != 0 + failures 数组
    code = 0 if not failures else 1
    msg = "ok" if not failures else f"部分失败（{len(failures)} 条失败，{len(created)} 条成功）"
    return {
        "code": code,
        "message": msg,
        "data": {
            "created": len(created),
            "ids": [c.id for c in created],
            "failures": failures,
        },
    }


# ---------------------------------------------------------------------------
# 数据集
# ---------------------------------------------------------------------------
@router.get("/datasets", response_model=dict)
async def list_datasets(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    project_id: int | None = None,
    category: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    q = db.query(TestDataset).filter(TestDataset.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(TestDataset.tenant_id == auth.tenant_id)
    if project_id:
        q = q.filter(TestDataset.project_id == project_id)
    if category:
        q = q.filter(TestDataset.category == category)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(TestDataset.name.ilike(like) | TestDataset.code.ilike(like))
    total = q.count()
    rows = (
        q.order_by(TestDataset.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [DatasetOut.model_validate(d).model_dump() for d in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@router.post("/datasets", response_model=dict)
async def create_dataset(
    body: DatasetCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    d = TestDataset(
        code=gen_no("DS"),
        project_id=body.project_id,
        name=body.name,
        category=body.category,
        description=body.description,
        case_ids=body.case_ids,
        case_count=len(body.case_ids or []),
        parameters=body.parameters or [],
        data_rows=body.data_rows or [],
        source=body.source,
        visibility=body.visibility,
        created_by=auth.user_id,
        tenant_id=auth.tenant_id,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return {
        "code": 0,
        "message": "ok",
        "data": DatasetOut.model_validate(d).model_dump(),
    }


@router.delete("/datasets/{dataset_id}", response_model=dict)
async def delete_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    d = db.get(TestDataset, dataset_id)
    if d is None or d.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0007", "数据集不存在")
    await ensure_data_scope(auth, resource_tenant_id=d.tenant_id)
    d.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.post("/datasets/batch-delete", response_model=dict)
async def batch_delete_datasets(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """D-DEL-03：批量删除数据集（软删）。"""
    ids = [int(x) for x in (body.get("ids") or [])]
    if not ids:
        return {"code": 0, "message": "ok", "data": {"deleted": 0, "skipped": 0, "not_found": []}}
    now = datetime.now(timezone.utc)
    deleted = skipped = 0
    not_found: list[int] = []
    for did in ids:
        d = db.get(TestDataset, did)
        if d is None or d.deleted_at is not None:
            not_found.append(did); continue
        if d.tenant_id != auth.tenant_id:
            skipped += 1; continue
        d.deleted_at = now; deleted += 1
    db.commit()
    return {"code": 0, "message": "ok",
            "data": {"deleted": deleted, "skipped": skipped, "not_found": not_found}}


# ---------------------------------------------------------------------------
# 场景（数据流）
# ---------------------------------------------------------------------------
@router.get("/scenarios", response_model=dict)
async def list_scenarios(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    project_id: int | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """测试场景列表（标准分页格式，与 cases/datasets 保持一致）。"""
    q = db.query(Scenario).filter(Scenario.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(Scenario.tenant_id == auth.tenant_id)
    if project_id:
        q = q.filter(Scenario.project_id == project_id)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(Scenario.name.ilike(like) | Scenario.description.ilike(like))
    total = q.count()
    rows = (
        q.order_by(Scenario.id.desc())
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
                    "project_id": s.project_id,
                    "name": s.name,
                    "description": s.description,
                    "module": s.module,
                    "source": s.source,
                    "steps_count": len(s.steps or []),
                    "visibility": s.visibility,
                    "created_at": s.created_at,
                }
                for s in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@router.post("/scenarios", response_model=dict)
async def create_scenario(
    body: ScenarioCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    # P2-08：保存前编译期校验（if/loop/parallel 合法性 + 嵌套深度），非法 → ES-BIZ-0015
    _scenario_steps_to_engine(body.steps or [])
    s = Scenario(
        code=gen_no("SCN"),
        project_id=body.project_id,
        name=body.name,
        description=body.description,
        steps=body.steps,
        variables=body.variables,
        data_sources=body.data_sources,
        visibility=body.visibility,
        module=body.module,
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
            "module": s.module,
            "steps": s.steps,
            "variables": s.variables,
            "data_sources": s.data_sources,
        },
    }


@router.post("/scenarios/import-recording", response_model=dict)
async def import_scenario_recording(
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """P2-08：Playwright 录制导入 → 数据流场景（source=UI_RECORD）。

    请求体：{project_id, name?, module?, description?, actions:[...]}，actions 亦可为
    形如 {"actions":[...]} 的对象。未识别动作 → 记入 warnings 返回，不阻断入库。
    """
    project_id = body.get("project_id")
    if not project_id:
        raise _scenario_err("导入录制必须指定 project_id")
    p = db.get(Project, project_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")
    await ensure_data_scope(auth, resource_tenant_id=p.tenant_id)

    actions = body.get("actions")
    if isinstance(actions, dict):
        actions = actions.get("actions")
    if not isinstance(actions, list) or not actions:
        raise _scenario_err("录制内容为空或格式非法（应为动作数组）")

    steps, warnings = _recording_actions_to_steps(actions)
    if not steps:
        raise _scenario_err("录制内容未包含可映射的动作（支持 goto/click/fill/expect）")

    name = str(body.get("name") or "").strip() or f"UI 录制导入 {datetime.now().strftime('%Y%m%d%H%M%S')}"
    s = Scenario(
        code=gen_no("SCN"),
        project_id=project_id,
        name=name[:128],
        description=body.get("description"),
        module=body.get("module"),
        steps=steps,
        variables=body.get("variables") if isinstance(body.get("variables"), dict) else {},
        source="UI_RECORD",
        visibility=body.get("visibility") or "PRIVATE",
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
            "id": s.id, "code": s.code, "name": s.name, "source": s.source,
            "steps": s.steps, "step_count": len(steps), "warnings": warnings,
        },
    }


# ---------------------------------------------------------------------------
# 评测集 / 评测运行（BUG-006 拆分至 evals_core.router，原位聚合保持注册顺序）
# ---------------------------------------------------------------------------
router.include_router(evals_core.router)


# ---------------------------------------------------------------------------
# 场景（补：详情 / 编辑 / 删除）
# ---------------------------------------------------------------------------
@router.get("/scenarios/{scenario_id}", response_model=dict)
async def get_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    s = db.get(Scenario, scenario_id)
    if s is None or s.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0017", "场景不存在")
    await ensure_data_scope(auth, resource_tenant_id=s.tenant_id)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "id": s.id,
            "code": s.code,
            "project_id": s.project_id,
            "name": s.name,
            "description": s.description,
            "module": s.module,
            "steps": s.steps,
            "variables": s.variables,
            "data_sources": s.data_sources,
            "visibility": s.visibility,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        },
    }


@router.put("/scenarios/{scenario_id}", response_model=dict)
async def update_scenario(
    scenario_id: int,
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    s = db.get(Scenario, scenario_id)
    if s is None or s.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0017", "场景不存在")
    await ensure_data_scope(auth, resource_tenant_id=s.tenant_id)
    updatable = ("name", "description", "steps", "variables", "data_sources", "visibility", "module")
    # P2-08：步骤变更时先做编译期校验，非法 → ES-BIZ-0015（不落库）
    if body.get("steps") is not None:
        _scenario_steps_to_engine(body.get("steps") or [])
    changed = False
    for k in updatable:
        v = body.get(k)
        if v is not None:
            setattr(s, k, v)
            changed = True
    if changed:
        s.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(s)
    return await get_scenario(scenario_id, db, auth)


@router.delete("/scenarios/{scenario_id}", response_model=dict)
async def delete_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    s = db.get(Scenario, scenario_id)
    if s is None or s.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0017", "场景不存在")
    await ensure_data_scope(auth, resource_tenant_id=s.tenant_id)
    s.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.post("/scenarios/batch-delete", response_model=dict)
async def batch_delete_scenarios(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """D-DEL-04：批量删除场景（软删）。"""
    ids = [int(x) for x in (body.get("ids") or [])]
    if not ids:
        return {"code": 0, "message": "ok", "data": {"deleted": 0, "skipped": 0, "not_found": []}}
    now = datetime.now(timezone.utc)
    deleted = skipped = 0
    not_found: list[int] = []
    for sid in ids:
        s = db.get(Scenario, sid)
        if s is None or s.deleted_at is not None:
            not_found.append(sid); continue
        if s.tenant_id != auth.tenant_id:
            skipped += 1; continue
        s.deleted_at = now; deleted += 1
    db.commit()
    return {"code": 0, "message": "ok",
            "data": {"deleted": deleted, "skipped": skipped, "not_found": not_found}}


# ---------------------------------------------------------------------------
# 数据集（补：详情 / 编辑）
# ---------------------------------------------------------------------------
@router.get("/datasets/{dataset_id}", response_model=dict)
async def get_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    d = db.get(TestDataset, dataset_id)
    if d is None or d.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0007", "数据集不存在")
    await ensure_data_scope(auth, resource_tenant_id=d.tenant_id)
    # 可选：联查 case 标题列表返回 cases_summary（非必需，但有用）
    cases_summary = []
    if d.case_ids:
        cs = (
            db.query(TestCase.id, TestCase.title)
            .filter(TestCase.id.in_(d.case_ids), TestCase.deleted_at.is_(None))
            .all()
        )
        cases_summary = [{"id": cid, "title": title} for cid, title in cs]
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "id": d.id,
            "code": d.code,
            "project_id": d.project_id,
            "name": d.name,
            "category": d.category,
            "description": d.description,
            "case_ids": d.case_ids,
            "case_count": d.case_count,
            "parameters": d.parameters or [],
            "data_rows": d.data_rows or [],
            "visibility": d.visibility,
            "source": d.source,
            "meta": d.meta,
            "cases_summary": cases_summary,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
        },
    }


@router.put("/datasets/{dataset_id}", response_model=dict)
async def update_dataset(
    dataset_id: int,
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    d = db.get(TestDataset, dataset_id)
    if d is None or d.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0007", "数据集不存在")
    await ensure_data_scope(auth, resource_tenant_id=d.tenant_id)
    updatable = ("name", "description", "category", "case_ids", "parameters", "data_rows", "visibility", "source")
    changed = False
    for k in updatable:
        v = body.get(k)
        if v is not None:
            setattr(d, k, v)
            changed = True
    # 重算 case_count
    if body.get("case_ids") is not None:
        d.case_count = len(body.get("case_ids") or [])
        changed = True
    if changed:
        d.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(d)
    return await get_dataset(dataset_id, db, auth)


# ---------------------------------------------------------------------------
# 评测集/评测运行（补：详情 / 编辑 / 删除，BUG-006 拆分至 evals_core.extra_router）
# ---------------------------------------------------------------------------
router.include_router(evals_core.extra_router)


# ===========================================================================
# P2-5 AI 生成数据集 + P2-6 AI 断言补全（2026-09-29）
# ===========================================================================

@router.post("/datasets/generate", response_model=dict)
async def ai_generate_dataset(
    body: "DatasetGenerateRequest",  # 字符串前向引用避免循环导入
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """P2-5：根据业务描述生成参数列 + 数据行（优先 LLM，兜底规则）。"""
    from ..schemas import DatasetGenerateRequest as _DGR
    if not isinstance(body, _DGR):
        body = _DGR.model_validate(body.model_dump())
    p = db.get(Project, body.project_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")
    # 校验 category 合法性（与 TestCase/EvalSet 保持一致）
    from ..schemas import VALID_CASE_CATEGORIES
    if body.category not in VALID_CASE_CATEGORIES:
        raise BizError(
            "ES-BIZ-0016",
            f"非法数据集类别 {body.category!r}（合法：{sorted(VALID_CASE_CATEGORIES)}）",
        )
    # B5 社区版 AI 生成：每日次数（通过后即累加）+ 单次条数上限
    check_limit("case_gen_per_day", db, auth)
    check_limit("case_gen_per_call", db, auth, n=3)

    # 兜底规则：从 prompt 中提取典型参数名 + 真实业务示例值（产品视角：数据集要真实可执行）
    prompt_lower = body.prompt.lower()
    parameters = []
    data_rows = []

    # 常见业务场景参数模板：命中即用真实示例值，不命中再走关键词兜底
    # 同时支持中文别名（产品视角：业务描述多为中文，如"手机号邮箱"）
    common_params = [
        ("username", "string", "admin", ["username", "用户名", "账号", "帐号", "登录名"]),
        ("password", "string", "Passw0rd!a", ["password", "密码", "口令"]),
        ("phone", "string", "13800138000", ["phone", "手机号", "手机", "电话", "手机号码"]),
        ("email", "string", "zhang.san@example.com", ["email", "邮箱", "邮件"]),
        ("user_id", "string", "U1001", ["user_id", "用户id", "用户编号"]),
        ("order_id", "string", "SO20261003-001", ["order_id", "订单id", "订单号", "订单编号"]),
        ("amount", "number", "299.99", ["amount", "金额", "价格", "价钱"]),
        ("keyword", "string", "订单查询", ["keyword", "关键词", "关键字", "搜索词"]),
        ("title", "string", "发布新版本说明", ["title", "标题", "名称", "主题"]),
        ("status", "string", "ACTIVE", ["status", "状态"]),
        ("remark", "string", "验证通过后归档", ["remark", "备注", "说明", "描述"]),
        ("version", "string", "v1.2.0", ["version", "版本", "版本号"]),
    ]
    for name, typ, ex, aliases in common_params:
        if any(a in prompt_lower for a in aliases):
            parameters.append({"name": name, "type": typ, "example": ex})
    if not parameters:
        # 没命中关键词：用 prompt 最后一个业务词做兜底参数，示例值从 prompt 取
        parameters.append({"name": "keyword", "type": "string", "example": body.prompt[:12]})

    # 生成 3 条真实语义数据行：每条按参数类型给出接近真实的值（不再用 v1/v2 占位）
    for i in range(3):
        row = {}
        for p_ in parameters:
            name, typ, ex = p_["name"], p_["type"], p_["example"]
            if typ == "number":
                # 数值型：在示例值附近生成合理递增/递减
                try:
                    base = float(ex)
                    row[name] = round(base + (i - 1) * (base / 10 or 1), 2)
                except (TypeError, ValueError):
                    row[name] = str(i + 1)
            elif name == "phone":
                row[name] = f"138{str(10000000 + i * 11111)}"
            elif name == "email":
                row[name] = f"user{['zhangsan', 'lisi', 'wangwu'][i]}@example.com"
            elif name == "user_id":
                row[name] = f"U{1001 + i}"
            elif name == "order_id":
                row[name] = f"SO20261003-{str(i + 1).zfill(3)}"
            elif name == "username":
                row[name] = ["zhangsan", "lisi", "wangwu"][i]
            elif name == "password":
                row[name] = "Passw0rd!a"
            else:
                # 字符串兜底：示例值 + 序号（业务语义弱化的最小后缀）
                row[name] = f"{ex} {i + 1}" if not str(ex).endswith(str(i + 1)) else str(ex)
        data_rows.append(row)

    # 落库（source=AI_GEN）
    d = TestDataset(
        code=gen_no("DS"),
        project_id=body.project_id,
        name=f"{body.prompt[:20]}数据集",
        category=body.category,
        description=f"AI 自动生成（业务描述: {body.prompt[:100]}）· 参数 {len(parameters)} 列 / 数据 {len(data_rows)} 行",
        parameters=parameters,
        data_rows=data_rows,
        source="AI_GEN",
        visibility="PRIVATE",
        created_by=auth.user_id,
        tenant_id=auth.tenant_id,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return {
        "code": 0, "message": "ok",
        "data": {
            "dataset_id": d.id, "code": d.code, "name": d.name,
            "parameters": parameters, "data_rows": data_rows,
            "source": d.source,
        },
    }


@router.post("/cases/{case_id}/complete-assertions", response_model=dict)
async def ai_complete_assertions(
    case_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """P2-6：AI 断言补全（优先 LLM，兜底规则）。返回候选断言列表。"""
    c = db.get(TestCase, case_id)
    if c is None or c.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0006", "用例不存在")
    await ensure_data_scope(auth, resource_tenant_id=c.tenant_id)
    if c.assertions:
        return {"code": 0, "message": "ok", "data": {"has_existing": True, "assertions": c.assertions}}
    check_limit("case_gen_per_day", db, auth)  # B5 社区版 AI 生成每日次数
    # 规则兜底：基于 request_spec.method + last_actual 生成基础断言
    candidates = []
    spec = c.request_spec or {}
    last_actual = c.last_actual or {}
    method = (spec.get("method") or "GET").upper()
    candidates.append({"path": "status_code", "op": "eq", "expected": 200})
    if "POST" == method:
        candidates.append({"path": "$.code", "op": "eq", "expected": 0})
    candidates.append({"path": "$.message", "op": "notNull"})
    # 若有 last_actual，把实际值作为参考
    try:
        actual_values = set()
        for k, v in (last_actual or {}).items():
            if isinstance(v, dict) and v.get("actual") is not None:
                actual_values.add(str(v["actual"]))
    except Exception:
        actual_values = set()
    return {
        "code": 0, "message": "ok",
        "data": {
            "case_id": case_id,
            "candidates": candidates,
            "actual_hints": sorted(list(actual_values))[:5],
            "tip": "勾选后保存即可写入 assertions 字段",
        },
    }


