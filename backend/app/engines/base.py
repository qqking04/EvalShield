# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""引擎基础接口：EngineContext / EngineResult / BaseEngine。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session


@dataclass
class EngineContext:
    """引擎执行上下文（由任务调度器组装）。"""

    task_id: int
    task_no: str
    step_id: int
    step_no: str
    project_id: int
    engine_code: str
    config: dict[str, Any] = field(default_factory=dict)
    db: Session | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    # ES9-P-10 预留字段，当前无任何引擎消费者；引擎不逐题执行题库题目。
    # 覆盖口径见「优化12.md」M0.2（双轨证据）。填充本字段需改 engines/ 内文件，受锁 1 约束。
    # 回归断言：tests 中 test_engine_context_questions_unused 钉死 engines/ 源码零本字段消费。
    questions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EngineResult:
    """引擎执行结果（统一结构，供阶段状态与报告组装）。"""

    status: str = "SUCCESS"  # SUCCESS / FAILED / SKIPPED
    summary: dict[str, Any] = field(default_factory=dict)
    report_payload: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    # ES9-P-01/P-13：实现真实度（real=真实执行 / rule=规则匹配 / simulated=模拟演示）。
    # 由 run_engine_step 统一回填 engine.fidelity，随结果落库供报告渲染角标。
    fidelity: str = ""

    @property
    def passed(self) -> int:
        return int(self.summary.get("passed", 0))

    @property
    def failed(self) -> int:
        return int(self.summary.get("failed", 0))

    @property
    def total(self) -> int:
        return int(self.summary.get("total", 0))

    @property
    def metrics(self) -> dict[str, Any]:
        """契约兼容层：从 summary 提炼指标，支持 result.metrics['p95_ms'] 等访问。

        实际引擎执行结果写入 summary；metrics 是扁平化提取的只读视图，
        同时兼容测试方案期望的 p95_ms / p99_ms / rps 等命名变体。
        """
        m: dict[str, Any] = {}
        # 直接拷贝 summary（多数指标如 p95 / rps / total 已在里面）
        m.update(self.summary)
        # 常见命名归一化：p95_ms ← summary['p95'] / summary['p95_ms']
        for k_src, k_dst in [("p95", "p95_ms"), ("p99", "p99_ms"), ("latency_p95", "p95_ms"),
                              ("latency_p99", "p99_ms"), ("avg_rps", "rps")]:
            if k_dst not in m and k_src in self.summary:
                m[k_dst] = self.summary[k_src]
        return m


class BaseEngine:
    """所有引擎的基类。

    子类约定：
    - engine_code / engine_name / category / engine_type 类属性必填。
    - 实现 execute(ctx: EngineContext) -> EngineResult。
    - 业务对象编号（case_no / step_no / report_no）由引擎内部通过 ctx.extra 传入的 no 生成器或工具方法生成。
    """

    engine_code: str = ""
    engine_name: str = ""
    engine_type: str = "AI"  # TRADITIONAL / AI / ENGINEERING
    category: str = ""  # UI/API/PERF/DATAFLOW/HALLUCINATION/...
    version: str = "1.0.0"
    description: str = ""
    # ES9-P-01/P-13：实现真实度（类属性=单一事实源，注册时由
    # sync_engine_fidelity 回写 test_engines.fidelity；取值 real/rule/simulated）。
    # 未显式标注的新引擎按 simulated 保守处理（结论不出具交付）。
    fidelity: str = "simulated"

    # 前端表单渲染 schema（可选）。
    # 形如: [{"key": "base_url", "label": "被测系统地址", "type": "text", "required": true}, ...]
    # 未定义时，前端 fallback 到本地 ENGINE_PARAMS 硬编码。
    params_schema: list[dict] | None = None

    def execute(
        self, ctx: EngineContext
    ) -> EngineResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def _timed(self, ctx: EngineContext) -> tuple[EngineResult, int]:
        start = time.perf_counter()
        result = self.execute(ctx)
        duration_ms = int((time.perf_counter() - start) * 1000)
        # 统一回填真实度，落库进 result_summary.fidelity / run_snapshot.fidelity
        if not result.fidelity:
            result.fidelity = self.fidelity
        if isinstance(result.summary, dict) and "fidelity" not in result.summary:
            result.summary["fidelity"] = result.fidelity
        return result, duration_ms


def run_engine_step(engine: BaseEngine, ctx: EngineContext) -> tuple[EngineResult, int]:
    """执行单个引擎步骤并返回结果与耗时（毫秒）。"""
    return engine._timed(ctx)  # noqa: SLF001


def make_http_client(target_url: str, **kwargs: Any):
    """构造引擎用 httpx 客户端。

    被测系统常为回环地址（localhost/127.x），而 Windows 注册表级系统代理会被
    httpx trust_env 读取且不识别代理绕过表，导致探测自身时经代理超时。
    对回环/私有网段目标禁用系统代理，其余目标保持默认行为。
    """
    import httpx
    from urllib.parse import urlparse

    host = (urlparse(target_url or "").hostname or "").lower()
    loopback = host in ("localhost", "::1") or host.startswith("127.")
    if loopback:
        kwargs.setdefault("trust_env", False)
    return httpx.Client(**kwargs)


def resolve_dataset_groups(case: Any, db: Session | None) -> list[dict[str, Any]]:
    """数据驱动兜底：用例归属数据集且有 data_rows 时，按数据行逐行展开。

    优先级：用例显式 test_data > 数据集 data_rows > 默认单分组。
    返回形如 [{"case": "数据行1", "params": {"列名": 值, ...}}, ...]；
    无归属数据集或数据行为空时返回空列表，由引擎回退默认分组。
    任何异常不阻断引擎执行（优雅降级）。
    """
    if not case:
        return []
    ds_id = getattr(case, "dataset_id", None)
    if ds_id is None and isinstance(case, dict):
        ds_id = case.get("dataset_id")
    if not ds_id or db is None:
        return []
    try:
        from ..models import TestDataset

        ds = db.get(TestDataset, int(ds_id))
        rows = (ds.data_rows if ds and isinstance(ds.data_rows, list) else []) or []
        return [
            {"case": f"数据行{idx + 1}", "params": dict(row)}
            for idx, row in enumerate(rows)
            if isinstance(row, dict) and row
        ]
    except Exception:  # noqa: BLE001
        return []
