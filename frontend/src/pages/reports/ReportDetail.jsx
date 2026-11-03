/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { lazy, useEffect, useState } from 'react'
import {
  Space, Row, Col, Card, Typography, Descriptions, Button, Collapse, Tag, Table, App, Empty, Tabs, Alert, Tooltip,
} from 'antd'
import { SafetyCertificateOutlined, ShareAltOutlined, DownloadOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { tokens } from '../../theme/tokens'
import { useAuth } from '../../auth'
import TermTooltip from '../../components/common/TermTooltip'
import { THREAT_TYPES } from '../../components/cases/caseSchemas'
import { REPORT_STATUS_MAP, REPORT_TYPE_MAP, ENGINE_NAME_MAP, VERDICT_CN_MAP, SEVERITY_CN_MAP, STEP_STATUS_CN_MAP, labelOf } from '../../constants/enums'
import {
  BRAND, buildRadarOption, buildBarOption, buildPieOption, buildLineOption,
  ChartBox, SummaryCard, RadarChartOutlined, CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
} from './charts'
import EnvironmentBlock from './EnvironmentBlock'
import ScreenshotGallery from './ScreenshotGallery'
import ReproductionSteps from './ReproductionSteps'
import FailureLogPanel from './FailureLogPanel'
import BugDetailDrawer from './BugDetailDrawer'
import ReactECharts from 'echarts-for-react'
import {
  RedteamReport, HallucinationReport, EthicsReport,
  InjectionReport, RagReport, MultiTurnReport,
} from '../eval/reportRenderers'
import ComplianceConclusion from './ComplianceConclusion'
import { useIsCommunity } from '../../edition/EditionContext'
import UpgradeEmpty from '../../components/UpgradeEmpty'
import CommercialGate from '../../components/CommercialGate'
import PageSuspense from '../../components/common/PageSuspense'
// ES11 P10：交付就绪区（上线建议 + G4 阻塞项直达修复页），置于图表之前
import { DeliveryReadinessSection } from '../es11/deliveryVerdict'

// F1 版本隔离：安全审计报告视图属商业模块（OSS 构建整目录剔除 + 说明符改写）
const SecurityReportView = lazy(() => import('../CommercialPlaceholder'))

// AI 引擎专用渲染器（与 EvalCenter 同一套契约：items=引擎 report_payload.items）
const AI_ENGINE_RENDERERS = {
  REDTEAM_TEST: RedteamReport,
  HALLUCINATION_TEST: HallucinationReport,
  ETHICS_TEST: EthicsReport,
  PROMPT_INJECTION: InjectionReport,
  RAG_TEST: RagReport,
  MULTI_TURN_TEST: MultiTurnReport,
}

// ---------------- 注入向量审计（与后端导出同口径：PROMPT_INJECTION 用例级 DIRECT/INDIRECT 分组） ----------------
const THREAT_TYPE_CN = Object.fromEntries(THREAT_TYPES.map((t) => [t.value, t.label]))
function InjectionVectorAudit({ items }) {
  const direct = items.filter((i) => i.injection_vector === 'DIRECT')
  const indirect = items.filter((i) => i.injection_vector === 'INDIRECT')
  const riskCount = (arr) => arr.filter((i) => i.verdict === 'RISK').length
  const columns = [
    { title: '用例', dataIndex: 'item_no', width: 90, render: (v, _, i) => v || `#${i + 1}` },
    { title: '标题', dataIndex: 'title', ellipsis: true },
    { title: '威胁类型', dataIndex: 'threat_type', width: 140, render: (v) => THREAT_TYPE_CN[v] || v || '-' },
    {
      title: '判定', dataIndex: 'verdict', width: 90,
      render: (v) => <Tag color={v === 'RISK' ? 'red' : v === 'PASS' ? 'green' : 'default'}>{VERDICT_CN_MAP[v] || v || '-'}</Tag>,
    },
    { title: '严重度', dataIndex: 'severity', width: 90, render: (v) => (v ? <Tag>{SEVERITY_CN_MAP[v] || v}</Tag> : '-') },
  ]
  const group = (label, color, rows) => (
    <Card
      size="small"
      title={(
        <Space>
          <Tag color={color}>{label}</Tag>
          <Typography.Text type="secondary">{rows.length} 条 / 风险 {riskCount(rows)} 条</Typography.Text>
        </Space>
      )}
    >
      <Table
        rowKey={(_, idx) => idx}
        size="small"
        columns={columns}
        dataSource={rows}
        pagination={{ pageSize: 10, showSizeChanger: false }}
      />
    </Card>
  )
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Space size={8}>
        <Tag color="volcano">直接注入风险 {riskCount(direct)} / {direct.length}</Tag>
        <Tag color="geekblue">间接注入风险 {riskCount(indirect)} / {indirect.length}</Tag>
      </Space>
      {group('直接注入', 'volcano', direct)}
      {group('间接注入', 'geekblue', indirect)}
    </Space>
  )
}

// ---------------- BUG-7：报告三级展开（用例 / 数据分组 / 断言明细） ----------------
const RESULT_COLOR = { PASS: '#3f9c3f', FAIL: '#d9404f', SKIP: '#8b97a7' }

// 引擎指标常见键名中文映射（未知键回退原始键名）
const METRIC_LABEL_CN = {
  avg_similarity: '平均语义相似度',
  severity_distribution: '严重度分布',
  score: '得分',
  threshold: '阈值',
  pass_rate: '通过率',
  total: '用例总数',
  passed: '通过数',
  failed: '失败数',
  skipped: '跳过数',
  avg_consistency: '平均一致性',
  contradictions: '矛盾次数',
  avg_compliance: '平均合规得分',
  overall: '综合得分',
  qps: 'QPS（每秒请求数）',
  p95: 'P95 延迟(ms)',
  avg_latency_ms: '平均延迟(ms)',
  total_requests: '请求总数',
  error_rate: '错误率',
}

function renderValue(v) {
  if (v === null || v === undefined) return '-'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

// BUG-014：response_preview 完整展示 + 展开/收起（与后端 MAX_PREVIEW=500 统一）
function ResponsePreview({ value }) {
  const [logExpanded, setLogExpanded] = useState(false)
  const MAX_PREVIEW = 500
  const str = renderValue(value)
  if (str === '-') return null
  if (logExpanded || str.length <= MAX_PREVIEW) {
    return (
      <div style={{ marginBottom: 4 }}>
        <Typography.Text strong>响应预览：</Typography.Text>
        <pre style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: '#8b97a7' }}>
          {str}
        </pre>
      </div>
    )
  }
  return (
    <div style={{ marginBottom: 4 }}>
      <Typography.Text strong>响应预览：</Typography.Text>
      <pre style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: '#8b97a7' }}>
        {str.slice(0, MAX_PREVIEW)}...
      </pre>
      <Button size="small" type="link" onClick={() => setLogExpanded(true)}>
        展开完整日志（{str.length} 字符）
      </Button>
    </div>
  )
}

/** 断言/失败明细：将 failures 文本逐条展开（含 op/path/expected/actual） */
function FailureList({ failures }) {
  if (!failures || !failures.length) return <Typography.Text type="secondary">无失败项</Typography.Text>
  const rows = failures.map((f, i) => ({ key: i, text: renderValue(f) }))
  return (
    <Table
      size="small"
      rowKey="key"
      dataSource={rows}
      pagination={false}
      columns={[
        { title: '#', width: 40, render: (_, __, i) => i + 1 },
        { title: <TermTooltip term="失败明细" explain="每次自动比对 实际输出 vs 预期输出 的记录" example="期望 code=0，实际 code=500" children="失败明细" />, dataIndex: 'text' },
      ]}
      style={{ marginTop: 8 }}
    />
  )
}

/** 数据分组（用例执行单元）明细 */
function GroupDetail({ group, reportId, projectId, taskId }) {
  const { message } = App.useApp()
  const handleToDefect = async () => {
    try {
      await http.post('/defects', {
        report_id: reportId,
        project_id: projectId,
        task_id: taskId,
        case_id: group.case_id,
        title: `[报告] ${group.case_no || ''} ${group.title || ''} 执行失败`,
        severity: 'P2',
      })
      message.success('缺陷已创建，actual/expected 由后端自动填充')
    } catch (e) { console.warn('[ReportDetail] to-defect 失败', e?.message) }
  }
  const desc = [
    { label: '用例编号', value: group.case_no },
    { label: '用例名称', value: group.title },
    { label: '数据分组', value: group.group },
    { label: '请求方法', value: group.method },
    { label: '请求路径', value: group.path },
    { label: '期望状态码', value: group.expected_status },
    { label: '实际状态码', value: group.status_code },
    { label: '耗时(ms)', value: group.duration_ms },
    { label: '结果', value: group.result ? (VERDICT_CN_MAP[group.result] || group.result) : group.result },
  ].filter((it) => it.value !== undefined)
  return (
    <>
      <Descriptions column={2} size="small" bordered style={{ marginBottom: 8 }}>
        {desc.map((it) => (
          <Descriptions.Item key={it.label} label={it.label}>{renderValue(it.value)}</Descriptions.Item>
        ))}
      </Descriptions>
      {group.result === 'FAIL' && reportId && (
        <Button size="small" type="primary" danger onClick={handleToDefect} style={{ marginBottom: 8 }}>
          一键转缺陷
        </Button>
      )}
      {group.response_preview !== undefined && (
        <ResponsePreview value={group.response_preview} />
      )}
      <Typography.Text strong>断言判定：</Typography.Text>
      <FailureList failures={group.failures} />
    </>
  )
}

/** 引擎步骤明细：用例级 → 数据分组级 → 断言明细级 三级展开 */
function StepDetailsSection({ stepDetails, report }) {
  const { message } = App.useApp()
  const { hasPerm } = useAuth()
  const [markedMap, setMarkedMap] = useState({}) // ES8 M6：本地乐观更新的「已标记」态（按 item_index）
  const [marking, setMarking] = useState(null)
  if (!stepDetails || !stepDetails.length) {
    return <Card size="small"><Typography.Text type="secondary">无步骤明细数据</Typography.Text></Card>
  }
  // ES8 M6：报告详情复核徽标数据（report.review = {runs:[{run_id,items:{idx:{...}}}], reviewable}）
  const reviewData = report?.review
  const reviewByIndex = {}
  if (reviewData?.reviewable) {
    for (const r of reviewData.runs || []) {
      for (const [k, v] of Object.entries(r.items || {})) {
        reviewByIndex[Number(k)] = { ...v, runId: r.run_id }
      }
    }
  }
  // 标记「判分不对」入队（幂等：OPEN 态重复标记返回既有项），成功后本地刷新徽标
  const markWrong = async (runId, idx) => {
    setMarking(idx)
    try {
      await http.post('/review/items/from-report', { run_id: runId, item_index: idx })
      message.success('已标记并加入复核队列')
      setMarkedMap((prev) => ({ ...prev, [idx]: { status: 'OPEN', runId } }))
    } catch (e) { /* 拦截器已弹错，此处仅留痕 */ console.warn('[ReportDetail] 标记复核失败', e?.message) }
    finally { setMarking(null) }
  }
  const stepItems = stepDetails.map((step, si) => {
    const details = step.details || {}
    const results = Array.isArray(details.results) ? details.results : []
    const items = Array.isArray(details.items) ? details.items : []
    const warnings = details.cleanup_warnings || []
    const inner = []
    if (results.length) {
      inner.push({
        key: `r-${si}`,
        label: `用例/数据分组（${results.length}）`,
        children: (
          <Collapse
            size="small"
            items={results.map((g, gi) => ({
              key: `g-${si}-${gi}`,
              label: (
                <Space size={8}>
                  <Typography.Text>{g.case_no || `分组${gi + 1}`}</Typography.Text>
                  <Typography.Text type="secondary">{g.title}</Typography.Text>
                  {g.group && <Tag>分组：{renderValue(g.group)}</Tag>}
                  <Tag color={g.result === 'FAIL' ? 'red' : g.result === 'SKIP' ? 'default' : 'green'}>{VERDICT_CN_MAP[g.result] || renderValue(g.result)}</Tag>
                </Space>
              ),
              children: <GroupDetail group={g} reportId={report?.id} projectId={report?.project_id} taskId={report?.task_id} />,
            }))}
          />
        ),
      })
    }
    if (items.length) {
      const AiRenderer = AI_ENGINE_RENDERERS[step.engine]
      inner.push({
        key: `it-${si}`,
        label: `样本判定明细（${items.length}）`,
        children: AiRenderer ? (
          <AiRenderer
            items={items}
            summary={details.summary || step.summary || {}}
            ragas={details.ragas || step.summary?.ragas}
          />
        ) : (
          <Table
            size="small"
            rowKey={(r, i) => `it-${si}-${i}`}
            dataSource={items}
            pagination={false}
            columns={[
              { title: '#', width: 50, render: (_, __, i) => i + 1 },
              { title: '样本/场景', dataIndex: 'item', render: (v, r) => renderValue(r.item ?? r.case_no ?? r.title) },
              { title: '结果', dataIndex: 'result', width: 100, render: (v) => <Tag color={v === 'PASS' ? 'green' : v === 'SKIP' ? 'default' : 'red'}>{VERDICT_CN_MAP[v] || renderValue(v)}</Tag> },
              { title: '判定详情', dataIndex: 'reason', render: (v, r) => renderValue(v ?? r.verdict ?? r.note ?? '') },
              // ES8 M6：复核徽标列——仅对与 EvalRun items 同序的普通明细表展示
              ...(reviewData?.reviewable ? [{
                title: '复核', width: 170,
                render: (_, __, i) => {
                  const rv = markedMap[i] || reviewByIndex[i]
                  if (rv?.status === 'DONE') {
                    return (
                      <Tooltip title={`人判：${VERDICT_CN_MAP[rv.human_verdict] || rv.human_verdict || '-'}`}>
                        <Tag color="green">已复核</Tag>
                      </Tooltip>
                    )
                  }
                  if (rv?.status === 'ASSIGNED') return <Tag color="gold">已指派</Tag>
                  if (rv?.status === 'OPEN') return <Tag color="orange">待复核</Tag>
                  if (!hasPerm('review:manage')) return null
                  return (
                    <Button
                      size="small" type="link" style={{ padding: 0 }}
                      loading={marking === i}
                      onClick={() => markWrong(reviewData.runs[0]?.run_id, i)}
                    >标记判分不对</Button>
                  )
                },
              }] : []),
            ]}
          />
        ),
      })
    }
    if (warnings.length) {
      inner.push({
        key: `w-${si}`,
        label: `后置清理告警（${warnings.length}）`,
        children: (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {warnings.map((w, wi) => (
              <li key={wi} style={{ color: '#c98b2d', fontSize: 12 }}>{renderValue(w)}</li>
            ))}
          </ul>
        ),
      })
    }
    if (details.metrics) {
      inner.push({
        key: `m-${si}`,
        label: '引擎指标（metrics）',
        children: (
          <Descriptions column={2} size="small" bordered>
            {Object.entries(details.metrics || {}).map(([k, v]) => (
              <Descriptions.Item key={k} label={METRIC_LABEL_CN[k] || k}>{renderValue(v)}</Descriptions.Item>
            ))}
          </Descriptions>
        ),
      })
    }
    if (!inner.length) {
      // BUG-002：去掉 <pre> 原始 JSON 兜底，改为空态摘要
      inner.push({
        key: `e-${si}`,
        label: '详情',
        children: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该步骤无结构化明细数据" />,
      })
    }
    return {
      key: `s-${si}`,
      label: (
        <Space size={8}>
          <Typography.Text strong>{ENGINE_NAME_MAP[step.engine] || step.engine || `步骤${si + 1}`}</Typography.Text>
          <Tag color={step.status === 'SUCCESS' ? 'green' : step.status === 'SKIPPED' ? 'default' : 'red'}>{STEP_STATUS_CN_MAP[step.status] || renderValue(step.status)}</Tag>
          {step.conclusion && <Typography.Text type="secondary">{renderValue(step.conclusion)}</Typography.Text>}
        </Space>
      ),
      children: <Collapse size="small" items={inner} defaultActiveKey={AI_ENGINE_RENDERERS[step.engine] && items.length ? [`it-${si}`] : []} />,
    }
  })
  // AI 引擎步骤默认展开，保证用例明细直接可见
  const aiStepKeys = stepDetails
    .map((s, i) => (AI_ENGINE_RENDERERS[s.engine] && Array.isArray((s.details || {}).items) && (s.details || {}).items.length ? `s-${i}` : null))
    .filter(Boolean)
  return (
    <Collapse
      items={stepItems}
      style={{ marginTop: 8 }}
      defaultActiveKey={aiStepKeys}
      expandIconPosition="end"
    />
  )
}

// ---------------------------------------------------------------------------

export default function ReportDetail({ report, onShareClick }) {
  const [charts, setCharts] = useState(null)
  const [chartsLoading, setChartsLoading] = useState(false)
  const [sections, setSections] = useState(null)
  const [bugDrawerVisible, setBugDrawerVisible] = useState(false)
  const [selectedBug, setSelectedBug] = useState(null)
  const { message } = App.useApp()
  const isCommunity = useIsCommunity()

  const loadSections = (id) => {
    http.get(`/reports/${id}/sections`)
      .then((d) => { const data = d && d.data ? d.data : (d || {}); setSections(Array.isArray(data.sections) ? data.sections : []) })
      .catch(() => setSections([]))
  }

  useEffect(() => {
    if (!report?.id) return
    let cancelled = false
    setChartsLoading(true)
    http.get(`/reports/${report.id}/charts`)
      .then((d) => { if (!cancelled) setCharts(d) })
      .catch((e) => { /* 静默降级 */ console.warn('[ReportDetail] charts load failed', e?.message || e) })
      .finally(() => !cancelled && setChartsLoading(false))
    return () => { cancelled = true }
  }, [report?.id])

  // 报告四节化：覆盖 / 数据流 / 页面明细 / BUG 清单
  const refreshSections = () => { if (report?.id) loadSections(report.id) }
  useEffect(() => {
    if (!report?.id) { setSections(null); return }
    loadSections(report.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report?.id])

  // BUG 节一键批量转缺陷
  const handleBulkDefect = async (items = []) => {
    const toCreate = (items || []).filter((it) => !it.id)
    if (!toCreate.length) { message.info('没有可转换的缺陷条目'); return }
    const body = toCreate.map((it) => ({
      project_id: report.project_id,
      case_id: it.case_id,
      task_id: report.task_id,
      title: it.title,
      severity: it.severity,
      priority: it.priority,
      module: it.module,
      actual: it.actual,
      expected: it.expected,
    }))
    try {
      await http.post('/defects/bulk', { items: body })
      message.success(`已批量转换 ${body.length} 条缺陷`)
      refreshSections()
    } catch (e) { console.warn('[ReportDetail] bulk to-defect 失败', e?.message || e) }
  }

  // BUG-002：报告详情「导出 JSON」按钮
  const exportJson = async () => {
    if (!report?.id) return
    try {
      const blob = await http.get(`/reports/${report.id}/export`, { params: { format: 'json' }, responseType: 'blob', timeout: 120000 })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${report.report_no || 'report'}.json`
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
      message.success('报告 JSON 已导出')
    } catch (e) { console.warn('[ReportDetail] 导出 JSON 失败', e?.message || e) }
  }

  // 渲染一个分节
  const renderSection = (sec) => {
    const items = sec.items || []
    const reproItems = (sections || []).find((s) => s.key === 'reproduction')?.items || []
    if (!items.length) {
      return <Card size="small" title={sec.title}><Empty description="本节约无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} /></Card>
    }
    switch (sec.key) {
      case 'coverage':
        return (
          <Card size="small" title={sec.title}>
            <Table size="small" rowKey={(_, i) => i} pagination={false} dataSource={items}
              columns={[
                { title: '模块', dataIndex: 'module', render: (v) => v || '-' },
                { title: '用例数', dataIndex: 'case_count', width: 110, align: 'center' },
                { title: '执行次数', dataIndex: 'run_count', width: 110, align: 'center' },
              ]} />
          </Card>
        )
      case 'dataflow':
        return (
          <Card size="small" title={sec.title}>
            <Table size="small" rowKey={(_, i) => i} pagination={false} dataSource={items}
              columns={[
                { title: '引擎', dataIndex: 'engine', render: (v) => ENGINE_NAME_MAP[v] || v || '-' },
                { title: '状态', dataIndex: 'status', width: 130, render: (v) => <Tag color={v === 'SUCCESS' ? 'green' : v === 'SKIPPED' ? 'default' : 'red'}>{STEP_STATUS_CN_MAP[v] || renderValue(v)}</Tag> },
                { title: '摘要', dataIndex: 'summary', render: (v) => renderValue(v) },
              ]} />
          </Card>
        )
      case 'pages':
        return (
          <Card size="small" title={sec.title}>
            <Table size="small" rowKey={(_, i) => i} pagination={false} dataSource={items}
              columns={[
                { title: '引擎', dataIndex: 'engine', render: (v) => ENGINE_NAME_MAP[v] || v || '-' },
                { title: '状态', dataIndex: 'status', width: 130, render: (v) => <Tag color={v === 'SUCCESS' ? 'green' : v === 'SKIPPED' ? 'default' : 'red'}>{STEP_STATUS_CN_MAP[v] || renderValue(v)}</Tag> },
                { title: '结论', dataIndex: 'conclusion', render: (v) => renderValue(v) },
              ]} />
          </Card>
        )
      case 'bugs':
        return (
          <Card size="small" title={sec.title} extra={items.some((it) => !it.id) ? (
            <Button size="small" type="primary" danger onClick={() => handleBulkDefect(items)}>
              一键批量转缺陷（{items.filter((it) => !it.id).length}）
            </Button>
          ) : undefined}>
            <Table size="small" rowKey={(r, i) => r.defect_no || `b-${i}`} pagination={false} dataSource={items}
              onRow={(record) => ({
                onClick: () => { setSelectedBug(record); setBugDrawerVisible(true) },
                style: { cursor: 'pointer' },
              })}
              columns={[
                { title: '缺陷编号', dataIndex: 'defect_no', width: 170, render: (v) => v || '-' },
                { title: '标题', dataIndex: 'title', ellipsis: true, render: (v) => v || '-' },
                { title: '严重度', dataIndex: 'severity', width: 90, render: (v) => v || '-' },
                { title: '优先级', dataIndex: 'priority', width: 90, render: (v) => v || '-' },
                { title: '状态', dataIndex: 'status', width: 90, render: (v) => v || '-' },
                { title: '指派人', dataIndex: 'assignee', width: 100, render: (v, r) => v || r.assignee_name || '未指派' },
                { title: '关联需求号', dataIndex: 'requirement_id', width: 150, render: (v) => v ? <Tag color="blue">{v}</Tag> : '-' },
                { title: '模块', dataIndex: 'module', width: 110, render: (v) => v || '-' },
              ]} />
          </Card>
        )
      case 'failures':
        return (
          <Card size="small" title={sec.title}>
            <Collapse
              size="small"
              items={items.map((f, i) => ({
                key: `f-${i}`,
                label: (
                  <Space size={8} wrap>
                    <Typography.Text strong>{f.case_no || `失败用例 ${i + 1}`}</Typography.Text>
                    <Typography.Text type="secondary">{f.title}</Typography.Text>
                    {f.engine && <Tag>{ENGINE_NAME_MAP[f.engine] || f.engine}</Tag>}
                    <Tag color="red">失败</Tag>
                  </Space>
                ),
                children: (
                  <>
                    <ScreenshotGallery screenshots={f.screenshots || []} />
                    <ReproductionSteps
                      reproduction={reproItems.find((r) => r.case_id === f.case_id)}
                    />
                    <FailureLogPanel failureDetail={f.failure_detail} />
                  </>
                ),
              }))}
            />
          </Card>
        )
      case 'screenshots':
        return (
          <Card size="small" title={sec.title}>
            <ScreenshotGallery screenshots={items} />
          </Card>
        )
      case 'reproduction':
        return (
          <Card size="small" title={sec.title}>
            <Collapse
              size="small"
              items={items.map((r, i) => ({
                key: `rp-${i}`,
                label: (
                  <Space size={8} wrap>
                    <Typography.Text strong>{r.case_no || `用例 ${r.case_id}`}</Typography.Text>
                    <Tag color="red">{r.probability}</Tag>
                  </Space>
                ),
                children: <ReproductionSteps reproduction={r} />,
              }))}
            />
          </Card>
        )
      default:
        return <Card size="small" title={sec.title}><Typography.Text type="secondary">{renderValue(items)}</Typography.Text></Card>
    }
  }

  const summary = report?.summary || {}
  const content = report?.content || {}
  // 三级明细优先取 content.step_details，老报告兜底到 summary.step_results
  const stepDetails =
    (typeof content === 'object' && Array.isArray(content.step_details) && content.step_details) ||
    (Array.isArray(summary.step_results) && summary.step_results) || []
  const sectionByKey = Object.fromEntries((sections || []).map((s) => [s.key, s]))
  // 注入向量审计：与后端 _injection_vector_items 同口径（PROMPT_INJECTION 步骤含 injection_vector 的用例）
  const vectorItems = stepDetails
    .filter((s) => s?.engine === 'PROMPT_INJECTION')
    .flatMap((s) => ((s.details || {}).items || []).filter((r) => r?.injection_vector))
  // BUG-003/004/006：七节 Tabs（覆盖/数据流/页面明细/BUG清单/失败明细/截图/复现步骤）；缺节保留 Tab 空态
  const SECTION_TABS = [
    { key: 'coverage', label: '功能覆盖' },
    { key: 'dataflow', label: '数据流执行' },
    { key: 'pages', label: '页面·接口明细' },
    { key: 'bugs', label: 'BUG 清单' },
    { key: 'failures', label: '失败明细' },
    { key: 'screenshots', label: '失败截图' },
    { key: 'reproduction', label: '复现步骤' },
  ]

  const isDemo =
    content?.demo_mode === true ||
    summary?.demo_mode === true ||
    stepDetails.some((s) => s?.target_mode === 'INTERNAL_DEMO')

  // ES8 M5：门禁徽章（PASSED 绿 / FAILED 红 / NOT_EVALUATED 灰；非门禁任务不渲染）
  const gate = report?.gate || {}
  const GATE_BADGE = {
    PASSED: { text: '门禁通过 PASSED', color: tokens.success },
    FAILED: { text: '门禁未过 FAILED', color: tokens.danger },
    NOT_EVALUATED: { text: '门禁未评估', color: tokens.text3 },
  }
  const gateBadge = GATE_BADGE[gate.verdict]
  const gateTip = (gate.checks || [])
    .map((c) => (c.skipped ? `${c.metric}：缺数据（跳过）` : `${c.metric} ${c.op} ${c.threshold} → ${c.actual}${c.ok ? ' ✓' : ' ✗'}`))
    .join('\n')

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {/* v2.0 P3：演示模式黄色横幅（说明数据真实性，避免误解为"假数据"） */}
      {isDemo && (
        <Alert
          type="warning"
          showIcon
          banner
          message="演示模式报告（被测对象为平台内置演示模型）"
          description="本报告中的用例、执行记录、得分与图表均来自本平台的真实执行数据；但本次任务未绑定外部真实被测系统，被测对象为平台内置演示模型，结果反映的是 EvalShield 平台自身能力，不能作为对客户系统验收的依据。导出 PDF 将带演示水印。"
          style={{ borderRadius: 6 }}
        />
      )}
      {/* ES11 P10：交付就绪区——先给上线建议（通过/有条件通过/不可交付/证据不足），再给图表 */}
      <DeliveryReadinessSection reportId={report?.id} />
      {gate.enabled && gateBadge && (
        <Tooltip title={<span style={{ whiteSpace: 'pre-line' }}>{gateTip || gateBadge.text}</span>}>
          <Tag
            icon={<SafetyCertificateOutlined />}
            style={{ color: gateBadge.color, borderColor: gateBadge.color, background: 'transparent', fontSize: 13, padding: '2px 10px' }}
          >
            {gateBadge.text}
          </Tag>
        </Tooltip>
      )}
      <SummaryCard
        score={report?.overall_score ?? summary?.overall_score}
        riskLevel={report?.risk_level ?? summary?.risk_level}
        passed={summary?.passed ?? report?.passed}
        total={summary?.total ?? report?.total}
        rate={summary?.pass_rate ?? report?.pass_rate}
      />
      {chartsLoading ? (
        <div style={{ textAlign: 'center', padding: 24, color: '#8b97a7' }}>图表加载中…</div>
      ) : charts ? (
        <Row gutter={[12, 12]}>
          <Col xs={24} md={12}><ChartBox title="雷达评分" icon={<RadarChartOutlined style={{ color: BRAND, marginRight: 4 }} />}><ReactECharts option={buildRadarOption(charts.radar)} notMerge lazyUpdate /></ChartBox></Col>
          <Col xs={24} md={12}><ChartBox title="柱状对比" icon={<CheckCircleOutlined style={{ color: BRAND, marginRight: 4 }} />}><ReactECharts option={buildBarOption(charts.bar)} notMerge lazyUpdate /></ChartBox></Col>
          <Col xs={24} md={12}><ChartBox title="结果分布" icon={<CloseCircleOutlined style={{ color: BRAND, marginRight: 4 }} />}><ReactECharts option={buildPieOption(charts.pie)} notMerge lazyUpdate /></ChartBox></Col>
          <Col xs={24} md={12}><ChartBox title="历史趋势" icon={<ExclamationCircleOutlined style={{ color: BRAND, marginRight: 4 }} />}><ReactECharts option={buildLineOption(charts.line)} notMerge lazyUpdate /></ChartBox></Col>
        </Row>
      ) : (
        <Card size="small"><Typography.Text type="secondary">暂无图表数据</Typography.Text></Card>
      )}
      <Descriptions column={2} size="small" bordered>
        <Descriptions.Item label="报告编号">{report.report_no}</Descriptions.Item>
        <Descriptions.Item label="关联任务">{report.task_no}</Descriptions.Item>
        <Descriptions.Item label="类型">{labelOf(REPORT_TYPE_MAP, report.report_type)}</Descriptions.Item>
        <Descriptions.Item label="状态">{labelOf(REPORT_STATUS_MAP, report.status)}</Descriptions.Item>
      </Descriptions>
      {/* v2.0 BUG-002/012：环境指纹 + 风险等级判定依据 */}
      <EnvironmentBlock
        environment={report?.environment ?? content?.environment ?? charts?.environment}
        riskLevel={report?.risk_level ?? charts?.summary?.risk_level ?? summary?.risk_level}
        riskBasis={report?.risk_basis ?? charts?.summary?.risk_basis ?? summary?.risk_basis}
      />
      {/* P1：合规结论章节（含法条映射与盖章落款） */}
      {content?.compliance_conclusion && <ComplianceConclusion conclusion={content.compliance_conclusion} />}
      {Object.keys(summary).length > 0 && (
        <>
          <Typography.Title level={5}>测试汇总</Typography.Title>
          {summary.confidence_note && (
            <Alert
              type={summary.confidence_note.startsWith('样本量') ? 'warning' : 'info'}
              showIcon
              style={{ marginBottom: 12 }}
              message={`统计置信度：${summary.confidence_note}`}
            />
          )}
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="用例总数">{summary.total ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="通过数">{summary.passed ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="失败数">{summary.failed ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="通过率">{summary.pass_rate != null ? `${Math.round(summary.pass_rate * 100)}%` : '-'}</Descriptions.Item>
          </Descriptions>
        </>
      )}
      {/* ES10-P-01/P-02：样本量与来源（空则整块不渲染） */}
      {(report.fact_source?.name || report.project_version?.version_no) && (
        <Card size="small" title="样本量与来源" style={{ marginTop: 16 }}>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="样本量">{report.summary?.total ?? '-'} 题</Descriptions.Item>
            {report.fact_source?.name && (
              <Descriptions.Item label="事实基准">{report.fact_source.name}</Descriptions.Item>
            )}
            {report.project_version?.version_no && (
              <Descriptions.Item label="项目版本">基于 {report.project_version.version_no}</Descriptions.Item>
            )}
          </Descriptions>
        </Card>
      )}
      {/* P1-15：六维度统计（功能/UI/性能/安全/数据流/兼容性）+ 性能指标 + 安全扫描结果 */}
      {summary.dimension_stats && Object.keys(summary.dimension_stats).length > 0 && (
        <>
          <Typography.Title level={5}>全维度测试统计</Typography.Title>
          <Row gutter={12} style={{ marginBottom: 12 }}>
            <Col xs={24} md={12}>
              <ChartBox title="维度通过率（%）">
                <ReactECharts
                  notMerge lazyUpdate
                  option={buildBarOption(Object.entries(summary.dimension_stats).map(([dim, b]) => ({
                    name: dim, value: b.pass_rate != null ? Math.round(b.pass_rate * 100) : 0,
                  })))}
                />
              </ChartBox>
            </Col>
            <Col xs={24} md={12}>
              <ChartBox title="维度用例数分布">
                <ReactECharts
                  notMerge lazyUpdate
                  option={buildPieOption(Object.entries(summary.dimension_stats).map(([dim, b]) => ({
                    name: dim, value: b.total ?? 0,
                  })))}
                />
              </ChartBox>
            </Col>
          </Row>
          <Descriptions column={2} size="small" bordered>
            {Object.entries(summary.dimension_stats).map(([dim, b]) => (
              <Descriptions.Item key={dim} label={dim}>
                {`共 ${b.total ?? 0} 项 / 通过 ${b.passed ?? 0} / 失败 ${b.failed ?? 0} / 跳过 ${b.skipped ?? 0}`}
                {b.pass_rate != null ? `（通过率 ${Math.round(b.pass_rate * 100)}%）` : ''}
              </Descriptions.Item>
            ))}
          </Descriptions>
          {summary.perf_metrics && Object.keys(summary.perf_metrics).length > 0 && (
            <Descriptions column={3} size="small" bordered title="性能指标">
              {Object.entries(summary.perf_metrics).map(([k, v]) => (
                <Descriptions.Item key={k} label={k}>{typeof v === 'number' ? Math.round(v * 100) / 100 : String(v)}</Descriptions.Item>
              ))}
            </Descriptions>
          )}
          {Array.isArray(summary.security_findings) && summary.security_findings.length > 0 && (
            <Table
              size="small"
              rowKey={(r, i) => `${r.owasp_id}-${i}`}
              pagination={false}
              dataSource={summary.security_findings}
              columns={[
                { title: 'OWASP', dataIndex: 'owasp_id', width: 90 },
                { title: '类型', dataIndex: 'attack_type', width: 110 },
                { title: '用例', dataIndex: 'title', ellipsis: true },
                { title: '状态码', dataIndex: 'status_code', width: 80 },
                {
                  title: '结论', dataIndex: 'result', width: 80,
                  render: (v) => (v === 'PASS'
                    ? <Tag color="success">通过</Tag>
                    : v === 'FAIL' ? <Tag color="error">风险</Tag>
                    : <Tag>{v ?? '-'}</Tag>),
                },
              ]}
            />
          )}
        </>
      )}
      {/* BUG-003：报告四节化 = 功能覆盖/数据流执行/页面·接口明细/BUG清单 四 Tabs（空数据保留 Tab 空态） */}
      {sections !== null && (
        <Card size="small" title="报告分节内容">
          <Tabs
            items={[
              {
                key: 'security',
                label: '安全审计报告',
                // 与 RequirePerm commercialOnly 同一判定：社区版 tab 入口保留，内容见升级引导
                children: isCommunity ? <UpgradeEmpty kind="security_assets" /> : (
                  <CommercialGate kind="security_assets">
                    <PageSuspense><SecurityReportView reportId={report.id} /></PageSuspense>
                  </CommercialGate>
                ),
              },
              ...(vectorItems.length
                ? [{
                    key: 'injection-vectors',
                    label: <span>注入向量审计 <Tag color="volcano" style={{ marginInlineStart: 4 }}>{vectorItems.length}</Tag></span>,
                    children: <InjectionVectorAudit items={vectorItems} />,
                  }]
                : []),
              ...SECTION_TABS.map((t) => ({
                key: t.key,
                label: t.label,
                children: sectionByKey[t.key] ? renderSection(sectionByKey[t.key]) : <Empty description="本节约无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
              })),
            ]}
          />
        </Card>
      )}
      <Typography.Title level={5}>执行明细（用例 / 数据分组 / 断言 三级展开）</Typography.Title>
      <StepDetailsSection stepDetails={stepDetails} report={report} />
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <Button icon={<DownloadOutlined />} onClick={exportJson}>导出 JSON</Button>
        <Button type="primary" icon={<ShareAltOutlined />} onClick={onShareClick}>分享报告</Button>
      </div>
      {/* v2.0 BUG-007：BUG 清单行点击展开缺陷详情抽屉 */}
      <BugDetailDrawer visible={bugDrawerVisible} onClose={() => setBugDrawerVisible(false)} bug={selectedBug} />
    </Space>
  )
}
