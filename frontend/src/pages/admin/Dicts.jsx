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
  Table, Button, Card, Space, Tag, Modal, Form, Input, Select, App, Popconfirm, Typography,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import http from '../../api/http'

export default function AdminDicts() {
  const [rows, setRows] = useState([])
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [itemsText, setItemsText] = useState('')
  const [form] = Form.useForm()
  const { message } = App.useApp()

  const load = async (kw = keyword) => {
    setLoading(true)
    try {
      const d = await http.get('/admin/dicts', { params: kw ? { keyword: kw } : {} })
      setRows(d.items || d || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const submit = async () => {
    const values = await form.validateFields()
    const items = itemsText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
      .map((line) => {
        const [label, value] = line.split(/\s+/)
        return { item_label: label, item_value: value || label }
      })
    if (editing) {
      await http.put(`/admin/dicts/${editing.id}`, { ...values, items, dict_type: editing.dict_type || 'BUSINESS' })
      message.success('字典更新成功')
    } else {
      await http.post('/admin/dicts', { ...values, items, dict_type: 'BUSINESS' })
      message.success('字典创建成功')
    }
    setModalOpen(false)
    load()
  }

  const openEdit = (row) => {
    setEditing(row)
    form.setFieldsValue({
      dict_code: row.dict_code,
      dict_name: row.dict_name,
      description: row.description,
    })
    setItemsText((row.items || []).map((it) => `${it.item_label} ${it.item_value}`).join('\n'))
    setModalOpen(true)
  }

  const remove = async (id) => {
    await http.delete(`/admin/dicts/${id}`)
    message.success('字典已删除')
    load()
  }

  const columns = [
    { title: '字典编码', dataIndex: 'dict_code', width: 180 },
    { title: '字典名称', dataIndex: 'dict_name', width: 180 },
    { title: '类型', dataIndex: 'dict_type', width: 120, render: (v) => <Tag color="blue">{v}</Tag> },
    { title: '内置', dataIndex: 'is_system', width: 80, render: (v) => (v ? <Tag color="orange">系统</Tag> : '-') },
    {
      title: '字典项',
      dataIndex: 'items',
      render: (v) => (
        <Space wrap>
          {(v || []).map((it) => (
            <Tag key={it.id} color="purple">{it.item_label}={it.item_value}</Tag>
          ))}
          {(v || []).length === 0 && <Typography.Text type="secondary">-</Typography.Text>}
        </Space>
      ),
    },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
    {
      title: '操作',
      width: 140,
      render: (_, row) =>
        row.is_system ? null : (
          <Space>
            <Button type="link" size="small" onClick={() => openEdit(row)}>编辑</Button>
            <Popconfirm title="确认删除该字典？" onConfirm={() => remove(row.id)}>
              <Button type="link" size="small" danger>删除</Button>
            </Popconfirm>
          </Space>
        ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>数据字典</Typography.Title>
        <Space>
          <Input.Search placeholder="按编码/名称搜索" allowClear onSearch={(v) => { setKeyword(v); load(v) }} style={{ width: 240 }} />
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setItemsText(''); setModalOpen(true) }}>新建字典</Button>
        </Space>
      </div>
      <Card>
        <Table rowKey="id" loading={loading} columns={columns} dataSource={rows} pagination={{ showTotal: (t) => `共 ${t} 条`, showSizeChanger: true, showQuickJumper: true }} expandable={{ defaultExpandAllRows: false }} />
      </Card>
      <Modal title={editing ? '编辑数据字典' : '新建数据字典'} open={modalOpen} onOk={submit} okText="保存" cancelText="取消" onCancel={() => setModalOpen(false)} destroyOnHidden width={900} styles={{ body: { maxHeight: '72vh', overflowY: 'auto' } }}>
        <Form form={form} layout="vertical">
          <Form.Item name="dict_code" label="字典编码" rules={[{ required: true, min: 2 }, { pattern: /^[A-Z0-9_]+$/, message: '仅允许大写字母、数字、下划线' }]}>
            <Input placeholder="如 TASK_STATUS" />
          </Form.Item>
          <Form.Item name="dict_name" label="字典名称" rules={[{ required: true }]}>
            <Input placeholder="如：任务状态" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input />
          </Form.Item>
          <Form.Item label="字典项（每行：标签 值，空格分隔）">
            <Input.TextArea rows={6} value={itemsText} onChange={(e) => setItemsText(e.target.value)} placeholder={'PENDING 待执行\nRUNNING 执行中\nSUCCESS 成功\nFAILED 失败'} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}