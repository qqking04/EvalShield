/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// v2.0 P2：新建评测集批量导入（上传 JSON/CSV 到后端 /eval-sets/import）
// 与 EvalImportModal（向已有集追加/覆盖）互补：本组件直接创建新评测集
import { useState } from 'react'
import { Modal, Upload, Form, Select, Input, App, Typography } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { EVAL_CATEGORY_MAP } from '../../constants/enums'

const { Dragger } = Upload

const CATEGORY_OPTIONS = ['HALLUCINATION', 'ETHICS', 'REDTEAM', 'RAG', 'SECURITY', 'MULTI_TURN'].map(
  (v) => ({ value: v, label: EVAL_CATEGORY_MAP[v] || v }),
)

export default function EvalSetImportModal({ open, onClose, onImported }) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [file, setFile] = useState(null)
  const [saving, setSaving] = useState(false)

  const close = () => { setFile(null); form.resetFields(); onClose() }

  const submit = async () => {
    const values = await form.validateFields()
    if (!file) { message.warning('请选择 JSON/CSV 文件'); return }
    setSaving(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('category', values.category)
      if (values.name) fd.append('name', values.name)
      const data = await http.post('/eval-sets/import', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      message.success(`导入成功：${data.item_count} 条样本（${data.eval_set_no}）`)
      onImported?.(data)
      close()
    } catch { /* 拦截器已提示 */ } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="批量导入评测集"
      open={open}
      onOk={submit}
      okText="确认导入"
      cancelText="取消"
      confirmLoading={saving}
      onCancel={close}
      destroyOnHidden
      width={560}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="category" label="类别" rules={[{ required: true, message: '请选择类别' }]}>
          <Select options={CATEGORY_OPTIONS} placeholder="选择评测集类别" />
        </Form.Item>
        <Form.Item name="name" label="评测集名称（可选，缺省取文件名）">
          <Input placeholder="如：幻觉检测基准集 v3" maxLength={128} />
        </Form.Item>
        <Dragger
          accept=".json,.csv"
          maxCount={1}
          showUploadList
          beforeUpload={(f) => { setFile(f); return false }}
          onRemove={() => setFile(null)}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p style={{ margin: 0 }}>点击或拖拽 JSON / CSV 文件到此处</p>
          <p style={{ margin: 0, fontSize: 12, color: '#8b97a7' }}>
            {'JSON：数组 [{"no":"…","prompt":"…","references":["…"],"tags":["…"]}]；CSV：表头 no,prompt,references(竖线分隔),tags(逗号分隔)；样本量需 ≥10 条'}
          </p>
        </Dragger>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          导入后 source=IMPORT，类别与引擎契约对齐：REDTEAM 用 threat、SECURITY 用 threat_type、RAG 用 prompt/contexts/ground_truth、MULTI_TURN 用 session/topic/rounds。
        </Typography.Text>
      </Form>
    </Modal>
  )
}
