/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// §6.5.5 EthicsReport（违规条款透视）（U8-2 自 reportRenderers.jsx 原样迁出）
import { useMemo, useState } from 'react'
import { Space, Card, Table, Drawer, Tag, Typography, Alert, Divider } from 'antd'
import ReactECharts from 'echarts-for-react'
import { complianceHeat } from '../engineCharts'
import { mono, mergeItems, severityTag } from './shared'

export function EthicsReport({ items = [], summary = {} }) {
  const rows = mergeItems(items)
  const [regFilter, setRegFilter] = useState(null)
  const [drawerRow, setDrawerRow] = useState(null)
  const sevRank = ['NONE', 'MINOR', 'MODERATE', 'MAJOR', 'CRITICAL']
  const agg = useMemo(() => {
    const map = {}
    rows.forEach((r) => (r.violations || []).forEach((v) => {
      const key = v.regulation_no || '未标注法规'
      if (!map[key]) map[key] = { regulation_no: key, clauses: new Set(), count: 0, worst: 'NONE' }
      map[key].clauses.add(v.clause_no || '-')
      map[key].count += 1
      if (sevRank.indexOf(v.severity || 'NONE') > sevRank.indexOf(map[key].worst)) map[key].worst = v.severity || 'NONE'
    }))
    return Object.values(map).map((g) => ({ ...g, clause_no: [...g.clauses].join('、') }))
  }, [rows])
  const filtered = regFilter ? rows.filter((r) => (r.violations || []).some((v) => (v.regulation_no || '未标注法规') === regFilter)) : rows
  const columns = [
    { title: '编号', dataIndex: 'item_no', width: 100, render: (v, _, i) => v || `#${i + 1}` },
    { title: '提示词', dataIndex: 'prompt', ellipsis: true },
    { title: '回答', dataIndex: 'answer', ellipsis: true, render: (v) => <a onClick={() => setDrawerRow({ title: '回答全文', text: v })}>{v || '-'}</a> },
    { title: '最重等级', dataIndex: 'worst_severity', width: 110, render: severityTag },
    { title: '合规分', dataIndex: 'compliance_score', width: 90, render: (v) => (v == null ? '-' : <span style={mono}>{Number(v).toFixed(2)}</span>) },
    { title: '拒绝', dataIndex: 'refused', width: 80, render: (v) => (v ? <Tag color="green">已拒绝</Tag> : <Tag>未拒绝</Tag>) },
    {
      title: '操作', width: 100,
      render: (_, r) => <a onClick={() => setDrawerRow({ title: `题项 ${r.item_no || ''} 违规条款`, row: r })}>查看条款</a>,
    },
  ]
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small" title="合规得分热力条（0 红 → 1 绿）">
        <ReactECharts option={complianceHeat(rows)} style={{ height: 180 }} notMerge lazyUpdate />
      </Card>
      <Card size="small" title={regFilter ? `违规条款聚合（已按 ${regFilter} 过滤明细，再次点击取消）` : '违规条款聚合（点击行过滤关联用例）'}>
        <Table
          rowKey="regulation_no"
          size="small"
          dataSource={agg}
          pagination={false}
          onRow={(g) => ({ onClick: () => setRegFilter((f) => (f === g.regulation_no ? null : g.regulation_no)), style: { cursor: 'pointer', background: regFilter === g.regulation_no ? '#1e2736' : undefined } })}
          columns={[
            { title: '法规', dataIndex: 'regulation_no', ellipsis: true },
            { title: '条款号', dataIndex: 'clause_no', ellipsis: true },
            { title: '命中次数', dataIndex: 'count', width: 100, render: (v) => <span style={mono}>{v}</span> },
            { title: '最高严重度', dataIndex: 'worst', width: 120, render: severityTag },
          ]}
        />
      </Card>
      <Card size="small" title={`伦理审查明细（${filtered.length}/${rows.length} 条）`}>
        <Table
          rowKey={(_, idx) => idx}
          size="small"
          columns={columns}
          dataSource={filtered}
          pagination={{ pageSize: 10, showSizeChanger: false }}
        />
        {(rows[0]?.checked_regulations || []).length > 0 && (
          <Space size={6} wrap style={{ marginTop: 8 }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>审查法规版本：</Typography.Text>
            {(rows[0]?.checked_regulations || []).map((reg) => <Tag key={reg}>{reg.includes('@') ? reg : `${reg}@v1`}</Tag>)}
          </Space>
        )}
      </Card>
      <Drawer title={drawerRow?.title || '详情'} width={620} open={!!drawerRow} onClose={() => setDrawerRow(null)}>
        {drawerRow?.text != null && (
          <Typography.Paragraph style={{ ...mono, fontSize: 12, whiteSpace: 'pre-wrap' }}>{drawerRow.text || '（空）'}</Typography.Paragraph>
        )}
        {drawerRow?.row && (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Typography.Paragraph style={{ ...mono, fontSize: 12, whiteSpace: 'pre-wrap' }}>{drawerRow.row.prompt}</Typography.Paragraph>
            <Divider style={{ margin: '4px 0' }} />
            {(drawerRow.row.violations || []).length === 0 && <Alert type="success" showIcon message="该题项未命中任何违规条款" />}
            {(drawerRow.row.violations || []).map((v, i) => (
              <Card key={i} size="small" style={{ background: '#0f141b' }}>
                <Space direction="vertical" size={4}>
                  <Space wrap>
                    <Tag color="blue">{v.regulation_no || '未标注法规'}</Tag>
                    <Tag>{v.clause_no || '-'}</Tag>
                    {severityTag(v.severity)}
                  </Space>
                  <Typography.Text style={{ fontSize: 12 }}>{v.reason}</Typography.Text>
                </Space>
              </Card>
            ))}
          </Space>
        )}
      </Drawer>
    </Space>
  )
}
