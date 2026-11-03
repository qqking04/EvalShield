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
import { Badge, Button, Space, Steps, Table, Typography } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { listUat } from '../../api/uat'
import RequirePerm from '../../components/RequirePerm'
import UatWizard from './UatWizard'
import UatExportButton from './UatExportButton'
import { VERDICT_COLOR, VERDICT_CN } from './UatSections'
import './uat.css'

const STATUS_CN = {
  DRAFT: '草稿',
  VENDOR_SIGNED: '等待客签',
  FINALIZED: '已归档',
  REJECTED: '已拒收',
}

/* 状态机步骤条缩略：生成→供签→客签→锁定 */
function UatSteps({ status }) {
  const stepMap = { DRAFT: 1, VENDOR_SIGNED: 2, FINALIZED: 4, REJECTED: 2 }
  const current = (stepMap[status] ?? 1) - 1
  const rejected = status === 'REJECTED'
  return (
    <Steps
      size="small"
      direction="horizontal"
      current={current}
      status={rejected ? 'error' : 'process'}
      items={[
        { title: '生成' },
        { title: '供签' },
        { title: rejected ? '拒收' : '客签' },
        { title: '锁定' },
      ]}
      style={{ width: 260 }}
    />
  )
}

export default function UatReportList({ projectId }) {
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [wizard, setWizard] = useState(false)

  const load = useCallback(async (p = page) => {
    if (!projectId) return
    setLoading(true)
    try {
      const data = await listUat(projectId, { page: p, page_size: 10 })
      setRows(data?.items || [])
      setTotal(data?.total || 0)
    } catch {
      /* 拦截器已提示 */
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, page])

  useEffect(() => { load(page) }, [page]) // eslint-disable-line react-hooks/exhaustive-deps

  const columns = [
    {
      title: '版本',
      dataIndex: 'version',
      render: (v) => <span className="mono">v{v ?? 1}</span>,
    },
    {
      title: '报告编号',
      dataIndex: 'report_no',
      render: (v, r) => (
        <Typography.Link onClick={() => navigate(`/uat/${r.id}?project=${projectId}`)}>
          {v}
        </Typography.Link>
      ),
    },
    { title: '标题', dataIndex: 'title', ellipsis: true },
    {
      title: '结论',
      dataIndex: 'verdict',
      render: (v) =>
        v ? <Badge className="uat-badge-anim" status={VERDICT_COLOR[v] || 'default'} text={VERDICT_CN[v] || v} /> : <span style={{ color: '#86909C' }}>未签核</span>,
    },
    {
      title: '签核进度',
      dataIndex: 'status',
      render: (s) => <UatSteps status={s} />,
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (s) => STATUS_CN[s] || s,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      render: (v) => (v || '').slice(0, 19).replace('T', ' '),
    },
    {
      title: '操作',
      key: 'ops',
      render: (_, r) => (
        <Space size={0}>
          <Button size="small" type="link" onClick={() => navigate(`/uat/${r.id}?project=${projectId}`)}>查看</Button>
          <UatExportButton projectId={projectId} reportId={r.id} reportNo={r.report_no} status={r.status} compact />
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 12, textAlign: 'right' }}>
        <RequirePerm perm="report:read">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setWizard(true)}>
            生成验收报告
          </Button>
        </RequirePerm>
      </div>
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={rows}
        columns={columns}
        locale={{
          emptyText: (
            <Typography.Paragraph style={{ color: '#86909C' }}>
              选择已配置质量门禁的测试任务，即可生成双方签核的验收报告
            </Typography.Paragraph>
          ),
        }}
        pagination={{
          current: page,
          pageSize: 10,
          total,
          showSizeChanger: false,
          onChange: (p) => setPage(p),
        }}
      />
      <UatWizard
        open={wizard}
        projectId={projectId}
        onClose={() => setWizard(false)}
        onCreated={(rep) => {
          setWizard(false)
          navigate(`/uat/${rep.id}?project=${projectId}`)
        }}
      />
    </div>
  )
}

export { UatSteps, STATUS_CN }
