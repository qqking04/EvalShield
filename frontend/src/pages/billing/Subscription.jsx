/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES8 M1：租户自助订阅页（subscriptions 权威 + billing_quotas 派生用量）
// ES8 M2：升级/续费下单（orders + 收银台跳转）、resume 反悔恢复、订单历史、账单列表
import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button, Card, Space, Tag, Typography, Progress, Statistic, Row, Col, Alert, Modal, Input,
  InputNumber, Radio, Table, message,
} from 'antd'
import { ReloadOutlined, CreditCardOutlined, CalendarOutlined, RiseOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { fmtTime } from '../../utils'

const { Text } = Typography

const SUB_STATUS_META = {
  TRIALING: { label: '试用中', color: 'processing' },
  ACTIVE: { label: '生效中', color: 'success' },
  GRACE: { label: '宽限期', color: 'warning' },
  PAST_DUE: { label: '已欠费', color: 'error' },
}

const ORDER_STATUS_META = {
  PENDING: { label: '待支付', color: 'processing' },
  PAID: { label: '已支付', color: 'success' },
  FULFILLED: { label: '已开通', color: 'success' },
  CLOSED: { label: '已关闭', color: 'default' },
  FAILED: { label: '支付失败', color: 'error' },
  REFUNDED: { label: '已退款', color: 'warning' },
}

const fmtYuan = (cents) => `¥${((cents || 0) / 100).toFixed(2)}`

const pct = (used, total) => (total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0)

export default function Subscription() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [cancelReason, setCancelReason] = useState('')
  const [canceling, setCanceling] = useState(false)
  // ES8 M2：升级弹窗 / 订单历史 / 账单
  const [upgradeOpen, setUpgradeOpen] = useState(false)
  const [plans, setPlans] = useState([])
  const [pick, setPick] = useState({ planCode: null, cycle: 'monthly', useCredits: 0 })
  const [placing, setPlacing] = useState(false)
  const [orders, setOrders] = useState({ items: [], total: 0 })
  const [ordersPage, setOrdersPage] = useState(1)
  const [ordersLoading, setOrdersLoading] = useState(false)
  const [invoices, setInvoices] = useState({ items: [], total: 0 })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await http.get('/billing/subscription'))
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setLoading(false)
    }
  }, [])

  const loadOrders = useCallback(async (page = 1) => {
    setOrdersLoading(true)
    try {
      setOrders(await http.get('/billing/orders', { params: { page, page_size: 10 } }))
      setOrdersPage(page)
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setOrdersLoading(false)
    }
  }, [])

  const loadInvoices = useCallback(async () => {
    try {
      setInvoices(await http.get('/billing/invoices', { params: { page: 1, page_size: 10 } }))
    } catch {
      /* 错误已由拦截器提示 */
    }
  }, [])

  const openUpgrade = async () => {
    setUpgradeOpen(true)
    if (plans.length === 0) {
      try {
        const d = await http.get('/pricing/plans-public')
        setPlans(d?.items || [])
        if (!pick.planCode && d?.items?.length) setPick((p) => ({ ...p, planCode: d.items[0].code }))
      } catch {
        /* 错误已由拦截器提示 */
      }
    }
  }

  useEffect(() => {
    load()
    loadOrders()
    loadInvoices()
  }, [load, loadOrders, loadInvoices])

  const sub = data?.subscription
  const quota = data?.quota
  const banner = data?.sub_status
  const meta = sub ? (SUB_STATUS_META[sub.status] || { label: sub.status, color: 'default' }) : null

  const trialDaysLeft = sub?.trial_ends_at
    ? Math.max(0, Math.ceil((new Date(sub.trial_ends_at).getTime() - Date.now()) / 86400000))
    : null

  const quotaCards = quota ? [
    { title: '任务额度', used: quota.task_used, total: quota.task_quota, color: '#1F4E79' },
    { title: '评测额度', used: quota.eval_used, total: quota.eval_quota, color: '#722ED1' },
    { title: '存储额度 (MB)', used: quota.storage_used_mb, total: quota.storage_quota_mb, color: '#D48806' },
  ] : []

  const doCancel = async () => {
    setCanceling(true)
    try {
      await http.post('/billing/subscription/cancel', { reason: cancelReason || null })
      message.success('已提交取消申请，当前账期结束（权益保留至到期日）后生效。')
      setCancelOpen(false)
      setCancelReason('')
      load()
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setCanceling(false)
    }
  }

  const doResume = async () => {
    try {
      await http.post('/billing/subscription/resume')
      message.success('已恢复订阅，到期后将正常续费。')
      load()
    } catch {
      /* 错误已由拦截器提示 */
    }
  }

  // 升级弹窗派生：所选套餐 / 订单原价 / 抵扣预估（与服务端 place_order 同口径：min(申请,余额,原价50%)）
  const pickPlan = plans.find((p) => p.code === pick.planCode)
  const grossCents = pickPlan
    ? (pick.cycle === 'yearly' ? pickPlan.price_yearly_cents : pickPlan.price_monthly_cents) || 0
    : 0
  const balanceCents = Math.round((quota?.credits || 0) * 100)
  const estDeduct = Math.max(0, Math.min(
    Math.round((pick.useCredits || 0) * 100), balanceCents, Math.floor(grossCents / 2),
  ))
  const payCents = Math.max(0, grossCents - estDeduct)

  const doPlaceOrder = async () => {
    if (!pick.planCode) {
      message.warning('请选择套餐')
      return
    }
    setPlacing(true)
    try {
      const d = await http.post('/billing/orders', {
        plan_code: pick.planCode,
        billing_cycle: pick.cycle,
        use_credits: pick.useCredits || 0,
      })
      message.success('订单已创建，正在跳转收银台…')
      setUpgradeOpen(false)
      loadOrders(1)
      navigate(d.pay_url || `/billing/pay?order_no=${d.order_no}`)
    } catch {
      /* 错误已由拦截器提示（503 缺 KEY / 404 套餐停用等） */
    } finally {
      setPlacing(false)
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>我的订阅</Typography.Title>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
      </div>

      {sub?.status === 'TRIALING' && trialDaysLeft != null && (
        <Alert
          type="info"
          showIcon
          icon={<CalendarOutlined />}
          message={`免费试用进行中：剩 ${trialDaysLeft} 天（至 ${fmtTime(sub.trial_ends_at)}）。升级套餐可继续使用全部功能。`}
        />
      )}
      {banner?.sub_status === 'GRACE' && (
        <Alert
          type="warning"
          showIcon
          message={`服务已进入宽限期（剩 ${banner.grace_remaining_days ?? 0} 天），请尽快续费；超期后将暂停新建与提交。`}
        />
      )}
      {banner?.sub_status === 'PAST_DUE' && (
        <Alert
          type="error"
          showIcon
          message="订阅已超期：现有数据只读，新建与提交已暂停。续费后立即恢复。"
          action={<Button size="small" danger onClick={openUpgrade}>立即续费</Button>}
        />
      )}
      {sub?.cancel_at_period_end && (
        <Alert
          type="warning"
          showIcon
          message={`订阅已安排在 ${fmtTime(sub.current_period_end)} 账期结束后取消，期间权益不受影响。`}
        />
      )}

      <Card title={<Space><CreditCardOutlined />当前套餐</Space>}>
        {sub ? (
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="工作区" value={data?.tenant?.name || '-'} />
            </Col>
            <Col span={5}>
              <Statistic
                title="套餐"
                value={sub.plan_name || sub.plan_code}
                suffix={<Tag color={meta?.color}>{meta?.label}</Tag>}
              />
            </Col>
            <Col span={6}>
              <Statistic title="计费周期" value={sub.billing_cycle === 'yearly' ? '按年' : '按月'} />
            </Col>
            <Col span={7}>
              <Statistic
                title="本期截止"
                value={sub.current_period_end ? fmtTime(sub.current_period_end) : '-'}
              />
            </Col>
          </Row>
        ) : (
          <Typography.Text type="secondary">当前租户暂无有效订购记录（联系管理员开通或由运营后台下单）。</Typography.Text>
        )}
        <Space style={{ marginTop: 16 }}>
          <Button type="primary" icon={<RiseOutlined />} disabled={!sub} onClick={openUpgrade}>
            升级套餐
          </Button>
          {sub?.cancel_at_period_end && (
            <Button onClick={doResume}>恢复订阅（取消期末终止）</Button>
          )}
          <Button danger disabled={!sub || sub.cancel_at_period_end} onClick={() => setCancelOpen(true)}>
            取消订阅（期末生效）
          </Button>
        </Space>
      </Card>

      <Card title="额度与用量">
        {quota ? (
          <Row gutter={16}>
            {quotaCards.map((c) => (
              <Col span={8} key={c.title}>
                <Card size="small" styles={{ body: { padding: 16 } }}>
                  <Statistic title={c.title} value={c.used} suffix={`/ ${c.total}`} valueStyle={{ color: c.color }} />
                  <Progress percent={pct(c.used, c.total)} size="small" strokeColor={c.color} />
                </Card>
              </Col>
            ))}
          </Row>
        ) : (
          <Typography.Text type="secondary">暂无配额数据（账户尚未初始化配额）。</Typography.Text>
        )}
      </Card>

      <Card
        title="订单历史"
        extra={<Button size="small" icon={<ReloadOutlined />} loading={ordersLoading} onClick={() => loadOrders(ordersPage)}>刷新</Button>}
      >
        <Table
          rowKey="order_no"
          size="small"
          loading={ordersLoading}
          dataSource={orders.items || []}
          pagination={{
            current: ordersPage,
            pageSize: 10,
            total: orders.total || 0,
            showSizeChanger: false,
            onChange: (p) => loadOrders(p),
          }}
          columns={[
            { title: '订单号', dataIndex: 'order_no', width: 190 },
            { title: '套餐', dataIndex: 'plan_code', width: 110 },
            {
              title: '周期', dataIndex: 'billing_cycle', width: 70,
              render: (v) => (v === 'yearly' ? '按年' : '按月'),
            },
            {
              title: '原价', dataIndex: 'amount_cents', width: 90,
              render: (_, r) => fmtYuan((r.amount_cents || 0) + (r.credit_deduct_cents || 0) + (r.discount_cents || 0)),
            },
            {
              title: 'credits 抵扣', dataIndex: 'credit_deduct_cents', width: 110,
              render: (v) => (v ? <Text type="warning">-{fmtYuan(v)}</Text> : '-'),
            },
            { title: '应付', dataIndex: 'amount_cents', key: 'pay', width: 90, render: (v) => fmtYuan(v) },
            {
              title: '状态', dataIndex: 'status', width: 90,
              render: (v) => {
                const m = ORDER_STATUS_META[v] || { label: v, color: 'default' }
                return <Tag color={m.color}>{m.label}</Tag>
              },
            },
            { title: '创建时间', dataIndex: 'created_at', width: 165, render: (v) => fmtTime(v) },
            { title: '支付时间', dataIndex: 'paid_at', width: 165, render: (v) => fmtTime(v) },
            {
              title: '操作', key: 'act', width: 90,
              render: (_, r) => (r.status === 'PENDING' ? (
                <Button size="small" type="link" onClick={() => navigate(`/billing/pay?order_no=${r.order_no}`)}>去支付</Button>
              ) : null),
            },
          ]}
        />
      </Card>

      <Card title="账单（已支付订单与支付流水）">
        <Table
          rowKey="order_no"
          size="small"
          dataSource={invoices.items || []}
          pagination={{
            current: 1,
            pageSize: 10,
            total: invoices.total || 0,
            showSizeChanger: false,
          }}
          columns={[
            { title: '账单号（订单号）', dataIndex: 'order_no', width: 190 },
            { title: '套餐', dataIndex: 'plan_code', width: 110 },
            {
              title: '周期', dataIndex: 'billing_cycle', width: 70,
              render: (v) => (v === 'yearly' ? '按年' : '按月'),
            },
            { title: '金额', dataIndex: 'amount_cents', width: 90, render: (v) => fmtYuan(v) },
            {
              title: '支付流水号', key: 'trade', width: 200,
              render: (_, r) => r.trades?.[0]?.trade_no || '-',
            },
            {
              title: '渠道', key: 'provider', width: 90,
              render: (_, r) => r.trades?.[0]?.provider || '-',
            },
            { title: '支付时间', dataIndex: 'paid_at', width: 165, render: (v) => fmtTime(v) },
            {
              title: '状态', dataIndex: 'status', width: 90,
              render: (v) => {
                const m = ORDER_STATUS_META[v] || { label: v, color: 'default' }
                return <Tag color={m.color}>{m.label}</Tag>
              },
            },
            {
              title: '发票', dataIndex: 'invoice_status', width: 70,
              render: () => <Text type="secondary">-（开票即将开放）</Text>,
            },
          ]}
        />
      </Card>

      <Modal
        title="确认取消订阅？"
        open={cancelOpen}
        okText="确认取消"
        okButtonProps={{ danger: true, loading: canceling }}
        onOk={doCancel}
        onCancel={() => setCancelOpen(false)}
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="取消将在当前账期结束后生效，期间全部权益保留。到期后工作区数据只读保留 30 天。"
        />
        <Input.TextArea
          rows={3}
          maxLength={512}
          placeholder="取消原因（选填，帮助我们改进）"
          value={cancelReason}
          onChange={(e) => setCancelReason(e.target.value)}
        />
      </Modal>

      <Modal
        title="升级 / 续费下单"
        open={upgradeOpen}
        width={640}
        okText="创建订单并支付"
        okButtonProps={{ loading: placing, disabled: !pick.planCode }}
        onOk={doPlaceOrder}
        onCancel={() => setUpgradeOpen(false)}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <div>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>选择套餐</Text>
            <Radio.Group
              style={{ width: '100%' }}
              value={pick.planCode}
              onChange={(e) => setPick((p) => ({ ...p, planCode: e.target.value }))}
            >
              <Space direction="vertical" style={{ width: '100%' }}>
                {plans.map((p) => (
                  <Radio key={p.code} value={p.code} style={{ display: 'flex', alignItems: 'flex-start' }}>
                    <Space direction="vertical" size={0} style={{ marginLeft: 4 }}>
                      <Text strong>{p.name || p.code}</Text>
                      <Text type="secondary">{p.description || '-'}</Text>
                      <Text type="secondary">
                        月付 {fmtYuan(p.price_monthly_cents)} · 年付 {fmtYuan(p.price_yearly_cents)}
                      </Text>
                    </Space>
                  </Radio>
                ))}
                {plans.length === 0 && <Text type="secondary">加载套餐列表中…</Text>}
              </Space>
            </Radio.Group>
          </div>
          <div>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>计费周期</Text>
            <Radio.Group
              value={pick.cycle}
              onChange={(e) => setPick((p) => ({ ...p, cycle: e.target.value }))}
            >
              <Radio.Button value="monthly">按月</Radio.Button>
              <Radio.Button value="yearly">按年</Radio.Button>
            </Radio.Group>
          </div>
          <div>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>
              使用 credits 抵扣（余额 {fmtYuan(balanceCents)}，单笔订单最高抵扣 50%）
            </Text>
            <InputNumber
              min={0}
              max={Math.min(balanceCents / 100, grossCents / 200)}
              step={1}
              precision={2}
              style={{ width: 200 }}
              addonAfter="元"
              value={pick.useCredits}
              onChange={(v) => setPick((p) => ({ ...p, useCredits: v || 0 }))}
            />
          </div>
          <Alert
            type="info"
            showIcon
            message={
              <Space direction="vertical" size={0}>
                <span>订单原价：{fmtYuan(grossCents)}</span>
                <span>credits 抵扣：-{fmtYuan(estDeduct)}</span>
                <Text strong>应付金额：{fmtYuan(payCents)}</Text>
              </Space>
            }
          />
        </Space>
      </Modal>
    </Space>
  )
}
