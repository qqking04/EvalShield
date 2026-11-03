# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M12 数据保留路由：策略 CRUD（retention:manage 权限点）。

【硬约束】audit_logs 类型在创建/更新时经 validate_policy 硬拒，
抛 BizError("ES8-RET-0002")——审计日志在任何保留策略下不可清理
（详见 services/retention.py 模块注释）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import AuthContext, ensure_data_scope, require_permission
from ..errors import BizError, NotFoundError
from ..models import RetentionPolicy
from ..services.audit import write_audit
from ..services.retention import validate_policy

router = APIRouter()


class PolicyUpsert(BaseModel):
    artifact_type: str = Field(..., min_length=1, max_length=32)
    days: int = Field(..., ge=1, le=36500, description="保留天数（>0）")
    purge_action: str = Field("delete", description="delete|archive_ref")
    archive_ref: str | None = Field(None, max_length=256)


def _policy_out(p: RetentionPolicy) -> dict:
    return {
        "id": p.id,
        "tenant_id": p.tenant_id,
        "artifact_type": p.artifact_type,
        "days": p.days,
        "purge_action": p.purge_action,
        "archive_ref": p.archive_ref,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def _get_policy(db: Session, policy_id: int) -> RetentionPolicy:
    p = db.query(RetentionPolicy).filter(RetentionPolicy.id == policy_id).first()
    if p is None:
        raise NotFoundError("ES-BIZ-0120", "保留策略不存在")
    return p


@router.get("/policies", response_model=dict)
async def list_policies(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("retention", "manage")),
):
    q = db.query(RetentionPolicy)
    if not auth.is_super_admin:
        q = q.filter(RetentionPolicy.tenant_id == auth.tenant_id)
    rows = q.order_by(RetentionPolicy.artifact_type).all()
    return {
        "code": 0, "message": "ok",
        "data": {
            "items": [_policy_out(p) for p in rows],
            "artifact_types": list(RetentionPolicy.ARTIFACT_TYPES),
            "purge_actions": list(RetentionPolicy.PURGE_ACTIONS),
        },
    }


@router.post("/policies", response_model=dict)
async def create_policy(
    body: PolicyUpsert,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("retention", "manage")),
):
    # audit_logs 硬拒发生处之一（ES8-RET-0002）；未知类型/动作 0001/0003
    validate_policy(body.artifact_type, body.purge_action)
    exists = (
        db.query(RetentionPolicy)
        .filter(
            RetentionPolicy.tenant_id == auth.tenant_id,
            RetentionPolicy.artifact_type == body.artifact_type,
        )
        .first()
    )
    if exists is not None:
        raise BizError("ES-BIZ-0121", "该数据类型已存在保留策略，请直接修改")
    p = RetentionPolicy(
        tenant_id=auth.tenant_id,
        artifact_type=body.artifact_type,
        days=body.days,
        purge_action=body.purge_action,
        archive_ref=body.archive_ref,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="retention.policy.create", module="retention", request=request,
        detail=f"新建保留策略：{p.artifact_type} 保留 {p.days} 天（{p.purge_action}）",
    )
    return {"code": 0, "message": "ok", "data": _policy_out(p)}


@router.put("/policies/{policy_id}", response_model=dict)
async def update_policy(
    policy_id: int,
    body: PolicyUpsert,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("retention", "manage")),
):
    p = _get_policy(db, policy_id)
    await ensure_data_scope(auth, resource_tenant_id=p.tenant_id)
    validate_policy(body.artifact_type, body.purge_action)
    if body.artifact_type != p.artifact_type:
        dup = (
            db.query(RetentionPolicy)
            .filter(
                RetentionPolicy.tenant_id == p.tenant_id,
                RetentionPolicy.artifact_type == body.artifact_type,
                RetentionPolicy.id != policy_id,
            )
            .first()
        )
        if dup is not None:
            raise BizError("ES-BIZ-0121", "该数据类型已存在保留策略")
    p.artifact_type = body.artifact_type
    p.days = body.days
    p.purge_action = body.purge_action
    p.archive_ref = body.archive_ref
    db.commit()
    db.refresh(p)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="retention.policy.update", module="retention", request=request,
        detail=f"修改保留策略 {p.id}：{p.artifact_type} 保留 {p.days} 天（{p.purge_action}）",
    )
    return {"code": 0, "message": "ok", "data": _policy_out(p)}


@router.delete("/policies/{policy_id}", response_model=dict)
async def delete_policy(
    policy_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("retention", "manage")),
):
    p = _get_policy(db, policy_id)
    await ensure_data_scope(auth, resource_tenant_id=p.tenant_id)
    snapshot = _policy_out(p)
    db.delete(p)
    db.commit()
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="retention.policy.delete", module="retention", request=request,
        detail=f"删除保留策略 {policy_id}：{snapshot['artifact_type']}",
    )
    return {"code": 0, "message": "ok", "data": None}
