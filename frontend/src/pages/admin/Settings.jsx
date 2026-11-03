/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useState, useMemo } from 'react'
import { Table, Card, Input, Select, Switch, Button, Space, App, InputNumber } from 'antd'
import { ReloadOutlined, SaveOutlined } from '@ant-design/icons'
import http from '../../api/http'
import VulnDbCard from '../../components/security/VulnDbCard'

export default function AdminSettings() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [activeGroup, setActiveGroup] = useState(null)
  const [editMap, setEditMap] = useState({})   // id → new value
  const { message } = App.useApp()

  const load = async () => {
    setLoading(true)
    try {
      const d = await http.get('/admin/settings')
      setRows(d.items || d || [])
      const groups = d.groups || [...new Set((d.items || []).map((s) => s.group))]
      setActiveGroup(activeGroup || groups[0] || null)
    } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const groups = useMemo(() => [...new Set(rows.map((s) => s.group))], [rows])
  const filtered = rows.filter((s) => s.group === activeGroup)

  const updateValue = (id, val) => setEditMap((m) => ({ ...m, [id]: val }))

  const save = async () => {
    const items = Object.entries(editMap).map(([id, value]) => ({ id: Number(id), value: String(value) }))
    if (!items.length) { message.warning('无修改'); return }
    try {
      await http.put('/admin/settings/batch', { items })
      message.success('保存成功')
      setEditMap({})
      load()
    } catch (e) { console.warn(e) }
  }

  const renderValueInput = (s) => {
    const cur = (s.id in editMap) ? editMap[s.id] : s.value
    if (s.is_secret && !cur) return <Input.Password placeholder="未设置" onChange={(e) => updateValue(s.id, e.target.value)} />
    if (s.value_type === 'boolean') return <Switch checked={String(cur).toLowerCase() === 'true'} onChange={(v) => updateValue(s.id, v ? 'true' : 'false')} />
    if (s.value_type === 'integer') return <InputNumber value={Number(cur) || 0} onChange={(v) => updateValue(s.id, v)} />
    if (s.value_type === 'json') return <Input.TextArea rows={2} value={cur || ''} onChange={(e) => updateValue(s.id, e.target.value)} />
    return <Input value={cur || ''} onChange={(e) => updateValue(s.id, e.target.value)} />
  }

  const columns = [
    { title: '参数', dataIndex: 'key', width: 180, render: (k) => <code>{k}</code> },
    { title: '当前值', width: 260, render: (_, s) => renderValueInput(s) },
    { title: '类型', dataIndex: 'value_type', width: 90 },
    { title: '描述', dataIndex: 'description' },
    { title: '敏感', dataIndex: 'is_secret', width: 70, render: (v) => v ? '🔒' : '-' },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        分组：
        <Select style={{ width: 160 }} value={activeGroup} onChange={setActiveGroup}
          options={groups.map((g) => ({ label: g, value: g }))} />
        <Button type="primary" icon={<SaveOutlined />} onClick={save}>保存修改 ({Object.keys(editMap).length})</Button>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Card>
        <Table rowKey="id" loading={loading} columns={columns} dataSource={filtered} pagination={false} />
      </Card>
      <div style={{ marginTop: 16 }}>
        <VulnDbCard />
      </div>
    </div>
  )
}
