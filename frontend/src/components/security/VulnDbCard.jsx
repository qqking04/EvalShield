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
  Card, Table, Button, Space, Input, App, Tag, Alert, Popconfirm, Typography, Tooltip,
} from 'antd'
import {
  BugOutlined, ReloadOutlined, SaveOutlined, PlusOutlined, DeleteOutlined, EditOutlined,
} from '@ant-design/icons'
import http from '../../api/http'
import { useAuth } from '../../auth'

// A06 易损/过时组件版本表管理卡片（v2.0 推荐方案 #1）：
// 查看当前生效版本表 → 编辑（增删改）→ 保存写回外置文件并热更引擎，无需重启后端。
// 查看对所有登录用户开放；编辑/保存/热更需要 admin:* 权限。
export default function VulnDbCard() {
  const { message } = App.useApp()
  const { hasPerm } = useAuth()
  const canEdit = hasPerm('admin:*')
  const [meta, setMeta] = useState(null)          // { updated_at, source, count, path }
  const [rows, setRows] = useState([])            // [{ key, pattern, desc }]
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [editing, setEditing] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const d = await http.get('/security/vuln-db')
      setMeta(d)
      setRows((d.patterns || []).map((p, i) => ({ key: i, pattern: p.pattern, desc: p.desc })))
      setEditing(false)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  const patchRow = (key, field, val) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, [field]: val } : r)))

  const addRow = () =>
    setRows((rs) => [...rs, { key: Date.now(), pattern: '', desc: '' }])

  const delRow = (key) => setRows((rs) => rs.filter((r) => r.key !== key))

  const save = async () => {
    const patterns = rows
      .map((r) => ({ pattern: (r.pattern || '').trim(), desc: (r.desc || '').trim() }))
      .filter((p) => p.pattern)
    if (!patterns.length) { message.warning('至少保留一条有效正则'); return }
    setSaving(true)
    try {
      const d = await http.put('/security/vuln-db', { patterns })
      message.success(`已保存并热更新，当前生效 ${d.count} 条`)
      load()
    } finally {
      setSaving(false)
    }
  }

  const hotRefresh = async () => {
    setRefreshing(true)
    try {
      const d = await http.post('/security/refresh-vuln-db', {})
      message.success(`已重新读取外置版本表，当前生效 ${d.count} 条`)
      load()
    } finally {
      setRefreshing(false)
    }
  }

  const columns = editing
    ? [
      {
        title: '匹配正则（Server / X-Powered-By，小写）',
        dataIndex: 'pattern',
        render: (v, r) => <Input value={v} placeholder="如 nginx/1.1[0-7]." onChange={(e) => patchRow(r.key, 'pattern', e.target.value)} />,
      },
      {
        title: '风险说明',
        dataIndex: 'desc',
        render: (v, r) => <Input value={v} placeholder="如 Nginx 1.10-1.17（EOL）" onChange={(e) => patchRow(r.key, 'desc', e.target.value)} />,
      },
      {
        title: '操作',
        width: 70,
        render: (_, r) => (
          <Popconfirm title="删除该条？" okText="删除" cancelText="取消" onConfirm={() => delRow(r.key)}>
            <Button type="text" danger size="small" icon={<DeleteOutlined />} />
          </Popconfirm>
        ),
      },
    ]
    : [
      {
        title: '匹配正则（Server / X-Powered-By，小写）',
        dataIndex: 'pattern',
        render: (v) => <code>{v}</code>,
      },
      { title: '风险说明', dataIndex: 'desc' },
    ]

  return (
    <Card
      title={<Space><BugOutlined />A06 易损/过时组件版本表</Space>}
      extra={
        <Space>
          {meta && <Tag color="blue">生效 {meta.count} 条</Tag>}
          {meta && <Tooltip title={meta.path}><Tag>{meta.updated_at === 'builtin' ? '内置回退表' : `更新于 ${meta.updated_at}`}</Tag></Tooltip>}
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="安全测试引擎按此表比对被测系统响应头版本，命中即判「易损/过时组件」风险。保存后即时热更新，无需重启后端。"
      />
      <Space style={{ marginBottom: 12 }} wrap>
        {canEdit && !editing && (
          <Button icon={<EditOutlined />} onClick={() => setEditing(true)}>编辑</Button>
        )}
        {canEdit && editing && (
          <>
            <Button icon={<PlusOutlined />} onClick={addRow}>新增规则</Button>
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={save}>保存并热更新</Button>
            <Button onClick={() => load()}>取消</Button>
          </>
        )}
        {canEdit && (
          <Button icon={<ReloadOutlined />} loading={refreshing} onClick={hotRefresh}>重新读取文件</Button>
        )}
      </Space>
      <Table
        rowKey="key"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
        scroll={{ y: 360 }}
      />
      {!editing && (
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
          数据文件：backend/data/vuln_components.json · 命中示例：Server: nginx/1.16.1 → 判为 EOL 风险
        </Typography.Text>
      )}
    </Card>
  )
}
