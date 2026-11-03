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
import { Form, Input, Button, Card, Typography, App, Divider } from 'antd'
import { LockOutlined, UserOutlined, SafetyOutlined, LoginOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth'
import http from '../api/http'

const { Title, Text } = Typography

export default function LoginPage() {
  const { login, setToken } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [loading, setLoading] = useState(false)
  const [providers, setProviders] = useState([])
  const { message } = App.useApp()

  // 深链：?u= 由注册成功后生成用于回填用户名；?redirect= 由邀请页生成用于登录后回跳
  // 防开放重定向：仅允许站内绝对路径（以单个 / 开头，排除 // 协议相对地址）
  const redirect = (() => {
    const r = searchParams.get('redirect') || ''
    return r.startsWith('/') && !r.startsWith('//') ? r : '/'
  })()

  // ES8 M10：SSO 回调回跳带 ?token=&refresh= → 收令牌直接进系统
  useEffect(() => {
    const token = searchParams.get('token')
    const refresh = searchParams.get('refresh')
    if (!token) return
    setToken(token, refresh)
      .then(() => {
        message.success('单点登录成功')
        navigate(redirect, { replace: true })
      })
      .catch(() => message.error('单点登录令牌无效，请重试'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ES8 M10：拉取 SSO 提供方列表（公开端点；能力位未点亮时后端返回空）
  useEffect(() => {
    http
      .get('/auth/sso/providers')
      .then((items) => setProviders(Array.isArray(items) ? items : []))
      .catch(() => setProviders([]))
  }, [])

  const onFinish = async (values) => {
    setLoading(true)
    try {
      const data = await login(values.username, values.password, values.totpCode)
      // 优化7 T4：首登强制改密——半态令牌下直接进改密页
      if (data?.must_change_pwd) {
        navigate('/force-change-password', { replace: true })
        return
      }
      message.success('登录成功')
      navigate(redirect, { replace: true })
    } catch (e) {
      console.warn('[Login] 登录失败', e?.message || e)
      /* 错误已由拦截器提示 */
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-bg">
      <Card style={{ width: 400, boxShadow: '0 12px 40px rgba(0,0,0,0.25)' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <SafetyOutlined style={{ fontSize: 44, color: '#1F4E79' }} />
          <Title level={3} style={{ marginTop: 8, marginBottom: 4 }}>
            EvalShield
          </Title>
          <Text type="secondary">大模型应用安全与合规评测（私有化）</Text>
        </div>
        <Form name="login" size="large" onFinish={onFinish} autoComplete="off" initialValues={{ username: searchParams.get('u') || undefined }}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item name="totpCode">
            <Input placeholder="TOTP 动态码（未开启可留空）" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登 录
            </Button>
          </Form.Item>
        </Form>
        {providers.length > 0 && (
          <>
            <Divider plain style={{ margin: '8px 0 16px' }}>
              <Text type="secondary" style={{ fontSize: 12 }}>单点登录</Text>
            </Divider>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {providers.map((p) => (
                <Button
                  key={p.id}
                  block
                  icon={<LoginOutlined />}
                  // 整页跳转走后端 302 流（中转 cookie 需浏览器原生携带）
                  onClick={() => {
                    window.location.href = `/api/auth/sso/configs/${p.id}/start`
                  }}
                >
                  使用「{p.name}」登录
                </Button>
              ))}
            </div>
          </>
        )}
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Text type="secondary">还没有账号？</Text>
          <a onClick={() => navigate('/register')} style={{ marginLeft: 6 }}>注册账号</a>
        </div>
      </Card>
    </div>
  )
}