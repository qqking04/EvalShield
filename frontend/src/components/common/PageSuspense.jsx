/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Suspense } from 'react'
import { Spin } from 'antd'

// 路由级按需加载骨架（App.jsx 与商业 tab 共用，避免循环依赖）
export function PageSuspense({ children }) {
  return (
    <Suspense
      fallback={
        <div style={{ textAlign: 'center', paddingTop: 120 }}>
          <Spin size="large" tip="页面加载中...">
            <div style={{ minHeight: 80, minWidth: 80 }} />
          </Spin>
        </div>
      }
    >
      {children}
    </Suspense>
  )
}

export default PageSuspense
