# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""优化7 T5：License 到期三态状态机（active → grace → revoked）。

条款（说明书 §5）：
- active   : now < expires_at，全功能。
- grace    : expires_at < now ≤ expires_at + LICENSE_GRACE_DAYS（默认 30 天），
             只读锁——GET 全通，写操作 403 ES-LIC-EXPIRED-GRACE，
             白名单=改密/登出/License 激活；能力位仍回放（不做破坏性锁定）。
- revoked  : 超宽限未续证，停服——非超管登录提示「授权已过期，联系服务商」，
             超管仅可达 License 管理页续证。
- 买断证 expires_at 为 null → 永远 active，永不进 grace/revoked。

本模块纯函数、无项目依赖，供 register._license_gate / middleware /
edition_core / auth 登录拦截共同消费。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

PHASE_ACTIVE = "active"
PHASE_GRACE = "grace"
PHASE_REVOKED = "revoked"


def _parse_expires(expires_at: object) -> datetime | None:
    """解析 ISO8601 字符串（兼容 Z 后缀、naive 视为 UTC）；null/解析失败返回 None。"""
    if not expires_at:
        return None
    try:
        exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp


def compute_license_phase(
    expires_at: object, grace_days: int = 30, now: datetime | None = None
) -> dict:
    """按 expires_at 动态计算三态。返回 {phase, grace_remaining_days}。

    grace_remaining_days：grace 期内为剩余宽限天数（向上取整，1..grace_days），
    其余阶段为 None。
    """
    exp = _parse_expires(expires_at)
    if exp is None:  # 买断证：永不过期
        return {"phase": PHASE_ACTIVE, "grace_remaining_days": None}

    now = now or datetime.now(timezone.utc)
    if now < exp:
        return {"phase": PHASE_ACTIVE, "grace_remaining_days": None}

    deadline = exp.timestamp() + grace_days * 86400
    if now.timestamp() <= deadline:
        remaining = max(1, math.ceil((deadline - now.timestamp()) / 86400))
        return {"phase": PHASE_GRACE, "grace_remaining_days": remaining}

    return {"phase": PHASE_REVOKED, "grace_remaining_days": None}


def resolve_license_state(license_status: dict | None, grace_days: int = 30) -> dict:
    """按存储的 expires_at **请求时重算** phase（grace/revoked 相变发生在运行期，
    不能只信启动快照）。无状态（community / saas / 未挂载）返回 {}。

    约定：state 中没有 `phase` 键 → 说明闸门未进入三态流程（如验签失败未挂载），
    不参与解析。
    """
    if not license_status or "phase" not in license_status:
        return {}
    computed = compute_license_phase(
        license_status.get("expires_at"), grace_days
    )
    # 无到期日的停服态（如吊销）不允许因 expires_at 为 null 而自动回到 active
    if license_status.get("phase") == PHASE_REVOKED and not license_status.get("expires_at"):
        computed = {"phase": PHASE_REVOKED, "grace_remaining_days": None}
    return computed
