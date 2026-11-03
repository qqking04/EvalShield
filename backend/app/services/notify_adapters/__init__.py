# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M3 通知渠道适配器注册表。

kind → send(config, msg) 映射；未知 kind 由 emit 层记 FAILED。
"""

from __future__ import annotations

from .base import SEND_TIMEOUT, SendResult
from . import email as _email
from . import im_bots as _im
from . import webhook as _webhook

# 支持的渠道类型（notify_channels.kind 枚举面）
CHANNEL_KINDS = ("email", "dingtalk", "feishu", "wecom", "webhook")

ADAPTERS = {
    "email": _email.send,
    "webhook": _webhook.send,
    "dingtalk": _im.send_dingtalk,
    "feishu": _im.send_feishu,
    "wecom": _im.send_wecom,
}

__all__ = ["ADAPTERS", "CHANNEL_KINDS", "SEND_TIMEOUT", "SendResult"]
