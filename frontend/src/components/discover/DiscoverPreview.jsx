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
import { Tabs, Table, Tag, Checkbox, Button, Modal, Input, Space, Typography, Statistic, Alert, Tooltip, Drawer } from 'antd'
import { CheckCircleOutlined, RedoOutlined } from '@ant-design/icons'
import { C, MONO } from './consoleTheme'

const { Text } = Typography

const SEV_COLOR = { P0: '#ff4d4f', P1: '#ff7a45', P2: '#ffd666', P3: '#13c2c2', P4: '#7a8a9c' }
// A12/PO-04：用例 priority 着色（高/中/低 与 P0-P4 双口径兼容）
const PRIORITY_COLOR = { HIGH: 'red', P0: 'red', P1: 'red', MEDIUM: 'gold', P2: 'gold', LOW: 'blue', P3: 'blue', P4: 'blue' }
const UNVERIFIED_COLOR = '#ffd666'

// 预览确认：模块卡片 + 用例/数据集/场景三 Tab + 勾选入库（FC-06）
export default function DiscoverPreview({ payload, jobId, onConfirmed }) {
  const cases = payload?.cases || []
  const datasets = payload?.datasets || []
  const scenarios = payload?.scenarios || []
  const confidence = payload?.confidence ?? 0
  const confMap = payload?.confidence_map || {}
  const replayedCount = payload?.replayed_count ?? cases.filter((c) => c.replay_status !== 'UNVERIFIED').length
  const unverifiedCount = payload?.unverified_count ?? cases.filter((c) => c.replay_status === 'UNVERIFIED').length

  // 默认勾选：只选已回放（非 UNVERIFIED）的用例
  const [selected, setSelected] = useState(() => new Set(cases.filter((c) => c.replay_status !== 'UNVERIFIED').map((c) => c.title)))
  const [editing, setEditing] = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [autoExec, setAutoExec] = useState(false)
  const [rowPreview, setRowPreview] = useState(null)

  const modules = useMemo(() => {
    const m = {}
    for (const c of cases) {
      const k = c.module || '未分类'
      m[k] = (m[k] || 0) + 1
    }
    return m
  }, [cases])

  const caseColumns = [
    {
      title: '',
      width: 40,
      render: (_, r) => <Checkbox checked={selected.has(r.title)} onChange={() => toggle(r)} />,
    },
    { title: '模块', dataIndex: 'module', width: 110, render: (m) => <Tag color="cyan">{m}</Tag> },
    { title: '用例', dataIndex: 'title', ellipsis: true },
    {
      title: '请求',
      width: 210,
      render: (_, r) => (
        <span className="disc-mono" style={{ fontSize: 11 }}>
          <Tag color="blue">{r.request_spec?.method}</Tag>
          {r.request_spec?.path}
        </span>
      ),
    },
    {
      title: '严重度',
      dataIndex: 'severity',
      width: 80,
      render: (s) => <Tag color={SEV_COLOR[s] || 'default'}>{s}</Tag>,
    },
    {
      // A12/PO-04：优先级列（数据源 cases[].priority，缺省显示 '-'）
      title: '优先级',
      dataIndex: 'priority',
      width: 88,
      render: (p) => (p ? <Tag color={PRIORITY_COLOR[String(p).toUpperCase()] || 'default'}>{p}</Tag> : <span style={{ color: C.dim }}>-</span>),
    },
    {
      title: '预期',
      dataIndex: 'expected',
      ellipsis: true,
      render: (v) => <span style={{ color: C.dim, fontSize: 12 }}>{v || '—'}</span>,
    },
    {
      title: '回放',
      dataIndex: 'replay_status',
      width: 96,
      render: (v) =>
        v === 'UNVERIFIED' ? (
          <Tooltip title="body 由表单推断，未回放">
            <Tag style={{ background: UNVERIFIED_COLOR, borderColor: UNVERIFIED_COLOR, color: '#000' }}>未验证</Tag>
          </Tooltip>
        ) : (
          <Tooltip title="GET 接口已回放校验">
            <Tag color="green">已回放</Tag>
          </Tooltip>
        ),
    },
    {
      title: '断言',
      width: 90,
      render: (_, r) => <span className="disc-mono" style={{ fontSize: 11 }}>{(r.assertions || []).length} 条</span>,
    },
    {
      title: '置信度',
      width: 170,
      render: (_, r) => {
        const cm = confMap[r.title] || {}
        // confidence 已是 0–100 百分数；null 表示写接口未回放
        if (cm.confidence == null) {
          return <span className="disc-mono" style={{ fontSize: 11, color: C.dim }} title={cm.reason}>未回放</span>
        }
        const pct = Math.round(cm.confidence)
        return (
          <Space size={6}>
            <div className="disc-bar" style={{ width: 70 }}>
              <div
                className="disc-bar-inner"
                style={{ width: `${pct}%`, background: pct >= 80 ? C.green : pct >= 50 ? C.amber : C.red, animation: 'none' }}
              />
            </div>
            <span className="disc-mono" style={{ fontSize: 11, color: C.dim }} title={cm.reason}>{pct}%</span>
          </Space>
        )
      },
    },
    {
      title: '',
      width: 60,
      render: (_, r) => (
        <Button size="small" type="text" icon={<RedoOutlined />} onClick={() => setEditing(r)} title="编辑">
        </Button>
      ),
    },
  ]

  const filteredSelectedHasUnverified = cases.some((c) => c.replay_status === 'UNVERIFIED' && selected.has(c.title))

  const toggle = (row) => {
    const title = row.title
    setSelected((prev) => {
      if (prev.has(title)) {
        const n = new Set(prev)
        n.delete(title)
        return n
      }
      return prev
    })
    if (row.replay_status === 'UNVERIFIED' && !selected.has(title)) {
      Modal.confirm({
        title: '纳入未验证用例？',
        content: '该用例为写接口，未回放验证，确认将其纳入入库？',
        okText: '纳入入库',
        cancelText: '取消',
        onOk: () => setSelected((prev) => new Set(prev).add(title)),
      })
    } else if (!selected.has(title)) {
      setSelected((prev) => new Set(prev).add(title))
    }
  }

  const doConfirm = () => {
    if (selected.size === 0) return
    const includeUnverified = filteredSelectedHasUnverified
    Modal.confirm({
      title: '确认入库',
      content: `将把选中的 ${selected.size} 条用例（含关联数据集/场景）写入资产中心${includeUnverified ? '（含未验证用例）' : ''}${autoExec ? '，并立即自动执行' : ''}。`,
      okText: '确认入库',
      cancelText: '再想想',
      okButtonProps: { style: { background: C.cyan, borderColor: C.cyan } },
      onOk: async () => {
        setConfirming(true)
        try {
          const { default: http } = await import('../../api/http')
          const body = { selected_case_titles: [...selected], auto_execute: autoExec }
          if (includeUnverified) body.include_unverified = true
          const d = await http.post(`/ai/discover/${jobId}/confirm`, body)
          onConfirmed?.(d)
        } catch {
          /* 拦截器已提示 */
        } finally {
          setConfirming(false)
        }
      },
    })
  }

  const dsColumns = [
    {
      title: '数据集',
      dataIndex: 'name',
      render: (v, r) => (
        <a onClick={() => setRowPreview(r)} style={{ color: C.cyan }}>{v}</a>
      ),
    },
    {
      title: '参数列',
      render: (_, r) => (
        <span className="disc-mono" style={{ fontSize: 11 }}>
          {(r.parameters || []).map((p) => p.name).join(', ')}
        </span>
      ),
    },
    { title: '数据行', width: 90, render: (_, r) => `${(r.data_rows || []).length} 行` },
    {
      title: '绑定用例数',
      width: 110,
      render: (_, r) => `${r.module ? cases.filter((c) => c.module === r.module).length : 0} 条`,
    },
  ]

  const scColumns = [
    { title: '场景', dataIndex: 'name' },
    { title: '步骤数', dataIndex: 'steps', width: 100, render: (s) => `${(s || []).length} 步` },
    {
      title: '链路',
      render: (_, r) => (
        <span className="disc-mono" style={{ fontSize: 11 }}>
          {(r.steps || []).map((s) => s.target).filter(Boolean).slice(0, 3).join(' → ')}
        </span>
      ),
    },
  ]

  return (
    <div className="disc-panel" style={{ marginTop: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 10 }}>
        <Space size="large" wrap>
          <Statistic title={<span style={{ color: C.dim, fontSize: 11 }}>已回放</span>} value={replayedCount} suffix="条" valueStyle={{ color: C.green, fontSize: 22 }} />
          <Statistic title={<span style={{ color: C.dim, fontSize: 11 }}>预计可执行率</span>} value={Math.round(confidence)} suffix="%" valueStyle={{ color: C.cyan, fontSize: 22 }} />
          <Statistic title={<span style={{ color: C.dim, fontSize: 11 }}>未验证</span>} value={unverifiedCount} suffix="条" valueStyle={{ color: C.amber, fontSize: 22 }} />
          <Statistic title={<span style={{ color: C.dim, fontSize: 11 }}>已选用例</span>} value={selected.size} valueStyle={{ color: C.text, fontSize: 22 }} />
        </Space>
        <Space>
          <Checkbox checked={autoExec} onChange={(e) => setAutoExec(e.target.checked)}>
            <span style={{ color: C.dim, fontSize: 12 }}>入库后自动执行（API_TEST）</span>
          </Checkbox>
          <Button
            type="primary"
            icon={<CheckCircleOutlined />}
            loading={confirming}
            disabled={selected.size === 0}
            onClick={doConfirm}
            style={{ background: C.cyan, borderColor: C.cyan, fontWeight: 600 }}
          >
            确认入库（{selected.size}）
          </Button>
        </Space>
      </div>

      {Object.keys(modules).length > 0 && (
        <div style={{ marginBottom: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {Object.entries(modules).map(([m, n]) => (
            <Tag key={m} color="cyan">{m} · {n}</Tag>
          ))}
        </div>
      )}

      <Tabs
        items={[
          { key: 'cases', label: `用例（${cases.length}）`, children: <Table size="small" rowKey="title" columns={caseColumns} dataSource={cases} pagination={{ pageSize: 10, showSizeChanger: false }} /> },
          { key: 'ds', label: `数据集（${datasets.length}）`, children: <Table size="small" rowKey="name" columns={dsColumns} dataSource={datasets} pagination={{ pageSize: 10 }} /> },
          { key: 'sc', label: `场景（${scenarios.length}）`, children: <Table size="small" rowKey="name" columns={scColumns} dataSource={scenarios} pagination={{ pageSize: 10 }} /> },
        ]}
      />

      <Modal
        open={!!editing}
        title={<span style={{ color: C.text }}>编辑用例</span>}
        onCancel={() => setEditing(null)}
        footer={null}
        width={560}
        styles={{ content: { background: C.panel, border: `1px solid ${C.panelBorder}` } }}
      >
        {editing && (
          <Space direction="vertical" style={{ width: '100%' }} size="small">
            <Alert type="info" message="预览态编辑仅调整本次入库内容，保存于「确认入库」时生效（内存中）。" style={{ fontSize: 12 }} />
            <Text style={{ color: C.dim, fontSize: 12 }}>用例标题</Text>
            <Input value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} style={{ background: '#0d1420', color: C.text }} />
            <Text style={{ color: C.dim, fontSize: 12 }}>请求路径</Text>
            <Input value={editing.request_spec?.path} onChange={(e) => setEditing({ ...editing, request_spec: { ...editing.request_spec, path: e.target.value } })} style={{ background: '#0d1420', color: C.text, fontFamily: MONO }} />
            <Text style={{ color: C.dim, fontSize: 12 }}>预期状态码</Text>
            <Input value={editing.request_spec?.expected_status} onChange={(e) => setEditing({ ...editing, request_spec: { ...editing.request_spec, expected_status: parseInt(e.target.value || '0', 10) } })} style={{ background: '#0d1420', color: C.text, fontFamily: MONO }} />
            <Button type="primary" style={{ background: C.cyan, borderColor: C.cyan, alignSelf: 'flex-end' }} onClick={() => setEditing(null)}>
              完成
            </Button>
          </Space>
        )}
      </Modal>

      <Drawer
        open={!!rowPreview}
        title={<span style={{ color: C.text }}>数据集预览：{rowPreview?.name}（前 10 行）</span>}
        placement="right"
        width={640}
        onClose={() => setRowPreview(null)}
        styles={{ body: { background: C.panel }, header: { background: C.panel, borderBottom: `1px solid ${C.panelBorder}` } }}
      >
        <Table
          size="small"
          rowKey={(_, i) => i}
          columns={(rowPreview?.parameters || []).map((p) => ({ title: p.name, dataIndex: p.name, ellipsis: true }))}
          dataSource={(rowPreview?.data_rows || []).slice(0, 10)}
          pagination={false}
          locale={{ emptyText: <span style={{ color: C.dim, fontSize: 12 }}>暂无数据行</span> }}
        />
      </Drawer>
    </div>
  )
}
