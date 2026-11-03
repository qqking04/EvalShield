# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""引擎内 LLM 接入辅助：统一解析任务配置中的模型，提供真实模型输出。

约定：
- 任务 config.model_args 可携带：
    model_code: str  指定 ModelConfig.code（优先级最高）
    model_outputs: dict  显式预置输出（次优先，兼容旧 mock 数据）
- 未指定 model_code 时回退到 ModelConfig.is_default=True 且 status=ACTIVE 的记录。
- 无可用模型 → 返回空 dict（引擎侧走规则兜底逻辑）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from .llm_client import LLMClientError, chat_completion

logger = logging.getLogger("evalshield.llm")

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)

# 匹配 .format() 模板中未转义的单花括号占位符：{xxx} 但排除 {{xxx}} 双花括号
# 先替换 {{ 和 }} 为占位符 → 再找 {xxx} → 再恢复双花括号
_SINGLE_BRACE_RE = re.compile(
    r"(?<!\{)\{([^{}]+)\}(?!\})"
)


def safe_format_prompt(template: str, **kwargs: Any) -> str:
    """安全的 prompt 模板格式化（BUG-12/13 根因级防护）。

    **核心策略：不使用 Python ``str.format()`` 做 prompt 注入**，改用
    ``{{ var }}`` 占位符 + 简单字符串替换，从结构上彻底避免 JSON 示例
    里的 ``{...}`` 被误解析为占位符。

    用法：
    - 注入变量：写 ``{{ answer }}`` 或 ``{{answer}}`` → 替换为 kwargs 中的值
    - JSON 示例：直接写 ``{"contradiction": true|false}`` —— 无需任何转义！

    兼容旧模板（仍用 ``.format()`` 风格 ``{var}``）：
    若检测到 ``{var}`` 风格占位符且 kwargs 中有对应 key，自动降级为
    ``.format()`` 并 warn 提示迁移。

    Args:
        template: prompt 模板（JSON 示例中的 ``{...}`` 无需转义）
        **kwargs: 注入变量

    Returns:
        替换后的 prompt

    Example:
        >>> safe_format_prompt(
        ...     '只输出 JSON：{"ok": true}\\n答案：{{ answer }}',
        ...     answer='hello'
        ... )
        '只输出 JSON：{"ok": true}\\n答案：hello'
    """
    result = template

    # 处理 {{ var }} / {{var}} 占位符（空格可选）
    for key, value in kwargs.items():
        result = result.replace("{{ " + key + " }}", str(value))
        result = result.replace("{{" + key + "}}", str(value))

    # 降级兼容：若模板仍有旧风格 {var}（单花括号 + var 在 kwargs 里）
    # 自动 .format() 并 warn 提示迁移（.format() 遇到 JSON {xxx} 会 KeyError → 静默跳过）
    legacy_pattern = re.compile(
        r"(?<!\{)\{(" + "|".join(re.escape(k) for k in kwargs) + r")\}(?!\})"
    )
    if legacy_pattern.search(result):
        logger.warning(
            "safe_format_prompt: 检测到旧模板风格 {var}，建议迁移为 {{ var }} "
            "（避免与 JSON 示例冲突）"
        )
        try:
            result = result.format(**kwargs)
        except (KeyError, IndexError):
            pass  # 遇到 JSON 示例里的 {xxx} 就放弃降级

    return result


def llm_generate_json(
    model: dict | None,
    *,
    prompt: str | None = None,
    system: str | None = None,
    cache_namespace: str | None = None,
) -> dict | None:
    """调用 LLM 并容错解析 JSON 对象；任何失败返回 None（调用方必须回退规则）。"""
    raw = llm_generate(
        model, prompt=prompt, system=system, json_mode=True,
        cache_namespace=cache_namespace,
    )
    if not raw:
        return None
    return extract_json_object(raw)


_TICKS = chr(96) * 3  # 三个反引号序列：避免在 markdown 代码块内出现字面量


def extract_json_object(raw: str) -> dict | None:
    """从 LLM 输出中提取第一个 JSON 对象（兼容 markdown 围栏与前后缀噪音）。"""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith(_TICKS):
        text = re.sub(r"^" + _TICKS + r"[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*" + _TICKS + r"$", "", text)
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(obj, dict):
        return _normalize_dict_keys(obj)
    return None


def _normalize_dict_keys(obj: Any) -> Any:
    """递归清理 dict key 中的各种引号/转义残留。

    处理格式：
    - ``"key"`` / ``\"key\"`` 双引号包裹
    - ``'key'`` 单引号包裹（少数模型输出）
    - ``\\key`` 开头残留反斜杠
    - key 为空字符串时丢弃
    """
    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for raw_k, v in obj.items():
            nk = str(raw_k).strip()
            # 去首尾双引号
            if len(nk) >= 2 and nk[0] == '"' and nk[-1] == '"':
                nk = nk[1:-1].replace('\\"', '"').strip()
            # 去首尾单引号
            elif len(nk) >= 2 and nk[0] == "'" and nk[-1] == "'":
                nk = nk[1:-1].replace("\\'", "'").strip()
            # 清理中间残留的转义引号
            nk = nk.replace('\\"', '"').replace("\\'", "'").strip()
            # 去开头孤立反斜杠
            nk = nk.lstrip("\\")
            if nk:  # 空 key 丢弃
                cleaned[nk] = _normalize_dict_keys(v)
        return cleaned
    if isinstance(obj, list):
        return [_normalize_dict_keys(item) for item in obj]
    return obj


def _fallback_default_row(q, tenant_id: int | None):
    """在带租户过滤的 query 上按正确优先级挑默认模型。

    优先级：本租户私有 is_default > 全局 is_system is_default > id 升（稳定兜底）。
    """
    from ..models import ModelConfig
    if tenant_id is None:
        return (
            q.filter(ModelConfig.is_default == True)  # noqa: E712
            .order_by(ModelConfig.id.asc())
            .first()
        )
    is_private_default = (ModelConfig.tenant_id == tenant_id) & (ModelConfig.is_default == True)  # noqa: E712
    is_system_default = ModelConfig.is_system.is_(True) & (ModelConfig.is_default == True)         # noqa: E712
    return (
        q.filter(ModelConfig.is_default == True)  # noqa: E712
        .order_by(is_private_default.desc(), is_system_default.desc(), ModelConfig.id.asc())
        .first()
    )


def resolve_model_config(
    db: Session | None, config: dict[str, Any] | None,
    tenant_id: int | None = None,
) -> dict[str, Any] | None:
    """返回 {code, provider, base_url, model, api_key_env, temperature, max_tokens, timeout_sec}。

    P0-2 租户隔离扩展：新增可选 ``tenant_id`` 参数，传入时过滤
    ``(ModelConfig.tenant_id == tenant_id) | (ModelConfig.is_system.is_(True))``，
    保证跨租户不串默认模型；``tenant_id=None``（默认）保持旧逻辑，不影响引擎既有调用。

    #3 静默回退留痕：显式指定 model_code 未命中而降级默认时，返回 dict 附
    ``fallback_note``（请求值 vs 实际值），由引擎写入 snapshot/note 透出，不改变回退行为本身。
    """
    if db is None:
        logger.warning("resolve_model_config: db=None，返回 None（引擎将走规则兜底）")
        return None
    from ..models import ModelConfig

    cfg = config or {}
    model_args = cfg.get("model_args") or {}
    # 优先级：顶层 model_gateway > judge_model（6 引擎统一契约 §3.1）> model_args.model_code > 默认
    model_code = cfg.get("model_gateway") or cfg.get("judge_model") or model_args.get("model_code")
    fallback_note = None
    q = db.query(ModelConfig).filter(
        ModelConfig.deleted_at.is_(None), ModelConfig.status == "ACTIVE"
    )
    if model_code:
        # 用户显式指定 model_gateway / model_code → 优先精确查找（带租户过滤）
        row = q.filter(ModelConfig.code == model_code).first()
        if row is None:
            logger.warning(
                "resolve_model_config: 指定 model_code=%s 未找到 ACTIVE 记录，尝试降级默认",
                model_code,
            )
            row = _fallback_default_row(q, tenant_id)
            if row is not None:
                fallback_note = f"指定模型「{model_code}」未命中，实际使用「{row.code}」"
    elif tenant_id is not None:
        row = _fallback_default_row(q, tenant_id)
    else:
        row = (
            q.filter(ModelConfig.is_default == True)  # noqa: E712
            .order_by(ModelConfig.id.asc())
            .first()
        )
    if row is None:
        logger.warning(
            "resolve_model_config: 无任何 ACTIVE+default 模型配置，返回 None"
        )
        return None
    result: dict[str, Any] = {
        "code": row.code,
        "provider": row.provider,
        "base_url": row.base_url,
        "model": row.model,
        "api_key_env": row.api_key_env,
        "api_key_enc": row.api_key_enc,
        "temperature": row.temperature,
        "max_tokens": row.max_tokens,
        "timeout_sec": row.timeout_sec,
        "seed": row.seed,
        "input_price_per_mtok": row.input_price_per_mtok,
        "output_price_per_mtok": row.output_price_per_mtok,
    }
    if fallback_note:
        result["fallback_note"] = fallback_note
    return result


def llm_generate(
    model: dict[str, Any] | None,
    *,
    prompt: str | None = None,
    system: str | None = None,
    history: list[dict[str, str]] | None = None,
    json_mode: bool = False,
    cache_namespace: str | None = None,
) -> str | None:
    """调用真实 LLM；任何失败（未配置/网络/超时）返回 None，不抛异常。"""
    if model is None:
        return None
    try:
        return chat_completion(
            provider=model.get("provider", "LOCAL"),
            base_url=model.get("base_url"),
            model=model.get("model", ""),
            api_key_env=model.get("api_key_env"),
            api_key_enc=model.get("api_key_enc"),
            prompt=prompt,
            system=system,
            history=history,
            temperature=float(model.get("temperature", 0.2)),
            max_tokens=int(model.get("max_tokens", 2048)),
            timeout_sec=int(model.get("timeout_sec", 60)),
            json_mode=json_mode,
            seed=model.get("seed"),
            cache_namespace=cache_namespace,
        )
    except LLMClientError as exc:
        logger.warning("LLM 调用失败（引擎降级为规则输出）: %s", exc)
        return None
