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
import {
  Card, Typography, Space, Button, Tag, Input, Form, App, Alert, Divider, QRCode, Steps, Descriptions,
} from 'antd'
import { SafetyCertificateOutlined, KeyOutlined, LockOutlined, CheckCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import http from '../api/http'
import { useAuth } from '../auth'

export default function Security() {
  const { user, fetchMe } = useAuth()
  const { message } = App.useApp()
  const [mfaEnabled, setMfaEnabled] = useState(Boolean(user?.mfa_enabled))
  const [setupData, setSetupData] = useState(null)
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [disableLoading, setDisableLoading] = useState(false)
  const [pwdForm] = Form.useForm()
  const [mfaForm] = Form.useForm()

  const startMfa = async () => {
    try {
      const d = await http.post('/auth/mfa/setup', {})
      setSetupData(d)
    } catch (e) {
      console.warn('[Security] MFA 设置失败', e?.message || e)
      /* 拦截器已提示 */
    }
  }

  const confirmMfa = async () => {
    try {
      const { code } = await mfaForm.validateFields()
      setConfirmLoading(true)
      await http.post('/auth/mfa/confirm', { code })
      message.success('二次认证已开启，下次登录需输入动态验证码')
      setMfaEnabled(true)
      setSetupData(null)
      mfaForm.resetFields()
      await fetchMe()
    } finally {
      setConfirmLoading(false)
    }
  }

  const cancelMfa = () => {
    setSetupData(null)
    mfaForm.resetFields()
  }

  const disableMfa = async () => {
    try {
      const { code } = await mfaForm.validateFields()
      setDisableLoading(true)
      await http.post('/auth/mfa/disable', { code })
      message.success('二次认证已关闭')
      setMfaEnabled(false)
      mfaForm.resetFields()
      await fetchMe()
    } finally {
      setDisableLoading(false)
    }
  }

  const changePwd = async () => {
    try {
      const values = await pwdForm.validateFields()
      await http.post('/auth/change-password', {
        old_password: values.old_password,
        new_password: values.new_password,
      })
      message.success('密码修改成功，下次登录请使用新密码')
      pwdForm.resetFields()
    } catch (e) {
      console.warn('[Security] 修改密码失败', e?.message || e)
      /* 拦截器已提示 */
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Title level={4} style={{ margin: 0 }}>个人安全</Typography.Title>

      <Card
        title={<Space><SafetyCertificateOutlined />双重认证（TOTP）</Space>}
        extra={mfaEnabled ? <Tag color="green"><CheckCircleOutlined /> 已开启</Tag> : <Tag>未开启</Tag>}
      >
        {!mfaEnabled && !setupData && (
          <Space direction="vertical" size={12}>
            <Typography.Paragraph style={{ margin: 0 }}>
              启用后，每次登录除密码外还需输入身份验证器生成的 6 位动态验证码，提升账号安全性。
            </Typography.Paragraph>
            <Button type="primary" icon={<LockOutlined />} onClick={startMfa}>开启双重认证</Button>
          </Space>
        )}

        {!mfaEnabled && setupData && (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Steps
              size="small"
              current={1}
              items={[
                { title: '打开验证器', description: '使用 Google Authenticator / 微信小程序等' },
                { title: '扫描二维码或手动输入密钥' },
                { title: '输入动态验证码确认' },
              ]}
            />
            <Space size={24} align="start" wrap>
              {setupData.otpauth_url ? (
                <QRCode value={setupData.otpauth_url} size={140} />
              ) : (
                <Alert type="warning" showIcon message="未获取到绑定链接" />
              )}
              <Space direction="vertical" size={8}>
                <Typography.Text type="secondary">无法扫码？手动添加密钥：</Typography.Text>
                <Typography.Paragraph copyable code style={{ margin: 0 }}>
                  {setupData.secret}
                </Typography.Paragraph>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  账户：{user?.username} · 签发：EvalShield
                </Typography.Text>
                <Alert
                  type="info"
                  showIcon
                  message="此密钥仅展示一次，开启后立即生效"
                  style={{ maxWidth: 360 }}
                />
              </Space>
            </Space>
            <Form form={mfaForm} layout="inline">
              <Form.Item name="code" rules={[{ required: true, message: '请输入 6 位验证码' }, { len: 6, message: '验证码为 6 位数字' }]}>
                <Input placeholder="6 位动态验证码" maxLength={6} style={{ width: 180 }} />
              </Form.Item>
              <Form.Item>
                <Space>
                  <Button type="primary" loading={confirmLoading} onClick={confirmMfa}>确认开启</Button>
                  <Button onClick={cancelMfa}>取消</Button>
                </Space>
              </Form.Item>
            </Form>
          </Space>
        )}

        {mfaEnabled && (
          <Space direction="vertical" size={12}>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="状态"><Tag color="green">已开启</Tag></Descriptions.Item>
              <Descriptions.Item label="登录要求">密码 + 6 位动态验证码</Descriptions.Item>
            </Descriptions>
            <Form form={mfaForm} layout="inline">
              <Form.Item name="code" rules={[{ required: true, message: '请输入 6 位验证码' }, { len: 6, message: '验证码为 6 位数字' }]}>
                <Input placeholder="当前动态验证码" maxLength={6} style={{ width: 180 }} />
              </Form.Item>
              <Form.Item>
                <Button danger loading={disableLoading} icon={<ReloadOutlined />} onClick={disableMfa}>关闭双重认证</Button>
              </Form.Item>
            </Form>
          </Space>
        )}
      </Card>

      <Divider style={{ margin: '8px 0' }} />

      <Card title={<Space><KeyOutlined />修改密码</Space>}>
        <Form form={pwdForm} layout="vertical" style={{ maxWidth: 420 }}>
          <Form.Item name="old_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
            <Input.Password placeholder="当前登录密码" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 8, message: '密码至少 8 位' },
            ]}
          >
            <Input.Password placeholder="至少 8 位，建议包含字母与数字" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('new_password') === value) return Promise.resolve()
                  return Promise.reject(new Error('两次输入的密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password placeholder="再次输入新密码" />
          </Form.Item>
          <Button type="primary" onClick={changePwd}>保存新密码</Button>
        </Form>
      </Card>
    </Space>
  )
}