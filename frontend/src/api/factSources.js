/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES9-P-12（§4.3.3）：事实源（知识源）配置 API 封装
// GET 列表 auth 字段返回 sk-****abcd 掩码；编辑留空表示不修改凭据。
import http from './http'

export const listFactSources = (params = {}) =>
  http.get('/fact-sources', { params })

export const createFactSource = (body) =>
  http.post('/fact-sources', body)

export const updateFactSource = (id, body) =>
  http.put(`/fact-sources/${id}`, body)

export const deleteFactSource = (id) =>
  http.delete(`/fact-sources/${id}`)

// 连通性测试：返回 { ok, status, latency_ms?, error? }
// status 三态：REACHABLE 可达 / TIMEOUT 超时 / UNCONFIGURED 未配置
export const testFactSource = (id) =>
  http.post(`/fact-sources/${id}/test`)
