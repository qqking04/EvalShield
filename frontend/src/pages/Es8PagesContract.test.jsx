// ES8-BUG-008 前端增量契约回归（方案 §8.1 点名的 7 页 + Register 三形态 + M6 键盘流）
// 零网络：http 全 mock；echarts / react-countup / auth / EditionContext 以轻量桩替换。
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { App } from 'antd'
import http from '../api/http'
import Notify from './settings/Notify'
import MonitorList from './monitor/MonitorList'
import ReviewQueuePage from './review/Queue'
import TraceList from './traces/TraceList'
import DefectSync from './settings/DefectSync'
import Retention from './settings/Retention'
import PlatformOverview from './CommercialPlaceholder'
import Register from './auth/Register'
import { useAuth } from '../auth'
import { useEdition } from '../edition/EditionContext'

vi.mock('../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
vi.mock('../auth', () => ({ useAuth: vi.fn() }))
vi.mock('../edition/EditionContext', () => ({ useEdition: vi.fn() }))
// jsdom 无 canvas，echarts 真实渲染会抛错——统一桩替换
vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts-mock" />,
}))
vi.mock('react-countup', () => ({
  default: ({ end }) => <span>{end ?? 0}</span>,
}))

// 按 URL 前缀分发的 GET 路由表（最长键优先，兼容 /traces 与 /traces/policy 同前缀）
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

function setAuth({ perms = [], user = { id: 1 } } = {}) {
  useAuth.mockReturnValue({
    user,
    loading: false,
    licensed: true,
    hasPerm: (p) => (p === '*' ? true : perms.includes(p)),
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  routes.clear()
  localStorage.removeItem('es_token')
  setAuth()
  useEdition.mockReturnValue({ edition: 'enterprise' })
  http.get.mockImplementation((url) => {
    const k = matchRoute(url)
    if (k === null) return Promise.resolve({})
    const v = routes.get(k)
    return Promise.resolve(typeof v === 'function' ? v(url) : v)
  })
  http.post.mockResolvedValue({ ok: true })
  http.put.mockResolvedValue({ ok: true })
  http.delete.mockResolvedValue({ ok: true })
})

const page = (ui) =>
  render(
    <App>
      <MemoryRouter>{ui}</MemoryRouter>
    </App>,
  )

// ============================================================ M3 通知中心 ====
describe('Notify 通知中心（M3）', () => {
  it('渠道列表渲染名称/类型/探测状态，发送测试打到契约端点', async () => {
    routes.set('/notify/channels', {
      items: [{ id: 7, name: '安全群', kind: 'dingtalk', enabled: true, last_probe_ok: true, config_keys: ['url'] }],
      total: 1,
    })
    page(<Notify />)
    await waitFor(() => expect(screen.getByText('通知中心')).toBeInTheDocument())
    expect(screen.getByText('安全群')).toBeInTheDocument()
    expect(screen.getByText('钉钉机器人')).toBeInTheDocument()
    fireEvent.click(screen.getByText('发送测试'))
    await waitFor(() => expect(http.post).toHaveBeenCalledWith('/notify/channels/7/test'))
  })

  it('无渠道时展示站内信兜底空态', async () => {
    routes.set('/notify/channels', { items: [], total: 0 })
    page(<Notify />)
    await waitFor(() =>
      expect(screen.getByText('暂无渠道，事件仅站内信兜底')).toBeInTheDocument(),
    )
  })
})

// ==================================================== M4 定时监控列表页 ====
describe('MonitorList 定时监控（M4）', () => {
  it('卡片渲染名称/cron/FIRING 红点，立即执行调用 run-now 端点', async () => {
    routes.set('/monitors', {
      items: [
        {
          id: 1, name: '核心回归看门狗', suite_id: 9, cron: '0 9 * * *', enabled: true,
          next_fire_at: null, firing_count: 2, last_checked_at: null,
          alert_conditions: [{ metric: 'pass_rate', op: 'lt', threshold: 0.8 }],
        },
      ],
      total: 1,
    })
    routes.set('/projects', { items: [], total: 0 })
    page(<MonitorList />)
    await waitFor(() => expect(screen.getByText('定时监控')).toBeInTheDocument())
    expect(screen.getByText('核心回归看门狗')).toBeInTheDocument()
    expect(screen.getByText('0 9 * * *')).toBeInTheDocument()
    expect(screen.getByText(/FIRING 2/)).toBeInTheDocument()
    http.post.mockResolvedValue({ created_task_ids: [11, 12] })
    fireEvent.click(screen.getByText('立即执行'))
    await waitFor(() => expect(http.post).toHaveBeenCalledWith('/monitors/1/run-now'))
  })

  it('空列表展示排程引导空态', async () => {
    routes.set('/monitors', { items: [], total: 0 })
    routes.set('/projects', { items: [], total: 0 })
    page(<MonitorList />)
    await waitFor(() => expect(screen.getByText(/暂无监控/)).toBeInTheDocument())
  })
})

// ============================================= M6 复核台（键盘流核心）====
// ES9-P-10 三栏工作台契约：GET /review/queue + POST /review/items/{id}/decision；
// 键盘流 j/k 移动、1/2/3 选处置（PASS/FAIL/RETURN）、e 备注、s 保存跳下一条。
const QUEUE_ITEMS = {
  items: [
    { id: 11, status: 'OPEN', source: 'run_item', auto_verdict: 'PASS', auto_confidence: 0.9, context: { no: 'S-1', prompt: '注入样本A', category: 'SEC' } },
    { id: 12, status: 'OPEN', source: 'trace', auto_verdict: 'FAIL', auto_confidence: 0.8, context: { no: 'S-2', prompt: '链路样本B', category: 'RAG' } },
  ],
  total: 2,
  stats: { pending: 2, processed_today: 3, agreement: 0.85 },
}
function mountQueue() {
  routes.set('/review/queue', QUEUE_ITEMS)
  page(<ReviewQueuePage />)
}

describe('ReviewQueue 复核台 M6 键盘流（j/k/1-3/e/s）', () => {
  it('默认选中首项，j/k 在队列内切换当前复核项', async () => {
    setAuth({ perms: ['review:manage'] })
    mountQueue()
    await waitFor(() => expect(screen.getByText(/项 #11/)).toBeInTheDocument())
    fireEvent.keyDown(window, { key: 'j' })
    await waitFor(() => expect(screen.getByText(/项 #12/)).toBeInTheDocument())
    fireEvent.keyDown(window, { key: 'k' })
    await waitFor(() => expect(screen.getByText(/项 #11/)).toBeInTheDocument())
  })

  it('数字键 1 选维持 PASS + s 提交并自动跳下一项', async () => {
    setAuth({ perms: ['review:manage'] })
    mountQueue()
    await waitFor(() => expect(screen.getByTestId('disposition-PASS')).toBeInTheDocument())
    fireEvent.keyDown(window, { key: '1' })
    fireEvent.keyDown(window, { key: 's' })
    await waitFor(() =>
      expect(http.post).toHaveBeenCalledWith('/review/items/11/decision', {
        verdict: 'PASS', // 1 → 维持 PASS（三档处置顺序口径）
        note: undefined,
        promote_rule: false,
      }),
    )
    await waitFor(() => expect(screen.getByText(/项 #12/)).toBeInTheDocument())
  })

  it('数字键 2 选改判 FAIL 提交', async () => {
    setAuth({ perms: ['review:manage'] })
    mountQueue()
    await waitFor(() => expect(screen.getByText(/项 #11/)).toBeInTheDocument())
    fireEvent.keyDown(window, { key: '2' })
    fireEvent.keyDown(window, { key: 's' })
    await waitFor(() =>
      expect(http.post).toHaveBeenCalledWith(
        '/review/items/11/decision',
        expect.objectContaining({ verdict: 'FAIL' }),
      ),
    )
  })

  it('e 键聚焦复核备注输入框', async () => {
    setAuth({ perms: ['review:manage'] })
    mountQueue()
    const ta = await waitFor(() =>
      screen.getByPlaceholderText('记录判定依据，供评审 prompt 校准回溯'),
    )
    fireEvent.keyDown(window, { key: 'e' })
    expect(document.activeElement).toBe(ta)
  })

  it('无 review:manage 权限：处置面板隐藏，键盘提交不生效', async () => {
    setAuth({ perms: [] })
    mountQueue()
    await waitFor(() => expect(screen.getByText(/项 #11/)).toBeInTheDocument())
    expect(screen.queryByTestId('disposition-PASS')).not.toBeInTheDocument()
    fireEvent.keyDown(window, { key: '1' })
    fireEvent.keyDown(window, { key: 's' })
    expect(http.post).not.toHaveBeenCalled()
  })
})

// ==================================================== M8 在线评测 Trace ====
describe('TraceList 在线评测（M8）', () => {
  const TRACE_ROW = {
    id: 1, occurred_at: '2026-10-01T10:00:00', source: 'gateway', model: 'gpt-x',
    eval_status: 'SCORED', overall: 0.3, reviewed: false,
    request_preview: 'q1', response_preview: 'r1', tokens: 10, latency_ms: 100,
  }
  const POLICY = {
    enabled: true, sample_rate: 0.2, judge_metrics: ['injection'],
    daily_cap: 500, low_score_threshold: 0.6,
  }

  it('评分徽章按低分阈值分红/青，策略按钮受 trace:manage 门控', async () => {
    setAuth({ perms: ['trace:manage'] })
    routes.set('/traces/policy', POLICY) // 最长键优先，须先于 /traces
    routes.set('/traces', { items: [{ ...TRACE_ROW, id: 2, overall: 0.9 }], total: 1 })
    page(<TraceList />)
    await waitFor(() => expect(screen.getByText('在线评测 Trace')).toBeInTheDocument())
    expect(screen.getByText('已评分 0.9')).toBeInTheDocument() // 高分 → 青徽章
    expect(screen.getByText('策略配置')).toBeInTheDocument()
    expect(screen.queryByText('API Key')).not.toBeInTheDocument() // 无 admin:*
  })

  it('overall 低于阈值展示低分红徽章', async () => {
    setAuth({ perms: ['trace:manage'] })
    routes.set('/traces/policy', POLICY)
    routes.set('/traces', { items: [TRACE_ROW], total: 1 })
    page(<TraceList />)
    await waitFor(() => expect(screen.getByText('低分 0.3')).toBeInTheDocument())
  })

  it('策略抽屉打开时按 GET /traces/policy 回读', async () => {
    setAuth({ perms: ['trace:manage'] })
    routes.set('/traces/policy', POLICY)
    routes.set('/traces', { items: [], total: 0 })
    page(<TraceList />)
    await waitFor(() => expect(screen.getByText('策略配置')).toBeInTheDocument())
    fireEvent.click(screen.getByText('策略配置'))
    await waitFor(() => expect(screen.getByText('采样评分策略')).toBeInTheDocument())
    expect(http.get).toHaveBeenCalledWith('/traces/policy')
  })
})

// ==================================================== M11 工单集成 ====
describe('DefectSync 工单集成（M11）', () => {
  it('目标卡片渲染仓库与令牌掩码，测试连接打到契约端点', async () => {
    routes.set('/defect-sync/targets', {
      items: [
        {
          id: 3, name: '核心产品主仓', provider: 'github', enabled: true, last_probe_ok: null,
          config: { repo: 'acme/product', token_mask: 'ghp_****' },
        },
      ],
      total: 1,
    })
    page(<DefectSync />)
    await waitFor(() => expect(screen.getByText('工单集成')).toBeInTheDocument())
    expect(screen.getByText('核心产品主仓')).toBeInTheDocument()
    expect(screen.getByText('GitHub Issues')).toBeInTheDocument()
    expect(screen.getByText(/仓库：acme\/product/)).toBeInTheDocument()
    http.post.mockResolvedValue({ ok: true })
    fireEvent.click(screen.getByText('测试连接'))
    await waitFor(() => expect(http.post).toHaveBeenCalledWith('/defect-sync/targets/3/test'))
  })

  it('无目标时展示缺陷推送不可用空态', async () => {
    routes.set('/defect-sync/targets', { items: [], total: 0 })
    page(<DefectSync />)
    await waitFor(() =>
      expect(screen.getByText('暂无工单目标，缺陷详情页推送入口将不可用')).toBeInTheDocument(),
    )
  })
})

// ==================================================== M12 数据保留 ====
describe('Retention 数据保留与注销（M12）', () => {
  const SUB = { subscription: { status: 'ACTIVE', plan_code: 'pro' }, tenant: { id: 5, name: 'ACME' } }

  it('saas 形态：策略表中文标签 + 注销入口同屏', async () => {
    useEdition.mockReturnValue({ edition: 'saas' })
    routes.set('/retention/policies', {
      items: [
        { id: 1, artifact_type: 'traces', days: 30, purge_action: 'delete', archive_ref: null, updated_at: null },
      ],
      artifact_types: ['traces', 'audit_logs'],
      purge_actions: ['delete', 'archive_ref'],
    })
    routes.set('/billing/subscription', SUB)
    page(<Retention />)
    await waitFor(() => expect(screen.getByText('数据保留')).toBeInTheDocument())
    expect(screen.getByText('在线评测轨迹')).toBeInTheDocument()
    expect(screen.getByText('30 天')).toBeInTheDocument()
    expect(screen.getByText('物理删除')).toBeInTheDocument()
    // "注销并匿名化"在卡片标题与操作按钮各出现一次，断言按钮存在即可
    expect(screen.getAllByText('注销并匿名化').length).toBeGreaterThanOrEqual(2)
  })

  it('非 saas 形态：注销入口隐藏（后端 404 同步收敛）', async () => {
    useEdition.mockReturnValue({ edition: 'enterprise' })
    routes.set('/retention/policies', { items: [], artifact_types: [], purge_actions: [] })
    page(<Retention />)
    await waitFor(() => expect(screen.getByText('数据保留')).toBeInTheDocument())
    expect(screen.queryByText('注销并匿名化')).not.toBeInTheDocument()
    expect(http.get).not.toHaveBeenCalledWith('/billing/subscription')
  })
})

// ==================================================== M13 平台看板 ====
describe('PlatformOverview 平台运营看板（M13）', () => {
  function mountSaas() {
    setAuth({ perms: ['platform:manage'] })
    routes.set('/platform/overview', {
      active_tenants: 12, dau_today: 30, new_users_7d: 8,
      new_tenants_7d: 2, trialing_count: 5, past_due_count: 1,
    })
    routes.set('/platform/funnel', { buckets: [{ week_start: '2026-09-28', registered: 3, tenants_created: 2, trial_to_paid: 1 }] })
    routes.set('/platform/revenue', { buckets: [{ month: '2026-09', revenue_yuan: 1000, mrr_yuan: 900 }], current_mrr_yuan: 900 })
    routes.set('/platform/usage/top', { items: [{ tenant_id: 1, tenant_name: 'ACME', total_amount: 50, by_biz_type: { TASK: 5 } }] })
    routes.set('/platform/churn-risks', {
      items: [
        { tenant_id: 2, tenant_name: 'Beta', sub_status: 'GRACE', plan: 'pro', expires_at: '2026-11-01T00:00:00', overdue_days: 0, credits: 10, has_tasks: true },
      ],
    })
    page(<PlatformOverview />)
  }

  it('saas 五路聚合渲染指标卡与流失清单，代续费弹窗可达', async () => {
    mountSaas()
    await waitFor(() => expect(screen.getByText('平台运营看板')).toBeInTheDocument())
    expect(screen.getByText('活跃租户')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText(/流失风险清单/)).toBeInTheDocument()
    expect(screen.getByText('Beta')).toBeInTheDocument()
    fireEvent.click(screen.getByText('代续费'))
    await waitFor(() => expect(screen.getByText(/代续费：Beta/)).toBeInTheDocument())
  })

  it('端点 404 → 形态提示 Alert（非 saas 部署兜底）', async () => {
    setAuth({ perms: ['platform:manage'] })
    http.get.mockRejectedValue({ response: { status: 404 } })
    page(<PlatformOverview />)
    await waitFor(() =>
      expect(screen.getByText('平台运营看板仅 SaaS 形态可用')).toBeInTheDocument(),
    )
  })
})

// ============================================ M1 Register 三形态渲染 ====
describe('Register 三形态条件渲染（M1）', () => {
  it('saas：工作区文案 + 必填条款勾选 + 公开套餐列表', async () => {
    routes.set('/auth/capabilities', {
      registration_open: true, edition_hint: 'saas',
      plans_public: [{ code: 'pro', name: '专业版', price_monthly_cents: 29900 }],
    })
    page(<Register />)
    await waitFor(() =>
      expect(screen.getByText('注册即创建工作区，默认免费版，随时可升级')).toBeInTheDocument(),
    )
    expect(screen.getByText('企业/工作区名称')).toBeInTheDocument()
    expect(screen.getByText('《服务条款》')).toBeInTheDocument()
    expect(screen.getByText('可选套餐：')).toBeInTheDocument()
    expect(screen.getByText(/专业版/)).toBeInTheDocument()
  })

  it('enterprise：组织名称可选，无条款勾选', async () => {
    routes.set('/auth/capabilities', { registration_open: true, edition_hint: 'enterprise', plans_public: [] })
    page(<Register />)
    await waitFor(() =>
      expect(screen.getByText('注册后即可开始 AI 系统测试之旅')).toBeInTheDocument(),
    )
    expect(screen.getByText('组织名称（可选）')).toBeInTheDocument()
    expect(screen.queryByText('《服务条款》')).not.toBeInTheDocument()
  })

  it('registration_open=false：警示条提示联系管理员', async () => {
    routes.set('/auth/capabilities', { registration_open: false, edition_hint: 'enterprise', plans_public: [] })
    page(<Register />)
    await waitFor(() =>
      expect(screen.getByText('当前部署未开放自助注册，请联系管理员为您开通账号。')).toBeInTheDocument(),
    )
  })

  it('capabilities 拉取失败：按企业版保守形态渲染不白屏', async () => {
    http.get.mockRejectedValue(new Error('network down'))
    page(<Register />)
    await waitFor(() =>
      expect(screen.getByText('注册后即可开始 AI 系统测试之旅')).toBeInTheDocument(),
    )
    expect(screen.getByText('组织名称（可选）')).toBeInTheDocument()
  })
})
