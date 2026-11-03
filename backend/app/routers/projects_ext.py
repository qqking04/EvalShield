# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""M2 项目深度管理：环境 / 版本 / 套件（说明书 4.2，17 端点）。

技术约束：
- 无外键：全部用 project_id / tenant_id / suite_id / task_id 逻辑关联。
- 统一认证：Depends(authenticate_request)，租户隔离 + 可见性校验。
- 统一响应：{"code":0,"message":"ok","data":...}；异常抛 BizError / NotFoundError / DataScopeError。
- environments 以 JSON 数组存储在 Project.environments 字段中（无独立表）。
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import security
from ..database import get_db
from ..deps import AuthContext, authenticate_request
from ..errors import (
    AuthError,
    BizError,
    DataScopeError,
    NotFoundError,
    ok,
)
from ..models import (
    AssetVersion,
    Project,
    ProjectMembers,
    ProjectVersion,
    Report,
    Scenario,
    TestCase,
    TestDataset,
    TestSuite,
    TestSuiteItem,
    TestTask,
    TestEnvironment,
)
from ..utils.no import gen_no
from ..limits import check_limit
from ..services.suite_exec import launch_suite

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic 请求体
# ---------------------------------------------------------------------------
class EnvCreate(BaseModel):
    name: str = Field(..., max_length=128)
    base_url: str | None = None
    headers: dict[str, Any] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


class EnvUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    headers: dict[str, Any] | None = None
    variables: dict[str, Any] | None = None
    is_default: bool | None = None


class VersionCreate(BaseModel):
    version_no: str
    description: str | None = None
    is_baseline: bool = False
    baseline_reason: str | None = None


class VersionUpdate(BaseModel):
    description: str | None = None


class BaselineSet(BaseModel):
    baseline_reason: str | None = None


class SuiteCreate(BaseModel):
    name: str
    description: str | None = None
    exec_mode: str = "SEQUENTIAL"
    cron_expr: str | None = None
    is_enabled: bool = True


class SuiteUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    exec_mode: str | None = None
    cron_expr: str | None = None
    is_enabled: bool | None = None


class SuiteItemAdd(BaseModel):
    task_id: int | None = None
    task_ids: list[int] | None = None
    sort_order: int | None = None


class SuiteItemUpdate(BaseModel):
    sort_order: int


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
_SENSITIVE_KEY_RE = re.compile(
    r"(key|token|secret|password|authorization)", re.IGNORECASE
)
_SENSITIVE_PLACEHOLDER = "******"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_project(db: Session, project_id: int, auth: AuthContext) -> Project:
    """加载项目并校验租户 + 可见性。"""
    p = (
        db.query(Project)
        .filter(Project.id == project_id, Project.deleted_at.is_(None))
        .first()
    )
    if p is None:
        raise NotFoundError(message="项目不存在")
    if auth.is_super_admin:
        return p
    if p.tenant_id != auth.tenant_id:
        # OBS-001（方案 v1.2）：异租户与不存在同形 404，闭合存在性枚举侧信道
        raise NotFoundError(message="项目不存在")
    # PRIVATE 可见性：仅 owner 或成员可访问；TEAM/PUBLIC 同租户均可
    if p.visibility == "PRIVATE":
        if p.owner_id != auth.user_id:
            member = (
                db.query(ProjectMembers)
                .filter(
                    ProjectMembers.project_id == p.id,
                    ProjectMembers.user_id == auth.user_id,
                    ProjectMembers.tenant_id == auth.tenant_id,
                    ProjectMembers.deleted_at.is_(None),
                )
                .first()
            )
            if member is None:
                raise DataScopeError(message="该项目为私有，您不在成员名单中")
    return p


def _env_mask(d: dict[str, Any] | None) -> dict[str, Any]:
    """敏感键前端回显一律 ******。"""
    if not d:
        return {}
    out: dict[str, Any] = {}
    for k, v in d.items():
        if _SENSITIVE_KEY_RE.search(k or ""):
            out[k] = _SENSITIVE_PLACEHOLDER if isinstance(v, str) else v
        else:
            out[k] = v
    return out


def _env_encrypt(d: dict[str, Any] | None) -> dict[str, Any]:
    """敏感键入库前加密（复用 security.encrypt_sensitive_dict）。"""
    return security.encrypt_sensitive_dict(d)


# _build_env_list / _gen_env_id 已废弃，改用 _env_row_to_dict / 新表 id 映射


# ===================================================================
# 1. 项目聚合统计
# ===================================================================
@router.get("/projects/{project_id}/overview")
async def project_overview(
    project_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, project_id, auth)
    now = _now()
    three_months_ago = now - timedelta(days=90)

    task_total = (
        db.query(func.count(TestTask.id))
        .filter(
            TestTask.project_id == project.id,
            TestTask.tenant_id == auth.tenant_id,
            TestTask.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    task_running = (
        db.query(func.count(TestTask.id))
        .filter(
            TestTask.project_id == project.id,
            TestTask.tenant_id == auth.tenant_id,
            TestTask.deleted_at.is_(None),
            TestTask.status.in_(["PENDING", "RUNNING", "CANCELING"]),
        )
        .scalar()
        or 0
    )
    task_finished = (
        db.query(func.count(TestTask.id))
        .filter(
            TestTask.project_id == project.id,
            TestTask.tenant_id == auth.tenant_id,
            TestTask.deleted_at.is_(None),
            TestTask.status.in_(["SUCCESS", "FAILED", "CANCELLED"]),
        )
        .scalar()
        or 0
    )
    task_success = (
        db.query(func.count(TestTask.id))
        .filter(
            TestTask.project_id == project.id,
            TestTask.tenant_id == auth.tenant_id,
            TestTask.deleted_at.is_(None),
            TestTask.status == "SUCCESS",
        )
        .scalar()
        or 0
    )
    pass_rate = round(task_success / task_finished * 100, 2) if task_finished > 0 else 0.0

    report_total = (
        db.query(func.count(Report.id))
        .filter(
            Report.project_id == project.id,
            Report.tenant_id == auth.tenant_id,
            Report.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    env_count = (
        db.query(func.count(TestEnvironment.id))
        .filter(
            TestEnvironment.project_id == project.id,
            TestEnvironment.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    member_count = (
        db.query(func.count(ProjectMembers.id))
        .filter(
            ProjectMembers.project_id == project.id,
            ProjectMembers.tenant_id == auth.tenant_id,
            ProjectMembers.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    suite_count = (
        db.query(func.count(TestSuite.id))
        .filter(
            TestSuite.project_id == project.id,
            TestSuite.tenant_id == auth.tenant_id,
            TestSuite.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    latest_version = (
        db.query(ProjectVersion)
        .filter(
            ProjectVersion.project_id == project.id,
            ProjectVersion.tenant_id == auth.tenant_id,
        )
        .order_by(ProjectVersion.created_at.desc())
        .first()
    )
    baseline_version = (
        db.query(ProjectVersion)
        .filter(
            ProjectVersion.project_id == project.id,
            ProjectVersion.tenant_id == auth.tenant_id,
            ProjectVersion.is_baseline == True,  # noqa: E712
        )
        .first()
    )

    recent_tasks = (
        db.query(TestTask)
        .filter(
            TestTask.project_id == project.id,
            TestTask.tenant_id == auth.tenant_id,
            TestTask.deleted_at.is_(None),
        )
        .order_by(TestTask.created_at.desc())
        .limit(5)
        .all()
    )
    recent_reports = (
        db.query(Report)
        .filter(
            Report.project_id == project.id,
            Report.tenant_id == auth.tenant_id,
            Report.deleted_at.is_(None),
        )
        .order_by(Report.created_at.desc())
        .limit(5)
        .all()
    )

    data = {
        "task_total": task_total,
        "task_running": task_running,
        "pass_rate": pass_rate,
        "report_total": report_total,
        "env_count": env_count,
        "member_count": member_count,
        "suite_count": suite_count,
        "latest_version": {
            "version_no": latest_version.version_no,
            "created_at": latest_version.created_at.isoformat() if latest_version else None,
        }
        if latest_version
        else None,
        "baseline_version": {
            "version_no": baseline_version.version_no,
            "created_at": baseline_version.created_at.isoformat() if baseline_version else None,
        }
        if baseline_version
        else None,
        "recent_tasks": [
            {
                "task_no": t.task_no,
                "name": t.name,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in recent_tasks
        ],
        "recent_reports": [
            {
                "report_no": r.report_no,
                "title": r.title,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent_reports
        ],
    }
    return ok(data)


# ===================================================================
# 环境管理（统一 TestEnvironment 新表，废弃 project.environments JSON）
#   迁移脚本已将存量 JSON 全部搬到新表；所有 CRUD 只读新表。
#   前端约定 env_id 为业务字符串，后端自动映射到 TestEnvironment.id。
# ===================================================================
def _env_row_to_dict(e: "TestEnvironment", mask_sensitive: bool = True) -> dict[str, Any]:
    """TestEnvironment ORM → API 返回 dict（同时提供 id / env_id 双字段兼容前端）。"""
    auth = e.auth or {}
    headers_raw = auth.get("headers") or {}
    variables_raw = auth.get("variables") or {}
    headers = _env_mask(headers_raw) if mask_sensitive else headers_raw
    variables = _env_mask(variables_raw) if mask_sensitive else variables_raw
    return {
        "id": e.id,                        # ← 前端 Select.value 需要（数字）
        "env_id": str(e.id),               # ← 业务字符串（旧兼容）
        "project_id": e.project_id,
        "name": e.name,
        "base_url": e.base_url,
        "headers": headers,
        "variables": variables,
        "is_default": bool(e.is_default),
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


def _env_set_default_uniqueness(project_id: int, db: Session):
    """设新默认前，撤销同 project 其它环境的 is_default。"""
    envs = db.query(TestEnvironment).filter(
        TestEnvironment.project_id == project_id,
        TestEnvironment.deleted_at.is_(None),
        TestEnvironment.is_default.is_(True),
    ).all()
    for e in envs:
        e.is_default = False


@router.get("/projects/{id}/environments")
async def list_environments(
    id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, id, auth)
    rows = db.query(TestEnvironment).filter(
        TestEnvironment.project_id == project.id,
        TestEnvironment.deleted_at.is_(None),
    ).order_by(TestEnvironment.is_default.desc(), TestEnvironment.id.asc()).all()
    return ok([_env_row_to_dict(r, mask_sensitive=True) for r in rows])


@router.post("/projects/{id}/environments")
async def create_environment(
    id: int,
    body: EnvCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, id, auth)
    default_for_project = db.query(TestEnvironment).filter(
        TestEnvironment.project_id == project.id,
        TestEnvironment.deleted_at.is_(None),
        TestEnvironment.is_default.is_(True),
    ).first()
    is_default = bool(body.is_default or not default_for_project)
    if is_default:
        _env_set_default_uniqueness(project.id, db)
    headers = _env_encrypt(body.headers) if body.headers else {}
    variables = _env_encrypt(body.variables) if body.variables else {}
    env = TestEnvironment(
        project_id=project.id, name=body.name, base_url=body.base_url,
        auth={"type": "custom", "headers": headers, "variables": variables},
        is_default=is_default, tenant_id=project.tenant_id or auth.tenant_id,
        created_by=auth.user_id,
    )
    db.add(env); db.commit(); db.refresh(env)
    return ok(_env_row_to_dict(env, mask_sensitive=True))


def _resolve_env_row(db: Session, project_id: int, env_id: str) -> "TestEnvironment":
    """env_id 是业务字符串：尝试 int(id) → 新表主键；找不到则报错。"""
    eid = None
    try:
        eid = int(env_id)
    except (TypeError, ValueError):
        pass
    if eid is not None:
        row = db.query(TestEnvironment).filter(
            TestEnvironment.id == eid,
            TestEnvironment.project_id == project_id,
            TestEnvironment.deleted_at.is_(None),
        ).first()
        if row:
            return row
    raise NotFoundError(message="环境不存在")


@router.put("/projects/{id}/environments/{env_id}")
async def update_environment(
    id: int,
    env_id: str,
    body: EnvUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, id, auth)
    env = _resolve_env_row(db, project.id, env_id)

    if body.name is not None:
        env.name = body.name
    if body.base_url is not None:
        env.base_url = body.base_url

    # headers 敏感合并逻辑（同旧 JSON 版）
    auth_dict = dict(env.auth or {})
    if body.headers is not None:
        original_headers = auth_dict.get("headers") or {}
        merged_headers = {}
        for k, new_v in body.headers.items():
            if _SENSITIVE_KEY_RE.search(k or "") and isinstance(new_v, str) and new_v == _SENSITIVE_PLACEHOLDER:
                merged_headers[k] = original_headers.get(k)
            else:
                merged_headers[k] = _env_encrypt({k: new_v})[k] if _SENSITIVE_KEY_RE.search(k or "") else new_v
        for k, v in original_headers.items():
            if k not in merged_headers:
                merged_headers[k] = v
        auth_dict["headers"] = merged_headers

    if body.variables is not None:
        original_vars = auth_dict.get("variables") or {}
        merged_vars = {}
        for k, new_v in body.variables.items():
            if _SENSITIVE_KEY_RE.search(k or "") and isinstance(new_v, str) and new_v == _SENSITIVE_PLACEHOLDER:
                merged_vars[k] = original_vars.get(k)
            else:
                merged_vars[k] = _env_encrypt({k: new_v})[k] if _SENSITIVE_KEY_RE.search(k or "") else new_v
        for k, v in original_vars.items():
            if k not in merged_vars:
                merged_vars[k] = v
        auth_dict["variables"] = merged_vars

    env.auth = auth_dict

    if body.is_default is not None:
        env.is_default = bool(body.is_default)
        if env.is_default:
            _env_set_default_uniqueness(project.id, db)
            env.is_default = True  # 上一行会把自己也清了，重设回来

    db.add(env); db.commit(); db.refresh(env)
    return ok(_env_row_to_dict(env, mask_sensitive=True))


@router.delete("/projects/{id}/environments/{env_id}")
async def delete_environment(
    id: int,
    env_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, id, auth)
    env = _resolve_env_row(db, project.id, env_id)
    was_default = bool(env.is_default)
    env.deleted_at = _now()
    if was_default:
        next_default = db.query(TestEnvironment).filter(
            TestEnvironment.project_id == project.id,
            TestEnvironment.deleted_at.is_(None),
        ).order_by(TestEnvironment.id.asc()).first()
        if next_default:
            next_default.is_default = True
    db.add(env); db.commit()
    return ok({"deleted": env_id})


@router.post("/projects/{id}/environments/{env_id}/duplicate")
async def duplicate_environment(
    id: int,
    env_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, id, auth)
    src = _resolve_env_row(db, project.id, env_id)
    dup = TestEnvironment(
        project_id=src.project_id,
        name=f"{src.name} - copy",
        base_url=src.base_url,
        auth=copy.deepcopy(src.auth or {}),
        is_default=False,
        tenant_id=src.tenant_id,
        created_by=auth.user_id,
    )
    db.add(dup); db.commit(); db.refresh(dup)
    return ok(_env_row_to_dict(dup, mask_sensitive=True))


# ===================================================================
# 版本管理
# ===================================================================
def _version_to_dict(v: ProjectVersion, counts: dict[int, dict] | None = None) -> dict[str, Any]:
    d = {
        "id": v.id,
        "version_no": v.version_no,
        "description": v.description,
        "is_baseline": bool(v.is_baseline),
        "baseline_reason": v.baseline_reason,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }
    # ES10-P-02 §9.2.3（矛盾表⑥修复）：补齐 Versions.jsx 既有 task_count / pass_rate 契约
    c = (counts or {}).get(v.id) or {"task_count": 0, "pass_rate": None}
    d["task_count"] = c["task_count"]
    d["pass_rate"] = c["pass_rate"]
    return d


@router.get("/projects/{id}/versions")
def list_versions(
    id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, id, auth)
    q = db.query(ProjectVersion).filter(
        ProjectVersion.project_id == project.id,
        ProjectVersion.tenant_id == auth.tenant_id,
    )
    total = q.count()
    rows = (
        q.order_by(ProjectVersion.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    # ES10-P-02：逐版本聚合任务数与通过率（双口径并集：
    #   新任务走 project_version_id 归因列，存量任务只有 task_version 字符串）
    counts: dict[int, dict] = {}
    for v in rows:
        tasks = (
            db.query(TestTask)
            .filter(
                TestTask.project_id == project.id,
                TestTask.deleted_at.is_(None),
                or_(TestTask.project_version_id == v.id, TestTask.task_version == v.version_no),
            )
            .all()
        )
        done = [t for t in tasks if t.status in ("SUCCESS", "FAILED", "DONE")]
        total_cnt = sum(int((t.summary or {}).get("total") or 0) for t in done)
        passed_cnt = sum(int((t.summary or {}).get("passed") or 0) for t in done)
        counts[v.id] = {
            "task_count": len(tasks),
            "pass_rate": round(passed_cnt / total_cnt, 4) if total_cnt else None,
        }
    return ok(
        {
            "items": [_version_to_dict(v, counts) for v in rows],
            "total": total,
            "page": page,
            "size": size,
        }
    )


@router.post("/projects/{id}/versions")
def create_version(
    id: int,
    body: VersionCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, id, auth)
    exists = (
        db.query(ProjectVersion)
        .filter(
            ProjectVersion.project_id == project.id,
            ProjectVersion.tenant_id == auth.tenant_id,
            ProjectVersion.version_no == body.version_no,
        )
        .first()
    )
    if exists:
        raise BizError(message=f"版本号 {body.version_no} 已存在")

    # 应用层：先取消旧基线，再设置新基线
    if body.is_baseline:
        db.query(ProjectVersion).filter(
            ProjectVersion.project_id == project.id,
            ProjectVersion.tenant_id == auth.tenant_id,
            ProjectVersion.is_baseline == True,  # noqa: E712
        ).update({"is_baseline": False}, synchronize_session=False)

    v = ProjectVersion(
        project_id=project.id,
        version_no=body.version_no,
        description=body.description,
        is_baseline=bool(body.is_baseline),
        baseline_reason=body.baseline_reason if body.is_baseline else None,
        tenant_id=auth.tenant_id,
        created_by=auth.user_id,
        created_at=_now(),
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return ok(_version_to_dict(v))


@router.put("/projects/{id}/versions/{vid}/baseline")
def set_baseline(
    id: int,
    vid: int,
    body: BaselineSet | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, id, auth)
    target = (
        db.query(ProjectVersion)
        .filter(
            ProjectVersion.id == vid,
            ProjectVersion.project_id == project.id,
            ProjectVersion.tenant_id == auth.tenant_id,
        )
        .first()
    )
    if target is None:
        raise NotFoundError(message="版本不存在")
    if target.is_baseline:
        raise BizError(message="该版本已是基线")
    # 应用层先清
    db.query(ProjectVersion).filter(
        ProjectVersion.project_id == project.id,
        ProjectVersion.tenant_id == auth.tenant_id,
        ProjectVersion.is_baseline == True,  # noqa: E712
    ).update({"is_baseline": False}, synchronize_session=False)
    target.is_baseline = True
    target.baseline_reason = (body.baseline_reason if body else None) or target.baseline_reason or ""
    db.add(target)
    db.commit()
    db.refresh(target)
    return ok(_version_to_dict(target))


@router.get("/projects/{id}/versions/trend")
def version_trend(
    id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, id, auth)
    versions = (
        db.query(ProjectVersion)
        .filter(
            ProjectVersion.project_id == project.id,
            ProjectVersion.tenant_id == auth.tenant_id,
        )
        .order_by(ProjectVersion.created_at.asc())
        .all()
    )
    # 每个版本关联的任务数 & 报告数
    trend: list[dict[str, Any]] = []
    for v in versions:
        task_cnt = (
            db.query(func.count(TestTask.id))
            .filter(
                TestTask.project_id == project.id,
                TestTask.tenant_id == auth.tenant_id,
                TestTask.task_version == v.version_no,
                TestTask.deleted_at.is_(None),
            )
            .scalar()
            or 0
        )
        report_cnt = (
            db.query(func.count(Report.id))
            .filter(
                Report.project_id == project.id,
                Report.tenant_id == auth.tenant_id,
                Report.deleted_at.is_(None),
            )
            .scalar()
            or 0
        )
        trend.append(
            {
                "version_no": v.version_no,
                "is_baseline": bool(v.is_baseline),
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "task_count": task_cnt,
                "report_count": report_cnt,
            }
        )
    return ok(trend)


@router.get("/projects/{id}/versions/compare")
def compare_versions(
    id: int,
    from_version: str = Query(...),
    to_version: str = Query(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, id, auth)
    v_from = (
        db.query(ProjectVersion)
        .filter(
            ProjectVersion.project_id == project.id,
            ProjectVersion.tenant_id == auth.tenant_id,
            ProjectVersion.version_no == from_version,
        )
        .first()
    )
    v_to = (
        db.query(ProjectVersion)
        .filter(
            ProjectVersion.project_id == project.id,
            ProjectVersion.tenant_id == auth.tenant_id,
            ProjectVersion.version_no == to_version,
        )
        .first()
    )
    if v_from is None or v_to is None:
        raise NotFoundError(message="任一版本不存在")
    # 版本描述 / 基线信息差异
    diff_tasks = (
        db.query(TestTask)
        .filter(
            TestTask.project_id == project.id,
            TestTask.tenant_id == auth.tenant_id,
            TestTask.task_version.in_([from_version, to_version]),
            TestTask.deleted_at.is_(None),
        )
        .order_by(TestTask.task_version, TestTask.created_at.desc())
        .all()
    )
    # 简单聚合：两个版本各自任务数 + 状态
    summary: dict[str, Any] = {"from": from_version, "to": to_version}
    side: dict[str, dict[str, Any]] = {}
    for vn in [from_version, to_version]:
        tcnt = sum(1 for t in diff_tasks if t.task_version == vn)
        scnt = sum(1 for t in diff_tasks if t.task_version == vn and t.status == "SUCCESS")
        side[vn] = {"task_total": tcnt, "task_success": scnt}
    summary["side"] = side
    summary["description_from"] = v_from.description
    summary["description_to"] = v_to.description
    summary["is_baseline_from"] = bool(v_from.is_baseline)
    summary["is_baseline_to"] = bool(v_to.is_baseline)
    summary["created_at_from"] = v_from.created_at.isoformat() if v_from.created_at else None
    summary["created_at_to"] = v_to.created_at.isoformat() if v_to.created_at else None
    return ok(summary)


# ===================================================================
# P2-19 测试资产版本管理（快照 / 历史 / diff / 回滚）
# ===================================================================
_ASSET_MODELS = {
    "CASE": TestCase,
    "DATASET": TestDataset,
    "SCENARIO": Scenario,
}
_ASSET_NO_FIELD = {"CASE": "case_no", "DATASET": "code", "SCENARIO": "code"}
_SNAPSHOT_EXCLUDE = {"tenant_id", "created_by", "created_at", "updated_at", "deleted_at"}


def _asset_snapshot(obj: Any) -> dict[str, Any]:
    """资产全量字段快照（排除审计字段，JSONB 值原样序列化）。"""
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        if col.name in _SNAPSHOT_EXCLUDE:
            continue
        v = getattr(obj, col.name)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        out[col.name] = v
    return out


def _load_asset(db: Session, asset_type: str, asset_id: int, auth: AuthContext):
    model = _ASSET_MODELS.get(asset_type.upper())
    if model is None:
        raise BizError(message=f"不支持的资产类型 {asset_type}")
    a = db.query(model).filter(
        model.id == asset_id, model.deleted_at.is_(None)
    ).first()
    if a is None:
        raise NotFoundError(message="资产不存在")
    if not auth.is_super_admin and a.tenant_id != auth.tenant_id:
        raise DataScopeError(message="无权访问该资产")
    return a


@router.post("/projects/{id}/assets/{asset_type}/{asset_id}/snapshot")
def create_asset_snapshot(
    id: int,
    asset_type: str,
    asset_id: int,
    body: dict | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """资产快照：把当前内容存为 asset_versions 新版本（可关联项目版本号）。"""
    project = _load_project(db, id, auth)
    a = _load_asset(db, asset_type, asset_id, auth)
    at = asset_type.upper()
    if a.project_id != project.id:
        raise BizError(message="资产不属于该项目")
    pv_id = None
    body = body or {}
    if body.get("version_no"):
        pv = (
            db.query(ProjectVersion)
            .filter(
                ProjectVersion.project_id == project.id,
                ProjectVersion.version_no == body["version_no"],
            )
            .first()
        )
        pv_id = pv.id if pv else None
    last_seq = (
        db.query(func.max(AssetVersion.seq))
        .filter(
            AssetVersion.asset_type == at,
            AssetVersion.asset_id == a.id,
            AssetVersion.tenant_id == auth.tenant_id,
        )
        .scalar()
        or 0
    )
    av = AssetVersion(
        project_id=project.id,
        project_version_id=pv_id,
        asset_type=at,
        asset_id=a.id,
        asset_no=getattr(a, _ASSET_NO_FIELD[at], None),
        seq=last_seq + 1,
        snapshot=_asset_snapshot(a),
        change_note=(body.get("change_note") or "")[:500] or None,
        tenant_id=auth.tenant_id,
        created_by=auth.user_id,
        created_at=_now(),
    )
    db.add(av)
    db.commit()
    db.refresh(av)
    return ok({"id": av.id, "seq": av.seq, "asset_type": at, "asset_id": a.id})


@router.get("/projects/{id}/assets/{asset_type}/{asset_id}/versions")
def list_asset_versions(
    id: int,
    asset_type: str,
    asset_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """资产历史版本列表（不含快照体，仅元信息）。"""
    _load_project(db, id, auth)
    a = _load_asset(db, asset_type, asset_id, auth)
    rows = (
        db.query(AssetVersion)
        .filter(
            AssetVersion.asset_type == asset_type.upper(),
            AssetVersion.asset_id == a.id,
            AssetVersion.tenant_id == auth.tenant_id,
        )
        .order_by(AssetVersion.seq.desc())
        .all()
    )
    pv_ids = {r.project_version_id for r in rows if r.project_version_id}
    pv_map = {}
    if pv_ids:
        for pv in db.query(ProjectVersion).filter(ProjectVersion.id.in_(pv_ids)).all():
            pv_map[pv.id] = pv.version_no
    return ok([
        {
            "id": r.id, "seq": r.seq, "asset_no": r.asset_no,
            "change_note": r.change_note,
            "project_version_no": pv_map.get(r.project_version_id),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "created_by": r.created_by,
        }
        for r in rows
    ])


@router.get("/projects/{id}/assets/{asset_type}/{asset_id}/versions/compare")
def compare_asset_versions(
    id: int,
    asset_type: str,
    asset_id: int,
    from_seq: int = Query(...),
    to_seq: int = Query(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """版本间差异对比：逐字段 diff（added/removed/changed）。"""
    _load_project(db, id, auth)
    a = _load_asset(db, asset_type, asset_id, auth)
    at = asset_type.upper()

    def _snap(seq: int) -> dict:
        r = (
            db.query(AssetVersion)
            .filter(
                AssetVersion.asset_type == at,
                AssetVersion.asset_id == a.id,
                AssetVersion.seq == seq,
                AssetVersion.tenant_id == auth.tenant_id,
            )
            .first()
        )
        if r is None:
            raise NotFoundError(message=f"版本 seq={seq} 不存在")
        return r.snapshot or {}

    s_from, s_to = _snap(from_seq), _snap(to_seq)
    keys = sorted(set(s_from) | set(s_to))
    diffs = []
    for k in keys:
        v1, v2 = s_from.get(k), s_to.get(k)
        if v1 == v2:
            continue
        if k not in s_from:
            diffs.append({"field": k, "type": "added", "to": v2})
        elif k not in s_to:
            diffs.append({"field": k, "type": "removed", "from": v1})
        else:
            diffs.append({"field": k, "type": "changed", "from": v1, "to": v2})
    return ok({"from_seq": from_seq, "to_seq": to_seq, "diffs": diffs, "changed": len(diffs)})


@router.post("/projects/{id}/assets/{asset_type}/{asset_id}/versions/{seq}/rollback")
def rollback_asset_version(
    id: int,
    asset_type: str,
    asset_id: int,
    seq: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """回滚：把资产内容恢复到指定快照版本（回滚前自动为当前内容补一次快照）。"""
    project = _load_project(db, id, auth)
    a = _load_asset(db, asset_type, asset_id, auth)
    at = asset_type.upper()
    target = (
        db.query(AssetVersion)
        .filter(
            AssetVersion.asset_type == at,
            AssetVersion.asset_id == a.id,
            AssetVersion.seq == seq,
            AssetVersion.tenant_id == auth.tenant_id,
        )
        .first()
    )
    if target is None:
        raise NotFoundError(message="目标版本不存在")

    # 回滚前先快照当前内容（避免丢失）
    cur_max = (
        db.query(func.max(AssetVersion.seq))
        .filter(AssetVersion.asset_type == at, AssetVersion.asset_id == a.id,
                AssetVersion.tenant_id == auth.tenant_id)
        .scalar() or 0
    )
    db.add(AssetVersion(
        project_id=project.id, asset_type=at, asset_id=a.id,
        asset_no=getattr(a, _ASSET_NO_FIELD[at], None),
        seq=cur_max + 1, snapshot=_asset_snapshot(a),
        change_note=f"回滚至 v{seq} 前自动快照",
        tenant_id=auth.tenant_id, created_by=auth.user_id, created_at=_now(),
    ))

    # 恢复字段（跳过主键/编号/租户/项目/审计字段）
    skip = {"id", "case_no", "code", "project_id", "tenant_id"} | _SNAPSHOT_EXCLUDE
    for k, v in (target.snapshot or {}).items():
        if k in skip or not hasattr(a, k):
            continue
        setattr(a, k, v)
    a.updated_at = _now()
    db.commit()
    return ok({"rolled_back_to": seq, "asset_id": a.id, "asset_type": at})


# ===================================================================
# 套件管理（CRUD + 明细 + 一键执行）
# ===================================================================
def _suite_to_dict(s: TestSuite, item_count: int = 0, last_task_count: int = 0) -> dict[str, Any]:
    return {
        "id": s.id,
        "suite_no": s.suite_no,
        "project_id": s.project_id,
        "name": s.name,
        "description": s.description,
        "exec_mode": s.exec_mode,
        "cron_expr": s.cron_expr,
        "is_enabled": bool(s.is_enabled),
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "item_count": item_count,
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _suite_detail(s: TestSuite, db: Session, auth: AuthContext) -> dict[str, Any]:
    items = (
        db.query(TestSuiteItem)
        .filter(
            TestSuiteItem.suite_id == s.id,
            TestSuiteItem.tenant_id == auth.tenant_id,
        )
        .order_by(TestSuiteItem.sort_order.asc())
        .all()
    )
    item_list = []
    for it in items:
        t = (
            db.query(TestTask)
            .filter(TestTask.id == it.task_id, TestTask.deleted_at.is_(None))
            .first()
        )
        item_list.append(
            {
                "id": it.id,
                "task_id": it.task_id,
                "task_no": t.task_no if t else None,
                "task_name": t.name if t else None,
                "sort_order": it.sort_order,
            }
        )
    return {
        **_suite_to_dict(s, item_count=len(items)),
        "items": item_list,
    }


@router.get("/projects/{id}/suites")
async def list_suites(
    id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, id, auth)
    q = db.query(TestSuite).filter(
        TestSuite.project_id == project.id,
        TestSuite.tenant_id == auth.tenant_id,
        TestSuite.deleted_at.is_(None),
    )
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(TestSuite.name.ilike(like) | TestSuite.suite_no.ilike(like))
    total = q.count()
    rows = (
        q.order_by(TestSuite.updated_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    # 批量计算 item_count
    ids = [r.id for r in rows]
    cnt_map: dict[int, int] = {}
    if ids:
        cnt_rows = (
            db.query(TestSuiteItem.suite_id, func.count(TestSuiteItem.id))
            .filter(
                TestSuiteItem.suite_id.in_(ids),
                TestSuiteItem.tenant_id == auth.tenant_id,
            )
            .group_by(TestSuiteItem.suite_id)
            .all()
        )
        cnt_map = {sid: c for sid, c in cnt_rows}
    return ok(
        {
            "items": [_suite_to_dict(s, item_count=cnt_map.get(s.id, 0)) for s in rows],
            "total": total,
            "page": page,
            "size": size,
        }
    )


@router.post("/projects/{id}/suites")
async def create_suite(
    id: int,
    body: SuiteCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    project = _load_project(db, id, auth)
    # B7：社区版套件定时（cron）关闭
    if body.cron_expr:
        check_limit("scheduler", db, auth)
    s = TestSuite(
        suite_no=gen_no("TS"),
        project_id=project.id,
        name=body.name,
        description=body.description,
        exec_mode=body.exec_mode or "SEQUENTIAL",
        cron_expr=body.cron_expr,
        is_enabled=bool(body.is_enabled),
        tenant_id=auth.tenant_id,
        created_by=auth.user_id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return ok(_suite_to_dict(s, item_count=0))


@router.put("/suites/{suite_id}")
async def update_suite(
    suite_id: int,
    body: SuiteUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    s = (
        db.query(TestSuite)
        .filter(
            TestSuite.id == suite_id,
            TestSuite.tenant_id == auth.tenant_id,
            TestSuite.deleted_at.is_(None),
        )
        .first()
    )
    if s is None:
        raise NotFoundError(message="套件不存在")
    if not auth.is_super_admin and s.tenant_id != auth.tenant_id:
        raise DataScopeError(message="无权访问该套件")
    # B7：社区版套件定时（cron）关闭（更新置空 cron 属于解除定时，放行）
    _upd = body.model_dump(exclude_unset=True)
    if _upd.get("cron_expr") or (_upd.get("is_enabled") and s.cron_expr):
        check_limit("scheduler", db, auth)
    for field, value in _upd.items():
        setattr(s, field, value)
    s.updated_at = _now()
    db.add(s)
    db.commit()
    db.refresh(s)
    item_cnt = (
        db.query(func.count(TestSuiteItem.id))
        .filter(
            TestSuiteItem.suite_id == s.id,
            TestSuiteItem.tenant_id == auth.tenant_id,
        )
        .scalar()
        or 0
    )
    return ok(_suite_to_dict(s, item_count=item_cnt))


@router.delete("/suites/{suite_id}")
async def delete_suite(
    suite_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    s = (
        db.query(TestSuite)
        .filter(
            TestSuite.id == suite_id,
            TestSuite.tenant_id == auth.tenant_id,
            TestSuite.deleted_at.is_(None),
        )
        .first()
    )
    if s is None:
        raise NotFoundError(message="套件不存在")
    if not auth.is_super_admin and s.tenant_id != auth.tenant_id:
        raise DataScopeError(message="无权访问该套件")
    # 软删除套件
    s.deleted_at = _now()
    s.updated_at = _now()
    db.add(s)
    # 物理删除 items
    db.query(TestSuiteItem).filter(
        TestSuiteItem.suite_id == s.id,
        TestSuiteItem.tenant_id == auth.tenant_id,
    ).delete(synchronize_session=False)
    db.commit()
    return ok({"deleted": suite_id})


@router.get("/suites/{suite_id}")
async def get_suite(
    suite_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    s = (
        db.query(TestSuite)
        .filter(
            TestSuite.id == suite_id,
            TestSuite.tenant_id == auth.tenant_id,
            TestSuite.deleted_at.is_(None),
        )
        .first()
    )
    if s is None:
        raise NotFoundError(message="套件不存在")
    return ok(_suite_detail(s, db, auth))


@router.get("/suites/{suite_id}/items")
async def list_suite_items(
    suite_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """套件明细列表（前端 Suites 详情页依赖；按 sort_order 升序）。"""
    s = (
        db.query(TestSuite)
        .filter(
            TestSuite.id == suite_id,
            TestSuite.tenant_id == auth.tenant_id,
            TestSuite.deleted_at.is_(None),
        )
        .first()
    )
    if s is None:
        raise NotFoundError(message="套件不存在")
    detail = _suite_detail(s, db, auth)
    return ok({"items": detail["items"]})


@router.post("/suites/{suite_id}/items")
async def add_suite_item(
    suite_id: int,
    body: SuiteItemAdd,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    s = (
        db.query(TestSuite)
        .filter(
            TestSuite.id == suite_id,
            TestSuite.tenant_id == auth.tenant_id,
            TestSuite.deleted_at.is_(None),
        )
        .first()
    )
    if s is None:
        raise NotFoundError(message="套件不存在")
    # 兼容单值 task_id 与批量 task_ids（前端「从项目任务库添加」多选提交 task_ids）
    if body.task_ids:
        task_ids = list(dict.fromkeys(body.task_ids))  # 去重保序
        batch = True
    elif body.task_id is not None:
        task_ids = [body.task_id]
        batch = False
    else:
        raise BizError(message="task_id 与 task_ids 至少提供一个")
    # 校验任务存在 & 同项目
    tasks: list[TestTask] = []
    for tid in task_ids:
        t = (
            db.query(TestTask)
            .filter(TestTask.id == tid, TestTask.deleted_at.is_(None))
            .first()
        )
        if t is None:
            raise NotFoundError(message="任务不存在")
        if t.project_id != s.project_id:
            raise BizError(message="任务所属项目与套件不一致")
        tasks.append(t)
    # sort_order：若未指定，取当前最大值 + 1 起递增
    if body.sort_order is None:
        row = (
            db.query(func.max(TestSuiteItem.sort_order))
            .filter(
                TestSuiteItem.suite_id == s.id,
                TestSuiteItem.tenant_id == auth.tenant_id,
            )
            .scalar()
        )
        next_sort = (row or 0) + 1
    else:
        next_sort = body.sort_order
    for t in tasks:
        # 防重复：单值模式保持报错语义；批量模式跳过已存在项
        dup = (
            db.query(TestSuiteItem)
            .filter(
                TestSuiteItem.suite_id == s.id,
                TestSuiteItem.task_id == t.id,
                TestSuiteItem.tenant_id == auth.tenant_id,
            )
            .first()
        )
        if dup:
            if not batch:
                raise BizError(message="该任务已在套件中")
            continue
        it = TestSuiteItem(
            suite_id=s.id,
            task_id=t.id,
            sort_order=next_sort,
            tenant_id=auth.tenant_id,
            created_at=_now(),
        )
        next_sort += 1
        db.add(it)
    db.commit()
    return ok(_suite_detail(s, db, auth))


@router.put("/suites/{suite_id}/items/{item_id}")
async def update_suite_item(
    suite_id: int,
    item_id: int,
    body: SuiteItemUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    s = (
        db.query(TestSuite)
        .filter(
            TestSuite.id == suite_id,
            TestSuite.tenant_id == auth.tenant_id,
            TestSuite.deleted_at.is_(None),
        )
        .first()
    )
    if s is None:
        raise NotFoundError(message="套件不存在")
    it = (
        db.query(TestSuiteItem)
        .filter(
            TestSuiteItem.id == item_id,
            TestSuiteItem.suite_id == s.id,
            TestSuiteItem.tenant_id == auth.tenant_id,
        )
        .first()
    )
    if it is None:
        raise NotFoundError(message="套件条目不存在")
    it.sort_order = body.sort_order
    db.add(it)
    db.commit()
    db.refresh(it)
    return ok(_suite_detail(s, db, auth))


@router.delete("/suites/{suite_id}/items/{item_id}")
async def remove_suite_item(
    suite_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    s = (
        db.query(TestSuite)
        .filter(
            TestSuite.id == suite_id,
            TestSuite.tenant_id == auth.tenant_id,
            TestSuite.deleted_at.is_(None),
        )
        .first()
    )
    if s is None:
        raise NotFoundError(message="套件不存在")
    it = (
        db.query(TestSuiteItem)
        .filter(
            TestSuiteItem.id == item_id,
            TestSuiteItem.suite_id == s.id,
            TestSuiteItem.tenant_id == auth.tenant_id,
        )
        .first()
    )
    if it is None:
        raise NotFoundError(message="套件条目不存在")
    db.delete(it)
    db.commit()
    return ok(_suite_detail(s, db, auth))


@router.post("/suites/{suite_id}/execute")
async def execute_suite(
    suite_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """一键执行：复制套件内每个任务，设置 suite_id = 当前套件 id。

    ES8 M4：主体逻辑抽取至 services/suite_exec.launch_suite（monitor 定时共用）。
    """
    return ok(launch_suite(db, suite_id, auth))


@router.get("/suites/{suite_id}/runs")
async def suite_run_history(
    suite_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    s = (
        db.query(TestSuite)
        .filter(
            TestSuite.id == suite_id,
            TestSuite.tenant_id == auth.tenant_id,
            TestSuite.deleted_at.is_(None),
        )
        .first()
    )
    if s is None:
        raise NotFoundError(message="套件不存在")
    tasks = (
        db.query(TestTask)
        .filter(
            TestTask.suite_id == s.id,
            TestTask.tenant_id == auth.tenant_id,
            TestTask.deleted_at.is_(None),
        )
        .order_by(TestTask.created_at.desc())
        .all()
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for t in tasks:
        key = t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "unknown"
        grouped.setdefault(key, []).append(
            {
                "task_id": t.id,
                "task_no": t.task_no,
                "name": t.name,
                "status": t.status,
                "progress": t.progress,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
        )
    return ok(
        {
            "suite_id": s.id,
            "suite_no": s.suite_no,
            "suite_name": s.name,
            "total_runs": len(tasks),
            "runs": [
                {"group_time": k, "tasks": v}
                for k, v in grouped.items()
            ],
        }
    )
