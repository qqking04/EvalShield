# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES9-P-14：业务指标定义与 /metrics 暴露。

设计要点（优化9详细设计方案 §6 P-14）：
- prometheus_client / prometheus-fastapi-instrumentator 为可选依赖：
  try-import 成功 → METRICS_AVAILABLE=True，正常注册指标；
  缺失 → 全部采集函数 no-op fallback，业务代码零感知（不抛异常、不建 Registry）。
- instrument_app() 由 main.create_app 调用：仅当 METRICS_ENABLED 且依赖可用时挂载，
  /metrics 端点按 METRICS_TOKEN 做 Bearer 校验（令牌为空则不校验，仅限受信内网）。

指标清单：
- eval_run_items_total{verdict,split}      评估条目计数（按判定/数据集切分）
- sandbox_queue_depth                      沙箱待执行队列深度（gauge）
- sandbox_exec_seconds                     沙箱单次执行耗时直方图
- llm_calls_total{model}                   LLM 调用次数
- llm_tokens_total{model,kind}             LLM token 消耗（kind=prompt|completion）
- evidence_dir_bytes                       证据目录占用字节（gauge，供磁盘水位面板）
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

METRICS_AVAILABLE: bool = False
_INSTRUMENTATOR_AVAILABLE: bool = False

try:  # 可选依赖：缺失时 no-op fallback
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        multiprocess,
    )

    METRICS_AVAILABLE = True
except ImportError:  # pragma: no cover - 依赖缺失环境
    generate_latest = None  # type: ignore[assignment]
    multiprocess = None  # type: ignore[assignment]

try:
    from prometheus_fastapi_instrumentator import Instrumentator

    _INSTRUMENTATOR_AVAILABLE = True
except ImportError:  # pragma: no cover - 依赖缺失环境
    Instrumentator = None  # type: ignore[assignment, misc]


# ---------------------------------------------------------------------------
# 指标定义（prometheus_client 缺失时全部为 None，采集函数自动 no-op）
# ---------------------------------------------------------------------------

if METRICS_AVAILABLE:
    EVAL_RUN_ITEMS_TOTAL = Counter(
        "evalshield_eval_run_items_total",
        "评估条目累计数（按判定结果与数据集切分）",
        ["verdict", "split"],
    )
    SANDBOX_QUEUE_DEPTH = Gauge(
        "evalshield_sandbox_queue_depth",
        "沙箱待执行队列深度",
    )
    SANDBOX_EXEC_SECONDS = Histogram(
        "evalshield_sandbox_exec_seconds",
        "沙箱单次执行耗时（秒）",
        buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1800),
    )
    LLM_CALLS_TOTAL = Counter(
        "evalshield_llm_calls_total",
        "LLM 网关调用累计次数",
        ["model"],
    )
    LLM_TOKENS_TOTAL = Counter(
        "evalshield_llm_tokens_total",
        "LLM token 累计消耗（kind=prompt|completion）",
        ["model", "kind"],
    )
    EVIDENCE_DIR_BYTES = Gauge(
        "evalshield_evidence_dir_bytes",
        "证据目录（EVIDENCE_DIR）占用字节数",
    )
else:  # no-op fallback：占位对象，任何读写调用都被安全吸收
    class _Noop:
        def labels(self, *_a: Any, **_k: Any) -> "_Noop":
            return self

        def inc(self, *_a: Any, **_k: Any) -> None:
            pass

        def dec(self, *_a: Any, **_k: Any) -> None:
            pass

        def set(self, *_a: Any, **_k: Any) -> None:
            pass

        def observe(self, *_a: Any, **_k: Any) -> None:
            pass

    EVAL_RUN_ITEMS_TOTAL = _Noop()  # type: ignore[assignment]
    SANDBOX_QUEUE_DEPTH = _Noop()  # type: ignore[assignment]
    SANDBOX_EXEC_SECONDS = _Noop()  # type: ignore[assignment]
    LLM_CALLS_TOTAL = _Noop()  # type: ignore[assignment]
    LLM_TOKENS_TOTAL = _Noop()  # type: ignore[assignment]
    EVIDENCE_DIR_BYTES = _Noop()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 便捷采集入口（业务侧统一调用，避免直接 import prometheus 对象散落各处）
# ---------------------------------------------------------------------------

def record_eval_item(verdict: str, split: str) -> None:
    """评估条目完成时调用：verdict=PASS/FAIL/...，split=train/holdout/..."""
    EVAL_RUN_ITEMS_TOTAL.labels(verdict=verdict or "unknown", split=split or "unknown").inc()


def record_llm_call(model: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    """LLM 网关单次调用结束（无论成败）时调用。"""
    key = model or "unknown"
    LLM_CALLS_TOTAL.labels(model=key).inc()
    if prompt_tokens:
        LLM_TOKENS_TOTAL.labels(model=key, kind="prompt").inc(prompt_tokens)
    if completion_tokens:
        LLM_TOKENS_TOTAL.labels(model=key, kind="completion").inc(completion_tokens)


def record_sandbox_exec(seconds: float) -> None:
    """沙箱一次执行完成时调用（秒）。"""
    SANDBOX_EXEC_SECONDS.observe(max(0.0, float(seconds)))


def set_sandbox_queue_depth(depth: int) -> None:
    """调度器周期刷新沙箱队列深度。"""
    SANDBOX_QUEUE_DEPTH.set(max(0, int(depth)))


def set_evidence_dir_bytes(total_bytes: int) -> None:
    """证据目录体积（磁盘水位告警数据源）。"""
    EVIDENCE_DIR_BYTES.set(max(0, int(total_bytes)))


# ---------------------------------------------------------------------------
# FastAPI 挂载
# ---------------------------------------------------------------------------

def instrument_app(app: Any) -> bool:
    """按开关挂载 prometheus-fastapi-instrumentator（HTTP 指标 + /metrics）。

    返回是否实际挂载。METRICS_ENABLED=false 或依赖缺失时静默跳过。
    /metrics 加 Bearer METRICS_TOKEN 校验由调用方通过包装 route 实现——
    instrumentator 的 /metrics 端点无法直接加依赖，这里用中间层做最小拦截：
    仅拦截 GET /metrics 未授权请求，返回 401 统一信封。
    """
    if not METRICS_AVAILABLE or not _INSTRUMENTATOR_AVAILABLE:
        logger.info("metrics: prometheus deps absent, skip instrumentation")
        return False
    from ..config import settings

    if not settings.METRICS_ENABLED:
        logger.info("metrics: METRICS_ENABLED=false, skip instrumentation")
        return False

    token = settings.METRICS_TOKEN
    expected = f"Bearer {token}" if token else None

    @app.middleware("http")
    async def metrics_auth_middleware(request, call_next):  # noqa: ANN001
        if request.url.path == "/metrics" and expected is not None:
            if request.headers.get("Authorization", "") != expected:
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=401,
                    content={"code": "ES-METRICS-UNAUTHORIZED", "message": "metrics token invalid", "data": None},
                )
        return await call_next(request)

    Instrumentator(
        should_group_status_codes=True,
        should_respect_env_var=False,
        excluded_handlers=["/metrics", "/api/healthz", "/api/readyz"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    logger.info("metrics: instrumentator mounted at /metrics (auth=%s)", "token" if token else "open")
    return True


def render_metrics() -> bytes:
    """当前默认 Registry 的 exposition 文本（测试/备用出口用）。"""
    if not METRICS_AVAILABLE or generate_latest is None:
        return b""
    return generate_latest()
