/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import React, { useCallback, useEffect, useState } from 'react'
import { Button, Select, Space, Table, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { listAllUat } from '../../api/uat'
import './uat.css'

const STATUS_META = {
  DRAFT: { text: '草稿', color: 'default' },
  VENDOR_SIGNED: { text: '供方已签', color: 'blue' },
  FINALIZED: { text: '已定稿', color: 'green' },
  REJECTED: { text: '已拒收', color: 'red' },
}

const VERDICT_META = {
  PASSED: { text: '通过', color: 'green' },
  PASSED_WITH_DEFECTS: { text: '带缺陷通过', color: 'orange' },
  FAILED: { text: '不通过', color: 'red' },
}

// ES9 UAT 跨项目验收报告汇总（推荐3）：状态过滤 + 分页，行点击进详情
export default function UatReportCenter() {
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    listAllUat({ page, page_size: size, ...(status ? { status } : {}) })
      .then((data) => {
        setRows(data?.items || [])
        setTotal(data?.total || 0)
      })
      .catch(() => {
        setRows([])
        setTotal(0)
      })
      .finally(() => setLoading(false))
  }, [page, size, status])

  useEffect(load, [load])

  const columns = [
    {
      title: '报告编号',
      dataIndex: 'report_no',
      render: (v, r) => (
        <Typography.Link onClick={() => navigate(`/uat/${r.id}?project=${r.project_id}`)}>
          <span className="mono">{v}</span>
        </Typography.Link>
      ),
    },
    { title: '标题', dataIndex: 'title', ellipsis: true },
    { title: '所属项目', dataIndex: 'project_name', ellipsis: true, width: 180 },
    { title: '版本', dataIndex: 'version', width: 70, render: (v) => (v != null ? `v${v}` : '-') },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (s) => {
        const m = STATUS_META[s] || { text: s, color: 'default' }
        return <Tag color={m.color}>{m.text}</Tag>
      },
    },
    {
      title: '结论',
      dataIndex: 'verdict',
      width: 120,
      render: (v) => {
        const m = VERDICT_META[v]
        return m ? <Tag color={m.color}>{m.text}</Tag> : '-'
      },
    },
    {
      title: '定稿时间',
      dataIndex: 'finalized_at',
      width: 170,
      render: (v) => (v ? new Date(v).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v) => (v ? new Date(v).toLocaleString('zh-CN') : '-'),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>验收报告中心</Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            此处为甲乙双方签核的 UAT 验收报告；单次评测运行的技术报告请在「报告中心（评测报告）」查看。
          </Typography.Text>
        </div>
        <Select
          allowClear
          placeholder="按状态筛选"
          style={{ width: 160 }}
          value={status}
          onChange={(v) => {
            setStatus(v || null)
            setPage(1)
          }}
          options={Object.entries(STATUS_META).map(([k, m]) => ({ value: k, label: m.text }))}
        />
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={rows}
        columns={columns}
        pagination={{
          current: page,
          pageSize: size,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, s) => {
            setPage(p)
            setSize(s)
          },
        }}
      />
    </div>
  )
}
