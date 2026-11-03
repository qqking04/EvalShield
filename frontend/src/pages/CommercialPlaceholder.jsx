/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import UpgradeEmpty from '../components/UpgradeEmpty'

// OSS 社区构建占位模块（scripts/strip_fe.js 的改写目标）：
// 社区构建已物理删除 src/pages/commercial/，App.jsx / Reports.jsx /
// ReportDetail.jsx 中被剔除的 import 说明符统一改写指向本文件，
// 保证构建零错且入口渲染升级引导而非白屏。
export default function CommercialPlaceholder() {
  return <UpgradeEmpty />
}
