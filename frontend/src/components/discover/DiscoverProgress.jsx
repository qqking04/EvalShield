/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Steps } from 'antd'
import {
  LoginOutlined,
  ApiOutlined,
  FileTextOutlined,
  SafetyOutlined,
  CheckSquareOutlined,
} from '@ant-design/icons'
import { C, STATUS_COLOR, STAGE_LABEL, MONO } from './consoleTheme'

const ORDER = ['LOGINNING', 'DISCOVERING', 'GENERATING', 'VALIDATE', 'PREVIEW']
const ICONS = [LoginOutlined, ApiOutlined, FileTextOutlined, SafetyOutlined, CheckSquareOutlined]

// 阶段进度：Stepper + cyan 流光进度条（FC-07）
export default function DiscoverProgress({ job }) {
  if (!job) return null
  const status = job.status
  const pct = job.progress_pct || 0
  let current = ORDER.indexOf(status)
  if (status === 'FAILED') current = Math.max(0, ORDER.indexOf(job.error_stage) >= 0 ? 0 : current)
  if (status === 'CONFIRMED') current = ORDER.length
  if (status === 'CANCELLED') current = Math.max(0, current)

  return (
    <div>
      <Steps
        size="small"
        current={current < 0 ? 0 : current}
        status={
          status === 'FAILED' || status === 'CANCELLED' ? 'error'
            : status === 'CONFIRMED' || status === 'PREVIEW' ? 'finish' : 'process'
        }
        items={ORDER.map((s, i) => ({
          title: (
            <span style={{ color: current >= i ? C.text : C.dim, fontSize: 12 }}>
              {STAGE_LABEL[s]}
            </span>
          ),
          icon: status === 'WAITING_HUMAN' && ORDER[i] === 'LOGINNING' ? null : undefined,
        }))}
      />
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
        <div className="disc-bar" style={{ flex: 1 }}>
          <div className="disc-bar-inner" style={{ width: `${Math.max(3, pct)}%` }} />
        </div>
        <span className="disc-mono" style={{ color: STATUS_COLOR[status] || C.dim, fontSize: 12, minWidth: 150, textAlign: 'right' }}>
          {STAGE_LABEL[status] || status} · {pct}%
        </span>
      </div>
      {status === 'WAITING_HUMAN' && (
        <div className="disc-mono" style={{ color: C.amber, fontSize: 12, marginTop: 8 }}>
          ⚠ 检测到人机验证，请在弹窗中完成输入（超时 {300}s 自动失败）
        </div>
      )}
      {status === 'FAILED' && job.error_message && (
        <div className="disc-mono" style={{ color: C.red, fontSize: 12, marginTop: 8 }}>
          ✗ {job.error_message}
        </div>
      )}
      {status === 'CANCELLED' && (
        <div className="disc-mono" style={{ color: C.gray, fontSize: 12, marginTop: 8 }}>
          ⊘ 任务已取消，探测流程已停止
        </div>
      )}
    </div>
  )
}
