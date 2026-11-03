/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import http from './http'
import axios from 'axios'

// ES9 UAT 验收报告（后端 /api/projects/{id}/uat-reports，响应经 http 拦截器解包 data）
// opts: { criteriaOverride, contractNo, defectDisposals } —— 覆写参数 JSON 串化走 query，后端重算口径与 create 一致
export const uatCandidates = (projectId, taskIds, opts = {}) => {
  const params = { task_ids: taskIds.join(',') }
  if (opts.criteriaOverride) params.criteria_override = JSON.stringify(opts.criteriaOverride)
  if (opts.contractNo) params.contract_no = opts.contractNo
  if (opts.defectDisposals) params.defect_disposals = JSON.stringify(opts.defectDisposals)
  return http.get(`/projects/${projectId}/uat-reports/candidates`, { params })
}
export const createUat = (projectId, body) => http.post(`/projects/${projectId}/uat-reports`, body)
export const listUat = (projectId, params) => http.get(`/projects/${projectId}/uat-reports`, { params })
// 跨项目 UAT 汇总（推荐3）：GET /api/uat-reports?project_id=&status=&page=&page_size=
export const listAllUat = (params) => http.get('/uat-reports', { params })
export const getUat = (projectId, id) => http.get(`/projects/${projectId}/uat-reports/${id}`)
export const signUat = (projectId, id, body) => http.post(`/projects/${projectId}/uat-reports/${id}/sign`, body)
export const rejectUat = (projectId, id, body) => http.post(`/projects/${projectId}/uat-reports/${id}/reject`, body)
export const resampleUat = (projectId, id, body) => http.post(`/projects/${projectId}/uat-reports/${id}/resample`, body)
export const shareUat = (projectId, id) => http.post(`/projects/${projectId}/uat-reports/${id}/share`)

// 导出：blob 下载（后端 Content-Disposition 给文件名，前端自拼装）
export const exportUat = (projectId, id, format) =>
  http.get(`/projects/${projectId}/uat-reports/${id}/export`, {
    params: { format },
    responseType: 'blob',
    timeout: 120000,
  })

// 免登录客户签署通道（ShareReport.jsx 同款独立实例，不带鉴权拦截器）
export const pubUat = axios.create({ baseURL: '/api', timeout: 30000 })
export const publicGetUat = (token) => pubUat.get(`/public/uat-sign/${token}/report`, { validateStatus: () => true })
export const publicSignUat = (token, body) => pubUat.post(`/public/uat-sign/${token}`, body, { validateStatus: () => true })
