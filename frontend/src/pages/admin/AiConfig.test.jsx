// ES8-BUG-008 AI 配置管理契约测试：列表 GET、设为默认 PUT 双步、测试连接 POST、删除
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { App } from 'antd'
import http from '../../api/http'
import AiConfig from './AiConfig'
import { useAuth } from '../../auth'

vi.mock('../../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
vi.mock('../../auth', () => ({ useAuth: vi.fn() }))

const CONFIGS = {
  items: [
    { code: 'MC-001', name: '本地Qwen', provider: 'LOCAL', usage: 'CHAT', model: 'qwen2.5:7b', base_url: 'http://127.0.0.1:11434/v1', status: 'ACTIVE', is_default: true },
    { code: 'MC-002', name: 'DeepSeek对话', provider: 'DEEPSEEK', usage: 'CHAT', model: 'deepseek-chat', status: 'ACTIVE', is_default: false },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  useAuth.mockReturnValue({
    user: { id: 1 }, loading: false, licensed: true,
    hasPerm: (p) => (p === '*' ? true : ['model:update', 'model:test', 'model:create', 'model:delete'].includes(p)),
  })
  http.get.mockResolvedValue(CONFIGS)
  http.put.mockResolvedValue({ ok: true })
  http.post.mockResolvedValue({ ok: true })
  http.delete.mockResolvedValue({ ok: true })
})

const page = (ui) => render(<App><MemoryRouter>{ui}</MemoryRouter></App>)

describe('AiConfig AI 配置管理', () => {
  it('标题 + 表格渲染，GET /model-configs 契约参数', async () => {
    page(<AiConfig />)
    await waitFor(() => expect(screen.getByText('AI 配置管理')).toBeInTheDocument())
    expect(screen.getByText('MC-001')).toBeInTheDocument()
    // 顶部默认配置 Descriptions 卡片与表格行会双份渲染以下文本
    expect(screen.getAllByText('本地Qwen').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('本地模型').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('qwen2.5:7b').length).toBeGreaterThanOrEqual(1)
    expect(http.get).toHaveBeenCalledWith('/model-configs', { params: { page: 1, page_size: 100 } })
  })

  it('「设为默认」双默认 409 契约：先清旧默认 PUT false，再置新默认 PUT true', async () => {
    // CONFIGS 中 MC-001 为 CHAT 旧默认；对 MC-002 行点「设为默认」
    page(<AiConfig />)
    await waitFor(() => expect(screen.getByText('设为默认')).toBeInTheDocument())
    fireEvent.click(screen.getByText('设为默认'))
    await waitFor(() =>
      expect(http.put).toHaveBeenNthCalledWith(1, '/model-configs/MC-001', { is_default: false }),
    )
    await waitFor(() =>
      expect(http.put).toHaveBeenNthCalledWith(2, '/model-configs/MC-002', { is_default: true }),
    )
  })

  it('「测试连接」→ Modal 确认 → POST /model-configs/{code}/test', async () => {
    http.post.mockResolvedValue({ ok: true, model: 'deepseek-chat', latency_ms: 420 })
    page(<AiConfig />)
    await waitFor(() => expect(screen.getAllByText('测试连接').length).toBeGreaterThanOrEqual(2))
    fireEvent.click(screen.getAllByText('测试连接')[1]) // MC-002 行
    await waitFor(() => expect(screen.getByText('开始测试')).toBeInTheDocument())
    fireEvent.click(screen.getByText('开始测试'))
    await waitFor(() =>
      expect(http.post).toHaveBeenCalledWith('/model-configs/MC-002/test', { api_key: undefined }),
    )
  })

  it('「删除」→ Popconfirm → DELETE /model-configs/{code}', async () => {
    const { container } = page(<AiConfig />)
    await waitFor(() => expect(screen.getByText('MC-002')).toBeInTheDocument())
    const delBtns = screen.getAllByText('删除')
    fireEvent.click(delBtns[1]) // 第二行 MC-002（MC-001 为系统预置亦可见删除）
    await waitFor(() => expect(screen.getByText('确认删除该 AI 接入？')).toBeInTheDocument())
    fireEvent.click(container.ownerDocument.querySelector('.ant-popconfirm .ant-btn-primary'))
    await waitFor(() => expect(http.delete).toHaveBeenCalledWith('/model-configs/MC-002'))
  })
})
