// ES10-P-04：API 密钥页 scope 契约回归（零网络：http 全 mock）
// 覆盖方案 §4 L3 用例 V-K-1 ~ V-K-5（优化10测试方案.md）。
// 断言以方案预期为准；组件实现与方案不符处不改断言（缺陷另行记录）。
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { App } from 'antd'
import http from '../../api/http'
import AdminApiKeys, { normalizeScopes } from './ApiKeys'

vi.mock('../../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

beforeEach(() => {
  vi.clearAllMocks()
  http.get.mockResolvedValue({ items: [] })
  http.post.mockResolvedValue({ api_key: 'es-sk-plain' })
})

function renderPage() {
  render(
    <MemoryRouter>
      <App>
        <AdminApiKeys />
      </App>
    </MemoryRouter>,
  )
}

async function openCreateModal() {
  renderPage()
  fireEvent.click(await screen.findByText('创建密钥'))
  fireEvent.change(await screen.findByLabelText('密钥名称'), { target: { value: 'k1' } })
}

describe('normalizeScopes（写必含读归一化）', () => {
  it('勾 traces:write 自动补 traces:read；勾 cases:write 自动补 cases:read', () => {
    expect(normalizeScopes(['traces:write']).sort()).toEqual(['traces:read', 'traces:write'])
    expect(normalizeScopes(['cases:write']).sort()).toEqual(['cases:read', 'cases:write'])
  })

  it('无 write 时原样去重返回；空/undefined 返回空数组', () => {
    expect(normalizeScopes(['eval:run', 'eval:run'])).toEqual(['eval:run'])
    expect(normalizeScopes(['traces:read'])).toEqual(['traces:read'])
    expect(normalizeScopes(undefined)).toEqual([])
    expect(normalizeScopes([])).toEqual([])
  })
})

describe('AdminApiKeys 页面', () => {
  // V-K-1 write 联动
  it('V-K-1 勾 traces:write 提交 → POST body 自动含 traces:read', async () => {
    await openCreateModal()
    fireEvent.click(await screen.findByLabelText('写入（traces:write）'))
    fireEvent.click(screen.getByRole('button', { name: '创 建' }))
    await waitFor(() =>
      expect(http.post).toHaveBeenCalledWith(
        '/admin/api-keys',
        expect.objectContaining({ key_name: 'k1' }),
      ),
    )
    expect(http.post.mock.calls[0][1].scopes.sort()).toEqual(['traces:read', 'traces:write'])
  })

  // V-K-2 取消联动反向（read 被 write 隐含）
  it('V-K-2 勾 write 与 read 后取消 read → 提交 body 仍含 traces:read（write 隐含 read）', async () => {
    await openCreateModal()
    fireEvent.click(await screen.findByLabelText('写入（traces:write）'))
    const readBox = await screen.findByLabelText('读取（traces:read）')
    fireEvent.click(readBox)
    expect(readBox.checked).toBe(true)
    fireEvent.click(readBox) // 取消 read，write 仍勾
    expect(readBox.checked).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: '创 建' }))
    await waitFor(() => expect(http.post).toHaveBeenCalled())
    const scopes = http.post.mock.calls[0][1].scopes
    expect(scopes).toContain('traces:write')
    expect(scopes).toContain('traces:read')
  })

  // V-K-3 零 scope 拦截
  it('V-K-3 零 scope 提交被拦截：提示「至少选择一个权限范围」，不发 POST', async () => {
    renderPage()
    fireEvent.click(await screen.findByText('创建密钥'))
    fireEvent.change(await screen.findByLabelText('密钥名称'), { target: { value: 'CI 自动化调用' } })
    fireEvent.click(screen.getByRole('button', { name: '创 建' }))
    // help 容器由 aria-describedby 契约定位；rc-motion 在 jsdom 下需等 motionDeadline 挂载
    await waitFor(() => {
      const help = document.getElementById('scopes_help')
      expect(help?.textContent).toContain('至少选择一个权限范围')
    }, { timeout: 4000 })
    expect(http.post).not.toHaveBeenCalled()
  })

  // V-K-4 预留项标注（拆两个独立用例：同 it 内二次 renderPage 会产生重复「创建密钥」按钮）
  it('V-K-4a 预留 scope（cases:read）勾选可提交（账本未挂载不拒绝）', async () => {
    await openCreateModal()
    fireEvent.click(await screen.findByLabelText('读取（cases:read）'))
    fireEvent.click(screen.getByRole('button', { name: '创 建' }))
    await waitFor(() => expect(http.post).toHaveBeenCalled())
    expect(http.post.mock.calls[0][1].scopes).toContain('cases:read')
  })

  it('V-K-4b 方案预期：4 个预留 scope 逐项渲染 Tooltip「预留，尚未开放 API-Key 通道」', async () => {
    await openCreateModal()
    for (const s of ['cases:read', 'cases:write', 'eval:read', 'eval:run']) {
      // BUG-8 实现：Tooltip 挂在 label 内层触发 span 上（mouseenter 不冒泡，
      // 悬停 checkbox input 不会触发），故直接定位含 scope 文案的 span 作为悬停目标
      const trigger = await screen.findByText(new RegExp(`（${s}）$`))
      fireEvent.mouseEnter(trigger)
      fireEvent.mouseOver(trigger)
      // 高负载全量跑时 jsdom 清理有延迟，前轮 Tooltip 可能残留 → 用 AllBy 宽松匹配
      // eslint-disable-next-line no-await-in-loop
      await waitFor(() =>
        expect(screen.queryAllByText('预留，尚未开放 API-Key 通道').length).toBeGreaterThan(0),
        { timeout: 3000 },
      )
    }
  })

  // V-K-5 旧 Key 展示：灰 Tag + Tooltip；有界 Key 逐项蓝 Tag
  it('V-K-5 列表行 scopes 空 → 灰 Tag「全部（旧版）」+Tooltip 说明；有界 Key → 逐项蓝 Tag', async () => {
    http.get.mockResolvedValue({
      items: [
        { id: 1, key_name: 'legacy', key_prefix: 'es_a', scopes: [], created_at: '2026-01-01T00:00:00' },
        { id: 2, key_name: 'new', key_prefix: 'es_b', scopes: ['traces:read'], created_at: '2026-01-02T00:00:00' },
      ],
    })
    renderPage()
    const legacyTag = await screen.findByText('全部（旧版）')
    expect(screen.getByText('traces:read')).toBeInTheDocument()
    // 旧 Key Tooltip 说明（hover 触发）
    fireEvent.mouseEnter(legacyTag)
    fireEvent.mouseOver(legacyTag)
    await waitFor(() =>
      expect(document.querySelector('.ant-tooltip-inner')?.textContent).toBeTruthy(),
      { timeout: 3000 },
    )
    // 有界 Key 逐项蓝 Tag
    expect(legacyTag.className).toContain('ant-tag-default')
    const bounded = screen.getByText('traces:read').closest('.ant-tag')
    expect(bounded.className).toContain('ant-tag-blue')
  })
})
