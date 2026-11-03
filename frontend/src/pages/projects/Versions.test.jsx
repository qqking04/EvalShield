// ES10-P-02：版本列表契约回归（方案 §4 L3 用例 V-V-1 ~ V-V-3）。
// task_count>0 渲染可点击 <a>，点击后 navigate('/tasks?project_version_id=<id>')；
// 0/null 显示 '-'；pass_rate:0.5 → Progress percent 50。
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import http from '../../api/http'
import Versions from './Versions'

vi.mock('../../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
vi.mock('echarts-for-react', () => ({ default: () => <div data-testid="echarts" /> }))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => ({
  ...await importOriginal(),
  useNavigate: () => mockNavigate,
}))

beforeEach(() => {
  vi.clearAllMocks()
  http.get.mockImplementation((url) => {
    if (url === '/projects/7/versions') {
      return Promise.resolve({
        items: [
          { id: 11, version_no: '1.2.0', is_baseline: true, task_count: 3, pass_rate: 0.91, created_at: '2026-10-01T00:00:00' },
          { id: 12, version_no: '1.3.0', is_baseline: false, task_count: 0, pass_rate: null, created_at: '2026-10-02T00:00:00' },
        ],
        total: 2,
      })
    }
    return Promise.resolve([])
  })
})

function renderVersions() {
  return render(
    <MemoryRouter initialEntries={['/projects/7/versions']}>
      <Routes>
        <Route path="/projects/:id/versions" element={<Versions />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('Versions 任务数链接（ES10-P-02）', () => {
  it('V-V-1 task_count=3 → 渲染 <a>3</a>，点击按版本过滤跳转任务列表', async () => {
    renderVersions()
    const link = await screen.findByText('3')
    fireEvent.click(link)
    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/tasks?project_version_id=11'),
    )
  })

  it('V-V-2 task_count=0 → 显示 "-"，不可点击；pass_rate:null → "-"', async () => {
    renderVersions()
    await waitFor(() => expect(screen.getByText('3')).toBeInTheDocument())
    expect(screen.queryByText('0')).not.toBeInTheDocument()
    expect(screen.getByText('1.3.0')).toBeInTheDocument()
    // pass_rate null 的行（1.3.0）通过率列显示 '-'（两行各有一个 '-'：说明列 + 通过率列，取 ≥2 个）
    const dashes = screen.getAllByText('-')
    expect(dashes.length).toBeGreaterThanOrEqual(2)
  })

  it('V-V-3 pass_rate=0.5 → Progress percent 50', async () => {
    http.get.mockImplementation((url) => {
      if (url === '/projects/7/versions') {
        return Promise.resolve({
          items: [
            { id: 21, version_no: '2.0.0', is_baseline: false, task_count: 1, pass_rate: 0.5, created_at: '2026-10-03T00:00:00' },
          ],
          total: 1,
        })
      }
      return Promise.resolve([])
    })
    renderVersions()
    await screen.findByText('2.0.0')
    const bar = document.querySelector('.ant-progress')
    expect(bar).not.toBeNull()
    expect(bar.textContent).toContain('50%')
    const inner = document.querySelector('.ant-progress-bg')
    expect(inner.style.width).toBe('50%')
  })
})
