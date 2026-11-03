/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 性能测试预览 Tab：展示并发梯度、持续时间、P95/P99 目标、TPS 目标
import { Table, Tag, Progress, Tooltip } from 'antd'
import { C } from './consoleTheme'

export default function DiscoverPreviewPerfTab({ cases, selected, onToggle, readOnly = false }) {
  const perfCases = cases.filter((c) => (c.category || '').toUpperCase() === 'PERFORMANCE')

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
      title: '接口',
      width: 220,
      render: (_, r) => (
        <span className="disc-mono" style={{ fontSize: 11 }}>
          <Tag color="blue">{r.request_spec?.method || 'GET'}</Tag>
          {r.request_spec?.path}
        </span>
      ),
    },
    {
      title: '并发梯度',
      dataIndex: 'performance_config',
      width: 120,
      render: (cfg) => {
        const conc = cfg?.concurrency || []
        return (
          <span style={{ color: C.dim, fontSize: 12 }}>
            {conc.length > 0 ? conc.join(' / ') + ' 并发' : '—'}
          </span>
        )
      },
    },
    {
      title: '持续时间',
      dataIndex: 'performance_config',
      width: 90,
      render: (cfg) => (
        <span style={{ color: C.dim, fontSize: 12 }}>
          {cfg?.duration ? cfg.duration + 's' : '—'}
        </span>
      ),
    },
    {
      title: 'P95 目标',
      dataIndex: 'performance_config',
      width: 100,
      render: (cfg) => (
        <span style={{ color: '#fa8c16', fontSize: 12, fontWeight: 600 }}>
          {cfg?.target_rt_p95 ? '< ' + cfg.target_rt_p95 + 'ms' : '—'}
        </span>
      ),
    },
    {
      title: 'P99 目标',
      dataIndex: 'performance_config',
      width: 100,
      render: (cfg) => (
        <span style={{ color: '#f5222d', fontSize: 12, fontWeight: 600 }}>
          {cfg?.target_rt_p99 ? '< ' + cfg.target_rt_p99 + 'ms' : '—'}
        </span>
      ),
    },
    {
      title: 'TPS 目标',
      dataIndex: 'performance_config',
      width: 90,
      render: (cfg) => (
        <span style={{ color: C.cyan, fontSize: 12, fontWeight: 600 }}>
          {cfg?.target_tps ? '≥ ' + cfg.target_tps : '—'}
        </span>
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
      dataSource={perfCases}
      pagination={{ pageSize: 10, showSizeChanger: false }}
      locale={{ emptyText: <span style={{ color: C.dim }}>暂无性能测试用例</span> }}
    />
  )
}
