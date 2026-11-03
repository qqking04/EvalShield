# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M10 SSO 单点登录路由（方案 §11 M10）。

公开链路（浏览器 302 流，均不走 authenticate_request）：
- GET  /api/auth/sso/providers?tenant_hint=   登录页按钮列表（只回 id/name/kind，
        绝不泄露 issuer 原文与 secret）
- GET|POST /api/auth/sso/{config_id}/start    生成 state/nonce/PKCE，签名中转 cookie
        → 302 到 authorization_endpoint（disabled 配置 → 404）
- GET  /api/auth/sso/callback                 校 state（防 CSRF + 一次性消费）→
        code 换 token → 验 id_token → 按 email|username(sub) 匹配用户 →
        auto_provision 建号入租户 → 复用 login 同款 _build_tokens 签 JWT →
        302 回前端 /login?token=...

管理链路（RBAC sso:manage + 能力位 sso 未点亮 403 置灰）：
- /api/admin/sso/configs CRUD，client_secret 入参 encrypt_secret 落库，
  出参只回 ****+后4位。
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import security
from ..config import settings
from ..database import SessionLocal, get_db
from ..deps import AuthContext, require_permission
from ..enterprise.features import feature_enabled
from ..errors import BizError, NotFoundError
from ..models import SsoConfig, SystemUser
from ..services import sso_oidc
from ..services.audit import write_audit
from ..services.provisioning import create_user_in_org, resolve_org_by_name

router = APIRouter()
router_admin = APIRouter()

_KINDS = ("oidc", "wecom", "feishu")
_KIND_PATTERN = "^(" + "|".join(_KINDS) + ")$"
_RELAY_COOKIE = "es_sso_relay"
_RELAY_PATH = "/api/auth/sso"


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------
def _guard_sso_feature() -> None:
    """能力位守卫：sso 未点亮时管理端点置灰（照 redteam._guard_* 范式）。"""
    if not feature_enabled("sso"):
        raise BizError(
            "ES-LIC-0003",
            "单点登录（SSO）为企业/SaaS 能力，当前授权未包含该模块",
            http_status=403,
        )


def _load_config(db: Session, config_id: int, *, require_enabled: bool) -> SsoConfig:
    cfg = db.query(SsoConfig).filter(SsoConfig.id == config_id).first()
    if cfg is None or (require_enabled and not cfg.enabled):
        # 禁用与不存在统一 404，不泄露配置存在性
        raise NotFoundError("ES-SSO-0004", "SSO 配置不存在或已停用")
    return cfg


def _secret_mask(enc: str) -> str:
    """出参脱敏：只回 ****+解密后明文末 4 位，绝不回密文/原文。"""
    if not enc:
        return ""
    try:
        plain = security.decrypt_secret(enc)
    except Exception:  # noqa: BLE001 —— 解密失败按空处理
        return "****"
    return "****" + plain[-4:] if plain else ""


# ---------------------------------------------------------------------------
# 公开：providers 列表（登录页按钮）
# ---------------------------------------------------------------------------
@router.get("/providers", response_model=dict)
async def list_providers(
    tenant_hint: int | None = Query(None, ge=1, description="租户 ID 提示；缺省取默认租户"),
    db: Session = Depends(get_db),
):
    """公开端点：仅回 id/name/kind。能力位未点亮或无配置 → 空列表（前端不显入口）。"""
    if not feature_enabled("sso"):
        return {"code": 0, "message": "ok", "data": []}
    tid = tenant_hint or 1
    rows = (
        db.query(SsoConfig)
        .filter(SsoConfig.tenant_id == tid, SsoConfig.enabled == True)  # noqa: E712
        .order_by(SsoConfig.id)
        .all()
    )
    items = [{"id": r.id, "name": r.name, "kind": r.kind} for r in rows]
    return {"code": 0, "message": "ok", "data": items}


# ---------------------------------------------------------------------------
# 公开：start（302 到 authorize URL）
# ---------------------------------------------------------------------------
async def _start_impl(
    config_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _guard_sso_feature()
    cfg = _load_config(db, config_id, require_enabled=True)
    if not cfg.issuer.strip():
        raise BizError("ES-SSO-0002", "SSO 配置缺少 issuer，无法发起授权")
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = sso_oidc.gen_pkce()
    try:
        doc = sso_oidc.discover(cfg.issuer)
        url = sso_oidc.build_authorize_url(
            doc,
            client_id=cfg.client_id,
            redirect_uri=sso_oidc.resolve_redirect_uri(cfg),
            scope=cfg.scopes,
            state=state,
            nonce=nonce,
            code_challenge=challenge,
        )
    except Exception as exc:  # noqa: BLE001 —— provider 不可达/文档缺字段统一转 400
        raise BizError("ES-SSO-0003", f"身份提供方不可达：{exc}") from exc
    # state/nonce/verifier 经 HS256 签名的短 TTL 中转 cookie 携带（无服务端会话）
    relay = sso_oidc.make_relay_token(cfg.id, state, nonce, verifier)
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(
        _RELAY_COOKIE, relay, max_age=sso_oidc._RELAY_TTL,
        httponly=True, samesite="lax", path=_RELAY_PATH,
    )
    return resp


@router.get("/configs/{config_id}/start", operation_id="sso_start_get")
async def start_get(
    config_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    return await _start_impl(config_id, request, db)


@router.post("/configs/{config_id}/start", operation_id="sso_start_post")
async def start_post(
    config_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    return await _start_impl(config_id, request, db)


# ---------------------------------------------------------------------------
# 公开：callback
# ---------------------------------------------------------------------------
@router.get("/callback")
async def callback(
    request: Request,
    code: str = Query("", description="授权码"),
    state: str = Query("", description="CSRF 校验串"),
    db: Session = Depends(get_db),
):
    relay_token = request.cookies.get(_RELAY_COOKIE, "")
    if not relay_token or not code:
        raise BizError("ES-SSO-0001", "SSO 回调缺少会话或授权码")
    # 先解出 cfg 归属（不消费 jti），再按 config 权威校验并一次性消费
    cfg_id = _decode_relay_lightweight(relay_token)
    if cfg_id is None:
        raise BizError("ES-SSO-0001", "SSO 会话令牌无效或已过期")
    cfg = _load_config(db, cfg_id, require_enabled=True)
    relay = sso_oidc.read_relay_token(relay_token, cfg_id)
    if relay is None or relay.get("st") != state:
        # state 不符 / 重放 / 过期 → CSRF 防护失败
        raise BizError("ES-SSO-0001", "SSO 会话校验失败（state 不符或已过期）")
    try:
        doc = sso_oidc.discover(cfg.issuer)
        tokens = sso_oidc.exchange_code(
            doc,
            client_id=cfg.client_id,
            client_secret=security.decrypt_secret(cfg.client_secret_enc),
            code=code,
            redirect_uri=sso_oidc.resolve_redirect_uri(cfg),
            code_verifier=relay["cv"],
        )
        if tokens.get("id_token"):
            claims = sso_oidc.verify_id_token(
                tokens["id_token"],
                issuer=cfg.issuer,
                client_id=cfg.client_id,
                nonce=relay["nc"],
            )
        else:  # 无 id_token 的 provider：userinfo 兜底（nonce 校验不适用此路径）
            claims = tokens.get("userinfo") or {}
    except BizError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BizError("ES-SSO-0003", f"SSO 令牌校验失败：{exc}") from exc

    user = _match_or_provision_user(db, cfg, claims)
    from .auth import _build_tokens

    payload = _build_tokens(user, db)
    _write_sso_login(user, request, ok=True)

    # 302 回前端登录页带令牌（前端解析 token 后 setToken 并跳首页）
    base = settings.UI_DEFAULT_BASE_URL.rstrip("/")
    qs = urlencode(
        {"token": payload["access_token"], "refresh": payload["refresh_token"]}
    )
    resp = RedirectResponse(f"{base}/login?{qs}", status_code=302)
    resp.delete_cookie(_RELAY_COOKIE, path=_RELAY_PATH)  # 一次性消费后清 cookie
    return resp


def _decode_relay_lightweight(token: str) -> int | None:
    """仅解出 config_id（不校验 jti），供回调先定位配置；权威校验在 read_relay_token。"""
    try:
        from jose import jwt as _jwt

        payload = _jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return int(payload.get("cfg", -1))
    except Exception:  # noqa: BLE001
        return None


def _match_or_provision_user(db: Session, cfg: SsoConfig, claims: dict) -> SystemUser:
    """按 email 优先、sub（回退 username 精确匹配）命中存量用户；
    不命中且 auto_provision 开 → 建号进对租户 + default_role。"""
    email = (claims.get("email") or "").strip().lower()
    sub = str(claims.get("sub") or "").strip()
    user: SystemUser | None = None
    if email:
        user = (
            db.query(SystemUser)
            .filter(
                SystemUser.tenant_id == cfg.tenant_id,
                SystemUser.email == email,
                SystemUser.status == "ACTIVE",
            )
            .first()
        )
    if user is None and sub:
        user = (
            db.query(SystemUser)
            .filter(
                SystemUser.tenant_id == cfg.tenant_id,
                SystemUser.username == sub,
                SystemUser.status == "ACTIVE",
            )
            .first()
        )
    if user is not None:
        return user
    if not cfg.auto_provision:
        raise BizError("ES-SSO-0005", "该身份未绑定系统账号，请联系管理员", 403)
    # 建号：用户名 email 前缀或 sso_+sub 派生，随机不可登录口令
    if email:
        username = email.split("@", 1)[0][:56]
    else:
        username = f"sso_{secrets.token_hex(6)}"
    if db.query(SystemUser).filter(SystemUser.username == username).first():
        username = f"sso_{secrets.token_hex(6)}"
    org_name = None
    if cfg.org_binding_mode == "name":
        org_name = claims.get("department") or claims.get("org") or None
    org = resolve_org_by_name(db, cfg.tenant_id, org_name)
    user = create_user_in_org(
        db,
        tenant_id=cfg.tenant_id,
        org=org,
        username=username,
        email=email or None,
        password_hash=security.hash_password(secrets.token_urlsafe(24)),
        display_name=(claims.get("name") or username)[:128],
        role_code=cfg.default_role,
        user_type="EXTERNAL",
    )
    db.commit()
    db.refresh(user)
    return user


def _write_sso_login(user: SystemUser, request: Request, *, ok: bool) -> None:
    """登录留痕复用 auth 同款 login_attempts + 审计（独立 Session，不污染主事务）。"""
    from .auth import _write_login_attempt

    _write_login_attempt(
        user.username,
        request.client.host if request.client else None,
        ok,
        None if ok else "sso",
        tenant_id=user.tenant_id,
    )
    s = SessionLocal()
    try:
        write_audit(
            s, user_id=user.id, username=user.username, tenant_id=user.tenant_id,
            action="sso.login", module="auth", request=request,
            result="SUCCESS" if ok else "FAILED",
        )
    finally:
        s.close()


# ---------------------------------------------------------------------------
# 管理端 CRUD（/api/admin/sso/configs）
# ---------------------------------------------------------------------------
class SsoConfigCreate(BaseModel):
    kind: str = Field(..., pattern=_KIND_PATTERN)
    name: str = Field(..., min_length=1, max_length=128)
    issuer: str = ""
    client_id: str = ""
    client_secret: str = Field("", description="明文，落库前 encrypt_secret")
    scopes: str = "openid profile email"
    redirect_uri: str = ""
    enabled: bool = True
    auto_provision: bool = False
    default_role: str = "MEMBER"
    org_binding_mode: str = "none"


class SsoConfigUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    issuer: str | None = None
    client_id: str | None = None
    client_secret: str | None = Field(
        None, description="留空/省略 = 保留既有密文不变更"
    )
    scopes: str | None = None
    redirect_uri: str | None = None
    enabled: bool | None = None
    auto_provision: bool | None = None
    default_role: str | None = None
    org_binding_mode: str | None = None


def _cfg_out(c: SsoConfig) -> dict:
    """出参：secret 只回 ****+后4位；issuer 仅管理端可见（登录页端点不含）。"""
    return {
        "id": c.id,
        "tenant_id": c.tenant_id,
        "kind": c.kind,
        "name": c.name,
        "issuer": c.issuer,
        "client_id": c.client_id,
        "client_secret_masked": _secret_mask(c.client_secret_enc),
        "scopes": c.scopes,
        "redirect_uri": c.redirect_uri,
        "enabled": c.enabled,
        "auto_provision": c.auto_provision,
        "default_role": c.default_role,
        "org_binding_mode": c.org_binding_mode,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


@router_admin.get("/configs", response_model=dict)
async def list_configs(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("sso", "manage")),
):
    _guard_sso_feature()
    q = db.query(SsoConfig)
    if not auth.is_super_admin:
        q = q.filter(SsoConfig.tenant_id == auth.tenant_id)
    rows = q.order_by(SsoConfig.id.desc()).all()
    return {"code": 0, "message": "ok", "data": {"items": [_cfg_out(c) for c in rows]}}


@router_admin.post("/configs", response_model=dict)
async def create_config(
    body: SsoConfigCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("sso", "manage")),
):
    _guard_sso_feature()
    c = SsoConfig(
        tenant_id=auth.tenant_id,
        kind=body.kind,
        name=body.name,
        issuer=body.issuer.strip(),
        client_id=body.client_id.strip(),
        client_secret_enc=(
            security.encrypt_secret(body.client_secret) if body.client_secret else ""
        ),
        scopes=body.scopes.strip() or "openid profile email",
        redirect_uri=body.redirect_uri.strip(),
        enabled=body.enabled,
        auto_provision=body.auto_provision,
        default_role=body.default_role.strip() or "MEMBER",
        org_binding_mode=body.org_binding_mode.strip() or "none",
        created_by=auth.user_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    sso_oidc.clear_caches()  # 新配置可能改 issuer，缓存宁可作废
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="sso.config.create", module="sso", request=request,
        detail=f"新建 SSO 配置：{c.name}（{c.kind}）",
    )
    return {"code": 0, "message": "ok", "data": _cfg_out(c)}


@router_admin.put("/configs/{config_id}", response_model=dict)
async def update_config(
    config_id: int,
    body: SsoConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("sso", "manage")),
):
    _guard_sso_feature()
    c = _load_config(db, config_id, require_enabled=False)
    if not auth.is_super_admin and c.tenant_id != auth.tenant_id:
        raise NotFoundError("ES-SSO-0004", "SSO 配置不存在")
    data = body.model_dump(exclude_unset=True)
    if "client_secret" in data:
        secret = (data.pop("client_secret") or "").strip()
        if secret:  # 留空 = 不变更既有密文
            c.client_secret_enc = security.encrypt_secret(secret)
    for field in (
        "name", "issuer", "client_id", "scopes", "redirect_uri",
        "enabled", "auto_provision", "default_role", "org_binding_mode",
    ):
        if field in data:
            setattr(c, field, data[field])
    db.commit()
    db.refresh(c)
    sso_oidc.clear_caches()
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="sso.config.update", module="sso", request=request,
        detail=f"更新 SSO 配置：{c.name}",
    )
    return {"code": 0, "message": "ok", "data": _cfg_out(c)}


@router_admin.delete("/configs/{config_id}", response_model=dict)
async def delete_config(
    config_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("sso", "manage")),
):
    _guard_sso_feature()
    c = _load_config(db, config_id, require_enabled=False)
    if not auth.is_super_admin and c.tenant_id != auth.tenant_id:
        raise NotFoundError("ES-SSO-0004", "SSO 配置不存在")
    db.delete(c)
    db.commit()
    sso_oidc.clear_caches()
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="sso.config.delete", module="sso", request=request,
        detail=f"删除 SSO 配置：{c.name}",
    )
    return {"code": 0, "message": "ok", "data": None}
