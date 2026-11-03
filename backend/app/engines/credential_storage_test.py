# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""凭证存储方式检测引擎（B3）。

Playwright 浏览器自动化：登录目标站点 → 读取 localStorage / sessionStorage / Cookie，
检测 Token/密码等敏感凭证是否以非 HttpOnly 前端存储方式暴露（XSS 可窃取）。
未安装 playwright 或浏览器启动失败时如实返回 FAILED，不仿真。
"""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseEngine, EngineContext, EngineResult

logger = logging.getLogger("evalshield.engine.credential_storage_test")

# 敏感键名关键字
_SENSITIVE_KEYS = ("token", "password", "passwd", "secret", "auth", "jwt", "session")


class CredentialStorageTestEngine(BaseEngine):
    engine_code = "CREDENTIAL_STORAGE_TEST"
    engine_name = "凭证存储方式检测引擎"
    engine_type = "TRADITIONAL"
    category = "SECURITY"
    version = "1.0.0"
    description = "浏览器自动化登录后检查 localStorage/sessionStorage/Cookie 中的敏感凭证存储方式。"
    fidelity = "real"

    params_schema = [
        {"key": "login_url", "label": "登录页地址", "type": "text", "required": True},
        {"key": "username", "label": "测试账号", "type": "text", "required": True},
        {"key": "password", "label": "测试密码", "type": "password", "required": True},
        {"key": "username_selector", "label": "用户名输入框选择器", "type": "text", "default": "input[name='username']"},
        {"key": "password_selector", "label": "密码输入框选择器", "type": "text", "default": "input[name='password']"},
        {"key": "submit_selector", "label": "登录按钮选择器", "type": "text", "default": "button[type='submit']"},
        {"key": "timeout_seconds", "label": "超时（秒）", "type": "number", "default": 30},
    ]

    def execute(self, ctx: EngineContext) -> EngineResult:
        cfg = ctx.config
        login_url = cfg.get("login_url") or cfg.get(f"config__{self.engine_code}__login_url") or ""
        username = cfg.get("username") or ""
        password = cfg.get("password") or ""
        if not login_url or not username:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0},
                report_payload={"engine": self.engine_code, "results": []},
                error="E_CRED_NO_CONFIG: 缺少 login_url / username / password 配置",
            )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0},
                report_payload={"engine": self.engine_code, "results": []},
                error=f"未安装 playwright（{exc}），无法执行凭证存储检测",
            )

        timeout_ms = int(float(cfg.get("timeout_seconds", 30)) * 1000)
        results: list[dict[str, Any]] = []
        p = None
        browser = None
        try:
            p = sync_playwright().start()
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_ms)
            # 执行登录
            page.fill(cfg.get("username_selector") or "input[name='username']", username)
            page.fill(cfg.get("password_selector") or "input[name='password']", password)
            page.click(cfg.get("submit_selector") or "button[type='submit']")
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:  # noqa: BLE001
                pass  # 无 networkidle 也继续读取存储

            local = page.evaluate("() => Object.entries(localStorage)") or []
            session = page.evaluate("() => Object.entries(sessionStorage)") or []
            cookies = page.cookies()
        except Exception as exc:  # noqa: BLE001
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0},
                report_payload={"engine": self.engine_code, "results": []},
                error=f"浏览器自动化执行失败: {exc.__class__.__name__}: {exc}",
            )
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
            if p is not None:
                try:
                    p.stop()
                except Exception:  # noqa: BLE001
                    pass

        # 1) localStorage 敏感凭证检测（XSS 可窃取 → FAIL）
        ls_hits = [(k, v) for k, v in local if any(s in str(k).lower() for s in _SENSITIVE_KEYS)]
        results.append(self._storage_case("CS-001", "localStorage", login_url, ls_hits, local,
                                          risk="high",
                                          fail_msg="E_CRED_LOCALSTORAGE: 敏感凭证存储于 localStorage，XSS 可窃取"))
        # 2) sessionStorage 敏感凭证检测
        ss_hits = [(k, v) for k, v in session if any(s in str(k).lower() for s in _SENSITIVE_KEYS)]
        results.append(self._storage_case("CS-002", "sessionStorage", login_url, ss_hits, session,
                                          risk="medium",
                                          fail_msg="E_CRED_SESSIONSTORAGE: 敏感凭证存储于 sessionStorage"))
        # 3) Cookie 安全属性检测：含敏感词但未设 HttpOnly
        ck_sensitive = [c for c in cookies
                        if any(s in str(c.get("name", "")).lower() for s in _SENSITIVE_KEYS)]
        ck_no_httponly = [c for c in ck_sensitive if not c.get("httpOnly")]
        ck_no_secure = [c for c in ck_sensitive if not c.get("secure")]
        results.append({
            "case_no": "CS-003", "title": "Cookie 安全属性（HttpOnly/Secure）",
            "owasp_id": "A02", "op_type": "凭证存储", "method": "BROWSER", "path": login_url,
            "storage": {"cookie_total": len(cookies), "cookie_sensitive": len(ck_sensitive),
                        "cookie_no_httponly": [c.get("name") for c in ck_no_httponly],
                        "cookie_no_secure": [c.get("name") for c in ck_no_secure]},
            "result": "FAIL" if (ck_no_httponly or ck_no_secure) else "PASS",
            "risk_level": "none" if not (ck_no_httponly or ck_no_secure) else (
                "high" if ck_no_httponly else "medium"),
            "failures": (
                ([f"E_CRED_COOKIE_NO_HTTPONLY: Cookie {', '.join(str(c.get('name')) for c in ck_no_httponly)} 未设 HttpOnly"]
                 if ck_no_httponly else [])
                + ([f"E_CRED_COOKIE_NO_SECURE: Cookie {', '.join(str(c.get('name')) for c in ck_no_secure)} 未设 Secure"]
                   if ck_no_secure else [])
            ),
        })

        passed = sum(1 for r in results if r["result"] == "PASS")
        failed = sum(1 for r in results if r["result"] == "FAIL")
        total = len(results)
        ok = failed == 0
        return EngineResult(
            status="SUCCESS" if ok else "FAILED",
            summary={
                "total": total, "passed": passed, "failed": failed,
                "pass_rate": round(passed / max(total, 1), 4),
                "key": "credential_storage_pass_rate",
            },
            report_payload={
                "engine": self.engine_code,
                "engine_name": self.engine_name,
                "results": results,
                "conclusion": f"凭证存储检测 {passed}/{total} 通过"
                + ("" if ok else f"，{failed} 项存储方式不安全"),
            },
            error=None if ok else f"{failed} 项凭证存储风险",
        )

    @staticmethod
    def _storage_case(no: str, store: str, url: str, hits: list, all_items: list,
                      risk: str, fail_msg: str) -> dict[str, Any]:
        return {
            "case_no": no, "title": f"{store} 敏感凭证检测",
            "owasp_id": "A02", "op_type": "凭证存储", "method": "BROWSER", "path": url,
            "storage": {"store": store, "total": len(all_items),
                        "sensitive_keys": [k for k, _ in hits]},
            "result": "FAIL" if hits else "PASS",
            "risk_level": risk if hits else "none",
            "failures": [fail_msg] if hits else [],
        }
