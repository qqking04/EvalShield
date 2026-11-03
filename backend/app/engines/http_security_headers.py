# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""HTTP 安全头检测引擎（A1 响应头安全策略）。

GET 目标地址 → 检查响应头是否包含安全策略（HSTS/CSP/X-Frame-Options 等）。
缺失即 FAIL，按头自带 risk_level 定级；不仿真、真实发请求。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import settings
from .base import BaseEngine, EngineContext, EngineResult, make_http_client

logger = logging.getLogger("evalshield.engine.http_security_headers")

# 必需安全头清单：缺失时的风险等级与建议值
REQUIRED_HEADERS: list[dict[str, Any]] = [
    {"header": "Strict-Transport-Security", "owasp_id": "A02",
     "description": "HSTS（HTTP 严格传输安全）", "recommended": "max-age=31536000; includeSubDomains",
     "risk_level": "high"},
    {"header": "Content-Security-Policy", "owasp_id": "A03",
     "description": "CSP（内容安全策略）", "recommended": "default-src 'self'",
     "risk_level": "high"},
    {"header": "X-Frame-Options", "owasp_id": "A03",
     "description": "防止点击劫持", "recommended": "DENY 或 SAMEORIGIN",
     "risk_level": "medium"},
    {"header": "X-Content-Type-Options", "owasp_id": "A05",
     "description": "防止 MIME 类型嗅探", "recommended": "nosniff",
     "risk_level": "medium"},
    {"header": "Referrer-Policy", "owasp_id": "A05",
     "description": "控制 Referrer 信息泄露", "recommended": "strict-origin-when-cross-origin",
     "risk_level": "low"},
]


class HttpSecurityHeadersEngine(BaseEngine):
    engine_code = "HTTP_SECURITY_HEADERS"
    engine_name = "HTTP 安全头检测引擎"
    engine_type = "TRADITIONAL"
    category = "SECURITY"
    version = "1.0.0"
    description = "检查 HTTP 响应头是否包含安全策略（CSP、HSTS、X-Frame-Options、X-Content-Type-Options、Referrer-Policy）。"
    fidelity = "rule"

    params_schema = [
        {"key": "base_url", "label": "被测系统地址", "type": "text", "required": True},
        {"key": "timeout_seconds", "label": "超时（秒）", "type": "number", "default": 15},
    ]

    def execute(self, ctx: EngineContext) -> EngineResult:
        base_url = (
            ctx.config.get("base_url")
            or ctx.config.get(f"config__{self.engine_code}__base_url")
            or ctx.extra.get("base_url")
            or settings.API_DEFAULT_BASE_URL
        ).rstrip("/")
        auth_cfg = ctx.config.get("auth") or {}
        if not auth_cfg:
            # 环境解析钩子把 TestEnvironment.auth 注入为 config__<ENGINE>__auth
            auth_cfg = ctx.config.get(f"config__{self.engine_code}__auth") or {}
        timeout = float(ctx.config.get("timeout_seconds", 15))
        headers = {}
        bearer = auth_cfg.get("bearer") or auth_cfg.get("token") or auth_cfg.get("access_token")
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"

        results: list[dict[str, Any]] = []
        try:
            with make_http_client(base_url, timeout=timeout, follow_redirects=True) as client:
                resp = client.get(base_url, headers=headers or None)
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                for spec in REQUIRED_HEADERS:
                    present = spec["header"].lower() in resp_headers
                    results.append({
                        "case_no": f"HS-{len(results) + 1:03d}",
                        "title": f"{spec['header']}（{spec['description']}）",
                        "header": spec["header"],
                        "description": spec["description"],
                        "owasp_id": spec["owasp_id"],
                        "op_type": "响应头检测",
                        "method": "GET",
                        "path": base_url,
                        "status_code": resp.status_code,
                        "present": present,
                        "value": resp_headers.get(spec["header"].lower(), ""),
                        "recommended": spec["recommended"],
                        "risk_level": "none" if present else spec["risk_level"],
                        "result": "PASS" if present else "FAIL",
                        "failures": [] if present else [
                            f"E_SEC_HEADER_MISSING: 响应缺少 {spec['header']}，建议值 {spec['recommended']}"
                        ],
                    })
        except httpx.HTTPError as exc:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0},
                report_payload={"engine": self.engine_code, "results": []},
                error=f"HTTP 请求失败: {exc.__class__.__name__}: {exc}",
            )

        passed = sum(1 for r in results if r["result"] == "PASS")
        failed = sum(1 for r in results if r["result"] == "FAIL")
        total = len(results)
        ok = failed == 0
        return EngineResult(
            status="SUCCESS" if ok else "FAILED",
            summary={
                "total": total, "passed": passed, "failed": failed,
                "pass_rate": round(passed / max(total, 1), 4),
                "key": "security_headers_pass_rate",
            },
            report_payload={
                "engine": self.engine_code,
                "engine_name": self.engine_name,
                "results": results,
                "conclusion": f"HTTP 安全头检测 {passed}/{total} 通过"
                + ("" if ok else f"，{failed} 项安全头缺失"),
            },
            error=None if ok else f"{failed} 项安全响应头缺失",
        )
