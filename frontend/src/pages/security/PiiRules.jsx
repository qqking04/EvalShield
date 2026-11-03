/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// PII 规则库管理页（产品优化3 §U2）：列表 + 类型/严重度筛选 + 新增/编辑/删除 + 单条启停 + 规则试算
// 后端契约：GET/POST /api/pii/rules，PUT/DELETE /api/pii/rules/{id}（写需 admin:dict）
import { useEffect, useState } from 'react'
import {
  Table, Button, Card, Space, Tag, Input, Select, Switch, Popconfirm, App, Typography,
} from 'antd'
import { PlusOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { fmtTime } from '../../utils'
import PiiRuleForm, { PII_TYPE_OPTIONS, SEVERITY_OPTIONS } from '../../components/security/PiiRuleForm'

const PII_TYPE_COLOR = {
  ID_CARD: 'red', PHONE: 'volcano', BANK_CARD: 'orange', EMAIL: 'gold',
  API_KEY: 'lime', ADDRESS: 'cyan', PASSWORD: 'purple', OTHER: 'blue',
}
const SEVERITY_TAG_COLOR = { CRITICAL: 'red', HIGH: 'volcano', MEDIUM: 'gold', LOW: 'green' }

export default function PiiRules() {
  const { message } = App.useApp()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [piiType, setPiiType] = useState(undefined)
  const [severity, setSeverity] = useState(undefined)
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)

  const load = async (p = page, ps = pageSize, t = piiType, kw = keyword, sev = severity) => {
    setLoading(true)
    try {
      const d = await http.get('/pii/rules', {
        params: {
          page: p, page_size: ps,
          ...(t ? { pii_type: t } : {}),
          ...(kw ? { keyword: kw } : {}),
          ...(sev ? { severity: sev } : {}),
        },
      })
      setRows(d.items || [])
      setTotal(d.total || 0)
    } catch (e) {
      /* 错误已由拦截器统一提示 */
      console.warn('[PiiRules] load failed', e?.message || e)
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
    load(1, pageSize, piiType, kw)
  }

  const onType = (t) => {
    setPiiType(t)
    setPage(1)
    load(1, pageSize, t, keyword)
  }

  const onSeverity = (sev) => {
    setSeverity(sev)
    setPage(1)
    load(1, pageSize, piiType, keyword, sev)
  }

  const toggleActive = async (row, checked) => {
    try {
      await http.put(`/pii/rules/${row.id}`, { is_active: checked })
      setRows((rs) => rs.map((r) => (r.id === row.id ? { ...r, is_active: checked } : r)))
    } catch (e) {
      console.warn('[PiiRules] toggle failed', e?.message || e)
    }
  }

  const remove = async (id) => {
    await http.delete(`/pii/rules/${id}`)
    message.success('PII 规则已删除')
    load()
  }

  const onSaved = (row) => {
    message.success(row ? '规则已更新' : '规则已新增')
    load()
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    {
      title: 'PII 类型', dataIndex: 'pii_type', width: 130,
      render: (v) => <Tag color={PII_TYPE_COLOR[v] || 'default'}>{v}</Tag>,
    },
    { title: '规则名称', dataIndex: 'rule_name', width: 200, ellipsis: true },
    {
      title: '正则表达式', dataIndex: 'regex_pattern', ellipsis: true,
      render: (v) => <Typography.Text code style={{ fontSize: 12 }}>{v}</Typography.Text>,
    },
    {
      title: '上下文佐证', dataIndex: 'context_keywords', width: 200,
      render: (v) => v?.length
        ? v.map((k) => <Tag key={k} color="geekblue">{k}</Tag>)
        : <Typography.Text type="secondary">不校验</Typography.Text>,
    },
    {
      title: '严重度', dataIndex: 'severity', width: 110,
      render: (v) => <Tag color={SEVERITY_TAG_COLOR[v] || 'default'}>{v}</Tag>,
    },
    {
      title: '启用', dataIndex: 'is_active', width: 80,
      render: (v, row) => <Switch size="small" checked={!!v} onChange={(c) => toggleActive(row, c)} />,
    },
    { title: '更新时间', dataIndex: 'updated_at', width: 160, render: (v) => fmtTime(v) },
    {
      title: '操作', width: 150, fixed: 'right',
      render: (_, row) => (
        <Space size={0}>
          <Button
            type="link" size="small" icon={<ThunderboltOutlined />}
            onClick={() => { setEditing(row); setModalOpen(true) }}
          >
            编辑/试算
          </Button>
          <Popconfirm title="确认删除该规则？" onConfirm={() => remove(row.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>PII 规则库</Typography.Title>
        <Space>
          <Select
            allowClear
            placeholder="PII 类型筛选"
            style={{ width: 180 }}
            options={PII_TYPE_OPTIONS}
            value={piiType}
            onChange={onType}
          />
          <Select
            allowClear
            placeholder="严重度筛选"
            style={{ width: 160 }}
            options={SEVERITY_OPTIONS}
            value={severity}
            onChange={onSeverity}
          />
          <Input.Search placeholder="按规则名称/类型搜索" allowClear onSearch={onSearch} style={{ width: 220 }} />
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setModalOpen(true) }}>新增规则</Button>
        </Space>
      </div>
      <Card>
        <Table
          rowKey="id"
          size="middle"
          loading={loading}
          columns={columns}
          dataSource={rows}
          scroll={{ x: 1100 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); load(p, ps, piiType, keyword, severity) },
          }}
        />
      </Card>
      <PiiRuleForm open={modalOpen} editing={editing} onClose={() => setModalOpen(false)} onSaved={onSaved} />
    </Space>
  )
}
