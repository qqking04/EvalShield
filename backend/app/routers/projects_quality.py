# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""优化 4：项目质量视图（实时聚合）（doc/优化4方案.md §4.2）。

- GET /api/projects/{project_id}/quality-overview  视图（登录即可，租户隔离）

版本隔离改造（B13）：GET /api/projects/{project_id}/quality-report/export
已剪切迁出至 app/commercial/routers/quality_export.py（URL 不变），
渲染 helper 群仅被导出端点使用，随迁。
数据源单一：视图与导出均走 services.quality_view.build_quality_payload，
"页面所见"与"导出所得"数字 100% 同源。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import authenticate_request
from ..errors import ok
from ..services.quality_view import build_quality_payload
from .projects_ext import _load_project

router = APIRouter()


@router.get("/projects/{project_id}/quality-overview", response_model=dict)
async def quality_overview(
    project_id: int,
    days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
    auth=Depends(authenticate_request),
):
    """项目质量视图（实时聚合，不落库；登录即可 + 租户/可见性校验）。"""
    project = _load_project(db, project_id, auth)
    payload = build_quality_payload(db, project, auth.tenant_id, days)
    return ok(payload)
