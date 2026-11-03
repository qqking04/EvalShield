/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// UI 测试预览 Tab：展示 DOM 选择器、操作类型、页面 URL
import { Table, Tag, Tooltip, Button } from 'antd'
import { RedoOutlined } from '@ant-design/icons'
import { C, MONO } from './consoleTheme'

const OP_TYPE_COLOR = {
  '表单': 'purple',
  '列表': 'blue',
  '导航': 'cyan',
  '按钮': 'green',
}

export default function DiscoverPreviewUITab({ cases, selected, onToggle, readOnly = false, onEdit }) {
  const uiCases = cases.filter((c) => (c.category || '').toUpperCase() === 'UI')

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
      title: '页面',
      dataIndex: 'page_url',
      width: 180,
      render: (url) => (
        <span className="disc-mono" style={{ fontSize: 11, color: C.dim }}>
          {url || '—'}
        </span>
      ),
    },
    {
      title: '操作类型',
      dataIndex: 'op_type',
      width: 90,
      render: (t) => <Tag color={OP_TYPE_COLOR[t] || 'default'}>{t || '其他'}</Tag>,
    },
    {
      title: 'DOM 选择器',
      dataIndex: 'dom_selector',
      width: 200,
      render: (s) => (
        <Tooltip title={s}>
          <span className="disc-mono" style={{ fontSize: 11, color: '#722ed1' }}>
            {s || '—'}
          </span>
        </Tooltip>
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
    {
      title: '步骤数',
      dataIndex: 'steps',
      width: 80,
      render: (s) => <span style={{ color: C.dim, fontSize: 11 }}>{(s || []).length} 步</span>,
    },
    {
      title: '',
      width: 50,
      render: (_, r) => (
        <Button size="small" type="text" icon={<RedoOutlined />} onClick={() => onEdit?.({ ...r, _origTitle: r.title })} title="编辑选择器" />
      ),
    },
  ].filter((col) => !(readOnly && col.title === ''))

  return (
    <Table
      size="small"
      rowKey="title"
      columns={columns}
      dataSource={uiCases}
      pagination={{ pageSize: 10, showSizeChanger: false }}
      locale={{ emptyText: <span style={{ color: C.dim }}>暂无 UI 测试用例</span> }}
    />
  )
}
