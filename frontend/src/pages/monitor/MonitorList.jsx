/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES8 M4 定时监控与回归告警（Watchdog）列表页（方案 §5.4）
// 卡片列表：名称 / 套件 / cron / 下次触发倒计时 / FIRING 红点；
// 详情抽屉：基本信息编辑 + 告警条件编辑器 + 告警时间线。
import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  App, Badge, Button, Card, Col, Drawer, Empty, Form, Input, InputNumber,
  Popconfirm, Row, Select, Space, Spin, Switch, Tag, Timeline, Tooltip, Typography,
} from 'antd'
import {
  DeleteOutlined, FieldTimeOutlined, PlayCircleOutlined, PlusOutlined,
  ReloadOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import http from '../../api/http'
import { tokens } from '../../theme/tokens'

// 告警指标下拉（与后端 ALERT_METRICS 一致）
const METRIC_OPTIONS = [
  { value: 'pass_rate', label: '通过率 pass_rate' },
  { value: 'injection_success_rate', label: '注入成功率 injection_success_rate' },
  { value: 'hallucination_rate', label: '幻觉率 hallucination_rate' },
]
const OP_OPTIONS = [
  { value: 'lt', label: '低于 <' },
  { value: 'gt', label: '高于 >' },
]
const FIRING_COLOR = '#FF4D4F'

// 每秒刷新一次的当前时间（倒计时用）
function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}

// next_fire_at(UTC ISO) → 人类可读倒计时
function fmtCountdown(iso, nowMs) {
  if (!iso) return '未排程'
  const ms = new Date(iso).getTime() - nowMs
  if (Number.isNaN(ms)) return '未排程'
  if (ms <= 0) return '即将触发'
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s} 秒后`
  if (s < 3600) return `${Math.floor(s / 60)} 分 ${s % 60} 秒后`
  if (s < 86400) return `${Math.floor(s / 3600)} 小时 ${Math.floor((s % 3600) / 60)} 分后`
  return `${Math.floor(s / 86400)} 天 ${Math.floor((s % 86400) / 3600)} 小时后`
}

function fmtTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString('zh-CN', { hour12: false })
}

// 告警时间线（抽屉内，打开时拉取）
function AlertTimeline({ monitorId }) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    if (!monitorId) return
    setLoading(true)
    http
      .get(`/monitors/${monitorId}/alerts`, { params: { page_size: 50 } })
      .then((d) => setRows(d?.items || []))
      .catch((e) => console.warn('[Monitor] alerts fail', e?.message || e))
      .finally(() => setLoading(false))
  }, [monitorId])

  if (loading) return <Spin style={{ display: 'block', margin: '16px auto' }} />
  if (!rows.length) return <Empty description="暂无告警记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  return (
    <Timeline
      style={{ paddingTop: 4 }}
      items={rows.map((a) => ({
        color: a.state === 'FIRING' ? FIRING_COLOR : tokens.success,
        children: (
          <div>
            <Space size={8}>
              <Tag color={a.state === 'FIRING' ? 'red' : 'green'} style={{ marginRight: 0 }}>
                {a.state === 'FIRING' ? '告警中' : '已恢复'}
              </Tag>
              <Typography.Text style={{ color: tokens.text1 }}>
                {a.metric} {a.op} {a.threshold}
              </Typography.Text>
              <Typography.Text style={{ color: tokens.text2 }}>实际值 {a.value}</Typography.Text>
            </Space>
            <div style={{ color: tokens.text3, fontSize: 12, marginTop: 2 }}>
              触发 {fmtTime(a.fired_at)}
              {a.resolved_at ? ` · 恢复 ${fmtTime(a.resolved_at)}` : ''}
              {a.run_id ? ` · 批次 #${a.run_id}` : ''}
            </div>
          </div>
        ),
      }))}
    />
  )
}

// 详情抽屉：新建/编辑监控 + 告警条件编辑器 + 告警时间线
function MonitorDrawer({ open, monitor, suiteOptions, onClose, onSaved }) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const isEdit = !!monitor?.id

  useEffect(() => {
    if (!open) return
    form.resetFields()
    if (monitor) {
      form.setFieldsValue({
        name: monitor.name,
        suite_id: monitor.suite_id,
        cron: monitor.cron,
        enabled: monitor.enabled,
        alert_conditions: monitor.alert_conditions || [],
      })
    } else {
      form.setFieldsValue({ enabled: true, alert_conditions: [] })
    }
  }, [open, monitor, form])

  const save = async () => {
    const v = await form.validateFields()
    const body = {
      name: v.name,
      suite_id: v.suite_id,
      cron: v.cron,
      enabled: !!v.enabled,
      alert_conditions: (v.alert_conditions || []).map((c) => ({
        metric: c.metric, op: c.op, threshold: Number(c.threshold),
      })),
    }
    setSaving(true)
    try {
      if (isEdit) await http.put(`/monitors/${monitor.id}`, body)
      else await http.post('/monitors', body)
      message.success('已保存')
      onSaved()
      onClose()
    } catch (e) {
      /* 错误已由拦截器提示 */
      console.warn('[Monitor] save fail', e?.message || e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer
      title={isEdit ? `监控详情 · ${monitor.name}` : '新建监控'}
      width={560}
      open={open}
      onClose={onClose}
      destroyOnClose
      styles={{ body: { background: tokens.bgPage } }}
      extra={
        <Button type="primary" loading={saving} onClick={save}>保存</Button>
      }
    >
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="监控名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input maxLength={128} placeholder="如：核心回归看门狗" />
        </Form.Item>
        <Form.Item name="suite_id" label="测试套件" rules={[{ required: true, message: '请选择套件' }]}>
          <Select
            showSearch
            optionFilterProp="label"
            placeholder="选择本租户的套件"
            options={suiteOptions}
          />
        </Form.Item>
        <Form.Item
          name="cron"
          label="调度表达式（5 段 cron）"
          rules={[{ required: true, message: '请输入 cron' }]}
          extra="示例：*/30 * * * * 每 30 分钟；0 9 * * 1 每周一 09:00"
        >
          <Input maxLength={32} placeholder="分 时 日 月 周" />
        </Form.Item>
        <Form.Item name="enabled" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Typography.Title level={5} style={{ color: tokens.text1 }}>告警条件</Typography.Title>
        <Form.List name="alert_conditions">
          {(fields, { add, remove }) => (
            <>
              {fields.map((f) => (
                <Space key={f.key} align="baseline" style={{ display: 'flex', marginBottom: 4 }}>
                  <Form.Item
                    {...f} name={[f.name, 'metric']}
                    rules={[{ required: true, message: '指标' }]}
                  >
                    <Select style={{ width: 220 }} placeholder="指标" options={METRIC_OPTIONS} />
                  </Form.Item>
                  <Form.Item
                    {...f} name={[f.name, 'op']} initialValue="lt"
                    rules={[{ required: true, message: '方向' }]}
                  >
                    <Select style={{ width: 100 }} options={OP_OPTIONS} />
                  </Form.Item>
                  <Form.Item
                    {...f} name={[f.name, 'threshold']}
                    rules={[{ required: true, message: '阈值' }]}
                  >
                    <InputNumber style={{ width: 110 }} min={0} max={1} step={0.05} placeholder="0~1" />
                  </Form.Item>
                  <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(f.name)} />
                </Space>
              ))}
              <Button
                type="dashed" block icon={<PlusOutlined />} style={{ marginBottom: 16 }}
                onClick={() => add({ op: 'lt', threshold: 0.8 })}
              >
                添加条件
              </Button>
            </>
          )}
        </Form.List>
      </Form>

      {isEdit && (
        <>
          <Typography.Title level={5} style={{ color: tokens.text1 }}>告警时间线</Typography.Title>
          <AlertTimeline monitorId={monitor.id} />
        </>
      )}
    </Drawer>
  )
}

export default function MonitorList() {
  const { message } = App.useApp()
  const now = useNow(1000)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [suiteMap, setSuiteMap] = useState({}) // id -> name
  const [drawer, setDrawer] = useState({ open: false, monitor: null })
  const [running, setRunning] = useState(0)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await http.get('/monitors', { params: { page_size: 100 } })
      setRows(d?.items || [])
    } catch (e) {
      /* 能力位未开通等错误由拦截器统一提示 */
      console.warn('[Monitor] list fail', e?.message || e)
    } finally {
      setLoading(false)
    }
  }, [])

  // 套件选项：拉项目列表后逐个取套件（租户量小，一次装配成 id→name 映射）
  const loadSuites = useCallback(async () => {
    try {
      const d = await http.get('/projects', { params: { page: 1, page_size: 100 } })
      const projs = (d?.items || []).map((p) => p.id)
      const lists = await Promise.all(
        projs.map((pid) => http.get(`/projects/${pid}/suites`).catch(() => [])),
      )
      const map = {}
      for (const x of lists) {
        const arr = Array.isArray(x) ? x : x?.items || []
        for (const s of arr) map[s.id] = s.name
      }
      setSuiteMap(map)
    } catch (e) {
      console.warn('[Monitor] suites fail', e?.message || e)
    }
  }, [])

  useEffect(() => { load(); loadSuites() }, [load, loadSuites])

  const suiteOptions = useMemo(
    () => Object.entries(suiteMap).map(([id, name]) => ({ value: Number(id), label: name })),
    [suiteMap],
  )

  const toggle = async (m, enabled) => {
    try {
      await http.put(`/monitors/${m.id}`, { enabled })
      message.success(enabled ? '已启用' : '已停用')
      load()
    } catch (e) { console.warn('[Monitor] toggle fail', e?.message || e) }
  }

  const runNow = async (m) => {
    setRunning(m.id)
    try {
      const d = await http.post(`/monitors/${m.id}/run-now`)
      message.success(`已触发批次，克隆任务 ${ (d?.created_task_ids || []).length } 个`)
      load()
    } catch (e) { console.warn('[Monitor] run-now fail', e?.message || e) }
    finally { setRunning(0) }
  }

  const remove = async (m) => {
    try {
      await http.delete(`/monitors/${m.id}`)
      message.success('已删除')
      load()
    } catch (e) { console.warn('[Monitor] delete fail', e?.message || e) }
  }

  return (
    <div>
      <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0, color: tokens.text1 }}>定时监控</Typography.Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <Button
            type="primary" icon={<PlusOutlined />}
            onClick={() => setDrawer({ open: true, monitor: null })}
          >
            新建监控
          </Button>
        </Space>
      </Space>

      {!loading && rows.length === 0 && (
        <Card style={{ background: tokens.bgPanel, borderColor: tokens.border }}>
          <Empty
            description={
              <span style={{ color: tokens.text2 }}>
                暂无监控。为测试套件配置 cron 排程与阈值条件，回归异常将自动触发告警通知。
              </span>
            }
          />
        </Card>
      )}

      <Spin spinning={loading}>
        <Row gutter={[12, 12]}>
          {rows.map((m) => (
            <Col key={m.id} xs={24} md={12} xl={8}>
              <Card
                size="small"
                hoverable
                style={{ background: tokens.bgPanel, borderColor: tokens.border }}
                title={
                  <Space size={8}>
                    {/* FIRING 红点：存在未恢复告警时点亮 */}
                    <Badge dot={m.firing_count > 0} color={FIRING_COLOR} offset={[2, 0]}>
                      <FieldTimeOutlined style={{ color: m.enabled ? tokens.primary : tokens.text3 }} />
                    </Badge>
                    <span style={{ color: tokens.text1 }}>{m.name}</span>
                    {m.firing_count > 0 && (
                      <Tooltip title={`${m.firing_count} 条告警未恢复`}>
                        <Tag color="red" style={{ marginRight: 0 }}>FIRING {m.firing_count}</Tag>
                      </Tooltip>
                    )}
                  </Space>
                }
                extra={
                  <Space size={4}>
                    <Switch
                      size="small"
                      checked={m.enabled}
                      onChange={(v) => toggle(m, v)}
                    />
                  </Space>
                }
                actions={[
                  <Button
                    key="run" type="text" size="small" icon={<PlayCircleOutlined />}
                    loading={running === m.id} onClick={() => runNow(m)}
                  >立即执行</Button>,
                  <Button
                    key="edit" type="text" size="small" icon={<ThunderboltOutlined />}
                    onClick={() => setDrawer({ open: true, monitor: m })}
                  >详情</Button>,
                  <Popconfirm
                    key="del" title={`删除监控「${m.name}」？`}
                    okButtonProps={{ danger: true }} onConfirm={() => remove(m)}
                  >
                    <Button type="text" size="small" danger icon={<DeleteOutlined />}>删除</Button>
                  </Popconfirm>,
                ]}
              >
                <div style={{ fontSize: 13, color: tokens.text2, lineHeight: '26px' }}>
                  <div>套件：<span style={{ color: tokens.text1 }}>{suiteMap[m.suite_id] || `#${m.suite_id}`}</span></div>
                  <div>排程：<Typography.Text code style={{ fontSize: 12 }}>{m.cron}</Typography.Text></div>
                  <div>
                    下次触发：
                    <span style={{ color: m.enabled ? tokens.primary : tokens.text3 }}>
                      {m.enabled ? fmtCountdown(m.next_fire_at, now) : '已停用'}
                    </span>
                  </div>
                  <div style={{ color: tokens.text3, fontSize: 12 }}>
                    条件 {m.alert_conditions.length} 条 · 上次检查 {fmtTime(m.last_checked_at)}
                  </div>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      </Spin>

      <MonitorDrawer
        open={drawer.open}
        monitor={drawer.monitor}
        suiteOptions={suiteOptions}
        onClose={() => setDrawer({ open: false, monitor: null })}
        onSaved={load}
      />
    </div>
  )
}
