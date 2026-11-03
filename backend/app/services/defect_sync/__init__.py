# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M11 缺陷工单同步适配器注册表（provider → 适配器模块）。

与 notify_adapters 同构：provider 枚举面 + 按 kind 分发；
未知 provider 由路由层记 FAILED。
回写能力：github=webhook 双向；gitee=scheduler 日轮询；jira=单向。
"""

from __future__ import annotations

from .base import SyncResult, append_system_note, apply_external_state, defect_payload
from . import gitee as _gitee
from . import github as _github
from . import jira as _jira

# 支持的工单平台（defect_sync_targets.provider 枚举面）
PROVIDERS = ("github", "gitee", "jira")

ADAPTERS = {
    "github": _github,
    "gitee": _gitee,
    "jira": _jira,
}

__all__ = [
    "ADAPTERS", "PROVIDERS", "SyncResult", "defect_payload",
    "append_system_note", "apply_external_state",
]
