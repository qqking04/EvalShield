# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""租户开通服务（ES8 M1，共享域——只 import models，auth.py 与 commercial 两端可用）。

权威链：billing_plans（套餐定义）→ subscriptions（订购关系，状态机权威）
        → billing_quotas（派生缓存，由本模块 sync_quota_from_subscription 同步）。

- saas 自助注册：create_tenant_with_trial 同事务建 tenants + 默认根 org + OWNER 用户
  + subscriptions(TRIALING) + billing_quotas + 审计。
- enterprise 自助注册：复用 get_default_tenant / resolve_org_by_name / create_user_in_org。
- commercial 侧 tenants.py create_tenant 同样 import 本模块，消除手写重复。
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import (
    AuditLog,
    BillingPlan,
    BillingQuota,
    Organization,
    Role,
    Subscription,
    SystemUser,
    Tenant,
    UserRole,
)
from ..utils.no import gen_no

logger = logging.getLogger("evalshield.services.provisioning")

# 租户短码格式（与 commercial/routers/tenants.py _CODE_RE 对齐）
_CODE_RE = re.compile(r"^[a-z][a-z0-9\-]{1,30}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 租户主数据
# ---------------------------------------------------------------------------
def _slugify(name: str) -> str:
    """租户名 → 短码基底（小写字母数字，中文等非 ASCII 回退 't'）。"""
    s = re.sub(r"[^a-z0-9\-]+", "-", (name or "").lower()).strip("-")
    s = s[:18].strip("-")
    return s if re.match(r"^[a-z]", s or "") else ("t-" + s if s else "t")


def gen_unique_tenant_code(db: Session, name: str) -> str:
    """slug + 随机后缀防撞；重试上限内必唯一（后缀 6 位 hex，碰撞概率极低）。"""
    base = _slugify(name)
    for _ in range(20):
        suffix = secrets.token_hex(3)  # 6 位 hex
        code = f"{base}-{suffix}"[:31]
        if not _CODE_RE.match(code):
            code = f"t-{suffix}"
        # 含软删行也视为占用（与 tenants.py 查重口径一致）
        exists = db.query(Tenant.id).filter(Tenant.code == code).first()
        if exists is None:
            return code
    raise RuntimeError("ES8-PROV-FAIL: 租户短码生成连续碰撞")


def get_default_tenant(db: Session) -> Tenant:
    """enterprise/community 的固定租户（tenant_id=1）。缺失则幂等补建。"""
    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == 1, Tenant.deleted_at.is_(None))
        .first()
    )
    if tenant is None:
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
    if tenant is None:
        tenant = Tenant(
            id=1, code="default", name="默认租户", status="ACTIVE", source="sync",
        )
        db.add(tenant)
        db.flush()
    return tenant


# ---------------------------------------------------------------------------
# 组织 / 用户
# ---------------------------------------------------------------------------
def resolve_org_by_name(db: Session, tenant_id: int, org_name: str | None) -> Organization:
    """按名称找租户内根组织；不存在则创建。org_name 为空时取租户名。"""
    name = (org_name or "").strip()
    if not name:
        tenant = db.get(Tenant, tenant_id)
        name = (tenant.name if tenant else "默认组织") or "默认组织"
    org = (
        db.query(Organization)
        .filter(
            Organization.org_name == name,
            Organization.tenant_id == tenant_id,
            Organization.deleted_at.is_(None),
        )
        .first()
    )
    if org is None:
        org = Organization(
            org_no=gen_no("ORG"),
            org_name=name[:128],
            org_path="/",
            plan="free",
            quota_tasks_monthly=100,
            status="ACTIVE",
            tenant_id=tenant_id,
        )
        db.add(org)
        db.flush()
    return org


def _pick_role(db: Session, role_code: str) -> Role | None:
    role = db.query(Role).filter(Role.role_code == role_code).first()
    if role is None:
        role = db.query(Role).first()
    return role


def create_user_in_org(
    db: Session,
    *,
    tenant_id: int,
    org: Organization,
    username: str,
    email: str | None,
    password_hash: str,
    display_name: str | None = None,
    role_code: str = "OWNER",
    user_type: str = "EXTERNAL",
    must_change_pwd: bool = False,
) -> SystemUser:
    """在指定租户/组织下建用户并绑定角色（同事务，调用方负责 commit）。"""
    user = SystemUser(
        user_no=gen_no("U"),
        username=username,
        email=email,
        password_hash=password_hash,
        display_name=(display_name or username)[:128],
        user_type=user_type,
        status="ACTIVE",
        org_id=org.id,
        tenant_id=tenant_id,  # ES8：隔离键统一指向 tenants.id
        must_change_pwd=must_change_pwd,
    )
    db.add(user)
    db.flush()
    role = _pick_role(db, role_code)
    if role is not None:
        db.add(UserRole(user_id=user.id, role_id=role.id, tenant_id=tenant_id))
    return user


# ---------------------------------------------------------------------------
# 订购 → 配额派生缓存
# ---------------------------------------------------------------------------
def snapshot_plan_quota(db: Session, plan_code: str) -> dict:
    """订购时从 billing_plans 快照额度（权威链第一环；套餐缺失回退保守默认）。"""
    plan = (
        db.query(BillingPlan)
        .filter(BillingPlan.code == plan_code, BillingPlan.deleted_at.is_(None))
        .first()
    )
    if plan is None:
        return {}
    snap: dict = {}
    if plan.max_tasks is not None:
        snap["task_quota"] = plan.max_tasks
    if plan.credits:
        snap["credits"] = plan.credits
    return snap


def sync_quota_from_subscription(
    db: Session, sub: Subscription, *, create_missing: bool = True
) -> BillingQuota | None:
    """subscriptions 生命周期同步 billing_quotas（派生缓存唯一写入口）。"""
    q = db.query(BillingQuota).filter(BillingQuota.tenant_id == sub.tenant_id).first()
    if q is None:
        if not create_missing:
            return None
        q = BillingQuota(tenant_id=sub.tenant_id, plan=sub.plan_code)
        db.add(q)
    q.plan = sub.plan_code
    q.expires_at = sub.current_period_end
    q.period_start = sub.current_period_start
    q.period_end = sub.current_period_end
    # billing_quotas.sub_status 状态机（ACTIVE|GRACE|PAST_DUE|CANCELED）与
    # subscriptions 对齐：TRIALING/ACTIVE → ACTIVE；EXPIRED → CANCELED
    if sub.status in (Subscription.STATUS_TRIALING, Subscription.STATUS_ACTIVE):
        q.sub_status = "ACTIVE"
    elif sub.status in (Subscription.STATUS_GRACE,):
        q.sub_status = "GRACE"
    elif sub.status in (Subscription.STATUS_PAST_DUE,):
        q.sub_status = "PAST_DUE"
    elif sub.status in (Subscription.STATUS_CANCELED, Subscription.STATUS_EXPIRED):
        q.sub_status = "CANCELED"
    db.flush()
    return q


# ---------------------------------------------------------------------------
# saas：注册即开通租户（同事务五件套）
# ---------------------------------------------------------------------------
def create_tenant_with_trial(
    db: Session,
    *,
    tenant_name: str,
    username: str,
    email: str | None,
    password_hash: str,
    plan_code: str = "free",
    trial_days: int = 14,
    request: Request | None = None,
) -> tuple[Tenant, Organization, SystemUser, Subscription]:
    """saas 自助注册原子开通：tenants + 根 org + OWNER 用户 + subscriptions + quotas。

    不 commit（调用方统一提交，保持单事务语义）；审计在 commit 成功后另 session 写。
    """
    now = _now()
    trial_ends = now + timedelta(days=max(1, trial_days))

    tenant = Tenant(
        code=gen_unique_tenant_code(db, tenant_name),
        name=(tenant_name or f"{username}的工作区")[:128],
        status="ACTIVE",
        contact_email=email,
        source="self_serve",
        plan_code=plan_code,
        trial_ends_at=trial_ends,
    )
    db.add(tenant)
    db.flush()

    org = resolve_org_by_name(db, tenant.id, tenant_name)
    # ES7-T6 约定：organizations.tenant_id 挂租户主键；租户回指默认根 org
    tenant.org_id = org.id

    user = create_user_in_org(
        db,
        tenant_id=tenant.id,
        org=org,
        username=username,
        email=email,
        password_hash=password_hash,
        role_code="OWNER",
    )
    tenant.owner_user_id = user.id

    sub = Subscription(
        tenant_id=tenant.id,
        plan_code=plan_code,
        status=Subscription.STATUS_TRIALING,
        billing_cycle="monthly",
        trial_ends_at=trial_ends,
        current_period_start=now,
        current_period_end=trial_ends,
        cancel_at_period_end=False,
        auto_renew=True,
    )
    db.add(sub)
    db.flush()

    q = sync_quota_from_subscription(db, sub)
    # 套餐额度快照（free 缺失时保持 BillingQuota 列默认）
    for k, v in snapshot_plan_quota(db, plan_code).items():
        setattr(q, k, v)

    db.flush()
    if request is not None:
        _audit_registration(request, user, tenant)
    return tenant, org, user, sub


def _audit_registration(request: Request, user: SystemUser, tenant: Tenant) -> None:
    """注册开通审计（独立 Session，与 auth.py _write_audit 同法，防回滚污染）。"""
    s = SessionLocal()
    try:
        s.add(AuditLog(
            log_no=gen_no("AL"), user_id=user.id, username=user.username,
            tenant_id=tenant.id, action="tenant.provision", module="auth",
            method=request.method, path=request.url.path, result="SUCCESS",
            ip=request.client.host if request.client else None,
            ua=request.headers.get("user-agent", ""),
        ))
        s.commit()
    except Exception:  # noqa: BLE001
        s.rollback()
        logger.warning("tenant.provision 审计写入失败 tenant_id=%s", tenant.id)
    finally:
        s.close()
