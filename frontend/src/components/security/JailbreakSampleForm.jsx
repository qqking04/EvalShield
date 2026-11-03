/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 越狱样本新增/编辑表单（Drawer 形态，产品优化3 §U2）
import { useEffect, useState } from 'react'
import { Drawer, Form, Input, Select, Switch, Button, Space } from 'antd'
import http from '../../api/http'

export const CATEGORY_OPTIONS = [
  { value: 'ROLEPLAY', label: '角色扮演（ROLEPLAY）' },
  { value: 'ENCODING', label: '编码绕过（ENCODING）' },
  { value: 'CONTEXT_POISON', label: '上下文投毒（CONTEXT_POISON）' },
  { value: 'CLASSIC_EN', label: '英文经典模板（CLASSIC_EN）' },
]

export const SEVERITY_OPTIONS = [
  { value: 'CRITICAL', label: '严重 CRITICAL' },
  { value: 'HIGH', label: '高危 HIGH' },
  { value: 'MEDIUM', label: '中危 MEDIUM' },
  { value: 'LOW', label: '低危 LOW' },
]

export default function JailbreakSampleForm({ open, editing, onClose, onSaved }) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    form.resetFields()
    if (editing) {
      form.setFieldsValue(editing)
    } else {
      form.setFieldsValue({ category: 'ROLEPLAY', severity: 'HIGH', is_active: true })
    }
  }, [open, editing, form])

  const submit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        await http.put(`/jailbreak/samples/${editing.id}`, values)
      } else {
        await http.post('/jailbreak/samples', values)
      }
      onSaved(editing)
      onClose()
    } catch (e) {
      /* 网络/业务错误已由 http 拦截器统一提示 */
      console.warn('[JailbreakSampleForm] save failed', e?.message || e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer
      title={editing ? `编辑越狱样本 #${editing.id}` : '新增越狱样本'}
      open={open}
      onClose={onClose}
      width={560}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={saving} onClick={submit}>保存</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical">
        <Form.Item name="category" label="类别" rules={[{ required: true }]}>
          <Select options={CATEGORY_OPTIONS} placeholder="选择攻击类别" />
        </Form.Item>
        <Form.Item name="attack_vector" label="攻击向量" rules={[{ required: true, message: '攻击向量描述不能为空' }]}>
          <Input maxLength={128} placeholder="如：开发者模式越狱" />
        </Form.Item>
        <Form.Item name="prompt_template" label="越狱提示模板" rules={[{ required: true, message: '越狱提示模板不能为空' }]}>
          <Input.TextArea rows={5} placeholder="发送给被测模型的越狱提示词" />
        </Form.Item>
        <Form.Item name="severity" label="严重度" rules={[{ required: true }]}>
          <Select options={SEVERITY_OPTIONS} />
        </Form.Item>
        <Form.Item name="source" label="来源" rules={[{ required: true, message: '来源为必填项' }]} extra="标注样本出处（如：自建、公开数据集名称）">
          <Input maxLength={64} placeholder="如：自建 / AdvBench" />
        </Form.Item>
        <Form.Item name="is_active" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
