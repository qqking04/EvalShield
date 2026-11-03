# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""认证路由：登录（含失败锁定 + login_attempts 审计 + rehash 钩子）、刷新令牌、注册、忘记/重置密码、
个人资料、修改密码（密码策略 + 历史查重）、TOTP、登出。

说明书 4.1 M1（14 端点）+ 4.4 M9 安全加固。
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import security
from ..database import SessionLocal, get_db
from ..deps import AuthContext, authenticate_request
from ..enterprise.features import feature_enabled
from ..errors import AuthError, BizError
from ..limits import check_limit
from ..models import (
    AuditLog,
    LoginAttempt,
    Notification,
    Organization,
    PasswordHistory,
    Role,
    SystemSetting,
    SystemUser,
    UserRole,
)
from ..utils.no import gen_no

router = APIRouter()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _build_tokens(user: SystemUser, db: Session) -> dict:
    roles: list[str] = []
    role_ids: list[int] = []
    is_super = False
    rows = (
        db.query(UserRole.role_id, Role.role_code)
        .join(Role, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user.id, UserRole.tenant_id == user.tenant_id)
        .all()
    )
    for rid, role_code in rows:
        roles.append(role_code)
        role_ids.append(rid)
        if role_code == "SUPER_ADMIN":
            is_super = True
    perms: set[str] = set()
    if role_ids:
        from ..models import RolePermission
        perm_rows = db.query(RolePermission.perm_code).filter(RolePermission.role_id.in_(role_ids)).all()
        perms = {p.perm_code for p in perm_rows}
    # 优化7 T4：must_change_pwd → 半态令牌（scope=pwd_change_only，全局中间件拦截业务接口）
    scope = ["pwd_change_only"] if user.must_change_pwd else None
    access, refresh = security.create_token_pair(
        user_id=user.id, tenant_id=user.tenant_id, roles=roles, perms=list(perms), scope=scope
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": security.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "roles": roles,
        "perms": list(perms),
        "is_super_admin": is_super,
        "must_change_pwd": bool(user.must_change_pwd),
    }


def _write_audit(db: Session | None = None, *, user_id=None, username=None, tenant_id=1, action, module, request: Request, result="SUCCESS", error_msg=None) -> None:
    """审计日志独立 Session，避免 rollback 污染主业务事务。"""
    s = SessionLocal()
    try:
        s.add(AuditLog(
            log_no=gen_no("AL"), user_id=user_id, username=username, tenant_id=tenant_id,
            action=action, module=module, method=request.method, path=request.url.path,
            result=result, ip=request.client.host if request.client else None,
            ua=request.headers.get("user-agent", ""), error_msg=error_msg,
        ))
        s.commit()
    except Exception:  # noqa: BLE001
        s.rollback()
    finally:
        s.close()


def _write_login_attempt(username: str, ip: str | None, success: bool, fail_reason: str | None, tenant_id: int = 1) -> None:
    """独立 Session 写登录尝试，避免污染主事务。"""
    s = SessionLocal()
    try:
        s.add(LoginAttempt(username=username, ip=ip, success=success, fail_reason=fail_reason, tenant_id=tenant_id))
        s.commit()
    except Exception:  # noqa: BLE001
        s.rollback()
    finally:
        s.close()


def _is_locked_by_attempts(db: Session, username: str, ip: str | None = None) -> bool:
    """LOGIN_LOCK_MINUTES 窗口内累计 LOGIN_FAIL_LIMIT 次失败 → 锁定。

    F-06：双维度判定——用户名维度（防针对单账号的爆破）+ IP 维度
    （防分布式撒网式撞库：同一 IP 对不同用户名轮换失败同样触发锁定）。
    """
    since = datetime.now(timezone.utc) - timedelta(minutes=security.LOCK_MINUTES)
    count = (
        db.query(LoginAttempt)
        .filter(LoginAttempt.username == username, LoginAttempt.success == False, LoginAttempt.created_at >= since)
        .count()
    )  # noqa: E712
    if count >= security.MAX_LOGIN_FAILS:
        return True
    if ip:
        ip_count = (
            db.query(LoginAttempt)
            .filter(LoginAttempt.ip == ip, LoginAttempt.success == False, LoginAttempt.created_at >= since)
            .count()
        )  # noqa: E712
        if ip_count >= security.MAX_LOGIN_FAILS:
            return True
    return False


def _do_rehash_if_needed(user: SystemUser, plain: str, db: Session) -> None:
    """F-03：仅在口令哈希为未知格式时重写；bcrypt 存量保持不降级（MD5 为新建终态）。"""
    if security.needs_rehash(user.password_hash):
        new_hash = security.hash_password(plain)
        user.password_hash = new_hash
        db.add(PasswordHistory(user_id=user.id, password_hash=new_hash, tenant_id=user.tenant_id))
        db.commit()


def _append_password_history(user_id: int, password_hash: str, tenant_id: int, db: Session) -> None:
    db.add(PasswordHistory(user_id=user_id, password_hash=password_hash, tenant_id=tenant_id))


def _ensure_owner_permissions(db: Session, role) -> None:
    """防御性补齐 OWNER 角色权限（仅工作空间级，不含系统管理/admin/model/engine/billing）。

    生产部署偶发 seed 遗漏时 OWNER 角色 role_permissions 为空，导致新注册用户登录后
    前端 hasPerm() 全部返回 false、菜单整体被过滤。此处检测到权限为空则自动补齐。

    ⚠️ 边界：OWNER 是"工作空间拥有者"，不是系统管理员。系统级权限（admin:*、
    model:*、engine:*、billing:*）只分配给 SUPER_ADMIN / ADMIN，OWNER 不拥有。
    """
    if role is None:
        return
    from sqlalchemy import text as sa_text

    count = db.execute(
        sa_text("SELECT count(*) FROM role_permissions WHERE role_id = :rid"),
        {"rid": role.id},
    ).scalar()
    if count and count > 0:
        return  # 已有权限，跳过

    # OWNER 白名单：工作空间级权限（覆盖前端所有菜单，除系统管理/模型网关/引擎/计费）
    _OWNER_PERM_CODES = (
        # 仪表盘
        "dashboard:view",
        # 项目 + 环境管理（共用 project:*）
        "project:*",
        "project:create", "project:read", "project:update", "project:delete",
        # 任务中心 + AI 自动化 + AI 自动探测
        "task:*",
        "task:create", "task:read", "task:update", "task:delete", "task:execute",
        # 资产中心 + UI 录制 + 文档导入（case:* + case:create 覆盖文档导入）
        "case:*",
        "case:create", "case:read", "case:update", "case:delete",
        # 评测中心
        "eval:*",
        "eval:create", "eval:read", "eval:execute",
        # 报告中心
        "report:*",
        "report:read", "report:export",
        # 缺陷管理
        "defect:*",
        "defect:read", "defect:create", "defect:update", "defect:delete",
        # 场景 / 数据集
        "scenario:*",
        "scenario:create", "scenario:read", "scenario:delete",
        "dataset:*",
        "dataset:create", "dataset:read", "dataset:delete",
    )

    # 用 permissions 表做白名单过滤，只灌真实存在的 perm_code
    existing = set(
        c for (c,) in db.execute(sa_text("SELECT perm_code FROM permissions"))
    )
    for code in _OWNER_PERM_CODES:
        if code not in existing:
            continue
        db.execute(
            sa_text(
                "INSERT INTO role_permissions (role_id, perm_code, created_at) "
                "VALUES (:rid, :code, now()) ON CONFLICT DO NOTHING"
            ),
            {"rid": role.id, "code": code},
        )


# ---------------------------------------------------------------------------
# 4.1.1 注册 POST /api/auth/register（免登录）
# ES8 M1：三形态分流（saas=开租户+试用；enterprise=需 self_register 能力位；community=关）
# ---------------------------------------------------------------------------
@router.get("/capabilities")
async def capabilities(db: Session = Depends(get_db)):
    """公开端点：注册开放状态 + 形态提示 + 对外套餐列表（免登录，供注册页条件渲染）。"""
    from ..config import settings
    from ..models import BillingPlan
    from ..services.registration import registration_enabled

    plans = (
        db.query(BillingPlan)
        .filter(BillingPlan.status == "ACTIVE", BillingPlan.deleted_at.is_(None))
        .order_by(BillingPlan.price_monthly.asc(), BillingPlan.id.asc())
        .all()
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "registration_open": registration_enabled(),
            "edition_hint": settings.EDITION,  # community | saas | enterprise
            "plans_public": [
                {
                    "code": p.code,
                    "name": p.name,
                    "price_monthly_cents": int(round((p.price_monthly or 0.0) * 100)),
                    "credits": p.credits,
                    "max_tasks": p.max_tasks,
                    "features": p.features or [],
                }
                for p in plans
            ],
        },
    }


@router.post("/register")
async def register(body: dict, request: Request, db: Session = Depends(get_db)):
    # B5：社区版单用户体系——self_register 关闭（ES-LIMIT-0002，先于注册闸门）
    check_limit("self_register", db, None)  # 开关型不触碰 db/auth
    # ES8 M1：闸门收敛到共享域 registration_enabled()（saas→multi_tenant；enterprise→self_register；community→恒关）
    from ..config import settings
    from ..services.registration import registration_enabled

    if not registration_enabled():
        raise BizError(
            "ES-LIC-0003",
            "当前部署形态未开放自助注册，请联系管理员开通账号",
            http_status=403,
        )
    username = (body.get("username") or "").strip()
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    tenant_name = (body.get("tenant_name") or "").strip()
    agree_terms = bool(body.get("agree_terms"))
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]{3,31}$", username):
        raise BizError("ES-AUTH-0011", "用户名 4-32 位，字母开头，字母/数字/下划线")
    if not email or "@" not in email:
        raise BizError("ES-AUTH-0011", "邮箱格式不正确")

    existing = db.query(SystemUser).filter(SystemUser.username == username, SystemUser.deleted_at.is_(None)).first()
    if existing:
        raise BizError("ES-AUTH-0011", "用户名已存在", http_status=400)
    existing_email = db.query(SystemUser).filter(SystemUser.email == email, SystemUser.deleted_at.is_(None)).first()
    if existing_email:
        raise BizError("ES-AUTH-0010", "邮箱已被注册", http_status=400)

    security.validate_password_policy(password)
    hashed = security.hash_password(password)

    edition = settings.EDITION
    tenant_data: dict | None = None
    if edition == "saas":
        # saas：服务条款必须同意（新用户即开通独立租户）
        if not agree_terms:
            raise BizError("ES-AUTH-0016", "请先阅读并同意服务条款", http_status=422)
        # 函数内延迟 import：provisioning 属共享域（只依赖 models），OSS 树可用
        from ..services import provisioning

        tenant, org, user, _sub = provisioning.create_tenant_with_trial(
            db,
            tenant_name=tenant_name or f"{username}的工作区",
            username=username,
            email=email,
            password_hash=hashed,
            plan_code="free",
            trial_days=settings.TRIAL_DAYS,
            request=request,
        )
        tenant_data = {
            "id": tenant.id,
            "name": tenant.name,
            "plan_code": tenant.plan_code,
            "trial_ends_at": tenant.trial_ends_at.isoformat() if tenant.trial_ends_at else None,
        }
    else:
        # enterprise（registration_enabled 已确认 self_register 位）：收口到默认租户 + 组织树
        from ..services import provisioning

        tenant = provisioning.get_default_tenant(db)
        org = provisioning.resolve_org_by_name(db, tenant.id, tenant_name or (body.get("organization_name") or ""))
        is_first_user = (
            db.query(SystemUser)
            .filter(SystemUser.org_id == org.id, SystemUser.deleted_at.is_(None))
            .count()
            == 0
        )
        user = provisioning.create_user_in_org(
            db,
            tenant_id=tenant.id,
            org=org,
            username=username,
            email=email,
            password_hash=hashed,
            role_code="ADMIN" if is_first_user else "MEMBER",
        )
        tenant_data = {
            "id": tenant.id,
            "name": tenant.name,
            "plan_code": tenant.plan_code,
            "trial_ends_at": tenant.trial_ends_at.isoformat() if tenant.trial_ends_at else None,
        }
        # OWNER 角色权限防御性补齐仅对 saas 开通路径有意义；enterprise 走 ADMIN/MEMBER
        _ensure_owner_permissions(db, db.query(Role).filter(Role.role_code == "ADMIN").first())

    _append_password_history(user.id, hashed, user.tenant_id, db)
    _write_audit(user_id=user.id, username=username, tenant_id=user.tenant_id, action="user.register", module="auth", request=request)
    db.commit()
    tokens = _build_tokens(user, db)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "user_id": user.id,
            "org_id": org.id,
            "username": username,
            "token": tokens,
            "tenant": tenant_data,
        },
    }


# ---------------------------------------------------------------------------
# 4.1.2 忘记密码 POST /api/auth/forgot-password（免登录）
# ---------------------------------------------------------------------------
@router.post("/forgot-password")
async def forgot_password(body: dict, request: Request, db: Session = Depends(get_db)):
    email = (body.get("email") or "").strip()
    if not email or "@" not in email:
        raise BizError("ES-AUTH-0014", "邮箱格式不正确")
    # 统一返回，不暴露邮箱是否存在
    user = db.query(SystemUser).filter(SystemUser.email == email, SystemUser.deleted_at.is_(None)).first()
    if user and user.status == "ACTIVE":
        token = secrets.token_urlsafe(32)
        user.pwd_reset_token = token
        user.pwd_reset_expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        db.add(Notification(
            notif_no=gen_no("NF"), user_id=user.id, tenant_id=user.tenant_id,
            title="密码重置验证码", content=f"重置令牌：{token}\n有效期 30 分钟", notif_type="SYSTEM",
        ))
        db.commit()
    return {"code": 0, "message": "ok", "data": None}


# ---------------------------------------------------------------------------
# 4.1.3 重置密码 POST /api/auth/reset-password（免登录）
# ---------------------------------------------------------------------------
@router.post("/reset-password")
async def reset_password(body: dict, request: Request, db: Session = Depends(get_db)):
    token = (body.get("token") or "").strip()
    new_password = body.get("new_password") or ""
    security.validate_password_policy(new_password)

    now = datetime.now(timezone.utc)
    user = (
        db.query(SystemUser)
        .filter(SystemUser.pwd_reset_token == token, SystemUser.deleted_at.is_(None))
        .first()
    )
    if user is None or user.pwd_reset_expires_at is None or user.pwd_reset_expires_at < now:
        raise BizError("ES-AUTH-0014", "重置链接无效或已过期", http_status=400)

    security.ensure_not_reused(user.id, new_password, db)

    new_hash = security.hash_password(new_password)

    user.password_hash = new_hash
    user.pwd_reset_token = None
    user.pwd_reset_expires_at = None
    user.password_changed_at = now
    user.updated_at = now
    _append_password_history(user.id, new_hash, user.tenant_id, db)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


# ---------------------------------------------------------------------------
# 4.1.4 个人资料 PUT /api/auth/profile（登录）
# ---------------------------------------------------------------------------
@router.put("/profile")
async def update_profile(body: dict, request: Request, auth: AuthContext = Depends(authenticate_request), db: Session = Depends(get_db)):
    user = db.get(SystemUser, auth.user_id)
    if user is None:
        raise AuthError()
    if "nickname" in body and body["nickname"]:
        user.display_name = body["nickname"]
    if "phone" in body:
        user.phone = body["phone"] or None
    if "department" in body:
        user.title = body["department"] or None
    # avatar 简化：只接收路径
    if "avatar" in body:
        user.avatar = body["avatar"] or None
    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": {
        "id": user.id, "username": user.username, "display_name": user.display_name,
        "email": user.email, "phone": user.phone, "title": user.title, "avatar": user.avatar,
    }}


def _is_revoked_and_not_super(db: Session, request: Request, user: SystemUser) -> bool:
    """优化7 T5-4：License revoked（超宽限停服）时非超管一律拒绝进入系统。

    超管放行以达「License 管理」页续证；phase 按存储的 expires_at 请求时重算。
    """
    from ..config import settings
    from ..license_state import PHASE_REVOKED, resolve_license_state

    lic = resolve_license_state(
        getattr(request.app.state, "license_status", None), settings.LICENSE_GRACE_DAYS
    )
    if lic.get("phase") != PHASE_REVOKED:
        return False
    super_row = (
        db.query(UserRole.id)
        .join(Role, UserRole.role_id == Role.id)
        .filter(
            UserRole.user_id == user.id,
            UserRole.tenant_id == user.tenant_id,
            Role.role_code == "SUPER_ADMIN",
        )
        .first()
    )
    return super_row is None


# ---------------------------------------------------------------------------
# 登录（含 login_attempts + rehash）
# ---------------------------------------------------------------------------
@router.post("/login")
async def login(body: dict, request: Request, db: Session = Depends(get_db)):
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    totp_code = body.get("totp_code") or None

    user = (
        db.query(SystemUser)
        .filter(SystemUser.username == username, SystemUser.deleted_at.is_(None))
        .first()
    )
    now = datetime.now(timezone.utc)
    client_ip = request.client.host if request.client else None

    # 锁定检查前置（A07）：按 15 分钟窗口失败次数判定，不存在的用户名同样锁定，
    # 避免通过「永不锁定的无效账号」进行用户名枚举/撞库探测
    if _is_locked_by_attempts(db, username, client_ip):
        raise AuthError(
            "ES-AUTH-0013",
            f"登录失败次数过多，账号已锁定 {security.LOCK_MINUTES} 分钟",
            http_status=423,
        )

    if user is None:
        _write_login_attempt(username, client_ip, False, "用户不存在")
        _write_audit(user_id=None, username=username, tenant_id=1, action="user.login", module="auth", request=request, result="FAILED", error_msg="用户不存在")
        raise AuthError("ES-AUTH-0001", "用户名或密码错误")

    if user.status == "DISABLED":
        _write_login_attempt(username, client_ip, False, "账号已停用", user.tenant_id)
        raise AuthError("ES-AUTH-0002", "账号已停用，请联系管理员")

    if user.locked_until and user.locked_until > now:
        raise AuthError(
            "ES-AUTH-0013",
            f"登录失败次数过多，账号已锁定 {security.LOCK_MINUTES} 分钟",
            http_status=423,
        )

    if not security.verify_password(password, user.password_hash):
        _write_login_attempt(username, client_ip, False, "密码错误", user.tenant_id)
        # 兼容旧字段计数
        user.login_fail_count = (user.login_fail_count or 0) + 1
        if user.login_fail_count >= security.MAX_LOGIN_FAILS:
            user.status = "LOCKED"
            user.locked_until = now + timedelta(minutes=security.LOCK_MINUTES)
        user.updated_at = now
        db.commit()
        _write_audit(user_id=user.id, username=username, tenant_id=user.tenant_id, action="user.login", module="auth", request=request, result="FAILED", error_msg="密码错误")
        raise AuthError("ES-AUTH-0001", "用户名或密码错误")

    # TOTP
    if user.mfa_enabled and user.mfa_secret:
        if not totp_code:
            raise AuthError("ES-AUTH-0007", "该账号已开启二次认证，请输入 TOTP 验证码")
        if not security.verify_totp(user.mfa_secret, totp_code):
            raise AuthError("ES-AUTH-0007", "TOTP 验证码错误")

    # 优化7 T5-4：revoked 停服——非超管登录拒绝，超管放行至 License 管理页续证
    if _is_revoked_and_not_super(db, request, user):
        _write_login_attempt(username, client_ip, False, "授权已过期（revoked）", user.tenant_id)
        raise AuthError("ES-LIC-EXPIRED-REVOKED", "授权已过期，请联系服务商续证", http_status=403)

    # 优化7 T6-2：租户被停用/关闭 → 该租户成员登录 403（平台管理员与超管放行，保运营通道）
    if user.user_type != "platform_admin":
        from ..models import Tenant as _Tenant
        _t = db.query(_Tenant).filter(_Tenant.id == user.tenant_id, _Tenant.deleted_at.is_(None)).first()
        if _t is not None and _t.status in ("SUSPENDED", "CLOSED"):
            is_super = (
                db.query(Role.id)
                .join(UserRole, UserRole.role_id == Role.id)
                .filter(UserRole.user_id == user.id, Role.role_code == "SUPER_ADMIN")
                .first()
            ) is not None
            if not is_super:
                _write_login_attempt(username, client_ip, False, f"租户已{_t.status}", user.tenant_id)
                raise AuthError(
                    "ES-TENANT-SUSPENDED",
                    "所属服务空间已被暂停，请联系服务商恢复后续用" if _t.status == "SUSPENDED"
                    else "所属服务空间已关闭，请联系服务商",
                    http_status=403,
                )

    # 成功：重置失败计数 + rehash
    user.login_fail_count = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_login_ip = client_ip
    user.status = "ACTIVE"
    user.updated_at = now
    _do_rehash_if_needed(user, password, db)
    # ES11-AUTH-FIX：解锁状态必须落库。此前仅 rehash 分支隐式 commit，
    # 密码失败锁定（status=LOCKED）后正确密码登录虽发 token，但库中仍 LOCKED，
    # 后续所有鉴权请求 401，账号实质永久失效。
    db.commit()
    _write_login_attempt(username, client_ip, True, None, user.tenant_id)

    tokens = _build_tokens(user, db)
    tokens.update({"user_id": user.id, "username": user.username, "display_name": user.display_name})
    _write_audit(user_id=user.id, username=username, tenant_id=user.tenant_id, action="user.login", module="auth", request=request, result="SUCCESS")
    return {"code": 0, "message": "ok", "data": tokens}


# ---------------------------------------------------------------------------
# 刷新令牌
# ---------------------------------------------------------------------------
@router.post("/refresh")
async def refresh_token(body: dict, request: Request, db: Session = Depends(get_db)):
    refresh_token = body.get("refresh_token") or ""
    payload = security.decode_token(refresh_token)
    if payload is None or payload.get("typ") != "refresh":
        raise AuthError("ES-AUTH-0005", "刷新令牌无效或已过期")
    try:
        user_id = int(payload["sub"])
        tenant_id = int(payload.get("ten", 0))
    except (KeyError, TypeError, ValueError):
        raise AuthError("ES-AUTH-0005", "刷新令牌无效")
    user = db.get(SystemUser, user_id)
    if user is None or user.deleted_at is not None or user.status != "ACTIVE":
        raise AuthError("ES-AUTH-0005", "账号不可用")
    # 优化7 T5-4：revoked 停服——续期同样拦截非超管，防既有会话在停服期续命
    if _is_revoked_and_not_super(db, request, user):
        raise AuthError("ES-LIC-EXPIRED-REVOKED", "授权已过期，请联系服务商续证", http_status=403)
    # 优化7 T4：走 _build_tokens 统一传导 must_change_pwd 半态，防 refresh 绕过
    tokens = _build_tokens(user, db)
    return {"code": 0, "message": "ok", "data": tokens}


# ---------------------------------------------------------------------------
# 修改密码（加策略 + 历史查重）
# ---------------------------------------------------------------------------
@router.post("/change-password")
async def change_password(body: dict, request: Request, auth: AuthContext = Depends(authenticate_request), db: Session = Depends(get_db)):
    old_password = body.get("old_password") or ""
    new_password = body.get("new_password") or ""
    # confirm_password 前端可选传入，传入时才校验一致性（说明书未强制此字段）
    confirm_password = body.get("confirm_password")
    if confirm_password is not None and new_password != confirm_password:
        raise BizError("ES-AUTH-0008", "两次输入的新密码不一致")
    policy = security.get_pwd_policy(db)
    security.validate_password_policy(new_password, policy)

    user = db.get(SystemUser, auth.user_id)
    half_session = "pwd_change_only" in (auth.scope or [])
    # 优化7 T4：半态（首登强制改密）无需旧密码——初始口令可能由系统随机生成；
    # 「知道初始口令才能登录」本身即持有证明，防绕过由 scope 拦截保证。
    if not half_session and (user is None or not security.verify_password(old_password, user.password_hash)):
        raise AuthError("ES-AUTH-0001", "旧密码错误")

    security.ensure_not_reused(user.id, new_password, db, history_keep=int(policy.get("history_keep", 5)))
    new_hash = security.hash_password(new_password)
    user.password_hash = new_hash
    user.password_changed_at = datetime.now(timezone.utc)
    user.updated_at = datetime.now(timezone.utc)
    user.must_change_pwd = False  # 优化7 T4：清标志
    _append_password_history(user.id, new_hash, user.tenant_id, db)
    db.commit()
    _write_audit(user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id, action="user.change_password", module="auth", request=request)
    # 重签全态令牌，前端直接替换 localStorage 后续会话
    tokens = _build_tokens(user, db)
    return {"code": 0, "message": "ok", "data": {"tokens": tokens}}


# ---------------------------------------------------------------------------
# 当前用户信息
# ---------------------------------------------------------------------------
@router.get("/me")
async def me(auth: AuthContext = Depends(authenticate_request), db: Session = Depends(get_db)):
    user = db.get(SystemUser, auth.user_id)
    if user is None:
        raise AuthError()
    return {"code": 0, "message": "ok", "data": {
        "id": user.id, "user_no": user.user_no, "username": user.username,
        "display_name": user.display_name, "email": user.email, "phone": user.phone,
        "title": user.title, "avatar": user.avatar, "status": user.status,
        "mfa_enabled": bool(user.mfa_enabled),
        "tenant_id": auth.tenant_id,
        "user_type": user.user_type or "",  # 优化7 T6：前端平台区门控
        "roles": auth.roles, "perms": sorted(auth.perms), "is_super_admin": auth.is_super_admin,
    }}


# ---------------------------------------------------------------------------
# TOTP
# ---------------------------------------------------------------------------
@router.post("/mfa/setup")
async def mfa_setup(request: Request, auth: AuthContext = Depends(authenticate_request), db: Session = Depends(get_db)):
    from ..security import generate_totp_secret, build_totp_uri
    user = db.get(SystemUser, auth.user_id)
    if user is None:
        raise AuthError()
    secret = generate_totp_secret()
    user.mfa_secret = secret
    user.mfa_enabled = False
    db.commit()
    return {"code": 0, "message": "ok", "data": {"secret": secret, "otpauth_url": build_totp_uri(secret, account=user.username)}}


@router.post("/mfa/confirm")
async def mfa_confirm(body: dict, request: Request, auth: AuthContext = Depends(authenticate_request), db: Session = Depends(get_db)):
    from ..security import verify_totp
    user = db.get(SystemUser, auth.user_id)
    if user is None or not user.mfa_secret:
        raise BizError("ES-AUTH-0009", "请先执行 MFA setup 获取密钥")
    if not verify_totp(user.mfa_secret, body.get("code") or ""):
        raise AuthError("ES-AUTH-0010", "验证码错误或已过期")
    user.mfa_enabled = True
    db.commit()
    return {"code": 0, "message": "ok", "data": {"mfa_enabled": True}}


@router.post("/mfa/disable")
async def mfa_disable(body: dict, auth: AuthContext = Depends(authenticate_request), db: Session = Depends(get_db)):
    from ..security import verify_totp
    user = db.get(SystemUser, auth.user_id)
    if user is None:
        raise AuthError()
    ok = False
    if user.mfa_secret and verify_totp(user.mfa_secret, body.get("code") or ""):
        ok = True
    elif body.get("password") and security.verify_password(body["password"], user.password_hash):
        ok = True
    if not ok:
        raise AuthError("ES-AUTH-0010", "验证码或密码错误")
    user.mfa_enabled = False
    user.mfa_secret = None
    db.commit()
    return {"code": 0, "message": "ok", "data": {"mfa_enabled": False}}


# ---------------------------------------------------------------------------
# 登出
# ---------------------------------------------------------------------------
@router.post("/logout")
async def logout(request: Request, auth: AuthContext = Depends(authenticate_request), db: Session = Depends(get_db)):
    _write_audit(user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id, action="user.logout", module="auth", request=request)
    return {"code": 0, "message": "ok", "data": None}


# ---------------------------------------------------------------------------
# 公开前端配置（免登录）：白标品牌 + SSO 入口 —— 企业能力位 whitelabel / sso 的闸门落点
# ---------------------------------------------------------------------------
_DEFAULT_BRAND = {
    "site_name": "EvalShield",
    "logo_url": "",
    "theme_color": "#13c2c2",
    "footer_text": "EvalShield AI 系统测试服务平台",
}


@router.get("/public-config")
async def public_config(db: Session = Depends(get_db)):
    """登录页/外壳使用的公开配置：白标品牌信息与企业版入口开关。

    - whitelabel 能力位开启时，返回 system_settings(brand 组) 中的自定义品牌；
      未开启一律返回默认品牌（社区版不可白标）。
    - sso 能力位开启且配置了 provider 时返回 sso.enabled=True，前端据此渲染单点登录入口。
    """
    brand = dict(_DEFAULT_BRAND)
    whitelabel_on = feature_enabled("whitelabel")
    if whitelabel_on:
        rows = (
            db.query(SystemSetting)
            .filter(SystemSetting.setting_group == "brand", SystemSetting.is_secret.is_(False))
            .all()
        )
        for s in rows:
            if s.setting_key in brand and s.setting_value:
                brand[s.setting_key] = s.setting_value

    sso_enabled = feature_enabled("sso")
    sso_providers: list[dict] = []
    if sso_enabled:
        sso_rows = db.query(SystemSetting).filter(SystemSetting.setting_group == "sso").all()
        conf = {s.setting_key: s.setting_value for s in sso_rows if s.setting_value}
        for key in ("oidc", "cas", "saml", "ldap"):
            if conf.get(f"{key}_enabled", "").lower() in ("1", "true", "yes", "on"):
                sso_providers.append({"provider": key, "display_name": conf.get(f"{key}_name", key.upper())})
        if not sso_providers and conf.get("enabled", "").lower() in ("1", "true", "yes", "on"):
            sso_providers.append({"provider": conf.get("provider", "oidc"), "display_name": conf.get("provider_name", "SSO")})

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "edition_features": {
                "whitelabel": whitelabel_on,
                "sso": sso_enabled,
                "multi_tenant": feature_enabled("multi_tenant"),
                "compliance_package": feature_enabled("compliance_package"),
            },
            "brand": brand,
            "sso": {"enabled": bool(sso_providers), "providers": sso_providers},
        },
    }
