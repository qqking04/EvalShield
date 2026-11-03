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
import { Card, Table, Tag, Typography, Button, Space, Alert, Tooltip } from 'antd'
import { ReloadOutlined, CheckOutlined, MinusOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { useEdition, IS_COMMUNITY_BUILD } from '../../edition/EditionContext'
import tokens from '../../theme/tokens'

// ES9-P-02（§2.2.3）：版本能力对比页 —— 免登录公开路由 /edition-compare。
// 数据源 GET /api/meta/edition-matrix：{ rows: [{ capability, group, community, professional, enterprise, group_edition }] }。
// 失败时渲染静态兜底矩阵 + 重试按钮。当前形态列 primary 描边并标「你在这里」。

// 静态兜底（与后端矩阵种子同口径的精简版；拉取失败时保证页面可讲清差异）
const FALLBACK_ROWS = [
  { group: '核心评测', capability: '评测任务与报告', community: true, professional: true, enterprise: true, group_edition: true },
  { group: '核心评测', capability: '题库与覆盖度', community: '1 库 / 500 题', professional: true, enterprise: true, group_edition: true },
  { group: '核心评测', capability: '人工复核工作台', community: true, professional: true, enterprise: true, group_edition: true },
  { group: '商业能力', capability: '成本看板 / 模型对比', community: false, professional: true, enterprise: true, group_edition: true },
  { group: '商业能力', capability: 'UAT 验收报告', community: false, professional: true, enterprise: true, group_edition: true },
  { group: '商业能力', capability: 'SRC 轻量代码检查', community: false, professional: true, enterprise: true, group_edition: true },
  { group: '商业能力', capability: '定时监控 / 在线评测 / 红队', community: false, professional: '限量', enterprise: true, group_edition: true },
  { group: '部署形态', capability: '私有化离线部署', community: true, professional: true, enterprise: true, group_edition: true },
  { group: '部署形态', capability: '多租户与平台运营', community: false, professional: false, enterprise: true, group_edition: true },
  { group: '部署形态', capability: '集团版组织级隔离', community: false, professional: false, enterprise: false, group_edition: true },
]

const COLS = [
  { key: 'community', title: '社区版' },
  { key: 'professional', title: '专业版' },
  { key: 'enterprise', title: '企业版' },
  { key: 'group_edition', title: '集团版' },
]

function CellValue({ value }) {
  if (value === true) return <CheckOutlined style={{ color: tokens.success }} />
  if (value === false || value == null) return <MinusOutlined style={{ color: tokens.text3 }} />
  return <Typography.Text style={{ color: tokens.text2, fontSize: 12 }}>{String(value)}</Typography.Text>
}

export default function EditionCompare() {
  const [rows, setRows] = useState(null)
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(true)
  const { edition } = useEdition()

  const load = () => {
    setLoading(true)
    setFailed(false)
    http
      .get('/meta/edition-matrix')
      .then((data) => {
        const list = Array.isArray(data?.rows) ? data.rows : []
        if (!list.length) throw new Error('empty matrix')
        setRows(list)
      })
      .catch(() => {
        setRows(FALLBACK_ROWS)
        setFailed(true)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  // 当前形态列：探测失败时按构建期形态兜底（OSS 社区包=community）
  const currentKey = useMemo(() => {
    const ed = edition || (IS_COMMUNITY_BUILD ? 'community' : null)
    if (ed === 'community' || ed === 'saas') return 'community'
    if (ed === 'professional') return 'professional'
    if (ed === 'enterprise') return 'enterprise'
    if (ed === 'group') return 'group_edition'
    return null
  }, [edition])

  const columns = useMemo(() => {
    const base = [
      {
        title: '能力项',
        dataIndex: 'capability',
        key: 'capability',
        width: 260,
        render: (v) => <Typography.Text style={{ color: tokens.text1 }}>{v}</Typography.Text>,
      },
    ]
    COLS.forEach((c) => {
      const isCurrent = c.key === currentKey
      base.push({
        title: (
          <Space size={6}>
            <span>{c.title}</span>
            {isCurrent && <Tag color="cyan" style={{ marginInlineEnd: 0 }}>你在这里</Tag>}
          </Space>
        ),
        dataIndex: c.key,
        key: c.key,
        align: 'center',
        width: 160,
        onCell: () => ({
          style: isCurrent
            ? { borderLeft: `2px solid ${tokens.primary}`, borderRight: `2px solid ${tokens.primary}` }
            : undefined,
        }),
        onHeaderCell: () => ({
          style: isCurrent ? { border: `1px solid ${tokens.primary}`, color: tokens.primary } : undefined,
        }),
        render: (v) => <CellValue value={v} />,
      })
    })
    return base
  }, [currentKey])

  // 分组行：group 字段变化时注入分隔行（dataSource 内混入 __group 标记行）
  const data = useMemo(() => {
    const list = rows || []
    const out = []
    let lastGroup = null
    list.forEach((r, i) => {
      if (r.group && r.group !== lastGroup) {
        out.push({ key: `g-${i}`, __group: r.group })
        lastGroup = r.group
      }
      out.push({ ...r, key: r.capability || `r-${i}` })
    })
    return out
  }, [rows])

  return (
    <div style={{ maxWidth: 980, margin: '0 auto', padding: '32px 16px' }}>
      <Space direction="vertical" size={4} style={{ marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0, color: tokens.text1 }}>
          版本能力对比
        </Typography.Title>
        <Typography.Text style={{ color: tokens.text2 }}>
          大模型应用安全与合规评测（私有化）· 各形态能力与限额一览
        </Typography.Text>
      </Space>
      {failed && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="实时矩阵加载失败，当前为静态兜底数据"
          action={
            <Tooltip title="重新拉取 /api/meta/edition-matrix">
              <Button size="small" icon={<ReloadOutlined />} onClick={load}>
                重试
              </Button>
            </Tooltip>
          }
        />
      )}
      <Card styles={{ body: { padding: 0 } }}>
        <Table
          size="middle"
          rowKey="key"
          loading={loading}
          columns={columns}
          dataSource={data}
          pagination={false}
          bordered
          onRow={() => ({})}
          components={{
            body: {
              row: ({ record, children, ...rest }) => {
                if (record?.__group) {
                  return (
                    <tr>
                      <td colSpan={5} style={{ background: tokens.bgHover, color: tokens.text2, fontSize: 12, padding: '6px 12px' }}>
                        {record.__group}
                      </td>
                    </tr>
                  )
                }
                return <tr {...rest}>{children}</tr>
              },
            },
          }}
        />
      </Card>
    </div>
  )
}
