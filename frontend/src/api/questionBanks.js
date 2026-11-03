/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import http, { downloadBlob } from './http'

// ES9-P-09（§4.1.2 路由表）：题库与覆盖度 API 封装
export const listBanks = (params) => http.get('/question-banks', { params })
export const createBank = (payload) => http.post('/question-banks', payload)
export const getBank = (id) => http.get(`/question-banks/${id}`)
export const updateBank = (id, payload) => http.patch(`/question-banks/${id}`, payload)
export const deleteBank = (id) => http.delete(`/question-banks/${id}`)

export const listQuestions = (id, params) => http.get(`/question-banks/${id}/questions`, { params })
export const createQuestion = (id, payload) => http.post(`/question-banks/${id}/questions`, payload)
export const updateQuestion = (qid, payload) => http.patch(`/questions/${qid}`, payload)
export const deleteQuestion = (qid) => http.delete(`/questions/${qid}`)

export const createImport = (id, formData, config) =>
  http.post(`/question-banks/${id}/imports`, formData, config)
export const getImportJob = (jobId, config) => http.get(`/question-imports/${jobId}`, config)

export const getCoverage = (id, params) => http.get(`/question-banks/${id}/coverage`, { params })
// ES11-R1：题库治理视图聚合（优化11.md §17.2，只读派生）
export const getGovernance = (id) => http.get(`/question-banks/${id}/governance`)
export const exportCoverage = (id) =>
  downloadBlob(`/question-banks/${id}/coverage/export`, undefined, `coverage-${id}.csv`)
