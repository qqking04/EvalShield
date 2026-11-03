/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Table, Button, Card, Space, Tag, Switch, Input, Select, App, Typography, Tooltip, Popconfirm, Statistic, Row, Col,
} from 'antd'
import { ReloadOutlined, CloudSyncOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { ENGINE_TYPE_MAP } from '../../constants/enums'

const TYPE_COLOR = { TRADITIONAL: 'blue', AI: 'purple', ENGINEERING: 'orange' }

// ES9：实现层级（fidelity）——结论可信度口径，simulated 不出具交付结论
const FIDELITY_META = {
  real: { color: 'green', label: '真实执行' },
  rule: { color: 'gold', label: '规则匹配' },
  simulated: { color: 'red', label: '演示级', tooltip: '演示级引擎：结论不出具交付' },
}

export default function AdminEngines() {
  const { message } = App.useApp()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [toggling, setToggling] = useState('')
  const [keyword, setKeyword] = useState('')
  const [typeFilter, setTypeFilter] = useState()
  const [statusFilter, setStatusFilter] = useState()

  const load = async () => {
    setLoading(true)
    try {
      const d = await http.get('/engines')
      setRows(d?.items || [])
    } catch (e) {
      message.error(e?.message || '引擎列表加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const filtered = useMemo(() => rows.filter((r) => {
    const kw = keyword.trim().toLowerCase()
    if (kw && !(`${r.engine_code} ${r.engine_name || ''} ${r.description || ''}`.toLowerCase().includes(kw))) return false
    if (typeFilter && r.engine_type !== typeFilter) return false
    if (statusFilter && r.status !== statusFilter) return false
    return true
  }), [rows, keyword, typeFilter, statusFilter])

  const counts = useMemo(() => ({
    total: rows.length,
    enabled: rows.filter((r) => r.status === 'ENABLED').length,
    disabled: rows.filter((r) => r.status === 'DISABLED').length,
  }), [rows])

  async function toggle(row, checked) {
    setToggling(row.engine_code)
    try {
      await http.put(`/engines/${row.engine_code}/status`, { status: checked ? 'ENABLED' : 'DISABLED' })
      message.success(`${row.engine_name || row.engine_code} 已${checked ? '启用' : '停用'}`)
      load()
    } catch (e) {
      message.error(e?.message || '操作失败')
    } finally {
      setToggling('')
    }
  }

  async function syncRegistry() {
    setSyncing(true)
    try {
      const d = await http.post('/engines/sync')
      message.success(`同步完成：${d?.synced_count ?? 0} 个引擎`)
      load()
    } catch (e) {
      message.error(e?.message || '同步失败')
    } finally {
      setSyncing(false)
    }
  }

  const columns = [
    { title: '引擎编码', dataIndex: 'engine_code', width: 190, render: (v) => <Typography.Text code>{v}</Typography.Text> },
    { title: '引擎名称', dataIndex: 'engine_name', width: 170, render: (v) => v || '-' },
    {
      title: '类型', dataIndex: 'engine_type', width: 110,
      render: (v) => <Tag color={TYPE_COLOR[v] || 'default'}>{ENGINE_TYPE_MAP[v] || v || '-'}</Tag>,
    },
    {
      title: '细分类别', dataIndex: 'category', width: 150, render: (v) => v || '-',
    },
    {
      title: '实现层级', dataIndex: 'fidelity', width: 110,
      render: (v) => {
        const m = FIDELITY_META[v]
        if (!m) return <Typography.Text type="secondary">-</Typography.Text>
        const tag = <Tag color={m.color}>{m.label}</Tag>
        return m.tooltip ? <Tooltip title={m.tooltip}>{tag}</Tooltip> : tag
      },
    },
    { title: '版本', dataIndex: 'version', width: 90, render: (v) => v || '-' },
    {
      title: '说明', dataIndex: 'description', ellipsis: true,
      render: (v) => (v ? <Tooltip title={v}>{v}</Tooltip> : <Typography.Text type="secondary">-</Typography.Text>),
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v) => <Tag color={v === 'ENABLED' ? 'green' : 'red'}>{v === 'ENABLED' ? '已启用' : '已停用'}</Tag>,
    },
    {
      title: '开关', dataIndex: 'status', key: 'switch', width: 90,
      render: (v, row) => (
        <Switch
          checked={v === 'ENABLED'}
          loading={toggling === row.engine_code}
          onChange={(checked) => toggle(row, checked)}
        />
      ),
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title="引擎总数" value={counts.total} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="已启用" value={counts.enabled} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="已停用" value={counts.disabled} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
      </Row>

      <Card
        title="引擎管理"
        extra={(
          <Space>
            <Input allowClear placeholder="搜索编码/名称/说明" style={{ width: 200 }} value={keyword} onChange={(e) => setKeyword(e.target.value)} />
            <Select allowClear placeholder="类型" style={{ width: 130 }} value={typeFilter} onChange={setTypeFilter}
              options={Object.entries(ENGINE_TYPE_MAP).map(([k, v]) => ({ value: k, label: v }))} />
            <Select allowClear placeholder="状态" style={{ width: 110 }} value={statusFilter} onChange={setStatusFilter}
              options={[{ value: 'ENABLED', label: '已启用' }, { value: 'DISABLED', label: '已停用' }]} />
            <Button icon={<CloudSyncOutlined />} loading={syncing} onClick={syncRegistry}>同步注册表</Button>
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          </Space>
        )}
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          停用的引擎将无法被测试任务调用；开关对内置引擎同样生效（记录写入数据库）。
        </Typography.Paragraph>
        <Table rowKey="engine_code" size="small" loading={loading} columns={columns} dataSource={filtered}
          pagination={{ showSizeChanger: true, showQuickJumper: true, pageSize: 20, showTotal: (t) => `共 ${t} 条` }} />
      </Card>
    </div>
  )
}
