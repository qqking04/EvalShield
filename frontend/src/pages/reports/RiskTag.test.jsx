/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// RiskTag（方案 §2.3 RiskLevelBadge 的 React 实际对应物，BUG-02）
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { RiskTag } from './charts'

describe('RiskTag 风险等级标签', () => {
  it.each([
    ['critical', '严重风险'],
    ['high', '高风险'],
    ['medium', '中风险'],
    ['low', '低风险'],
    ['none', '无风险项'],
  ])('%s 渲染中文标签 %s', (level, label) => {
    render(<RiskTag level={level} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('未知等级回退为无风险项', () => {
    render(<RiskTag level="unknown" />)
    expect(screen.getByText('无风险项')).toBeInTheDocument()
  })

  it('空值回退为无风险项', () => {
    render(<RiskTag level={undefined} />)
    expect(screen.getByText('无风险项')).toBeInTheDocument()
  })
})
