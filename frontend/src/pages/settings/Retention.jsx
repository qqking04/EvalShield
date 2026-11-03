/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES8 M12：数据保留与注销（策略 CRUD + 注销并匿名化入口，仅 saas 形态展示）
import { useState, useEffect, useCallback } from 'react'
import {
  App, Button, Card, Form, Input, InputNumber, Modal, Popconfirm,
  Select, Space, Table, Tag, Typography,
} from 'antd'
import { PlusOutlined, ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { tokens } from '../../theme/tokens'
import { useEdition } from '../../edition/EditionContext'

// 数据类型中文标签（audit_logs 受合规保护，后端硬拒配置）
const TYPE_LABEL = {
  traces: '在线评测轨迹',
  runs: '评测运行',
  recordings: '录制脚本',
  attachments: '任务附件',
  audit_logs: '审计日志',
}
const ACTION_LABEL = {
  delete: '物理删除',
  archive_ref: '归档引用',
}

function PolicyTab() {
  const { message } = App.useApp()
  const [rows, setRows] = useState([])
  const [types, setTypes] = useState([])
  const [actions, setActions] = useState([])
  const [loading, setLoading] = useState(false)
  const [modal, setModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await http.get('/retention/policies')
      setRows(d?.items || [])
      setTypes(d?.artifact_types || [])
      setActions(d?.purge_actions || ['delete', 'archive_ref'])
    } catch (err) { console.warn('[Retention] policies load fail', err) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const open = (row) => {
    setEditing(row || {}); setModal(true)
    form.resetFields()
    if (row) form.setFieldsValue({
      artifact_type: row.artifact_type, days: row.days,
      purge_action: row.purge_action, archive_ref: row.archive_ref,
    })
  }

  const save = async () => {
    const v = await form.validateFields()
    const body = {
      artifact_type: v.artifact_type,
      days: v.days,
      purge_action: v.purge_action,
      archive_ref: v.archive_ref || null,
    }
    setSaving(true)
    try {
      if (editing?.id) await http.put(`/retention/policies/${editing.id}`, body)
      else await http.post('/retention/policies', body)
      message.success('已保存')
      setModal(false); setEditing(null); load()
    } catch (err) { console.warn('[Retention] save policy fail', err) }
    finally { setSaving(false) }
  }

  const purgeAction = Form.useWatch('purge_action', form)

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => open(null)}>新建策略</Button>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <Typography.Text style={{ color: tokens.text3 }}>
          过期数据每日自动清理，每轮每策略至多 5000 行；审计日志受合规保护，不可配置清理。
        </Typography.Text>
      </Space>
      <Table
        rowKey="id" size="small" loading={loading} dataSource={rows} pagination={false}
        columns={[
          {
            title: '数据类型', dataIndex: 'artifact_type',
            render: (v) => <Tag color="cyan">{TYPE_LABEL[v] || v}</Tag>,
          },
          { title: '保留天数', dataIndex: 'days', width: 100, render: (v) => `${v} 天` },
          {
            title: '清理动作', dataIndex: 'purge_action', width: 120,
            render: (v) => <Tag color={v === 'archive_ref' ? 'geekblue' : 'red'}>{ACTION_LABEL[v] || v}</Tag>,
          },
          {
            title: '归档引用', dataIndex: 'archive_ref', ellipsis: true,
            render: (v) => v || <span style={{ color: tokens.text3 }}>—</span>,
          },
          {
            title: '更新时间', dataIndex: 'updated_at', width: 170,
            render: (v) => <span style={{ color: tokens.text3, fontSize: 12 }}>{String(v || '').replace('T', ' ').slice(0, 19)}</span>,
          },
          {
            title: '操作', key: 'op', width: 120,
            render: (_, row) => (
              <Space>
                <Button size="small" type="link" onClick={() => open(row)}>编辑</Button>
                <Popconfirm
                  title="删除该保留策略？"
                  onConfirm={async () => {
                    await http.delete(`/retention/policies/${row.id}`)
                    message.success('已删除'); load()
                  }}
                >
                  <Button size="small" type="link" danger>删除</Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        open={modal} title={editing?.id ? '编辑保留策略' : '新建保留策略'}
        onCancel={() => { setModal(false); setEditing(null) }}
        onOk={save} okText="保存" confirmLoading={saving} destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ days: 90, purge_action: 'delete' }}>
          <Form.Item name="artifact_type" label="数据类型" rules={[{ required: true, message: '请选择数据类型' }]}>
            <Select
              disabled={!!editing?.id}
              placeholder="选择要配置保留期的数据类型"
              options={types.map((t) => ({
                value: t,
                label: `${TYPE_LABEL[t] || t}（${t}）`,
                // audit_logs 受合规保护：选项展示但禁选（后端 ES8-RET-0002 硬拒兜底）
                disabled: t === 'audit_logs',
              }))}
            />
          </Form.Item>
          <Form.Item
            name="days" label="保留天数"
            extra="超过该天数的数据将在每日清理任务中处理（至少 1 天）"
            rules={[{ required: true, message: '请输入保留天数' }]}
          >
            <InputNumber min={1} max={36500} style={{ width: '100%' }} addonAfter="天" />
          </Form.Item>
          <Form.Item name="purge_action" label="清理动作" rules={[{ required: true }]}>
            <Select
              options={actions.map((a) => ({
                value: a,
                label: a === 'archive_ref'
                  ? '归档引用（可软删的数据打归档标记，其余等价物理删除）'
                  : '物理删除（直接清除过期行）',
              }))}
            />
          </Form.Item>
          {purgeAction === 'archive_ref' && (
            <Form.Item name="archive_ref" label="归档引用" extra="如对象存储桶/归档系统标识，留空仅打归档标记">
              <Input placeholder="如 oss://archive-bucket/evalshield" maxLength={256} />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </>
  )
}

function CancelTab() {
  const { message } = App.useApp()
  const [sub, setSub] = useState(null)
  const [tenant, setTenant] = useState(null)
  const [loading, setLoading] = useState(false)
  const [modal, setModal] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await http.get('/billing/subscription')
      setSub(d?.subscription || null)
      setTenant(d?.tenant || null)
    } catch (err) { console.warn('[Retention] subscription load fail', err) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const confirmText = Form.useWatch('confirm_name', form)

  const submit = async () => {
    const v = await form.validateFields()
    setSubmitting(true)
    try {
      const d = await http.post('/billing/subscription/cancel-and-anonymize', { reason: v.reason || null })
      message.success(`已注销，${d?.cooldown_days ?? 30} 天后数据将匿名化`)
      setModal(false); form.resetFields(); load()
    } catch (err) { console.warn('[Retention] cancel fail', err) }
    finally { setSubmitting(false) }
  }

  return (
    <Card
      title={<Space><SafetyCertificateOutlined style={{ color: tokens.danger }} />注销并匿名化</Space>}
      style={{ background: tokens.bgPanel, borderColor: tokens.border }}
      loading={loading}
    >
      <Typography.Paragraph style={{ color: tokens.text2 }}>
        注销当前租户订购：订阅立即停用，30 天冷静期后系统自动将本租户的业务数据内容匿名化
        （保留不可识别的最小墓碑记录），审计日志不受匿名化影响、按合规要求永久留存。
      </Typography.Paragraph>
      <Space direction="vertical" style={{ marginBottom: 16 }}>
        <Typography.Text style={{ color: tokens.text2 }}>
          当前租户：<span style={{ color: tokens.text1 }}>{tenant?.name || `#${tenant?.id ?? '—'}`}</span>
        </Typography.Text>
        <Typography.Text style={{ color: tokens.text2 }}>
          当前订购：
          {sub
            ? <Tag color={sub.status === 'ACTIVE' ? 'green' : 'orange'}>{sub.plan_name || sub.plan_code} · {sub.status}</Tag>
            : <span style={{ color: tokens.text3 }}>无有效订购</span>}
        </Typography.Text>
      </Space>
      <div>
        <Button
          danger type="primary" disabled={!sub}
          onClick={() => { form.resetFields(); setModal(true) }}
        >
          注销并匿名化
        </Button>
        {!sub && (
          <Typography.Text style={{ color: tokens.text3, marginLeft: 12, fontSize: 12 }}>
            当前无有效订购，无法发起注销
          </Typography.Text>
        )}
      </div>
      <Modal
        open={modal} title="确认注销并匿名化？"
        okText="确认注销" confirmLoading={submitting}
        okButtonProps={{ danger: true, disabled: confirmText !== (tenant?.name || '') }}
        onCancel={() => { setModal(false); form.resetFields() }}
        onOk={submit} destroyOnClose
      >
        <Typography.Paragraph style={{ color: tokens.text2 }}>
          此操作不可撤销。请输入租户名称
          <span style={{ color: tokens.text1, fontWeight: 600 }}>「{tenant?.name || '—'}」</span>
          以确认：
        </Typography.Paragraph>
        <Form form={form} layout="vertical">
          <Form.Item
            name="confirm_name"
            rules={[{
              validator: (_, value) =>
                value === (tenant?.name || '') ? Promise.resolve() : Promise.reject(new Error('请输入正确的租户名称')),
            }]}
          >
            <Input placeholder="输入租户名称以确认" />
          </Form.Item>
          <Form.Item name="reason" label="注销原因（选填）">
            <Input.TextArea rows={2} maxLength={512} placeholder="我们将记录在审计留痕中" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default function Retention() {
  const { edition } = useEdition()
  // 注销端点 saas-only（非 saas 后端 404），入口同步隐藏
  const isSaas = edition === 'saas'
  return (
    <div style={{ padding: 16 }}>
      <Typography.Title level={4} style={{ color: tokens.text1 }}>数据保留</Typography.Title>
      <div style={{ marginBottom: 24 }}>
        <PolicyTab />
      </div>
      {isSaas && <CancelTab />}
    </div>
  )
}
