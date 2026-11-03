/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES11 P10：报告交付 G4 工作台（/reports/:id/delivery）。
// 上线建议优先于图表；G4 清单阻塞项直达修复页；结论冻结（report:deliver，幂等）；
// 交付四件套台账（G4 未过仅带「草稿/未冻结」水印预览包）。
import { useCallback, useEffect, useState } from 'react'
import {
  Alert, App, Button, Card, Descriptions, Input, Result, Space, Table, Tag, Typography,
} from 'antd'
import {
  ExclamationCircleFilled, FileProtectOutlined,
  LockFilled, RightOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import * as es11 from '../../api/es11'
import { fmtTime } from '../../utils'
import { ES, GateChecklist, Mono } from './gate'
import { useAuth } from '../../auth'

const KIND_LABEL = { pdf: '技术支撑报告', zip: '证据链包', csv: '整改建议清单', md: '复测点列表' }
const PKG_STATUS = {
  ready: { color: 'success', text: '正式包' },
  draft: { color: 'gold', text: '草稿水印预览包' },
  building: { color: 'processing', text: '生成中' },
  delivered: { color: 'green', text: '已交付' },
}

function fmtSize(v) {
  if (v == null) return '-'
  if (v < 1024) return `${v} B`
  if (v < 1048576) return `${(v / 1024).toFixed(1)} KB`
  return `${(v / 1048576).toFixed(2)} MB`
}

// 上线建议（P10 首屏）：据 deliverable + concluded + freeze 派生四态
// ES11 P10：与 ReportDetail 交付就绪区共用，抽出到 deliveryVerdict.jsx
// ES11-BUG-006：re-export 不引入本模块作用域，需显式 import 后使用
import { verdictOf } from './deliveryVerdict'

const DIM_STATUS_META = {
  PASS: { color: 'success', text: '达标' },
  WARN: { color: 'warning', text: '关注' },
  BLOCK: { color: 'error', text: '阻塞' },
  NOT_CONFIGURED: { color: 'default', text: '未核定' },
  'N/A': { color: 'default', text: '不计官方' },
}

/**
 * 优化12 §10.3：交付工作台「维度覆盖」卡（G4 卡上方）。
 * 判定唯一实现在后端 services/dimension_coverage，此处仅渲染；
 * 旧口径 run（coverage:null）→ 灰态说明（铁律 7：出具时点冻结，不回填）。
 */
function CoverageCard({ runId, onBenchmark }) {
  const [cov, setCov] = useState(null)
  const [ver, setVer] = useState(null)
  const [state, setState] = useState('loading') // loading|ready|err

  useEffect(() => {
    if (runId == null) return undefined
    let alive = true
    setState('loading')
    es11.getRunDimensionCoverage(runId)
      .then((d) => { if (!alive) return; setCov(d?.coverage ?? null); setVer(d?.standards_ver ?? null); setState('ready') })
      .catch(() => { if (alive) setState('err') })
    return () => { alive = false }
  }, [runId])

  if (runId == null) return null

  if (state === 'err') {
    return (
      <Card size="small" title="GBT45654 五维度覆盖">
        <Alert type="error" showIcon message="覆盖矩阵加载失败" description="不影响下方 G4 清单判定，可刷新本页重试。" />
      </Card>
    )
  }

  if (state === 'loading') {
    return <Card size="small" title="GBT45654 五维度覆盖" loading />
  }

  if (cov == null) {
    return (
      <Card size="small" title="GBT45654 五维度覆盖">
        <Alert type="info" showIcon
          message="该运行按 TC260-003 草案口径出件（出具时点冻结，铁律 7）"
          description={`运行标准版本「${ver || '未知'}」非 GBT45654 现行口径，不产维度覆盖结论；如需五维度达标证明，请以现行口径重跑。`} />
      </Card>
    )
  }

  return (
    <Card size="small" title="GBT45654 五维度覆盖"
      extra={(
        <Space size={8}>
          <Tag color={cov.overall?.official_pass ? 'success' : 'error'}>
            {cov.overall?.official_pass ? '官方结论达标' : '官方结论未达标'}
          </Tag>
          <a onClick={() => onBenchmark?.()}>完整矩阵 <RightOutlined /></a>
        </Space>
      )}
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space size={[8, 8]} wrap>
          {(cov.dimensions || []).map((d) => {
            const m = DIM_STATUS_META[d.dimension_status] || DIM_STATUS_META.NOT_CONFIGURED
            return (
              <Tag key={d.dimension_code} color={m.color}>
                {d.dimension_name}
                {d.dimension_rate != null ? ` ${Math.round(d.dimension_rate * 100)}%` : ''}
                {' · '}{m.text}
                {d.gap_questions ? ` · 缺 ${d.gap_questions} 题` : ''}
              </Tag>
            )
          })}
        </Space>
        <Descriptions size="small" column={3} items={[
          {
            key: 'refuse', label: '拒答合格率',
            children: cov.refusal?.refuse_pass_rate != null
              ? <Mono>{`${Math.round(cov.refusal.refuse_pass_rate * 100)}%`}</Mono> : <Mono color={ES.sub}>未测</Mono>,
          },
          {
            key: 'false', label: '应答误拒率',
            children: cov.refusal?.answer_false_refuse_rate != null
              ? <Mono>{`${Math.round(cov.refusal.answer_false_refuse_rate * 100)}%`}</Mono> : <Mono color={ES.sub}>未测</Mono>,
          },
          {
            key: 'asr', label: '攻击成功率',
            children: cov.refusal?.attack_success_rate != null
              ? <Mono>{`${Math.round(cov.refusal.attack_success_rate * 100)}%`}</Mono> : <Mono color={ES.sub}>未测</Mono>,
          },
        ]} />
        {(cov.overall?.block_items || []).slice(0, 3).map((b, i) => (
          <div key={`b${i}`} style={{ color: ES.BLOCK, fontSize: 12 }}>{typeof b === 'string' ? b : (b.reason || JSON.stringify(b))}</div>
        ))}
        {(cov.overall?.warn_items || []).slice(0, 3).map((w, i) => (
          <div key={`w${i}`} style={{ color: ES.WARN, fontSize: 12 }}>{typeof w === 'string' ? w : (w.reason || JSON.stringify(w))}</div>
        ))}
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{cov.disclaimer}</Typography.Text>
      </Space>
    </Card>
  )
}

export default function ReportDelivery() {
  const { id: reportId } = useParams()
  const navigate = useNavigate()
  const { message, modal } = App.useApp()
  const { hasPerm } = useAuth()

  const [rd, setRd] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadErr, setLoadErr] = useState('')
  const [pkg, setPkg] = useState(null)
  const [pkgBusy, setPkgBusy] = useState(false)
  const [freezeBusy, setFreezeBusy] = useState(false)
  const [freezeNote, setFreezeNote] = useState('')
  const [freezeHint, setFreezeHint] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    setLoadErr('')
    es11.getDeliveryReadiness(reportId)
      .then((d) => setRd(d))
      .catch((e) => { setRd(null); setLoadErr(e?.message || '交付就绪数据加载失败') })
      .finally(() => setLoading(false))
  }, [reportId])

  useEffect(() => { load() }, [load])

  const verdict = verdictOf(rd)

  // 生成交付四件套：G4 未过时先确认「草稿水印预览包」影响范围
  const doCreatePkg = async () => {
    setPkgBusy(true)
    try {
      const d = await es11.createDeliveryPackage(rd.run_id)
      setPkg(d)
      message.success(d?.status === 'draft'
        ? '已生成带「草稿/未冻结」水印的预览包，不可用于正式交付'
        : `交付四件套 ${d?.package_no || ''} 已生成`)
      load() // 刷新清单：PACKAGE 检查项状态随之更新
    } catch { /* 拦截器已提示原因 */ } finally {
      setPkgBusy(false)
    }
  }
  const createPkg = () => {
    if (!rd?.deliverable) {
      modal.confirm({
        title: 'G4 未通过，仍要生成交付包？',
        icon: <ExclamationCircleFilled style={{ color: ES.WARN }} />,
        content: '将产出带「草稿/未冻结」水印的预览包：仅供内部预览整改范围，不可用于正式交付；G4 转绿后需重新生成正式包。',
        okText: '生成预览包', cancelText: '取消',
        onOk: doCreatePkg,
      })
      return
    }
    doCreatePkg()
  }

  // 冻结结论（危险动作：弹窗说明影响范围；ES-BIZ-FREEZE-0001 拦截保持界面不变）
  const doFreeze = () => {
    modal.confirm({
      title: '冻结报告结论',
      icon: <ExclamationCircleFilled style={{ color: ES.BLOCK }} />,
      content: `冻结后报告 #${reportId} 内容转为只读，结论不可再修改；操作写入审计，并作为正式交付包的前置条件。存在待复核项时将被拒绝。`,
      okText: '确认冻结',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setFreezeBusy(true)
        try {
          const d = await es11.freezeConclusion(reportId, { note: freezeNote || undefined })
          message.success(d?.already_frozen ? '结论此前已冻结（幂等，未重复操作）' : '结论已冻结')
          setFreezeHint('')
          setFreezeNote('')
          load()
        } catch (e) {
          if (e?.code === 'ES-BIZ-FREEZE-0001') setFreezeHint('请先完成人工复核：该运行仍有待复核项，结论不可冻结（拦截器已提示待复核数量）')
          // 其余错误：拦截器已 message.error，界面保持不变
        } finally {
          setFreezeBusy(false)
        }
      },
    })
  }

  if (loadErr && !loading) {
    return (
      <div style={{ padding: 16 }}>
        <Result
          status="error"
          title="交付就绪数据加载失败"
          subTitle={`${loadErr}。若提示报告不存在，请确认深链来自当前租户的报告列表。`}
          extra={(
            <Space>
              <Button onClick={load}>重试</Button>
              <Button type="primary" onClick={() => navigate('/reports')}>返回报告列表</Button>
            </Space>
          )}
        />
      </div>
    )
  }

  return (
    <div style={{ padding: 16 }}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* 上线建议（P10：优先于一切图表） */}
        <Card size="small" title={<Space><FileProtectOutlined />报告 #{reportId} · 上线建议</Space>} loading={loading && !rd}
          extra={rd?.run_id ? <a onClick={() => navigate(`/eval/runs/${rd.run_id}`)}>关联运行 <Mono>{rd.run_no}</Mono> ›</a> : null}
        >
          {verdict && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '8px 4px' }}>
              <span style={{ fontSize: 30, lineHeight: 1, color: verdict.color }}>{verdict.icon}</span>
              <div>
                <Typography.Text style={{ color: verdict.color, fontSize: 20, fontWeight: 700 }}>
                  {verdict.label}
                </Typography.Text>
                <div><Typography.Text type="secondary" style={{ fontSize: 13 }}>{verdict.desc}</Typography.Text></div>
              </div>
            </div>
          )}
          {rd?.failure_mix && (
            <Descriptions size="small" column={3} style={{ marginTop: 8 }} items={[
              { key: 'cfg', label: '配置失败', children: <Mono color={ES.WARN}>{rd.failure_mix.config ?? 0}</Mono> },
              { key: 'infra', label: '基础设施失败', children: <Mono color={ES.BLOCK}>{rd.failure_mix.infra ?? 0}</Mono> },
              { key: 'qual', label: '质量失败', children: <Mono color={ES.BLOCK}>{rd.failure_mix.quality ?? 0}</Mono> },
            ]} />
          )}
        </Card>

        {/* 维度覆盖（优化12 §10.3：G4 卡片上方） */}
        <CoverageCard runId={rd?.run_id ?? null}
          onBenchmark={() => navigate(`/standards/gbt45654?run=${rd.run_id}&tab=coverage`)} />

        {/* G4 交付就绪区 */}
        <Card
          size="small"
          title="G4 交付就绪清单"
          extra={rd?.run_id != null && (
            <Button type="primary" size="small" loading={pkgBusy} onClick={createPkg}>
              生成交付包{!rd.deliverable ? '（草稿水印预览）' : ''}
            </Button>
          )}
        >
          {rd?.run_id == null && (
            <Alert
              type="warning" showIcon style={{ marginBottom: 12 }}
              message="报告未关联评测运行"
              description="G4 判定依赖运行证据链；请从运行侧重新生成关联报告，或前往运行列表核对。"
              action={<Button size="small" onClick={() => navigate('/eval')}>查看运行</Button>}
            />
          )}
          <GateChecklist checks={rd?.checklist || []} onAction={(a) => a?.path && navigate(a.path)} />
        </Card>

        {/* 冻结结论区 */}
        <Card size="small" title="结论冻结">
          {rd?.freeze ? (
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Tag icon={<LockFilled />} color="success" style={{ fontWeight: 600 }}>结论已冻结（报告只读）</Tag>
              <Descriptions size="small" column={3} items={[
                { key: 'at', label: '冻结时间', children: fmtTime(rd.freeze.frozen_at) },
                { key: 'by', label: '冻结人', children: rd.freeze.frozen_by_name || `用户 #${rd.freeze.frozen_by ?? '-'}` },
                { key: 'note', label: '备注', children: rd.freeze.note || '-' },
              ]} />
            </Space>
          ) : hasPerm('report:deliver') ? (
            <Space direction="vertical" size={10} style={{ width: '100%' }}>
              {freezeHint && <Alert type="warning" showIcon message={freezeHint} />}
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                未冻结。冻结后报告内容只读，正式交付包以此为准；操作幂等并写入审计。
              </Typography.Text>
              <Space.Compact style={{ width: '100%', maxWidth: 560 }}>
                <Input
                  placeholder="冻结备注（可选，如交付合同号）" maxLength={500}
                  value={freezeNote} onChange={(e) => setFreezeNote(e.target.value)}
                />
                <Button danger type="primary" icon={<LockFilled />} loading={freezeBusy} onClick={doFreeze}>
                  冻结结论
                </Button>
              </Space.Compact>
            </Space>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              当前账号无报告交付权限（report:deliver），无法冻结结论；请联系项目交付负责人处理。
            </Typography.Text>
          )}
        </Card>

        {/* 交付包台账 */}
        {pkg && (
          <Card size="small" title={<Space>交付包台账<Mono>{pkg.package_no}</Mono></Space>}
            extra={<Tag color={PKG_STATUS[pkg.status]?.color || 'default'}>{PKG_STATUS[pkg.status]?.text || pkg.status}</Tag>}
          >
            {pkg.status === 'draft' && (
              <Alert type="warning" showIcon style={{ marginBottom: 12 }}
                message="该包为「草稿/未冻结」水印预览包"
                description="G4 未通过或结论未冻结，四件套均带水印，不可用于正式交付；完成阻塞项修复与冻结后重新生成。" />
            )}
            <Table
              size="small" rowKey={(r) => `${r.kind}-${r.file_name}`} dataSource={pkg.items || []}
              pagination={false}
              columns={[
                { title: '件', dataIndex: 'kind', width: 120, render: (v) => KIND_LABEL[v] || v },
                { title: '文件名', dataIndex: 'file_name', ellipsis: true },
                { title: '大小', dataIndex: 'size', width: 90, render: fmtSize },
                {
                  title: 'sha256（交付核对）', dataIndex: 'sha256',
                  render: (v) => (v
                    ? <Typography.Text copyable style={{ maxWidth: 320 }}><Mono color={ES.sub}>{v}</Mono></Typography.Text>
                    : <Typography.Text type="danger">缺失（BLOCK 项）</Typography.Text>),
                },
              ]}
            />
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
              生成时间 {fmtTime(pkg.created_at)}{pkg.standards_ver ? ` · 标准版本 ${pkg.standards_ver}` : ''}
            </Typography.Text>
          </Card>
        )}
      </Space>
    </div>
  )
}
