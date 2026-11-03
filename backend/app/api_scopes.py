# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES10-P-04：API Key scope 注册表。

命名：资源:动作。scope 仅约束 API-Key 通道；JWT 会话走 RBAC
（require_permission），两套语义不混用。
NULL / 空数组 = 旧 Key 全量兼容（见 deps.require_scope）。
"""

SCOPES = {
    "traces:read": "查询链路追踪数据",
    "traces:write": "上报链路追踪数据",
    "cases:read": "查询用例资产（预留，尚未开放 API-Key 通道）",
    "cases:write": "写入用例资产（预留，尚未开放 API-Key 通道）",
    "eval:read": "查询评测结果（预留，尚未开放 API-Key 通道）",
    "eval:run": "发起评测（预留，尚未开放 API-Key 通道）",
}

# 已实际挂载 require_scope 的端点对照（评审与解冻收紧时的账本）
ENFORCEMENT = {
    "POST /api/traces/ingest": "traces:write",
    "GET /api/traces": "traces:read",
    "GET /api/traces/{id}": "traces:read",
}
