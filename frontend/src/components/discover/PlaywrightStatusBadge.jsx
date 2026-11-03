/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { C, STATUS_COLOR, STAGE_LABEL, MONO } from './consoleTheme'

// 接管状态徽标：常驻右上角，WAITING_HUMAN 高亮（FC-08）
export default function PlaywrightStatusBadge({ job }) {
  if (!job) return null
  const s = job.status
  const cls =
    s === 'WAITING_HUMAN' ? 'waiting'
      : s === 'FAILED' ? 'failed'
        : s === 'CANCELLED' ? 'cancelled'
          : s === 'CONFIRMED' ? '' : 'running'
  const label =
    s === 'WAITING_HUMAN' ? '⏸ 待人工输入'
      : s === 'FAILED' ? '✗ 已失败'
        : s === 'CANCELLED' ? '⊘ 已取消'
          : s === 'CONFIRMED' ? '✓ 已入库'
            : s === 'PREVIEW' ? '◈ 待确认入库' : `▶ ${STAGE_LABEL[s] || s}`
  return (
    <div className={`disc-badge ${cls}`}>
      <span style={{ fontFamily: MONO }}>{label}</span>
      <span style={{ marginLeft: 8, color: C.dim }}>{job.job_no}</span>
    </div>
  )
}
