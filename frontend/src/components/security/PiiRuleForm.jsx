/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// PII 规则新增/编辑表单（Modal 形态，产品优化3 §U2）
// 附带「规则试算」：前端本地用 RegExp 试匹配，命中结果必须脱敏展示，绝不回显完整明文。
import { useEffect, useState } from 'react'
import { Modal, Form, Input, Select, Switch, Button, Alert, Tag, Typography, Divider, Space } from 'antd'
import http from '../../api/http'

export const PII_TYPE_OPTIONS = [
  { value: 'ID_CARD', label: '身份证号（ID_CARD）' },
  { value: 'PHONE', label: '手机号（PHONE）' },
  { value: 'BANK_CARD', label: '银行卡号（BANK_CARD）' },
  { value: 'EMAIL', label: '邮箱（EMAIL）' },
  { value: 'API_KEY', label: 'API 密钥（API_KEY）' },
  { value: 'ADDRESS', label: '住址（ADDRESS）' },
  { value: 'PASSWORD', label: '口令（PASSWORD）' },
  { value: 'OTHER', label: '其他（OTHER）' },
]

export const SEVERITY_OPTIONS = [
  { value: 'CRITICAL', label: '严重 CRITICAL' },
  { value: 'HIGH', label: '高危 HIGH' },
  { value: 'MEDIUM', label: '中危 MEDIUM' },
  { value: 'LOW', label: '低危 LOW' },
]

// 命中脱敏：保留首尾各 2 字符，中间打码（短串保留首 1 尾 1）
export function maskMatch(text) {
  if (!text) return ''
  if (text.length <= 6) return (text[0] || '') + '*'.repeat(Math.max(text.length - 2, 1)) + (text[text.length - 1] || '')
  return text.slice(0, 2) + '*'.repeat(text.length - 4) + text.slice(-2)
}

// 本地试算：返回 { ok, error, count, masked } —— masked 已脱敏，不含完整明文
export function tryMatch(pattern, sample) {
  if (!pattern || !sample) return { ok: false, error: '', count: 0, masked: [] }
  let re
  try {
    re = new RegExp(pattern, 'g')
  } catch (e) {
    return { ok: false, error: e?.message || '正则表达式非法', count: 0, masked: [] }
  }
  const hits = []
  let m
  let guard = 0
  while ((m = re.exec(sample)) !== null && guard < 100) {
    if (m[0] === '') { re.lastIndex += 1; continue } // 防空匹配死循环
    hits.push(maskMatch(m[0]))
    guard += 1
  }
  return { ok: true, error: '', count: hits.length, masked: hits }
}

export default function PiiRuleForm({ open, editing, onClose, onSaved }) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [trialSample, setTrialSample] = useState('')
  const [trial, setTrial] = useState(null)

  useEffect(() => {
    if (!open) return
    form.resetFields()
    setTrialSample('')
    setTrial(null)
    if (editing) {
      form.setFieldsValue(editing)
    } else {
      form.setFieldsValue({ pii_type: 'PHONE', severity: 'HIGH', is_active: true })
    }
  }, [open, editing, form])

  const runTrial = () => {
    const pattern = form.getFieldValue('regex_pattern') || ''
    setTrial(tryMatch(pattern, trialSample))
  }

  const submit = async () => {
    let values
    try {
      values = await form.validateFields()
    } catch {
      // 校验失败：antd 已在字段上显示红字提示，静默返回，避免 unhandled rejection
      return
    }
    setSaving(true)
    try {
      if (editing) {
        await http.put(`/pii/rules/${editing.id}`, values)
      } else {
        await http.post('/pii/rules', values)
      }
      onSaved(editing)
      onClose()
    } catch (e) {
      /* 网络/业务错误已由 http 拦截器统一提示 */
      console.warn('[PiiRuleForm] save failed', e?.message || e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={editing ? `编辑 PII 规则 #${editing.id}` : '新增 PII 规则'}
      open={open}
      onOk={submit}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      onCancel={onClose}
      destroyOnHidden
      width={640}
      styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="pii_type" label="PII 类型" rules={[{ required: true }]}>
          <Select options={PII_TYPE_OPTIONS} placeholder="选择 PII 类型" />
        </Form.Item>
        <Form.Item name="rule_name" label="规则名称" rules={[{ required: true, message: '规则名称不能为空' }]}>
          <Input maxLength={128} placeholder="如：中国大陆手机号" />
        </Form.Item>
        <Form.Item
          name="regex_pattern"
          label="正则表达式"
          rules={[
            { required: true, message: '正则表达式不能为空' },
            {
              validator: (_, v) => {
                if (!v) return Promise.resolve()
                try { new RegExp(v); return Promise.resolve() } catch { return Promise.reject(new Error('正则表达式非法')) }
              },
            },
          ]}
        >
          <Input.TextArea rows={2} placeholder="如：1[3-9]\\d{9}" style={{ fontFamily: 'Consolas, monospace' }} />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} placeholder="规则用途说明（可选）" />
        </Form.Item>
        <Form.Item name="severity" label="严重度" rules={[{ required: true }]}>
          <Select options={SEVERITY_OPTIONS} />
        </Form.Item>
        <Form.Item
          name="context_keywords"
          label="上下文关键词（可选）"
          extra="正则命中位置前后 30 字符窗口内含任一关键词才计入违规；留空 = 不校验（与旧版行为一致）"
        >
          <Select
            mode="tags"
            open={false}
            tokenSeparators={[',', '，', ' ']}
            placeholder="输入后回车确认，如：qq、号码、联系"
          />
        </Form.Item>
        <Form.Item name="is_active" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>

      <Divider style={{ margin: '8px 0 12px' }}>规则试算</Divider>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        粘贴测试文本，本地用当前正则试匹配。命中结果自动脱敏展示（中间打码），不会回显完整明文。
      </Typography.Paragraph>
      <Input.TextArea
        rows={3}
        value={trialSample}
        onChange={(e) => setTrialSample(e.target.value)}
        placeholder="如：我的手机号是13812345678，邮箱 a@b.com"
      />
      <Button style={{ marginTop: 8 }} onClick={runTrial} disabled={!trialSample}>试算</Button>
      {trial && (
        <div style={{ marginTop: 12 }}>
          {trial.error ? (
            <Alert type="error" showIcon message={`正则非法：${trial.error}`} />
          ) : trial.count === 0 ? (
            <Alert type="info" showIcon message="未命中任何内容" />
          ) : (
            <Alert
              type="warning"
              showIcon
              message={`命中 ${trial.count} 处（已脱敏）`}
              description={
                <Space wrap size={4}>
                  {trial.masked.map((v, i) => (
                    <Tag key={i} color="orange" style={{ fontFamily: 'Consolas, monospace' }}>{v}</Tag>
                  ))}
                </Space>
              }
            />
          )}
        </div>
      )}
    </Modal>
  )
}
