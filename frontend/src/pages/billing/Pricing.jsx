/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES8 M2：公开定价页（免登录可达；数据源 /api/pricing/plans-public）
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, Card, Col, Row, Space, Spin, Tag, Typography, Segmented } from 'antd'
import { CheckCircleOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { tokens } from '../../theme/tokens'

const fmtYuan = (cents) => `¥${(cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`

export default function Pricing() {
  const [plans, setPlans] = useState(null)
  const [cycle, setCycle] = useState('monthly')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    http
      .get('/pricing/plans-public')
      .then((d) => setPlans(d?.items || []))
      .catch(() => setPlans([]))
      .finally(() => setLoading(false))
  }, [])

  const token = localStorage.getItem('es_token')

  return (
    <div style={{ minHeight: '100vh', background: tokens.bgPage, padding: '48px 24px' }}>
      <div style={{ maxWidth: 1080, margin: '0 auto' }}>
        <Space direction="vertical" size={8} style={{ width: '100%', textAlign: 'center', marginBottom: 32 }}>
          <Typography.Title level={2} style={{ color: tokens.text1, margin: 0 }}>
            大模型应用安全与合规评测（私有化）
          </Typography.Title>
          <Typography.Text style={{ color: tokens.text2 }}>
            选择适合团队的 EvalShield 方案；所有方案含核心评测能力，年付立省两个月。
          </Typography.Text>
          <Segmented
            value={cycle}
            onChange={setCycle}
            options={[
              { label: '按月', value: 'monthly' },
              { label: '按年（省17%）', value: 'yearly' },
            ]}
          />
        </Space>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 64 }}><Spin size="large" /></div>
        ) : (
          <Row gutter={[16, 16]} justify="center">
            {(plans || []).map((p) => {
              const cents = cycle === 'yearly' ? p.price_yearly_cents : p.price_monthly_cents
              return (
                <Col xs={24} sm={12} lg={6} key={p.code}>
                  <Card
                    title={<Space>{p.name}{p.code === 'pro' && <Tag color={tokens.primary}>推荐</Tag>}</Space>}
                    style={{ height: '100%', borderColor: tokens.border }}
                  >
                    <Typography.Title level={3} style={{ color: tokens.primary, margin: '8px 0' }}>
                      {fmtYuan(cents)}
                      <Typography.Text style={{ color: tokens.text3, fontSize: 14 }}>
                        /{cycle === 'yearly' ? '年' : '月'}
                      </Typography.Text>
                    </Typography.Title>
                    <Typography.Paragraph style={{ color: tokens.text2, minHeight: 44 }}>
                      {p.description || ''}
                    </Typography.Paragraph>
                    <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                      {p.max_tasks != null && (
                        <li style={{ color: tokens.text1 }}><CheckCircleOutlined style={{ color: tokens.success }} /> 任务额度 {p.max_tasks}/期</li>
                      )}
                      <li style={{ color: tokens.text1 }}><CheckCircleOutlined style={{ color: tokens.success }} /> Credits {p.credits}/期</li>
                      {(p.features || []).map((f) => (
                        <li key={f} style={{ color: tokens.text1 }}><CheckCircleOutlined style={{ color: tokens.success }} /> {f}</li>
                      ))}
                    </ul>
                    <Button
                      type="primary"
                      block
                      style={{ marginTop: 16 }}
                      // 未登录 → 去注册并回跳订阅页；已登录 → 订阅页发起下单
                      href={token ? '/billing/subscription' : `/register?next=${encodeURIComponent('/billing/subscription')}`}
                    >
                      {token ? '升级到此套餐' : `免费试用 ${p.trial_days || 14} 天`}
                    </Button>
                  </Card>
                </Col>
              )
            })}
            {plans?.length === 0 && (
              <Typography.Text style={{ color: tokens.text3 }}>
                暂无公开套餐。
              </Typography.Text>
            )}
          </Row>
        )}
        <div style={{ textAlign: 'center', marginTop: 32 }}>
          <Link to="/login" style={{ color: tokens.text2 }}>已有账号？登录</Link>
        </div>
      </div>
    </div>
  )
}
