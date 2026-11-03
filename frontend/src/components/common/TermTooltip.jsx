/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ===========================================================================
// TermTooltip：术语通俗化提示组件（P1-4）
// hover 或点击显示白话解释，降低非技术用户门槛
// ===========================================================================
import { Tooltip } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'

export default function TermTooltip({ term, explain, example, children }) {
  const text = (
    <span style={{ fontSize: 12, lineHeight: 1.6 }}>
      <b style={{ color: '#13c2c2' }}>{term}</b>
      <span style={{ color: 'rgba(255,255,255,0.85)' }}> = {explain}</span>
      {example && (
        <div style={{ marginTop: 6, color: 'rgba(255,255,255,0.65)' }}>示例：{example}</div>
      )}
    </span>
  )
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      {children}
      <Tooltip title={text} color="#1f2937" overlayInnerStyle={{ maxWidth: 360, padding: '10px 12px' }}>
        <QuestionCircleOutlined style={{ color: '#13c2c2', cursor: 'help', fontSize: 14 }} />
      </Tooltip>
    </span>
  )
}
