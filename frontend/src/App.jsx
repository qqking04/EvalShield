/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { lazy } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { AuthProvider, useAuth } from './auth'
import { EditionProvider } from './edition/EditionContext'
import RequirePerm from './components/RequirePerm'
import CommercialGate from './components/CommercialGate'
import PageSuspense from './components/common/PageSuspense'

import LoginPage from './pages/Login'
import MainLayout from './layout/MainLayout'

import Dashboard from './pages/Dashboard'
import Projects from './pages/Projects'
import TaskDetail from './pages/TaskDetail'
import Assets from './pages/Assets'
import EvalCenter from './pages/EvalCenter'
import Reports from './pages/Reports'
import Models from './pages/Models'
import HealthCheck from './pages/HealthCheck'
import Security from './pages/Security'
import AdminUsers from './pages/admin/Users'
import AdminRoles from './pages/admin/Roles'
import AdminDicts from './pages/admin/Dicts'
import AdminEngines from './pages/admin/Engines'
import AdminApiKeys from './pages/admin/ApiKeys'
import AdminAudit from './pages/admin/AuditLogs'
import AdminMenus from './pages/admin/Menus'
import AdminPermissions from './pages/admin/Permissions'
import AdminSettings from './pages/admin/Settings'
import AdminEditionOps from './pages/admin/EditionOps'
import AdminAiConfig from './pages/admin/AiConfig'
import AdminLoginLogs from './pages/admin/LoginLogs'

// 新增页面（免登录）
import Register from './pages/auth/Register'
import ForgotPassword from './pages/auth/ForgotPassword'
import ResetPassword from './pages/auth/ResetPassword'
import InviteAccept from './pages/auth/InviteAccept'
import ShareReport from './pages/auth/ShareReport'
import ForceChangePassword from './pages/auth/ForceChangePassword'
// ES9 UAT：免登录客户签署页
import UatSignView from './pages/uat/UatSignView'

// 新增页面（需登录）
import ProfileSettings from './pages/settings/ProfileSettings'
import WorkspaceSettings from './pages/settings/WorkspaceSettings'
import ProjectDetail from './pages/projects/ProjectDetail'
// ES9 UAT：验收报告详情（需登录）
import UatReportDetail from './pages/uat/UatReportDetail'
// ES9 UAT 推荐3：跨项目验收报告汇总中心
import UatReportCenter from './pages/uat/UatReportCenter'
import Suites from './pages/projects/Suites'
import Versions from './pages/projects/Versions'
import DocumentImport from './pages/DocumentImport'
import AIAutomation from './pages/AIAutomation'

// F9：首屏大页面按需分包（TC-ROUTE-006），build 后各自成独立 chunk
const Tasks = lazy(() => import('./pages/Tasks'))
// ES9-P-16：商业域（security_assets）直连 import 页面补 lazy——路由元素包在
// <Commercial>（内部已含 PageSuspense）里，仅改 import 形态不动 Route 定义
const JailbreakSamples = lazy(() => import('./pages/security/JailbreakSamples'))
const PiiRules = lazy(() => import('./pages/security/PiiRules'))

// F1 版本隔离：商业页面物理收敛到 pages/commercial/（OSS 构建 strip_fe.js 整目录剔除）；
// F-build：全部改 lazy，chunk 缺失时由 CommercialGate 兜底渲染 UpgradeEmpty。
const AIDiscover = lazy(() => import('./pages/CommercialPlaceholder'))
const DiscoverJobDetail = lazy(() => import('./pages/CommercialPlaceholder'))
const SrcAudit = lazy(() => import('./pages/CommercialPlaceholder'))
const CostDashboard = lazy(() => import('./pages/CommercialPlaceholder'))
const ModelCompare = lazy(() => import('./pages/CommercialPlaceholder'))
const LicenseAdmin = lazy(() => import('./pages/CommercialPlaceholder'))
const Billing = lazy(() => import('./pages/CommercialPlaceholder'))
// ES8 M1：租户自助订阅页
const SubscriptionPage = lazy(() => import('./pages/billing/Subscription'))
// ES8 M2：公开定价页（免登录）+ 站内收银台
const PricingPage = lazy(() => import('./pages/billing/Pricing'))
const PaymentPage = lazy(() => import('./pages/billing/Payment'))
const DefectsTab = lazy(() => import('./pages/CommercialPlaceholder'))
const RecordingsTab = lazy(() => import('./pages/CommercialPlaceholder'))
const ReportCompare = lazy(() => import('./pages/CommercialPlaceholder'))
const RegulationLibrary = lazy(() => import('./pages/CommercialPlaceholder'))
const AdminOrgs = lazy(() => import('./pages/CommercialPlaceholder'))
const Tenants = lazy(() => import('./pages/CommercialPlaceholder'))
const PlanRates = lazy(() => import('./pages/CommercialPlaceholder'))
// ES8 M3：通知中心
const NotifyCenter = lazy(() => import('./pages/settings/Notify'))
// ES8 M10：SSO 单点登录配置
const SsoSettings = lazy(() => import('./pages/settings/Sso'))
// ES8 M12：数据保留与注销
const RetentionSettings = lazy(() => import('./pages/settings/Retention'))
// ES8 M11：缺陷工单同步（工单集成）
const DefectSyncSettings = lazy(() => import('./pages/settings/DefectSync'))
// ES8 M4：定时监控与回归告警（Watchdog）
const MonitorList = lazy(() => import('./pages/monitor/MonitorList'))
// ES8 M6：人工复核队列与 judge 校准
const ReviewQueue = lazy(() => import('./pages/review/Queue'))
// ES8 M8：在线评测最小闭环（trace 摄入 + 采样评分 + 回流）
const TraceList = lazy(() => import('./pages/traces/TraceList'))
// ES8 M9：生成式红队（样本池审批 + 载荷变异 + 框架覆盖与防护建议）
const RedTeamCenter = lazy(() => import('./pages/redteam/RedTeamCenter'))
// ES8 M13：平台运营看板（saas-only）
const PlatformOverview = lazy(() => import('./pages/CommercialPlaceholder'))
// ES9-P-01/02/09：题库与覆盖度、被测系统、版本能力对比
const QuestionBanksList = lazy(() => import('./pages/question-banks/QuestionBanksList'))
const QuestionBankDetail = lazy(() => import('./pages/question-banks/QuestionBankDetail'))
const TargetsPage = lazy(() => import('./pages/TargetsPage'))
const EditionCompare = lazy(() => import('./pages/edition/EditionCompare'))
// ES11：企业级闭环（质量总览/运行详情/缺陷详情/Trace 分诊/报告交付）
const QualityOverview = lazy(() => import('./pages/es11/QualityOverview'))
const RunWorkspace = lazy(() => import('./pages/es11/RunWorkspace'))
const DefectDetail = lazy(() => import('./pages/es11/DefectDetail'))
const TraceTriage = lazy(() => import('./pages/es11/TraceTriage'))
const ReportDelivery = lazy(() => import('./pages/es11/ReportDelivery'))
// 优化12 M5：GBT45654 合规对标页（§10.3）
const DimensionBenchmark = lazy(() => import('./pages/es11/DimensionBenchmark'))

// 商业路由统一装载：门控（社区版→升级引导）→ chunk 缺失兜底 → 按需加载骨架
function Commercial({ kind, perm, enterpriseOnly, children }) {
  return (
    <RequirePerm perm={perm} enterpriseOnly={enterpriseOnly} commercialOnly upgradeKind={kind}>
      <CommercialGate kind={kind}>
        <PageSuspense>{children}</PageSuspense>
      </CommercialGate>
    </RequirePerm>
  )
}

function RequireAuth({ children }) {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 120 }}>
        {/* BUG-010：antd Spin 需包裹 children，否则 tip 告警 */}
        <Spin size="large" tip="加载中...">
          <div style={{ minHeight: 80, minWidth: 80 }} />
        </Spin>
      </div>
    )
  }
  if (!user) {
    return <Navigate to="/login" replace />
  }
  return children
}

/**
 * 优化12 §8.1/§8.3：后端门禁出链统一为 /eval-center?tab=banks&sub=...，
 * 重定向到 /eval 时保留 query（Navigate 静态写法会丢深链参数）。
 */
function EvalCenterRedirect() {
  const location = useLocation()
  return <Navigate to={`/eval${location.search || ''}`} replace />
}

export default function App() {
  return (
    <EditionProvider>
      <AuthProvider>
        {/* BUG-010：显式声明 v7 Future Flag，消除 Router 控制台告警 */}
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routes>
            {/* 免登录公开页 */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<Register />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route path="/invite/accept" element={<InviteAccept />} />
            <Route path="/share/:token" element={<ShareReport />} />
            {/* ES9 UAT：免登录客户签署页 */}
            <Route path="/s/uat/:token" element={<UatSignView />} />
            {/* ES8 M2：公开定价页（免登录营销页，后端缺席时页面自容错） */}
            <Route path="/pricing" element={<PageSuspense><PricingPage /></PageSuspense>} />
            {/* ES9-P-02：版本能力对比页（免登录公开） */}
            <Route path="/edition-compare" element={<PageSuspense><EditionCompare /></PageSuspense>} />
            {/* 优化7 T4：半态令牌专用页（持有已登录 token，但不在受保护布局内） */}
            <Route path="/force-change-password" element={<ForceChangePassword />} />

            {/* 需登录 */}
            <Route
              path="/"
              element={
                <RequireAuth>
                  <MainLayout />
                </RequireAuth>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="projects" element={<Projects />} />
              <Route path="projects/:id" element={<ProjectDetail />} />
              {/* ES9 UAT：验收报告详情（挂在主布局内，report:read 权限） */}
              <Route path="uat/:reportId" element={
                <RequirePerm perm="report:read"><UatReportDetail /></RequirePerm>
              } />
              {/* ES9 UAT 推荐3：跨项目验收报告汇总中心 */}
              <Route path="uat-reports" element={
                <RequirePerm perm="report:read"><UatReportCenter /></RequirePerm>
              } />
              <Route path="projects/:id/suites" element={<Suites />} />
              <Route path="projects/:id/versions" element={<Versions />} />
              <Route path="tasks" element={<PageSuspense><Tasks /></PageSuspense>} />
              <Route path="tasks/:id" element={<TaskDetail />} />
              <Route path="assets" element={<Assets />} />
              <Route path="eval" element={<EvalCenter />} />
              {/* 优化12 §8.1：后端门禁 action.path 统一出链 /eval-center，重定向到评测中心（保留 query 深链参数） */}
              <Route path="eval-center" element={<EvalCenterRedirect />} />
              {/* 优化12 M5：合规对标独立页（不动 /compliance） */}
              <Route path="standards/gbt45654" element={
                <RequirePerm perm="eval:read"><PageSuspense><DimensionBenchmark /></PageSuspense></RequirePerm>
              } />
              {/* ES11 统一运行详情深链（P3） */}
              <Route path="eval/runs/:id" element={
                <RequirePerm perm="eval:read"><PageSuspense><RunWorkspace /></PageSuspense></RequirePerm>
              } />
              {/* ES11 缺陷闭环详情深链（P4） */}
              <Route path="defects/:id" element={
                <RequirePerm perm="defect:read"><PageSuspense><DefectDetail /></PageSuspense></RequirePerm>
              } />
              {/* ES11 在线质量 Trace 分诊深链（P9） */}
              <Route path="traces/:id" element={
                <RequirePerm perm="trace:read"><PageSuspense><TraceTriage /></PageSuspense></RequirePerm>
              } />
              {/* ES11 报告交付 G4（P10） */}
              <Route path="reports/:id/delivery" element={
                <RequirePerm perm="report:read"><PageSuspense><ReportDelivery /></PageSuspense></RequirePerm>
              } />
              {/* ES11 质量总览（P1，导航重组入口） */}
              <Route path="dashboard" element={
                <RequirePerm perm="eval:read"><PageSuspense><QualityOverview /></PageSuspense></RequirePerm>
              } />
              {/* ES9-P-09：题库与覆盖度（一级导航第 3 入口） */}
              <Route path="question-banks" element={
                <RequirePerm perm="case:read"><PageSuspense><QuestionBanksList /></PageSuspense></RequirePerm>
              } />
              <Route path="question-banks/:id" element={
                <RequirePerm perm="case:read"><PageSuspense><QuestionBankDetail /></PageSuspense></RequirePerm>
              } />
              {/* ES9-P-01：被测系统门面 */}
              <Route path="targets" element={
                <RequirePerm perm="model:read"><PageSuspense><TargetsPage /></PageSuspense></RequirePerm>
              } />
              <Route path="reports" element={<Reports />} />
              <Route path="reports/compare" element={<Commercial kind="report_compare"><ReportCompare /></Commercial>} />
              <Route path="defects" element={<Commercial kind="defects"><DefectsTab /></Commercial>} />
              <Route path="recordings" element={<Commercial kind="recordings"><RecordingsTab /></Commercial>} />
              <Route path="documents/import" element={<DocumentImport />} />
              <Route path="ai/automation" element={<AIAutomation />} />
              <Route path="ai/discover" element={<Commercial kind="discover"><AIDiscover /></Commercial>} />
              <Route path="ai/discover/:jobId" element={<Commercial kind="discover"><DiscoverJobDetail /></Commercial>} />
              {/* 合规映射的落点是 /reports 的 compliance tab，门控在 Reports.jsx 内部 */}
              <Route path="compliance" element={<Navigate to="/reports?tab=compliance" replace />} />
              <Route path="regulations" element={<Commercial kind="regulations"><RegulationLibrary /></Commercial>} />
              <Route path="src-audit" element={<Commercial kind="src_audit"><SrcAudit /></Commercial>} />
              <Route path="models" element={<Models />} />
              <Route path="license" element={
                <Commercial kind="license_ledger" perm="license:revoke" enterpriseOnly><LicenseAdmin /></Commercial>
              } />
              <Route path="cost" element={<Commercial kind="cost"><CostDashboard /></Commercial>} />
              <Route path="model-compare" element={<Commercial kind="model_compare"><ModelCompare /></Commercial>} />
              <Route path="health" element={<HealthCheck />} />
              <Route path="model-gateways" element={<Navigate to="/models" replace />} />

              {/* 设置 */}
              <Route path="settings/profile" element={<ProfileSettings />} />
              <Route path="settings/workspace" element={<WorkspaceSettings />} />
              {/* ES8 M3：通知中心（渠道/规则/留痕） */}
              <Route path="settings/notify" element={
                <RequirePerm perm="notify:manage"><PageSuspense><NotifyCenter /></PageSuspense></RequirePerm>
              } />
              {/* ES8 M10：SSO 单点登录配置 */}
              <Route path="settings/sso" element={
                <RequirePerm perm="sso:manage"><PageSuspense><SsoSettings /></PageSuspense></RequirePerm>
              } />
              {/* ES8 M12：数据保留与注销 */}
              <Route path="settings/retention" element={
                <RequirePerm perm="retention:manage"><PageSuspense><RetentionSettings /></PageSuspense></RequirePerm>
              } />
              {/* ES8 M11：工单集成（defect:manage 权限，能力位由后端 403 兜底） */}
              <Route path="settings/defect-sync" element={
                <RequirePerm perm="defect:manage"><PageSuspense><DefectSyncSettings /></PageSuspense></RequirePerm>
              } />
              {/* ES8 M4：定时监控（capability monitor 由后端 403 兜底） */}
              <Route path="monitor" element={
                <RequirePerm perm="monitor:read"><PageSuspense><MonitorList /></PageSuspense></RequirePerm>
              } />
              {/* ES8 M6：人工复核队列与 judge 校准 */}
              <Route path="review" element={
                <RequirePerm perm="review:read"><PageSuspense><ReviewQueue /></PageSuspense></RequirePerm>
              } />
              {/* ES8 M8：在线评测最小闭环 */}
              <Route path="traces" element={
                <RequirePerm perm="trace:read"><PageSuspense><TraceList /></PageSuspense></RequirePerm>
              } />
              {/* ES8 M9：生成式红队（能力位 generative_redteam 未点亮时后端各端点 403） */}
              <Route path="redteam" element={
                <RequirePerm perm="redteam:manage"><PageSuspense><RedTeamCenter /></PageSuspense></RequirePerm>
              } />

              {/* 管理 */}
              <Route path="admin/users" element={
                <RequirePerm perm="admin:user"><AdminUsers /></RequirePerm>
              } />
              <Route path="admin/roles" element={
                <RequirePerm perm="admin:role"><AdminRoles /></RequirePerm>
              } />
              <Route path="admin/dicts" element={
                <RequirePerm perm="admin:dict"><AdminDicts /></RequirePerm>
              } />
              <Route path="admin/engines" element={
                <RequirePerm perm="admin:setting"><AdminEngines /></RequirePerm>
              } />
              <Route path="admin/api-keys" element={
                <RequirePerm perm="admin:apikey"><AdminApiKeys /></RequirePerm>
              } />
              <Route path="admin/audit" element={
                <RequirePerm perm="admin:audit"><AdminAudit /></RequirePerm>
              } />
              <Route path="admin/orgs" element={
                <Commercial kind="orgs" perm="admin:org"><AdminOrgs /></Commercial>
              } />
              {/* 优化7 T6：租户主数据运营后台（saas-only，后端 404 兜底 + 页内形态提示） */}
              <Route path="admin/tenants" element={
                <Commercial kind="tenants"><PageSuspense><Tenants /></PageSuspense></Commercial>
              } />
              {/* 优化7 T6b：套餐费率维护（saas-only） */}
              <Route path="admin/plan-rates" element={
                <Commercial kind="plan-rates"><PageSuspense><PlanRates /></PageSuspense></Commercial>
              } />
              {/* ES8 M13：平台运营看板（saas-only，platform:read；后端 404 兜底 + 页内形态提示） */}
              <Route path="platform" element={
                <Commercial kind="platform" perm="platform:read"><PageSuspense><PlatformOverview /></PageSuspense></Commercial>
              } />
              <Route path="admin/perms" element={
                <RequirePerm perm="admin:perm"><AdminPermissions /></RequirePerm>
              } />
              <Route path="admin/menus" element={
                <RequirePerm perm="admin:menu"><AdminMenus /></RequirePerm>
              } />
              <Route path="admin/settings" element={
                <RequirePerm perm="admin:setting"><AdminSettings /></RequirePerm>
              } />
              {/* ES9 任务十二：超管运维侧版本形态管理（页内二次门控 is_super_admin） */}
              <Route path="admin/edition-ops" element={
                <RequirePerm perm="admin:setting"><AdminEditionOps /></RequirePerm>
              } />
              <Route path="admin/ai-config" element={
                <RequirePerm perm="admin:setting"><AdminAiConfig /></RequirePerm>
              } />
              <Route path="admin/login-logs" element={
                <RequirePerm perm="admin:log"><AdminLoginLogs /></RequirePerm>
              } />

              <Route path="billing" element={<Commercial kind="billing"><Billing /></Commercial>} />
              {/* ES8 M1：租户自助订阅页（billing:read） */}
              <Route path="billing/subscription" element={
                <Commercial kind="billing" perm="billing:read"><PageSuspense><SubscriptionPage /></PageSuspense></Commercial>
              } />
              {/* ES8 M2：站内收银台（orders 属商业面，同 billing 门控） */}
              <Route path="billing/pay" element={
                <Commercial kind="billing" perm="billing:read"><PageSuspense><PaymentPage /></PageSuspense></Commercial>
              } />
              {/* /security 本体是 MFA/改密页（核心 /auth/* 端点），不属商业能力面 */}
              <Route path="security" element={<Security />} />
              {/* 越狱样本/PII 规则管理的数据面在 security_p0 商业路由（/jailbreak、/pii） */}
              <Route path="security/jailbreak-samples" element={
                <Commercial kind="security_assets" perm="admin:dict"><JailbreakSamples /></Commercial>
              } />
              <Route path="security/pii-rules" element={
                <Commercial kind="security_assets" perm="admin:dict"><PiiRules /></Commercial>
              } />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </EditionProvider>
  )
}
