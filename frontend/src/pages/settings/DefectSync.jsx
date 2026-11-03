/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES8 M11 工单集成（方案 §12.4）：GitHub/Gitee/Jira 同步目标管理
import { useState, useEffect, useCallback } from 'react'
import {
  App, Badge, Button, Card, Col, Empty, Form, Input, Modal, Row, Select, Space,
  Switch, Table, Tabs, Tag, Typography,
} from 'antd'
import {
  DeleteOutlined, EditOutlined, ExperimentOutlined, LinkOutlined, PlusOutlined, ReloadOutlined,
} from '@ant-design/icons'
import http from '../../api/http'
import { tokens } from '../../theme/tokens'

const PROVIDERS = [
  {
    value: 'github', label: 'GitHub Issues',
    fields: [['repo', '仓库（owner/name）'], ['token', '访问令牌（PAT）'], ['api_base', 'API 地址（内网自建可选）'], ['webhook_secret', 'Webhook 密钥（回写验签）']],
    required: ['repo'],
    hint: '出站推送 + Webhook 实时回写（外部关单 → 缺陷自动关闭）。收端地址：/api/defect-sync/webhook/github，事件选 Issues。',
  },
  {
    value: 'gitee', label: 'Gitee Issues',
    fields: [['repo', '仓库（owner/name）'], ['token', '私人令牌'], ['api_base', 'API 地址（可选）']],
    required: ['repo'],
    hint: '出站推送 + 每日轮询回写（延迟 ≤24h）。',
  },
  {
    value: 'jira', label: 'Jira',
    fields: [['base_url', '站点地址（https://jira.example.com）'], ['project_key', '项目 KEY'], ['personal_token', 'Personal Access Token'], ['issue_type', 'Issue 类型（默认 Bug）']],
    required: ['base_url', 'project_key'],
    hint: '出站单向推送，不回写状态。',
  },
]

const PROVIDER_LABEL = Object.fromEntries(PROVIDERS.map((p) => [p.value, p.label]))

const SYNC_STATUS_META = {
  SYNCED: { color: tokens.primary, text: '已同步' },
  EXTERNAL_CLOSED: { color: tokens.text3, text: '外部已关单' },
  LOCAL_CLOSED: { color: tokens.text3, text: '本地已关单' },
  FAILED: { color: '#FF4D4F', text: '推送失败' },
}

// 探测状态点：teal=可用 / 红=失败 / 灰=未探测（与通知中心同范式）
function probeBadge(t) {
  if (t.last_probe_ok === true) return <Badge color={tokens.primary} text={<span style={{ color: tokens.text2 }}>可用</span>} />
  if (t.last_probe_ok === false) return <Badge color="#FF4D4F" text={<span style={{ color: tokens.text2 }}>探测失败</span>} />
  return <Badge color={tokens.text3} text={<span style={{ color: tokens.text3 }}>未探测</span>} />
}

function TargetsTab() {
  const { message } = App.useApp()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState(null) // null=关闭；{} = 新建；{id} = 编辑
  const [form] = Form.useForm()
  const provider = Form.useWatch('provider', form)
  const meta = PROVIDERS.find((p) => p.value === provider) || PROVIDERS[0]

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await http.get('/defect-sync/targets', { params: { page_size: 100 } })
      setRows(d?.items || [])
    } catch (e) { console.warn('[DefectSync] targets load fail', e) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const save = async () => {
    const v = await form.validateFields()
    const config = {}
    for (const [key] of meta.fields) {
      if (v[`cfg_${key}`] !== undefined && v[`cfg_${key}`] !== '') config[key] = v[`cfg_${key}`]
    }
    try {
      if (editing?.id) {
        await http.put(`/defect-sync/targets/${editing.id}`, { name: v.name, enabled: v.enabled, config })
      } else {
        await http.post('/defect-sync/targets', { provider: v.provider, name: v.name, config })
      }
      message.success('已保存')
      setEditing(null)
      form.resetFields()
      load()
    } catch (e) { console.warn('[DefectSync] save target fail', e) }
  }

  const sendTest = async (id) => {
    try {
      const d = await http.post(`/defect-sync/targets/${id}/test`)
      if (d?.ok) message.success('连接测试成功')
      else message.error(`测试失败：${d?.error || '未知原因'}`)
      load()
    } catch (e) { console.warn('[DefectSync] test fail', e) }
  }

  const openEdit = (t) => {
    setEditing(t || {})
    form.resetFields()
    if (t) form.setFieldsValue({ provider: t.provider, name: t.name, enabled: t.enabled })
  }

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openEdit(null)}>新建目标</Button>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Row gutter={[12, 12]}>
        {rows.length === 0 && !loading && <Col span={24}><Empty description="暂无工单目标，缺陷详情页推送入口将不可用" /></Col>}
        {rows.map((t) => (
          <Col key={t.id} xs={24} md={12} xl={8}>
            <Card
              size="small"
              title={<Space><span style={{ color: tokens.text1 }}>{t.name}</span><Tag color="cyan">{PROVIDER_LABEL[t.provider] || t.provider}</Tag></Space>}
              extra={
                <Space size={4}>
                  <Button type="text" size="small" icon={<EditOutlined />} style={{ color: tokens.text2 }} onClick={() => openEdit(t)} />
                  <Button type="text" size="small" icon={<DeleteOutlined />} danger onClick={() => Modal.confirm({ title: `删除目标「${t.name}」？`, content: '将同时删除其全部外联记录（不影响缺陷本身）', okButtonProps: { danger: true }, onOk: async () => { await http.delete(`/defect-sync/targets/${t.id}`); message.success('已删除'); load() } })} />
                </Space>
              }
              style={{ background: tokens.bgPanel, borderColor: tokens.border }}
            >
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <div>{probeBadge(t)}{t.last_probe_at ? <Typography.Text style={{ color: tokens.text3, fontSize: 12, marginLeft: 8 }}>{String(t.last_probe_at).replace('T', ' ').slice(0, 19)}</Typography.Text> : null}</div>
                <Typography.Text style={{ color: tokens.text3, fontSize: 12 }}>
                  {t.config?.repo ? `仓库：${t.config.repo}` : ''}{t.config?.project_key ? `项目：${t.config.project_key}` : ''}{t.config?.base_url ? ` 站点：${t.config.base_url}` : ''}
                  {' '}令牌：<span style={{ color: tokens.text2 }}>{t.config?.token_mask || '****'}</span>
                </Typography.Text>
                <Space>
                  <Switch size="small" checked={t.enabled} onChange={async (v) => { await http.put(`/defect-sync/targets/${t.id}`, { enabled: v }); load() }} />
                  <Typography.Text style={{ color: tokens.text2, fontSize: 12 }}>{t.enabled ? '启用中' : '已禁用'}</Typography.Text>
                </Space>
                <Button size="small" icon={<ExperimentOutlined />} onClick={() => sendTest(t.id)} disabled={!t.enabled}>测试连接</Button>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
      <Modal open={!!editing} title={editing?.id ? '编辑工单目标' : '新建工单目标'} onOk={save} onCancel={() => { setEditing(null); form.resetFields() }} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="provider" label="平台" initialValue="github" rules={[{ required: true }]}>
            <Select disabled={!!editing?.id} options={PROVIDERS.map((p) => ({ value: p.value, label: p.label }))} />
          </Form.Item>
          <Form.Item name="name" label="目标名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={128} placeholder="如：核心产品 GitHub 主仓" />
          </Form.Item>
          {meta.fields.map(([key, label]) => {
            const secret = key === 'token' || key === 'personal_token' || key === 'webhook_secret'
            return (
              <Form.Item key={key} name={`cfg_${key}`} label={label} rules={meta.required.includes(key) && !editing?.id ? [{ required: true, message: `请输入${label}` }] : undefined}>
                {secret ? <Input.Password autoComplete="new-password" placeholder={editing?.id ? '留空 = 保留原值' : undefined} /> : <Input placeholder={editing?.id ? '留空 = 保留原值' : undefined} />}
              </Form.Item>
            )
          })}
          <Typography.Paragraph style={{ color: tokens.text3, fontSize: 12, marginBottom: 0 }}>{meta.hint}</Typography.Paragraph>
        </Form>
      </Modal>
    </>
  )
}

function LinksTab() {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [defectId, setDefectId] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (p = 1, did = defectId) => {
    if (!did) { setRows([]); setTotal(0); return }
    setLoading(true)
    try {
      // links 接口按缺陷查询（外联记录以缺陷为入口）
      const d = await http.get('/defect-sync/links', { params: { defect_id: Number(did) } })
      const items = d?.items || []
      setRows(items)
      setTotal(items.length)
      void p
    } catch (e) { console.warn('[DefectSync] links load fail', e) }
    finally { setLoading(false) }
  }, [defectId])

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Input
          placeholder="缺陷 ID（必填）" style={{ width: 180 }} value={defectId}
          onChange={(e) => setDefectId(e.target.value.replace(/\D/g, ''))} onPressEnter={() => load(1)}
        />
        <Button type="primary" icon={<LinkOutlined />} onClick={() => load(1)}>查询外联</Button>
      </Space>
      <Table
        rowKey="id" size="small" loading={loading} dataSource={rows}
        pagination={{ current: page, pageSize: 20, total, onChange: (p) => { setPage(p); load(p) }, showSizeChanger: false }}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 70 },
          { title: '目标', dataIndex: 'target_id', render: (v) => <Tag color="cyan">#{v}</Tag> },
          { title: '缺陷', dataIndex: 'defect_id', width: 80 },
          { title: '外部单号', dataIndex: 'external_id' },
          {
            title: '外部链接', dataIndex: 'external_url', ellipsis: true,
            render: (v) => (v ? <a href={v} target="_blank" rel="noreferrer">{v}</a> : '-'),
          },
          {
            title: '状态', dataIndex: 'sync_status',
            render: (v) => {
              const m = SYNC_STATUS_META[v] || { color: tokens.text3, text: v }
              return <Tag color={m.color}>{m.text}</Tag>
            },
          },
          { title: '失败原因', dataIndex: 'fail_reason', ellipsis: true, render: (v) => (v ? <Typography.Text style={{ color: '#FF4D4F', fontSize: 12 }}>{v}</Typography.Text> : '-') },
          { title: '最近同步', dataIndex: 'last_synced_at', render: (v) => String(v || '').replace('T', ' ').slice(0, 19) || '-' },
        ]}
      />
    </>
  )
}

export default function DefectSync() {
  return (
    <div style={{ padding: 16 }}>
      <Typography.Title level={4} style={{ color: tokens.text1 }}>工单集成</Typography.Title>
      <Tabs
        items={[
          { key: 'targets', label: '同步目标', children: <TargetsTab /> },
          { key: 'links', label: '外联记录', children: <LinksTab /> },
        ]}
      />
    </div>
  )
}
