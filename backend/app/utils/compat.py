# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""异步兼容工具：把阻塞调用卸载到线程池，避免冻结事件循环。"""
from __future__ import annotations

import asyncio
import subprocess
from typing import Sequence


async def run_cmd(
    cmd: Sequence[str], *, timeout: float, text: bool = True, **kwargs
) -> subprocess.CompletedProcess:
    """把阻塞式 subprocess.run 放到默认线程池，避免冻结事件循环。"""
    return await asyncio.to_thread(
        subprocess.run, list(cmd), timeout=timeout, text=text, **kwargs
    )
