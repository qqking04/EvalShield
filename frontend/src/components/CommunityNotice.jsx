/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Alert } from 'antd'
import { Link } from 'react-router-dom'
import { useIsCommunity, useEdition } from '../edition/EditionContext'

// ES9-P-02（§2.2.3）：社区形态首启一次性提示条，挂在 LicenseBanner 旁。
// 内容数据来自 EditionContext.limits；关闭状态记 localStorage 不再重复打扰。
const DISMISS_KEY = 'es_community_notice_done'

const LIMIT_LABEL = {
  projects_total: '项目 3 个',
  questions_total: '题库 500 题',
  eval_runs_month: '每月评测 20 次',
  users_total: '成员 5 人',
  concurrent_tasks: '并发任务 1 个',
}

export default function CommunityNotice() {
  const isCommunity = useIsCommunity()
  const { limits, loaded } = useEdition()
  // OBS-002：服务端 /api/edition 就绪前不渲染（默认隐藏），避免社区构建包
  // 部署在 saas 环境时按构建期默认值闪现「当前为社区版」横幅
  if (!loaded || !isCommunity || localStorage.getItem(DISMISS_KEY)) return null
  const limitText = Object.entries(limits || {})
    .filter(([k]) => LIMIT_LABEL[k])
    .map(([k, v]) => LIMIT_LABEL[k] + (typeof v === 'number' ? `（上限 ${v}）` : ''))
    .slice(0, 3)
    .join(' · ')
  return (
    <Alert
      type="info"
      showIcon
      closable
      banner
      onClose={() => {
        try { localStorage.setItem(DISMISS_KEY, '1') } catch { /* 隐私模式静默 */ }
      }}
      message={
        <span>
          当前为社区版{limitText ? `，限额：${limitText}` : ''}。
          <Link to="/edition-compare">查看各版本能力对比与升级方式</Link>
        </span>
      }
    />
  )
}
