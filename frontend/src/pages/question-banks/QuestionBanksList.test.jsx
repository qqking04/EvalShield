// ES8-BUG-008 题库列表契约测试：卡片栅格、api/questionBanks→http 路径快照、空态引导
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { App } from 'antd'
import http from '../../api/http'
import QuestionBanksList from './QuestionBanksList'

vi.mock('../../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  downloadBlob: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
  http.get.mockResolvedValue({ items: [], total: 0 })
  http.post.mockResolvedValue({ ok: true })
  http.delete.mockResolvedValue({ ok: true })
})

const page = (ui) => render(<App><MemoryRouter>{ui}</MemoryRouter></App>)

describe('QuestionBanksList 题库与覆盖度', () => {
  it('标题渲染 + listBanks → GET /question-banks 契约参数', async () => {
    http.get.mockResolvedValue({
      items: [{ id: 2, name: 'TC260 生成式风险题库', question_count: 128, description: '合规基线', created_at: '2026-10-01T10:00:00' }],
      total: 1,
    })
    page(<QuestionBanksList />)
    await waitFor(() => expect(screen.getByText('题库与覆盖度')).toBeInTheDocument())
    expect(screen.getByText('TC260 生成式风险题库')).toBeInTheDocument()
    expect(screen.getByText(/128 题/)).toBeInTheDocument()
    expect(http.get).toHaveBeenCalledWith('/question-banks', {
      params: { keyword: undefined, page: 1, page_size: 12 },
    })
  })

  it('空态：还没有题库 + 创建第一个题库引导', async () => {
    http.get.mockResolvedValue({ items: [], total: 0 })
    page(<QuestionBanksList />)
    await waitFor(() => expect(screen.getByText('还没有题库')).toBeInTheDocument())
    expect(screen.getByText('创建第一个题库')).toBeInTheDocument()
  })

  it('删除题库 → Popconfirm 确认 → DELETE /question-banks/{id}', async () => {
    http.get.mockResolvedValue({
      items: [{ id: 7, name: '待删题库', question_count: 3 }],
      total: 1,
    })
    const { container } = page(<QuestionBanksList />)
    await waitFor(() => expect(screen.getByText('待删题库')).toBeInTheDocument())
    const delBtn = container.querySelector('.anticon-delete').closest('button')
    fireEvent.click(delBtn)
    await waitFor(() =>
      expect(screen.getByText('删除题库将级联删除题目，确认？')).toBeInTheDocument(),
    )
    fireEvent.click(container.ownerDocument.querySelector('.ant-popconfirm .ant-btn-primary'))
    await waitFor(() => expect(http.delete).toHaveBeenCalledWith('/question-banks/7'))
  })

  it('新建题库 Modal 提交 → POST /question-banks 表单契约', async () => {
    const { container } = page(<QuestionBanksList />)
    await waitFor(() => expect(screen.getByText('新建题库')).toBeInTheDocument())
    fireEvent.click(screen.getByText('新建题库'))
    const nameInput = await waitFor(() => screen.getByPlaceholderText('如：TC260 生成式风险题库 v1'))
    fireEvent.change(nameInput, { target: { value: '我的题库' } })
    // 未配 ConfigProvider locale 时 Modal 默认 okText 为英文 OK，用主按钮类名定位
    fireEvent.click(container.ownerDocument.querySelector('.ant-modal-footer .ant-btn-primary'))
    await waitFor(() =>
      expect(http.post).toHaveBeenCalledWith(
        '/question-banks',
        expect.objectContaining({ name: '我的题库' }),
      ),
    )
  })
})
