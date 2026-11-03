// ES8-BUG-008 仪表盘契约测试：有数据形态 + 空库引导形态 + GET /dashboard/stats
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { App } from 'antd'
import http from '../api/http'
import Dashboard from './Dashboard'

vi.mock('../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

beforeEach(() => {
  vi.clearAllMocks()
  http.get.mockResolvedValue({})
})

const page = (ui) => render(<App><MemoryRouter>{ui}</MemoryRouter></App>)

describe('Dashboard 仪表盘', () => {
  it('有数据：标题/统计卡/最近任务表渲染，GET /dashboard/stats 契约', async () => {
    http.get.mockResolvedValue({
      project_total: 3, task_total: 12, task_running: 1, task_success: 9, case_total: 480,
      engine_stats: [{ engine_type: 'SEC_AUDIT', count: 2 }],
      recent_tasks: [{ id: 9, task_no: 'T-9', name: '最近任务', status: 'COMPLETED', progress: 100, created_at: '2026-10-01T10:00:00' }],
    })
    page(<Dashboard />)
    await waitFor(() => expect(screen.getByText('仪表盘')).toBeInTheDocument())
    expect(screen.getByText('项目总数')).toBeInTheDocument()
    expect(screen.getByText('任务总数')).toBeInTheDocument()
    expect(screen.getByText('运行中任务')).toBeInTheDocument()
    expect(screen.getByText('成功任务')).toBeInTheDocument()
    expect(screen.getByText('最近执行任务')).toBeInTheDocument()
    expect(screen.getByText('T-9')).toBeInTheDocument()
    expect(http.get).toHaveBeenCalledWith('/dashboard/stats')
  })

  it('空库（项目/任务/用例全 0）：渲染三步引导首屏', async () => {
    http.get.mockResolvedValue({ project_total: 0, task_total: 0, case_total: 0 })
    page(<Dashboard />)
    await waitFor(() => expect(screen.getByText('欢迎使用 EvalShield')).toBeInTheDocument())
    expect(screen.getByText('创建项目')).toBeInTheDocument()
    expect(screen.getByText('导入用例库')).toBeInTheDocument()
    expect(screen.getByText('配置模型网关')).toBeInTheDocument()
    expect(screen.queryByText('仪表盘')).not.toBeInTheDocument()
  })
})
