/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
/*
 * EvalRunLaunchModal — 发起评测共享弹窗（ES10-P-03 断链修复 + ES10-P-01 事实基准入口）
 * 两个入口复用：
 *   1. EvalCenter「评测运行」Tab 的「发起评测」按钮（question_bank_id 用户自选）
 *   2. 题库详情页「用此库发起评测」（initialQuestionBank 预选并锁定）
 * 后端契约：POST /eval-runs，question_bank_id 必填（evals_core.py create_eval_run，
 *   缺失必 422 ES-RUN-LEGACY —— 本组件的前端必填校验即为此断链的修复点）。
 */
import { useEffect, useMemo, useState } from 'react'
import { Modal, Form, Select, InputNumber, AutoComplete, Alert, Space, Typography, App } from 'antd'
import { Link } from 'react-router-dom'
import http from '../api/http'

// 与后端 models.EVAL_RUN_TARGET_TYPES / EvalRunCreate pattern 对齐（#8 枚举收敛）
const TARGET_TYPE_OPTIONS = [
  { value: 'MODEL', label: '大模型' },
  { value: 'AGENT', label: 'Agent 应用' },
  { value: 'RAG', label: 'RAG 系统' },
  { value: 'API', label: 'API 服务' },
]

export default function EvalRunLaunchModal({ open, onClose, onSuccess, initialQuestionBank = null }) {
  const { message, modal } = App.useApp()
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')
  const [banks, setBanks] = useState([])          // 题库（必填样本源）
  const [sets, setSets] = useState([])            // 评测集（可选，保留原能力）
  const [modelConfigs, setModelConfigs] = useState([])
  const [factSources, setFactSources] = useState([]) // ES10-P-01 事实基准
  const [targetRows, setTargetRows] = useState([])   // /targets 注册表（被测对象标识建议，防手输错码静默回退演示模式）
  const bankId = Form.useWatch('question_bank_id', form)
  const judgeMode = Form.useWatch('judge_mode', form)
  const factSourceId = Form.useWatch('fact_source_id', form)

  useEffect(() => {
    if (!open) return
    form.resetFields()
    form.setFieldsValue({
      judge_mode: 'RULE',
      target_type: 'MODEL',
      ...(initialQuestionBank ? { question_bank_id: initialQuestionBank.id } : {}),
    })
    setFormError('')
    http.get('/question-banks', { params: { page_size: 100 } })
      .then((d) => setBanks(d.items || d || [])).catch(() => setBanks([]))
    http.get('/eval-sets', { params: { page_size: 100 } })
      .then((d) => setSets(d.items || [])).catch(() => setSets([]))
    http.get('/model-configs')
      .then((d) => setModelConfigs(((d.items || d) || []).filter((m) => m.status === 'ACTIVE')))
      .catch(() => setModelConfigs([]))
    // ES10-P-01：仅展示可用知识源（后端 status 小写枚举 active/disabled，大小写不敏感过滤）
    http.get('/fact-sources', { params: { page_size: 200 } })
      .then((d) => setFactSources((d.items || d || []).filter((s) => String(s.status || '').toLowerCase() !== 'disabled')))
      .catch(() => setFactSources([]))
    // 被测系统注册表（ACTIVE）：标识字段以下拉建议呈现，手输未知 code 会静默回退内置演示模式
    http.get('/targets', { params: { status: 'ACTIVE', page_size: 200 } })
      .then((d) => { const p = d?.data || d; setTargetRows(p.items || (Array.isArray(p) ? p : [])) })
      .catch(() => setTargetRows([]))
  }, [open, initialQuestionBank, form])

  const selectedBank = useMemo(
    () => banks.find((b) => b.id === bankId) || (initialQuestionBank?.id === bankId ? initialQuestionBank : null),
    [banks, bankId, initialQuestionBank],
  )

  const doSubmit = async (payload) => {
    setSubmitting(true)
    setFormError('')
    try {
      await http.post('/eval-runs', payload)
      message.success('评测已发起')
      onClose()
      onSuccess?.()
    } catch (err) {
      // 失败回显：422/400 等错误在表单顶部展示后端原始 message，不弹裸 toast
      setFormError(err?.message || '发起失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  const submit = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const payload = { ...values }
    if (payload.judge_mode !== 'MODEL' && payload.judge_mode !== 'HYBRID') delete payload.judge_model
    if (!payload.fact_source_id) delete payload.fact_source_id // 未选不传（P-01-A）
    if (!payload.sample_size) delete payload.sample_size       // 留空 = 全量（后端 ge=1）
    // 断链防护：注册表有数据时，手输未注册的 code 需二次确认（后端会静默回退内置演示模式，结果不可交付）
    if (targetRows.length > 0 && payload.target_id
      && !targetRows.some((t) => t.code === payload.target_id)) {
      modal.confirm({
        title: '被测对象标识未注册',
        content: `「${payload.target_id}」不在「被测系统」注册表中，评测将回退平台内置模型自问自答，结果不可交付。确认继续？`,
        okText: '仍然发起',
        cancelText: '返回修改',
        onOk: () => doSubmit(payload),
      })
      return
    }
    await doSubmit(payload)
  }

  return (
    <Modal
      title={initialQuestionBank ? `用题库「${initialQuestionBank.name}」发起评测` : '发起平台化评测'}
      open={open}
      okText="开始评测"
      cancelText="取消"
      onOk={submit}
      onCancel={onClose}
      confirmLoading={submitting}
      destroyOnHidden
      width={720}
      styles={{ body: { maxHeight: '72vh', overflowY: 'auto' } }}
    >
      {formError && <Alert type="error" showIcon message={formError} style={{ marginBottom: 12 }} />}
      <Form form={form} layout="vertical">
        <Typography.Title level={5} style={{ marginTop: 0 }}>题目来源</Typography.Title>
        <Form.Item name="question_bank_id" label="题库"
          rules={[{ required: true, message: '请选择题库（评测必须绑定题库）' }]}>
          <Select
            showSearch optionFilterProp="label" placeholder="选择题库"
            disabled={!!initialQuestionBank}   // 题库详情页入口：预选并锁定
            options={banks.map((b) => ({ value: b.id, label: `${b.name}（${b.question_count ?? 0} 题）` }))}
            notFoundContent={
              <Space direction="vertical" size={4}>
                <Typography.Text type="secondary">暂无题库</Typography.Text>
                <Link to="/question-banks">去新建题库</Link>
              </Space>
            }
          />
        </Form.Item>
        <Form.Item name="sample_size" label="抽题数量"
          tooltip="留空 = 全量执行"
          extra={selectedBank ? `该题库共 ${selectedBank.question_count ?? 0} 题` : ' '}>
          <InputNumber min={1} max={5000} style={{ width: 220 }} placeholder="留空 = 全量" />
        </Form.Item>
        <Form.Item name="eval_set_id" label="评测集（可选）">
          <Select allowClear placeholder="不用评测集"
            options={sets.map((s) => ({ value: s.id, label: `${s.code} - ${s.name}` }))} />
        </Form.Item>

        <Typography.Title level={5}>被测与执行</Typography.Title>
        <Space wrap size={12}>
          <Form.Item name="target_type" label="被测对象类型" rules={[{ required: true }]}>
            <Select style={{ width: 180 }} options={TARGET_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="target_id" label="被测对象标识" rules={[{ required: true }]}
            extra={targetRows.length > 0
              ? '可从「被测系统」注册表选择；手输未注册的 code 将回退内置演示模式（结果不可交付）'
              : '未配置注册表时手输标识将回退内置演示模式（结果不可交付），建议先到「被测系统」页注册'}
          >
            <AutoComplete
              style={{ width: 260 }}
              placeholder="选择已注册被测系统，或输入模型 / Agent 编码"
              options={targetRows.map((t) => ({ value: t.code, label: `${t.code} — ${t.name}` }))}
              filterOption={(input, option) => (option?.value || '').toLowerCase().includes(input.toLowerCase())
                || (option?.label || '').toLowerCase().includes(input.toLowerCase())}
            />
          </Form.Item>
        </Space>
        <Form.Item name="model_gateway" label="主模型网关">
          <Select allowClear style={{ width: 360 }} placeholder="留空使用项目默认网关"
            options={modelConfigs.map((m) => ({ value: m.code, label: `${m.name}（${m.code}）` }))} />
        </Form.Item>
        {/* ES10-P-01-A：事实基准（知识源） */}
        <Form.Item name="fact_source_id" label="事实基准（知识源）">
          <Select allowClear style={{ width: 360 }} placeholder="不选 = 仅自我一致性检测"
            options={factSources.map((s) => ({ value: s.id, label: s.name }))}
            notFoundContent={
              <Space direction="vertical" size={4}>
                <Typography.Text type="secondary">暂无知识源</Typography.Text>
                <Link to="/targets?tab=fact-sources">去配置知识源</Link>
              </Space>
            } />
        </Form.Item>
        {selectedBank && factSourceId && (
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: -8 }}>
            评测时将调用该知识源检索参考答案；题面已带参考答案的优先题面。
          </Typography.Paragraph>
        )}

        <Typography.Title level={5}>判定</Typography.Title>
        <Form.Item name="judge_mode" label="裁判模式" rules={[{ required: true }]} initialValue="RULE">
          <Select style={{ width: 220 }} options={[
            { value: 'RULE', label: '规则判定' },
            { value: 'MODEL', label: '模型裁判' },
            { value: 'HYBRID', label: '规则 + 模型' },
          ]} />
        </Form.Item>
        {(judgeMode === 'MODEL' || judgeMode === 'HYBRID') && (
          <Form.Item name="judge_model" label="裁判模型"
            tooltip="即各评测引擎参数中的「判定模型」（Judge）：模型裁判 / 规则+模型 模式下用于打分的对话模型">
            <Select allowClear placeholder="选择模型配置作为裁判" style={{ width: 360 }}
              options={modelConfigs.map((m) => ({ value: m.code, label: `${m.name}（${m.code}）` }))} />
          </Form.Item>
        )}
      </Form>
    </Modal>
  )
}
