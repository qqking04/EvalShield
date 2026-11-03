# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""用例后置清理执行器（BE-6）。

在用例执行完成后清理测试产生的脏数据/恢复环境。支持动作：
  - reset_account    : 重置测试账号锁定/状态（向 target 发清理请求）
  - delete_record    : 删除测试创建的记录（向 target 发清理请求）
  - restore_resource : 恢复被压测资源（向 target 发清理请求）
  - custom_script    : 自定义清理脚本（经沙箱/Sandbox 执行，禁止宿主机直连）

设计原则：清理失败仅输出 W_CLEANUP 告警，不判定用例失败（清理非主判定）。
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

logger = logging.getLogger("evalshield.post_cleanup")

# 清理动作识别：区分"发 HTTP 清理请求"与"沙箱脚本"两类
_HTTP_ACTIONS = {"reset_account", "delete_record", "restore_resource"}


def _build_cleanup_request(
    item: dict[str, Any], variables: dict | None
) -> tuple[str, str, dict, Any, str]:
    """把清理条目解析为 (url, method, headers, body, note)。"""
    params = dict((item.get("params") or {}) if isinstance(item, dict) else {})
    for k, v in list(params.items()):
        if isinstance(v, str):
            for vk, vv in (variables or {}).items():
                v = v.replace("{{" + vk + "}}", "" if vv is None else str(vv))
            params[k] = v
    target = item.get("target") or params.pop("url", None) or ""
    path = params.pop("path", "") or ""
    method = (params.pop("method", "POST") or "POST").upper()
    url = target.rstrip("/") + "/" + path.lstrip("/")
    headers = params.pop("headers", {}) or {}
    note = params.pop("note", "")
    return url, method, headers, params, note


def _run_http_cleanup(item: dict, variables: dict | None) -> str | None:
    """执行 HTTP 类清理请求。成功返回 None，异常返回告警文本。"""
    try:
        url, method, headers, payload, note = _build_cleanup_request(item, variables)
        if not url:
            return "W_CLEANUP: 清理条目缺少 target"
        timeout = float((item.get("params") or {}).get("timeout", 10))
        with httpx.Client(timeout=timeout) as client:
            resp = client.request(method, url, headers=headers, json=payload)
        if resp.status_code >= 400:
            return f"W_CLEANUP: {method} {url} 返回 {resp.status_code}" + (
                f"（{note}）" if note else ""
            )
        logger.info("清理完成 %s %s %s", method, url, note or "")
        return None
    except Exception as exc:  # noqa: BLE001
        return f"W_CLEANUP: 清理请求失败: {exc.__class__.__name__}: {exc}"


def _run_custom_script(item: dict, variables: dict | None) -> str | None:
    """执行自定义清理脚本（经沙箱），返回 None 或告警。"""
    params = dict((item.get("params") or {}) if isinstance(item, dict) else {})
    script = params.get("script") or ""
    if not script:
        return "W_CLEANUP: custom_script 缺少 params.script"
    # 由调用方注入的 sandbox_driver 执行（无则给出占位告警，避免崩溃）
    sandbox_driver = params.get("_sandbox_driver")
    try:
        if sandbox_driver is not None:
            result = sandbox_driver(script, variables or {})
            if result is False:
                return "W_CLEANUP: custom_script 执行失败"
        else:
            return "W_CLEANUP: custom_script 未配置沙箱执行器，跳过（不影响主判定）"
        return None
    except Exception as exc:  # noqa: BLE001
        return f"W_CLEANUP: custom_script 执行异常: {exc.__class__.__name__}: {exc}"


def run_post_cleanup(
    post_cleanup: list | None,
    variables: dict | None = None,
    sandbox_driver=None,
) -> list[str]:
    """执行用例后置清理。返回告警列表（不抛出异常）。"""
    warnings: list[str] = []
    for item in post_cleanup or []:
        if not isinstance(item, dict):
            continue
        action = item.get("action", "")
        params = dict((item.get("params") or {}) if isinstance(item, dict) else {})
        if action == "custom_script":
            if sandbox_driver is not None:
                params = dict(params, _sandbox_driver=sandbox_driver)
                item = dict(item, params=params)
            warn = _run_custom_script(item, variables)
        elif action in _HTTP_ACTIONS:
            warn = _run_http_cleanup(item, variables)
        else:
            warn = f"W_CLEANUP: 未知清理动作 {action!r}"
        if warn:
            warnings.append(warn)
            logger.warning("%s", warn)
    return warnings