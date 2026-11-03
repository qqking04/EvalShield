# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""元数据路由（优化9 ES9-P-01/P-02）：

- GET /api/meta/feature-flags   登录态：导航 flag + 形态 + 引擎实现层级
- GET /api/meta/edition-matrix  免登录：版本能力对比矩阵（升级引导页数据源）

flag 求值链（单一事实源 app/plans.py，禁止前端重复维护常量）：
EDITION（形态）→ License 能力位（enterprise/features 进程内存态）→
resolve_flags() 逐 flag AND。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import __version__
from ..config import settings
from ..deps import AuthContext, authenticate_request
from ..engines.registry import discover_engines, engine_registry
from ..plans import build_edition_matrix, resolve_flags

router = APIRouter()


def _licensed_features() -> list[str] | None:
    """License 能力位快照（None = 未激活 License，按 EDITION 默认档位全集）。

    enterprise.features 模块在 community 构建同样存在（非 commercial 包内），
    取私有态仅作只读反射，不改其判定逻辑。
    """
    try:
        from ..enterprise import features as ef

        if ef._licensed_features is not None:  # noqa: SLF001
            return sorted(ef._licensed_features)
    except Exception:  # noqa: BLE001
        pass
    return None


@router.get("/feature-flags", response_model=dict)
async def feature_flags(auth: AuthContext = Depends(authenticate_request)):
    """导航 feature flags（登录态；前端 flags.js 消费 fail-open）。

    响应契约：{version, edition, nav_profile, flags: {<key>: bool}, engines: [...]}
    engines[] 为 ES9-P-13 扩展：公开 28 引擎实现层级（fidelity 来自类属性反射）。
    """
    flags = resolve_flags(
        edition=settings.EDITION,
        nav_profile=settings.NAV_PROFILE,
        plan_features=_licensed_features(),
    )
    discover_engines()
    engines_meta = [
        {
            "engine_code": m["engine_code"],
            "engine_name": m["engine_name"],
            "category": m["category"],
            "fidelity": m["fidelity"],
        }
        for m in engine_registry.meta_list()
    ]
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "version": __version__,
            "edition": settings.EDITION,
            "nav_profile": settings.NAV_PROFILE,
            "flags": flags,
            "engines": engines_meta,
        },
    }


@router.get("/edition-matrix", response_model=dict)
async def edition_matrix():
    """版本能力对比矩阵（免登录；数字全部由 plans.py/limits.py 常量反射生成）。

    响应契约：{rows: [{group, capability, community, professional,
    enterprise, group_edition}]} —— 前端 EditionCompare.jsx 直接消费。
    """
    return {"code": 0, "message": "ok", "data": build_edition_matrix()}
