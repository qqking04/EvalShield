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
import { Space, Card, Button, List, Tag, Popconfirm, Typography, message } from 'antd'
import { CheckSquareOutlined, ReloadOutlined, DeleteOutlined } from '@ant-design/icons'
import http from '../../api/http'
import { fmtTime } from '../../utils'

export default function NotificationsList() {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [markingAll, setMarkingAll] = useState(false)

  const load = async (p = page) => {
    setLoading(true)
    try {
      const d = await http.get('/notifications', { params: { page: p, page_size: 10 } })
      setRows(d.items || [])
      setTotal(d.total || 0)
    } finally { setLoading(false) }
  }

  useEffect(() => { load(1) /* eslint-disable-next-line */ }, [])

  const markRead = async (id) => { await http.post(`/notifications/${id}/read`); load(page) }
  const markAllRead = async () => {
    setMarkingAll(true)
    try { await http.post('/notifications/read-all'); message.success('已将全部通知标记为已读'); load(page) }
    finally { setMarkingAll(false) }
  }
  const handleDelete = async (notif) => {
    try { await http.delete(`/notifications/${notif.id}`); message.success('通知已删除'); load(page) } catch { /* 静默 */ }
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small" styles={{ body: { padding: '8px 16px' } }}>
        <Space>
          <Button type="primary" icon={<CheckSquareOutlined />} loading={markingAll} onClick={markAllRead}>全部标记已读</Button>
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
        </Space>
      </Card>
      <List loading={loading} dataSource={rows} pagination={{ current: page, total, pageSize: 10, onChange: (p) => { setPage(p); load(p) } }}
        renderItem={(item) => (
          <List.Item actions={[
            !item.is_read && <Button key="read" type="link" size="small" onClick={() => markRead(item.id)}>标记已读</Button>,
            <Popconfirm key="del" title="确认删除该通知？" okText="确认删除" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={() => handleDelete(item)}>
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>,
          ]}>
            <List.Item.Meta
              title={<Space><Typography.Text strong={!item.is_read}>{item.title}</Typography.Text>{!item.is_read && <Tag color="red">未读</Tag>}<Tag>{item.notif_type}</Tag></Space>}
              description={<Space direction="vertical" size={0}><span>{item.content || '-'}</span><Typography.Text type="secondary" style={{ fontSize: 12 }}>{item.notif_no} · {fmtTime(item.created_at)}</Typography.Text></Space>}
            />
          </List.Item>
        )}
      />
    </Space>
  )
}
