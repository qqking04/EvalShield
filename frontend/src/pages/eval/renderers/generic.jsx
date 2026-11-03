/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// §6.5.2 结论横幅 + 兜底 GenericItemTable（U8-2 自 reportRenderers.jsx 原样迁出）
import { useMemo } from 'react'
import {
  Table, Space, Card, Typography, Tooltip, Popover, Row, Col, Descriptions, Tag,
} from 'antd'
import ReactECharts from 'echarts-for-react'
import { brandColor } from '../../../theme'
import { fmtDuration, toScorePercent } from '../../../utils'
import { mono, verdictTag, cnNote } from './shared'

const TARGET_MODE_CN = { INTERNAL_DEMO: '内置演示模型', LIVE_TARGET: '真实被测系统' }

export function RunBanner({ run }) {
  const snap = run?.run_snapshot || {}
  const summary = run?.summary || {}
  const demo = snap.target_mode === 'INTERNAL_DEMO' || summary.target_mode === 'INTERNAL_DEMO'
  const score = run?.overall_score
  const pass = run?.verdict === 'PASS'
  const dataset = run?.eval_set_code ? `${run.eval_set_code}${run.dataset_version ? `@${run.dataset_version}` : ''}` : '-'
  const snapshotContent = (
    <Descriptions size="small" column={1} style={{ maxWidth: 360 }}>
      {Object.entries({
        引擎版本: snap.engine_version, 判定模型: snap.judge_model_code, 被测模式: TARGET_MODE_CN[snap.target_mode] || snap.target_mode,
        评测集: snap.dataset_code, 数据集版本: snap.dataset_version, 温度: snap.temperature,
        随机种子: snap.seed, 判定模式: snap.judge_mode,
      }).filter(([, v]) => v != null && v !== '').map(([k, v]) => (
        <Descriptions.Item key={k} label={k}><span style={mono}>{String(v)}</span></Descriptions.Item>
      ))}
      {/* 静默回退留痕（#1/#2/#3）：请求值与实际值不一致时透出，正常时为 undefined 不渲染 */}
      {[snap.env_fallback_note, snap.judge_fallback_note, snap.model_fallback_note].filter(Boolean).map((note) => (
        <Descriptions.Item key={note} label="回退提示"><Typography.Text type="warning" style={{ fontSize: 12 }}>{note}</Typography.Text></Descriptions.Item>
      ))}
      {Object.keys(snap).length === 0 && <Descriptions.Item label="提示">该运行无快照（历史数据）</Descriptions.Item>}
    </Descriptions>
  )
  return (
    <div
      style={{
        padding: '12px 16px',
        borderRadius: 8,
        border: `1px solid ${pass ? 'rgba(19,194,194,0.55)' : 'rgba(250,84,28,0.65)'}`,
        boxShadow: pass ? '0 0 12px rgba(19,194,194,0.25)' : '0 0 12px rgba(245,34,45,0.2)',
        background: '#141923',
      }}
    >
      <Row align="middle" gutter={16}>
        <Col flex="none">
          <Space size={12} align="center">
            {verdictTag(run?.verdict)}
            <span style={{ ...mono, fontSize: 30, fontWeight: 700, color: pass ? brandColor : '#fa541c', lineHeight: 1 }}>
              {(() => { const p = toScorePercent(score); return p == null ? '-' : p.toFixed(1) })()}
            </span>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>综合得分</Typography.Text>
          </Space>
        </Col>
        <Col flex="auto">
          <Space size={8} wrap>
            <Tag>评测集 {dataset}</Tag>
            <Tag>判定模型 {snap.judge_model_code || run?.judge_model || '默认'}</Tag>
            {demo
              ? (
                <Tooltip title="未配置被测系统（target），本次评测对象为平台内置模型，结果反映 EvalShield 自身能力而非真实被测系统（F7）">
                  <Tag color="warning" style={{ cursor: 'help' }}>内置演示</Tag>
                </Tooltip>
              )
              : <Tag color="cyan">被测系统 {snap.target_code || run?.target_id || '-'}</Tag>}
          </Space>
        </Col>
        <Col flex="none">
          <Space size={12} style={mono}>
            <span>成本 <Typography.Text style={{ color: '#e6ebf0' }}>¥{run?.actual_cost != null ? Number(run.actual_cost).toFixed(4) : '-'}</Typography.Text> / 预算 ¥{run?.estimated_cost != null ? Number(run.estimated_cost).toFixed(4) : '-'}</span>
            <span>耗时 {fmtDuration(run?.duration_ms)}</span>
            <Popover content={snapshotContent} title="运行快照（可复现性）" trigger="click">
              <Tag color="geekblue" style={{ cursor: 'pointer' }}>快照</Tag>
            </Popover>
          </Space>
        </Col>
      </Row>
    </div>
  )
}

// ---------- 兜底：GenericItemTable（保留现有五维雷达+表，旧数据不崩） ----------
export function GenericItemTable({ items = [], overall = 0 }) {
  const rows = Array.isArray(items) ? items : []
  const radarOption = useMemo(() => {
    const scores = rows.map((i) => i.score).filter((s) => s != null)
    const total = scores.length || 1
    const avg = scores.reduce((a, b) => a + b, 0) / total
    const max = scores.length ? Math.max(...scores, 0) : 0
    const min = scores.length ? Math.min(...scores, 1) : 0
    const passCount = rows.filter((i) => i.verdict === 'PASS').length
    const passRate = rows.length > 0 ? passCount / rows.length : 0
    const variance = scores.reduce((s, v) => s + (v - avg) ** 2, 0) / total
    const stability = Math.max(0, 1 - Math.sqrt(variance) * 4)
    const values = [avg * 100, passRate * 100, max * 100, (1 - min) * 100, stability * 100]
    return {
      backgroundColor: 'transparent',
      textStyle: { color: 'rgba(255,255,255,0.85)' },
      tooltip: {},
      radar: {
        indicator: [
          { name: '平均分', max: 100 }, { name: '通过率', max: 100 }, { name: '最高分项', max: 100 },
          { name: '低分惩罚', max: 100 }, { name: '稳定性', max: 100 },
        ],
        radius: '65%',
        center: ['50%', '55%'],
        axisName: { color: '#8b97a7' },
      },
      series: [{
        type: 'radar',
        data: [{ value: values, name: `综合得分 ${Math.round(toScorePercent(overall) ?? avg * 100)}%`, areaStyle: { opacity: 0.3 }, lineStyle: { color: brandColor }, itemStyle: { color: brandColor } }],
      }],
    }
  }, [rows, overall])

  const columns = [
    { title: '题号', dataIndex: 'no', width: 90, render: (v, _, idx) => v || idx + 1 },
    { title: '提示词', dataIndex: 'prompt', ellipsis: true, render: (v, r) => v ?? r.question ?? '' },
    { title: '判定', dataIndex: 'verdict', width: 110, render: verdictTag },
    { title: '得分', dataIndex: 'score', width: 90, render: (v) => (v == null ? '-' : <span style={mono}>{`${Math.round(v * 100)}%`}</span>) },
    { title: '详情', dataIndex: 'reason', ellipsis: true, render: (v, r) => cnNote(v || r.judge_detail || r.note || '-') },
  ]
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {rows.length > 0 && (
        <Card size="small" title="评测五维雷达图">
          <ReactECharts option={radarOption} style={{ height: 300 }} notMerge lazyUpdate />
        </Card>
      )}
      <Table
        rowKey={(_, idx) => idx}
        size="small"
        columns={columns}
        dataSource={rows}
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 10, showSizeChanger: false }}
      />
    </Space>
  )
}
