# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
# backend/app/services/llm_client.py（P2 升级版——保持既有函数签名，内部走统一链路）
"""模型网关客户端：统一 限流 -> 预算预检 -> 语义缓存 -> LLM 调用 -> 记账 -> 指标。

兼容性：
- chat_completion(provider, base_url, model, api_key_env, explicit_key, prompt,
                  system, history)：签名与旧版完全一致，现有引擎零改动。
- 新增 chat_completion_v2(model_cfg, prompt, system, history, **kw)：返回
  ChatCompletionResult（新网关链路推荐使用）。
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from openai import OpenAI
from openai import (
    APITimeoutError,
    APIStatusError,
    RateLimitError as OpenAIRateLimitError,
)

logger = logging.getLogger("evalshield.llm_client")


# ---------------------------------------------------------------- 错误体系 --
class GatewayErrorCode:
    RATE_LIMITED = "ES-GW-0001"
    TIMEOUT = "ES-GW-0002"
    AUTH = "ES-GW-0003"
    UPSTREAM = "ES-GW-0004"
    PARSE = "ES-GW-0005"
    BUDGET = "ES-GW-0006"
    PARAM = "ES-GW-0007"


class LLMClientError(Exception):
    """统一网关异常。error_code 对齐系统错误码 ES-GW-xxxx。"""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = GatewayErrorCode.UPSTREAM,
        retryable: bool = False,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.retryable = retryable
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.error_code, "message": self.message}


# ---------------------------------------------------------------- 配置常量 --
PROVIDER_DEFAULT_BASE_URLS: dict[str, str] = {
    # 与前端 Models.jsx PROVIDER_OPTIONS + seed.py MODEL_PROVIDER 严格对齐（大写 key）
    "DASHSCOPE": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "BAIDU": "https://qianfan.baidubce.com/v2",            # 百度千帆（前端传 BAIDU，旧 QIANFAN 已废弃）
    "VOLCENGINE": "https://ark.cn-beijing.volces.com/api/v3",  # 火山方舟（新增）
    "OPENAI": "https://api.openai.com/v1",
    "DEEPSEEK": "https://api.deepseek.com/v1",
    "LOCAL": "http://host.docker.internal:11434/v1",
}

MODEL_QPS_LIMIT: float = float(os.getenv("GATEWAY_MODEL_QPS", "2"))
MODEL_CONCURRENCY_LIMIT: int = int(os.getenv("GATEWAY_MODEL_CONCURRENCY", "4"))
GATEWAY_MAX_RETRIES: int = 2  # 指数退避重试上限（总尝试 = 1 + 2）


def effective_base_url(provider: str, base_url: str | None) -> str:
    if base_url:
        return base_url
    if provider == "LOCAL":
        # 本地模型统一走宿主机 Ollama（与 config.OLLAMA_BASE_URL 单一配置源对齐）
        from ..config import settings

        return settings.OLLAMA_BASE_URL
    return PROVIDER_DEFAULT_BASE_URLS.get(
        provider, PROVIDER_DEFAULT_BASE_URLS["LOCAL"]
    )


def resolve_api_key(
    *, api_key_env: str | None, api_key_enc: str | None = None
) -> str | None:
    """取 API Key：库内密文（ES9-P-05，与 env 名互斥）优先，其次环境变量名。

    两者皆空返回 None。api_key_enc 由 services/crypto.py 解密（旧明文透明兼容）。
    """
    if api_key_enc:
        from .crypto import decrypt_api_key

        plain = decrypt_api_key(api_key_enc)
        if plain:
            return plain.strip() or None
    if not api_key_env:
        return None
    return os.getenv(api_key_env, "").strip() or None


# ---------------------------------------------------------------- 数据类 ----
@dataclass
class ChatUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class ChatCompletionResult:
    text: str
    provider: str
    model: str
    latency_ms: int
    cache_hit: bool = False
    usage: ChatUsage = field(default_factory=ChatUsage)
    cost: float = 0.0
    error_code: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "cache_hit": self.cache_hit,
            "usage": self.usage.to_dict(),
            "cost": round(self.cost, 6),
            "error_code": self.error_code,
        }


# ---------------------------------------------------------------- 内部调用 --
def _call_single(
    model_cfg: dict[str, Any],
    *,
    prompt: str,
    system: str | None,
    history: list[dict[str, str]] | None,
    json_mode: bool = False,
) -> tuple[str, ChatUsage, dict[str, Any]]:
    """单次 LLM 调用（不做重试）。返回 (text, usage, raw)。

    抛出的异常由调用方按类型分类决定是否重试：
    - OpenAIRateLimitError / APITimeoutError -> retryable
    - APIStatusError（其他 4xx/5xx）-> 不可重试，编码为对应错误码
    """
    url = effective_base_url(
        model_cfg.get("provider", "LOCAL"), model_cfg.get("base_url")
    )
    api_key = resolve_api_key(
        api_key_env=model_cfg.get("api_key_env"),
        api_key_enc=model_cfg.get("api_key_enc"),
    )
    client = OpenAI(
        base_url=url,
        api_key=api_key or "EMPTY",
        timeout=float(model_cfg.get("timeout_sec") or 60),
        max_retries=1,  # SDK 层最多重试 1 次；编排层另有指数退避（不与 SDK 叠加过多）
    )
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": str(system)})
    for h in history or []:
        messages.append(
            {"role": str(h.get("role", "user")), "content": str(h.get("content", ""))}
        )
    messages.append({"role": "user", "content": str(prompt)})

    params: dict[str, Any] = {
        "model": model_cfg.get("model", ""),
        "messages": messages,
        "temperature": float(model_cfg.get("temperature") or 0.4),
        "max_tokens": int(model_cfg.get("max_tokens") or 4096),
    }
    # 6 引擎改进 T2：固定采样种子（Provider 不支持时忽略 extra_body 中的未知字段）
    if model_cfg.get("seed") is not None:
        params["extra_body"] = {"seed": int(model_cfg["seed"])}
    if json_mode:
        params["response_format"] = {"type": "json_object"}
        if not any(m.get("role") == "system" for m in messages):
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": "始终只输出合法 JSON，不要输出任何其他文字。",
                },
            )
    resp = client.chat.completions.create(**params)
    text = resp.choices[0].message.content or ""
    raw = {
        "id": resp.id,
        "finish_reason": resp.choices[0].finish_reason,
        "model": resp.model,
    }
    return (
        text,
        ChatUsage(
            prompt_tokens=int(getattr(resp.usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(resp.usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(resp.usage, "total_tokens", 0) or 0),
        ),
        raw,
    )


def _call_with_retry(
    model_cfg: dict[str, Any],
    *,
    prompt: str,
    system: str | None,
    history: list[dict[str, str]] | None,
    json_mode: bool = False,
) -> tuple[str, ChatUsage, dict[str, Any]]:
    """编排层指数退避重试（max 2 次）。"""
    last_retryable: LLMClientError | None = None
    for attempt in range(1, GATEWAY_MAX_RETRIES + 2):  # attempt = 1,2,3
        try:
            return _call_single(
                model_cfg,
                prompt=prompt,
                system=system,
                history=history,
                json_mode=json_mode,
            )
        except OpenAIRateLimitError as exc:
            last_retryable = LLMClientError(
                f"上游限流: {exc}",
                error_code=GatewayErrorCode.RATE_LIMITED,
                retryable=True,
                status_code=429,
            )
        except APITimeoutError as exc:
            last_retryable = LLMClientError(
                f"上游超时: {exc}",
                error_code=GatewayErrorCode.TIMEOUT,
                retryable=True,
            )
        except APIStatusError as exc:
            status = exc.status_code
            if status in (401, 403):
                raise LLMClientError(
                    f"鉴权失败({status}): {exc}",
                    error_code=GatewayErrorCode.AUTH,
                ) from exc
            # 5xx 与其余 4xx 按不可重试处理
            raise LLMClientError(
                f"上游返回 {status}: {exc}",
                error_code=GatewayErrorCode.UPSTREAM,
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 调用未知异常: %s", exc)
            last_retryable = LLMClientError(
                f"未知调用异常: {exc}",
                error_code=GatewayErrorCode.UPSTREAM,
                retryable=True,
            )
        if (
            last_retryable is not None
            and attempt <= GATEWAY_MAX_RETRIES
            and last_retryable.retryable
        ):
            delay = min(0.5 * (2**attempt), 4.0) + random.uniform(0, 0.2)
            logger.info(
                "LLM 调用重试 %s/%s，延迟 %.2fs", attempt, GATEWAY_MAX_RETRIES, delay
            )
            time.sleep(delay)
    assert last_retryable is not None
    raise last_retryable


# ---------------------------------------------------------------- 主入口 ----
def _gateway_pipeline(
    model_cfg: dict[str, Any],
    *,
    prompt: str,
    system: str | None,
    history: list[dict[str, str]] | None,
    use_cache: bool = True,
    use_semantic_cache: bool = True,
    db: Any = None,
    task_id: int | None = None,
    step_id: int | None = None,
    tenant_id: int = 1,
    ref_no: str | None = None,
    allow_budget_check: bool = True,
    json_mode: bool = False,
    cache_namespace: str | None = None,
) -> ChatCompletionResult:
    """统一编排：限流 -> 预算 -> 缓存 -> 调用 -> 记账 -> 写缓存。"""
    from .gateway_records import check_budget, estimate_prompt_tokens, record_usage
    from .llm_cache import llm_cache, normalize_messages
    from .rate_limiter import RateLimitReached, rate_limiter_registry

    provider = model_cfg.get("provider", "LOCAL")
    model = model_cfg.get("model", "")
    code = model_cfg.get("code") or model_cfg.get("model_code")
    in_price = float(model_cfg.get("input_price_per_mtok") or 0.0)
    out_price = float(model_cfg.get("output_price_per_mtok") or 0.0)
    start = time.perf_counter()
    error_code: str | None = None
    status = "SUCCESS"

    def _latency() -> int:
        return int((time.perf_counter() - start) * 1000)

    # 1) 限流键（令牌桶 + 并发槽在真实调用段获取，调用结束 finally 归还，避免槽位泄漏）
    limiter_key = code or f"{provider}:{model}"

    msgs = normalize_messages(prompt, system, history)

    # 2) 预算预检（估算）
    if allow_budget_check and db is not None:
        estimate_total = estimate_prompt_tokens(prompt or "") + int(
            model_cfg.get("max_tokens") or 4096
        )
        ok, ctx = check_budget(
            db, tenant_id=tenant_id, estimate_total_tokens=estimate_total
        )
        if not ok:
            record_usage(
                db,
                tenant_id=tenant_id,
                provider=provider,
                model=model,
                model_code=code,
                latency_ms=_latency(),
                status="FAILED",
                error_code=GatewayErrorCode.BUDGET,
                error_msg=f"token 预算不足（剩余 {ctx['remaining']}）",
            )
            raise LLMClientError(
                f"token 预算不足（剩余 {ctx['remaining']}）",
                error_code=GatewayErrorCode.BUDGET,
                status_code=429,
            )

    # 3) 缓存查询
    if use_cache:
        hit = llm_cache.get(
            db,
            tenant_id=tenant_id,
            provider=provider,
            model=model,
            messages=msgs,
            semantic_prompt=prompt if use_semantic_cache else None,
            namespace=cache_namespace,
        )
        if hit is not None:
            text, is_semantic = hit
            result = ChatCompletionResult(
                text=text,
                provider=provider,
                model=model,
                latency_ms=_latency(),
                cache_hit=True,
                usage=ChatUsage(),
                cost=0.0,
            )
            record_usage(
                db,
                tenant_id=tenant_id,
                provider=provider,
                model=model,
                model_code=code,
                cache_hit=True,
                latency_ms=_latency(),
                status="SUCCESS",
            )
            return result

    # 4) 限流获取 + 调用（含指数退避重试）
    # 旧实现缺陷：在缓存查询前 acquire 且从不 release → 并发槽泄漏，
    # 8 次调用后所有请求永久「限流触发」。现仅在真实调用期间占用槽位。
    limiter = rate_limiter_registry.get(limiter_key)
    _wait_left = 15.0
    while True:
        try:
            limiter.acquire()
            break
        except RateLimitReached as exc:
            if _wait_left <= 0:
                record_usage(
                    db,
                    tenant_id=tenant_id,
                    provider=provider,
                    model=model,
                    model_code=code,
                    latency_ms=_latency(),
                    status="FAILED",
                    error_code=GatewayErrorCode.RATE_LIMITED,
                    error_msg=str(exc),
                )
                raise LLMClientError(
                    str(exc),
                    error_code=GatewayErrorCode.RATE_LIMITED,
                    status_code=429,
                ) from exc
            time.sleep(0.2)
            _wait_left -= 0.2
    try:
        text, usage, raw = _call_with_retry(
            model_cfg,
            prompt=prompt,
            system=system,
            history=history,
            json_mode=json_mode,
        )
    except LLMClientError as exc:
        error_code = exc.error_code
        status = "FAILED"
        record_usage(
            db,
            tenant_id=tenant_id,
            provider=provider,
            model=model,
            model_code=code,
            latency_ms=_latency(),
            status=status,
            error_code=error_code,
            error_msg=str(exc.message),
            input_price_per_mtok=in_price,
            output_price_per_mtok=out_price,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        error_code = GatewayErrorCode.UPSTREAM
        status = "FAILED"
        record_usage(
            db,
            tenant_id=tenant_id,
            provider=provider,
            model=model,
            model_code=code,
            latency_ms=_latency(),
            status=status,
            error_code=error_code,
            error_msg=str(exc),
        )
        raise LLMClientError(str(exc), error_code=error_code) from exc
    finally:
        limiter.release()

    # 5) 记账（token / 成本 / occupancy）
    record_usage(
        db,
        tenant_id=tenant_id,
        user_id=model_cfg.get("user_id"),
        task_id=task_id,
        step_id=step_id,
        ref_no=ref_no,
        provider=provider,
        model=model,
        model_code=code,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        input_price_per_mtok=in_price,
        output_price_per_mtok=out_price,
        latency_ms=_latency(),
        status="SUCCESS",
    )

    # 6) 写缓存
    if use_cache:
        llm_cache.set(
            db,
            tenant_id=tenant_id,
            provider=provider,
            model=model,
            messages=msgs,
            response_text=text,
            semantic_prompt=prompt if use_semantic_cache else None,
            namespace=cache_namespace,
        )

    return ChatCompletionResult(
        text=text,
        provider=provider,
        model=model,
        latency_ms=_latency(),
        cache_hit=False,
        usage=usage,
        cost=round(
            usage.prompt_tokens / 1e6 * in_price
            + usage.completion_tokens / 1e6 * out_price,
            6,
        ),
        raw=raw,
    )


def chat_completion_v2(
    model_cfg: dict[str, Any],
    *,
    prompt: str,
    system: str | None = None,
    history: list[dict[str, str]] | None = None,
    use_cache: bool = True,
    use_semantic_cache: bool = True,
    db: Any = None,
    task_id: int | None = None,
    step_id: int | None = None,
    tenant_id: int = 1,
    ref_no: str | None = None,
    json_mode: bool = False,
    cache_namespace: str | None = None,
) -> ChatCompletionResult:
    """网关统一入口：返回结构化结果。推荐新链路（Agent/多裁判/组合引擎）使用。"""
    return _gateway_pipeline(
        model_cfg,
        prompt=prompt,
        system=system,
        history=history,
        use_cache=use_cache,
        use_semantic_cache=use_semantic_cache,
        db=db,
        task_id=task_id,
        step_id=step_id,
        tenant_id=tenant_id,
        ref_no=ref_no,
        json_mode=json_mode,
        cache_namespace=cache_namespace,
    )


# ---------------------------------------------------------------- 兼容入口 --
def chat_completion(
    provider: str,
    base_url: str | None,
    model: str,
    api_key_env: str | None = None,
    explicit_key: str | None = None,
    api_key_enc: str | None = None,
    prompt: str = "",
    system: str | None = None,
    history: Iterable[dict[str, str]] | None = None,
    temperature: float = 0.4,
    max_tokens: int = 4096,
    timeout_sec: int = 60,
    use_cache: bool = True,
    db: Any = None,
    task_id: int | None = None,
    step_id: int | None = None,
    tenant_id: int = 1,
    ref_no: str | None = None,
    json_mode: bool = False,
    seed: int | None = None,
    cache_namespace: str | None = None,
) -> str:
    """【兼容层】旧签名保持不变，内部走统一网关链路。

    返回纯文本。任何错误以 LLMClientError 抛出（引擎层 engine_llm.llm_generate
    已 catch 后返回 None，行为与升级前一致）。
    """
    model_cfg: dict[str, Any] = {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key_env": api_key_env,
        "api_key_enc": api_key_enc,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout_sec": timeout_sec,
    }
    if seed is not None:
        model_cfg["seed"] = seed
    # 显式 key 优先级高于 env 变量名（兼容显式传 key 的调用方）
    if explicit_key:
        os.environ.setdefault(f"_EW_TMP_{api_key_env or 'KEY'}", explicit_key)
        model_cfg["api_key_env"] = f"_EW_TMP_{api_key_env or 'KEY'}"
    try:
        result = _gateway_pipeline(
            model_cfg,
            prompt=prompt,
            system=system,
            history=list(history) if history is not None else None,
            use_cache=use_cache,
            db=db,
            task_id=task_id,
            step_id=step_id,
            tenant_id=tenant_id,
            ref_no=ref_no,
            json_mode=json_mode,
            cache_namespace=cache_namespace,
        )
        return result.text
    finally:
        # 清理临时 env key，避免显式 key 残留在进程环境
        tmp_env = model_cfg.get("api_key_env")
        if tmp_env and tmp_env.startswith("_EW_TMP_"):
            os.environ.pop(tmp_env, None)


def embedding_completion(
    model_cfg: dict[str, Any], *, prompt: str
) -> list[float] | None:
    """计算 prompt 的 embedding 向量；失败返回 None（语义缓存静默降级）。"""
    try:
        url = effective_base_url(
            model_cfg.get("provider", "LOCAL"), model_cfg.get("base_url")
        )
        api_key = resolve_api_key(
            api_key_env=model_cfg.get("api_key_env"),
            api_key_enc=model_cfg.get("api_key_enc"),
        )
        client = OpenAI(
            base_url=url,
            api_key=api_key or "EMPTY",
            timeout=float(model_cfg.get("timeout_sec") or 30),
            max_retries=1,
        )
        resp = client.embeddings.create(
            model=model_cfg.get("model", ""), input=str(prompt)[:8000]
        )
        return list(resp.data[0].embedding)
    except Exception:  # noqa: BLE001
        return None


def test_connection(
    provider: str,
    base_url: str | None,
    model: str,
    api_key_env: str | None = None,
    explicit_key: str | None = None,
    api_key_enc: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 16,
    timeout_sec: int = 30,
) -> dict[str, Any]:
    """模型连通性测试：走真实 LLM 最小请求（不重试、不缓存、不记账）。

    返回 {"ok": bool, "error"?: str}。供 routers/business.py 连通性测试接口使用。
    """
    model_cfg: dict[str, Any] = {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key_env": api_key_env,
        "api_key_enc": api_key_enc,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout_sec": timeout_sec,
    }
    if explicit_key:
        os.environ.setdefault(f"_EW_TMP_{api_key_env or 'KEY'}", explicit_key)
        model_cfg["api_key_env"] = f"_EW_TMP_{api_key_env or 'KEY'}"
    try:
        text, usage, raw = _call_single(
            model_cfg, prompt="ping", system=None, history=None, json_mode=False
        )
        return {
            "ok": True,
            "reply": text[:100],
            "model": model,
            "prompt_tokens": usage.prompt_tokens,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("模型连通性测试失败: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        tmp_env = model_cfg.get("api_key_env")
        if tmp_env and tmp_env.startswith("_EW_TMP_"):
            os.environ.pop(tmp_env, None)


def metrics_snapshot() -> dict[str, Any]:
    """网关当前可观测快照：调用计数 / 平均延迟 / 缓存命中率 / 限流并发。"""
    from .rate_limiter import rate_limiter_registry
    from .llm_cache import llm_cache

    hit = llm_cache.hit_ratio()
    total = hit["hits"] + hit["misses"]
    return {
        "requests_total": total,
        "requests_hits": hit["hits"],
        "requests_misses": hit["misses"],
        "semantic_hits": hit["semantic_hits"],
        "cache_hit_ratio": hit["hit_ratio"],
        "active_limiter_entries": rate_limiter_registry.count(),
    }
