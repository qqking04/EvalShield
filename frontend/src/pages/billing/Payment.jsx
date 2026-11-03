/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES8 M2：收银台（/billing/pay?order_no=xxx）
// 轮询订单状态；mock 渠道提供「模拟支付」按钮，真实渠道接入后按 pay_url 外跳。
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Descriptions, Result, Space, Spin, Tag, Typography, message } from 'antd'
import { SafetyCertificateOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { fmtTime } from '../../utils'

const ORDER_STATUS_META = {
  PENDING: { label: '待支付', color: 'processing' },
  PAID: { label: '已支付', color: 'success' },
  FULFILLED: { label: '已开通', color: 'success' },
  CLOSED: { label: '已关闭', color: 'default' },
  FAILED: { label: '支付失败', color: 'error' },
  REFUNDED: { label: '已退款', color: 'warning' },
}

const fmtYuan = (cents) => `¥${(cents / 100).toFixed(2)}`

export default function Payment() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const orderNo = params.get('order_no') || ''
  const [order, setOrder] = useState(null)
  const [notFound, setNotFound] = useState(false)
  const [paying, setPaying] = useState(false)
  const timerRef = useRef(null)

  const load = useCallback(async () => {
    if (!orderNo) return
    try {
      setOrder(await http.get(`/billing/orders/${orderNo}`))
    } catch {
      setNotFound(true)
    }
  }, [orderNo])

  useEffect(() => { load() }, [load])

  // PENDING 期间轮询（真实渠道外跳支付后回站内即自动感知）
  useEffect(() => {
    if (order?.status === 'PENDING') {
      timerRef.current = setInterval(load, 3000)
      return () => clearInterval(timerRef.current)
    }
    return undefined
  }, [order?.status, load])

  const doMockPay = async () => {
    setPaying(true)
    try {
      const d = await http.post(`/billing/orders/${orderNo}/mock-pay`, {})
      setOrder(d)
      message.success(d.idempotent ? '该订单已支付（幂等回放）' : '支付成功，套餐已开通')
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setPaying(false)
    }
  }

  if (!orderNo || notFound) {
    return (
      <Result
        status="404"
        title="订单不存在"
        subTitle="请从订阅页重新发起下单。"
        extra={<Button onClick={() => navigate('/billing/subscription')}>返回我的订阅</Button>}
      />
    )
  }

  if (!order) {
    return <div style={{ textAlign: 'center', padding: 64 }}><Spin size="large" /></div>
  }

  const meta = ORDER_STATUS_META[order.status] || { label: order.status, color: 'default' }
  const done = order.status === 'FULFILLED' || order.status === 'PAID'

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 640, margin: '0 auto' }}>
      <Typography.Title level={4}>收银台</Typography.Title>
      {order.status === 'PENDING' && (
        <Alert type="info" showIcon message="订单待支付。mock 环境点击下方按钮模拟渠道回调；支付成功后本页自动刷新。" />
      )}
      {done && (
        <Result
          status="success"
          title="支付成功"
          subTitle={`套餐 ${order.plan_code} 已开通${order.credit_deduct_cents ? `（credits 抵扣 ${fmtYuan(order.credit_deduct_cents)}）` : ''}。`}
          extra={<Button type="primary" onClick={() => navigate('/billing/subscription')}>查看我的订阅</Button>}
        />
      )}
      {order.status === 'FAILED' && (
        <Alert type="error" showIcon message="支付失败，冻结的 credits 抵扣已退回账户。请重新下单。" />
      )}
      {order.status === 'CLOSED' && (
        <Alert type="warning" showIcon message="订单已关闭（新订单取代）。" />
      )}
      <Card>
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="订单号">{order.order_no}</Descriptions.Item>
          <Descriptions.Item label="套餐">{order.plan_code}</Descriptions.Item>
          <Descriptions.Item label="周期">{order.billing_cycle === 'yearly' ? '按年' : '按月'}</Descriptions.Item>
          <Descriptions.Item label="credits 抵扣">{fmtYuan(order.credit_deduct_cents)}</Descriptions.Item>
          <Descriptions.Item label="应付金额">
            <Typography.Text strong style={{ fontSize: 18 }}>{fmtYuan(order.amount_cents)}</Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="状态"><Tag color={meta.color}>{meta.label}</Tag></Descriptions.Item>
          <Descriptions.Item label="渠道">{order.provider}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{fmtTime(order.created_at)}</Descriptions.Item>
          {order.paid_at && <Descriptions.Item label="支付时间">{fmtTime(order.paid_at)}</Descriptions.Item>}
        </Descriptions>
        {order.status === 'PENDING' && (
          <Space style={{ marginTop: 16 }}>
            <Button type="primary" icon={<SafetyCertificateOutlined />} loading={paying} onClick={doMockPay}>
              模拟支付 {fmtYuan(order.amount_cents)}
            </Button>
            <Button onClick={() => navigate('/billing/subscription')}>放弃支付</Button>
          </Space>
        )}
      </Card>
    </Space>
  )
}
