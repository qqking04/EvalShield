# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""ES11：defect_events 追加式仓储（开发方案 §4.3）。

硬约束：只追加、不改写、不删除——本模块不提供 UPDATE/DELETE 路径；
事件写入与状态变更在同一事务内提交，保证时间线与状态机一致。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import DefectEvent

EVENT_TYPES = (
    "CREATED", "ASSIGNED", "REMEDIATED", "RETEST_STARTED",
    "VERIFIED", "REOPENED", "WAIVED", "CORRECTION",
)


def append(
    db: Session,
    *,
    defect_id: int,
    event_type: str,
    actor_id: int,
    actor_name: str | None = None,
    tenant_id: int = 1,
    status_from: str | None = None,
    status_to: str | None = None,
    run_id: int | None = None,
    project_version_id: int | None = None,
    note: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> DefectEvent:
    """追加一条事件（调用方负责 db.commit()，与状态变更同事务）。"""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"非法事件类型 {event_type}（允许：{EVENT_TYPES}）")
    ev = DefectEvent(
        defect_id=int(defect_id),
        event_type=event_type,
        status_from=status_from,
        status_to=status_to,
        run_id=run_id,
        project_version_id=project_version_id,
        note=note,
        evidence=evidence,
        actor_id=int(actor_id),
        actor_name=actor_name,
        tenant_id=int(tenant_id),
    )
    db.add(ev)
    db.flush()
    return ev


def timeline(db: Session, defect_id: int) -> list[DefectEvent]:
    return (
        db.query(DefectEvent)
        .filter(DefectEvent.defect_id == int(defect_id))
        .order_by(DefectEvent.created_at.asc(), DefectEvent.id.asc())
        .all()
    )


def timeline_bulk(db: Session, defect_ids: list[int]) -> list[DefectEvent]:
    """批量读取（只读，供 P5 列表富化；不改变只追加语义）。"""
    if not defect_ids:
        return []
    return (
        db.query(DefectEvent)
        .filter(DefectEvent.defect_id.in_([int(i) for i in defect_ids]))
        .order_by(DefectEvent.defect_id.asc(),
                  DefectEvent.created_at.asc(), DefectEvent.id.asc())
        .all()
    )
