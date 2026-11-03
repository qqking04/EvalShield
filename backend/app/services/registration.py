# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""自助注册闸门（ES8 M1，共享域——auth.py 属 OSS 树，禁止 import commercial）。

收敛原 auth.py 内联的 `feature_enabled("multi_tenant")` 判定为单一事实源：
- saas：`feature_enabled("multi_tenant")`（行为不变，注册即开新租户）
- enterprise：`feature_enabled("self_register")`（License 授权才开放自助注册）
- community：恒 False（OSS 版由管理员后台建号）
"""

from __future__ import annotations

from ..config import settings
from ..enterprise.features import feature_enabled


def registration_enabled() -> bool:
    """当前形态是否开放自助注册。"""
    edition = settings.EDITION
    if edition == "saas":
        return feature_enabled("multi_tenant")
    if edition == "enterprise":
        return feature_enabled("self_register")
    # community 及未知形态：不开放
    return False
