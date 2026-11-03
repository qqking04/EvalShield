# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""前端硬编码密钥扫描引擎（A3 JS 包静态分析）。

下载目标站点 HTML 中引用的 JS 资源 → 正则匹配密钥模式（api_key/token/password/private_key 等）。
命中即 FAIL；限制资源数量与体积，避免拖垮目标站。
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

import httpx

from ..config import settings
from .base import BaseEngine, EngineContext, EngineResult, make_http_client

logger = logging.getLogger("evalshield.engine.static_secret_scan")

# 密钥模式（名称 → 正则）。要求值长度 >= 8 降低误报。
SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("API Key", re.compile(r"""api[_-]?key["']?\s*[:=]\s*["']([A-Za-z0-9_\-\.]{8,})["']""", re.I)),
    ("Access Token", re.compile(r"""(?:access[_-]?token|auth[_-]?token)["']?\s*[:=]\s*["']([A-Za-z0-9_\-\.=]{8,})["']""", re.I)),
    ("Secret", re.compile(r"""(?:app[_-]?secret|client[_-]?secret|secret[_-]?key)["']?\s*[:=]\s*["']([A-Za-z0-9_\-\.=]{8,})["']""", re.I)),
    ("Password", re.compile(r"""(?:password|passwd|pwd)["']?\s*[:=]\s*["']([^"']{6,})["']""", re.I)),
    ("Private Key", re.compile(r"""-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----""", re.I)),
    ("AWS Key", re.compile(r"""AKIA[0-9A-Z]{16}""")),
]

_MAX_ASSETS = 20          # 最多扫描的 JS 资源数
_MAX_ASSET_BYTES = 2 * 1024 * 1024  # 单资源 2MB 上限
# 明显非密钥的占位值（误报过滤）
_PLACEHOLDER_VALUES = {"your_api_key", "yourapikey", "xxxxxxxx", "placeholder", "example", "changeme"}


class StaticSecretScanEngine(BaseEngine):
    engine_code = "STATIC_SECRET_SCAN"
    engine_name = "前端硬编码密钥扫描引擎"
    engine_type = "TRADITIONAL"
    category = "SECURITY"
    version = "1.0.0"
    description = "下载目标站点 JS 资源，正则匹配硬编码 API Key/Token/Password/Private Key。"
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
        timeout = float(ctx.config.get("timeout_seconds", 15))

        results: list[dict[str, Any]] = []
        try:
            with make_http_client(base_url, timeout=timeout, follow_redirects=True) as client:
                html = self._fetch_html(client, base_url)
                if html is None:
                    return EngineResult(
                        status="FAILED",
                        summary={"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0},
                        report_payload={"engine": self.engine_code, "results": []},
                        error="E_SCAN_NO_HTML: 目标地址不可达或无 HTML 响应",
                    )
                js_urls = self._extract_js_urls(html, base_url)
                if not js_urls:
                    return EngineResult(
                        status="SUCCESS",
                        summary={"total": 1, "passed": 1, "failed": 0, "pass_rate": 1.0},
                        report_payload={
                            "engine": self.engine_code, "engine_name": self.engine_name,
                            "results": [{
                                "case_no": "SS-000", "title": "页面未引用外部 JS 资源",
                                "owasp_id": "A02", "op_type": "静态扫描",
                                "method": "GET", "path": base_url,
                                "result": "PASS", "risk_level": "none", "failures": [],
                            }],
                            "conclusion": "未发现可扫描的 JS 资源",
                        },
                    )
                for idx, js_url in enumerate(js_urls, 1):
                    findings = self._scan_asset(client, js_url, timeout)
                    if findings is None:  # 下载失败，如实记录但不判漏洞
                        results.append({
                            "case_no": f"SS-{idx:03d}", "title": f"资源下载失败 {js_url}",
                            "owasp_id": "A02", "op_type": "静态扫描",
                            "method": "GET", "path": js_url, "file": js_url,
                            "result": "SKIP", "risk_level": "none",
                            "failures": ["资源下载失败或超出体积上限，跳过"],
                        })
                        continue
                    if not findings:
                        results.append({
                            "case_no": f"SS-{idx:03d}", "title": f"无硬编码密钥 {js_url}",
                            "owasp_id": "A02", "op_type": "静态扫描",
                            "method": "GET", "path": js_url, "file": js_url,
                            "result": "PASS", "risk_level": "none", "failures": [],
                        })
                    else:
                        for kind, sample in findings:
                            results.append({
                                "case_no": f"SS-{idx:03d}", "title": f"硬编码 {kind}：{js_url}",
                                "owasp_id": "A02", "op_type": "静态扫描",
                                "method": "GET", "path": js_url, "file": js_url,
                                "matches": [self._mask(s) for s in sample[:3]],
                                "result": "FAIL", "risk_level": "high",
                                "failures": [f"E_SECRET_HARDCODED: JS 资源中发现硬编码 {kind}（样例已脱敏）"],
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
                "key": "secret_scan_pass_rate",
            },
            report_payload={
                "engine": self.engine_code,
                "engine_name": self.engine_name,
                "results": results,
                "conclusion": f"静态密钥扫描 {passed}/{total} 通过"
                + ("" if ok else f"，发现 {failed} 处硬编码密钥"),
            },
            error=None if ok else f"{failed} 处硬编码密钥",
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _fetch_html(client: httpx.Client, base_url: str) -> str | None:
        try:
            resp = client.get(base_url)
            ctype = resp.headers.get("content-type", "")
            if "html" not in ctype and "<html" not in resp.text.lower()[:500]:
                return None
            return resp.text
        except httpx.HTTPError:
            return None

    @staticmethod
    def _extract_js_urls(html: str, base_url: str) -> list[str]:
        urls = []
        for m in re.finditer(r"""<script[^>]+src=["']([^"']+)["']""", html, re.I):
            src = m.group(1)
            if src.startswith("data:") or src.startswith("blob:"):
                continue
            urls.append(urljoin(base_url + "/", src))
        # 去重限量
        seen: set[str] = set()
        uniq = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                uniq.append(u)
        return uniq[:_MAX_ASSETS]

    @staticmethod
    def _scan_asset(client: httpx.Client, js_url: str, timeout: float) -> list[tuple[str, list[str]]] | None:
        """返回命中的 (类型, 样例值) 列表；下载失败返回 None。"""
        try:
            resp = client.get(js_url)
            if resp.status_code != 200 or len(resp.content) > _MAX_ASSET_BYTES:
                return None
            content = resp.text
        except (httpx.HTTPError, UnicodeDecodeError):
            return None
        findings: list[tuple[str, list[str]]] = []
        for kind, pattern in SECRET_PATTERNS:
            matches = pattern.findall(content)
            real = [v for v in matches if v and v.lower().strip("\"'") not in _PLACEHOLDER_VALUES]
            if real:
                findings.append((kind, real))
        return findings

    @staticmethod
    def _mask(value: str) -> str:
        """样例脱敏：只保留前 4 位。"""
        v = str(value)
        if len(v) <= 4:
            return "****"
        return v[:4] + "*" * min(len(v) - 4, 12)
