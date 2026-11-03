/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES8 M8 在线评测最小闭环（方案 §9.4）
// trace 列表 + 评分徽章（SCORED 低分红 / 正常 teal / PENDING·SKIPPED·FAILED 灰）、
// 详情抽屉（request/response 双栏等宽 pre + 评分明细）、策略配置抽屉（GET/PUT /traces/policy）、
// API Key 管理 Modal（复用 /admin/api-keys，创建一次性明文警示 + 列表只显前缀）。
// ES11 P9：列表增列（项目/被测系统/会话引用/触发规则/风险等级/回流状态/关联实体/是否复发），
// 行点击改跳 /traces/:id 分诊工作台深链（四分诊动作在 TraceTriage 承载）。
import { useState, useEffect, useCallback } from 'react'
import {
  App, Alert, Button, Card, Drawer, Form, Input, InputNumber,
  Modal, Select, Space, Switch, Table, Tag, Tooltip, Typography,
} from 'antd'
import {
  ApiOutlined, KeyOutlined, ReloadOutlined, SafetyOutlined, CopyOutlined,
  RightOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import http from '../../api/http'
import { useAuth } from '../../auth'

const SOURCE_LABEL = { gateway: '网关留痕', ingest_api: 'API 推送' }
const METRIC_LABEL = { injection: '注入风险', pii_leak: 'PII 泄露', hallucination: '幻觉' }
const RISK_LABEL = { HIGH: '高', MEDIUM: '中', LOW: '低', SAFE: '安全' }
const RISK_COLOR = { HIGH: 'red', MEDIUM: 'orange', LOW: 'blue', SAFE: 'green' }

function fmtTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString('zh-CN', { hour12: false })
}

// 评分徽章：SCORED 且 reviewed（低分回流）→ 红；SCORED 正常 → teal；其余灰
function evalBadge(r, threshold) {
  if (r.eval_status === 'SCORED') {
    const low = r.reviewed === true
      || (r.overall != null && r.overall < (threshold ?? 0.6))
    return <Tag color={low ? '#FF4D4F' : 'cyan'}>{low ? `低分 ${r.overall ?? '-'}` : `已评分 ${r.overall ?? '-'}`}</Tag>
  }
  if (r.eval_status === 'PENDING') return <Tag>待评估</Tag>
  if (r.eval_status === 'SKIPPED') return <Tag>未抽样</Tag>
  if (r.eval_status === 'FAILED') return <Tag color="volcano">评估失败</Tag>
  return <Tag>{r.eval_status}</Tag>
}

// ---------------------------------------------------------------- 策略抽屉 ----

function PolicyDrawer({ open, onClose, onSaved }) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    http.get('/traces/policy')
      .then((p) => form.setFieldsValue({
        enabled: !!p.enabled,
        sample_rate: p.sample_rate,
        judge_metrics: p.judge_metrics || [],
        daily_cap: p.daily_cap,
        low_score_threshold: p.low_score_threshold,
      }))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [open, form])

  const save = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      await http.put('/traces/policy', v)
      message.success('策略已保存')
      onSaved?.(v)
      onClose()
    } catch (e) {
      message.error(e?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer title={<Space><SafetyOutlined />采样评分策略</Space>} open={open} onClose={onClose} width={460} destroyOnClose>
      <Form form={form} layout="vertical" disabled={loading}>
        <Form.Item name="enabled" label="启用在线评测" valuePropName="checked" tooltip="关闭后新 trace 将保持待评估，不做抽样评分">
          <Switch />
        </Form.Item>
        <Form.Item name="sample_rate" label="抽样率（0-1）" tooltip="每条 PENDING trace 按此概率被抽中评分" rules={[{ required: true, message: '必填' }]}>
          <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="judge_metrics" label="评分指标" tooltip="hallucination 需租户已配置 judge 模型，缺席时该指标自动降级">
          <Select mode="multiple" options={Object.entries(METRIC_LABEL).map(([v, l]) => ({ value: v, label: l }))} />
        </Form.Item>
        <Form.Item name="daily_cap" label="日评分上限（熔断）" tooltip="当日已评分条数达上限后本批熔断，摄入侧限额为该值×5" rules={[{ required: true, message: '必填' }]}>
          <InputNumber min={1} max={100000} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="low_score_threshold" label="低分阈值（0-1）" tooltip="overall 低于该值的 trace 自动回流人工复核队列" rules={[{ required: true, message: '必填' }]}>
          <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
      <Button type="primary" block loading={saving} onClick={save}>保存策略</Button>
    </Drawer>
  )
}

// ------------------------------------------------------------ API Key 弹窗 ----

function ApiKeyModal({ open, onClose }) {
  const { message } = App.useApp()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm()
  // 一次性明文：创建成功后仅展示这一次，关闭即销毁
  const [plainKey, setPlainKey] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    http.get('/admin/api-keys')
      .then((d) => setRows(d?.items || []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { if (open) { load(); setPlainKey(null) } }, [open, load])

  const create = async () => {
    const v = await form.validateFields()
    setCreating(true)
    try {
      const d = await http.post('/admin/api-keys', { key_name: v.key_name, scopes: ['traces:ingest'] })
      setPlainKey(d?.api_key || null)
      form.resetFields()
      load()
    } catch (e) {
      message.error(e?.message || '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const revoke = async (id) => {
    try { await http.delete(`/admin/api-keys/${id}`); message.success('已吊销'); load() } catch { /* http 拦截器已提示 */ }
  }

  return (
    <Modal open={open} onCancel={onClose} footer={null} width={640} destroyOnClose
      title={<Space><KeyOutlined />摄入 API Key 管理</Space>}>
      {plainKey ? (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="明文仅展示这一次，请立即复制保存"
          description={(
            <Space direction="vertical" style={{ width: '100%' }}>
              <Typography.Paragraph copyable={{ icon: <CopyOutlined /> }} code style={{ wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>{plainKey}</Typography.Paragraph>
              <Typography.Text type="secondary">请求头 <Typography.Text code>X-API-Key</Typography.Text> 推送 POST /api/traces/ingest</Typography.Text>
            </Space>
          )}
        />
      ) : (
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
          message="外部系统通过 API Key 调用 POST /api/traces/ingest 推送 trace（批量 ≤100 条/请求）" />
      )}
      <Form form={form} layout="inline" style={{ marginBottom: 12 }}>
        <Form.Item name="key_name" rules={[{ required: true, message: '名称必填' }]}>
          <Input placeholder="Key 名称，如 prod-push" style={{ width: 220 }} />
        </Form.Item>
        <Button type="primary" icon={<ApiOutlined />} loading={creating} onClick={create}>创建</Button>
      </Form>
      <Table size="small" rowKey="id" loading={loading} dataSource={rows} pagination={false}
        columns={[
          { title: '名称', dataIndex: 'key_name' },
          // 列表只显前缀（前 8 位），明文后端只回传一次
          { title: '前缀', dataIndex: 'key_prefix', render: (v) => <Typography.Text code>{v}••••</Typography.Text> },
          { title: '作用域', dataIndex: 'scopes', render: (v) => (v || []).map((s) => <Tag key={s}>{s}</Tag>) },
          { title: '最近使用', dataIndex: 'last_used_at', render: fmtTime },
          {
            title: '状态', dataIndex: 'disabled', width: 70,
            render: (v) => (v ? <Tag color="red">已吊销</Tag> : <Tag color="green">有效</Tag>),
          },
          {
            title: '', width: 60,
            render: (_, r) => (!r.disabled && <Button size="small" danger onClick={() => revoke(r.id)}>吊销</Button>),
          },
        ]}
      />
    </Modal>
  )
}

// ------------------------------------------------------------------ 主页面 ----

export default function TraceList() {
  const { hasPerm } = useAuth()
  const canManage = hasPerm('trace:manage')
  const canKeyAdmin = hasPerm('admin:*')
  const navigate = useNavigate()

  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [evalFilter, setEvalFilter] = useState(null)
  const [sourceFilter, setSourceFilter] = useState(null)
  const [lowOnly, setLowOnly] = useState(false)
  const [policy, setPolicy] = useState(null)
  const [policyOpen, setPolicyOpen] = useState(false)
  const [keyOpen, setKeyOpen] = useState(false)

  const load = useCallback((p = 1, over = {}) => {
    setLoading(true)
    http.get('/traces', {
      params: {
        page: p, page_size: 20,
        eval_status: over.eval_status !== undefined ? over.eval_status : evalFilter || undefined,
        source: over.source !== undefined ? over.source : sourceFilter || undefined,
        low_only: over.low_only !== undefined ? over.low_only : (lowOnly || undefined),
      },
    })
      .then((d) => { setRows(d?.items || []); setTotal(d?.total || 0); setPage(p) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [evalFilter, sourceFilter, lowOnly])

  useEffect(() => { load(1) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    http.get('/traces/policy').then(setPolicy).catch(() => {})
  }, [])

  return (
    <div style={{ padding: 16 }}>
      <Card
        size="small"
        title={
          <Space>
            <ApiOutlined />在线评测 Trace
            <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 'normal' }}>
              对线上真实流量抽样评分；离线批量评测请用「评测中心」
            </Typography.Text>
          </Space>
        }
        extra={(
          <Space size={6}>
            <Select allowClear placeholder="评估状态" style={{ width: 120 }} size="small"
              value={evalFilter}
              onChange={(v) => { setEvalFilter(v || null); load(1, { eval_status: v || undefined }) }}
              options={[
                { value: 'PENDING', label: '待评估' }, { value: 'SCORED', label: '已评分' },
                { value: 'SKIPPED', label: '未抽样' }, { value: 'FAILED', label: '评估失败' },
              ]}
            />
            <Select allowClear placeholder="来源" style={{ width: 110 }} size="small"
              value={sourceFilter}
              onChange={(v) => { setSourceFilter(v || null); load(1, { source: v || undefined }) }}
              options={[
                { value: 'gateway', label: '网关留痕' }, { value: 'ingest_api', label: 'API 推送' },
              ]}
            />
            <Tooltip title="只看自动回流人工复核的低分 trace">
              <Button size="small" type={lowOnly ? 'primary' : 'default'}
                onClick={() => { const v = !lowOnly; setLowOnly(v); load(1, { low_only: v || undefined }) }}>
                仅低分
              </Button>
            </Tooltip>
            <Tooltip title="刷新"><Button size="small" type="text" icon={<ReloadOutlined spin={loading} />} onClick={() => load(page)} /></Tooltip>
            {canManage && <Button size="small" icon={<SafetyOutlined />} onClick={() => setPolicyOpen(true)}>策略配置</Button>}
            {canKeyAdmin && <Button size="small" icon={<KeyOutlined />} onClick={() => setKeyOpen(true)}>API Key</Button>}
          </Space>
        )}
      >
        <Table
          size="small" rowKey="id" loading={loading} dataSource={rows}
          scroll={{ x: 1480 }}
          pagination={{ current: page, pageSize: 20, total, showSizeChanger: false, onChange: (p) => load(p) }}
          onRow={(r) => ({ onClick: () => navigate(`/traces/${r.id}`), style: { cursor: 'pointer' } })}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 80, fixed: 'left' },
            { title: '发生时间', dataIndex: 'occurred_at', width: 160, render: fmtTime },
            { title: '来源', dataIndex: 'source', width: 90, render: (v) => <Tag>{SOURCE_LABEL[v] || v}</Tag> },
            { title: '项目', dataIndex: 'project_name', width: 130, ellipsis: true, render: (v) => v || '-' },
            { title: '被测系统', dataIndex: 'target_name', width: 130, ellipsis: true, render: (v) => v || '-' },
            { title: '会话引用', dataIndex: 'session_ref', width: 120, ellipsis: true, render: (v) => v || '-' },
            { title: '模型', dataIndex: 'model', width: 120, ellipsis: true, render: (v) => v || '-' },
            { title: '评估', dataIndex: 'eval_status', width: 110, render: (_, r) => evalBadge(r, policy?.low_score_threshold) },
            {
              title: '触发规则', dataIndex: 'trigger_rule', width: 100,
              render: (v) => (v ? <Tag color="volcano">{METRIC_LABEL[v] || v}</Tag> : '-'),
            },
            {
              title: '风险', dataIndex: 'risk_level', width: 72,
              render: (v) => (v ? <Tag color={RISK_COLOR[v]}>{RISK_LABEL[v]}</Tag> : '-'),
            },
            {
              title: '回流状态', key: 'reflow', width: 110,
              render: (_, r) => {
                if (r.defect_count > 0) return <Tag color="red">已转缺陷 ×{r.defect_count}</Tag>
                if (r.reviewed) return <Tag color="orange">已回流复核</Tag>
                if (r.eval_status === 'PENDING') return <Tag>待评估</Tag>
                return <Tag>未回流</Tag>
              },
            },
            {
              title: '关联实体', key: 'linked', width: 110,
              render: (_, r) => (
                <Space size={4}>
                  {r.reviewed && <Tag color="gold">复核</Tag>}
                  {r.defect_count > 0 && <Tag color="red">缺陷</Tag>}
                  {r.has_payload && <Tag color="geekblue">轨迹</Tag>}
                  {!r.reviewed && !r.defect_count && !r.has_payload && '-'}
                </Space>
              ),
            },
            {
              title: '复发', dataIndex: 'recurrence', width: 64,
              render: (v) => (v ? <Tag color="purple">复发</Tag> : '-'),
            },
            { title: '请求预览', dataIndex: 'request_preview', width: 200, ellipsis: true },
            { title: 'Tokens', dataIndex: 'tokens', width: 72, render: (v) => v ?? '-' },
            { title: '耗时', dataIndex: 'latency_ms', width: 80, render: (v) => (v != null ? `${v}ms` : '-') },
            {
              title: '分诊', key: 'go', width: 80, fixed: 'right',
              render: (_, r) => (
                <a onClick={(e) => { e.stopPropagation(); navigate(`/traces/${r.id}`) }}>
                  分诊 <RightOutlined />
                </a>
              ),
            },
          ]}
        />
      </Card>

      <PolicyDrawer open={policyOpen} onClose={() => setPolicyOpen(false)}
        onSaved={(v) => setPolicy((p) => ({ ...p, ...v }))} />
      <ApiKeyModal open={keyOpen} onClose={() => setKeyOpen(false)} />
    </div>
  )
}
