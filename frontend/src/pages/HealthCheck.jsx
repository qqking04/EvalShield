/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// v2.0 P4：部署卫生检查面板（Docker 容器 / 端口 / 数据库 / 实跑任务）
// ES9 §3.1.3/§3.2.3/§3.4.3：沙箱 worker 池状态、口令治理组、传输安全组（deploy-check）
import { useEffect, useState } from 'react'
import { Card, List, Tag, Button, Alert, Space, App, Typography, Table, Descriptions, Row, Col } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, WarningOutlined, ReloadOutlined } from '@ant-design/icons'
import http from '../api/http'

const STATUS_COLOR = { PASS: 'success', FAIL: 'error', WARN: 'warning' }
const WORKER_STATUS_COLOR = { IDLE: 'green', BUSY: 'blue', DRAINING: 'orange', DEAD: 'red' }

function StatusIcon({ status }) {
  if (status === 'PASS') return <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 18 }} />
  if (status === 'FAIL') return <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 18 }} />
  return <WarningOutlined style={{ color: '#faad14', fontSize: 18 }} />
}

// deploy-check 的分组检查项渲染：404（后端未启用）时显示"未启用"占位
function CheckGroup({ title, items, disabled }) {
  if (disabled) {
    return (
      <Card size="small" title={title}>
        <Alert type="info" showIcon message="未启用" description="后端未提供该项检查接口（/api/health/deploy-check）。" />
      </Card>
    )
  }
  if (!items) {
    return (
      <Card size="small" title={title}>
        <Typography.Text type="secondary">点击「运行检查」后加载</Typography.Text>
      </Card>
    )
  }
  return (
    <Card size="small" title={title}>
      <List
        size="small"
        dataSource={items}
        locale={{ emptyText: '无检查项' }}
        renderItem={(item) => (
          <List.Item>
            <List.Item.Meta
              avatar={<StatusIcon status={item.status} />}
              title={item.name}
              description={item.message}
            />
            <Tag color={STATUS_COLOR[item.status] || 'default'}>{item.status}</Tag>
          </List.Item>
        )}
      />
    </Card>
  )
}

export default function HealthCheck() {
  const { message } = App.useApp()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [pool, setPool] = useState(null) // GET /sandbox/pool/status
  const [poolMissing, setPoolMissing] = useState(false)
  const [deploy, setDeploy] = useState(null) // GET /health/deploy-check
  const [deployMissing, setDeployMissing] = useState(false)

  const loadPool = async () => {
    try {
      // pool 模式未启用是预期状态（页面有"未启用"降级 UI），静默探测避免全局报错 toast
      const d = await http.get('/sandbox/pool/status', { silent: true })
      setPool(d)
      setPoolMissing(false)
    } catch (e) {
      // silent 模式下拦截器透传原始错误：404=pool 模式未启用（legacy docker 模式）
      if (e?.status === 404 || e?.response?.status === 404) setPoolMissing(true)
      else setPoolMissing(false)
      setPool(null)
    }
  }

  const loadDeploy = async () => {
    try {
      const d = await http.get('/health/deploy-check', { silent: true })
      setDeploy(d)
      setDeployMissing(false)
    } catch (e) {
      if (e?.status === 404 || e?.response?.status === 404) setDeployMissing(true)
      else setDeployMissing(false)
      setDeploy(null)
    }
  }

  useEffect(() => { loadPool(); loadDeploy() }, [])

  const runCheck = async () => {
    setLoading(true)
    try {
      const [d] = await Promise.all([
        http.get('/health/check'),
        loadPool(),
        loadDeploy(),
      ])
      setData(d)
      if (d.healthy) message.success('健康检查通过，可以演示')
      else message.warning('健康检查未通过，请修复后重试')
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title="部署卫生检查"
        extra={
          <Space>
            {data && (
              <Typography.Text type={data.healthy ? 'success' : 'warning'}>{data.summary}</Typography.Text>
            )}
            <Button type="primary" icon={<ReloadOutlined />} loading={loading} onClick={runCheck}>运行检查</Button>
          </Space>
        }
      >
        {!data && (
          <Alert
            type="info"
            showIcon
            message="点击「运行检查」逐项验证部署状态"
            description="检查项：Docker 容器（本机服务模式为 WARN 可忽略）、端口 5432/8000/11434/8891、数据库连通、最近实跑任务、沙箱 worker 池、口令治理与传输安全。全部通过（无 FAIL）即可演示。"
          />
        )}
        {data && (
          <List
            dataSource={data.checks}
            renderItem={(item) => (
              <List.Item>
                <List.Item.Meta
                  avatar={<StatusIcon status={item.status} />}
                  title={item.name}
                  description={item.message}
                />
                <Tag color={STATUS_COLOR[item.status] || 'default'}>{item.status}</Tag>
              </List.Item>
            )}
          />
        )}
      </Card>

      {/* ES9-P-03（§3.1.3）：沙箱 worker 池状态，部署验收截图用 */}
      <Card
        size="small"
        title="沙箱 worker 池"
        extra={<Button size="small" icon={<ReloadOutlined />} onClick={loadPool}>刷新</Button>}
      >
        {poolMissing ? (
          <Alert type="info" showIcon message="未启用" description="pool 模式未启用（legacy docker 模式），无 worker 池状态接口。" />
        ) : pool ? (
          <>
            <Descriptions size="small" column={4} style={{ marginBottom: 12 }}>
              <Descriptions.Item title="模式">{pool.mode || 'pool'}</Descriptions.Item>
              <Descriptions.Item title="worker 总数">{pool.workers?.length ?? 0}</Descriptions.Item>
              <Descriptions.Item title="在线">{(pool.workers || []).filter((w) => w.status !== 'DEAD').length}</Descriptions.Item>
              <Descriptions.Item title="在跑任务">{(pool.workers || []).reduce((s, w) => s + (w.current_tasks ?? 0), 0)}</Descriptions.Item>
            </Descriptions>
            <Table
              rowKey={(w) => w.worker_id || w.id}
              size="small"
              pagination={false}
              dataSource={pool.workers || []}
              locale={{ emptyText: '无 worker 实例' }}
              columns={[
                { title: 'worker id', dataIndex: 'worker_id', render: (v, r) => v || r.id },
                {
                  title: '状态', dataIndex: 'status', width: 100,
                  render: (v) => <Tag color={WORKER_STATUS_COLOR[v] || 'default'}>{v}</Tag>,
                },
                { title: '当前任务数', dataIndex: 'current_tasks', width: 110, render: (v) => v ?? 0 },
                {
                  title: '内存水位', dataIndex: 'mem_mb', width: 120,
                  render: (v, r) => (v != null ? `${v} MB${r.mem_limit_mb ? ` / ${r.mem_limit_mb} MB` : ''}` : '-'),
                },
              ]}
            />
            {Array.isArray(pool.hardening) && pool.hardening.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>加固项（只读）：</Typography.Text>
                <Space size={4} wrap style={{ marginLeft: 8 }}>
                  {pool.hardening.map((h) => <Tag key={typeof h === 'string' ? h : h.name} color="geekblue">{typeof h === 'string' ? h : h.name}</Tag>)}
                </Space>
              </div>
            )}
          </>
        ) : (
          <Typography.Text type="secondary">点击「运行检查」后加载</Typography.Text>
        )}
      </Card>

      {/* ES9-P-04/P-06（§3.2.3/§3.4.3）：口令治理 + 传输安全（deploy-check 合并接口） */}
      <Row gutter={16}>
        <Col span={12}>
          <CheckGroup title="口令治理" items={deploy?.password?.checks || deploy?.password} disabled={deployMissing} />
        </Col>
        <Col span={12}>
          <CheckGroup title="传输安全" items={deploy?.transport?.checks || deploy?.transport} disabled={deployMissing} />
        </Col>
      </Row>
      {deploy && !deployMissing && deploy.transport?.protocol && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          当前协议：{deploy.transport.protocol}
          {deploy.transport.rate_limiter ? ` · 限流器：${deploy.transport.rate_limiter}` : ''}
        </Typography.Text>
      )}
    </Space>
  )
}
