/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ReproductionSteps.jsx —— 复现步骤展示（v2.0 BUG-004）
import { Steps, Tag, Typography, Empty } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'

const { Text, Paragraph } = Typography

/**
 * 复现步骤展示组件
 * @param {Object} reproduction - {case_id, probability, occurrence, steps: [{no, action, expected, actual}]}
 */
export default function ReproductionSteps({ reproduction }) {
  if (!reproduction || !reproduction.steps || reproduction.steps.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无复现步骤" />
  }

  const { probability, occurrence, steps } = reproduction
  const probColor = probability === '必现' ? '#ff4d4f' : '#fa8c16'

  return (
    <div style={{ padding: '8px 0' }}>
      <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 12 }}>
        <Text strong>复现概率：</Text>
        <Tag color={probColor}>{probability || '未知'}</Tag>
        {occurrence && <Text type="secondary">（{occurrence}）</Text>}
      </div>

      <Steps
        direction="vertical"
        size="small"
        current={steps.length}
        items={steps.map((step) => {
          const ok = step.actual === step.expected
          return {
            title: (
              <div>
                <Text strong>步骤 {step.no}：</Text>
                <Text>{step.action}</Text>
              </div>
            ),
            description: (
              <div style={{ marginTop: 4 }}>
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  <div style={{ flex: 1, minWidth: 200 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>预期结果：</Text>
                    <Paragraph style={{ margin: 0, fontSize: 13 }}>{step.expected || '-'}</Paragraph>
                  </div>
                  <div style={{ flex: 1, minWidth: 200 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>实际结果：</Text>
                    <Paragraph style={{ margin: 0, fontSize: 13, color: ok ? '#52c41a' : '#ff4d4f' }}>
                      {step.actual || '-'}
                      {ok
                        ? <CheckCircleOutlined style={{ marginLeft: 4, color: '#52c41a' }} />
                        : <CloseCircleOutlined style={{ marginLeft: 4, color: '#ff4d4f' }} />}
                    </Paragraph>
                  </div>
                </div>
              </div>
            ),
            status: ok ? 'finish' : 'error',
          }
        })}
      />
    </div>
  )
}
