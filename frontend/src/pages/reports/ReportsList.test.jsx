// ES8-BUG-008 报告列表契约测试：列表 GET/筛选参数、查看/删除端点、批量删除入口
// ReportDetail / ShareModal 为重型抽屉组件（内含懒加载与安全报告视图），此处桩替换，
// 聚焦列表页自身的 API 契约。
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { App } from 'antd'
import http, { downloadBlob } from '../../api/http'
import ReportsList from './ReportsList'

vi.mock('../../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  downloadBlob: vi.fn(),
}))
vi.mock('./ReportDetail', () => ({ default: () => <div data-testid="report-detail-mock" /> }))
vi.mock('./ShareModal', () => ({ default: () => null }))

const REPORT_ROW = {
  id: 3, report_no: 'R-20261001-003', title: '核心回归报告', project_id: 1,
  task_no: 'T-20261001-005', report_type: 'EVAL', format: 'json',
  status: 'GENERATED', risk_level: 'LOW', summary: { pass_rate: 0.92 },
  generated_at: '2026-10-01T10:00:00',
}

const routes = new Map()
function matchRoute(url) {
  let best = null
  for (const k of routes.keys()) {
    if (url === k || url.startsWith(k)) {
      if (best === null || k.length > best.length) best = k
    }
  }
  return best
}

beforeEach(() => {
  vi.clearAllMocks()
  routes.clear()
  routes.set('/reports', { items: [REPORT_ROW], total: 1 })
  routes.set('/projects', { items: [{ id: 1, code: 'P-1', name: '示例项目' }] })
  routes.set('/dicts', [])
  http.get.mockImplementation((url) => {
    const k = matchRoute(url)
    if (k === null) return Promise.resolve({})
    const v = routes.get(k)
    return Promise.resolve(typeof v === 'function' ? v(url) : v)
  })
  http.post.mockResolvedValue({ ok: true })
  http.delete.mockResolvedValue({ ok: true })
})

const page = (ui) => render(<App><MemoryRouter>{ui}</MemoryRouter></App>)

describe('ReportsList 报告列表', () => {
  it('表格渲染报告编号/标题，初始 GET 契约（列表/项目下拉/source 字典）', async () => {
    page(<ReportsList />)
    await waitFor(() => expect(screen.getByText('R-20261001-003')).toBeInTheDocument())
    // ellipsis 列的 measure-cell 会双份渲染表头与标题文本
    expect(screen.getAllByText('核心回归报告').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('报告编号').length).toBeGreaterThanOrEqual(1)
    expect(http.get).toHaveBeenCalledWith('/reports', { params: { page: 1, page_size: 10 } })
    expect(http.get).toHaveBeenCalledWith('/projects', { params: { page_size: 500 } })
    expect(http.get).toHaveBeenCalledWith('/dicts', { params: { dict_code: 'source' } })
  })

  it('「查看」→ GET /reports/{id} 并打开详情抽屉', async () => {
    routes.set('/reports/3', { id: 3, report_no: 'R-20261001-003', status: 'GENERATED' })
    const { container } = page(<ReportsList />)
    await waitFor(() => expect(screen.getByText('查看')).toBeInTheDocument())
    fireEvent.click(screen.getByText('查看'))
    await waitFor(() => expect(http.get).toHaveBeenCalledWith('/reports/3'))
    await waitFor(() =>
      // Drawer portal 挂到 document.body，不在 render container 内
      expect(container.ownerDocument.querySelector('.ant-drawer-open')).not.toBeNull(),
    )
    expect(screen.getByTestId('report-detail-mock')).toBeInTheDocument()
  })

  it('「删除」→ Popconfirm 确认 → DELETE /reports/{id}', async () => {
    const { container } = page(<ReportsList />)
    await waitFor(() => expect(screen.getByText('删除')).toBeInTheDocument())
    fireEvent.click(screen.getByText('删除'))
    await waitFor(() => expect(screen.getByText('确认删除该报告？')).toBeInTheDocument())
    fireEvent.click(container.ownerDocument.querySelector('.ant-popconfirm .ant-btn-primary'))
    await waitFor(() => expect(http.delete).toHaveBeenCalledWith('/reports/3'))
  })

  it('未勾选行时「批量删除」禁用，POST /reports/batch-delete 由勾选后触发', async () => {
    page(<ReportsList />)
    await waitFor(() => expect(screen.getByText('R-20261001-003')).toBeInTheDocument())
    const batchBtn = screen.getByText(/批量删除/).closest('button')
    expect(batchBtn.disabled).toBe(true)
    // 勾选首行复选框后按钮解禁
    const rowCheckbox = document.querySelector('.ant-table-tbody .ant-checkbox-input')
    expect(rowCheckbox).not.toBeNull()
    fireEvent.click(rowCheckbox)
    await waitFor(() => expect(screen.getByText(/批量删除/).closest('button').disabled).toBe(false))
  })

  it('状态筛选：选择「已完成」→ 点筛选 → GET /reports 带 status=DONE；重置后不带 status', async () => {
    page(<ReportsList />)
    await waitFor(() => expect(screen.getByText('R-20261001-003')).toBeInTheDocument())
    // 打开状态下拉（当前值文本即「全部状态」选项）
    fireEvent.mouseDown(screen.getByText('全部状态'))
    await waitFor(() => expect(screen.getByText('已完成')).toBeInTheDocument())
    fireEvent.click(screen.getByText('已完成'))
    fireEvent.click(screen.getByText('筛选'))
    await waitFor(() =>
      expect(http.get).toHaveBeenCalledWith('/reports', {
        params: { page: 1, page_size: 10, status: 'DONE' },
      }),
    )
    // 重置 → 清空状态并重新拉取（最后一次 /reports 调用不带 status 键）
    fireEvent.click(screen.getByText('重置'))
    await waitFor(() => {
      const last = http.get.mock.calls.filter(([u]) => u === '/reports').slice(-1)[0]
      expect(last[1].params).not.toHaveProperty('status')
    })
  })

  it('PDF 导出经「更多」菜单 + Modal 确认 → downloadBlob(/reports/{id}/export)', async () => {
    downloadBlob.mockResolvedValue(undefined)
    page(<ReportsList />)
    await waitFor(() => expect(screen.getByText('更多')).toBeInTheDocument())
    fireEvent.click(screen.getByText('更多'))
    await waitFor(() => expect(screen.getByText('导出 PDF')).toBeInTheDocument())
    fireEvent.click(screen.getByText('导出 PDF'))
    // Modal.confirm 同时渲染 .ant-modal-title 与 .ant-modal-confirm-title 两份标题
    await waitFor(() => expect(screen.getAllByText(/导出报告（PDF）/).length).toBeGreaterThanOrEqual(1))
    fireEvent.click(
      screen.getAllByText('导出报告（PDF）')[0].closest('.ant-modal-confirm, .ant-modal')
        .querySelector('.ant-btn-primary'),
    )
    await waitFor(() =>
      expect(downloadBlob).toHaveBeenCalledWith(
        '/reports/3/export',
        { format: 'pdf' },
        'R-20261001-003.pdf',
      ),
    )
  })
})
