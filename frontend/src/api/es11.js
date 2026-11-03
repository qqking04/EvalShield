/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * SPDX-License-Identifier: BUSL-1.1
 * ES11 统一接口层（开发方案 §3，17 接口）。http 拦截器已解包 data，直接返回业务体。
 */
import http from './http'

// ---- G0 准备度 / 活动工作区（§3.1/§3.2）----
export const checkReadiness = (cfg) => http.post('/eval-runs/readiness', cfg)
// BUG-007（优化12）正解已落地：题库执行分支转后台异步（返回 run_id 即回，
// 响应 data.async=true），RunWorkspace 非终态轮询刷新；超时回退默认 60s。
export const createEvalRun = (cfg) => http.post('/eval-runs', cfg)
export const getDefectLoopBoard = (ids) => http.get('/defect-loop-board', { params: { ids: ids.join(',') } })
export const listRedteamCampaigns = (params) => http.get('/redteam/campaigns', { params })
export const getRunWorkspace = (runId) => http.get(`/eval-runs/${runId}/workspace`)
export const getRunItems = (runId, params) => http.get(`/eval-runs/${runId}/items`, { params })
export const setBaseline = (runId) => http.put(`/eval-runs/${runId}/baseline`)
export const compareRun = (runId, baselineRunId) =>
  http.get(`/eval-runs/${runId}/compare`, { params: { baseline_run_id: baselineRunId } })

// ---- 缺陷闭环（§3.4，G3）----
export const getDefectTimeline = (id) => http.get(`/defects/${id}/timeline`)
export const submitRemediation = (id, body) => http.post(`/defects/${id}/remediation`, body)
export const startRetest = (id, body) => http.post(`/defects/${id}/retest`, body)
export const verifyDefect = (id, body) => http.post(`/defects/${id}/verify`, body)
export const reopenDefect = (id, body) => http.post(`/defects/${id}/reopen`, body)
export const waiveDefect = (id, body) => http.post(`/defects/${id}/waive`, body)

// ---- Trace 回流（§3.5）----
export const promoteQuestion = (traceId, body) => http.post(`/traces/${traceId}/promote-question`, body)
export const traceToDefect = (traceId, body) => http.post(`/traces/${traceId}/create-defect`, body)
export const launchRegression = (traceId, body) => http.post(`/traces/${traceId}/launch-regression`, body)
export const getTraceLineage = (traceId) => http.get(`/traces/${traceId}/lineage`)

// ---- 报告交付（§3.6，G4）----
export const getDeliveryReadiness = (reportId) => http.get(`/reports/${reportId}/delivery-readiness`)
export const freezeConclusion = (reportId, body) => http.post(`/reports/${reportId}/freeze-conclusion`, body || {})
export const createDeliveryPackage = (runId) => http.post(`/reports/${runId}/delivery-package`)

// ---- 质量总览聚合（§3.7）----
export const getQualityOverview = (days = 30) => http.get('/dashboard/quality', { params: { days } })

// ---- Judge 治理与题库治理（§3.2 治理视图配套端点）----
export const getBankGovernance = (bankId) => http.get(`/question-banks/${bankId}/governance`)
export const getJudgeCalibration = (params) => http.get('/review/calibration', { params })

// ---- 复用既有端点（缺陷列表/详情、运行列表）----
export const listDefects = (params) => http.get('/defects', { params })
export const getDefect = (id) => http.get(`/defects/${id}`)
export const listRuns = (params) => http.get('/eval-runs', { params })

// ---- 优化12 M5 前端（方案 §10.3）：标准元信息 / 双轨覆盖矩阵 / 阈值核定 ----
export const getStandardsDimensions = () => http.get('/meta/standards')
export const getRunDimensionCoverage = (runId) => http.get(`/eval-runs/${runId}/dimension-coverage`)
export const calibrateThresholds = (body) => http.put('/standards/thresholds', body)
