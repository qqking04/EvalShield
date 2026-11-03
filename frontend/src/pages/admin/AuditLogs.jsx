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
import { Table, Card, Space, Tag, Input, Select, Button, Typography, DatePicker, Modal, Descriptions, Badge } from 'antd'
import { ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { fmtTime } from '../../utils'

const { RangePicker } = DatePicker

const ACTION_MAP = {
  'project.create': '创建项目',
  'project.update': '更新项目',
  'project.delete': '删除项目',
  'task.create': '创建任务',
  'task.update': '更新任务',
  'task.run': '执行任务',
  'task.cancel': '取消任务',
  'task.delete': '删除任务',
  'case.create': '创建用例',
  'case.update': '更新用例',
  'case.delete': '删除用例',
  'case.read': '查看用例',
  'report.read': '查看报告',
  'report.export': '导出报告',
  'report.share': '分享报告',
  'user.create': '创建用户',
  'user.update': '更新用户',
  'user.reset_password': '重置密码',
  'user.delete': '删除用户',
  'role.create': '创建角色',
  'role.update': '更新角色',
  'auth.login': '登录',
  'auth.logout': '登出',
  'api.test': 'API 测试',
}

export default function AdminAuditLogs() {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({})
  const [verifyOpen, setVerifyOpen] = useState(false)
  const [verifyResult, setVerifyResult] = useState(null)
  const [verifyLoading, setVerifyLoading] = useState(false)

  const load = async (p = page, f = filters) => {
    setLoading(true)
    try {
      const params = { page: p, page_size: 10 }
      if (f.action) params.action = f.action
      if (f.module) params.module = f.module
      if (f.result) params.result = f.result
      if (f.range && f.range[0] && f.range[1]) {
        params.start_time = f.range[0].startOf('day').toISOString()
        params.end_time = f.range[1].endOf('day').toISOString()
      }
      const d = await http.get('/admin/audit-logs', { params })
      setRows(d.items || [])
      setTotal(d.total || 0)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load(1)
  }, [])

  const handleVerify = async () => {
    setVerifyLoading(true)
    try {
      const d = await http.get('/admin/audit-logs/verify')
      setVerifyResult(d)
      setVerifyOpen(true)
    } catch (e) {
      Modal.error({ title: '校验链检查失败', content: e?.message || '无法连接校验链服务' })
    } finally {
      setVerifyLoading(false)
    }
  }

  const columns = [
    { title: '日志编号', dataIndex: 'log_no', width: 180 },
    { title: '操作人', dataIndex: 'username', width: 120, render: (v) => v || '-' },
    { title: '动作', dataIndex: 'action', width: 170, render: (v) => <Tag>{ACTION_MAP[v] || v}</Tag> },
    { title: '模块', dataIndex: 'module', width: 110, render: (v) => <Tag color="blue">{v}</Tag> },
    { title: '请求', dataIndex: 'path', ellipsis: true, render: (v) => v || '-' },
    { title: '方法', dataIndex: 'method', width: 80 },
    { title: '结果', dataIndex: 'result', width: 100, render: (v) => <Tag color={v === 'SUCCESS' ? 'green' : 'red'}>{v}</Tag> },
    { title: 'IP', dataIndex: 'ip', width: 130, render: (v) => v || '-' },
    { title: '耗时', dataIndex: 'duration_ms', width: 90, render: (v) => (v != null ? `${v}ms` : '-') },
    { title: '时间', dataIndex: 'created_at', width: 170, render: (v) => fmtTime(v) },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>审计日志</Typography.Title>
        <Space>
          <Button icon={<SafetyCertificateOutlined />} loading={verifyLoading} onClick={handleVerify}>校验链</Button>
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
        </Space>
      </div>
      <Space wrap>
        <Input placeholder="动作，如 project.create" style={{ width: 200 }} allowClear onChange={(e) => setFilters((f) => ({ ...f, action: e.target.value }))} />
        <Input placeholder="模块，如 auth" style={{ width: 160 }} allowClear onChange={(e) => setFilters((f) => ({ ...f, module: e.target.value }))} />
        <Select
          placeholder="结果"
          allowClear
          style={{ width: 120 }}
          options={[{ value: 'SUCCESS', label: '成功' }, { value: 'FAILED', label: '失败' }]}
          onChange={(v) => setFilters((f) => ({ ...f, result: v }))}
        />
        <RangePicker onChange={(r) => setFilters((f) => ({ ...f, range: r }))} />
        <Button type="primary" onClick={() => { setPage(1); load(1, filters) }}>查询</Button>
      </Space>
      <Card>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={rows}
          size="small"
          scroll={{ x: 'max-content' }}
          pagination={{ current: page, total, pageSize: 10, showTotal: (t) => `共 ${t} 条`, onChange: (p) => { setPage(p); load(p) } }}
        />
      </Card>
      <Modal
        title={<Space><SafetyCertificateOutlined />SHA-256 审计链校验结果</Space>}
        open={verifyOpen}
        onCancel={() => setVerifyOpen(false)}
        footer={[<Button key="close" onClick={() => setVerifyOpen(false)}>关闭</Button>]}
        width={640}
      >
        {verifyResult && (
          <Descriptions bordered column={1} size="small">
            <Descriptions.Item label="校验链启用">
              <Badge status={verifyResult.enabled ? 'success' : 'default'} text={verifyResult.enabled ? '已启用' : '未启用'} />
            </Descriptions.Item>
            <Descriptions.Item label="完整性校验">
              <Badge status={verifyResult.valid ? 'success' : 'error'} text={verifyResult.valid ? '✓ 完整未篡改' : '✗ 发现断裂'} />
            </Descriptions.Item>
            <Descriptions.Item label="日志总数">{verifyResult.total ?? '-'}</Descriptions.Item>
            {verifyResult.breaks && verifyResult.breaks.length > 0 && (
              <Descriptions.Item label="断裂位置">
                <div style={{ color: '#ff4d4f' }}>{verifyResult.breaks.join(', ')}</div>
              </Descriptions.Item>
            )}
            {verifyResult.missing_indices && verifyResult.missing_indices.length > 0 && (
              <Descriptions.Item label="缺失索引">
                <div style={{ color: '#faad14' }}>{verifyResult.missing_indices.join(', ')}</div>
              </Descriptions.Item>
            )}
            <Descriptions.Item label="索引范围">
              {verifyResult.first_index ?? '-'}{verifyResult.last_index ? ` → ${verifyResult.last_index}` : ''}
            </Descriptions.Item>
            {verifyResult.enabled && verifyResult.valid && (
              <Descriptions.Item label="校验结论">
                <span style={{ color: '#52c41a', fontWeight: 600 }}>审计日志完整性验证通过，SHA-256 链未被篡改</span>
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Modal>
    </Space>
  )
}