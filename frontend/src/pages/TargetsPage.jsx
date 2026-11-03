/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES9（§2.1.3）导航收敛：一级入口「被测系统」独立页面（/targets）
// 组装 被测系统注册 + 知识源（ES9-P-12）双子 Tab；模型网关配置页（/models）保留同源能力。
import { Space, Tabs, Typography } from 'antd'
import { useSearchParams } from 'react-router-dom'
import TargetRegistryTab from './eval/TargetRegistryTab'
import FactSourcesTab from './eval/FactSourcesTab'

export default function TargetsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const valid = ['targets', 'fact-sources']
  const active = valid.includes(searchParams.get('tab')) ? searchParams.get('tab') : 'targets'
  const onTabChange = (k) => {
    const np = new URLSearchParams(searchParams)
    np.set('tab', k)
    setSearchParams(np, { replace: true })
  }
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Title level={4} style={{ margin: 0 }}>被测系统</Typography.Title>
      <Tabs
        activeKey={active}
        onChange={onTabChange}
        items={[
          { key: 'targets', label: '被测系统注册', children: <TargetRegistryTab /> },
          { key: 'fact-sources', label: '知识源', children: <FactSourcesTab /> },
        ]}
      />
    </Space>
  )
}
