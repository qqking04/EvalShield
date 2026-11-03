# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""被测系统门面：统一 target 适配层，与 Judge 模型彻底分离（根治 F7）。

- LLM_API：OpenAI 兼容 chat/completions，response_path 点路径提取回答。
- APP_API：request_template（{{prompt}}/{{history_json}} 占位）渲染自定义请求体。
- INTERNAL_MODEL / 未注册：回退 EvalShield 内置模型，target_mode=INTERNAL_DEMO。
- 任何网络/解析异常 → output=""、error 填原因，不抛出（引擎侧降级）。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..models import TargetRegistry
from .engine_llm import llm_generate
from .llm_client import resolve_api_key

logger = logging.getLogger("evalshield.target_gateway")

DEFAULT_RESPONSE_PATH = "choices.0.message.content"


class TargetError(Exception):
    """门面配置错误（如密钥缺失）。"""


def load_target(db: Session | None, code: str | None, tenant_id: int = 1) -> dict[str, Any] | None:
    """按 code 读取 ACTIVE 被测对象；code 为空/查不到返回 None（调用方走 INTERNAL_DEMO）。"""
    if db is None or not code:
        return None
    row = (
        db.query(TargetRegistry)
        .filter(
            TargetRegistry.code == code,
            TargetRegistry.status == "ACTIVE",
            TargetRegistry.deleted_at.is_(None),
            TargetRegistry.tenant_id == tenant_id,
        )
        .first()
    )
    if row is None:
        logger.warning("load_target: code=%s 无 ACTIVE 记录，走 INTERNAL_DEMO", code)
        return None
    return {
        "code": row.code,
        "name": row.name,
        "target_type": row.target_type,
        "tenant_id": row.tenant_id,  # ES8 M8：旁路留痕需要租户上下文
        "base_url": row.base_url,
        "chat_path": row.chat_path or "/chat/completions",
        "protocol": row.protocol or "OPENAI",
        "auth_env": row.auth_env,
        "headers": row.headers or {},
        "request_template": row.request_template,
        "response_path": row.response_path or DEFAULT_RESPONSE_PATH,
        "model": getattr(row, "model", None),
        "timeout_sec": row.timeout_sec or 30,
    }


def _extract_path(payload: Any, path: str) -> Any:
    """点路径取值：choices.0.message.content / data.answer（数字段按列表下标）。"""
    cur = payload
    for seg in (path or "").split("."):
        if not seg:
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(seg)]
            except (ValueError, IndexError):
                raise KeyError(path)
        elif isinstance(cur, dict):
            if seg not in cur:
                raise KeyError(path)
            cur = cur[seg]
        else:
            raise KeyError(path)
    return cur


def _render_template(template: Any, prompt: str, history: list[dict[str, str]] | None) -> Any:
    """渲染 {{prompt}} / {{history_json}} 占位（仅字符串叶子）。"""
    hist_json = json.dumps(history or [], ensure_ascii=False)

    def _sub(v: Any) -> Any:
        if isinstance(v, str):
            return v.replace("{{prompt}}", prompt).replace("{{history_json}}", hist_json)
        if isinstance(v, dict):
            return {k: _sub(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_sub(x) for x in v]
        return v

    return _sub(template)


def respond(
    target: dict | None,
    *,
    prompt: str,
    history: list[dict[str, str]] | None = None,
    system: str | None = None,
    internal_model: dict | None = None,
) -> dict[str, Any]:
    """统一应答入口。

    返回: {"output": str, "latency_ms": int, "target_mode": "API"|"INTERNAL_DEMO",
           "error": str|None, "raw": dict|None}
    """
    t0 = time.perf_counter()
    if target is not None and (target.get("base_url") or "").startswith("internal://offline"):
        # 离线靶机：不发起任何真实调用，输出完全由引擎侧 preset_outputs 兜底
        # （§9.2 确定性断言专用；respond 返回空 output，引擎按题号下标取预置输出）
        return {
            "output": "",
            "latency_ms": 0,
            "target_mode": "INTERNAL_DEMO",
            "error": "预置输出靶机：不发起真实调用，连通测试不适用（评测时输出由题目预置数据兜底）",
            "raw": None,
        }
    if target is None or target.get("target_type") == "INTERNAL_MODEL":
        # INTERNAL_DEMO：走评判/内置模型通道（engine_llm.llm_generate）
        try:
            out = llm_generate(internal_model, prompt=prompt, system=system, history=history) or ""
            err = None if out else "内置模型不可用"
            return {
                "output": out,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "target_mode": "INTERNAL_DEMO",
                "error": err,
                "raw": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "output": "",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "target_mode": "INTERNAL_DEMO",
                "error": f"内置模型调用失败: {exc}",
                "raw": None,
            }

    mode = "INTERNAL_DEMO" if target.get("target_type") == "INTERNAL_MODEL" else "API"
    timeout = int(target.get("timeout_sec") or 30)
    try:
        api_key = resolve_api_key(api_key_env=target.get("auth_env"))
        if target.get("auth_env") and not api_key:
            return {
                "output": "",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "target_mode": mode,
                "error": f"密钥环境变量 {target.get('auth_env')} 未配置",
                "raw": None,
            }
        headers = {"Content-Type": "application/json"}
        headers.update(target.get("headers") or {})
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        if target.get("target_type") == "APP_API" or target.get("protocol") == "CUSTOM":
            body = _render_template(
                target.get("request_template") or {"prompt": "{{prompt}}"},
                prompt, history,
            )
            url = target["base_url"].rstrip("/")
        else:  # LLM_API / OPENAI 协议
            msgs: list[dict[str, str]] = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.extend(history or [])
            msgs.append({"role": "user", "content": prompt})
            body = {"messages": msgs}
            if target.get("model"):
                body["model"] = target["model"]
            url = target["base_url"].rstrip("/") + (target.get("chat_path") or "/chat/completions")

        r = httpx.post(url, json=body, headers=headers, timeout=timeout)
        if r.status_code >= 400:
            return {
                "output": "",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "target_mode": mode,
                "error": f"HTTP {r.status_code}: {(r.text or '')[:200]}",
                "raw": None,
            }
        raw = r.json()
        text = _extract_path(raw, target.get("response_path") or DEFAULT_RESPONSE_PATH)
        out = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
        latency = int((time.perf_counter() - t0) * 1000)
        # ES8 M8：真实网关 API 成功 → 旁路留痕（内部全容错，绝不阻断转发）
        from .trace_recording import _extract_tokens, maybe_record_gateway_trace

        maybe_record_gateway_trace(
            target,
            prompt=prompt,
            response=out or "",
            latency_ms=latency,
            external_ref=(raw or {}).get("id") if isinstance(raw, dict) else None,
            tokens=_extract_tokens(raw if isinstance(raw, dict) else None),
        )
        return {
            "output": out or "",
            "latency_ms": latency,
            "target_mode": mode,
            "error": None if out else "接口返回成功但内容为空，请检查 response_path 配置",
            "raw": raw,
        }
    except KeyError as exc:
        return {
            "output": "",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "target_mode": mode,
            "error": f"response_path 取值失败: {exc.args[0] if exc.args else exc}",
            "raw": None,
        }
    except Exception as exc:  # noqa: BLE001 - 网络/解析异常一律降级
        logger.warning("target %s 调用失败: %s", target.get("code"), exc)
        return {
            "output": "",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "target_mode": mode,
            "error": f"{type(exc).__name__}: {exc}",
            "raw": None,
        }


def test_target(db: Session | None, code: str, tenant_id: int = 1) -> dict[str, Any]:
    """连通性自检：发送固定 prompt「你好」，返回 {ok, latency_ms, sample, error, skipped?}。"""
    target = load_target(db, code, tenant_id=tenant_id)
    if target is None:
        return {"ok": False, "latency_ms": 0, "sample": "", "error": f"被测对象 {code} 不存在或非 ACTIVE"}
    if (target.get("base_url") or "").startswith("internal://offline"):
        # 预置输出靶机按设计不发起真实调用，连通测试不适用（非失败）
        return {
            "ok": True,
            "skipped": True,
            "latency_ms": 0,
            "sample": "",
            "error": "预置输出靶机：不发起真实调用，连通测试不适用（评测时输出由题目预置数据兜底）",
        }
    internal_model = None
    if target.get("target_type") == "INTERNAL_MODEL":
        # 内置模型走评判/默认模型通道：需解析默认配置，否则 llm_generate(None) 恒失败
        from .engine_llm import resolve_model_config
        internal_model = resolve_model_config(db, None, tenant_id=tenant_id)
    resp = respond(target, prompt="你好", internal_model=internal_model)
    return {
        "ok": bool(resp["output"]) and resp["error"] is None,
        "latency_ms": resp["latency_ms"],
        "sample": (resp["output"] or "")[:200],
        "error": resp["error"],
    }
