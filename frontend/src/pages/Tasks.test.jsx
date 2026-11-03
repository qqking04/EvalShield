// ES8-BUG-008 任务中心契约测试：初始加载端点 + 行渲染 + 执行/删除契约
// ES10-P-02：V-T-1 版本过滤 Tag（URL 参数进入 + 可移除）
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { App } from 'antd'
import http from '../api/http'
import Tasks from './Tasks'
import { useAuth } from '../auth'
import { useEdition } from '../edition/EditionContext'

vi.mock('../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
vi.mock('../auth', () => ({ useAuth: vi.fn() }))
vi.mock('../edition/EditionContext', () => ({ useEdition: vi.fn(), useIsCommunity: () => false }))

const TASK_ROW = {
  id: 5, task_no: 'T-20261001-005', name: '核心回归任务', project_code: 'P-1',
  engines: ['SEC_AUDIT'], status: 'COMPLETED', progress: 100, trigger_mode: 'MANUAL',
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

beforeEach(() => {
  vi.clearAllMocks()
  routes.clear()
  useAuth.mockReturnValue({
    user: { id: 1 }, loading: false, licensed: true,
    hasPerm: () => true,
  })
  useEdition.mockReturnValue({ edition: 'enterprise', enabled_engines: [] })
  routes.set('/tasks', { items: [TASK_ROW], total: 1 })
  routes.set('/projects', { items: [], total: 0 })
  routes.set('/engine-options', { items: [] })
  routes.set('/model-configs', { items: [] })
  routes.set('/eval-sets', [])
  routes.set('/targets', { items: [] })
  http.get.mockImplementation((url) => {
    const k = matchRoute(url)
    if (k === null) return Promise.resolve({})
    const v = routes.get(k)
    return Promise.resolve(typeof v === 'function' ? v(url) : v)
  })
  http.post.mockResolvedValue({ ok: true })
  http.delete.mockResolvedValue({ ok: true })
})

const page = (ui, entry = '/tasks') => render(<App><MemoryRouter initialEntries={[entry]}>{ui}</MemoryRouter></App>)

describe('Tasks 任务中心', () => {
  it('标题渲染 + 初始 GET 契约（列表/项目/引擎/模型/评测集/被测系统）', async () => {
    page(<Tasks />)
    await waitFor(() => expect(screen.getByText('任务中心')).toBeInTheDocument())
    expect(screen.getByText('T-20261001-005')).toBeInTheDocument()
    expect(screen.getByText('核心回归任务')).toBeInTheDocument()
    expect(http.get).toHaveBeenCalledWith('/tasks', { params: { page: 1, page_size: 10 } })
    expect(http.get).toHaveBeenCalledWith('/projects', { params: { page_size: 200 } })
    expect(http.get).toHaveBeenCalledWith('/engine-options')
    expect(http.get).toHaveBeenCalledWith('/model-configs')
    expect(http.get).toHaveBeenCalledWith('/eval-sets')
    expect(http.get).toHaveBeenCalledWith('/targets', { params: { status: 'ACTIVE', page_size: 200 } })
  })

  it('点击「执行」→ POST /tasks/{id}/run（空 body）', async () => {
    page(<Tasks />)
    await waitFor(() => expect(screen.getByText('T-20261001-005')).toBeInTheDocument())
    fireEvent.click(screen.getByText('执行'))
    await waitFor(() => expect(http.post).toHaveBeenCalledWith('/tasks/5/run', {}))
  })

  it('删除走 Popconfirm 确认 → DELETE /tasks/{id}', async () => {
    const { container } = page(<Tasks />)
    await waitFor(() => expect(screen.getByText('T-20261001-005')).toBeInTheDocument())
    fireEvent.click(screen.getByText('删除'))
    await waitFor(() => expect(screen.getByText('确认删除该任务？')).toBeInTheDocument())
    const okBtn = container.ownerDocument.querySelector('.ant-popconfirm .ant-btn-primary')
    fireEvent.click(okBtn)
    await waitFor(() => expect(http.delete).toHaveBeenCalledWith('/tasks/5'))
  })

  // ES10-P-02 V-T-1：URL 带 project_version_id → 列表参数携带 + 可移除「版本」Tag
  it('V-T-1 /tasks?project_version_id=9 → GET /tasks params 含该键 + 「版本」Tag，点 × 后参数消失', async () => {
    page(<Tasks />, '/tasks?project_version_id=9')
    await waitFor(() => expect(screen.getByText('T-20261001-005')).toBeInTheDocument())
    const callsWithPv = http.get.mock.calls.filter(
      ([url, opts]) => url === '/tasks' && opts?.params?.project_version_id === 9,
    )
    expect(callsWithPv.length).toBeGreaterThanOrEqual(1)
    // 筛选条出现可移除「版本」Tag（行数据无 project_id → 反查不触发，显示 #9）
    const tag = await screen.findByText(/版本：/)
    expect(tag.textContent).toContain('版本：')
    // 点 × 移除过滤
    const closeIcon = tag.closest('.ant-tag').querySelector('.anticon-close')
    expect(closeIcon).not.toBeNull()
    fireEvent.click(closeIcon)
    await waitFor(() => {
      const last = [...http.get.mock.calls].reverse().find(([url]) => url === '/tasks')
      expect(last[1].params).not.toHaveProperty('project_version_id')
    })
    await waitFor(() => expect(screen.queryByText(/版本：/)).not.toBeInTheDocument())
  })
})
