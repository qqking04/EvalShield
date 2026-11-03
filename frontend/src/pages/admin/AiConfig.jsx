/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Alert, App, Button, Card, Col, Descriptions, Empty, Form, Input, InputNumber, Modal,
  Popconfirm, Radio, Row, Select, Space, Switch, Table, Tag, Typography,
} from 'antd'
import {
  CheckCircleOutlined, EditOutlined, PlusOutlined, ReloadOutlined,
  RobotOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import http from '../../api/http'
import { useAuth } from '../../auth'

const PROVIDER_OPTIONS = [
  { value: 'LOCAL', label: '本地大模型（Ollama / vLLM，数据不出网）' },
  { value: 'DEEPSEEK', label: 'DeepSeek（公有云）' },
  { value: 'DASHSCOPE', label: '通义千问（公有云）' },
  { value: 'OPENAI', label: 'OpenAI（公有云）' },
  { value: 'BAIDU', label: '百度千帆（公有云）' },
  { value: 'VOLCENGINE', label: '火山方舟（公有云）' },
]

const PROVIDER_COLOR = {
  LOCAL: 'orange', DEEPSEEK: 'cyan', DASHSCOPE: 'purple',
  OPENAI: 'green', BAIDU: 'red', VOLCENGINE: 'blue',
}

const PROVIDER_LABEL = {
  LOCAL: '本地模型', DEEPSEEK: 'DeepSeek', DASHSCOPE: '通义千问',
  OPENAI: 'OpenAI', BAIDU: '百度千帆', VOLCENGINE: '火山方舟',
}

// AI 配置管理：默认模型（本地大模型优先）+ 其它 AI 接入管理
export default function AiConfig() {
  const { message } = App.useApp()
  const { hasPerm } = useAuth()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const [testingCode, setTestingCode] = useState(null)
  const [testResult, setTestResult] = useState(null)
  const [testOpen, setTestOpen] = useState(false)
  const [testForm] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const d = await http.get('/model-configs', { params: { page: 1, page_size: 100 } })
      const payload = d?.data || d
      setRows(payload.items || [])
    } catch (e) {
      message.error('AI 配置列表加载失败：' + (e?.message || e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const chatDefaults = useMemo(
    () => rows.filter((r) => r.is_default && (r.usage || 'CHAT') === 'CHAT' && r.status === 'ACTIVE'),
    [rows],
  )
  const embDefaults = useMemo(
    () => rows.filter((r) => r.is_default && r.usage === 'EMBEDDING' && r.status === 'ACTIVE'),
    [rows],
  )
  const localCount = useMemo(() => rows.filter((r) => r.provider === 'LOCAL').length, [rows])
  const cloudCount = useMemo(() => rows.filter((r) => r.provider !== 'LOCAL').length, [rows])

  // 设为默认：同用途先清除旧默认位（后端双默认 409 契约），再置新默认
  const setDefault = async (row) => {
    const usage = row.usage || 'CHAT'
    const olds = rows.filter(
      (r) => r.is_default && (r.usage || 'CHAT') === usage && r.code !== row.code,
    )
    try {
      for (const o of olds) {
        await http.put(`/model-configs/${o.code}`, { is_default: false })
      }
      await http.put(`/model-configs/${row.code}`, { is_default: true })
      message.success(`已将「${row.name}」设为 ${usage} 默认模型`)
      load()
    } catch (e) {
      /* 错误已由拦截器提示 */
    }
  }

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({
      provider: 'LOCAL',
      usage: 'CHAT',
      base_url: 'http://127.0.0.1:11434/v1',
      model: 'qwen2.5:7b',
      timeout_sec: 120,
      max_tokens: 2048,
      temperature: 0.2,
      is_default: false,
    })
    setModalOpen(true)
  }

  const openEdit = (row) => {
    setEditing(row)
    form.resetFields()
    form.setFieldsValue({
      name: row.name,
      provider: row.provider,
      model: row.model,
      base_url: row.base_url || undefined,
      api_key_env: row.api_key_env || undefined,
      timeout_sec: row.timeout_sec,
      max_tokens: row.max_tokens,
      temperature: row.temperature,
      usage: row.usage || 'CHAT',
      seed: row.seed ?? undefined,
      status: row.status,
    })
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    try {
      if (editing) {
        const patch = {}
        Object.keys(values).forEach((k) => {
          if (values[k] !== undefined && values[k] !== null && values[k] !== '') patch[k] = values[k]
        })
        await http.put(`/model-configs/${editing.code}`, patch)
        message.success(`AI 接入「${editing.name}」已更新`)
      } else {
        await http.post('/model-configs', values)
        message.success('AI 接入创建成功')
      }
    } catch (e) {
      return
    }
    setModalOpen(false)
    load()
  }

  const remove = async (row) => {
    await http.delete(`/model-configs/${row.code}`)
    message.success('AI 接入已删除')
    load()
  }

  const openTest = (row) => {
    setTestingCode(row.code)
    setTestResult(null)
    testForm.resetFields()
    setTestOpen(true)
  }

  const runTest = async () => {
    const values = testForm.getFieldsValue()
    try {
      const r = await http.post(`/model-configs/${testingCode}/test`, {
        api_key: values.api_key || undefined,
      })
      setTestResult(r)
      if (r && r.ok) message.success(`连接成功，延迟 ${r.latency_ms}ms`)
      else message.error(`连接失败：${(r && r.error) || '未知错误'}`)
    } catch (e) {
      /* 拦截器已提示 */
    }
  }

  const columns = [
    { title: '编号', dataIndex: 'code', width: 170 },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    {
      title: '类型', dataIndex: 'provider', width: 120,
      render: (v) => (
        <Tag color={PROVIDER_COLOR[v] || 'default'}>
          {v === 'LOCAL' ? <RobotOutlined /> : <ThunderboltOutlined />} {PROVIDER_LABEL[v] || v}
        </Tag>
      ),
    },
    {
      title: '用途', dataIndex: 'usage', width: 110,
      render: (v) => (v === 'EMBEDDING'
        ? <Tag color="cyan">EMBEDDING 向量</Tag>
        : <Tag color="blue">CHAT 对话</Tag>),
    },
    { title: '模型', dataIndex: 'model', width: 180 },
    { title: '端点', dataIndex: 'base_url', ellipsis: true, render: (v) => v || '（提供商默认）' },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (v) => <Tag color={v === 'ACTIVE' ? 'green' : 'default'}>{v === 'ACTIVE' ? '启用' : '停用'}</Tag>,
    },
    {
      title: '默认', width: 90,
      render: (_, row) => (row.is_default
        ? <Tag color="green" icon={<CheckCircleOutlined />}>默认</Tag>
        : (hasPerm('model:update')
          ? <Button type="link" size="small" onClick={() => setDefault(row)}>设为默认</Button>
          : '-')),
    },
    {
      title: '操作', width: 220,
      render: (_, row) => (
        <Space size={0}>
          {hasPerm('model:test') && (
            <Button type="link" size="small" icon={<ThunderboltOutlined />} onClick={() => openTest(row)}>测试连接</Button>
          )}
          {hasPerm('model:update') && (
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          )}
          {hasPerm('model:delete') && !row.is_system && (
            <Popconfirm title="确认删除该 AI 接入？" onConfirm={() => remove(row)}>
              <Button type="link" size="small" danger>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Title level={4} style={{ margin: 0 }}>AI 配置管理</Typography.Title>
      <Alert
        type="info"
        showIcon
        message="默认使用本地大模型（Ollama / vLLM，数据不出网）；DeepSeek、通义千问等公有云 AI 可随时接入并一键切换默认。API Key 不落库，仅保存环境变量名。"
      />
      <Row gutter={16}>
        <Col span={8}>
          <Card size="small" title="当前默认对话模型">
            {chatDefaults.length ? (
              <Descriptions column={1} size="small">
                <Descriptions.Item label="名称">{chatDefaults[0].name}</Descriptions.Item>
                <Descriptions.Item label="提供商">
                  <Tag color={PROVIDER_COLOR[chatDefaults[0].provider]}>{PROVIDER_LABEL[chatDefaults[0].provider] || chatDefaults[0].provider}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="模型">{chatDefaults[0].model}</Descriptions.Item>
                <Descriptions.Item label="端点">{chatDefaults[0].base_url || '默认'}</Descriptions.Item>
              </Descriptions>
            ) : <Empty description="未设置默认对话模型" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title="当前默认向量模型">
            {embDefaults.length ? (
              <Descriptions column={1} size="small">
                <Descriptions.Item label="名称">{embDefaults[0].name}</Descriptions.Item>
                <Descriptions.Item label="模型">{embDefaults[0].model}</Descriptions.Item>
              </Descriptions>
            ) : <Empty description="未设置默认向量模型" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title="接入概况">
            <Space direction="vertical">
              <Typography.Text>本地模型：<Typography.Text strong>{localCount}</Typography.Text> 个</Typography.Text>
              <Typography.Text>公有云 AI：<Typography.Text strong>{cloudCount}</Typography.Text> 个</Typography.Text>
              <Typography.Text>合计：<Typography.Text strong>{rows.length}</Typography.Text> 个接入</Typography.Text>
            </Space>
          </Card>
        </Col>
      </Row>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          {hasPerm('model:create') && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>接入新 AI</Button>
          )}
        </Space>
      </div>
      <Card>
        <Table rowKey="code" loading={loading} columns={columns} dataSource={rows}
          scroll={{ x: 'max-content' }} pagination={false} />
      </Card>

      <Modal
        title={editing ? `编辑 AI 接入（${editing.code}）` : '接入新 AI'}
        open={modalOpen} onOk={submit} okText="保存" cancelText="取消"
        onCancel={() => setModalOpen(false)} destroyOnHidden width={760}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="接入名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：本地 Qwen2.5 / DeepSeek 生产接入" />
          </Form.Item>
          <Form.Item name="provider" label="AI 提供商" rules={[{ required: true }]}>
            <Select options={PROVIDER_OPTIONS} />
          </Form.Item>
          <Form.Item name="model" label="模型名称" rules={[{ required: true, message: '请输入模型名称' }]}>
            <Input placeholder="如 qwen2.5:7b / deepseek-chat / gpt-4o" />
          </Form.Item>
          <Form.Item name="base_url" label="端点地址" tooltip="本地 Ollama 填 http://127.0.0.1:11434/v1；公有云留空使用默认地址">
            <Input placeholder="http://127.0.0.1:11434/v1（本地）或留空（公有云默认）" />
          </Form.Item>
          <Form.Item name="api_key_env" label="API Key 环境变量名" tooltip="密钥本体保存在服务端环境变量，不写入数据库；本地模型可留空">
            <Input placeholder="如 DEEPSEEK_API_KEY（本地模型留空）" />
          </Form.Item>
          <Form.Item name="usage" label="用途">
            <Radio.Group options={[
              { value: 'CHAT', label: 'CHAT 对话/判定' },
              { value: 'EMBEDDING', label: 'EMBEDDING 向量' },
            ]} />
          </Form.Item>
          <Space size={16} style={{ width: '100%' }}>
            <Form.Item name="timeout_sec" label="超时（秒）" style={{ width: 140 }}>
              <InputNumber min={5} max={600} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="max_tokens" label="最大 Tokens" style={{ width: 150 }}>
              <InputNumber min={16} max={32768} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="temperature" label="温度" style={{ width: 120 }}>
              <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="seed" label="随机种子" style={{ width: 140 }}>
              <InputNumber min={0} max={2147483647} style={{ width: '100%' }} placeholder="判定建议 42" />
            </Form.Item>
          </Space>
          {editing && (
            <Form.Item name="status" label="状态">
              <Select style={{ width: 140 }} options={[
                { value: 'ACTIVE', label: '启用' },
                { value: 'DISABLED', label: '停用' },
              ]} />
            </Form.Item>
          )}
        </Form>
      </Modal>

      <Modal
        title={`测试连接 - ${testingCode || ''}`}
        open={testOpen} onOk={runTest} onCancel={() => setTestOpen(false)}
        okText="开始测试" cancelText="取消" destroyOnHidden width={560}
      >
        <Alert type="warning" showIcon style={{ marginBottom: 16 }}
          message="将发起一次真实最小请求验证连通性，公有云可能产生少量费用。" />
        <Form form={testForm} layout="vertical">
          <Form.Item name="api_key" label="临时 API Key（可选）" tooltip="留空使用环境变量密钥；填写仅本次测试，不保存">
            <Input.Password
              placeholder="不修改则留空"
              onFocus={() => testForm.setFieldsValue({ api_key: '' })}
            />
          </Form.Item>
        </Form>
        {testResult && (
          <Alert type={testResult.ok ? 'success' : 'error'} showIcon
            message={testResult.ok ? '连接成功' : '连接失败'}
            description={testResult.ok
              ? `模型：${testResult.model || '-'}，延迟：${testResult.latency_ms}ms`
              : `${testResult.error || '未知错误'}（${testResult.latency_ms}ms）`} />
        )}
      </Modal>
    </Space>
  )
}
