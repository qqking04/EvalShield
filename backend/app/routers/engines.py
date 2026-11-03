# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""测试引擎路由：注册表列表、引擎详情、注册表同步到数据库。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import AuthContext, authenticate_request, require_permission
from ..engines.registry import discover_engines, engine_registry
from ..models import TestEngine
from ..schemas import EngineOut

router = APIRouter()


class EngineStatusUpdate(BaseModel):
    status: str = Field(pattern="^(ENABLED|DISABLED)$")


@router.get("", response_model=dict)
async def list_engines(
    db: Session = Depends(get_db), auth: AuthContext = Depends(authenticate_request)
):
    """引擎列表（含内置注册表 + 数据库记录）。"""
    discover_engines()
    registry_meta = engine_registry.meta_list()
    db_rows = db.query(TestEngine).order_by(TestEngine.id).all()
    synced = {e.engine_code for e in db_rows}
    items = []
    for m in registry_meta:
        row = {
            "engine_code": m["engine_code"],
            "engine_name": m["engine_name"],
            "engine_type": m["engine_type"],
            "category": m["category"],
            "version": m["version"],
            "description": m["description"],
            "fidelity": m["fidelity"],
            "params_schema": m["params_schema"],
            "status": "ENABLED",
            "is_system": True,
        }
        if m["engine_code"] in synced:
            db_e = next(e for e in db_rows if e.engine_code == m["engine_code"])
            row["status"] = db_e.status
            row["supports_params"] = getattr(db_e, "supports_params", None)
        items.append(row)
    for e in db_rows:
        if e.engine_code not in {m["engine_code"] for m in registry_meta}:
            # 社区形态：仅展示内存注册表（12 社区引擎），
            # 不合并 DB 存量行（同库商业形态 seed 的 16 商业引擎行会泄露）
            if settings.EDITION == "community":
                continue
            items.append(EngineOut.model_validate(e).model_dump())
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": items, "total": len(items)},
    }


@router.get("/{engine_code}", response_model=dict)
async def get_engine_detail(
    engine_code: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """引擎详情：支持参数 schema 与说明。"""
    discover_engines()
    engine = engine_registry.get(engine_code)
    db_e = db.query(TestEngine).filter(TestEngine.engine_code == engine_code).first()
    if engine is None and db_e is None:
        return {"code": 0, "message": "ok", "data": None}
    base = {
        "engine_code": engine_code,
        "engine_name": engine.engine_name
        if engine
        else (db_e.engine_name if db_e else ""),
        "engine_type": engine.engine_type
        if engine
        else (db_e.engine_type if db_e else ""),
        "category": engine.category if engine else (db_e.category if db_e else ""),
        "version": engine.version if engine else (db_e.version if db_e else ""),
        "description": engine.description
        if engine
        else (db_e.description if db_e else ""),
        "fidelity": engine.fidelity
        if engine
        else (db_e.fidelity if db_e else ""),
        "params_schema": engine.params_schema if engine else None,
    }
    if db_e:
        base["status"] = db_e.status
        base["supports_params"] = db_e.supports_params
    else:
        base["status"] = "ENABLED"
        base["supports_params"] = {}
    return {"code": 0, "message": "ok", "data": base}


@router.put("/{engine_code}/status", response_model=dict)
async def set_engine_status(
    engine_code: str,
    body: EngineStatusUpdate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
    _: AuthContext = Depends(require_permission("admin", "*")),
):
    """引擎开关：ENABLED/DISABLED（注册表内置引擎若未落库则自动 upsert）。"""
    discover_engines()
    meta = next((m for m in engine_registry.meta_list() if m["engine_code"] == engine_code), None)
    row = db.query(TestEngine).filter(TestEngine.engine_code == engine_code).first()
    if row is None:
        if meta is None:
            return {"code": 4040, "message": f"引擎 {engine_code} 不存在", "data": None}
        row = TestEngine(
            engine_code=meta["engine_code"],
            engine_name=meta["engine_name"],
            engine_type=meta["engine_type"],
            category=meta["category"],
            version=meta["version"],
            description=meta["description"],
            status=body.status,
            is_system=True,
        )
        db.add(row)
    else:
        row.status = body.status
    db.commit()
    db.refresh(row)
    return {"code": 0, "message": "ok", "data": {"engine_code": row.engine_code, "status": row.status}}


@router.post("/sync", response_model=dict)
async def sync_engines(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
    _: AuthContext = Depends(require_permission("admin", "*")),
):
    """将内置注册表同步到数据库 test_engines（幂等：按 engine_code upsert）。"""
    discover_engines()
    synced_count = 0
    for m in engine_registry.meta_list():
        row = (
            db.query(TestEngine)
            .filter(TestEngine.engine_code == m["engine_code"])
            .first()
        )
        if row is None:
            db.add(
                TestEngine(
                    engine_code=m["engine_code"],
                    engine_name=m["engine_name"],
                    engine_type=m["engine_type"],
                    category=m["category"],
                    version=m["version"],
                    description=m["description"],
                    fidelity=m["fidelity"],
                    status="ENABLED",
                    is_system=True,
                )
            )
            synced_count += 1
        else:
            row.engine_name = m["engine_name"]
            row.engine_type = m["engine_type"]
            row.category = m["category"]
            row.version = m["version"]
            row.description = m["description"]
            row.fidelity = m["fidelity"]
            synced_count += 1
    db.commit()
    return {
        "code": 0,
        "message": "ok",
        "data": {"synced_count": synced_count, "total": len(engine_registry.codes())},
    }
