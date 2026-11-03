/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES9 UAT 前端契约测试（§6.2 R02 骨架）
// 断言：Step1 门禁禁用+tooltip / Step2 冲突二选一阻塞 / Step3 生成 toast v1 草稿 /
//       CONDITIONAL 空 note 必填拦截 / FINALIZED 签核栏 disabled 非隐藏 / 版本链面包屑 v1 › 当前
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import http from '../../api/http'
import { listUat, getUat, uatCandidates, createUat, signUat } from '../../api/uat'
import UatReportList from './UatReportList'
import UatWizard from './UatWizard'
import UatReportDetail from './UatReportDetail'

vi.mock('../../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))
vi.mock('../../api/uat', () => ({
  listUat: vi.fn(),
  getUat: vi.fn(),
  uatCandidates: vi.fn(),
  createUat: vi.fn(),
  signUat: vi.fn(),
  rejectUat: vi.fn(),
  resampleUat: vi.fn(),
  shareUat: vi.fn(),
  exportUat: vi.fn(),
}))
vi.mock('../../auth', () => ({
  useAuth: () => ({ user: { username: 'vendor01' }, loading: false, hasPerm: () => true, licensed: false }),
}))
vi.mock('../../edition/EditionContext', () => {
  const useEdition = () => ({ edition: 'community', commercial: false })
  return {
    useEdition,
    useIsCommunity: () => true,
    IS_COMMUNITY_BUILD: true,
    default: { create: (v) => v },
  }
})

/* ---------------- 数据工厂 ---------------- */

const TASKS = {
  items: [
    { id: 1, task_no: 'T-001', name: '核心流程回归', status: 'SUCCESS', gate_rules: '[{"metric":"pass_rate","op":">=","threshold":0.95}]' },
    { id: 2, task_no: 'T-002', name: '未配门禁任务', status: 'SUCCESS', gate_rules: '[]' },
    { id: 3, task_no: 'T-003', name: '进行中任务', status: 'RUNNING', gate_rules: '[{"metric":"pass_rate","op":">=","threshold":0.9}]' },
  ],
}

// pass_rate 双行 → 冲突组，须二选一
const CANDIDATES = {
  preview: null,
  payload: {
    report_no: 'UAT-20261020-0001',
    title: 'UAT 验收报告',
    uat_version: 1,
    task_ids: [1],
    report_hash: 'a'.repeat(64),
    sections: {
      s1_overview: { project_id: 1, task_nos: ['T-001'] },
      s2_scope: {
        criteria_source: 'gate_rules',
        contract_no: '',
        criteria: [
          { metric: 'pass_rate', op: '>=', threshold: 0.95 },
          { metric: 'pass_rate', op: '>=', threshold: 0.98 },
          { metric: 'p95_rt', op: '<=', threshold: 200 },
        ],
      },
      s3_environment: { env: { os: 'linux' }, distinct_env_count: 1 },
      s4_results: { per_task: [{ task_id: 1, task_no: 'T-001', title: '核心流程回归', cases: 100, pass_rate: 0.98, verdict: 'PASSED' }], total_cases: 100, agg_pass_rate: 0.98 },
      s5_gate: { checks: [{ metric: 'pass_rate', op: '>=', threshold: 0.95, actual: 0.98, passed: true }], verdict: 'PASSED' },
      s6_perf_security: { performance: { tps: 1200 }, security: { risk_level: 'low', risk_basis: [] } },
      s7_defects: [],
      s8_conclusion: { verdict_suggested: 'PASSED' },
    },
  },
}

function detailOf({ status = 'DRAFT', acceptance = {}, version = 1, chain = [], id = 10 } = {}) {
  return {
    id,
    report_no: 'UAT-20261020-0001',
    title: 'UAT 验收报告',
    uat_version: version,
    generated_at: '2026-10-20T10:00:00',
    acceptance: { status, ...acceptance },
    content: JSON.parse(JSON.stringify(CANDIDATES.payload)),
    chain,
  }
}

function renderDetail(id = 10) {
  return render(
    <MemoryRouter initialEntries={[`/uat/${id}?project=1`]}>
      <Routes>
        <Route path="/uat/:reportId" element={<UatReportDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

/** rc-table 复选框无无障碍名：boxes[0]=表头全选，其后按行序 */
async function getCheckBoxes() {
  await waitFor(() => expect(screen.getByText('T-001')).toBeInTheDocument())
  return screen.findAllByRole('checkbox')
}

/** 向导走完 Step1→Step3（含冲突二选一） */
async function walkToStep3(user) {
  const boxes = await getCheckBoxes()
  await user.click(boxes[1]) // T-001
  await user.click(screen.getByRole('button', { name: '下一步：确定标准' }))
  await waitFor(() => expect(uatCandidates).toHaveBeenCalled())
  // Step2 初始：冲突未解 → 预览禁用
  expect(screen.getByRole('button', { name: '下一步：预览' })).toBeDisabled()
  const rows = screen.getAllByRole('radio')
  await user.click(rows[0]) // pass_rate 保留第一行
  await waitFor(() => expect(screen.getByRole('button', { name: '下一步：预览' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: '下一步：预览' }))
  await waitFor(() => expect(screen.getByText('生成草稿')).toBeInTheDocument())
}

beforeEach(() => {
  vi.clearAllMocks()
  http.get.mockImplementation((url) => {
    if (url === '/tasks') return Promise.resolve(TASKS)
    return Promise.resolve({})
  })
  uatCandidates.mockResolvedValue(CANDIDATES)
  createUat.mockResolvedValue({ id: 11, uat_version: 1 })
})

/* ---------------- ① Step1 门禁禁用 + 原因 tooltip ---------------- */

describe('UatWizard Step1 任务准入', () => {
  it('未配门禁/非终态任务禁用勾选并给出原因 tooltip', async () => {
    // 禁用行 checkbox 带 pointer-events:none，hover 其容器 span 需跳过该项检查
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render(<UatWizard open projectId={1} onClose={() => {}} />)
    const boxes = await getCheckBoxes()
    expect(boxes[2]).toBeDisabled() // T-002 未配门禁
    expect(boxes[3]).toBeDisabled() // T-003 非终态
    expect(boxes[1]).toBeEnabled()

    // Tooltip 挂在 renderCell 的 <span>（checkbox 父级）上 → hover checkbox 冒泡触发
    await user.hover(boxes[2])
    expect(await screen.findByText('该任务未配置质量门禁，请先在任务设置中配置')).toBeInTheDocument()
    await user.unhover(boxes[2])

    await user.hover(boxes[3])
    expect(await screen.findByText(/仅终态（SUCCESS \/ COMPLETED_WITH_RISK）可纳入验收/)).toBeInTheDocument()
  })
})

/* ---------------- ② Step2 冲突二选一阻塞 + ③ Step3 生成 toast ---------------- */

describe('UatWizard 三步流转', () => {
  it('冲突阈值未二选一不可进 Step3；生成成功 toast「验收报告 v1 已生成（草稿）」并回传报告', async () => {
    const user = userEvent.setup()
    const onCreated = vi.fn()
    render(<UatWizard open projectId={1} onClose={() => {}} onCreated={onCreated} />)
    await walkToStep3(user)

    // Step3 预览含 §5 门禁结论，且不含 §8
    expect(screen.getByText('§5 质量门禁结论')).toBeInTheDocument()
    expect(screen.queryByText('§8 验收结论与签核')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '生成草稿' }))
    await waitFor(() =>
      expect(createUat).toHaveBeenCalledWith(1, expect.objectContaining({
        task_ids: [1],
        criteria_override: [
          { metric: 'pass_rate', op: '>=', threshold: 0.95 },
          { metric: 'p95_rt', op: '<=', threshold: 200 },
        ],
      })),
    )
    expect(await screen.findByText('验收报告 v1 已生成（草稿）')).toBeInTheDocument()
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 11 }))
  })
})

/* ---------------- ④ CONDITIONAL 空 note 必填拦截 ---------------- */

describe('签署验收 Modal', () => {
  it('verdict=CONDITIONAL 且 note 为空 → 后端同款必填文案拦截，不发起签署', async () => {
    const user = userEvent.setup()
    getUat.mockResolvedValue(detailOf({ status: 'DRAFT' }))
    renderDetail()
    await waitFor(() => expect(screen.getByText('UAT-20261020-0001')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: '签署验收' }))
    await waitFor(() => expect(screen.getByText('签署验收（供应商）')).toBeInTheDocument())
    await user.click(screen.getByRole('radio', { name: '有条件通过' }))
    // note textarea 展开且为空
    const note = screen.getByPlaceholderText('有条件通过必须填写豁免说明（note）')
    expect(note).toBeInTheDocument()
    // okText=「签署验收」，与吸底栏同名 → 取弹窗容器内的确认按钮
    const modal = document.querySelector('.ant-modal')
    await user.click(within(modal).getByRole('button', { name: '签署验收' }))
    expect(await screen.findByText('有条件通过必须填写豁免说明（note）')).toBeInTheDocument()
    expect(signUat).not.toHaveBeenCalled()
  })

  it('PASSED 直签成功 → toast「已签署，等待客户确认」', async () => {
    const user = userEvent.setup()
    getUat.mockResolvedValue(detailOf({ status: 'DRAFT' }))
    signUat.mockResolvedValue({ status: 'VENDOR_SIGNED' })
    renderDetail()
    await waitFor(() => expect(screen.getByText('UAT-20261020-0001')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: '签署验收' }))
    await waitFor(() => expect(screen.getByText('签署验收（供应商）')).toBeInTheDocument())
    const modal = document.querySelector('.ant-modal')
    await user.click(within(modal).getByRole('button', { name: '签署验收' }))
    expect(await screen.findByText('已签署，等待客户确认')).toBeInTheDocument()
    expect(signUat).toHaveBeenCalledWith(1, 10, expect.objectContaining({ name: 'vendor01', verdict: 'PASSED' }))
  })
})

/* ---------------- ⑤ FINALIZED 签核栏 disabled 非隐藏 ---------------- */

describe('终态锁', () => {
  it('acceptance.status=FINALIZED → 签署按钮 disabled 且可见', async () => {
    getUat.mockResolvedValue(
      detailOf({
        status: 'FINALIZED',
        acceptance: { verdict: 'PASSED', signer_vendor: { name: 'vendor01', signed_at: '2026-10-20' } },
      }),
    )
    renderDetail()
    await waitFor(() => expect(screen.getByText('UAT-20261020-0001')).toBeInTheDocument())
    const btn = screen.getByRole('button', { name: '签署验收' })
    expect(btn).toBeInTheDocument()
    expect(btn).toBeDisabled()
    expect(screen.getByText('已归档')).toBeInTheDocument()
  })
})

/* ---------------- ⑥ 版本链面包屑 v1 › 当前 ---------------- */

describe('版本链面包屑', () => {
  it('chain=[v1 REJECTED] → 面包屑渲染 v1 已拒收 › 当前 v2', async () => {
    getUat.mockResolvedValue(
      detailOf({
        id: 20,
        status: 'REJECTED',
        version: 2,
        acceptance: { verdict: null, reject_reason: '数据不符' },
        chain: [{ id: 10, report_no: 'UAT-20261020-0001', version: 1, status: 'REJECTED' }],
      }),
    )
    renderDetail(20)
    await waitFor(() => expect(screen.getByText('当前 v2')).toBeInTheDocument())
    // Typography.Link（无 href 的 <a>）：按文本定位
    expect(screen.getByText('v1 已拒收')).toBeInTheDocument()
  })
})

/* ---------------- 列表空态与入口 ---------------- */

describe('UatReportList', () => {
  it('空态文案 + 生成入口按钮存在', async () => {
    listUat.mockResolvedValue({ items: [], total: 0 })
    render(
      <MemoryRouter>
        <UatReportList projectId={1} />
      </MemoryRouter>,
    )
    expect(await screen.findByText('选择已配置质量门禁的测试任务，即可生成双方签核的验收报告')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /生成验收报告/ })).toBeInTheDocument()
  })

  it('行渲染：版本/编号/状态中文/步骤条', async () => {
    listUat.mockResolvedValue({
      items: [{ id: 10, report_no: 'UAT-20261020-0001', title: 'UAT 验收报告', version: 1, status: 'VENDOR_SIGNED', verdict: 'CONDITIONAL', created_at: '2026-10-20T10:00:00' }],
      total: 1,
    })
    render(
      <MemoryRouter>
        <UatReportList projectId={1} />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('UAT-20261020-0001')).toBeInTheDocument())
    expect(screen.getByText('v1')).toBeInTheDocument()
    expect(screen.getByText('等待客签')).toBeInTheDocument()
    expect(screen.getByText('有条件通过')).toBeInTheDocument()
  })
})
