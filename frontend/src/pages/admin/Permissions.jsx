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
import { Table, Card, Input, Space, Tag, App } from 'antd'
import { ReloadOutlined, LockOutlined } from '@ant-design/icons'
import http from '../../api/http'

export default function AdminPermissions() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const { message } = App.useApp()

  const load = async () => {
    setLoading(true)
    try {
      const d = await http.get('/admin/permissions')
      setRows(d.items || d || [])
    } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const grouped = useMemo(() => {
    const q = search.trim().toLowerCase()
    const byModule = {}
    for (const p of rows) {
      if (q && !(p.perm_code?.toLowerCase().includes(q) || (p.perm_name || '').toLowerCase().includes(q) || (p.module || '').toLowerCase().includes(q))) continue
      byModule[p.module || 'other'] = byModule[p.module || 'other'] || []
      byModule[p.module || 'other'].push(p)
    }
    return byModule
  }, [rows, search])

  const columns = [
    { title: '权限码', dataIndex: 'perm_code', width: 200, render: (c) => <code>{c}</code> },
    { title: '名称', dataIndex: 'perm_name', width: 180 },
    { title: '模块', dataIndex: 'module', width: 120, render: (m) => <Tag color="blue">{m}</Tag> },
    { title: '类型', dataIndex: 'perm_type', width: 90 },
    { title: '父权限', dataIndex: 'parent_code', width: 160, render: (c) => c ? <code>{c}</code> : '-' },
    { title: '排序', dataIndex: 'sort_order', width: 70 },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Input.Search allowClear placeholder="搜索 权限码 / 名称 / 模块" style={{ width: 320 }}
          onSearch={setSearch} onChange={(e) => !e.target.value && setSearch('')} />
        <a onClick={load}><ReloadOutlined /> 刷新</a>
      </Space>
      {Object.entries(grouped).map(([mod, list]) => (
        <Card key={mod} size="small" title={<span><LockOutlined /> {mod} <span style={{color:'#888',fontSize:12}}>({list.length})</span></span>}
          style={{ marginBottom: 12 }}>
          <Table rowKey="id" loading={loading} columns={columns} dataSource={list} pagination={false} size="small" />
        </Card>
      ))}
      {Object.keys(grouped).length === 0 && !loading && <div style={{color:'#888'}}>无匹配权限</div>}
    </div>
  )
}
