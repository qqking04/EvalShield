/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 六维度统计卡片：功能/UI/性能/安全/数据流/数据集
import { useMemo } from 'react'
import { Card, Col, Row, Statistic, Tooltip } from 'antd'
import {
  ApiOutlined,
  ExperimentOutlined,
  SafetyOutlined,
  DashboardOutlined,
  ThunderboltOutlined,
  DatabaseOutlined,
} from '@ant-design/icons'
import { C } from './consoleTheme'

const DIM_CONFIG = [
  { key: 'functional', label: '功能测试', icon: <ApiOutlined />, color: C.cyan, category: 'API' },
  { key: 'ui', label: 'UI 测试', icon: <DashboardOutlined />, color: '#722ed1', category: 'UI' },
  { key: 'performance', label: '性能测试', icon: <ThunderboltOutlined />, color: '#fa8c16', category: 'PERFORMANCE' },
  { key: 'security', label: '安全测试', icon: <SafetyOutlined />, color: '#f5222d', category: 'SECURITY' },
  { key: 'dataflow', label: '数据流', icon: <ExperimentOutlined />, color: '#1890ff', category: 'DATAFLOW' },
  { key: 'dataset', label: '数据集', icon: <DatabaseOutlined />, color: '#52c41a', category: 'DATASET' },
]

export default function DiscoverStatsCards({ cases, datasets, scenarios, confidence, replayedCount, unverifiedCount }) {
  const counts = useMemo(() => {
    const c = { functional: 0, ui: 0, performance: 0, security: 0, dataflow: 0, dataset: datasets.length }
    for (const item of cases) {
      const cat = (item.category || '').toUpperCase()
      if (cat === 'API') c.functional++
      else if (cat === 'UI') c.ui++
      else if (cat === 'PERFORMANCE') c.performance++
      else if (cat === 'SECURITY' || cat === 'REDTEAM') c.security++
      else if (cat === 'DATAFLOW') c.dataflow++
    }
    return c
  }, [cases, datasets])

  return (
    <Row gutter={12} style={{ marginBottom: 16 }}>
      {DIM_CONFIG.map((dim) => (
        <Col key={dim.key} span={4}>
          <Tooltip title={`${dim.label}用例数`}>
            <Card
              size="small"
              style={{
                background: C.panel,
                border: `1px solid ${C.panelBorder}`,
                borderRadius: 8,
                textAlign: 'center',
              }}
              bodyStyle={{ padding: '12px 8px' }}
            >
              <div style={{ color: dim.color, fontSize: 20, marginBottom: 4 }}>{dim.icon}</div>
              <Statistic
                title={<span style={{ color: C.dim, fontSize: 11 }}>{dim.label}</span>}
                value={counts[dim.key]}
                suffix="条"
                valueStyle={{ color: dim.color, fontSize: 20, fontWeight: 700 }}
              />
            </Card>
          </Tooltip>
        </Col>
      ))}
      <Col span={4}>
        <Card
          size="small"
          style={{ background: C.panel, border: `1px solid ${C.panelBorder}`, borderRadius: 8, textAlign: 'center' }}
          bodyStyle={{ padding: '12px 8px' }}
        >
          <div style={{ color: C.green, fontSize: 20, marginBottom: 4 }}>✓</div>
          <Statistic
            title={<span style={{ color: C.dim, fontSize: 11 }}>可执行率</span>}
            value={Math.round(confidence)}
            suffix="%"
            valueStyle={{ color: C.green, fontSize: 20, fontWeight: 700 }}
          />
        </Card>
      </Col>
    </Row>
  )
}
