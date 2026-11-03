/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useMemo, useState } from 'react'
import { Form, Input, Button, Typography, App } from 'antd'
import { LockOutlined, SafetyOutlined } from '@ant-design/icons'
import { useNavigate, Navigate } from 'react-router-dom'
import http from '../../api/http'
import { useAuth } from '../../auth'

const { Text } = Typography

// 优化7 T4：首登强制改密（合规页形态——居中单卡、克制装饰、无跳过出口）
export default function ForceChangePassword() {
  const [form] = Form.useForm()
  const [pwd, setPwd] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { user, setToken } = useAuth()

  const rules = useMemo(
    () => [
      { label: '至少 10 位', pass: pwd.length >= 10 },
      { label: '含大写字母', pass: /[A-Z]/.test(pwd) },
      { label: '含小写字母', pass: /[a-z]/.test(pwd) },
      { label: '含数字', pass: /\d/.test(pwd) },
      { label: '含特殊符号', pass: /[^A-Za-z0-9]/.test(pwd) },
    ],
    [pwd]
  )
  const passed = rules.filter((r) => r.pass).length

  if (!localStorage.getItem('es_token')) {
    return <Navigate to="/login" replace />
  }

  const onFinish = async (values) => {
    setLoading(true)
    try {
      const data = await http.post('/auth/change-password', {
        old_password: '',
        new_password: values.password,
        confirm_password: values.confirm_password,
      })
      // 后端已清 must_change_pwd 并重签全态令牌
      if (data?.tokens?.access_token) {
        localStorage.setItem('es_token', data.tokens.access_token)
        localStorage.setItem('es_refresh', data.tokens.refresh_token || '')
      }
      await setToken(data?.tokens?.access_token || null, data?.tokens?.refresh_token || null)
      message.success('密码已更新')
      navigate('/', { replace: true })
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#F2F3F5',
      }}
    >
      <div
        style={{
          width: 420,
          background: '#fff',
          borderRadius: 8,
          padding: '40px 36px 28px',
          boxShadow: '0 8px 32px rgba(31,56,88,0.12)',
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <LockOutlined style={{ fontSize: 40, color: '#165DFF' }} />
          <div style={{ fontSize: 20, fontWeight: 600, marginTop: 12 }}>
            首次登录，请修改初始密码
          </div>
          <Text type="secondary" style={{ fontSize: 13 }}>
            {user?.username ? `${user.username} · ` : ''}依据安全合规要求，修改密码后方可使用系统
          </Text>
        </div>
        <Form form={form} layout="vertical" size="large" onFinish={onFinish} requiredMark={false}>
          <Form.Item
            label="新密码"
            name="password"
            rules={[
              { required: true, message: '请输入新密码' },
              {
                validator: (_, v) => {
                  if (!v) return Promise.resolve()
                  if (v.length < 10) return Promise.reject(new Error('密码至少 10 位'))
                  const classes =
                    (/[A-Z]/.test(v) ? 1 : 0) +
                    (/[a-z]/.test(v) ? 1 : 0) +
                    (/\d/.test(v) ? 1 : 0) +
                    (/[^A-Za-z0-9]/.test(v) ? 1 : 0)
                  if (classes < 3)
                    return Promise.reject(new Error('须含大写、小写、数字、符号中至少 3 类'))
                  return Promise.resolve()
                },
              },
            ]}
          >
            <Input.Password
              placeholder="输入新密码"
              autoComplete="new-password"
              onChange={(e) => setPwd(e.target.value)}
            />
          </Form.Item>
          {/* 强度条：5 段勾选（10 位 + 四类字符） */}
          <div style={{ display: 'flex', gap: 4, margin: '-12px 0 8px' }}>
            {rules.map((r, i) => (
              <span
                key={i}
                style={{
                  flex: 1,
                  height: 4,
                  borderRadius: 2,
                  background: r.pass ? '#165DFF' : '#E5E6EB',
                  transition: 'background 0.2s',
                }}
              />
            ))}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', marginBottom: 20 }}>
            {rules.map((r, i) => (
              <span
                key={i}
                style={{ fontSize: 12, color: r.pass ? '#165DFF' : '#86909C' }}
              >
                {r.pass ? '✓' : '○'} {r.label}
              </span>
            ))}
            <span style={{ fontSize: 12, color: '#86909C', marginLeft: 'auto' }}>
              {passed === rules.length ? '强度：强' : `已满足 ${passed}/${rules.length}`}
            </span>
          </div>
          <Form.Item
            label="确认新密码"
            name="confirm_password"
            dependencies={['password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) return Promise.resolve()
                  return Promise.reject(new Error('两次输入的密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password placeholder="再次输入新密码" autoComplete="new-password" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 8 }}>
            <Button
              type="primary"
              htmlType="submit"
              block
              loading={loading}
              disabled={passed < 2}
              style={{ background: '#165DFF', borderColor: '#165DFF' }}
            >
              确认修改并进入系统
            </Button>
          </Form.Item>
        </Form>
        <div style={{ textAlign: 'center', marginTop: 12 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            <SafetyOutlined /> 不可跳过；如需帮助请联系系统管理员
          </Text>
        </div>
      </div>
    </div>
  )
}
