/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 安全测试预览 Tab：展示 OWASP 编号、攻击类型、Payload 示例
import { Table, Tag, Tooltip, Typography } from 'antd'
import { C, MONO } from './consoleTheme'

const { Text } = Typography

const ATTACK_TYPE_COLOR = {
  'SQL注入': '#f5222d',
  'XSS': '#fa541c',
  '越权': '#faad14',
  'CSRF': '#722ed1',
  '敏感数据': '#13c2c2',
}

const OWASP_DESC = {
  'A01:2021': '失效的访问控制',
  'A02:2021': '加密机制失效',
  'A03:2021': '注入',
  'A04:2021': '不安全的设计',
  'A05:2021': '安全配置错误',
  'A06:2021': '易损/过时组件',
  'A07:2021': '身份认证失效',
}

export default function DiscoverPreviewSecTab({ cases, selected, onToggle, readOnly = false }) {
  const secCases = cases.filter((c) => {
    const cat = (c.category || '').toUpperCase()
    return cat === 'SECURITY' || cat === 'REDTEAM'
  })

  const columns = [
    {
      title: '',
      width: 40,
      render: (_, r) => (
        <input
          type="checkbox"
          checked={selected.has(r.title)}
          onChange={() => onToggle(r)}
          style={{ accentColor: C.cyan }}
        />
      ),
    },
    {
      title: '模块',
      dataIndex: 'module',
      width: 100,
      render: (m) => <Tag color="cyan">{m}</Tag>,
    },
    {
      title: '用例',
      dataIndex: 'title',
      ellipsis: true,
    },
    {
      title: '攻击类型',
      dataIndex: 'attack_type',
      width: 100,
      render: (t) => (
        <Tag color={ATTACK_TYPE_COLOR[t] || '#8c8c8c'}>{t || '安全测试'}</Tag>
      ),
    },
    {
      title: 'OWASP',
      dataIndex: 'owasp_id',
      width: 110,
      render: (id) => (
        <Tooltip title={OWASP_DESC[id] || ''}>
          <Tag
            style={{
              background: '#fff1f0',
              borderColor: '#ff4d4f',
              color: '#cf1322',
              fontFamily: MONO,
              fontSize: 11,
            }}
          >
            {id || '—'}
          </Tag>
        </Tooltip>
      ),
    },
    {
      title: 'Payload 示例',
      dataIndex: 'payload_sample',
      width: 200,
      render: (p) => (
        <Tooltip title={p}>
          <Text
            copyable={{ text: p || '' }}
            style={{
              fontFamily: MONO,
              fontSize: 11,
              color: '#f5222d',
              maxWidth: 180,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              display: 'inline-block',
            }}
          >
            {p || '—'}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: '预期响应',
      dataIndex: 'expected_response',
      width: 120,
      render: (v) => (
        <span style={{ color: C.green, fontSize: 12 }}>{v || '拦截/拒绝'}</span>
      ),
    },
    {
      title: '严重度',
      dataIndex: 'severity',
      width: 80,
      render: (s) => (
        <Tag color={{ P0: '#ff4d4f', P1: '#ff7a45', P2: '#ffd666', P3: '#13c2c2', P4: '#7a8a9c' }[s] || 'default'}>
          {s}
        </Tag>
      ),
    },
  ].filter((col) => !(readOnly && col.title === ''))

  return (
    <Table
      size="small"
      rowKey="title"
      columns={columns}
      dataSource={secCases}
      pagination={{ pageSize: 10, showSizeChanger: false }}
      locale={{ emptyText: <span style={{ color: C.dim }}>暂无安全测试用例</span> }}
    />
  )
}
