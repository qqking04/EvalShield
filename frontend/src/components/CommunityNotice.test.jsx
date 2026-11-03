// OBS-002 回归：EDITION=saas + 有效 License 环境下，社区版限额横幅不得残留。
// vitest 下 __EDITION__ 走 vite define 默认值 'community'（IS_COMMUNITY_BUILD=true），
// 正好复现「社区构建包部署到 saas 环境」的场景：
// ① 服务端未就绪（loaded=false）→ 不渲染；
// ② 服务端返回 edition=saas → 以实时值为准，隐藏横幅；
// ③ 服务端返回 edition=community 且非商业 → 正常渲染横幅。
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import CommunityNotice from './CommunityNotice'
import { EditionProvider } from '../edition/EditionContext'

function mockEditionFetch(payload) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ code: 0, message: 'ok', data: payload }),
    })
  )
}

const saasPayload = () => ({
  edition: 'saas',
  commercial: true,
  enabled_engines: ['api', 'ui'],
  limits: { projects_total: 3 },
  license: { valid: true, reason: '', expires_at: '2099-01-01', phase: 'active' },
  platform: { available: true, tenants_api: true },
})

const communityPayload = () => ({
  edition: 'community',
  commercial: false,
  enabled_engines: ['api'],
  limits: { projects_total: 3 },
  license: null,
  platform: null,
})

function renderNotice() {
  return render(
    <MemoryRouter>
      <EditionProvider>
        <CommunityNotice />
      </EditionProvider>
    </MemoryRouter>
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

describe('CommunityNotice（OBS-002）', () => {
  it('服务端返回 edition=saas 时不渲染「当前为社区版」横幅（即使构建期 __EDITION__=community）', async () => {
    mockEditionFetch(saasPayload())
    renderNotice()
    // 等 edition 探测完成（横幅首帧本就不渲染，这里防的是就绪后误显示）
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/edition', expect.anything()))
    await waitFor(() => expect(screen.queryByText(/当前为社区版/)).not.toBeInTheDocument())
    expect(screen.queryByText(/当前为社区版/)).not.toBeInTheDocument()
  })

  it('服务端返回 edition=community（非商业）时正常渲染限额横幅', async () => {
    mockEditionFetch(communityPayload())
    renderNotice()
    await waitFor(() => expect(screen.getByText(/当前为社区版/)).toBeInTheDocument())
    expect(screen.getByText(/项目 3 个/)).toBeInTheDocument()
  })
})
