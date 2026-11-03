# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""邮件适配器：smtplib + 现有 SMTP_* 全局配置。

渠道 config 支持键：host / port / user / password / from_addr / to_addrs（列表或逗号串）。
缺字段逐项回退 settings.SMTP_*（保留"租户未配 email 渠道时走全局通道"的既有行为）；
全局也未配置 → 返回失败（可重试 → emit 记 DEGRADED，站内信已兜底）。
"""

from __future__ import annotations

import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from ...config import settings
from .base import SEND_TIMEOUT, SendResult


def _as_list(v) -> list[str]:
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def send(config: dict, msg: dict) -> SendResult:
    cfg = config or {}
    host = str(cfg.get("host") or settings.SMTP_HOST or "")
    try:
        port = int(cfg.get("port") or settings.SMTP_PORT or 465)
    except (TypeError, ValueError):
        port = 465
    user = str(cfg.get("user") or settings.SMTP_USER or "")
    password = str(cfg.get("password") or settings.SMTP_PASSWORD or "")
    from_addr = str(cfg.get("from_addr") or user or "")
    to_addrs = _as_list(cfg.get("to_addrs") or cfg.get("to") or user)

    if not host or not from_addr or not to_addrs:
        # SMTP 未配置：视为可重试失败（emit 层重试后记 DEGRADED，站内信兜底）
        return SendResult(ok=False, error="SMTP 未配置（host/from/to 缺失）", retryable=True)

    subject = str(msg.get("title") or "")
    body = str(msg.get("content") or "")
    try:
        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = Header(subject, "utf-8")
        message["From"] = formataddr((str(Header("EvalShield", "utf-8")), from_addr))
        message["To"] = ", ".join(to_addrs)

        smtp_cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        with smtp_cls(host, port, timeout=SEND_TIMEOUT) as server:
            if port != 465:
                try:
                    server.starttls()
                except smtplib.SMTPException:
                    pass  # 明文内网网关允许降级
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, to_addrs, message.as_string())
        return SendResult(ok=True)
    except Exception as exc:  # noqa: BLE001 —— 网络/对端类失败统一可重试
        return SendResult(ok=False, error=f"邮件发送失败: {exc.__class__.__name__}: {exc}", retryable=True)
