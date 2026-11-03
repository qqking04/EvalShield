/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 共享工具：各引擎渲染器通用（U8-2 自 reportRenderers.jsx 原样迁出）
import { Tag } from 'antd'
import { SEVERITY_COLOR, VERDICT_COLOR, MONO_FONT } from '../../../theme'
import { VERDICT_CN_MAP, SEVERITY_CN_MAP } from '../../../constants/enums'

export const mono = { fontFamily: MONO_FONT }

// detail 可能是对象、JSON 字符串或数组（MULTI_TURN trace），统一解出
export function parseDetail(item) {
  let d = item?.detail
  if (d == null || d === '') return {}
  if (typeof d === 'string') {
    try { d = JSON.parse(d) } catch { return {} }
  }
  return d
}

// 原始行 + detail 合并（detail 字段优先）
export function mergeItems(items = []) {
  return (Array.isArray(items) ? items : []).map((it) => {
    const d = parseDetail(it)
    if (Array.isArray(d)) return { ...it, trace: d }
    return { ...it, ...d, detail: undefined }
  })
}

export const verdictTag = (v) => <Tag color={VERDICT_COLOR[v] || 'default'}>{VERDICT_CN_MAP[v] || v || '-'}</Tag>
export const severityTag = (s) => (s ? <Tag color={SEVERITY_COLOR[s] || '#8c8c8c'} style={{ color: '#0a0d12', fontWeight: 600 }}>{SEVERITY_CN_MAP[s] || s}</Tag> : '-')

// 引擎产出的说明文本中文化：把裸英文枚举与术语转为中文（仅独立大写词，避免误伤）
const NOTE_TERM_CN = [
  [/\bembedding\b/gi, '向量模型'],
  [/\bHIGH\b/g, '高'],
  [/\bMEDIUM\b/g, '中'],
  [/\bLOW\b/g, '低'],
  [/\bCRITICAL\b/g, '严重'],
  [/\bMINOR\b/g, '轻微'],
  [/\bMODERATE\b/g, '中'],
  [/\bMAJOR\b/g, '较重'],
  [/\bNONE\b/g, '无'],
  [/\bPASS\b/g, '通过'],
  [/\bFAIL(?:ED)?\b/g, '失败'],
]
export const cnNote = (v) => {
  if (!v || typeof v !== 'string') return v || '-'
  return NOTE_TERM_CN.reduce((s, [re, cn]) => s.replace(re, cn), v)
}
