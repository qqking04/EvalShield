# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""并发批处理判定管道（§4.4 / T9）：限流 + 缓存 + 退避重试 + 顺序保持 + 成本估算。

- batch_llm_judge：ThreadPoolExecutor 并行执行 llm_generate_json 任务列表，
  结果与 tasks 等长且顺序一致，失败位返回 None（不抛异常）。
- estimate_cost：按 model_configs 单价估算 LLM 调用成本（元），价格缺失返回 None。
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .engine_llm import llm_generate_json
from .llm_cache import LLMCache, llm_cache, normalize_messages
from .rate_limiter import rate_limiter_registry, retry_with_backoff

logger = logging.getLogger("evalshield.engine_batch")


def batch_llm_judge(
    tasks: list[dict],
    *,
    concurrency: int = 4,
    limiter_key: str,
    tenant_id: int = 1,
    use_cache: bool = False,
    db=None,
    model: dict | None = None,
    cache_namespace: str | None = None,
) -> list[Any]:
    """并行执行 llm_generate_json 任务列表。

    tasks 元素为 dict：{"prompt": str, "system": str?}（其余键透传忽略）。
    - 每次真实调用前 limiter.acquire()（finally release）；
      RateLimitReached 由 retry_with_backoff 指数退避重试（最多 3 次尝试）；
    - use_cache=True 时先查 LLMCache.get，命中则跳过真实调用并 json.loads 返回；
    - 失败位返回 None；返回列表与 tasks 等长、顺序一致。
    """
    if not tasks:
        return []
    conc = max(1, int(concurrency or 1))
    # 新建限流器时给足默认容量（DB 规则已由 load_rules_from_db 预注册则复用）；
    # 并发槽取 max(conc, 4)：同一 limiter_key 可能被多个引擎 worker 线程共享
    # （如 MULTI_TURN 会话级并行各自 batch=1），槽位过小会互相撞限流。
    from .rate_limiter import DEFAULT_CONCURRENCY
    limiter = rate_limiter_registry.get(
        limiter_key,
        qps=max(20.0, conc * 10.0),
        concurrency=max(conc, DEFAULT_CONCURRENCY),
    )
    provider = (model or {}).get("provider") or ""
    model_name = (model or {}).get("model") or ""

    def _run_one(task: dict) -> Any:
        prompt = task.get("prompt") or ""
        system = task.get("system")
        if use_cache:
            messages = normalize_messages(prompt, system)
            hit = llm_cache.get(
                db,
                tenant_id=tenant_id,
                provider=provider,
                model=model_name,
                messages=messages,
                namespace=cache_namespace,
            )
            if hit is not None:
                # 兼容 (response_text, semantic) 元组与纯字符串两种返回
                text = hit[0] if isinstance(hit, tuple) else hit
                try:
                    return json.loads(text)
                except (TypeError, ValueError):
                    return None

        def _attempt():
            limiter.acquire()
            try:
                return llm_generate_json(
                    model, prompt=prompt, system=system,
                    cache_namespace=cache_namespace,
                )
            finally:
                limiter.release()

        try:
            return retry_with_backoff(_attempt, max_retries=2, base_delay=0.05)()
        except Exception as exc:  # noqa: BLE001 - 失败位 None，不阻断批次
            logger.warning("batch_llm_judge 任务失败: %s", exc)
            return None

    with ThreadPoolExecutor(max_workers=min(conc, len(tasks))) as pool:
        return list(pool.map(_run_one, tasks))


def judge_with_consistency(
    fn,
    *,
    n: int = 1,
    key: str = "severity",
    concurrency: int = 4,
    **fn_kwargs,
) -> tuple[Any, str | None]:
    """§4.6 self_consistency_n：判定类调用采样 N 次取多数。

    fn 为无副作用判定函数（如幻觉 _judge_item），返回 dict 且含 key 字段；
    n<=1 时单次直调（零开销，默认关闭）；n>1 时 ThreadPool 并行采样 n 次，
    按 key 多数表决取对应结果，返回 (多数结果, "8/10 多数一致" 文本)。
    采样失败位忽略；全部失败返回 (None, None)。
    """
    n = max(1, int(n or 1))
    if n == 1:
        return fn(**fn_kwargs), None

    def _one(_i: int):
        try:
            return fn(**fn_kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("judge_with_consistency 采样失败: %s", exc)
            return None

    with ThreadPoolExecutor(max_workers=min(max(1, concurrency), n)) as pool:
        votes = list(pool.map(_one, range(n)))
    valid = [v for v in votes if isinstance(v, dict)]
    if not valid:
        return None, None
    counts: dict[Any, int] = {}
    for v in valid:
        k = v.get(key)
        counts[k] = counts.get(k, 0) + 1
    majority_key = max(counts, key=lambda c: counts[c])
    majority_result = next(v for v in valid if v.get(key) == majority_key)
    agree = counts[majority_key]
    consistency = f"{agree}/{n} 多数一致"
    return majority_result, consistency


def estimate_cost(
    db,
    model_code: str | None,
    calls: int,
    avg_in_tok: int,
    avg_out_tok: int,
) -> float | None:
    """按 ModelConfig.input/output_price_per_mtok 估算总成本（元）。

    calls × (avg_in_tok×输入单价 + avg_out_tok×输出单价) / 1e6；
    单价缺失或为 0 → 返回 None（前端显示「未配置单价」）。
    """
    if db is None or not model_code or not calls:
        return None
    from ..models import ModelConfig

    row = (
        db.query(ModelConfig)
        .filter(
            ModelConfig.code == model_code,
            ModelConfig.deleted_at.is_(None),
        )
        .first()
    )
    if row is None:
        return None
    in_p = float(row.input_price_per_mtok or 0)
    out_p = float(row.output_price_per_mtok or 0)
    if in_p <= 0 or out_p <= 0:
        return None
    return round(int(calls) * (int(avg_in_tok) * in_p + int(avg_out_tok) * out_p) / 1e6, 6)
