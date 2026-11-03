// ES11-BUG-006/007 回归锁定测试（推荐 R-6）：
// ① verdictOf 四态派生纯函数口径；
// ② ReportDelivery 页真实挂载渲染（锁定 re-export 未入作用域一类构建期不报错的缺陷）；
// ③ 就绪区/工作台「查看运行」深链落点为已注册的 /eval（BUG-007）。
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { App } from 'antd'
import { verdictOf } from './deliveryVerdict'
import { DeliveryReadinessSection } from './deliveryVerdict'
import ReportDelivery from './ReportDelivery'
import * as es11 from '../../api/es11'

vi.mock('../../api/es11', () => ({
  getDeliveryReadiness: vi.fn(),
  freezeConclusion: vi.fn(),
  createDeliveryPackage: vi.fn(),
  // 优化12 BUG-002：ReportDelivery 挂载后会拉 coverage API（M4/M5 新增调用），
  // mock 工厂缺键会导致该属性为 undefined 而抛 TypeError。默认解析为旧口径 null。
  getRunDimensionCoverage: vi.fn().mockResolvedValue({ coverage: null, standards_ver: null }),
}))
vi.mock('../../auth', () => ({
  useAuth: () => ({ hasPerm: () => true }),
}))
vi.mock('../../utils', () => ({ fmtTime: (v) => String(v ?? '-') }))

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="loc">{loc.pathname}</div>
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

describe('verdictOf 四态派生（纯函数）', () => {
  it('null → null；run_id 缺失 → 证据不足', () => {
    expect(verdictOf(null)).toBeNull()
    expect(verdictOf({ run_id: null }).label).toBe('证据不足')
  })
  it('存在 BLOCK 或未 deliverable → 不可交付', () => {
    expect(verdictOf({ run_id: 1, deliverable: false, checklist: [] }).label).toBe('不可交付')
    expect(
      verdictOf({ run_id: 1, deliverable: true, checklist: [{ status: 'BLOCK' }] }).label
    ).toBe('不可交付')
  })
  it('G4 全过 + 已冻结 → 可交付；未冻结 → 有条件通过（区分 concluded）', () => {
    const pass = { run_id: 1, deliverable: true, checklist: [{ status: 'PASS' }] }
    expect(verdictOf({ ...pass, freeze: { frozen_at: 'x' } }).label).toBe('可交付')
    const cond = verdictOf({ ...pass, concluded: true })
    expect(cond.label).toBe('有条件通过')
    expect(cond.desc).toContain('冻结')
    expect(verdictOf({ ...pass, concluded: false }).desc).toContain('运行结论未达成')
  })
})

describe('ReportDelivery 页挂载渲染（BUG-006 回归锁定）', () => {
  const rd = (patch) => ({
    run_id: 501, run_no: 'R-501', deliverable: true, concluded: true,
    freeze: { frozen_at: '2026-10-29T00:00:00', frozen_by: 1, frozen_by_name: 'admin', note: '' },
    checklist: [{ code: 'G4-DEFECT', status: 'PASS' }],
    ...patch,
  })

  it('可交付态：四态文案与 G4 清单渲染，不抛 ReferenceError', async () => {
    es11.getDeliveryReadiness.mockResolvedValue(rd())
    render(
      <App>
        <MemoryRouter initialEntries={['/reports/6879/delivery']}>
          <Routes>
            <Route path="/reports/:id/delivery" element={<ReportDelivery />} />
          </Routes>
          <LocationProbe />
        </MemoryRouter>
      </App>
    )
    await waitFor(() => expect(screen.getByText('可交付')).toBeInTheDocument())
    expect(screen.getByText('G4 交付就绪清单')).toBeInTheDocument()
    expect(screen.queryByText('verdictOf is not defined')).not.toBeInTheDocument()
  })

  it('证据不足态：渲染警示与「查看运行」，点击落 /eval（BUG-007 工作台侧）', async () => {
    es11.getDeliveryReadiness.mockResolvedValue(rd({ run_id: null, deliverable: false, freeze: null, checklist: [] }))
    render(
      <App>
        <MemoryRouter initialEntries={['/reports/6879/delivery']}>
          <Routes>
            <Route path="/reports/:id/delivery" element={<ReportDelivery />} />
            <Route path="/eval" element={<div>eval center</div>} />
          </Routes>
          <LocationProbe />
        </MemoryRouter>
      </App>
    )
    await waitFor(() => expect(screen.getByText('证据不足')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: '查看运行' }))
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/eval'))
  })
})

describe('DeliveryReadinessSection 就绪区（嵌入 ReportDetail 顶部）', () => {
  it('未关联运行：警示 + 「查看运行」点击落 /eval（BUG-007 就绪区侧）', async () => {
    es11.getDeliveryReadiness.mockResolvedValue({ run_id: null, deliverable: false, checklist: [] })
    render(
      <App>
        <MemoryRouter initialEntries={['/reports']}>
          <DeliveryReadinessSection reportId={6879} />
          <Routes>
            <Route path="/eval" element={<div>eval center</div>} />
          </Routes>
          <LocationProbe />
        </MemoryRouter>
      </App>
    )
    await waitFor(() => expect(screen.getByText('证据不足')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: '查看运行' }))
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/eval'))
  })

  it('加载失败：降级提示 + 工作台入口可达', async () => {
    es11.getDeliveryReadiness.mockRejectedValue(new Error('boom'))
    render(
      <App>
        <MemoryRouter initialEntries={['/reports']}>
          <DeliveryReadinessSection reportId={6879} />
          <Routes>
            <Route path="/reports/:id/delivery" element={<div>delivery</div>} />
          </Routes>
          <LocationProbe />
        </MemoryRouter>
      </App>
    )
    await waitFor(() => expect(screen.getByText('交付就绪数据暂不可用')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: '打开交付工作台' }))
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/reports/6879/delivery'))
  })
})
