/*
 * ES8-BUG-008：被测系统页测试。
 * 本测试覆盖子组件 eval/TargetRegistryTab.jsx；
 * TargetsPage.jsx 本体的 <Space> 漏导入缺陷已修复，回归见 pages/TargetsPage.test.jsx。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { App } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import http from '../../api/http'
import { useAuth } from '../../auth'
import TargetRegistryTab from './TargetRegistryTab'

// vi.mock 工厂会被提升到 import 之前，工厂体不能引用外层变量（TDZ）；
// 返回内联对象，测试内通过 import 拿到的即同一 mock 实例。
vi.mock('../../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
vi.mock('../../auth', () => ({ useAuth: vi.fn() }))

const TARGET_ROW = {
  code: 'T-001',
  name: '智能客服机器人',
  target_type: 'LLM_API',
  base_url: 'https://api.example.com/v1',
  protocol: 'OPENAI',
  auth_env: 'TARGET_API_KEY',
  status: 'ACTIVE',
}

const renderPage = (ui) => render(<App><MemoryRouter>{ui}</MemoryRouter></App>)

describe('TargetRegistryTab（被测系统注册）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({
      user: { id: 1 }, loading: false, licensed: true,
      hasPerm: (p) => ['model:test', 'model:update', 'model:delete', 'model:create'].includes(p),
    })
    http.get.mockResolvedValue({ items: [TARGET_ROW], total: 1 })
    http.post.mockResolvedValue({ ok: true, latency_ms: 123 })
    http.put.mockResolvedValue({})
    http.delete.mockResolvedValue({})
  })

  it('渲染说明文案与表格，初始 GET /targets 契约正确', async () => {
    const { container } = renderPage(<TargetRegistryTab />)
    expect(await screen.findByText(/被测系统（Target）是评测引擎的应答来源/)).toBeInTheDocument()
    expect(http.get).toHaveBeenCalledWith('/targets', { params: { page: 1, page_size: 10 } })
    await waitFor(() => expect(screen.getByText('T-001')).toBeInTheDocument())
    expect(screen.getByText('智能客服机器人')).toBeInTheDocument()
    expect(screen.getByText('大模型API')).toBeInTheDocument()
    expect(screen.getByText('https://api.example.com/v1')).toBeInTheDocument()
    expect(screen.getByText('启用')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /连通测试/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /新增被测系统/ })).toBeInTheDocument()
    expect(container.querySelector('.ant-table')).toBeInTheDocument()
  })

  it('连通测试：POST /targets/{code}/test 并展示结果 Alert', async () => {
    renderPage(<TargetRegistryTab />)
    await waitFor(() => expect(screen.getByText('T-001')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /连通测试/ }))
    await waitFor(() => expect(http.post).toHaveBeenCalledWith('/targets/T-001/test'))
    expect(await screen.findByText(/连通测试 - 智能客服机器人（T-001）：成功，延迟 123ms/)).toBeInTheDocument()
  })

  it('删除：Popconfirm 确认后 DELETE /targets/{code}', async () => {
    const { container } = renderPage(<TargetRegistryTab />)
    await waitFor(() => expect(screen.getByText('T-001')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /删\s*除/ }))
    await waitFor(() => expect(screen.getByText('确认删除该被测系统？')).toBeInTheDocument())
    const ok = container.ownerDocument.querySelector('.ant-popconfirm .ant-btn-primary')
    expect(ok).not.toBeNull()
    fireEvent.click(ok)
    await waitFor(() => expect(http.delete).toHaveBeenCalledWith('/targets/T-001'))
  })

  it('编辑：PUT /targets/{code} 携带表单值', async () => {
    const { container } = renderPage(<TargetRegistryTab />)
    await waitFor(() => expect(screen.getByText('T-001')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /编\s*辑/ }))
    await waitFor(() => expect(screen.getByText('编辑被测系统（T-001）')).toBeInTheDocument())
    const nameInput = container.ownerDocument.querySelector('.ant-modal input#name')
    expect(nameInput).not.toBeNull()
    fireEvent.change(nameInput, { target: { value: '改名后的靶机' } })
    const modalRoot = container.ownerDocument.querySelector('.ant-modal-root')
    fireEvent.click([...modalRoot.querySelectorAll('.ant-modal-footer button')]
      .find((b) => /保\s*存/.test(b.textContent)))
    await waitFor(() =>
      expect(http.put).toHaveBeenCalledWith('/targets/T-001', expect.objectContaining({ name: '改名后的靶机' })),
    )
  })
})
