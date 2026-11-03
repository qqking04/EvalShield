/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// FailureLogPanel.jsx —— 失败日志完整展示面板（v2.0 BUG-006）
// 说明：方案文档的 Collapse.Panel 写法在 antd 5.22 已废弃，此处统一改 items API
import { useState } from 'react'
import { Collapse, Typography, Tag, Descriptions, Button, Empty } from 'antd'
import { CodeOutlined, ExpandOutlined, CompressOutlined } from '@ant-design/icons'

const { Text } = Typography

/**
 * 失败日志完整展示面板
 * @param {Object} failureDetail - 后端 sections.failures[].failure_detail 对象
 */
export default function FailureLogPanel({ failureDetail }) {
  const [expanded, setExpanded] = useState(false)

  if (!failureDetail) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无失败明细" />
  }

  const {
    assertion,
    failures = [],
    http_status,
    request = {},
    response = {},
    traceback,
    trace_id,
    request_id,
    timestamp,
    log_lines = [],
    response_preview,
  } = failureDetail

  const statusColor = (code) => {
    if (!code) return 'default'
    if (code < 300) return 'green'
    if (code < 400) return 'blue'
    if (code < 500) return 'orange'
    return 'red'
  }

  const truncate = (text, maxLen = 500) => {
    if (!text) return ''
    const str = String(text)
    if (expanded || str.length <= maxLen) return str
    return `${str.slice(0, maxLen)}\n... (共 ${str.length} 字符，点击"展开"查看完整内容)`
  }

  const asText = (v) => {
    if (v === null || v === undefined) return ''
    if (typeof v === 'string') return v
    try { return JSON.stringify(v, null, 2) } catch { return String(v) }
  }

  const assertionText = assertion || (Array.isArray(failures) && failures.length ? failures.map((f) => String(f)).join('\n') : '') || '-'

  const collapseItems = [
    {
      key: 'req',
      label: <span><CodeOutlined /> 请求详情</span>,
      children: (
        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="Method"><Tag>{request.method || '-'}</Tag></Descriptions.Item>
          <Descriptions.Item label="URL"><Text copyable>{request.url || '-'}</Text></Descriptions.Item>
          <Descriptions.Item label="Headers">
            <pre style={{ margin: 0, fontSize: 12, maxHeight: 200, overflow: 'auto' }}>
              {asText(request.headers) || '-'}
            </pre>
          </Descriptions.Item>
          <Descriptions.Item label="Body">
            <pre style={{ margin: 0, fontSize: 12, maxHeight: 300, overflow: 'auto' }}>
              {truncate(asText(request.body)) || '-'}
            </pre>
          </Descriptions.Item>
        </Descriptions>
      ),
    },
    {
      key: 'resp',
      label: <span><CodeOutlined /> 响应详情（完整）</span>,
      children: (
        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="Status">
            <Tag color={statusColor(response.status || http_status)}>{response.status || http_status || '-'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Headers">
            <pre style={{ margin: 0, fontSize: 12, maxHeight: 200, overflow: 'auto' }}>
              {asText(response.headers) || '-'}
            </pre>
          </Descriptions.Item>
          <Descriptions.Item label="Body（完整响应体）">
            <Button
              size="small"
              type="link"
              icon={expanded ? <CompressOutlined /> : <ExpandOutlined />}
              onClick={() => setExpanded(!expanded)}
              style={{ marginBottom: 4, padding: 0 }}
            >
              {expanded ? '收起' : '展开'}
            </Button>
            <pre style={{
              margin: 0,
              fontSize: 12,
              maxHeight: expanded ? 'none' : 400,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            }}>
              {truncate(asText(response.body || response_preview), 10000) || '-'}
            </pre>
          </Descriptions.Item>
        </Descriptions>
      ),
    },
  ]

  if (traceback) {
    collapseItems.push({
      key: 'tb',
      label: <span><CodeOutlined style={{ color: '#ff4d4f' }} /> 异常堆栈</span>,
      children: (
        <pre style={{
          margin: 0, fontSize: 12, color: '#ff4d4f', background: '#fff1f0',
          padding: 12, borderRadius: 4, maxHeight: 400, overflow: 'auto', whiteSpace: 'pre-wrap',
        }}>
          {traceback}
        </pre>
      ),
    })
  }

  if (log_lines.length > 0) {
    collapseItems.push({
      key: 'log',
      label: <span><CodeOutlined /> 执行日志（{log_lines.length} 行）</span>,
      children: (
        <pre style={{
          margin: 0, fontSize: 11, background: '#f5f5f5',
          padding: 12, borderRadius: 4, maxHeight: 400, overflow: 'auto',
        }}>
          {log_lines.join('\n')}
        </pre>
      ),
    })
  }

  return (
    <div style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }}>
      <Descriptions bordered size="small" column={2} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="HTTP 状态码">
          <Tag color={statusColor(http_status || response.status)}>{http_status || response.status || '-'}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="断言/失败项">
          <pre style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap' }}>{assertionText}</pre>
        </Descriptions.Item>
        <Descriptions.Item label="trace_id"><Text copyable code>{trace_id || '-'}</Text></Descriptions.Item>
        <Descriptions.Item label="request_id"><Text copyable code>{request_id || '-'}</Text></Descriptions.Item>
        <Descriptions.Item label="时间戳" span={2}>{timestamp || '-'}</Descriptions.Item>
      </Descriptions>

      <Collapse size="small" defaultActiveKey={[]} ghost items={collapseItems} />
    </div>
  )
}
