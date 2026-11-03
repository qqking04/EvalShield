/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES11 P9：在线质量 Trace 分诊工作台（/traces/:id 深链）。
// 概要 + 四动作分诊（标记误报/进入复核/转缺陷/脱敏入题库并回归）+ 血缘四组 + 证据轨详情。
// 无 :id 时降级为 Trace 选择列表；闭环状态由关联实体派生，reviewed 布尔位仅作兼容展示。
import { useCallback, useEffect, useState } from 'react'
import {
  Alert, App, Button, Card, Col, Descriptions, Empty, Form, Input, Modal,
  Result, Row, Select, Space, Table, Tag, Timeline, Tooltip, Typography,
} from 'antd'
import {
  ApiOutlined, AuditOutlined, BugOutlined, CheckCircleFilled,
  DatabaseOutlined, ExclamationCircleFilled,
  RightOutlined, StopOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import http from '../../api/http'
import * as es11 from '../../api/es11'
import { fmtTime } from '../../utils'
import { ES, EvidencePanel, Mono } from './gate'

const SOURCE_LABEL = { gateway: '网关留痕', ingest_api: 'API 推送' }
const EVAL_LABEL = { PENDING: '待评估', SCORED: '已评分', SKIPPED: '未抽样', FAILED: '评估失败' }
const REVIEW_STATUS_LABEL = { OPEN: '待指派', ASSIGNED: '已指派', DONE: '已完成', DISCARDED: '已废弃' }
const DEFECT_STATUS_LABEL = { NEW: '新建', OPEN: '处理中', FIXED: '已修复', VERIFYING: '待验证', REOPENED: '已重开', CLOSED: '已关闭' }
const RUN_STATUS_LABEL = { RUNNING: '执行中', PASSED: '通过', SUCCESS: '成功', FAILED: '失败', CANCELLED: '已取消' }
const SPLIT_OPTIONS = [
  { value: 'HOLDOUT', label: 'HOLDOUT（生产回流留出集，默认）' },
  { value: 'DEV', label: 'DEV（开发调试分层）' },
  { value: 'TEST', label: 'TEST（验收测试分层）' },
]
const SPAN_STAGE_LABEL = {
  user_input: '用户输入', safety_filter: '安全过滤', retrieval: '检索',
  tool_call: '工具调用', model_generation: '模型生成', post_process: '后处理', response: '响应',
}
const PRE_STYLE = {
  margin: 0, padding: 10, overflow: 'auto', maxHeight: 260,
  color: ES.ink, fontSize: 12, lineHeight: 1.6,
  whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontFamily: ES.mono,
}

// 血缘组：标题 + 条目列表（空态给下一步提示）
function LineageGroup({ title, hint, children }) {
  return (
    <Card size="small" title={title} style={{ height: '100%' }}>
      {children || <Typography.Text type="secondary" style={{ fontSize: 12 }}>{hint}</Typography.Text>}
    </Card>
  )
}

export default function TraceTriage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { message, modal } = App.useApp()

  // ---- 无 :id：Trace 选择列表 ----
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [listLoading, setListLoading] = useState(false)

  const loadList = useCallback((p = 1) => {
    setListLoading(true)
    http.get('/traces', { params: { page: p, page_size: 20 } })
      .then((d) => { setRows(d?.items || []); setTotal(d?.total || 0); setPage(p) })
      .catch(() => { setRows([]); setTotal(0) })
      .finally(() => setListLoading(false))
  }, [])

  useEffect(() => { if (!id) loadList(1) }, [id, loadList])

  // ---- 有 :id：详情 + 血缘 ----
  const [detail, setDetail] = useState(null)
  const [lineage, setLineage] = useState(null)
  const [loading, setLoading] = useState(false)
  const [notFound, setNotFound] = useState(false)

  const loadLineage = useCallback(() => {
    if (!id) return
    es11.getTraceLineage(id).then(setLineage).catch(() => {})
  }, [id])

  useEffect(() => {
    if (!id) return
    let alive = true
    setLoading(true)
    setNotFound(false)
    Promise.all([http.get(`/traces/${id}`), es11.getTraceLineage(id)])
      .then(([d, lin]) => { if (alive) { setDetail(d); setLineage(lin) } })
      .catch(() => { if (alive) setNotFound(true) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [id])

  // ---- 分诊动作结果反馈（事件流：动作 → 实体链接）----
  const [events, setEvents] = useState([])
  const pushEvent = (ev) => setEvents((prev) => [{ key: `${Date.now()}-${prev.length}`, ...ev }, ...prev])

  // 动作一：标记误报 —— 对该 Trace 关联的待处理复核项提交「改判」结论
  const [fpOpen, setFpOpen] = useState(false)
  const [fpForm] = Form.useForm()
  const pendingReview = (lineage?.review_items || []).find(
    (r) => r.status === 'OPEN' || r.status === 'ASSIGNED',
  )
  const submitFalsePositive = async () => {
    const v = await fpForm.validateFields().catch(() => null)
    if (!v) return
    try {
      await http.post(`/review/items/${pendingReview.id}/decision`, {
        verdict: 'reject', note: v.note || 'Trace 分诊：判定为评分误报',
      })
      pushEvent({
        type: 'success',
        text: `已按误报改判复核项 #${pendingReview.id}（维持原判=approve，改判=reject），复核项进入终态`,
        linkText: '查看复核队列', linkTo: '/review',
      })
      setFpOpen(false)
      fpForm.resetFields()
      loadLineage()
    } catch { /* 拦截器已提示原因，界面保持不变 */ }
  }

  // 动作二：进入复核 —— 跳转人工复核工作台（低分 Trace 由评分调度自动回流队列）
  const enterReview = () => {
    const items = lineage?.review_items || []
    if (items.length === 0) {
      // 无实体可链：留在本页给出原因与入口，避免跳转后反馈丢失
      pushEvent({
        type: 'warning',
        text: '该 Trace 尚无关联复核项：低分 Trace 由评分调度自动回流复核队列，请确认采样评分策略已启用且该 Trace 已完成评分',
        linkText: '仍前往复核队列', linkTo: '/review',
      })
      return
    }
    navigate('/review')
  }

  // 动作三：转缺陷（幂等：重复操作返回既有缺陷）
  const toDefect = () => {
    modal.confirm({
      title: '转缺陷',
      icon: <ExclamationCircleFilled style={{ color: ES.BLOCK }} />,
      content: '将基于该 Trace 创建缺陷记录（附请求/响应与评分证据），进入缺陷闭环流程（指派 → 整改 → 复测 → 验证）。操作幂等：此前已转过将返回既有缺陷，不会产生重复记录。',
      okText: '确认转缺陷',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          const d = await es11.traceToDefect(id, {})
          pushEvent({
            type: d.deduped ? 'info' : 'success',
            text: d.deduped
              ? `该 Trace 此前已转缺陷（幂等返回既有记录）：${d.defect_no}`
              : `已创建缺陷 ${d.defect_no}（来源=Trace #${id}，状态=新建）`,
            linkText: '查看缺陷', linkTo: `/defects/${d.defect_id}`,
          })
          loadLineage()
        } catch { /* 拦截器已提示 */ }
      },
    })
  }

  // 动作四：脱敏入题库并回归（promoteQuestion → launchRegression）
  const [pgOpen, setPgOpen] = useState(false)
  const [pgBusy, setPgBusy] = useState(false)
  const [pgForm] = Form.useForm()
  const [banks, setBanks] = useState([])
  const [targets, setTargets] = useState([])

  useEffect(() => {
    if (!pgOpen) return
    http.get('/question-banks', { params: { page_size: 100 } })
      .then((d) => setBanks((d?.items || d || []).filter((b) => !b.is_builtin)))
      .catch(() => setBanks([]))
    http.get('/targets', { params: { status: 'ACTIVE', page_size: 200 } })
      .then((d) => { const p = d?.data || d; setTargets(p.items || (Array.isArray(p) ? p : [])) })
      .catch(() => setTargets([]))
  }, [pgOpen])

  const promoteAndRegress = async () => {
    const v = await pgForm.validateFields().catch(() => null)
    if (!v) return
    setPgBusy(true)
    let promoted = null
    try {
      promoted = await es11.promoteQuestion(id, {
        question_bank_id: v.question_bank_id,
        split: v.split || 'HOLDOUT',
        category: v.category || undefined,
        note: v.note || undefined,
      })
      pushEvent({
        type: promoted.deduped ? 'info' : 'success',
        text: promoted.deduped
          ? `脱敏文本已存在于目标题库，复用既有候选题 #${promoted.question_id}（幂等去重）`
          : `已自动脱敏并生成候选题 #${promoted.question_id}（分层=${promoted.split || v.split}，请人工确认预期行为后正式入库）`,
        linkText: '查看题库', linkTo: `/question-banks/${v.question_bank_id}`,
      })
    } catch {
      setPgBusy(false)
      return // 入题库失败：不发起回归，弹窗保持可重试
    }
    try {
      const d = await es11.launchRegression(id, {
        question_ids: [promoted.question_id],
        target_id: v.target_id,
      })
      const run = d?.run || (d?.run_id ? { id: d.run_id } : null)
      pushEvent({
        type: 'success',
        text: `已发起 TRACE_REPLAY 回归运行${run?.run_no ? ` ${run.run_no}` : ''}（状态=${RUN_STATUS_LABEL[run?.status] || run?.status || '-'}）`,
        linkText: '查看运行', linkTo: run?.id ? `/eval/runs/${run.id}` : '/eval',
      })
      setPgOpen(false)
      pgForm.resetFields()
    } catch (e) {
      pushEvent({
        type: 'warning',
        text: `入题库已成功，但回归发起失败：${e?.message || '请检查被测系统注册状态'}。可重新打开本弹窗仅重试发起（入题库幂等不会产生重复题）`,
      })
    } finally {
      setPgBusy(false)
      loadLineage()
    }
  }

  // ---------------------------------------------------------------- 选择列表 ----
  if (!id) {
    return (
      <div style={{ padding: 16 }}>
        <Card
          size="small"
          title={<Space><ApiOutlined />在线质量 Trace 分诊<Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 'normal' }}>选择一条 Trace 进入分诊工作台</Typography.Text></Space>}
          extra={<Button size="small" onClick={() => loadList(page)}>刷新</Button>}
        >
          <Table
            size="small" rowKey="id" loading={listLoading} dataSource={rows}
            onRow={(r) => ({ onClick: () => navigate(`/traces/${r.id}`), style: { cursor: 'pointer' } })}
            pagination={{ current: page, pageSize: 20, total, showSizeChanger: false, onChange: loadList }}
            locale={{
              emptyText: (
                <Empty description="暂无回流 Trace：网关留痕或 API 推送产生 Trace 后，按采样策略评分并在此分诊">
                  <Button type="primary" onClick={() => navigate('/traces')}>查看在线评测与策略配置</Button>
                </Empty>
              ),
            }}
            columns={[
              { title: 'ID', dataIndex: 'id', width: 80 },
              { title: '发生时间', dataIndex: 'occurred_at', width: 170, render: fmtTime },
              { title: '来源', dataIndex: 'source', width: 100, render: (v) => <Tag>{SOURCE_LABEL[v] || v}</Tag> },
              { title: '模型', dataIndex: 'model', width: 150, ellipsis: true, render: (v) => v || '-' },
              { title: '评估', dataIndex: 'eval_status', width: 90, render: (v) => <Tag>{EVAL_LABEL[v] || v}</Tag> },
              { title: '请求预览', dataIndex: 'request_preview', ellipsis: true },
              { title: '', key: 'go', width: 90, render: (_, r) => <a onClick={(e) => { e.stopPropagation(); navigate(`/traces/${r.id}`) }}>分诊 <RightOutlined /></a> },
            ]}
          />
        </Card>
      </div>
    )
  }

  // ---------------------------------------------------------------- 详情视图 ----
  if (notFound && !loading) {
    return (
      <div style={{ padding: 16 }}>
        <Result
          status="warning"
          title={`Trace #${id} 不存在或不属于当前租户`}
          subTitle="深链可能来自已清理的历史数据；请从 Trace 列表重新选择。"
          extra={<Button type="primary" onClick={() => navigate('/traces')}>返回 Trace 列表</Button>}
        />
      </div>
    )
  }

  const lin = lineage || {}
  const spans = detail?.trace_payload?.spans
  const hasSpans = Array.isArray(spans) && spans.length > 0

  return (
    <div style={{ padding: 16 }}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* 概要 + 闭环标记 */}
        <Card
          size="small"
          title={
            <Space>
              <ApiOutlined />Trace #{id} 分诊
              {lin.loop_closed && (
                <Tag icon={<CheckCircleFilled />} color="success" style={{ fontWeight: 600 }}>闭环已达成</Tag>
              )}
            </Space>
          }
          extra={<Button size="small" onClick={() => navigate('/traces')}>返回列表</Button>}
          loading={loading}
        >
          <Descriptions size="small" column={4} items={[
            { key: 'src', label: '来源', children: <Tag>{SOURCE_LABEL[detail?.source] || detail?.source || '-'}</Tag> },
            { key: 'model', label: '模型', children: detail?.model || '-' },
            { key: 'occ', label: '发生时间', children: fmtTime(detail?.occurred_at) },
            { key: 'eval', label: '评估状态', children: <Tag>{EVAL_LABEL[detail?.eval_status || lin.eval_status] || detail?.eval_status || lin.eval_status || '-'}</Tag> },
            { key: 'overall', label: '质量分', children: detail?.overall != null ? String(detail.overall) : '-' },
            { key: 'proj', label: '归属项目', children: lin.project_id != null ? <Mono color={ES.sub}>#{lin.project_id}</Mono> : '-' },
            { key: 'sess', label: '会话引用', children: lin.session_id ? <Mono color={ES.sub}>{lin.session_id}</Mono> : '-' },
            { key: 'rev', label: '已回流(兼容位)', children: lin.reviewed ? '是' : '否' },
          ]} />
        </Card>

        {/* 分诊动作区（方案 P9 四动作） */}
        <Card size="small" title="分诊动作">
          <Space size={8} wrap>
            <Tooltip title={pendingReview ? '对该 Trace 关联的待处理复核项提交「改判」结论' : '无待处理关联复核项：低分 Trace 由评分调度自动回流复核队列'}>
              <Button icon={<StopOutlined />} disabled={!pendingReview} onClick={() => setFpOpen(true)}>标记误报</Button>
            </Tooltip>
            <Button icon={<AuditOutlined />} onClick={enterReview}>进入复核</Button>
            <Button icon={<BugOutlined />} danger onClick={toDefect}>转缺陷</Button>
            <Button type="primary" icon={<DatabaseOutlined />} onClick={() => setPgOpen(true)}>脱敏入题库并回归</Button>
          </Space>
          {events.length > 0 && (
            <Space direction="vertical" size={8} style={{ width: '100%', marginTop: 12 }}>
              {events.map((ev) => (
                <Alert
                  key={ev.key} type={ev.type} showIcon
                  message={
                    <Space size={8}>
                      <span>{ev.text}</span>
                      {ev.linkTo && (
                        <Button size="small" type="link" style={{ padding: 0 }} onClick={() => navigate(ev.linkTo)}>
                          {ev.linkText || '查看'} <RightOutlined />
                        </Button>
                      )}
                    </Space>
                  }
                />
              ))}
            </Space>
          )}
        </Card>

        {/* 血缘视图：复核项 / 题库样本 / 缺陷 / 回归运行 */}
        <Card
          size="small"
          title={<Space>血缘视图{lin.loop_closed
            ? <Tag icon={<CheckCircleFilled />} color="success">闭环已达成：全部关联缺陷已关闭</Tag>
            : <Tag color="default">闭环未达成：界面状态由关联实体派生</Tag>}</Space>}
        >
          <Row gutter={[12, 12]}>
            <Col xs={24} md={12}>
              <LineageGroup title={`关联复核项（${(lin.review_items || []).length}）`} hint="尚无关联复核项；低分 Trace 由评分调度自动回流">
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  {(lin.review_items || []).map((r) => (
                    <a key={r.id} onClick={() => navigate('/review')} style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Mono color={ES.ink}>复核项 #{r.id}</Mono>
                      <Tag>{REVIEW_STATUS_LABEL[r.status] || r.status}</Tag>
                    </a>
                  ))}
                </Space>
              </LineageGroup>
            </Col>
            <Col xs={24} md={12}>
              <LineageGroup title={`题库样本（${(lin.questions || []).length}）`} hint="尚未脱敏入题库；可用上方「脱敏入题库并回归」">
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  {(lin.questions || []).map((q) => (
                    <div key={q.id} style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Mono color={ES.ink}>题目 #{q.id}</Mono>
                      <Tag color="purple">{q.split || '-'}</Tag>
                    </div>
                  ))}
                </Space>
              </LineageGroup>
            </Col>
            <Col xs={24} md={12}>
              <LineageGroup title={`缺陷（${(lin.defects || []).length}）`} hint="尚未转缺陷；可用上方「转缺陷」（幂等）">
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  {(lin.defects || []).map((d) => (
                    <a key={d.id} onClick={() => navigate(`/defects/${d.id}`)} style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Mono>{d.defect_no}</Mono>
                      <Tag color={d.status === 'CLOSED' ? 'success' : 'warning'}>{DEFECT_STATUS_LABEL[d.status] || d.status}</Tag>
                    </a>
                  ))}
                </Space>
              </LineageGroup>
            </Col>
            <Col xs={24} md={12}>
              <LineageGroup title={`回归运行（${(lin.replay_runs || []).length}）`} hint="尚无 TRACE_REPLAY 运行">
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  {(lin.replay_runs || []).map((r) => (
                    <a key={r.id} onClick={() => navigate(`/eval/runs/${r.id}`)} style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Mono>{r.run_no}</Mono>
                      <span>
                        <Tag>{RUN_STATUS_LABEL[r.status] || r.status}</Tag>
                        {r.verdict && <Tag color={r.verdict === 'PASS' ? 'success' : 'error'}>{r.verdict}</Tag>}
                      </span>
                    </a>
                  ))}
                </Space>
              </LineageGroup>
            </Col>
          </Row>
        </Card>

        {/* 详情区：spans 时间线（无则标记仅最终输入输出）+ 证据轨 */}
        <Card size="small" title="处理轨迹与原始证据">
          {hasSpans ? (
            <Timeline
              items={spans.map((s, i) => ({
                color: i === spans.length - 1 ? ES.accent : 'gray',
                children: (
                  <Space direction="vertical" size={0}>
                    <Typography.Text style={{ color: ES.ink, fontSize: 13 }}>
                      {SPAN_STAGE_LABEL[s.stage || s.name] || s.name || s.op || `阶段 ${i + 1}`}
                    </Typography.Text>
                    <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>
                      <Mono color={ES.sub}>{s.started_at || s.start || s.ts ? fmtTime(s.started_at || s.start || s.ts) : '-'}</Mono>
                      {s.duration_ms != null ? ` · ${s.duration_ms}ms` : ''}
                      {s.status ? ` · ${s.status}` : ''}
                    </Typography.Text>
                  </Space>
                ),
              }))}
            />
          ) : (
            <Alert
              type="info" showIcon icon={<ExclamationCircleFilled />} style={{ marginBottom: 12 }}
              message="仅最终输入输出"
              description="该 Trace 未上报处理轨迹（spans），无法定位安全过滤/检索/工具调用等中间阶段；以下仅展示最终请求与响应。"
            />
          )}
          <Row gutter={12}>
            <Col xs={24} md={12}>
              <EvidencePanel title="REQUEST · 原始请求">
                <pre style={PRE_STYLE}>{detail?.request || '（空）'}</pre>
              </EvidencePanel>
            </Col>
            <Col xs={24} md={12}>
              <EvidencePanel title="RESPONSE · 原始响应">
                <pre style={PRE_STYLE}>{detail?.response || '（空）'}</pre>
              </EvidencePanel>
            </Col>
          </Row>
        </Card>
      </Space>

      {/* 标记误报确认弹窗（危险动作：说明影响范围） */}
      <Modal
        open={fpOpen} title="标记误报" okText="确认按误报改判" cancelText="取消"
        onOk={submitFalsePositive} onCancel={() => { setFpOpen(false); fpForm.resetFields() }}
      >
        <Alert
          type="warning" showIcon style={{ marginBottom: 12 }}
          message="影响范围"
          description={`将向复核项 #${pendingReview?.id ?? '-'} 提交「改判（reject）」结论：该复核项进入终态、计入复核完成度；误报判定不会自动转缺陷或入题库。`}
        />
        <Form form={fpForm} layout="vertical">
          <Form.Item name="note" label="判定备注">
            <Input.TextArea rows={3} maxLength={500} placeholder="说明误报理由（如评分模型误判、上下文缺失），将写入复核台账" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 脱敏入题库并回归 */}
      <Modal
        open={pgOpen} title="脱敏入题库并回归" okText="执行" cancelText="取消"
        confirmLoading={pgBusy} onOk={promoteAndRegress}
        onCancel={() => { setPgOpen(false); pgForm.resetFields() }}
        destroyOnClose
      >
        <Alert
          type="info" showIcon style={{ marginBottom: 12 }}
          message="请求文本将按 PII 规则库自动脱敏后入题库（默认 HOLDOUT 留出分层，保留来源 Trace 引用）；随后以该题对选定被测系统发起 TRACE_REPLAY 回归。"
        />
        <Form form={pgForm} layout="vertical" initialValues={{ split: 'HOLDOUT' }}>
          <Form.Item name="question_bank_id" label="目标题库" rules={[{ required: true, message: '请选择题库' }]}>
            <Select
              showSearch optionFilterProp="label" placeholder="搜索并选择题库（内置库不可写入，已隐藏）"
              notFoundContent={banks.length === 0 ? '暂无可写题库，请先到「被测对象 → 题库与覆盖度」创建' : '无匹配'}
              options={banks.map((b) => ({ value: b.id, label: `${b.name}（${b.question_count ?? 0} 题）` }))}
            />
          </Form.Item>
          <Form.Item name="split" label="分层" tooltip="生产回流样本默认进 HOLDOUT 留出集，避免污染开发调试分层">
            <Select options={SPLIT_OPTIONS} />
          </Form.Item>
          <Form.Item name="category" label="类别" tooltip="留空默认 TRACE_REFLOW">
            <Input maxLength={64} placeholder="TRACE_REFLOW（默认）" />
          </Form.Item>
          <Form.Item name="target_id" label="回归被测系统" rules={[{ required: true, message: '回归必须指定被测系统' }]}
            tooltip="来自被测系统注册表（ACTIVE）；未注册系统不可发起回归">
            <Select
              showSearch optionFilterProp="label" placeholder="搜索并选择已注册被测系统"
              notFoundContent={targets.length === 0 ? '注册表暂无 ACTIVE 系统，请先到「被测对象 → 被测系统」注册' : '无匹配'}
              options={targets.map((t) => ({ value: t.code, label: `${t.name}（${t.code}）` }))}
            />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} maxLength={500} placeholder="回流原因说明（可选）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
