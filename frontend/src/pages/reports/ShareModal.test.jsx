// ES10-P-05：分享弹窗契约回归（零网络：http 全 mock）
// 覆盖方案 §4 L3 用例 V-S-1 ~ V-S-5（优化10测试方案.md）。
// 断言以方案预期为准；组件实现与方案不符处不改断言（缺陷另行记录）。
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { App } from 'antd'
import http from '../../api/http'
import ShareModal from './ShareModal'

vi.mock('../../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

beforeEach(() => {
  vi.clearAllMocks()
  http.get.mockImplementation((url) => {
    if (url === '/dicts') return Promise.resolve([]) // 字典为空 → ShareModal 兜底静态选项
    if (url.startsWith('/reports/')) return Promise.resolve([]) // 已有分享列表
    return Promise.resolve([])
  })
  http.post.mockResolvedValue({ url: 'https://example.com/s/abc', is_permanent: false })
})

function openModal() {
  render(
    <MemoryRouter>
      <App>
        <ShareModal open onClose={vi.fn()} reportId={42} />
      </App>
    </MemoryRouter>,
  )
}

describe('ShareModal（ES10-P-05 分享链接）', () => {
  // V-S-1 字段名
  it('V-S-1 默认有效期 7 天：POST body 键名为 expires_in_days，无 expiry 键；成功 message 回显天数', async () => {
    openModal()
    fireEvent.click(await screen.findByText('生成新链接'))
    await waitFor(() =>
      expect(http.post).toHaveBeenCalledWith(
        '/reports/42/shares',
        expect.objectContaining({ expires_in_days: 7 }),
      ),
    )
    const body = http.post.mock.calls[0][1]
    expect(body).not.toHaveProperty('expiry')
    await screen.findByText('分享链接已生成，7 天后过期')
  })

  // V-S-2 永久选项 + V-S-3 成功回显（永久有效）
  it('V-S-2/V-S-3 选「永久」→ expires_in_days=0，is_permanent 响应回显永久有效', async () => {
    openModal()
    await screen.findByText('已有分享链接')
    const sel = document.getElementById('expires_in_days').closest('.ant-select')
    fireEvent.mouseDown(sel.querySelector('.ant-select-selector'))
    fireEvent.click(await screen.findByText('永久'))
    http.post.mockResolvedValue({ url: 'https://example.com/s/perma', is_permanent: true })
    fireEvent.click(screen.getByText('生成新链接'))
    await waitFor(() => expect(http.post).toHaveBeenCalled())
    expect(http.post.mock.calls[0][1].expires_in_days).toBe(0)
    await screen.findByText('分享链接已生成（永久有效）')
  })

  // V-S-4 列表列：expires_at（日期或"永久"）与 view/max_views；旧 expiry 列不存在
  it('V-S-4 已有分享列表渲染有效期（永久/日期）与 访问 view/max_views 列，无旧 expiry 列', async () => {
    http.get.mockImplementation((url) => {
      if (url === '/dicts') return Promise.resolve([])
      if (url === '/reports/42/shares') {
        return Promise.resolve([
          { id: 1, share_no: 'SH-1', url: 'https://example.com/s/1', is_permanent: true, expires_at: null, view_count: 3, max_views: 10, is_enabled: true, created_at: '2026-10-01T10:00:00' },
          { id: 2, share_no: 'SH-2', url: 'https://example.com/s/2', is_permanent: false, expires_at: '2026-11-01T00:00:00', view_count: 1, is_enabled: true, created_at: '2026-10-02T10:00:00' },
        ])
      }
      return Promise.resolve([])
    })
    openModal()
    await screen.findByText('SH-1')
    // 有效期列：永久 Tag/文本 + 日期
    expect(screen.getByText('永久')).toBeInTheDocument()
    expect(screen.getByText('至 2026-11-01')).toBeInTheDocument()
    // 访问列：view/max_views
    expect(screen.getByText('3 / 10')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
    // 旧 expiry 列不存在
    const headers = Array.from(document.querySelectorAll('th')).map((th) => th.textContent)
    expect(headers.some((h) => h.toLowerCase().includes('expiry'))).toBe(false)
  })

  // V-S-5 max_views 表单项
  it('V-S-5 「最大访问次数」InputNumber 存在且提交 {max_views:10}', async () => {
    openModal()
    const input = await screen.findByLabelText('最大访问次数')
    fireEvent.change(input, { target: { value: '10' } })
    fireEvent.click(screen.getByText('生成新链接'))
    await waitFor(() => expect(http.post).toHaveBeenCalled())
    expect(http.post.mock.calls[0][1].max_views).toBe(10)
  })
})
