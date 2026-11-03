/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// RequirePerm 三层判定回归（测试方案 F8：!hasPerm / enterpriseOnly 未激活 / 全通过）
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import RequirePerm from './RequirePerm'

vi.mock('../auth', () => ({
  useAuth: vi.fn(),
}))
vi.mock('../edition/EditionContext', () => ({
  useIsCommunity: vi.fn(),
}))
vi.mock('./UpgradeEmpty', () => ({
  default: ({ kind }) => <div data-testid="upgrade-empty">{kind}</div>,
}))

import { useAuth } from '../auth'
import { useIsCommunity } from '../edition/EditionContext'

function setAuth({ perm = true, licensed = true, user = { id: 1 } } = {}) {
  useAuth.mockReturnValue({
    user,
    loading: false,
    licensed,
    hasPerm: () => perm,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  useIsCommunity.mockReturnValue(false)
})

describe('RequirePerm 三层判定', () => {
  it('缺少权限 → 403（NoPerm）', () => {
    setAuth({ perm: false })
    render(
      <RequirePerm perm="task:create">
        <div>PAGE</div>
      </RequirePerm>,
    )
    expect(screen.getByText('无权访问该页面')).toBeInTheDocument()
    expect(screen.queryByText('PAGE')).not.toBeInTheDocument()
  })

  it('enterpriseOnly 且未激活 License → 403 企业版专属', () => {
    setAuth({ licensed: false })
    render(
      <RequirePerm enterpriseOnly>
        <div>PAGE</div>
      </RequirePerm>,
    )
    expect(screen.getByText(/企业版专属/)).toBeInTheDocument()
    expect(screen.queryByText('PAGE')).not.toBeInTheDocument()
  })

  it('commercialOnly 且社区形态 → UpgradeEmpty', () => {
    setAuth()
    useIsCommunity.mockReturnValue(true)
    render(
      <RequirePerm commercialOnly upgradeKind="cost">
        <div>PAGE</div>
      </RequirePerm>,
    )
    expect(screen.getByTestId('upgrade-empty')).toBeInTheDocument()
    expect(screen.getByText('cost')).toBeInTheDocument()
    expect(screen.queryByText('PAGE')).not.toBeInTheDocument()
  })

  it('全通过 → 渲染 children', () => {
    setAuth()
    render(
      <RequirePerm perm="task:create" commercialOnly upgradeKind="cost">
        <div>PAGE</div>
      </RequirePerm>,
    )
    expect(screen.getByText('PAGE')).toBeInTheDocument()
    expect(screen.queryByTestId('upgrade-empty')).not.toBeInTheDocument()
  })

  it('/api/edition 探测失败（isCommunity=false 保守值）不误伤商业页', () => {
    setAuth()
    useIsCommunity.mockReturnValue(false)
    render(
      <RequirePerm commercialOnly upgradeKind="cost">
        <div>PAGE</div>
      </RequirePerm>,
    )
    expect(screen.getByText('PAGE')).toBeInTheDocument()
  })
})
