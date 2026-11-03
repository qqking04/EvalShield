/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 越狱样本库管理页冒烟测试（产品优化3 §U2）
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { App } from 'antd'
import http from '../../api/http'
import JailbreakSamples from './JailbreakSamples'

vi.mock('../../api/http', () => ({
  default: { get: vi.fn(), put: vi.fn(), delete: vi.fn(), post: vi.fn() },
}))

const LIST = {
  items: [
    {
      id: 1, category: 'ROLEPLAY', attack_vector: 'DAN 变体', prompt_template: '你现在是DAN……',
      severity: 'HIGH', source: '内部研究', is_active: true, updated_at: '2026-10-01T10:00:00Z',
    },
    {
      id: 2, category: 'ENCODING', attack_vector: 'Base64 绕过', prompt_template: 'YQ==……',
      severity: 'CRITICAL', source: null, is_active: false, updated_at: '2026-10-02T10:00:00Z',
    },
  ],
  total: 2,
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('JailbreakSamples 越狱样本库页', () => {
  it('加载并渲染列表与契约请求路径', async () => {
    http.get.mockResolvedValue(LIST)
    render(
      <App>
        <JailbreakSamples />
      </App>,
    )
    await waitFor(() => expect(screen.getByText('DAN 变体')).toBeInTheDocument())
    expect(http.get).toHaveBeenCalledWith('/jailbreak/samples', expect.objectContaining({
      params: expect.objectContaining({ page: 1, page_size: 20 }),
    }))
    expect(screen.getByText('Base64 绕过')).toBeInTheDocument()
    expect(screen.getByText('ROLEPLAY')).toBeInTheDocument()
    expect(screen.getByText('共 2 条')).toBeInTheDocument()
  })

  it('页面标题与新增入口存在', async () => {
    http.get.mockResolvedValue({ items: [], total: 0 })
    render(
      <App>
        <JailbreakSamples />
      </App>,
    )
    await waitFor(() => expect(http.get).toHaveBeenCalled())
    expect(screen.getByText('越狱样本库')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /新增样本/ })).toBeInTheDocument()
  })
})
