# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""被测系统注册路由（§4.1.3）：CRUD + 连通测试。权限与 model-configs 同级。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import AuthContext, ensure_data_scope, require_permission
from ..errors import NotFoundError
from ..models import TargetRegistry
from ..services.audit import write_audit
from ..services.ssrf_guard import validate_base_url
from ..services.target_gateway import test_target

router = APIRouter()


class TargetCreate(BaseModel):
    code: str | None = None
    name: str = Field(..., min_length=1, max_length=128)
    target_type: str = Field(..., pattern="^(LLM_API|APP_API|INTERNAL_MODEL)$")
    base_url: str = Field(..., min_length=1, max_length=512)
    chat_path: str | None = "/chat/completions"
    protocol: str = "OPENAI"
    auth_env: str | None = None
    headers: dict | None = None
    request_template: dict | None = None
    response_path: str | None = None
    model: str | None = None
    timeout_sec: int = 30
    remark: str | None = None


class TargetUpdate(BaseModel):
    name: str | None = None
    target_type: str | None = Field(None, pattern="^(LLM_API|APP_API|INTERNAL_MODEL)$")
    base_url: str | None = None
    chat_path: str | None = None
    protocol: str | None = None
    auth_env: str | None = None
    headers: dict | None = None
    request_template: dict | None = None
    response_path: str | None = None
    model: str | None = None
    timeout_sec: int | None = None
    status: str | None = None
    remark: str | None = None


def _row_out(t: TargetRegistry) -> dict:
    return {
        "code": t.code,
        "name": t.name,
        "target_type": t.target_type,
        "base_url": t.base_url,
        "chat_path": t.chat_path,
        "protocol": t.protocol,
        "auth_env": t.auth_env,
        "headers": t.headers,
        "request_template": t.request_template,
        "response_path": t.response_path,
        "model": getattr(t, "model", None),
        "timeout_sec": t.timeout_sec,
        "status": t.status,
        "remark": t.remark,
        "tenant_id": t.tenant_id,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


@router.get("/targets", response_model=dict)
async def list_targets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "read")),
):
    q = db.query(TargetRegistry).filter(TargetRegistry.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(TargetRegistry.tenant_id == auth.tenant_id)
    if status:
        q = q.filter(TargetRegistry.status == status)
    total = q.count()
    rows = q.order_by(TargetRegistry.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"code": 0, "message": "ok", "data": {"items": [_row_out(t) for t in rows], "total": total}}


@router.post("/targets", response_model=dict)
async def create_target(
    body: TargetCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "create")),
):
    code = body.code or _next_code(db, auth.tenant_id)
    exists = (
        db.query(TargetRegistry)
        .filter(TargetRegistry.code == code, TargetRegistry.deleted_at.is_(None))
        .first()
    )
    if exists:
        raise NotFoundError("ES-BIZ-0070", f"被测对象编号 {code} 已存在")
    # BUG-003（D-16/HAL-08）：出网地址 SSRF 校验（内网/回环/元数据拒绝）
    validate_base_url(body.base_url, error_code="ES-TARGET-SSRF")
    t = TargetRegistry(
        code=code,
        name=body.name,
        target_type=body.target_type,
        base_url=body.base_url,
        chat_path=body.chat_path or "/chat/completions",
        protocol=body.protocol or "OPENAI",
        auth_env=body.auth_env,
        headers=body.headers or {},
        request_template=body.request_template,
        response_path=body.response_path,
        model=body.model,
        timeout_sec=body.timeout_sec or 30,
        remark=body.remark,
        tenant_id=auth.tenant_id,
        created_by=auth.user_id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="target.create", module="target", request=request,
        detail=f"注册被测系统：{t.name}（{t.code}，{t.target_type}）",
    )
    return {"code": 0, "message": "ok", "data": _row_out(t)}


def _next_code(db: Session, tenant_id: int) -> str:
    """code 缺省 TG- + 序号（按现有行数递增，软删行也占号避免复用）。"""
    n = db.query(TargetRegistry).filter(TargetRegistry.tenant_id == tenant_id).count()
    while True:
        n += 1
        code = f"TG-{n:03d}"
        if not db.query(TargetRegistry).filter(TargetRegistry.code == code).first():
            return code


@router.put("/targets/{target_code}", response_model=dict)
async def update_target(
    target_code: str,
    body: TargetUpdate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "update")),
):
    t = (
        db.query(TargetRegistry)
        .filter(TargetRegistry.code == target_code, TargetRegistry.deleted_at.is_(None))
        .first()
    )
    if t is None:
        raise NotFoundError("ES-BIZ-0071", "被测对象不存在")
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    if body.base_url is not None:
        validate_base_url(body.base_url, error_code="ES-TARGET-SSRF")
    for key in ("name", "target_type", "base_url", "chat_path", "protocol", "auth_env",
                 "headers", "request_template", "response_path", "model", "timeout_sec", "status", "remark"):
        val = getattr(body, key)
        if val is not None:
            setattr(t, key, val)
    db.commit()
    db.refresh(t)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="target.update", module="target", request=request,
        detail=f"更新被测系统：{t.name}（{t.code}）",
    )
    return {"code": 0, "message": "ok", "data": _row_out(t)}


@router.delete("/targets/{target_code}", response_model=dict)
async def delete_target(
    target_code: str,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "delete")),
):
    t = (
        db.query(TargetRegistry)
        .filter(TargetRegistry.code == target_code, TargetRegistry.deleted_at.is_(None))
        .first()
    )
    if t is None:
        raise NotFoundError("ES-BIZ-0071", "被测对象不存在")
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    t.deleted_at = datetime.now(timezone.utc)
    t.status = "DISABLED"
    db.commit()
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="target.delete", module="target", request=request,
        detail=f"删除被测系统：{t.name}（{t.code}）",
    )
    return {"code": 0, "message": "ok", "data": {"deleted": True}}


@router.post("/targets/{target_code}/test", response_model=dict)
async def test_target_conn(
    target_code: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "test")),
):
    t = (
        db.query(TargetRegistry)
        .filter(TargetRegistry.code == target_code, TargetRegistry.deleted_at.is_(None))
        .first()
    )
    if t is None:
        raise NotFoundError("ES-BIZ-0071", "被测对象不存在")
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    result = test_target(db, target_code, tenant_id=t.tenant_id)
    return {"code": 0, "message": "ok", "data": result}
