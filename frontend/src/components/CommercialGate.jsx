/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Component } from 'react'
import UpgradeEmpty from './UpgradeEmpty'

// 商业路由双保险（方案 §4-F-build）：
// 正常门控由 RequirePerm 完成；此边界兜底 lazy chunk 加载失败
// （OSS 构建已物理剔除商业模块、或 chunk 网络故障）→ 渲染 UpgradeEmpty。
class GateBoundary extends Component {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error) {
    // 保留控制台线索，便于区分「模块被剔除」与「运行时 Bug」
    console.warn('[commercial-gate] 商业模块加载失败，已降级为升级引导：', error?.message)
  }

  render() {
    if (this.state.failed) return <UpgradeEmpty kind={this.props.kind} />
    return this.props.children
  }
}

export default function CommercialGate({ kind, children }) {
  return (
    <GateBoundary key={kind} kind={kind}>
      {children}
    </GateBoundary>
  )
}
