# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
# backend/app/services/gateway_errors.py
"""网关统一错误码与异常类型。"""

from __future__ import annotations


class GatewayErrorCode:
    RATE_LIMITED = "ES-GW-0001"
    TIMEOUT = "ES-GW-0002"
    AUTH = "ES-GW-0003"
    UPSTREAM = "ES-GW-0004"
    PARSE = "ES-GW-0005"
    BUDGET = "ES-GW-0006"
    PARAM = "ES-GW-0007"

    ALL = {
        RATE_LIMITED: "限流（令牌桶不足/并发超限/租户级 QPS 超限）",
        TIMEOUT: "上游超时",
        AUTH: "鉴权失败",
        UPSTREAM: "上游非 2xx 响应",
        PARSE: "响应解析失败",
        BUDGET: "token 预算超支",
        PARAM: "参数错误",
    }

    RETRYABLE = {RATE_LIMITED, TIMEOUT}


class GatewayError(Exception):
    """网关统一异常。携带 error_code 与 retry_after_sec（限流/预算场景）。"""

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        retryable: bool = False,
        retry_after_sec: int = 0,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.retryable = retryable
        self.retry_after_sec = retry_after_sec

    def to_http(self) -> dict[str, object]:
        """映射为 FastAPI 响应体（兼容 app/errors.py 的错误响应结构）。"""
        status_map = {
            GatewayErrorCode.RATE_LIMITED: 429,
            GatewayErrorCode.TIMEOUT: 504,
            GatewayErrorCode.AUTH: 401,
            GatewayErrorCode.UPSTREAM: 502,
            GatewayErrorCode.PARSE: 502,
            GatewayErrorCode.BUDGET: 429,
            GatewayErrorCode.PARAM: 400,
        }
        return {
            "status_code": status_map.get(self.error_code, 502),
            "body": {"code": self.error_code, "message": self.message},
        }
