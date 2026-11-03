/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES11 缺陷闭环详情（深链 /defects/:id，方案 §3.4/§5，G3 门禁）
// 左栏：只追加、不可覆盖的闭环时间线（defect_events 全量）；
// 右栏：按当前状态呈现阶段面板（缺陷内容 / 整改内容 / 复测与六条件 / 关闭记录）；
// 底部：仅暴露当前状态合法的动作按钮；危险动作一律 Modal.confirm。
// 硬约束：CLOSED 仅经 verify 六条件全满足产生；验证读 body.result（非 verdict）；
// 整改人==验证人时留痕「职责未分离」；拦截器已弹后端原因，前端不重复 toast。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  App, Alert, Button, Card, Col, Descriptions, Empty, Form, Input, Modal,
  Row, Space, Spin, Tag, Timeline, Tooltip, Typography,
} from 'antd'
import {
  ArrowLeftOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ReloadOutlined, RedoOutlined, SendOutlined, StopOutlined,
} from '@ant-design/icons'
import * as es11 from '../../api/es11'
import http from '../../api/http'
import { fmtTime } from '../../utils'
import { ES, GateBadge, GateChecklist, EvidencePanel, Mono } from './gate'

const STATUS_LABEL = {
  NEW: '新建', OPEN: '处理中', FIXED: '已修复',
  VERIFYING: '验证中', REOPENED: '重新打开', CLOSED: '已关闭',
}
const STATUS_COLOR = {
  NEW: 'default', OPEN: 'blue', FIXED: 'cyan',
  VERIFYING: 'gold', REOPENED: 'orange', CLOSED: 'green',
}
const EVENT_LABEL = {
  CREATED: '创建', ASSIGNED: '指派', REMEDIATED: '提交整改',
  RETEST_STARTED: '发起复测', VERIFIED: '验证通过', REOPENED: '重新打开',
  WAIVED: '豁免', CORRECTION: '更正',
}
const EVENT_DOT = {
  CREATED: 'gray', ASSIGNED: 'blue', REMEDIATED: ES.PASS,
  RETEST_STARTED: ES.accent, VERIFIED: ES.PASS, REOPENED: ES.BLOCK,
  WAIVED: ES.WARN, CORRECTION: 'gray',
}
const RUN_STATUS_LABEL = {
  PENDING: '等待中', QUEUED: '排队中', RUNNING: '运行中',
  SUCCESS: '成功', PASSED: '通过', FAILED: '失败', ERROR: '错误', CANCELLED: '已取消',
}
const VERDICT_LABEL = { PASS: '通过', FAIL: '失败', PARTIAL: '部分通过', UNKNOWN: '未知' }

function toText(v) {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try { return JSON.stringify(v, null, 1) } catch { return String(v) }
}

/** 长文本折叠：默认 rows 行，点「展开」看全。 */
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

/** 事件序列中最后一条指定类型（时间线按时间升序返回）。 */
function lastByType(events, type) {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    if (events[i].event_type === type) return events[i]
  }
  return null
}

export default function DefectDetail() {
  const { id } = useParams()
  const defectId = Number(id)
  const navigate = useNavigate()
  const { message, modal } = App.useApp()

  const [tl, setTl] = useState(null) // timeline 响应（权威状态源）
  const [detail, setDetail] = useState(null) // getDefect 详情（缺陷内容）
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [saving, setSaving] = useState(false)

  const [remOpen, setRemOpen] = useState(false)
  const [retestOpen, setRetestOpen] = useState(false)
  const [reopenOpen, setReopenOpen] = useState(false)
  const [waiveOpen, setWaiveOpen] = useState(false)
  const [remForm] = Form.useForm()
  const [retestForm] = Form.useForm()
  const [reopenForm] = Form.useForm()
  const [waiveForm] = Form.useForm()

  const load = useCallback(() => {
    setLoading(true)
    Promise.allSettled([es11.getDefectTimeline(defectId), es11.getDefect(defectId)])
      .then(([t, d]) => {
        if (t.status === 'fulfilled') { setTl(t.value); setLoadErr('') }
        else setLoadErr(t.reason?.message || '闭环时间线加载失败')
        if (d.status === 'fulfilled') setDetail(d.value)
      })
      .finally(() => setLoading(false))
  }, [defectId])

  useEffect(() => { load() }, [load])

  const events = useMemo(() => tl?.events || [], [tl])
  const defect = tl?.defect || detail || {}
  const status = defect.status || ''
  const unmet = tl?.unmet || []
  const conditions = tl?.close_conditions || []

  const remEv = useMemo(() => lastByType(events, 'REMEDIATED'), [events])
  const rtEv = useMemo(() => lastByType(events, 'RETEST_STARTED'), [events])
  const verEv = useMemo(() => lastByType(events, 'VERIFIED'), [events])
  // 职责未分离：最近一次整改人与最近一次验证人为同一人（仅留痕，不阻断）
  const dutyUnsep = !!(remEv && verEv && String(remEv.actor_id) === String(verEv.actor_id))

  const checks = useMemo(() => conditions.map((c) => ({
    code: c.code,
    reason: c.desc,
    status: unmet.includes(c.code) ? 'BLOCK' : 'PASS',
  })), [conditions, unmet])

  const nextHint = {
    NEW: '下一步：核实缺陷内容后提交整改（必须附变更引用）',
    OPEN: '下一步：提交整改（commit / 版本 / 工单至少一项）',
    FIXED: '下一步：发起真实复测（重新判分不能作为验证证据）',
    VERIFYING: unmet.length
      ? `六条件尚缺 ${unmet.length} 项：待复测运行到成功终态且原失败项达标后方可验证`
      : '六条件已满足：可由具备验证权限者执行「验证通过」关闭',
    REOPENED: '下一步：针对重开原因重新提交整改',
    CLOSED: '已闭环。若问题复现，可填写原因重开（追加事件，不改写历史）',
  }[status] || ''

  // ------------------------------------------------------------------ 动作
  const doRemediation = async () => {
    const v = await remForm.validateFields()
    const refs = {
      commit: (v.commit || '').trim(),
      version: (v.version || '').trim(),
      ticket: (v.ticket || '').trim(),
      refs: (v.refs || '').trim(),
    }
    if (!Object.values(refs).some((x) => x)) {
      message.warning('ES-BIZ-DEFECT-0010：整改必须提供变更引用（commit / 版本 / 工单 / 其他引用至少一项），否则无法追溯修复内容')
      return
    }
    setSaving(true)
    try {
      await es11.submitRemediation(defectId, {
        change_refs: refs,
        note: v.note || undefined,
        impact_scope: v.impact_scope || undefined,
      })
      message.success('整改已提交，状态进入「已修复」')
      setRemOpen(false)
      load()
    } catch (e) {
      if (!e?.message) message.error('提交整改失败，请稍后在闭环页重试')
    } finally {
      setSaving(false)
    }
  }

  // 复测后台执行轮询（ES11：retest 端点异步化，5s 查运行终态→刷新时间线）
  const pollTimer = useRef(null)
  const stopPolling = useCallback(() => {
    if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null }
  }, [])
  const startRunPolling = useCallback((runId) => {
    stopPolling()
    pollTimer.current = setInterval(async () => {
      try {
        const r = await http.get(`/eval-runs/${runId}`)
        if (r?.status && r.status !== 'RUNNING') {
          stopPolling()
          message.success(`复测运行已完成：${RUN_STATUS_LABEL[r.status] || r.status}（可发起验证）`)
          load()
        }
      } catch (e) { /* 瞬时错误忽略，下个周期重试 */ }
    }, 5000)
  }, [stopPolling, load, message])
  useEffect(() => stopPolling, [stopPolling])
  // 刷新页面场景：时间线最近一次复测运行仍 RUNNING 时自动恢复轮询
  useEffect(() => {
    if (pollTimer.current) return
    const last = [...events].reverse()
      .find((e) => e.event_type === 'RETEST_STARTED' && e.run)
    if (last?.run?.status === 'RUNNING') startRunPolling(last.run.id)
  }, [events, startRunPolling])

  const doRetest = async () => {
    const v = await retestForm.validateFields()
    setSaving(true)
    try {
      const d = await es11.startRetest(defectId, { note: v.note || undefined })
      const run = d?.retest_run || d?.run || (d?.id ? { id: d.id } : null)
      const runId = d?.retest_run?.id ?? d?.run?.id ?? d?.run_id
      setRetestOpen(false)
      const running = run?.status === 'RUNNING'
      modal.success({
        title: `复测运行 ${run?.run_no || '#' + (runId ?? '-')} 已${running ? '启动（后台执行中）' : '执行'}`,
        content: (
          <div>
            <div>状态：{RUN_STATUS_LABEL[run?.status] || run?.status || '-'}
              {'  '}结论：{VERDICT_LABEL[String(run?.verdict || '').toUpperCase()] || run?.verdict || '-'}</div>
            <div style={{ marginTop: 6 }}>
              {running
                ? '真实复测在后台执行，可在复测运行页查看进度；完成后缺陷方可验证关闭（六条件：复测成功终态且原失败项达标）。'
                : '缺陷已进入「验证中」。关闭前须满足六条件：复测成功终态且原失败项达标。'}
            </div>
          </div>
        ),
        okText: runId ? (running ? '查看执行进度' : '查看复测运行') : '知道了',
        onOk: () => { if (runId) navigate(`/eval/runs/${runId}`) },
      })
      if (running && runId) startRunPolling(runId)
      load()
    } catch (e) {
      if (e?.code === 'ES-BIZ-DEFECT-0013') {
        modal.warning({
          title: '无法自动绑定复测题目（ES-BIZ-DEFECT-0013）',
          content: '该缺陷没有可用的来源运行项（或来源题目已删除）。修复路径：在运行工作区「题级证据」中从失败题重新转缺陷，或联系管理员手选题目复测。',
          okText: '返回评测中心',
          onOk: () => navigate('/eval'),
        })
      } else if (!e?.message) message.error('发起复测失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  const doVerify = (result) => {
    const pass = result === 'PASS'
    modal.confirm({
      title: pass ? '验证通过并关闭缺陷' : '验证失败并重新打开',
      content: pass
        ? '六条件已全部满足。确认后将追加 VERIFIED 事件、状态进入 CLOSED（只追加、不可改写）。若整改人与验证人为同一人，将留痕「职责未分离」。'
        : '确认后将追加 REOPENED 事件，缺陷回到「重新打开」，需重新提交整改并再次复测。此操作会记录在闭环时间线上，不可删除。',
      okText: pass ? '确认通过并关闭' : '确认验证失败',
      okButtonProps: pass ? undefined : { danger: true },
      onOk: async () => {
        try {
          const d = await es11.verifyDefect(defectId, { result })
          load()
          if (pass && d?.duty_unseparated) {
            modal.warning({
              title: '已关闭，但留痕「职责未分离」',
              content: '本次整改人与验证人为同一账号。关闭仍然有效，该标记供 G3 审计追溯；建议后续由不同角色执行验证。',
            })
          }
        } catch (e) {
          // 拦截器已弹后端原因（如 ES-BIZ-VERIFY-0001），此处仅防 unhandled rejection
        }
      },
    })
  }

  const doReopen = async () => {
    const v = await reopenForm.validateFields()
    setSaving(true)
    try {
      await es11.reopenDefect(defectId, { reason: v.reason.trim() })
      message.success('缺陷已重开（REOPENED），原关闭记录保留')
      setReopenOpen(false)
      load()
    } catch (e) {
      if (!e?.message) message.error('重开失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  const doWaive = async () => {
    const v = await waiveForm.validateFields()
    setSaving(true)
    try {
      await es11.waiveDefect(defectId, {
        reason: v.reason.trim(),
        deadline: v.deadline?.trim() || undefined,
      })
      message.success('已记录风险接受（WAIVED），G4 该项豁免放行；缺陷仍未闭环，可随时继续整改')
      setWaiveOpen(false)
      waiveForm.resetFields()
      load()
    } catch (e) {
      if (!e?.message) message.error('风险接受提交失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  // ---------------------------------------------------------------- 渲染
  if (loading && !tl) {
    return <Card style={{ textAlign: 'center', padding: 48 }}><Spin tip="加载闭环时间线…" /></Card>
  }
  if (!tl) {
    return (
      <Card>
        <Alert type="error" showIcon message="缺陷闭环数据加载失败"
          description={`${loadErr || '未知错误'}。请确认缺陷 ID 有效且未被删除。`}
          action={
            <Space direction="vertical">
              <Button size="small" icon={<ReloadOutlined />} onClick={load}>重试</Button>
              <Button size="small" type="primary" onClick={() => navigate('/defects')}>返回缺陷管理</Button>
            </Space>
          }
        />
      </Card>
    )
  }

  const sevColor = (s) => (s === 'P0' || s === 'P1' ? 'red' : s ? 'orange' : 'default')

  const timelineCol = (
    <Card size="small" title="闭环时间线（只追加，不可覆盖）"
      extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>{events.length} 个事件</Typography.Text>}>
      {events.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无闭环事件">
          <Button type="primary" size="small" icon={<SendOutlined />} onClick={() => { remForm.resetFields(); setRemOpen(true) }}>
            提交整改
          </Button>
        </Empty>
      ) : (
        <Timeline
          items={events.map((e) => ({
            color: EVENT_DOT[e.event_type] || 'gray',
            children: (
              <div style={{ paddingBottom: 4 }}>
                <Space size={8} wrap>
                  <Typography.Text style={{ color: ES.ink, fontWeight: 600 }}>
                    {EVENT_LABEL[e.event_type] || e.event_type}
                  </Typography.Text>
                  {e.status_from && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {`${STATUS_LABEL[e.status_from] || e.status_from} → ${STATUS_LABEL[e.status_to] || e.status_to || '-'}`}
                    </Typography.Text>
                  )}
                </Space>
                <div style={{ color: ES.sub, fontSize: 12, marginTop: 2 }}>
                  {e.actor_name || '-'} · {fmtTime(e.created_at)}
                  {e.project_version_id != null && (
                    <> · <Mono color={ES.sub}>v#{e.project_version_id}</Mono></>
                  )}
                </div>
                {e.run && (
                  <div style={{ marginTop: 4 }}>
                    <a onClick={() => navigate(`/eval/runs/${e.run.id}`)}>
                      <Mono>{e.run.run_no || `RUN-${e.run.id}`}</Mono>
                    </a>
                    <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                      {e.run.run_purpose === 'RETEST' ? '复测运行' : '关联运行'} ·
                      {RUN_STATUS_LABEL[e.run.status] || e.run.status || '-'}
                      {e.run.verdict ? ` · ${VERDICT_LABEL[String(e.run.verdict).toUpperCase()] || e.run.verdict}` : ''}
                    </Typography.Text>
                  </div>
                )}
                {e.note && (
                  <div style={{ marginTop: 4, color: '#b8c7d4', fontSize: 12.5 }}>
                    <ClipText text={e.note} rows={2} />
                  </div>
                )}
                {e.evidence != null && (
                  <EvidencePanel title="事件证据" style={{ marginTop: 6, padding: 10 }}>
                    <ClipText text={toText(e.evidence)} rows={2} mono />
                  </EvidencePanel>
                )}
              </div>
            ),
          }))}
        />
      )}
    </Card>
  )

  const changeRefs = remEv?.evidence?.change_refs || {}
  const refRows = [
    ['代码提交', changeRefs.commit], ['修复版本', changeRefs.version],
    ['工单编号', changeRefs.ticket], ['其他引用', changeRefs.refs],
  ].filter(([, v]) => v)

  const stageCol = (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      {(status === 'NEW' || status === 'OPEN' || status === 'REOPENED') && (
        <Card size="small" title="缺陷内容">
          {detail ? (
            <Space direction="vertical" size={10} style={{ width: '100%' }}>
              <Descriptions size="small" column={1} items={[
                { key: 'sev', label: '严重度 / 优先级', children: `${detail.severity || '-'} / ${detail.priority === 'HIGH' ? '高' : detail.priority === 'LOW' ? '低' : '中'}` },
                { key: 'asg', label: '指派给', children: detail.assignee_name || '-' },
                { key: 'mod', label: '模块', children: detail.module || '-' },
                { key: 'req', label: '关联需求', children: detail.requirement_id || '-' },
              ]} />
              <EvidencePanel title="实际表现">
                <ClipText text={detail.actual} rows={4} mono />
              </EvidencePanel>
              <EvidencePanel title="预期表现">
                <ClipText text={detail.expected} rows={3} />
              </EvidencePanel>
              {Array.isArray(detail.reproduce_steps) && detail.reproduce_steps.length > 0 && (
                <EvidencePanel title="复现步骤">
                  {detail.reproduce_steps.map((s, i) => (
                    <div key={i} style={{ color: ES.ink, fontSize: 12.5 }}>{i + 1}. {toText(s)}</div>
                  ))}
                </EvidencePanel>
              )}
              {Array.isArray(detail.evidence) && detail.evidence.length > 0 && (
                <EvidencePanel title="原始证据">
                  {detail.evidence.map((x, i) => (
                    <div key={i} style={{ borderBottom: i < detail.evidence.length - 1 ? `1px solid ${ES.line}` : 'none', paddingBottom: 6, marginBottom: 6 }}>
                      <ClipText text={toText(x)} rows={2} />
                    </div>
                  ))}
                </EvidencePanel>
              )}
              {detail.fix_suggestion && (
                <EvidencePanel title="修复建议"><ClipText text={detail.fix_suggestion} rows={3} /></EvidencePanel>
              )}
            </Space>
          ) : (
            <Alert type="warning" showIcon message="缺陷基础信息加载失败"
              description="闭环时间线不受影响；可点击下方「重试」重新加载缺陷内容。"
              action={<Button size="small" onClick={load}>重试</Button>} />
          )}
        </Card>
      )}

      {status === 'FIXED' && (
        <Card size="small" title="整改内容（最近一次提交整改事件）">
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            {refRows.length ? (
              <Descriptions size="small" column={1} bordered
                items={refRows.map(([k, v], i) => ({ key: `r${i}`, label: k, children: <Mono>{String(v)}</Mono> }))} />
            ) : (
              <Typography.Text type="secondary">（变更引用缺失，请重新提交整改补充）</Typography.Text>
            )}
            {remEv?.evidence?.impact_scope != null && (
              <EvidencePanel title="影响范围"><ClipText text={toText(remEv.evidence.impact_scope)} rows={3} /></EvidencePanel>
            )}
            {remEv?.note && <EvidencePanel title="整改说明"><ClipText text={remEv.note} rows={4} /></EvidencePanel>}
            <Alert type="info" showIcon
              message="下一步：发起真实复测"
              description="复测将继承原运行配置、绑定原失败题真实调用被测系统；仅重新判分不能作为验证证据。" />
          </Space>
        </Card>
      )}

      {status === 'VERIFYING' && (
        <Card size="small"
          title={<Space>关闭六条件 <GateBadge status={unmet.length ? 'BLOCK' : 'PASS'}
            text={`${conditions.length - unmet.length}/${conditions.length}`} /></Space>}
          extra={rtEv?.run && (
            <a onClick={() => navigate(`/eval/runs/${rtEv.run.id}`)}>
              <Mono>{rtEv.run.run_no || `RUN-${rtEv.run.id}`}</Mono>
              <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
                {RUN_STATUS_LABEL[rtEv.run.status] || rtEv.run.status}
              </Typography.Text>
            </a>
          )}
        >
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            {rtEv?.run?.status && rtEv.run.status !== 'SUCCESS' && rtEv.run.status !== 'PASSED' && (
              <Alert type="info" showIcon
                message={`复测运行当前状态：${RUN_STATUS_LABEL[rtEv.run.status] || rtEv.run.status}`}
                description="复测到达成功终态前，「验证通过」保持禁用；可进入运行工作区查看执行进度与题级证据。" />
            )}
            <GateChecklist checks={checks} />
            {unmet.length > 0 && (
              <Alert type="error" showIcon message="以下条件未满足，无法关闭"
                description={unmet.map((c) => (
                  <div key={c}><Mono color={ES.BLOCK}>{c}</Mono>{` ${conditions.find((x) => x.code === c)?.desc || ''}`}</div>
                ))} />
            )}
          </Space>
        </Card>
      )}

      {status === 'CLOSED' && (
        <Card size="small" title="关闭记录">
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Descriptions size="small" column={1} bordered items={[
              { key: 'vres', label: '验证结论', children: <Tag color="green">通过</Tag> },
              { key: 'vrun', label: '复测运行', children: verEv?.evidence?.retest_run_no ? <Mono>{verEv.evidence.retest_run_no}</Mono> : '-' },
              { key: 'vduty', label: '职责分离', children: dutyUnsep ? <Tag color="orange">职责未分离（留痕）</Tag> : <Tag color="green">已分离</Tag> },
              ...(verEv?.note ? [{ key: 'vnote', label: '验证说明', children: verEv.note }] : []),
            ]} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              关闭时间：{fmtTime(verEv?.created_at)} · 验证人：{verEv?.actor_name || '-'}。历史事件不可改写；如需返工请使用「重开」。
            </Typography.Text>
          </Space>
        </Card>
      )}

      <Card size="small" styles={{ body: { background: ES.bg } }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <Typography.Text style={{ color: ES.accent, fontSize: 13 }}>{nextHint}</Typography.Text>
          <Space size={8} wrap>
            {(status === 'NEW' || status === 'OPEN' || status === 'REOPENED') && (
              <Button type="primary" icon={<SendOutlined />}
                onClick={() => { remForm.resetFields(); setRemOpen(true) }}>提交整改</Button>
            )}
            {status === 'FIXED' && (
              <Button type="primary" icon={<RedoOutlined />}
                onClick={() => { retestForm.resetFields(); setRetestOpen(true) }}>发起复测</Button>
            )}
            {status === 'VERIFYING' && (
              <>
                <Tooltip title={unmet.length ? `六条件未满足：${unmet.join('、')}` : '追加 VERIFIED 事件并进入 CLOSED'}>
                  <Button type="primary" icon={<CheckCircleOutlined />} disabled={unmet.length > 0}
                    onClick={() => doVerify('PASS')}>验证通过</Button>
                </Tooltip>
                <Button danger icon={<CloseCircleOutlined />} onClick={() => doVerify('FAIL')}>验证失败</Button>
              </>
            )}
            {status === 'CLOSED' && (
              <Button danger onClick={() => { reopenForm.resetFields(); setReopenOpen(true) }}>重开</Button>
            )}
            {status !== 'CLOSED' && (defect.severity === 'P0' || defect.severity === 'P1') && (
              <Tooltip title="不闭环但豁免 G4 交付阻断（ES11-G4-004）：追加 WAIVED 事件留痕豁免人/原因；后续重开自动失效">
                <Button icon={<StopOutlined />}
                  onClick={() => { waiveForm.resetFields(); setWaiveOpen(true) }}>风险接受</Button>
              </Tooltip>
            )}
          </Space>
        </div>
      </Card>
    </Space>
  )

  return (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      <Card styles={{ body: { background: ES.bg, borderRadius: 8 } }} style={{ border: `1px solid ${ES.line}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ minWidth: 0 }}>
            <Space size={8} wrap>
              <Button size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate('/defects')}>缺陷管理</Button>
              <Mono>{defect.defect_no || `DEF-${defectId}`}</Mono>
              <Typography.Text style={{ color: ES.ink, fontSize: 17, fontWeight: 600 }}>
                {defect.title || '（无标题）'}
              </Typography.Text>
              {defect.severity && <Tag color={sevColor(defect.severity)}>{defect.severity}</Tag>}
              <Tag color={STATUS_COLOR[status] || 'default'}>{STATUS_LABEL[status] || status || '-'}</Tag>
              {dutyUnsep && (
                <Tooltip title="最近一次整改人与验证人为同一账号，仅供 G3 审计留痕，不阻断流程">
                  <Tag color="orange">职责未分离</Tag>
                </Tooltip>
              )}
            </Space>
            <div style={{ marginTop: 6, color: ES.sub, fontSize: 12.5 }}>
              来源：{defect.origin?.type === 'RUN_ITEM' ? (
                <a onClick={() => navigate(`/eval/runs/${defect.origin.run_id}`)}>
                  <Mono>运行 #{defect.origin.run_id} · 题 #{defect.origin.question_id ?? '-'}</Mono>
                </a>
              ) : defect.origin?.type === 'TRACE' ? (
                <Mono color={ES.sub}>Trace #{defect.origin.trace_id}</Mono>
              ) : defect.origin?.type === 'SRC' ? (
                <a onClick={() => navigate('/src-audit')}><Mono>代码审计发现项 #{defect.origin.finding_id}</Mono></a>
              ) : '手工创建'}
              {'  '}|{'  '}目标版本：{defect.target_version_id != null ? <Mono color={ES.sub}>v#{defect.target_version_id}</Mono> : '-'}
              {'  '}|{'  '}报告：{defect.report_id != null ? `#${defect.report_id}` : '-'}
              {'  '}|{'  '}创建时间：{fmtTime(detail?.created_at)}
            </div>
          </div>
          <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
        </div>
      </Card>

      <Row gutter={14} align="top">
        <Col xs={24} lg={10} style={{ marginBottom: 14 }}>{timelineCol}</Col>
        <Col xs={24} lg={14}>{stageCol}</Col>
      </Row>

      {/* 提交整改 */}
      <Modal open={remOpen} title="提交整改（状态 → 已修复）" width={620} destroyOnHidden
        onCancel={() => setRemOpen(false)} onOk={doRemediation} okButtonProps={{ loading: saving }}>
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="变更引用（commit / 版本 / 工单 / 其他引用）至少填写一项，否则后端拒绝（ES-BIZ-DEFECT-0010）" />
        <Form form={remForm} layout="vertical">
          <Space style={{ display: 'flex' }} size={12}>
            <Form.Item name="commit" label="代码提交" style={{ flex: 1 }}><Input maxLength={200} placeholder="commit hash" /></Form.Item>
            <Form.Item name="version" label="修复版本" style={{ flex: 1 }}><Input maxLength={200} placeholder="版本号" /></Form.Item>
          </Space>
          <Space style={{ display: 'flex' }} size={12}>
            <Form.Item name="ticket" label="工单编号" style={{ flex: 1 }}><Input maxLength={200} placeholder="如 ISSUE-123" /></Form.Item>
            <Form.Item name="refs" label="其他引用" style={{ flex: 1 }}><Input maxLength={500} placeholder="PR / 文档链接等" /></Form.Item>
          </Space>
          <Form.Item name="impact_scope" label="影响范围"><Input maxLength={500} placeholder="受影响模块 / 接口（可选）" /></Form.Item>
          <Form.Item name="note" label="整改说明"><Input.TextArea rows={3} maxLength={2000} showCount placeholder="修复了什么、怎么修的（可选）" /></Form.Item>
        </Form>
      </Modal>

      {/* 发起复测 */}
      <Modal open={retestOpen} title="发起真实复测（状态 → 验证中）" destroyOnHidden
        onCancel={() => setRetestOpen(false)} onOk={doRetest} okButtonProps={{ loading: saving }}>
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="复测将继承原运行配置并绑定缺陷来源的失败题目，真实调用被测系统"
          description="若缺陷无来源运行项或来源题目已删除，将返回 ES-BIZ-DEFECT-0013，请按提示改从运行工作区转缺陷。" />
        <Form form={retestForm} layout="vertical">
          <Form.Item name="note" label="复测说明"><Input.TextArea rows={2} maxLength={2000} placeholder="可选" /></Form.Item>
        </Form>
      </Modal>

      {/* 重开 */}
      <Modal open={reopenOpen} title="重开已关闭缺陷" destroyOnHidden
        onCancel={() => setReopenOpen(false)} onOk={doReopen}
        okButtonProps={{ loading: saving, danger: true }}>
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="重开将追加 REOPENED 事件（状态 → 重新打开），原关闭记录保留、不可改写" />
        <Form form={reopenForm} layout="vertical">
          <Form.Item name="reason" label="重开原因" rules={[{ required: true, whitespace: true, message: '必须填写重开原因' }]}>
            <Input.TextArea rows={3} maxLength={2000} showCount placeholder="为何关闭不成立（必填）" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 风险接受（WAIVED） */}
      <Modal open={waiveOpen} title="风险接受（不闭环，豁免 G4 交付阻断）" destroyOnHidden
        onCancel={() => setWaiveOpen(false)} onOk={doWaive} okButtonProps={{ loading: saving }}>
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="豁免记录进缺陷时间线与交付包清单（风险接受记录），豁免人即当前账号"
          description="缺陷保持未闭环状态，可随时继续整改→复测→关闭；豁免后若产生更新的「重新打开」事件，豁免自动失效。" />
        <Form form={waiveForm} layout="vertical">
          <Form.Item name="reason" label="接受理由（如：合成演示数据 / 残余风险已评估）"
            rules={[{ required: true, whitespace: true, message: '风险接受必须填写原因' }]}>
            <Input.TextArea rows={3} maxLength={2000} showCount placeholder="为何可接受该未闭环风险（必填，随事件留痕）" />
          </Form.Item>
          <Form.Item name="deadline" label="限期处置（可选）">
            <Input maxLength={64} placeholder="如 2026-12-31，写入豁免记录供台账跟踪" />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
