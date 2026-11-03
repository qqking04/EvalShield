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
 * ES11 测试发起向导（方案 §5.4 P2）：五步 = 场景 → 范围 → 证据来源 → 验收规则 → G0 准备度。
 * 第 5 步调 checkReadiness(cfg)，GateChecklist 逐条渲染；存在 BLOCK 时禁止发起并引导修复。
 * 场景仅决定默认编排与血缘标记，不创建、不新增测试引擎（AGENTS.md 锁 1）。
 */
import { useCallback, useEffect, useState } from 'react'
import {
  Modal, Steps, Button, Space, Select, InputNumber, Input, Radio, Alert, Typography, Form, App, Spin,
} from 'antd'
import { Link, useNavigate } from 'react-router-dom'
import http from '../../api/http'
import { checkReadiness } from '../../api/es11'
import { ES, GateChecklist } from './gate'

const STEP_ITEMS = [
  { title: '选择场景' },
  { title: '确定范围' },
  { title: '证据来源' },
  { title: '验收规则' },
  { title: '准备度检查' },
]

const PURPOSE_OPTIONS = [
  { value: 'STANDARD', label: '标准评测', desc: '对题库全量/抽样执行，产出完整证据链。' },
  { value: 'REGRESSION', label: '版本回归', desc: '版本变更后重放基线题库，比对新失败与已修复项。' },
  { value: 'RETEST', label: '缺陷复测', desc: '针对已整改缺陷的真实重测，作为验证证据（判分重放不算）。' },
  { value: 'TRACE_REPLAY', label: 'Trace 回流', desc: '将线上低分 Trace 回流为回归样本执行。' },
]

const JUDGE_OPTIONS = [
  { value: 'RULE', label: '规则判定', desc: '关键词/正则/期望断言判定，零模型成本，口径稳定。' },
  { value: 'MODEL', label: '模型裁判', desc: '由裁判模型打分，需选择裁判模型并关注双轨一致性。' },
  { value: 'HYBRID', label: '规则 + 模型', desc: '规则先行过滤，模型兜底判定，兼顾成本与覆盖。' },
]

const GATE_RULES = [
  ['G0 准备度', '被测系统、题库、裁判与事实源配置完整，连通性预检通过'],
  ['G1 执行质量', '基础设施 / 配置类失败单列，不计入质量结论'],
  ['G2 人工复核', '抽样复核完成且双轨一致率达到阈值'],
  ['G3 缺陷闭环', 'P0/P1 全部经真实复测验证关闭'],
  ['G4 交付准出', '报告结论冻结，证据包完整可追溯'],
]

const DEFAULT_CFG = {
  run_purpose: 'STANDARD',
  engine_code: undefined,
  target_id: undefined,
  question_bank_id: undefined,
  sample_size: undefined,
  judge_mode: 'RULE',
  judge_model: undefined,
  fact_source_id: undefined,
}

export default function ActivityLaunchWizard({ open, onClose, onLaunched }) {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [step, setStep] = useState(0)
  const [cfg, setCfg] = useState(DEFAULT_CFG)
  const [targets, setTargets] = useState([])
  const [banks, setBanks] = useState([])
  const [factSources, setFactSources] = useState([])
  const [models, setModels] = useState([])
  const [rd, setRd] = useState(null) // { ready, checks }
  const [checking, setChecking] = useState(false)
  const [checkError, setCheckError] = useState('')

  const set = (patch) => setCfg((c) => ({ ...c, ...patch }))

  useEffect(() => {
    if (!open) return
    setStep(0)
    setCfg(DEFAULT_CFG)
    setRd(null)
    setCheckError('')
  }, [open])

  // 选项数据复用既有端点（与 EvalRunLaunchModal 同一取数口径）
  useEffect(() => {
    if (!open) return
    http.get('/targets', { params: { status: 'ACTIVE', page_size: 200 } })
      .then((d) => { const p = d?.data || d; setTargets(p.items || (Array.isArray(p) ? p : [])) }).catch(() => setTargets([]))
    http.get('/question-banks', { params: { page_size: 100 } })
      .then((d) => setBanks(d.items || d || [])).catch(() => setBanks([]))
    http.get('/fact-sources', { params: { page_size: 200 } })
      .then((d) => setFactSources((d.items || d || []).filter((s) => String(s.status || '').toLowerCase() !== 'disabled')))
      .catch(() => setFactSources([]))
    http.get('/model-configs')
      .then((d) => setModels(((d.items || d) || []).filter((m) => m.status === 'ACTIVE'))).catch(() => setModels([]))
  }, [open])

  const runCheck = useCallback(async () => {
    setChecking(true)
    setCheckError('')
    setRd(null)
    try {
      setRd(await checkReadiness(cfg))
    } catch (e) {
      setCheckError(e?.message || '准备度检查失败，请稍后重试')
    } finally {
      setChecking(false)
    }
  }, [cfg])

  useEffect(() => {
    if (open && step === 4) runCheck()
  }, [open, step, runCheck])

  const blockCount = (rd?.checks || []).filter((c) => c.status === 'BLOCK').length
  const warnCount = (rd?.checks || []).filter((c) => c.status === 'WARN').length

  const stepOk = [
    true,
    Boolean(cfg.target_id && cfg.question_bank_id),
    cfg.judge_mode === 'RULE' || Boolean(cfg.judge_model),
    true,
    Boolean(rd) && blockCount === 0,
  ]

  const launch = () => {
    message.success('准备度通过，已提交发起请求，正在创建评测运行')
    // ES11 E2E 修复（问题4）：透传注册表协议类型（LLM_API/APP_API/INTERNAL_MODEL），
    // 由调用方映射为运行级形态（MODEL/RAG/AGENT/API）；两套枚举勿混用（models.py #8）
    const t = targets.find((x) => x.code === cfg.target_id)
    onLaunched?.({ ...cfg, __target_protocol_type: t?.target_type })
    onClose?.()
  }

  const body = () => {
    if (step === 0) {
      return (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Radio.Group
            value={cfg.run_purpose}
            onChange={(e) => set({ run_purpose: e.target.value })}
            style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
          >
            {PURPOSE_OPTIONS.map((p) => (
              <Radio key={p.value} value={p.value} style={{ alignItems: 'flex-start', padding: '8px 12px', border: `1px solid ${cfg.run_purpose === p.value ? ES.accent : '#d9d9d9'}`, borderRadius: 6 }}>
                <div>
                  <Typography.Text strong>{p.label}</Typography.Text>
                  <div><Typography.Text type="secondary" style={{ fontSize: 12 }}>{p.desc}</Typography.Text></div>
                </div>
              </Radio>
            ))}
          </Radio.Group>
          <Form layout="vertical" component={false}>
            <Form.Item label="引擎编排代码（可选）" tooltip="留空 = 平台默认编排；本向导不创建、不新增测试引擎">
              <Input
                style={{ width: 280 }}
                placeholder="留空 = 平台默认编排"
                value={cfg.engine_code || ''}
                onChange={(e) => set({ engine_code: e.target.value || undefined })}
              />
            </Form.Item>
          </Form>
        </Space>
      )
    }
    if (step === 1) {
      return (
        <Form layout="vertical">
          <Form.Item label="被测系统" required extra="下一步将真实调用该被测系统接口，请确认环境可用且数据已脱敏">
            <Select
              showSearch optionFilterProp="label" placeholder="选择已注册的 ACTIVE 被测系统"
              value={cfg.target_id} onChange={(v) => set({ target_id: v })}
              options={targets.map((t) => ({ value: t.code, label: `${t.code} — ${t.name}` }))}
              notFoundContent={<Space direction="vertical" size={4}><Typography.Text type="secondary">暂无已注册被测系统</Typography.Text><Link to="/targets">去注册被测系统</Link></Space>}
            />
          </Form.Item>
          <Form.Item label="题库" required extra="评测必须绑定题库，题目样本全部来自所选库">
            <Select
              showSearch optionFilterProp="label" placeholder="选择题库"
              value={cfg.question_bank_id} onChange={(v) => set({ question_bank_id: v })}
              options={banks.map((b) => ({ value: b.id, label: `${b.name}（${b.question_count ?? 0} 题）` }))}
              notFoundContent={<Space direction="vertical" size={4}><Typography.Text type="secondary">暂无题库</Typography.Text><Link to="/question-banks">去新建题库</Link></Space>}
            />
          </Form.Item>
          <Form.Item label="样本量" tooltip="留空 = 全量执行；抽样越小成本越低，但回归覆盖证据越弱">
            <InputNumber min={1} max={5000} style={{ width: 220 }} placeholder="留空 = 全量"
              value={cfg.sample_size} onChange={(v) => set({ sample_size: v ?? undefined })} />
          </Form.Item>
        </Form>
      )
    }
    if (step === 2) {
      return (
        <Form layout="vertical">
          <Form.Item label="事实基准（知识源）" tooltip="不选 = 仅自我一致性检测，事实性判定证据强度下降">
            <Select allowClear style={{ width: 360 }} placeholder="不选 = 仅自我一致性检测"
              value={cfg.fact_source_id} onChange={(v) => set({ fact_source_id: v })}
              options={factSources.map((s) => ({ value: s.id, label: s.name }))}
              notFoundContent={<Space direction="vertical" size={4}><Typography.Text type="secondary">暂无知识源</Typography.Text><Link to="/targets?tab=fact-sources">去配置知识源</Link></Space>}
            />
          </Form.Item>
          <Form.Item label="裁判模式" required>
            <Radio.Group value={cfg.judge_mode} onChange={(e) => set({ judge_mode: e.target.value })}>
              {JUDGE_OPTIONS.map((j) => (
                <Radio.Button key={j.value} value={j.value}>{j.label}</Radio.Button>
              ))}
            </Radio.Group>
            <div style={{ marginTop: 6 }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {JUDGE_OPTIONS.find((j) => j.value === cfg.judge_mode)?.desc}
              </Typography.Text>
            </div>
          </Form.Item>
          {(cfg.judge_mode === 'MODEL' || cfg.judge_mode === 'HYBRID') && (
            <Form.Item label="裁判模型" required extra="模型裁判将产生额外调用成本，其判定结果需经 G2 双轨复核校准">
              <Select allowClear style={{ width: 360 }} placeholder="选择 ACTIVE 模型配置作为裁判"
                value={cfg.judge_model} onChange={(v) => set({ judge_model: v })}
                options={models.map((m) => ({ value: m.code, label: `${m.name}（${m.code}）` }))}
                notFoundContent={<Space direction="vertical" size={4}><Typography.Text type="secondary">暂无可用模型配置</Typography.Text><Link to="/models">去配置模型网关</Link></Space>}
              />
            </Form.Item>
          )}
        </Form>
      )
    }
    if (step === 3) {
      return (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert type="info" showIcon
            message="验收阈值由平台门禁统一固化"
            description="本向导不开放逐次修改阈值；以下为本次运行将经历的准出链路说明（占位说明，具体数值以门禁配置为准）。"
          />
          <div style={{ background: ES.bg, border: `1px solid ${ES.line}`, borderRadius: 8, padding: 14 }}>
            {GATE_RULES.map(([g, desc]) => (
              <div key={g} style={{ display: 'flex', gap: 12, padding: '6px 0', borderBottom: `1px solid ${ES.line}` }}>
                <span style={{ fontFamily: ES.mono, color: ES.accent, fontSize: 12.5, minWidth: 96 }}>{g}</span>
                <span style={{ color: ES.ink, fontSize: 12.5 }}>{desc}</span>
              </div>
            ))}
          </div>
        </Space>
      )
    }
    // step 4：G0 准备度
    return (
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {checking && <Spin style={{ display: 'block', margin: '24px auto' }} tip="正在执行 G0 准备度检查…"><div style={{ minHeight: 80 }} /></Spin>}
        {checkError && (
          <Alert type="error" showIcon message="准备度检查失败" description={checkError}
            action={<Button size="small" onClick={runCheck}>重试</Button>} />
        )}
        {rd && !checking && (
          <>
            <Alert
              type={blockCount > 0 ? 'error' : warnCount > 0 ? 'warning' : 'success'}
              showIcon
              message={blockCount > 0
                ? `准备度未通过：存在 ${blockCount} 项阻塞，修复后方可发起`
                : warnCount > 0
                  ? `准备度基本就绪：${warnCount} 项需关注，不阻塞发起`
                  : '准备度全部通过，可发起评测'}
            />
            <GateChecklist
              checks={rd.checks}
              onAction={(a) => { onClose?.(); if (a?.path) navigate(a.path) }}
            />
          </>
        )}
      </Space>
    )
  }

  return (
    <Modal
      title="发起评测活动"
      open={open}
      onCancel={onClose}
      width={760}
      destroyOnHidden
      styles={{ body: { maxHeight: '68vh', overflowY: 'auto', paddingTop: 8 } }}
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            第 {step + 1} / 5 步 · {STEP_ITEMS[step].title}
          </Typography.Text>
          <Space>
            <Button onClick={onClose}>取消</Button>
            {step > 0 && <Button onClick={() => setStep(step - 1)}>上一步</Button>}
            {step < 4 ? (
              <Button type="primary" disabled={!stepOk[step]} onClick={() => setStep(step + 1)}>下一步</Button>
            ) : (
              <Space direction="vertical" size={2} align="end">
                <Space>
                  <Button onClick={runCheck} disabled={checking}>重新检查</Button>
                  <Button type="primary" loading={checking} disabled={!stepOk[4]} onClick={launch}>发起评测</Button>
                </Space>
                {rd && blockCount > 0 && (
                  <Typography.Text style={{ color: ES.BLOCK, fontSize: 12 }}>
                    存在 {blockCount} 项阻塞，请先修复
                  </Typography.Text>
                )}
              </Space>
            )}
          </Space>
        </div>
      }
    >
      <Steps size="small" current={step} items={STEP_ITEMS} style={{ marginBottom: 24 }} />
      {body()}
    </Modal>
  )
}
