# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""CSV 导出安全工具（SEC-04 公式注入防护）。

电子表格（Excel / WPS / LibreOffice）打开 CSV 时，会把以 ``=`` ``+`` ``-``
``@`` 以及制表符 / 回车开头的单元格当作公式求值，形成 CSV injection 攻击面。
导出用户可控文本前统一用 :func:`esc_csv` 转义。
"""
from __future__ import annotations

# 可能触发公式解析的前导字符
_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def esc_csv(value):
    """以危险字符开头的字符串前加单引号，其余原样返回。"""
    if isinstance(value, str) and value[:1] in _DANGEROUS_PREFIXES:
        return "'" + value
    return value


__all__ = ["esc_csv"]
