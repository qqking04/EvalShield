/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 越狱样本库管理页（产品优化3 §U2）：列表 + 类别/严重度筛选 + 新增/编辑/删除 + 单条启停
// 后端契约：GET/POST /api/jailbreak/samples，PUT/DELETE /api/jailbreak/samples/{id}（写需 admin:dict）
import { useEffect, useState } from 'react'
import {
  Table, Button, Card, Space, Tag, Input, Select, Switch, Popconfirm, App, Typography,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { fmtTime } from '../../utils'
import JailbreakSampleForm, { CATEGORY_OPTIONS, SEVERITY_OPTIONS } from '../../components/security/JailbreakSampleForm'

const CATEGORY_COLOR = { ROLEPLAY: 'purple', ENCODING: 'blue', CONTEXT_POISON: 'orange', CLASSIC_EN: 'geekblue' }
const SEVERITY_TAG_COLOR = { CRITICAL: 'red', HIGH: 'volcano', MEDIUM: 'gold', LOW: 'green' }

export default function JailbreakSamples() {
  const { message } = App.useApp()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [category, setCategory] = useState(undefined)
  const [severity, setSeverity] = useState(undefined)
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editing, setEditing] = useState(null)

  const load = async (p = page, ps = pageSize, cat = category, kw = keyword, sev = severity) => {
    setLoading(true)
    try {
      const d = await http.get('/jailbreak/samples', {
        params: {
          page: p, page_size: ps,
          ...(cat ? { category: cat } : {}),
          ...(kw ? { keyword: kw } : {}),
          ...(sev ? { severity: sev } : {}),
        },
      })
      setRows(d.items || [])
      setTotal(d.total || 0)
    } catch (e) {
      /* 错误已由拦截器统一提示 */
      console.warn('[JailbreakSamples] load failed', e?.message || e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onSearch = (kw) => {
    setKeyword(kw)
    setPage(1)
    load(1, pageSize, category, kw)
  }

  const onCategory = (cat) => {
    setCategory(cat)
    setPage(1)
    load(1, pageSize, cat, keyword)
  }

  const onSeverity = (sev) => {
    setSeverity(sev)
    setPage(1)
    load(1, pageSize, category, keyword, sev)
  }

  const toggleActive = async (row, checked) => {
    try {
      await http.put(`/jailbreak/samples/${row.id}`, { is_active: checked })
      setRows((rs) => rs.map((r) => (r.id === row.id ? { ...r, is_active: checked } : r)))
    } catch (e) {
      console.warn('[JailbreakSamples] toggle failed', e?.message || e)
    }
  }

  const remove = async (id) => {
    await http.delete(`/jailbreak/samples/${id}`)
    message.success('越狱样本已删除')
    load()
  }

  const onSaved = (row) => {
    message.success(row ? '样本已更新' : '样本已新增')
    load()
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    {
      title: '类别', dataIndex: 'category', width: 150,
      render: (v) => <Tag color={CATEGORY_COLOR[v] || 'default'}>{v}</Tag>,
    },
    { title: '攻击向量', dataIndex: 'attack_vector', width: 180, ellipsis: true },
    { title: '提示模板', dataIndex: 'prompt_template', ellipsis: true },
    {
      title: '严重度', dataIndex: 'severity', width: 110,
      render: (v) => <Tag color={SEVERITY_TAG_COLOR[v] || 'default'}>{v}</Tag>,
    },
    { title: '来源', dataIndex: 'source', width: 110, ellipsis: true, render: (v) => v || '-' },
    {
      title: '启用', dataIndex: 'is_active', width: 80,
      render: (v, row) => <Switch size="small" checked={!!v} onChange={(c) => toggleActive(row, c)} />,
    },
    { title: '更新时间', dataIndex: 'updated_at', width: 160, render: (v) => fmtTime(v) },
    {
      title: '操作', width: 130, fixed: 'right',
      render: (_, row) => (
        <Space size={0}>
          <Button type="link" size="small" onClick={() => { setEditing(row); setDrawerOpen(true) }}>编辑</Button>
          <Popconfirm title="确认删除该样本？" onConfirm={() => remove(row.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>越狱样本库</Typography.Title>
        <Space>
          <Select
            allowClear
            placeholder="类别筛选"
            style={{ width: 200 }}
            options={CATEGORY_OPTIONS}
            value={category}
            onChange={onCategory}
          />
          <Select
            allowClear
            placeholder="严重度筛选"
            style={{ width: 160 }}
            options={SEVERITY_OPTIONS}
            value={severity}
            onChange={onSeverity}
          />
          <Input.Search placeholder="按攻击向量/模板搜索" allowClear onSearch={onSearch} style={{ width: 220 }} />
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setDrawerOpen(true) }}>新增样本</Button>
        </Space>
      </div>
      <Card>
        <Table
          rowKey="id"
          size="middle"
          loading={loading}
          columns={columns}
          dataSource={rows}
          scroll={{ x: 1200 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); load(p, ps, category, keyword, severity) },
          }}
        />
      </Card>
      <JailbreakSampleForm open={drawerOpen} editing={editing} onClose={() => setDrawerOpen(false)} onSaved={onSaved} />
    </Space>
  )
}
