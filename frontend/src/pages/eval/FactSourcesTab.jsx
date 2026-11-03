/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES9-P-12（§4.3.3）：知识源（事实源）子 Tab — 被测系统页
// 列表 + 新建/编辑 Modal（auth 掩码回显、留空不修改）+ 连通测试三态 toast。
import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography, App,
} from 'antd'
import { PlusOutlined, ReloadOutlined, ThunderboltOutlined, EditOutlined } from '@ant-design/icons'
import { listFactSources, createFactSource, updateFactSource, deleteFactSource, testFactSource } from '../../api/factSources'
import { useAuth } from '../../auth'

const TYPE_OPTIONS = [{ value: 'kb_api', label: '知识库 API' }]
const STATUS_TAG = {
  active: <Tag color="green">启用</Tag>,
  disabled: <Tag>停用</Tag>,
}

export default function FactSourcesTab() {
  const { message } = App.useApp()
  const { hasPerm } = useAuth()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [testingId, setTestingId] = useState(null)
  const [form] = Form.useForm()

  const load = async (p = 1, ps = 10) => {
    setLoading(true)
    try {
      const d = await listFactSources({ page: p, page_size: ps })
      const payload = d?.data || d
      setRows(payload?.items || payload || [])
      setTotal(payload?.total ?? 0)
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(page, pageSize) }, [page, pageSize]) // eslint-disable-line react-hooks/exhaustive-deps

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ type: 'kb_api' })
    setModalOpen(true)
  }

  const openEdit = (row) => {
    setEditing(row)
    form.resetFields()
    form.setFieldsValue({ name: row.name, type: row.type || 'kb_api', base_url: row.base_url, auth: row.auth || '' })
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    // auth 为掩码回显且未修改时不提交，避免把掩码写回密文列
    if (editing && values.auth === editing.auth) delete values.auth
    try {
      if (editing) {
        await updateFactSource(editing.id, values)
        message.success('知识源已更新')
      } else {
        await createFactSource(values)
        message.success('知识源已创建，凭据已加密存储，仅显示末 4 位')
      }
      setModalOpen(false)
      load(page, pageSize)
    } catch { /* 拦截器已提示 */ }
  }

  const remove = async (row) => {
    try { await deleteFactSource(row.id); message.success('知识源已删除'); load(page, pageSize) } catch { /* 拦截器已提示 */ }
  }

  // 连通测试三态：可达 / 超时 / 未配置
  const runTest = async (row) => {
    setTestingId(row.id)
    try {
      const r = await testFactSource(row.id)
      if (r?.status === 'UNCONFIGURED' || (!r?.ok && !r?.status && !r?.error)) message.warning('未配置：该知识源暂不可用')
      else if (r?.ok || r?.status === 'REACHABLE') message.success(`可达：知识源 ${row.name} 连通正常${r?.latency_ms != null ? `（${r.latency_ms}ms）` : ''}`)
      else if (r?.status === 'TIMEOUT') message.warning('超时：知识源响应超时，请检查网络或服务状态')
      else message.error(`不可达：${r?.error || '未知错误'}`)
    } catch (e) {
      message.error(`连通测试失败：${e?.message || '未知错误'}`)
    } finally {
      setTestingId(null)
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '类型', dataIndex: 'type', width: 120, render: (v) => <Tag>{TYPE_OPTIONS.find((t) => t.value === v)?.label || v || 'kb_api'}</Tag> },
    { title: 'Base URL', dataIndex: 'base_url', ellipsis: true, render: (v) => v || '-' },
    {
      title: '凭据', dataIndex: 'auth', width: 140,
      render: (v) => (v ? <Typography.Text code style={{ fontSize: 12 }}>{v}</Typography.Text> : <span style={{ color: '#8b97a7' }}>无</span>),
    },
    { title: '状态', dataIndex: 'status', width: 90, render: (v) => STATUS_TAG[v] || <Tag>{v}</Tag> },
    { title: '被引用', dataIndex: 'usage_count', width: 90, render: (v) => (v ? `${v} 次评测` : '-') },
    {
      title: '操作', width: 220, fixed: 'right',
      render: (_, row) => (
        <Space size={0}>
          <Button type="link" size="small" icon={<ThunderboltOutlined />} loading={testingId === row.id} onClick={() => runTest(row)}>连通测试</Button>
          {hasPerm('model:update') && (
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          )}
          {hasPerm('model:delete') && (
            <Popconfirm
              title="确认删除该知识源？"
              description={row.usage_count > 0 ? `已有 ${row.usage_count} 次评测使用该知识源，删除后历史评测记录仍保留引用名，确认删除？` : undefined}
              onConfirm={() => remove(row)}
            >
              <Button type="link" size="small" danger>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="知识源用于幻觉/RAG 事实核验"
        description="配置后，在发起评测时选择『事实基准』即生效：幻觉评测将抽取断言句并检索知识源判定「有据/无据/矛盾」，RAG 评测用检索结果补位上下文；题面已带参考答案的优先题面。未配置时仅做自我一致性检测，不构成事实性结论。"
      />
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <Button icon={<ReloadOutlined />} onClick={() => load(page, pageSize)}>刷新</Button>
        {hasPerm('model:create') && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建知识源</Button>
        )}
      </div>
      <Card>
        <Table
          rowKey="id" size="small" loading={loading} columns={columns} dataSource={rows}
          scroll={{ x: 'max-content' }}
          pagination={{ current: page, pageSize, total, showSizeChanger: true, showTotal: (t) => `共 ${t} 条`, onChange: (p, ps) => { setPage(p); setPageSize(ps) } }}
        />
      </Card>

      <Modal
        title={editing ? `编辑知识源（${editing.name}）` : '新建知识源'}
        open={modalOpen}
        onOk={submit}
        okText="保存"
        cancelText="取消"
        onCancel={() => setModalOpen(false)}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：产品知识库" />
          </Form.Item>
          <Form.Item name="type" label="类型">
            <Select options={TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="base_url"
            label="Base URL"
            rules={[
              { required: true, message: '请输入知识源检索接口地址' },
              { pattern: /^https?:\/\//, message: '必须以 http:// 或 https:// 开头' },
            ]}
          >
            <Input placeholder="如 https://kb.example.com/api/search" />
          </Form.Item>
          <Form.Item
            name="auth"
            label="访问凭据"
            extra="加密存储，仅显示末 4 位；编辑时留空表示不修改"
          >
            <Input.Password
              placeholder="不修改则留空"
              onFocus={() => { if (editing) form.setFieldsValue({ auth: '' }) }}
              autoComplete="new-password"
            />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
