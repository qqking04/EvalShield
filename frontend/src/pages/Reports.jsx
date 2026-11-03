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
import { useSearchParams } from 'react-router-dom'
import { Space, Card, Tabs, Typography } from 'antd'
import { SafetyOutlined, FileProtectOutlined } from '@ant-design/icons'
import ReportsList from './reports/ReportsList'
import NotificationsList from './reports/NotificationsList'
import { useIsCommunity } from '../edition/EditionContext'
import UpgradeEmpty from '../components/UpgradeEmpty'
import CommercialGate from '../components/CommercialGate'
import { PageSuspense } from '../components/common/PageSuspense'

// F1 版本隔离：合规映射与 License 台账属商业模块（OSS 构建整目录剔除 + 说明符改写）
const ComplianceTab = lazy(() => import('./CommercialPlaceholder'))
const LicenseLedger = lazy(() => import('./CommercialPlaceholder'))

export default function Reports() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = searchParams.get('tab') || 'reports'
  const isCommunity = useIsCommunity()
  // 与 RequirePerm commercialOnly 同一判定：社区版 tab 入口保留，内容见升级引导
  const commercialTab = (kind, node) => (isCommunity ? (
    <UpgradeEmpty kind={kind} />
  ) : (
    <CommercialGate kind={kind}>
      <PageSuspense>{node}</PageSuspense>
    </CommercialGate>
  ))
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Title level={4} style={{ margin: 0 }}>报告中心</Typography.Title>
      <Card>
        <Tabs
          activeKey={tab}
          onChange={(k) => { setSearchParams({ tab: k }) }}
          items={[
            { key: 'reports', label: '测试报告', children: <ReportsList /> },
            { key: 'compliance', label: <span><SafetyOutlined /> 合规映射</span>, children: commercialTab('batch', <ComplianceTab />) },
            { key: 'license-ledger', label: <span><FileProtectOutlined /> License 台账</span>, children: commercialTab('license_ledger', <LicenseLedger />) },
            { key: 'notifs', label: '通知消息', children: <NotificationsList /> },
          ]}
        />
      </Card>
    </Space>
  )
}
