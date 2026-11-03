/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useState, useEffect } from 'react'
import { Tabs, Table, Button, Input, Select, App, Modal, Space, Popconfirm, Tag, Descriptions, Result } from 'antd'
import { PlusOutlined, CopyOutlined, MailOutlined } from '@ant-design/icons'
import http from '../../api/http'

export default function WorkspaceSettings() {
  const { message } = App.useApp()
  const [members, setMembers] = useState([])
  const [invites, setInvites] = useState([])
  const [workspace, setWorkspace] = useState(null)
  const [loading, setLoading] = useState(false)
  const [roleLoading, setRoleLoading] = useState(null)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('member')
  const [inviting, setInviting] = useState(false)
  const [inviteUrl, setInviteUrl] = useState('')
  const [newName, setNewName] = useState('')
  const [savingName, setSavingName] = useState(false)

  // 后端 orgs 路由要求带 org_id（/orgs/{org_id}/members 等）
  // loadAll 先拉 /orgs/my 拿到 cur.org_id 后再并行拉 members / invitations
  const loadAll = async () => {
    setLoading(true)
    try {
      // Step 1: 拿当前 org
      const w = await http.get('/orgs/my').catch((e) => { console.warn('[Workspace] orgs/my fail', e); return null })
      const list = w?.items || w || []
      const cur = list.find((o) => o.is_current || o.current) || list[0]
      const orgId = cur?.org_id || cur?.id
      setWorkspace(cur)
      setNewName(cur?.org_name || cur?.name || '')

      if (!orgId) {
        setMembers([]); setInvites([])
        return
      }

      // Step 2: 用 orgId 拉 members + invitations
      const [m, i] = await Promise.all([
        http.get(`/orgs/${orgId}/members`).catch((e) => { console.warn('[Workspace] members fail', e); return { items: [] } }),
        http.get(`/orgs/${orgId}/invitations`).catch((e) => { console.warn('[Workspace] invitations fail', e); return { items: [] } }),
      ])
      setMembers(m?.items || m || [])
      setInvites(i?.items || i || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  const changeRole = async (userId, role) => {
    const orgId = workspace?.org_id || workspace?.id
    if (!orgId) { message.warning('未获取到空间 ID'); return }
    setRoleLoading(userId)
    try {
      // 后端: PUT /orgs/{org_id}/members/{user_id} + {role}
      await http.put(`/orgs/${orgId}/members/${userId}`, { role })
      message.success('已更新')
      loadAll()
    } catch (e) { console.warn('[Workspace] changeRole fail', e); message.error('更新失败') }
    finally { setRoleLoading(null) }
  }

  const removeMember = async (userId) => {
    const orgId = workspace?.org_id || workspace?.id
    if (!orgId) return
    try {
      await http.delete(`/orgs/${orgId}/members/${userId}`)
      message.success('已移除')
      loadAll()
    } catch (e) { console.warn('[Workspace] removeMember fail', e); message.error('移除失败') }
  }

  const doInvite = async () => {
    const orgId = workspace?.org_id || workspace?.id
    if (!orgId) { message.warning('未获取到空间 ID'); return }
    if (!inviteEmail) { message.error('请输入邮箱'); return }
    setInviting(true)
    try {
      // 后端: POST /orgs/{org_id}/members/invite
      const data = await http.post(`/orgs/${orgId}/members/invite`, { email: inviteEmail, role: inviteRole })
      const acceptUrl = `${window.location.origin}/invite/accept?token=${data?.token || data?.invite_token}`
      setInviteUrl(acceptUrl)
      setInvites((prev) => [...prev, { email: inviteEmail, role: inviteRole, token: data?.token, accept_url: acceptUrl, created_at: new Date().toISOString(), status: 'pending' }])
      setInviteEmail('')
      Modal.success({
        title: '邀请已创建',
        content: (
          <div>
            <p style={{ color: '#8ba3b5' }}>请将以下链接发送给对方：</p>
            <Input.TextArea rows={3} value={acceptUrl} readOnly style={{ fontFamily: 'monospace', background: '#0b0f14', borderColor: '#1f2833', color: '#e6f7ff' }} />
          </div>
        ),
        okText: '好的',
      })
    } catch (e) { console.warn('[Workspace] doInvite fail', e); message.error('邀请失败') }
    finally { setInviting(false) }
  }

  const doSaveName = async () => {
    const orgId = workspace?.org_id || workspace?.id
    if (!orgId) return
    setSavingName(true)
    try {
      // 后端: PUT /orgs/{org_id}
      await http.put(`/orgs/${orgId}`, { name: newName, org_name: newName })
      message.success('已保存')
      loadAll()
    } catch (e) { console.warn('[Workspace] doSaveName fail', e); message.error('保存失败') }
    finally { setSavingName(false) }
  }

  const roleOptions = [
    { label: '管理员', value: 'ADMIN' },
    { label: '成员',   value: 'TESTER' },
    { label: '只读',   value: 'VIEWER' },
    { label: '审计',   value: 'AUDITOR' },
  ]

  const statusTag = (s) => {
    const map = {
      active: { color: 'green', text: '正常' },
      disabled: { color: 'red', text: '已停用' },
      pending: { color: 'orange', text: '待处理' },
    }
    const x = map[s] || { color: 'default', text: s || '未知' }
    return <Tag color={x.color}>{x.text}</Tag>
  }

  const memberCols = [
    { title: '用户名', dataIndex: 'username', key: 'username', render: (v, r) => v || r.user_id },
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    {
      title: '角色', dataIndex: 'role', key: 'role', width: 160,
      render: (v, r) => (
        <Select
          value={v || 'member'}
          options={roleOptions}
          loading={roleLoading === r.user_id}
          style={{ width: 120 }}
          onChange={(x) => changeRole(r.user_id, x)}
        />
      ),
    },
    { title: '加入时间', dataIndex: 'joined_at', key: 'joined_at', render: (v) => v || '—' },
    { title: '状态', dataIndex: 'status', key: 'status', render: statusTag },
    {
      title: '操作', key: 'act', width: 100,
      render: (_, r) => (
        <Popconfirm title="确认移除该成员？" onConfirm={() => removeMember(r.user_id)} okText="移除" cancelText="取消">
          <Button type="link" danger size="small">移除</Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <div>
      <h2 className="title-bar" style={{ marginBottom: 16, color: '#e6f7ff' }}>空间设置</h2>
      <Tabs
        items={[
          {
            key: 'members',
            label: '成员管理',
            children: (
              <Table
                rowKey="user_id"
                loading={loading}
                dataSource={members}
                columns={memberCols}
                pagination={{ pageSize: 10 }}
                size="small"
              />
            ),
          },
          {
            key: 'invite',
            label: '邀请成员',
            children: (
              <div>
                <Space style={{ marginBottom: 16 }}>
                  <Input
                    placeholder="邮箱地址"
                    type="email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    style={{ width: 260 }}
                  />
                  <Select
                    options={roleOptions}
                    value={inviteRole}
                    onChange={setInviteRole}
                    style={{ width: 120 }}
                  />
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    loading={inviting}
                    onClick={doInvite}
                    style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
                  >
                    生成邀请
                  </Button>
                </Space>

                <h4 style={{ color: '#e6f7ff', margin: '16px 0 8px' }}>待处理邀请</h4>
                <Table
                  rowKey={(r) => r.token || r.email}
                  size="small"
                  dataSource={invites}
                  loading={loading}
                  pagination={{ pageSize: 10 }}
                  columns={[
                    { title: '邮箱', dataIndex: 'email', key: 'email' },
                    { title: '角色', dataIndex: 'role', key: 'role' },
                    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (v) => v ? v.slice(0, 19).replace('T', ' ') : '—' },
                    {
                      title: '链接', key: 'url', render: (_, r) => {
                        const url = r.accept_url || (r.token ? `${window.location.origin}/invite/accept?token=${r.token}` : '')
                        if (!url) return <span style={{ color: '#869BAA' }}>—</span>
                        return (
                          <Space>
                            <span className="mono" style={{ maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: '#8ba3b5' }}>
                              {url}
                            </span>
                            <Button
                              type="link"
                              size="small"
                              icon={<CopyOutlined />}
                              onClick={() => {
                                navigator.clipboard?.writeText(url).then(() => message.success('已复制'))
                              }}
                            >
                              复制
                            </Button>
                          </Space>
                        )
                      },
                    },
                    { title: '状态', dataIndex: 'status', key: 'status', render: statusTag },
                  ]}
                />
              </div>
            ),
          },
          {
            key: 'info',
            label: '空间信息',
            children: (
              <div style={{ maxWidth: 640 }}>
                <Descriptions column={1} bordered size="small" labelStyle={{ width: 140, color: '#8ba3b5' }} contentStyle={{ color: '#e6f7ff' }}>
                  <Descriptions.Item label="空间 ID">
                    <span className="mono">{workspace?.id || '—'}</span>
                  </Descriptions.Item>
                  <Descriptions.Item label="空间名称">
                    <Space>
                      <Input
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        style={{ maxWidth: 240 }}
                      />
                      <Button
                        type="primary"
                        loading={savingName}
                        onClick={doSaveName}
                        style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
                      >
                        保存
                      </Button>
                    </Space>
                  </Descriptions.Item>
                  <Descriptions.Item label="创建时间">{workspace?.created_at || '—'}</Descriptions.Item>
                  <Descriptions.Item label="每月任务配额（只读）">
                    <span className="mono" style={{ color: '#13c2c2' }}>{workspace?.quota?.task_monthly ?? workspace?.monthly_quota ?? '—'}</span>
                  </Descriptions.Item>
                </Descriptions>
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}
