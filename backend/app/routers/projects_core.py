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
from ..limits import check_limit
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
from ..utils.csv_safe import esc_csv
from ..utils.cron import parse_cron
from ..utils.no import gen_no


router = APIRouter()
from ._business_common import *  # noqa: F401,F403

# ---------------------------------------------------------------------------
# 项目
# ---------------------------------------------------------------------------
@router.get("/projects", response_model=dict)
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    keyword: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    q = db.query(Project).filter(Project.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(Project.tenant_id == auth.tenant_id)
        # PRIVATE 项目仅创建者/成员可见（ProjectOut 含名称等细节，不能对非成员展示）
        member_ids = {
            int(r[0])
            for r in db.query(ProjectMembers.project_id)
            .filter(
                ProjectMembers.user_id == auth.user_id,
                ProjectMembers.deleted_at.is_(None),
            )
            .all()
        }
        visible = (
            Project.visibility != "PRIVATE"
        ) | (  # OR：本人创建，或是项目成员
            (Project.created_by == auth.user_id) | Project.id.in_(member_ids)
        )
        q = q.filter(visible)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(Project.name.ilike(like) | Project.code.ilike(like))
    if status:
        q = q.filter(Project.status == status)
    total = q.count()
    rows = (
        q.order_by(Project.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 任务数聚合
    task_counts: dict[int, int] = {}
    for pid_, cnt_ in (
        db.query(TestTask.project_id, func.count(TestTask.id))
        .filter(
            TestTask.project_id.in_([p.id for p in rows]), TestTask.deleted_at.is_(None)
        )
        .group_by(TestTask.project_id)
        .all()
    ):
        task_counts[int(pid_)] = int(cnt_)
    items = []
    for p in rows:
        row = ProjectOut.model_validate(p).model_dump()
        row["task_count"] = task_counts.get(p.id, 0)
        items.append(row)
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": items, "total": total, "page": page, "page_size": page_size},
    }


@router.post("/projects", response_model=dict)
async def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    check_limit("projects_total", db, auth, n=1)  # B5 社区版项目总量上限
    project = Project(
        code=gen_no("PRJ"),
        name=body.name,
        description=body.description,
        owner_id=body.owner_id or auth.user_id,
        owner_name=auth.username,
        target_system=body.target_system,
        visibility=body.visibility,
        tenant_id=auth.tenant_id,
        created_by=auth.user_id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return {
        "code": 0,
        "message": "ok",
        "data": ProjectOut.model_validate(project).model_dump(),
    }


@router.get("/projects/{project_id}", response_model=dict)
async def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    p = db.get(Project, project_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")
    await ensure_data_scope(
        auth,
        resource_tenant_id=p.tenant_id,
        visibility=p.visibility,
        owner_user_id=p.owner_id,
    )
    row = ProjectOut.model_validate(p).model_dump()
    row["task_count"] = (
        db.query(func.count(TestTask.id))
        .filter(TestTask.project_id == project_id, TestTask.deleted_at.is_(None))
        .scalar()
        or 0
    )
    return {"code": 0, "message": "ok", "data": row}


@router.put("/projects/{project_id}", response_model=dict)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    p = db.get(Project, project_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")
    await ensure_data_scope(
        auth,
        resource_tenant_id=p.tenant_id,
        visibility=p.visibility,
        owner_user_id=p.owner_id,
    )
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    p.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.delete("/projects/{project_id}", response_model=dict)
async def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    p = db.get(Project, project_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")
    await ensure_data_scope(
        auth,
        resource_tenant_id=p.tenant_id,
        visibility=p.visibility,
        owner_user_id=p.owner_id,
    )
    if (
        db.query(TestTask)
        .filter(TestTask.project_id == project_id, TestTask.deleted_at.is_(None))
        .first()
    ):
        raise BizError("ES-BIZ-0002", "项目下存在任务，不能删除（可先归档任务）")
    p.deleted_at = datetime.now(timezone.utc)
    p.status = "ARCHIVED"
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.get("/projects/{project_id}/members", response_model=dict)
async def list_project_members(
    project_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    p = db.get(Project, project_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")
    # 项目成员可读：项目 OWNER / SUPER_ADMIN / 自身已加入者
    is_admin = _is_project_admin(db, auth, project_id)
    row = (
        db.query(ProjectMembers)
        .filter(
            ProjectMembers.project_id == project_id,
            ProjectMembers.deleted_at.is_(None),
        )
        .all()
    )
    user_ids = [m.user_id for m in row]
    user_map: dict[int, SystemUser] = {}
    if user_ids:
        for u in db.query(SystemUser).filter(SystemUser.id.in_(user_ids)).all():
            user_map[u.id] = u
    items = []
    for m in row:
        u = user_map.get(m.user_id)
        items.append(
            {
                "user_id": m.user_id,
                "username": u.username if u else "",
                "display_name": u.display_name if u else "",
                "role": m.role,
            }
        )
    return {"code": 0, "message": "ok", "data": {"items": items, "total": len(items)}}


@router.post("/projects/{project_id}/members", response_model=dict)
async def add_project_member(
    project_id: int,
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    p = db.get(Project, project_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")
    if not _is_project_admin(db, auth, project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅项目 OWNER 或管理员可添加成员",
        )
    user_id = body.get("user_id")
    role = body.get("role", "MEMBER")
    if role not in ("OWNER", "MEMBER", "VIEWER"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="role 必须是 OWNER / MEMBER / VIEWER",
        )
    # 检查用户是否存在
    u = db.get(SystemUser, user_id)
    if u is None or u.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="用户不存在",
        )
    # 检查重复
    exists = (
        db.query(ProjectMembers)
        .filter(
            ProjectMembers.project_id == project_id,
            ProjectMembers.user_id == user_id,
            ProjectMembers.deleted_at.is_(None),
        )
        .first()
    )
    if exists:
        raise BizError("ES-BIZ-0019", "该用户已是项目成员")
    pm = ProjectMembers(
        project_id=project_id,
        user_id=user_id,
        role=role,
        tenant_id=auth.tenant_id,
        created_by=auth.user_id,
    )
    db.add(pm)
    db.commit()
    db.refresh(pm)
    return {"code": 0, "message": "ok", "data": {"user_id": pm.user_id, "role": pm.role}}


@router.put("/projects/{project_id}/members/{user_id}", response_model=dict)
async def update_project_member(
    project_id: int,
    user_id: int,
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    p = db.get(Project, project_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")
    if not _is_project_admin(db, auth, project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅项目 OWNER 或管理员可修改成员",
        )
    role = body.get("role")
    if not role or role not in ("OWNER", "MEMBER", "VIEWER"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="role 必须是 OWNER / MEMBER / VIEWER",
        )
    pm = (
        db.query(ProjectMembers)
        .filter(
            ProjectMembers.project_id == project_id,
            ProjectMembers.user_id == user_id,
            ProjectMembers.deleted_at.is_(None),
        )
        .first()
    )
    if pm is None:
        raise NotFoundError("ES-BIZ-0020", "成员不存在")
    # 注：OWNER 唯一性暂不强制，可后续加 unique 约束或业务检查
    pm.role = role
    pm.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": {"user_id": pm.user_id, "role": pm.role}}


@router.delete("/projects/{project_id}/members/{user_id}", response_model=dict)
async def remove_project_member(
    project_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    p = db.get(Project, project_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")
    if not _is_project_admin(db, auth, project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅项目 OWNER 或管理员可移除成员",
        )
    # OWNER 不能移除自己
    if user_id == auth.user_id:
        raise BizError("ES-BIZ-0021", "OWNER 不能移除自己（请先转移角色）")
    pm = (
        db.query(ProjectMembers)
        .filter(
            ProjectMembers.project_id == project_id,
            ProjectMembers.user_id == user_id,
            ProjectMembers.deleted_at.is_(None),
        )
        .first()
    )
    if pm is None:
        raise NotFoundError("ES-BIZ-0020", "成员不存在")
    pm.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


# ---------------------------------------------------------------------------
# IO-01~03: 用例导出（JSON 含 module/case_no，CSV 含「所属模块」列）
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/cases-export", response_model=dict)
async def export_cases(
    project_id: int,
    format: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """用例批量导出：JSON 全量 / CSV 表格，均含 module(所属模块) 列。"""
    p = db.get(Project, project_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")
    await ensure_data_scope(auth, resource_tenant_id=p.tenant_id)
    rows = db.query(TestCase).filter(
        TestCase.project_id == project_id,
        TestCase.deleted_at.is_(None),
    ).order_by(TestCase.id.asc()).all()

    if format == "json":
        data = [
            {
                "case_no": c.case_no,
                "title": c.title,
                "category": c.category,
                "module": c.module,
                "request_spec": c.request_spec,
                "assertions": c.assertions,
                "severity": c.severity,
                "priority": c.priority,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in rows
        ]
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        return StreamingResponse(
            iter([payload.encode("utf-8")]),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=cases_{project_id}.json"},
        )

    # CSV
    buf = io.StringIO(newline="")
    w = csv.writer(buf)
    w.writerow(["用例编号", "标题", "类别", "所属模块", "请求地址", "请求方法", "严重度", "优先级", "创建时间"])
    for c in rows:
        spec = c.request_spec or {}
        if isinstance(spec, str):
            try: spec = json.loads(spec)
            except Exception: spec = {}
        w.writerow([
            esc_csv(c.case_no),
            esc_csv(c.title or ""),
            esc_csv(c.category or ""),
            esc_csv(c.module or ""),
            esc_csv(spec.get("url", "") if isinstance(spec, dict) else ""),
            esc_csv(spec.get("method", "") if isinstance(spec, dict) else ""),
            c.severity or "",
            c.priority or "",
            c.created_at.strftime("%Y-%m-%d %H:%M:%S") if c.created_at else "",
        ])
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),  # utf-8-sig Excel 打开中文不乱码
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=cases_{project_id}.csv"},
    )


