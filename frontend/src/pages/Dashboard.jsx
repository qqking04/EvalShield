/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Table, Tag, Progress, Space, Typography, Button } from 'antd'
import {
  ProjectOutlined,
  ExperimentOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  FileTextOutlined,
  ImportOutlined,
  CloudServerOutlined,
  RightOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import http from '../api/http'
import { fmtTime } from '../utils'
import { TASK_STATUS_MAP, TASK_STATUS_COLOR, ENGINE_NAME_MAP, ENGINE_TYPE_MAP } from '../constants/enums'

// 优化7 T7-7a：空库首屏引导三卡片（图标+一句话，直链动作路由；禁插画）
const EMPTY_GUIDES = [
  {
    key: 'project',
    icon: <ProjectOutlined style={{ fontSize: 28, color: '#165DFF' }} />,
    title: '创建项目',
    desc: '创建项目，围绕被测 AI 系统组织用例、环境与任务。',
    path: '/projects',
    cta: '去创建项目',
  },
  {
    key: 'cases',
    icon: <ImportOutlined style={{ fontSize: 28, color: '#165DFF' }} />,
    title: '导入用例库',
    desc: '从文档批量导入测试用例，或手工/使用 AI 生成用例。',
    path: '/documents/import',
    cta: '去导入用例',
  },
  {
    key: 'model',
    icon: <CloudServerOutlined style={{ fontSize: 28, color: '#165DFF' }} />,
    title: '配置模型网关',
    desc: '接入被测模型 API 与评测打分模型，任务执行依赖网关。',
    path: '/models',
    cta: '去配置网关',
  },
]

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    http.get('/dashboard/stats').then((d) => setStats(d?.items || d)).catch((e) => console.warn('[Dashboard]', e?.message || e))
  }, [])

  // 优化7 T7-7a：加载完成且项目/任务/用例全为 0 → 新装空库，渲染引导首屏
  const isEmpty =
    stats != null &&
    (stats?.project_total ?? 0) === 0 &&
    (stats?.task_total ?? 0) === 0 &&
    (stats?.case_total ?? 0) === 0

  const columns = [
    { title: '任务编号', dataIndex: 'task_no', width: 220 },
    { title: '任务名称', dataIndex: 'name', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (v) => <Tag color={TASK_STATUS_COLOR[v]}>{TASK_STATUS_MAP[v] || v}</Tag>,
    },
    { title: '进度', dataIndex: 'progress', width: 140, render: (v) => <Progress percent={v} size="small" /> },
    { title: '执行时间', dataIndex: 'created_at', width: 170, render: (v) => fmtTime(v) },
  ]

  if (isEmpty) {
    return (
      <Space direction="vertical" size={24} style={{ width: '100%' }}>
        <div style={{ textAlign: 'center', paddingTop: 48 }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            欢迎使用 EvalShield
          </Typography.Title>
          <Typography.Text type="secondary">
            系统尚未有任何数据，按下面三步开始搭建你的第一个评测环境。
          </Typography.Text>
        </div>
        <Row gutter={16} justify="center">
          {EMPTY_GUIDES.map((g) => (
            <Col key={g.key} xs={24} sm={24} md={8}>
              <Card hoverable onClick={() => navigate(g.path)} style={{ height: '100%' }}>
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  {g.icon}
                  <Typography.Text strong style={{ fontSize: 16 }}>
                    {g.title}
                  </Typography.Text>
                  <Typography.Text type="secondary">{g.desc}</Typography.Text>
                  <Button type="link" style={{ paddingLeft: 0 }} onClick={(e) => { e.stopPropagation(); navigate(g.path) }}>
                    {g.cta} <RightOutlined />
                  </Button>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      </Space>
    )
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Title level={4} style={{ margin: 0 }}>
        仪表盘
      </Typography.Title>
      <Row gutter={16}>
        <Col span={6}>
          <Card>
            <Statistic title="项目总数" value={stats?.project_total ?? '-'} prefix={<ProjectOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="任务总数" value={stats?.task_total ?? '-'} prefix={<ExperimentOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="运行中任务" value={stats?.task_running ?? '-'} prefix={<PlayCircleOutlined />} valueStyle={{ color: '#cf1322' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="成功任务" value={stats?.task_success ?? '-'} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#3f8600' }} />
          </Card>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={8}>
          <Card title="引擎类型分布">
            {(stats?.engine_stats || []).map((e) => (
              <div key={e.engine_type} style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Tag color="cyan">{ENGINE_TYPE_MAP[e.engine_type] || e.engine_type}</Tag>
                <Typography.Text>{e.count} 个引擎</Typography.Text>
              </div>
            ))}
            {(!stats?.engine_stats || stats.engine_stats.length === 0) && (
              <Typography.Text type="secondary">暂无引擎数据</Typography.Text>
            )}
          </Card>
        </Col>
        <Col span={16}>
          <Card
            title="最近执行任务"
            extra={<Statistic title="用例总数" value={stats?.case_total ?? '-'} prefix={<FileTextOutlined />} valueStyle={{ fontSize: 16 }} />}
          >
            <Table
              rowKey="id"
              size="small"
              columns={columns}
              dataSource={stats?.recent_tasks || []}
              scroll={{ x: 'max-content' }}
              pagination={false}
            />
          </Card>
        </Col>
      </Row>
    </Space>
  )
}