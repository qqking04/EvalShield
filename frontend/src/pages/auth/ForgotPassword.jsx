/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useState } from 'react'
import { Form, Input, Button, App } from 'antd'
import { SafetyCertificateOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import http from '../../api/http'

export default function ForgotPassword() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const navigate = useNavigate()
  const { message } = App.useApp()

  const onFinish = async (values) => {
    setLoading(true)
    try {
      await http.post('/auth/forgot-password', values)
      // 安全提示：不泄露邮箱是否存在
      setDone(true)
    } catch {
      // 拦截器会提示，但我们统一成安全文案
      setDone(true)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-bg">
      <div className="auth-card fadeUp" style={{ animationDelay: '0ms' }}>
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <SafetyCertificateOutlined style={{ fontSize: 40, color: '#13c2c2' }} />
        </div>
        <h2 className="auth-title">找回密码</h2>
        <p className="auth-sub">输入注册邮箱，我们将发送重置链接</p>
        {!done ? (
          <Form form={form} layout="vertical" size="large" onFinish={onFinish}>
            <Form.Item
              label="注册邮箱"
              name="email"
              rules={[
                { required: true, message: '请输入邮箱' },
                { type: 'email', message: '邮箱格式不正确' },
              ]}
            >
              <Input placeholder="you@example.com" />
            </Form.Item>
            <Form.Item style={{ marginTop: 8 }}>
              <Button
                type="primary"
                htmlType="submit"
                block
                loading={loading}
                style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
              >
                发送重置链接
              </Button>
            </Form.Item>
            <div style={{ textAlign: 'center', color: '#8ba3b5', fontSize: 13 }}>
              想起密码了？<a onClick={() => navigate('/login')}>前往登录</a>
            </div>
          </Form>
        ) : (
          <div style={{ textAlign: 'center', padding: '16px 0' }}>
            <div style={{ color: '#13c2c2', fontSize: 16, fontWeight: 600 }}>已发送</div>
            <p style={{ color: '#8ba3b5', marginTop: 12, fontSize: 13 }}>
              如果邮箱存在，重置信息已发送，请查收邮件。
            </p>
            <Button
              type="primary"
              onClick={() => navigate('/login')}
              style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
            >
              返回登录
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
