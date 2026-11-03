/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES8 M3 通知中心（方案 §4.4）：渠道管理 / 订阅规则 / 投递留痕
import { useState, useEffect, useCallback } from 'react'
import {
  App, Badge, Button, Card, Col, Drawer, Dropdown, Empty, Form, Input, Modal,
  Popconfirm, Row, Select, Space, Switch, Table, Tabs, Tag, Tooltip, Typography,
} from 'antd'
import {
  DeleteOutlined, EditOutlined, ExperimentOutlined, PlusOutlined, ReloadOutlined,
} from '@ant-design/icons'
import http from '../../api/http'
import { tokens } from '../../theme/tokens'

const KINDS = [
  { value: 'webhook', label: 'Webhook', fields: [['url', '回调 URL（必填）'], ['secret', '签名密钥（可选）']] },
  { value: 'email', label: '邮件 SMTP', fields: [['host', 'SMTP 主机'], ['port', '端口（465=SSL）'], ['user', '账号'], ['password', '密码/授权码'], ['from_addr', '发件人'], ['to_addrs', '收件人（逗号分隔）']] },
  { value: 'dingtalk', label: '钉钉机器人', fields: [['url', '机器人 Webhook 地址'], ['secret', '加签密钥（可选）']] },
  { value: 'feishu', label: '飞书机器人', fields: [['url', '机器人 Webhook 地址']] },
  { value: 'wecom', label: '企业微信机器人', fields: [['url', '机器人 Webhook 地址']] },
]

const KIND_LABEL = Object.fromEntries(KINDS.map((k) => [k.value, k.label]))

const STATUS_META = {
  SUCCESS: { color: tokens.primary, text: '成功' },
  FAILED: { color: '#FF4D4F', text: '失败' },
  DEGRADED: { color: '#FFA657', text: '降级' },
  SKIPPED: { color: tokens.text3, text: '跳过' },
}

// 渠道状态点：teal=正常 / 红=失败 / 橙=降级（未探测=灰）
function probeBadge(ch) {
  if (ch.last_probe_ok === true) return <Badge status="success" color={tokens.primary} text={<span style={{ color: tokens.text2 }}>可用</span>} />
  if (ch.last_probe_ok === false) return <Badge status="error" color="#FF4D4F" text={<span style={{ color: tokens.text2 }}>失败</span>} />
  return <Badge status="default" text={<span style={{ color: tokens.text3 }}>未探测</span>} />
}

function ChannelTab() {
  const { message } = App.useApp()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState(null) // null=关闭；{ } = 新建；{id} = 编辑
  const [form] = Form.useForm()
  const kind = Form.useWatch('kind', form)
  const kindMeta = KINDS.find((k) => k.value === kind) || KINDS[0]

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await http.get('/notify/channels', { params: { page_size: 100 } })
      setRows(d?.items || [])
    } catch (e) { console.warn('[Notify] channels fail', e) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const save = async () => {
    const v = await form.validateFields()
    const config = {}
    for (const [key] of kindMeta.fields) {
      if (v[`cfg_${key}`] !== undefined && v[`cfg_${key}`] !== '') config[key] = v[`cfg_${key}`]
    }
    try {
      if (editing?.id) {
        await http.put(`/notify/channels/${editing.id}`, { name: v.name, enabled: v.enabled, config })
      } else {
        await http.post('/notify/channels', { kind: v.kind, name: v.name, config })
      }
      message.success('已保存')
      setEditing(null)
      form.resetFields()
      load()
    } catch (e) { console.warn('[Notify] save channel fail', e) }
  }

  const sendTest = async (id) => {
    try {
      const d = await http.post(`/notify/channels/${id}/test`)
      if (d?.ok) message.success('测试发送成功')
      else message.error(`测试失败：${d?.error || '未知原因'}`)
      load()
    } catch (e) { console.warn('[Notify] test fail', e) }
  }

  const openEdit = (ch) => {
    setEditing(ch || {})
    form.resetFields()
    if (ch) form.setFieldsValue({ kind: ch.kind, name: ch.name, enabled: ch.enabled })
  }

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openEdit(null)}>新建渠道</Button>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Row gutter={[12, 12]}>
        {rows.length === 0 && !loading && <Col span={24}><Empty description="暂无渠道，事件仅站内信兜底" /></Col>}
        {rows.map((ch) => (
          <Col key={ch.id} xs={24} md={12} xl={8}>
            <Card
              size="small"
              title={<Space><span style={{ color: tokens.text1 }}>{ch.name}</span><Tag color="cyan">{KIND_LABEL[ch.kind] || ch.kind}</Tag></Space>}
              extra={
                <Dropdown menu={{ items: [
                  { key: 'edit', icon: <EditOutlined />, label: '编辑' },
                  { key: 'del', icon: <DeleteOutlined />, label: '删除', danger: true },
                ], onClick: ({ key }) => { if (key === 'edit') openEdit(ch); if (key === 'del') Modal.confirm({ title: `删除渠道「${ch.name}」？`, okButtonProps: { danger: true }, onOk: async () => { await http.delete(`/notify/channels/${ch.id}`); message.success('已删除'); load() } }) } }}>
                  <Button type="text" size="small" style={{ color: tokens.text2 }}>···</Button>
                </Dropdown>
              }
              style={{ background: tokens.bgPanel, borderColor: tokens.border }}
            >
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <div>{probeBadge(ch)}{ch.last_probe_at ? <Typography.Text style={{ color: tokens.text3, fontSize: 12, marginLeft: 8 }}>{String(ch.last_probe_at).replace('T', ' ').slice(0, 19)}</Typography.Text> : null}</div>
                <Typography.Text style={{ color: tokens.text3, fontSize: 12 }}>参数：{(ch.config_keys || []).join(', ') || '（空）'}</Typography.Text>
                <Space>
                  <Switch size="small" checked={ch.enabled} onChange={async (v) => { await http.put(`/notify/channels/${ch.id}`, { enabled: v }); load() }} />
                  <Typography.Text style={{ color: tokens.text2, fontSize: 12 }}>{ch.enabled ? '启用中' : '已禁用'}</Typography.Text>
                </Space>
                <Button size="small" icon={<ExperimentOutlined />} onClick={() => sendTest(ch.id)} disabled={!ch.enabled}>发送测试</Button>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
      <Modal open={!!editing} title={editing?.id ? '编辑渠道' : '新建渠道'} onOk={save} onCancel={() => { setEditing(null); form.resetFields() }} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="kind" label="渠道类型" initialValue="webhook" rules={[{ required: true }]}>
            <Select disabled={!!editing?.id} options={KINDS.map((k) => ({ value: k.value, label: k.label }))} />
          </Form.Item>
          <Form.Item name="name" label="渠道名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={128} placeholder="如：安全群钉钉机器人" />
          </Form.Item>
          {kindMeta.fields.map(([key, label]) => {
            const secret = key === 'password' || key === 'secret'
            return (
              <Form.Item key={key} name={`cfg_${key}`} label={label}>
                {secret ? <Input.Password autoComplete="new-password" /> : <Input />}
              </Form.Item>
            )
          })}
          {editing?.id ? (
            <Typography.Text style={{ color: tokens.text3, fontSize: 12 }}>出于安全，配置密文不回填；保存将整体覆盖参数。</Typography.Text>
          ) : null}
        </Form>
      </Modal>
    </>
  )
}

function RulesTab() {
  const { message } = App.useApp()
  const [rows, setRows] = useState([])
  const [channels, setChannels] = useState([])
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)
  const [drawer, setDrawer] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [r, c, e] = await Promise.all([
        http.get('/notify/rules', { params: { page_size: 100 } }),
        http.get('/notify/channels', { params: { page_size: 100 } }),
        http.get('/notify/events'),
      ])
      setRows(r?.items || [])
      setChannels(c?.items || [])
      setEvents(e || [])
    } catch (err) { console.warn('[Notify] rules load fail', err) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const save = async () => {
    const v = await form.validateFields()
    const body = {
      event: v.event,
      channel_ids: v.channel_ids || [],
      min_severity: v.min_severity || 'LOW',
      enabled: v.enabled !== false,
      scope: v.project_id ? { project_id: Number(v.project_id) } : null,
    }
    try {
      if (editing?.id) await http.put(`/notify/rules/${editing.id}`, body)
      else await http.post('/notify/rules', { ...body, event: v.event })
      message.success('已保存')
      setDrawer(false); setEditing(null); form.resetFields(); load()
    } catch (err) { console.warn('[Notify] save rule fail', err) }
  }

  const open = (row) => {
    setEditing(row || {}); setDrawer(true)
    form.resetFields()
    if (row) form.setFieldsValue({ event: row.event, channel_ids: row.channel_ids, min_severity: row.min_severity, enabled: row.enabled, project_id: row.scope?.project_id })
  }

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => open(null)}>新建规则</Button>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Table
        rowKey="id" size="small" loading={loading} dataSource={rows} pagination={false}
        columns={[
          { title: '事件', dataIndex: 'event', render: (v) => <Tag color="geekblue">{events.find((e) => e.event === v)?.label || v}</Tag> },
          { title: '事件码', dataIndex: 'event', key: 'code', render: (v) => <Typography.Text style={{ color: tokens.text3, fontSize: 12 }}>{v}</Typography.Text> },
          { title: '范围', dataIndex: 'scope', render: (s) => (s && Object.keys(s).length ? Object.entries(s).map(([k, v]) => `${k}=${v}`).join('; ') : '全部') },
          { title: '最低级别', dataIndex: 'min_severity', render: (v) => <Tag>{v}</Tag> },
          {
            title: '渠道', dataIndex: 'channel_ids',
            render: (ids) => (ids || []).map((id) => <Tag key={id} color="cyan">{channels.find((c) => c.id === id)?.name || `#${id}`}</Tag>),
          },
          {
            title: '启用', dataIndex: 'enabled', width: 70,
            render: (v, row) => <Switch size="small" checked={v} onChange={async (x) => { await http.put(`/notify/rules/${row.id}`, { enabled: x }); load() }} />,
          },
          {
            title: '操作', key: 'op', width: 120,
            render: (_, row) => (
              <Space>
                <Button size="small" type="link" onClick={() => open(row)}>编辑</Button>
                <Popconfirm title="删除该规则？" onConfirm={async () => { await http.delete(`/notify/rules/${row.id}`); message.success('已删除'); load() }}>
                  <Button size="small" type="link" danger>删除</Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Drawer open={drawer} title={editing?.id ? '编辑规则' : '新建规则'} onClose={() => { setDrawer(false); setEditing(null) }} width={420}>
        <Form form={form} layout="vertical">
          <Form.Item name="event" label="订阅事件" rules={[{ required: true, message: '请选择事件' }]}>
            <Select disabled={!!editing?.id} options={events.map((e) => ({ value: e.event, label: `${e.label}（${e.event}）` }))} />
          </Form.Item>
          <Form.Item name="channel_ids" label="外发渠道" extra="不选 = 仅站内信">
            <Select mode="multiple" options={channels.map((c) => ({ value: c.id, label: `${c.name}（${KIND_LABEL[c.kind] || c.kind}）`, disabled: !c.enabled }))} />
          </Form.Item>
          <Form.Item name="min_severity" label="最低严重级" initialValue="LOW">
            <Select options={['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((v) => ({ value: v, label: v }))} />
          </Form.Item>
          <Form.Item name="project_id" label="限定项目 ID" extra="留空 = 全部项目">
            <Input placeholder="如 7" />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue>
            <Switch />
          </Form.Item>
          <Button type="primary" block onClick={save}>保存</Button>
        </Form>
      </Drawer>
    </>
  )
}

function DeliveriesTab() {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (p = page, s = status) => {
    setLoading(true)
    try {
      const d = await http.get('/notify/deliveries', { params: { page: p, page_size: 20, ...(s ? { status: s } : {}) } })
      setRows(d?.items || [])
      setTotal(d?.total || 0)
    } catch (e) { console.warn('[Notify] deliveries fail', e) }
    finally { setLoading(false) }
  }, [page, status])
  useEffect(() => { load() }, [page, status]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Select
          allowClear placeholder="状态过滤" style={{ width: 160 }} value={status}
          onChange={(v) => { setStatus(v || null); setPage(1) }}
          options={Object.entries(STATUS_META).map(([k, m]) => ({ value: k, label: m.text }))}
        />
        <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
      </Space>
      <Table
        rowKey="id" size="small" loading={loading} dataSource={rows}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage, showSizeChanger: false }}
        expandable={{
          // 失败原因红字展开（§4.4）
          rowExpandable: (r) => !!r.error || !!r.payload,
          expandedRowRender: (r) => (
            <Space direction="vertical" style={{ width: '100%' }}>
              {r.error ? <Typography.Text style={{ color: '#FF4D4F' }}>失败原因：{r.error}</Typography.Text> : null}
              {r.payload ? <Typography.Text style={{ color: tokens.text3, fontSize: 12 }}>内容摘要：{r.payload}</Typography.Text> : null}
            </Space>
          ),
        }}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 70 },
          { title: '事件', dataIndex: 'event' },
          { title: '渠道', dataIndex: 'channel_kind', render: (v) => KIND_LABEL[v] || v },
          {
            title: '状态', dataIndex: 'status',
            render: (v) => {
              const m = STATUS_META[v] || { color: tokens.text3, text: v }
              return (
                <Tooltip title={v === 'DEGRADED' ? '外发失败已重试，站内信兜底送达' : undefined}>
                  <Tag color={m.color}>{m.text}</Tag>
                </Tooltip>
              )
            },
          },
          { title: '尝试', dataIndex: 'attempts', width: 60 },
          { title: '时间', dataIndex: 'created_at', render: (v) => String(v || '').replace('T', ' ').slice(0, 19) },
        ]}
      />
    </>
  )
}

export default function Notify() {
  return (
    <div style={{ padding: 16 }}>
      <Typography.Title level={4} style={{ color: tokens.text1 }}>通知中心</Typography.Title>
      <Tabs
        items={[
          { key: 'channels', label: '触达渠道', children: <ChannelTab /> },
          { key: 'rules', label: '订阅规则', children: <RulesTab /> },
          { key: 'deliveries', label: '投递留痕', children: <DeliveriesTab /> },
        ]}
      />
    </div>
  )
}
