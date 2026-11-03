/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// P1：合规结论章节（风险等级 + 违规项→法规映射 + 整改建议 + 盖章落款）
// 数据契约：report.content.compliance_conclusion（task_runner._build_compliance_conclusion）
import { Card, Tag, Table, Typography, Space, Descriptions, Divider, Empty, Tooltip } from 'antd'
import { SafetyCertificateOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import { MONO_FONT } from '../../theme'
import { ENGINE_NAME_MAP, SEVERITY_CN_MAP } from '../../constants/enums'

const mono = { fontFamily: MONO_FONT }

const RISK_META = {
  HIGH: { color: '#f5222d', text: '高风险' },
  MEDIUM: { color: '#faad14', text: '中风险' },
  LOW: { color: '#8db600', text: '低风险' },
  // 审计惯用语（对齐 ISO 27001 / 等保 / TC260「符合 / 基本符合 / 不符合」口径），避免裸「合规通过」被误读
  NONE: { color: '#13c2c2', text: '未发现不符合项（基本符合）' },
}

const SEV_COLOR = { CRITICAL: '#f5222d', MAJOR: '#fa541c', HIGH: '#fa541c', MODERATE: '#faad14', MEDIUM: '#faad14', MINOR: '#8db600' }

export default function ComplianceConclusion({ conclusion }) {
  if (!conclusion) return null
  const risk = RISK_META[conclusion.risk_level] || RISK_META.NONE
  const violations = conclusion.violations || []
  const sig = conclusion.signature || {}

  return (
    <Card
      size="small"
      title={(
        <Space>
          <SafetyCertificateOutlined style={{ color: risk.color }} />
          <span>合规结论</span>
          <Tag style={{ background: risk.color, color: '#0a0d12', fontWeight: 600, border: 'none' }}>{risk.text}</Tag>
        </Space>
      )}
      style={{ border: `1px solid ${risk.color}55`, boxShadow: `0 0 10px ${risk.color}22` }}
    >
      <Descriptions size="small" column={2} style={{ marginBottom: 12 }}>
        <Descriptions.Item label={(
          <Space size={4}>
            合规认定（法规符合性）
            <Tooltip title="本认定仅针对监管法规违规项（如生成违法违规内容、数据合规缺陷），采用「符合 / 基本符合 / 不符合」审计口径；与报告整体风险等级（基于用例通过率与失败严重度）口径不同，二者可以同时成立。">
              <QuestionCircleOutlined style={{ color: 'rgba(255,255,255,0.45)' }} />
            </Tooltip>
          </Space>
        )}>
          <span style={{ color: risk.color, fontWeight: 700 }}>{risk.text}</span>
        </Descriptions.Item>
        <Descriptions.Item label="违规项数量">
          <span style={{ ...mono, color: violations.length ? '#fa541c' : '#13c2c2', fontWeight: 700 }}>{conclusion.violation_count ?? violations.length}</span>
        </Descriptions.Item>
      </Descriptions>
      {violations.length === 0 && (
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
          说明：本次执行在合规映射范围内未发现监管法规不符合项（基本符合）；第三章「风险发现等级」为测试发现项定位，不构成违规定性；若报告整体风险等级为中/高风险，属于测试质量或功能缺陷层面问题，不代表存在合规违规。
        </Typography.Paragraph>
      )}

      {violations.length > 0 && (
        <>
          <Typography.Title level={5} style={{ marginTop: 0 }}>违规项与关联法规</Typography.Title>
          <Table
            size="small"
            rowKey={(_, i) => i}
            pagination={{ pageSize: 8, showSizeChanger: false }}
            dataSource={violations}
            columns={[
              { title: '来源引擎', dataIndex: 'source_engine', width: 130, render: (v) => <Tag>{ENGINE_NAME_MAP[v] || v || '-'}</Tag> },
              { title: '用例', dataIndex: 'item_no', width: 100, render: (v) => <span style={mono}>{v || '-'}</span> },
              {
                title: '严重度', dataIndex: 'severity', width: 100,
                render: (v) => <Tag style={{ background: SEV_COLOR[v] || '#8c8c8c', color: '#0a0d12', fontWeight: 600, border: 'none' }}>{SEVERITY_CN_MAP[v] || v || '-'}</Tag>,
              },
              { title: '风险类别', dataIndex: 'risk_category_cn', width: 130, render: (v, r) => v || r.risk_category || '-' },
              { title: '说明', dataIndex: 'description', ellipsis: true },
            ]}
            expandable={{
              rowExpandable: (r) => (r.regulations || []).length > 0,
              expandedRowRender: (r) => (
                <Table
                  size="small" rowKey={(_, i) => i} pagination={false}
                  dataSource={r.regulations || []}
                  columns={[
                    { title: '法规名称', dataIndex: 'regulation_name', width: 260 },
                    { title: '条文编号', dataIndex: 'article_number', width: 110, render: (v) => <span style={mono}>{v}</span> },
                    { title: '条文内容', dataIndex: 'article_content', ellipsis: true },
                    { title: '违反后果', dataIndex: 'violation_consequence', ellipsis: true, width: 220 },
                  ]}
                />
              ),
            }}
          />
        </>
      )}

      {(conclusion.remediation_suggestions || []).length > 0 && (
        <>
          <Typography.Title level={5}>整改建议</Typography.Title>
          <ol style={{ paddingLeft: 20, margin: 0 }}>
            {conclusion.remediation_suggestions.map((s, i) => (
              <li key={i} style={{ marginBottom: 6, color: 'rgba(255,255,255,0.85)' }}>{s}</li>
            ))}
          </ol>
        </>
      )}

      <Divider style={{ margin: '16px 0 8px' }} />
      <div style={{ textAlign: 'right', color: 'rgba(255,255,255,0.65)', fontSize: 13, lineHeight: 2 }}>
        <div>编制人：<span style={{ ...mono, color: '#e6ebf0' }}>{sig.prepared_by || '__________'}</span></div>
        <div>审核人：<span style={{ ...mono, color: '#e6ebf0' }}>{sig.reviewed_by || '__________'}</span></div>
        <div>日期：<span style={{ ...mono, color: '#e6ebf0' }}>{sig.date || '__________'}</span></div>
        <div
          style={{
            display: 'inline-block', marginTop: 8, padding: '6px 18px',
            border: '2px solid #f5222d66', color: '#f5222d99', borderRadius: 4,
            fontSize: 12, letterSpacing: 2, transform: 'rotate(-6deg)',
          }}
        >
          {sig.stamp || '（盖章位）'}
        </div>
      </div>
      {violations.length === 0 && (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未发现监管法规不符合项" style={{ marginTop: 8 }} />
      )}
    </Card>
  )
}
