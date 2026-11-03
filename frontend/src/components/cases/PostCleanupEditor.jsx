/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Alert, Button, Input, Select, Space } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { CLEANUP_ACTIONS } from './caseSchemas'

// FE-6 后置清理编辑器（受控 value/onChange）
// 行 { action 下拉, target, params(JSON 1行) }；action=custom_script 时提示沙箱执行
export default function PostCleanupEditor({ value = [], onChange }) {
  const rows = Array.isArray(value) ? value : []
  const update = (i, patch) => onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  const removeRow = (i) => onChange(rows.filter((_, idx) => idx !== i))
  const addRow = () => onChange([...rows, { action: undefined, target: '', params: '' }])

  return (
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      {rows.map((r, i) => (
        <div key={i} style={{ padding: 8, border: '1px solid #1f2833', borderRadius: 4, background: '#0f141b' }}>
          <Space align="baseline">
            <Select style={{ width: 240 }} placeholder="清理动作" options={CLEANUP_ACTIONS} value={r.action}
              onChange={(v) => update(i, { action: v })} />
            <Input style={{ width: 180 }} placeholder="目标，如账号/记录标识" value={r.target || ''}
              onChange={(e) => update(i, { target: e.target.value })} />
            <ParamsInput style={{ width: 220 }} value={r.params} onChange={(v) => update(i, { params: v })} />
            <DeleteOutlined style={{ color: '#999' }} onClick={() => removeRow(i)} />
          </Space>
          {r.action === 'custom_script' && (
            <Alert type="warning" showIcon style={{ marginTop: 6 }} message="脚本将提交沙箱执行，失败仅告警不判定失败" />
          )}
        </div>
      ))}
      <Button type="dashed" block icon={<PlusOutlined />} onClick={addRow}>添加清理动作</Button>
    </Space>
  )
}

function ParamsInput({ value, onChange, style }) {
  const text = value == null ? '' : (typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value))
  let invalid = false
  if (text.trim()) {
    try { JSON.parse(text) } catch { invalid = true }
  }
  return (
    <Space direction="vertical" size={2} style={{ width: '100%' }}>
      <Input placeholder='参数（JSON），如 {"key":"v"}' style={style || { width: 220 }} value={text}
        onChange={(e) => onChange(e.target.value)} />
      {invalid && <div style={{ color: '#ff4d4f', fontSize: 12 }}>参数不是合法 JSON，请检查</div>}
    </Space>
  )
}