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
  Table, Button, Card, Space, Tag, Modal, Form, Input, Select, App, Popconfirm, Typography, Drawer, Divider,
} from 'antd'
import { PlusOutlined, ReloadOutlined, ClearOutlined, UserOutlined, LinkOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import http from '../api/http'
import { fmtTime } from '../utils'
import { PROJECT_STATUS_MAP, MEMBER_ROLE_MAP, MEMBER_ROLE_COLOR, PROJECT_VISIBILITY_MAP } from '../constants/enums'

const { Text } = Typography

export default function Projects() {
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [loading, setLoading] = useState(false)
  // 列表筛选：keyword（名称/编号模糊）+ status（ACTIVE/ARCHIVED）
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState(null)
  const [statusFilter, setStatusFilter] = useState(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const { message } = App.useApp()

  // 成员管理 Drawer 状态
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerProject, setDrawerProject] = useState(null)
  const [members, setMembers] = useState([])
  const [membersLoading, setMembersLoading] = useState(false)
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [addForm] = Form.useForm()
  const [allUsers, setAllUsers] = useState([])

  // ---------- 项目列表 ----------
  const load = async (p = page, ps = pageSize, kw = keyword, st = statusFilter) => {
    setLoading(true)
    try {
      const params = { page: p, page_size: ps }
      if (kw) params.keyword = kw
      if (st) params.status = st
      const data = await http.get('/projects', { params })
      setRows(data.items || [])
      setTotal(data.total || 0)
    } finally {
      setLoading(false)
    }
  }

  const handleSearch = () => {
    const kw = keywordInput.trim() || null
    setKeyword(kw)
    setPage(1)
    load(1, pageSize, kw, statusFilter)
  }

  const handleReset = () => {
    setKeywordInput('')
    setKeyword(null)
    setStatusFilter(null)
    setPage(1)
    load(1, pageSize, null, null)
  }

  useEffect(() => {
    load(1, pageSize)
  }, [])

  // ---------- 新建/编辑项目 ----------
  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = async (row) => {
    setEditing(row)
    try {
      const detail = await http.get(`/projects/${row.id}`)
      form.setFieldsValue({
        name: detail.name,
        description: detail.description,
        target_system: detail.target_system,
        visibility: detail.visibility,
        status: detail.status,
      })
    } catch {
      // 详情获取失败时降级
      form.setFieldsValue({
        name: row.name,
        description: row.description,
        target_system: row.target_system,
        visibility: row.visibility,
        status: row.status,
      })
    }
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    const payload = { ...values }

    if (editing) {
      await http.put(`/projects/${editing.id}`, payload)
      message.success('项目更新成功')
    } else {
      await http.post('/projects', payload)
      message.success('项目创建成功')
    }
    setModalOpen(false)
    load(editing ? page : 1)
  }

  const remove = async (id) => {
    await http.delete(`/projects/${id}`)
    message.success('项目已删除')
    load(page)
  }

  // ---------- 成员管理 ----------
  const openMemberDrawer = (record) => {
    setDrawerProject(record)
    setDrawerOpen(true)
    loadMembers(record.id)
  }

  const loadMembers = async (projectId) => {
    setMembersLoading(true)
    try {
      const data = await http.get(`/projects/${projectId}/members`)
      // 兼容两种返回结构：直接数组 或 {items: []}
      setMembers(Array.isArray(data) ? data : (data.items || []))
    } catch {
      setMembers([])
    } finally {
      setMembersLoading(false)
    }
  }

  const updateMemberRole = async (memberId, newRole) => {
    try {
      await http.put(`/projects/${drawerProject.id}/members/${memberId}`, { role: newRole })
      message.success('角色已更新')
      loadMembers(drawerProject.id)
    } catch {
      /* 拦截器已提示 */
    }
  }

  const removeMember = async (memberId) => {
    try {
      await http.delete(`/projects/${drawerProject.id}/members/${memberId}`)
      message.success('成员已移除')
      loadMembers(drawerProject.id)
    } catch {
      /* 拦截器已提示 */
    }
  }

  // 打开添加成员弹窗前先拉用户列表
  const openAddMember = async () => {
    addForm.resetFields()
    setAddModalOpen(true)
    try {
      const data = await http.get('/admin/users', { params: { page_size: 200 } })
      setAllUsers(Array.isArray(data) ? data : (data.items || []))
    } catch {
      setAllUsers([])
    }
  }

  const submitAddMember = async () => {
    const values = await addForm.validateFields()
    try {
      await http.post(`/projects/${drawerProject.id}/members`, values)
      message.success('成员已添加')
      setAddModalOpen(false)
      loadMembers(drawerProject.id)
    } catch {
      /* 拦截器已提示 */
    }
  }

  // 已在成员列表的用户 ID 集合
  const memberUserIds = new Set(members.map((m) => m.user_id || m.username))

  // ---------- 表格列 ----------
  const columns = [
    { title: '项目编号', dataIndex: 'code', width: 200, render: (v) => <span className="mono">{v || '#'}</span> },
    { title: '项目名称', dataIndex: 'name', ellipsis: true, render: (v, r) => <a onClick={() => navigate(`/projects/${r.id}`)}>{v}</a> },
    { title: '被测系统', dataIndex: 'target_system', width: 180, ellipsis: true, render: (v) => v || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v) => <Tag color={v === 'ACTIVE' ? 'green' : v === 'ARCHIVED' ? 'orange' : 'default'}>{PROJECT_STATUS_MAP[v] || v}</Tag>,
    },
    { title: '可见性', dataIndex: 'visibility', width: 100, render: (v) => PROJECT_VISIBILITY_MAP[v] || v },
    { title: '负责人', dataIndex: 'owner_name', width: 120, render: (v) => v || '-' },
    { title: '任务数', dataIndex: 'task_count', width: 90, align: 'center' },
    { title: '创建时间', dataIndex: 'created_at', width: 170, render: (v) => fmtTime(v) },
    {
      title: '操作',
      width: 260,
      fixed: 'right',
      render: (_, row) => (
        <Space wrap size={4}>
          <Button type="link" size="small" icon={<UserOutlined />} onClick={() => openMemberDrawer(row)}>成员</Button>
          <Button type="link" size="small" onClick={() => openEdit(row)}>编辑</Button>
          <Popconfirm title="确认删除该项目？" onConfirm={() => remove(row.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
          <Divider type="vertical" />
          <Button type="link" size="small" icon={<LinkOutlined />} onClick={() => navigate(`/assets?project_id=${row.id}`)}>资产</Button>
          <Button type="link" size="small" icon={<LinkOutlined />} onClick={() => navigate(`/tasks?project_id=${row.id}`)}>任务</Button>
        </Space>
      ),
    },
  ]

  // 成员管理表格列
  const memberColumns = [
    {
      title: '用户名',
      dataIndex: 'display_name',
      render: (v, r) => (
        <Space>
          <UserOutlined />
          <span>{v || r.username || r.user_id || '-'}</span>
          {r.username && r.username !== v && <Text type="secondary">({r.username})</Text>}
        </Space>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      width: 120,
      render: (v) => (
        <Tag color={MEMBER_ROLE_COLOR[v] || 'default'}>{MEMBER_ROLE_MAP[v] || v}</Tag>
      ),
    },
    {
      title: '操作',
      width: 220,
      render: (_, m) => (
        <Space>
          <Select
            size="small"
            style={{ width: 110 }}
            value={m.role}
            disabled={m.role === 'OWNER'}
            onChange={(val) => updateMemberRole(m.user_id || m.id, val)}
            options={[
              { value: 'OWNER', label: '负责人' },
              { value: 'MEMBER', label: '成员' },
              { value: 'VIEWER', label: '只读' },
            ]}
          />
          {m.role !== 'OWNER' && (
            <Popconfirm title="确认移除该成员？" onConfirm={() => removeMember(m.user_id || m.id)}>
              <Button type="link" size="small" danger>移除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>项目管理</Typography.Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建项目</Button>
        </Space>
      </div>
      <Card>
        <Space style={{ marginBottom: 16 }} wrap>
          <Input.Search
            placeholder="搜索项目名称/编号"
            allowClear
            style={{ width: 240 }}
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            onSearch={handleSearch}
          />
          <Select
            allowClear
            placeholder="全部状态"
            style={{ width: 140 }}
            value={statusFilter}
            onChange={(val) => {
              setStatusFilter(val || null)
              setPage(1)
              load(1, pageSize, keyword, val || null)
            }}
            options={Object.entries(PROJECT_STATUS_MAP).map(([value, label]) => ({ value, label }))}
          />
          <Button icon={<ClearOutlined />} onClick={handleReset}>重置</Button>
        </Space>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={rows}
          scroll={{ x: 'max-content' }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true, showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => {
              setPage(p)
              setPageSize(ps)
              load(p, ps)
            },
          }}
        />
      </Card>

      {/* 新建/编辑项目 Modal */}
      <Modal
        title={editing ? '编辑项目' : '新建项目'}
        open={modalOpen}
        onOk={submit}
        onCancel={() => setModalOpen(false)}
        destroyOnHidden
        width={900}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}>
            <Input placeholder="如：智能问答系统验收测试" />
          </Form.Item>
          <Form.Item
            name="target_system" label="被测系统（备注）"
            extra="仅项目文字备注，不参与执行；功能测试地址在项目「环境」Tab 配置，AI 评测靶机在「被测系统」页注册"
          >
            <Input placeholder="被测系统名称 / 版本（如：智能客服系统 v2.1）" />
          </Form.Item>

          <Form.Item name="visibility" label="可见性" initialValue="PRIVATE">
            <Select options={[{ value: 'PRIVATE', label: '私有' }, { value: 'PUBLIC', label: '公开' }]} />
          </Form.Item>
          {editing && (
            <Form.Item name="status" label="状态" initialValue="ACTIVE">
              <Select options={[{ value: 'ACTIVE', label: '启用' }, { value: 'ARCHIVED', label: '已归档' }]} />
            </Form.Item>
          )}
          <Form.Item name="description" label="项目描述">
            <Input.TextArea rows={3} placeholder="项目目标、测试范围等" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 成员管理 Drawer */}
      <Drawer
        title={drawerProject ? `项目成员管理 - ${drawerProject.name}` : '项目成员管理'}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={640}
        extra={
          <Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={openAddMember}>添加成员</Button>
          </Space>
        }
      >
        <Table
          rowKey={(r) => r.user_id || r.username || r.id}
          loading={membersLoading}
          columns={memberColumns}
          dataSource={members}
          pagination={{ pageSize: 10 }}
        />
      </Drawer>

      {/* 添加成员 Modal */}
      <Modal
        title="添加项目成员"
        open={addModalOpen}
        onOk={submitAddMember}
        cancelText="取消"
        onCancel={() => setAddModalOpen(false)}
        destroyOnHidden
        width={760}
      >
        <Form form={addForm} layout="vertical">
          <Form.Item name="user_id" label="选择用户" rules={[{ required: true, message: '请选择用户' }]}>
            <Select
              showSearch
              placeholder="搜索并选择要添加的用户"
              optionFilterProp="label"
              options={allUsers
                .filter((u) => !memberUserIds.has(u.id) && !memberUserIds.has(u.username))
                .map((u) => ({
                  value: u.id || u.user_id || u.username,
                  label: `${u.display_name || u.username || u.id} (${u.username || u.email || ''})`,
                }))}
            />
          </Form.Item>
          <Form.Item name="role" label="角色" initialValue="MEMBER" rules={[{ required: true, message: '请选择角色' }]}>
            <Select
              options={[
                { value: 'OWNER', label: '负责人' },
                { value: 'MEMBER', label: '成员' },
                { value: 'VIEWER', label: '只读' },
              ]}
            />
          </Form.Item>
        </Form>
        <Typography.Text type="secondary">
          注：仅显示 200 条可用用户，已在项目中的成员已过滤。
        </Typography.Text>
      </Modal>

      {/* 补 code 列：列表里展示项目业务编号（与底部说明对齐） */}
      {/* 已在 columns 定义了第一列 name，code 可作为第二列展示 */}
    </Space>
  )
}
