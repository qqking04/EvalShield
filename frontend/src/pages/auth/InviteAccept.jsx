/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useState, useEffect } from 'react'
import { Button, App, Result, Card, Descriptions, Spin } from 'antd'
import { SafetyCertificateOutlined, TeamOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import axios from 'axios'
import { useAuth } from '../../auth'

export default function InviteAccept() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const navigate = useNavigate()
  const { user } = useAuth()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [info, setInfo] = useState(null)
  const [accepted, setAccepted] = useState(false)

  // 用无拦截器的 axios（避免 401 自动跳 /login）
  const raw = axios.create({ baseURL: '/api', timeout: 15000 })

  useEffect(() => {
    if (!token) return
    setLoading(true)
    raw
      .get(`/orgs/invitations/${token}`)
      .then((r) => setInfo(r.data))
      .catch((e) => {
        /* 可能未登录或邀请已过期 */
        console.warn('[InviteAccept] invitation load failed', e?.message || e)
      })
      .finally(() => setLoading(false))
  }, [token])

  if (!token) {
    return (
      <div className="auth-bg">
        <div className="auth-card fadeUp">
          <Result status="error" title="邀请链接无效" subTitle="缺少 token 参数" />
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="auth-bg">
        <div className="auth-card fadeUp" style={{ textAlign: 'center', padding: 40 }}>
          <Spin tip="加载中..." />
        </div>
      </div>
    )
  }

  if (!user) {
    return (
      <div className="auth-bg">
        <div className="auth-card fadeUp">
          <div style={{ textAlign: 'center', marginBottom: 20 }}>
            <TeamOutlined style={{ fontSize: 40, color: '#13c2c2' }} />
          </div>
          <h2 className="auth-title">邀请加入空间</h2>
          <p className="auth-sub">请先登录，登录后会自动接受此邀请</p>
          <div style={{ textAlign: 'center', padding: '16px 0' }}>
            <Button
              type="primary"
              size="large"
              onClick={() => navigate(`/login?redirect=${encodeURIComponent(`/invite/accept?token=${token}`)}`)}
              style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
            >
              去登录并接受
            </Button>
            <div style={{ marginTop: 12, color: '#8ba3b5', fontSize: 13 }}>
              还没有账号？<a onClick={() => navigate(`/register?invite_token=${encodeURIComponent(token)}`)}>注册新账号</a>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const doAccept = async () => {
    setLoading(true)
    try {
      await raw.post(`/orgs/invitations/${token}/accept`)
      setAccepted(true)
      message.success('已加入新空间')
    } catch (e) {
      message.error(e?.response?.data?.message || '接受失败')
    } finally {
      setLoading(false)
    }
  }

  if (accepted) {
    return (
      <div className="auth-bg">
        <div className="auth-card fadeUp">
          <Result
            status="success"
            title="已成功加入空间"
            subTitle="顶部 Header 中可用「组织切换器」切换当前工作空间。"
            extra={
              <Button
                type="primary"
                onClick={() => navigate('/')}
                style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
              >
                返回工作台
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
        <h2 className="auth-title">接受空间邀请</h2>
        <p className="auth-sub">当前账号：{user?.username || '—'}</p>
        {info ? (
          <Card size="small" style={{ background: '#0b0f14', borderColor: '#1f2833', marginBottom: 16 }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="空间名称">{info.org_name || info.org?.name || '—'}</Descriptions.Item>
              <Descriptions.Item label="邀请角色">{info.role_name || info.role || '—'}</Descriptions.Item>
              <Descriptions.Item label="邀请人">{info.inviter || info.inviter_name || '—'}</Descriptions.Item>
            </Descriptions>
          </Card>
        ) : (
          <div style={{ color: '#8ba3b5', fontSize: 13, marginBottom: 16 }}>
            （邀请详情加载失败，仍可尝试接受）
          </div>
        )}
        <Button
          type="primary"
          block
          loading={loading}
          onClick={doAccept}
          style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
        >
          接受邀请并加入
        </Button>
      </div>
    </div>
  )
}
