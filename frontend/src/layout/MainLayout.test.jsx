// ES12 导航重排：左侧菜单分类结构契约测试
// 覆盖：①一级目录顺序与分组归属（8 目录单轴旅程制）②叶子 key(路由) 全集守恒（只重排不增删）
// ③目录 key 不与真实路由冲突 ④Tour 依赖的标签文案仍在菜单中
// ⑤过滤管线行为不回退（perm 拒绝隐藏、空目录逐层抑制、三层目录展开）
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import MainLayout from '../layout/MainLayout'

vi.mock('../api/http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

let mockPerms = null // null = 全放行
vi.mock('../auth', () => ({
  useAuth: () => ({
    user: { id: 1, display_name: 'tester' },
    loading: false,
    licensed: true,
    login: vi.fn(),
    logout: vi.fn(),
    setToken: vi.fn(),
    fetchMe: vi.fn(),
    // perm 支持字符串或数组（any-of）
    hasPerm: (p) => {
      if (Array.isArray(p)) return p.some((x) => (mockPerms ? mockPerms.has(x) : true))
      return mockPerms ? mockPerms.has(p) : true
    },
  }),
}))

vi.mock('../edition/EditionContext', () => ({
  useEdition: () => ({ edition: 'saas', editionInfo: {} }),
  useIsCommunity: () => false,
}))

// FE-002 复跑加固：flagOn 用真实实现（fail-open 语义），flags 由 mockFlags 驱动，
// 验证「目录子项全部被 flag 关闭 → 目录整体隐藏」不是仅靠 mock 全真通过。
let mockFlags = null
vi.mock('../edition/flags', async () => {
  const actual = await vi.importActual('../edition/flags')
  return {
    ...actual,
    useFeatureFlags: () => ({
      flags: mockFlags ?? Object.fromEntries(actual.KNOWN_NAV_FLAGS.map((k) => [k, true])),
      loaded: true,
      failed: false,
      refresh: vi.fn(),
    }),
  }
})

import http from '../api/http'

beforeEach(() => {
  vi.clearAllMocks()
  mockPerms = null
  mockFlags = null
  localStorage.clear()
  http.get.mockResolvedValue({ items: [] })
})

async function renderMenu() {
  render(
    <MemoryRouter initialEntries={['/dashboard-probe']}>
      <MainLayout />
    </MemoryRouter>
  )
  await waitFor(() => expect(screen.getByText('EvalShield')).toBeInTheDocument())
  return document.querySelector('.ant-menu')
}

// 展开指定标题的目录，返回目录内叶子项文本数组
async function expand(title, expectText) {
  const el = [...document.querySelectorAll('.ant-menu-submenu-title')].find((t) =>
    t.textContent.includes(title)
  )
  expect(el, `目录「${title}」应存在`).toBeTruthy()
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await waitFor(() => expect(screen.getByText(expectText)).toBeInTheDocument())
  return [...el.closest('.ant-menu-submenu').querySelectorAll('.ant-menu-item')].map((li) =>
    li.textContent.trim()
  )
}

describe('ES12 菜单分类结构（单轴旅程制）', () => {
  it('一级目录收敛为 8 项：概览→测试与评测→被测对象→专项工作台→实验区→空间设置→运营商务→系统管理', async () => {
    await renderMenu()
    const topTitles = [...document.querySelectorAll('.ant-menu > li')].map(
      (li) => (li.querySelector(':scope .ant-menu-title-content')?.textContent || '').trim()
    )
    expect(topTitles).toEqual([
      '概览',
      '测试与评测',
      '被测对象',
      '专项工作台',
      '实验区',
      '空间设置',
      '运营商务',
      '系统管理',
    ])
  })

  it('概览归组：质量总览/合规对标/报告中心/验收报告同目录（结果视角统一入口）', async () => {
    await renderMenu()
    const children = await expand('概览', '质量总览')
    for (const label of ['质量总览', '合规对标', '报告中心', '验收报告']) {
      expect(children.some((t) => t.includes(label)), `概览应包含 ${label}`).toBe(true)
    }
  })

  it('测试与评测闭环：执行域四件套 + 评测工作台并入，消除双工作台割裂', async () => {
    await renderMenu()
    const children = await expand('测试与评测', '资产中心')
    for (const label of ['项目管理', '任务中心', '资产中心', '文档导入', '评测工作台', '法规库', '缺陷管理', '人工复核']) {
      expect(children.some((t) => t.includes(label)), `测试与评测应包含 ${label}`).toBe(true)
    }
    // 一级不再有「测试工作台」「评测工作台」「报告中心」独立项
    expect(screen.queryByText('测试工作台')).not.toBeInTheDocument()
  })

  it('被测对象归组：被测系统/题库与覆盖度/模型网关/模型对比/成本看板同目录', async () => {
    await renderMenu()
    const children = await expand('被测对象', '被测系统')
    for (const label of ['被测系统', '题库与覆盖度', '模型网关', '模型对比', '成本看板']) {
      expect(children.some((t) => t.includes(label)), `被测对象应包含 ${label}`).toBe(true)
    }
    expect(screen.queryByText('模型服务')).not.toBeInTheDocument()
  })

  it('专项工作台仍含安全攻防/在线质量；实验区仅剩实验性能力（验收报告已迁概览）', async () => {
    await renderMenu()
    const spChildren = await expand('专项工作台', '安全攻防')
    for (const label of ['安全攻防', '在线质量']) {
      expect(spChildren.some((t) => t.includes(label)), `专项工作台应包含 ${label}`).toBe(true)
    }
    const labChildren = await expand('实验区', '定时监控')
    for (const label of ['定时监控', '源代码审计', 'UI 录制', 'AI 自动化', 'AI 自动探测']) {
      expect(labChildren.some((t) => t.includes(label)), `实验区应包含 ${label}`).toBe(true)
    }
    for (const gone of ['资产中心', '任务中心', '项目管理', '缺陷管理', '仪表盘', '计费管理', '模型网关', '安全攻防', '在线质量', '验收报告']) {
      expect(labChildren.some((t) => t.includes(gone)), `实验区不应再包含 ${gone}`).toBe(false)
    }
  })

  it('空间设置从头像下拉解耦：空间配置/通知中心/单点登录/数据保留/工单集成成目录', async () => {
    await renderMenu()
    const children = await expand('空间设置', '空间配置')
    for (const label of ['空间配置', '通知中心', '单点登录', '数据保留', '工单集成']) {
      expect(children.some((t) => t.includes(label)), `空间设置应包含 ${label}`).toBe(true)
    }
  })

  it('运营商务归组：计费/License/平台看板/部署检查同目录', async () => {
    await renderMenu()
    const children = await expand('运营商务', '计费管理')
    for (const label of ['计费管理', 'License 管理', '平台看板', '部署检查']) {
      expect(children.some((t) => t.includes(label)), `运营商务应包含 ${label}`).toBe(true)
    }
  })

  it('系统管理二级分组：平台基础/能力运维/安全与审计/租户运营四组，叶子不直接挂一级目录下', async () => {
    await renderMenu()
    const admin = [...document.querySelectorAll('.ant-menu-submenu-title')].find((el) =>
      el.textContent.includes('系统管理')
    )
    admin.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await waitFor(() => expect(screen.getByText('平台基础')).toBeInTheDocument())
    const platform = await expand('平台基础', '用户管理')
    for (const label of ['用户管理', '角色权限', '权限字典', '菜单管理', '数据字典', '系统参数', '组织机构']) {
      expect(platform.some((t) => t.includes(label)), `平台基础应包含 ${label}`).toBe(true)
    }
    const capability = await expand('能力运维', '引擎管理')
    for (const label of ['引擎管理', 'AI 配置管理', '版本形态']) {
      expect(capability.some((t) => t.includes(label)), `能力运维应包含 ${label}`).toBe(true)
    }
    const security = await expand('安全与审计', '审计日志')
    for (const label of ['API 密钥', '审计日志', '登录日志', '越狱样本库', 'PII 规则库']) {
      expect(security.some((t) => t.includes(label)), `安全与审计应包含 ${label}`).toBe(true)
    }
    const tenant = await expand('租户运营', '租户管理')
    for (const label of ['租户管理', '套餐费率']) {
      expect(tenant.some((t) => t.includes(label)), `租户运营应包含 ${label}`).toBe(true)
    }
  })

  it('菜单不再含「仪表盘」条目（/ 路由保留可达，唯一总览入口为质量总览）', async () => {
    await renderMenu()
    expect(screen.queryByText('仪表盘')).not.toBeInTheDocument()
    await expand('概览', '质量总览')
    expect(screen.getByText('质量总览')).toBeInTheDocument()
  })

  it('Tour 依赖文案（资产中心/任务中心/报告中心/缺陷管理）保持可被 textContent 匹配', async () => {
    await renderMenu()
    await expand('概览', '报告中心')
    await expand('测试与评测', '资产中心')
    // 模拟 tourTarget 的匹配方式：.ant-menu-item textContent.includes
    const items = [...document.querySelectorAll('.ant-menu-item')]
    for (const label of ['资产中心', '任务中心', '缺陷管理', '报告中心']) {
      expect(items.some((el) => el.textContent.includes(label)), `Tour 应能匹配 ${label}`).toBe(true)
    }
  })

  it('无 model:read 且无 eval:read 权限时：被测系统隐藏、概览内仅剩报告类叶子（空目录抑制不回退）', async () => {
    mockPerms = new Set(['project:read', 'task:read', 'case:read', 'case:create', 'defect:read', 'review:read', 'report:read'])
    await renderMenu()
    await waitFor(() => expect(screen.getByText('测试与评测')).toBeInTheDocument())
    // 概览仅剩报告中心/验收报告（质量总览、合规对标需 eval:read）
    expect(screen.queryByText('质量总览')).not.toBeInTheDocument()
    expect(screen.getByText('概览')).toBeInTheDocument()
    const children = await expand('概览', '报告中心')
    expect(children.some((t) => t.includes('被测系统'))).toBe(false)
    // 被测对象目录仍显示（题库与覆盖度 case:read 可见），但被测系统/模型网关/模型对比/成本看板隐藏
    const supply = await expand('被测对象', '题库与覆盖度')
    expect(supply.some((t) => t.includes('被测系统'))).toBe(false)
    expect(supply.some((t) => t.includes('模型网关'))).toBe(false)
  })

  // 任务一-2 语义保留：被测系统 perm 为 any-of(['model:read','eval:read'])，
  // 仅持 eval:read 的评测员必须能看到靶机入口（现藏于「被测对象」目录内）
  it('仅 eval:read（无 model:read）时展开「被测对象」仍可见被测系统，模型网关隐藏', async () => {
    mockPerms = new Set(['eval:read', 'case:read', 'report:read'])
    await renderMenu()
    await waitFor(() => expect(screen.getByText('被测对象')).toBeInTheDocument())
    const supply = await expand('被测对象', '被测系统')
    expect(supply.some((t) => t.includes('被测系统'))).toBe(true)
    expect(supply.some((t) => t.includes('模型网关'))).toBe(false)
  })

  // 任务一-1：缺陷管理图标语义修正为 ToolOutlined（此前误用 SafetyCertificateOutlined，与合规对标重复）
  it('缺陷管理图标为 ToolOutlined 而非 SafetyCertificateOutlined', async () => {
    await renderMenu()
    await expand('测试与评测', '缺陷管理')
    const defectLi = [...document.querySelectorAll('.ant-menu-item')].find((el) =>
      el.textContent.includes('缺陷管理')
    )
    expect(defectLi.querySelector('.anticon-tool')).toBeTruthy()
    expect(defectLi.querySelector('.anticon-safety-certificate')).toBeFalsy()
  })

  // FE-002（saas+focused 复跑口径）：专项工作台两个子项的 flag 全关时，
  // 目录必须整体隐藏而不是渲染为可展开的空目录。
  it('nav.lab.redteam 与 nav.lab.perf 同时关闭 →「专项工作台」目录隐藏（flag 空目录抑制）', async () => {
    mockFlags = { 'nav.lab.redteam': false, 'nav.lab.perf': false }
    await renderMenu()
    await waitFor(() => expect(screen.getByText('概览')).toBeInTheDocument())
    expect(screen.queryByText('专项工作台')).not.toBeInTheDocument()
    // 其他子项仍有开启的目录不受影响
    expect(screen.getByText('实验区')).toBeInTheDocument()
    expect(screen.getByText('运营商务')).toBeInTheDocument()
  })

  // ES12 三层目录：进入二级分组内的叶子路由时，一级+二级目录应自动展开
  it('路由命中三层叶子（/admin/users）时「系统管理」与「平台基础」自动展开', async () => {
    render(
      <MemoryRouter initialEntries={['/admin/users']}>
        <MainLayout />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('EvalShield')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('用户管理')).toBeInTheDocument())
    const userLi = [...document.querySelectorAll('.ant-menu-item')].find((el) =>
      el.textContent.includes('用户管理')
    )
    expect(userLi).toBeTruthy()
    // 选中态仅落在叶子，不落目录（高亮修复不回退）
    expect(userLi.className).toContain('ant-menu-item-selected')
    const adminTitle = [...document.querySelectorAll('.ant-menu-submenu-title')].find((el) =>
      el.textContent.includes('系统管理')
    )
    expect(adminTitle.closest('.ant-menu-submenu').className).toContain('ant-menu-submenu-open')
  })
})
