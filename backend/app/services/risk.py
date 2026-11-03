# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""风险等级计算（自测测试 v2.0 BUG-012）。

判定规则（《自测测试v2.0修改方案.md》第 6 章）：
| 条件                       | 风险等级 (risk_level) |
|----------------------------|-----------------------|
| 阻断用例致后续未执行        | critical（报告头标注阻塞） |
| 存在"严重"失败（P0/CRITICAL/FATAL/严重/高） | high |
| 存在"高"失败（P1/HIGH）     | medium |
| 只存在"中/低"失败           | low |
| 失败用例数 = 0             | none（无风险项）       |

> 严重度枚举兼容中英文与 P0-P4：缺陷模型 severity 存 P0-P4，
> 历史/探测数据可能存 CRITICAL/HIGH/中/低 等，统一归一化后判定。
"""

from __future__ import annotations

from typing import Any

# 归一化：把各种严重度写法映射到内部档位
# 判定规则对照：严重/CRITICAL/P0 → high；高/HIGH/P1 → medium；中/低/P2-P4 → low
_SEV_CRITICAL = {"P0", "CRITICAL", "FATAL", "严重", "致命"}
_SEV_HIGH = {"P1", "HIGH", "高", "重大"}
_SEV_LOW = {"P2", "P3", "P4", "MEDIUM", "LOW", "中", "低", "一般", "轻微", "提示"}


def _norm_sev(raw: Any) -> str:
    """返回 'critical' / 'high' / 'low' / 'unknown'。"""
    s = str(raw or "").strip()
    if not s:
        return "unknown"
    su = s.upper()
    if su in {x.upper() for x in _SEV_CRITICAL} or s in _SEV_CRITICAL:
        return "critical"
    if su in {x.upper() for x in _SEV_HIGH} or s in _SEV_HIGH:
        return "high"
    if su in {x.upper() for x in _SEV_LOW} or s in _SEV_LOW:
        return "low"
    return "unknown"


def compute_risk_level(
    defects: list[dict[str, Any]],
    total: int,
    passed: int,
    blocked: bool = False,
) -> tuple[str, str]:
    """计算风险等级与判定依据。

    参数
    ----
    defects : 缺陷/失败项列表（每项可含 severity 字段）
    total   : 用例总数
    passed  : 通过数
    blocked : 是否存在阻断用例导致后续未执行

    返回
    ----
    (risk_level, risk_basis)
    risk_level ∈ {critical, high, medium, low, none}
    """
    failed = max(int(total or 0) - int(passed or 0), 0)

    # 阻断优先
    if blocked:
        return "critical", "存在阻断用例导致后续步骤未执行，判定为严重风险"

    # 无失败 → none
    if failed == 0 and not defects:
        rate = round((passed / total * 100), 2) if total else 100.0
        return "none", f"通过率 {rate}% 且无失败用例，判定为无风险项"

    # 按缺陷严重度归档
    buckets = {"critical": 0, "high": 0, "low": 0, "unknown": 0}
    for d in defects or []:
        sev = _norm_sev(d.get("severity") if isinstance(d, dict) else None)
        buckets[sev] = buckets.get(sev, 0) + 1

    if buckets["critical"] > 0:
        return "high", (
            f"存在 {buckets['critical']} 个严重级失败用例（P0/CRITICAL），判定为高风险"
        )
    if buckets["high"] > 0:
        return "medium", (
            f"存在 {buckets['high']} 个高级失败用例（P1/HIGH），判定为中风险"
        )
    if buckets["low"] > 0:
        return "low", (
            f"仅存在 {buckets['low']} 个中/低级失败用例，判定为低风险"
        )
    # 有失败但缺陷列表为空/严重度未知 → 按失败数兜底
    if failed > 0:
        return "medium", f"存在 {failed} 个失败用例（严重度未标注），保守判定为中风险"
    return "none", "无失败用例，判定为无风险项"
