/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Descriptions, Table, Tag, Space, Button, App, Typography, Progress, Collapse, Empty, Spin, Modal, Drawer,
} from 'antd'
import { ArrowLeftOutlined, PlayCircleOutlined, StopOutlined, LinkOutlined } from '@ant-design/icons'
import http from '../api/http'
import { fmtTime, TASK_STATUS_MAP, TASK_STATUS_COLOR, STEP_STATUS_COLOR, fmtDuration, toScorePercent } from '../utils'

export default function TaskDetail() {
  const { id } = useParams() // id 为任务内部主键（页面展示统一用业务编号 task_no）
  const navigate = useNavigate()
  const [task, setTask] = useState(null)
  const [loading, setLoading] = useState(true)
  const [evalRuns, setEvalRuns] = useState([])
  const { message } = App.useApp()
  const pollTimer = useRef(null)

  const stopPolling = () => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current)
      pollTimer.current = null
    }
  }

  const load = async () => {
    setLoading(true)
    try {
      const data = await http.get(`/tasks/${id}`)
      setTask(data)
      const isActive = data.status === 'RUNNING' || data.status === 'PENDING'
      if (isActive && !pollTimer.current) {
        pollTimer.current = setInterval(load, 3000)
      } else if (!isActive) {
        stopPolling()
      }
    } finally {
      setLoading(false)
    }
    // R2-13: 加载关联评测运行（AI 引擎执行后自动创建的 EvalRun）
    try {
      const er = await http.get('/eval-runs', { params: { task_id: id, page: 1, page_size: 20 } })
      setEvalRuns(er.items || [])
    } catch (e) {
      console.warn('[TaskDetail] 关联评测运行加载失败', e?.message || e)
      setEvalRuns([])
    }
  }

  useEffect(() => {
    load()
    return stopPolling
  }, [id])

  const runTask = async () => {
    try {
      const data = await http.post(`/tasks/${task.id}/run`, {})
      message.success((data && data.message) || '任务已提交，后台执行中')
      load()
    } catch {
      /* 错误已由拦截器提示 */
    }
  }

  const cancelTask = async () => {
    Modal.confirm({
      title: '确认取消该任务？',
      content: '取消后将停止后续引擎步骤执行，已完成的步骤结果保留，操作会写入审计日志。',
      okText: '确认取消',
      cancelText: '保留任务',
      okButtonProps: { danger: true },
      onOk: async () => {
        await http.post(`/tasks/${task.id}/cancel`)
        message.success('任务已取消')
        load()
      },
    })
  }

  const stepColumns = [
    { title: '步骤', dataIndex: 'seq', width: 60, align: 'center' },
    { title: '步骤编号', dataIndex: 'step_no', width: 200 },
    { title: '引擎', dataIndex: 'engine_code', width: 160, render: (v, r) => <Space direction="vertical" size={0}><Tag>{v}</Tag><Typography.Text type="secondary" style={{ fontSize: 12 }}>{r.engine_name}</Typography.Text></Space> },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (v) => <Tag color={STEP_STATUS_COLOR[v]}>{TASK_STATUS_MAP[v] || v}</Tag>,
    },
    { title: '耗时', dataIndex: 'duration_ms', width: 100, render: (v) => fmtDuration(v) },
    { title: '错误信息', dataIndex: 'error_msg', ellipsis: true, render: (v) => v || '-' },
    {
      title: '执行概要',
      dataIndex: 'result_summary',
      render: (v) =>
        v ? (
          <Typography.Paragraph style={{ margin: 0 }} ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}>
            {typeof v === 'string' ? v : JSON.stringify(v)}
          </Typography.Paragraph>
        ) : (
          '-'
        ),
    },
  ]

  if (loading || !task) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 120 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  const summary = task.summary || {}

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Space>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/tasks')}>返回</Button>
        <Typography.Title level={4} style={{ margin: 0 }}>任务详情 - {task.task_no}</Typography.Title>
        <Tag color={TASK_STATUS_COLOR[task.status]}>{TASK_STATUS_MAP[task.status] || task.status}</Tag>
        {task.status === 'RUNNING' && <Progress percent={task.progress} style={{ width: 160 }} size="small" />}
      </Space>
      <Card>
        <Descriptions column={3} size="small" bordered>
          <Descriptions.Item label="任务名称">{task.name}</Descriptions.Item>
          <Descriptions.Item label="所属项目">{task.project_code || '-'}</Descriptions.Item>
          <Descriptions.Item label="触发方式">{task.trigger_mode === 'SCHEDULED' ? '定时执行' : '手动执行'}</Descriptions.Item>
          <Descriptions.Item label="下次执行">{task.next_run_at ? fmtTime(task.next_run_at) : '-'}</Descriptions.Item>
          {task.trigger_mode === 'SCHEDULED' && <Descriptions.Item label="Cron 表达式">{task.schedule_cron || '-'}</Descriptions.Item>}
          <Descriptions.Item label="创建人">{task.created_by_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{fmtTime(task.created_at)}</Descriptions.Item>
          <Descriptions.Item label="耗时">{fmtDuration(task.duration_ms)}</Descriptions.Item>
          <Descriptions.Item label="错误信息" span={3}>{task.error_msg || '无'}</Descriptions.Item>
          {task.status === 'COMPLETED_WITH_RISK' && (
            <Descriptions.Item label="业务结论" span={3}>
              <Typography.Text type="warning">{task.conclusion || '质量未达标'}</Typography.Text>
            </Descriptions.Item>
          )}
        </Descriptions>
        <Space style={{ marginTop: 16 }}>
          <Button type="primary" icon={<PlayCircleOutlined />} disabled={task.status === 'RUNNING'} onClick={runTask}>
            重新执行
          </Button>
          {task.status === 'RUNNING' && (
            <Button danger icon={<StopOutlined />} onClick={cancelTask}>取消任务</Button>
          )}
        </Space>
      </Card>
      <Card title={`执行步骤（${(task.steps || []).length}）`}>
        {summary.total !== undefined && (
          <Typography.Paragraph>
            <Tag color="blue">用例总数：{summary.total}</Tag>
            <Tag color="green">通过：{summary.passed}</Tag>
            <Tag color="red">失败：{summary.failed}</Tag>
            <Tag color="purple">通过率：{((summary.pass_rate || 0) * 100).toFixed(2)}%</Tag>
          </Typography.Paragraph>
        )}
        <Table rowKey="id" size="small" columns={stepColumns} dataSource={task.steps || []} scroll={{ x: 'max-content' }} pagination={false} />
        {summary.step_results && summary.step_results.length > 0 && (
          <Collapse
            style={{ marginTop: 16 }}
            items={summary.step_results.map((s, i) => ({
              key: i,
              label: `${s.engine}：${s.conclusion || '详见步骤表'}`,
              children: (
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 12, background: '#f6f8fa', padding: 8, borderRadius: 4 }}>
                  {JSON.stringify(s.summary, null, 2)}
                </pre>
              ),
            }))}
          />
        )}
      </Card>
      {/* R2-13: 关联评测运行（AI 引擎执行后自动创建，打通任务侧与评测中心双入口） */}
      <Card
        title={
          <Space>
            <span>关联评测运行（{evalRuns.length}）</span>
            <Tag color="geekblue">AI 引擎自动创建</Tag>
          </Space>
        }
        extra={<Button type="link" icon={<LinkOutlined />} onClick={() => navigate('/eval?tab=runs')}>前往评测中心</Button>}
      >
        {evalRuns.length === 0 ? (
          <Empty description="该任务未关联评测运行（非 AI 引擎或未执行）" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={evalRuns}
            columns={[
              { title: '运行编号', dataIndex: 'run_no', width: 180, render: (v, r) => <a onClick={() => navigate(`/eval?tab=runs&run=${r.id}${task.project_id ? `&project=${task.project_id}` : ''}`)}>{v}</a> },
              { title: '评测集', dataIndex: 'eval_set_code', width: 160, render: (v) => v || '-' },
              { title: '状态', dataIndex: 'status', width: 100, render: (v) => <Tag color={v === 'SUCCESS' ? 'green' : v === 'FAILED' ? 'red' : 'blue'}>{v}</Tag> },
              { title: '评分', dataIndex: 'overall_score', width: 100, render: (v) => { const p = toScorePercent(v); return p != null ? `${p.toFixed(1)}` : '-' } },
              { title: '结论', dataIndex: 'verdict', width: 90, render: (v) => v ? <Tag color={v === 'PASS' ? 'green' : 'red'}>{v}</Tag> : '-' },
              { title: '耗时', dataIndex: 'duration_ms', width: 100, render: (v) => fmtDuration(v) },
              { title: '创建时间', dataIndex: 'created_at', width: 180, render: (v) => fmtTime(v) },
              { title: '操作', width: 100, render: (_, r) => <a onClick={() => navigate(`/eval?tab=runs&run=${r.id}${task.project_id ? `&project=${task.project_id}` : ''}`)}>查看详情</a> },
            ]}
          />
        )}
      </Card>
    </Space>
  )
}