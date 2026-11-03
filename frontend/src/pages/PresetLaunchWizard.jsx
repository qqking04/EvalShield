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
 * 优化12 §8.1/§8.1a：GBT45654 全量评估预设向导（EvalCenter 入口）。
 * 预设即配置：presets.yaml → /meta/standards 的 presets[]（calibrated 派生）。
 * 发起 = 前端生成 activity_id（UUID）→ createEvalRun（带 category_quotas）
 *        + 逐个 POST /api/tasks（config.activity_id 同 UUID，§4.1a 软键零 DDL）。
 * 社区档额度不足：readiness 预检捕获 LIMIT_QUOTA_INSUFFICIENT → 降级 SCREENING 出口（§8.1a）。
 * calibrated:false 预设可预览明细、不可发起。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Modal, Steps, Select, Table, InputNumber, Typography, Space, Alert, Button, Tag, Tooltip, App,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import http from '../api/http'
import { getStandardsDimensions, checkReadiness, createEvalRun } from '../api/es11'
import { getCoverage } from '../api/questionBanks'
import { ES, GateChecklist } from './es11/gate'

export default function PresetLaunchWizard({ open, onClose }) {
  const { message } = App.useApp()
  const [step, setStep] = useState(0)
  const [meta, setMeta] = useState(null)
  const [metaError, setMetaError] = useState('')
  const [preset, setPreset] = useState(null)
  const [quotas, setQuotas] = useState({}) // {bank_category: number}
  const [cfg, setCfg] = useState({}) // {target_id, question_bank_id, project_id, sample_size, judge_mode, judge_model}
  const [options, setOptions] = useState({ targets: [], banks: [], projects: [] })
  const [readiness, setReadiness] = useState(null) // {ready, checks} | null
  const [checking, setChecking] = useState(false)
  const [launching, setLaunching] = useState(false)
  const [downgrade, setDowngrade] = useState(false) // 社区档降级 SCREENING 中
  const [bankGaps, setBankGaps] = useState(null) // BUG-006：选题库后实时子类题量缺口 [{category, min_questions, current_count}]
  const navigateTo = useNavigate()

  useEffect(() => {
    if (!open) {
      setStep(0); setPreset(null); setQuotas({}); setCfg({}); setReadiness(null); setDowngrade(false); setBankGaps(null)
      return
    }
    getStandardsDimensions()
      .then((d) => setMeta(d))
      .catch((e) => { setMeta(null); setMetaError(e?.message || '标准元信息加载失败') })
    http.get('/targets', { params: { status: 'ACTIVE', page_size: 200 } })
      .then((d) => setOptions((o) => ({ ...o, targets: (d?.items || []).map((t) => ({ value: t.code, label: `${t.code} - ${t.name}` })) })))
      .catch(() => {})
    http.get('/question-banks', { params: { page_size: 100 } })
      .then((d) => setOptions((o) => ({ ...o, banks: (d?.items || []).map((b) => ({ value: b.id, label: `${b.name}（${b.status}）` })) })))
      .catch(() => {})
    http.get('/projects', { params: { page_size: 200 } })
      .then((d) => setOptions((o) => ({ ...o, projects: ((d?.items || d) || []).map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` })) })))
      .catch(() => {})
  }, [open])

  // 预设副行信息（维度中文名映射，仅预览用）
  const dimNameOf = useMemo(() => {
    const m = {}
    ;(meta?.dimensions || []).forEach((d) => { m[d.dimension_code] = d.dimension_name })
    return m
  }, [meta])

  const pickPreset = (p) => {
    setPreset(p)
    setReadiness(null)
    setDowngrade(false)
    setBankGaps(null)
    // category_quotas 初值 = 该预设官方子类核定 min_questions（按 bank_category 聚合）
    const init = {}
    const dims = new Set(p.dimension_order || [])
    ;(meta?.mapping || []).forEach((r) => {
      if (dims.has(r.dimension_code) && r.regulatory && r.bank_category && r.min_questions != null) {
        init[r.bank_category] = (init[r.bank_category] || 0) + r.min_questions
      }
    })
    setQuotas(init)
    setStep(1)
  }

  const quotaRows = useMemo(() => Object.entries(quotas).map(([cat, n]) => ({ key: cat, cat, n })), [quotas])
  const quotaSum = quotaRows.reduce((a, r) => a + (r.n || 0), 0)
  const minBank = preset?.min_bank_questions ?? 0

  const buildActivityCfg = useCallback((purpose) => ({
    target_id: cfg.target_id,
    question_bank_id: cfg.question_bank_id,
    sample_size: cfg.sample_size || quotaSum || undefined,
    judge_mode: cfg.judge_mode || 'RULE',
    judge_model: cfg.judge_model || undefined,
    run_purpose: purpose,
    activity_id: cfg.__activity_id || undefined,
    category_quotas: quotas,
  }), [cfg, quotas, quotaSum])

  const runCheck = async (purpose) => {
    if (!cfg.target_id || !cfg.question_bank_id || !cfg.project_id) {
      message.warning('请先选择项目、被测系统与题库')
      return
    }
    setChecking(true)
    setReadiness(null)
    try {
      const d = await checkReadiness(buildActivityCfg(purpose))
      setReadiness(d)
      setStep(2)
    } catch (e) {
      message.error(e?.message || '预检失败')
    } finally {
      setChecking(false)
    }
  }

  const limitCheck = readiness?.checks?.find((c) => c.code === 'LIMIT_QUOTA_INSUFFICIENT')

  // BUG-006：选题库后异步拉取该库对标准子类核定题量的缺口（复用 /question-banks/{id}/coverage）
  const pickBank = (v) => {
    setCfg((c) => ({ ...c, question_bank_id: v }))
    setBankGaps(null)
    if (!v) return
    getCoverage(v)
      .then((d) => setBankGaps((d?.gaps || []).map((g) => ({
        cat: g.category, min: g.min_questions, have: g.current_count, missing: g.min_questions - g.current_count,
      }))))
      .catch(() => setBankGaps([])) // 静默：缺口提示为增强项，失败不阻断流程
  }

  const launch = async () => {
    setLaunching(true)
    const purpose = downgrade ? 'SCREENING' : (preset?.run_purpose || 'STANDARD')
    const activityId = (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID() : `act-${Date.now()}`
    try {
      const run = await createEvalRun({
        target_type: 'MODEL',
        ...buildActivityCfg(purpose),
        activity_id: activityId,
      })
      // 引擎任务：逐个 POST /api/tasks，config 携带同一 activity_id（§4.1a）
      const taskResults = []
      for (const code of (preset?.engines || [])) {
        try {
          // eslint-disable-next-line no-await-in-loop
          await http.post('/tasks', {
            project_id: cfg.project_id,
            name: `${preset.name}·${code}·${run?.run_no || activityId.slice(0, 8)}`,
            engines: [code],
            config: {
              activity_id: activityId,
              target_id: cfg.target_id,
              // BUG-005：MULTI_TURN_TEST 后端必配 config.target_code（tasks_core L416），
              // 向导 targets 选项 value 即 target.code，直接携带避免 400 ES-BIZ-0017
              target_code: cfg.target_id,
              question_bank_id: cfg.question_bank_id,
            },
          })
          taskResults.push({ code, ok: true })
        } catch (e) {
          taskResults.push({ code, ok: false, err: e?.message || '创建失败' })
        }
      }
      const failed = taskResults.filter((t) => !t.ok)
      if (failed.length) {
        message.warning(`评估运行已创建；${failed.length} 个引擎任务创建失败：${failed.map((f) => `${f.code}(${f.err})`).join('；')}`)
      } else {
        message.success('评估活动已发起（运行 + 引擎任务共享活动编号）')
      }
      onClose?.()
      if (run?.id) navigateTo(`/eval/runs/${run.id}`)
    } catch (e) {
      // BUG-007：超时/中断时后端可能仍在执行并落库，明确提示避免用户重复点击造成脏 run
      const aborted = e?.code === 'ECONNABORTED' || /timeout|aborted/i.test(String(e?.message || ''))
      message.error(aborted
        ? '发起请求超时：后台可能仍在执行并已创建运行，请前往「测试与评测 → 评测工作台」刷新确认，勿重复点击'
        : (e?.message || '发起失败'))
    } finally {
      setLaunching(false)
    }
  }

  const presets = meta?.presets || []

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width={860}
      footer={null}
      destroyOnClose
      title="GBT45654 全量评估 · 预设向导"
    >
      <Steps
        size="small"
        current={step}
        style={{ marginBottom: 18 }}
        items={[{ title: '选预设' }, { title: '配置与配额' }, { title: '预检（G0）' }, { title: '发起' }]}
      />
      {metaError && (
        <Alert type="error" showIcon message="标准元信息加载失败" description={metaError} />
      )}
      {step === 0 && (
        <>
          {meta?.presets_error && (
            <Alert type="warning" showIcon message="预设清单不可用" description={`${meta.presets_error}——向导降级：暂无可发起预设。`} />
          )}
          {!presets.length && !meta && !metaError && <Alert type="info" showIcon message="加载中…" />}
          {!!presets.length && (
            <Table
              rowKey="preset_code"
              size="small"
              pagination={false}
              dataSource={presets}
              columns={[
                { title: '预设', dataIndex: 'name', render: (v, r) => (
                  <Space><span>{v}</span><Tag>{r.preset_code}</Tag>
                    {r.run_purpose === 'SCREENING' && <Tag color="orange">抽样探查</Tag>}
                  </Space>
                ) },
                { title: '覆盖维度', dataIndex: 'dimension_order', render: (v) => (v || []).map((d) => dimNameOf[d] || d).join('、') },
                { title: '要求引擎', dataIndex: 'engines', render: (v) => (v || []).join('、') || '—' },
                { title: '题库最低题量', dataIndex: 'min_bank_questions', width: 110, render: (v) => `${v ?? 0} 题` },
                {
                  title: '核定状态', dataIndex: 'calibrated', width: 170,
                  render: (v, r) => (v
                    ? <Tag color="green">已核定</Tag>
                    : <Tooltip title={`未核定子类 ${r.uncalibrated_items?.length || 0} 个：${(r.uncalibrated_items || []).slice(0, 6).join('、')}…可预览明细，核定后方可发起`}>
                        <Tag color="gold">未核定（仅预览）</Tag>
                      </Tooltip>),
                },
                {
                  title: '', key: 'act', width: 110,
                  render: (_, r) => (
                    <Button size="small" type={r.calibrated ? 'primary' : 'default'} onClick={() => pickPreset(r)}>
                      {r.calibrated ? '选择 ›' : '预览 ›'}
                    </Button>
                  ),
                },
              ]}
            />
          )}
        </>
      )}
      {step === 1 && preset && (
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          {!preset.calibrated && (
            <Alert type="warning" showIcon
              message="该预设存在未核定子类，仅可预览；下一步预检将被拦截"
              description="阈值核定入口在「合规对标」页（仅管理员可见）。" />
          )}
          <Typography.Text strong>{preset.name} · 分类配额（题级轨 category_quotas）</Typography.Text>
          <Table
            rowKey="key"
            size="small"
            pagination={false}
            dataSource={quotaRows}
            columns={[
              { title: '题库分类', dataIndex: 'cat' },
              {
                title: '配额（题）', dataIndex: 'n', width: 160,
                render: (v, r) => (
                  <InputNumber min={0} value={v} style={{ width: 130 }}
                    disabled={!preset.calibrated}
                    onChange={(x) => setQuotas((q) => ({ ...q, [r.cat]: x ?? 0 }))} />
                ),
              },
            ]}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            合计 {quotaSum} 题；预设派生题库最低题量 min_bank_questions = {minBank} 题。
            配额只可上调；社区档额度不足将在预检中给出降级「抽样探查」出口。
          </Typography.Text>
          <Space wrap size={12}>
            <Select style={{ width: 240 }} placeholder="项目（引擎任务归属）" value={cfg.project_id}
              onChange={(v) => setCfg((c) => ({ ...c, project_id: v }))} options={options.projects} showSearch optionFilterProp="label" />
            <Select style={{ width: 240 }} placeholder="被测系统" value={cfg.target_id}
              onChange={(v) => setCfg((c) => ({ ...c, target_id: v }))} options={options.targets} showSearch optionFilterProp="label" />
            <Select style={{ width: 240 }} placeholder="题库" value={cfg.question_bank_id}
              onChange={pickBank} options={options.banks} showSearch optionFilterProp="label" />
            <Select style={{ width: 140 }} placeholder="判定模式" value={cfg.judge_mode}
              onChange={(v) => setCfg((c) => ({ ...c, judge_mode: v }))}
              options={[{ value: 'RULE', label: 'RULE' }, { value: 'MODEL', label: 'MODEL' }, { value: 'HYBRID', label: 'HYBRID' }]} />
            <InputNumber min={1} placeholder="抽样数" value={cfg.sample_size} style={{ width: 120 }}
              onChange={(v) => setCfg((c) => ({ ...c, sample_size: v }))} />
          </Space>
          {bankGaps && bankGaps.length > 0 && (
            <Alert type="warning" showIcon
              message={`所选题库存在 ${bankGaps.length} 个子类题量缺口（发起后 G4 将 BLOCK）`}
              description={
                <Space wrap size={6}>
                  {bankGaps.slice(0, 8).map((g) => (
                    <Tag key={g.cat} color="orange">{g.cat} 缺 {g.missing} 题（{g.have}/{g.min}）</Tag>
                  ))}
                  {bankGaps.length > 8 && <Typography.Text type="secondary">…等 {bankGaps.length} 项</Typography.Text>}
                </Space>
              } />
          )}
          {bankGaps && bankGaps.length === 0 && cfg.question_bank_id && (
            <Alert type="success" showIcon message="所选题库对各核定子类题量无缺口" />
          )}
          <Space>
            <Button onClick={() => setStep(0)}>上一步</Button>
            <Button type="primary" disabled={!preset.calibrated} loading={checking}
              onClick={() => runCheck(downgrade ? 'SCREENING' : (preset.run_purpose || 'STANDARD'))}>
              下一步：G0 预检
            </Button>
          </Space>
        </Space>
      )}
      {step === 2 && (
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            活动编号（activity_id，发起时前端生成 UUID）：软键贯通评测运行与 {preset?.engines?.length || 0} 个引擎任务（{preset?.engines?.join('、')}）。
          </Typography.Text>
          {limitCheck && !downgrade && (
            <Alert
              type="warning"
              showIcon
              message="题量额度不足（社区档）"
              description={limitCheck.reason}
              action={
                <Button size="small" onClick={() => { setDowngrade(true); runCheck('SCREENING') }}>
                  降级为抽样探查（SCREENING）
                </Button>
              }
            />
          )}
          {readiness ? (
            <GateChecklist checks={readiness.checks || []} onAction={(a) => { if (a?.path) { onClose?.(); navigateTo(a.path) } }} />
          ) : <Alert type="info" showIcon message="预检未执行" />}
          <Space>
            <Button onClick={() => setStep(1)}>上一步</Button>
            <Button onClick={() => runCheck(downgrade ? 'SCREENING' : (preset.run_purpose || 'STANDARD'))} loading={checking}>重新预检</Button>
            <Button type="primary" disabled={!readiness?.ready} loading={launching} onClick={launch}>
              {downgrade ? '按抽样探查发起' : `发起评估活动${preset?.run_purpose === 'SCREENING' ? '（抽样探查）' : ''}`}
            </Button>
          </Space>
          {!readiness?.ready && readiness && (
            <Typography.Text style={{ color: ES.WARN, fontSize: 12 }}>存在阻塞项：修复后重新预检。</Typography.Text>
          )}
        </Space>
      )}
    </Modal>
  )
}
