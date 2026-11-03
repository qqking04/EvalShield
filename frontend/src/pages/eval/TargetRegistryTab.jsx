/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// §6.3 TargetRegistryTab.jsx — 被测系统注册（T12）：CRUD + 连通测试
import { useEffect, useState } from 'react'
import {
  Table, Button, Card, Space, Tag, Modal, Form, Input, Select, InputNumber, App, Popconfirm, Typography, Alert, Tooltip,
} from 'antd'
import { PlusOutlined, ReloadOutlined, ThunderboltOutlined, EditOutlined, GlobalOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { useAuth } from '../../auth'

const TYPE_OPTIONS = [
  { value: 'LLM_API', label: '大模型API' },
  { value: 'APP_API', label: '应用端点' },
  { value: 'INTERNAL_MODEL', label: '内置模型(演示)' },
]
const TYPE_COLOR = { LLM_API: 'cyan', APP_API: 'blue', INTERNAL_MODEL: 'default' }
const TYPE_LABEL = { LLM_API: '大模型API', APP_API: '应用端点', INTERNAL_MODEL: '内置模型(演示)' }
const PROTOCOL_OPTIONS = [
  { value: 'OPENAI', label: 'OPENAI 兼容' },
  { value: 'CUSTOM', label: 'CUSTOM 自定义' },
]

const DEFAULT_FORM = {
  target_type: 'LLM_API',
  protocol: 'OPENAI',
  chat_path: '/chat/completions',
  response_path: 'choices.0.message.content',
  timeout_sec: 30,
}

export default function TargetRegistryTab() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const [targetType, setTargetType] = useState('LLM_API')
  const [testResult, setTestResult] = useState(null)
  const [testTarget, setTestTarget] = useState(null)
  const [testing, setTesting] = useState(false)
  const { message, modal } = App.useApp()
  const { hasPerm } = useAuth()

  const load = async (p = page) => {
    setLoading(true)
    try {
      const d = await http.get('/targets', { params: { page: p, page_size: 10 } })
      const payload = d?.data || d
      setRows(payload.items || [])
      setTotal(payload.total || 0)
      setPage(p)
    } catch (e) {
      console.warn('[TargetRegistry] 被测系统列表加载失败', e?.message || e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(1) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue(DEFAULT_FORM)
    setTargetType('LLM_API')
    setModalOpen(true)
  }

  const openEdit = (row) => {
    setEditing(row)
    form.resetFields()
    form.setFieldsValue({
      name: row.name,
      target_type: row.target_type,
      base_url: row.base_url,
      chat_path: row.chat_path || '/chat/completions',
      protocol: row.protocol || 'OPENAI',
      auth_env: row.auth_env,
      request_template: row.request_template ? JSON.stringify(row.request_template, null, 2) : undefined,
      response_path: row.response_path,
      model: row.model,
      timeout_sec: row.timeout_sec ?? 30,
      remark: row.remark,
    })
    setTargetType(row.target_type)
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    const body = { ...values }
    if (body.target_type === 'INTERNAL_MODEL') {
      // 内置模型不采集 Base URL，但后端 base_url 必填：补占位地址，避免 422
      body.base_url = 'internal://default-model'
    }
    if (body.request_template && typeof body.request_template === 'string') {
      try { body.request_template = JSON.parse(body.request_template) } catch {
        message.error('request_template 不是合法 JSON')
        return
      }
    } else {
      delete body.request_template
    }
    const doSave = async () => {
      try {
        if (editing) {
          await http.put(`/targets/${editing.code}`, body)
          message.success(`被测系统 ${editing.code} 已更新`)
        } else {
          await http.post('/targets', body)
          message.success('被测系统创建成功')
        }
        setModalOpen(false)
        load(editing ? page : 1)
      } catch { /* 拦截器已提示 */ }
    }
    if (body.target_type === 'INTERNAL_MODEL') {
      modal.warning({
        title: '内置模型仅供演示',
        content: '内置模型评测结果反映的是 EvalShield 自身能力，非真实被测系统，请勿交付客户。',
        okText: '我已知悉，继续保存',
        onOk: doSave,
      })
    } else {
      await doSave()
    }
  }

  const remove = async (row) => {
    await http.delete(`/targets/${row.code}`)
    message.success('被测系统已删除')
    load()
  }

  const runTest = async (row) => {
    setTesting(true)
    setTestTarget(row)
    setTestResult(null)
    try {
      const r = await http.post(`/targets/${row.code}/test`)
      setTestResult(r)
      if (r && r.ok && r.skipped) message.info('连通测试不适用（预置输出靶机，不发起真实调用）')
      else if (r && r.ok) message.success(`连通测试成功，延迟 ${r.latency_ms}ms`)
      else message.error(`连通测试失败：${(r && r.error) || '未知错误'}`)
    } catch (e) {
      setTestResult({ ok: false, error: e?.message || '未知错误' })
    } finally {
      setTesting(false)
    }
  }

  const columns = [
    { title: '编号', dataIndex: 'code', width: 130 },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    {
      title: '类型', dataIndex: 'target_type', width: 130,
      render: (v) => <Tag color={TYPE_COLOR[v] || 'default'}>{TYPE_LABEL[v] || v}</Tag>,
    },
    { title: 'Base URL', dataIndex: 'base_url', ellipsis: true },
    { title: '协议', dataIndex: 'protocol', width: 90, render: (v) => v || '-' },
    {
      title: '密钥来源', dataIndex: 'auth_env', width: 140,
      render: (v) => (v ? <Tooltip title="环境变量名，密钥不落库"><Tag>{v}</Tag></Tooltip> : <span style={{ color: '#8b97a7' }}>无需</span>),
    },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (v) => <Tag color={v === 'ACTIVE' ? 'green' : 'default'}>{v === 'ACTIVE' ? '启用' : (v === 'DISABLED' ? '停用' : v)}</Tag>,
    },
    {
      title: '操作', width: 230, fixed: 'right',
      render: (_, row) => (
        <Space size={0}>
          {hasPerm('model:test') && (
            <Button type="link" size="small" icon={<ThunderboltOutlined />} loading={testing && testTarget?.code === row.code} onClick={() => runTest(row)}>连通测试</Button>
          )}
          {hasPerm('model:update') && (
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          )}
          {hasPerm('model:delete') && (
            <Popconfirm title="确认删除该被测系统？" onConfirm={() => remove(row)}>
              <Button type="link" size="small" danger>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Text type="secondary">
          被测系统（Target）是评测引擎的应答来源，与判定模型（Judge）彻底分离；未配置时引擎回退内置模型演示模式。
          注意：与项目详情「环境」Tab 不同——那是功能测试（UI/API/安全）的执行地址，两者互不替代。
        </Typography.Text>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
          {hasPerm('model:create') && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增被测系统</Button>
          )}
        </Space>
      </div>

      {testResult && testTarget && (
        <Alert
          type={testResult.skipped ? 'info' : (testResult.ok ? 'success' : 'error')}
          showIcon
          closable
          onClose={() => setTestResult(null)}
          message={`连通测试 - ${testTarget.name}（${testTarget.code}）：${testResult.skipped ? '不适用' : (testResult.ok ? '成功' : '失败')}${testResult.latency_ms != null && !testResult.skipped ? `，延迟 ${testResult.latency_ms}ms` : ''}`}
          description={
            testResult.ok
              ? (testResult.sample ? <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', fontSize: 12 }}>{String(testResult.sample).slice(0, 120)}</span> : (testResult.error || '连通正常'))
              : (testResult.error || '未知错误')
          }
        />
      )}

      <Card>
        <Table
          rowKey="code"
          loading={loading}
          columns={columns}
          dataSource={rows}
          scroll={{ x: 'max-content' }}
          pagination={{ current: page, total, pageSize: 10, showTotal: (t) => `共 ${t} 条`, onChange: (p) => load(p) }}
        />
      </Card>

      <Modal
        title={editing ? `编辑被测系统（${editing.code}）` : '新增被测系统'}
        open={modalOpen}
        onOk={submit}
        okText="保存"
        cancelText="取消"
        onCancel={() => setModalOpen(false)}
        destroyOnHidden
        width={720}
        styles={{ body: { maxHeight: '72vh', overflowY: 'auto' } }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：智能客服机器人" />
          </Form.Item>
          <Form.Item name="target_type" label="类型" rules={[{ required: true }]}>
            <Select
              options={TYPE_OPTIONS}
              onChange={(v) => {
                setTargetType(v)
                if (v === 'LLM_API') form.setFieldsValue({ response_path: 'choices.0.message.content' })
                else if (v === 'APP_API') form.setFieldsValue({ response_path: 'data.answer' })
              }}
            />
          </Form.Item>
          {targetType !== 'INTERNAL_MODEL' && (
            <>
              <Form.Item
                name="base_url"
                label="Base URL"
                rules={[
                  { required: true, message: '请输入 Base URL' },
                  { pattern: /^https?:\/\//, message: '必须以 http:// 或 https:// 开头' },
                ]}
              >
                <Input prefix={<GlobalOutlined />} placeholder="如 https://api.example.com/v1" />
              </Form.Item>
              {targetType === 'LLM_API' && (
                <Form.Item name="chat_path" label="对话路径">
                  <Input placeholder="/chat/completions" />
                </Form.Item>
              )}
              {targetType === 'LLM_API' && (
                <Form.Item name="model" label="被测模型名" extra="OpenAI 协议请求体 model 字段，如 qwen2.5:7b；留空则不发送">
                  <Input placeholder="如 qwen2.5:7b / gpt-4o-mini" />
                </Form.Item>
              )}
              <Form.Item name="protocol" label="协议">
                <Select options={PROTOCOL_OPTIONS} />
              </Form.Item>
              <Form.Item name="auth_env" label="密钥环境变量名" extra="环境变量名，密钥不落库，如 TARGET_API_KEY">
                <Input placeholder="如 TARGET_API_KEY" />
              </Form.Item>
              {targetType === 'APP_API' && (
                <Form.Item
                  name="request_template"
                  label="请求模板（JSON）"
                  rules={[
                    { required: true, message: 'APP_API 必须提供请求模板' },
                    { validator: (_, v) => {
                      if (!v) return Promise.resolve()
                      try { JSON.parse(v); return Promise.resolve() } catch { return Promise.reject(new Error('不是合法 JSON')) }
                    } },
                  ]}
                  extra="支持 {{prompt}} / {{history_json}} 占位符"
                >
                  <Input.TextArea rows={4} placeholder={'{\n  "question": "{{prompt}}",\n  "history": {{history_json}}\n}'} />
                </Form.Item>
              )}
              <Form.Item name="response_path" label="回答取值路径" extra="点路径取值，如 data.answer 或 choices.0.message.content">
                <Input placeholder="choices.0.message.content" />
              </Form.Item>
            </>
          )}
          {targetType === 'INTERNAL_MODEL' && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="内置模型仅供演示"
              description="评测结果反映的是 EvalShield 自身能力，非真实被测系统，请勿交付客户。"
            />
          )}
          <Form.Item name="timeout_sec" label="超时（秒）">
            <InputNumber min={1} max={600} style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
