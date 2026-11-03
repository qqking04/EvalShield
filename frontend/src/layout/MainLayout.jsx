/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useMemo, useState } from 'react'
import { Layout, Menu, Dropdown, Avatar, Badge, Space, Typography, Button, Spin, Tour, message } from 'antd'
import {
  ProjectOutlined,
  ExperimentOutlined,
  DatabaseOutlined,
  AuditOutlined,
  FileTextOutlined,
  CloudServerOutlined,
  SettingOutlined,
  UserOutlined,
  TeamOutlined,
  KeyOutlined,
  ApartmentOutlined,
  ClusterOutlined,
  BellOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  CodeOutlined,
  WalletOutlined,
  SwapOutlined,
  ThunderboltOutlined,
  CompassOutlined,
  UploadOutlined,
  LoadingOutlined,
  LockOutlined,
  MenuOutlined,
  ControlOutlined,
  LoginOutlined,
  RobotOutlined,
  FileProtectOutlined,
  CrownOutlined,
  DollarOutlined,
  BarChartOutlined,
  AccountBookOutlined,
  NotificationOutlined,
  FieldTimeOutlined,
  BugOutlined,
  FundOutlined,
  SyncOutlined,
  ApiOutlined,
  ScheduleOutlined,
  ToolOutlined,
  AppstoreOutlined,
  DeploymentUnitOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth'
import { useEdition } from '../edition/EditionContext'
import { useFeatureFlags, flagOn } from '../edition/flags'
import LicenseBanner from '../components/LicenseBanner'
import CommunityNotice from '../components/CommunityNotice'
import http from '../api/http'

const { Sider, Header, Content } = Layout

// 菜单结构（ES12 导航重排）：一级按「角色旅程」单轴收敛为 8 个目录，成熟度（实验区）仅作补充维度：
// 概览(总览·合规·报告·验收) / 测试与评测(资产→执行→缺陷→复核闭环) / 被测对象(靶机·题库·模型服务) /
// 专项工作台 / 实验区(仅未闭环能力) / 空间设置(租户级配置，从头像下拉解耦) / 运营商务 /
// 系统管理(平台基础·能力运维·安全与审计·租户运营四组)。
// 重排原则：所有叶子 key(路由)、perm、flag、enterpriseOnly/saasOnly 原样保留，不增删路由；
// 目录 key(/overview、/supply、/space、/admin/* 分组) 为纯分组标识，不对应路由，渲染前逐层做空目录抑制。
// 目录不挂 perm 除非其全部成员共享同一 perm（避免收紧可见性契约）。
// 每项可挂 flag（nav.* / nav.lab.*），渲染前按 feature-flags 过滤；
// enterpriseOnly/saasOnly 旧字段保留一个版本做兼容判断。
const MENUS = [
  // perm 支持字符串或数组：数组为 any-of（任一命中即可见）。
  {
    // 结果与总览视角统一入口。原「/」仪表盘条目已移除（路由仍可达，App.jsx index → Dashboard）。
    key: '/overview',
    icon: <AppstoreOutlined />,
    label: '概览',
    children: [
      { key: '/dashboard', icon: <SafetyCertificateOutlined />, label: '质量总览', perm: 'eval:read' },
      // 优化12 M5：GBT45654 合规对标独立页（§10.3）
      { key: '/standards/gbt45654', icon: <FileProtectOutlined />, label: '合规对标', perm: 'eval:read' },
      { key: '/reports', icon: <FileTextOutlined />, label: '报告中心', perm: 'report:read', flag: 'nav.reports' },
      // ES9 UAT 推荐3：跨项目验收报告汇总中心（原实验区，属结果视角故并入概览）
      { key: '/uat-reports', icon: <AuditOutlined />, label: '验收报告', perm: 'report:read', flag: 'nav.lab.uat' },
    ],
  },
  {
    // 执行域闭环：Tour 引导链路「资产→执行→报告→缺陷」；评测工作台并入，消除测试/评测双入口割裂
    key: '/workflow',
    icon: <ProjectOutlined />,
    label: '测试与评测',
    children: [
      { key: '/projects', icon: <ProjectOutlined />, label: '项目管理', perm: 'project:read' },
      { key: '/tasks', icon: <ScheduleOutlined />, label: '任务中心', perm: 'task:read' },
      { key: '/assets', icon: <ClusterOutlined />, label: '资产中心', perm: 'case:read' },
      { key: '/documents/import', icon: <UploadOutlined />, label: '文档导入', perm: 'case:create' },
      { key: '/eval', icon: <AuditOutlined />, label: '评测工作台', perm: 'eval:read' },
      { key: '/regulations', icon: <FileProtectOutlined />, label: '法规库' },
      { key: '/defects', icon: <ToolOutlined />, label: '缺陷管理', perm: 'defect:read' },
      // ES8 M6：人工复核队列与 judge 校准
      { key: '/review', icon: <AuditOutlined />, label: '人工复核', perm: 'review:read' },
    ],
  },
  {
    // 被测对象供给侧统一：靶机 + 题库 + 模型基础设施同域；成员 perm 异构，目录不挂 perm
    key: '/supply',
    icon: <DeploymentUnitOutlined />,
    label: '被测对象',
    children: [
      { key: '/targets', icon: <CloudServerOutlined />, label: '被测系统', perm: ['model:read', 'eval:read'], flag: 'nav.targets' },
      { key: '/question-banks', icon: <DatabaseOutlined />, label: '题库与覆盖度', perm: 'case:read', flag: 'nav.question_bank' },
      { key: '/models', icon: <ApiOutlined />, label: '模型网关', perm: 'model:read' },
      { key: '/model-compare', icon: <BarChartOutlined />, label: '模型对比', perm: 'model:read', enterpriseOnly: true, flag: 'nav.lab.model_compare' },
      { key: '/cost', icon: <DollarOutlined />, label: '成本看板', perm: 'model:read', enterpriseOnly: true, flag: 'nav.lab.cost' },
    ],
  },
  {
    // ES11 §5.2 专项工作台：已形成生产闭环的专项能力；成员 perm 异构，目录不挂 perm
    key: '/specialized',
    icon: <ThunderboltOutlined />,
    label: '专项工作台',
    children: [
      // ES8 M9：生成式红队（样本池审批 + 载荷变异 + 框架覆盖与防护建议）
      { key: '/redteam', icon: <BugOutlined />, label: '安全攻防', perm: 'redteam:manage', flag: 'nav.lab.redteam' },
      // ES8 M8：在线评测最小闭环（trace 摄入 + 采样评分 + 回流）
      { key: '/traces', icon: <CompassOutlined />, label: '在线质量', perm: 'trace:read', flag: 'nav.lab.perf' },
    ],
  },
  {
    // 实验区仅保留未形成生产闭环的实验性/前瞻能力（验收报告已迁概览）
    key: '/lab',
    icon: <ExperimentOutlined />,
    label: '实验区',
    children: [
      // ES8 M4：定时监控与回归告警（Watchdog）
      { key: '/monitor', icon: <FieldTimeOutlined />, label: '定时监控', perm: 'monitor:read', flag: 'nav.lab.monitor' },
      { key: '/src-audit', icon: <CodeOutlined />, label: '源代码审计', flag: 'nav.lab.src' },
      { key: '/recordings', icon: <SwapOutlined />, label: 'UI 录制', perm: 'case:read', flag: 'nav.lab.recordings' },
      { key: '/ai/automation', icon: <ThunderboltOutlined />, label: 'AI 自动化', perm: 'task:create', flag: 'nav.lab.ci' },
      { key: '/ai/discover', icon: <RobotOutlined />, label: 'AI 自动探测', perm: 'task:create', flag: 'nav.lab.discover' },
    ],
  },
  {
    // 租户级空间配置从头像下拉解耦为独立目录；成员 perm 异构（含无 perm 项），目录不挂 perm
    key: '/space',
    icon: <ControlOutlined />,
    label: '空间设置',
    children: [
      { key: '/settings/workspace', icon: <TeamOutlined />, label: '空间配置' },
      { key: '/settings/notify', icon: <NotificationOutlined />, label: '通知中心', perm: 'notify:manage' },
      { key: '/settings/sso', icon: <LoginOutlined />, label: '单点登录', perm: 'sso:manage' },
      { key: '/settings/retention', icon: <DatabaseOutlined />, label: '数据保留', perm: 'retention:manage' },
      { key: '/settings/defect-sync', icon: <SyncOutlined />, label: '工单集成', perm: 'defect:manage' },
    ],
  },
  {
    // 运营/商务入口；成员 perm 异构，目录不挂 perm
    key: '/ops',
    icon: <WalletOutlined />,
    label: '运营商务',
    children: [
      { key: '/billing', icon: <WalletOutlined />, label: '计费管理', perm: 'billing:read' },
      { key: '/license', icon: <CrownOutlined />, label: 'License 管理', enterpriseOnly: true },
      // ES8 M13：平台运营看板（仅 saas 形态且持 platform:read 显示）
      { key: '/platform', icon: <AccountBookOutlined />, label: '平台看板', perm: 'platform:read', saasOnly: true },
      { key: '/health', icon: <FundOutlined />, label: '部署检查' },
    ],
  },
  {
    key: '/admin',
    icon: <SettingOutlined />,
    label: '系统管理',
    perm: 'admin:*',
    children: [
      {
        // 平台基础配置（目录级 admin:* 门控不变，子项 perm 原样保留）
        key: '/admin/platform',
        icon: <TeamOutlined />,
        label: '平台基础',
        children: [
          { key: '/admin/users', icon: <UserOutlined />, label: '用户管理' },
          { key: '/admin/roles', icon: <TeamOutlined />, label: '角色权限' },
          { key: '/admin/perms', icon: <LockOutlined />, label: '权限字典', perm: 'admin:perm' },
          { key: '/admin/menus', icon: <MenuOutlined />, label: '菜单管理', perm: 'admin:menu' },
          { key: '/admin/dicts', icon: <DatabaseOutlined />, label: '数据字典' },
          { key: '/admin/settings', icon: <ControlOutlined />, label: '系统参数', perm: 'admin:setting' },
          { key: '/admin/orgs', icon: <ApartmentOutlined />, label: '组织机构' },
        ],
      },
      {
        // 评测能力运维
        key: '/admin/capability',
        icon: <ThunderboltOutlined />,
        label: '能力运维',
        children: [
          { key: '/admin/engines', icon: <ThunderboltOutlined />, label: '引擎管理', perm: 'admin:setting' },
          { key: '/admin/ai-config', icon: <RobotOutlined />, label: 'AI 配置管理', perm: 'admin:setting' },
          // ES9 任务十二：版本形态运维（超管可见，路由/端点双重收紧）
          { key: '/admin/edition-ops', icon: <SwapOutlined />, label: '版本形态', perm: 'admin:setting' },
        ],
      },
      {
        // 安全与审计：ES9-P-01 安全配置类入口（越狱样本库 / PII 规则库，路由不变）
        key: '/admin/security',
        icon: <LockOutlined />,
        label: '安全与审计',
        children: [
          { key: '/admin/api-keys', icon: <KeyOutlined />, label: 'API 密钥' },
          { key: '/admin/audit', icon: <AuditOutlined />, label: '审计日志' },
          { key: '/admin/login-logs', icon: <LoginOutlined />, label: '登录日志', perm: 'admin:log' },
          { key: '/security/jailbreak-samples', icon: <ThunderboltOutlined />, label: '越狱样本库', perm: 'admin:dict' },
          { key: '/security/pii-rules', icon: <LockOutlined />, label: 'PII 规则库', perm: 'admin:dict' },
        ],
      },
      {
        // 租户运营（优化7 T6/T6b，仅 saas 形态显示；saasOnly 上提至目录，空目录抑制保证非 saas 形态不渲染）
        key: '/admin/tenant',
        icon: <ClusterOutlined />,
        label: '租户运营',
        saasOnly: true,
        children: [
          { key: '/admin/tenants', icon: <ClusterOutlined />, label: '租户管理' },
          { key: '/admin/plan-rates', icon: <AccountBookOutlined />, label: '套餐费率' },
        ],
      },
    ],
  },
]

// 组织切换器
function OrgSwitcher({ user, setToken }) {
  const [orgs, setOrgs] = useState([])
  const [loading, setLoading] = useState(false)
  const [switching, setSwitching] = useState(false)

  useEffect(() => {
    if (!user) return
    setLoading(true)
    http
      .get('/orgs/my')
      .then((data) => {
        const list = (data && (data.items || data)) || []
        setOrgs(list)
      })
      .catch((e) => {
        /* 组织列表加载失败（非阻断） */
        console.warn('[MainLayout] orgs list failed', e?.message || e)
      })
      .finally(() => setLoading(false))
  }, [user])

  const currentOrgId = user?.org?.id || user?.org_id || null
  const currentOrgName =
    user?.org?.name || user?.org_name || orgs.find((o) => o.id === currentOrgId)?.name || '当前空间'

  const handleSwitch = async (orgId) => {
    if (orgId === currentOrgId || switching) return
    setSwitching(true)
    try {
      const data = await http.post('/orgs/switch', { org_id: orgId })
      if (data && data.access_token) {
        await setToken(data.access_token, data.refresh_token)
        window.location.reload()
      }
    } catch (e) {
      /* 错误已由拦截器提示 */
      console.warn('[MainLayout] org switch failed', e?.message || e)
    } finally {
      setSwitching(false)
    }
  }

  const dropdownItems = orgs.map((o) => ({
    key: String(o.id),
    label: (
      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {o.id === currentOrgId ? <span style={{ color: '#13c2c2' }}>✓</span> : <span style={{ width: 12, display: 'inline-block' }} />}
        <span>{o.name}</span>
        <span style={{ color: '#869BAA', fontSize: 12 }}>{o.role_name || ''}</span>
      </span>
    ),
    onClick: () => handleSwitch(orgId),
  }))

  return (
    <Dropdown
      menu={{ items: dropdownItems.length ? dropdownItems : [{ key: 'none', label: '暂无其他空间', disabled: true }] }}
      trigger={['click']}
      disabled={loading || orgs.length <= 1}
    >
      <div className="org-switcher" style={{ color: '#e6f7ff' }}>
        <span className="active-mark" />
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 }}>
          {switching ? '切换中...' : currentOrgName}
        </span>
        {switching ? <LoadingOutlined style={{ color: '#13c2c2' }} /> : <SwapOutlined style={{ color: '#8ba3b5' }} />}
      </div>
    </Dropdown>
  )
}

// BUG-007（C18）：新手引导 Tour —— 4 步弹层，首次登录弹出，可手动关闭，重启不重复弹层
const TOUR_STORAGE_KEY = 'es_tour_done'
// BUG-011：Tour target 必须返回「已布局且可见」的元素。
// jsdom/无布局环境下 getBoundingClientRect 全 0；侧栏收起或菜单项尚未渲染时，
// 兜底节点也可能不可见。此时返回 null，按 antd Tour 惯例跳过该 step 的遮罩定位，
// 避免遮罩对负宽/零宽 rect 定位产生 console error。
function visibleOr(el) {
  if (!el) return null
  try {
    const rect = el.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) return null
    if (typeof window.getComputedStyle === 'function' && window.getComputedStyle(el).visibility === 'hidden') return null
  } catch {
    return null
  }
  return el
}
const tourTarget = (label) => () => {
  const items = document.querySelectorAll('.ant-menu-item')
  const hit = [...items].find((el) => el.textContent && el.textContent.includes(label))
  return visibleOr(hit) || visibleOr(document.querySelector('.ant-layout-sider'))
}

// 在已过滤的菜单树中查找与当前路径匹配的叶子：
// 精确命中优先，其次最长前缀命中（如 /tasks/123 命中 /tasks）；
// 返回 { key, trail }，trail 为自顶向下的目录 key 链（用于展开）。
function findLeaf(menus, pathname, trail = []) {
  let best = null
  for (const m of menus) {
    if (m.children) {
      const hit = findLeaf(m.children, pathname, [...trail, m.key])
      if (hit && (!best || hit.key.length > best.key.length)) best = hit
    } else if (pathname === m.key || (m.key !== '/' && pathname.startsWith(m.key + '/'))) {
      if (!best || m.key.length > best.key.length) best = { key: m.key, trail }
    }
  }
  return best
}

export default function MainLayout() {
  const { user, logout, hasPerm, setToken, licensed } = useAuth()
  // 优化7 T6：形态名用于 saasOnly 菜单门控（License 横幅收敛到 LicenseBanner 组件）
  const { edition: edName } = useEdition()
  // ES9-P-01：feature flags 驱动导航过滤；拉取失败 flags 全 true（fail-open）+ 一次性提示
  const { flags, failed: flagsFailed } = useFeatureFlags()
  const navigate = useNavigate()
  const location = useLocation()
  const [notifCount, setNotifCount] = useState(0)
  const [collapsed, setCollapsed] = useState(false)
  const [tourOpen, setTourOpen] = useState(false)
  const [tourStats, setTourStats] = useState(null)
  // ES12：三层目录结构下的受控展开状态
  const [openKeys, setOpenKeys] = useState([])

  useEffect(() => {
    // 一次性提示：本地记录已读则不再打扰
    if (flagsFailed && !localStorage.getItem('es_flags_fail_notice_done')) {
      message.warning('导航配置加载失败，已显示完整入口')
      try { localStorage.setItem('es_flags_fail_notice_done', '1') } catch { /* 隐私模式静默 */ }
    }
  }, [flagsFailed])

  const items = useMemo(() => {
    // perm 兼容字符串与数组：数组为 any-of（任一命中即可见）
    const permOk = (perm) =>
      !perm || (Array.isArray(perm) ? perm.some((p) => hasPerm(p)) : hasPerm(perm))
    // 逐层过滤 + 逐层空目录抑制：任一目录（含嵌套目录）子项全部被过滤掉时隐藏该目录
    const filter = (menus) =>
      menus
        .filter((m) => permOk(m.perm))
        .filter((m) => !m.enterpriseOnly || licensed) // 旧字段兼容：保留一个版本
        .filter((m) => !m.saasOnly || edName === 'saas') // 旧字段兼容：保留一个版本
        .filter((m) => flagOn(flags, m.flag)) // ES9-P-01：flag 过滤（未知/缺省 fail-open）
        .map((m) => {
          if (!m.children) return { key: m.key, icon: m.icon, label: m.label }
          return { key: m.key, icon: m.icon, label: m.label, children: filter(m.children) }
        })
        .filter((m) => !m.children || m.children.length > 0)
    return filter(MENUS)
  }, [user, licensed, edName, flags])

  // 选中叶子与祖先目录链（进入详情页时自动展开对应目录，不回退此前的高亮修复）。
  // 依赖取 key/trail 的字符串快照：auth/flags 上下文每次渲染返回新对象时，
  // items/leaf 的 memo 引用不稳定，若直接以对象为依赖会造成展开效果无限重跑。
  const leaf = useMemo(() => findLeaf(items, location.pathname), [items, location.pathname])
  const selected = leaf?.key || '/'
  const trailKey = leaf?.trail?.join('|') || ''
  useEffect(() => {
    if (!trailKey) return
    const trail = trailKey.split('|')
    setOpenKeys((prev) => {
      const missing = trail.filter((k) => !prev.includes(k))
      if (!missing.length) return prev
      return [...prev, ...missing]
    })
  }, [trailKey])

  useEffect(() => {
    if (!user) return
    http
      .get('/notifications')
      .then((data) => {
        const items = (data && data.items) || []
        setNotifCount(items.filter((n) => !n.is_read).length)
      })
      .catch((e) => console.warn('[MainLayout] notifications fail', e?.message || e))
  }, [user])

  // BUG-007：首次登录（localStorage 无标记）延迟弹出 4 步引导；关闭即写标记，重启不重复弹
  useEffect(() => {
    if (!user) return
    try {
      if (localStorage.getItem(TOUR_STORAGE_KEY)) return
      http.get('/assets/stats').then((d) => setTourStats(d && d.data ? d.data : d)).catch(() => {})
      // BUG-011：等待布局完成（rAF 下一帧）再打开 Tour，避免遮罩拿到未布局的 rect
      const t = setTimeout(() => requestAnimationFrame(() => setTourOpen(true)), 800)
      return () => clearTimeout(t)
    } catch { /* 隐私模式等异常静默 */ }
  }, [user])

  const finishTour = () => {
    setTourOpen(false)
    try { localStorage.setItem(TOUR_STORAGE_KEY, '1') } catch { /* ignore */ }
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        width={220}
        theme="dark"
      >
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: collapsed ? 14 : 17,
            fontWeight: 600,
            letterSpacing: 1,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
          }}
        >
          <SafetyCertificateOutlined style={{ marginRight: collapsed ? 0 : 8 }} />
          {!collapsed && 'EvalShield'}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selected]}
          openKeys={openKeys}
          onOpenChange={(keys) => setOpenKeys(keys)}
          items={items}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#11161d',
            padding: '0 24px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            borderBottom: '1px solid #1f2833',
            boxShadow: 'none',
          }}
        >
          <Space size={16}>
            <Typography.Text strong style={{ fontSize: 15, color: '#e6f7ff' }}>
              AI 系统测试服务平台
            </Typography.Text>
            <OrgSwitcher user={user} setToken={setToken} />
          </Space>
          <Space size={20}>
            <Badge count={notifCount} size="small">
              <Button
                type="text"
                icon={<BellOutlined />}
                onClick={() => navigate('/reports')}
                style={{ color: '#8ba3b5' }}
              />
            </Badge>
            {/* ES12：租户级配置（通知/SSO/数据保留/工单集成）已迁至「空间设置」目录，
                下拉仅保留个人维度入口 */}
            <Dropdown
              menu={{
                items: [
                  {
                    key: 'profile',
                    icon: <UserOutlined />,
                    label: '个人资料',
                    onClick: () => navigate('/settings/profile'),
                  },
                  { key: 'security', icon: <SafetyCertificateOutlined />, label: '个人安全' },
                  { type: 'divider' },
                  { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
                ],
                onClick: async ({ key }) => {
                  if (key === 'logout') {
                    await logout()
                    navigate('/login')
                  } else if (key === 'security') {
                    navigate('/security')
                  }
                },
              }}
            >
              <Space style={{ cursor: 'pointer' }}>
                <Avatar style={{ background: '#13c2c2', color: '#0b0f14' }} icon={<UserOutlined />} />
                <span style={{ color: '#e6f7ff' }}>{user?.display_name || user?.username}</span>
              </Space>
            </Dropdown>
          </Space>
        </Header>
        {/* 优化7 T5/T7：License 全局横幅（未激活引导 / grace / revoked 三态同一组件） */}
        <LicenseBanner />
        {/* ES9-P-02：社区形态首启一次性升级提示 */}
        <CommunityNotice />
        <Content style={{ margin: 16 }}>
          <Outlet />
        </Content>
      </Layout>
      {/* BUG-007：新手引导 4 步 Tour（步骤完成态随覆盖数据刷新，展示当前资产统计） */}
      <Tour
        open={tourOpen}
        onClose={finishTour}
        steps={[
          {
            title: '① 资产中心：准备测试素材',
            description: `管理「测试用例」「数据集」「数据流场景」与「评测集」。当前已有 用例 ${tourStats?.cases?.total ?? 0} 条、数据集 ${tourStats?.datasets?.total ?? 0} 个、场景 ${tourStats?.scenarios?.total ?? 0} 个、评测集 ${tourStats?.eval_sets?.total ?? 0} 个。可手动「新建」，也可用「AI 生成」自动产出。`,
            target: tourTarget('资产中心'),
            placement: 'right',
          },
          {
            title: '② 任务中心：发起测试任务',
            description: '创建任务选择引擎（API/UI/数据流/性能等）执行用例；也可在资产中心对单个用例「快速执行」或对场景点「执行」发起数据流任务。',
            target: tourTarget('任务中心'),
            placement: 'right',
          },
          {
            title: '③ 报告中心：查看结果',
            description: '执行结果以「功能覆盖 / 数据流执行 / 页面·接口明细 / BUG 清单」四 Tabs 呈现，可一键导出 JSON / PDF / Word。',
            target: tourTarget('报告中心'),
            placement: 'right',
          },
          {
            title: '④ 缺陷管理：闭环跟踪',
            description: '失败用例可一键批量转缺陷；缺陷支持 AI 分类、关联用例/报告/任务、上传附件与状态流转。至此完成「资产→执行→报告→缺陷」全链路。',
            target: tourTarget('缺陷管理'),
            placement: 'right',
          },
        ]}
      />
    </Layout>
  )
}
