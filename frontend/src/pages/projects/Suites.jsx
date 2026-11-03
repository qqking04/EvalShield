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
import { useNavigate, useParams } from 'react-router-dom'
import {
  Button, Card, Space, Row, Col, Tag, Drawer, Form, Input, Radio, Table, Modal, message, Typography, Empty, Spin,
} from 'antd'
import {
  PlusOutlined, ReloadOutlined, PlayCircleOutlined, ArrowUpOutlined, ArrowDownOutlined, CloseOutlined,
  DeleteOutlined, EditOutlined, AppstoreOutlined, ClockCircleOutlined, CheckSquareOutlined,
} from '@ant-design/icons'
import http from '../../api/http'
import useDict from '../../hooks/useDict'
import { fmtTime } from '../../utils'

const BRAND = '#13c2c2'

// 字典缺失时的兜底
const FALLBACK_EXEC_MODE = [
  { value: 'SEQUENTIAL', label: '串行（顺序执行）' },
  { value: 'PARALLEL', label: '并行（同时执行）' },
]

const SUITE_EXEC_COLOR = {
  SEQUENTIAL: '#13c2c2',
  PARALLEL: '#faad14',
}

function ExecModeTag({ mode }) {
  const color = SUITE_EXEC_COLOR[mode] || '#8b97a7'
  const label = mode === 'SEQUENTIAL' ? '串行' : mode === 'PARALLEL' ? '并行' : mode
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '0 8px',
        height: 22,
        lineHeight: '20px',
        fontSize: 12,
        border: `1px solid ${color}`,
        borderRadius: 2,
        color,
        fontFamily: 'JetBrains Mono, Consolas, monospace',
      }}
    >
      {label}
    </span>
  )
}

export default function Suites() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { items: execModeDict, loading: dictLoading } = useDict('suite_exec_mode')

  const [suites, setSuites] = useState([])
  const [loading, setLoading] = useState(false)

  // 新建/编辑 Drawer
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editTarget, setEditTarget] = useState(null) // null 代表新建
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)

  // 套件详情 Drawer
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailTarget, setDetailTarget] = useState(null)
  const [itemsLoading, setItemsLoading] = useState(false)
  const [items, setItems] = useState([])

  // 从项目任务库添加
  const [addTaskOpen, setAddTaskOpen] = useState(false)
  const [addTaskLoading, setAddTaskLoading] = useState(false)
  const [projectTasks, setProjectTasks] = useState([])
  const [selectedTaskIds, setSelectedTaskIds] = useState([])

  // 执行套件
  const [executeTarget, setExecuteTarget] = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const d = await http.get(`/projects/${id}/suites`)
      setSuites(Array.isArray(d) ? d : (d?.items || []))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const execModeOptions = execModeDict.length > 0
    ? execModeDict
    : FALLBACK_EXEC_MODE

  // —— 打开新建 Drawer ——
  const openCreate = () => {
    setEditTarget(null)
    form.resetFields()
    form.setFieldsValue({ exec_mode: 'SEQUENTIAL', cron_expr: '' })
    setDrawerOpen(true)
  }

  // —— 打开编辑 Drawer ——
  const openEdit = (suite) => {
    setEditTarget(suite)
    form.setFieldsValue({
      name: suite.name,
      description: suite.description,
      exec_mode: suite.exec_mode,
      cron_expr: suite.cron_expr,
    })
    setDrawerOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      if (editTarget) {
        await http.put(`/suites/${editTarget.id}`, values)
        message.success('套件已更新')
      } else {
        await http.post(`/projects/${id}/suites`, values)
        message.success('套件已创建')
      }
      setDrawerOpen(false)
      load()
    } finally {
      setSubmitting(false)
    }
  }

  // —— 套件详情 ——
  const openDetail = async (suite) => {
    setDetailTarget(suite)
    setDetailOpen(true)
    setItemsLoading(true)
    try {
      const d = await http.get(`/suites/${suite.id}/items`)
      const list = Array.isArray(d) ? d : (d?.items || [])
      setItems(list)
    } finally {
      setItemsLoading(false)
    }
  }

  const adjustOrder = async (item, dir) => {
    // dir: -1 上移 / +1 下移
    const idx = items.findIndex((x) => x.id === item.id)
    const other = items[idx + dir]
    if (!other) return
    const newItems = [...items]
    newItems[idx] = other
    newItems[idx + dir] = item
    setItems(newItems)

    const sortA = item.sort_order ?? idx
    const sortB = other.sort_order ?? idx + dir
    try {
      await http.put(`/suites/${detailTarget.id}/items/${item.id}`, { sort_order: sortB })
      await http.put(`/suites/${detailTarget.id}/items/${other.id}`, { sort_order: sortA })
    } catch {
      // 失败则回滚
      setItems(items)
    }
  }

  const removeItem = async (item) => {
    Modal.confirm({
      title: '移除任务',
      content: `将从套件中移除 "${item.task_no || item.name}"？`,
      okText: '移除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        await http.delete(`/suites/${detailTarget.id}/items/${item.id}`)
        setItems((prev) => prev.filter((x) => x.id !== item.id))
        message.success('已移除')
      },
    })
  }

  // —— 添加项目任务 ——
  const openAddTasks = async () => {
    setAddTaskOpen(true)
    setSelectedTaskIds([])
    setAddTaskLoading(true)
    try {
      const d = await http.get(`/tasks`, { params: { project_id: id, page_size: 200 } })
      const list = Array.isArray(d) ? d : (d?.items || [])
      setProjectTasks(list)
    } finally {
      setAddTaskLoading(false)
    }
  }

  const confirmAddTasks = async () => {
    if (!selectedTaskIds.length) {
      message.warning('请先选择任务')
      return
    }
    setAddTaskLoading(true)
    try {
      await http.post(`/suites/${detailTarget.id}/items`, {
        task_ids: selectedTaskIds,
      })
      message.success(`已添加 ${selectedTaskIds.length} 个任务`)
      setAddTaskOpen(false)
      // 刷新 items
      const d = await http.get(`/suites/${detailTarget.id}/items`)
      setItems(Array.isArray(d) ? d : (d?.items || []))
    } finally {
      setAddTaskLoading(false)
    }
  }

  // —— 删除套件 ——
  const handleDelete = (suite) => {
    Modal.confirm({
      title: '确认删除该套件？',
      content: `删除后不可恢复：${suite.name}`,
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        await http.delete(`/suites/${suite.id}`)
        message.success('套件已删除')
        load()
      },
    })
  }

  // —— 执行套件 ——
  const handleExecute = async () => {
    if (!executeTarget) return
    try {
      const d = await http.post(`/suites/${executeTarget.id}/execute`)
      const created = d?.created ?? d?.count ?? items.length ?? 0
      message.success(`已创建 ${created} 个任务，可在任务页查看进度`)
      navigate(`/projects/${id}?suite=${executeTarget.id}`)
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setExecuteTarget(null)
    }
  }

  const itemColumns = [
    {
      title: '序号',
      dataIndex: 'sort_order',
      width: 70,
      className: 'mono-no',
      render: (v, _, idx) => v ?? idx + 1,
    },
    {
      title: '任务编号',
      dataIndex: 'task_no',
      width: 160,
      className: 'mono-no',
      render: (v) => (
        <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }}>{v || '-'}</span>
      ),
    },
    { title: '任务名', dataIndex: 'task_name', ellipsis: true, render: (v) => v || <span style={{ color: '#8b97a7' }}>-</span> },
    {
      title: '执行方式',
      dataIndex: 'exec_mode',
      width: 90,
      render: () => <ExecModeTag mode={detailTarget?.exec_mode} />,
    },
    {
      title: '操作',
      width: 160,
      render: (_, row, idx) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            icon={<ArrowUpOutlined />}
            disabled={idx === 0}
            onClick={() => adjustOrder(row, -1)}
          >上移</Button>
          <Button
            type="link"
            size="small"
            icon={<ArrowDownOutlined />}
            disabled={idx === items.length - 1}
            onClick={() => adjustOrder(row, 1)}
          >下移</Button>
          <Button type="link" size="small" danger icon={<CloseOutlined />} onClick={() => removeItem(row)}>移除</Button>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          <AppstoreOutlined style={{ color: BRAND, marginRight: 8 }} />
          任务套件
        </Typography.Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建套件</Button>
        </Space>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
      ) : suites.length === 0 ? (
        <Card>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无任务套件，点击右上角「新建套件」开始编排"
          />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {suites.map((s) => (
            <Col key={s.id} xs={24} sm={12} md={8} lg={6}>
              <Card
                hoverable
                size="small"
                styles={{ body: { padding: 16 } }}
                title={
                  <div style={{ borderLeft: `3px solid ${BRAND}`, paddingLeft: 8 }}>
                    <span style={{ color: '#e6ebf0', fontWeight: 600 }}>{s.name}</span>
                  </div>
                }
                extra={<ExecModeTag mode={s.exec_mode} />}
                actions={[
                  <Button key="detail" type="link" size="small" onClick={() => openDetail(s)}>详情</Button>,
                  <Button key="edit" type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(s)}>编辑</Button>,
                  <Button key="del" type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(s)}>删除</Button>,
                ]}
              >
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  <div style={{ color: '#8b97a7', fontSize: 12, minHeight: 34 }}>
                    {s.description || '—'}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', color: '#8b97a7', fontSize: 12 }}>
                      <ClockCircleOutlined /> {s.cron_expr || '未设置 cron'}
                    </span>
                    <span className="mono-no">
                      <CheckSquareOutlined /> {s.item_count ?? s.tasks?.length ?? 0} 个任务
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
                    <span style={{ fontSize: 12, color: '#8b97a7' }}>最近执行</span>
                    <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', fontSize: 12 }}>
                      {fmtTime(s.last_executed_at)}
                    </span>
                  </div>
                  {/* 单次确认：直接打开执行 Modal（原 Popconfirm + Modal 双重确认已合并） */}
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    block
                    style={{ marginTop: 4 }}
                    onClick={() => setExecuteTarget(s)}
                  >
                    一键执行
                  </Button>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {/* —— 新建/编辑 Drawer —— */}
      <Drawer
        title={editTarget ? '编辑套件' : '新建套件'}
        width={480}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        footer={
          <Space style={{ justifyContent: 'flex-end', width: '100%' }}>
            <Button onClick={() => setDrawerOpen(false)}>取消</Button>
            <Button type="primary" loading={submitting} onClick={handleSubmit}>
              {editTarget ? '保存' : '创建'}
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label="套件名称" rules={[{ required: true, message: '请输入套件名称' }]}>
            <Input placeholder="如：冒烟测试套件" />
          </Form.Item>
          <Form.Item name="description" label="套件描述">
            <Input.TextArea rows={3} placeholder="简述该套件的用途" />
          </Form.Item>
          <Form.Item name="exec_mode" label="执行方式" rules={[{ required: true, message: '请选择执行方式' }]}>
            <Radio.Group>
              {execModeOptions.map((o) => (
                <Radio key={o.value} value={o.value}>{o.label}</Radio>
              ))}
            </Radio.Group>
          </Form.Item>
          <Form.Item name="cron_expr" label="Cron 表达式">
            <Input
              placeholder="如 0 2 * * 1"
              style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }}
            />
            <div style={{ color: '#8b97a7', fontSize: 12, marginTop: 6 }}>
              标准 5 段表达式，如 <span className="mono-no">0 2 * * 1</span>；当前版本仅保存。
            </div>
          </Form.Item>
          {dictLoading && (
            <div style={{ color: '#8b97a7', fontSize: 12 }}>字典加载中，已使用默认选项…</div>
          )}
        </Form>
      </Drawer>

      {/* —— 套件详情 Drawer —— */}
      <Drawer
        title={<span style={{ borderLeft: `3px solid ${BRAND}`, paddingLeft: 8 }}>{detailTarget?.name} · 任务明细</span>}
        width={760}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={openAddTasks}>
            从项目任务库添加
          </Button>
        }
      >
        {detailTarget && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Card size="small" styles={{ body: { padding: 12 } }}>
              <Space size={16}>
                <Tag color="default">{detailTarget.description || '无描述'}</Tag>
                <ExecModeTag mode={detailTarget.exec_mode} />
                <span className="mono-no"><ClockCircleOutlined /> {detailTarget.cron_expr || '未设置 cron'}</span>
                <span className="mono-no">共 {items.length} 项</span>
              </Space>
            </Card>
            <Spin spinning={itemsLoading}>
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                columns={itemColumns}
                dataSource={items}
                locale={{ emptyText: '暂无任务，请从项目任务库添加' }}
              />
            </Spin>
          </Space>
        )}
      </Drawer>

      {/* —— 添加任务 Modal —— */}
      <Modal
        title="从项目任务库添加"
        open={addTaskOpen}
        width={720}
        confirmLoading={addTaskLoading}
        onCancel={() => setAddTaskOpen(false)}
        onOk={confirmAddTasks}
        okText={`添加（已选 ${selectedTaskIds.length}）`}
        cancelText="取消"
      >
        <Spin spinning={addTaskLoading && projectTasks.length === 0}>
          <Table
            rowKey="id"
            size="small"
            rowSelection={{
              selectedRowKeys: selectedTaskIds,
              onChange: setSelectedTaskIds,
            }}
            pagination={{ pageSize: 10, size: 'small' }}
            dataSource={projectTasks}
            locale={{ emptyText: '该项目下暂无任务' }}
            columns={[
              { title: '任务编号', dataIndex: 'task_no', width: 160, className: 'mono-no', render: (v) => <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }}>{v}</span> },
              { title: '任务名', dataIndex: 'name', ellipsis: true, render: (v) => v || <span style={{ color: '#8b97a7' }}>-</span> },
              { title: '状态', dataIndex: 'status', width: 90, render: (v) => <Tag>{v}</Tag> },
              { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v) => fmtTime(v) },
            ]}
          />
        </Spin>
      </Modal>

      {/* —— 执行套件确认 Modal —— */}
      {executeTarget && (
        <Modal
          title="确认执行套件？"
          open
          onOk={handleExecute}
          onCancel={() => setExecuteTarget(null)}
          okText="立即执行"
          cancelText="取消"
          okButtonProps={{ type: 'primary', danger: true, icon: <PlayCircleOutlined /> }}
        >
          套件 <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', color: BRAND }}>
            {executeTarget.name}
          </span> 将创建 <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }}>
            {executeTarget.item_count ?? executeTarget.tasks?.length ?? 0}
          </span> 个任务，是否执行？
        </Modal>
      )}
    </Space>
  )
}
