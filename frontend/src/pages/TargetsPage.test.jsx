/*
 * /targets 黑屏回归：TargetsPage 曾使用 <Space> 但未从 antd 导入，
 * 渲染即抛 ReferenceError → 路由整页空白。
 * 本测试直接渲染 TargetsPage 本体（而非子 Tab 组件），锁死该缺陷不再复发。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { App } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import TargetsPage from './TargetsPage'

vi.mock('../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('../auth', () => ({ useAuth: vi.fn() }))
vi.mock('../api/factSources', () => ({
  listFactSources: vi.fn(), createFactSource: vi.fn(), updateFactSource: vi.fn(),
  deleteFactSource: vi.fn(), testFactSource: vi.fn(),
}))

import http from '../api/http'
import { useAuth } from '../auth'
import { listFactSources } from '../api/factSources'

describe('TargetsPage（/targets 一级入口）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({
      user: { id: 1 }, loading: false, licensed: true,
      hasPerm: () => true,
    })
    http.get.mockResolvedValue({ items: [], total: 0 })
    listFactSources.mockResolvedValue({ items: [], total: 0 })
  })

  it('本体渲染不抛错：标题 + 双子 Tab 均可见', () => {
    render(
      <App>
        <MemoryRouter initialEntries={['/targets']}>
          <TargetsPage />
        </MemoryRouter>
      </App>,
    )
    expect(screen.getByRole('heading', { name: '被测系统' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '被测系统注册' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '知识源' })).toBeInTheDocument()
    // 默认激活 targets 子 Tab → 触发被测系统列表请求
    expect(http.get).toHaveBeenCalledWith('/targets', { params: { page: 1, page_size: 10 } })
  })

  it('切换「知识源」Tab 不崩且触发知识源列表请求', () => {
    render(
      <App>
        <MemoryRouter initialEntries={['/targets']}>
          <TargetsPage />
        </MemoryRouter>
      </App>,
    )
    fireEvent.click(screen.getByRole('tab', { name: '知识源' }))
    expect(listFactSources).toHaveBeenCalledWith({ page: 1, page_size: 10 })
    expect(screen.getByRole('heading', { name: '被测系统' })).toBeInTheDocument()
  })
})
