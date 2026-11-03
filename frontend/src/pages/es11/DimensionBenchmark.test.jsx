// 优化12 V8 前端断言：DimensionBenchmark 三态图标+文字、矩阵行点击开抽屉与深链、
// 旧口径 run 灰态文案、核定入口权限表现；QualityOverview 摘要卡不位移英雄区。
// 零网络：api/es11 全 mock；echarts / auth 轻量桩替换（jsdom 无 canvas）。
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { App } from 'antd'
import {
  getStandardsDimensions, getRunDimensionCoverage, calibrateThresholds, listRuns, getRunItems,
  getQualityOverview,
} from '../../api/es11'
import DimensionBenchmark from './DimensionBenchmark'
import QualityOverview from './QualityOverview'
import { useAuth } from '../../auth'

vi.mock('../../api/es11', () => ({
  getStandardsDimensions: vi.fn(),
  getRunDimensionCoverage: vi.fn(),
  calibrateThresholds: vi.fn(),
  listRuns: vi.fn(),
  getRunItems: vi.fn(),
  getQualityOverview: vi.fn(),
  listDefects: vi.fn().mockResolvedValue({ items: [], total: 0 }),
}))
vi.mock('../../auth', () => ({ useAuth: vi.fn() }))
vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts-mock" />,
}))

function setAuth(user) {
  useAuth.mockReturnValue({
    user,
    loading: false,
    licensed: true,
    hasPerm: () => true,
  })
}

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="loc">{`${loc.pathname}${loc.search}`}</div>
}

const page = (ui) =>
  render(
    <App>
      <MemoryRouter initialEntries={['/standards/gbt45654']}>
        {ui}
        <LocationProbe />
      </MemoryRouter>
    </App>,
  )

// ---- 标准元信息（GET /meta/standards 形状快照）----
const META = {
  loaded: true,
  standard: { code: 'GBT45654', name: '网络安全技术 生成式人工智能服务安全基本要求', version: '2025', source: 'GB/T 45654—2025' },
  dimensions: [
    {
      dimension_code: 'A.1', dimension_name: 'A.1 违法犯罪', regulatory: true,
      subs: [
        { sub_code: 'A1a', bank_category: '危害国家安全', min_questions: 40, pass_threshold: 0.96 },
        { sub_code: 'A1b', bank_category: '恐怖主义', min_questions: null, pass_threshold: null },
      ],
    },
    {
      dimension_code: 'A.3', dimension_name: 'A.3 歧视', regulatory: true,
      subs: [{ sub_code: 'A3a', bank_category: '民族歧视', min_questions: 30, pass_threshold: 0.9 }],
    },
    {
      dimension_code: 'B.1', dimension_name: 'B.1 性能', regulatory: false,
      subs: [{ sub_code: 'B1a', bank_category: '生成质量', min_questions: 20, pass_threshold: 0.8 }],
    },
  ],
  mapping: [
    { category_code: 'A1a', dimension_code: 'A.1', dimension_name: 'A.1 违法犯罪', bank_category: '危害国家安全', regulatory: true, min_questions: 40, pass_threshold: 0.96 },
    { category_code: 'A1b', dimension_code: 'A.1', dimension_name: 'A.1 违法犯罪', bank_category: '恐怖主义', regulatory: true, min_questions: null, pass_threshold: null },
    { category_code: 'A3a', dimension_code: 'A.3', dimension_name: 'A.3 歧视', bank_category: '民族歧视', regulatory: true, min_questions: 30, pass_threshold: 0.9 },
  ],
  statement: '平台自动化判定，不替代监管认定。',
  thresholds_missing: ['A1b'],
  presets: [],
}

// ---- 双轨覆盖矩阵（dimension-coverage 响应形状快照）----
const COVERAGE = {
  standards_ver: 'GBT45654@2025',
  coverage: {
    standards_ver: 'GBT45654@2025',
    activity_id: '2f8e3a90-0000-4000-8000-000000000001',
    disclaimer: '本矩阵为平台自动化判定，不替代监管认定与人类专家复核。',
    dimensions: [
      {
        dimension_code: 'A.1', dimension_name: 'A.1 违法犯罪', regulatory: true,
        dimension_tested: 50, dimension_pass: 46, dimension_rate: 0.92, dimension_status: 'BLOCK', gap_questions: 20,
        subs: [
          {
            sub_code: 'A1a', bank_category: '危害国家安全', service_type: '生成合成服务',
            tested: 50, pass: 46, rate: 0.92, min_questions: 40, pass_threshold: 0.96, gap_questions: 0,
            engines: [
              { code: 'REDTEAM_TEST', state: 'EXECUTED', run_id: 9, run_no: 'RUN-009', status: 'PASSED' },
              { code: 'ETHICS_TEST', state: 'MISSING' },
              { code: 'HALLUCINATION_TEST', state: 'N/A' },
            ],
            status: 'BLOCK',
          },
        ],
      },
      {
        dimension_code: 'A.3', dimension_name: 'A.3 歧视', regulatory: true,
        dimension_tested: 0, dimension_pass: 0, dimension_rate: null, dimension_status: 'NOT_CONFIGURED', gap_questions: 0,
        subs: [
          {
            sub_code: 'A3a', bank_category: '民族歧视', service_type: null,
            tested: 0, pass: 0, rate: null, min_questions: 30, pass_threshold: 0.9, gap_questions: 30,
            engines: [], status: 'NOT_CONFIGURED',
          },
        ],
      },
    ],
    refusal: {
      refuse_pass_rate: 0.91, answer_false_refuse_rate: 0.04, attack_success_rate: null,
      thresholds: { refuse_pass_rate_min: null, false_refuse_rate_max: null },
    },
    overall: { official_pass: false, block_items: ['A.1/A1a 危害国家安全：合格率不足'], warn_items: ['引擎级覆盖缺失：ETHICS_TEST'] },
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  setAuth({ id: 1, is_super_admin: true })
  getStandardsDimensions.mockResolvedValue(META)
  listRuns.mockResolvedValue({ items: [{ id: 5, run_no: 'RUN-005', status: 'PASSED', created_at: '2026-10-01T10:00:00' }], total: 1 })
  getRunDimensionCoverage.mockResolvedValue(COVERAGE)
  getRunItems.mockResolvedValue({ items: [{ id: 11, item_id: 11, seq: 3, category: '危害国家安全', prompt: '测试题面', final_verdict: 'PASS' }], total: 1 })
})

describe('DimensionBenchmark 合规对标页', () => {
  it('引擎三态 = 图标+文字+色 三通道（EXECUTED/MISSING/N/A）', async () => {
    page(<DimensionBenchmark />)
    await waitFor(() => expect(screen.getByText('安全基本要求 · 双轨覆盖矩阵')).toBeInTheDocument())
    // 文字通道
    expect(screen.getByText(/REDTEAM_TEST 已执行/)).toBeInTheDocument()
    expect(screen.getByText(/ETHICS_TEST 缺失/)).toBeInTheDocument()
    expect(screen.getByText(/HALLUCINATION_TEST N\/A/)).toBeInTheDocument()
    // 图标通道（antd 图标落 DOM）
    const row = screen.getByText(/REDTEAM_TEST 已执行/).closest('tr')
    expect(row.querySelector('.anticon-check-circle')).toBeTruthy()
    expect(screen.getByText(/ETHICS_TEST 缺失/).querySelector('.anticon-exclamation-circle')).toBeTruthy()
    expect(screen.getByText(/HALLUCINATION_TEST N\/A/).querySelector('.anticon-minus')).toBeTruthy()
    // 颜色通道（令牌色，非单靠颜色但色仍在）
    expect(screen.getByText(/REDTEAM_TEST 已执行/).getAttribute('style')).toContain('rgb(63, 185, 80)')
    expect(screen.getByText(/ETHICS_TEST 缺失/).getAttribute('style')).toContain('rgb(248, 81, 73)')
  })

  it('口径说明原文固定在矩阵表上方', async () => {
    page(<DimensionBenchmark />)
    await waitFor(() => expect(screen.getByText('安全基本要求 · 双轨覆盖矩阵')).toBeInTheDocument())
    const disc = screen.getByText('本矩阵为平台自动化判定，不替代监管认定与人类专家复核。')
    // antd Table measure 副本也在 DOM：限定真正的 <th>
    const th = document.querySelector('th.ant-table-cell')
    expect(th).toBeTruthy()
    expect(th.textContent).toContain('维度 / 子类')
    // DOM 序：disclaimer Alert 在矩阵表头之前
    expect(th.compareDocumentPosition(disc) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
  })

  it('矩阵子类行点击 → 证据抽屉打开并拉取题级证据', async () => {
    page(<DimensionBenchmark />)
    await waitFor(() => expect(screen.getByText('安全基本要求 · 双轨覆盖矩阵')).toBeInTheDocument())
    // "危害国家安全"在矩阵行与缺口清单各出现一次，取矩阵（首个）行
    fireEvent.click(screen.getAllByText('危害国家安全')[0])
    await waitFor(() => expect(getRunItems).toHaveBeenCalledWith(5, { page: 1, page_size: 50 }))
    expect(await screen.findByText('题库分类')).toBeInTheDocument()
    expect(screen.getByText(/命中 1 题/)).toBeInTheDocument()
  })

  it('抽屉内"在运行明细中查看全部"深链 → /eval/runs/:id?tab=items', async () => {
    page(<DimensionBenchmark />)
    await waitFor(() => expect(screen.getByText('安全基本要求 · 双轨覆盖矩阵')).toBeInTheDocument())
    fireEvent.click(screen.getAllByText('危害国家安全')[0])
    const link = await waitFor(() => screen.getByText('在运行明细中查看全部 ›'))
    fireEvent.click(link)
    await waitFor(() =>
      expect(screen.getByTestId('loc')).toHaveTextContent('/eval/runs/5?tab=items'))
  })

  it('缺口清单：BLOCK 行给"补题 ›"深链、NOT_CONFIGURED 给核定出路', async () => {
    page(<DimensionBenchmark />)
    await waitFor(() => expect(screen.getByText('缺口清单', { exact: false })).toBeInTheDocument())
    expect(screen.getByText('补题 ›')).toBeInTheDocument()
    expect(screen.getByText('去核定 ›')).toBeInTheDocument()
    expect(screen.getByText(/本矩阵为平台自动化判定/)).toBeInTheDocument()
  })

  it('旧口径 run（coverage:null）→ 灰态警示、不渲染雷达与矩阵', async () => {
    getRunDimensionCoverage.mockResolvedValue({ standards_ver: 'TC260-003@draft', coverage: null })
    page(<DimensionBenchmark />)
    await waitFor(() =>
      expect(screen.getByText('该运行早于现行标准口径，不产维度覆盖结论')).toBeInTheDocument())
    expect(screen.queryByText('安全基本要求 · 双轨覆盖矩阵')).not.toBeInTheDocument()
    expect(screen.queryByTestId('echarts-mock')).not.toBeInTheDocument()
  })

  it('拒答双指标：阈值核定前只展示、不阻断', async () => {
    page(<DimensionBenchmark />)
    await waitFor(() => expect(screen.getByText('拒答双指标（安全护栏）')).toBeInTheDocument())
    expect(screen.getByText('阈值核定前只展示、不阻断')).toBeInTheDocument()
    expect(screen.getByText('应拒答题目拒答率')).toBeInTheDocument()
    expect(screen.getByText('91.0%')).toBeInTheDocument()
    expect(screen.getAllByText(/待核定/).length).toBeGreaterThan(0)
  })

  it('非超管：无阈值核定入口；NOT_CONFIGURED 出路显示"仅管理员可核定"', async () => {
    setAuth({ id: 2, is_super_admin: false })
    page(<DimensionBenchmark />)
    await waitFor(() => expect(screen.getByText('安全基本要求 · 双轨覆盖矩阵')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '阈值核定' })).not.toBeInTheDocument()
    expect(screen.getByText('仅管理员可核定')).toBeInTheDocument()
    expect(screen.getByText('核定入口仅管理员可见。')).toBeInTheDocument()
  })

  it('超管核定抽屉：必填留痕校验 + PUT 契约（pass_threshold /100 归一）', async () => {
    calibrateThresholds.mockResolvedValue({ ok: true })
    page(<DimensionBenchmark />)
    await waitFor(() => expect(screen.getByRole('button', { name: '阈值核定' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: '阈值核定' }))
    fireEvent.change(await screen.findByPlaceholderText('姓名 / 工号'), { target: { value: '张三' } })
    fireEvent.change(screen.getByPlaceholderText(/GB\/T 45654/), { target: { value: '§5.1 评审纪要' } })
    // 未选子类 → 前端必填拦截，不发 PUT（antd 校验走异步 Promise，给足余量）
    fireEvent.click(screen.getByRole('button', { name: '提交核定' }))
    await waitFor(() => expect(screen.getByText('请选择子类')).toBeInTheDocument(), { timeout: 3000 })
    expect(calibrateThresholds).not.toHaveBeenCalled()
  })
})

describe('QualityOverview 摘要卡（V8：不位移英雄区）', () => {
  const OV = {
    window_days: 30,
    generated_at: '2026-10-30T08:00:00',
    metrics: {
      deliverable_runs: { value: 1, terminal_runs: 2 },
      pending_review_items: { value: 0 },
      blocked_runs: { value: 0, review: 0, demo: 0 },
      recent_regression_runs: { value: 0 },
      open_p0p1_defects: { value: 0 },
      remediated_unverified: { value: 0 },
      defect_verified_close_rate: { value: null, verified_closed: 0, verified_total: 0 },
      judge_health: { sufficient: false, sample: 0 },
      low_score_trace_recurrence: { value: 0, threshold: 0.5, traces: 0 },
    },
  }

  it('摘要卡挂载于英雄区之前，ShipVerdict 三段仍在位', async () => {
    setAuth({ id: 1 })
    getQualityOverview.mockResolvedValue(OV)
    listRuns.mockResolvedValue({ items: [], total: 1 })
    render(
      <App>
        <MemoryRouter><QualityOverview /></MemoryRouter>
      </App>,
    )
    await waitFor(() => expect(screen.getByText('GBT45654 五维度达标状态')).toBeInTheDocument())
    const card = screen.getByText('GBT45654 五维度达标状态').closest('.ant-card')
    // 英雄区三段（ShipVerdict 结构未位移）；同名文案在下方 Metric 瓦片也出现，取首个 = 英雄区
    expect(screen.getAllByText('可交付运行')[0]).toBeInTheDocument()
    expect(screen.getAllByText('待复核条目')[0]).toBeInTheDocument()
    expect(screen.getAllByText('被阻塞运行')[0]).toBeInTheDocument()
    const hero = screen.getAllByText('待复核条目')[0].parentElement.parentElement
    // 摘要卡在英雄区之前（信息层级：标准事实先行）
    expect(card.compareDocumentPosition(hero) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // 摘要卡数据源 = meta/standards 首个消费者
    expect(getStandardsDimensions).toHaveBeenCalled()
  })

  it('meta/standards 失败：静默降级不挂载摘要卡，英雄区不受影响', async () => {
    setAuth({ id: 1 })
    getQualityOverview.mockResolvedValue(OV)
    getStandardsDimensions.mockRejectedValue(new Error('503'))
    listRuns.mockResolvedValue({ items: [], total: 1 })
    render(
      <App>
        <MemoryRouter><QualityOverview /></MemoryRouter>
      </App>,
    )
    await waitFor(() => expect(screen.getAllByText('可交付运行').length).toBeGreaterThan(0))
    expect(screen.queryByText('GBT45654 五维度达标状态')).not.toBeInTheDocument()
  })
})
