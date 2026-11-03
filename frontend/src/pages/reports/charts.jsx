/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import ReactECharts from 'echarts-for-react'
import { Card } from 'antd'
import CountUp from 'react-countup'
import { Row, Col, Tag, Tooltip } from 'antd'
import { Typography } from 'antd'
import { RadarChartOutlined, CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined } from '@ant-design/icons'

export const BRAND = '#13c2c2'
export const RED = '#ff4d4f'
export const GREEN = '#52c41a'
export const ORANGE = '#faad14'

// —— 风险等级 Tag（v2.0 BUG-012：兼容中英文枚举 + CRITICAL/NONE） ——
const RISK_MAP = {
  CRITICAL: { color: '#cf1322', label: '严重风险' },
  HIGH: { color: '#ff4d4f', label: '高风险' },
  MEDIUM: { color: '#fa8c16', label: '中风险' },
  LOW: { color: '#52c41a', label: '低风险' },
  NONE: { color: '#8c8c8c', label: '无风险项' },
  '严重': { color: '#cf1322', label: '严重风险' },
  '高': { color: '#ff4d4f', label: '高风险' },
  '中': { color: '#fa8c16', label: '中风险' },
  '低': { color: '#52c41a', label: '低风险' },
  '无': { color: '#8c8c8c', label: '无风险项' },
}

export function RiskTag({ level }) {
  const normalized = String(level || '').toUpperCase()
  const item = RISK_MAP[normalized] || RISK_MAP[level] || RISK_MAP.NONE
  return (
    <Tag style={{
      borderColor: item.color,
      color: item.color,
      background: `${item.color}15`,
      fontFamily: 'JetBrains Mono, Consolas, monospace',
    }}>
      {item.label}
    </Tag>
  )
}

function _baseOption(data) {
  return { backgroundColor: 'transparent' }
}

export function buildRadarOption(data) {
  if (!data || !Array.isArray(data)) return _baseOption(data)
  const indicator = data.map((x) => ({ name: x.name, max: 100 }))
  return {
    backgroundColor: 'transparent',
    tooltip: { backgroundColor: '#1a2130', borderColor: '#1f2833', textStyle: { color: '#e6ebf0' } },
    radar: {
      indicator,
      splitLine: { lineStyle: { color: '#1f2833' } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: '#2f3a4a' } },
      name: { color: '#8b97a7' },
    },
    series: [{
      type: 'radar',
      data: [{
        value: data.map((x) => Number(x.value || 0)),
        areaStyle: { color: `${BRAND}44` },
        lineStyle: { color: BRAND },
        itemStyle: { color: BRAND },
      }],
    }],
  }
}

export function buildBarOption(data) {
  if (!data || !Array.isArray(data)) return _baseOption(data)
  return {
    backgroundColor: 'transparent',
    grid: { left: 40, right: 12, top: 20, bottom: 30 },
    tooltip: { backgroundColor: '#1a2130', borderColor: '#1f2833', textStyle: { color: '#e6ebf0' } },
    xAxis: { type: 'category', data: data.map((x) => x.name), axisLine: { lineStyle: { color: '#2f3a4a' } }, axisLabel: { color: '#8b97a7', fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { color: '#8b97a7' }, splitLine: { lineStyle: { color: '#1f2833', type: 'dashed' } } },
    series: [{ type: 'bar', data: data.map((x) => x.value), itemStyle: { color: BRAND, borderRadius: [2, 2, 0, 0] } }],
  }
}

export function buildPieOption(data) {
  if (!data || !Array.isArray(data)) return _baseOption(data)
  return {
    backgroundColor: 'transparent',
    tooltip: { backgroundColor: '#1a2130', borderColor: '#1f2833', textStyle: { color: '#e6ebf0' } },
    legend: { bottom: 0, textStyle: { color: '#8b97a7', fontSize: 11 } },
    series: [{
      type: 'pie',
      radius: ['40%', '65%'],
      center: ['50%', '42%'],
      data,
      label: { color: '#c8d1de', fontSize: 11 },
      emphasis: { itemStyle: { shadowBlur: 6, shadowColor: `${BRAND}55` } },
    }],
  }
}

export function buildLineOption(data) {
  if (!data || !Array.isArray(data)) return _baseOption(data)
  return {
    backgroundColor: 'transparent',
    grid: { left: 40, right: 12, top: 20, bottom: 30 },
    tooltip: { backgroundColor: '#1a2130', borderColor: '#1f2833', textStyle: { color: '#e6ebf0' } },
    xAxis: { type: 'category', data: data.map((x) => x.name), axisLine: { lineStyle: { color: '#2f3a4a' } }, axisLabel: { color: '#8b97a7', fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { color: '#8b97a7' }, splitLine: { lineStyle: { color: '#1f2833', type: 'dashed' } } },
    series: [{
      type: 'line', smooth: true, data: data.map((x) => x.value),
      lineStyle: { color: BRAND, width: 2 }, itemStyle: { color: BRAND },
      areaStyle: { color: `${BRAND}22` }, symbol: 'circle', symbolSize: 4,
    }],
  }
}

export function ChartBox({ title, icon, children }) {
  return (
    <Card
      size="small"
      styles={{ body: { padding: 8 } }}
      title={<span style={{ borderLeft: `3px solid ${BRAND}`, paddingLeft: 8, fontSize: 13 }}>{icon} {title}</span>}
    >
      <div style={{ height: 260 }}>{children}</div>
    </Card>
  )
}

export function SummaryCard({ score, riskLevel, passed, total, rate }) {
  const ratePct = rate != null ? Math.round(Number(rate) * 100) : null
  const numScore = score != null && score !== '' ? Number(score) : null
  return (
    <Card size="small" styles={{ body: { padding: 16 } }}>
      <Row gutter={16} align="middle" wrap={false}>
        <Col>
          <Tooltip title="全部引擎用例的加权平均得分（满分 100），来源于本次执行的真实结果数据">
            <div style={{ color: '#8b97a7', fontSize: 12 }}>综合评分</div>
          </Tooltip>
          <div style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', fontSize: 28, fontWeight: 700, color: BRAND, letterSpacing: '0.5px' }}>
            {numScore != null ? <CountUp end={numScore} decimals={1} duration={1.2} /> : <span>-</span>}
          </div>
        </Col>
        <Col>
          <Tooltip title={`整体风险等级基于用例通过率与失败严重度计算，与"合规认定（法规符合性）"口径不同——合规认定只看监管法规违规项，通过率不足不代表存在合规违规`}>
            <div style={{ color: '#8b97a7', fontSize: 12 }}>整体风险等级</div>
          </Tooltip>
          <div style={{ marginTop: 4 }}><RiskTag level={riskLevel || 'LOW'} /></div>
        </Col>
        <Col>
          <Tooltip title={`本次执行共 ${total ?? '-'} 条用例，通过 ${passed ?? '-'} 条。未通过用例属于测试质量或功能缺陷层面问题，与是否存在合规违规无关，因此可能出现"通过率不足但法规符合性未发现不符合项"并存的情况`}>
            <div style={{ color: '#8b97a7', fontSize: 12 }}>通过 / 总数</div>
          </Tooltip>
          <div style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', fontSize: 20, marginTop: 2 }}>
            <span style={{ color: GREEN }}>{passed ?? '-'}</span>
            <span style={{ color: '#8b97a7', margin: '0 6px' }}>/</span>
            <span>{total ?? '-'}</span>
            {ratePct != null && <span style={{ color: '#8b97a7', marginLeft: 8, fontSize: 14 }}>{ratePct}%</span>}
          </div>
        </Col>
      </Row>
    </Card>
  )
}

// Re-export icons so parent files can import from here
export { RadarChartOutlined, CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined }
export { Typography }
