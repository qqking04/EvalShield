/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ===========================================================================
// CaseImportExport：测试用例 JSON 全量导出 / 全量导入 + CSV 基础视图
// FE-10 / FE-11
// ===========================================================================

// 完整导出字段（对齐后端 CaseOut，含结构化新字段，保证 JSON 无损往返）
export const FULL_EXPORT_FIELDS = [
  'project_id', 'dataset_id', 'module', 'title', 'category', 'source', 'severity', 'priority',
  'precondition', 'steps', 'expected', 'request_spec', 'tags', 'content_schema',
  'preconditions', 'test_data', 'assertions', 'extract_vars', 'post_cleanup', 'requirement_id', 'case_no',
]

const FULL_EXPORT_WIDTH = 1000

// 后端合法用例类别（与 schemas.VALID_CASE_CATEGORIES 一致），用于前端导入预校验
export const VALID_CASE_CATEGORIES = new Set([
  'FUNCTIONAL', 'API', 'UI', 'PERFORMANCE', 'HALLUCINATION', 'REDTEAM',
  'RAG', 'ETHICS', 'DATAFLOW', 'MULTITURN', 'EVAL', 'CASE_GEN',
  'SECURITY', 'PERF', 'DATA_QUALITY', 'DEFECT_PREDICT', 'MULTI_TURN', 'SELF_HEAL',
])

function toJsonText(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') {
    try { return JSON.stringify(v) } catch { return String(v) }
  }
  return String(v)
}

function download(filename, content, mime = 'application/json;charset=utf-8') {
  const blob = new Blob(['\uFEFF' + content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// 排序键，保证稳定输出
function sortKeys(obj) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return obj
  const out = {}
  FULL_EXPORT_FIELDS.forEach((k) => {
    if (obj[k] !== undefined) out[k] = obj[k]
  })
  Object.keys(obj).forEach((k) => {
    if (!(k in out)) out[k] = obj[k]
  })
  return out
}

// FE-10：JSON 全量导出（含结构化字段，UTF-8 BOM 防中文乱码）
export function exportFullJson(items) {
  const cleaned = (items || []).map(sortKeys)
  const text = JSON.stringify(cleaned, null, 2)
  download(`用例全量导出_${Date.now()}.json`, text)
  return (items || []).length
}

// CSV 基础视图（仅基础列，保留兼容）
export function exportCsv(items) {
  const j2s = (v) => (v === null || v === undefined ? '' : (typeof v === 'object' ? JSON.stringify(v) : String(v)))
  const esc = (v) => { const s = j2s(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s }
  const header = ['case_no', '所属模块', '项目ID', 'title', 'category', 'severity', 'priority', 'tags', 'precondition', 'expected', 'test_data', 'steps', 'assertions']
  const lines = [header.join(',')]
  for (const c of items || []) {
    lines.push([
      c.case_no,
      esc(c.module),
      esc(c.project_id),
      esc(c.title),
      esc(c.category),
      esc(c.severity),
      esc(c.priority),
      esc((c.tags || []).join('|')),
      esc(c.precondition),
      esc(c.expected),
      esc(c.test_data),
      esc(c.steps),
      esc(c.assertions),
    ].join(','))
  }
  download(`用例导出_${Date.now()}.csv`, lines.join('\n'), 'text/csv;charset=utf-8')
  return (items || []).length
}

// 解析导入文本：JSON 数组（推荐）或 CSV（表头+行）
// 返回 { format: 'json'|'csv', objs: object[] }；解析失败抛错
export function parseImportText(raw) {
  const text = (raw || '').trim()
  if (!text) return { format: 'json', objs: [] }
  if (text.startsWith('[') || text.startsWith('{')) {
    let parsed
    try { parsed = JSON.parse(text) } catch (e) { throw new Error('JSON 解析失败：' + e.message) }
    const objs = Array.isArray(parsed) ? parsed : [parsed]
    return { format: 'json', objs }
  }
  // CSV
  const lines = text.split(/\r?\n/).filter((l) => l.trim())
  if (lines.length < 2) throw new Error('CSV 需要表头和数据行')
  const head = lines[0].split(',').map((h) => h.trim().replace(/^"|"$/g, ''))
  const objs = lines.slice(1).map((line) => {
    const cells = []
    let cur = '', inQ = false
    for (const ch of line) {
      if (ch === '"') { inQ = !inQ; continue }
      if (ch === ',' && !inQ) { cells.push(cur); cur = '' } else cur += ch
    }
    cells.push(cur)
    const obj = {}
    head.forEach((h, i) => { obj[h] = (cells[i] || '').trim() })
    return obj
  })
  return { format: 'csv', objs }
}

// 字段别名兼容（CSV 中英列名 / JSON 英文标准名）
function pick(obj, keys) {
  for (const k of keys) {
    if (obj[k] !== undefined && obj[k] !== null && obj[k] !== '') return obj[k]
  }
  return undefined
}

function toNumber(v, fd) {
  const n = Number(v ?? fd)
  return Number.isFinite(n) ? n : undefined
}

function normalizeTags(v) {
  if (v === undefined || v === null) return undefined
  if (Array.isArray(v)) return v.map((s) => String(s).trim()).filter(Boolean)
  if (typeof v === 'string') return v.split('|').map((s) => s.trim()).filter(Boolean)
  return undefined
}

// 将解析后的对象映射为 CaseCreate 干净 payload（含结构化字段）
export function normalizeForBulk(objs) {
  const out = []
  for (const raw of objs || []) {
    const project_id = toNumber(pick(raw, ['project_id', '项目ID', 'projectId']), undefined)
    const category = pick(raw, ['category', '类别']) || ''
    const title = pick(raw, ['title', '用例标题', '标题']) || ''
    // 预校验：必须包含有效 project_id/title/category
    if (!title || !category || !project_id || project_id <= 0) continue
    const severity = String(pick(raw, ['severity', '严重度']) || 'P2').toUpperCase()
    const priority = String(pick(raw, ['priority', '优先级']) || 'MEDIUM').toUpperCase()

    const obj = {
      project_id,
      title,
      category,
      severity,
      priority,
      source: pick(raw, ['source']) || 'MANUAL',
    }
    const module = pick(raw, ['module', '所属模块'])
    if (module) obj.module = String(module).trim()
    const dataset_id = toNumber(pick(raw, ['dataset_id', '数据集ID']), undefined)
    if (dataset_id) obj.dataset_id = dataset_id

    // 结构化新字段（JSON 全量往返；CSV 不携带则跳过）
    const structuredMap = [
      ['steps', 'steps'],
      ['request_spec', 'request_spec'],
      ['preconditions', 'preconditions'],
      ['test_data', 'test_data'],
      ['assertions', 'assertions'],
      ['extract_vars', 'extract_vars'],
      ['post_cleanup', 'post_cleanup'],
      ['content_schema', 'content_schema'],
    ]
    for (const [field, key] of structuredMap) {
      let v = raw[key]
      if (v === undefined || v === null) continue
      // 若为 JSON 字符串（部分来源），尝试解析为对象
      if (typeof v === 'string' && v.trim()) {
        try { v = JSON.parse(v) } catch { /* 保留字符串 */ }
      }
      if (v !== undefined && v !== null) obj[field] = v
    }

    const reqId = pick(raw, ['requirement_id', '需求编号'])
    if (reqId) obj.requirement_id = String(reqId).trim()

    const precondition = pick(raw, ['precondition', '前置条件'])
    if (precondition) obj.precondition = precondition
    const expected = pick(raw, ['expected', '预期结果'])
    if (expected) obj.expected = expected
    const tags = normalizeTags(raw.tags)
    if (tags) obj.tags = tags

    out.push(obj)
  }
  return out
}

const format = { exportFullJson, exportCsv, parseImportText, normalizeForBulk, VALID_CASE_CATEGORIES, FULL_EXPORT_FIELDS, FULL_EXPORT_WIDTH }
export default format