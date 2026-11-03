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
import { Table, Card, Input, Select, Space, Tag, Button } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import http from '../../api/http'

export default function AdminLoginLogs() {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState(null)
  const [username, setUsername] = useState('')
  const [ip, setIp] = useState('')

  const load = async (p = page) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: p, page_size: 20 })
      if (status) params.set('status', status)
      if (username) params.set('username', username)
      if (ip) params.set('ip', ip)
      const d = await http.get(`/admin/login-logs?${params.toString()}`)
      setRows(d.items || [])
      setTotal(d.total || 0)
      setPage(p)
    } finally { setLoading(false) }
  }
  useEffect(() => { load(1) }, [])

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '用户名', dataIndex: 'username', width: 180 },
    { title: 'IP', dataIndex: 'ip', width: 160, render: (v) => <code>{v}</code> },
    { title: '状态', dataIndex: 'success', width: 100, render: (v) => v ? <Tag color="green">成功</Tag> : <Tag color="red">失败</Tag> },
    { title: '失败原因', dataIndex: 'fail_reason', render: (v) => v || '-' },
    { title: '时间', dataIndex: 'created_at', width: 210 },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 12 }} wrap>
        <Input placeholder="用户名" style={{ width: 160 }} value={username} onChange={(e) => setUsername(e.target.value)} />
        <Input placeholder="IP" style={{ width: 140 }} value={ip} onChange={(e) => setIp(e.target.value)} />
        <Select allowClear placeholder="状态" style={{ width: 120 }} value={status} onChange={setStatus}
          options={[{label:'成功',value:'success'},{label:'失败',value:'fail'}]} />
        <Button type="primary" onClick={() => load(1)}>查询</Button>
        <Button icon={<ReloadOutlined />} onClick={() => { setStatus(null); setUsername(''); setIp(''); load(1) }}>重置</Button>
      </Space>
      <Card>
        <Table rowKey="id" loading={loading} columns={columns} dataSource={rows}
          pagination={{ current: page, total, pageSize: 20, showTotal: (t) => `共 ${t} 条`, onChange: (p) => load(p) }} />
      </Card>
    </div>
  )
}
