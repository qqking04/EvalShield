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
import { Form, Input, Button, Upload, Card, Row, Col, App, Collapse, Avatar } from 'antd'
import { UserOutlined, LockOutlined, UploadOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { useAuth } from '../../auth'

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
      <div className="policy-bar">{rules.map((r, i) => <span key={i} className={`seg ${r.pass ? 'on' : ''}`} />)}</div>
      <div className="policy-tips">
        {rules.map((r, i) => (
          <span key={i} className={r.pass ? 'on' : ''}>{r.pass ? '✓' : '○'} {r.label}</span>
        ))}
      </div>
    </>
  )
}

export default function ProfileSettings() {
  const { user, setToken, fetchMe } = useAuth()
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [pwdForm] = Form.useForm()
  const [avatarUrl, setAvatarUrl] = useState(user?.avatar || '')
  const [avatarLoading, setAvatarLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [pwd, setPwd] = useState('')
  const [pwdSaving, setPwdSaving] = useState(false)

  const initial = {
    nickname: user?.display_name || user?.username || '',
    phone: user?.phone || '',
    email: user?.email || '',
    department: user?.department || '',
  }

  const handleBeforeUpload = (file) => {
    if (!/\.(jpg|jpeg|png)$/i.test(file.name)) {
      message.error('仅支持 .jpg / .png')
      return Upload.LIST_IGNORE
    }
    if (file.size > 2 * 1024 * 1024) {
      message.error('图片不能超过 2MB')
      return Upload.LIST_IGNORE
    }
    setAvatarLoading(true)
    const reader = new FileReader()
    reader.onload = () => {
      setAvatarUrl(reader.result)
      setAvatarLoading(false)
    }
    reader.readAsDataURL(file)
    return false // 阻止自动上传
  }

  const onSaveProfile = async (values) => {
    setSaving(true)
    try {
      await http.put('/auth/profile', {
        ...values,
        avatar: avatarUrl,
      })
      message.success('已保存')
      await fetchMe()
    } catch {
      /* 拦截器提示 */
    } finally {
      setSaving(false)
    }
  }

  const onChangePwd = async (values) => {
    if (values.new_password !== values.new_password_confirm) {
      message.error('两次密码不一致')
      return
    }
    setPwdSaving(true)
    try {
      await http.post('/auth/change-password', {
        old_password: values.old_password,
        new_password: values.new_password,
      })
      message.success('密码已更新')
      pwdForm.resetFields()
      setPwd('')
    } catch {
      /* 拦截器提示 */
    } finally {
      setPwdSaving(false)
    }
  }

  return (
    <div>
      <h2 className="title-bar" style={{ marginBottom: 16, color: '#e6f7ff' }}>个人资料</h2>
      <Row gutter={16}>
        {/* 左 1/3 头像卡 */}
        <Col xs={24} md={8}>
          <Card
            style={{ background: '#11161d', borderColor: '#1f2833' }}
            bodyStyle={{ textAlign: 'center' }}
          >
            <Avatar
              size={96}
              src={avatarUrl}
              icon={<UserOutlined />}
              style={{ background: '#13c2c2', color: '#0b0f14', marginBottom: 12 }}
            />
            <div style={{ marginBottom: 12, fontSize: 14, color: '#e6f7ff' }}>
              {user?.username}
            </div>
            <Upload
              showUploadList={false}
              accept=".jpg,.png"
              beforeUpload={handleBeforeUpload}
            >
              <Button
                icon={<UploadOutlined />}
                loading={avatarLoading}
                style={{ borderRadius: 2 }}
              >
                上传头像
              </Button>
            </Upload>
            <div style={{ marginTop: 8, fontSize: 12, color: '#869BAA' }}>
              支持 .jpg / .png，≤ 2MB
            </div>
          </Card>
        </Col>

        {/* 右 2/3 表单 */}
        <Col xs={24} md={16}>
          <Card
            style={{ background: '#11161d', borderColor: '#1f2833' }}
            title={<span style={{ color: '#e6f7ff' }}>基本信息</span>}
          >
            <Form
              form={form}
              layout="vertical"
              initialValues={initial}
              onFinish={onSaveProfile}
            >
              <Row gutter={16}>
                <Col xs={24} sm={12}>
                  <Form.Item label="昵称" name="nickname">
                    <Input placeholder="显示名称" />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item label="手机号" name="phone">
                    <Input placeholder="可选" />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item label="部门" name="department">
                    <Input placeholder="可选" />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item label="邮箱">
                    <Input value={initial.email} disabled style={{ color: '#869BAA' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={saving}
                  style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
                >
                  保存
                </Button>
              </Form.Item>
            </Form>
          </Card>

          {/* 修改密码 折叠面板 */}
          <Card
            style={{ background: '#11161d', borderColor: '#1f2833', marginTop: 16 }}
            bodyStyle={{ padding: '0 24px' }}
          >
            <Collapse
              ghost
              style={{ background: 'transparent' }}
              items={[
                {
                  key: 'pwd',
                  label: <span style={{ color: '#e6f7ff' }}><LockOutlined style={{ marginRight: 8 }} />修改登录密码</span>,
                  children: (
                    <Form
                      form={pwdForm}
                      layout="vertical"
                      onFinish={onChangePwd}
                      style={{ padding: '16px 0' }}
                    >
                      <Row gutter={16}>
                        <Col xs={24} sm={12}>
                          <Form.Item
                            label="当前密码"
                            name="old_password"
                            rules={[{ required: true, message: '请输入当前密码' }]}
                          >
                            <Input.Password />
                          </Form.Item>
                        </Col>
                        <Col xs={24} sm={12}>
                          <Form.Item
                            label="新密码"
                            name="new_password"
                            rules={[
                              { required: true, message: '请输入新密码' },
                              {
                                validator: (_, v) => {
                                  if (!v) return Promise.resolve()
                                  const ok = v.length >= 8 && /[A-Z]/.test(v) && /[a-z]/.test(v) && /\d/.test(v)
                                  return ok ? Promise.resolve() : Promise.reject(new Error('需满足全部 4 条策略'))
                                },
                              },
                            ]}
                          >
                            <Input.Password onChange={(e) => setPwd(e.target.value)} />
                          </Form.Item>
                          <PolicyBar password={pwd} />
                        </Col>
                        <Col xs={24} sm={12}>
                          <Form.Item
                            label="确认新密码"
                            name="new_password_confirm"
                            dependencies={['new_password']}
                            rules={[
                              { required: true, message: '请再次输入新密码' },
                              ({ getFieldValue }) => ({
                                validator(_, value) {
                                  if (!value || getFieldValue('new_password') === value) return Promise.resolve()
                                  return Promise.reject(new Error('两次输入不一致'))
                                },
                              }),
                            ]}
                          >
                            <Input.Password />
                          </Form.Item>
                        </Col>
                      </Row>
                      <Form.Item>
                        <Button
                          type="primary"
                          htmlType="submit"
                          loading={pwdSaving}
                          style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
                        >
                          更新密码
                        </Button>
                      </Form.Item>
                    </Form>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
