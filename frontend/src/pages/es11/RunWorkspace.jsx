/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES11 统一运行详情（深链 /eval/runs/:id，方案 §3.2/§5）
// 头部固定区：活动/运行编号/门禁徽章一行/负责人/下一动作 + 四动作。
// Tabs：概览 / 题级证据（三栏，方案 P3）/ Judge 与复核 / 缺陷与复测 / 回归差异。
// 硬约束：历史运行无 evidence_payload 不伪造；基线不可比时禁止直接归因模型版本（P6）；
// 所有 ID 走可搜索 Select，禁手填。
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  App, Alert, Button, Card, Collapse, Descriptions, Empty, Form, Input, Modal, Progress,
  Select, Space, Spin, Table, Tabs, Tag, Tooltip, Typography,
} from 'antd'
import {
  BugOutlined, FileTextOutlined, FlagOutlined, ReloadOutlined,
  RedoOutlined, RightOutlined,
} from '@ant-design/icons'
import * as es11 from '../../api/es11'
import http from '../../api/http'
import { fmtTime } from '../../utils'
import { ES, GateBadge, EvidencePanel, Mono } from './gate'

const PURPOSE_LABEL = { STANDARD: '标准评测', REGRESSION: '回归', RETEST: '复测', BASELINE: '基线', MONITOR: '监控' }
const RUN_STATUS_LABEL = {
  PENDING: '等待中', QUEUED: '排队中', RUNNING: '运行中',
  SUCCESS: '成功', PASSED: '通过', FAILED: '失败', ERROR: '错误', CANCELLED: '已取消',
}
const VERDICT_META = {
  PASS: { color: 'green', label: '通过' },
  FAIL: { color: 'red', label: '失败' },
  PARTIAL: { color: 'gold', label: '部分通过' },
  UNKNOWN: { color: 'default', label: '未知' },
}
const FAIL_CLASS_LABEL = { CONFIG: '配置', INFRA: '基础设施', QUALITY: '质量' }
const SEVERITY_OPTIONS = ['P0', 'P1', 'P2', 'P3', 'P4'].map((v) => ({ value: v, label: v }))
const PRIORITY_OPTIONS = [
  { value: 'HIGH', label: '高' }, { value: 'MEDIUM', label: '中' }, { value: 'LOW', label: '低' },
]
const CAT_ORDER = ['NEW_FAIL', 'FIXED', 'STILL_FAIL', 'STILL_PASS', 'NEW_SAMPLE', 'REMOVED_SAMPLE', 'NOT_COMPARABLE']
const CAT_LABEL = {
  NEW_FAIL: '新增失败', FIXED: '已修复', STILL_FAIL: '仍然失败', STILL_PASS: '持续通过',
  NEW_SAMPLE: '新增样本', REMOVED_SAMPLE: '移除样本', NOT_COMPARABLE: '不可比',
}

function verdictTag(v) {
  if (!v) return <Typography.Text type="secondary">-</Typography.Text>
  const m = VERDICT_META[String(v).toUpperCase()] || { color: 'default', label: String(v) }
  return <Tag color={m.color}>{m.label}</Tag>
}

// 对象/字符串统一转可读文本（证据条目结构不固定，防御式渲染）
function toText(v) {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try { return JSON.stringify(v, null, 1) } catch { return String(v) }
}

/** 长文本折叠：默认 3 行，点「展开」看全。 */
function ClipText({ text, rows = 3, style, mono }) {
  if (!text) return <Typography.Text style={{ color: ES.sub, ...style }}>（空）</Typography.Text>
  return (
    <Typography.Paragraph
      style={{ marginBottom: 4, color: ES.ink, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
        fontFamily: mono ? ES.mono : undefined, ...style }}
      ellipsis={{ rows, expandable: true, symbol: '展开' }}
    >
      {text}
    </Typography.Paragraph>
  )
}

/** G1 三类失败计数 → 门禁状态：基建/质量>0 阻塞；仅配置>0 关注；全零通过。 */
function g1Status(mix = {}) {
  if ((mix.infra || 0) > 0 || (mix.quality || 0) > 0) return 'BLOCK'
  if ((mix.config || 0) > 0) return 'WARN'
  return 'PASS'
}

function GateRow({ gates = {} }) {
  const g0 = gates.G0 === 'BLOCKED' ? 'BLOCK' : gates.G0 || 'UNKNOWN'
  const mix = gates.G1 || {}
  const g2 = gates.G2 || {}
  const g3n = gates.G3?.open_p0p1 ?? 0
  const g4 = gates.G4
  return (
    <Space size={18} wrap style={{ marginTop: 10 }}>
      <GateBadge status={g0} text={`G0 准备度·${gates.G0 === 'BLOCKED' ? '阻塞' : gates.G0 === 'PASS' ? '通过' : '未知'}`}
        reason={gates.G0 === 'UNKNOWN' ? '存量运行未固化准备度快照，显示为未知' : undefined} />
      <GateBadge status={g1Status(mix)} text={`G1 失败口径·配置${mix.config || 0}/基建${mix.infra || 0}/质量${mix.quality || 0}`}
        reason="基建/质量类失败阻塞结论；配置类失败需修正后重跑" />
      <GateBadge status={g2.status === 'PASS' ? 'PASS' : 'BLOCK'} text={`G2 复核·待${g2.pending_review ?? '-'}`}
        reason={g2.status !== 'PASS' ? '强制复核未全部完成，结论未冻结' : undefined} />
      <GateBadge status={g3n > 0 ? 'BLOCK' : 'PASS'} text={`G3 缺陷·未闭环P0/P1 ${g3n}`} />
      <GateBadge status={g4 === 'PASS' ? 'PASS' : g4 === 'NO_REPORT' ? 'WARN' : 'BLOCK'}
        text={`G4 交付·${g4 === 'PASS' ? '可交付' : g4 === 'NO_REPORT' ? '未出报告' : '阻塞'}`} />
    </Space>
  )
}

function nextAction(ws) {
  const g = ws?.gates || {}
  const mix = g.G1 || {}
  if (g.G0 === 'BLOCKED') return 'G0 未过：先修复准备度检查项，再执行评测'
  if ((mix.infra || 0) > 0 || (mix.quality || 0) > 0) return 'G1 存在基建/质量失败：在「题级证据」筛选定位后重新执行'
  if ((g.G2?.pending_review ?? 0) > 0) return `G2 待复核 ${g.G2.pending_review} 条：前往复核队列完成人工结论`
  if ((g.G3?.open_p0p1 ?? 0) > 0) return `G3 有 ${g.G3.open_p0p1} 个 P0/P1 缺陷未闭环：在「缺陷与复测」推进整改`
  if (g.G4 === 'NO_REPORT') return 'G4 未出报告：生成报告后方可交付'
  if (g.G4 === 'BLOCKED') return 'G4 交付被阻塞：检查报告准出条件'
  return '结论可交付：可建立基线用于后续回归对比'
}

/**
 * 优化12 §10.4：概览页「维度覆盖」折叠面板——展开时才拉 dimension-coverage，
 * 旧口径 run（coverage:null）灰态说明；深链到合规对标页看完整矩阵。
 */
function CoveragePanel({ runId, onOpenBenchmark }) {
  const [open, setOpen] = useState(false)
  const [cov, setCov] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const onCollapse = (keys) => {
    const willOpen = keys.length > 0
    setOpen(willOpen)
    if (willOpen && !cov && !loading && !err) {
      setLoading(true)
      es11.getRunDimensionCoverage(runId)
        .then((d) => setCov(d))
        .catch((e) => setErr(e?.message || '覆盖矩阵加载失败'))
        .finally(() => setLoading(false))
    }
  }

  const summary = (
    <Space size={10} wrap>
      <GateBadge status={cov?.coverage?.overall?.official_pass ? 'PASS' : cov?.coverage ? 'WARN' : 'UNKNOWN'} text="GBT45654 维度覆盖" />
      {cov?.coverage && (
        <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>
          {(cov.coverage.dimensions || []).map((d) => `${d.dimension_name} ${d.dimension_rate != null ? `${Math.round(d.dimension_rate * 100)}%` : '—'}`).join(' · ')}
        </Typography.Text>
      )}
    </Space>
  )

  return (
    <Collapse size="small" activeKey={open ? ['cov'] : []} onChange={onCollapse}
      items={[{
        key: 'cov',
        label: summary,
        children: loading ? <Spin size="small" /> : err ? (
          <Alert type="error" showIcon message="覆盖矩阵加载失败" description={err} />
        ) : cov && cov.coverage == null ? (
          <Alert type="warning" showIcon
            message="该运行早于现行标准口径，不产维度覆盖结论"
            description={`运行标准版本「${cov.standards_ver || '未知'}」非 GBT45654 口径，需以现行口径重跑。`} />
        ) : cov?.coverage ? (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>{cov.coverage.disclaimer}</Typography.Text>
            {(cov.coverage.overall?.block_items || []).slice(0, 5).map((b, i) => (
              <div key={i} style={{ color: ES.BLOCK, fontSize: 12 }}><BugOutlined /> {typeof b === 'string' ? b : (b.reason || b.sub_code || JSON.stringify(b))}</div>
            ))}
            {(cov.coverage.overall?.warn_items || []).slice(0, 5).map((w, i) => (
              <div key={`w${i}`} style={{ color: ES.WARN, fontSize: 12 }}><FlagOutlined /> {typeof w === 'string' ? w : (w.reason || JSON.stringify(w))}</div>
            ))}
            <Button size="small" onClick={onOpenBenchmark}>查看完整覆盖矩阵 <RightOutlined /></Button>
          </Space>
        ) : <Typography.Text type="secondary">暂无覆盖数据</Typography.Text>,
      }]} />
  )
}

export default function RunWorkspace() {
  const { id } = useParams()
  const runId = Number(id)
  const navigate = useNavigate()
  const { message, modal } = App.useApp()

  const [searchParams] = useSearchParams() // ?tab=rag 深链（方案 P7）
  const [ws, setWs] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [tab, setTab] = useState(searchParams.get('tab') || 'overview')
  const [baselining, setBaselining] = useState(false)

  // 创建缺陷弹窗（头部「创建缺陷」与证据栏「转缺陷」共用）
  const [defectOpen, setDefectOpen] = useState(false)
  const [defectPrefill, setDefectPrefill] = useState(null)
  const [defectSaving, setDefectSaving] = useState(false)
  const [projects, setProjects] = useState([])
  const [dform] = Form.useForm()

  const load = useCallback(() => {
    setLoading(true)
    es11.getRunWorkspace(runId)
      .then((d) => { setWs(d); setLoadErr('') })
      .catch((e) => setLoadErr(e?.message || '工作区加载失败'))
      .finally(() => setLoading(false))
  }, [runId])

  useEffect(() => { load() }, [load])

  // 优化12 BUG-007：题库评测逐题执行转后台，非终态时静默轮询刷新
  // （终态自动停止；组件卸载清理定时器；轮询失败静默，下轮重试）
  const runStatus = ws?.run?.status
  useEffect(() => {
    if (runStatus !== 'PENDING' && runStatus !== 'RUNNING') return undefined
    const timer = setInterval(() => {
      es11.getRunWorkspace(runId)
        .then((d) => { if (d) { setWs(d); setLoadErr('') } })
        .catch(() => {})
    }, 3000)
    return () => clearInterval(timer)
  }, [runId, runStatus])

  useEffect(() => {
    http.get('/projects', { params: { page: 1, page_size: 200 } })
      .then((d) => setProjects((d?.items || []).map((p) => ({ value: p.id, label: p.name }))))
      .catch(() => {})
  }, [])

  const run = ws?.run
  const snapshot = ws?.snapshot || {}

  const openDefectModal = (prefill) => {
    setDefectPrefill(prefill || null)
    dform.resetFields()
    if (prefill) dform.setFieldsValue(prefill)
    setDefectOpen(true)
  }

  const createDefect = async () => {
    const v = await dform.validateFields()
    setDefectSaving(true)
    try {
      // ES11 E2E 修复：题级转缺陷携带 RUN_ITEM 血缘（复测自动绑题、关闭六条件依赖）
      const origin = defectPrefill?.__origin_item_id
        ? { origin_type: 'RUN_ITEM', origin_id: defectPrefill.__origin_item_id }
        : {}
      const { __origin_item_id, ...fields } = v
      const d = await http.post('/defects', {
        ...fields, ...origin, report_id: ws?.report?.id || undefined,
      })
      message.success('缺陷已创建（NEW），进入闭环时间线')
      setDefectOpen(false)
      navigate(`/defects/${d.id}`)
    } catch (e) {
      // 拦截器已弹后端原因，这里只补修复路径提示
      if (!e?.message) message.error('创建缺陷失败，请在缺陷管理中重试')
    } finally {
      setDefectSaving(false)
    }
  }

  const doSetBaseline = async () => {
    setBaselining(true)
    try {
      await es11.setBaseline(runId)
      message.success('已设为基线（同题库旧基线已自动取消标记）')
      load()
    } catch (e) {
      if (e?.code === 'ES-BIZ-BASE-0001') {
        modal.warning({
          title: '不能建立基线（ES-BIZ-BASE-0001）',
          content: '强制复核未全部完成，或运行未到终态。修复路径：在「Judge 与复核」完成全部人工复核（G2 通过）后重试。',
          okText: '前往复核队列',
          onOk: () => navigate('/review'),
        })
      }
    } finally {
      setBaselining(false)
    }
  }

  if (loading) {
    return <Card style={{ textAlign: 'center', padding: 48 }}><Spin tip="加载运行工作区…" /></Card>
  }
  if (!ws) {
    return (
      <Card>
        <Alert type="error" showIcon message="运行工作区加载失败"
          description={`${loadErr || '未知错误'}。请确认该运行 ID 有效且未被删除；可返回评测中心重新选择运行。`}
          action={
            <Space direction="vertical">
              <Button size="small" onClick={load}>重试</Button>
              <Button size="small" type="primary" onClick={() => navigate('/eval')}>返回评测中心</Button>
            </Space>
          }
        />
      </Card>
    )
  }

  // ------------------------------------------------------------ 头部固定区
  const header = (
    <Card styles={{ body: { background: ES.bg, borderRadius: 8 } }} style={{ border: `1px solid ${ES.line}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 0 }}>
          <Space size={8} wrap>
            <Typography.Text style={{ color: ES.ink, fontSize: 17, fontWeight: 600 }}>
              {PURPOSE_LABEL[run?.run_purpose] || run?.run_purpose || '评测活动'}
            </Typography.Text>
            <Mono>{run?.run_no || `RUN-${runId}`}</Mono>
            <Tag>{RUN_STATUS_LABEL[run?.status] || run?.status || '-'}</Tag>
            {(run?.status === 'RUNNING' || run?.status === 'PENDING')
              && <Tag color="processing">执行中（后台逐题评估，页面自动刷新）</Tag>}
            {run?.concluded && <Tag color="green">结论已冻结</Tag>}
            {snapshot.is_baseline && <Tag color="cyan">基线</Tag>}
            {run?.verdict ? verdictTag(run.verdict) : null}
          </Space>
          <div style={{ marginTop: 6, color: ES.sub, fontSize: 12.5 }}>
            被测系统：{run?.target_type ? `${run.target_type} · ${run.target_id || '-'}` : (run?.target_id || '-')}
            {'  '}|{'  '}版本：{run?.project_version_id ? <Mono color={ES.sub}>v#{run.project_version_id}</Mono> : '-'}
            {'  '}|{'  '}题库：{run?.question_bank_id ? <Mono color={ES.sub}>#{run.question_bank_id}</Mono> : '-'}
            {'  '}|{'  '}负责人：{run?.owner_name || run?.created_by_name || snapshot.owner || '-'}
          </div>
        </div>
        <Space size={8} wrap>
          <Tooltip title="前往报告中心为本运行生成/交付报告（G4）">
            <Button icon={<FileTextOutlined />} onClick={() => navigate('/reports')}>生成报告</Button>
          </Tooltip>
          <Button icon={<BugOutlined />} onClick={() => openDefectModal(null)}>创建缺陷</Button>
          <Tooltip title={ws.baseline_diff?.baseline_run_id === runId ? '本运行已是基线' : 'G2 通过后方可建立基线'}>
            <Button icon={<FlagOutlined />} loading={baselining} onClick={doSetBaseline}>建立基线</Button>
          </Tooltip>
          <Button type="primary" icon={<RedoOutlined />} onClick={() => navigate('/eval')}>重新执行</Button>
        </Space>
      </div>
      <GateRow gates={ws.gates} />
      <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
        <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>下一动作</Typography.Text>
        <Typography.Text style={{ color: ES.accent, fontSize: 13 }}>{nextAction(ws)}</Typography.Text>
      </div>
    </Card>
  )

  // ---------------------------------------------------------------- 概览
  const summaryEntries = Object.entries(run?.summary || {})
  const overview = (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      {ws.baseline_diff && !ws.baseline_diff.comparable && (
        <Alert type="warning" showIcon
          message="与基线条件不一致，差异不可直接归因模型版本（方案 P6）"
          description={
            <div>
              {(ws.baseline_diff.diff_reasons || []).map((r, i) => <div key={i}>· {typeof r === 'string' ? r : toText(r)}</div>)}
              <div style={{ marginTop: 6 }}>请先核对题库版本、Judge 模型与抽样种子配置一致后再解读回归差异。</div>
            </div>
          }
        />
      )}
      <Card size="small" title="关键指标">
        <Descriptions size="small" column={3} bordered items={[
          { key: 'score', label: '总分', children: run?.overall_score ?? '-' },
          { key: 'concl', label: '结论状态', children: run?.concluded ? '已冻结' : '未冻结（复核未完成或未终态）' },
          { key: 'judge', label: 'Judge 模式', children: `${run?.judge_mode || '-'}${run?.judge_model ? ` · ${run.judge_model}` : ''}` },
          { key: 'mode', label: '被测模式', children: snapshot.target_mode || '-' },
          { key: 'seed', label: '抽样种子', children: snapshot.sample_seed != null ? <Mono>{snapshot.sample_seed}</Mono> : '-' },
          { key: 'time', label: '起止时间', children: `${fmtTime(run?.started_at)} ~ ${fmtTime(run?.finished_at)}` },
          ...summaryEntries.filter(([k]) => !('failure_mix' === k)).map(([k, v]) => ({
            key: `s-${k}`, label: k, children: typeof v === 'object' ? toText(v) : String(v),
          })),
        ]} />
      </Card>
      <Card size="small" title="与基线对比（概览）">
        {ws.baseline_diff ? (
          ws.baseline_diff.comparable ? (
            <Space size={24} wrap>
              <span>新增失败 <Typography.Text style={{ color: ES.BLOCK, fontWeight: 700, fontFamily: ES.mono, fontSize: 20 }}>{ws.baseline_diff.new_fail ?? 0}</Typography.Text></span>
              <span>已修复 <Typography.Text style={{ color: ES.PASS, fontWeight: 700, fontFamily: ES.mono, fontSize: 20 }}>{ws.baseline_diff.fixed ?? 0}</Typography.Text></span>
              <span>仍然失败 <Typography.Text style={{ color: ES.WARN, fontWeight: 700, fontFamily: ES.mono, fontSize: 20 }}>{ws.baseline_diff.still_fail ?? 0}</Typography.Text></span>
              <Button size="small" onClick={() => setTab('compare')}>查看回归差异 <RightOutlined /></Button>
            </Space>
          ) : (
            <Typography.Text type="secondary">基线运行 #{ws.baseline_diff.baseline_run_id} 条件不可比，差异计数不可用。</Typography.Text>
          )
        ) : (
          <Empty description="同题库尚无基线运行" image={Empty.PRESENTED_IMAGE_SIMPLE}>
            <Button type="primary" size="small" loading={baselining} onClick={doSetBaseline}>建立基线</Button>
          </Empty>
        )}
      </Card>
      <Card size="small" title="报告与交付（G4）">
        {ws.report ? (
          <Descriptions size="small" column={3} items={[
            { key: 'no', label: '报告编号', children: <Mono>{ws.report.report_no}</Mono> },
            { key: 'st', label: '状态', children: ws.report.status || '-' },
            { key: 'dl', label: '可交付', children: ws.report.deliverable ? '是' : '否' },
          ]} />
        ) : (
          <Space>
            <Typography.Text type="secondary">本运行尚未生成报告。</Typography.Text>
            <Button size="small" onClick={() => navigate('/reports')}>前往报告中心</Button>
          </Space>
        )}
      </Card>
      <CoveragePanel runId={runId} onOpenBenchmark={() => navigate(`/standards/gbt45654?run=${runId}&tab=coverage`)} />
    </Space>
  )

  // -------------------------------------------------------------- 题级证据
  const itemsTab = (
    <ItemsColumn
      runId={runId} runNo={run?.run_no} bankId={run?.question_bank_id}
      onToDefect={(prefill) => openDefectModal(prefill)}
    />
  )

  // ------------------------------------------------------------ Judge 与复核
  const jh = ws.judge_health || {}
  const rp = ws.review_progress || {}
  const judgeTab = (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      <Card size="small" title="Judge 健康度">
        <Descriptions size="small" column={2} bordered items={[
          {
            key: 'kappa', label: '一致性 Kappa',
            children: jh.kappa == null
              ? <Typography.Text type="secondary">样本不足，无法计算</Typography.Text>
              : (
                <Typography.Text style={{ color: Number(jh.kappa) >= Number(jh.threshold ?? 0.6) ? ES.PASS : ES.BLOCK, fontWeight: 600 }}>
                  {Number(jh.kappa).toFixed(3)}（阈值 {jh.threshold ?? '-'}）
                </Typography.Text>
              ),
          },
          { key: 'sample', label: '校准样本数', children: jh.sample ?? 0 },
          {
            key: 'suf', label: '样本充分性',
            children: jh.sufficient ? <Tag color="green">充分</Tag> : <Tag color="orange">不足（&lt;10，仅供参考）</Tag>,
          },
          {
            key: 'agree', label: '双轨一致率',
            children: jh.agreement_rate == null ? '-' : `${(Number(jh.agreement_rate) * 100).toFixed(1)}%`,
          },
        ]} />
        {jh.sufficient === false && (
          <Alert style={{ marginTop: 10 }} type="warning" showIcon
            message="校准样本不足 10 条：Judge 可信度未达监控口径，结论请依赖人工复核。" />
        )}
      </Card>
      <Card size="small" title="强制复核进度（G2）">
        <Progress
          percent={rp.total ? Math.round(((rp.done || 0) / rp.total) * 100) : 0}
          status={rp.pending ? 'active' : 'success'}
        />
        <div style={{ marginTop: 8 }}>
          <Typography.Text type="secondary">
            共 {rp.total ?? 0} 条，已完成 {rp.done ?? 0} 条，待复核 {rp.pending ?? 0} 条。
            复核全部完成前，结论不冻结、不能建立基线。
          </Typography.Text>
        </div>
        {(rp.pending ?? 0) > 0 && (
          <Button type="primary" size="small" style={{ marginTop: 10 }} onClick={() => navigate('/review')}>
            前往复核队列完成复核
          </Button>
        )}
      </Card>
    </Space>
  )

  // ------------------------------------------------------------- 缺陷与复测
  const defectTab = (
    <DefectsTab
      ws={ws} runId={runId}
      onNew={() => openDefectModal(null)}
      onOpen={(did) => navigate(`/defects/${did}`)}
    />
  )

  // --------------------------------------------------------------- 回归差异
  const compareTab = (
    <CompareTab
      runId={runId} bankId={run?.question_bank_id}
      defaultBaselineId={ws.baseline_diff?.baseline_run_id}
    />
  )

  // ----------------------------------------------------- 攻击轨迹（红队运行）
  const rt = ws.redteam
  const attackTab = rt ? <AttackTraceTab redteam={rt} runId={runId} runNo={run?.run_no} onToDefect={openDefectModal} /> : null

  // ---------------------------------------------------------------- 审计
  const auditTab = <AuditTab audit={ws.audit} runId={runId} />

  return (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      {header}
      <Card styles={{ body: { paddingTop: 0 } }}>
        <Tabs
          activeKey={tab === 'rag' && !(ws.rag?.telemetry > 0) ? 'overview' : tab}
          onChange={setTab}
          destroyOnHidden
          items={[
            { key: 'overview', label: '概览', children: overview },
            { key: 'items', label: '题级证据', children: itemsTab },
            // RAG 轨迹页签：有检索遥测数据才显示（方案 P3/P7）
            ...(ws.rag?.telemetry > 0
              ? [{
                  key: 'rag',
                  label: `RAG 轨迹（${ws.rag.telemetry}）`,
                  children: (
                    <RagWorkbench
                      runId={runId} runNo={run?.run_no} rag={ws.rag}
                      onToDefect={openDefectModal}
                    />
                  ),
                }]
              : []),
            // 攻击轨迹页签：红队运行（后端仅对红队类引擎组装 redteam 数据）才显示
            ...(rt ? [{ key: 'attack', label: `攻击轨迹（${rt.totals?.attempts ?? 0}）`, children: attackTab }] : []),
            { key: 'judge', label: 'Judge 与复核', children: judgeTab },
            { key: 'defects', label: `缺陷与复测${ws.defects?.total ? `（${ws.defects.total}）` : ''}`, children: defectTab },
            { key: 'compare', label: '回归差异', children: compareTab },
            { key: 'audit', label: `审计${ws.audit?.total ? `（${ws.audit.total}）` : ''}`, children: auditTab },
          ]}
        />
      </Card>

      <Modal open={defectOpen} title="创建缺陷（进入闭环时间线）" onCancel={() => setDefectOpen(false)}
        onOk={createDefect} okButtonProps={{ loading: defectSaving }} width={640} destroyOnHidden>
        <Form form={dform} layout="vertical" initialValues={{ severity: 'P2', priority: 'MEDIUM' }}>
          <Form.Item name="project_id" label="所属项目" rules={[{ required: true, message: '请选择项目' }]}>
            <Select showSearch placeholder="可搜索项目名称" options={projects}
              filterOption={(q, o) => String(o?.label || '').toLowerCase().includes(q.toLowerCase())} />
          </Form.Item>
          <Form.Item name="title" label="缺陷标题" rules={[{ required: true, message: '必填' }]}>
            <Input maxLength={500} placeholder="一句话描述失败现象" />
          </Form.Item>
          <Space style={{ display: 'flex' }} size={12}>
            <Form.Item name="severity" label="严重度" style={{ width: 120 }}><Select options={SEVERITY_OPTIONS} /></Form.Item>
            <Form.Item name="priority" label="优先级" style={{ width: 120 }}><Select options={PRIORITY_OPTIONS} /></Form.Item>
            <Form.Item name="assignee_name" label="指派给" style={{ width: 200 }}><Input maxLength={100} /></Form.Item>
          </Space>
          <Form.Item name="expected" label="预期表现"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="actual" label="实际表现"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}

// ============================================================ 题级证据三栏
function ItemsColumn({ runId, runNo, bankId, onToDefect }) {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [filters, setFilters] = useState({ verdict: undefined, failure_class: undefined, needs_review: undefined })
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(null)
  const [full, setFull] = useState(null) // item_id → 全文版
  const [fullLoading, setFullLoading] = useState(false)

  const load = useCallback((p = 1, f = filters) => {
    setLoading(true)
    es11.getRunItems(runId, {
      page: p, page_size: pageSize,
      verdict: f.verdict || undefined,
      failure_class: f.failure_class || undefined,
      needs_review: f.needs_review,
    })
      .then((d) => {
        setItems(d.items || []); setTotal(d.total || 0); setPage(p)
      })
      .catch(() => { setItems([]); setTotal(0) })
      .finally(() => setLoading(false))
  }, [runId, pageSize, filters])

  useEffect(() => { load(1) }, [load]) // eslint-disable-line react-hooks/exhaustive-deps

  // FAIL/分歧优先：仅对当前页重排，不改变后端分页口径
  const queue = useMemo(() => {
    const rank = (it) => (String(it.final_verdict).toUpperCase() === 'FAIL' ? 0 : it.judge_agreement === false ? 1 : 2)
    return [...items].sort((a, b) => rank(a) - rank(b) || (a.seq || 0) - (b.seq || 0))
  }, [items])

  const cur = full && full.id === selected?.id ? full : selected
  const ep = cur?.evidence_payload

  const loadFull = async (it) => {
    setSelected(it); setFull(null)
    setFullLoading(true)
    try {
      const d = es11.getRunItems
        ? await es11.getRunItems(runId, { item_id: it.id, full: true, page: 1, page_size: 1 })
        : null
      const one = d?.items?.[0]
      if (one) setFull(one)
    } catch (e) {
      message.error('全文加载失败：' + (e?.message || '未知错误'))
    } finally {
      setFullLoading(false)
    }
  }

  const renderEvidenceList = (val, title) => {
    if (val == null) return null
    const arr = Array.isArray(val) ? val : [val]
    return (
      <EvidencePanel title={title} style={{ marginTop: 10 }}>
        {arr.map((x, i) => (
          <div key={i} style={{ borderBottom: i < arr.length - 1 ? `1px solid ${ES.line}` : 'none', paddingBottom: 6, marginBottom: 6 }}>
            <ClipText text={toText(x)} rows={2} />
          </div>
        ))}
      </EvidencePanel>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
      {/* 左 300px：题目队列 */}
      <div style={{ width: 300, flexShrink: 0 }}>
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space size={6} wrap>
            <Select size="small" placeholder="结论" allowClear style={{ width: 96 }} value={filters.verdict}
              onChange={(v) => setFilters((f) => ({ ...f, verdict: v }))}
              options={[{ value: 'PASS', label: '通过' }, { value: 'FAIL', label: '失败' }]} />
            <Select size="small" placeholder="失败口径" allowClear style={{ width: 110 }} value={filters.failure_class}
              onChange={(v) => setFilters((f) => ({ ...f, failure_class: v }))}
              options={Object.entries(FAIL_CLASS_LABEL).map(([value, label]) => ({ value, label }))} />
            <Select size="small" placeholder="复核" allowClear style={{ width: 100 }} value={filters.needs_review}
              onChange={(v) => setFilters((f) => ({ ...f, needs_review: v }))}
              options={[{ value: true, label: '待复核' }, { value: false, label: '已复核' }]} />
          </Space>
          <div style={{ border: `1px solid ${ES.line}`, borderRadius: 8, maxHeight: 560, overflow: 'auto' }}>
            {loading && <div style={{ padding: 24, textAlign: 'center' }}><Spin size="small" /></div>}
            {!loading && queue.length === 0 && (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前筛选无题目" style={{ padding: 24 }} />
            )}
            {!loading && queue.map((it) => {
              const active = selected?.id === it.id
              return (
                <div key={it.id} onClick={() => loadFull(it)}
                  style={{
                    padding: '8px 10px', cursor: 'pointer', borderBottom: `1px solid ${ES.line}`,
                    background: active ? '#0d1420' : 'transparent',
                    borderLeft: `3px solid ${String(it.final_verdict).toUpperCase() === 'FAIL' ? ES.BLOCK : 'transparent'}`,
                  }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
                    <Mono color={active ? ES.accent : ES.sub}>#{it.seq ?? it.id}</Mono>
                    <Space size={4}>
                      {it.judge_agreement === false && <Tag color="orange">分歧</Tag>}
                      {it.review_status === 'pending' && <Tag>待复核</Tag>}
                      {verdictTag(it.final_verdict)}
                    </Space>
                  </div>
                  <div style={{ color: '#b8c7d4', fontSize: 12, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {it.prompt || '（无题面）'}
                  </div>
                </div>
              )
            })}
          </div>
          <div style={{ textAlign: 'right' }}>
            <PaginationMini page={page} pageSize={pageSize} total={total} onChange={(p) => load(p)} />
          </div>
        </Space>
      </div>

      {/* 中部：证据主体 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {!cur ? (
          <Card size="small"><Empty description="从左侧队列选择一道题查看完整证据；FAIL 与双轨分歧已优先排列" /></Card>
        ) : (
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Space size={8}>
                <Mono>item#{cur.id}</Mono>
                <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>question#{cur.question_id} · {cur.category || '-'} · {cur.split || '-'}</Typography.Text>
              </Space>
              <Button size="small" loading={fullLoading}
                onClick={() => loadFull(cur.id === selected?.id ? selected : cur)}>
                {full && full.id === cur.id ? '已加载全文' : '加载全文'}
              </Button>
            </div>
            <EvidencePanel title={`输入与预期（第 ${cur.seq ?? '-'} 题${full ? '，全文' : '，截断'})`}>
              <ClipText text={cur.prompt} rows={4} />
              {cur.verdict_reason && (
                <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>判定理由：{cur.verdict_reason}</Typography.Text>
              )}
            </EvidencePanel>
            {ep == null && (
              <Alert type="info" showIcon message="历史运行，仅基础证据（无结构化检索/轨迹载荷，不做补造）" />
            )}
            {ep != null && (
              <>
                {ep.failure_class && (
                  <Tag color={ep.failure_class === 'CONFIG' ? 'gold' : 'red'}>
                    失败口径：{FAIL_CLASS_LABEL[ep.failure_class] || ep.failure_class}
                  </Tag>
                )}
                {renderEvidenceList(ep.retrieval, '检索上下文')}
                {renderEvidenceList(ep.spans, '工具 / 攻击轨迹')}
                {renderEvidenceList(ep.citations, '引用来源')}
              </>
            )}
            <EvidencePanel title="被测回答">
              <ClipText text={cur.response} rows={5} />
              {!cur.response && <Typography.Text style={{ color: ES.sub }}>（无回答内容）</Typography.Text>}
            </EvidencePanel>
            <EvidencePanel title="指标">
              <Space size={16} wrap>
                <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>时延 {cur.latency_ms ?? '-'} ms</Typography.Text>
                {ep?.metrics && Object.entries(ep.metrics).map(([k, v]) => (
                  <Typography.Text key={k} style={{ color: ES.sub, fontSize: 12 }}>{k}={String(v)}</Typography.Text>
                ))}
                {cur.evidence_ref && <Mono color={ES.sub}>{cur.evidence_ref}</Mono>}
              </Space>
            </EvidencePanel>
          </Space>
        )}
      </div>

      {/* 右 300px：判定与动作 */}
      <div style={{ width: 300, flexShrink: 0 }}>
        {!cur ? (
          <Card size="small"><Typography.Text type="secondary">选择题目后显示双轨判定与动作。</Typography.Text></Card>
        ) : (
          <Card size="small" title="判定与动作">
            <Space direction="vertical" size={10} style={{ width: '100%' }}>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>规则轨</Typography.Text>
                <div>{verdictTag(cur.rule_verdict)}</div>
              </div>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>Judge 轨</Typography.Text>
                <div>
                  {verdictTag(cur.judge_verdict)}
                  {cur.judge_agreement === true && <Tag color="green">双轨一致</Tag>}
                  {cur.judge_agreement === false && <Tag color="orange">双轨分歧</Tag>}
                </div>
                {cur.judge_model && <Mono color={ES.sub}>{cur.judge_model}</Mono>}
              </div>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>人工结论</Typography.Text>
                <div>
                  {cur.review_status === 'pending'
                    ? <Tag color="gold">待复核</Tag>
                    : <Tag color={cur.review_status ? 'green' : 'default'}>{cur.review_status || '无需复核'}</Tag>}
                  {verdictTag(cur.final_verdict)}
                </div>
              </div>
              <Button block icon={<BugOutlined />}
                onClick={() => onToDefect({
                  title: `[${runNo || `RUN-${runId}`}] 第${cur.seq ?? cur.id}题 ${String(cur.final_verdict).toUpperCase() === 'FAIL' ? '失败' : '异常'}`,
                  severity: 'P1',
                  actual: (cur.response || '').slice(0, 500),
                  expected: cur.verdict_reason || undefined,
                  __origin_item_id: cur.id,
                })}>
                转缺陷
              </Button>
              <Tooltip title="题目已归属本运行题库；前往题库详情将其维护进回归切分（split）">
                <Button block onClick={() => {
                  if (!bankId) { message.warning('该运行未关联题库，无法维护回归集'); return }
                  navigate(`/question-banks/${bankId}`)
                }}>
                  加入回归集
                </Button>
              </Tooltip>
            </Space>
          </Card>
        )}
      </div>
    </div>
  )
}

function PaginationMini({ page, pageSize, total, onChange }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <Space size={6}>
      <Button size="small" disabled={page <= 1} onClick={() => onChange(page - 1)}>上一页</Button>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>{page}/{pages} · 共 {total}</Typography.Text>
      <Button size="small" disabled={page >= pages} onClick={() => onChange(page + 1)}>下一页</Button>
    </Space>
  )
}

// ============================================================ RAG 证据工作台（P7）
const RAG_CAT_LABEL = {
  NO_HIT: '无命中', LOW_RECALL: '低召回', LOW_FAITH: '低忠实度',
  CITATION_ERROR: '引用错误', ACL: '疑似越权',
}
const RAG_RATE_META = [
  ['retrieval_fail', '检索失败率', '检索空命中占比'],
  ['ungrounded', '无引用回答率', '有检索遥测且引用集显式为空（缺 citations 键视为未采集，不计）'],
  ['acl_hit', '越权命中率', '检索命中文档带 acl_violation 标记'],
  ['conflict', '事实冲突率', '忠实度低于阈值（回答与上下文冲突）'],
]

/** 单题阶段诊断：按检索→召回→权限→引用→生成顺序给出定位（口径与后端谓词一致）。 */
function ragDiagnose(ep, th) {
  if (!ep || typeof ep !== 'object' || !('retrieval' in ep)) {
    return [{ stage: '遥测', desc: '仅黑盒结论，无法定位检索阶段（该题无检索遥测）', tone: 'gray' }]
  }
  const out = []
  const ret = Array.isArray(ep.retrieval) ? ep.retrieval : []
  if (ret.length === 0) out.push({ stage: '检索', desc: '无命中：检索返回空文档集', tone: 'red' })
  else if (Number(ret[0]?.score ?? 1) < th.low_score) {
    out.push({ stage: '召回', desc: `低召回：首条分数 ${ret[0]?.score} < ${th.low_score}`, tone: 'orange' })
  }
  if (ret.some((r) => (r?.labels || []).includes('acl_violation'))) {
    out.push({ stage: '权限', desc: '疑似越权：检索命中带 acl_violation 标记的文档', tone: 'red' })
  }
  const cits = Array.isArray(ep.citations) ? ep.citations : null
  if (cits && cits.length === 0 && ret.length > 0) {
    out.push({ stage: '引用', desc: '无引用回答：有检索命中但回答未附引用', tone: 'gold' })
  }
  if (cits?.length) {
    const ids = new Set(ret.map((r) => r?.doc_id))
    const bad = cits.filter((c) => c?.doc_id && !ids.has(c.doc_id))
    if (bad.length) out.push({ stage: '引用', desc: `引用错误：${bad.length} 处引用不在检索文档集`, tone: 'red' })
  }
  const faith = ep.metrics?.faithfulness
  if (faith != null && Number(faith) < th.low_faith) {
    out.push({ stage: '生成', desc: `低忠实度：${faith} < ${th.low_faith}，回答与检索上下文冲突`, tone: 'red' })
  }
  if (!out.length) out.push({ stage: '各阶段', desc: '检索/引用/忠实度未见异常', tone: 'green' })
  return out
}

function RagWorkbench({ runId, runNo, rag, onToDefect }) {
  const { message } = App.useApp()
  const th = rag.thresholds || { low_score: 0.3, low_faith: 0.6 }
  const [cat, setCat] = useState(null)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(null)
  const [full, setFull] = useState(null)
  const [fullLoading, setFullLoading] = useState(false)

  const load = useCallback((p = 1, c = cat) => {
    setLoading(true)
    es11.getRunItems(runId, { page: p, page_size: pageSize, rag: c || undefined })
      .then((d) => { setItems(d.items || []); setTotal(d.total || 0); setPage(p) })
      .catch(() => { setItems([]); setTotal(0) })
      .finally(() => setLoading(false))
  }, [runId, pageSize, cat])

  useEffect(() => { load(1) }, [load]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadFull = async (it) => {
    setSelected(it); setFull(null); setFullLoading(true)
    try {
      const d = await es11.getRunItems(runId, { item_id: it.id, full: true, page: 1, page_size: 1 })
      if (d?.items?.[0]) setFull(d.items[0])
    } catch (e) { message.error('全文加载失败：' + (e?.message || '未知错误')) } finally { setFullLoading(false) }
  }

  const cur = full && selected && full.id === selected.id ? full : null
  const ep = cur?.evidence_payload
  const ret = Array.isArray(ep?.retrieval) ? ep.retrieval : []
  const cits = Array.isArray(ep?.citations) ? ep.citations : []
  const diag = cur ? ragDiagnose(ep, th) : []
  const pct = (v) => (v == null ? '-' : `${(v * 100).toFixed(1)}%`)

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {/* 顶部：运行级四指标（分母=遥测条目数） */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {RAG_RATE_META.map(([key, label, tip]) => (
          <Card key={key} size="small" style={{ flex: '1 1 200px' }}>
            <Tooltip title={tip}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>{label}</Typography.Text>
            </Tooltip>
            <div style={{ fontSize: 22, color: ES.ink, fontFamily: ES.mono }}>
              {pct(rag.rates?.[key])}
              <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                {rag.counts?.[{ retrieval_fail: 'no_hit', ungrounded: 'ungrounded', acl_hit: 'acl', conflict: 'low_faith' }[key]] ?? 0} / {rag.telemetry} 题
              </Typography.Text>
            </div>
          </Card>
        ))}
      </div>
      {rag.rates?.citation_error > 0 && (
        <Alert type="warning" showIcon message={`另有 ${rag.counts.citation_error} 题存在引用错误（引用不在检索文档集）`} />
      )}

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {/* 左：阶段筛选 + 题目队列 */}
        <div style={{ width: 300, flexShrink: 0 }}>
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Space size={6} wrap>
              {Object.entries(RAG_CAT_LABEL).map(([k, label]) => (
                <Tag.CheckableTag key={k} checked={cat === k}
                  onChange={(on) => { setCat(on ? k : null); setFull(null); setSelected(null) }}>
                  {label}（{rag.counts?.[k.toLowerCase()] ?? 0}）
                </Tag.CheckableTag>
              ))}
            </Space>
            <div style={{ border: `1px solid ${ES.line}`, borderRadius: 8, maxHeight: 520, overflow: 'auto' }}>
              {loading && <div style={{ padding: 24, textAlign: 'center' }}><Spin size="small" /></div>}
              {!loading && items.length === 0 && (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={cat ? '该阶段无题目' : '本运行无检索遥测题目'} style={{ padding: 24 }} />
              )}
              {!loading && items.map((it) => {
                const active = selected?.id === it.id
                return (
                  <div key={it.id} onClick={() => loadFull(it)}
                    style={{
                      padding: '8px 10px', cursor: 'pointer', borderBottom: `1px solid ${ES.line}`,
                      background: active ? '#0d1420' : 'transparent',
                      borderLeft: `3px solid ${String(it.final_verdict).toUpperCase() === 'FAIL' ? ES.BLOCK : 'transparent'}`,
                    }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                      <Mono color={active ? ES.accent : ES.sub}>#{it.seq ?? it.id}</Mono>
                      <Space size={4}>{verdictTag(it.final_verdict)}</Space>
                    </div>
                    <div style={{ color: '#b8c7d4', fontSize: 12, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {it.prompt || '（无题面）'}
                    </div>
                  </div>
                )
              })}
            </div>
            <div style={{ textAlign: 'right' }}>
              <PaginationMini page={page} pageSize={pageSize} total={total} onChange={(p) => load(p)} />
            </div>
          </Space>
        </div>

        {/* 中：检索文档 / 重排 / 引用 / 回答 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {!cur ? (
            <Card size="small">
              <Empty description={fullLoading ? '加载中…' : '从左侧选择题目查看检索轨迹；阶段筛选基于运行遥测（retrieval/citations/metrics）'} />
            </Card>
          ) : (
            <Space direction="vertical" size={10} style={{ width: '100%' }}>
              <Space size={8}>
                <Mono>item#{cur.id}</Mono>
                <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>
                  question#{cur.question_id} · {cur.category || '-'} · {cur.split || '-'}
                </Typography.Text>
              </Space>
              <EvidencePanel title="检索文档（rank / score / 标签 / 片段）">
                {ret.length === 0 ? (
                  <Typography.Text style={{ color: ES.sub }}>（无命中文档）</Typography.Text>
                ) : (
                  <Table
                    size="small" rowKey={(r, i) => `${r?.doc_id || 'doc'}-${i}`} dataSource={ret}
                    pagination={false}
                    columns={[
                      { title: 'rank', dataIndex: 'rank', width: 56, render: (v, r, i) => v ?? i + 1 },
                      { title: 'doc_id', dataIndex: 'doc_id', width: 140, render: (v) => <Mono>{v ?? '-'}</Mono> },
                      {
                        title: 'score', dataIndex: 'score', width: 80,
                        render: (v) => (
                          <span style={{ color: Number(v) < th.low_score ? ES.BLOCK : ES.ink, fontFamily: ES.mono }}>
                            {v ?? '-'}
                          </span>
                        ),
                      },
                      {
                        title: '标签', dataIndex: 'labels', width: 130,
                        render: (v) => (v || []).map((l) => (
                          <Tag key={l} color={l === 'acl_violation' ? 'red' : 'default'}>{l}</Tag>
                        )),
                      },
                      { title: '片段', dataIndex: 'content', render: (v) => <ClipText text={v} rows={2} /> },
                    ]}
                  />
                )}
              </EvidencePanel>
              {Array.isArray(ep?.reranked) && ep.reranked.length > 0 && (
                <EvidencePanel title="重排变化（rerank）">
                  <ClipText text={toText(ep.reranked)} rows={3} mono />
                </EvidencePanel>
              )}
              <EvidencePanel title={`引用片段（${cits.length}）`}>
                {cits.length === 0 ? (
                  <Typography.Text style={{ color: ES.sub }}>（回答无引用支撑）</Typography.Text>
                ) : cits.map((c, i) => (
                  <div key={i} style={{ borderBottom: i < cits.length - 1 ? `1px solid ${ES.line}` : 'none', paddingBottom: 6, marginBottom: 6 }}>
                    <Mono>{c?.doc_id || `#${i + 1}`}</Mono>
                    <ClipText text={c?.snippet || toText(c)} rows={2} />
                  </div>
                ))}
              </EvidencePanel>
              <EvidencePanel title="被测回答">
                <ClipText text={cur.response} rows={5} />
                {!cur.response && <Typography.Text style={{ color: ES.sub }}>（无回答内容）</Typography.Text>}
              </EvidencePanel>
            </Space>
          )}
        </div>

        {/* 右：阶段诊断 + 转缺陷 */}
        <div style={{ width: 300, flexShrink: 0 }}>
          <Card size="small" title="阶段诊断">
            {!cur ? (
              <Typography.Text type="secondary">选择题目后按 检索→召回→权限→引用→生成 定位失败阶段。</Typography.Text>
            ) : (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {diag.map((d) => (
                  <div key={d.stage + d.desc}>
                    <Tag color={d.tone === 'red' ? 'red' : d.tone === 'orange' ? 'orange' : d.tone === 'gold' ? 'gold' : d.tone === 'green' ? 'green' : 'default'}>
                      {d.stage}
                    </Tag>
                    <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>{d.desc}</Typography.Text>
                  </div>
                ))}
                {ep?.metrics?.faithfulness != null && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    忠实度 {String(ep.metrics.faithfulness)} · 阈值 {th.low_faith}
                  </Typography.Text>
                )}
                <Button block icon={<BugOutlined />} disabled={diag[0]?.tone === 'gray'}
                  onClick={() => onToDefect({
                    title: `[${runNo || `RUN-${runId}`}] 第${cur.seq ?? cur.id}题 RAG ${diag[0]?.stage}阶段异常`,
                    severity: diag.some((x) => x.stage === '权限') ? 'P0' : 'P1',
                    actual: (cur.response || '').slice(0, 500) || diag.map((x) => x.desc).join('；'),
                    expected: cur.verdict_reason || '检索证据应支撑回答且无越权命中',
                    __origin_item_id: cur.id,
                  })}>
                  转缺陷
                </Button>
              </Space>
            )}
          </Card>
        </div>
      </div>
    </Space>
  )
}

// =========================================================== 缺陷与复测 Tab
function DefectsTab({ ws, runId, onNew, onOpen }) {
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const counts = ws.defects || {}
  const run = ws.run || {}

  useEffect(() => {
    setLoading(true)
    es11.listDefects({ page: 1, page_size: 20 })
      .then((d) => setRows(d.items || []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [])

  return (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      {run.run_purpose === 'RETEST' && run.parent_run_id && (
        <Alert type="info" showIcon
          message="本运行是缺陷复测运行"
          description={<a onClick={() => navigate(`/eval/runs/${run.parent_run_id}`)}>返回原运行 #{run.parent_run_id} 工作区</a>}
        />
      )}
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        <span>缺陷总数 <b style={{ fontFamily: ES.mono }}>{counts.total ?? 0}</b></span>
        <span>未闭环 P0/P1 <b style={{ fontFamily: ES.mono, color: (counts.open_p0p1 || 0) > 0 ? ES.BLOCK : ES.PASS }}>{counts.open_p0p1 ?? 0}</b></span>
        <span>已修复待验证 <b style={{ fontFamily: ES.mono, color: ES.WARN }}>{counts.fixed_unverified ?? 0}</b></span>
        <span style={{ color: '#8b97a7', fontSize: 12 }}>（租户级口径；下表为最近缺陷，点击行进入闭环时间线）</span>
      </div>
      <Table
        size="small" rowKey="id" loading={loading} dataSource={rows}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        onRow={(r) => ({ onClick: () => onOpen(r.id), style: { cursor: 'pointer' } })}
        locale={{
          emptyText: (
            <Empty description="暂无缺陷记录" image={Empty.PRESENTED_IMAGE_SIMPLE}>
              <Button type="primary" size="small" onClick={onNew}>创建缺陷</Button>
            </Empty>
          ),
        }}
        columns={[
          { title: '编号', dataIndex: 'defect_no', width: 150, render: (v) => <Mono>{v}</Mono> },
          { title: '标题', dataIndex: 'title', ellipsis: true },
          { title: '严重度', dataIndex: 'severity', width: 90, render: (v) => (v ? <Tag color={v === 'P0' || v === 'P1' ? 'red' : 'orange'}>{v}</Tag> : '-') },
          { title: '状态', dataIndex: 'status', width: 100, render: (v) => <Tag>{v || '-'}</Tag> },
          { title: '操作', key: 'op', width: 110, render: (_, r) => <a onClick={(e) => { e.stopPropagation(); onOpen(r.id) }}>闭环详情 ›</a> },
        ]}
      />
    </Space>
  )
}

// ============================================================ 回归差异 Tab
function CompareTab({ runId, bankId, defaultBaselineId }) {
  const { message } = App.useApp()
  const [runs, setRuns] = useState([])
  const [baselineId, setBaselineId] = useState(defaultBaselineId || undefined)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    // 同题库运行候选：后端不支持按题库过滤，取最近 50 条客户端过滤（禁手填 ID）
    es11.listRuns({ page: 1, page_size: 50 })
      .then((d) => {
        const same = (d.items || []).filter((r) => r.id !== runId && (!bankId || r.question_bank_id === bankId))
        setRuns(same.map((r) => ({
          value: r.id,
          label: `${r.run_no || `#${r.id}`} · ${fmtTime(r.started_at || r.created_at)}${r.question_bank_id === bankId ? '' : ' · 异库'}`,
        })))
      })
      .catch(() => setRuns([]))
  }, [runId, bankId])

  useEffect(() => {
    if (!baselineId && defaultBaselineId) setBaselineId(defaultBaselineId)
  }, [defaultBaselineId, baselineId])

  const compare = async () => {
    if (!baselineId) { message.warning('请先选择基线运行'); return }
    setLoading(true)
    try {
      setResult(await es11.compareRun(runId, baselineId))
    } catch (e) {
      message.error('对比失败：' + (e?.message || '未知错误'))
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const cats = result?.categories || {}
  const counts = result?.counts || Object.fromEntries(
    Object.entries(cats).map(([k, v]) => [k, Array.isArray(v) ? v.length : 0]),
  )

  return (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      <Card size="small">
        <Space size={10} wrap>
          <Typography.Text type="secondary">基线运行（同题库，可搜索）</Typography.Text>
          <Select
            showSearch style={{ width: 380 }} placeholder="选择用于对比的基线运行"
            value={baselineId} onChange={setBaselineId}
            filterOption={(q, o) => String(o?.label || '').toLowerCase().includes(q.toLowerCase())}
            options={runs}
            notFoundContent={runs.length ? undefined : '同题库暂无其他运行'}
          />
          <Button type="primary" loading={loading} onClick={compare}>对比</Button>
        </Space>
      </Card>
      {result && !result.same_condition && (
        <Alert type="warning" showIcon
          message="条件不一致，不可直接对比（禁止归因模型版本，方案 P6）"
          description={
            <div>
              {(result.diff_reasons || []).map((r, i) => <div key={i}>· {typeof r === 'string' ? r : toText(r)}</div>)}
              <div style={{ marginTop: 6 }}>修复路径：核对题库、Judge 模型与版本、抽样种子一致后重新对比。</div>
            </div>
          }
        />
      )}
      {result && result.same_condition && (
        <>
          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
            {CAT_ORDER.filter((k) => counts[k] != null).map((k) => (
              <span key={k}>
                {CAT_LABEL[k] || k}{' '}
                <b style={{
                  fontFamily: ES.mono,
                  color: k === 'NEW_FAIL' || k === 'STILL_FAIL' ? ES.BLOCK : k === 'FIXED' ? ES.PASS : undefined,
                }}>{counts[k]}</b>
              </span>
            ))}
          </div>
          {['NEW_FAIL', 'FIXED'].map((k) => (
            <Card key={k} size="small"
              title={<span>{CAT_LABEL[k]}（{counts[k] ?? 0}）{k === 'NEW_FAIL' && <Typography.Text type="danger" style={{ fontSize: 12, marginLeft: 8 }}>优先处理</Typography.Text>}</span>}>
              <CompareItemTable rows={cats[k] || []} />
            </Card>
          ))}
          {['STILL_FAIL', 'STILL_PASS', 'NEW_SAMPLE', 'REMOVED_SAMPLE'].map((k) => (
            <Card key={k} size="small" title={`${CAT_LABEL[k]}（${counts[k] ?? 0}）`}>
              <CompareItemTable rows={cats[k] || []} />
            </Card>
          ))}
        </>
      )}
      {!result && (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="选择基线运行后点击「对比」，渲染七类差异（新增失败/已修复优先展示）" />
      )}
    </Space>
  )
}

function CompareItemTable({ rows }) {
  if (!rows.length) return <Typography.Text type="secondary">（无）</Typography.Text>
  return (
    <Table
      size="small" rowKey="id" dataSource={rows}
      pagination={{ pageSize: 10, showSizeChanger: false }}
      columns={[
        { title: '序号', dataIndex: 'seq', width: 70, render: (v) => <Mono>#{v}</Mono> },
        { title: '结论', dataIndex: 'final_verdict', width: 90, render: verdictTag },
        {
          title: '失败口径', dataIndex: 'failure_class', width: 110,
          render: (v) => (v ? <Tag color={v === 'CONFIG' ? 'gold' : 'red'}>{FAIL_CLASS_LABEL[v] || v}</Tag> : '-'),
        },
        { title: '题面', dataIndex: 'prompt', ellipsis: true },
      ]}
    />
  )
}

// ============================================================ 攻击轨迹 Tab（P3，红队运行）
function AttackTraceTab({ redteam, runId, runNo, onToDefect }) {
  const traces = redteam.traces || []
  const totals = redteam.totals || {}
  const rate = totals.attempts ? ((totals.bypassed / totals.attempts) * 100).toFixed(1) : '-'
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        <span>投递载荷 <b style={{ fontFamily: ES.mono }}>{totals.attempts ?? 0}</b></span>
        <span>绕过 <b style={{ fontFamily: ES.mono, color: (totals.bypassed || 0) > 0 ? ES.BLOCK : ES.PASS }}>{totals.bypassed ?? 0}</b></span>
        <span>绕过率 <b style={{ fontFamily: ES.mono }}>{rate === '-' ? '-' : `${rate}%`}</b></span>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          （口径与攻击活动台账一致：detail.bypassed 或 verdict=BYPASSED 计绕过；最多展示 200 条）
        </Typography.Text>
      </div>
      <Table
        size="small" rowKey="seq" dataSource={traces}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本运行无结构化攻击条目" /> }}
        columns={[
          { title: '#', dataIndex: 'seq', width: 56, render: (v) => <Mono>#{v}</Mono> },
          {
            title: '框架条目', dataIndex: 'framework_code', width: 170,
            render: (v) => (v ? <Mono>{v}</Mono> : <Typography.Text type="secondary">-</Typography.Text>),
          },
          {
            title: '绕过', dataIndex: 'bypassed', width: 80,
            render: (v) => (v ? <Tag color="red">绕过</Tag> : <Tag>拦截</Tag>),
          },
          { title: '结论', dataIndex: 'verdict', width: 100, render: (v) => v || '-' },
          { title: '轮次', dataIndex: 'rounds', width: 70, render: (v) => v ?? '-' },
          { title: '攻击载荷', dataIndex: 'payload', render: (v) => <ClipText text={v} rows={2} mono /> },
          {
            title: '操作', key: 'op', width: 90,
            render: (_, r) => (r.bypassed ? (
              <a onClick={() => onToDefect({
                title: `[${runNo || `RUN-${runId}`}] 攻击载荷绕过（${r.framework_code || '未标注框架'}）`,
                severity: 'P0',
                actual: (r.payload || '').slice(0, 500),
                expected: '护栏应拦截该载荷',
                // ES11 修复：workspace 红队 traces 已按 seq 反查补 item_id，携带题级血缘
                __origin_item_id: r.item_id || undefined,
              })}>转缺陷</a>
            ) : null),
          },
        ]}
      />
    </Space>
  )
}

// ============================================================ 审计 Tab（P3）
function AuditTab({ audit, runId }) {
  const navigate = useNavigate()
  const items = audit?.items || []
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        与本运行相关的操作日志（路径含 runs/{runId}，含冻结、基线、复核、缺陷等写操作；最近 50 条）。
        全量审计请前往 <a onClick={() => navigate('/admin/audit')}>系统管理 › 审计日志</a>。
      </Typography.Text>
      <Table
        size="small" rowKey="log_no" dataSource={items}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无与该运行关联的审计记录" /> }}
        columns={[
          { title: '日志编号', dataIndex: 'log_no', width: 160, render: (v) => <Mono>{v}</Mono> },
          { title: '时间', dataIndex: 'created_at', width: 170, render: (v) => fmtTime(v) },
          { title: '操作人', dataIndex: 'username', width: 120, render: (v) => v || '-' },
          { title: '动作', dataIndex: 'action', width: 180, render: (v) => <Mono>{v}</Mono> },
          {
            title: '结果', dataIndex: 'result', width: 90,
            render: (v) => <Tag color={v === 'SUCCESS' ? 'green' : 'red'}>{v === 'SUCCESS' ? '成功' : '失败'}</Tag>,
          },
          { title: 'IP', dataIndex: 'ip', width: 130, render: (v) => v || '-' },
          { title: '失败原因', dataIndex: 'error_msg', ellipsis: true, render: (v) => v || '' },
        ]}
      />
    </Space>
  )
}
