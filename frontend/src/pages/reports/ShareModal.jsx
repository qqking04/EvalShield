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
import { Modal, Form, Select, Input, InputNumber, Button, Space, Row, Col, Card, Tooltip, Switch, message, Table } from 'antd'
import { CopyOutlined, DeleteOutlined } from '@ant-design/icons'
import ClipboardJS from 'clipboard'
import http from '../../api/http'
import useDict from '../../hooks/useDict'
import { fmtTime } from '../../utils'

export default function ShareModal({ open, onClose, reportId }) {
  const { items: expiryOptions } = useDict('share_expiry')
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [shares, setShares] = useState([])
  const [generated, setGenerated] = useState(null)

  const loadShares = async () => {
    if (!reportId) return
    try {
      const d = await http.get(`/reports/${reportId}/shares`)
      setShares(Array.isArray(d) ? d : (d?.items || []))
    } catch { /* 静默 */ }
  }

  useEffect(() => {
    if (open) {
      form.resetFields()
      setGenerated(null)
      loadShares()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, reportId])

  const handleCreate = async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      const d = await http.post(`/reports/${reportId}/shares`, {
        expires_in_days: values.expires_in_days,
        password: values.password || undefined,
        max_views: values.max_views ?? undefined,
      })
      setGenerated(d)
      message.success(
        d.is_permanent ? '分享链接已生成（永久有效）'
        : `分享链接已生成，${d.expires_in_days ?? values.expires_in_days} 天后过期`,
      )
      loadShares()
    } finally { setSubmitting(false) }
  }

  const handleCopy = () => {
    if (!generated?.url) return
    try {
      const btn = document.createElement('button')
      btn.setAttribute('data-clipboard-text', generated.url)
      document.body.appendChild(btn)
      const cb = new ClipboardJS(btn)
      cb.on('success', () => { message.success('链接已复制'); cb.destroy(); btn.remove() })
      cb.on('error', () => { cb.destroy(); btn.remove(); message.error('复制失败，请手动复制') })
      btn.click()
    } catch { message.error('复制失败') }
  }

  const toggleEnabled = async (share) => {
    try { await http.put(`/shares/${share.id}`, { is_enabled: !share.is_enabled }); message.success(share.is_enabled ? '已停用' : '已启用'); loadShares() } catch { /* 静默 */ }
  }

  const handleDelete = async (share) => {
    Modal.confirm({
      title: '确认删除该分享链接？', okText: '删除', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => { await http.delete(`/shares/${share.id}`); message.success('已删除'); loadShares() },
    })
  }

  const expirySelectOptions = expiryOptions.length > 0 ? expiryOptions
    : [{ value: 1, label: '1 天' }, { value: 7, label: '7 天' }, { value: 30, label: '30 天' }, { value: 0, label: '永久' }]

  return (
    <Modal title="分享报告" open={open} width={760} okText="生成链接" cancelText="关闭" onCancel={onClose}
      footer={[<Button key="close" onClick={onClose}>关闭</Button>, <Button key="create" type="primary" loading={submitting} onClick={handleCreate}>生成新链接</Button>]}
    >
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Form form={form} layout="inline" preserve={false}>
          <Space wrap>
            <Form.Item name="expires_in_days" label="有效期" rules={[{ required: true, message: '请选择有效期' }]} initialValue={7}>
              <Select style={{ width: 140 }} options={expirySelectOptions} />
            </Form.Item>
            <Form.Item name="max_views" label="最大访问次数" tooltip="留空 = 不限次数">
              <InputNumber min={1} style={{ width: 120 }} placeholder="不限" />
            </Form.Item>
            <Form.Item name="password" label="访问密码（可选）">
              <Input placeholder="4-6 位数字密码" maxLength={6} style={{ width: 160, fontFamily: 'JetBrains Mono, Consolas, monospace' }} />
            </Form.Item>
          </Space>
        </Form>
        {generated && (
          <Card size="small" title="已生成的分享链接" styles={{ body: { padding: 12 } }}>
            <Row gutter={8} align="middle">
              <Col flex="auto"><Input readOnly value={generated.url} style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }} /></Col>
              <Col><Button type="primary" icon={<CopyOutlined />} onClick={handleCopy}>复制</Button></Col>
            </Row>
            {generated.password && <div style={{ marginTop: 8, color: '#8b97a7', fontSize: 12 }}>访问密码：<span className="mono-no">{generated.password}</span></div>}
          </Card>
        )}
        <Card size="small" title="已有分享链接" styles={{ body: { padding: 0 } }}>
          {shares.length === 0 ? (
            <div style={{ padding: 20, textAlign: 'center', color: '#8b97a7' }}>暂无分享</div>
          ) : (
            <Table size="small" pagination={false} rowKey="id" dataSource={shares} columns={[
              { title: '链接', dataIndex: 'share_no', render: (_, row) => <Tooltip title={row.url}><span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', color: '#13c2c2' }}>{row.share_no || row.id}</span></Tooltip> },
              {
                title: '有效期', dataIndex: 'expires_at', width: 120,
                render: (_, row) => row.is_permanent ? '永久'
                  : (row.expires_at ? `至 ${fmtTime(row.expires_at).slice(0, 10)}` : '-'),
              },
              { title: '访问', dataIndex: 'view_count', width: 90, render: (v, row) => `${v ?? 0}${row.max_views ? ` / ${row.max_views}` : ''}` },
              { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v) => fmtTime(v) },
              { title: '状态', dataIndex: 'is_enabled', width: 120, render: (v, row) => <Switch checked={v} onChange={() => toggleEnabled(row)} /> },
              { title: '操作', width: 80, render: (_, row) => <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(row)}>删除</Button> },
            ]} />
          )}
        </Card>
      </Space>
    </Modal>
  )
}
