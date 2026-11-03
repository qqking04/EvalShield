/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Col, Dropdown, Empty, Result, Row, Segmented,
  Skeleton, Space, Statistic, Table, Tabs, Tag, Tooltip, Typography,
} from 'antd'
import {
  DownloadOutlined, CheckCircleFilled, CloseCircleFilled,
  FilePdfOutlined, FileWordOutlined, FileMarkdownOutlined, Html5Outlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import http from '../../api/http'
import { useAuth } from '../../auth'
import { brandColor, SEVERITY_COLOR, MONO_FONT } from '../../theme'

const { Text } = Typography

// 门禁四态：PASSED 用色板 PASS 绿，FAILED 用 CRITICAL 红，WARN 用 MODERATE 橙，NO_DATA 用 NONE 灰
const GATE = {
  PASSED: { label: '达标', color: SEVERITY_COLOR.PASS },
  FAILED: { label: '未达标', color: SEVERITY_COLOR.CRITICAL },
  WARN: { label: '预警', color: SEVERITY_COLOR.MODERATE },
  NO_DATA: { label: '暂无数据', color: SEVERITY_COLOR.NONE },
}
const SEV_COLOR = { P0: 'red', P1: 'orange', P2: 'gold', P3: 'blue', P4: 'default' } // AntD Tag 预设名
const RISK_LABEL = { critical: '严重', high: '高', medium: '中', low: '低', none: '无' }
const riskColor = (k) => SEVERITY_COLOR[String(k).toUpperCase()] ?? SEVERITY_COLOR.NONE

const EXPORT_ITEMS = [
  { key: 'pdf', label: 'PDF', icon: <FilePdfOutlined /> },
  { key: 'word', label: 'Word', icon: <FileWordOutlined /> },
  { key: 'md', label: 'Markdown', icon: <FileMarkdownOutlined /> },
  { key: 'html', label: 'HTML', icon: <Html5Outlined /> },
]

export default function ProjectQualityView({ id, onGoTab }) {
  const { hasPerm } = useAuth()
  const canExport = hasPerm('report:export')
  const [days, setDays] = useState(90)
  const [state, setState] = useState({ loading: true, error: null, data: null })
  const [exporting, setExporting] = useState(false)

  const load = () => {
    setState((s) => ({ ...s, loading: true, error: null }))
    http.get(`/projects/${id}/quality-overview`, { params: { days } })
      .then((d) => setState({ loading: false, error: null, data: d }))
      .catch((e) => setState({ loading: false, error: e?.message || '加载失败', data: null }))
  }
  useEffect(load, [id, days]) // eslint-disable-line react-hooks/exhaustive-deps

  const doExport = async (format) => {
    setExporting(true)
    try {
      const blob = await http.get(`/projects/${id}/quality-report/export`, {
        params: { format, days }, responseType: 'blob', timeout: 120000,
      })
      const ext = { pdf: 'pdf', word: 'docx', md: 'md', html: 'html' }[format]
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `质量报告_${state.data?.project?.code ?? id}_${dayjs().format('YYYYMMDD')}.${ext}`
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(a.href)
    } catch { /* 错误已由拦截器提示 */ } finally {
      setExporting(false)
    }
  }

  // ---------- 失败态 ----------
  if (state.error && !state.data) {
    return (
      <Result
        status="error"
        title="质量视图加载失败"
        subTitle={state.error}
        extra={<Button onClick={load}>重试</Button>}
      />
    )
  }

  // ---------- 加载态 ----------
  if (state.loading && !state.data) {
    return (
      <div>
        <Skeleton active paragraph={{ rows: 3 }} style={{ marginBottom: 16 }} />
        <Row gutter={[16, 16]}>
          <Col span={12}><Card><Skeleton active paragraph={false} /></Card></Col>
          <Col span={12}><Card><Skeleton active paragraph={false} /></Card></Col>
        </Row>
      </div>
    )
  }

  const data = state.data
  const { project, gate, metrics, trend, by_engine: byEngine, latest_reports: latestReports } = data
  const g = GATE[gate.conclusion] ?? GATE.NO_DATA
  const noData = gate.conclusion === 'NO_DATA'

  // ---------- 图表 option ----------
  // 注意：不能在这里用 useMemo——上方有错误/加载两个提前 return，
  // hooks 必须全部提到 return 之前，否则切换状态时 hooks 数量不一致（React #310 白屏）。
  // option 仅在 days 变化触发重载时随 data 引用更新，直接计算即可。
  const trendOption = ({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#8b97a7' }, top: 0 },
    grid: { left: 44, right: 44, top: 32, bottom: 24 },
    xAxis: {
      type: 'category', data: trend.dates,
      axisLabel: { color: '#8b97a7', formatter: (v) => v.slice(5), interval: 'auto' },
    },
    yAxis: [
      { type: 'value', min: 0, max: 100, axisLabel: { color: '#8b97a7', formatter: '{value}%' }, splitLine: { lineStyle: { color: '#253042' } } },
      { type: 'value', minInterval: 1, axisLabel: { color: '#8b97a7' }, splitLine: { show: false } },
    ],
    series: [
      {
        name: '通过率', type: 'line', yAxisIndex: 0, data: trend.pass_rate,
        connectNulls: false, symbol: 'circle', symbolSize: 4,
        lineStyle: { color: brandColor }, itemStyle: { color: brandColor },
      },
      { name: '缺陷新增', type: 'bar', yAxisIndex: 1, data: trend.defect_new, itemStyle: { color: SEVERITY_COLOR.HIGH }, barMaxWidth: 10 },
      { name: '缺陷闭环', type: 'bar', yAxisIndex: 1, data: trend.defect_closed, itemStyle: { color: SEVERITY_COLOR.PASS }, barMaxWidth: 10 },
    ],
  })

  const riskOption = ({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie', radius: ['55%', '75%'],
      label: { color: '#8b97a7' },
      data: Object.entries(metrics.risk_distribution).map(([k, v]) => ({
        name: RISK_LABEL[k] ?? k, value: v, itemStyle: { color: riskColor(k) },
      })),
    }],
    graphic: [{
      type: 'text', left: 'center', top: 'middle',
      style: { text: String(metrics.report_total ?? 0), fill: '#e6ebf0', fontSize: 22, fontFamily: MONO_FONT },
    }],
  })

  // ---------- ④ 明细 Tabs ----------
  const detailItems = [
    {
      key: 'defects',
      label: '未闭环缺陷 TOP5',
      children: (
        <Table
          rowKey="defect_no" size="small" pagination={false}
          dataSource={metrics.top_open_defects}
          locale={{ emptyText: <Empty description="无未闭环缺陷" /> }}
          columns={[
            { title: '编号', dataIndex: 'defect_no', width: 160, render: (v) => <span style={{ fontFamily: MONO_FONT }}>{v}</span> },
            { title: '标题', dataIndex: 'title', ellipsis: true },
            { title: '严重度', dataIndex: 'severity', width: 90, render: (v) => <Tag color={SEV_COLOR[v] ?? 'default'}>{v}</Tag> },
            { title: '状态', dataIndex: 'status', width: 90, render: (v) => <Tag>{v}</Tag> },
            { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v) => (v || '').slice(0, 16).replace('T', ' ') },
          ]}
        />
      ),
    },
    byEngine.length > 0 && {
      key: 'engines',
      label: '分引擎风险',
      children: (
        <Table
          rowKey="engine" size="small" pagination={false}
          dataSource={byEngine}
          columns={[
            { title: '引擎', dataIndex: 'engine', render: (v) => <span style={{ fontFamily: MONO_FONT }}>{v}</span> },
            { title: '执行次数', dataIndex: 'runs', width: 100 },
            { title: '发现问题', dataIndex: 'issues', width: 100 },
            {
              title: '最近风险', dataIndex: 'latest_risk', width: 110,
              render: (v) => <Tag color={riskColor(v)} style={{ color: '#fff', border: 'none' }}>{RISK_LABEL[v] ?? v}</Tag>,
            },
            {
              title: '最近报告', dataIndex: 'latest_report_id', width: 100,
              render: (v) => (v ? <a href={`/reports/${v}`}>查看</a> : '—'),
            },
          ]}
        />
      ),
    },
    {
      key: 'reports',
      label: '最近报告',
      children: (
        <Table
          rowKey="id" size="small" pagination={false}
          dataSource={latestReports}
          locale={{ emptyText: <Empty description="暂无报告" /> }}
          columns={[
            { title: '报告编号', dataIndex: 'report_no', width: 180, render: (v, r) => <a href={`/reports/${r.id}`} style={{ fontFamily: MONO_FONT }}>{v}</a> },
            { title: '标题', dataIndex: 'title', ellipsis: true },
            {
              title: '风险', dataIndex: 'risk_level', width: 90,
              render: (v) => <Tag color={riskColor(v)} style={{ color: '#fff', border: 'none' }}>{RISK_LABEL[v] ?? v}</Tag>,
            },
            { title: '生成时间', dataIndex: 'generated_at', width: 160, render: (v) => (v || '').slice(0, 16).replace('T', ' ') },
          ]}
        />
      ),
    },
  ].filter(Boolean)

  return (
    <div>
      {/* ① GateBanner —— 全页唯一强视觉元素 */}
      <Card
        size="small"
        style={{ borderLeft: `4px solid ${g.color}`, background: `${g.color}14`, marginBottom: 16 }}
      >
        <Row gutter={[16, 16]} align="middle">
          <Col xs={24} lg={7}>
            <div style={{ fontSize: 20, fontWeight: 600, color: g.color }}>{g.label}</div>
            <div style={{ color: '#8b97a7', fontSize: 13, marginTop: 4 }}>
              近30天通过率 {metrics.pass_rate_30d == null ? '—' : `${metrics.pass_rate_30d}%`}
            </div>
            <div style={{ color: '#8b97a7', fontSize: 12, marginTop: 6, fontFamily: MONO_FONT }}>
              生成于 {dayjs(data.generated_at).format('YYYY-MM-DD HH:mm')}
            </div>
          </Col>
          <Col xs={24} lg={10}>
            <Row gutter={[8, 8]}>
              {gate.checks.map((c) => {
                const cColor = c.passed ? undefined : (c.redline ? SEVERITY_COLOR.CRITICAL : SEVERITY_COLOR.MODERATE)
                return (
                  <Col xs={24} sm={12} lg={6} key={c.code}>
                    <div
                      style={{
                        borderLeft: `3px solid ${cColor ?? '#253042'}`,
                        background: cColor && c.redline ? `${SEVERITY_COLOR.CRITICAL}22` : undefined,
                        borderRadius: 4, padding: '6px 10px',
                      }}
                    >
                      <div style={{ fontSize: 12, color: '#8b97a7' }}>
                        {c.name}{' '}
                        {c.redline && <Tag color="red" style={{ marginLeft: 4 }}>红线</Tag>}
                        {c.passed
                          ? <CheckCircleFilled aria-label={`${c.name} 通过`} style={{ color: SEVERITY_COLOR.PASS, float: 'right' }} />
                          : <CloseCircleFilled aria-label={`${c.name} 未通过`} style={{ color: SEVERITY_COLOR.CRITICAL, float: 'right' }} />}
                      </div>
                      <div style={{ fontFamily: MONO_FONT, fontSize: 16 }}>
                        <span style={{ color: cColor ?? '#e6ebf0' }}>{c.actual}</span>
                        <span style={{ color: '#8b97a7', fontSize: 12 }}> / 阈值 {c.threshold}</span>
                      </div>
                    </div>
                  </Col>
                )
              })}
            </Row>
          </Col>
          <Col xs={24} lg={7} style={{ textAlign: 'right' }}>
            <Space direction="vertical" align="end">
              <Segmented
                options={[30, 90, 365].map((v) => ({ label: `${v} 天`, value: v }))}
                value={days}
                onChange={setDays}
              />
              <Tooltip title={canExport ? undefined : '需要报告导出权限'}>
                <Dropdown.Button
                  disabled={!canExport}
                  loading={exporting}
                  icon={<DownloadOutlined />}
                  menu={{ items: EXPORT_ITEMS, onClick: ({ key }) => doExport(key) }}
                  dropdownRender={(menu) => (
                    <>
                      {menu}
                      {/* §5.2 ①：导出现场提示——与页面底注、文件尾注构成三道"视图非存档"认知防线 */}
                      <div style={{ padding: '6px 12px', borderTop: '1px solid #253042', fontSize: 12, color: '#8b97a7' }}>
                        数据实时聚合，导出即快照
                      </div>
                    </>
                  )}
                  onClick={() => doExport('pdf')}
                >
                  导出质量报告
                </Dropdown.Button>
              </Tooltip>
            </Space>
          </Col>
        </Row>
      </Card>

      {/* ② MetricCards */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {[
          { title: '总任务', value: metrics.task_total },
          { title: '已完成', value: metrics.task_finished },
          { title: '通过率', value: metrics.pass_rate, suffix: '%' },
          { title: '缺陷总数', value: metrics.defect_total },
          { title: '未闭环', value: metrics.defect_open, suffix: null },
          { title: '闭环率', value: metrics.closure_rate, suffix: '%' },
        ].map((m) => (
          <Col xs={12} sm={8} lg={4} key={m.title}>
            <Card size="small">
              <Statistic
                title={m.title}
                value={m.value}
                suffix={m.suffix}
                valueStyle={{ fontFamily: MONO_FONT, color: brandColor }}
              />
              {m.title === '未闭环' && (
                <Text type="secondary" style={{ fontSize: 12 }}>P0:{metrics.p0_open} · P1:{metrics.p1_open}</Text>
              )}
            </Card>
          </Col>
        ))}
      </Row>

      {noData ? (
        /* NO_DATA：③④ 替换为引导空态 */
        <Card size="small" style={{ marginBottom: 16 }}>
          <Empty description="该项目还没有已完成的任务，去创建测试任务">
            <Button type="primary" onClick={() => onGoTab?.('tasks')}>去创建测试任务</Button>
          </Empty>
        </Card>
      ) : (
        <>
          {/* ③ ChartsRow */}
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={24} md={14}>
              <Card size="small" title={<span style={{ fontSize: 13 }}>任务通过率与缺陷趋势（近 {data.days} 天）</span>}>
                <ReactECharts option={trendOption} style={{ height: 280 }} notMerge lazyUpdate />
              </Card>
            </Col>
            <Col xs={24} md={10}>
              <Card size="small" title={<span style={{ fontSize: 13 }}>报告风险分布</span>}>
                <ReactECharts option={riskOption} style={{ height: 280 }} notMerge lazyUpdate />
              </Card>
            </Col>
          </Row>

          {/* ④ DetailTabs */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <Tabs size="small" items={detailItems} />
          </Card>
        </>
      )}

      <Alert
        type="info"
        showIcon
        message="本页与导出的质量报告均为实时聚合视图，数据随新任务执行而变化；某次执行的存档结论请查看对应任务报告。"
      />
    </div>
  )
}
