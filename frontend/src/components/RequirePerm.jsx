/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Spin, Result } from 'antd'
import { useAuth } from '../auth'
import { useIsCommunity } from '../edition/EditionContext'
import UpgradeEmpty from './UpgradeEmpty'

// 权限守卫组件：需要登录 + 需要特定权限码（perm）+ 可选企业版门控（enterpriseOnly）
// + 可选商业能力门控（commercialOnly：saas/enterprise 可用，community 见升级引导）
export default function RequirePerm({ perm, enterpriseOnly, commercialOnly, upgradeKind, children }) {
  const { user, loading, hasPerm, licensed } = useAuth()
  const isCommunity = useIsCommunity()

  if (loading) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 120 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }
  if (!user) return children // 未登录场景由外层 RequireAuth 处理
  if (perm && !hasPerm(perm)) {
    return (
      <Result
        status="403"
        title="无权访问该页面"
        subTitle="当前账号缺少访问所需的权限，请联系空间管理员。"
      />
    )
  }
  // 版本门控与 MainLayout /license 菜单 enterpriseOnly 判定一致（TC-ROUTE-001）
  if (enterpriseOnly && !licensed) {
    return (
      <Result
        status="403"
        title="无权访问该页面"
        subTitle="该功能为企业版专属，当前部署未激活企业版 License。"
      />
    )
  }
  // 商业能力门控（方案 §4-F2）：入口保留不隐藏，社区版点击见价值对比而非 403。
  // 仅在明确探测到社区形态时降级；/api/edition 拉取失败（edition=null）不误伤，
  // 后端商业端点 404 + CommercialGate 兜底，双保险不白屏。
  if (commercialOnly && isCommunity) {
    return <UpgradeEmpty kind={upgradeKind} />
  }
  return children
}
