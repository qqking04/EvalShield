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
  Table, Button, Card, Space, Tag, Modal, Form, Input, App, Popconfirm, Typography, Alert,
  Checkbox, Tooltip, Collapse,
} from 'antd'
import { PlusOutlined, ReloadOutlined, CopyOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { fmtTime } from '../../utils'

// ES10-P-04：scope 注册表（与 backend/app/api_scopes.py SCOPES 对齐）
const SCOPE_GROUPS = [
  { label: '上报数据', items: [['traces:read', '读取'], ['traces:write', '写入']] },
  { label: '用例资产', items: [['cases:read', '读取'], ['cases:write', '写入']] },
  { label: '评测执行', items: [['eval:read', '读取'], ['eval:run', '执行']] },
]

// 已挂载 require_scope 的端点对照（与 backend ENFORCEMENT 静态同步）
const ENFORCEMENT_HINTS = [
  ['POST /api/traces/ingest', '上报链路追踪数据', 'traces:write'],
  ['GET /api/traces', '查询链路追踪列表', 'traces:read'],
  ['GET /api/traces/{id}', '查询链路追踪详情', 'traces:read'],
]

// ES10 BUG-8：账本未挂载 require_scope 的预留 scope（api_scopes.py §对照表）
const RESERVED_SCOPES = new Set(['cases:read', 'cases:write', 'eval:read', 'eval:run'])

// 提交前归一化：write 勾了 read 没勾 → 自动补 read（写必含读）
export function normalizeScopes(list) {
  const out = new Set(list || [])
  if (out.has('traces:write')) out.add('traces:read')
  if (out.has('cases:write')) out.add('cases:read')
  return [...out]
}

// 受控小组件：按 groups 渲染三组 Checkbox，value/onChange 为扁平字符串数组
export function CheckboxGroupMatrix({ value = [], onChange }) {
  const selected = new Set(value)
  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      {SCOPE_GROUPS.map((g) => {
        const all = g.items.map(([s]) => s)
        return (
          <div key={g.label} data-testid={`scope-group-${g.label}`}>
            <Typography.Text type="secondary" style={{ marginRight: 12 }}>{g.label}</Typography.Text>
            <Checkbox.Group
              value={all.filter((s) => selected.has(s))}
              onChange={(vals) => {
                const others = value.filter((s) => !all.includes(s))
                onChange?.([...others, ...vals])
              }}
            >
              {g.items.map(([s, name]) => (
                <Checkbox key={s} value={s}>
                  {RESERVED_SCOPES.has(s) ? (
                    <Tooltip title="预留，尚未开放 API-Key 通道">
                      <span>{name}（{s}）</span>
                    </Tooltip>
                  ) : (
                    <>{name}（{s}）</>
                  )}
                </Checkbox>
              ))}
            </Checkbox.Group>
          </div>
        )
      })}
    </Space>
  )
}

export default function AdminApiKeys() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [createdKey, setCreatedKey] = useState(null)
  const [form] = Form.useForm()
  const { message } = App.useApp()

  const load = async () => {
    setLoading(true)
    try {
      const d = await http.get('/admin/api-keys')
      setRows(d.items || d || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const submit = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const d = await http.post('/admin/api-keys', { key_name: values.key_name, scopes: normalizeScopes(values.scopes || []) })
    setModalOpen(false)
    setCreatedKey(d.api_key)
    message.success('已加密存储，仅显示末 4 位；明文只显示这一次，请立即复制')
    load()
  }

  const remove = async (id) => {
    await http.delete(`/admin/api-keys/${id}`)
    message.success('API Key 已吊销')
    load()
  }

  const columns = [
    { title: '名称', dataIndex: 'key_name', width: 160 },
    { title: 'Key 前缀', dataIndex: 'key_prefix', width: 160, render: (v) => <Typography.Text code>{v}...</Typography.Text> },
    {
      title: '权限范围',
      dataIndex: 'scopes',
      width: 260,
      render: (v) => (Array.isArray(v) && v.length)
        ? v.map((s) => <Tag key={s} color="blue">{s}</Tag>)
        : (
          <Tooltip title="旧版 Key 未限定范围，拥有全部 API 权限；建议重建为显式范围">
            <Tag color="default">全部（旧版）</Tag>
          </Tooltip>
        ),
    },
    { title: '过期时间', dataIndex: 'expires_at', width: 160, render: (v) => (v ? fmtTime(v) : '长期有效') },
    { title: '禁用', dataIndex: 'disabled', width: 80, render: (v) => (v ? <Tag color="red">是</Tag> : '-') },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v) => fmtTime(v) },
    {
      title: '操作',
      width: 90,
      render: (_, row) => (
        <Popconfirm title="吊销后将立即失效，确认？" onConfirm={() => remove(row.id)}>
          <Button type="link" size="small" danger>吊销</Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>API 密钥</Typography.Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setModalOpen(true) }}>创建密钥</Button>
        </Space>
      </div>
      <Card>
        <Table rowKey="id" loading={loading} columns={columns} dataSource={rows} pagination={{ showTotal: (t) => `共 ${t} 条`, showSizeChanger: true, showQuickJumper: true }} />
      </Card>
      <Modal
        title="创建 API 密钥"
        open={modalOpen}
        onOk={submit}
        okText="创建"
        cancelText="取消"
        onCancel={() => setModalOpen(false)}
        destroyOnHidden
        width={760}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="key_name" label="密钥名称" rules={[{ required: true }]}>
            <Input placeholder="如：CI 自动化调用" />
          </Form.Item>
          <Form.Item
            name="scopes"
            label="权限范围"
            rules={[{ required: true, message: '至少选择一个权限范围' }]}
            extra="勾选「写入」将自动附带对应「读取」权限；用例资产与评测执行范围目前仅登记、尚未开放 API-Key 通道。"
          >
            <CheckboxGroupMatrix groups={SCOPE_GROUPS} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="密钥创建成功"
        open={!!createdKey}
        onOk={() => setCreatedKey(null)}
        onCancel={() => setCreatedKey(null)}
        footer={<Button type="primary" onClick={() => setCreatedKey(null)}>我已保存</Button>}
      >
        <Alert
          type="warning"
          showIcon
          message="请立即复制并妥善保存，明文只显示这一次！"
          description={<Space direction="vertical"><Typography.Text code copyable={{ icon: <CopyOutlined /> }}>{createdKey}</Typography.Text><Typography.Text type="secondary">密钥以 SHA-256 摘要存储，丢失后无法找回，只能重新创建。</Typography.Text></Space>}
        />
        <Collapse
          style={{ marginTop: 16 }}
          items={[{
            key: 'how-to-use',
            label: '如何使用该 Key',
            children: (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Typography.Paragraph style={{ marginBottom: 0 }}>
                  在请求头携带：<Typography.Text code copyable={{ icon: <CopyOutlined /> }}>{`X-API-Key: ${createdKey || '<your-key>'}`}</Typography.Text>
                </Typography.Paragraph>
                <Typography.Text type="secondary">当前已按权限范围约束的端点：</Typography.Text>
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {ENFORCEMENT_HINTS.map(([ep, desc, scope]) => (
                    <li key={ep}>
                      <Typography.Text code>{ep}</Typography.Text> —— {desc}（需要 <Tag key={scope} style={{ margin: 0 }}>{scope}</Tag>）
                    </li>
                  ))}
                </ul>
                <Typography.Text type="secondary">权限不足将返回 403（错误码 ES-SCOPE-0001，message 含缺失的权限名）。</Typography.Text>
              </Space>
            ),
          }]}
        />
      </Modal>
    </Space>
  )
}
