# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""认证与授权依赖。

- authenticate_request：从 Authorization Bearer 或 X-API-Key 解析当前用户。
- require_permission(...)：RBAC 功能权限校验（模块:动作）。
- ensure_data_scope(...)：数据权限校验（租户隔离 + 资源可见性）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .database import get_db
from .errors import AuthError, DataScopeError, PermError
from .models import ApiKey, Role, RolePermission, SystemUser, UserRole
from .security import decode_token, hash_api_key


@dataclass
class AuthContext:
    user_id: int
    username: str
    tenant_id: int
    user_type: str = ""
    roles: list[str] = field(default_factory=list)
    perms: set[str] = field(default_factory=set)
    is_super_admin: bool = False
    auth_mode: str = "jwt"  # jwt | apikey
    scope: list[str] = field(default_factory=list)  # 优化7 T4：半态令牌 scope（pwd_change_only）
    key_scopes: list[str] | None = None  # ES10-P-04：API Key 权限范围；F-04 收紧后空=拒绝


def _load_user_ctx(db: Session, user_id: int, tenant_id: int) -> AuthContext:
    user = db.get(SystemUser, user_id)
    if user is None or user.deleted_at is not None:
        raise AuthError()
    if user.status != "ACTIVE":
        raise AuthError("ES-AUTH-0002", f"账号状态异常（{user.status}），无法访问")

    roles: list[str] = []
    role_ids: list[int] = []
    is_super: bool = False
    rows = (
        db.query(UserRole.role_id, Role.role_code)
        .join(Role, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user_id, UserRole.tenant_id == tenant_id)
        .all()
    )
    for rid, role_code in rows:
        roles.append(role_code)
        role_ids.append(rid)
        if role_code == "SUPER_ADMIN":
            is_super = True

    perms: set[str] = set()
    if role_ids:
        perm_rows = (
            db.query(RolePermission.perm_code)
            .filter(RolePermission.role_id.in_(role_ids))
            .all()
        )
        perms = {p.perm_code for p in perm_rows}

    return AuthContext(
        user_id=user_id,
        username=user.username,
        tenant_id=tenant_id,
        user_type=user.user_type,
        roles=roles,
        perms=perms,
        is_super_admin=is_super,
    )


async def authenticate_request(
    request: Request, db: Session = Depends(get_db)
) -> AuthContext:
    """从请求头解析身份（JWT 或 API Key）。"""
    auth = request.headers.get("Authorization", "")
    api_key = request.headers.get("X-API-Key", "")

    if api_key:
        key_hash = hash_api_key(api_key)
        row = (
            db.query(ApiKey)
            .filter(ApiKey.key_hash == key_hash, ApiKey.disabled == False)
            .first()
        )  # noqa: E712
        if row is None:
            raise AuthError("ES-AUTH-0006", "API Key 无效或已吊销")
        now = datetime.now(timezone.utc)
        if row.expires_at is not None and row.expires_at < now:
            raise AuthError("ES-AUTH-0006", "API Key 已过期")
        # 绑定用户与租户
        ctx = _load_user_ctx(db, row.user_id, row.tenant_id)
        ctx.auth_mode = "apikey"
        # F-04 修复（收紧）：NULL 与 [] 同义为空 scopes → require_scope 一律拒绝，
        # 不再享有旧的"全量放行"语义（超管除外）。存量 Key 需显式授予 scopes。
        ctx.key_scopes = list(row.scopes) if row.scopes else []
        row.last_used_at = now
        db.add(row)
        db.commit()
        return ctx

    if not auth.startswith("Bearer "):
        raise AuthError()
    token = auth[7:]
    payload = decode_token(token)
    if payload is None or payload.get("typ") != "access":
        raise AuthError("ES-AUTH-0005", "令牌无效或已过期")
    try:
        user_id = int(payload["sub"])
        tenant_id = int(payload.get("ten", 0))
    except (KeyError, TypeError, ValueError):
        raise AuthError()
    ctx = _load_user_ctx(db, user_id, tenant_id)
    ctx.scope = list(payload.get("scope") or [])
    return ctx


def require_permission(code_prefix: str, action: str) -> Callable:
    """RBAC 功能权限依赖工厂：require_permission('project', 'create')。"""

    def checker(auth: AuthContext = Depends(authenticate_request)) -> AuthContext:
        if auth.is_super_admin:
            return auth
        required = f"{code_prefix}:{action}"
        if required not in auth.perms and f"{code_prefix}:*" not in auth.perms:
            raise PermError(message=f"缺少权限 {required}")
        return auth

    return checker


def require_any_permission(*specs: tuple[str, str]) -> Callable:
    """优化12 §6.3：任一 (code_prefix, action) 命中即放行，否则 403。

    与 require_permission 同口径支持 `prefix:*` 通配；超管放行。
    用于守卫单向放宽（如 meta GET 同时接受 case:read / eval:read）。
    """

    def checker(auth: AuthContext = Depends(authenticate_request)) -> AuthContext:
        if auth.is_super_admin:
            return auth
        for code_prefix, action in specs:
            if (f"{code_prefix}:{action}" in auth.perms
                    or f"{code_prefix}:*" in auth.perms):
                return auth
        joined = " 或 ".join(f"{p}:{a}" for p, a in specs)
        raise PermError(message=f"缺少权限 {joined}")

    return checker


def require_scope(required: str) -> Callable:
    """ES10-P-04：API Key scope 校验依赖工厂。

    - JWT 通道：不校验（返回 ctx，RBAC 由 require_permission 另行负责）。
    - API-Key 通道：F-04 收紧后 key_scopes 为空（NULL/[] 旧 Key）→ 拒绝；
      required 必须在列表内，缺失 → 403 ES-SCOPE-0001（SUPER_ADMIN 放行）。
    """

    def checker(auth: AuthContext = Depends(authenticate_request)) -> AuthContext:
        if auth.auth_mode != "apikey":
            return auth
        if auth.is_super_admin:
            return auth
        if required not in (auth.key_scopes or []):
            raise PermError("ES-SCOPE-0001", f"API Key 缺少权限 {required}")
        return auth

    return checker


async def ensure_data_scope(
    auth: AuthContext,
    resource_tenant_id: int | None = None,
    visibility: str | None = None,
    owner_user_id: int | None = None,
) -> None:
    """数据权限：租户隔离 + 可见性校验。

    - 资源不属于当前租户 → 拒绝（跨租户）。
    - SUPER_ADMIN 全量放行。
    - PRIVATE：仅所有者；TEAM：同租户可见（扩展可按部门）；PUBLIC：租户内可见。
    """
    if auth.is_super_admin:
        return
    if resource_tenant_id is not None and resource_tenant_id != auth.tenant_id:
        raise DataScopeError()
    if (
        visibility == "PRIVATE"
        and owner_user_id is not None
        and owner_user_id != auth.user_id
    ):
        raise DataScopeError()
    return None
