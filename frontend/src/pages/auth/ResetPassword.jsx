/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useState, useMemo } from 'react'
import { Form, Input, Button, App, Result } from 'antd'
import { SafetyCertificateOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import http from '../../api/http'

function PolicyBar({ password }) {
  const rules = useMemo(() => {
    return [
      { label: '≥8 位', pass: password.length >= 8 },
      { label: '含大写', pass: /[A-Z]/.test(password) },
      { label: '含小写', pass: /[a-z]/.test(password) },
      { label: '含数字', pass: /\d/.test(password) },
    ]
  }, [password])
  return (
    <>
      <div className="policy-bar">
        {rules.map((r, i) => (
          <span key={i} className={`seg ${r.pass ? 'on' : ''}`} />
        ))}
      </div>
      <div className="policy-tips">
        {rules.map((r, i) => (
          <span key={i} className={r.pass ? 'on' : ''}>
            {r.pass ? '✓' : '○'} {r.label}
          </span>
        ))}
      </div>
    </>
  )
}

export default function ResetPassword() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [pwd, setPwd] = useState('')
  const [done, setDone] = useState(false)
  const navigate = useNavigate()
  const { message } = App.useApp()

  const onFinish = async (values) => {
    setLoading(true)
    try {
      await http.post('/auth/reset-password', {
        token,
        password: values.password,
      })
      setDone(true)
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setLoading(false)
    }
  }

  if (!token) {
    return (
      <div className="auth-bg">
        <div className="auth-card fadeUp">
          <Result
            status="error"
            title="链接无效"
            subTitle="重置链接中缺少 token，请重新从邮件进入"
            extra={
              <Button type="primary" onClick={() => navigate('/forgot-password')}>
                返回找回
              </Button>
            }
          />
        </div>
      </div>
    )
  }

  if (done) {
    return (
      <div className="auth-bg">
        <div className="auth-card fadeUp">
          <Result
            status="success"
            title="密码已重置"
            subTitle="您可以使用新密码登录了"
            extra={
              <Button
                type="primary"
                onClick={() => navigate('/login')}
                style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
              >
                前往登录
              </Button>
            }
          />
        </div>
      </div>
    )
  }

  return (
    <div className="auth-bg">
      <div className="auth-card fadeUp">
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <SafetyCertificateOutlined style={{ fontSize: 40, color: '#13c2c2' }} />
        </div>
        <h2 className="auth-title">重置密码</h2>
        <p className="auth-sub">请设置新的登录密码</p>
        <Form form={form} layout="vertical" size="large" onFinish={onFinish}>
          <Form.Item
            label="新密码"
            name="password"
            rules={[
              { required: true, message: '请输入新密码' },
              {
                validator: (_, v) => {
                  if (!v) return Promise.resolve()
                  const ok =
                    v.length >= 8 && /[A-Z]/.test(v) && /[a-z]/.test(v) && /\d/.test(v)
                  return ok ? Promise.resolve() : Promise.reject(new Error('需满足下方全部 4 条策略'))
                },
              },
            ]}
          >
            <Input.Password
              placeholder="输入新密码"
              onChange={(e) => setPwd(e.target.value)}
            />
          </Form.Item>
          <PolicyBar password={pwd} />
          <Form.Item
            label="确认新密码"
            name="password_confirm"
            dependencies={['password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) {
                    return Promise.resolve()
                  }
                  return Promise.reject(new Error('两次输入的密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password placeholder="再次输入新密码" />
          </Form.Item>
          <Form.Item style={{ marginTop: 16 }}>
            <Button
              type="primary"
              htmlType="submit"
              block
              loading={loading}
              style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
            >
              确认重置
            </Button>
          </Form.Item>
        </Form>
      </div>
    </div>
  )
}
