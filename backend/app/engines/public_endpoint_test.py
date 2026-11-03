# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""公开接口参数校验检测引擎（B2 公开接口校验）。

遍历公开端点清单：每个端点发送合法参数与非法参数各一次——
- 非法参数未被拒绝（非 4xx）→ 参数校验缺失（FAIL）
- 非法参数响应回显内部信息（堆栈/SQL/框架报错）→ 信息泄露（FAIL）
真实发请求，绝不仿真。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from ..config import settings
from .base import BaseEngine, EngineContext, EngineResult

logger = logging.getLogger("evalshield.engine.public_endpoint_test")

# 响应中视为内部信息泄露的特征（框架报错/堆栈/SQL）
_LEAK_PATTERNS = [
    re.compile(r"Traceback \(most recent call last\)", re.I),
    re.compile(r"org\.springframework|\.java:\d+", re.I),
    re.compile(r"syntax error at or near|SQLSTATE|sqlite3?\.", re.I),
    re.compile(r"Exception in module|at line \d+ of", re.I),
    re.compile(r"django\.core|flask\._app|werkzeug", re.I),
    re.compile(r'"stack[_-]?trace"\s*:', re.I),
]


class PublicEndpointTestEngine(BaseEngine):
    engine_code = "PUBLIC_ENDPOINT_TEST"
    engine_name = "公开接口参数校验检测引擎"
    engine_type = "TRADITIONAL"
    category = "SECURITY"
    version = "1.0.0"
    description = "遍历公开端点，发送合法/非法参数验证服务端校验与错误信息脱敏。"
    fidelity = "rule"

    params_schema = [
        {"key": "base_url", "label": "被测系统地址", "type": "text", "required": True},
        {"key": "endpoints", "label": "公开端点（JSON：[{method,path,valid_params,invalid_params}]）", "type": "json", "required": True},
        {"key": "timeout_seconds", "label": "超时（秒）", "type": "number", "default": 15},
    ]

    def execute(self, ctx: EngineContext) -> EngineResult:
        base_url = (
            ctx.config.get("base_url")
            or ctx.config.get(f"config__{self.engine_code}__base_url")
            or ctx.extra.get("base_url")
            or settings.API_DEFAULT_BASE_URL
        ).rstrip("/")
        endpoints = self._as_list(ctx.config.get("endpoints"))
        timeout = float(ctx.config.get("timeout_seconds", 15))

        if not endpoints:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0},
                report_payload={"engine": self.engine_code, "results": []},
                error="E_PUBEP_NO_CONFIG: 缺少 endpoints 配置（[{method,path,valid_params,invalid_params}]）",
            )

        results: list[dict[str, Any]] = []
        idx = 0
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            for ep in endpoints:
                method = str(ep.get("method") or "GET").upper()
                path = str(ep.get("path") or "").strip()
                if not path:
                    continue
                url = path if path.startswith("http") else base_url + "/" + path.lstrip("/")
                auth_cfg = ctx.config.get("auth") or {}
                bearer = auth_cfg.get("bearer") or auth_cfg.get("token")
                headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}

                # 1) 合法参数：应可达（非 5xx）
                idx += 1
                valid = ep.get("valid_params") or {}
                r_valid = self._request(client, method, url, valid, headers)
                if isinstance(r_valid, str):  # 连接错误
                    results.append(self._conn_case(idx, method, path, r_valid))
                    continue
                leak_ok = not self._has_leak(r_valid.text)
                results.append({
                    "case_no": f"PE-{idx:03d}", "title": f"{method} {path} 合法参数可达",
                    "owasp_id": "A03", "op_type": "公开端点校验", "method": method, "path": path,
                    "status_code": r_valid.status_code,
                    "result": "PASS" if r_valid.status_code < 500 and leak_ok else "FAIL",
                    "risk_level": "none" if r_valid.status_code < 500 and leak_ok else "medium",
                    "failures": (
                        ([f"E_PUBEP_5XX: 合法请求返回 {r_valid.status_code}，服务端异常"]
                         if r_valid.status_code >= 500 else [])
                        + ([f"E_PUBEP_INFO_LEAK: 响应回显内部报错/堆栈信息"] if not leak_ok else [])
                    ),
                })

                # 2) 非法参数：必须被拒绝（4xx）且不回显内部信息
                idx += 1
                invalid = ep.get("invalid_params")
                if invalid is None:
                    invalid = {"id": "' OR 1=1 --", "page": -99999}
                r_bad = self._request(client, method, url, invalid, headers)
                if isinstance(r_bad, str):
                    results.append(self._conn_case(idx, method, path, r_bad))
                    continue
                rejected = 400 <= r_bad.status_code < 500
                leak = self._has_leak(r_bad.text)
                failures = []
                if not rejected:
                    failures.append(
                        f"E_PUBEP_NO_VALIDATION: 非法参数未被拒绝（{r_bad.status_code}），服务端缺少输入校验")
                if leak:
                    failures.append("E_PUBEP_INFO_LEAK: 错误响应回显堆栈/SQL/框架内部信息")
                risk = "none"
                if failures:
                    risk = "high" if leak else "medium"
                results.append({
                    "case_no": f"PE-{idx:03d}", "title": f"{method} {path} 非法参数被拒绝且不泄露",
                    "owasp_id": "A03", "op_type": "公开端点校验", "method": method, "path": path,
                    "status_code": r_bad.status_code,
                    "result": "FAIL" if failures else "PASS",
                    "risk_level": risk, "failures": failures,
                })

        passed = sum(1 for r in results if r["result"] == "PASS")
        failed = sum(1 for r in results if r["result"] == "FAIL")
        total = len(results)
        ok = failed == 0 and passed > 0
        return EngineResult(
            status="SUCCESS" if ok else "FAILED",
            summary={
                "total": total, "passed": passed, "failed": failed,
                "pass_rate": round(passed / max(total, 1), 4),
                "key": "public_endpoint_pass_rate",
            },
            report_payload={
                "engine": self.engine_code,
                "engine_name": self.engine_name,
                "results": results,
                "conclusion": f"公开端点校验 {passed}/{total} 通过"
                + ("" if ok else f"，{failed} 项校验缺失或信息泄露"),
            },
            error=None if ok else f"{failed} 项公开端点校验异常",
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _request(client: httpx.Client, method: str, url: str, params: dict, headers: dict):
        """GET/HEAD 走 query，其余走 json body；连接失败返回错误文本。"""
        try:
            if method in ("GET", "HEAD", "DELETE"):
                return client.request(method, url, params=params or None, headers=headers or None)
            return client.request(method, url, json=params or {}, headers=headers or None)
        except httpx.HTTPError as exc:
            return f"{exc.__class__.__name__}: {exc}"

    @staticmethod
    def _has_leak(text: str) -> bool:
        return any(p.search(text or "") for p in _LEAK_PATTERNS)

    @staticmethod
    def _conn_case(idx: int, method: str, path: str, err: str) -> dict[str, Any]:
        return {
            "case_no": f"PE-{idx:03d}", "title": f"{method} {path} 请求失败",
            "owasp_id": "A03", "op_type": "公开端点校验", "method": method, "path": path,
            "result": "FAIL", "risk_level": "medium",
            "failures": [f"E_PUBEP_CONN: {err}"],
        }

    @staticmethod
    def _as_list(v: Any) -> list[dict]:
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, str):
            try:
                data = json.loads(v)
                if isinstance(data, list):
                    return [x for x in data if isinstance(x, dict)]
            except (ValueError, TypeError):
                return []
        return []
