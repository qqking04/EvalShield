// 优化12 任务二：GBT45654 预设向导契约回归（零网络：http / api 层全 mock）
// 断言覆盖：
//  - BUG-005：POST /tasks 的每个引擎任务 config 必带 target_code（MULTI_TURN_TEST 后端硬要求）
//  - BUG-006：选题库后 getCoverage 返回 gaps → 渲染「子类题量缺口」Alert
//  - BUG-007 缓解：createEvalRun 超时 reject → 提示「发起请求超时…」且不 onClose、不跳转
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { App } from 'antd'
import http from '../api/http'
import { checkReadiness, createEvalRun, getStandardsDimensions } from '../api/es11'
import { getCoverage } from '../api/questionBanks'
import PresetLaunchWizard from './PresetLaunchWizard'

vi.mock('../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
vi.mock('../api/es11', () => ({
  getStandardsDimensions: vi.fn(),
  checkReadiness: vi.fn(),
  createEvalRun: vi.fn(),
}))
vi.mock('../api/questionBanks', () => ({
  getCoverage: vi.fn(),
}))

const PRESET = {
  preset_code: 'GBT45654-FULL',
  name: 'GBT45654 全量评估',
  calibrated: true,
  run_purpose: 'STANDARD',
  engines: ['SECURITY_TEST', 'MULTI_TURN_TEST'],
  dimension_order: ['DIM-A'],
  min_bank_questions: 100,
}
const META = {
  presets: [PRESET],
  dimensions: [{ dimension_code: 'DIM-A', dimension_name: '维度A' }],
  mapping: [
    { dimension_code: 'DIM-A', regulatory: true, bank_category: 'CAT1', min_questions: 30 },
  ],
}
const TARGET_OPT = 'TGT-001 - 被测甲'
const BANK_OPT = '题库G（ACTIVE）'
const PROJECT_OPT = 'PRJ-01 - 项目一'

/** 显示当前路由的探针，用于断言"未跳转"。 */
function LocProbe() {
  const loc = useLocation()
  return <div data-testid="loc">{loc.pathname}</div>
}

function openWizard(onClose = vi.fn()) {
  render(
    <MemoryRouter initialEntries={['/eval/center']}>
      <App>
        <PresetLaunchWizard open onClose={onClose} />
        <Routes>
          <Route path="*" element={<LocProbe />} />
        </Routes>
      </App>
    </MemoryRouter>,
  )
  return onClose
}

/** antd Select 无 id，用 placeholder 定位后 mouseDown 打开下拉，再点选项。 */
async function pickOption(placeholder, text) {
  const sel = screen.getByText(placeholder).closest('.ant-select')
  fireEvent.mouseDown(sel.querySelector('.ant-select-selector'))
  fireEvent.click(await screen.findByText(text))
}

/** step0 选预设 → step1 选齐项目/被测系统/题库 → 进入 G0 预检（step2）。 */
async function walkToStep2() {
  fireEvent.click(await screen.findByText('选择 ›'))
  await pickOption('项目（引擎任务归属）', PROJECT_OPT)
  await pickOption('被测系统', TARGET_OPT)
  await pickOption('题库', BANK_OPT)
  fireEvent.click(screen.getByText('下一步：G0 预检').closest('button'))
  await screen.findByText('发起评估活动')
}

beforeEach(() => {
  vi.clearAllMocks()
  getStandardsDimensions.mockResolvedValue(META)
  checkReadiness.mockResolvedValue({ ready: true, checks: [] })
  createEvalRun.mockResolvedValue({ id: 42, run_no: 'RUN-0042' })
  getCoverage.mockResolvedValue({ gaps: [] })
  http.post.mockResolvedValue({ id: 1 })
  http.get.mockImplementation((url) => {
    if (url === '/targets') return Promise.resolve({ items: [{ code: 'TGT-001', name: '被测甲' }] })
    if (url === '/question-banks') return Promise.resolve({ items: [{ id: 5, name: '题库G', status: 'ACTIVE' }] })
    if (url === '/projects') return Promise.resolve({ items: [{ id: 3, code: 'PRJ-01', name: '项目一' }] })
    return Promise.resolve({ items: [] })
  })
})

describe('PresetLaunchWizard（优化12 任务二）', () => {
  it('冒烟：打开向导 → 渲染标题与已核定预设表（选择按钮可用）', async () => {
    openWizard()
    await screen.findByText('GBT45654 全量评估 · 预设向导')
    await screen.findByText('GBT45654 全量评估')
    expect(screen.getByText('已核定')).toBeInTheDocument()
    expect(screen.getByText('选择 ›')).toBeInTheDocument()
  })

  // BUG-005：向导发起的每个引擎任务 config 必须携带 target_code
  it('BUG-005 走完向导后，每个引擎任务 POST /tasks 的 config 含 target_code', async () => {
    openWizard()
    await walkToStep2()
    fireEvent.click(screen.getByText('发起评估活动').closest('button'))
    await screen.findByText('评估活动已发起（运行 + 引擎任务共享活动编号）')
    const taskCalls = http.post.mock.calls.filter((c) => c[0] === '/tasks')
    expect(taskCalls.length).toBe(2) // SECURITY_TEST + MULTI_TURN_TEST
    for (const [, body] of taskCalls) {
      expect(body.config.target_code).toBe('TGT-001')
      expect(body.config.question_bank_id).toBe(5)
      expect(body.config.project_id ?? body.project_id).toBe(3)
      expect(body.config.activity_id).toBeTruthy()
    }
    // run 与任务共享同一 activity_id
    const runBody = createEvalRun.mock.calls[0][0]
    expect(taskCalls[0][1].config.activity_id).toBe(runBody.activity_id)
  })

  // BUG-006：选题库后 coverage gaps → 缺口 Alert
  it('BUG-006 所选题库存在子类题量缺口时渲染缺口 Alert 与明细 Tag', async () => {
    // 后端 gaps 仅返回真实缺口项，组件按数组长度计数
    getCoverage.mockResolvedValue({
      gaps: [{ category: 'CAT1', min_questions: 30, current_count: 10 }],
    })
    openWizard()
    fireEvent.click(await screen.findByText('选择 ›'))
    await pickOption('题库', BANK_OPT)
    await screen.findByText('所选题库存在 1 个子类题量缺口（发起后 G4 将 BLOCK）')
    expect(screen.getByText('CAT1 缺 20 题（10/30）')).toBeInTheDocument()
    expect(getCoverage).toHaveBeenCalledWith(5)
  })

  // BUG-007 缓解：createEvalRun 超时 → 明确超时提示、不关闭向导、不跳转
  it('BUG-007 createEvalRun 超时 reject → 提示超时且不 onClose、不跳转', async () => {
    const err = Object.assign(new Error('timeout of 60000ms exceeded'), { code: 'ECONNABORTED' })
    createEvalRun.mockRejectedValue(err)
    const onClose = openWizard()
    await walkToStep2()
    fireEvent.click(screen.getByText('发起评估活动').closest('button'))
    await screen.findByText(/发起请求超时/)
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByTestId('loc').textContent).toBe('/eval/center')
    expect(http.post).not.toHaveBeenCalled() // 未进入引擎任务创建环节
  })
})
