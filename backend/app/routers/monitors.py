# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M4 定时监控路由（§5.4）：monitors CRUD + run-now + 告警时间线。

守卫范式照 business.py：每个端点函数内 capability "monitor" 门控（403 ES-LIC-0003）
+ require_permission("monitor", read/manage)（section 45 已种子权限点）；
租户隔离：非超管一律按 auth.tenant_id 过滤。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import AuthContext, require_permission
from ..errors import BizError, NotFoundError
from ..models import Monitor, MonitorAlert, TestSuite
from ..services.audit import write_audit
from ..services.monitor import ALERT_METRICS, fire_monitor
from ..utils.cron import next_fire

router = APIRouter()


def _guard_monitor_feature() -> None:
    """能力位闸门：monitor 未开启（community / enterprise 未授权）一律 403。"""
    from ..enterprise.features import feature_enabled

    if not feature_enabled("monitor"):
        raise BizError(
            "ES-LIC-0003",
            "定时监控为企业/SaaS 能力（monitor），请先开通该能力",
            http_status=403,
        )


# ---------------------------------------------------------------- 请求体 ----

class AlertCondition(BaseModel):
    metric: str = Field(..., description="|".join(ALERT_METRICS))
    op: str = Field("lt", pattern="^(lt|gt)$")
    threshold: float


class MonitorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    suite_id: int
    cron: str = Field(..., min_length=1, max_length=32)
    alert_conditions: list[AlertCondition] = Field(default_factory=list)
    enabled: bool = True


class MonitorUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    suite_id: int | None = None
    cron: str | None = Field(None, min_length=1, max_length=32)
    alert_conditions: list[AlertCondition] | None = None
    enabled: bool | None = None


# ------------------------------------------------------------------ 工具 ----

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_conditions(conds: list[AlertCondition]) -> str:
    for c in conds:
        if c.metric not in ALERT_METRICS:
            raise BizError("ES-BIZ-0090", f"不支持的告警指标：{c.metric}（可选 {'/'.join(ALERT_METRICS)}）")
    return json.dumps([c.model_dump() for c in conds], ensure_ascii=False)


def _validate_suite(db: Session, suite_id: int, auth: AuthContext) -> None:
    q = db.query(TestSuite).filter(TestSuite.id == suite_id, TestSuite.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(TestSuite.tenant_id == auth.tenant_id)
    if q.first() is None:
        raise BizError("ES-BIZ-0091", "套件不存在或不属于当前租户")


def _get_monitor(db: Session, monitor_id: int, auth: AuthContext) -> Monitor:
    q = db.query(Monitor).filter(Monitor.id == monitor_id)
    if not auth.is_super_admin:
        q = q.filter(Monitor.tenant_id == auth.tenant_id)
    m = q.first()
    if m is None:
        raise NotFoundError("ES-BIZ-0092", "监控不存在")
    return m


def _firing_count_map(db: Session, monitor_ids: list[int]) -> dict[int, int]:
    """各 monitor 当前 FIRING（未恢复）告警数，用于列表红点。"""
    if not monitor_ids:
        return {}
    rows = (
        db.query(MonitorAlert.monitor_id, func.count(MonitorAlert.id))
        .filter(
            MonitorAlert.monitor_id.in_(monitor_ids),
            MonitorAlert.state == "FIRING",
            MonitorAlert.resolved_at.is_(None),
        )
        .group_by(MonitorAlert.monitor_id)
        .all()
    )
    return {r[0]: int(r[1]) for r in rows}


def _monitor_out(m: Monitor, firing: int) -> dict:
    try:
        conds = json.loads(m.alert_conditions or "[]")
    except (TypeError, ValueError):
        conds = []
    return {
        "id": m.id,
        "tenant_id": m.tenant_id,
        "name": m.name,
        "suite_id": m.suite_id,
        "cron": m.cron,
        "alert_conditions": conds,
        "enabled": m.enabled,
        "baseline_mode": m.baseline_mode,
        "last_run_id": m.last_run_id,
        "last_checked_at": m.last_checked_at,
        "next_fire_at": m.next_fire_at,
        "firing_count": firing,
        "created_at": m.created_at,
        "updated_at": m.updated_at,
    }


# ---------------------------------------------------------------- 端点 ----

@router.get("", response_model=dict)
async def list_monitors(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("monitor", "read")),
):
    """监控列表（含 next_fire_at 与各 monitor 最近 FIRING 数）。"""
    _guard_monitor_feature()
    q = db.query(Monitor)
    if not auth.is_super_admin:
        q = q.filter(Monitor.tenant_id == auth.tenant_id)
    total = q.count()
    rows = q.order_by(Monitor.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    firing = _firing_count_map(db, [r.id for r in rows])
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": [_monitor_out(r, firing.get(r.id, 0)) for r in rows], "total": total},
    }


@router.post("", response_model=dict)
async def create_monitor(
    body: MonitorCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("monitor", "manage")),
):
    """创建监控：cron 必须可解析，suite 必须属本租户；next_fire_at 立即求值。"""
    _guard_monitor_feature()
    if next_fire(body.cron, _now()) is None:
        raise BizError("ES-BIZ-0093", f"cron 表达式无效或 400 天内不可能命中：{body.cron!r}")
    _validate_suite(db, body.suite_id, auth)
    m = Monitor(
        tenant_id=auth.tenant_id,
        org_id=0,
        name=body.name,
        suite_id=body.suite_id,
        cron=body.cron.strip(),
        alert_conditions=_validate_conditions(body.alert_conditions),
        enabled=body.enabled,
        next_fire_at=next_fire(body.cron, _now()) if body.enabled else None,
        created_by=auth.user_id,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="monitor.create", module="monitor", request=request,
        detail=f"id={m.id} name={m.name}",
    )
    return {"code": 0, "message": "ok", "data": _monitor_out(m, 0)}


@router.put("/{monitor_id}", response_model=dict)
async def update_monitor(
    monitor_id: int,
    body: MonitorUpdate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("monitor", "manage")),
):
    """更新监控：cron/启用态变化时重求 next_fire_at。"""
    _guard_monitor_feature()
    m = _get_monitor(db, monitor_id, auth)
    if body.suite_id is not None:
        _validate_suite(db, body.suite_id, auth)
        m.suite_id = body.suite_id
    if body.name is not None:
        m.name = body.name
    if body.alert_conditions is not None:
        m.alert_conditions = _validate_conditions(body.alert_conditions)
    if body.cron is not None:
        if next_fire(body.cron, _now()) is None:
            raise BizError("ES-BIZ-0093", f"cron 表达式无效或 400 天内不可能命中：{body.cron!r}")
        m.cron = body.cron.strip()
    if body.enabled is not None:
        m.enabled = body.enabled
    # 启用态 / cron 变更后重排下次触发；停用则清空
    m.next_fire_at = next_fire(m.cron, _now()) if m.enabled else None
    db.add(m)
    db.commit()
    db.refresh(m)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="monitor.update", module="monitor", request=request,
        detail=f"id={m.id}",
    )
    firing = _firing_count_map(db, [m.id]).get(m.id, 0)
    return {"code": 0, "message": "ok", "data": _monitor_out(m, firing)}


@router.delete("/{monitor_id}", response_model=dict)
async def delete_monitor(
    monitor_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("monitor", "manage")),
):
    """删除监控（物理删；告警时间线保留，按 monitor_id 逻辑引用可追溯）。"""
    _guard_monitor_feature()
    m = _get_monitor(db, monitor_id, auth)
    db.delete(m)
    db.commit()
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="monitor.delete", module="monitor", request=request,
        detail=f"id={monitor_id}",
    )
    return {"code": 0, "message": "ok", "data": {"deleted": monitor_id}}


@router.post("/{monitor_id}/run-now", response_model=dict)
async def run_monitor_now(
    monitor_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("monitor", "manage")),
):
    """绕过 cron 立即触发一次（不等 tick；批次执行完成后由 tick 评估告警）。"""
    _guard_monitor_feature()
    m = _get_monitor(db, monitor_id, auth)
    task_ids = fire_monitor(db, m)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="monitor.run_now", module="monitor", request=request,
        detail=f"id={m.id} tasks={task_ids}",
    )
    return {"code": 0, "message": "ok", "data": {"monitor_id": m.id, "created_task_ids": task_ids}}


@router.get("/{monitor_id}/alerts", response_model=dict)
async def list_monitor_alerts(
    monitor_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    state: str | None = Query(None, pattern="^(FIRING|RESOLVED)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("monitor", "read")),
):
    """告警时间线（FIRING|RESOLVED，按 fired_at 倒序）。"""
    _guard_monitor_feature()
    m = _get_monitor(db, monitor_id, auth)
    q = db.query(MonitorAlert).filter(MonitorAlert.monitor_id == m.id)
    if state:
        q = q.filter(MonitorAlert.state == state)
    total = q.count()
    rows = (
        q.order_by(MonitorAlert.fired_at.desc(), MonitorAlert.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "id": a.id,
            "monitor_id": a.monitor_id,
            "run_id": a.run_id,
            "metric": a.metric,
            "value": a.value,
            "threshold": a.threshold,
            "op": a.op,
            "state": a.state,
            "fired_at": a.fired_at,
            "resolved_at": a.resolved_at,
            "notified": a.notified,
        }
        for a in rows
    ]
    return {"code": 0, "message": "ok", "data": {"items": items, "total": total}}
