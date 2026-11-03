/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import axios from 'axios'
import { message } from 'antd'
import { showEditionLimitModal } from '../components/EditionLimitCard'

// ES9-P-02：超限错误码前缀（后端 limits.py 单一事实源，HTTP 403 + 结构化 detail）
const isLimitError = (code) => typeof code === 'string' && code.startsWith('ES-LIMIT-')

// axios 实例：统一 baseURL、令牌注入、错误提示
const http = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('es_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        const msg = body.message || '请求失败'
        // ES9-P-02：超限错误不弹 message，改弹升级引导卡
        if (isLimitError(body.code)) {
          showEditionLimitModal({ code: body.code, message: msg, detail: body.detail })
        } else {
          message.error(msg)
        }
        const err = new Error(msg)
        err.code = body.code
        return Promise.reject(err)
      }
      return body.data
    }
    return body
  },
  (error) => {
    const resp = error.response
    // 调用方显式声明静默探测（如 license 能力探测）→ 失败不弹全局 toast，由调用方降级处理
    if (error.config?.silent) {
      return Promise.reject(error)
    }
    let msg = '网络请求失败'
    if (resp) {
      if (resp.status === 401) {
        const reqUrl = error.config?.url || ''
        // 登录/注册/SSO 等免认证入口的 401（如"用户名或密码错误"）不是会话过期：
        // 透出后端文案，不清 token、不重定向，避免刚登录即弹"登录已过期"
        const isAuthEntry = /^\/auth\/(login|register|sso|forgot-password|reset-password)/.test(reqUrl)
        if (isAuthEntry) {
          msg = resp.data?.message || '账号或密码错误'
        } else {
          localStorage.removeItem('es_token')
          localStorage.removeItem('es_refresh')
          // 已在登录页：本就没有有效会话，静默失败即可（否则一打开登录页就弹过期提示）
          if (window.location.pathname.startsWith('/login')) {
            const silentErr = new Error(resp.data?.message || '未登录')
            silentErr.code = resp.data?.code
            return Promise.reject(silentErr)
          }
          msg = '登录已过期，请重新登录'
          window.location.href = '/login'
        }
      } else if (resp.status === 403) {
        // 优化7 T4：半态令牌（首登未改密）→ 跳强制改密页；不清 token（改密页要用）
        if (resp.data?.code === 'ES-AUTH-PWD-REQUIRED') {
          if (!window.location.pathname.startsWith('/force-change-password')) {
            window.location.href = '/force-change-password'
          }
          const pwdErr = new Error(resp.data?.message || '首次登录必须修改初始密码')
          pwdErr.code = 'ES-AUTH-PWD-REQUIRED'
          return Promise.reject(pwdErr)
        }
        // ES9-P-02：403 + ES-LIMIT-* → 升级引导卡（不 message.error）
        if (isLimitError(resp.data?.code)) {
          showEditionLimitModal({ code: resp.data.code, message: resp.data?.message, detail: resp.data?.detail })
          const limitErr = new Error(resp.data?.message || '超出社区版上限')
          limitErr.code = resp.data.code
          return Promise.reject(limitErr)
        }
        msg = resp.data?.message || '无权访问该资源'
      } else {
        msg = resp.data?.message || `请求失败(${resp.status})`
      }
    }
    message.error(msg)
    return Promise.reject(new Error(msg))
  },
)

// ES9-P-08（§3.5.3）：导出下载统一封装。
// 先以 JSON 形态探测（responseType blob 下错误体也是 Blob，需回读文本），
// 超限/无权限等标准错误走拦截器渲染；确认成功才触发浏览器下载。
async function probeBlobError(blob) {
  if (!blob || blob.type === '') return null
  if (!/json/i.test(blob.type)) return null
  try {
    const text = await blob.text()
    const body = JSON.parse(text)
    return body && typeof body === 'object' && 'code' in body && body.code !== 0 ? body : null
  } catch {
    return null
  }
}

export async function downloadBlob(url, params, filename) {
  const resp = await http.request({ url, method: 'get', params, responseType: 'blob' })
  const blob = resp.data
  const errBody = await probeBlobError(blob)
  if (errBody) {
    if (isLimitError(errBody.code)) {
      showEditionLimitModal({ code: errBody.code, message: errBody.message, detail: errBody.detail })
    } else {
      message.error(errBody.message || '导出失败')
    }
    const err = new Error(errBody.message || '导出失败')
    err.code = errBody.code
    throw err
  }
  const objectUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objectUrl
  a.download = filename || url.split('/').filter(Boolean).pop() || 'export.csv'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(objectUrl)
}

export default http