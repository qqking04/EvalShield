/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES8 M7：批量导入向导 —— 上传 CSV/JSONL → 后端预览（猜映射）→ 列映射确认 → 建集（source=IMPORT）
// 与 EvalSetImportModal（multipart 简易导入）互补：本向导走 import-preview / import-confirm 无状态链路
import { useState } from 'react'
import { Alert, App, Button, Form, Input, Modal, Select, Space, Spin, Steps, Table, Tag, Typography, Upload } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { EVAL_CATEGORY_MAP } from '../../constants/enums'

const { Dragger } = Upload

// 列映射目标（与后端 dataset_io.MAP_TARGETS 对齐）
const MAP_FIELDS = [
  { key: 'question', label: '问题（必填）', required: true },
  { key: 'answer', label: '期望答案' },
  { key: 'tags', label: '标签' },
]

// File → base64（不走 FileReader 事件，直接 arrayBuffer 转）
async function fileToB64(file) {
  const buf = new Uint8Array(await file.arrayBuffer())
  let s = ''
  const CHUNK = 0x8000
  for (let i = 0; i < buf.length; i += CHUNK) s += String.fromCharCode(...buf.subarray(i, i + CHUNK))
  return btoa(s)
}

export default function EvalSetWizardModal({ open, onClose, onImported, categoryOptions = [] }) {
  const { message } = App.useApp()
  const [step, setStep] = useState(0)
  const [file, setFile] = useState(null)
  const [parsing, setParsing] = useState(false)
  const [preview, setPreview] = useState(null) // import-preview 返回体
  const [mapping, setMapping] = useState({ question: null, answer: null, tags: null })
  const [meta, setMeta] = useState({ name: '', category: undefined })
  const [saving, setSaving] = useState(false)

  const categoryOpts = categoryOptions.length
    ? categoryOptions
    : Object.entries(EVAL_CATEGORY_MAP).map(([v, l]) => ({ value: v, label: l }))

  const reset = () => {
    setStep(0); setFile(null); setPreview(null)
    setMapping({ question: null, answer: null, tags: null })
    setMeta({ name: '', category: undefined })
  }
  const close = () => { reset(); onClose() }

  // 调 import-preview（可携带用户改后的 mapping）
  const doPreview = async (f, m) => {
    setParsing(true)
    try {
      const b64 = await fileToB64(f)
      const d = await http.post('/eval-sets/import-preview', {
        filename: f.name,
        content_b64: b64,
        ...(m ? { mapping: m } : {}),
      })
      setPreview(d)
      setMapping(d.suggested_mapping || { question: null, answer: null, tags: null })
      return true
    } catch { return false } // 拦截器已提示（含解析/映射错误）
    finally { setParsing(false) }
  }

  // 第 1 步 → 第 2 步：先本地校验必填，再进映射步骤
  const goStep2 = async () => {
    if (!file) { message.warning('请选择 CSV / JSONL 文件'); return }
    if (!meta.name.trim()) { message.warning('请填写评测集名称'); return }
    if (!meta.category) { message.warning('请选择类别'); return }
    if (await doPreview(file, null)) setStep(1)
  }

  // 修改列映射 → 带 mapping 重新预览
  const changeMapping = async (key, col) => {
    const next = { ...mapping, [key]: col }
    setMapping(next)
    await doPreview(file, next)
  }

  const confirm = async () => {
    if (!mapping.question) { message.warning('请选择问题列'); return }
    const items = preview?.all_items
    if (!items || !items.length) { message.warning('映射后无可用条目，请检查列映射'); return }
    setSaving(true)
    try {
      const d = await http.post('/eval-sets/import-confirm', {
        name: meta.name.trim(),
        category: meta.category,
        items,
        mapping,
      })
      message.success(`导入成功：${d.item_count} 条题项（${d.eval_set_no}）`)
      onImported?.(d)
      close()
    } catch { /* 拦截器已提示 */ } finally { setSaving(false) }
  }

  const headerOptions = (preview?.headers || []).map((h) => ({ value: h, label: h }))
  const diffCols = preview
    ? Object.keys(preview.preview_rows?.[0] || {}).map((k) => ({ title: k, dataIndex: k, ellipsis: true, render: (v) => String(v ?? '') }))
    : []

  return (
    <Modal
      title="批量导入向导（CSV / JSONL）"
      open={open}
      onCancel={close}
      destroyOnHidden
      width={780}
      footer={
        step === 0 ? [
          <Button key="c" onClick={close}>取消</Button>,
          <Button key="n" type="primary" loading={parsing} onClick={goStep2}>下一步：解析与列映射</Button>,
        ] : step === 1 ? [
          <Button key="b" onClick={() => setStep(0)}>上一步</Button>,
          <Button key="n" type="primary" disabled={!preview?.all_items?.length} onClick={() => setStep(2)}>下一步：预览确认</Button>,
        ] : [
          <Button key="b" onClick={() => setStep(1)}>上一步</Button>,
          <Button key="ok" type="primary" loading={saving} onClick={confirm}>确认导入建集</Button>,
        ]
      }
      styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
    >
      <Steps
        size="small"
        current={step}
        items={[{ title: '上传文件' }, { title: '列映射' }, { title: '预览确认' }]}
        style={{ marginBottom: 16 }}
      />
      <Spin spinning={parsing}>
        {step === 0 && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Form layout="vertical">
              <Form.Item label="评测集名称" required>
                <Input value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} maxLength={128} placeholder="如：幻觉检测基准集 v1" />
              </Form.Item>
              <Form.Item label="类别" required>
                <Select value={meta.category} onChange={(v) => setMeta({ ...meta, category: v })} options={categoryOpts} placeholder="选择评测集类别" />
              </Form.Item>
            </Form>
            <Dragger
              accept=".csv,.jsonl,.json"
              maxCount={1}
              showUploadList
              beforeUpload={(f) => { setFile(f); return false }}
              onRemove={() => setFile(null)}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p style={{ margin: 0 }}>点击或拖拽 CSV / JSONL / JSON 文件到此处</p>
              <p style={{ margin: 0, fontSize: 12, color: '#8b97a7' }}>
                CSV 首行为表头（RFC4180 引号/换行安全）；JSONL 每行一个 JSON 对象；编码 UTF-8
              </p>
            </Dragger>
          </Space>
        )}
        {step === 1 && preview && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Alert
              type="info"
              showIcon
              message={<Space size={12}>
                <span>格式：{preview.format?.toUpperCase()}</span>
                <Tag>{preview.row_count} 行</Tag>
                {preview.truncated && <Tag color="orange">预览截断 {preview.preview_rows?.length} 行</Tag>}
              </Space>}
              description="自动猜测了列映射，如有偏差请在此修正（问题列必填；未映射列将原样透传到题项）。"
            />
            {preview.mapping_error && (
              <Alert type="warning" showIcon message="当前映射无法完成转换" description={preview.mapping_error} />
            )}
            <Space wrap size={16}>
              {MAP_FIELDS.map((f) => (
                <Space key={f.key} direction="vertical" size={2}>
                  <Typography.Text type={f.required && !mapping[f.key] ? 'danger' : 'secondary'} style={{ fontSize: 12 }}>
                    {f.label}{f.required ? ' *' : ''}
                  </Typography.Text>
                  <Select
                    allowClear
                    style={{ width: 200 }}
                    placeholder={f.required ? '选择问题列' : '不映射'}
                    value={mapping[f.key] ?? undefined}
                    options={headerOptions}
                    onChange={(v) => changeMapping(f.key, v ?? null)}
                  />
                </Space>
              ))}
            </Space>
            <Table
              rowKey={(_, idx) => idx}
              size="small"
              columns={diffCols}
              dataSource={preview.preview_rows || []}
              pagination={false}
              scroll={{ x: 'max-content' }}
            />
          </Space>
        )}
        {step === 2 && preview && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Alert
              type="success"
              showIcon
              message={`将创建评测集「${meta.name}」（${preview.all_items?.length ?? 0} 条题项，source=IMPORT）`}
              description={<Space size={8}>
                <Typography.Text>映射：</Typography.Text>
                {MAP_FIELDS.map((f) => <Tag key={f.key}>{f.key} → {mapping[f.key] || '—'}</Tag>)}
              </Space>}
            />
            <Table
              rowKey="no"
              size="small"
              columns={[
                { title: '编号', dataIndex: 'no', width: 110 },
                { title: '提示词 / 题目', dataIndex: 'prompt', ellipsis: true },
                { title: '预期答案', dataIndex: 'expected', ellipsis: true, render: (v) => v ?? '-' },
                { title: '标签', dataIndex: 'tags', width: 160, render: (v) => (v || []).map((t) => <Tag key={t}>{t}</Tag>) },
              ]}
              dataSource={preview.preview_items || []}
              pagination={false}
              scroll={{ x: 'max-content' }}
            />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              以上仅预览前 {preview.preview_items?.length ?? 0} 条，导入将包含全部 {preview.all_items?.length ?? 0} 条。
            </Typography.Text>
          </Space>
        )}
      </Spin>
    </Modal>
  )
}
