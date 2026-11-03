# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M3 通知渠道适配器基础约定。

所有适配器实现 ``send(config, msg) -> SendResult``：
- config：decrypt_secret + json.loads 后的渠道配置 dict；
- msg：渲染好的消息 {title, content, event, severity, payload}；
- 单次调用内部超时 3 秒；不抛异常，统一以 SendResult 返回。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SendResult:
    """适配器发送结果。

    retryable=True：网络/对端类失败，emit 层重试 1 次后记 DEGRADED；
    retryable=False：配置类失败（缺 URL 等），直接记 FAILED 不重试。
    """

    ok: bool
    error: str | None = None
    retryable: bool = False


# 统一发送超时（秒），§4.3：同步 3s 超时
SEND_TIMEOUT = 3.0
