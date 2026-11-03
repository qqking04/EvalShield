# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""版本形态契约路由（版本隔离改造 B8，方案 §2-B8）。

GET /api/edition：前后端唯一契约，免登录可访问（匿名即社区可见口径）。
- edition    ：settings.EDITION 实态（community / saas / enterprise）
- commercial ：商业模块是否实际挂载（app.state.commercial_mounted，
               community 发布树物理缺席时为 False）
- enabled_engines：与引擎注册表实态一致，动态生成（非硬编码清单）
- limits     ：社区版配额表（COMMUNITY_LIMITS，前端据此展示上限文案）
- license    ：enterprise 专有字段（register._license_gate 结果），
               未挂载/无状态时降级 {"valid": false, "reason": "...", "expires_at": None}
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..config import settings
from ..engines import engine_registry
from ..engines.registry import discover_engines
from ..limits import COMMUNITY_LIMITS

router = APIRouter()

_DEFAULT_LICENSE = {"valid": False, "reason": "非企业版形态或未激活授权", "expires_at": None}


@router.get("/edition", response_model=dict)
async def get_edition(request: Request):
    """当前部署形态与能力（免登录；URL 与响应结构即前后端契约，勿改）。"""
    discover_engines()
    commercial = bool(getattr(request.app.state, "commercial_mounted", False))
    license_status = getattr(request.app.state, "license_status", None) or _DEFAULT_LICENSE
    # 优化7 T5：三态 phase 按存储的 expires_at 请求时动态重算（grace/revoked 相变在运行期）
    from ..config import settings
    from ..license_state import resolve_license_state

    lic_phase = resolve_license_state(license_status, settings.LICENSE_GRACE_DAYS)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "edition": settings.EDITION,
            "commercial": commercial,
            "enabled_engines": sorted(engine_registry.codes()),
            "limits": COMMUNITY_LIMITS,
            "license": {
                "valid": bool(license_status.get("valid")),
                "reason": license_status.get("reason") or "",
                "expires_at": license_status.get("expires_at"),
                "phase": lic_phase.get("phase"),
                "grace_remaining_days": lic_phase.get("grace_remaining_days"),
            },
            # 优化7 T6：平台运营区（/api/tenants 等）可用门控——仅 saas 形态；
            # 具体身份（platform_admin / SUPER_ADMIN）由前端结合会话 userType 判定
            "platform": {
                "available": settings.EDITION == "saas" and commercial,
                "tenants_api": settings.EDITION == "saas",
            },
        },
    }
