/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// BugDetailDrawer.jsx —— 缺陷详情抽屉（v2.0 BUG-007）
import { Drawer, Descriptions, Typography, Tag, Divider, Empty } from 'antd'
import { BugOutlined, UserOutlined, ToolOutlined, LinkOutlined } from '@ant-design/icons'

const { Text, Paragraph } = Typography

/**
 * 缺陷详情抽屉
 * @param {boolean} visible
 * @param {Function} onClose
 * @param {Object} bug - 缺陷对象（sections.bugs 项）
 */
export default function BugDetailDrawer({ visible, onClose, bug }) {
  if (!bug) return null

  // 严重度颜色（兼容中文 / P0-P4 / 英文枚举）
  const severityColor = (s) => {
    const key = String(s || '')
    const map = {
      '严重': '#cf1322', '高': '#ff4d4f', '中': '#fa8c16', '低': '#52c41a',
      P0: '#cf1322', CRITICAL: '#cf1322',
      P1: '#ff4d4f', HIGH: '#ff4d4f',
      P2: '#fa8c16', MEDIUM: '#fa8c16',
      P3: '#52c41a', P4: '#52c41a', LOW: '#52c41a',
    }
    return map[key] || map[key.toUpperCase()] || '#8c8c8c'
  }

  const priorityColor = (p) => {
    const map = { P0: '#cf1322', P1: '#ff4d4f', P2: '#fa8c16' }
    return map[String(p || '').toUpperCase()] || '#8c8c8c'
  }

  const statusColor = (s) => {
    const map = {
      NEW: 'default', OPEN: 'processing', FIXED: 'success', CLOSED: 'default',
      '新建': 'default', '处理中': 'processing', '已修复': 'success', '已关闭': 'default',
    }
    return map[s] || 'default'
  }

  return (
    <Drawer
      title={<span><BugOutlined /> 缺陷详情：{bug.defect_no || bug.bug_id || '-'}</span>}
      placement="right"
      width={640}
      open={visible}
      onClose={onClose}
    >
      <Descriptions bordered column={1} size="small">
        <Descriptions.Item label="标题">{bug.title || '-'}</Descriptions.Item>
        <Descriptions.Item label="严重度">
          <Tag color={severityColor(bug.severity)}>{bug.severity || '-'}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="优先级">
          <Tag color={priorityColor(bug.priority)}>{bug.priority || '-'}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={statusColor(bug.status)}>{bug.status || '-'}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="模块">{bug.module || '-'}</Descriptions.Item>
        <Descriptions.Item label="关联用例">{bug.case_id ?? '-'}</Descriptions.Item>
      </Descriptions>

      <Divider />

      {/* v2.0 新增字段 */}
      <Descriptions bordered column={1} size="small" title="专业化字段">
        <Descriptions.Item label={<span><UserOutlined /> 指派人</span>}>
          {bug.assignee || bug.assignee_name || <Text type="secondary">未指派</Text>}
        </Descriptions.Item>
        <Descriptions.Item label={<span><ToolOutlined /> 修复建议</span>}>
          <Paragraph style={{ margin: 0 }}>
            {bug.fix_suggestion || <Text type="secondary">暂无修复建议</Text>}
          </Paragraph>
        </Descriptions.Item>
        <Descriptions.Item label="定级依据">
          <Paragraph style={{ margin: 0 }}>
            {bug.severity_basis || <Text type="secondary">暂无定级依据</Text>}
          </Paragraph>
        </Descriptions.Item>
        <Descriptions.Item label={<span><LinkOutlined /> 关联需求号</span>}>
          {bug.requirement_id ? (
            <Tag color="blue">{bug.requirement_id}</Tag>
          ) : <Text type="secondary">未关联</Text>}
        </Descriptions.Item>
      </Descriptions>

      {/* 复现步骤 */}
      {bug.reproduce_steps && bug.reproduce_steps.length > 0 && (
        <>
          <Divider />
          <Text strong>复现步骤</Text>
          <div style={{ marginTop: 8 }}>
            {bug.reproduce_steps.map((step, i) => (
              <div key={i} style={{ padding: '4px 0', borderBottom: '1px solid #f0f0f0' }}>
                <Text strong>步骤 {step.no || i + 1}：</Text>
                <Text>{step.action || (typeof step === 'string' ? step : JSON.stringify(step))}</Text>
              </div>
            ))}
          </div>
        </>
      )}

      {/* 实际/期望结果 */}
      {(bug.actual || bug.expected) && (
        <>
          <Divider />
          <Descriptions bordered column={1} size="small">
            <Descriptions.Item label="实际结果">
              <Paragraph style={{ margin: 0, color: '#ff4d4f' }}>{bug.actual || '-'}</Paragraph>
            </Descriptions.Item>
            <Descriptions.Item label="预期结果">
              <Paragraph style={{ margin: 0, color: '#52c41a' }}>{bug.expected || '-'}</Paragraph>
            </Descriptions.Item>
          </Descriptions>
        </>
      )}

      {(!bug.reproduce_steps || bug.reproduce_steps.length === 0) && !bug.actual && !bug.expected && (
        <div style={{ marginTop: 12 }}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无更多明细" />
        </div>
      )}
    </Drawer>
  )
}
