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
import { PlusOutlined, ReloadOutlined, KeyOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { fmtTime } from '../../utils'

export default function AdminUsers() {
  const [rows, setRows] = useState([])
  const [roles, setRoles] = useState([])
  const [orgs, setOrgs] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const { message, modal } = App.useApp()

  const load = async (p = page) => {
    setLoading(true)
    try {
      const d = await http.get('/admin/users', { params: { page: p, page_size: 10 } })
      setRows(d.items || [])
      setTotal(d.total || 0)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load(1)
    http.get('/admin/roles').then((d) => setRoles(d?.items || d || [])).catch((e) => console.warn('[Admin/Users]', e?.message || e))
    http.get('/admin/organizations').then((d) => setOrgs(d?.items || d || [])).catch((e) => console.warn('[Admin/Users]', e?.message || e))
  }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (row) => {
    setEditing(row)
    form.setFieldsValue({
      display_name: row.display_name,
      email: row.email,
      phone: row.phone,
      title: row.title,
      org_id: row.org_id,
      status: row.status,
      role_ids: (row.roles || []).map((code) => roles.find((r) => r.role_code === code)?.id).filter(Boolean),
    })
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    if (editing) {
      await http.put(`/admin/users/${editing.id}`, values)
      message.success('用户更新成功')
    } else {
      await http.post('/admin/users', values)
      message.success('用户创建成功')
    }
    setModalOpen(false)
    load(1)
  }

  const resetPwd = async (id) => {
    const d = await http.post(`/admin/users/${id}/reset-password`)
    modal.success({ title: '密码已重置', content: `新密码：${d.new_password}`, okText: '知道了' })
  }

  const remove = async (id) => {
    await http.delete(`/admin/users/${id}`)
    message.success('用户已删除')
    load(page)
  }

  const columns = [
    { title: '用户编号', dataIndex: 'user_no', width: 150 },
    { title: '登录名', dataIndex: 'username', width: 130 },
    { title: '显示名', dataIndex: 'display_name', width: 130, render: (v) => v || '-' },
    { title: '邮箱', dataIndex: 'email', ellipsis: true, render: (v) => v || '-' },
    { title: '角色', dataIndex: 'roles', width: 160, render: (v) => (v || []).map((r) => <Tag key={r} color="blue">{r}</Tag>) },
    { title: '状态', dataIndex: 'status', width: 100, render: (v) => <Tag color={v === 'ACTIVE' ? 'green' : 'red'}>{v}</Tag> },
    { title: 'MFA', dataIndex: 'mfa_enabled', width: 80, render: (v) => (v ? <Tag color="purple">已开启</Tag> : '-') },
    { title: '最近登录', dataIndex: 'last_login_at', width: 160, render: (v) => (v ? fmtTime(v) : '-') },
    {
      title: '操作',
      width: 220,
      render: (_, row) => (
        <Space>
          <Button type="link" size="small" onClick={() => openEdit(row)}>编辑</Button>
          <Popconfirm title="重置密码为 EvalShield@123？" onConfirm={() => resetPwd(row.id)}>
            <Button type="link" size="small" icon={<KeyOutlined />}>重置密码</Button>
          </Popconfirm>
          <Popconfirm title="确认删除该用户？" onConfirm={() => remove(row.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>用户管理</Typography.Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用户</Button>
        </Space>
      </div>
      <Card>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={rows}
          scroll={{ x: 'max-content' }}
          pagination={{ current: page, total, pageSize: 10, showTotal: (t) => `共 ${t} 条`, onChange: (p) => { setPage(p); load(p) } }}
        />
      </Card>
      <Modal
        title={editing ? '编辑用户' : '新建用户'}
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
          {!editing && (
            <>
              <Form.Item name="username" label="登录名" rules={[{ required: true, min: 2 }]}>
                <Input placeholder="2-64 个字符" />
              </Form.Item>
              <Form.Item name="display_name" label="显示名" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 8 }]}>
                <Input.Password placeholder="至少 8 位" />
              </Form.Item>
            </>
          )}
          {editing && (
            <Form.Item name="display_name" label="显示名" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
          )}
          <Form.Item name="email" label="邮箱">
            <Input />
          </Form.Item>
          <Form.Item name="phone" label="手机号">
            <Input />
          </Form.Item>
          <Form.Item name="title" label="职位">
            <Input placeholder="如：测试工程师" />
          </Form.Item>
          <Form.Item name="org_id" label="所属部门">
            <Select
              allowClear
              options={(orgs || []).map((o) => ({ value: o.id, label: o.org_name }))}
            />
          </Form.Item>
          <Form.Item name="role_ids" label="角色">
            <Select mode="multiple" options={(roles || []).map((r) => ({ value: r.id, label: `${r.role_name} (${r.role_code})` }))} />
          </Form.Item>
          <Form.Item name="status" label="状态" initialValue="ACTIVE">
            <Select options={[{ value: 'ACTIVE', label: 'ACTIVE' }, { value: 'DISABLED', label: 'DISABLED' }]} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}