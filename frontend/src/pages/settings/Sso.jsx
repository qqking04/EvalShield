/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES8 M10：SSO 单点登录配置管理（OIDC / 企微 / 飞书网关）
import { useEffect, useState } from 'react'
import {
  App, Button, Card, Col, Empty, Form, Input, Modal, Row, Select,
  Space, Switch, Tag, Typography, Popconfirm, Spin,
} from 'antd'
import { EditOutlined, DeleteOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import http from '../../api/http'
import tokens from '../../theme/tokens'

const { Title, Text, Paragraph } = Typography

// 支持的 SSO 类型（与后端 _KINDS 对齐）
const KINDS = [
  { value: 'oidc', label: '标准 OIDC', color: 'cyan' },
  { value: 'wecom', label: '企业微信', color: 'blue' },
  { value: 'feishu', label: '飞书', color: 'purple' },
]
const kindMeta = (k) => KINDS.find((x) => x.value === k) || KINDS[0]

export default function SsoSettings() {
  const { message } = App.useApp()
  const [list, setList] = useState([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null) // null=新建
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const data = await http.get('/admin/sso/configs', { params: { page_size: 100 } })
      setList(data?.items || data || [])
    } catch (e) {
      message.error(e?.message || '加载 SSO 配置失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ kind: 'oidc', enabled: true, auto_provision: false, default_role: 'MEMBER', org_binding_mode: 'none', scopes: 'openid profile email' })
    setModalOpen(true)
  }

  const openEdit = (cfg) => {
    setEditing(cfg)
    form.resetFields()
    // 出于安全，client_secret 密文不回填，留空表示不变更
    form.setFieldsValue({
      name: cfg.name,
      kind: cfg.kind,
      issuer: cfg.issuer,
      client_id: cfg.client_id,
      scopes: cfg.scopes,
      redirect_uri: cfg.redirect_uri,
      enabled: cfg.enabled,
      auto_provision: cfg.auto_provision,
      default_role: cfg.default_role,
      org_binding_mode: cfg.org_binding_mode,
    })
    setModalOpen(true)
  }

  const onSubmit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        await http.put(`/admin/sso/configs/${editing.id}`, values)
        message.success('已更新')
      } else {
        await http.post('/admin/sso/configs', values)
        message.success('已创建')
      }
      setModalOpen(false)
      load()
    } catch (e) {
      message.error(e?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const onToggle = async (cfg, enabled) => {
    try {
      await http.put(`/admin/sso/configs/${cfg.id}`, { enabled })
      load()
    } catch (e) {
      message.error(e?.message || '切换失败')
    }
  }

  const onDelete = async (cfg) => {
    try {
      await http.delete(`/admin/sso/configs/${cfg.id}`)
      message.success('已删除')
      load()
    } catch (e) {
      message.error(e?.message || '删除失败')
    }
  }

  return (
    <div style={{ padding: 16 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 12 }}>
        <Col>
          <Title level={4} style={{ color: tokens.text1, margin: 0 }}>单点登录（SSO）</Title>
          <Text style={{ color: tokens.text3 }}>
            OIDC Authorization Code + PKCE；配置后登录页出现对应登录入口
          </Text>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建配置</Button>
          </Space>
        </Col>
      </Row>

      <Spin spinning={loading}>
        {list.length === 0 && !loading ? (
          <Empty description={<span style={{ color: tokens.text3 }}>暂无 SSO 配置</span>} />
        ) : (
          <Row gutter={[12, 12]}>
            {list.map((cfg) => (
              <Col key={cfg.id} xs={24} md={12} xl={8}>
                <Card
                  size="small"
                  style={{ background: tokens.bgPanel, borderColor: tokens.border }}
                  title={
                    <Space>
                      <Text style={{ color: tokens.text1 }}>{cfg.name}</Text>
                      <Tag color={kindMeta(cfg.kind).color}>{kindMeta(cfg.kind).label}</Tag>
                    </Space>
                  }
                  extra={<Switch size="small" checked={cfg.enabled} onChange={(v) => onToggle(cfg, v)} />}
                  actions={[
                    <EditOutlined key="edit" onClick={() => openEdit(cfg)} />,
                    <Popconfirm key="del" title="确认删除该 SSO 配置？" onConfirm={() => onDelete(cfg)}>
                      <DeleteOutlined style={{ color: tokens.danger }} />
                    </Popconfirm>,
                  ]}
                >
                  <Paragraph style={{ color: tokens.text2, marginBottom: 4 }} ellipsis={{ rows: 1 }}>
                    Issuer：{cfg.issuer || '-'}
                  </Paragraph>
                  <Paragraph style={{ color: tokens.text2, marginBottom: 4 }} ellipsis={{ rows: 1 }}>
                    Client ID：{cfg.client_id || '-'}（Secret：{cfg.client_secret_masked || '-'}）
                  </Paragraph>
                  <Space size={4} wrap>
                    <Tag>{cfg.auto_provision ? '自动建号' : '仅匹配已有账号'}</Tag>
                    <Tag>默认角色 {cfg.default_role}</Tag>
                    {cfg.org_binding_mode && cfg.org_binding_mode !== 'none' && (
                      <Tag color="gold">组织绑定 {cfg.org_binding_mode}</Tag>
                    )}
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Spin>

      <Modal
        title={editing ? `编辑：${editing.name}` : '新建 SSO 配置'}
        open={modalOpen}
        onOk={onSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        destroyOnClose
        width={620}
      >
        <Form form={form} layout="vertical">
          <Row gutter={12}>
            <Col span={14}>
              <Form.Item name="name" label="显示名称" rules={[{ required: true, message: '请输入名称' }]}>
                <Input placeholder="例如：公司 Keycloak" />
              </Form.Item>
            </Col>
            <Col span={10}>
              <Form.Item name="kind" label="类型" rules={[{ required: true }]}>
                <Select options={KINDS.map((k) => ({ value: k.value, label: k.label }))} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="issuer"
            label="Issuer"
            extra="OIDC 发行方地址（企微/飞书填其 OIDC 网关前缀），发现文档 = Issuer/.well-known/openid-configuration"
            rules={[{ required: true, message: '请输入 Issuer' }]}
          >
            <Input placeholder="https://sso.example.com/realms/main" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="client_id" label="Client ID" rules={[{ required: true, message: '请输入 Client ID' }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="client_secret"
                label="Client Secret"
                extra={editing ? '出于安全，密文不回填；留空 = 不变更' : '加密存储，仅显示后 4 位'}
                rules={editing ? [] : [{ required: true, message: '请输入 Client Secret' }]}
              >
                <Input.Password autoComplete="new-password" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="scopes" label="Scopes">
                <Input placeholder="openid profile email" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="redirect_uri" label="Redirect URI" extra="留空使用系统默认回调地址">
                <Input placeholder="https://…/api/auth/sso/callback" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="enabled" label="启用" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="auto_provision" label="自动建号" valuePropName="checked" extra="未匹配到已有账号时按默认角色创建">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="default_role" label="默认角色">
                <Select
                  options={[
                    { value: 'MEMBER', label: 'MEMBER' },
                    { value: 'VIEWER', label: 'VIEWER' },
                    { value: 'AUDITOR', label: 'AUDITOR' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="org_binding_mode" label="组织绑定">
            <Select
              options={[
                { value: 'none', label: '不绑定' },
                { value: 'name', label: '按 Claim 名称匹配组织' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
