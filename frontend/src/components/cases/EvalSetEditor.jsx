/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Button, Input, Select, Space } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'

// FE-7 评测条目编辑器（受控 value/onChange）
// 按 category 渲染条目列内容，每条即一行题项对象（如 { prompt, references }）
// 题项表格可增删行、编辑字段
export default function EvalSetEditor({ value = [], onChange, category }) {
  const rows = Array.isArray(value) ? value : []
  const fields = fieldsOf(category)
  const update = (i, patch) => onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  const removeRow = (i) => onChange(rows.filter((_, idx) => idx !== i))
  const addRow = () => onChange([...rows, blank(category)])

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      {rows.length === 0 && (
        <div style={{ color: '#869BAA', fontSize: 12 }}>该类别暂无条目，点击下方按钮新增评测条目。</div>
      )}
      {rows.map((r, i) => (
        <div key={i} style={{ padding: 10, border: '1px solid #1f2833', borderRadius: 4, background: '#0f141b' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ color: '#8ba3b5', fontSize: 12 }}>条目 #{(r.no ?? i + 1)}</span>
            <DeleteOutlined style={{ color: '#999' }} onClick={() => removeRow(i)} />
          </div>
          <FieldEditor fields={fields} item={r} update={(patch) => update(i, patch)} />
        </div>
      ))}
      <Button type="dashed" block icon={<PlusOutlined />} onClick={addRow}>添加评测条目</Button>
    </Space>
  )
}

// 类别 → 字段列表（多行字段用 TextArea；multi 表示按行存为数组）
export function fieldsOf(category) {
  switch (category) {
    case 'EVAL': return [{ key: 'prompt', label: '评测提示词', area: true }, { key: 'rubric', label: '评分标准（rubric）', area: true }]
    case 'HALLUCINATION': return [{ key: 'question', label: '问题', area: true }, { key: 'references', label: '参考资料（每行一条）', area: true, multi: true }]
    case 'RAG': return [{ key: 'question', label: '问题', area: true }, { key: 'contexts', label: '上下文（每行一条）', area: true, multi: true }, { key: 'ground_truth', label: '参考答案（ground_truth）', area: true }]
    case 'ETHICS': return [{ key: 'prompt', label: '提示词', area: true }, { key: 'references', label: '参考资料（每行一条）', area: true, multi: true }]
    case 'MULTI_TURN':
    case 'MULTITURN': return [{ key: 'sessions', label: '会话（sessions，JSON）', area: true, json: true }, { key: 'fact_slots', label: '事实槽位（fact_slots，JSON）', area: true, json: true }]
    case 'REDTEAM': return [{ key: 'prompt', label: '攻击提示词', area: true }, { key: 'threat', label: '威胁类型（threat）', input: true }]
    case 'SECURITY': return [{ key: 'prompt', label: '注入提示词', area: true }, { key: 'threat_type', label: '威胁类型（threat_type）', input: true }]
    default: return [{ key: 'prompt', label: '提示词', area: true }]
  }
}

function blank(category) {
  const b = { no: undefined }
  fieldsOf(category).forEach((f) => { b[f.key] = f.json ? '{}' : (f.multi ? [] : '') })
  return b
}

function FieldEditor({ fields, item, update }) {
  return (
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      {fields.map((f) => {
        const raw = item[f.key]
        let text = ''
        if (f.multi && Array.isArray(raw)) text = raw.join('\n')
        else if (raw == null) text = ''
        else if (typeof raw === 'string') text = raw
        else text = JSON.stringify(raw, null, 2)
        const isJson = f.json
        const invalid = isJson && text.trim() && !(text.trim() === '{}')
          ? !isValidJson(text) : false
        const mode = f.json ? 'json' : (f.input ? 'input' : 'area')
        return (
          <div key={f.key}>
            <div style={{ color: '#8ba3b5', fontSize: 12, marginBottom: 4 }}>{f.label}</div>
            {mode === 'input' ? (
              <Input style={{ width: 300 }} value={text}
                onChange={(e) => update({ [f.key]: e.target.value })} />
            ) : (
              <Input.TextArea rows={f.json ? 4 : 3} value={text} placeholder={f.json ? '请输入 JSON' : '每行一条内容'}
                onChange={(e) => {
                  const v = e.target.value
                  update({ [f.key]: f.json ? v : (f.multi ? v.split('\n').map((s) => s.trim()).filter(Boolean) : v) })
                }} />
            )}
            {invalid && <div style={{ color: '#ff4d4f', fontSize: 12 }}>字段 {f.label} 不是合法 JSON</div>}
          </div>
        )
      })}
    </Space>
  )
}

function isValidJson(text) {
  try { JSON.parse(text); return true } catch { return false }
}