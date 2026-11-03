# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""管理路由：用户、角色、权限、数据字典、审计日志、API Key、组织机构。

全部接口仅 SUPER_ADMIN / ADMIN 角色可访问（require_permission 校验）。
列表/详情统一展示业务编号（user_no/role_code/...），不展示主键 ID 的业务意义。
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ..api_scopes import SCOPES
from ..database import get_db
from ..deps import AuthContext, authenticate_request, require_permission
from ..enterprise.features import feature_enabled
from ..errors import BizError, NotFoundError
from ..models import (
    ApiKey,
    AuditLog,
    DataDict,
    DictItem,
    LoginAttempt,
    Menu,
    Organization,
    Permission,
    Role,
    RoleMenu,
    RolePermission,
    SystemSetting,
    SystemUser,
    UserRole,
)
from ..schemas import (
    AuditLogOut,
    DictCreate,
    DictOut,
    PermissionOut,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from ..security import (
    generate_api_key,
    generate_totp_secret,
    hash_api_key,
    hash_password,
)
from ..config import Settings, settings
from ..services.audit import write_audit
from ..utils.audit_chain import verify_chain
from ..utils.no import gen_no

router = APIRouter(dependencies=[Depends(require_permission("admin", "*"))])


# ---------------------------------------------------------------------------
# 用户管理
# ---------------------------------------------------------------------------
@router.get("/users", response_model=dict)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    keyword: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    q = db.query(SystemUser).filter(SystemUser.deleted_at.is_(None))
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            SystemUser.username.ilike(like)
            | SystemUser.display_name.ilike(like)
            | SystemUser.email.ilike(like)
        )
    if status:
        q = q.filter(SystemUser.status == status)

    total = q.count()
    rows = (
        q.order_by(SystemUser.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 角色聚合
    user_ids = [u.id for u in rows]
    role_map: dict[int, list[str]] = {}
    if user_ids:
        joins = (
            db.query(UserRole.user_id, Role.role_code)
            .join(Role, UserRole.role_id == Role.id)
            .filter(UserRole.user_id.in_(user_ids))
            .all()
        )
        for uid, code in joins:
            role_map.setdefault(uid, []).append(code)

    items = []
    for u in rows:
        row = UserOut.model_validate(u).model_dump()
        row["roles"] = role_map.get(u.id, [])
        items.append(row)

    return {
        "code": 0,
        "message": "ok",
        "data": {"items": items, "total": total, "page": page, "page_size": page_size},
    }


@router.post("/users", response_model=dict)
async def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    if (
        db.query(SystemUser)
        .filter(SystemUser.username == body.username, SystemUser.deleted_at.is_(None))
        .first()
    ):
        raise BizError("ES-ADMIN-0001", f"用户名 {body.username} 已存在")
    if body.email:
        if (
            db.query(SystemUser)
            .filter(SystemUser.email == body.email, SystemUser.deleted_at.is_(None))
            .first()
        ):
            raise BizError("ES-ADMIN-0001", f"邮箱 {body.email} 已被使用")
    user = SystemUser(
        user_no=gen_no("U"),
        username=body.username,
        display_name=body.display_name,
        email=body.email,
        phone=body.phone,
        org_id=body.org_id,
        title=body.title,
        user_type=body.user_type,
        status=body.status,
        password_hash=hash_password(body.password),
        tenant_id=auth.tenant_id,
        created_by=auth.user_id,
    )
    db.add(user)
    db.flush()
    for rid in body.role_ids:
        db.add(UserRole(user_id=user.id, role_id=rid, tenant_id=auth.tenant_id))
    db.commit()
    db.refresh(user)
    return {
        "code": 0,
        "message": "ok",
        "data": UserOut.model_validate(user).model_dump(),
    }


@router.put("/users/{user_id}", response_model=dict)
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    user = db.get(SystemUser, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFoundError("ES-ADMIN-0002", "用户不存在")
    data = body.model_dump(exclude_unset=True)
    if "role_ids" in data:
        role_ids = data.pop("role_ids")
        db.query(UserRole).filter(
            UserRole.user_id == user_id, UserRole.tenant_id == auth.tenant_id
        ).delete()
        for rid in role_ids:
            db.add(UserRole(user_id=user_id, role_id=rid, tenant_id=auth.tenant_id))
    for k, v in data.items():
        setattr(user, k, v)
    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.delete("/users/{user_id}", response_model=dict)
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    if user_id == auth.user_id:
        raise BizError("ES-ADMIN-0003", "不能删除当前登录用户")
    user = db.get(SystemUser, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFoundError("ES-ADMIN-0002", "用户不存在")
    if user.username == "admin":
        raise BizError("ES-ADMIN-0003", "内置管理员不可删除")
    user.deleted_at = datetime.now(timezone.utc)
    user.status = "DISABLED"
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.post("/users/{user_id}/reset-password", response_model=dict)
async def reset_password(user_id: int, db: Session = Depends(get_db)):
    user = db.get(SystemUser, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFoundError("ES-ADMIN-0002", "用户不存在")
    new_pwd = "EvalShield@123"
    user.password_hash = hash_password(new_pwd)
    user.login_fail_count = 0
    user.locked_until = None
    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": {"new_password": new_pwd}}


@router.post("/users/{user_id}/toggle-mfa", response_model=dict)
async def toggle_mfa(user_id: int, enabled: bool, db: Session = Depends(get_db)):
    user = db.get(SystemUser, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFoundError("ES-ADMIN-0002", "用户不存在")
    if enabled and not user.mfa_secret:
        user.mfa_secret = generate_totp_secret()
    user.mfa_enabled = enabled
    db.commit()
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "mfa_enabled": user.mfa_enabled,
            "secret": user.mfa_secret if enabled else None,
        },
    }


# ---------------------------------------------------------------------------
# 角色管理
# ---------------------------------------------------------------------------
@router.get("/roles", response_model=dict)
async def list_roles(db: Session = Depends(get_db)):
    rows = db.query(Role).filter(Role.deleted_at.is_(None)).order_by(Role.id).all()
    perm_map: dict[int, list[str]] = {}
    menu_map: dict[int, list[int]] = {}
    if rows:
        ids = [r.id for r in rows]
        perm_rows = (
            db.query(RolePermission.role_id, RolePermission.perm_code)
            .filter(RolePermission.role_id.in_(ids))
            .all()
        )
        for rid, code in perm_rows:
            perm_map.setdefault(rid, []).append(code)
        menu_rows = (
            db.query(RoleMenu.role_id, RoleMenu.menu_id)
            .filter(RoleMenu.role_id.in_(ids))
            .all()
        )
        for rid, mid in menu_rows:
            menu_map.setdefault(rid, []).append(mid)
    items = []
    for r in rows:
        row = RoleOut.model_validate(r).model_dump()
        row["perm_codes"] = perm_map.get(r.id, [])
        row["menu_ids"] = menu_map.get(r.id, [])
        items.append(row)
    return {"code": 0, "message": "ok", "data": {"items": items, "total": len(items)}}


@router.post("/roles", response_model=dict)
async def create_role(
    body: RoleCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    if (
        db.query(Role)
        .filter(Role.role_code == body.role_code, Role.deleted_at.is_(None))
        .first()
    ):
        raise BizError("ES-ADMIN-0001", f"角色编码 {body.role_code} 已存在")
    role = Role(
        role_code=body.role_code,
        role_name=body.role_name,
        description=body.description,
        tenant_id=auth.tenant_id,
        created_by=auth.user_id,
    )
    db.add(role)
    db.flush()
    for code in body.perm_codes:
        if db.query(Permission).filter(Permission.perm_code == code).first():
            db.add(RolePermission(role_id=role.id, perm_code=code))
    for mid in body.menu_ids:
        if db.query(Menu).filter(Menu.id == mid).first():
            db.add(RoleMenu(role_id=role.id, menu_id=mid))
    db.commit()
    db.refresh(role)
    return {
        "code": 0,
        "message": "ok",
        "data": RoleOut.model_validate(role).model_dump(),
    }


@router.put("/roles/{role_id}", response_model=dict)
async def update_role(role_id: int, body: RoleUpdate, db: Session = Depends(get_db)):
    role = db.get(Role, role_id)
    if role is None or role.deleted_at is not None:
        raise NotFoundError("ES-ADMIN-0002", "角色不存在")
    data = body.model_dump(exclude_unset=True)
    if "perm_codes" in data:
        codes = data.pop("perm_codes")
        db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
        for code in codes:
            if db.query(Permission).filter(Permission.perm_code == code).first():
                db.add(RolePermission(role_id=role_id, perm_code=code))
    if "menu_ids" in data:
        mids = data.pop("menu_ids")
        db.query(RoleMenu).filter(RoleMenu.role_id == role_id).delete()
        valid_ids = {m[0] for m in db.query(Menu.id).filter(Menu.deleted_at.is_(None)).all()}
        for mid in mids:
            if mid in valid_ids:
                db.add(RoleMenu(role_id=role_id, menu_id=mid))
    for k, v in data.items():
        setattr(role, k, v)
    role.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.delete("/roles/{role_id}", response_model=dict)
async def delete_role(role_id: int, db: Session = Depends(get_db)):
    role = db.get(Role, role_id)
    if role is None or role.deleted_at is not None:
        raise NotFoundError("ES-ADMIN-0002", "角色不存在")
    if role.is_system:
        raise BizError("ES-ADMIN-0003", "系统内置角色不可删除")
    if db.query(UserRole).filter(UserRole.role_id == role_id).first():
        raise BizError("ES-ADMIN-0003", "该角色下仍有用户，不能删除")
    role.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


# ---------------------------------------------------------------------------
# 权限点
# ---------------------------------------------------------------------------
@router.get("/permissions", response_model=dict)
async def list_permissions(db: Session = Depends(get_db)):
    rows = (
        db.query(Permission)
        .order_by(Permission.module, Permission.sort_order, Permission.id)
        .all()
    )
    items = [PermissionOut.model_validate(p).model_dump() for p in rows]
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": items, "total": len(items)},
    }


# ---------------------------------------------------------------------------
# 数据字典
# ---------------------------------------------------------------------------
@router.get("/dicts", response_model=dict)
async def list_dicts(keyword: str | None = None, db: Session = Depends(get_db)):
    q = db.query(DataDict).filter(DataDict.deleted_at.is_(None))
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(DataDict.dict_code.ilike(like) | DataDict.dict_name.ilike(like))
    rows = q.order_by(DataDict.id).all()
    dict_ids = [d.id for d in rows]
    items_map: dict[int, list] = {}
    if dict_ids:
        dict_items = (
            db.query(DictItem)
            .filter(DictItem.dict_id.in_(dict_ids), DictItem.deleted_at.is_(None))
            .order_by(DictItem.sort_order, DictItem.id)
            .all()
        )
        for it in dict_items:
            items_map.setdefault(it.dict_id, []).append(
                {
                    "id": it.id,
                    "item_label": it.item_label,
                    "item_value": it.item_value,
                    "sort_order": it.sort_order,
                    "ext": it.ext,
                    "status": it.status,
                }
            )
    items = []
    for d in rows:
        row = DictOut.model_validate(d).model_dump()
        row["items"] = items_map.get(d.id, [])
        items.append(row)
    return {"code": 0, "message": "ok", "data": {"items": items, "total": len(items)}}


@router.post("/dicts", response_model=dict)
async def create_dict(
    body: DictCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    if (
        db.query(DataDict)
        .filter(DataDict.dict_code == body.dict_code, DataDict.deleted_at.is_(None))
        .first()
    ):
        raise BizError("ES-ADMIN-0001", f"字典编码 {body.dict_code} 已存在")
    d = DataDict(
        dict_code=body.dict_code,
        dict_name=body.dict_name,
        dict_type=body.dict_type,
        description=body.description,
        created_by=auth.user_id,
    )
    db.add(d)
    db.flush()
    for it in body.items:
        db.add(
            DictItem(
                dict_id=d.id,
                item_label=it.item_label,
                item_value=it.item_value,
                sort_order=it.sort_order,
                ext=it.ext,
                status=it.status,
            )
        )
    db.commit()
    return {"code": 0, "message": "ok", "data": {"dict_code": d.dict_code}}


@router.put("/dicts/{dict_id}", response_model=dict)
async def update_dict(
    dict_id: int,
    body: DictCreate,
    db: Session = Depends(get_db),
):
    d = db.get(DataDict, dict_id)
    if d is None or d.deleted_at is not None:
        raise NotFoundError("ES-ADMIN-0002", "字典不存在")
    if d.is_system:
        raise BizError("ES-ADMIN-0003", "系统内置字典不可编辑")
    if (
        db.query(DataDict)
        .filter(
            DataDict.dict_code == body.dict_code,
            DataDict.id != dict_id,
            DataDict.deleted_at.is_(None),
        )
        .first()
    ):
        raise BizError("ES-ADMIN-0001", f"字典编码 {body.dict_code} 已存在")
    d.dict_code = body.dict_code
    d.dict_name = body.dict_name
    d.dict_type = body.dict_type
    d.description = body.description
    # 字典项整体替换（旧项软删 + 新项插入）
    now = datetime.now(timezone.utc)
    db.query(DictItem).filter(
        DictItem.dict_id == dict_id, DictItem.deleted_at.is_(None)
    ).update({"deleted_at": now}, synchronize_session=False)
    for it in body.items:
        db.add(
            DictItem(
                dict_id=dict_id,
                item_label=it.item_label,
                item_value=it.item_value,
                sort_order=it.sort_order,
                ext=it.ext,
                status=it.status,
            )
        )
    db.commit()
    return {"code": 0, "message": "ok", "data": {"dict_code": d.dict_code}}


@router.delete("/dicts/{dict_id}", response_model=dict)
async def delete_dict(dict_id: int, db: Session = Depends(get_db)):
    d = db.get(DataDict, dict_id)
    if d is None or d.deleted_at is not None:
        raise NotFoundError("ES-ADMIN-0002", "字典不存在")
    if d.is_system:
        raise BizError("ES-ADMIN-0003", "系统内置字典不可删除")
    d.deleted_at = datetime.now(timezone.utc)
    db.query(DictItem).filter(DictItem.dict_id == dict_id).update(
        {"deleted_at": datetime.now(timezone.utc)}
    )
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------
@router.get("/audit-logs", response_model=dict)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    action: str | None = None,
    module: str | None = None,
    result: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if module:
        q = q.filter(AuditLog.module == module)
    if result:
        q = q.filter(AuditLog.result == result)
    if start_time:
        q = q.filter(AuditLog.created_at >= start_time)
    if end_time:
        q = q.filter(AuditLog.created_at <= end_time)
    total = q.count()
    rows = (
        q.order_by(AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [AuditLogOut.model_validate(r).model_dump() for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


# ---------------------------------------------------------------------------
# API Key 管理
# ---------------------------------------------------------------------------
@router.get("/api-keys", response_model=dict)
async def list_api_keys(
    db: Session = Depends(get_db), auth: AuthContext = Depends(authenticate_request)
):
    rows = (
        db.query(ApiKey)
        .filter(ApiKey.deleted_at.is_(None), ApiKey.tenant_id == auth.tenant_id)
        .order_by(ApiKey.id.desc())
        .all()
    )
    items = [
        {
            "id": k.id,
            "key_name": k.key_name,
            "key_prefix": k.key_prefix,
            "scopes": k.scopes,
            "expires_at": k.expires_at,
            "last_used_at": k.last_used_at,
            "disabled": k.disabled,
            "created_at": k.created_at,
        }
        for k in rows
    ]
    return {"code": 0, "message": "ok", "data": {"items": items, "total": len(items)}}


@router.post("/api-keys", response_model=dict)
async def create_api_key(
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """创建 API Key，明文仅返回一次。"""
    key_name = (body.get("key_name") or "default").strip()
    scopes = body.get("scopes") or []
    if not isinstance(scopes, list) or not scopes:
        raise BizError(
            "ES-ADMIN-0005", "新 Key 必须至少选择一个权限范围（scopes）", http_status=422
        )
    unknown = [s for s in scopes if s not in SCOPES]
    if unknown:
        raise BizError(
            "ES-ADMIN-0006", f"未知的权限范围：{', '.join(unknown)}", http_status=422
        )
    plain = generate_api_key()
    k = ApiKey(
        key_name=key_name,
        key_prefix=plain[:8],
        key_hash=hash_api_key(plain),
        user_id=auth.user_id,
        tenant_id=auth.tenant_id,
        scopes=scopes,
    )
    db.add(k)
    db.commit()
    return {
        "code": 0,
        "message": "ok",
        "data": {"id": k.id, "api_key": plain, "key_prefix": plain[:8]},
    }


@router.delete("/api-keys/{key_id}", response_model=dict)
async def delete_api_key(key_id: int, db: Session = Depends(get_db)):
    k = db.get(ApiKey, key_id)
    if k is None or k.deleted_at is not None:
        raise NotFoundError("ES-ADMIN-0002", "API Key 不存在")
    k.disabled = True
    k.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


# ---------------------------------------------------------------------------
# 组织机构
# ---------------------------------------------------------------------------
@router.get("/organizations", response_model=dict)
async def list_organizations(db: Session = Depends(get_db)):
    rows = (
        db.query(Organization)
        .filter(Organization.deleted_at.is_(None))
        .order_by(Organization.sort_order, Organization.id)
        .all()
    )
    # ES10-P-07：成员归属计数（SystemUser.org_id 分组，单次批量查询）
    counts = dict(
        db.query(SystemUser.org_id, func.count(SystemUser.id))
        .filter(SystemUser.deleted_at.is_(None), SystemUser.org_id.isnot(None))
        .group_by(SystemUser.org_id)
        .all()
    )
    return {
        "code": 0,
        "message": "ok",
        "data": [
            {
                "id": o.id,
                "org_no": o.org_no,
                "org_name": o.org_name,
                "parent_id": o.parent_id,
                "org_path": o.org_path,
                "sort_order": o.sort_order,
                "status": o.status,
                "member_count": counts.get(o.id, 0),
            }
            for o in rows
        ],
    }


@router.post("/organizations", response_model=dict)
async def create_organization(
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    # 企业能力位闸门：创建组织/租户属 multi_tenant 能力（规划 §12.4）
    if not feature_enabled("multi_tenant"):
        raise BizError(
            "ES-LIC-0003",
            "创建组织为企业版能力（multi_tenant），请先激活含该能力的 License",
            http_status=403,
        )
    name = (body.get("org_name") or "").strip()
    if not name:
        raise BizError("ES-ADMIN-0004", "部门名称不能为空")
    parent_id = body.get("parent_id")
    org = Organization(
        org_no=gen_no("ORG"),
        org_name=name,
        parent_id=parent_id,
        sort_order=int(body.get("sort_order") or 0),
        tenant_id=auth.tenant_id,
    )
    if parent_id:
        parent = db.get(Organization, parent_id)
        if parent:
            org.org_path = f"{parent.org_path}{parent.id}/"
    db.add(org)
    db.commit()
    db.refresh(org)
    return {"code": 0, "message": "ok", "data": {"id": org.id, "org_no": org.org_no}}


@router.delete("/organizations/{org_id}", response_model=dict)
async def delete_organization(org_id: int, db: Session = Depends(get_db)):
    org = db.get(Organization, org_id)
    if org is None or org.deleted_at is not None:
        raise NotFoundError("ES-ADMIN-0002", "部门不存在")
    if (
        db.query(SystemUser)
        .filter(SystemUser.org_id == org_id, SystemUser.deleted_at.is_(None))
        .first()
    ):
        raise BizError("ES-ADMIN-0003", "该部门下仍有用户，不能删除")
    org.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


# ---------------------------------------------------------------------------
# 审计日志校验（第 2 章）
# ---------------------------------------------------------------------------
@router.get("/audit-logs/verify", response_model=dict)
async def audit_logs_verify(
    tenant_id: int | None = None,
    db: Session = Depends(get_db),
):
    """校验审计日志链完整性。"""
    if not settings.AUDIT_LOG_VERIFY_CHAIN:
        return {
            "code": 0,
            "message": "ok",
            "data": {"enabled": False, "reason": "AUDIT_LOG_VERIFY_CHAIN is disabled"},
        }
    result = verify_chain(db, tenant_id=tenant_id)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "enabled": True,
            "valid": result["valid"],
            "total": result["total"],
            "legacy_count": result.get("legacy_count", 0),
            "first_index": result["first_index"],
            "last_index": result["last_index"],
            "breaks": result["breaks"],
            "missing_indices": result["missing_indices"],
        },
    }


@router.post("/audit-logs/archive", response_model=dict)
async def audit_logs_archive(
    log_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """软归档单条审计日志（仅 SUPER_ADMIN）。"""
    if not auth.is_super_admin:
        raise BizError("ES-AUTH-0006", "仅超级管理员可归档审计日志")
    log = db.get(AuditLog, log_id)
    if log is None:
        raise NotFoundError("ES-ADMIN-0002", "日志不存在")
    from datetime import datetime, timezone

    archived_at = datetime.now(timezone.utc)
    # 通过原生 SQL 绕过触发器仅更新 archived_at
    db.execute(
        text(
            """
            UPDATE audit_logs
            SET archived_at = :archived_at
            WHERE id = :log_id
            """
        ),
        {"archived_at": archived_at, "log_id": log_id},
    )
    db.commit()
    return {
        "code": 0,
        "message": "ok",
        "data": {"archived_at": archived_at.isoformat()},
    }


# ---------------------------------------------------------------------------
# 统计（仪表盘用）
# ---------------------------------------------------------------------------
@router.get("/stats", response_model=dict)
async def admin_stats(db: Session = Depends(get_db)):
    user_total = (
        db.query(func.count(SystemUser.id))
        .filter(SystemUser.deleted_at.is_(None))
        .scalar()
        or 0
    )
    role_total = (
        db.query(func.count(Role.id)).filter(Role.deleted_at.is_(None)).scalar() or 0
    )
    dict_total = (
        db.query(func.count(DataDict.id)).filter(DataDict.deleted_at.is_(None)).scalar()
        or 0
    )
    audit_total = db.query(func.count(AuditLog.id)).scalar() or 0
    menu_total = db.query(func.count(Menu.id)).filter(Menu.deleted_at.is_(None)).scalar() or 0
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "user_total": user_total,
            "role_total": role_total,
            "dict_total": dict_total,
            "audit_total": audit_total,
            "menu_total": menu_total,
        },
    }


# ============================================================================
# 菜单管理 CRUD（admin:*）
# ============================================================================

@router.get("/menus", response_model=dict)
def list_menus(db: Session = Depends(get_db), _: AuthContext = Depends(require_permission("admin", "menu"))):
    """返回完整菜单树（含所有 type，供管理端展示）。"""
    rows = db.query(Menu).filter(Menu.deleted_at.is_(None)).order_by(Menu.parent_id, Menu.sort_order).all()
    tree = _build_menu_tree(rows)
    # 附带菜单绑定的角色（管理端用于分配）
    role_bindings = db.query(RoleMenu.menu_id, Role.role_code).join(Role, RoleMenu.role_id == Role.id).all()
    bindings_map: dict[int, list[str]] = {}
    for mid, rcode in role_bindings:
        bindings_map.setdefault(mid, []).append(rcode)
    return {"code": 0, "message": "ok", "data": {"items": tree, "total": len(rows), "bindings": bindings_map}}


@router.post("/menus", response_model=dict)
def create_menu(body: dict, db: Session = Depends(get_db), _: AuthContext = Depends(require_permission("admin", "menu"))):
    m = Menu(
        parent_id=body.get("parent_id"),
        path=body["path"],
        component=body.get("component"),
        icon=body.get("icon"),
        title=body["title"],
        perm=body.get("perm"),
        sort_order=body.get("sort_order", 0),
        visible=body.get("visible", True),
        menu_type=body.get("menu_type", "menu"),
        remark=body.get("remark"),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"code": 0, "message": "ok", "data": _menu_to_dict(m)}


# ⚠️ 必须在 /menus/{menu_id} 之前定义 —— FastAPI 先匹配静态路径
@router.put("/menus/{menu_id}/reorder", response_model=dict)
def reorder_menu(menu_id: int, body: dict, db: Session = Depends(get_db), _: AuthContext = Depends(require_permission("admin", "menu"))):
    """拖拽排序：将同一 parent 下全部 menu_id 按 body.order 重新设置 sort_order。"""
    order = body.get("order") or []
    for i, mid in enumerate(order):
        db.query(Menu).filter(Menu.id == mid).update({Menu.sort_order: i})
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.put("/menus/{menu_id}/roles", response_model=dict)
def bind_menu_roles(menu_id: int, body: dict, db: Session = Depends(get_db), _: AuthContext = Depends(require_permission("admin", "menu"))):
    """给某个菜单绑定哪些角色可见（清空后重绑）。"""
    role_ids: list[int] = body.get("role_ids") or []
    db.query(RoleMenu).filter(RoleMenu.menu_id == menu_id).delete()
    for rid in role_ids:
        db.execute(text(
            "INSERT INTO role_menus (role_id, menu_id, created_at) VALUES (:r, :m, now()) ON CONFLICT DO NOTHING"
        ), {"r": rid, "m": menu_id})
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.put("/menus/{menu_id}", response_model=dict)
def update_menu(menu_id: int, body: dict, db: Session = Depends(get_db), _: AuthContext = Depends(require_permission("admin", "menu"))):
    m = db.query(Menu).filter(Menu.id == menu_id).first()
    if not m:
        raise NotFoundError("菜单不存在")
    for f in ("parent_id", "path", "component", "icon", "title", "perm", "sort_order", "visible", "menu_type", "remark"):
        if f in body:
            setattr(m, f, body[f])
    db.commit()
    db.refresh(m)
    return {"code": 0, "message": "ok", "data": _menu_to_dict(m)}


@router.delete("/menus/{menu_id}", response_model=dict)
def delete_menu(menu_id: int, db: Session = Depends(get_db), _: AuthContext = Depends(require_permission("admin", "menu"))):
    m = db.query(Menu).filter(Menu.id == menu_id).first()
    if not m:
        raise NotFoundError("菜单不存在")
    m.deleted_at = datetime.now(timezone.utc)
    # 同时软删子菜单
    db.query(Menu).filter(Menu.parent_id == menu_id).update({Menu.deleted_at: datetime.now(timezone.utc)})
    # 清 role_menus
    db.query(RoleMenu).filter(RoleMenu.menu_id == menu_id).delete()
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


# ============================================================================
# 系统参数 settings（admin:setting）
# ============================================================================

@router.get("/settings", response_model=dict)
def list_settings(group: str | None = Query(None), db: Session = Depends(get_db), _: AuthContext = Depends(require_permission("admin", "setting"))):
    q = db.query(SystemSetting)
    if group:
        q = q.filter(SystemSetting.setting_group == group)
    rows = q.order_by(SystemSetting.setting_group, SystemSetting.setting_key).all()
    # 脱敏 secret 值
    items = []
    for s in rows:
        d = {
            "id": s.id, "group": s.setting_group, "key": s.setting_key,
            "value": "******" if s.is_secret and s.setting_value else s.setting_value,
            "value_type": s.value_type, "description": s.description,
            "is_secret": s.is_secret, "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        items.append(d)
    return {"code": 0, "message": "ok", "data": {"items": items, "groups": sorted({s.setting_group for s in rows})}}


@router.put("/settings/batch", response_model=dict)
def update_settings_batch(body: dict, db: Session = Depends(get_db), auth: AuthContext = Depends(authenticate_request)):
    """批量更新 settings（body.items = [{id, value}]）。"""
    items: list[dict] = body.get("items") or []
    # 企业能力位闸门：brand 组（白标品牌）仅 whitelabel 授权后可编辑（规划 §12.4）
    if not feature_enabled("whitelabel"):
        brand_ids = {
            s.id
            for s in db.query(SystemSetting).filter(SystemSetting.setting_group == "brand").all()
        }
        for it in items:
            if it.get("group") == "brand" or (it.get("id") in brand_ids and it.get("id") is not None):
                raise BizError(
                    "ES-LIC-0003",
                    "品牌白标为企业版能力（whitelabel），请先激活含该能力的 License",
                    http_status=403,
                )
    for it in items:
        sid = it.get("id")
        if sid:
            db.query(SystemSetting).filter(SystemSetting.id == sid).update({
                SystemSetting.setting_value: it.get("value"),
                SystemSetting.updated_by: auth.user_id,
            })
        else:
            # group + key 定位
            db.execute(text("""
                INSERT INTO system_settings (setting_group, setting_key, setting_value, updated_by)
                VALUES (:g, :k, :v, :uid)
                ON CONFLICT (setting_group, setting_key) DO UPDATE SET
                    setting_value = EXCLUDED.setting_value, updated_by = EXCLUDED.updated_by
            """), {"g": it.get("group"), "k": it.get("key"), "v": it.get("value"), "uid": auth.user_id})
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


# ============================================================================
# 登录日志 login-logs（已有表 login_attempts）
# ============================================================================

@router.get("/login-logs", response_model=dict)
def list_login_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = Query(None),
    username: str | None = Query(None),
    ip: str | None = Query(None),
    db: Session = Depends(get_db),
    _: AuthContext = Depends(require_permission("admin", "log")),
):
    q = db.query(LoginAttempt)
    if status:
        q = q.filter(LoginAttempt.success == (status == "success"))
    if username:
        q = q.filter(LoginAttempt.username.ilike(f"%{username}%"))
    if ip:
        q = q.filter(LoginAttempt.ip.ilike(f"%{ip}%"))
    total = q.count()
    rows = q.order_by(LoginAttempt.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for r in rows:
        items.append({
            "id": r.id, "username": r.username, "ip": r.ip,
            "success": r.success, "fail_reason": r.fail_reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"code": 0, "message": "ok", "data": {"items": items, "total": total, "page": page, "page_size": page_size}}


# ============================================================================
# 公开路由：按当前用户角色返回可见菜单树（不含 admin:* 权限，需登录即可）
# 此 router 单独挂（main.py include_router 时不带 admin:* 依赖）
# ============================================================================

router_public = APIRouter()


@router_public.get("/menus/me", response_model=dict)
def get_my_menus(db: Session = Depends(get_db), auth: AuthContext = Depends(authenticate_request)):
    """按当前用户的 roles + permissions 返回前端可见菜单树。

    SUPER_ADMIN / is_super_admin → 全量返回；
    非超管：先按 perms 过滤（功能权限驱动），再按 role_menus 做交集（菜单可见性驱动）。
    如果角色未绑定 role_menus（历史数据），回退到纯 perms 过滤保证不丢菜单。
    """
    perms_set: set[str] = auth.perms or set()

    all_rows = db.query(Menu).filter(
        Menu.deleted_at.is_(None), Menu.visible.is_(True)
    ).order_by(Menu.parent_id, Menu.sort_order).all()

    if auth.is_super_admin:
        rows = all_rows
    else:
        # Step 1: 按 perms 过滤（功能权限驱动）
        perm_ok_ids: set[int] = set()
        id_to_menu: dict[int, Menu] = {m.id: m for m in all_rows}
        for m in all_rows:
            if not m.perm:
                perm_ok_ids.add(m.id); continue
            if m.perm in perms_set:
                perm_ok_ids.add(m.id); continue
            pref = m.perm.split(":")[0] + ":*"
            if pref in perms_set or "*" in perms_set:
                perm_ok_ids.add(m.id)

        # Step 2: 查 role_menus（菜单可见性驱动）
        role_ids = [r[0] for r in db.query(Role.id).filter(
            Role.role_code.in_(auth.roles or []), Role.deleted_at.is_(None)
        ).all()]
        menu_binding_ids: set[int] = set()
        if role_ids:
            menu_binding_ids = {
                r[0] for r in db.query(RoleMenu.menu_id).filter(
                    RoleMenu.role_id.in_(role_ids)
                ).all()
            }

        if menu_binding_ids:
            # 交集：必须同时有权限 + 菜单绑定
            visible_ids = perm_ok_ids & menu_binding_ids
        else:
            # 无 role_menus 绑定 → 回退纯 perms（向后兼容）
            visible_ids = perm_ok_ids

        # Step 3: 补祖先链（子菜单可见 → 父目录也必须显示）
        ancestor_ids: set[int] = set(visible_ids)
        changed = True
        while changed:
            changed = False
            for mid in list(ancestor_ids):
                m = id_to_menu.get(mid)
                if m and m.parent_id and m.parent_id not in ancestor_ids:
                    ancestor_ids.add(m.parent_id)
                    changed = True

        rows = [m for m in all_rows if m.id in ancestor_ids]

    tree = _build_menu_tree(rows)
    return {"code": 0, "message": "ok", "data": {"items": tree}}


# ============================================================================
# 版本形态运维 edition-ops（仅 SUPER_ADMIN；预览 → 切换 .env → 受控重启）
#
# 背景（优化9 §1.4 两维度）：部署形态 EDITION 由环境变量 + .env + 进程重启决定，
# 不是运行时开关。本段提供运维侧受控流程：
#   GET  /edition-ops/current  现形态 + .env 值漂移检测 + License 态
#   POST /edition-ops/preview  目标形态影响清单（模块差集 / 密钥预检 / 警告）
#   POST /edition-ops/switch   预检通过后原子重写 backend/.env 的 EDITION 行
#   POST /edition-ops/restart  以 .env 新值强制注入进程环境，拉起分离新进程后自终止
# 审计：switch / restart 均强制 write_audit。
# ============================================================================

_EDITION_VALUES = ("community", "saas", "enterprise")
_EDITION_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
_EDITION_ENV_FILE = _EDITION_BACKEND_DIR / ".env"
# 与 config.assert_production_safe 同规则（复用其口径，目标形态下预检）
_EDITION_INSECURE = set(Settings._INSECURE) if hasattr(Settings, "_INSECURE") else {
    "EvalShield-dev-secret-change-me-in-prod-2026",
    "EvalShield-webhook-secret-dev",
}


def _require_super_admin(auth: AuthContext) -> None:
    if not auth.is_super_admin:
        raise BizError("ES-ADMIN-0006", "版本形态运维仅超级管理员可执行", http_status=403)


def _read_env_edition() -> str | None:
    """读 backend/.env 中 EDITION= 行的当前值（无文件/无行返回 None）。"""
    if not _EDITION_ENV_FILE.exists():
        return None
    for raw in _EDITION_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "EDITION":
            return value.strip().strip('"').strip("'").lower() or None
    return None


def _secret_precheck(target: str) -> list[str]:
    """目标形态下 SECRET_KEY / WEBHOOK_SECRET 是否满足 fail-fast（返回违规项）。"""
    if target not in ("enterprise", "saas"):
        return []  # community 放行（与 config.assert_production_safe 口径一致）
    return [
        k for k in ("SECRET_KEY", "WEBHOOK_SECRET")
        if getattr(settings, k) in _EDITION_INSECURE or len(getattr(settings, k) or "") < 32
    ]


def _edition_preview_payload(target: str) -> dict:
    """构建预览影响清单（preview 与 switch 共用，switch 复跑保证最终一致）。"""
    from ..plans import _enabled_modules, resolve_flags

    current = settings.EDITION
    nav_profile = settings.NAV_PROFILE
    flags_before = resolve_flags(current, nav_profile)
    flags_after = resolve_flags(target, nav_profile)
    modules_before = _enabled_modules(current, None)
    modules_after = _enabled_modules(target, None)
    checks: list[dict] = []
    bad_secrets = _secret_precheck(target)
    checks.append({
        "key": "secrets",
        "label": "生产密钥预检（SECRET_KEY / WEBHOOK_SECRET ≥32 位且非默认值）",
        "ok": not bad_secrets,
        "detail": ("通过" if not bad_secrets
                   else f"目标形态 {target} 将拒绝启动：{','.join(bad_secrets)} 不合规"),
    })
    warnings: list[str] = []
    if target == "community":
        warnings.append(
            "切换后 app/commercial/ 整棵商业路由树将不挂载（计费、License、平台运营、"
            "租户等页面 404），本地已订阅数据保留但不可访问。"
        )
    if target == "enterprise":
        warnings.append(
            "企业版形态需激活 License 才能解锁商业能力；未激活时商业端点按 License 闸门降级。"
        )
    if target == "saas":
        warnings.append("SaaS 形态开放平台运营区（/api/tenants 等），依赖订阅态数据。")
    warnings.append(
        "前端 __EDITION__ 为构建期常量：dev 需以对应 EDITION 环境变量重启 vite，"
        "生产需重新构建前端，否则页面门控与后端形态不一致。"
    )
    if nav_profile == "full":
        warnings.append(
            f"NAV_PROFILE=full（当前），导航不收敛——形态切换只影响商业路由挂载与模块能力，"
            f"不改变导航入口可见性。"
        )
    lost_modules = sorted(modules_before - modules_after)
    gained_modules = sorted(modules_after - modules_before)
    return {
        "current": current,
        "target": target,
        "ok_to_switch": not bad_secrets,
        "checks": checks,
        "impact": {
            "commercial_mounted_after": target != "community",
            "platform_available_after": target == "saas",
            "modules_current": sorted(modules_before),
            "modules_after": sorted(modules_after),
            "modules_lost": lost_modules,
            "modules_gained": gained_modules,
            "nav_flags_off_after": sorted(k for k, v in flags_after.items() if not v),
        },
        "warnings": warnings,
    }


@router.get("/edition-ops/current", response_model=dict)
async def edition_ops_current(
    request: Request,
    auth: AuthContext = Depends(authenticate_request),
):
    """当前形态实态 + .env 期望值 + 漂移提示 + License 三态。"""
    _require_super_admin(auth)
    from ..license_state import resolve_license_state

    license_status = getattr(request.app.state, "license_status", None) or {}
    lic = resolve_license_state(license_status, settings.LICENSE_GRACE_DAYS) or {}
    file_edition = _read_env_edition()
    runtime_edition = settings.EDITION
    drift = file_edition is not None and file_edition != runtime_edition
    return {"code": 0, "message": "ok", "data": {
        "runtime_edition": runtime_edition,
        "env_file_edition": file_edition,
        "drift": drift,
        "drift_hint": (
            f".env 中 EDITION={file_edition}，但运行进程为 {runtime_edition}"
            "（启动时存在显式进程环境变量覆盖，或尚未重启）。一键重启将以 .env 值为准。"
            if drift else ""
        ),
        "commercial_mounted": bool(getattr(request.app.state, "commercial_mounted", False)),
        "nav_profile": settings.NAV_PROFILE,
        "license": {
            "valid": bool(license_status.get("valid")),
            "reason": license_status.get("reason") or "",
            "expires_at": license_status.get("expires_at"),
            "phase": lic.get("phase"),
        },
        "frontend_build_edition": None,  # 后端不可知，前端页自行展示 __EDITION__
        "allowed_editions": list(_EDITION_VALUES),
    }}


@router.post("/edition-ops/preview", response_model=dict)
async def edition_ops_preview(
    body: dict,
    auth: AuthContext = Depends(authenticate_request),
):
    """目标形态影响预览（不落任何变更，可反复调用）。"""
    _require_super_admin(auth)
    target = str(body.get("target") or "").strip().lower()
    if target not in _EDITION_VALUES:
        raise BizError("ES-ADMIN-0007", f"EDITION 非法值: {target!r}（允许 {'/'.join(_EDITION_VALUES)}）", http_status=400)
    return {"code": 0, "message": "ok", "data": _edition_preview_payload(target)}


@router.post("/edition-ops/switch", response_model=dict)
def edition_ops_switch(
    request: Request,
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """把目标形态写入 backend/.env（不重启不生效；重启用 restart 端点）。"""
    _require_super_admin(auth)
    target = str(body.get("target") or "").strip().lower()
    confirm = str(body.get("confirm") or "").strip().lower()
    if target not in _EDITION_VALUES:
        raise BizError("ES-ADMIN-0007", f"EDITION 非法值: {target!r}（允许 {'/'.join(_EDITION_VALUES)}）", http_status=400)
    if confirm != target:
        raise BizError("ES-ADMIN-0008", "危险操作：confirm 必须与目标形态一致", http_status=400)

    payload = _edition_preview_payload(target)
    if not payload["ok_to_switch"]:
        detail = "；".join(c["detail"] for c in payload["checks"] if not c["ok"])
        write_audit(
            db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
            action="admin.edition_switch", module="admin", request=request,
            result="FAILED", error_msg=detail,
            detail=f"target={target} 预检失败: {detail}",
        )
        raise BizError("ES-ADMIN-0009", f"预检失败，拒绝写入 .env：{detail}", http_status=409)

    if not _EDITION_ENV_FILE.exists():
        raise BizError("ES-ADMIN-0010", f"未找到 {_EDITION_ENV_FILE}，请先按部署脚本生成 .env", http_status=500)

    # 行替换：仅改 EDITION= 行，保留其余内容与注释；无该行则追加。原子写（tmp + replace）。
    lines = _EDITION_ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=False)
    replaced = False
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and stripped.split("=", 1)[0].strip() == "EDITION":
            lines[i] = f"EDITION={target}"
            replaced = True
            break
    if not replaced:
        lines.append(f"EDITION={target}")
    tmp = _EDITION_ENV_FILE.with_suffix(".env.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, _EDITION_ENV_FILE)

    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="admin.edition_switch", module="admin", request=request,
        result="SUCCESS",
        detail=f"{settings.EDITION} -> {target}（写入 {_EDITION_ENV_FILE.name}，待重启生效）",
    )
    return {"code": 0, "message": "ok", "data": {
        "env_file_edition": target,
        "runtime_edition": settings.EDITION,
        "applied": target == settings.EDITION and _read_env_edition() == settings.EDITION,
        "next": "需受控重启后端进程生效（POST /admin/edition-ops/restart）",
    }}


@router.post("/edition-ops/restart", response_model=dict)
def edition_ops_restart(
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """受控重启：以 .env 的 EDITION 强制覆盖继承环境后拉起分离新进程，本进程延迟自终止。

    说明：_load_dotenv 只在 key 不在 os.environ 时注入——当前进程环境里可能残留
    启动期注入的旧 EDITION 值，故 spawn 前显式 set EDITION=<.env 新值>。
    """
    _require_super_admin(auth)
    import signal
    import subprocess
    import tempfile

    target = _read_env_edition()
    if target not in _EDITION_VALUES:
        raise BizError("ES-ADMIN-0007", f".env 中 EDITION={target!r} 非法，先执行 switch 写入合法值", http_status=409)

    env = dict(os.environ)
    env["EDITION"] = target
    log_path = Path(tempfile.gettempdir()) / "evalshield_restart.log"
    logf = open(log_path, "ab")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", settings.SERVER_HOST, "--port", str(settings.SERVER_PORT),
        ],
        cwd=str(_EDITION_BACKEND_DIR),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=logf,
        stderr=logf,
        creationflags=creationflags,
    )

    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="admin.edition_restart", module="admin", request=request,
        result="SUCCESS",
        detail=f"自进程 {os.getpid()} 重启为 pid={proc.pid}（EDITION={target}）",
    )

    # 先 spawn 后自杀：新进程 import 期远慢于本进程终止，端口竞争窗口可忽略。
    threading.Timer(1.0, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return {"code": 0, "message": "ok", "data": {
        "new_pid": proc.pid,
        "edition": target,
        "log": str(log_path),
        "hint": "服务将中断数秒，前端轮询 /api/edition 直至新形态生效",
    }}


# ============================================================================
# 内部工具函数
# ============================================================================

def _menu_to_dict(m: Menu) -> dict:
    return {
        "id": m.id, "parent_id": m.parent_id, "path": m.path,
        "component": m.component, "icon": m.icon, "title": m.title,
        "perm": m.perm, "sort_order": m.sort_order, "visible": m.visible,
        "menu_type": m.menu_type, "remark": m.remark,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _build_menu_tree(rows: list[Menu]) -> list[dict]:
    """扁平菜单列表 → 树形结构。"""
    pool: dict[int, dict] = {}
    for m in rows:
        node = _menu_to_dict(m)
        node["children"] = []
        pool[m.id] = node
    roots = []
    for m in rows:
        node = pool[m.id]
        if m.parent_id and m.parent_id in pool:
            pool[m.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots
