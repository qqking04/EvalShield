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
from sqlalchemy import String, case, cast, func, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..config import settings
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
from ..limits import check_limit
from ..services.audit import write_audit
from ..services.quality_gate import validate_gate_rules
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
    ProjectVersion,
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
from ._business_common import *  # noqa: F401,F403

# ---------------------------------------------------------------------------
# 仪表盘统计
# ---------------------------------------------------------------------------
@router.get("/dashboard/stats", response_model=dict)
async def dashboard_stats(
    db: Session = Depends(get_db), auth: AuthContext = Depends(authenticate_request)
):
    """租户级统计：项目/任务/通过率/最近执行。"""
    is_super = auth.is_super_admin
    project_q = db.query(func.count(Project.id)).filter(Project.deleted_at.is_(None))
    if not is_super:
        project_q = project_q.filter(Project.tenant_id == auth.tenant_id)
    project_total = project_q.scalar() or 0

    task_total_q = db.query(func.count(TestTask.id)).filter(TestTask.deleted_at.is_(None))
    if not is_super:
        task_total_q = task_total_q.filter(TestTask.tenant_id == auth.tenant_id)
    task_total = task_total_q.scalar() or 0

    task_running_q = db.query(func.count(TestTask.id)).filter(TestTask.status == "RUNNING")
    if not is_super:
        task_running_q = task_running_q.filter(TestTask.tenant_id == auth.tenant_id)
    task_running = task_running_q.scalar() or 0

    task_success_q = db.query(func.count(TestTask.id)).filter(TestTask.status == "SUCCESS")
    if not is_super:
        task_success_q = task_success_q.filter(TestTask.tenant_id == auth.tenant_id)
    task_success = task_success_q.scalar() or 0

    case_total_q = db.query(func.count(TestCase.id)).filter(TestCase.deleted_at.is_(None))
    if not is_super:
        case_total_q = case_total_q.filter(TestCase.tenant_id == auth.tenant_id)
    case_total = case_total_q.scalar() or 0

    recent_q = db.query(TestTask).filter(TestTask.deleted_at.is_(None))
    if not is_super:
        recent_q = recent_q.filter(TestTask.tenant_id == auth.tenant_id)
    recent = recent_q.order_by(TestTask.id.desc()).limit(5).all()
    recent_items = [TaskOut.model_validate(t).model_dump() for t in recent]

    # 引擎类型分布
    engine_stats = []
    engines = db.query(TestEngine).filter(TestEngine.status == "ENABLED").all()
    by_type: dict[str, int] = {}
    for e in engines:
        by_type[e.engine_type] = by_type.get(e.engine_type, 0) + 1
    engine_stats = [{"engine_type": k, "count": v} for k, v in sorted(by_type.items())]

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "project_total": project_total,
            "task_total": task_total,
            "task_running": task_running,
            "task_success": task_success,
            "case_total": case_total,
            "recent_tasks": recent_items,
            "engine_stats": engine_stats,
        },
    }


@router.get("/dashboard/trend", response_model=dict)
async def dashboard_trend(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db), auth: AuthContext = Depends(authenticate_request)
):
    """过去 N 天的任务/通过率趋势（每天一个数据点）。"""
    from datetime import datetime, timedelta
    is_super = auth.is_super_admin
    points = []
    for i in range(days - 1, -1, -1):
        day = (datetime.utcnow() - timedelta(days=i)).date()
        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)
        q = db.query(TestTask).filter(
            TestTask.deleted_at.is_(None),
            TestTask.created_at >= start, TestTask.created_at < end,
        )
        if not is_super:
            q = q.filter(TestTask.tenant_id == auth.tenant_id)
        total = q.count()
        success = q.filter(TestTask.status == "SUCCESS").count()
        points.append({
            "date": day.isoformat(),
            "tasks": total,
            "success": success,
            "pass_rate": round(success / total * 100, 1) if total > 0 else 0.0,
        })
    return {"code": 0, "message": "ok", "data": points}


# ---------------------------------------------------------------------------
# 引擎列表（公开给任务编排选择）
# ---------------------------------------------------------------------------
@router.get("/engine-options", response_model=dict)
async def engine_options(db: Session = Depends(get_db)):
    discover_engines()
    meta = engine_registry.meta_list()
    # 与数据库注册表合并
    db_engines = db.query(TestEngine).filter(TestEngine.status == "ENABLED").all()
    if db_engines:
        codes = {m["engine_code"] for m in meta}
        for e in db_engines:
            if e.engine_code not in codes:
                # 社区形态：仅展示内存注册表（12 社区引擎），
                # 不合并 DB 存量行（同库商业形态 seed 的商业引擎行会泄露）
                if settings.EDITION == "community":
                    continue
                meta.append(
                    {
                        "engine_code": e.engine_code,
                        "engine_name": e.engine_name,
                        "engine_type": e.engine_type,
                        "category": e.category,
                        "version": e.version,
                        "description": e.description or "",
                    }
                )
    return {"code": 0, "message": "ok", "data": meta}


# ---------------------------------------------------------------------------
# 任务：创建 / 列表 / 详情 / 执行 / 取消 / 历史
# ---------------------------------------------------------------------------
@router.get("/tasks", response_model=dict)
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    project_id: int | None = None,
    project_version_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    q = db.query(TestTask).filter(TestTask.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(TestTask.tenant_id == auth.tenant_id)
    if project_id:
        q = q.filter(TestTask.project_id == project_id)
    if project_version_id:
        # ES10-P-02 §9.2.4：双口径——新任务走归因列，存量任务回退 task_version 字符串
        v = db.get(ProjectVersion, project_version_id)
        q = q.filter(
            or_(
                TestTask.project_version_id == project_version_id,
                TestTask.task_version == (v.version_no if v else ""),
            )
        )
    if status:
        q = q.filter(TestTask.status == status)
    if keyword:
        q = q.filter(TestTask.name.ilike(f"%{keyword}%"))
    total = q.count()
    rows = (
        q.order_by(TestTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = []
    for t in rows:
        row = TaskOut.model_validate(t).model_dump()
        row["next_run_at"] = next_run_at(t)
        items.append(row)
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


@router.post("/tasks/estimate-cost", response_model=dict)
async def estimate_task_cost(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """v2.0 P6 / 开发方案§7.1：任务成本预估（契约端点）。

    入参 {engine_code, eval_set_id?, eval_set_code?, judge_model?, concurrency?}；
    返回 data.cost_yuan / data.duration_min（方案契约字段名），
    并附 estimated_cost / estimated_minutes 别名保持与 /eval-runs/estimate 一致。
    """
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
    judge_model = body.get("judge_model")
    if not judge_model:
        from ..services.engine_llm import resolve_model_config

        _default = resolve_model_config(db, {}, tenant_id=auth.tenant_id)
        judge_model = (_default or {}).get("code")
    cost = _estimate_run_cost(db, engine_code, judge_model, calls)
    conc = max(1, int(body.get("concurrency") or 2))
    duration_min = round(calls * 2 / conc / 60, 1)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "item_count": item_count,
            "calls": calls,
            "cost_yuan": cost,
            "duration_min": duration_min,
            "estimated_cost": cost,
            "estimated_minutes": duration_min,
        },
    }


@router.post("/tasks", response_model=dict)
async def create_task(
    body: TaskCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("task", "create")),
):
    p = db.get(Project, body.project_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")
    await ensure_data_scope(auth, resource_tenant_id=p.tenant_id)

    # 配额拦截 — P2-QUOTA
    from ..models import BillingQuota
    quota = db.query(BillingQuota).filter(BillingQuota.tenant_id == auth.tenant_id).first()
    if quota and quota.task_quota is not None and quota.task_quota <= 0:
        raise BizError("ES-BIZ-QUOTA-001", "测试任务配额已耗尽，请联系管理员升级计划")

    if body.trigger_mode == "SCHEDULED":
        if not body.schedule_cron:
            raise BizError("ES-BIZ-0012", "定时模式必须填写 cron 表达式")
        if parse_cron(body.schedule_cron) is None:
            raise BizError(
                "ES-BIZ-0013", "cron 表达式格式错误（应为5段：分 时 日 月 周）"
            )
        # B7：社区版定时/批量回归关闭
        check_limit("scheduler", db, auth)
    await ensure_data_scope(
        auth,
        resource_tenant_id=p.tenant_id,
        visibility=p.visibility,
        owner_user_id=p.owner_id,
    )

    discover_engines()
    available = engine_registry.codes()
    for e in body.engines:
        if e not in available:
            raise BizError("ES-BIZ-0003", f"引擎 {e} 未注册或不可用")

    # 若传 env_id 合并进 config
    final_config = dict(body.config or {})
    if body.env_id:
        final_config["env_id"] = body.env_id

    # 优化12 §4.1a：引擎轨 activity_id 白名单校验（归一化 + 非法即 422）
    act = final_config.get("activity_id")
    if act is not None:
        try:
            final_config["activity_id"] = str(uuid.UUID(str(act)))
        except ValueError:
            raise BizError("ES-BIZ-PARAM-0001", "config.activity_id 不是合法 UUID",
                           http_status=422)

    # FE-02：base_url 空串兜底（前端必填 + 后端兜底校验），HTTP 类引擎禁止空串提交
    if any(e in _HTTP_BASED_ENGINES for e in body.engines) and "base_url" in final_config:
        if not str(final_config.get("base_url") or "").strip():
            raise BizError("ES-BIZ-0014", "被测系统地址（base_url）不能为空，请选择或填写被测环境")

    # v2.0 P5：多轮引擎必须绑定真实被测系统（避免"测自己"的价值折损）
    if "MULTI_TURN_TEST" in body.engines and not str(final_config.get("target_code") or "").strip():
        raise BizError("ES-BIZ-0017", "多轮引擎必须选择被测系统（target_code），否则测试的是平台内置模型")

    # B5：社区版单任务规模上限（用例数 / 被测目标数 / 压测参数）
    _scen = final_config.get("scenario_ids") or ([final_config.get("scenario_id")] if final_config.get("scenario_id") else [])
    _tgt = len([x for x in _scen if x is not None])
    if str(final_config.get("target_code") or "").strip():
        _tgt = max(_tgt, 1)
    check_limit("cases_per_task", db, auth, n=len(final_config.get("case_ids") or []))
    check_limit("targets_per_task", db, auth, scenario_targets=_tgt)
    if "PERF_TEST" in body.engines or "LOCUST_PERF" in body.engines:
        check_limit("perf_concurrency", db, auth, config=final_config)
        check_limit("perf_duration_s", db, auth, config=final_config)

    # ES8 M5：门禁规则严格校验（非法结构 → 422 BizError；未传 = 默认 "[]"）
    gate_rules_json = validate_gate_rules(body.gate_rules)

    # ES10-P-02：自动版本归因 —— 基线优先，否则该项目最新版本（矛盾裁定①）
    #   用户显式传了 body.project_version_id（未来表单入口）则尊重传入值并校验归属
    pv_id = body.project_version_id
    if pv_id is not None:
        pv = db.get(ProjectVersion, pv_id)
        if pv is None or pv.project_id != p.id:
            # ES-BIZ-0019/0020/0021 已被项目成员管理占用，本处使用首个空闲码 0022
            raise BizError("ES-BIZ-0022", "指定的项目版本不存在或不属于该项目")
    else:
        pv = (
            db.query(ProjectVersion)
            .filter(
                ProjectVersion.project_id == p.id,
            )
            .order_by(ProjectVersion.is_baseline.desc(), ProjectVersion.created_at.desc())
            .first()
        )
        pv_id = pv.id if pv else None

    task = TestTask(
        task_no=gen_no("TSK"),
        project_id=p.id,
        project_version_id=pv_id,
        project_code=p.code,
        name=body.name,
        description=body.description,
        task_type="单测",
        engines=body.engines,
        config=final_config,
        trigger_mode=body.trigger_mode,
        schedule_cron=body.schedule_cron,
        status="PENDING",
        gate_rules=gate_rules_json,
        created_by=auth.user_id,
        created_by_name=auth.username,
        tenant_id=auth.tenant_id,
        executor=auth.username,  # P2-7：创建时即绑定执行人
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {
        "code": 0,
        "message": "ok",
        "data": TaskOut.model_validate(task).model_dump(),
    }


@router.get("/tasks/{task_id}", response_model=dict)
async def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    t = db.get(TestTask, task_id)
    if t is None or t.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0004", "任务不存在")
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    steps = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id)
        .order_by(TaskStep.seq)
        .all()
    )
    row = TaskOut.model_validate(t).model_dump()
    row["steps"] = [StepOut.model_validate(s).model_dump() for s in steps]
    row["next_run_at"] = next_run_at(t)
    return {"code": 0, "message": "ok", "data": row}


@router.post("/tasks/{task_id}/run", response_model=dict)
async def run_task(
    task_id: int,
    request: Request,
    body: TaskRunRequest | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """执行任务：异步后台执行引擎链，立即返回；进度通过 GET /tasks/{id} 轮询。"""
    t = db.get(TestTask, task_id)
    if t is None or t.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0004", "任务不存在")
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    if is_running(task_id):
        raise BizError("ES-BIZ-0005", "任务正在执行中，请勿重复触发")

    engines = (body.engines if body and body.engines else t.engines) or []
    config = (body.config if body and body.config else t.config) or {}

    # B5：执行入口兜底复核单任务规模（PUT 编辑 config 不经创建校验）
    _scen = config.get("scenario_ids") or ([config.get("scenario_id")] if config.get("scenario_id") else [])
    _tgt = len([x for x in _scen if x is not None])
    if str(config.get("target_code") or "").strip():
        _tgt = max(_tgt, 1)
    check_limit("cases_per_task", db, auth, n=len(config.get("case_ids") or []))
    check_limit("targets_per_task", db, auth, scenario_targets=_tgt)
    if "PERF_TEST" in engines or "LOCUST_PERF" in engines:
        check_limit("perf_concurrency", db, auth, config=config)
        check_limit("perf_duration_s", db, auth, config=config)

    t.status = "PENDING"
    t.progress = 0
    t.started_at = None
    t.finished_at = None
    t.error_msg = None
    t.current_step = None
    t.executor = auth.username  # P2-7：执行人 = 触发执行的用户
    db.commit()

    launch_task_async(task_id, engines=engines, config=config)
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="task.execute",
        module="task",
        request=request,
        result="SUCCESS",
        detail=f"触发执行任务 {t.task_no}（{t.name}），引擎链 {engines}",
    )
    row = TaskOut.model_validate(t).model_dump()
    row["next_run_at"] = None
    return {
        "code": 0,
        "message": "ok",
        "data": {"task": row, "async": True, "report_no": None},
    }


@router.post("/tasks/{task_id}/cancel", response_model=dict)
async def cancel_task(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    t = db.get(TestTask, task_id)
    if t is None or t.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0004", "任务不存在")
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    old_status = t.status
    if t.status == "RUNNING" and t.started_at is None:
        # 已调度但尚未真正启动的兜底
        t.status = "CANCELLED"
        t.finished_at = datetime.now(timezone.utc)
    elif t.status in ("PENDING", "SCHEDULED"):
        # 未开始：直接置为已取消
        t.status = "CANCELLED"
        t.finished_at = datetime.now(timezone.utc)
    elif t.status == "RUNNING":
        # 执行中：置 CANCELING，执行器在检查点感知后置 CANCELLED
        t.status = "CANCELING"
    db.commit()
    if t.status != old_status:
        write_audit(
            db,
            user_id=auth.user_id,
            username=auth.username,
            tenant_id=auth.tenant_id,
            action="task.cancel",
            module="task",
            request=request,
            result="SUCCESS",
            detail=f"取消任务 {t.task_no}（{t.name}）：{old_status} → {t.status}",
        )
    return {"code": 0, "message": "ok", "data": {"status": t.status}}


@router.get("/tasks/{task_id}/steps", response_model=dict)
async def list_task_steps(
    task_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    t = db.get(TestTask, task_id)
    if t is None:
        raise NotFoundError("ES-BIZ-0004", "任务不存在")
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    steps = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id)
        .order_by(TaskStep.seq)
        .all()
    )
    return {
        "code": 0,
        "message": "ok",
        "data": [StepOut.model_validate(s).model_dump() for s in steps],
    }


# ---------------------------------------------------------------------------
# 资产（报告产物文件落盘）
# ---------------------------------------------------------------------------
@router.get("/artifacts", response_model=dict)
async def list_artifacts(
    task_id: int | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    q = db.query(TaskArtifact).filter(TaskArtifact.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(TaskArtifact.tenant_id == auth.tenant_id)
    if task_id:
        q = q.filter(TaskArtifact.task_id == task_id)
    rows = q.order_by(TaskArtifact.id.desc()).limit(200).all()
    return {
        "code": 0,
        "message": "ok",
        "data": [
            {
                "id": a.id,
                "artifact_no": a.artifact_no,
                "task_id": a.task_id,
                "file_name": a.file_name,
                "file_path": a.file_path,
                "file_size": a.file_size,
                "mime_type": a.mime_type,
                "art_type": a.art_type,
                "created_at": a.created_at,
            }
            for a in rows
        ],
    }


# ---------------------------------------------------------------------------
# 任务（补：编辑 / 删除）
# ---------------------------------------------------------------------------
@router.put("/tasks/{task_id}", response_model=dict)
async def update_task(
    task_id: int,
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    t = db.get(TestTask, task_id)
    if t is None or t.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0004", "任务不存在")
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    if t.status == "RUNNING":
        raise BizError("ES-BIZ-0015", "运行中任务不可编辑")
    # B7：编辑为定时任务同样受社区版开关约束
    if body.get("trigger_mode") == "SCHEDULED" or body.get("schedule_cron"):
        check_limit("scheduler", db, auth)
    updatable = ("name", "description", "engines", "config", "trigger_mode", "schedule_cron")
    changed = False
    for k in updatable:
        v = body.get(k)
        if v is not None:
            setattr(t, k, v)
            changed = True
    # ES8 M5：gate_rules 显式传了才更新（需严格校验；传 [] / "" 视为清空门禁）
    if "gate_rules" in body:
        t.gate_rules = validate_gate_rules(body.get("gate_rules"))
        changed = True
    if changed:
        t.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(t)
    row = TaskOut.model_validate(t).model_dump()
    row["next_run_at"] = next_run_at(t)
    return {"code": 0, "message": "ok", "data": row}


@router.delete("/tasks/{task_id}", response_model=dict)
async def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    t = db.get(TestTask, task_id)
    if t is None or t.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0004", "任务不存在")
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    # 若任务仍在执行中，先自动置为 CANCELLED 再删除（软删）
    if t.status in ("RUNNING", "CANCELING", "SCHEDULED", "PENDING"):
        t.status = "CANCELLED"
        if t.finished_at is None:
            t.finished_at = datetime.now(timezone.utc)
    t.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.post("/tasks/batch-delete", response_model=dict)
async def batch_delete_tasks(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """D-DEL-01：批量删除任务（软删 + 运行中先置 CANCELLED）。"""
    ids = [int(x) for x in (body.get("ids") or [])]
    if not ids:
        return {"code": 0, "message": "ok", "data": {"deleted": 0, "skipped": 0, "not_found": []}}
    now = datetime.now(timezone.utc)
    deleted = skipped = 0
    not_found: list[int] = []
    for tid in ids:
        t = db.get(TestTask, tid)
        if t is None or t.deleted_at is not None:
            not_found.append(tid); continue
        if t.tenant_id != auth.tenant_id:
            skipped += 1; continue
        if t.status in ("RUNNING", "CANCELING", "SCHEDULED", "PENDING"):
            t.status = "CANCELLED"
            if t.finished_at is None:
                t.finished_at = now
        t.deleted_at = now
        deleted += 1
    db.commit()
    return {"code": 0, "message": "ok",
            "data": {"deleted": deleted, "skipped": skipped, "not_found": not_found}}


