# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M3 通知中心路由（§4.4）：渠道 CRUD + 发送测试、规则 CRUD、投递留痕查询。

安全约束：列表/详情响应绝不回显 config 原文（加密串也不回显），
创建/更新接收 JSON 明文经 encrypt_secret 加密落库。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import AuthContext, ensure_data_scope, require_permission
from ..errors import BizError, NotFoundError
from ..models import NotifyChannelConfig, NotifyDelivery, NotifyRule
from ..security import decrypt_secret, encrypt_secret
from ..services.audit import write_audit
from ..services.notifications import (
    EVENTS,
    EVENT_LABELS,
    SEVERITY_ORDER,
    _record_delivery,
    render_message,
)
from ..services.notify_adapters import ADAPTERS, CHANNEL_KINDS

router = APIRouter()

_KIND_PATTERN = "^(" + "|".join(CHANNEL_KINDS) + ")$"
_SEV_PATTERN = "^(" + "|".join(SEVERITY_ORDER.keys()) + ")$"


# ---------------------------------------------------------------- 渠道 ----

class ChannelCreate(BaseModel):
    kind: str = Field(..., pattern=_KIND_PATTERN)
    name: str = Field(..., min_length=1, max_length=128)
    config: dict = Field(default_factory=dict, description="渠道参数明文 JSON")
    enabled: bool = True


class ChannelUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    config: dict | None = None
    enabled: bool | None = None


def _channel_out(c: NotifyChannelConfig) -> dict:
    """渠道出参：绝不回显 config 原文/密文，仅给参数键名供前端展示。"""
    keys: list[str] = []
    try:
        cfg = json.loads(decrypt_secret(c.config))
        if isinstance(cfg, dict):
            keys = sorted(cfg.keys())
    except Exception:  # noqa: BLE001 —— 解密失败按空处理，不影响列表
        keys = []
    return {
        "id": c.id,
        "tenant_id": c.tenant_id,
        "kind": c.kind,
        "name": c.name,
        "config_keys": keys,
        "enabled": c.enabled,
        "last_probe_at": c.last_probe_at,
        "last_probe_ok": c.last_probe_ok,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


def _get_channel(db: Session, channel_id: int, auth: AuthContext) -> NotifyChannelConfig:
    c = db.query(NotifyChannelConfig).filter(NotifyChannelConfig.id == channel_id).first()
    if c is None:
        raise NotFoundError("ES-BIZ-0080", "通知渠道不存在")
    return c


@router.get("/channels", response_model=dict)
async def list_channels(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    kind: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("notify", "manage")),
):
    q = db.query(NotifyChannelConfig)
    if not auth.is_super_admin:
        q = q.filter(NotifyChannelConfig.tenant_id == auth.tenant_id)
    if kind:
        q = q.filter(NotifyChannelConfig.kind == kind)
    total = q.count()
    rows = q.order_by(NotifyChannelConfig.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"code": 0, "message": "ok", "data": {"items": [_channel_out(c) for c in rows], "total": total}}


@router.post("/channels", response_model=dict)
async def create_channel(
    body: ChannelCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("notify", "manage")),
):
    if body.kind not in ADAPTERS:
        raise BizError("ES-BIZ-0081", f"不支持的渠道类型：{body.kind}")
    c = NotifyChannelConfig(
        tenant_id=auth.tenant_id,
        kind=body.kind,
        name=body.name,
        config=encrypt_secret(json.dumps(body.config or {}, ensure_ascii=False)),
        enabled=body.enabled,
        created_by=auth.user_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="notify.channel.create", module="notify", request=request,
        detail=f"新建通知渠道：{c.name}（{c.kind}）",
    )
    return {"code": 0, "message": "ok", "data": _channel_out(c)}


@router.put("/channels/{channel_id}", response_model=dict)
async def update_channel(
    channel_id: int,
    body: ChannelUpdate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("notify", "manage")),
):
    c = _get_channel(db, channel_id, auth)
    await ensure_data_scope(auth, resource_tenant_id=c.tenant_id)
    if body.name is not None:
        c.name = body.name
    if body.config is not None:
        c.config = encrypt_secret(json.dumps(body.config, ensure_ascii=False))
    if body.enabled is not None:
        c.enabled = body.enabled
    db.commit()
    db.refresh(c)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="notify.channel.update", module="notify", request=request,
        detail=f"更新通知渠道：{c.name}（{c.id}）",
    )
    return {"code": 0, "message": "ok", "data": _channel_out(c)}


@router.delete("/channels/{channel_id}", response_model=dict)
async def delete_channel(
    channel_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("notify", "manage")),
):
    c = _get_channel(db, channel_id, auth)
    await ensure_data_scope(auth, resource_tenant_id=c.tenant_id)
    name = c.name
    db.delete(c)
    db.commit()
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="notify.channel.delete", module="notify", request=request,
        detail=f"删除通知渠道：{name}（{channel_id}）",
    )
    return {"code": 0, "message": "ok", "data": {"deleted": True}}


@router.post("/channels/{channel_id}/test", response_model=dict)
async def test_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("notify", "manage")),
):
    """发送测试：解密配置 → 直调适配器一次（不重试）→ 更新探测态 + 投递留痕。"""
    c = _get_channel(db, channel_id, auth)
    await ensure_data_scope(auth, resource_tenant_id=c.tenant_id)
    msg = render_message(
        "channel.test",
        {"title": f"[EvalShield] 通知渠道连通测试：{c.name}",
         "content": f"渠道「{c.name}」（{c.kind}）发送测试，收到即表示配置可用。"},
        "LOW",
    )
    adapter = ADAPTERS.get(c.kind)
    probe_ok = False
    error: str | None = None
    if adapter is None:
        error = f"未知渠道类型 {c.kind}"
        msg = {**msg, "content": error}
    else:
        try:
            config = json.loads(decrypt_secret(c.config))
            if not isinstance(config, dict):
                raise ValueError("渠道配置解密后不是 JSON 对象")
        except Exception as exc:  # noqa: BLE001
            error = f"配置解密失败: {exc}"
            msg = {**msg, "content": error}
        else:
            result = adapter(config, msg)  # 测试语义：单次发送，失败不重试
            probe_ok = bool(result.ok)
            error = result.error
    c.last_probe_at = datetime.now(timezone.utc)
    c.last_probe_ok = probe_ok
    db.commit()
    _record_delivery(db, c.tenant_id, None, msg, c, "SUCCESS" if probe_ok else "FAILED", error, 1)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=c.tenant_id,
        action="notify.channel.test", module="notify",
        detail=f"渠道测试：{c.name} 结果={'成功' if probe_ok else '失败'}",
    )
    return {"code": 0, "message": "ok", "data": {"ok": probe_ok, "error": error}}


# ---------------------------------------------------------------- 规则 ----

class RuleCreate(BaseModel):
    event: str = Field(..., pattern="^(" + "|".join(EVENTS) + ")$")
    scope: dict | None = None
    channel_ids: list[int] = Field(default_factory=list)
    template_key: str | None = None
    min_severity: str = Field("LOW", pattern=_SEV_PATTERN)
    enabled: bool = True


class RuleUpdate(BaseModel):
    scope: dict | None = None
    channel_ids: list[int] | None = None
    template_key: str | None = None
    min_severity: str | None = Field(None, pattern=_SEV_PATTERN)
    enabled: bool | None = None


def _rule_out(r: NotifyRule) -> dict:
    try:
        scope = json.loads(r.scope) if (r.scope or "").strip() else None
    except (ValueError, TypeError):
        scope = None
    try:
        cids = [int(x) for x in json.loads(r.channel_ids or "[]")]
    except (ValueError, TypeError):
        cids = []
    return {
        "id": r.id,
        "tenant_id": r.tenant_id,
        "event": r.event,
        "scope": scope,
        "channel_ids": cids,
        "template_key": r.template_key,
        "min_severity": r.min_severity,
        "enabled": r.enabled,
        "created_at": r.created_at,
    }


@router.get("/events", response_model=dict)
async def list_events(
    auth: AuthContext = Depends(require_permission("notify", "manage")),
):
    """事件语义面（前端规则下拉用）。"""
    return {"code": 0, "message": "ok", "data": [
        {"event": e, "label": EVENT_LABELS.get(e, e)} for e in EVENTS
    ]}


@router.get("/rules", response_model=dict)
async def list_rules(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    event: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("notify", "manage")),
):
    q = db.query(NotifyRule)
    if not auth.is_super_admin:
        q = q.filter(NotifyRule.tenant_id == auth.tenant_id)
    if event:
        q = q.filter(NotifyRule.event == event)
    total = q.count()
    rows = q.order_by(NotifyRule.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"code": 0, "message": "ok", "data": {"items": [_rule_out(r) for r in rows], "total": total}}


@router.post("/rules", response_model=dict)
async def create_rule(
    body: RuleCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("notify", "manage")),
):
    r = NotifyRule(
        tenant_id=auth.tenant_id,
        event=body.event,
        scope=json.dumps(body.scope, ensure_ascii=False) if body.scope else None,
        channel_ids=json.dumps(body.channel_ids, ensure_ascii=False),
        template_key=body.template_key,
        min_severity=body.min_severity,
        enabled=body.enabled,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="notify.rule.create", module="notify", request=request,
        detail=f"新建通知规则：{r.event} → 渠道 {body.channel_ids}",
    )
    return {"code": 0, "message": "ok", "data": _rule_out(r)}


@router.put("/rules/{rule_id}", response_model=dict)
async def update_rule(
    rule_id: int,
    body: RuleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("notify", "manage")),
):
    r = db.query(NotifyRule).filter(NotifyRule.id == rule_id).first()
    if r is None:
        raise NotFoundError("ES-BIZ-0082", "通知规则不存在")
    await ensure_data_scope(auth, resource_tenant_id=r.tenant_id)
    if body.scope is not None:
        r.scope = json.dumps(body.scope, ensure_ascii=False) if body.scope else None
    if body.channel_ids is not None:
        r.channel_ids = json.dumps(body.channel_ids, ensure_ascii=False)
    if body.template_key is not None:
        r.template_key = body.template_key
    if body.min_severity is not None:
        r.min_severity = body.min_severity
    if body.enabled is not None:
        r.enabled = body.enabled
    db.commit()
    db.refresh(r)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="notify.rule.update", module="notify", request=request,
        detail=f"更新通知规则：{r.event}（{r.id}）",
    )
    return {"code": 0, "message": "ok", "data": _rule_out(r)}


@router.delete("/rules/{rule_id}", response_model=dict)
async def delete_rule(
    rule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("notify", "manage")),
):
    r = db.query(NotifyRule).filter(NotifyRule.id == rule_id).first()
    if r is None:
        raise NotFoundError("ES-BIZ-0082", "通知规则不存在")
    await ensure_data_scope(auth, resource_tenant_id=r.tenant_id)
    event = r.event
    db.delete(r)
    db.commit()
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="notify.rule.delete", module="notify", request=request,
        detail=f"删除通知规则：{event}（{rule_id}）",
    )
    return {"code": 0, "message": "ok", "data": {"deleted": True}}


# ------------------------------------------------------------ 投递留痕 ----

def _delivery_out(d: NotifyDelivery) -> dict:
    return {
        "id": d.id,
        "tenant_id": d.tenant_id,
        "rule_id": d.rule_id,
        "event": d.event,
        "channel_kind": d.channel_kind,
        "channel_id": d.channel_id,
        "payload": d.payload,
        "status": d.status,
        "error": d.error,
        "attempts": d.attempts,
        "created_at": d.created_at,
    }


@router.get("/deliveries", response_model=dict)
async def list_deliveries(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    event: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("notify", "manage")),
):
    if status is not None and status not in ("SUCCESS", "FAILED", "DEGRADED", "SKIPPED"):
        raise BizError("ES-BIZ-0083", f"非法投递状态：{status}")
    q = db.query(NotifyDelivery)
    if not auth.is_super_admin:
        q = q.filter(NotifyDelivery.tenant_id == auth.tenant_id)
    if status:
        q = q.filter(NotifyDelivery.status == status)
    if event:
        q = q.filter(NotifyDelivery.event == event)
    total = q.count()
    rows = q.order_by(NotifyDelivery.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"code": 0, "message": "ok", "data": {"items": [_delivery_out(d) for d in rows], "total": total}}
