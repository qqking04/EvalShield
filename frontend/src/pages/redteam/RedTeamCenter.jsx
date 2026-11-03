/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES8 M9 生成式红队中心（方案 §10）+ ES11 P8 攻击活动台账
// ES11：默认页签为「攻击活动」（目标与版本/样本与绕过/首绕路径/框架覆盖/转缺陷闭环态），
// 原三个资产页签（样本池/变异/覆盖）降为次级；覆盖查询改为 项目→目标→版本→运行 级联选择器。
// 能力位 generative_redteam 未点亮时后端各端点 403，http 拦截器统一提示。
import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  App, Alert, Button, Card, Descriptions, Form, Input, InputNumber, Modal,
  Select, Space, Table, Tabs, Tag, Tooltip, Typography,
} from 'antd'
import {
  AimOutlined, AuditOutlined, CheckOutlined, CloseOutlined, DownloadOutlined,
  GoldOutlined, ReloadOutlined, SafetyOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import http from '../../api/http'
import { listRedteamCampaigns } from '../../api/es11'
import { tokens } from '../../theme/tokens'

const STATUS_LABEL = { DRAFT: '待审批', APPROVED: '已通过', REJECTED: '已驳回' }
const STATUS_COLOR = { DRAFT: 'gold', APPROVED: 'green', REJECTED: 'red' }
const STATUS_RUN_LABEL = { PENDING: '排队中', RUNNING: '执行中', PASSED: '已完成', SUCCESS: '已完成', FAILED: '已失败', ERROR: '异常', CANCELLED: '已取消' }
// 变异类型中文名（与后端 MUTATION_TYPE_CN 对齐）
const MUTATION_TYPE_LABEL = {
  rewrite: '语义改写', encoding: '编码混淆', multilingual: '多语言切换',
  roleplay_wrap: '角色扮演包裹', multi_turn: '多轮拆解',
}
const PRE_STYLE = {
  margin: 0, padding: 10, overflow: 'auto', maxHeight: 200,
  background: '#12161f', border: `1px solid ${tokens.border || '#1f2833'}`, borderRadius: 6,
  fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
  fontFamily: 'JetBrains Mono, Consolas, monospace',
}

function fmtTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString('zh-CN', { hour12: false })
}

// ------------------------------------------------------ 攻击活动 Tab (ES11 P8) ----

function CampaignTab() {
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [denied, setDenied] = useState(false)

  const load = useCallback((p = 1) => {
    setLoading(true)
    listRedteamCampaigns({ page: p, page_size: 10 })
      .then((d) => { setRows(d.items || []); setTotal(d.total || 0); setPage(p); setDenied(false) })
      .catch(() => setDenied(true))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load(1) }, [load])

  return (
    <Card
      size="small"
      title={<Space><AimOutlined />攻击活动台账</Space>}
      extra={<Tooltip title="刷新"><Button size="small" type="text" icon={<ReloadOutlined spin={loading} />} onClick={() => load(page)} /></Tooltip>}
    >
      {denied ? (
        <Alert type="warning" showIcon message="攻击活动数据不可用"
          description="生成式红队能力位未点亮或接口异常。请先在「样本池审批」准备载荷并发起越狱评测运行，本台账自动归集。" />
      ) : (
        <Table
          size="small" rowKey="run_id" loading={loading} dataSource={rows}
          onRow={(r) => ({ onClick: () => navigate(`/eval/runs/${r.run_id}`), style: { cursor: 'pointer' } })}
          pagination={{ current: page, pageSize: 10, total, showSizeChanger: false, onChange: (p) => load(p) }}
          locale={{
            emptyText: (
              <Space direction="vertical" size={8}>
                <Typography.Text type="secondary">尚无越狱/红队评测运行。</Typography.Text>
                <Button type="primary" size="small" onClick={() => navigate('/eval')}>去测试活动中心发起攻击评测</Button>
              </Space>
            ),
          }}
          columns={[
            {
              title: '目标与版本', width: 200, ellipsis: true,
              render: (_, r) => `${r.target_id || '-'}${r.version ? ` · ${r.version}` : ''}`,
            },
            {
              title: '样本/变异/轮次', width: 130,
              render: (_, r) => `${r.samples ?? 0} / ${r.mutations ?? '-'} / ${r.rounds ?? '-'}`,
            },
            {
              title: '绕过数', dataIndex: 'bypassed', width: 90,
              render: (v) => (v > 0 ? <Tag color="red">{v}</Tag> : <Tag color="green">0</Tag>),
            },
            {
              title: '首次绕过路径', width: 220, ellipsis: true,
              render: (_, r) => (r.first_bypass
                ? <Tooltip title={r.first_bypass.payload}>{r.first_bypass.framework_code || '未标框架'}</Tooltip>
                : <Typography.Text type="secondary">无绕过</Typography.Text>),
            },
            {
              title: '框架覆盖', width: 100,
              render: (_, r) => `${r.framework_covered}/${r.framework_total}`,
            },
            {
              title: '转缺陷数', width: 90,
              render: (_, r) => (r.defects?.total ? `${r.defects.total}（未闭环 ${r.defects.open}）` : '-'),
            },
            {
              title: '整改复测状态', width: 130,
              render: (_, r) => {
                const d = r.defects || {}
                if (!d.total) return <Typography.Text type="secondary">-</Typography.Text>
                if (d.closed === d.total) return <Tag color="green">全部闭环</Tag>
                if (d.open === d.total) return <Tag color="red">全部未整改</Tag>
                return <Tag color="gold">部分闭环</Tag>
              },
            },
            { title: '运行编号', dataIndex: 'run_no', width: 150, ellipsis: true },
            { title: '发起时间', dataIndex: 'created_at', width: 160, render: fmtTime },
          ]}
        />
      )}
    </Card>
  )
}

// ------------------------------------------------------------ 样本池 Tab ----

function SamplePoolTab() {
  const { message } = App.useApp()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback((p = 1, over = {}) => {
    setLoading(true)
    http.get('/redteam/samples', {
      params: { page: p, page_size: 20, status: statusFilter || undefined, ...over },
    })
      .then((d) => { setRows(d.items || []); setTotal(d.total || 0); setPage(p) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [statusFilter])

  useEffect(() => { load(1) }, [load])

  // 审批：DRAFT→APPROVED/REJECTED（后端非 DRAFT 返回 409，拦截器提示）
  const transition = async (id, action) => {
    try {
      await http.post(`/redteam/samples/${id}/${action}`)
      message.success(action === 'approve' ? '已通过，注入执行需勾选 include_generated' : '已驳回（终态）')
      load(page)
    } catch (e) {
      message.error(e?.message || '审批失败')
    }
  }

  const create = async () => {
    const v = await form.validateFields()
    setCreating(true)
    try {
      await http.post('/redteam/samples', v)
      message.success('已创建 DRAFT 样本')
      setCreateOpen(false)
      form.resetFields()
      load(1)
    } catch (e) {
      message.error(e?.message || '创建失败')
    } finally {
      setCreating(false)
    }
  }

  return (
    <Card
      size="small"
      title={<Space><AuditOutlined />红队样本池</Space>}
      extra={(
        <Space size={6}>
          <Select allowClear placeholder="状态" style={{ width: 110 }} size="small"
            value={statusFilter}
            onChange={(v) => setStatusFilter(v || null)}
            options={Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label }))}
          />
          <Tooltip title="刷新"><Button size="small" type="text" icon={<ReloadOutlined spin={loading} />} onClick={() => load(page)} /></Tooltip>
          <Button size="small" type="primary" onClick={() => setCreateOpen(true)}>手工新建</Button>
        </Space>
      )}
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 8 }}
        message="仅「已通过」样本会被越狱引擎 include_generated 开关注入执行；待审批样本不参与任何评测。"
      />
      <Table
        size="small" rowKey="id" loading={loading} dataSource={rows}
        pagination={{ current: page, pageSize: 20, total, showSizeChanger: false, onChange: (p) => load(p) }}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 70 },
          {
            title: '状态', dataIndex: 'status', width: 90,
            render: (v) => <Tag color={STATUS_COLOR[v] || 'default'}>{STATUS_LABEL[v] || v}</Tag>,
          },
          { title: '框架条目', dataIndex: 'framework_code', width: 120, ellipsis: true, render: (v) => v || '-' },
          {
            title: '载荷', dataIndex: 'payload', ellipsis: true,
            render: (v) => <Tooltip title={<span style={{ whiteSpace: 'pre-wrap' }}>{v}</span>}>{v}</Tooltip>,
          },
          {
            title: '源种子', dataIndex: 'mutation_of', width: 80,
            render: (v) => (v == null ? '手工' : `#${v}`),
          },
          {
            title: '命中', dataIndex: 'hit_stats', width: 100,
            render: (h) => ((h?.attempts || 0) > 0
              ? <Tag color={h.bypassed > 0 ? 'red' : 'cyan'}>{h.attempts}投{h.bypassed}绕</Tag>
              : <Tag>未投递</Tag>),
          },
          { title: '创建时间', dataIndex: 'created_at', width: 160, render: fmtTime },
          {
            title: '审批', key: 'op', width: 120,
            render: (_, r) => (r.status === 'DRAFT' ? (
              <Space size={4}>
                <Tooltip title="通过"><Button size="small" type="text" icon={<CheckOutlined style={{ color: tokens.primary }} />} onClick={(e) => { e.stopPropagation(); transition(r.id, 'approve') }} /></Tooltip>
                <Tooltip title="驳回"><Button size="small" type="text" danger icon={<CloseOutlined />} onClick={(e) => { e.stopPropagation(); transition(r.id, 'reject') }} /></Tooltip>
              </Space>
            ) : null),
          },
        ]}
      />
      <Modal open={createOpen} title="手工新建 DRAFT 样本" onCancel={() => setCreateOpen(false)}
        onOk={create} okButtonProps={{ loading: creating }} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="payload" label="攻击载荷" rules={[{ required: true, message: '必填' }]}>
            <Input.TextArea rows={4} placeholder="输入红队测试载荷文本" />
          </Form.Item>
          <Form.Item name="framework_code" label="关联框架条目" tooltip="可选，如 LLM01:2025 或 ATLAS 技术号">
            <Input maxLength={64} placeholder="framework_code（可选）" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

// ---------------------------------------------------------- 变异批任务 Tab ----

function MutationTab() {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null) // {mode, created, items}

  const run = async () => {
    const v = await form.validateFields()
    setRunning(true)
    try {
      const d = await http.post('/redteam/mutations', v)
      setResult(d)
      message.success(`批任务完成：产出 ${d.created} 条 DRAFT`)
    } catch (e) {
      message.error(e?.message || '变异失败')
    } finally {
      setRunning(false)
    }
  }

  return (
    <Card size="small" title={<Space><ThunderboltOutlined />载荷变异批任务</Space>}>
      <Form form={form} layout="inline" style={{ marginBottom: 12 }}
        initialValues={{ count: 20, mutation_types: Object.keys(MUTATION_TYPE_LABEL) }}>
        <Form.Item name="count" label="条数" rules={[{ required: true, message: '必填' }]}
          tooltip="默认 20，上限 50（每批按产出条数计费）">
          <InputNumber min={1} max={50} style={{ width: 90 }} />
        </Form.Item>
        <Form.Item name="mutation_types" label="变异类型" tooltip="缺省 5 类全开，轮转分配">
          <Select mode="multiple" allowClear style={{ minWidth: 300 }} placeholder="全部类型"
            options={Object.entries(MUTATION_TYPE_LABEL).map(([value, label]) => ({ value, label }))}
            maxTagCount="responsive" />
        </Form.Item>
        <Form.Item>
          <Button type="primary" loading={running} onClick={run}>执行变异</Button>
        </Form.Item>
      </Form>
      {result && (
        <Alert style={{ marginBottom: 12 }} type={result.mode === 'LLM' ? 'success' : 'warning'} showIcon
          message={`生成方式：${result.mode === 'LLM' ? '租户 LLM 变异' : '内置模板变异（未配置可用 LLM，已明确降级）'}`}
          description={`本批产出 ${result.created} 条待审批（DRAFT）样本，可前往「样本池审批」处理。`}
        />
      )}
      {result && (
        <Table
          size="small" rowKey="id" dataSource={result.items || []}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 70 },
            { title: '框架条目', dataIndex: 'framework_code', width: 120, ellipsis: true, render: (v) => v || '-' },
            { title: '载荷', dataIndex: 'payload', ellipsis: true, render: (v) => <Tooltip title={<span style={{ whiteSpace: 'pre-wrap' }}>{v}</span>}>{v}</Tooltip> },
            { title: '源种子', dataIndex: 'mutation_of', width: 80, render: (v) => (v == null ? '手工' : `#${v}`) },
            { title: '产出时间', dataIndex: 'created_at', width: 160, render: fmtTime },
          ]}
        />
      )}
    </Card>
  )
}

// ---------------------------------------------------------- 框架覆盖 Tab ----

function CoverageTab() {
  const { message } = App.useApp()
  // ES11 P8：手填运行 ID → 项目→目标→版本→运行 级联选择器（选项全部来自真实数据）
  const [projects, setProjects] = useState([])
  const [runs, setRuns] = useState([])
  const [projectId, setProjectId] = useState(null)
  const [targetId, setTargetId] = useState(null)
  const [version, setVersion] = useState(null)
  const [runId, setRunId] = useState(null)
  const [cov, setCov] = useState(null) // {run_id, items, totals}
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  // ES11 P8：绕过条目转整改项（缺陷），创建即 NEW，不自动标记已修复
  const [convertItem, setConvertItem] = useState(null)
  const [convertProject, setConvertProject] = useState(null)
  const [converting, setConverting] = useState(false)

  const openConvert = (r) => { setConvertItem(r); setConvertProject(null) }
  const submitConvert = async () => {
    if (!convertProject) { message.warning('请选择归属项目'); return }
    setConverting(true)
    try {
      await http.post('/defects', {
        project_id: convertProject,
        title: `红队绕过整改：${convertItem.code} ${convertItem.name || ''}（运行 #${runId}）`,
        severity: 'P1', status: 'NEW', priority: 'HIGH',
        expected: '该框架条目对应攻击载荷应被护栏拦截',
        actual: `运行 #${runId} 中 ${convertItem.attempts} 次投递、${convertItem.bypassed} 次被绕过`,
      })
      message.success('整改缺陷已创建（新建态），请走整改→复测→验证闭环')
      setConvertItem(null)
    } catch (e) {
      message.error(e?.message || '创建整改缺陷失败')
    } finally { setConverting(false) }
  }

  useEffect(() => {
    http.get('/projects', { params: { page_size: 200 } })
      .then((d) => setProjects((d?.items || d) || [])).catch(() => {})
    http.get('/eval-runs', { params: { page_size: 200 } })
      .then((d) => setRuns(d?.items || [])).catch(() => {})
  }, [])

  const byProject = useMemo(
    () => (projectId ? runs.filter((r) => r.project_id === projectId) : runs),
    [runs, projectId])
  const targetOptions = useMemo(
    () => [...new Set(byProject.map((r) => r.target_id).filter(Boolean))]
      .map((v) => ({ value: v, label: v })), [byProject])
  const byTarget = useMemo(
    () => (targetId ? byProject.filter((r) => r.target_id === targetId) : byProject),
    [byProject, targetId])
  const versionOptions = useMemo(
    () => [...new Set(byTarget.map((r) => r.dataset_version).filter(Boolean))]
      .map((v) => ({ value: v, label: `v${v}` })), [byTarget])
  const byVersion = useMemo(
    () => (version ? byTarget.filter((r) => String(r.dataset_version) === String(version)) : byTarget),
    [byTarget, version])
  const runOptions = useMemo(
    () => byVersion.map((r) => ({
      value: r.id,
      label: `#${r.id} ${r.run_no}（${STATUS_RUN_LABEL[r.status] || r.status}）`,
    })), [byVersion])

  const load = async () => {
    if (!runId) { message.warning('请先选择到具体运行'); return }
    setLoading(true)
    try {
      setCov(await http.get('/redteam/coverage', { params: { run_id: runId } }))
    } catch (e) {
      message.error(e?.message || '覆盖数据加载失败')
      setCov(null)
    } finally {
      setLoading(false)
    }
  }

  // 防护包下载：http.js 拦截器按 JSON unwrap 且丢弃响应头，
  // 故用原生 fetch 手工带 Bearer token 取 blob 后触发保存
  const download = async () => {
    setDownloading(true)
    try {
      const resp = await fetch(
        `/api/redteam/guardrail-package${runId ? `?run_id=${runId}` : ''}`,
        { headers: { Authorization: `Bearer ${localStorage.getItem('es_token') || ''}` } },
      )
      if (!resp.ok) {
        const body = await resp.json().catch(() => null)
        throw new Error(body?.message || `下载失败（HTTP ${resp.status}）`)
      }
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `guardrail-package-${runId ?? 'tenant'}.json`
      a.click()
      URL.revokeObjectURL(url)
      message.success('防护建议包已开始下载')
    } catch (e) {
      message.error(e?.message || '下载失败')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <Card
      size="small"
      title={<Space><GoldOutlined />国际框架覆盖与防护建议</Space>}
      extra={(
        <Space size={6} wrap>
          <Select allowClear showSearch placeholder="项目" style={{ width: 150 }} size="small"
            value={projectId}
            onChange={(v) => { setProjectId(v ?? null); setTargetId(null); setVersion(null); setRunId(null) }}
            options={projects.map((p) => ({ value: p.id, label: p.name || p.code }))}
            optionFilterProp="label" />
          <Select allowClear showSearch placeholder="目标" style={{ width: 150 }} size="small"
            value={targetId}
            onChange={(v) => { setTargetId(v ?? null); setVersion(null); setRunId(null) }}
            options={targetOptions} optionFilterProp="label" />
          <Select allowClear placeholder="版本" style={{ width: 110 }} size="small"
            value={version}
            onChange={(v) => { setVersion(v ?? null); setRunId(null) }}
            options={versionOptions} />
          <Select showSearch placeholder="运行" style={{ width: 210 }} size="small"
            value={runId} onChange={setRunId}
            options={runOptions} optionFilterProp="label" />
          <Button size="small" type="primary" loading={loading} onClick={load}>查询覆盖</Button>
          <Tooltip title="下载防护建议包（JSON，含绕过特征拦截规则）">
            <Button size="small" icon={<DownloadOutlined />} loading={downloading} onClick={download}>防护包</Button>
          </Tooltip>
        </Space>
      )}
    >
      {cov ? (
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Descriptions size="small" column={4} bordered items={[
            { key: 'run', label: '运行 ID', children: cov.run_id ?? '-' },
            { key: 'a', label: '总投递数', children: cov.totals?.attempts ?? 0 },
            { key: 'b', label: '被绕过数', children: <Typography.Text type={cov.totals?.bypassed > 0 ? 'danger' : undefined}>{cov.totals?.bypassed ?? 0}</Typography.Text> },
            { key: 'c', label: '覆盖条目 / 字典总数', children: `${cov.totals?.codes_covered ?? 0} / ${cov.totals?.framework_items_total ?? 0}` },
          ]} />
          <Table
            size="small" rowKey="code" loading={loading} dataSource={cov.items || []}
            pagination={{ pageSize: 20, showSizeChanger: false }}
            columns={[
              { title: '框架条目', dataIndex: 'code', width: 130 },
              { title: '名称', dataIndex: 'name', ellipsis: true },
              {
                title: '框架', dataIndex: 'framework', width: 100,
                render: (v) => (v ? <Tag color={v === 'atlas' ? 'purple' : 'cyan'}>{v === 'atlas' ? 'MITRE ATLAS' : 'OWASP LLM'}</Tag> : '-'),
              },
              { title: '类型', dataIndex: 'item_type', width: 90, render: (v) => v || '-' },
              { title: '战术', dataIndex: 'tactic', width: 140, ellipsis: true, render: (v) => v || '-' },
              { title: '投递数', dataIndex: 'attempts', width: 80 },
              {
                title: '被绕过', dataIndex: 'bypassed', width: 80,
                render: (v) => (v > 0 ? <Tag color="red">{v}</Tag> : v),
              },
              {
                // ES11 P8：防护建议可转整改项（缺陷），但绝不自动标记已修复
                title: '转整改项', width: 100,
                render: (_, r) => (r.bypassed > 0 ? (
                  <Button size="small" type="link" onClick={() => openConvert(r)}>转缺陷</Button>
                ) : null),
              },
            ]}
          />
          <Modal
            open={!!convertItem} title={`转整改项：${convertItem?.code || ''}`}
            onCancel={() => setConvertItem(null)} onOk={submitConvert}
            okText="创建缺陷" okButtonProps={{ loading: converting }} destroyOnHidden
          >
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Typography.Text type="secondary">
                将创建状态为「新建」的整改缺陷（不自动标记已修复），后续须走整改→复测→验证闭环。
              </Typography.Text>
              <Select
                style={{ width: '100%' }} placeholder="选择归属项目" showSearch
                value={convertProject} onChange={setConvertProject}
                options={projects.map((p) => ({ value: p.id, label: p.name || p.code }))}
                optionFilterProp="label"
              />
            </Space>
          </Modal>
        </Space>
      ) : (
        <Alert type="info" showIcon icon={<SafetyOutlined />}
          message="按 项目→目标→版本→运行 逐级选择越狱评测运行查询框架覆盖矩阵；「防护包」可不选运行仅按租户样本命中归纳。"
        />
      )}
    </Card>
  )
}

// ------------------------------------------------------------------ 页面 ----

export default function RedTeamCenter() {
  return (
    <div style={{ padding: 16 }}>
      <Tabs
        defaultActiveKey="campaigns"
        items={[
          { key: 'campaigns', label: '攻击活动', children: <CampaignTab /> },
          { key: 'samples', label: '样本池审批', children: <SamplePoolTab /> },
          { key: 'mutations', label: '载荷变异', children: <MutationTab /> },
          { key: 'coverage', label: '框架覆盖与防护建议', children: <CoverageTab /> },
        ]}
      />
    </div>
  )
}
