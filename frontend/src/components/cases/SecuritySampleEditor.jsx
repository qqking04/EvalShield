/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Button, Input, Select, Space, Alert } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { THREAT_TYPES } from './caseSchemas'

// FE-8 安全样本编辑器（受控 value/onChange）
// 每行 { title, threat_type, payload, context(JSON), expected_behavior }
export default function SecuritySampleEditor({ value = [], onChange }) {
  const rows = Array.isArray(value) ? value : []
  const update = (i, patch) => onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  const removeRow = (i) => onChange(rows.filter((_, idx) => idx !== i))
  const addRow = () => onChange([
    ...rows,
    { title: '', threat_type: undefined, payload: '', context: '', expected_behavior: '' },
  ])

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      {rows.map((r, i) => (
        <div key={i} style={{ padding: 10, border: '1px solid #1f2833', borderRadius: 4, background: '#0f141b' }}>
          <Space align="baseline" style={{ width: '100%', marginBottom: 6 }}>
            <Input style={{ width: 200 }} placeholder="样本标题" value={r.title || ''}
              onChange={(e) => update(i, { title: e.target.value })} />
            <Select style={{ width: 240 }} placeholder="威胁类型" options={THREAT_TYPES} value={r.threat_type}
              onChange={(v) => update(i, { threat_type: v })} />
            <DeleteOutlined style={{ color: '#999' }} onClick={() => removeRow(i)} />
          </Space>
          <div style={{ marginBottom: 6 }}>
            <div style={{ color: '#8ba3b5', fontSize: 12, marginBottom: 4 }}>攻击载荷（payload）</div>
            <Input.TextArea rows={2} value={r.payload || ''} placeholder="攻击提示词/载荷"
              onChange={(e) => update(i, { payload: e.target.value })} />
          </div>
          <div style={{ marginBottom: 6 }}>
            <div style={{ color: '#8ba3b5', fontSize: 12, marginBottom: 4 }}>上下文（context，JSON 字符串）</div>
            <ContextInput value={r.context} onChange={(v) => update(i, { context: v })} />
          </div>
          <div>
            <div style={{ color: '#8ba3b5', fontSize: 12, marginBottom: 4 }}>预期行为（expected_behavior）</div>
            <Input.TextArea rows={2} value={r.expected_behavior || ''} placeholder="面对该攻击的期望防御行为"
              onChange={(e) => update(i, { expected_behavior: e.target.value })} />
          </div>
        </div>
      ))}
      <Button type="dashed" block icon={<PlusOutlined />} onClick={addRow}>添加安全样本</Button>
    </Space>
  )
}

function ContextInput({ value, onChange }) {
  const text = value == null ? '' : (typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value))
  let invalid = false
  if (text.trim() && text.trim() !== '{}') {
    try { JSON.parse(text) } catch { invalid = true }
  }
  return (
    <Space direction="vertical" size={2} style={{ width: '100%' }}>
      <Input.TextArea rows={2} value={text} placeholder='{"role":"assistant","memory":[...]}'
        onChange={(e) => onChange(e.target.value)} />
      {invalid && <Alert type="error" showIcon message="上下文不是合法 JSON，请检查" />}
    </Space>
  )
}