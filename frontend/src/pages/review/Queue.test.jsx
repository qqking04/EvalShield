// ES8-BUG-008 复核工作台契约测试（ES9-P-10 三栏工作台）
// 键盘流必须走 userEvent.keyboard：j/k 移动、1/2/3 选处置、e 备注、s 保存跳下一条。
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { App } from 'antd'
import http from '../../api/http'
import ReviewQueuePage from './Queue'
import { useAuth } from '../../auth'

vi.mock('../../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
vi.mock('../../auth', () => ({ useAuth: vi.fn() }))
vi.mock('echarts-for-react', () => ({ default: () => <div data-testid="echarts-mock" /> }))
vi.mock('react-countup', () => ({ default: ({ end }) => <span>{end ?? 0}</span> }))

const QUEUE_PAYLOAD = {
  items: [
    { id: 11, status: 'OPEN', source: 'run_item', auto_verdict: 'PASS', auto_confidence: 0.9, context: { no: 'S-1', prompt: '注入样本A', category: 'SEC', rule_verdict: 'PASS' } },
    { id: 12, status: 'OPEN', source: 'trace', auto_verdict: 'FAIL', auto_confidence: 0.8, context: { no: 'S-2', prompt: '链路样本B', category: 'RAG', rule_verdict: 'PASS' } },
  ],
  total: 2,
  stats: { pending: 2, processed_today: 3, agreement: 0.85 },
}

const routes = new Map()
function matchRoute(url) {
  let best = null
  for (const k of routes.keys()) {
    if (url === k || url.startsWith(k)) {
      if (best === null || k.length > best.length) best = k
    }
  }
  return best
}

function setAuth({ perms = ['review:manage'] } = {}) {
  useAuth.mockReturnValue({
    user: { id: 1 },
    loading: false,
    licensed: true,
    hasPerm: (p) => (p === '*' ? true : perms.includes(p)),
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  routes.clear()
  setAuth()
  routes.set('/review/queue', QUEUE_PAYLOAD)
  http.get.mockImplementation((url) => {
    const k = matchRoute(url)
    if (k === null) return Promise.resolve({})
    const v = routes.get(k)
    return Promise.resolve(typeof v === 'function' ? v(url) : v)
  })
  http.post.mockResolvedValue({ ok: true })
})

const page = (ui) => render(<App><MemoryRouter>{ui}</MemoryRouter></App>)

describe('ReviewQueue 三栏复核工作台（键盘流）', () => {
  it('初始加载契约：GET /review/queue 分页参数 + 队列行/统计条/分组渲染', async () => {
    page(<ReviewQueuePage />)
    await waitFor(() => expect(screen.getByTestId('review-workbench')).toBeInTheDocument())
    expect(screen.getByTestId('queue-row-11')).toBeInTheDocument()
    expect(screen.getByTestId('queue-row-12')).toBeInTheDocument()
    expect(screen.getByTestId('queue-group-SEC')).toBeInTheDocument()
    expect(screen.getByText('85%')).toBeInTheDocument() // stats.agreement=0.85
    expect(screen.getByText(/项 #11/)).toBeInTheDocument() // 默认选中第一条
    expect(http.get).toHaveBeenCalledWith('/review/queue', {
      params: { page: 1, page_size: 50, status: 'OPEN' },
    })
  })

  it('userEvent 键盘流：j/k 移动 → e 备注聚焦 → 打字不触发热键 → Esc 失焦 → 2 选 FAIL → s 保存并跳下一条', async () => {
    const user = userEvent.setup()
    page(<ReviewQueuePage />)
    await waitFor(() => expect(screen.getByTestId('queue-row-11')).toBeInTheDocument())

    await user.keyboard('j')
    await waitFor(() => expect(screen.getByText(/项 #12/)).toBeInTheDocument())
    await user.keyboard('k')
    await waitFor(() => expect(screen.getByText(/项 #11/)).toBeInTheDocument())

    // e：备注框聚焦（noteRef.focus）
    await user.keyboard('e')
    await waitFor(() =>
      expect(document.activeElement).toHaveAttribute(
        'placeholder',
        '记录判定依据，供评审 prompt 校准回溯',
      ),
    )

    // typing 保护：输入框内的 1/2 不得改变处置选择
    await user.type(document.activeElement, '判定依据X')
    await user.keyboard('2')
    expect(screen.getByTestId('disposition-FAIL')).not.toBeChecked()

    // Esc 失焦后：2 选 FAIL，s 保存 → POST decision → 自动跳到下一条
    await user.keyboard('{Escape}')
    await user.keyboard('2')
    expect(screen.getByTestId('disposition-FAIL')).toBeChecked()
    await user.keyboard('s')
    await waitFor(() =>
      expect(http.post).toHaveBeenCalledWith('/review/items/11/decision', {
        verdict: 'FAIL',
        note: '判定依据X2',
        promote_rule: false,
      }),
    )
    await waitFor(() => expect(screen.getByText(/项 #12/)).toBeInTheDocument())
  })

  it('1/2/3 处置映射 PASS/FAIL/RETURN；未选处置时 s 保存不发请求', async () => {
    const user = userEvent.setup()
    page(<ReviewQueuePage />)
    await waitFor(() => expect(screen.getByTestId('disposition-PASS')).toBeInTheDocument())
    await user.keyboard('1')
    expect(screen.getByTestId('disposition-PASS')).toBeChecked()
    await user.keyboard('3')
    expect(screen.getByTestId('disposition-RETURN')).toBeChecked()

    // 切到下一条后处置重置；未选处置直接 s → 仅提示不发 POST
    await user.keyboard('j')
    await user.keyboard('s')
    await waitFor(() => expect(screen.getByText(/项 #12/)).toBeInTheDocument())
    expect(http.post).not.toHaveBeenCalled()
  })

  it('无 review:manage 权限：处置面板隐藏，键盘热键全部失效', async () => {
    setAuth({ perms: [] })
    const user = userEvent.setup()
    page(<ReviewQueuePage />)
    await waitFor(() => expect(screen.getByTestId('queue-row-11')).toBeInTheDocument())
    expect(screen.queryByTestId('disposition-PASS')).not.toBeInTheDocument()
    await user.keyboard('1s')
    expect(http.post).not.toHaveBeenCalled()
  })
})
