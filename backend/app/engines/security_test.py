# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""安全测试引擎（v2.0 §8 全维度）：真实执行 SECURITY 用例。

按 owasp_id/op_type 分派：
- A01 越权：剥离全部鉴权头发请求，断言 401/403；
- A03 注入（SQLi/XSS）：携带注入 payload 发请求，断言拒绝（400/422）或响应不含原始 payload。

复用 API 引擎的断言求值（_json_get/_op_ok），真实发请求、绝不仿真通过。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import httpx

from ..config import settings
from .api_test import _MISSING, _json_get, _op_ok, normalize_op
from .base import BaseEngine, EngineContext, EngineResult

logger = logging.getLogger("evalshield.engine.security_test")

# 越权类：期望被拒绝的状态码
_DENY_STATUSES = {401, 403}
# A05 调试泄露：响应体中的堆栈/调试标记（小写匹配）
_DEBUG_MARKERS = (
    "traceback (most recent call last)", "syntaxerror", "nullpointerexception",
    "at java.", "at com.", "sqlstate", "stack trace", "debug mode",
    "django.core.exception", "psycopg2.", "sqlalchemy.exc",
)
# A05 调试泄露：不应对外暴露的调试响应头
_DEBUG_HEADERS = {"x-debug", "x-powered-by", "server-timing-debug", "x-aspnet-debug"}
# A06 易损/过时组件：Server/X-Powered-By 头版本命中已知高危版本表即判风险。
# 版本表外置于 backend/data/vuln_components.json（可手动更新），文件缺失/损坏时回退内置表。
_VULN_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "vuln_components.json")
_VULN_SERVER_PATTERNS_BUILTIN = (
    ("apache/2.0", "Apache 2.0（2013 停止安全维护）"),
    ("apache/2.2", "Apache 2.2（2017 停止安全维护）"),
    ("nginx/0.", "Nginx 0.x（EOL）"),
    ("nginx/1.1[0-7].", "Nginx 1.10-1.17（EOL）"),
    ("iis/6.", "IIS 6（EOL）"),
    ("iis/7.", "IIS 7（EOL）"),
    ("jetty/6", "Jetty 6（EOL）"),
    ("jetty/7", "Jetty 7（EOL）"),
    ("jetty/8", "Jetty 8（EOL）"),
    ("jetty/9.", "Jetty 9（2022 EOL，建议升级 11/12）"),
    ("tomcat/6", "Tomcat 6（EOL）"),
    ("tomcat/7", "Tomcat 7（EOL）"),
    ("tomcat/8", "Tomcat 8（EOL，含 CVE-2017-12615 等）"),
    ("tomcat/9.0.[0-9][0-9]$", "Tomcat 9.0.0-99（早期版本含多个 CVE）"),
    ("openssl/1.0", "OpenSSL 1.0（EOL）"),
    ("php/5.", "PHP 5（EOL）"),
    ("php/7.[0-4]", "PHP 7.0-7.4（EOL）"),
)


def load_vuln_db(path: str | None = None) -> tuple[tuple, dict]:
    """加载外置组件漏洞版本表。返回 (patterns, meta)；文件缺失/非法时回退内置表。"""
    p = path or _VULN_DB_PATH
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        pats = tuple(
            (str(x["pattern"]), str(x.get("desc") or ""))
            for x in (data.get("patterns") or [])
            if isinstance(x, dict) and x.get("pattern")
        )
        if not pats:
            raise ValueError("patterns 为空")
        return pats, {"updated_at": data.get("updated_at"), "source": data.get("source"), "count": len(pats)}
    except (OSError, ValueError, KeyError):
        return _VULN_SERVER_PATTERNS_BUILTIN, {"updated_at": "builtin", "source": "内置表", "count": len(_VULN_SERVER_PATTERNS_BUILTIN)}


def refresh_vuln_db(path: str | None = None) -> dict:
    """热更新：重新读取外置版本表并替换全局匹配表。返回元信息。"""
    global _VULN_SERVER_PATTERNS
    pats, meta = load_vuln_db(path)
    _VULN_SERVER_PATTERNS = pats
    return meta


_VULN_SERVER_PATTERNS, _VULN_DB_META = load_vuln_db()


class SecurityTestEngine(BaseEngine):
    engine_code = "SECURITY_TEST"
    engine_name = "安全测试引擎"
    engine_type = "TRADITIONAL"
    category = "SECURITY"
    version = "1.0.0"
    description = "真实执行 OWASP 安全用例：越权剥离 Token、注入 payload 覆盖 body，按断言判定。"
    fidelity = "real"

    def _load_cases(self, ctx: EngineContext) -> list:
        cases = ctx.config.get("cases") or ctx.extra.get("cases") or []
        if not cases and ctx.db is not None:
            from ..models import TestCase

            # DISC-05：过滤软删用例
            q = ctx.db.query(TestCase).filter(
                TestCase.project_id == ctx.project_id,
                TestCase.category == "SECURITY",
                TestCase.deleted_at.is_(None),
            )
            ids = ctx.config.get("case_ids") or ctx.extra.get("case_ids")
            if ids:
                q = q.filter(TestCase.id.in_(ids))
            cases = q.all()
        return cases

    def execute(self, ctx: EngineContext) -> EngineResult:
        cases = self._load_cases(ctx)
        if not cases:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1},
                report_payload={"engine": self.engine_code},
                error="无 SECURITY 类用例可执行（请确认项目已入库安全用例）",
            )
        base_url = (
            ctx.config.get("base_url")
            or ctx.extra.get("base_url")
            or settings.API_DEFAULT_BASE_URL
        ).rstrip("/")
        # 全局 auth（注入类用例需要登录态才能触达接口；越权类强制剥离）
        auth_cfg = ctx.config.get("auth") or {}
        auth_headers: dict[str, str] = {}
        bearer = auth_cfg.get("bearer") or auth_cfg.get("token") or auth_cfg.get("access_token")
        if bearer:
            auth_headers["Authorization"] = f"Bearer {bearer}"
        timeout = float(ctx.config.get("timeout_seconds", 15))

        results: list[dict[str, Any]] = []
        with httpx.Client(timeout=timeout) as client:
            for i, case in enumerate(cases, 1):
                results.append(self._run_one(client, base_url, case, auth_headers, i))

        passed = sum(1 for r in results if r["result"] == "PASS")
        failed = sum(1 for r in results if r["result"] == "FAIL")
        skipped = sum(1 for r in results if r["result"] == "SKIP")
        total = len(results)
        ok = failed == 0 and passed > 0
        # 全 SKIP（仅人工评审项）→ SKIPPED，不误报失败也不假通过
        overall = "SUCCESS" if ok else ("SKIPPED" if (failed == 0 and passed == 0 and skipped > 0) else "FAILED")
        return EngineResult(
            status=overall,
            summary={
                "total": total, "passed": passed, "failed": failed, "skipped": skipped,
                "pass_rate": round(passed / max(total - skipped, 1), 4),
                "key": "security_pass_rate",
            },
            report_payload={
                "engine": self.engine_code,
                "engine_name": self.engine_name,
                "results": results,
                "conclusion": (
                    f"安全测试 {passed}/{total} 通过（越权拒绝、注入拦截符合预期）"
                    if ok
                    else f"全部 {skipped} 条为人工评审项（SKIP），需人工/白盒确认"
                    if overall == "SKIPPED"
                    else f"发现 {failed} 条安全用例未达预期（可能被绕过）"
                ),
            },
            error=None if ok or overall == "SKIPPED" else f"{failed} 条安全用例失败",
        )

    # ------------------------------------------------------------------
    def _run_one(
        self, client: httpx.Client, base_url: str, case: Any, auth_headers: dict, idx: int
    ) -> dict[str, Any]:
        def _get(name, default=None):
            v = getattr(case, name, None)
            if v is None and isinstance(case, dict):
                v = case.get(name, default)
            return v if v is not None else default

        title = _get("title", f"安全用例{idx}")
        case_no = _get("case_no", f"SEC-{idx:04d}")
        owasp = str(_get("owasp_id") or "")
        op_type = str(_get("op_type") or "")
        # 人工评审项（A04/A08/A09/A10）：黑盒不可自动判定，如实 SKIP 不造假，
        # 由 review_status（PENDING/IN_REVIEW/DONE）闭环跟踪
        if op_type == "人工评审" or owasp[:3] in ("A04", "A08", "A09", "A10"):
            return {"case_no": case_no, "case_id": _get("id"), "title": title,
                    "owasp_id": owasp, "op_type": op_type,
                    "result": "SKIP", "review_status": _get("review_status") or "PENDING",
                    "failures": ["人工评审项：需人工/白盒确认，引擎不自动判定"]}
        spec = _get("request_spec") or {}
        assertions = _get("assertions") or []
        method = str(spec.get("method") or "GET").upper()
        path = str(spec.get("path") or "").strip()
        if not path:
            return {"case_no": case_no, "title": title, "result": "FAIL",
                    "failures": ["E_SEC_NO_PATH: 用例缺少 request_spec.path"]}

        url = path if path.startswith("http") else base_url.rstrip("/") + "/" + path.lstrip("/")
        # 越权（A01）与调试泄露探测（A05）均剥离鉴权，验证未授权暴露面
        strip_auth = owasp.startswith("A01") or owasp.startswith("A05") or op_type in ("越权", "调试泄露")
        # 越权拒绝基线（必须 401/403）仅对 A01/越权 生效；A05 由用例断言判定（可含 404）
        enforce_unauth_deny = owasp.startswith("A01") or op_type == "越权"
        # 越权：剥离鉴权；注入：保留鉴权头以触达接口
        headers = {} if strip_auth else dict(auth_headers)
        # 用例自带 headers 合并（越权用例的 request_spec.headers 应为空）
        for k, v in (spec.get("headers") or {}).items():
            if strip_auth and k.lower() in ("authorization", "cookie"):
                continue  # 强制剥离
            headers[k] = v
        body = spec.get("body") or spec.get("json")
        # A07 暴力锁定：按 repeat 连续发同一请求，以末次响应判定是否触发锁定/限流
        repeat = max(1, int(spec.get("repeat") or 1))

        start = time.perf_counter()
        resp = None
        try:
            for _ in range(repeat):
                resp = client.request(method, url, headers=headers or None, json=body)
        except httpx.HTTPError as exc:
            return {"case_no": case_no, "title": title, "result": "FAIL",
                    "failures": [f"E_SEC_CONN: {exc.__class__.__name__}: {exc}"]}
        duration_ms = int((time.perf_counter() - start) * 1000)

        try:
            resp_json = resp.json()
        except ValueError:
            resp_json = None

        failures: list[str] = []
        # 1) 越权基线判定：必须被拒绝（401/403），被放行即漏洞
        if enforce_unauth_deny and resp.status_code not in _DENY_STATUSES:
            failures.append(
                f"E_SEC_UNAUTH_PASSED: 无 Token 请求被放行（{resp.status_code}），存在越权风险"
            )
        # 2) 注入基线判定：payload 原样出现在响应体 = 未转义/未拦截
        payload = ""
        if isinstance(body, dict):
            payload = str(next(iter(body.values()), ""))
        if not strip_auth and payload and payload in resp.text:
            failures.append("E_SEC_INJECTION_ECHO: 注入 payload 原样回显，疑似未过滤")
        # 3) A05 调试泄露判定：响应体/头含堆栈、调试标记即判泄露
        if owasp.startswith("A05") or op_type == "调试泄露":
            low_text = resp.text.lower()
            leak = next((m for m in _DEBUG_MARKERS if m in low_text), "")
            if leak:
                failures.append(f"E_SEC_DEBUG_LEAK: 响应含调试/堆栈标记 {leak!r}")
            dbg_hdr = next((k for k in resp.headers if k.lower() in _DEBUG_HEADERS), "")
            if dbg_hdr:
                failures.append(f"E_SEC_DEBUG_LEAK: 响应含调试头 {dbg_hdr!r}")

        # 3.1) A06 易损/过时组件判定：Server/X-Powered-By 头版本命中高危表即判风险
        if owasp.startswith("A06") or op_type == "组件漏洞":
            comp_hdr = (resp.headers.get("Server") or "") + " " + (resp.headers.get("X-Powered-By") or "")
            comp_hdr = comp_hdr.strip().lower()
            if comp_hdr:
                hit = next(
                    (desc for pat, desc in _VULN_SERVER_PATTERNS
                     if re.search(pat, comp_hdr)),
                    "")
                if hit:
                    failures.append(f"E_SEC_VULN_COMPONENT: 组件头 {comp_hdr!r} 命中已知高危版本（{hit}）")
                if "x-powered-by" in comp_hdr:
                    failures.append(f"E_SEC_COMPONENT_DISCLOSE: 响应头暴露技术栈 {comp_hdr[:80]!r}")

        # 4) 用例断言逐条求值（status/body）
        for a in assertions:
            if not isinstance(a, dict):
                continue
            ap = str(a.get("path") or "")
            op = normalize_op(str(a.get("op") or "eq"))
            expected = a.get("expected")
            if ap == "status":
                actual: Any = resp.status_code
            elif ap in ("body", "text"):
                actual = resp.text
            else:
                actual = _json_get(resp_json if resp_json is not None else {}, ap)
                if actual is _MISSING and ap:
                    failures.append(f"E_SEC_ASSERT: 响应缺少字段 {ap}")
                    continue
            if not _op_ok(op, actual, expected):
                failures.append(f"E_SEC_ASSERT: {ap} {op} {expected!r} 不满足（实际 {str(actual)[:120]!r}）")

        result = "FAIL" if failures else "PASS"
        return {
            "case_no": case_no, "case_id": _get("id"), "title": title,
            "owasp_id": owasp, "op_type": op_type, "attack_type": _get("attack_type", ""),
            "method": method, "path": path,
            "status_code": resp.status_code, "duration_ms": duration_ms,
            "auth_stripped": strip_auth,
            "result": result, "failures": failures,
        }
