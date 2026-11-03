# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""UI 自动化测试引擎：基于 Playwright 真实浏览器执行 UI 用例（打开/点击/输入/断言，截图证据）。

在单个 execute() 调用内启动/使用/释放 sync_playwright，保证同一线程内完成，线程安全。
缺 playwright 或浏览器时返回清晰失败，绝不打印仿真通过。
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import urllib.parse
from typing import Any

from ..config import settings
from .base import BaseEngine, EngineContext, EngineResult, resolve_dataset_groups

logger = logging.getLogger("evalshield.engine.ui")

# 浏览器路径兜底（引擎可能被独立进程/自测脚本直接 import）
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", settings.PLAYWRIGHT_BROWSERS_PATH)

# 支持的动作列表（用于未知 action 报错）
_SUPPORTED_ACTIONS = {
    "goto",
    "click",
    "fill",
    "wait",
    "press",
    "screenshot",
    "assert_text",
    "assert_visible",
}


_VAR_PLACEHOLDER = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_\-]*\s*\}\}")


def _find_undefined(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    found: list[str] = []
    for m in _VAR_PLACEHOLDER.finditer(text):
        name = m.group(0).strip("{}").strip()
        if name and name not in found:
            found.append(name)
    return found


def _inject_vars_value(value: str, variables: dict) -> str:
    if not variables:
        return str(value) if value is not None else ""
    out = str(value) if value is not None else ""
    for k, v in variables.items():
        out = out.replace("{{" + k + "}}", "" if v is None else str(v))
    return out


def _run_steps(page, steps: list[dict[str, Any]], base_url: str, variables: dict | None = None) -> tuple[bool, list[str], str, dict]:
    """在给定 page 上执行步骤序列，返回 (passed, failures, screenshot_path, variables)。"""
    failures: list[str] = []
    screenshot_path: str = ""
    variables = dict(variables or {})
    for i, step in enumerate(steps or [], 1):
        if not isinstance(step, dict):
            failures.append(f"步骤{i} 格式非法")
            break
        act = (step.get("action") or "").strip().lower()
        target = _inject_vars_value(step.get("target") or "", variables)
        value = _inject_vars_value(step.get("value") or step.get("expected") or "", variables)
        for u in _find_undefined(target) + _find_undefined(value):
            failures.append(f"E_VAR_UNDEFINED: 变量 {u!r} 未定义")
        try:
            if act == "goto":
                # goto 的 URL 优先取 target 字段（前端录制步骤格式），value 作为兜底兼容
                raw_url = target or value
                if raw_url.startswith("http"):
                    url = raw_url
                else:
                    url = base_url.rstrip("/") + "/" + raw_url.lstrip("/")
                page.goto(url, wait_until="load", timeout=int(step.get("timeout", 15000)))
            elif act == "click":
                page.click(target, timeout=int(step.get("timeout", 10000)))
            elif act == "fill":
                page.fill(target, value)
            elif act == "press":
                page.keyboard.press(target)
            elif act == "wait":
                ms = int(step.get("value", step.get("timeout", 500)))
                page.wait_for_timeout(max(ms, 0))
            elif act == "screenshot":
                screenshot_path = _take_screenshot(page, step.get("name", "shot"))
            elif act == "assert_text":
                page.locator(target).nth(0).wait_for(timeout=int(step.get("timeout", 10000)))
                texts = page.locator(target).all_inner_texts()
                if value not in " ".join(texts):
                    failures.append(f"E_UI_ASSERT_TEXT: 期望含 {value!r}，实际 {texts}")
            elif act == "assert_visible":
                loc = page.locator(target).nth(0)
                loc.wait_for(timeout=int(step.get("timeout", 10000)))
                if not loc.is_visible():
                    failures.append(f"E_UI_ASSERT_VISIBLE: 元素不可见 {target}")
            else:
                failures.append(f"E_UI_ACTION: 不支持的动作 {act!r}（支持 {sorted(_SUPPORTED_ACTIONS)}）")
                break

            # 步骤内断言块
            for a in step.get("assertions") or []:
                if not isinstance(a, dict):
                    continue
                a_val = _inject_vars_value(a.get("expected") or "", variables)
                texts = page.locator(target).all_inner_texts()
                joined = " ".join(texts)
                if a.get("op") in ("contains", "eq") or not a.get("op"):
                    ok = a_val in joined
                elif a.get("op") == "not_contains":
                    ok = a_val not in joined
                elif a.get("op") == "notNull":
                    ok = bool(texts)
                else:
                    ok = False
                if not ok:
                    failures.append(f"E_UI_ASSERT[{i}]: {target} {a.get('op')} {a_val!r} 失败，实际={joined[:120]}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"E_UI_STEP{i}: {act} 失败: {exc.__class__.__name__}: {exc}")
            break
        if failures:
            break
    return not failures, failures, screenshot_path, variables


def _take_screenshot(page, name: str) -> str:
    try:
        # F-01：文件名附加随机后缀，防止按步骤名枚举/猜测他人截图路径
        safe = re.sub(r"[^\w\u4e00-\u9fff-]", "_", str(name))[:60]
        path = os.path.join(settings.EVIDENCE_DIR, f"ui_{safe}_{secrets.token_hex(6)}.png")
        page.screenshot(path=path, full_page=True)
        return path
    except Exception as exc:  # noqa: BLE001
        logger.warning("截图失败: %s", exc)
        return ""


def _prepare_context(browser, auth: dict, base_url: str):
    """在给定 browser 上建立带鉴权的 context，并执行前置登录步骤。

    返回 (context, pre_login_errors)。多浏览器场景下每种内核各调一次，
    复用同一份 auth 配置（cookie/Bearer/自动登录），保证跨内核鉴权一致。
    """
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    pre_login_errors: list[str] = []

    # 1) 预置 cookie（用户直接给 cookie 字符串 / dict）
    preset_cookies = auth.get("cookies") or []
    if preset_cookies:
        try:
            cookie_list: list[dict[str, Any]] = []
            for c in (
                preset_cookies
                if isinstance(preset_cookies, list)
                else [preset_cookies]
            ):
                if isinstance(c, str) and "=" in c:
                    name, _, value = c.partition("=")
                    cookie_list.append(
                        {
                            "name": name.strip(),
                            "value": value.strip(),
                            "domain": (
                                urllib.parse.urlparse(base_url).hostname
                                or "localhost"
                            ),
                            "path": "/",
                        }
                    )
                elif isinstance(c, dict):
                    cookie_list.append(c)
            if cookie_list:
                context.add_cookies(cookie_list)
        except Exception as exc:  # noqa: BLE001
            logger.warning("预置 cookie 注入失败: %s", exc)

    # 2) 预置 Bearer token → 自动在 context 里加 Authorization 头
    bearer = auth.get("bearer") or auth.get("token") or auth.get("access_token")
    if bearer:
        context.set_extra_http_headers({"Authorization": f"Bearer {bearer}"})
    basic_user = auth.get("username") or auth.get("basic_user")
    basic_pass = auth.get("password") or auth.get("basic_pass")
    if basic_user and basic_pass and not bearer:
        import base64 as _b64

        token = _b64.b64encode(f"{basic_user}:{basic_pass}".encode()).decode()
        context.set_extra_http_headers({"Authorization": f"Basic {token}"})

    # 3) pre_login 自动登录步骤（填表单 + 点登录 + 等跳转）
    pre_login_steps = auth.get("pre_login_steps") or []
    if auth.get("login_url") and auth.get("username") and auth.get("password"):
        captcha_mode = auth.get("captcha_mode", "skip")
        auto_steps: list[dict[str, Any]] = [
            {"action": "goto", "target": auth["login_url"]},
            {"action": "fill",
             "target": auth.get("username_selector", "input[name='username'], input[type='text']"),
             "value": auth["username"]},
            {"action": "fill",
             "target": auth.get("password_selector", "input[type='password']"),
             "value": auth["password"]},
        ]
        if captcha_mode == "manual_input":
            auto_steps.append({
                "action": "fill",
                "target": auth.get("captcha_selector", "input[name='captcha']"),
                "value": auth.get("captcha_value", ""),
                "_note": "手动输入验证码后再点登录",
            })
        elif captcha_mode == "selector_only":
            auto_steps.append({
                "action": "wait",
                "value": auth.get("captcha_wait_ms", 500),
                "_note": "请在 pre_login_steps 里自定义滑块/点选步骤",
            })
        auto_steps.append({
            "action": "click",
            "target": auth.get("login_button_selector", "button[type='submit'], button.login"),
        })
        auto_steps.append({"action": "wait", "value": auth.get("post_login_wait", 2000)})
        pre_login_steps = auto_steps

    if pre_login_steps:
        page = None
        try:
            page = context.new_page()
            _passed, pre_fails, _shot = _run_steps(page, pre_login_steps, base_url)
            if pre_fails:
                pre_login_errors = pre_fails
                logger.warning("前置登录步骤有失败: %s", pre_fails)
        except Exception as exc:  # noqa: BLE001
            pre_login_errors = [f"前置登录异常: {exc.__class__.__name__}: {exc}"]
            logger.warning("前置登录抛异常: %s", exc)
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass

    return context, pre_login_errors


class UITestEngine(BaseEngine):
    engine_code = "UI_TEST"
    engine_name = "UI 自动化测试引擎"
    engine_type = "TRADITIONAL"
    category = "UI"
    version = "1.0.0"
    description = "基于 Playwright 真实浏览器执行 UI 用例：打开/点击/输入/断言，截图证据。"
    fidelity = "rule"

    def _load_cases(self, ctx: EngineContext) -> list:
        cases = ctx.config.get("cases") or ctx.extra.get("cases") or []
        if not cases and ctx.db is not None:
            from ..models import TestCase

            # DISC-05：过滤软删用例；case_ids 兼容 config 与 extra 双来源
            q = ctx.db.query(TestCase).filter(
                TestCase.project_id == ctx.project_id,
                TestCase.category == "UI",
                TestCase.deleted_at.is_(None),
            )
            ids = ctx.config.get("case_ids") or ctx.extra.get("case_ids")
            if ids:
                q = q.filter(TestCase.id.in_(ids))
            cases = [c for c in q.order_by(TestCase.id.desc()).all()]
        return cases

    def execute(self, ctx: EngineContext) -> EngineResult:
        cases = self._load_cases(ctx)
        base_url = (
            ctx.config.get("base_url")
            or ctx.extra.get("base_url")
            or settings.UI_DEFAULT_BASE_URL
        )
        # ---- 全局 auth 配置：登录凭据 / 预置 cookie / Bearer ----
        auth_cfg = ctx.config.get("auth") or ctx.config.get("login_credentials") or {}
        # 统一成 auth dict 格式
        auth = auth_cfg if isinstance(auth_cfg, dict) else {}

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 缺依赖
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0},
                report_payload={"engine": self.engine_code},
                error=f"未安装 playwright（{exc}），无法执行真实浏览器 UI 测试",
            )

        results: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        pre_login_errors: list[str] = []
        cleanup_warnings: list[str] = []
        # v2.0 §8.1：按用例 browser_config 分组启动对应内核（chromium/firefox/webkit）。
        # 主浏览器 = 多数用例所需内核（缺省 chromium），用于前置登录与无 browser_config 用例；
        # 次内核按需启动，内核未安装（playwright install 缺失）时该组用例判 SKIP 并标注原因，不造假。
        def _case_browser(c) -> str:
            b = getattr(c, "browser_config", None)
            if b is None and isinstance(c, dict):
                b = c.get("browser_config")
            return (str(b or "").strip().lower() or "chromium")

        browser_by_case = {id(c): _case_browser(c) for c in cases}
        # 主浏览器 = 用例最多所需内核；并列时优先 chromium（最稳定、通常已装）
        primary_browser = "chromium"
        if browser_by_case:
            _counts = {b: sum(1 for v in browser_by_case.values() if v == b) for b in ("chromium", "firefox", "webkit")}
            _best = max(_counts.values())
            for _pref in ("chromium", "firefox", "webkit"):
                if _counts[_pref] == _best and _best > 0:
                    primary_browser = _pref
                    break
        if primary_browser not in ("chromium", "firefox", "webkit"):
            primary_browser = "chromium"
        launch_error: str | None = None
        p = None
        browser = None
        try:
            p = sync_playwright().start()
            browser = getattr(p, primary_browser).launch(headless=True, args=["--no-sandbox"])
        except Exception as exc:  # noqa: BLE001
            launch_error = (
                f"浏览器启动失败: {exc}。请确认已安装对应 {primary_browser}"
                f"（python -m playwright install {primary_browser}），"
                f"且 PLAYWRIGHT_BROWSERS_PATH={settings.PLAYWRIGHT_BROWSERS_PATH}"
            )
        if launch_error is not None:
            if p is not None:
                try:
                    p.stop()
                except Exception:  # noqa: BLE001
                    pass
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0},
                report_payload={"engine": self.engine_code},
                error=launch_error,
            )

        try:
            # ---- 全局 context：所有用例共享 cookie（一次登录，全程保持） ----
            context, pre_login_errors = _prepare_context(browser, auth, base_url)

            # 多浏览器缓存：browser_name -> (browser_obj, context)；主浏览器已建
            browser_cache: dict[str, tuple[Any, Any]] = {primary_browser: (browser, context)}
            launch_failed: dict[str, str] = {}  # browser_name -> 失败原因

            for i, case in enumerate(cases, 1):
                title = (
                    getattr(case, "title", None)
                    or (case.get("title") if isinstance(case, dict) else "")
                    or f"UI 用例{i}"
                )
                steps = (
                    getattr(case, "steps", None)
                    or (case.get("steps") if isinstance(case, dict) else [])
                    or []
                )
                case_no = getattr(case, "case_no", None) or (
                    case.get("case_no") if isinstance(case, dict) else f"UI-{i:04d}"
                )
                case_assertions = (
                    getattr(case, "assertions", None)
                    or (case.get("assertions") if isinstance(case, dict) else [])
                    or []
                )
                # v2.0 兼容性：用例级视口/浏览器（viewport_config 真实生效；browser_config 记录，
                # 引擎当前以 chromium 执行，非 chromium 在结果中标注实际浏览器，不造假）
                viewport_cfg = (
                    getattr(case, "viewport_config", None)
                    or (case.get("viewport_config") if isinstance(case, dict) else None)
                    or None
                )
                browser_cfg = (
                    getattr(case, "browser_config", None)
                    or (case.get("browser_config") if isinstance(case, dict) else None)
                    or ""
                )
                test_data = (
                    getattr(case, "test_data", None)
                    or (case.get("test_data") if isinstance(case, dict) else [])
                    or []
                )
                if not steps:
                    # 无步骤：有断言也不能执行，计入 FAIL（区别于假通过）
                    results.append(
                        {
                            "case_no": case_no,
                            "case_id": getattr(case, "id", None),
                            "title": title,
                            "result": "FAIL",
                            "failures": ["E_UI_ACTION: 用例无 steps"],
                            "duration_ms": 0,
                        }
                    )
                    continue
                # 共享全局 context（所有用例 cookie/session 保持不变）
                # 数据驱动：显式 test_data > 归属数据集 data_rows > 默认单分组
                groups = (
                    test_data
                    or resolve_dataset_groups(case, ctx.db)
                    or [{"case": "默认", "params": {}}]
                )
                group_vars: dict[str, Any] = {}
                # 解析本用例所需内核对应的 context（惰性启动次内核；缺内核则记录 SKIP 原因）
                want_browser = browser_cfg or primary_browser
                if want_browser not in ("chromium", "firefox", "webkit"):
                    want_browser = primary_browser
                run_context = None
                skip_reason = None
                if want_browser in browser_cache:
                    run_context = browser_cache[want_browser][1]
                elif want_browser in launch_failed:
                    skip_reason = launch_failed[want_browser]
                else:
                    try:
                        nb = getattr(p, want_browser).launch(headless=True, args=["--no-sandbox"])
                        nctx, _errs = _prepare_context(nb, auth, base_url)
                        browser_cache[want_browser] = (nb, nctx)
                        run_context = nctx
                    except Exception as exc:  # noqa: BLE001
                        reason = (
                            f"内核 {want_browser} 未安装/启动失败（{exc.__class__.__name__}），"
                            f"请执行 python -m playwright install {want_browser}"
                        )
                        launch_failed[want_browser] = reason
                        skip_reason = reason
                if skip_reason is not None:
                    results.append(
                        {
                            "case_no": case_no,
                            "case_id": getattr(case, "id", None),
                            "title": title,
                            "result": "SKIP",
                            "failures": [skip_reason],
                            "duration_ms": 0,
                            "viewport": viewport_cfg if isinstance(viewport_cfg, dict) else None,
                            "browser": want_browser,
                        }
                    )
                    continue
                context = run_context
                for g in groups:
                    params = dict((g.get("params") or {}) if isinstance(g, dict) else {})
                    try:
                        page = context.new_page()
                        if isinstance(viewport_cfg, dict) and viewport_cfg.get("width") and viewport_cfg.get("height"):
                            try:
                                page.set_viewport_size({
                                    "width": int(viewport_cfg["width"]),
                                    "height": int(viewport_cfg["height"]),
                                })
                            except Exception:  # noqa: BLE001
                                pass
                        from time import perf_counter

                        start = perf_counter()
                        passed, failures, shot, variables = _run_steps(
                            page, steps, base_url, variables=params
                        )
                        group_vars.update(variables or {})
                        # 判定逻辑：
                        # 1) 步骤执行有异常（failures 非空，如 goto 不可达 → 抛 ERR_EMPTY_RESPONSE）→ 直接 FAIL
                        # 2) 步骤全部通过 + 有断言 → PASS
                        # 3) 步骤全部通过 + 无断言 → SKIP（纯导航/录制回放，不做最终判定）
                        has_assertion = bool(
                            case_assertions
                            or any(s.get("assertions") for s in steps)
                            or any(
                                str(s.get("action") or "").strip().lower().startswith("assert")
                                for s in steps
                            )
                        )
                        if failures:
                            result = "FAIL"
                        elif has_assertion:
                            result = "PASS"
                        else:
                            result = "SKIP"
                        duration_ms = int((perf_counter() - start) * 1000)
                        if shot:
                            artifacts.append(
                                {"name": f"ui_shot_{case_no}", "type": "IMAGE", "path": shot}
                            )
                        results.append(
                            {
                                "case_no": case_no,
                                "case_id": getattr(case, "id", None),
                                "title": title,
                                "group": g.get("case") if isinstance(g, dict) else "默认",
                                "result": result,
                                "failures": failures,
                                "duration_ms": duration_ms,
                                "screenshot": shot or None,
                                "viewport": viewport_cfg if isinstance(viewport_cfg, dict) else None,
                                "browser": want_browser,
                            }
                        )
                    finally:
                        try:
                            page.close()
                        except Exception:  # noqa: BLE001
                            pass
                # ---- BE-6 后置清理：用例执行完成后执行 ----
                post_cleanup = (
                    getattr(case, "post_cleanup", None)
                    or (case.get("post_cleanup") if isinstance(case, dict) else None)
                    or []
                )
                if post_cleanup:
                    from ..services.post_cleanup import run_post_cleanup
                    cleanup_warnings.extend(run_post_cleanup(post_cleanup, group_vars))
        finally:
            # 关闭全部内核 context 与 browser（含惰性启动的次内核）
            for _name, (_br, _ctx) in list(browser_cache.items()):
                try:
                    if _ctx is not None:
                        _ctx.close()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    if _br is not None:
                        _br.close()
                except Exception:  # noqa: BLE001
                    pass
            try:
                if p is not None:
                    p.stop()
            except Exception:  # noqa: BLE001
                pass

        passed = sum(1 for r in results if r["result"] == "PASS")
        skipped = sum(1 for r in results if r["result"] == "SKIP")
        judged = len(results) - skipped
        failed = judged - passed
        error = None
        if pre_login_errors:
            error = f"前置登录步骤存在失败: {pre_login_errors[0]}"
        if failed > 0:
            first_fail = next((r["failures"][0] if r["failures"] else "") for r in results if r["result"] == "FAIL")
            err_msg = f"{failed} 条 UI 用例失败，如: {first_fail}"
            error = (error + "；" + err_msg) if error else err_msg
        # 引擎整体状态判定：
        # - 有 FAIL 或 pre_login_errors → FAILED
        # - 有 PASS 且无 FAIL → SUCCESS
        # - 全 SKIP → SKIPPED（不再假装 SUCCESS）
        has_fail = failed > 0 or bool(pre_login_errors)
        has_pass = passed > 0
        all_skipped = skipped == len(results) and len(results) > 0
        if has_fail:
            overall_status = "FAILED"
        elif all_skipped:
            overall_status = "SKIPPED"
        elif has_pass:
            overall_status = "SUCCESS"
        else:
            overall_status = "SKIPPED"
        conclusion = (
            error or (
                "UI 用例全部通过" if overall_status == "SUCCESS"
                else "UI 用例全部 SKIP（无断言判定）" if overall_status == "SKIPPED"
                else "存在失败项"
            )
        )
        return EngineResult(
            status=overall_status,
            summary={
                "total": len(results),
                "passed": passed,
                "failed": failed + (1 if pre_login_errors else 0),
                "skipped": skipped,
                "pass_rate": round(passed / judged, 4) if judged else 0.0,
                "key": "ui_pass_rate",
            },
            report_payload={
                "engine": self.engine_code,
                "results": results,
                "pre_login_errors": pre_login_errors,
                "cleanup_warnings": cleanup_warnings,
                "conclusion": conclusion,
            },
            artifacts=artifacts,
            error=error,
        )