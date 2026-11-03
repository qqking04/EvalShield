/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useState, useMemo, useEffect } from 'react'
import { Form, Input, Button, Modal, App, Checkbox, Alert, Typography, Tag } from 'antd'
import { SafetyCertificateOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import http from '../../api/http'

// 密码 4 段式策略条（每段对应一个规则：≥8位/大写/小写/数字）
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

export default function Register() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [pwd, setPwd] = useState('')
  // ES8 M1：部署能力面（/auth/capabilities 公开端点，失败时按企业版保守形态渲染）
  const [caps, setCaps] = useState(null)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { message, modal } = App.useApp()

  useEffect(() => {
    http.get('/auth/capabilities')
      .then((d) => setCaps(d || null))
      .catch(() => setCaps({ registration_open: true, edition_hint: 'enterprise', plans_public: [] }))
  }, [])

  const isSaas = caps?.edition_hint === 'saas'

  const onFinish = async (values) => {
    setLoading(true)
    try {
      const data = await http.post('/auth/register', values)
      const username = data?.username || values.username
      // ES8 M1：saas 自助注册返回租户信息，成功文案带试用提示
      const trialEnds = data?.tenant?.trial_ends_at
      const trialTip = trialEnds
        ? `已为您创建工作区「${data?.tenant?.name || ''}」，${trialEnds.slice(0, 10)} 前免费试用全部功能。`
        : ''
      // 深链：?invite_token= 由邀请页生成。注册接口不消费该 token，
      // 注册成功后回跳登录页并携带 redirect，登录后自动进入「接受邀请」流程
      const inviteToken = searchParams.get('invite_token')
      let next = `/login?u=${encodeURIComponent(username)}`
      if (inviteToken) {
        const back = `/invite/accept?token=${encodeURIComponent(inviteToken)}`
        next += `&redirect=${encodeURIComponent(back)}`
      }
      modal.success({
        title: '注册成功',
        content: inviteToken
          ? `账号已创建，即将跳转登录；登录后会自动接受邀请。${trialTip}`
          : `账号已创建，即将跳转至登录页。${trialTip}`,
        onOk: () => navigate(next),
      })
    } catch {
      /* 错误已由拦截器提示 */
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
        <h2 className="auth-title">创建 EvalShield 账号</h2>
        <p className="auth-sub">
          {isSaas ? '注册即创建工作区，默认免费版，随时可升级' : '注册后即可开始 AI 系统测试之旅'}
        </p>
        {caps?.registration_open === false && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="当前部署未开放自助注册，请联系管理员为您开通账号。"
          />
        )}
        <Form
          form={form}
          layout="vertical"
          size="large"
          onFinish={onFinish}
          autoComplete="off"
          initialValues={{}}
        >
          <Form.Item
            label="用户名"
            name="username"
            rules={[{ required: true, message: '请输入用户名' }, { min: 3, message: '至少 3 个字符' }]}
          >
            <Input placeholder="3-32 位英文/数字" />
          </Form.Item>
          <Form.Item
            label={isSaas ? '企业/工作区名称' : '组织名称（可选）'}
            name="tenant_name"
            rules={isSaas ? [{ max: 128, message: '不超过 128 个字符' }] : []}
          >
            <Input placeholder={isSaas ? '留空则自动以「用户名的工作区」创建' : '留空则归入默认组织'} />
          </Form.Item>
          <Form.Item
            label="邮箱"
            name="email"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '邮箱格式不正确' },
            ]}
          >
            <Input placeholder="you@example.com" />
          </Form.Item>
          <Form.Item
            label="密码"
            name="password"
            rules={[
              { required: true, message: '请输入密码' },
              {
                validator: (_, v) => {
                  if (!v) return Promise.resolve()
                  const ok =
                    v.length >= 8 &&
                    /[A-Z]/.test(v) &&
                    /[a-z]/.test(v) &&
                    /\d/.test(v)
                  return ok ? Promise.resolve() : Promise.reject(new Error('需满足下方全部 4 条策略'))
                },
              },
            ]}
          >
            <Input.Password
              placeholder="设置登录密码"
              onChange={(e) => setPwd(e.target.value)}
            />
          </Form.Item>
          <PolicyBar password={pwd} />
          <Form.Item
            label="确认密码"
            name="password_confirm"
            dependencies={['password']}
            rules={[
              { required: true, message: '请再次输入密码' },
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
            <Input.Password placeholder="再次输入密码" />
          </Form.Item>
          <Form.Item style={{ marginTop: 16 }}>
            {isSaas && (
              <Form.Item
                name="agree_terms"
                valuePropName="checked"
                rules={[{
                  validator: (_, v) => (v ? Promise.resolve() : Promise.reject(new Error('请阅读并同意服务条款'))),
                }]}
                style={{ marginBottom: 12 }}
              >
                <Checkbox>
                  <span style={{ fontSize: 13 }}>我已阅读并同意</span>
                  <a onClick={(e) => e.preventDefault()}>《服务条款》</a>
                  <span style={{ fontSize: 13 }}>与</span>
                  <a onClick={(e) => e.preventDefault()}>《隐私政策》</a>
                </Checkbox>
              </Form.Item>
            )}
            {isSaas && caps?.plans_public?.length > 0 && (
              <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
                可选套餐：
                {caps.plans_public.map((p) => (
                  <Tag key={p.code} style={{ fontSize: 12 }}>
                    {p.name}
                    {p.price_monthly_cents > 0 ? ` ¥${(p.price_monthly_cents / 100).toFixed(0)}/月` : ' 免费'}
                  </Tag>
                ))}
              </Typography.Paragraph>
            )}
            <Button
              type="primary"
              htmlType="submit"
              block
              loading={loading}
              style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
            >
              立 即 注 册
            </Button>
          </Form.Item>
          <div style={{ textAlign: 'center', color: '#8ba3b5', fontSize: 13 }}>
            已有账号？<a onClick={() => navigate('/login')}>前往登录</a>
          </div>
        </Form>
      </div>
    </div>
  )
}
