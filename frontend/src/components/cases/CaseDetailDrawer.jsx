/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Drawer, Descriptions, Tag, Empty, Space, Collapse, Typography, Divider, Table, Button, Modal } from 'antd'
import { RobotOutlined } from '@ant-design/icons'
import { useState } from 'react'
import http from '../../api/http'
import { fmtTime } from '../../utils'
import { CASE_CATEGORY_MAP } from '../../constants/enums'

const { Text } = Typography

function JsonBlock({ value }) {
  if (value == null || value === '') return <Text type="secondary">-</Text>
  let text = value
  if (typeof value === 'object') {
    try { text = JSON.stringify(value, null, 2) } catch { text = String(value) }
  }
  return <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 12, color: '#cfd2da' }}>{String(text)}</pre>
}

function StatusTag({ status }) {
  const color = status === 'ACTIVE' ? 'green' : status === 'ARCHIVED' ? 'default' : 'orange'
  return <Tag color={color}>{status || 'ACTIVE'}</Tag>
}

// 渲染 last_actual（断言实际值摘要）
function LastActualBlock({ lastActual }) {
  if (!lastActual || typeof lastActual !== 'object') {
    return <Text type="secondary">暂无执行数据，执行一次任务后自动回填</Text>
  }
  const rows = Object.entries(lastActual).map(([k, v], idx) => ({
    key: idx,
    step: k,
    path: v?.path || '-',
    op: v?.op || '-',
    expected: v?.expected != null ? String(v.expected) : '-',
    actual: v?.actual != null ? String(v.actual) : '-',
    passed: v?.passed,
  }))
  if (rows.length === 0) return <Text type="secondary">暂无断言实际值</Text>
  const passedAll = rows.every((r) => r.passed)
  return (
    <Table
      size="small"
      pagination={false}
      dataSource={rows}
      columns={[
        { title: '步骤', dataIndex: 'step', width: 80 },
        { title: '断言路径', dataIndex: 'path', ellipsis: true },
        { title: '操作', dataIndex: 'op', width: 80 },
        { title: '预期值', dataIndex: 'expected', ellipsis: true },
        { title: '实际值', dataIndex: 'actual', ellipsis: true },
        {
          title: '结果', dataIndex: 'passed', width: 80,
          render: (v) => v === true ? <Tag color="green">PASS</Tag> : v === false ? <Tag color="red">FAIL</Tag> : <Tag>SKIP</Tag>,
        },
      ]}
      summary={() => (
        <Table.Summary fixed>
          <Table.Summary.Row>
            <Table.Summary.Cell index={0} colSpan={6}>
              <span style={{ fontSize: 12, color: passedAll ? '#52c41a' : '#ff4d4f' }}>
                本次执行{passedAll ? '全部通过' : '存在失败'}，共 {rows.length} 条断言实际值
              </span>
            </Table.Summary.Cell>
          </Table.Summary.Row>
        </Table.Summary>
      )}
    />
  )
}

export default function CaseDetailDrawer({ open, data, onClose, onAssertionsUpdated }) {
  const [aiLoading, setAiLoading] = useState(false)

  async function handleAIComplete() {
    if (!data?.id) return
    setAiLoading(true)
    try {
      const r = await http.post(`/cases/${data.id}/complete-assertions`)
      if (r?.has_existing) {
        Modal.info({ title: '已有断言', content: '该用例已有断言集，跳过补全。可手动编辑修改。' })
      } else if (r?.candidates?.length) {
        Modal.success({
          title: 'AI 断言候选',
          content: (
            <div style={{ maxHeight: 360, overflow: 'auto' }}>
              <div style={{ marginBottom: 8, color: '#888' }}>共 {r.candidates.length} 条候选断言，请在编辑器中确认后保存：</div>
              <pre style={{ background: '#0d1117', padding: 8, borderRadius: 4, color: '#c9d1d9', fontSize: 12 }}>
{JSON.stringify(r.candidates, null, 2)}
              </pre>
              <div style={{ marginTop: 8, color: '#888', fontSize: 12 }}>提示：AI 仅基于 request_spec + last_actual 生成基础断言，建议人工确认后保存。</div>
            </div>
          ),
        })
      } else {
        Modal.warning({ title: '无候选', content: '未生成可用断言候选，请手动添加。' })
      }
    } catch (e) { console.warn(e); Modal.error({ title: 'AI 补全失败', content: e?.message || '请稍后重试' }) } finally { setAiLoading(false) }
  }

  const title = data ? (
    <Space>
      <span>用例详情 - {data.case_no}</span>
      {(!data.assertions || data.assertions.length === 0) && (
        <Button size="small" icon={<RobotOutlined />} loading={aiLoading} onClick={handleAIComplete}>AI 补全断言</Button>
      )}
    </Space>
  ) : '用例详情'
  const items = []
  if (!data) {
    items.push({
      key: 'empty',
      label: '用例详情',
      children: <Empty description="暂无数据" />,
    })
  } else {
    // 前置条件
    const pre = (data.preconditions || []).length > 0
      ? data.preconditions.map((p, i) => `${i + 1}. [${p.kind || '-'}] ${p.desc || ''}`).join('\n')
      : (data.precondition || '')
    items.push({
      key: 'pre',
      label: '前置条件',
      children: pre ? <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 12, color: '#cfd2da' }}>{pre}</pre> : <Text type="secondary">-</Text>,
    })
    // 测试数据（数据驱动分组）
    items.push({
      key: 'data',
      label: `测试数据（${(data.test_data || []).length} 组）`,
      children: (data.test_data || []).length > 0
        ? <JsonBlock value={data.test_data} />
        : <Text type="secondary">无数据驱动分组</Text>,
    })
    // 步骤 / 请求 / 样本（按类别）
    let contentLabel = '内容'
    let contentVal = null
    const cat = data.category
    if (cat === 'UI') { contentLabel = '测试步骤'; contentVal = data.steps }
    else if (cat === 'API') { contentLabel = '接口请求'; contentVal = data.request_spec }
    else if (cat === 'PERFORMANCE') { contentLabel = '性能参数'; contentVal = data.request_spec }
    else if (cat === 'SECURITY') { contentLabel = '安全样本'; contentVal = data.security_samples || data.request_spec }
    else if (['HALLUCINATION', 'REDTEAM', 'RAG', 'ETHICS', 'MULTITURN', 'MULTI_TURN', 'EVAL'].includes(cat)) {
      contentLabel = '评测条目'; contentVal = data.eval_items || data.request_spec
    } else { contentLabel = '内容'; contentVal = data.steps || data.request_spec }
    items.push({
      key: 'content',
      label: contentLabel,
      children: <JsonBlock value={contentVal} />,
    })
    // 断言集
    items.push({
      key: 'assert',
      label: `断言集（${(data.assertions || []).length} 条）`,
      children: (data.assertions || []).length > 0
        ? <JsonBlock value={data.assertions} />
        : <Text type="secondary">无结构化断言</Text>,
    })
    // 后置清理
    items.push({
      key: 'cleanup',
      label: `后置清理（${(data.post_cleanup || []).length} 项）`,
      children: (data.post_cleanup || []).length > 0
        ? <JsonBlock value={data.post_cleanup} />
        : <Text type="secondary">无</Text>,
    })
    // 预期（旧字段说明）
    if (data.expected) {
      items.push({ key: 'expected', label: '预期结果（说明）', children: <Text>{data.expected}</Text> })
    }
    // P1-3：最近一次实际输出（断言实际值摘要）
    items.push({
      key: 'last_actual',
      label: `最近一次实际输出`,
      children: <LastActualBlock lastActual={data.last_actual} />,
    })
  }

  return (
    <Drawer
      title={title}
      open={open}
      onClose={onClose}
      width={760}
      destroyOnHidden
    >
      {data && (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="标题" span={2}>{data.title || '-'}</Descriptions.Item>
            <Descriptions.Item label="所属模块">{data.module || '-'}</Descriptions.Item>
            <Descriptions.Item label="类别"><Tag>{CASE_CATEGORY_MAP[data.category] || data.category}</Tag></Descriptions.Item>
            <Descriptions.Item label="状态"><StatusTag status={data.status} /></Descriptions.Item>
            <Descriptions.Item label="严重度">{data.severity || '-'}</Descriptions.Item>
            <Descriptions.Item label="优先级">{data.priority || '-'}</Descriptions.Item>
            <Descriptions.Item label="需求编号">{data.requirement_id || '-'}</Descriptions.Item>
            <Descriptions.Item label="执行次数">{data.run_count || 0}</Descriptions.Item>
            <Descriptions.Item label="通过率">{((data.pass_rate || 0) * 100).toFixed(1)}%</Descriptions.Item>
            <Descriptions.Item label="创建时间">{fmtTime(data.created_at)}</Descriptions.Item>
            <Descriptions.Item label="标签" span={2}>{(data.tags || []).join(' | ') || '-'}</Descriptions.Item>
          </Descriptions>
          <Divider style={{ margin: '4px 0' }} />
          <Collapse defaultActiveKey={['content', 'assert']} items={items} />
        </Space>
      )}
      {!data && <Empty description="请先选择用例" />}
    </Drawer>
  )
}