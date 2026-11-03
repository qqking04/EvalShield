/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES9-P-10 三栏复核工作台（优化9 §4.2.3）+ judge 校准 Tab
// 顶栏统计：待复核 / 今日已处理 / 一致率（GET /api/review/queue → stats）。
// 三栏：左队列 320px（按类别/低一致分组计数，行选中 3px primary 条）、
//       中判定详情（题目+被测回答超长折叠+规则轨/裁判轨并排对照，分歧行 warning 左侧线）、
//       右操作 280px（维持PASS/改判FAIL/退回 单选 + 备注 + 回流规则 Checkbox + 保存）。
// 键盘流（对齐 ES8-BUG-008 M6 契约）：j/k 移动、1/2/3 选处置、e 备注、s 保存并跳下一条；
//       输入框聚焦仅放行 Esc 失焦 / Ctrl+Enter 保存。
// 提交：POST /api/review/items/{id}/decision {verdict, note, promote_rule}；
//       组内批量：POST /api/review/items/{id}/batch {action, item_ids, verdict}。
import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
  App, Alert, Badge, Button, Card, Checkbox, Col, Empty, Input, Modal,
  Pagination, Radio, Row, Segmented, Select, Space, Spin, Table, Tabs,
  Tag, Tooltip, Typography,
} from 'antd'
import {
  AuditOutlined, CheckCircleOutlined, InboxOutlined,
  ExportOutlined, ReloadOutlined, SaveOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import http from '../../api/http'
import { getRunWorkspace } from '../../api/es11'
import { tokens } from '../../theme/tokens'
import { useAuth } from '../../auth'
import { BRAND, ChartBox } from '../reports/charts'

const STATUS_META = {
  OPEN: { color: 'orange', label: '待复核' },
  ASSIGNED: { color: 'gold', label: '已指派' },
  DONE: { color: 'green', label: '已复核' },
  DISCARDED: { color: 'default', label: '已废弃' },
}
const SOURCE_LABEL = {
  run_item: '运行入队',
  trace: '链路异常',
  defect: '缺陷回流',
}
const VERDICT_COLOR = { PASS: 'green', FAIL: 'red', PARTIAL: 'orange' }
const SET_CATEGORIES = ['EVAL', 'SEC', 'RAG', 'AGENT', 'MULTI_TURN', 'KB']

// 三档处置（数字键 1/2/3 顺序即数组顺序，勿改）
const DISPOSITIONS = [
  { key: 'PASS', label: '维持 PASS', hint: '机判 PASS 成立' },
  { key: 'FAIL', label: '改判 FAIL', hint: '机判漏判/误放，应判不通过' },
  { key: 'RETURN', label: '退回重判', hint: '证据不足，退回重跑判定' },
]
const DISPOSITION_BY_KEY = Object.fromEntries(DISPOSITIONS.map((d, i) => [d.key, { ...d, hotkey: i + 1 }]))

// 低一致分组谓词（与后端入队规则 P0 对齐：judge_agreement=false 或 priority=P0）
function isLowAgreement(r) {
  return r.priority === 'P0' || r.context?.judge_agreement === false
}

function fmtTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString('zh-CN', { hour12: false })
}

// ES11 P10：左栏等待时长（小时，向下取整；无时间戳显示 "-"）
function waitHours(iso) {
  if (!iso) return '-'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '-'
  return Math.max(0, Math.floor((Date.now() - t) / 3600000))
}

// ---------------------------------------------------------------- 校准 Tab ----

const MATRIX_LABELS = ['PASS', 'FAIL', 'PARTIAL']

function buildKappaOption(rows, threshold) {
  return {
    backgroundColor: 'transparent',
    grid: { left: 44, right: 12, top: 34, bottom: 30 },
    tooltip: { trigger: 'axis', backgroundColor: '#1a2130', borderColor: '#1f2833', textStyle: { color: '#e6ebf0' } },
    legend: { top: 2, textStyle: { color: '#8b97a7', fontSize: 11 } },
    xAxis: {
      type: 'category', data: rows.map((w) => w.week),
      axisLine: { lineStyle: { color: '#2f3a4a' } }, axisLabel: { color: '#8b97a7', fontSize: 10 },
    },
    yAxis: {
      type: 'value', min: -1, max: 1,
      axisLabel: { color: '#8b97a7' }, splitLine: { lineStyle: { color: '#1f2833', type: 'dashed' } },
    },
    series: [
      {
        name: "Cohen's Kappa", type: 'line', smooth: true,
        data: rows.map((w) => w.kappa),
        lineStyle: { color: BRAND, width: 2 }, itemStyle: { color: BRAND },
        areaStyle: { color: `${BRAND}22` }, symbol: 'circle', symbolSize: 5,
        markLine: threshold != null ? {
          silent: true, symbol: 'none',
          lineStyle: { color: tokens.danger, type: 'dashed' },
          label: { color: tokens.danger, fontSize: 10, formatter: `预警线 ${threshold}` },
          data: [{ yAxis: threshold }],
        } : undefined,
      },
      {
        name: '一致率', type: 'line', smooth: true,
        data: rows.map((w) => w.agreement),
        lineStyle: { color: tokens.warning, width: 1.5 }, itemStyle: { color: tokens.warning },
        symbol: 'circle', symbolSize: 4,
      },
    ],
  }
}

function MatrixCard({ week }) {
  if (!week) return null
  const rows = MATRIX_LABELS.map((auto) => ({
    auto,
    ...(week.matrix?.[auto] || { PASS: 0, FAIL: 0, PARTIAL: 0 }),
  }))
  return (
    <Card size="small" title={`混淆矩阵 · ${week.week}（机判 → 人判，样本 ${week.n}）`}>
      <Table
        size="small"
        rowKey="auto"
        pagination={false}
        dataSource={rows}
        columns={[
          {
            title: '机判 \\ 人判', dataIndex: 'auto', width: 110,
            render: (v) => <Tag color={VERDICT_COLOR[v]}>{v}</Tag>,
          },
          ...MATRIX_LABELS.map((human) => ({
            title: <Tag color={VERDICT_COLOR[human]}>{human}</Tag>,
            dataIndex: human,
            render: (v, r) => (
              <span style={{
                color: human === r.auto ? tokens.success : v ? tokens.danger : tokens.text3,
                fontWeight: human === r.auto ? 600 : 400,
              }}>{v ?? 0}</span>
            ),
          })),
        ]}
      />
    </Card>
  )
}

function CalibrationPanel() {
  const [weeksOpt, setWeeksOpt] = useState(12)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [pickWeek, setPickWeek] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    http
      .get('/review/calibration', { params: { weeks: weeksOpt } })
      .then((d) => {
        setData(d)
        const ws = d?.weeks || []
        setPickWeek(ws.length ? ws[ws.length - 1].week : null)
      })
      .catch((e) => console.warn('[Review] calibration fail', e?.message || e))
      .finally(() => setLoading(false))
  }, [weeksOpt])

  useEffect(() => { load() }, [load])

  if (loading && !data) return <Spin style={{ display: 'block', margin: '48px auto' }} />
  if (!data) return <Empty description="校准数据不可用" image={Empty.PRESENTED_IMAGE_SIMPLE} />

  const overall = data.overall || {}
  const weekRows = data.weeks || []
  const shown = weekRows.find((w) => w.week === pickWeek) || weekRows[weekRows.length - 1]
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {data.warning && (
        <Alert type="warning" showIcon message="judge 校准预警" description={data.warning} />
      )}
      <Row gutter={12}>
        <Col span={6}>
          <Card size="small">
            <Typography.Text type="secondary">已复核样本（DONE）</Typography.Text>
            <div style={{ fontSize: 26, fontFamily: 'JetBrains Mono, Consolas, monospace', color: tokens.text1 }}>{overall.n ?? 0}</div>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Typography.Text type="secondary">人机一致率</Typography.Text>
            <div style={{ fontSize: 26, fontFamily: 'JetBrains Mono, Consolas, monospace', color: tokens.primary }}>
              {overall.agreement != null ? `${Math.round(overall.agreement * 1000) / 10}%` : '-'}
            </div>
          </Card>
        </Col>
        <Col span={6}>
          <Tooltip title="Cohen's Kappa：剔除随机一致后的机判-人判 agreement，>0.6 判为校准健康；样本 < 10 不发布">
            <Typography.Text type="secondary">整体 Kappa</Typography.Text>
          </Tooltip>
          <div style={{
            fontSize: overall.sufficient === false ? 20 : 26,
            fontFamily: 'JetBrains Mono, Consolas, monospace',
            color: overall.sufficient === false
              ? tokens.text3
              : overall.kappa != null && overall.kappa < (data.threshold ?? 0.6) ? tokens.danger : tokens.success,
          }}>{overall.sufficient === false ? '样本不足' : (overall.kappa != null ? overall.kappa : '-')}</div>
          {overall.sufficient === false && (
            <div style={{ fontSize: 11, color: tokens.text3 }}>
              校准样本 {overall.n ?? 0} 个，需 ≥{data.min_sample ?? 10} 个方可评估一致性
            </div>
          )}
        </Col>
        <Col span={6}>
          <Card size="small">
            <Typography.Text type="secondary">口径外剔除</Typography.Text>
            <div style={{ fontSize: 26, fontFamily: 'JetBrains Mono, Consolas, monospace', color: tokens.text3 }}>
              {data.skipped_unknown_verdicts ?? 0}
            </div>
            <div style={{ fontSize: 11, color: tokens.text3 }}>判定值无法归一三分类的样本</div>
          </Card>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={14}>
          <ChartBox
            title="周度校准趋势（ISO 周）"
            icon={<AuditOutlined />}
            children={(
              <ReactECharts option={buildKappaOption(weekRows, data.threshold)} notMerge style={{ height: '100%' }} />
            )}
          />
        </Col>
        <Col span={10}>
          <Card
            size="small"
            styles={{ body: { padding: 8 } }}
            title={<span style={{ borderLeft: `3px solid ${BRAND}`, paddingLeft: 8, fontSize: 13 }}>范围 / 周选择</span>}
          >
            <Space direction="vertical" size={10} style={{ width: '100%' }}>
              <Select
                value={weeksOpt}
                onChange={setWeeksOpt}
                style={{ width: 180 }}
                options={[4, 12, 26, 52].map((n) => ({ value: n, label: `最近 ${n} 周` }))}
              />
              <Select
                value={pickWeek}
                onChange={setPickWeek}
                style={{ width: 180 }}
                placeholder="选择周"
                options={weekRows.map((w) => ({
                  value: w.week,
                  label: `${w.week} · n=${w.n} · κ=${w.kappa ?? '-'}`,
                }))}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                周序列按 DONE 复核项实际覆盖的 ISO 周聚合；kappa &lt; {data.threshold ?? 0.6} 触发预警并提示调整评审 prompt。
              </Typography.Text>
            </Space>
          </Card>
        </Col>
      </Row>
      {shown ? <MatrixCard week={shown} /> : <Empty description="尚无 DONE 复核样本，无法生成混淆矩阵" />}
      <JudgeGroupsCard data={data} />
    </Space>
  )
}

// ES11 P10：Judge 治理分组视图（按场景 / 裁判模型 / prompt 哈希三维）
const GROUP_DIMS = [
  { key: 'by_category', label: '按场景' },
  { key: 'by_judge_model', label: '按裁判模型' },
  { key: 'by_prompt_hash', label: '按 Prompt 哈希' },
]
const GROUP_COLUMNS = [
  { title: '分组', dataIndex: 'key', ellipsis: true },
  { title: '样本', dataIndex: 'n', width: 70, render: (v) => <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }}>{v}</span> },
  {
    title: '一致率', dataIndex: 'agreement', width: 90,
    render: (v) => (v == null ? '-' : `${Math.round(v * 1000) / 10}%`),
  },
  {
    title: 'Kappa', dataIndex: 'kappa', width: 120,
    render: (v, r) => (r.sufficient
      ? <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', color: v != null && v < 0.6 ? tokens.danger : tokens.success }}>{v ?? '-'}</span>
      : <Tag color="default">样本不足</Tag>),
  },
  {
    title: 'UNKNOWN 率', dataIndex: 'unknown_rate', width: 100,
    render: (v) => (v == null ? '-' : (
      <span style={{ color: v > 0.1 ? tokens.warning : tokens.text3 }}>
        {`${Math.round(v * 1000) / 10}%`}
      </span>
    )),
  },
]

function JudgeGroupsCard({ data }) {
  const [dim, setDim] = useState('by_category')
  const groups = data?.groups?.[dim] || []
  return (
    <Card
      size="small"
      styles={{ body: { padding: 8 } }}
      title={(
        <span style={{ borderLeft: `3px solid ${BRAND}`, paddingLeft: 8, fontSize: 13 }}>
          Judge 治理分组 · UNKNOWN 总率 {data?.unknown_rate != null ? `${Math.round(data.unknown_rate * 1000) / 10}%` : '-'}
        </span>
      )}
      extra={<Segmented size="small" value={dim} onChange={setDim} options={GROUP_DIMS.map((d) => ({ value: d.key, label: d.label }))} />}
    >
      <Table
        rowKey="key"
        size="small"
        columns={GROUP_COLUMNS}
        dataSource={groups}
        pagination={false}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: <Empty description="尚无 DONE 复核样本，无法生成分组统计" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        分组样本 &lt; {data?.min_sample ?? 10} 时不发布组内 Kappa（显示"样本不足"）；UNKNOWN 率 = 组内机判值无法归一三分类的占比，持续偏高说明裁判输出口径漂移。
      </Typography.Text>
    </Card>
  )
}

// ------------------------------------------------------- 复核台（三栏） ----

const panelCardStyle = {
  background: tokens.bgPanel,
  border: `1px solid ${tokens.border}`,
}
const mono = { fontFamily: 'JetBrains Mono, Consolas, monospace' }

function ReviewBench({ onChanged }) {
  const { message } = App.useApp()
  const { hasPerm } = useAuth()
  const canManage = hasPerm('review:manage')

  const pageSize = 50
  const [status, setStatus] = useState('OPEN')
  const [page, setPage] = useState(1)
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [groups, setGroups] = useState([])
  const [stats, setStats] = useState(null)
  const [activeGroup, setActiveGroup] = useState(null)
  const [loading, setLoading] = useState(false)
  const [currentId, setCurrentId] = useState(null)
  const [verdict, setVerdict] = useState(null)
  const [note, setNote] = useState('')
  const [promoteRule, setPromoteRule] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState([])
  const [packOpen, setPackOpen] = useState(false)
  const [packForm, setPackForm] = useState({ name: '', category: 'EVAL' })
  const noteRef = useRef(null)

  const loadQueue = useCallback(
    (opts = {}) => {
      setLoading(true)
      return http
        .get('/review/queue', { params: { page: opts.page ?? page, page_size: pageSize, status } })
        .then((d) => {
          const items = d?.items || []
          setRows(items)
          setTotal(d?.total ?? items.length)
          // 后端未回 groups 时按本类目/低一致在前端兜底聚合
          if (d?.groups) setGroups(d.groups)
          else {
            const byCat = {}
            items.forEach((r) => {
              const cat = r.context?.category || '未分类'
              byCat[cat] = (byCat[cat] || 0) + 1
            })
            const gs = Object.entries(byCat).map(([key, count]) => ({ key, label: key, count }))
            const low = items.filter(isLowAgreement).length
            if (low) gs.push({ key: '__low_agree', label: '低一致', count: low })
            setGroups(gs)
          }
          setStats(d?.stats || null)
          setCurrentId((prev) =>
            opts.keepCurrent && prev && items.some((it) => it.id === prev)
              ? prev
              : (items[0]?.id ?? null)
          )
          return items
        })
        .catch((e) => { console.warn('[Review] queue fail', e?.message || e); return [] })
        .finally(() => setLoading(false))
    },
    [page, status],
  )

  useEffect(() => { loadQueue({ page: 1 }); setPage(1) }, [status]) // eslint-disable-line
  useEffect(() => { loadQueue() }, [page]) // eslint-disable-line

  const current = rows.find((r) => r.id === currentId) || null

  // 当前分组过滤后的可见列表（键盘 j/k 与队列渲染共用）
  const visibleRows = useMemo(() => {
    if (!activeGroup) return rows
    if (activeGroup === '__low_agree') return rows.filter(isLowAgreement)
    return rows.filter((r) => (r.context?.category || '未分类') === activeGroup)
  }, [rows, activeGroup])

  const resetForm = () => { setVerdict(null); setNote(''); setPromoteRule(false) }

  // 保存处置：POST decision → 提示 → 跳下一条并刷新
  const saveCurrent = useCallback(async (it, v, n, pr) => {
    if (!it) return
    if (!v) { message.warning('请先按 1/2/3 选择处置'); return }
    if (it.status === 'DONE' || it.status === 'DISCARDED') { message.info('该项已是终态'); return }
    setSubmitting(true)
    try {
      await http.post(`/review/items/${it.id}/decision`, {
        verdict: v, note: n || undefined, promote_rule: !!pr,
      })
      message.success(`已保存：${DISPOSITION_BY_KEY[v]?.label || v}`)
      // ES11 P10：保存后提示影响的运行结论与报告门禁（仅运行入队项）
      const rid = it.context?.run_id
      if (rid) {
        getRunWorkspace(rid)
          .then((w) => {
            const g2 = w?.gates?.G2 || {}
            const prog = w?.review_progress || {}
            message.info(
              `运行 ${w?.run?.run_no || '#' + rid}：G2 ${g2.status || '-'}（待复核 ${g2.pending_review ?? prog.pending ?? '-'}），`
              + `结论${w?.run?.concluded ? '已定稿' : '未定稿'}${w?.gates?.G4 === 'BLOCK' ? '，报告交付仍被阻塞' : ''}`,
              6,
            )
          })
          .catch(() => {})
      }
      resetForm()
      const rest = visibleRows.filter((x) => x.id !== it.id)
      const next = rest.find((x) => x.status === 'OPEN') || rest[0]
      if (next && next.id !== it.id) setCurrentId(next.id)
      loadQueue({ keepCurrent: true })
      onChanged?.()
    } catch (e) {
      /* http 拦截器已弹出后端错误信息 */
    } finally {
      setSubmitting(false)
    }
  }, [visibleRows, loadQueue, onChanged, message])

  // 组内批量：对当前分组其余待处理项套用所选处置（缺省维持 PASS）
  const batchApproveGroup = useCallback(() => {
    if (!current || !canManage) return
    const ids = visibleRows
      .filter((x) => x.id !== current.id && x.status !== 'DONE' && x.status !== 'DISCARDED')
      .map((x) => x.id)
    if (!ids.length) { message.info('当前分组没有其余待处理项'); return }
    const v = verdict || 'PASS'
    Modal.confirm({
      title: `批量通过 ${ids.length} 项？`,
      content: `将对当前分组其余 ${ids.length} 项套用「${DISPOSITION_BY_KEY[v]?.label || v}」，事务执行、可审计回溯。`,
      okText: '批量保存',
      onOk: async () => {
        await http.post(`/review/items/${current.id}/batch`, { action: 'approve', item_ids: ids, verdict: v })
        message.success(`已批量保存 ${ids.length} 项`)
        loadQueue({ keepCurrent: true })
        onChanged?.()
      },
    })
  }, [current, visibleRows, verdict, canManage, loadQueue, onChanged, message])

  // 键盘流：j/k 移动、1/2/3 选处置、e 备注、s 保存并跳下一条；输入框聚焦仅放行 Esc / Ctrl+Enter
  useEffect(() => {
    const handler = (ev) => {
      if (!canManage) return
      const tag = ev.target?.tagName
      const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
      if (ev.ctrlKey || ev.metaKey) {
        if (ev.key === 'Enter' && typing) { ev.preventDefault(); saveCurrent(current, verdict, note, promoteRule) }
        return
      }
      if (typing) {
        if (ev.key === 'Escape') ev.target.blur()
        return
      }
      const idx = visibleRows.findIndex((r) => r.id === currentId)
      if (ev.key === 'j') {
        ev.preventDefault()
        if (idx >= 0 && idx < visibleRows.length - 1) { setCurrentId(visibleRows[idx + 1].id); resetForm() }
        else if (idx < 0 && visibleRows.length) { setCurrentId(visibleRows[0].id) }
      } else if (ev.key === 'k') {
        ev.preventDefault()
        if (idx > 0) { setCurrentId(visibleRows[idx - 1].id); resetForm() }
      } else if (['1', '2', '3'].includes(ev.key)) {
        ev.preventDefault()
        setVerdict(DISPOSITIONS[Number(ev.key) - 1].key)
      } else if (ev.key === 'e') {
        ev.preventDefault()
        noteRef.current?.focus?.()
      } else if (ev.key === 's') {
        ev.preventDefault()
        saveCurrent(current, verdict, note, promoteRule)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [visibleRows, currentId, current, verdict, note, promoteRule, canManage, saveCurrent])

  // 切换选中项时重置处置表单
  useEffect(() => {
    setVerdict(null)
    setNote(current?.context?.user_note || '')
    setPromoteRule(false)
  }, [currentId]) // eslint-disable-line

  const packageSelected = useCallback(async () => {
    if (!packForm.name.trim()) { message.warning('请填写评测集名称'); return }
    setSubmitting(true)
    try {
      const d = await http.post('/review/package-as-evalset', {
        item_ids: selectedKeys, name: packForm.name.trim(), category: packForm.category,
      })
      message.success(`已创建评测集 ${d?.eval_set_no}（${d?.item_count} 条，来源 FROM_REVIEW）`)
      setPackOpen(false)
      setSelectedKeys([])
      setPackForm({ name: '', category: 'EVAL' })
      loadQueue({ keepCurrent: true })
    } catch (e) { /* 拦截器已提示（ES-M6-0009/0010） */ }
    finally { setSubmitting(false) }
  }, [packForm, selectedKeys, loadQueue, message])

  // ------------------------------------------------------------ 判定详情列 ----
  const ctx = current?.context || {}
  const ruleVerdict = ctx.rule_verdict || 'UNKNOWN'
  const judgeVerdict = current?.auto_verdict || '-'
  const tracksDiffer = !!(current && ctx.rule_verdict && ctx.rule_verdict !== judgeVerdict)

  const statItem = (label, value, color) => (
    <span style={{ marginRight: 24 }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>{label}</Typography.Text>
      <span style={{ ...mono, fontSize: 20, marginLeft: 8, color: color || tokens.text1 }}>{value}</span>
    </span>
  )

  return (
    <div data-testid="review-workbench">
      {/* 顶栏统计 + 状态切换 */}
      <Card size="small" style={{ ...panelCardStyle, marginBottom: 12 }} styles={{ body: { padding: '8px 12px' } }}>
        <Space size={12} wrap style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space size={0} wrap>
            {statItem('待复核', stats?.pending ?? (status === 'OPEN' ? total : stats?.open ?? '-') , tokens.warning)}
            {statItem('今日已处理', stats?.processed_today ?? '-', tokens.success)}
            {statItem('一致率', stats?.agreement != null ? `${Math.round(stats.agreement * 1000) / 10}%` : '-', tokens.primary)}
          </Space>
          <Space size={8}>
            <Segmented
              size="small"
              value={status}
              onChange={(v) => { setStatus(v); setActiveGroup(null); setSelectedKeys([]) }}
              options={[
                { value: 'OPEN', label: '待复核' },
                { value: 'DONE', label: '已复核' },
              ]}
            />
            {canManage && status === 'DONE' && (
              <Badge count={selectedKeys.length} size="small">
                <Button size="small" icon={<ExportOutlined />} disabled={!selectedKeys.length} onClick={() => setPackOpen(true)}>打包为评测集</Button>
              </Badge>
            )}
            <Tooltip title="刷新"><Button size="small" type="text" icon={<ReloadOutlined spin={loading} />} onClick={() => loadQueue({ keepCurrent: true })} /></Tooltip>
          </Space>
        </Space>
      </Card>

      {/* 三栏 */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {/* 左：队列 320px */}
        <Card
          size="small"
          title={<Space size={6}><InboxOutlined />复核队列</Space>}
          style={{ ...panelCardStyle, width: 320, flex: '0 0 320px' }}
          styles={{ body: { padding: 8, maxHeight: 'calc(100vh - 280px)', overflowY: 'auto' } }}
        >
          {groups.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              {groups.map((g) => (
                <div
                  key={g.key}
                  data-testid={`queue-group-${g.key}`}
                  onClick={() => setActiveGroup(activeGroup === g.key ? null : g.key)}
                  style={{
                    display: 'flex', justifyContent: 'space-between', padding: '4px 8px', cursor: 'pointer',
                    borderRadius: 4, fontSize: 12,
                    color: activeGroup === g.key ? tokens.primary : tokens.text2,
                    background: activeGroup === g.key ? tokens.primaryDim : 'transparent',
                  }}
                >
                  <span>{'▸ '}{g.label || g.key}</span>
                  <span style={mono}>{g.count ?? 0}</span>
                </div>
              ))}
            </div>
          )}
          {visibleRows.length === 0 && !loading && (
            <Empty description="队列为空" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
          {visibleRows.map((r) => (
            <div
              key={r.id}
              data-testid={`queue-row-${r.id}`}
              onClick={() => setCurrentId(r.id)}
              style={{
                padding: '6px 8px', marginBottom: 4, cursor: 'pointer', borderRadius: 4,
                borderLeft: `3px solid ${r.id === currentId ? tokens.primary : 'transparent'}`,
                background: r.id === currentId ? tokens.primaryDim : tokens.bgHover,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                {status === 'DONE' && canManage && (
                  <Checkbox
                    checked={selectedKeys.includes(r.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => setSelectedKeys((ks) => (e.target.checked ? [...ks, r.id] : ks.filter((k) => k !== r.id)))}
                  />
                )}
                <div style={{ fontSize: 12, color: tokens.text1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}>
                  {r.context?.category ? <Tag style={{ marginRight: 4 }} color="cyan">{r.context.category}</Tag> : null}
                  #{r.id} {r.context?.prompt ? r.context.prompt.slice(0, 20) : (r.context?.no || '')}
                </div>
              </div>
              <div style={{ fontSize: 11, color: tokens.text3, marginTop: 2, display: 'flex', gap: 6, alignItems: 'center' }}>
                <Tag color={STATUS_META[r.status]?.color} style={{ marginInlineEnd: 0 }}>{STATUS_META[r.status]?.label || r.status}</Tag>
                {r.priority ? <Tag color={r.priority === 'P0' ? 'red' : r.priority === 'P1' ? 'orange' : 'default'} style={{ marginInlineEnd: 0 }}>{r.priority}</Tag> : null}
                {r.auto_verdict ? <Tag color={VERDICT_COLOR[r.auto_verdict] || 'blue'} style={{ marginInlineEnd: 0 }}>{r.auto_verdict}</Tag> : null}
                {isLowAgreement(r) ? <Tooltip title="规则轨/裁判轨低一致（P0）"><span style={{ color: tokens.warning }}>低一致</span></Tooltip> : null}
                {r.status === 'OPEN' && r.source === 'run_item' ? <Tooltip title="未复核项阻塞所属运行的 G2 门禁，进而阻塞交付"><span style={{ color: tokens.danger || '#f85149' }}>阻塞交付</span></Tooltip> : null}
                <span style={{ fontSize: 11 }}>等待 {waitHours(r.created_at)}h</span>
                <span style={{ marginLeft: 'auto' }}>{SOURCE_LABEL[r.source] || r.source}</span>
              </div>
            </div>
          ))}
          {total > pageSize && (
            <Pagination
              size="small" simple current={page} pageSize={pageSize} total={total}
              onChange={(p) => setPage(p)}
              style={{ marginTop: 8, textAlign: 'center' }}
            />
          )}
        </Card>

        {/* 中：判定详情 */}
        <Card
          size="small"
          title={<Space size={6}><AuditOutlined />判定详情{current ? ` · 项 #${current.id}` : ''}</Space>}
          style={{ ...panelCardStyle, flex: 1, minWidth: 0 }}
          styles={{ body: { padding: 12, maxHeight: 'calc(100vh - 280px)', overflowY: 'auto' } }}
        >
          {!current ? (
            <Empty description="队列为空或请从左侧选择复核项" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>题目</Typography.Text>
                <div style={{ marginTop: 4 }}>
                  {ctx.split ? <Tag color={ctx.split === 'REFUSE' ? 'red' : 'green'} style={{ marginRight: 6 }}>{ctx.split}</Tag> : null}
                  <Typography.Paragraph style={{ ...mono, margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: tokens.text1 }}>
                    {ctx.prompt || '-'}
                  </Typography.Paragraph>
                </div>
              </div>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>被测回答</Typography.Text>
                <Typography.Paragraph
                  style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: tokens.text2 }}
                  ellipsis={{ rows: 6, expandable: true, symbol: '展开' }}
                >
                  {ctx.response || ctx.answer || '-'}
                </Typography.Paragraph>
              </div>
              {/* 规则轨 / 裁判轨并排对照：分歧行 warning 左侧线 */}
              <Row gutter={12}>
                <Col span={12}>
                  <div style={{
                    padding: '8px 10px', borderRadius: 4, background: tokens.bgHover,
                    borderLeft: `3px solid ${tracksDiffer ? tokens.warning : tokens.border}`,
                  }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>规则轨</Typography.Text>
                    <div style={{ marginTop: 4 }}>
                      <Tag color={ruleVerdict === 'UNKNOWN' ? 'default' : (VERDICT_COLOR[ruleVerdict] || 'blue')}>{ruleVerdict}</Tag>
                      {ctx.rule_id ? <span style={{ ...mono, fontSize: 11, color: tokens.text3 }}>rule#{ctx.rule_id}</span> : null}
                    </div>
                  </div>
                </Col>
                <Col span={12}>
                  <div style={{
                    padding: '8px 10px', borderRadius: 4, background: tokens.bgHover,
                    borderLeft: `3px solid ${tracksDiffer ? tokens.warning : tokens.border}`,
                  }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>裁判轨</Typography.Text>
                    <div style={{ marginTop: 4 }}>
                      <Tag color={VERDICT_COLOR[judgeVerdict] || 'blue'}>{judgeVerdict}</Tag>
                      {current.auto_confidence != null ? (
                        <span style={{ ...mono, fontSize: 11, color: tokens.text3 }}>置信 {Math.round(current.auto_confidence * 100)}%</span>
                      ) : null}
                    </div>
                  </div>
                </Col>
              </Row>
              {tracksDiffer && (
                <div style={{ color: tokens.warning, fontSize: 12 }}>
                  规则轨与裁判轨判定分歧（{ruleVerdict} vs {judgeVerdict}）——优先处置
                </div>
              )}
              <div style={{ fontSize: 11, color: tokens.text3, ...mono }}>
                prompt{ctx.judge_prompt_hash ? `#${String(ctx.judge_prompt_hash).slice(0, 6)}` : ''}
                {ctx.judge_model || current.judge_model ? ` · ${ctx.judge_model || current.judge_model}` : ''}
                {' '}· {SOURCE_LABEL[current.source] || current.source} · {ctx.run_no || `run#${ctx.run_id ?? '-'}`}
                {' '}· 更新于 {fmtTime(current.updated_at)}
              </div>
              {current.status === 'DONE' && (
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>人判结论：</Typography.Text>
                  <Tag color={VERDICT_COLOR[current.human_verdict] || 'blue'}>{current.human_verdict}</Tag>
                  <Typography.Text style={{ fontSize: 12, color: tokens.text2 }}>{current.human_note || '（无备注）'}</Typography.Text>
                </div>
              )}
            </Space>
          )}
        </Card>

        {/* 右：操作 280px */}
        <Card
          size="small"
          title="处置"
          style={{ ...panelCardStyle, width: 280, flex: '0 0 280px' }}
          styles={{ body: { padding: 12 } }}
        >
          {!current || !canManage || current.status === 'DONE' || current.status === 'DISCARDED' ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {!current ? '选择复核项后可执行处置。' : '该项已是终态，无可操作处置。'}
            </Typography.Text>
          ) : (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Radio.Group
                value={verdict}
                onChange={(e) => setVerdict(e.target.value)}
                style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
              >
                {DISPOSITIONS.map((d) => (
                  <Radio key={d.key} value={d.key} data-testid={`disposition-${d.key}`}>
                    <Tooltip title={`${d.hint}（按 ${d.hotkey}）`}>
                      <span style={{ color: d.key === 'PASS' ? tokens.success : d.key === 'FAIL' ? tokens.danger : tokens.warning }}>
                        {d.label}
                      </span>
                      <span style={{ ...mono, fontSize: 11, color: tokens.text3, marginLeft: 6 }}>[{d.hotkey}]</span>
                    </Tooltip>
                  </Radio>
                ))}
              </Radio.Group>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>备注（按 e 聚焦）</Typography.Text>
                <Input.TextArea
                  ref={noteRef}
                  rows={3}
                  maxLength={2000}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="记录判定依据，供评审 prompt 校准回溯"
                />
              </div>
              <Checkbox checked={promoteRule} onChange={(e) => setPromoteRule(e.target.checked)}>
                <span style={{ fontSize: 12 }}>回流规则（关键词写入拒答规则库，同分类下一条走规则轨）</span>
              </Checkbox>
              <Button
                block type="primary" icon={<SaveOutlined />} loading={submitting}
                disabled={!verdict}
                onClick={() => saveCurrent(current, verdict, note, promoteRule)}
              >
                保存并跳下一条（s）
              </Button>
              <Button block size="small" onClick={batchApproveGroup}>
                批量通过组内其余项
              </Button>
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                键盘流：j / k 移动 · 1/2/3 选处置 · e 备注 · s 保存 · Ctrl+Enter 备注框内保存
              </Typography.Text>
            </Space>
          )}
        </Card>
      </div>

      {/* 打包建集 Modal */}
      <Modal
        title={`打包为评测集（${selectedKeys.length} 项，仅 DONE 生效）`}
        open={packOpen}
        onCancel={() => setPackOpen(false)}
        onOk={packageSelected}
        okText="创建评测集"
        confirmLoading={submitting}
        destroyOnClose
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Input
            placeholder="评测集名称（如：复核回流集 2026-10）"
            maxLength={128}
            value={packForm.name}
            onChange={(e) => setPackForm((f) => ({ ...f, name: e.target.value }))}
          />
          <Select
            style={{ width: '100%' }}
            value={packForm.category}
            onChange={(v) => setPackForm((f) => ({ ...f, category: v }))}
            options={SET_CATEGORIES.map((c) => ({ value: c, label: c }))}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            人判结论将作为期望判定（expected）写入；来源标记 FROM_REVIEW，非 DONE 项自动跳过。
          </Typography.Text>
        </Space>
      </Modal>
    </div>
  )
}

// ------------------------------------------------------------------ 页面 ----

export default function ReviewQueuePage() {
  const [tick, setTick] = useState(0)
  return (
    <Tabs
      defaultActiveKey="bench"
      items={[
        { key: 'bench', label: <span><CheckCircleOutlined /> 复核台</span>, children: <ReviewBench onChanged={() => setTick((t) => t + 1)} /> },
        { key: 'calibration', label: <span><AuditOutlined /> judge 校准</span>, children: <CalibrationPanel /> },
      ]}
    />
  )
}
