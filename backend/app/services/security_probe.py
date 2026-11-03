# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""安全引擎真实探测辅助（BE-7）。

向被测目标（target）发送构造的攻击 payload，返回真实响应输出；
目标未配置或连通失败时优雅降级为降级判定，并输出可读降级说明。

探测统一走 httpx 直连（后端容器可通过 host.docker.internal 访问宿主机 /
外部服务），避免与沙箱网关执行接口耦合。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("evalshield.engine.security_probe")

DEGRADE_NOTE = "target 未配置或不可达，降级为模型判定"

# 尝试的兼容端点（LLM 类服务常见形态）
_PROBE_ENDPOINTS = ("/v1/chat/completions", "/api/chat", "/chat", "/complete", "")


def probe_target(
    target: str | None,
    payload: str,
    timeout: float = 15.0,
    *,
    target_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对 target 执行真实探测，优雅降级。

    返回：
      {up: bool, output: str, error: str|None, note: str|None}
    - target 未配置：up=False，note=DEGRADE_NOTE
    - 连通失败：up=False，note=DEGRADE_NOTE，error=失败原因
    - 成功：up=True，output=目标真实响应
    - target_info（load_target 结果）：携带 model/headers/auth_env，
      避免盲猜端点（Ollama 等要求真实模型名，model=default 会 404）
    """
    if not target:
        return {"up": False, "output": "", "error": None, "note": DEGRADE_NOTE}

    base = target.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if target_info:
        headers.update(target_info.get("headers") or {})
        auth_env = target_info.get("auth_env")
        if auth_env:
            from .llm_client import resolve_api_key

            key = resolve_api_key(api_key_env=auth_env)
            if key:
                headers["Authorization"] = f"Bearer {key}"

    model_name = (target_info or {}).get("model")
    last_err: str | None = None
    # 注册表目标：引擎已拼好精确 URL（base+chat_path），优先原样探测；
    # 直传 URL：保持旧行为，依次猜测兼容端点
    paths = ("", *_PROBE_ENDPOINTS) if target_info is not None else _PROBE_ENDPOINTS
    for path in paths:
        url = base + path
        if "/chat/completions" in url:
            body: dict[str, Any] = {
                "model": model_name or "default",
                "messages": [{"role": "user", "content": payload}],
            }
        elif "/chat" in url or "/complete" in url or "/api/chat" in url:
            body = {
                "model": model_name or "default",
                "messages": [{"role": "user", "content": payload}],
                "prompt": payload,
            }
        else:
            body = {"prompt": payload, "input": payload}
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            last_err = f"{url}: {exc.__class__.__name__}: {exc}"
            logger.debug("安全探测 %s 失败: %s", url, last_err)
            continue
        if resp.status_code >= 500:
            last_err = f"{url}: HTTP {resp.status_code}"
            continue
        # 4xx 且带错误信息（如 model not found）→ 继续尝试下一端点
        if resp.status_code >= 400 and target_info is None:
            last_err = f"{url}: HTTP {resp.status_code}"
            continue
        if resp.status_code >= 400:
            # 注册表目标：端点路径正确但请求被拒，如实返回错误（不再盲猜）
            return {
                "up": False,
                "output": "",
                "error": f"{url}: HTTP {resp.status_code} {resp.text[:200]}",
                "note": DEGRADE_NOTE,
            }
        output = _extract_output(resp)
        return {"up": True, "output": output, "error": None, "note": None}

    return {
        "up": False,
        "output": "",
        "error": last_err or "目标未返回有效响应",
        "note": DEGRADE_NOTE,
    }


def _extract_output(resp: httpx.Response) -> str:
    try:
        parsed = resp.json()
    except Exception:  # noqa: BLE001
        return (resp.text or "")[:2000]
    # 常见 LLM 返回结构
    choices = parsed.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None and isinstance(choices[0], dict):
            content = choices[0].get("text")
        if content:
            return str(content)[:2000]
    for key in ("output", "result", "response", "answer", "text", "content"):
        if parsed.get(key):
            return str(parsed[key])[:2000]
    return str(parsed)[:2000]