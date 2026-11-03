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
  Table, Button, Card, Space, Modal, Form, Input, Select, Switch, Tag, App, Popconfirm,
} from 'antd'
import { PlusOutlined, ReloadOutlined, MenuOutlined } from '@ant-design/icons'
import http from '../../api/http'

const MENU_TYPES = [
  { label: '目录 (dir)', value: 'dir' },
  { label: '菜单 (menu)', value: 'menu' },
  { label: '按钮 (button)', value: 'button' },
]
const ICON_OPTIONS = ['SettingOutlined','UserOutlined','TeamOutlined','LockOutlined','MenuOutlined',
  'DatabaseOutlined','ControlOutlined','KeyOutlined','AuditOutlined','LoginOutlined',
  'ApartmentOutlined','DashboardOutlined','ProjectOutlined','ScheduleOutlined','FolderOpenOutlined',
  'ExperimentOutlined','FileTextOutlined','SafetyCertificateOutlined','CloudServerOutlined',
  'SwapOutlined','ThunderboltOutlined','CompassOutlined','UploadOutlined','WalletOutlined',
]

function flatten(tree, list = []) {
  for (const n of tree) { list.push(n); flatten(n.children || [], list) }
  return list
}

export default function AdminMenus() {
  const [tree, setTree] = useState([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const { message } = App.useApp()

  const load = async () => {
    setLoading(true)
    try {
      const d = await http.get('/admin/menus')
      setTree(d.items || d || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openCreate = (parentId = null) => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ parent_id: parentId ?? null, menu_type: 'menu', sort_order: 0, visible: true })
    setModalOpen(true)
  }
  const openEdit = (record) => {
    setEditing(record)
    form.setFieldsValue({ ...record })
    setModalOpen(true)
  }

  const submit = async () => {
    const vals = await form.validateFields()
    try {
      if (editing) {
        await http.put(`/admin/menus/${editing.id}`, vals)
        message.success('更新成功')
      } else {
        await http.post('/admin/menus', vals)
        message.success('创建成功')
      }
      setModalOpen(false)
      load()
    } catch (e) { console.warn(e) }
  }

  const remove = async (id) => {
    try {
      await http.delete(`/admin/menus/${id}`)
      message.success('删除成功（含子菜单已软删）')
      load()
    } catch (e) { console.warn(e) }
  }

  const columns = [
    { title: '标题', dataIndex: 'title', width: 180 },
    { title: '类型', dataIndex: 'menu_type', width: 90, render: (t) => <Tag color={t==='dir'?'blue':t==='button'?'orange':'green'}>{t}</Tag> },
    { title: '路径', dataIndex: 'path', width: 180, render: (p) => <code>{p}</code> },
    { title: '组件', dataIndex: 'component', width: 200, render: (c) => c || <span style={{color:'#aaa'}}>-</span> },
    { title: '图标', dataIndex: 'icon', width: 140 },
    { title: '权限码', dataIndex: 'perm', width: 140, render: (p) => <code>{p || '-'}</code> },
    { title: '排序', dataIndex: 'sort_order', width: 70, defaultSortOrder: 'ascend', sorter: (a, b) => a.sort_order - b.sort_order },
    { title: '可见', dataIndex: 'visible', width: 70, render: (v) => v ? '✅' : '❌' },
    {
      title: '操作', width: 220, fixed: 'right',
      render: (_, r) => (
        <Space>
          <Button size="small" type="link" onClick={() => openCreate(r.id)}>+子项</Button>
          <Button size="small" type="link" onClick={() => openEdit(r)}>编辑</Button>
          <Popconfirm title={`确认删除「${r.title}」？子菜单一并删除`} onConfirm={() => remove(r.id)}>
            <Button size="small" type="link" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const allNodes = flatten(tree)
  const parentOptions = [{ label: '— 顶级 —', value: null }, ...allNodes
    .filter((n) => n.menu_type === 'dir' || !n.parent_id)
    .map((n) => ({ label: n.title, value: n.id }))]

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate(null)}>新建菜单</Button>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Card>
        <Table
          rowKey="id" loading={loading} columns={columns} dataSource={tree}
          pagination={false} expandable={{ defaultExpandAllRows: true }}
        />
      </Card>

      <Modal
        title={editing ? '编辑菜单' : '新建菜单'}
        open={modalOpen} onOk={submit} okText="保存" cancelText="取消" onCancel={() => setModalOpen(false)}
        destroyOnHidden width={900} styles={{ body: { maxHeight: '72vh', overflowY: 'auto' } }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="menu_type" label="类型" rules={[{ required: true }]}>
            <Select options={MENU_TYPES} />
          </Form.Item>
          <Form.Item name="parent_id" label="上级菜单">
            <Select options={parentOptions} allowClear placeholder="顶级留空" />
          </Form.Item>
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input placeholder="如 仪表盘" />
          </Form.Item>
          <Form.Item name="path" label="前端路径" rules={[{ required: true }]}>
            <Input placeholder="如 /dashboard 或 /admin/menus" />
          </Form.Item>
          <Form.Item name="component" label="组件路径">
            <Input placeholder="如 pages/admin/Menus（动态路由用）" />
          </Form.Item>
          <Form.Item name="icon" label="图标名">
            <Select showSearch allowClear placeholder="Antd icon 名" options={ICON_OPTIONS.map((x) => ({label:x,value:x}))} />
          </Form.Item>
          <Form.Item name="perm" label="所需权限码">
            <Input placeholder="如 admin:menu 或留空（任何人可见）" />
          </Form.Item>
          <Form.Item name="sort_order" label="排序">
            <Input type="number" />
          </Form.Item>
          <Form.Item name="visible" label="是否可见" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
