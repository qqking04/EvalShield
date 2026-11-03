/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ---- 通用格式化工具 ----

export function fmtTime(dt) {
  if (!dt) return '-'
  return String(dt).replace('T', ' ').slice(0, 19)
}

export function fmtDuration(ms) {
  if (ms === null || ms === undefined) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function fmtRate(rate) {
  if (rate === null || rate === undefined) return '-'
  return `${(Number(rate) * 100).toFixed(1)}%`
}

// overall_score 双量纲归一：任务引擎链路存 0-100，评测中心自建链路存 0-1，统一换算为百分数
export function toScorePercent(v) {
  if (v === null || v === undefined) return null
  const n = Number(v)
  if (Number.isNaN(n)) return null
  return n <= 1 ? n * 100 : n
}

// 状态徽标配色（AntD Tag 颜色）
export const TASK_STATUS_COLOR = {
  PENDING: 'default',
  RUNNING: 'processing',
  SUCCESS: 'success',
  COMPLETED_WITH_RISK: 'warning',
  FAILED: 'error',
  CANCELLED: 'warning',
  ARCHIVED: 'default',
}

export const TASK_STATUS_TEXT = {
  PENDING: '待执行',
  RUNNING: '执行中',
  SUCCESS: '成功',
  COMPLETED_WITH_RISK: '未达阈值',
  FAILED: '失败',
  CANCELLED: '已取消',
  ARCHIVED: '已归档',
}

// 页面统一使用的状态中文映射
export const TASK_STATUS_MAP = TASK_STATUS_TEXT

// 步骤状态配色（含 SKIPPED / SKIP）
export const STEP_STATUS_COLOR = {
  PENDING: 'default',
  RUNNING: 'processing',
  SUCCESS: 'success',
  SKIPPED: 'warning',
  SKIP: 'warning',
  FAILED: 'error',
  CANCELLED: 'default',
}

export const ENGINE_TYPE_TEXT = {
  TRADITIONAL: '传统测试',
  AI: 'AI 测试',
  ENGINEERING: 'AI 工程化',
}

export function noText(prefix, no) {
  return no || `${prefix}-待生成`
}

// 保底 JSON 字符串化（防止 undefined 序列化丢失）
export function safeJson(value, indent = 2) {
  try {
    return JSON.stringify(value, null, indent)
  } catch {
    return String(value)
  }
}