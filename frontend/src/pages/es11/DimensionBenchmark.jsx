/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
/*
 * 优化12 §10.3：GBT45654-2025 合规对标页（/standards/gbt45654，perm eval:read）。
 * 叙事顺序即信息层级：⓪标准元信息 → ①五维雷达 → ②双轨覆盖矩阵 → ③缺口清单 → ④拒答双指标。
 * 数据分层：元信息/核定状态来自 GET /meta/standards（与 run 无关）；
 * 雷达/矩阵/缺口/拒答依赖选定 run 的 dimension-coverage（旧口径 run → coverage:null 灰态）。
 * 动效预算两处：雷达展开 400ms + 抽屉滑出（子组件），prefers-reduced-motion 降级。
 * 配色唯一令牌源 gate.jsx ES（F16），禁裸 hex。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Row, Col, Card, Space, Typography, Button, Select, Alert, Table, Tag, Tooltip,
  Drawer, Form, Input, InputNumber, Segmented, Spin, Empty,
} from 'antd'
import {
  ApartmentOutlined, SafetyCertificateOutlined, ApiOutlined, MinusOutlined,
  CheckCircleFilled, ExclamationCircleFilled, SyncOutlined,
} from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import {
  getStandardsDimensions, getRunDimensionCoverage, calibrateThresholds, listRuns,
} from '../../api/es11'
import { useAuth } from '../../auth'
import { fmtTime } from '../../utils'
import { usePrefersReducedMotion } from './usePrefersReducedMotion'
import { ES, GateBadge, Mono, EvidencePanel } from './gate'
import DimensionEvidenceDrawer from './DimensionEvidenceDrawer'

const pct = (v, digits = 1) => (v == null ? '-' : `${(v * 100).toFixed(digits)}%`)

const RUN_LABEL = { PENDING: '排队中', RUNNING: '执行中', PASSED: '已完成', SUCCESS: '已完成', FAILED: '已失败', ERROR: '异常' }
const TERMINAL = ['PASSED', 'SUCCESS', 'FAILED', 'ERROR']

/** 引擎三态（状态三通道：图标+文字+色）：EXECUTED / MISSING / N/A */
function EngineStateTag({ eng }) {
  if (eng.state === 'EXECUTED') {
    return (
      <Tooltip title={`引擎运行 ${eng.run_no || eng.run_id}（${RUN_LABEL[eng.status] || eng.status || ''}）`}>
        <span style={{ color: ES.PASS, fontSize: 12, whiteSpace: 'nowrap' }}>
          <CheckCircleFilled /> {eng.code} 已执行
        </span>
      </Tooltip>
    )
  }
  if (eng.state === 'MISSING') {
    return (
      <span style={{ color: ES.BLOCK, fontSize: 12, whiteSpace: 'nowrap' }}>
        <ExclamationCircleFilled /> {eng.code} 缺失
      </span>
    )
  }
  return (
    <span style={{ color: ES.sub, fontSize: 12, whiteSpace: 'nowrap' }}>
      <MinusOutlined /> {eng.code} N/A
    </span>
  )
}

/** ① 五维雷达：轴=维度加权合格率，系列1 实测（accent），系列2 核定阈值环（WARN 虚线）。 */
function DimensionRadar({ dimensions, reduced }) {
  const inds = dimensions.map((d) => {
    const calibrated = d.regulatory && d.subs?.some((s) => s.pass_threshold != null)
    return {
      name: calibrated ? d.dimension_name : `${d.dimension_name}\n待核定`,
      max: 1,
      _calibrated: calibrated,
    }
  })
  const actual = dimensions.map((d) => (d.dimension_rate == null ? '-' : Number(d.dimension_rate)))
  const threshold = dimensions.map((d) => {
    const ths = (d.subs || []).filter((s) => s.pass_threshold != null)
    if (!ths.length) return '-'
    const w = ths.reduce((a, s) => a + s.pass_threshold * (s.tested || 0), 0)
    const t = ths.reduce((a, s) => a + (s.tested || 0), 0)
    return t > 0 ? Number((w / t).toFixed(4)) : Number(ths[0].pass_threshold)
  })
  const option = {
    animation: !reduced,
    animationDuration: 400,
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const lines = dimensions.map((d, i) => {
          const ind = inds[i]
          const v = p.value?.[i]
          const vStr = v == null || v === '-' ? (ind._calibrated ? '无实测' : '待核定') : pct(v)
          return `${d.dimension_name}：${vStr}`
        })
        return `${p.seriesName}<br/>${lines.join('<br/>')}`
      },
    },
    radar: {
      indicator: inds,
      radius: '62%',
      splitNumber: 4,
      axisName: { color: ES.sub, fontSize: 12, lineHeight: 16 },
      splitLine: { lineStyle: { color: ES.line } },
      splitArea: { areaStyle: { color: ['transparent'] } },
      axisLine: { lineStyle: { color: ES.line } },
      axisTick: { show: false },
    },
    series: [{
      type: 'radar',
      data: [
        {
          name: '维度加权合格率（实测）', value: actual,
          lineStyle: { color: ES.accent, width: 2 },
          itemStyle: { color: ES.accent },
          areaStyle: { color: `${ES.accent}26` }, // accent @ 15% alpha（令牌派生，非第二配色）
          symbolSize: 5,
        },
        {
          name: '核定阈值环', value: threshold,
          lineStyle: { color: ES.WARN, width: 1.5, type: 'dashed' },
          itemStyle: { color: ES.WARN },
          symbolSize: 4,
        },
      ],
    }],
  }
  return <ReactECharts option={option} style={{ height: 360 }} notMerge lazyUpdate />
}

/** 阈值核定抽屉（超管）：PUT /api/standards/thresholds，422/403/409 以 e.message 呈现。 */
function CalibrateDrawer({ open, onClose, meta, onCalibrated }) {
  const [target, setTarget] = useState('threshold')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState('')
  const [form] = Form.useForm()

  useEffect(() => {
    if (open) { setErr(''); form.resetFields() }
  }, [open, form])

  const subOptions = useMemo(
    () => (meta?.mapping || []).map((m) => ({
      value: m.category_code, label: `${m.category_code} ${m.bank_category}（${m.dimension_name}）`,
    })),
    [meta],
  )

  const submit = async (dryRun) => {
    let values
    try { values = await form.validateFields() } catch { return }
    setSubmitting(true)
    setErr('')
    const body = target === 'threshold'
      ? {
          target: 'threshold', sub_code: values.sub_code,
          min_questions: values.min_questions ?? null,
          pass_threshold: values.pass_threshold != null ? values.pass_threshold / 100 : null,
          reviewer: values.reviewer, basis: values.basis, dry_run: !!dryRun,
        }
      : {
          target: 'refusal',
          refuse_pass_rate_min: values.refuse_pass_rate_min != null ? values.refuse_pass_rate_min / 100 : null,
          false_refuse_rate_max: values.false_refuse_rate_max != null ? values.false_refuse_rate_max / 100 : null,
          reviewer: values.reviewer, basis: values.basis, dry_run: !!dryRun,
        }
    try {
      const res = await calibrateThresholds(body)
      if (res?.dry_run) {
        setErr('')
        message_ok('试运行通过：未写入。核对后点「提交核定」落盘。')
      } else {
        message_ok('阈值核定已写入。')
        onCalibrated?.()
        onClose?.()
      }
    } catch (e) {
      setErr(e?.message || '核定失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  // 轻量成功提示（避免为此再引 antd message 全量样板）
  const [okTip, setOkTip] = useState('')
  const message_ok = (t) => {
    setOkTip(t)
    setTimeout(() => setOkTip(''), 4000)
  }

  return (
    <Drawer open={open} onClose={onClose} width={520} title="安全基本要求阈值核定" destroyOnClose>
      <Space direction="vertical" size={14} style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          写入 deploy/standards 事实源（带文件锁，409 表示并发核定，稍后重试）。核定后覆盖矩阵与门禁结论即时生效。
        </Typography.Text>
        <Segmented
          value={target}
          onChange={setTarget}
          options={[
            { value: 'threshold', label: '子类题量/合格率' },
            { value: 'refusal', label: '拒答率双指标' },
          ]}
        />
        {okTip && <Alert type="success" showIcon message={okTip} />}
        {err && <Alert type="error" showIcon message="核定未生效" description={err} />}
        <Form form={form} layout="vertical" requiredMark={false}>
          {target === 'threshold' && (
            <>
              <Form.Item name="sub_code" label="子类" rules={[{ required: true, message: '请选择子类' }]}>
                <Select showSearch options={subOptions} placeholder="如 A.3 商业违法违规" optionFilterProp="label" />
              </Form.Item>
              <Row gutter={12}>
                <Col span={12}>
                  <Form.Item name="min_questions" label="最小题量（题）" tooltip="低于该题量判 BLOCK；留空不改">
                    <InputNumber min={1} style={{ width: '100%' }} placeholder="未核定" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="pass_threshold" label="合格率阈值（%）" tooltip="写入按 /100 归一；留空不改">
                    <InputNumber min={0} max={100} style={{ width: '100%' }} placeholder="未核定" />
                  </Form.Item>
                </Col>
              </Row>
            </>
          )}
          {target === 'refusal' && (
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="refuse_pass_rate_min" label="应拒答拒答率下限（%）">
                  <InputNumber min={0} max={100} style={{ width: '100%' }} placeholder="未核定" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="false_refuse_rate_max" label="不应拒答误拒率上限（%）">
                  <InputNumber min={0} max={100} style={{ width: '100%' }} placeholder="未核定" />
                </Form.Item>
              </Col>
            </Row>
          )}
          <Form.Item name="reviewer" label="核定人" rules={[{ required: true, message: '核定人必填（留痕）' }]}>
            <Input maxLength={128} placeholder="姓名 / 工号" />
          </Form.Item>
          <Form.Item name="basis" label="核定依据" rules={[{ required: true, message: '核定依据必填（留痕）' }]}>
            <Input.TextArea maxLength={512} rows={2} placeholder="如：GB/T 45654—2025 §5.1 + 2026-10 评审会纪要" />
          </Form.Item>
        </Form>
        <Space>
          <Button loading={submitting} onClick={() => submit(true)}>试运行（不落盘）</Button>
          <Button type="primary" loading={submitting} onClick={() => submit(false)}>提交核定</Button>
        </Space>
      </Space>
    </Drawer>
  )
}

export default function DimensionBenchmark() {
  const [searchParams, setSearchParams] = useSearchParams()
  const reduced = usePrefersReducedMotion()
  const { user } = useAuth()
  const isSuper = !!user?.is_super_admin

  const [meta, setMeta] = useState(null)
  const [metaError, setMetaError] = useState('')
  const [metaLoading, setMetaLoading] = useState(true)

  const [runs, setRuns] = useState([])
  const [runId, setRunId] = useState(searchParams.get('run') ? Number(searchParams.get('run')) : null)
  const [coverage, setCoverage] = useState(null) // null=未加载; {standards_ver, coverage} 原样
  const [covLoading, setCovLoading] = useState(false)
  const [covError, setCovError] = useState('')

  const [drawerSub, setDrawerSub] = useState(null)
  const [calOpen, setCalOpen] = useState(false)

  const loadMeta = useCallback(() => {
    setMetaLoading(true)
    setMetaError('')
    getStandardsDimensions()
      .then((d) => setMeta(d))
      .catch((e) => { setMeta(null); setMetaError(e?.message || '标准元信息加载失败，请检查网络或稍后重试') })
      .finally(() => setMetaLoading(false))
  }, [])

  useEffect(() => { loadMeta() }, [loadMeta])

  useEffect(() => {
    listRuns({ page: 1, page_size: 20 })
      .then((d) => {
        const items = (d?.items || []).filter((r) => TERMINAL.includes(r.status))
        setRuns(items)
        setRunId((cur) => {
          if (cur) return cur
          return items[0]?.id ?? null // 默认最近一个终态运行
        })
      })
      .catch(() => setRuns([]))
  }, [])

  const loadCoverage = useCallback(() => {
    if (!runId) { setCoverage(null); return }
    setCovLoading(true)
    setCovError('')
    getRunDimensionCoverage(runId)
      .then((d) => setCoverage(d))
      .catch((e) => { setCoverage(null); setCovError(e?.message || '覆盖矩阵加载失败，请重试') })
      .finally(() => setCovLoading(false))
  }, [runId])

  useEffect(() => { loadCoverage() }, [loadCoverage])

  const changeRun = (id) => {
    setRunId(id)
    const next = new URLSearchParams(searchParams)
    if (id) next.set('run', String(id)); else next.delete('run')
    setSearchParams(next, { replace: true })
  }

  const cov = coverage?.coverage
  const dims = cov?.dimensions || []
  const isLegacyRun = coverage && cov == null && coverage.standards_ver
  const missingCount = meta?.thresholds_missing?.length ?? 0
  const calibrated = missingCount === 0 && !!meta?.loaded

  // ?tab=coverage 深链（RunWorkspace 出链）：矩阵渲染后滚动到锚点一次
  useEffect(() => {
    if (cov && searchParams.get('tab') === 'coverage') {
      const el = document.getElementById('coverage-matrix')
      if (el && typeof el.scrollIntoView === 'function') {
        el.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' })
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!cov])

  // ③ 缺口清单：矩阵行中 BLOCK / NOT_CONFIGURED 子类 + overall 暂存态提示
  const gapRows = useMemo(() => {
    const out = []
    dims.forEach((d) => {
      (d.subs || []).forEach((s) => {
        if (s.status === 'BLOCK' || s.status === 'NOT_CONFIGURED') {
          out.push({ ...s, key: s.sub_code, dimension_name: d.dimension_name })
        }
      })
    })
    return out
  }, [dims])

  const matrixColumns = [
    {
      title: '维度 / 子类', dataIndex: 'name', width: 250,
      render: (_, r) => (r.rowType === 'dim' ? (
        <Space size={6}>
          <GateBadge status={r.status} />
          <span style={{ color: ES.ink, fontWeight: 600 }}>{r.dimension_name}</span>
          {!r.regulatory && <Tag style={{ borderColor: ES.line }}><span style={{ color: ES.sub }}>非监管口径</span></Tag>}
        </Space>
      ) : (
        <span style={{ paddingLeft: 18 }}>
          <Mono color={ES.sub}>{r.sub_code}</Mono>
          <span style={{ color: ES.ink, marginLeft: 8 }}>{r.bank_category}</span>
        </span>
      )),
    },
    {
      title: '服务类型', dataIndex: 'service_type', width: 110,
      render: (v, r) => (r.rowType === 'dim' ? <span style={{ color: ES.sub }}>—</span> : (v || '—')),
    },
    {
      title: '题量 实测/核定', key: 'tested', width: 130,
      render: (_, r) => {
        const tested = r.rowType === 'dim' ? r.dimension_tested : r.tested
        const min = r.rowType === 'dim' ? null : r.min_questions
        return (
          <span style={{ fontFamily: ES.mono, color: min != null && tested < min ? ES.BLOCK : ES.ink }}>
            {tested ?? 0}
            {' / '}
            {min != null ? `≥${min}` : <span style={{ color: ES.sub }}>待核定</span>}
          </span>
        )
      },
    },
    {
      title: '合格率', dataIndex: 'rate', width: 90,
      render: (v, r) => {
        const rate = r.rowType === 'dim' ? r.dimension_rate : v
        const th = r.rowType === 'dim' ? null : r.pass_threshold
        const color = rate == null ? ES.sub : (th != null && rate < th ? ES.BLOCK : ES.PASS)
        return <span style={{ fontFamily: ES.mono, color }}>{pct(rate)}</span>
      },
    },
    {
      title: '阈值', key: 'threshold', width: 100,
      render: (_, r) => (r.rowType === 'dim'
        ? <span style={{ color: ES.sub }}>—</span>
        : (r.pass_threshold == null
          ? <span style={{ color: ES.sub }}>待核定</span>
          : <span style={{ fontFamily: ES.mono, color: ES.WARN }}>≥{pct(r.pass_threshold, 0)}</span>)),
    },
    {
      title: '要求引擎（执行状态）', key: 'engines', width: 260,
      render: (_, r) => {
        if (r.rowType === 'dim') {
          const codes = new Set()
          ;(r.subs || []).forEach((s) => (s.engines || []).forEach((e) => codes.add(e.code)))
          return <span style={{ color: ES.sub }}>{[...codes].join('、') || '—'}</span>
        }
        return (
          <Space size={10} wrap>
            {(r.engines || []).map((e) => <EngineStateTag key={e.code} eng={e} />)}
            {!r.engines?.length && <span style={{ color: ES.sub }}>未映射引擎</span>}
          </Space>
        )
      },
    },
    {
      title: '结论', dataIndex: 'status', key: 'concl', width: 100,
      render: (v) => <GateBadge status={v} />,
    },
  ]

  const flatRows = useMemo(() => {
    const rows = []
    dims.forEach((d) => {
      rows.push({ ...d, rowType: 'dim', status: d.dimension_status, key: `dim-${d.dimension_code}` })
      ;(d.subs || []).forEach((s) => rows.push({ ...s, rowType: 'sub', key: s.sub_code, dimension_code: d.dimension_code, service_type: s.service_type }))
    })
    return rows
  }, [dims])

  if (metaLoading && !meta) {
    return <Card><Spin style={{ display: 'block', margin: '48px auto' }} /></Card>
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* ⓪ 标准元信息卡 + 页头 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>合规对标 · GB(T) 安全基本要求</Typography.Title>
          <Typography.Text type="secondary">
            {meta?.standard ? `${meta.standard.code} · ${meta.standard.name}（${meta.standard.version}）` : '标准事实源未加载'}
          </Typography.Text>
        </div>
        <Space>
          {isSuper && <Button onClick={() => setCalOpen(true)}>阈值核定</Button>}
        </Space>
      </div>

      {metaError && (
        <Alert type="error" showIcon message="标准元信息加载失败" description={metaError}
          action={<Button size="small" onClick={loadMeta}>重试</Button>} />
      )}
      {!metaError && meta && (
        <Row gutter={[16, 16]}>
          <Col xs={24} md={8}>
            <Card size="small" title={<Space><SafetyCertificateOutlined style={{ color: ES.accent }} />核定状态</Space>}>
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <GateBadge
                  status={calibrated ? 'PASS' : 'WARN'}
                  text={calibrated ? '阈值全量核定' : `未核定子类 ${missingCount} 个`}
                  reason={meta?.standard?.source}
                />
                <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>
                  {calibrated
                    ? '出件门禁 G4 按核定阈值判定 PASS/BLOCK。'
                    : '阈值核定前：覆盖矩阵只展示、不阻断；出件门禁按「维度覆盖不足」保守阻断（仅监管维度）。'}
                </Typography.Text>
                {!calibrated && isSuper && (
                  <Button size="small" type="link" style={{ padding: 0 }} onClick={() => setCalOpen(true)}>
                    打开核定入口 ›
                  </Button>
                )}
                {!calibrated && !isSuper && (
                  <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>核定入口仅管理员可见。</Typography.Text>
                )}
              </Space>
            </Card>
          </Col>
          <Col xs={24} md={16}>
            <Card size="small" title={<Space><ApartmentOutlined style={{ color: ES.accent }} />维度与映射</Space>}
              extra={<Typography.Text style={{ color: ES.sub, fontSize: 12 }}>事实源 deploy/standards/tc260.yaml</Typography.Text>}>
              <Space size={[6, 6]} wrap>
                {(meta?.dimensions || []).map((d) => {
                  const subMiss = (d.subs || []).filter((s) => s.min_questions == null || s.pass_threshold == null).length
                  return (
                    <Tag key={d.dimension_code} style={{ borderColor: ES.line }}
                      title={`${d.dimension_name}（${d.subs?.length || 0} 子类）`}>
                      <span style={{ color: ES.ink }}>{d.dimension_name}</span>
                      <span style={{ color: ES.sub }}> {d.subs?.length || 0} 子类</span>
                      {subMiss > 0 && <span style={{ color: ES.WARN }}> · {subMiss} 待核定</span>}
                      {!d.regulatory && <span style={{ color: ES.sub }}> · 非监管</span>}
                    </Tag>
                  )
                })}
              </Space>
              {(meta?.statement?.delivery_qualifier || meta?.statement?.self_consistency_only) && (
                <EvidencePanel title="标准陈述" style={{ marginTop: 10 }}>
                  <Space direction="vertical" size={4}>
                    {meta.statement.delivery_qualifier && (
                      <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>{meta.statement.delivery_qualifier}</Typography.Text>
                    )}
                    {meta.statement.self_consistency_only && (
                      <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>{meta.statement.self_consistency_only}</Typography.Text>
                    )}
                  </Space>
                </EvidencePanel>
              )}
              {meta?.presets_error && (
                <Alert style={{ marginTop: 10 }} type="warning" showIcon
                  message="预设清单解析失败" description={`${meta.presets_error}（预设向导入口已置灰，标准元信息不受影响）`} />
              )}
            </Card>
          </Col>
        </Row>
      )}

      {/* run 选择器（雷达/矩阵/缺口/拒答的数据前提） */}
      <Card size="small">
        <Space wrap size={12} style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space size={8}>
            <ApiOutlined style={{ color: ES.accent }} />
            <Typography.Text style={{ color: ES.ink }}>覆盖数据源运行</Typography.Text>
            <Select
              style={{ minWidth: 340 }}
              placeholder={runs.length ? '选择终态运行' : '暂无终态运行'}
              value={runId ?? undefined}
              onChange={changeRun}
              loading={covLoading}
              options={runs.map((r) => ({
                value: r.id,
                label: `${r.run_no} · ${RUN_LABEL[r.status] || r.status} · ${fmtTime(r.created_at)}`,
              }))}
            />
          </Space>
          {cov && (
            <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>
              标准版本 <Mono>{cov.standards_ver || coverage?.standards_ver}</Mono>
              {cov?.activity_id ? <>　活动 <Mono>{String(cov.activity_id).slice(0, 8)}…</Mono></> : <>　<Typography.Text style={{ color: ES.WARN, fontSize: 12 }}>本运行未绑定评估活动（单运行视角）</Typography.Text></>}
            </Typography.Text>
          )}
        </Space>
      </Card>

      {covError && (
        <Alert type="error" showIcon message="覆盖矩阵加载失败" description={covError}
          action={<Button size="small" onClick={loadCoverage}>重试</Button>} />
      )}
      {isLegacyRun && (
        <Alert
          type="warning"
          showIcon
          message="该运行早于现行标准口径，不产维度覆盖结论"
          description={`运行标准版本「${coverage.standards_ver}」非 GBT45654 口径：雷达与矩阵不适用，请以现行口径重跑后查看覆盖结论。`}
        />
      )}
      {!cov && !covError && !isLegacyRun && !covLoading && (
        <Card>
          <Empty description={<span style={{ color: ES.sub }}>尚无可选终态运行。发起一次评测（建议走预设向导绑定评估活动），运行进入终态后即可查看五维覆盖结论。</span>}>
            <Button type="primary" onClick={() => { window.location.href = '/eval' }}>去发起评测 ›</Button>
          </Empty>
        </Card>
      )}

      {cov && (
        <>
          {/* ① 五维雷达 */}
          <Card size="small" title="维度加权合格率雷达（实测 vs 核定阈值环）">
            <DimensionRadar dimensions={dims} reduced={reduced} />
          </Card>

          {/* ② 双轨覆盖矩阵（?tab=coverage 深链锚点） */}
          <Card size="small" id="coverage-matrix"
            title="安全基本要求 · 双轨覆盖矩阵"
            extra={<Typography.Text style={{ color: ES.sub, fontSize: 12 }}>点击子类行查看证据 ›</Typography.Text>}>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={<span style={{ fontSize: 12 }}>{cov.disclaimer || '本矩阵为平台自动化判定，不替代监管认定与人类专家复核。'}</span>}
            />
            <Table
              size="small"
              rowKey="key"
              columns={matrixColumns}
              dataSource={flatRows}
              pagination={false}
              scroll={{ x: 1080 }}
              onRow={(r) => (r.rowType === 'sub' ? {
                onClick: () => setDrawerSub(r),
                tabIndex: 0,
                onKeyDown: (e) => { if (e.key === 'Enter') setDrawerSub(r) },
                style: { cursor: 'pointer' },
              } : { style: { background: ES.bg } })}
            />
          </Card>

          {/* ③ 缺口清单 */}
          <Card size="small" title={<span>缺口清单 <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>（仅阻塞级与未核定项，深链补题）</Typography.Text></span>}>
            {gapRows.length === 0 ? (
              <Typography.Text style={{ color: ES.sub }}>当前无阻塞/未核定缺口。</Typography.Text>
            ) : (
              <Table
                size="small"
                rowKey="sub_code"
                pagination={false}
                dataSource={gapRows}
                columns={[
                  { title: '维度', dataIndex: 'dimension_name', width: 160 },
                  { title: '子类', dataIndex: 'sub_code', width: 90, render: (v) => <Mono>{v}</Mono> },
                  { title: '分类', dataIndex: 'bank_category', ellipsis: true },
                  {
                    title: '缺口', key: 'gap',
                    render: (_, r) => (r.status === 'NOT_CONFIGURED'
                      ? <span style={{ color: ES.WARN }}>题量与合格率阈值未核定</span>
                      : <span style={{ color: ES.BLOCK }}>缺 {r.gap_questions ?? '?'} 题 / 合格率 {pct(r.rate)}（阈值 {pct(r.pass_threshold, 0)}）</span>),
                  },
                  { title: '结论', dataIndex: 'status', width: 90, render: (v) => <GateBadge status={v} /> },
                  {
                    title: '出路', key: 'fix', width: 140,
                    render: (_, r) => (r.status === 'NOT_CONFIGURED'
                      ? (isSuper
                        ? <Button size="small" type="link" style={{ padding: 0 }} onClick={() => setCalOpen(true)}>去核定 ›</Button>
                        : <Tooltip title="核定入口仅管理员可见"><span style={{ color: ES.sub }}>仅管理员可核定</span></Tooltip>)
                      : <Button size="small" type="link" style={{ padding: 0 }}
                          onClick={() => { window.location.href = `/eval?tab=banks&sub=${encodeURIComponent(r.sub_code)}` }}>补题 ›</Button>),
                  },
                ]}
              />
            )}
            {(cov.overall?.warn_items || []).length > 0 && (
              <div style={{ marginTop: 10 }}>
                {cov.overall.warn_items.map((w, i) => (
                  <div key={i} style={{ color: ES.WARN, fontSize: 12 }}><ExclamationCircleFilled /> {typeof w === 'string' ? w : (w.reason || w.code)}</div>
                ))}
              </div>
            )}
          </Card>

          {/* ④ 拒答双指标 */}
          {cov.refusal && (
            <Card size="small" title="拒答双指标（安全护栏）"
              extra={<Typography.Text style={{ color: ES.WARN, fontSize: 12 }}>阈值核定前只展示、不阻断</Typography.Text>}>
              <Row gutter={[16, 16]}>
                <Col xs={24} md={8}>
                  <MetricTile label="应拒答题目拒答率" value={pct(cov.refusal.refuse_pass_rate)}
                    threshold={cov.refusal.thresholds?.refuse_pass_rate_min != null ? `≥${pct(cov.refusal.thresholds.refuse_pass_rate_min, 0)}` : '待核定'}
                    ok={cov.refusal.thresholds?.refuse_pass_rate_min == null ? null : (cov.refusal.refuse_pass_rate ?? 0) >= cov.refusal.thresholds.refuse_pass_rate_min} />
                </Col>
                <Col xs={24} md={8}>
                  <MetricTile label="不应拒答题目误拒率" value={pct(cov.refusal.answer_false_refuse_rate)}
                    threshold={cov.refusal.thresholds?.false_refuse_rate_max != null ? `≤${pct(cov.refusal.thresholds.false_refuse_rate_max, 0)}` : '待核定'}
                    ok={cov.refusal.thresholds?.false_refuse_rate_max == null ? null : (cov.refusal.answer_false_refuse_rate ?? 1) <= cov.refusal.thresholds.false_refuse_rate_max} />
                </Col>
                <Col xs={24} md={8}>
                  <MetricTile label="攻击成功率（越低越好）" value={pct(cov.refusal.attack_success_rate)} threshold="—" ok={null} />
                </Col>
              </Row>
            </Card>
          )}
        </>
      )}

      <DimensionEvidenceDrawer
        open={!!drawerSub}
        sub={drawerSub}
        runId={runId}
        onClose={() => setDrawerSub(null)}
      />
      {isSuper && (
        <CalibrateDrawer open={calOpen} onClose={() => setCalOpen(false)} meta={meta} onCalibrated={loadMeta} />
      )}
    </Space>
  )
}

/** 拒答指标瓦片：数值+阈值+三通道状态。 */
function MetricTile({ label, value, threshold, ok }) {
  const m = ok == null ? { color: ES.sub, label: '只展示' } : (ok ? { color: ES.PASS, label: '达标' } : { color: ES.BLOCK, label: '未达标' })
  return (
    <div style={{ padding: '12px 14px', border: `1px solid ${ES.line}`, borderLeft: `3px solid ${m.color}`, borderRadius: 6, background: ES.bg }}>
      <div style={{ color: ES.sub, fontSize: 12 }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 6 }}>
        <span style={{ fontFamily: ES.mono, fontSize: 22, fontWeight: 700, color: m.color }}>{value}</span>
        <span style={{ color: ES.sub, fontSize: 12 }}>阈值 {threshold}</span>
        <span style={{ color: m.color, fontSize: 12, fontWeight: 600 }}>
          {ok == null ? '○' : ok ? '✓' : '✗'} {m.label}
        </span>
      </div>
    </div>
  )
}
