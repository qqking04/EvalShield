/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useState } from 'react'
import {
  Table, Button, Card, Space, Tag, Modal, Form, Input, Select, InputNumber, Switch, App, Popconfirm, Typography, Alert,
  Tabs, Row, Col,
} from 'antd'
import { PlusOutlined, ReloadOutlined, ThunderboltOutlined, EditOutlined, DownloadOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import http from '../api/http'
import { fmtTime } from '../utils'
import { useAuth } from '../auth'
import TargetRegistryTab from './eval/TargetRegistryTab'
import FactSourcesTab from './eval/FactSourcesTab'

const PROVIDER_OPTIONS = [
  { value: 'BAIDU', label: '百度千帆（公有云）' },
  { value: 'OPENAI', label: 'OpenAI（公有云）' },
  { value: 'VOLCENGINE', label: '火山方舟（公有云）' },
  { value: 'DASHSCOPE', label: '通义千问（公有云）' },
  { value: 'DEEPSEEK', label: 'DeepSeek（公有云）' },
  { value: 'LOCAL', label: '本地部署模型（Ollama/vLLM，GPU）' },
]

const PROVIDER_COLOR = {
  BAIDU: 'red', OPENAI: 'green', VOLCENGINE: 'blue', DASHSCOPE: 'purple', DEEPSEEK: 'cyan', LOCAL: 'orange',
}

const PROVIDER_LABEL = {
  BAIDU: '百度千帆', OPENAI: 'OpenAI', VOLCENGINE: '火山方舟', DASHSCOPE: '通义千问', DEEPSEEK: 'DeepSeek', LOCAL: '本地模型',
}

const STATUS_OPTIONS = [
  { value: 'ACTIVE', label: '启用' },
  { value: 'DISABLED', label: '停用' },
]

const EMPTY_FORM = {
  provider: 'LOCAL',
  timeout_sec: 60,
  max_tokens: 2048,
  temperature: 0.2,
  is_default: false,
  usage: 'CHAT',
}

function ModelConfigsTab() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null) // null=新增, {code,name,...}=编辑
  const [form] = Form.useForm()
  const [testOpen, setTestOpen] = useState(false)
  const [testForm] = Form.useForm()
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [testTarget, setTestTarget] = useState(null)
  const [ollamaModels, setOllamaModels] = useState([])
  const [pullingOllama, setPullingOllama] = useState(false)
  const [statsMap, setStatsMap] = useState({})
  const { message } = App.useApp()
  const { hasPerm } = useAuth()

  const load = async (p = page) => {
    setLoading(true)
    try {
      const d = await http.get('/model-configs', { params: { page: p, page_size: 10 } })
      const payload = d?.data || d
      setRows(payload.items || [])
      setTotal(payload.total || 0)
      setPage(p)
    } catch (e) {
      console.warn('[Models] 模型列表加载失败', e?.message || e)
      message.error('模型列表加载失败，请检查后端服务')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const loadStats = async (code, force = false) => {
    if (!code) return
    const cached = statsMap[code]
    if (!force && cached && Date.now() - (cached._ts || 0) < 30000) return
    try {
      const data = await http.get(`/model-configs/${code}/stats`)
      setStatsMap((m) => ({ ...m, [code]: { ...(data || {}), _ts: Date.now() } }))
    } catch (e) { console.warn('[Models] stats 加载失败', e?.message || e) }
  }

  useEffect(() => {
    if (!rows || !rows.length) return
    rows.forEach((r) => loadStats(r.code))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows])

  const openCreate = () => {
    setEditing(null)
    setOllamaModels([])
    form.resetFields()
    form.setFieldsValue(EMPTY_FORM)
    setModalOpen(true)
  }

  const openEdit = (row) => {
    setEditing(row)
    setOllamaModels([])
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
      is_default: row.is_default,
      status: row.status,
      usage: row.usage || 'CHAT',
      seed: row.seed ?? undefined,
      input_price_per_mtok: row.input_price_per_mtok ?? undefined,
      output_price_per_mtok: row.output_price_per_mtok ?? undefined,
    })
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    try {
      if (editing) {
        // 仅提交有值的字段（编辑时允许部分更新）
        const patch = {}
        Object.keys(values).forEach((k) => {
          if (values[k] !== undefined && values[k] !== null && values[k] !== '') patch[k] = values[k]
        })
        await http.put(`/model-configs/${editing.code}`, patch)
        message.success(`模型配置 ${editing.code} 已更新`)
      } else {
        await http.post('/model-configs', values)
        message.success('模型配置创建成功')
      }
    } catch (e) {
      if ((e?.message || '').includes('默认')) message.error('同用途仅允许一个默认模型')
      return
    }
    setModalOpen(false)
    load()
  }

  const remove = async (row) => {
    await http.delete(`/model-configs/${row.code}`)
    message.success('模型配置已删除')
    load()
  }

  const openTest = (row) => {
    setTestTarget(row)
    setTestResult(null)
    testForm.resetFields()
    setTestOpen(true)
  }

  const runTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const values = await testForm.validateFields()
      const r = await http.post(`/model-configs/${testTarget.code}/test`, {
        api_key: values.api_key || undefined,
      })
      setTestResult(r)
      if (r && r.ok) message.success(`连接成功，延迟 ${r.latency_ms}ms`)
      else message.error(`连接失败：${(r && r.error) || '未知错误'}`)
    } finally {
      setTesting(false)
    }
  }

  const pullOllamaModels = async () => {
    const code = editing?.code || form.getFieldValue('code')
    if (!code) {
      message.warning('请先填写配置编号后再拉取 Ollama 模型列表')
      return
    }
    setPullingOllama(true)
    try {
      const r = await http.post(`/model-configs/${code}/pull-ollama`)
      const models = (r && r.models) || (r && r.items) || []
      if (Array.isArray(models) && models.length > 0) {
        setOllamaModels(models)
        message.success(`成功拉取 ${models.length} 个本地模型`)
      } else {
        setOllamaModels([])
        message.warning('本地 Ollama 未返回任何模型，请先在 Ollama 中 pull 模型')
      }
    } catch (e) {
      setOllamaModels([])
      // 静默提示，不弹红色 error
      message.info('本地 Ollama 服务未启动，请先运行 ollama serve 后重试')
    } finally {
      setPullingOllama(false)
      load() // P2-7: 刷新外层模型列表，反映本地 Ollama 新注册的模型
    }
  }

  const columns = [
    { title: '配置编号', dataIndex: 'code', width: 170 },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    {
      title: '用途', dataIndex: 'usage', width: 110,
      render: (v) => (v === 'EMBEDDING'
        ? <Tag color="cyan">EMBEDDING 向量</Tag>
        : <Tag color="blue">CHAT 对话</Tag>),
    },
    {
      title: '提供商', dataIndex: 'provider', width: 110,
      render: (v) => <Tag color={PROVIDER_COLOR[v] || 'default'}>{PROVIDER_LABEL[v] || v}</Tag>,
    },
    { title: '模型', dataIndex: 'model', width: 180 },
    { title: '基础地址', dataIndex: 'base_url', ellipsis: true, render: (v) => v || '（默认）' },
    {
      title: '密钥来源', dataIndex: 'api_key_env', width: 130,
      render: (v) => (v ? <Tag>{v}</Tag> : <span style={{ color: '#999' }}>环境变量</span>),
    },
    {
      title: '参数', width: 180,
      render: (_, row) => (
        <span style={{ fontSize: 12, color: '#555' }}>
          temp {row.temperature} / max {row.max_tokens} / {row.timeout_sec}s
        </span>
      ),
    },
    {
      title: '默认', dataIndex: 'is_default', width: 70,
      render: (v) => (v ? <Tag color="green">默认</Tag> : '-'),
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v) => <Tag color={v === 'ACTIVE' ? 'green' : 'default'}>{v === 'ACTIVE' ? '启用' : (v === 'DISABLED' ? '停用' : v)}</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', width: 155, render: (v) => fmtTime(v) },
    {
      title: '用量统计',
      width: 260,
      render: (_, row) => {
        const s = statsMap[row.code]
        if (!s) return <Typography.Text type="secondary" style={{ fontSize: 12 }}>加载中...</Typography.Text>
        const calls = s.call_count || 0
        const succ = s.success_count || 0
        const succRate = calls > 0 ? ((succ / calls) * 100).toFixed(1) : '0.0'
        return (
          <Space size={14} style={{ fontSize: 12 }}>
            <span>调用 <Typography.Text type="success">{calls}</Typography.Text></span>
            <span>
              成功率{' '}
              <Typography.Text type={s.fail_count > 0 ? 'warning' : 'success'}>
                {succRate}%
              </Typography.Text>
            </span>
            <span>费用 <Typography.Text>¥{(s.total_cost || 0).toFixed(2)}</Typography.Text></span>
          </Space>
        )
      },
    },
    {
      title: '操作',
      width: 240,
      render: (_, row) => (
        <Space size={0}>
          <Button type="link" size="small" icon={<ReloadOutlined />} onClick={() => loadStats(row.code, true)}>刷新统计</Button>
          {hasPerm('model:update') && (
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          )}
          {hasPerm('model:test') && (
            <Button type="link" size="small" icon={<ThunderboltOutlined />} onClick={() => openTest(row)}>测试连接</Button>
          )}
          {hasPerm('model:delete') && (
            <Popconfirm title="确认删除该配置？" onConfirm={() => remove(row)}>
              <Button type="link" size="small" danger>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          {hasPerm('model:create') && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增模型配置</Button>
          )}
        </Space>
      </div>
      <Alert
        type="info"
        showIcon
        message="接入说明"
        description="支持本地部署大模型（Ollama / vLLM 等 OpenAI 兼容端点）与公有云大模型（百度千帆 / OpenAI / 火山方舟 / 通义千问）。API Key 不落库：仅保存环境变量名，密钥配置在服务端环境变量中；测试连接时可临时输入密钥进行连通性验证。"
      />
      <Card>
        <Table rowKey="code" loading={loading} columns={columns} dataSource={rows} scroll={{ x: 'max-content' }} pagination={{ current: page, total, pageSize: 10, showTotal: (t) => `共 ${t} 条`, showQuickJumper: true, onChange: (p) => load(p) }} />
      </Card>

      <Modal
        title={editing ? `编辑模型配置（${editing.code}）` : '新增模型配置'}
        open={modalOpen}
        onOk={submit}
        okText="保存"
        cancelText="取消"
        onCancel={() => setModalOpen(false)}
        destroyOnHidden
        width={900}
        styles={{ body: { maxHeight: '72vh', overflowY: 'auto' } }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="配置名称" rules={[{ required: true, message: '请输入配置名称' }]}>
            <Input placeholder="如：本地 Ollama 网关 / 百度文心旗舰" />
          </Form.Item>
          <Form.Item name="provider" label="提供商" rules={[{ required: true }]}>
            <Select options={PROVIDER_OPTIONS} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.provider !== cur.provider}>
            {({ getFieldValue }) => {
              const isLocal = getFieldValue('provider') === 'LOCAL'
              return isLocal ? (
                <Form.Item label="Ollama 本地模型">
                  <Button
                    icon={<DownloadOutlined />}
                    loading={pullingOllama}
                    onClick={pullOllamaModels}
                  >
                    拉取本地 Ollama 模型列表
                  </Button>
                  {ollamaModels.length > 0 && (
                    <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                      已加载 {ollamaModels.length} 个候选
                    </Typography.Text>
                  )}
                </Form.Item>
              ) : null
            }}
          </Form.Item>
          <Form.Item name="model" label="模型名称" rules={[{ required: true, message: '请输入模型名称' }]}>
            <Select
              allowCreate
              placeholder="如 ernie-4.0-turbo / gpt-4o / qwen2.5-72b / qwen-max"
              options={ollamaModels.map((m) => ({ value: m, label: m }))}
            />
          </Form.Item>
          <Form.Item
            name="base_url"
            label="基础地址（可选）"
            tooltip="留空使用提供商默认地址；本地模型填如 http://127.0.0.1:11434/v1（Ollama）或 http://127.0.0.1:8000/v1（vLLM）"
          >
            <Input placeholder="留空使用提供商默认地址；本地模型填 Ollama/vLLM 端点" />
          </Form.Item>
          <Form.Item
            name="api_key_env"
            label="API Key 环境变量名"
            tooltip="只保存环境变量名（如 LLM_API_KEY），密钥本体配置在服务端环境变量，不写入数据库"
          >
            <Input placeholder="如 LLM_API_KEY（本地模型可留空）" />
          </Form.Item>
          <Space size={16} style={{ width: '100%' }}>
            <Form.Item name="timeout_sec" label="超时（秒）" style={{ width: 160 }}>
              <InputNumber min={5} max={600} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="max_tokens" label="最大 Tokens" style={{ width: 180 }}>
              <InputNumber min={16} max={32768} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="temperature" label="温度" style={{ width: 160 }}>
              <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Space size={24}>
            <Form.Item name="is_default" label="设为默认" valuePropName="checked">
              <Switch />
            </Form.Item>
            {editing && (
              <Form.Item name="status" label="状态">
                <Select
                  style={{ width: 120 }}
                  options={STATUS_OPTIONS}
                />
              </Form.Item>
            )}
          </Space>
          <Form.Item name="usage" label="用途" initialValue="CHAT"
            extra="CHAT=对话/判定模型；EMBEDDING=向量模型（幻觉与RAG语义相似度必需）">
            <Select options={[{ value: 'CHAT', label: 'CHAT 对话' }, { value: 'EMBEDDING', label: 'EMBEDDING 向量' }]} />
          </Form.Item>
          <Form.Item name="seed" label="随机种子" extra="判定模型建议固定 seed=42 保证可复现">
            <InputNumber min={0} max={2147483647} style={{ width: 160 }} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="input_price_per_mtok" label="输入单价（元/百万Token）">
              <InputNumber min={0} step={0.1} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="output_price_per_mtok" label="输出单价（元/百万Token）">
              <InputNumber min={0} step={0.1} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>

      <Modal
        title={`测试连接 - ${testTarget ? `${testTarget.name}（${testTarget.code}）` : ''}`}
        open={testOpen}
        onOk={runTest}
        onCancel={() => setTestOpen(false)}
        confirmLoading={testing}
        okText="开始测试"
        cancelText="取消"
        destroyOnHidden
        width={640}
      >
        <Form form={testForm} layout="vertical">
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="将发起一次真实 LLM 最小请求验证连通性，可能产生少量调用费用。"
          />
          <Form.Item
            name="api_key"
            label="临时 API Key（可选）"
            tooltip="若该配置已使用环境变量密钥则无需填写；填写仅用于本次测试，不会保存"
          >
            <Input.Password
              placeholder={testTarget && testTarget.api_key_env ? `留空将使用环境变量 ${testTarget.api_key_env}（不修改则留空）` : '不修改则留空'}
              onFocus={() => testForm.setFieldsValue({ api_key: '' })}
            />
          </Form.Item>
        </Form>
        {testResult && (
          <Alert
            type={testResult.ok ? 'success' : 'error'}
            showIcon
            message={testResult.ok ? '连接成功' : '连接失败'}
            description={
              testResult.ok
                ? `模型：${testResult.model || '-'}，延迟：${testResult.latency_ms}ms，已返回最小响应。`
                : `错误信息：${testResult.error || '未知错误'}（${testResult.latency_ms}ms）`
            }
          />
        )}
      </Modal>
    </Space>
  )
}

// §6.2B：三 Tab（模型配置 + 被测系统 + 知识源），Tab key 同步 URL query ?tab=
export default function Models() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = ['targets', 'fact-sources'].includes(searchParams.get('tab')) ? searchParams.get('tab') : 'configs'
  const onTabChange = (k) => {
    const np = new URLSearchParams(searchParams)
    if (k === 'configs') np.delete('tab')
    else np.set('tab', k)
    setSearchParams(np, { replace: true })
  }
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div>
        <Typography.Title level={4} style={{ margin: 0 }}>模型网关配置</Typography.Title>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          本页的「被测系统 / 知识源」与「被测系统」页（/targets）为同一份数据，任一入口维护均生效；本页主要用于模型网关。
        </Typography.Text>
      </div>
      <Tabs
        activeKey={tab}
        onChange={onTabChange}
        items={[
          { key: 'configs', label: '模型配置', children: <ModelConfigsTab /> },
          { key: 'targets', label: '被测系统', children: <TargetRegistryTab /> },
          { key: 'fact-sources', label: '知识源', children: <FactSourcesTab /> },
        ]}
      />
    </Space>
  )
}