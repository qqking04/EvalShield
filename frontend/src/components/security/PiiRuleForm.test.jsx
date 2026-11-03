/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// PiiRuleForm 回归测试（BUG-001 / BUG-010）
// BUG-001：antd import 缺 Space → 试算面板渲染崩溃（Space is not defined）
// BUG-010：validateFields 在 try 外 → 必填留空提交产生 unhandled rejection
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import http from '../../api/http'
import PiiRuleForm from './PiiRuleForm'

vi.mock('../../api/http', () => ({
  default: { get: vi.fn(), put: vi.fn(), delete: vi.fn(), post: vi.fn() },
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PiiRuleForm（BUG-001/BUG-010 回归）', () => {
  it('正常渲染；试算命中后脱敏 Tag 区（Space）不再崩溃', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    render(
      <PiiRuleForm open editing={null} onClose={() => {}} onSaved={() => {}} />,
    )
    expect(screen.getByText('新增 PII 规则')).toBeInTheDocument()

    // 正则串含 {} ，userEvent.type 会解析为按键描述符，改用 paste 原样输入
    const patternBox = screen.getByPlaceholderText(/^如：1\[3-9\]/)
    await user.click(patternBox)
    await user.paste('1[3-9]\\d{9}')
    const sampleBox = screen.getByPlaceholderText(/我的手机号是/)
    await user.click(sampleBox)
    await user.paste('联系我：13812345678')
    // antd 两字按钮自动插空格（试 算），用正则匹配
    await user.click(screen.getByRole('button', { name: /试\s*算/ }))

    await waitFor(() => expect(screen.getByText(/命中 1 处（已脱敏）/)).toBeInTheDocument())
    // 脱敏展示：不允许回显完整明文
    expect(screen.getByText('13*******78')).toBeInTheDocument()
    expect(screen.queryByText('13812345678')).not.toBeInTheDocument()
  })

  it('必填留空提交：不产生 unhandledrejection（BUG-010）', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const rejections = []
    const onRejection = (e) => rejections.push(e.reason)
    window.addEventListener('unhandledrejection', onRejection)
    try {
      render(
        <PiiRuleForm open editing={null} onClose={() => {}} onSaved={() => {}} />,
      )
      // rule_name / regex_pattern 留空，直接点「保存」
      await user.click(screen.getByRole('button', { name: '保 存' }))
      // 校验红字出现，且未发起任何保存请求
      await waitFor(() => expect(screen.getByText('规则名称不能为空')).toBeInTheDocument())
      expect(screen.getByText('正则表达式不能为空')).toBeInTheDocument()
      expect(http.post).not.toHaveBeenCalled()
      // 等一个宏任务让潜在的 rejection 冒泡
      await new Promise((r) => setTimeout(r, 0))
      expect(rejections).toHaveLength(0)
    } finally {
      window.removeEventListener('unhandledrejection', onRejection)
    }
  })
})
