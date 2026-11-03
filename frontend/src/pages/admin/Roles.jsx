/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useMemo, useState, useRef } from 'react'
import {
  Table, Button, Card, Space, Tag, Modal, Form, Input, App, Popconfirm, Typography, Checkbox, Collapse,
  Tabs, Tree, Tooltip,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import http from '../../api/http'

/** 后端权限 module 英文 → 中文显示名映射。 */
const MODULE_CN = {
  admin: '系统管理',
  asset: '资产管理',
  billing: '计费',
  case: '测试用例',
  dashboard: '仪表盘',
  dataset: '测试数据集',
  defect: '缺陷管理',
  dictionary: '数据字典',
  engine: '引擎配置',
  eval: '评测',
  model: '模型网关',
  notification: '通知',
  project: '项目',
  report: '报告',
  scenario: '测试场景',
  security: '安全',
  task: '任务',
  user: '用户',
  org: '组织机构',
}
const moduleLabel = (m) => MODULE_CN[m] || m

/** 将后端菜单树转成 antd Tree 需要的 title/key/children 结构。 */
function toTreeData(nodes) {
  return (nodes || []).map((n) => ({
    key: n.id,
    title: (
      <Tooltip title={n.perm ? `权限码：${n.perm}` : '无权限码'} mouseEnterDelay={0.5}>
        <Space size={4}>
          <span>{n.title}</span>
          {n.menu_type === 'dir' && <Tag color="blue" style={{ marginLeft: 4 }}>目录</Tag>}
          {n.menu_type === 'button' && <Tag color="gold">按钮</Tag>}
        </Space>
      </Tooltip>
    ),
    children: toTreeData(n.children),
  }))
}

export default function AdminRoles() {
  const [rows, setRows] = useState([])
  const [perms, setPerms] = useState([])
  const [menuTree, setMenuTree] = useState([])     // 后端原始树（含 id）
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [permSearch, setPermSearch] = useState('')
  const [menuChecked, setMenuChecked] = useState([]) // Tree checked keys（菜单 id 数组）
  const [form] = Form.useForm()
  const editRowRef = useRef(null) // 保存最新待编辑的 row，解决 React setEditing 异步时序
  const { message } = App.useApp()

  const load = async () => {
    setLoading(true)
    try {
      const d = await http.get('/admin/roles')
      setRows(d.items || d || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    http.get('/admin/permissions').then((d) => setPerms(d.items || d || [])).catch((e) => console.warn(`[Admin/Roles] perms`, e?.message || e))
    http.get('/admin/menus').then((d) => {
      // http 拦截器已解 body.data，此处 d 即 {items,total,bindings}
      setMenuTree(d.items || [])
    }).catch((e) => console.warn(`[Admin/Roles] menus`, e?.message || e))
  }, [])

  // 按模块分组权限点（去掉泛模块通配 *，避免重复；支持关键词搜索）
  const permGroups = useMemo(() => {
    const q = permSearch.trim().toLowerCase()
    const groups = {}
    for (const p of perms) {
      if (p.perm_code.endsWith(':*')) continue
      if (q && !(p.perm_code.toLowerCase().includes(q) || (p.perm_name || '').toLowerCase().includes(q) || (p.module || '').toLowerCase().includes(q))) continue
      ;(groups[p.module] = groups[p.module] || []).push(p)
    }
    return Object.entries(groups).map(([module, items]) => ({
      module,
      items: items.sort((a, b) => a.sort_order - b.sort_order),
    }))
  }, [perms, permSearch])

  const openCreate = () => {
    editRowRef.current = null
    setEditing(null)
    setMenuChecked([])
    setModalOpen(true)
  }

  const openEdit = (row) => {
    editRowRef.current = row
    setEditing(row)
    setMenuChecked(row.menu_ids || [])
    setModalOpen(true)
  }

  // Modal 打开动画结束后再 setFieldsValue —— 保证 Form.Item 已完成 DOM 注册
  const handleAfterOpen = (open) => {
    if (!open) return
    const row = editRowRef.current
    form.resetFields()
    if (row) {
      form.setFieldsValue({
        role_name: row.role_name,
        description: row.description || '',
        perm_codes: row.perm_codes || [],
      })
    }
  }

  const submit = async () => {
    const values = await form.validateFields()
    const payload = {
      role_name: values.role_name,
      description: values.description,
      perm_codes: values.perm_codes || [],
      menu_ids: menuChecked || [],
    }
    try {
      if (editing) {
        await http.put(`/admin/roles/${editing.id}`, payload)
        message.success('角色更新成功')
      } else {
        await http.post('/admin/roles', { ...payload, role_code: values.role_code })
        message.success('角色创建成功')
      }
      setModalOpen(false)
      load()
    } catch (e) {
      // http 拦截器已经弹过 error，这里兜底
      if (e?.message) message.error(e.message)
    }
  }

  const remove = async (id) => {
    await http.delete(`/admin/roles/${id}`)
    message.success('角色已删除')
    load()
  }

  const columns = [
    { title: '角色编码', dataIndex: 'role_code', width: 160 },
    { title: '角色名称', dataIndex: 'role_name', width: 160 },
    { title: '类型', dataIndex: 'role_type', width: 110, render: (v) => <Tag color="blue">{v}</Tag> },
    { title: '内置', dataIndex: 'is_system', width: 80, render: (v) => (v ? <Tag color="orange">系统</Tag> : '-') },
    {
      title: '权限 / 菜单', width: 140, align: 'center',
      render: (_, row) => {
        const p = (row.perm_codes || []).length
        const m = (row.menu_ids || []).length
        return <Typography.Text>{p}/{m}</Typography.Text>
      }
    },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v) => (v ? String(v).slice(0, 19).replace('T', ' ') : '-') },
    {
      title: '操作',
      width: 140,
      render: (_, row) => (
        <Space>
          <Button type="link" size="small" onClick={() => openEdit(row)}>编辑</Button>
          {!row.is_system && (
            <Popconfirm title="确认删除该角色？" onConfirm={() => remove(row.id)}>
              <Button type="link" size="small" danger>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  const treeData = useMemo(() => toTreeData(menuTree), [menuTree])

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>角色权限</Typography.Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建角色</Button>
        </Space>
      </div>
      <Card>
        <Table rowKey="id" loading={loading} columns={columns} dataSource={rows}
          pagination={{ showTotal: (t) => `共 ${t} 条`, showSizeChanger: true, showQuickJumper: true }} />
      </Card>
      <Modal
        title={editing ? `编辑角色：${editing.role_name}` : '新建角色'}
        open={modalOpen}
        onOk={submit}
        onCancel={() => setModalOpen(false)}
        afterOpenChange={handleAfterOpen}
        width={900}
        okText={editing ? '保存' : '创建'}
        cancelText="取消"
      >
        <Form form={form} layout="vertical" preserve={false}>
          {!editing && (
            <Form.Item name="role_code" label="角色编码" rules={[
              { required: true, min: 2 },
              { pattern: /^[A-Z0-9_]+$/, message: '仅允许大写字母、数字、下划线' },
            ]}>
              <Input placeholder="如 QA_LEAD" />
            </Form.Item>
          )}
          <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
            <Form.Item name="role_name" label="角色名称" rules={[{ required: true }]} style={{ width: '50%' }}>
              <Input placeholder="如：质量负责人" />
            </Form.Item>
            <Form.Item name="description" label="描述" style={{ width: '50%' }}>
              <Input.TextArea rows={1} placeholder="角色职责简述" />
            </Form.Item>
          </Space.Compact>
          <Tabs
            defaultActiveKey="perms"
            items={[
              {
                key: 'perms',
                label: '功能权限',
                children: (
                  <>
                    <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                      控制角色能调用哪些后端接口，前端按钮的显示/隐藏也由此驱动。按模块分组，搜索支持编码/名称/模块。
                    </Typography.Text>
                    <Input.Search
                      size="small"
                      placeholder="搜索权限编码 / 名称 / 模块"
                      value={permSearch}
                      onChange={(e) => setPermSearch(e.target.value)}
                      allowClear
                      style={{ marginBottom: 8 }}
                    />
                    <Form.Item name="perm_codes">
                      <Checkbox.Group style={{ width: '100%' }}>
                        <Collapse
                          size="small"
                          defaultActiveKey={permGroups.map(g => g.module)}
                          items={permGroups.map((g) => ({
                            key: g.module,
                            label: `${moduleLabel(g.module)}（${g.items.length}）`,
                            children: (
                              <Space direction="vertical" size={6}>
                                {g.items.map((p) => (
                                  <Checkbox key={p.perm_code} value={p.perm_code}>
                                    {p.perm_name} <Typography.Text type="secondary" style={{ fontSize: 12 }}>({p.perm_code})</Typography.Text>
                                  </Checkbox>
                                ))}
                              </Space>
                            ),
                          }))}
                        />
                      </Checkbox.Group>
                    </Form.Item>
                  </>
                ),
              },
              {
                key: 'menus',
                label: '菜单可见性',
                children: (
                  <>
                    <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                      控制角色登录后左侧导航栏能看到哪些菜单项。SUPER_ADMIN 不受此限制，始终全量显示。
                      勾选子菜单时其父目录会自动补齐。
                    </Typography.Text>
                    {treeData.length === 0 ? (
                      <Typography.Text type="secondary">菜单数据加载中…</Typography.Text>
                    ) : (
                      <Tree
                        checkable
                        showLine={false}
                        defaultExpandAll
                        checkedKeys={menuChecked}
                        onCheck={(keys) => setMenuChecked(keys)}
                        treeData={treeData}
                      />
                    )}
                    <div style={{ marginTop: 8 }}>
                      <Button size="small" type="link" onClick={() => setMenuChecked([])}>清空</Button>
                      <Button size="small" type="link" onClick={() => {
                        const all = []
                        const walk = (nodes) => {
                          nodes.forEach((n) => {
                            all.push(n.key)
                            if (n.children?.length) walk(n.children)
                          })
                        }
                        walk(treeData)
                        setMenuChecked(all)
                      }}>全选</Button>
                      <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                        已选 {menuChecked.length} 项
                      </Typography.Text>
                    </div>
                  </>
                ),
              },
            ]}
          />
        </Form>
      </Modal>
    </Space>
  )
}
