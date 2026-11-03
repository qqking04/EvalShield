# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
# backend/app/services/rate_limiter.py
"""限流器：内存令牌桶 + Redis Lua 令牌桶 + 注册表 + 指数退避重试。

- 默认内存版（单进程精确）；REDIS_URL 可用时全进程共享 Redis 版。
- 规则来源：DB gateway_rate_limits 表（启动/热加载）；未配置时用环境默认值。
- 429 语义：RateLimitReached 异常，网关编排层捕捉后指数退避重试（max 2）。
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from typing import Any

logger = logging.getLogger("evalshield.rate_limiter")

DEFAULT_QPS: float = float(os.getenv("GATEWAY_MODEL_QPS", "2"))
DEFAULT_CONCURRENCY: int = int(os.getenv("GATEWAY_MODEL_CONCURRENCY", "4"))
TENANT_PER_MINUTE: int = int(os.getenv("GATEWAY_REQUEST_LIMIT_PER_MIN", "60"))
REDIS_URL: str | None = os.getenv("REDIS_URL") or None


class RateLimitReached(Exception):
    """限流拒绝。retry_after_sec 供调用方构造 Retry-After 头。"""

    def __init__(self, key: str, retry_after_sec: float = 1.0) -> None:
        super().__init__(f"限流触发: {key}")
        self.key = key
        self.retry_after_sec = retry_after_sec


# ------------------------------------------------------------------ 内存桶 --
class TokenBucket:
    """进程内令牌桶（qps 速率 + burst 容量）。线程安全。"""

    def __init__(self, key: str, qps: float, burst: int) -> None:
        self.key = key
        self.qps = max(qps, 0.0)
        self.burst = max(int(burst), 1)
        self._tokens = float(self.burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(
                float(self.burst),
                self._tokens + (now - self._last) * self.qps,
            )
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


class InMemoryLimiter:
    """qps 桶 + 并发槽（进程内）。"""

    def __init__(self, key: str, qps: float, concurrency: int) -> None:
        self.key = key
        self.bucket = TokenBucket(key, qps, burst=max(int(qps * 2), 1))
        self.concurrency = max(int(concurrency), 1)
        self._slots = 0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        if not self.bucket.try_acquire():
            raise RateLimitReached(
                self.key, retry_after_sec=1.0 / max(self.bucket.qps, 1e-6)
            )
        with self._lock:
            if self._slots >= self.concurrency:
                raise RateLimitReached(self.key, retry_after_sec=0.2)
            self._slots += 1

    def release(self) -> None:
        with self._lock:
            self._slots = max(self._slots - 1, 0)


# ----------------------------------------------------------------- Redis 版 --
class RedisLimiter:
    """Redis Lua 令牌桶 + 并发计数（跨进程共享）。

    keys: rate:{key}:v / rate:{key}:t / rate:{key}:s（并发计数，DECR 归还）。
    """

    _LUA_ACQUIRE = """
local v = tonumber(redis.call('GET', KEYS[1]) or '0')
local t = tonumber(redis.call('GET', KEYS[2]) or ARGV[3])
local now = tonumber(ARGV[3])
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local tokens = math.min(burst, v + (now - t) * rate)
if tokens >= 1 then
    redis.call('SET', KEYS[1], tokens - 1)
    redis.call('SET', KEYS[2], now)
    local slots = tonumber(redis.call('GET', KEYS[3]) or '0')
    if slots >= tonumber(ARGV[4]) then
        return 0
    end
    redis.call('INCR', KEYS[3])
    redis.call('EXPIRE', KEYS[3], 60)
    return 1
end
return 0
"""

    def __init__(self, key: str, qps: float, concurrency: int, redis_client) -> None:
        self.key = key
        self.qps = max(qps, 0.0)
        self.concurrency = max(int(concurrency), 1)
        self._r = redis_client
        self._rkey_v = f"rate:{key}:v"
        self._rkey_t = f"rate:{key}:t"
        self._rkey_s = f"rate:{key}:s"
        self._script = self._r.register_script(self._LUA_ACQUIRE)

    def acquire(self) -> None:
        ok = self._script(
            keys=[self._rkey_v, self._rkey_t, self._rkey_s],
            args=[
                self.qps / 1000.0,
                max(self.qps * 2, 1),
                int(time.time() * 1000),
                self.concurrency,
            ],
        )
        if not ok:
            raise RateLimitReached(self.key, retry_after_sec=1.0 / max(self.qps, 1e-6))

    def release(self) -> None:
        try:
            self._r.decr(self._rkey_s)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- 注册表 ----
class RateLimiterRegistry:
    """限流器注册表：按 rule_key 缓存 Limiter，支持 DB 规则热加载。单例。"""

    def __init__(self) -> None:
        self._limiters: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._redis_client = None
        if REDIS_URL:
            try:
                import redis

                self._redis_client = redis.from_url(REDIS_URL, decode_responses=True)
                logger.info("限流器使用 Redis 模式：%s", REDIS_URL)
            except Exception:  # noqa: BLE001
                logger.warning("Redis 不可用，降级为进程内内存令牌桶")
                self._redis_client = None

    def get(
        self, key: str, qps: float | None = None, concurrency: int | None = None
    ) -> Any:
        with self._lock:
            lim = self._limiters.get(key)
            if lim is None:
                q = DEFAULT_QPS if qps is None else qps
                c = DEFAULT_CONCURRENCY if concurrency is None else concurrency
                if self._redis_client is not None:
                    lim = RedisLimiter(key, q, c, self._redis_client)
                else:
                    lim = InMemoryLimiter(key, q, c)
                self._limiters[key] = lim
            return lim

    def load_rules_from_db(self, db, *, tenant_id: int = 1) -> int:
        """从 gateway_rate_limits 加载规则（模型级）。返回加载条数。"""
        from ..models import GatewayRateLimit

        loaded = 0
        try:
            rows = (
                db.query(GatewayRateLimit)
                .filter(
                    GatewayRateLimit.tenant_id == tenant_id,
                    GatewayRateLimit.scope == "MODEL",
                    GatewayRateLimit.enabled.is_(True),
                    GatewayRateLimit.deleted_at.is_(None),
                )
                .all()
            )
            with self._lock:
                for r in rows:
                    if r.qps <= 0 and r.concurrency <= 0:
                        continue
                    self._limiters[r.scope_key] = self._build(
                        r.scope_key, r.qps, r.concurrency
                    )
                    loaded += 1
        except Exception:  # noqa: BLE001
            logger.exception("加载限流规则失败（继续使用默认参数）")
        return loaded

    def _build(self, key: str, qps: float, concurrency: int) -> Any:
        if self._redis_client is not None:
            return RedisLimiter(key, qps, concurrency, self._redis_client)
        return InMemoryLimiter(key, qps, concurrency)

    def snapshot(self) -> list[dict[str, Any]]:
        return [{"key": k, "type": type(v).__name__} for k, v in self._limiters.items()]

    def count(self) -> int:
        return len(self._limiters)


rate_limiter_registry = RateLimiterRegistry()


# ---------------------------------------------------------- 退避重试封装 ----
def retry_with_backoff(
    fn,
    *,
    max_retries: int = 2,
    base_delay: float = 0.5,
    retry_on: tuple[type[Exception], ...] = (RateLimitReached,),
    on_retry: Any = None,
):
    """指数退避重试装饰器：捕获可重试异常后 sleep 再调用，最多 max_retries 次。

    用法：
        @retry_with_backoff(max_retries=2)
        def call_llm(): ...
    """

    def wrapper(*args, **kwargs):
        attempt = 0
        while True:
            try:
                return fn(*args, **kwargs)
            except retry_on as exc:
                attempt += 1
                if attempt > max_retries:
                    raise
                delay = min(base_delay * (2**attempt), 4.0) + random.uniform(0, 0.2)
                if on_retry is not None:
                    on_retry(exc, attempt, delay)
                time.sleep(delay)

    return wrapper
