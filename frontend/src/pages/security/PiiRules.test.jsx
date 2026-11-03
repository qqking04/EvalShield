/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// PII 规则库管理页冒烟测试（产品优化3 §U2）
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { App } from 'antd'
import http from '../../api/http'
import PiiRules from './PiiRules'

vi.mock('../../api/http', () => ({
  default: { get: vi.fn(), put: vi.fn(), delete: vi.fn(), post: vi.fn() },
}))

const LIST = {
  items: [
    {
      id: 1, pii_type: 'ID_CARD', rule_name: '身份证号（18 位）', regex_pattern: '\\d{17}[\\dXx]',
      severity: 'CRITICAL', is_active: true, updated_at: '2026-10-01T10:00:00Z',
    },
    {
      id: 2, pii_type: 'PHONE', rule_name: '手机号', regex_pattern: '1[3-9]\\d{9}',
      severity: 'HIGH', is_active: false, updated_at: '2026-10-02T10:00:00Z',
    },
  ],
  total: 2,
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PiiRules PII 规则库页', () => {
  it('加载并渲染列表与契约请求路径', async () => {
    http.get.mockResolvedValue(LIST)
    render(
      <App>
        <PiiRules />
      </App>,
    )
    await waitFor(() => expect(screen.getByText('身份证号（18 位）')).toBeInTheDocument())
    expect(http.get).toHaveBeenCalledWith('/pii/rules', expect.objectContaining({
      params: expect.objectContaining({ page: 1, page_size: 20 }),
    }))
    expect(screen.getByText('手机号')).toBeInTheDocument()
    expect(screen.getByText('ID_CARD')).toBeInTheDocument()
    expect(screen.getByText('共 2 条')).toBeInTheDocument()
  })

  it('页面标题与新增/试算入口存在', async () => {
    http.get.mockResolvedValue({ items: [], total: 0 })
    render(
      <App>
        <PiiRules />
      </App>,
    )
    await waitFor(() => expect(http.get).toHaveBeenCalled())
    expect(screen.getByText('PII 规则库')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /新增规则/ })).toBeInTheDocument()
  })
})
