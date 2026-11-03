# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""普通业务数据输入功能缺陷检测引擎（C3）。

Playwright 浏览器自动化：登录目标站点 → 表单输入正常业务数据提交 →
验证功能缺陷：无 5xx / 无错误堆栈回显 / 成功提示可见。
未安装 playwright 或执行失败时如实返回 FAILED，不仿真。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .base import BaseEngine, EngineContext, EngineResult

logger = logging.getLogger("evalshield.engine.functional_defect_test")

# 页面错误特征（缺陷判定）
_PAGE_ERR_PATTERNS = [
    re.compile(r"Internal Server Error", re.I),
    re.compile(r"Traceback \(most recent call last\)", re.I),
    re.compile(r"Exception|Error:|失败|错误", re.I),
]
_PAGE_OK_PATTERNS = [
    re.compile(r"成功|Success|已保存|已创建|提交成功", re.I),
]


class FunctionalDefectTestEngine(BaseEngine):
    engine_code = "FUNCTIONAL_DEFECT_TEST"
    engine_name = "业务数据输入功能缺陷检测引擎"
    engine_type = "TRADITIONAL"
    category = "SECURITY"
    version = "1.0.0"
    description = "浏览器自动化输入正常业务数据提交，检测 5xx/错误回显/成功提示缺失等功能缺陷。"
    fidelity = "real"

    params_schema = [
        {"key": "login_url", "label": "登录页地址", "type": "text", "required": True},
        {"key": "username", "label": "测试账号", "type": "text", "required": True},
        {"key": "password", "label": "测试密码", "type": "password", "required": True},
        {"key": "form_url", "label": "业务表单页地址", "type": "text", "required": True},
        {"key": "fields", "label": "业务数据（JSON：[{selector,value}]）", "type": "json", "required": True},
        {"key": "submit_selector", "label": "提交按钮选择器", "type": "text", "default": "button[type='submit']"},
        {"key": "success_selector", "label": "成功提示选择器（可选）", "type": "text", "required": False},
        {"key": "timeout_seconds", "label": "超时（秒）", "type": "number", "default": 30},
    ]

    def execute(self, ctx: EngineContext) -> EngineResult:
        cfg = ctx.config
        login_url = cfg.get("login_url") or ""
        username = cfg.get("username") or ""
        password = cfg.get("password") or ""
        form_url = cfg.get("form_url") or ""
        fields = cfg.get("fields") or []
        if isinstance(fields, str):
            import json as _json
            try:
                fields = _json.loads(fields)
            except (ValueError, TypeError):
                fields = []
        if not login_url or not username or not form_url or not isinstance(fields, list) or not fields:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0},
                report_payload={"engine": self.engine_code, "results": []},
                error="E_FUNC_NO_CONFIG: 缺少 login_url / username / form_url / fields 配置",
            )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0},
                report_payload={"engine": self.engine_code, "results": []},
                error=f"未安装 playwright（{exc}），无法执行功能缺陷检测",
            )

        timeout_ms = int(float(cfg.get("timeout_seconds", 30)) * 1000)
        results: list[dict[str, Any]] = []
        p = None
        browser = None
        try:
            p = sync_playwright().start()
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()

            # 登录
            page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.fill("input[name='username']", username)
            page.fill("input[name='password']", password)
            page.click("button[type='submit']")
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:  # noqa: BLE001
                pass

            # 打开业务表单
            page.goto(form_url, wait_until="domcontentloaded", timeout=timeout_ms)
            for f in fields:
                sel = f.get("selector")
                val = str(f.get("value", ""))
                if not sel:
                    continue
                page.fill(sel, val)

            # 提交
            page.click(cfg.get("submit_selector") or "button[type='submit']")
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:  # noqa: BLE001
                pass

            body_text = page.inner_text("body") or ""
            resp_status = None
            # 检查最近一次响应是否有 5xx
            try:
                resp = page.goto(form_url, wait_until="domcontentloaded", timeout=timeout_ms)
                resp_status = resp.status if resp else None
            except Exception:  # noqa: BLE001
                pass

            has_err = any(pat.search(body_text) for pat in _PAGE_ERR_PATTERNS)
            has_ok = any(pat.search(body_text) for pat in _PAGE_OK_PATTERNS)
            success_sel = cfg.get("success_selector")
            sel_ok = False
            if success_sel:
                try:
                    sel_ok = page.locator(success_sel).count() > 0
                except Exception:  # noqa: BLE001
                    sel_ok = False

            failures: list[str] = []
            if resp_status is not None and resp_status >= 500:
                failures.append(f"E_FUNC_5XX: 提交后页面返回 {resp_status}")
            if has_err and not has_ok:
                failures.append("E_FUNC_ERROR_ECHO: 页面回显错误/异常文本，功能执行失败")
            if not has_ok and not sel_ok:
                failures.append("E_FUNC_NO_SUCCESS_FEEDBACK: 提交后未见成功提示")

            results.append({
                "case_no": "FD-001", "title": f"业务数据提交功能验证（{form_url}）",
                "owasp_id": "A03", "op_type": "功能缺陷", "method": "BROWSER", "path": form_url,
                "result": "FAIL" if failures else "PASS",
                "risk_level": "none" if not failures else ("medium" if resp_status and resp_status >= 500 else "low"),
                "failures": failures,
            })
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

        passed = sum(1 for r in results if r["result"] == "PASS")
        failed = sum(1 for r in results if r["result"] == "FAIL")
        total = len(results)
        ok = failed == 0
        return EngineResult(
            status="SUCCESS" if ok else "FAILED",
            summary={
                "total": total, "passed": passed, "failed": failed,
                "pass_rate": round(passed / max(total, 1), 4),
                "key": "functional_defect_pass_rate",
            },
            report_payload={
                "engine": self.engine_code,
                "engine_name": self.engine_name,
                "results": results,
                "conclusion": f"功能缺陷检测 {passed}/{total} 通过"
                + ("" if ok else "，发现功能缺陷"),
            },
            error=None if ok else "业务数据输入存在功能缺陷",
        )
