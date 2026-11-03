# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""测试引擎包：传统 4 类 + AI 6 类 + 工程化 3 类，共 13 类引擎。

统一引擎接口：engine.execute(context) -> EngineResult
EngineResult: {status, summary, report_payload, artifacts, error}
引擎由 EngineRegistry 注册，TestTask 按 engines 列表顺序调度执行。
"""

from __future__ import annotations

from .registry import EngineRegistry, engine_registry
from .base import BaseEngine, EngineContext, EngineResult, run_engine_step

__all__ = [
    "EngineRegistry",
    "engine_registry",
    "BaseEngine",
    "EngineContext",
    "EngineResult",
    "run_engine_step",
]
