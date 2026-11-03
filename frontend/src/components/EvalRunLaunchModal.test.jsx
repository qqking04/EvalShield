// ES10-P-03/P-01：发起评测共享弹窗契约回归（零网络：http 全 mock）
// 覆盖方案 §4 L3 用例 V-L-1 ~ V-L-9（优化10测试方案.md）。
// 断言以方案预期为准；组件实现与方案不符处不改断言（缺陷另行记录）。
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { App } from 'antd'
import http from '../api/http'
import EvalRunLaunchModal from './EvalRunLaunchModal'

vi.mock('../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

const BANK = { id: 5, name: '题库G', question_count: 2 }
const BANK_X = { id: 7, name: '库X', question_count: 9 }

beforeEach(() => {
  vi.clearAllMocks()
  http.get.mockImplementation((url) => {
    if (url === '/question-banks') return Promise.resolve({ items: [BANK] })
    if (url === '/eval-sets') return Promise.resolve({ items: [{ id: 2, code: 'ES-A', name: '集A' }] })
    if (url === '/model-configs') return Promise.resolve({ items: [{ code: 'm-a', name: '模型A', status: 'ACTIVE' }] })
    if (url === '/fact-sources') return Promise.resolve({ items: [{ id: 3, name: 'FS3', status: 'active' }] })
    return Promise.resolve({ items: [] })
  })
  http.post.mockResolvedValue({ id: 1 })
})

function open(bank = null) {
  render(
    <MemoryRouter>
      <App>
        <EvalRunLaunchModal open onClose={vi.fn()} initialQuestionBank={bank} />
      </App>
    </MemoryRouter>,
  )
}

async function pickOption(fieldId, text) {
  const sel = document.getElementById(fieldId).closest('.ant-select')
  fireEvent.mouseDown(sel.querySelector('.ant-select-selector'))
  fireEvent.click(await screen.findByText(text))
}

async function submitWithTarget() {
  fireEvent.change(screen.getByLabelText('被测对象标识'), { target: { value: 'gpt-test' } })
  fireEvent.click(screen.getByText('开始评测').closest('button'))
  await waitFor(() => expect(http.post).toHaveBeenCalledWith('/eval-runs', expect.anything()))
  return http.post.mock.calls[0][1]
}

describe('EvalRunLaunchModal（ES10-P-03 断链修复）', () => {
  // V-L-1 挂载预取题库
  it('V-L-1 挂载即预取题库列表，下拉可选题库非空', async () => {
    open()
    await waitFor(() => expect(http.get).toHaveBeenCalledWith('/question-banks', expect.anything()))
    await pickOption('question_bank_id', '题库G（2 题）')
    expect(screen.getByText('该题库共 2 题')).toBeInTheDocument()
  })

  // V-L-2 题库必填拦截
  it('V-L-2 题库必填：未选题库点开始评测 → 拦截并提示，不发 POST', async () => {
    open()
    fireEvent.click(screen.getByText('开始评测').closest('button'))
    // 校验错误经 rc-motion 异步挂载（jsdom 下需等 motionDeadline），放宽超时
    await waitFor(() => {
      const help = document.getElementById('question_bank_id_help')
      expect(help?.textContent).toContain('请选择题库（评测必须绑定题库）')
    }, { timeout: 4000 })
    expect(http.post).not.toHaveBeenCalled()
  })

  // V-L-3 initialQuestionBank 锁定
  it("V-L-3 initialQuestionBank={id:7,name:'库X'} → 锁定+显示「库X」+payload 含 question_bank_id:7", async () => {
    http.get.mockImplementation((url) => {
      if (url === '/question-banks') return Promise.resolve({ items: [BANK, BANK_X] })
      if (url === '/eval-sets') return Promise.resolve({ items: [] })
      if (url === '/model-configs') return Promise.resolve({ items: [{ code: 'm-a', name: '模型A', status: 'ACTIVE' }] })
      if (url === '/fact-sources') return Promise.resolve({ items: [] })
      return Promise.resolve({ items: [] })
    })
    const onSuccess = vi.fn()
    render(
      <MemoryRouter>
        <App>
          <EvalRunLaunchModal open onClose={vi.fn()} onSuccess={onSuccess} initialQuestionBank={BANK_X} />
        </App>
      </MemoryRouter>,
    )
    await screen.findByText('用题库「库X」发起评测')
    const sel = document.getElementById('question_bank_id').closest('.ant-select')
    expect(sel.className).toContain('ant-select-disabled')
    await waitFor(() => expect(screen.getByText('库X（9 题）')).toBeInTheDocument())
    const payload = await submitWithTarget()
    expect(payload.question_bank_id).toBe(7)
    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
  })

  // V-L-4 空态给去路（Link 渲染断言，非裸"暂无数据"）
  it('V-L-4 题库空列表 → notFoundContent 渲染去题库页 Link', async () => {
    http.get.mockImplementation((url) => {
      if (url === '/question-banks') return Promise.resolve({ items: [] })
      return Promise.resolve({ items: [] })
    })
    open()
    const sel = document.getElementById('question_bank_id').closest('.ant-select')
    fireEvent.mouseDown(sel.querySelector('.ant-select-selector'))
    await screen.findByText('暂无题库')
    const link = await screen.findByRole('link', { hidden: true })
    expect(link.getAttribute('href')).toBe('/question-banks')
    // 方案预期文案「去新建题库」——实现文案差异记入笔误清单
    expect(link.textContent).toContain('去新建题库')
  })

  // V-L-5 payload 完整
  it('V-L-5 sample_size=50 + 事实基准=3 + RULE → payload 三键齐全且无 null/空串键', async () => {
    open(BANK)
    await screen.findByText('用题库「题库G」发起评测')
    fireEvent.change(screen.getByLabelText('抽题数量'), { target: { value: '50' } })
    await pickOption('fact_source_id', 'FS3')
    const payload = await submitWithTarget()
    expect(payload.question_bank_id).toBe(5)
    expect(payload.sample_size).toBe(50)
    expect(payload.fact_source_id).toBe(3)
    expect(payload.judge_mode).toBe('RULE')
    // 不含 fact_source_id:null/'' 之类空值键（delete 空键逻辑）
    expect(Object.values(payload).every((v) => v !== null && v !== '')).toBe(true)
  })

  // V-L-6 全量语义
  it('V-L-6 抽题数量留空 → payload 无 sample_size 键', async () => {
    open(BANK)
    await screen.findByText('用题库「题库G」发起评测')
    const payload = await submitWithTarget()
    expect(payload).not.toHaveProperty('sample_size')
    expect(payload).not.toHaveProperty('fact_source_id')
  })

  // V-L-7 judge_model 条件显隐 + RULE 不进 payload
  it('V-L-7 切模型裁判出现「裁判模型」，切回规则判定消失且不进 payload', async () => {
    open(BANK)
    await screen.findByText('用题库「题库G」发起评测')
    expect(screen.queryByText('裁判模型')).not.toBeInTheDocument()
    await pickOption('judge_mode', '模型裁判')
    await waitFor(() => expect(screen.getByText('裁判模型')).toBeInTheDocument())
    await pickOption('judge_model', '模型A（m-a）')
    await pickOption('judge_mode', '规则判定')
    await waitFor(() => expect(screen.queryByText('裁判模型')).not.toBeInTheDocument())
    const payload = await submitWithTarget()
    expect(payload.judge_mode).toBe('RULE')
    expect(payload).not.toHaveProperty('judge_model')
  })

  // V-L-8 eval_set_id 可选（拆两个独立用例：同 it 内二次 render 会产生重复 DOM）
  it('V-L-8a 评测集不选可提交（方案预期：不选评测集可提交）', async () => {
    open(BANK)
    await screen.findByText('用题库「题库G」发起评测')
    const payload = await submitWithTarget()
    expect(http.post).toHaveBeenCalledTimes(1)
    expect(payload.question_bank_id).toBe(5)
  })

  it('V-L-8b 选中评测集 → payload 含 eval_set_id', async () => {
    open(BANK)
    await screen.findByText('用题库「题库G」发起评测')
    await pickOption('eval_set_id', 'ES-A - 集A')
    const payload = await submitWithTarget()
    expect(payload.eval_set_id).toBe(2)
  })

  // V-L-9 失败回显进表单
  it('V-L-9 发起失败：后端 message 回显在表单顶部 Alert，不关闭弹窗', async () => {
    const onClose = vi.fn()
    render(
      <MemoryRouter>
        <App>
          <EvalRunLaunchModal open onClose={onClose} initialQuestionBank={BANK} />
        </App>
      </MemoryRouter>,
    )
    await screen.findByText('用题库「题库G」发起评测')
    http.post.mockRejectedValue(new Error('知识源不存在'))
    fireEvent.change(screen.getByLabelText('被测对象标识'), { target: { value: 'gpt-test' } })
    fireEvent.click(screen.getByText('开始评测').closest('button'))
    await screen.findByText('知识源不存在')
    expect(onClose).not.toHaveBeenCalled()
  })
})
