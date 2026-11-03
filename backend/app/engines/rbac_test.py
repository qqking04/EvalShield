# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""RBAC 接口鉴权检测引擎（B1 平台级接口鉴权 / 越权探测）。

多角色 Token × 受保护接口矩阵探测：
- 未授权角色访问返回 200 → 越权漏洞（FAIL）
- 授权角色访问返回 401/403 → 鉴权误伤（FAIL）
真实发请求，绝不仿真。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import settings
from .base import BaseEngine, EngineContext, EngineResult, make_http_client

logger = logging.getLogger("evalshield.engine.rbac_test")

_DENY_STATUSES = {401, 403}
_ALLOW_STATUSES = {200, 201, 204, 301, 302}


class RbacTestEngine(BaseEngine):
    engine_code = "RBAC_TEST"
    engine_name = "RBAC 接口鉴权检测引擎"
    engine_type = "TRADITIONAL"
    category = "SECURITY"
    version = "1.0.0"
    description = "多角色 Token 访问受保护接口矩阵，验证越权（未授权放行）与鉴权误伤。"
    fidelity = "rule"

    params_schema = [
        {"key": "base_url", "label": "被测系统地址", "type": "text", "required": True},
        {"key": "roles", "label": "角色 Token（JSON：[{name,bearer}]）", "type": "json", "required": True},
        {"key": "endpoints", "label": "受保护接口（JSON：[{method,path,allow:[角色名]}]）", "type": "json", "required": True},
        {"key": "timeout_seconds", "label": "超时（秒）", "type": "number", "default": 15},
    ]

    def execute(self, ctx: EngineContext) -> EngineResult:
        base_url = (
            ctx.config.get("base_url")
            or ctx.config.get(f"config__{self.engine_code}__base_url")
            or ctx.extra.get("base_url")
            or settings.API_DEFAULT_BASE_URL
        ).rstrip("/")
        roles = self._as_list(ctx.config.get("roles"))
        endpoints = self._as_list(ctx.config.get("endpoints"))
        timeout = float(ctx.config.get("timeout_seconds", 15))

        if not roles or not endpoints:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0},
                report_payload={"engine": self.engine_code, "results": []},
                error="E_RBAC_NO_CONFIG: 缺少 roles（角色 Token）或 endpoints（受保护接口）配置",
            )

        results: list[dict[str, Any]] = []
        idx = 0
        with make_http_client(base_url, timeout=timeout, follow_redirects=False) as client:
            for ep in endpoints:
                method = str(ep.get("method") or "GET").upper()
                path = str(ep.get("path") or "").strip()
                if not path:
                    continue
                allow = {str(r).lower() for r in (ep.get("allow") or [])}
                url = path if path.startswith("http") else base_url + "/" + path.lstrip("/")
                for role in roles:
                    idx += 1
                    role_name = str(role.get("name") or f"role_{idx}")
                    bearer = role.get("bearer") or role.get("token") or ""
                    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
                    case = {
                        "case_no": f"RB-{idx:03d}",
                        "title": f"{role_name} 访问 {method} {path}",
                        "owasp_id": "A01", "op_type": "越权探测",
                        "method": method, "path": path,
                    }
                    try:
                        resp = client.request(method, url, headers=headers or None)
                    except httpx.HTTPError as exc:
                        case.update({
                            "result": "FAIL", "risk_level": "medium",
                            "failures": [f"E_RBAC_CONN: {exc.__class__.__name__}: {exc}"],
                        })
                        results.append(case)
                        continue
                    case["status_code"] = resp.status_code
                    authorized = role_name.lower() in allow or not allow
                    failures: list[str] = []
                    if not authorized and resp.status_code not in _DENY_STATUSES:
                        failures.append(
                            f"E_RBAC_ESCALATION: 角色 {role_name} 未授权却访问成功（{resp.status_code}），存在越权")
                    if authorized and allow and resp.status_code in _DENY_STATUSES:
                        failures.append(
                            f"E_RBAC_OVER_DENY: 角色 {role_name} 已授权却被拒绝（{resp.status_code}），鉴权误伤")
                    case["result"] = "FAIL" if failures else "PASS"
                    case["risk_level"] = (
                        "none" if not failures
                        else ("high" if any("ESCALATION" in f for f in failures) else "medium")
                    )
                    case["failures"] = failures
                    results.append(case)

        passed = sum(1 for r in results if r["result"] == "PASS")
        failed = sum(1 for r in results if r["result"] == "FAIL")
        total = len(results)
        ok = failed == 0 and passed > 0
        return EngineResult(
            status="SUCCESS" if ok else "FAILED",
            summary={
                "total": total, "passed": passed, "failed": failed,
                "pass_rate": round(passed / max(total, 1), 4),
                "key": "rbac_pass_rate",
            },
            report_payload={
                "engine": self.engine_code,
                "engine_name": self.engine_name,
                "results": results,
                "conclusion": f"RBAC 鉴权矩阵 {passed}/{total} 通过"
                + ("" if ok else f"，{failed} 项越权/误伤"),
            },
            error=None if ok else f"{failed} 项 RBAC 鉴权异常",
        )

    @staticmethod
    def _as_list(v: Any) -> list[dict]:
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, str):
            import json
            try:
                data = json.loads(v)
                if isinstance(data, list):
                    return [x for x in data if isinstance(x, dict)]
            except (ValueError, TypeError):
                return []
        return []
