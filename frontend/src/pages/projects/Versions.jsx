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
import { useParams, useNavigate } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import {
  Button, Card, Space, Table, Tag, Modal, Form, Input, Select, message, Row, Col, Typography, Spin, Empty, Progress,
} from 'antd'
import { PlusOutlined, ArrowRightOutlined, SwapOutlined, LineChartOutlined, ReloadOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { fmtTime } from '../../utils'

const BRAND = '#13c2c2'
const RED = '#ff4d4f'
const GREEN = '#52c41a'

// —— 版本通过率趋势 ECharts option ——
function buildTrendOption(trend = [], baselineVersion) {
  const xs = trend.map((t) => t.version_no)
  const ys = trend.map((t) => t.pass_rate == null ? null : Number(t.pass_rate) * 100)
  const baselineIdx = xs.findIndex((v) => v === baselineVersion)
  return {
    backgroundColor: 'transparent',
    grid: { left: 48, right: 24, top: 32, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1a2130',
      borderColor: '#1f2833',
      textStyle: { color: '#e6ebf0' },
      formatter: (params) => {
        const p = params[0]
        const v = p.value
        return `<b>${p.name}</b><br/>通过率：${v == null ? '-' : v.toFixed(2)}%`
      },
    },
    xAxis: {
      type: 'category',
      data: xs,
      axisLine: { lineStyle: { color: '#2f3a4a' } },
      axisLabel: {
        color: '#8b97a7',
        fontFamily: 'JetBrains Mono, Consolas, monospace',
      },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: '#8b97a7', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#1f2833', type: 'dashed' } },
    },
    series: [
      {
        name: '通过率',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: (value, params) => (params.dataIndex === baselineIdx ? 10 : 6),
        showSymbol: true,
        data: ys.map((v, idx) => ({
          value: v,
          itemStyle: idx === baselineIdx ? { color: BRAND, borderColor: BRAND } : { color: '#8b97a7' },
        })),
        markLine: baselineIdx >= 0 ? {
          silent: true,
          symbol: 'none',
          lineStyle: { color: BRAND, type: 'dashed' },
          data: [{ xAxis: baselineIdx, label: { formatter: '基线', color: BRAND } }],
        } : undefined,
        animationDuration: 800,
        animationEasing: 'quarticOut',
        lineStyle: { width: 2, color: BRAND },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(19,194,194,0.35)' },
              { offset: 1, color: 'rgba(19,194,194,0.02)' },
            ],
          },
        },
      },
    ],
  }
}

// —— diff 箭头展示 ——
function DiffArrow({ value }) {
  if (value == null || Number.isNaN(Number(value))) return <span style={{ color: '#8b97a7' }}>-</span>
  const n = Number(value)
  const abs = Math.abs(n)
  if (abs < 1e-6) return <span style={{ color: '#8b97a7' }}>—</span>
  if (n > 0) {
    return (
      <span style={{ color: GREEN, fontFamily: 'JetBrains Mono, Consolas, monospace' }}>
        ↑ {abs.toFixed(2)}
      </span>
    )
  }
  return (
    <span style={{ color: RED, fontFamily: 'JetBrains Mono, Consolas, monospace' }}>
      ↓ {abs.toFixed(2)}
    </span>
  )
}

export default function Versions() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [loading, setLoading] = useState(false)
  const [trend, setTrend] = useState([])

  // Modal / Drawer 状态
  const [createOpen, setCreateOpen] = useState(false)
  const [createLoading, setCreateLoading] = useState(false)
  const [createForm] = Form.useForm()

  const [baselineOpen, setBaselineOpen] = useState(false)
  const [baselineTarget, setBaselineTarget] = useState(null)
  const [baselineOld, setBaselineOld] = useState(null)
  const [baselineLoading, setBaselineLoading] = useState(false)
  const [baselineForm] = Form.useForm()

  const [compareOpen, setCompareOpen] = useState(false)
  const [compareFrom, setCompareFrom] = useState(null)
  const [compareTo, setCompareTo] = useState(null)
  const [compareResult, setCompareResult] = useState(null)
  const [compareLoading, setCompareLoading] = useState(false)

  const loadList = async (p = page, ps = pageSize) => {
    setLoading(true)
    try {
      // 后端参数是 size 不是 page_size；返回 {items, total, page, size}
      const d = await http.get(`/projects/${id}/versions`, { params: { page: p, size: ps } })
      const wrapper = d && d.data ? d.data : d
      setRows(wrapper?.items || [])
      setTotal(wrapper?.total || 0)
    } finally {
      setLoading(false)
    }
  }

  const loadTrend = async () => {
    try {
      const d = await http.get(`/projects/${id}/versions/trend`)
      setTrend(Array.isArray(d) ? d : (d?.items || []))
    } catch {
      /* 趋势图接口缺失时静默降级 */
    }
  }

  useEffect(() => {
    loadList(1, pageSize)
    loadTrend()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const baselineVersion = useMemo(
    () => rows.find((r) => r.is_baseline)?.version_no,
    [rows]
  )

  // —— 新建版本 ——
  const handleCreate = async () => {
    const values = await createForm.validateFields()
    setCreateLoading(true)
    try {
      await http.post(`/projects/${id}/versions`, values)
      message.success('版本创建成功')
      setCreateOpen(false)
      createForm.resetFields()
      loadList(1, pageSize)
      loadTrend()
    } finally {
      setCreateLoading(false)
    }
  }

  // —— 设为基线 ——
  const openBaseline = (row) => {
    if (row.is_baseline) {
      message.info('该版本已是基线版本')
      return
    }
    const oldV = rows.find((r) => r.is_baseline)
    setBaselineTarget(row)
    setBaselineOld(oldV)
    setBaselineOpen(true)
    baselineForm.resetFields()
  }

  const handleSetBaseline = async () => {
    const values = await baselineForm.validateFields()
    setBaselineLoading(true)
    try {
      await http.put(`/projects/${id}/versions/${baselineTarget.id}/baseline`, {
        baseline_reason: values.reason,
      })
      message.success(`已将 ${baselineTarget.version_no} 设为基线`)
      setBaselineOpen(false)
      loadList(page, pageSize)
      loadTrend()
    } finally {
      setBaselineLoading(false)
    }
  }

  // —— 对比 ——
  const openCompare = (row) => {
    setCompareFrom(row?.id || null)
    setCompareTo(null)
    setCompareResult(null)
    setCompareOpen(true)
  }

  const runCompare = async () => {
    if (!compareFrom || !compareTo) {
      message.warning('请选择对比的两个版本')
      return
    }
    setCompareLoading(true)
    try {
      // 后端: GET /projects/{id}/versions/compare?from_version=xxx&to_version=xxx
      const fromV = rows.find((r) => r.id === compareFrom)?.version_no
      const toV = rows.find((r) => r.id === compareTo)?.version_no
      const d = await http.get(`/projects/${id}/versions/compare`, {
        params: { from_version: fromV, to_version: toV },
      })
      setCompareResult(d?.data ?? d)
    } finally {
      setCompareLoading(false)
    }
  }

  const fromVersion = rows.find((r) => r.id === compareFrom)
  const toVersion = rows.find((r) => r.id === compareTo)

  const columns = [
    {
      title: '版本号',
      dataIndex: 'version_no',
      width: 140,
      className: 'mono-no',
      render: (v) => <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }}>{v}</span>,
    },
    {
      title: '说明',
      dataIndex: 'description',
      ellipsis: true,
      render: (v) => v || <span style={{ color: '#8b97a7' }}>-</span>,
    },
    {
      title: '基线',
      dataIndex: 'is_baseline',
      width: 100,
      render: (v) => v
        ? <Tag style={{ borderColor: BRAND, color: BRAND, background: 'transparent' }}>基线版本</Tag>
        : <Tag color="default">非基线</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v) => fmtTime(v),
    },
    {
      title: '任务数',
      dataIndex: 'task_count',
      width: 90,
      className: 'mono-no',
      // ES10-P-02：可点击跳转到任务列表（按版本过滤）
      render: (n, r) => n
        ? <a onClick={() => navigate(`/tasks?project_version_id=${r.id}`)}>{n}</a>
        : <span style={{ color: '#8b97a7' }}>-</span>,
    },
    {
      title: '通过率',
      dataIndex: 'pass_rate',
      width: 110,
      // ES10-P-02：后端已返回 0-1 小数，用 Progress 展示；null 显示 '-'
      render: (p) => p == null
        ? <span style={{ color: '#8b97a7' }}>-</span>
        : <Progress percent={Math.round(Number(p) * 100)} size="small" />,
    },
    {
      title: '操作',
      width: 220,
      fixed: 'right',
      render: (_, row) => (
        <Space size={4} style={{ whiteSpace: 'nowrap' }}>
          <Button
            type="link"
            size="small"
            disabled={row.is_baseline}
            onClick={() => openBaseline(row)}
          >
            设为基线
          </Button>
          <Button
            type="link"
            size="small"
            icon={<SwapOutlined />}
            onClick={() => openCompare(row)}
          >
            对比
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          <LineChartOutlined style={{ color: BRAND, marginRight: 8 }} />
          版本管理
        </Typography.Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => { loadList(page, pageSize); loadTrend() }}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            新建版本
          </Button>
        </Space>
      </div>

      {/* 上半区：折线图 */}
      <Card
        size="small"
        title={<span style={{ borderLeft: `3px solid ${BRAND}`, paddingLeft: 8 }}>通过率趋势</span>}
        styles={{ body: { padding: 12 } }}
      >
        {trend.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无趋势数据" />
        ) : (
          <ReactECharts option={buildTrendOption(trend, baselineVersion)} style={{ height: 320 }} notMerge lazyUpdate />
        )}
      </Card>

      {/* 下半区：版本表格 */}
      <Card size="small" styles={{ body: { padding: 0 } }}>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={rows}
          scroll={{ x: 1100 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showTotal: (t) => `共 ${t} 个版本`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); loadList(p, ps) },
          }}
        />
      </Card>

      {/* —— 新建版本 Modal —— */}
      <Modal
        title="新建版本"
        open={createOpen}
        confirmLoading={createLoading}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        okText="创建"
        cancelText="取消"
      >
        <Form form={createForm} layout="vertical" preserve={false}>
          <Form.Item
            name="version_no"
            label="版本号"
            rules={[{ required: true, message: '请输入版本号' }]}
          >
            <Input placeholder="如 1.2.0" />
          </Form.Item>
          <Form.Item name="description" label="版本说明">
            <Input.TextArea rows={3} placeholder="描述该版本的主要变更" />
          </Form.Item>
        </Form>
      </Modal>

      {/* —— 设为基线 Modal —— */}
      <Modal
        title="设为基线版本"
        open={baselineOpen}
        confirmLoading={baselineLoading}
        onCancel={() => setBaselineOpen(false)}
        onOk={handleSetBaseline}
        okText="确认"
        cancelText="取消"
      >
        {baselineOld && baselineTarget && baselineOld.id !== baselineTarget.id && (
          <div style={{ color: RED, marginBottom: 12, padding: '8px 12px', border: `1px solid ${RED}33`, background: `${RED}11` }}>
            ⚠ 将取消原基线版本 <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }}>v{baselineOld.version_no}</span>
          </div>
        )}
        <div style={{ marginBottom: 12 }}>
          目标版本：<span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', color: BRAND, fontSize: 16 }}>
            v{baselineTarget?.version_no}
          </span>
        </div>
        <Form form={baselineForm} layout="vertical" preserve={false}>
          <Form.Item
            name="reason"
            label="设立基线原因"
            rules={[{ required: true, message: '请填写原因' }]}
          >
            <Input.TextArea rows={3} placeholder="说明为何选择该版本为基线，便于后续追溯" />
          </Form.Item>
        </Form>
      </Modal>

      {/* —— 版本对比 Modal —— */}
      <Modal
        title="版本对比"
        open={compareOpen}
        width={720}
        onCancel={() => setCompareOpen(false)}
        footer={[
          <Button key="close" onClick={() => setCompareOpen(false)}>关闭</Button>,
          <Button key="run" type="primary" loading={compareLoading} onClick={runCompare}>执行对比</Button>,
        ]}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Row gutter={12} align="middle">
            <Col span={10}>
              <Select
                style={{ width: '100%' }}
                placeholder="源版本（from）"
                value={compareFrom}
                onChange={setCompareFrom}
                options={rows.map((r) => ({ value: r.id, label: r.version_no }))}
              />
            </Col>
            <Col span={4} style={{ textAlign: 'center', color: BRAND }}>
              <ArrowRightOutlined style={{ fontSize: 20 }} />
            </Col>
            <Col span={10}>
              <Select
                style={{ width: '100%' }}
                placeholder="目标版本（to）"
                value={compareTo}
                onChange={setCompareTo}
                options={rows.map((r) => ({ value: r.id, label: r.version_no }))}
              />
            </Col>
          </Row>

          {compareResult && (
            <Spin spinning={compareLoading}>
              <Card size="small" styles={{ body: { padding: 16 } }}>
                <Row gutter={16}>
                  <Col span={12}>
                    <div style={{ borderLeft: `3px solid ${BRAND}`, paddingLeft: 8, marginBottom: 12 }}>
                      <div style={{ color: '#8b97a7' }}>源版本</div>
                      <div style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', fontSize: 18, color: BRAND }}>
                        {fromVersion?.version_no || '-'}
                      </div>
                    </div>
                    <DescriptionsMini
                      passRate={compareResult.from?.pass_rate}
                      total={compareResult.from?.total}
                      failed={compareResult.from?.failed}
                      summary={compareResult.from?.summary}
                    />
                  </Col>
                  <Col span={12}>
                    <div style={{ borderLeft: '3px solid #f59e0b', paddingLeft: 8, marginBottom: 12 }}>
                      <div style={{ color: '#8b97a7' }}>目标版本</div>
                      <div style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', fontSize: 18, color: '#f59e0b' }}>
                        {toVersion?.version_no || '-'}
                      </div>
                    </div>
                    <DescriptionsMini
                      passRate={compareResult.to?.pass_rate}
                      total={compareResult.to?.total}
                      failed={compareResult.to?.failed}
                      summary={compareResult.to?.summary}
                    />
                  </Col>
                </Row>

                {Array.isArray(compareResult.diff) && compareResult.diff.length > 0 && (
                  <div style={{ marginTop: 16 }}>
                    <div style={{ fontWeight: 600, marginBottom: 8 }}>指标差异</div>
                    {compareResult.diff.map((d) => (
                      <Row key={d.metric} gutter={12} style={{ padding: '6px 0', borderBottom: '1px dashed #1f2833' }}>
                        <Col span={8} style={{ color: '#e6ebf0' }}>{d.label || d.metric}</Col>
                        <Col span={6} style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', color: '#8b97a7' }}>
                          {typeof d.from === 'number' ? d.from.toFixed(2) : (d.from ?? '-')}
                        </Col>
                        <Col span={2} style={{ color: '#8b97a7', textAlign: 'center' }}>→</Col>
                        <Col span={6} style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', color: '#e6ebf0' }}>
                          {typeof d.to === 'number' ? d.to.toFixed(2) : (d.to ?? '-')}
                        </Col>
                        <Col span={2}><DiffArrow value={d.diff} /></Col>
                      </Row>
                    ))}
                  </div>
                )}
              </Card>
            </Spin>
          )}
        </Space>
      </Modal>
    </Space>
  )
}

// —— 内嵌小组件 ——
function DescriptionsMini({ passRate, total, failed, summary }) {
  const pr = passRate != null
    ? (typeof passRate === 'number' ? passRate : Number(passRate)) * 100
    : (summary?.pass_rate != null ? Number(summary.pass_rate) * 100 : null)
  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      <Row justify="space-between"><span style={{ color: '#8b97a7' }}>通过率</span><span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }}>{pr == null ? '-' : `${pr.toFixed(2)}%`}</span></Row>
      <Row justify="space-between"><span style={{ color: '#8b97a7' }}>用例总数</span><span className="mono-no">{summary?.total ?? total ?? '-'}</span></Row>
      <Row justify="space-between"><span style={{ color: '#8b97a7' }}>失败数</span><span className="mono-no">{summary?.failed ?? failed ?? '-'}</span></Row>
    </Space>
  )
}
