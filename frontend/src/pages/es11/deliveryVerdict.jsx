/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES11 P10：上线建议四态 + 可嵌入的「交付就绪区」。
// ReportDelivery（完整工作台）与 ReportDetail（顶部就绪区）共用同一派生逻辑，
// 保证两处口径一致：先给上线建议，再给 G4 阻塞清单，修复入口直达。
import { useEffect, useState } from 'react'
import { Alert, Button, Card, Space, Spin, Typography } from 'antd'
import {
  CheckCircleFilled, ExclamationCircleFilled, FileProtectOutlined,
  QuestionCircleFilled, StopFilled,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import * as es11 from '../../api/es11'
import { ES, GateChecklist } from './gate'

// 上线建议（P10 首屏）：据 deliverable + concluded + freeze 派生四态
export function verdictOf(r) {
  if (!r) return null
  if (r.run_id == null) {
    return { label: '证据不足', color: ES.sub, icon: <QuestionCircleFilled />, desc: '报告未关联评测运行，无法执行 G4 交付判定；请先关联运行或从运行侧生成报告' }
  }
  if (!r.deliverable || (r.checklist || []).some((c) => c.status === 'BLOCK')) {
    return { label: '不可交付', color: ES.BLOCK, icon: <StopFilled />, desc: 'G4 存在阻塞项，逐条点击修复入口处理后重新判定' }
  }
  if (r.freeze) {
    return { label: '可交付', color: ES.PASS, icon: <CheckCircleFilled />, desc: 'G4 全项通过且结论已冻结，可生成正式交付包对外交付' }
  }
  return {
    label: '有条件通过', color: ES.WARN, icon: <ExclamationCircleFilled />,
    desc: r.concluded
      ? 'G4 检查通过，但结论尚未冻结；冻结后方可出具正式交付包'
      : 'G4 检查通过，但运行结论未达成（复核未完成或运行未到终态），且结论未冻结',
  }
}

/**
 * 交付就绪区（嵌入 ReportDetail 顶部）：
 * 加载 delivery-readiness → 上线建议四态 + G4 阻塞项（直达修复页）+ 工作台入口。
 */
export function DeliveryReadinessSection({ reportId }) {
  const navigate = useNavigate()
  const [rd, setRd] = useState(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!reportId) return
    let cancelled = false
    setLoading(true)
    setFailed(false)
    es11.getDeliveryReadiness(reportId)
      .then((d) => { if (!cancelled) setRd(d) })
      .catch(() => { if (!cancelled) { setRd(null); setFailed(true) } })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [reportId])

  if (loading) {
    return (
      <Card size="small">
        <Space><Spin size="small" /><Typography.Text type="secondary">交付就绪（G4）数据加载中…</Typography.Text></Space>
      </Card>
    )
  }
  if (failed) {
    return (
      <Alert
        type="info" showIcon
        message="交付就绪数据暂不可用"
        description="无法获取 G4 交付判定数据；可稍后在交付工作台重试。"
        action={<Button size="small" onClick={() => navigate(`/reports/${reportId}/delivery`)}>打开交付工作台</Button>}
      />
    )
  }

  const verdict = verdictOf(rd)
  const blocked = (rd?.checklist || []).filter((c) => c.status === 'BLOCK')

  return (
    <Card
      size="small"
      title={<Space><FileProtectOutlined />交付就绪（G4）</Space>}
      extra={(
        <Space size={8}>
          {rd?.run_id != null && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>关联运行 {rd.run_no || `#${rd.run_id}`}</Typography.Text>
          )}
          <Button size="small" type="primary" ghost onClick={() => navigate(`/reports/${reportId}/delivery`)}>
            交付工作台
          </Button>
        </Space>
      )}
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        {verdict && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 26, lineHeight: 1, color: verdict.color }}>{verdict.icon}</span>
            <div>
              <Typography.Text style={{ color: verdict.color, fontSize: 17, fontWeight: 700 }}>
                {verdict.label}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 13, marginLeft: 10 }}>{verdict.desc}</Typography.Text>
            </div>
          </div>
        )}
        {rd?.run_id == null && (
          <Alert
            type="warning" showIcon
            message="报告未关联评测运行，证据链不完整"
            description="G4 判定依赖运行证据；请从运行侧生成报告，或前往运行列表核对。"
            action={<Button size="small" onClick={() => navigate('/eval')}>查看运行</Button>}
          />
        )}
        {blocked.length > 0 && (
          <div>
            <Typography.Text strong style={{ fontSize: 13 }}>阻塞项（{blocked.length}）</Typography.Text>
            <GateChecklist checks={blocked} onAction={(a) => a?.path && navigate(a.path)} />
          </div>
        )}
      </Space>
    </Card>
  )
}
