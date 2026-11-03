# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""统一日志配置。"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    # BUG-6：uvicorn 默认 handler 只覆盖 uvicorn.error/access 的 console 输出，
    # 其 logger propagate=False 导致应用 logger（evalshield.*）在 create_app 期
    # （早于 uvicorn 配置 dictConfig）的日志丢失。统一传播到 root 保证
    # commercial-absent 等启动关键日志必达控制台。
    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(_name).propagate = True
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
