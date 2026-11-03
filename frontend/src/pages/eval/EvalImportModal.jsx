/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// §6.5.10 EvalImportModal.jsx — CSV/JSONL 前端解析导入（T15，不引入新依赖）
// JSONL 按行 JSON.parse；CSV 按表头映射 no,prompt,references(分号分隔),contexts,ground_truth,tags
// 校验：no 唯一、prompt 非空；MULTI_TURN 校验 sessions[].user 非空
// 追加/覆盖两种模式 → 复用 PUT /eval-sets/{id}
import { useState } from 'react'
import { Modal, Upload, Table, Alert, Radio, Space, Typography, Tag, App } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import http from '../../api/http'

const { Dragger } = Upload

// 简单 CSV 解析（支持双引号转义、\r\n 换行）
function parseCsv(text) {
  const rows = []
  let row = []
  let field = ''
  let inQuotes = false
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i]
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i += 1 } else { inQuotes = false }
      } else { field += c }
    } else if (c === '"') { inQuotes = true } else if (c === ',') { row.push(field); field = '' } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i += 1
      row.push(field); field = ''
      if (row.some((v) => v.trim() !== '')) rows.push(row)
      row = []
    } else { field += c }
  }
  if (field !== '' || row.length > 0) {
    row.push(field)
    if (row.some((v) => v.trim() !== '')) rows.push(row)
  }
  return rows
}

function splitLines(text) {
  return text.split(/\r?\n/).map((s) => s.trim()).filter(Boolean)
}

// 表头映射后的字符串字段归一化：分号分隔 → 数组
function normalizeRow(obj, isMulti) {
  const o = { ...obj }
  for (const k of ['references', 'contexts', 'tags']) {
    if (typeof o[k] === 'string' && o[k].trim()) o[k] = o[k].split(';').map((s) => s.trim()).filter(Boolean)
  }
  if (isMulti) {
    for (const k of ['sessions', 'fact_slots']) {
      if (typeof o[k] === 'string' && o[k].trim()) {
        try { o[k] = JSON.parse(o[k]) } catch { /* 保留原样，校验会报错 */ }
      }
    }
  }
  if (o.no != null) o.no = String(o.no).trim()
  return o
}

// 解析文件文本 → items；返回 {items, error}
function parseFile(name, text, category) {
  const isJsonl = /\.jsonl$/i.test(name)
  const isMulti = category === 'MULTI_TURN' || category === 'MULTITURN'
  try {
    if (isJsonl) {
      const lines = splitLines(text)
      const items = []
      for (let i = 0; i < lines.length; i += 1) {
        try { items.push(normalizeRow(JSON.parse(lines[i]), isMulti)) } catch {
          return { items: [], error: `第 ${i + 1} 行不是合法 JSON` }
        }
      }
      return { items, error: null }
    }
    const rows = parseCsv(text)
    if (rows.length < 2) return { items: [], error: 'CSV 至少需要表头 + 1 行数据' }
    const header = rows[0].map((h) => h.trim())
    const items = rows.slice(1).map((r) => {
      const obj = {}
      header.forEach((h, i) => { obj[h] = r[i] ?? '' })
      return normalizeRow(obj, isMulti)
    })
    return { items, error: null }
  } catch (e) {
    return { items: [], error: e?.message || '解析失败' }
  }
}

// 校验：no 唯一、prompt 非空（MULTI_TURN 校验 sessions[].user 非空）
function validateItems(items, category) {
  const errors = []
  const isMulti = category === 'MULTI_TURN' || category === 'MULTITURN'
  const seen = new Set()
  items.forEach((it, idx) => {
    const no = it.no ?? it.item_no
    if (no != null && no !== '') {
      if (seen.has(String(no))) errors.push(`第 ${idx + 1} 条：编号 ${no} 重复`)
      seen.add(String(no))
    }
    if (isMulti) {
      const sessions = Array.isArray(it.sessions) ? it.sessions : []
      if (!sessions.length) errors.push(`第 ${idx + 1} 条：缺少 sessions`)
      sessions.forEach((s, si) => {
        const turns = Array.isArray(s?.turns) ? s.turns : (Array.isArray(s) ? s : [])
        const bad = turns.some((t) => !t || !String(t.user ?? '').trim())
        if (bad) errors.push(`第 ${idx + 1} 条：sessions[${si}] 存在 user 为空的轮次`)
      })
    } else {
      const prompt = it.prompt ?? it.question
      if (!String(prompt ?? '').trim()) errors.push(`第 ${idx + 1} 条：prompt 为空`)
    }
  })
  return errors
}

export default function EvalImportModal({ open, onClose, evalSet, existingItems = [], onSaved }) {
  const { message } = App.useApp()
  const [items, setItems] = useState([])
  const [parseError, setParseError] = useState(null)
  const [fileName, setFileName] = useState('')
  const [mode, setMode] = useState('append') // append | overwrite
  const [saving, setSaving] = useState(false)

  const reset = () => { setItems([]); setParseError(null); setFileName('') }
  const close = () => { reset(); onClose() }

  const handleFile = (file) => {
    const reader = new FileReader()
    reader.onload = () => {
      const text = String(reader.result || '')
      const { items: parsed, error } = parseFile(file.name, text, evalSet?.category)
      setFileName(file.name)
      if (error) { setParseError(error); setItems([]) } else { setParseError(null); setItems(parsed) }
    }
    reader.onerror = () => { setParseError('文件读取失败'); setItems([]) }
    reader.readAsText(file, 'utf-8')
    return false // 阻止自动上传
  }

  const errors = items.length ? validateItems(items, evalSet?.category) : []
  const previewColumns = [
    { title: '编号', dataIndex: 'no', width: 90, render: (v, _, i) => v || i + 1 },
    {
      title: '提示词 / 题目',
      dataIndex: 'prompt',
      ellipsis: true,
      render: (v, r) => {
        if (evalSet?.category === 'MULTI_TURN' || evalSet?.category === 'MULTITURN') {
          const n = Array.isArray(r.sessions) ? r.sessions.length : 0
          return <Tag>{n} 个会话</Tag>
        }
        return v ?? r.question ?? ''
      },
    },
    {
      title: '附加字段',
      ellipsis: true,
      render: (_, r) => {
        const extras = ['references', 'contexts', 'ground_truth', 'tags', 'fact_slots', 'sessions'].filter((k) => r[k] != null && r[k] !== '')
        return extras.map((k) => <Tag key={k}>{k}</Tag>)
      },
    },
  ]

  const save = async () => {
    if (!items.length) { message.warning('请先选择并解析文件'); return }
    if (errors.length) { message.error('存在校验错误，请修正后重新导入'); return }
    setSaving(true)
    try {
      const next = mode === 'append' ? [...existingItems, ...items] : items
      await http.put(`/eval-sets/${evalSet.id}`, { ...evalSet, items: next })
      message.success(`导入成功 ${items.length} 条（${mode === 'append' ? '追加' : '覆盖'}），共 ${next.length} 条`)
      reset()
      onSaved?.(next)
      onClose()
    } catch { /* 拦截器已提示 */ } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`导入 CSV/JSONL - ${evalSet ? `${evalSet.code}（${evalSet.category || '未分类'}）` : ''}`}
      open={open}
      onCancel={close}
      onOk={save}
      okText="确认导入"
      cancelText="取消"
      confirmLoading={saving}
      okButtonProps={{ disabled: !items.length || errors.length > 0 }}
      width={760}
      destroyOnHidden
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Dragger
          accept=".csv,.jsonl"
          maxCount={1}
          showUploadList={false}
          beforeUpload={handleFile}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p style={{ margin: 0 }}>点击或拖拽 CSV / JSONL 文件到此处（前端解析，不上传原文件）</p>
          <p style={{ margin: 0, fontSize: 12, color: '#8b97a7' }}>
            CSV 表头：no,prompt,references(分号分隔),contexts(分号分隔),ground_truth,tags(分号分隔)；JSONL 每行一个 JSON 对象
          </p>
        </Dragger>
        {fileName && (
          <Typography.Text type="secondary">已解析文件：{fileName}，共 {items.length} 条</Typography.Text>
        )}
        {parseError && <Alert type="error" showIcon message="解析失败" description={parseError} />}
        {errors.length > 0 && (
          <Alert
            type="error"
            showIcon
            message={`校验失败（${errors.length} 项）`}
            description={<ul style={{ margin: 0, paddingLeft: 18 }}>{errors.slice(0, 8).map((e, i) => <li key={i}>{e}</li>)}{errors.length > 8 && <li>…共 {errors.length} 项</li>}</ul>}
          />
        )}
        {items.length > 0 && (
          <>
            <Radio.Group value={mode} onChange={(e) => setMode(e.target.value)}>
              <Radio value="append">追加到现有 {existingItems.length} 条之后</Radio>
              <Radio value="overwrite">覆盖现有题项</Radio>
            </Radio.Group>
            <Table
              rowKey={(_, idx) => idx}
              size="small"
              columns={previewColumns}
              dataSource={items}
              pagination={{ pageSize: 6, showSizeChanger: false }}
            />
          </>
        )}
      </Space>
    </Modal>
  )
}
