/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Alert, Button, Input, InputNumber, Select, Space } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import AssertionRows from './AssertionRows'
import TermTooltip from '../common/TermTooltip'

const METHOD_OPTIONS = [
  { value: 'GET', label: 'GET' },
  { value: 'POST', label: 'POST' },
  { value: 'PUT', label: 'PUT' },
  { value: 'DELETE', label: 'DELETE' },
  { value: 'PATCH', label: 'PATCH' },
  { value: 'HEAD', label: 'HEAD' },
]

const TEMPLATES = [
  { key: 'health', label: 'GET 健康检查', spec: { method: 'GET', path: '/api/health', headers: {}, body: '', expected_status: 200, assertions: [{ path: 'code', op: 'eq', expected: 0, note: '返回码为 0' }] } },
  { key: 'login', label: 'POST 登录', spec: { method: 'POST', path: '/api/login', headers: { 'Content-Type': 'application/json' }, body: '{"username":"admin","password":"123456"}', expected_status: 200, assertions: [{ path: 'data.token', op: 'notNull', expected: '', note: '返回 token' }] } },
  { key: 'delete', label: 'DELETE 资源', spec: { method: 'DELETE', path: '/api/resource/{id}', headers: {}, body: '', expected_status: 200, assertions: [{ path: 'data.deleted', op: 'eq', expected: true, note: '删除成功' }] } },
]

// FE-3 API 可视化编辑器（受控 value/onChange）：组装 request_spec
export default function ApiCaseEditor({ value, onChange }) {
  const spec = value && typeof value === 'object' ? value : {}
  const set = (patch) => onChange({ ...spec, ...patch })

  const headers = Array.isArray(spec.headers) ? spec.headers
    : Object.keys(spec.headers || {}).map((k) => ({ key: k, value: spec.headers[k] }))

  const updateHeader = (i, patch) => {
    const next = headers.map((h, idx) => (idx === i ? { ...h, ...patch } : h))
    set({ headers: next })
  }
  const removeHeader = (i) => set({ headers: headers.filter((_, idx) => idx !== i) })
  const addHeader = () => set({ headers: [...headers, { key: '', value: '' }] })

  // 断言合法化：expected 数字字段尽量转数字
  const normalizeExpected = (rows) => (rows || []).map((r) => {
    if (r.op === 'eq' && r.expected !== '' && r.expected != null) {
      const n = Number(r.expected)
      if (!isNaN(n) && String(n) === String(r.expected).trim()) return { ...r, expected: n }
    }
    return r
  })

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      <Space wrap>
        {TEMPLATES.map((t) => (
          <Button key={t.key} size="small" onClick={() => onChange(t.spec)}>{t.label}</Button>
        ))}
      </Space>
      <Space wrap align="baseline">
        <Select style={{ width: 140 }} placeholder="方法" options={METHOD_OPTIONS} value={spec.method} onChange={(v) => set({ method: v })} />
        <Input style={{ width: 300 }} placeholder="路径，如 /api/login 或完整 URL" value={spec.path ?? spec.url ?? ''}
          onChange={(e) => { const next = { ...spec, path: e.target.value }; delete next.url; onChange(next) }} />
        <span style={{ color: '#869BAA' }}>期望状态码</span>
        <InputNumber style={{ width: 100 }} min={100} max={599} placeholder="200" value={spec.expected_status}
          onChange={(v) => set({ expected_status: v })} />
      </Space>
      <div style={{ borderLeft: '3px solid #13c2c2', paddingLeft: 10 }}>
        <div style={{ color: '#8ba3b5', fontSize: 12, marginBottom: 6 }}>请求头（键值对）</div>
        {headers.map((h, i) => (
          <Space key={i} align="baseline" style={{ marginBottom: 6 }}>
            <Input style={{ width: 200 }} placeholder="Header 名，如 Content-Type" value={h.key || ''}
              onChange={(e) => updateHeader(i, { key: e.target.value })} />
            <Input style={{ width: 240 }} placeholder="值" value={h.value || ''}
              onChange={(e) => updateHeader(i, { value: e.target.value })} />
            <DeleteOutlined style={{ color: '#999' }} onClick={() => removeHeader(i)} />
          </Space>
        ))}
        <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addHeader}>添加请求头</Button>
      </div>
      <div>
        <div style={{ color: '#8ba3b5', fontSize: 12, marginBottom: 6 }}>请求体（JSON 字符串）</div>
        <BodyEditor body={spec.body} onChange={(body) => set({ body })} />
      </div>
      <div style={{ borderLeft: '3px solid #13c2c2', paddingLeft: 10 }}>
        <div style={{ color: '#8ba3b5', fontSize: 12, marginBottom: 6 }}>
          <TermTooltip term="断言集" explain="预期输出的自动校验清单" example="path=$.code op=eq expected=0 表示返回码必须为 0">
            断言集（引擎按此判定）
          </TermTooltip>
        </div>
        <AssertionRows value={spec.assertions || []}
          onChange={(rows) => set({ assertions: normalizeExpected(rows) })} />
      </div>
    </Space>
  )
}

function BodyEditor({ body, onChange }) {
  const text = body == null ? '' : String(body)
  let invalid = false
  if (text && text.trim()) {
    try { JSON.parse(text) } catch { invalid = true }
  }
  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      <Input.TextArea rows={3} value={text} placeholder='{"username":"admin"} 或空'
        onChange={(e) => onChange(e.target.value)} />
      {invalid && <Alert type="error" showIcon message="请求体不是合法 JSON，请检查括号与引号" />}
    </Space>
  )
}