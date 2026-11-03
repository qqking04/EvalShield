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
 * ES11 质量总览（方案 §5.4 P1）：门禁驱动的可交付判断首屏。
 * 英雄区 = 上线结论三段（可交付/待复核/被阻塞，均可下钻）；四象限指标轨；最近活动表。
 * 禁虚荣指标：项目总数/任务总数一类数字已按 §5.4 明确删除，不得回填。
 */
import { useCallback, useEffect, useState } from 'react'
import { Row, Col, Card, Table, Space, Typography, Button, Segmented, Alert, Empty, Spin, Tag } from 'antd'
import {
  DashboardOutlined,
  WarningOutlined,
  RiseOutlined,
  AuditOutlined,
  RocketOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { getQualityOverview, listRuns, getStandardsDimensions } from '../../api/es11'
import { fmtTime } from '../../utils'
import { ES, ShipVerdict, statusMeta, Mono } from './gate'

const WINDOWS = [
  { value: 7, label: '近 7 天' },
  { value: 30, label: '近 30 天' },
  { value: 90, label: '近 90 天' },
]

// 活动目的（run_purpose 枚举，与后端 schemas.EvalRunCreate 对齐；优化12 §8.6 补 SCREENING）
const PURPOSE_LABEL = { STANDARD: '标准评测', REGRESSION: '版本回归', RETEST: '缺陷复测', TRACE_REPLAY: 'Trace 回流', SCREENING: '抽样探查' }

// 运行状态 → 门禁色轨（状态永不单靠颜色：图标 + 文字 + 色三通道）
const RUN_GATE = { PASSED: 'PASS', SUCCESS: 'PASS', FAILED: 'BLOCK', ERROR: 'BLOCK', RUNNING: 'WARN', PENDING: 'WARN' }
const RUN_LABEL = { PENDING: '排队中', RUNNING: '执行中', PASSED: '已完成', SUCCESS: '已完成', FAILED: '已失败', ERROR: '异常' }

const pct = (v, digits = 1) => (v == null ? '-' : `${(v * 100).toFixed(digits)}%`)

/** 指标瓦片：证据轨深色底，数字即下钻入口，色 = statusMeta。 */
function Metric({ label, value, status, hint, onClick }) {
  const m = statusMeta(status)
  return (
    <div
      onClick={onClick}
      style={{
        padding: '12px 14px', border: `1px solid ${ES.line}`, borderLeft: `3px solid ${m.color}`,
        borderRadius: 6, background: ES.bg, cursor: 'pointer',
      }}
    >
      <div style={{ color: ES.sub, fontSize: 12 }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 6 }}>
        <span style={{ fontFamily: ES.mono, fontSize: 24, fontWeight: 700, color: m.color, lineHeight: 1 }}>
          {value}
        </span>
        <span style={{ color: m.color, fontSize: 12, fontWeight: 600 }}>
          {m.icon} {m.label}
        </span>
      </div>
      {hint && <div style={{ color: ES.sub, fontSize: 12, marginTop: 6 }}>{hint}</div>}
    </div>
  )
}

/**
 * 优化12 §10.3：五维度达标状态摘要卡（GET /meta/standards 首个轻量消费者）。
 * 只展示标准级核定状态（5 状态格 + 进入链接），不依赖 run、不位移英雄区 ShipVerdict。
 */
function DimensionStatusCard({ stdMeta, onEnter }) {
  const official = (stdMeta.dimensions || []).filter((d) => d.regulatory)
  const missing = stdMeta.thresholds_missing?.length ?? 0
  return (
    <Card
      size="small"
      title={<Space><AuditOutlined style={{ color: ES.accent }} />GBT45654 五维度达标状态</Space>}
      extra={<Button type="link" size="small" onClick={onEnter}>进入合规对标 ›</Button>}
    >
      <Space size={[10, 10]} wrap>
        {official.map((d) => {
          const notConfigured = (d.subs || []).every((s) => s.min_questions == null && s.pass_threshold == null)
          const status = notConfigured ? 'UNKNOWN' : 'WARN'
          return (
            <span key={d.dimension_code} style={{ fontSize: 13 }}>
              {statusMeta(status).icon}{' '}
              <span style={{ color: ES.ink }}>{d.dimension_name}</span>{' '}
              <span style={{ color: statusMeta(status).color, fontSize: 12 }}>
                {notConfigured ? '阈值待核定' : '已核定（覆盖看对标页）'}
              </span>
            </span>
          )
        })}
        {missing > 0 && (
          <Typography.Text style={{ color: ES.WARN, fontSize: 12 }}>
            未核定子类 {missing} 个——核定前出件门禁按保守阻断。
          </Typography.Text>
        )}
      </Space>
    </Card>
  )
}

export default function QualityOverview() {
  const navigate = useNavigate()
  const [days, setDays] = useState(30)
  const [ov, setOv] = useState(null)
  const [ovError, setOvError] = useState('')
  const [loading, setLoading] = useState(true)
  const [runs, setRuns] = useState([])
  const [runsTotal, setRunsTotal] = useState(0)
  // 优化12 §10.3：五维度达标状态摘要卡（标准级事实，不依赖 run；失败静默降级不挂载）
  const [stdMeta, setStdMeta] = useState(null)

  const drill = (d) => d?.path && navigate(d.path)

  const load = useCallback(async (d) => {
    setLoading(true)
    setOvError('')
    try {
      setOv(await getQualityOverview(d))
    } catch (e) {
      setOv(null)
      setOvError(e?.message || '质量指标加载失败，请检查网络或稍后重试')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(days) }, [load, days])

  useEffect(() => {
    listRuns({ page: 1, page_size: 8 })
      .then((d) => { setRuns(d?.items || []); setRunsTotal(d?.total || 0) })
      .catch(() => { setRuns([]); setRunsTotal(0) })
  }, [])

  useEffect(() => {
    getStandardsDimensions()
      .then((d) => setStdMeta(d))
      .catch(() => setStdMeta(null))
  }, [])

  const mv = ov?.metrics
  const oldest = mv?.pending_review_items?.oldest_wait_hours
  const segments = mv
    ? [
        {
          key: 'deliverable', label: '可交付运行', value: mv.deliverable_runs?.value, status: 'PASS',
          hint: `窗口内终态运行 ${mv.deliverable_runs?.terminal_runs ?? 0} 个，门禁全绿方可计入`,
          drill: mv.deliverable_runs?.drill,
        },
        {
          key: 'pending', label: '待复核条目', value: mv.pending_review_items?.value,
          status: (mv.pending_review_items?.value ?? 0) > 0 ? 'WARN' : 'PASS',
          hint: oldest != null ? `最长已等待 ${oldest} 小时` : '复核队列无积压',
          drill: mv.pending_review_items?.drill,
        },
        {
          key: 'blocked', label: '被阻塞运行', value: mv.blocked_runs?.value,
          status: (mv.blocked_runs?.value ?? 0) > 0 ? 'BLOCK' : 'PASS',
          hint: `需复核 ${mv.blocked_runs?.review ?? 0} · 演示模式 ${mv.blocked_runs?.demo ?? 0}`,
          drill: mv.blocked_runs?.drill,
        },
      ]
    : []

  const closeRate = mv?.defect_verified_close_rate?.value
  const jh = mv?.judge_health
  const ls = mv?.low_score_trace_recurrence

  const columns = [
    {
      title: '场景', dataIndex: 'run_purpose', width: 110,
      render: (v) => PURPOSE_LABEL[v] || v || '标准评测',
    },
    {
      title: '被测系统', dataIndex: 'target_id', width: 180, ellipsis: true,
      render: (v) => <Mono color={ES.ink}>{v || '-'}</Mono>,
    },
    {
      title: '版本', dataIndex: 'version_no', width: 100,
      render: (v) => (v ? <Mono>{v}</Mono> : <Typography.Text type="secondary">—</Typography.Text>),
    },
    {
      title: '门禁', key: 'gates', width: 190,
      render: (_, r) => {
        const g0 = { PASS: { color: 'green', text: 'G0通过' }, BLOCKED: { color: 'red', text: 'G0阻塞' } }[r.g0_readiness]
          || { color: 'default', text: 'G0未知' }
        return (
          <Space size={4}>
            <Tag color={g0.color} style={{ marginInlineEnd: 0 }}>{g0.text}</Tag>
            {(r.review_pending || 0) > 0 && <Tag color="orange" style={{ marginInlineEnd: 0 }}>G2 待复核 {r.review_pending}</Tag>}
            {(r.open_p0p1 || 0) > 0 && <Tag color="red" style={{ marginInlineEnd: 0 }}>G3 P0/P1 {r.open_p0p1}</Tag>}
          </Space>
        )
      },
    },
    {
      title: '负责人', dataIndex: 'owner_name', width: 100, ellipsis: true,
      render: (v) => v || <Typography.Text type="secondary">—</Typography.Text>,
    },
    {
      title: '运行编号', dataIndex: 'run_no', width: 200,
      render: (v) => <Mono>{v}</Mono>,
    },
    {
      title: '状态', dataIndex: 'status', width: 110,
      render: (v) => {
        const g = statusMeta(RUN_GATE[v])
        return <span style={{ color: g.color, fontWeight: 600 }}>{g.icon} {RUN_LABEL[v] || v || '-'}</span>
      },
    },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v) => fmtTime(v) },
    {
      title: '下一动作', key: 'next', width: 120,
      render: (_, r) => (
        <Button type="link" size="small" onClick={() => navigate(`/eval/runs/${r.id}`)}>
          进入运行 ›
        </Button>
      ),
    },
  ]

  const isEmpty = !loading && !ovError && runsTotal === 0 && (mv?.deliverable_runs?.terminal_runs ?? 0) === 0

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>质量总览</Typography.Title>
          <Typography.Text type="secondary">
            统计窗口 {ov?.window_days ?? days} 天
            {ov?.generated_at ? ` · 生成于 ${fmtTime(ov.generated_at)}` : ''}
          </Typography.Text>
        </div>
        <Segmented options={WINDOWS} value={days} onChange={setDays} />
      </div>

      {ovError && (
        <Alert
          type="error"
          showIcon
          message="质量指标加载失败"
          description={ovError}
          action={<Button size="small" onClick={() => load(days)}>重试</Button>}
        />
      )}

      {loading && !ov && (
        <Card><Spin style={{ display: 'block', margin: '48px auto' }} /></Card>
      )}

      {isEmpty && (
        <Card>
          <Empty
            description={<span>尚无评测运行，质量结论需要先有证据。发起一次评测，平台将自动产出 G0–G4 门禁证据链。</span>}
            style={{ padding: '32px 0' }}
          >
            <Button type="primary" icon={<RocketOutlined />} onClick={() => navigate('/eval')}>
              发起第一次评测
            </Button>
          </Empty>
        </Card>
      )}

      {!loading && !ovError && !isEmpty && mv && (
        <>
          {stdMeta && (
            <DimensionStatusCard stdMeta={stdMeta} onEnter={() => navigate('/standards/gbt45654')} />
          )}

          <ShipVerdict segments={segments} onSelect={(s) => drill(s.drill)} />

          <Row gutter={[16, 16]}>
            <Col xs={24} md={12}>
              <Card size="small" title={<Space><DashboardOutlined style={{ color: ES.accent }} />活动状态轨</Space>}>
                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  <Metric
                    label="可交付运行" value={mv.deliverable_runs?.value ?? 0} status="PASS"
                    hint={`终态运行 ${mv.deliverable_runs?.terminal_runs ?? 0} 个`}
                    onClick={() => drill(mv.deliverable_runs?.drill)}
                  />
                  <Metric
                    label="被阻塞运行" value={mv.blocked_runs?.value ?? 0}
                    status={(mv.blocked_runs?.value ?? 0) > 0 ? 'BLOCK' : 'PASS'}
                    hint={`需复核 ${mv.blocked_runs?.review ?? 0} · 演示模式 ${mv.blocked_runs?.demo ?? 0}`}
                    onClick={() => drill(mv.blocked_runs?.drill)}
                  />
                  <Metric
                    label="最近版本回归" value={mv.recent_regression_runs?.value ?? 0} status="PASS"
                    hint="窗口内 run_purpose=REGRESSION 回归运行次数"
                    onClick={() => drill(mv.recent_regression_runs?.drill)}
                  />
                </Space>
              </Card>
            </Col>
            <Col xs={24} md={12}>
              <Card size="small" title={<Space><WarningOutlined style={{ color: ES.WARN }} />需要处理</Space>}>
                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  <Metric
                    label="待复核条目" value={mv.pending_review_items?.value ?? 0}
                    status={(mv.pending_review_items?.value ?? 0) > 0 ? 'WARN' : 'PASS'}
                    hint={oldest != null ? `最长已等待 ${oldest} 小时` : '复核队列无积压'}
                    onClick={() => drill(mv.pending_review_items?.drill)}
                  />
                  <Metric
                    label="未闭环 P0/P1 缺陷" value={mv.open_p0p1_defects?.value ?? 0}
                    status={(mv.open_p0p1_defects?.value ?? 0) > 0 ? 'BLOCK' : 'PASS'}
                    hint="P0/P1 未关闭将直接阻塞交付结论"
                    onClick={() => drill(mv.open_p0p1_defects?.drill)}
                  />
                  <Metric
                    label="已整改未验证" value={mv.remediated_unverified?.value ?? 0}
                    status={(mv.remediated_unverified?.value ?? 0) > 0 ? 'WARN' : 'PASS'}
                    hint="FIXED 停留态，需真实复测（RETEST）取证关闭"
                    onClick={() => drill(mv.remediated_unverified?.drill)}
                  />
                </Space>
              </Card>
            </Col>
            <Col xs={24} md={12}>
              <Card size="small" title={<Space><RiseOutlined style={{ color: ES.accent }} />版本风险变化</Space>}>
                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  <Metric
                    label="缺陷验证关闭率"
                    value={closeRate == null ? '暂无样本' : pct(closeRate)}
                    status={closeRate == null ? undefined : closeRate >= 0.9 ? 'PASS' : closeRate >= 0.7 ? 'WARN' : 'BLOCK'}
                    hint={`已验证缺陷 ${mv.defect_verified_close_rate?.verified_closed ?? 0}/${mv.defect_verified_close_rate?.verified_total ?? 0} 完成关闭`}
                    onClick={() => drill(mv.defect_verified_close_rate?.drill)}
                  />
                  <Metric
                    label="低分 Trace 复发" value={ls?.value ?? 0}
                    status={(ls?.value ?? 0) > 0 ? 'WARN' : 'PASS'}
                    hint={`同请求低分（overall < ${ls?.threshold ?? 0.5}）复发簇，涉及 ${ls?.traces ?? 0} 条线上 Trace`}
                    onClick={() => drill(ls?.drill)}
                  />
                </Space>
              </Card>
            </Col>
            <Col xs={24} md={12}>
              <Card size="small" title={<Space><AuditOutlined style={{ color: ES.accent }} />Judge 健康</Space>}>
                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  {jh?.sufficient ? (
                    <Metric
                      label="裁判一致性 Kappa" value={jh.kappa != null ? Number(jh.kappa).toFixed(2) : '-'}
                      status={jh.kappa != null && jh.kappa >= jh.threshold ? 'PASS' : 'WARN'}
                      hint={`样本 ${jh.sample} 个 · 双轨分歧率 ${pct(jh.disagreement_rate)}（阈值 ${jh.threshold}）`}
                      onClick={() => drill(jh.drill)}
                    />
                  ) : (
                    <Metric
                      label="裁判一致性 Kappa" value="样本不足" status="WARN"
                      hint={`校准样本 ${jh?.sample ?? 0} 个，需 ≥10 个方可评估一致性，暂不发布 Kappa`}
                      onClick={() => drill(jh?.drill)}
                    />
                  )}
                  <Metric
                    label="双轨分歧率" value={pct(jh?.disagreement_rate)}
                    status={jh?.disagreement_rate != null && jh.disagreement_rate > 0.1 ? 'WARN' : 'PASS'}
                    hint="模型裁判与人工复核不一致占比"
                    onClick={() => drill(jh?.drill)}
                  />
                </Space>
              </Card>
            </Col>
          </Row>

          <Card size="small" title="最近活动">
            <Table
              rowKey="id"
              size="small"
              columns={columns}
              dataSource={runs}
              scroll={{ x: 'max-content' }}
              pagination={false}
              locale={{
                emptyText: (
                  <Empty description="尚无评测运行">
                    <Button type="primary" icon={<RocketOutlined />} onClick={() => navigate('/eval')}>
                      发起第一次评测
                    </Button>
                  </Empty>
                ),
              }}
            />
          </Card>
        </>
      )}
    </Space>
  )
}
