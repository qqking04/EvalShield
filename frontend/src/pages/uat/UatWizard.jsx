/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Input, Modal, Radio, Space, Steps, Table, Tag, Tooltip, Typography, message,
} from 'antd'
import http from '../../api/http'
import { uatCandidates, createUat, resampleUat } from '../../api/uat'
import UatSections from './UatSections'

const UAT_TASK_STATUSES = new Set(['SUCCESS', 'COMPLETED_WITH_RISK'])

function parseGateRules(raw) {
  if (!raw) return []
  try {
    const arr = typeof raw === 'string' ? JSON.parse(raw) : raw
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

/* 同 metric 多阈值 → 冲突组（黄色高亮，Radio 强制二选一） */
function conflictGroups(criteria) {
  const byMetric = {}
  criteria.forEach((r, i) => {
    ;(byMetric[r.metric] = byMetric[r.metric] || []).push(i)
  })
  return Object.entries(byMetric)
    .filter(([, idxs]) => idxs.length > 1)
    .map(([metric, idxs]) => ({ metric, idxs }))
}

/*
 * ES9 UAT 生成向导（Modal 三步）：
 * Step1 选终态任务（未配门禁/非终态禁用并提示原因——把 ES9-UAT-0001 消灭在交互层）
 * Step2 定标准（覆写阈值 + 冲突二选一 + 合同编号 + §7 缺陷处置）
 * Step3 只读预览 → createUat / resampleUat
 * mode='resample'：Step1 锁定原 task_ids，直达 Step2。
 */
export default function UatWizard({ open, projectId, onClose, onCreated, mode = 'create', reportId, initialTaskIds }) {
  const [step, setStep] = useState(mode === 'resample' ? 1 : 0)
  const [tasks, setTasks] = useState([])
  const [tasksLoading, setTasksLoading] = useState(false)
  const [selected, setSelected] = useState(mode === 'resample' ? initialTaskIds || [] : [])
  const [criteria, setCriteria] = useState([])
  const [baseCriteria, setBaseCriteria] = useState([]) // candidates 原始阈值，用于判断是否实际改动
  const [picks, setPicks] = useState({}) // metric -> 保留的 row index
  const [contractNo, setContractNo] = useState('')
  const [disposals, setDisposals] = useState({}) // defect_id -> {deadline, waiver}
  const [preview, setPreview] = useState(null) // candidates payload
  const [creating, setCreating] = useState(false)
  const [recomputing, setRecomputing] = useState(false)

  useEffect(() => {
    if (!open) {
      setStep(mode === 'resample' ? 1 : 0)
      setSelected(mode === 'resample' ? initialTaskIds || [] : [])
      setCriteria([])
      setBaseCriteria([])
      setPicks({})
      setContractNo('')
      setDisposals({})
      setPreview(null)
      return
    }
    if (mode !== 'resample' && projectId) {
      setTasksLoading(true)
      http
        .get('/tasks', { params: { project_id: projectId, page: 1, page_size: 200 } })
        .then((data) => setTasks(data?.items || []))
        .catch(() => {})
        .finally(() => setTasksLoading(false))
    }
    if (mode === 'resample' && projectId && initialTaskIds?.length) {
      uatCandidates(projectId, initialTaskIds)
        .then((data) => {
          const payload = data?.payload || data
          const base = (payload?.sections?.s2_scope?.criteria || []).map((r) => ({ ...r }))
          setCriteria(base)
          setBaseCriteria(base.map((r) => ({ ...r })))
          setPreview(payload)
        })
        .catch(() => setStep(0))
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const disabledReason = (t) => {
    if (!UAT_TASK_STATUSES.has(t.status)) return `任务状态为 ${t.status}，仅终态（SUCCESS / COMPLETED_WITH_RISK）可纳入验收`
    if (!parseGateRules(t.gate_rules).length) return '该任务未配置质量门禁，请先在任务设置中配置'
    return ''
  }

  const groups = useMemo(() => conflictGroups(criteria), [criteria])
  const unresolved = groups.filter((g) => picks[g.metric] == null)

  const goPreview = async () => {
    if (!selected.length) {
      message.warning('请至少选择一个任务')
      return
    }
    try {
      const data = await uatCandidates(projectId, selected)
      const payload = data?.payload || data
      const base = (payload?.sections?.s2_scope?.criteria || []).map((r) => ({ ...r }))
      setCriteria(base)
      setBaseCriteria(base.map((r) => ({ ...r })))
      setPicks({})
      setPreview(payload)
      setStep(1)
    } catch {
      /* ES9-UAT-0001：拦截器已展示后端 message，回退 Step1 */
      setStep(0)
    }
  }

  const submit = async () => {
    // 冲突二选一后仅保留所选行；阈值有改动或发生过选择 → 提交覆写
    const dropIdx = new Set()
    groups.forEach((g) => {
      g.idxs.forEach((i) => { if (i !== picks[g.metric]) dropIdx.add(i) })
    })
    const override = criteria.filter((_, i) => !dropIdx.has(i))
    const overridden = dropIdx.size > 0
    const body = {
      task_ids: selected,
      criteria_override: overridden ? override : null,
      contract_no: contractNo || null,
      defect_disposals: Object.keys(disposals).length ? disposals : null,
    }
    setCreating(true)
    try {
      const rep = mode === 'resample'
        ? await resampleUat(projectId, reportId, body)
        : await createUat(projectId, body)
      message.success(`验收报告 v${rep?.uat_version ?? (mode === 'resample' ? 'n+1' : 1)} 已生成（草稿）`)
      onCreated?.(rep)
    } catch (err) {
      if (String(err?.message || '').includes('门禁')) setStep(0)
    } finally {
      setCreating(false)
    }
  }

  const taskColumns = [
    { title: '编号', dataIndex: 'task_no', render: (v) => <span className="mono">{v}</span> },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '状态', dataIndex: 'status', render: (s) => <Tag>{s}</Tag> },
    {
      title: '质量门禁',
      key: 'gate',
      render: (_, t) => {
        const n = parseGateRules(t.gate_rules).length
        return n ? <Tag color="green">{n} 条</Tag> : <Tag color="red">未配置</Tag>
      },
    },
  ]

  return (
    <Modal
      title={mode === 'resample' ? '重生成验收报告（新版本）' : '生成验收报告'}
      open={open}
      onCancel={onClose}
      width={920}
      destroyOnClose
      footer={
        <Space>
          {step > 0 && <Button onClick={() => setStep(step - 1)}>上一步</Button>}
          {step === 0 && (
            <Button type="primary" disabled={!selected.length} onClick={goPreview}>
              下一步：确定标准
            </Button>
          )}
          {step === 1 && (
            <Button type="primary" disabled={unresolved.length > 0} loading={recomputing} onClick={goPreview2}>
              下一步：预览
            </Button>
          )}
          {step === 2 && (
            <Button type="primary" loading={creating} onClick={submit}>
              生成草稿
            </Button>
          )}
          <Button onClick={onClose}>取消</Button>
        </Space>
      }
    >
      <Steps
        size="small"
        current={step}
        items={[{ title: '选择任务' }, { title: '确定标准' }, { title: '预览生成' }]}
        style={{ margin: '8px 0 20px' }}
      />

      {step === 0 && (
        <Table
          rowKey="id"
          size="small"
          loading={tasksLoading}
          dataSource={tasks}
          columns={taskColumns}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          rowSelection={{
            selectedRowKeys: selected,
            onChange: (keys) => setSelected(keys),
            getCheckboxProps: (t) => ({ disabled: !!disabledReason(t) }),
            renderCell: (_, t, index, origin) =>
              disabledReason(t) ? <Tooltip title={disabledReason(t)}><span>{origin}</span></Tooltip> : origin,
          }}
        />
      )}

      {step === 1 && (
        <>
          {unresolved.length > 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message={`指标「${unresolved.map((g) => g.metric).join('、')}」存在多个阈值，请二选一`}
            />
          )}
          <Typography.Text strong>验收标准（可覆写阈值）</Typography.Text>
          <Table
            rowKey={(_, i) => i}
            size="small"
            pagination={false}
            style={{ margin: '8px 0 16px' }}
            dataSource={criteria}
            rowClassName={(r) => {
              const i = criteria.indexOf(r)
              return groups.some((g) => g.idxs.includes(i)) ? 'uat-row-conflict' : ''
            }}
            columns={[
              {
                title: '冲突项', width: 90, render: (_, r) => {
                  const i = criteria.indexOf(r)
                  const g = groups.find((x) => x.idxs.includes(i))
                  return g ? (
                    <Radio
                      checked={picks[g.metric] === i}
                      onChange={() => setPicks({ ...picks, [g.metric]: i })}
                    />
                  ) : null
                },
              },
              { title: '指标', dataIndex: 'metric' },
              { title: '比较', dataIndex: 'op', width: 80 },
              {
                title: '阈值',
                dataIndex: 'threshold',
                width: 140,
                render: (v, r) => (
                  <Input
                    size="small"
                    value={v}
                    onChange={(e) => {
                      const next = [...criteria]
                      next[criteria.indexOf(r)] = { ...r, threshold: e.target.value }
                      setCriteria(next)
                    }}
                  />
                ),
              },
            ]}
          />
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Input
              addonBefore="合同编号"
              maxLength={64}
              value={contractNo}
              onChange={(e) => setContractNo(e.target.value)}
              placeholder="选填，将打印在 §2 验收依据"
            />
            <div>
              <Typography.Text strong>遗留缺陷处置（§7）</Typography.Text>
              {(preview?.sections?.s7_defects || []).length === 0 && (
                <Typography.Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
                  无未闭环严重级缺陷。
                </Typography.Paragraph>
              )}
              {(preview?.sections?.s7_defects || []).map((d) => (
                <div key={d.id} style={{ border: '1px solid #DCDFE6', borderRadius: 6, padding: 8, marginTop: 8 }}>
                  <div style={{ marginBottom: 6 }}>
                    <span className="mono">{d.defect_no}</span> {d.title} <Tag>{d.severity}</Tag>
                  </div>
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Input
                      size="small"
                      placeholder="承诺期限（如 2026-11-30）"
                      value={disposals[d.id]?.deadline || ''}
                      onChange={(e) => setDisposals({ ...disposals, [d.id]: { ...disposals[d.id], deadline: e.target.value } })}
                    />
                    <Input.TextArea
                      size="small"
                      rows={1}
                      placeholder="豁免理由（勾选带缺陷通过时必填）"
                      value={disposals[d.id]?.waiver || ''}
                      onChange={(e) => setDisposals({ ...disposals, [d.id]: { ...disposals[d.id], waiver: e.target.value } })}
                    />
                  </Space>
                </div>
              ))}
            </div>
          </Space>
        </>
      )}

      {step === 2 && preview && (
        <div className="uat-paper uat-doc" style={{ maxHeight: 480, overflow: 'auto', padding: '24px 32px' }}>
          <Typography.Paragraph type="secondary">以下为 §1–§7 只读预览，确认后生成 DRAFT 草稿。</Typography.Paragraph>
          <UatSections payload={preview} upTo={7} />
        </div>
      )}
    </Modal>
  )

  function localMergeOverride(payload, ov) {
    // 本地合并覆写结果（后端重算失败时的兜底；§7 处置意见为纯前端录入，两种路径都本地合入）
    const withDisposals = (src) => (src || []).map((d) => ({
      ...d,
      disposal: disposals[d.id]?.deadline || disposals[d.id]?.waiver ? disposals[d.id] : d.disposal,
    }))
    return {
      ...payload,
      sections: {
        ...payload.sections,
        s2_scope: {
          ...payload.sections.s2_scope,
          criteria: ov,
          criteria_source: 'override',
          contract_no: contractNo || '',
        },
        s7_defects: withDisposals(payload.sections.s7_defects),
      },
    }
  }

  async function goPreview2() {
    // Step2 → Step3：交后端 candidates 带覆权重算（与 create 同口径），失败回退本地合并
    const dropIdx = new Set()
    groups.forEach((g) => g.idxs.forEach((i) => { if (i !== picks[g.metric]) dropIdx.add(i) }))
    const override = criteria.filter((_, i) => !dropIdx.has(i))
    const overridden = dropIdx.size > 0
      || criteria.some((r, i) => !dropIdx.has(i) && String(r.threshold) !== String(baseCriteria[i]?.threshold))
    if (!overridden && !contractNo) {
      setPreview(localMergeOverride(preview, override))
      setStep(2)
      return
    }
    setRecomputing(true)
    try {
      const data = await uatCandidates(projectId, selected, {
        criteriaOverride: overridden ? override : undefined,
        contractNo: contractNo || undefined,
      })
      setPreview(localMergeOverride(data?.payload || data, override))
      setStep(2)
    } catch {
      /* 后端重算失败（覆写非法等）→ 拦截器已提示，本地合并兜底预览 */
      setPreview(localMergeOverride(preview, override))
      setStep(2)
    } finally {
      setRecomputing(false)
    }
  }
}
