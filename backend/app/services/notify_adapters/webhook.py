# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""通用 Webhook 适配器：HTTP POST JSON + HMAC 签名头。

签名约定（§4.3）：``X-EvalShield-Signature: sha256=<hex(sha256(secret + body))>``，
secret 取渠道 config.secret，缺省回退 settings.WEBHOOK_SECRET。
渠道 config 支持键：url（必填）/ secret / headers（附加头 dict）。
"""

from __future__ import annotations

import hashlib
import json
import logging

import httpx

from ...config import settings
from ...errors import BizError
from ..ssrf_guard import validate_base_url
from .base import SEND_TIMEOUT, SendResult

logger = logging.getLogger(__name__)


def sign_body(secret: str, body: str) -> str:
    """HMAC 简化签名：sha256(secret + body) 十六进制。"""
    return hashlib.sha256(f"{secret}{body}".encode("utf-8")).hexdigest()


def build_request(config: dict, msg: dict) -> tuple[str, str, dict]:
    """构造 (url, body_json_str, headers)，供 send 与签名自测复用。"""
    cfg = config or {}
    url = str(cfg.get("url") or "")
    secret = str(cfg.get("secret") or settings.WEBHOOK_SECRET or "")
    payload = {
        "event": msg.get("event"),
        "severity": msg.get("severity"),
        "title": msg.get("title"),
        "content": msg.get("content"),
        "data": msg.get("payload") or {},
    }
    body = json.dumps(payload, ensure_ascii=False, default=str)
    headers = {
        "Content-Type": "application/json",
        "X-EvalShield-Signature": f"sha256={sign_body(secret, body)}",
    }
    extra = cfg.get("headers")
    if isinstance(extra, dict):
        headers.update({str(k): str(v) for k, v in extra.items()})
    return url, body, headers


def send(config: dict, msg: dict) -> SendResult:
    url, body, headers = build_request(config, msg)
    if not url:
        # 缺 URL 属配置类错误：不可重试，emit 直接记 FAILED
        return SendResult(ok=False, error="webhook 渠道缺少 url 配置", retryable=False)
    # BUG-003（D-16/HAL-08）：httpx.post 前 SSRF 校验，内网/元数据地址拒绝。
    # warning 日志只记渠道级失败事实，不回显目标地址（防泄露内网拓扑）。
    try:
        validate_base_url(url, error_code="ES-TARGET-SSRF")
    except BizError:
        logger.warning("webhook 目标地址被 SSRF 防护拒绝，发送中止")
        return SendResult(
            ok=False, error="webhook 目标地址被 SSRF 防护拒绝（内网/元数据地址不可达）",
            retryable=False,
        )
    try:
        resp = httpx.post(url, content=body.encode("utf-8"), headers=headers, timeout=SEND_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 —— 网络类失败可重试
        return SendResult(ok=False, error=f"webhook 请求失败: {exc.__class__.__name__}: {exc}", retryable=True)
    if 200 <= resp.status_code < 300:
        return SendResult(ok=True)
    return SendResult(
        ok=False, error=f"webhook 响应 {resp.status_code}", retryable=True
    )
