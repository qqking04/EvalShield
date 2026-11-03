/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 六维度预览确认页 v2.0：功能/UI/性能/安全/数据流/覆盖率热力图
import { useEffect, useMemo, useState } from 'react'
import { Tabs, Table, Tag, Checkbox, Button, Modal, Input, Space, Typography, Tooltip, Drawer, Select, Slider, InputNumber } from 'antd'
import {
  CheckCircleOutlined,
  RedoOutlined,
  ApiOutlined,
  DashboardOutlined,
  ThunderboltOutlined,
  SafetyOutlined,
  ExperimentOutlined,
  DatabaseOutlined,
  ExportOutlined,
  AimOutlined,
} from '@ant-design/icons'
import { C, MONO } from './consoleTheme'
import DiscoverStatsCards from './DiscoverStatsCards'
import DiscoverPreviewUITab from './DiscoverPreviewUITab'
import DiscoverPreviewPerfTab from './DiscoverPreviewPerfTab'
import DiscoverPreviewSecTab from './DiscoverPreviewSecTab'
import DiscoverCoverageHeatmap from './DiscoverCoverageHeatmap'
import DiscoverSelectorPicker from './DiscoverSelectorPicker'

const { Text } = Typography

const SEV_COLOR = { P0: '#ff4d4f', P1: '#ff7a45', P2: '#ffd666', P3: '#13c2c2', P4: '#7a8a9c' }
const PRIORITY_COLOR = { HIGH: 'red', P0: 'red', P1: 'red', MEDIUM: 'gold', P2: 'gold', LOW: 'blue', P3: 'blue', P4: 'blue' }
const UNVERIFIED_COLOR = '#ffd666'

// FE-15：入库前模块维度覆盖率阈值（%），低于该值弹警告二次确认
const COVERAGE_WARN_THRESHOLD = 60

// FE-12：DOM 选择器语法校验（CSS / XPath），返回错误信息或 null
function validateSelector(sel) {
  const s = (sel || '').trim()
  if (!s) return null
  if (s.startsWith('/') || s.startsWith('./') || s.startsWith('(')) {
    // XPath：括号配对 + 基本字符集校验
    const opens = (s.match(/\[/g) || []).length
    const closes = (s.match(/\]/g) || []).length
    const lp = (s.match(/\(/g) || []).length
    const rp = (s.match(/\)/g) || []).length
    if (opens !== closes) return 'XPath 谓词方括号 [ ] 不配对'
    if (lp !== rp) return 'XPath 圆括号 ( ) 不配对'
    if (/[<>"'`]/.test(s)) return 'XPath 含非法字符'
    return null
  }
  // CSS：常见非法字符与结构校验
  if (/[<>"'`]/.test(s)) return 'CSS 选择器含非法字符'
  const bo = (s.match(/\[/g) || []).length
  const bc = (s.match(/\]/g) || []).length
  if (bo !== bc) return 'CSS 属性方括号 [ ] 不配对'
  if (/^[.#]?[\d]/.test(s) && !s.startsWith('[')) return 'CSS 选择器不能以数字或 .#数字 开头'
  if (/\s>|>\s*$|,$/.test(s)) return 'CSS 选择器组合符使用不当'
  return null
}

// FE-15/COV-P3：按模块计算 6 维覆盖率。payload 带 coverage_targets 时用计数加权口径
// （维度分 = min(选中用例数/目标数, 1)，目标数来自后端全量生成结果），否则回退旧布尔口径。
function calcModuleCoverage(cases, datasets, scenarios, coverageTargets) {
  const m = {}
  const ensure = (mod) => {
    if (!m[mod]) m[mod] = { functional: 0, ui: 0, performance: 0, security: 0, dataflow: 0, compat: 0 }
    return m[mod]
  }
  for (const c of cases) {
    if (c.global_review) continue // COV-P5：全局评审伪模块不参与模块覆盖率
    const mod = c.module || '未分类'
    const dims = ensure(mod)
    const cat = (c.category || '').toUpperCase()
    if (cat === 'API') dims.functional++
    else if (cat === 'UI') dims.ui++
    else if (cat === 'PERFORMANCE') dims.performance++
    else if (cat === 'SECURITY' || cat === 'REDTEAM') dims.security++
    else if (cat === 'DATAFLOW') dims.dataflow++
    else if (cat === 'COMPAT') dims.compat++
    // 兼容性维度：用例带 browser_config（chromium/firefox/webkit）即视为该模块有兼容覆盖
    if (c.browser_config) dims.compat++
  }
  for (const ds of datasets) { if (ds.module || '未分类' in m) m[ds.module || '未分类'].functional++ }
  for (const sc of scenarios) { if (sc.module || '未分类' in m) m[sc.module || '未分类'].dataflow++ }
  const out = {}
  const weighted = coverageTargets && Object.keys(coverageTargets).length > 0
  for (const [mod, dims] of Object.entries(m)) {
    const t = weighted ? coverageTargets[mod] : null
    if (t) {
      // COV-P5：分母只算适用维度（纯 API 模块的 UI/兼容不适用）
      const targets = t.targets || {}
      const applicable = t.applicable || {}
      let sum = 0
      let denom = 0
      for (const k of Object.keys(dims)) {
        if (applicable[k] === false && dims[k] === 0) continue
        const tg = targets[k] || 1
        sum += Math.min(dims[k] / tg, 1)
        denom += 1
      }
      out[mod] = denom ? Math.round((sum / denom) * 100) : 100
    } else {
      const covered = Object.values(dims).filter((n) => n > 0).length
      out[mod] = Math.round((covered / 6) * 100)
    }
  }
  return out
}

// 六维度 Tab 配置
const DIM_TABS = [
  { key: 'functional', label: '功能测试', icon: <ApiOutlined />, color: C.cyan },
  { key: 'ui', label: 'UI 测试', icon: <DashboardOutlined />, color: '#722ed1' },
  { key: 'performance', label: '性能测试', icon: <ThunderboltOutlined />, color: '#fa8c16' },
  { key: 'security', label: '安全测试', icon: <SafetyOutlined />, color: '#f5222d' },
  { key: 'dataflow', label: '数据流', icon: <ExperimentOutlined />, color: '#1890ff' },
  { key: 'dataset', label: '数据集', icon: <DatabaseOutlined />, color: '#52c41a' },
  { key: 'heatmap', label: '覆盖率', icon: null, color: C.text },
]

export default function DiscoverPreviewV2({ payload, jobId, onConfirmed, readOnly = false }) {
  const [cases, setCases] = useState(payload?.cases || [])
  const datasets = payload?.datasets || []
  const scenarios = payload?.scenarios || []
  const confidence = payload?.confidence ?? 0
  const confMap = payload?.confidence_map || {}
  const replayedCount = payload?.replayed_count ?? cases.filter((c) => c.replay_status !== 'UNVERIFIED').length
  const unverifiedCount = payload?.unverified_count ?? cases.filter((c) => c.replay_status === 'UNVERIFIED').length

  // payload 刷新（如重新拉取 job）时同步本地用例副本
  useEffect(() => { setCases(payload?.cases || []) }, [payload])

  // 默认勾选：只选已回放（非 UNVERIFIED）的用例
  const [selected, setSelected] = useState(() => new Set(cases.filter((c) => c.replay_status !== 'UNVERIFIED').map((c) => c.title)))
  const [editing, setEditing] = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [autoExec, setAutoExec] = useState(false)
  const [rowPreview, setRowPreview] = useState(null)
  const [filterCategory, setFilterCategory] = useState('all')
  const [filterModule, setFilterModule] = useState('all')
  const [filterSeverity, setFilterSeverity] = useState('all')
  const [pickerOpen, setPickerOpen] = useState(false)

  const modules = useMemo(() => {
    const m = {}
    for (const c of cases) {
      const k = c.module || '未分类'
      m[k] = (m[k] || 0) + 1
    }
    return m
  }, [cases])

  const moduleOptions = useMemo(() => Object.keys(modules).map((m) => ({ label: m, value: m })), [modules])

  // 筛选后的用例
  const filteredCases = useMemo(() => {
    return cases.filter((c) => {
      if (filterCategory !== 'all' && (c.category || '').toUpperCase() !== filterCategory.toUpperCase()) return false
      if (filterModule !== 'all' && c.module !== filterModule) return false
      if (filterSeverity !== 'all' && c.severity !== filterSeverity) return false
      return true
    })
  }, [cases, filterCategory, filterModule, filterSeverity])

  const toggle = (row) => {
    const title = row.title
    setSelected((prev) => {
      if (prev.has(title)) {
        const n = new Set(prev)
        n.delete(title)
        return n
      }
      return new Set(prev).add(title)
    })
    if (row.replay_status === 'UNVERIFIED' && !selected.has(title)) {
      Modal.confirm({
        title: '纳入未验证用例？',
        content: '该用例为写接口，未回放验证，确认将其纳入入库？',
        okText: '纳入入库',
        cancelText: '取消',
        onOk: () => setSelected((prev) => new Set(prev).add(title)),
      })
    }
  }

  const doConfirm = () => {
    if (selected.size === 0) return
    const includeUnverified = cases.some((c) => c.replay_status === 'UNVERIFIED' && selected.has(c.title))
    const submit = async () => {
      setConfirming(true)
      try {
        const { default: http } = await import('../../api/http')
        const body = { selected_case_titles: [...selected], auto_execute: autoExec, cases_override: cases }
        if (includeUnverified) body.include_unverified = true
        const d = await http.post(`/ai/discover/${jobId}/confirm`, body)
        onConfirmed?.(d)
      } catch {
        /* 拦截器已提示 */
      } finally {
        setConfirming(false)
      }
    }
    const openConfirmModal = () => {
      Modal.confirm({
        title: '确认入库',
        content: `将把选中的 ${selected.size} 条用例（含关联数据集/场景）写入资产中心${includeUnverified ? '（含未验证用例）' : ''}${autoExec ? '，并立即自动执行' : ''}。`,
        okText: '确认入库',
        cancelText: '再想想',
        okButtonProps: { style: { background: C.cyan, borderColor: C.cyan } },
        onOk: submit,
      })
    }
    // FE-15：入库前按选中用例计算模块维度覆盖率，低于阈值弹警告二次确认
    const selectedCases = cases.filter((c) => selected.has(c.title))
    const cov = calcModuleCoverage(selectedCases, datasets, scenarios, payload?.coverage_targets)
    const lowMods = Object.entries(cov).filter(([, pct]) => pct < COVERAGE_WARN_THRESHOLD)
    if (lowMods.length > 0) {
      Modal.confirm({
        title: '覆盖率不足警告',
        icon: null,
        content: (
          <div style={{ color: C.text }}>
            以下模块的六维覆盖率低于 {COVERAGE_WARN_THRESHOLD}%，建议补充用例后再入库：
            <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {lowMods.map(([m, pct]) => (
                <Tag key={m} color={pct < 40 ? 'red' : 'orange'}>{m} · {pct}%</Tag>
              ))}
            </div>
          </div>
        ),
        okText: '仍继续入库',
        cancelText: '返回补充',
        okButtonProps: { style: { background: C.amber, borderColor: C.amber } },
        onOk: openConfirmModal,
      })
      return
    }
    openConfirmModal()
  }

  const doExport = async () => {
    try {
      const { default: http } = await import('../../api/http')
      const d = await http.get(`/ai/discover/${jobId}/export`)
      const blob = new Blob([d?.content || ''], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = d?.filename || `test_plan_${jobId}.md`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      const { message } = await import('antd')
      message.success('测试计划已导出')
    } catch {
      /* 拦截器已提示 */
    }
  }

  // 功能测试 Tab 列定义
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
      title: '类别',
      dataIndex: 'category',
      width: 90,
      render: (c) => {
        const cat = (c || '').toUpperCase()
        const colorMap = { API: 'blue', UI: 'purple', PERFORMANCE: 'orange', SECURITY: 'red', DATAFLOW: 'cyan' }
        return <Tag color={colorMap[cat] || 'default'}>{c}</Tag>
      },
    },
    {
      title: '严重度',
      dataIndex: 'severity',
      width: 80,
      render: (s) => <Tag color={SEV_COLOR[s] || 'default'}>{s}</Tag>,
    },
    {
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
        <Button size="small" type="text" icon={<RedoOutlined />} onClick={() => setEditing({ ...r, _origTitle: r.title })} title="编辑" />
      ),
    },
  ].filter((col) => !(readOnly && col.title === ''))

  // 数据集列定义
  const dsColumns = [
    {
      title: '数据集',
      dataIndex: 'name',
      render: (v, r) => <a onClick={() => setRowPreview(r)} style={{ color: C.cyan }}>{v}</a>,
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

  // 场景列定义
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

  const tabItems = [
    {
      key: 'functional',
      label: (
        <span>
          <ApiOutlined /> 功能测试（{cases.filter((c) => (c.category || '').toUpperCase() === 'API').length}）
        </span>
      ),
      children: (
        <div>
          <div style={{ marginBottom: 12, display: 'flex', gap: 8 }}>
            <Select
              value={filterCategory}
              onChange={setFilterCategory}
              style={{ width: 120 }}
              options={[
                { label: '全部类别', value: 'all' },
                { label: 'API', value: 'API' },
                { label: 'UI', value: 'UI' },
                { label: 'PERFORMANCE', value: 'PERFORMANCE' },
                { label: 'SECURITY', value: 'SECURITY' },
                { label: 'DATAFLOW', value: 'DATAFLOW' },
              ]}
            />
            <Select
              value={filterModule}
              onChange={setFilterModule}
              style={{ width: 140 }}
              placeholder="全部模块"
              options={[{ label: '全部模块', value: 'all' }, ...moduleOptions]}
            />
            <Select
              value={filterSeverity}
              onChange={setFilterSeverity}
              style={{ width: 120 }}
              options={[
                { label: '全部严重度', value: 'all' },
                { label: 'P0', value: 'P0' },
                { label: 'P1', value: 'P1' },
                { label: 'P2', value: 'P2' },
                { label: 'P3', value: 'P3' },
                { label: 'P4', value: 'P4' },
              ]}
            />
          </div>
          <Table
            size="small"
            rowKey="title"
            columns={caseColumns}
            dataSource={filteredCases.filter((c) => (c.category || '').toUpperCase() === 'API')}
            pagination={{ pageSize: 10, showSizeChanger: false }}
          />
        </div>
      ),
    },
    {
      key: 'ui',
      label: (
        <span>
          <DashboardOutlined /> UI 测试（{cases.filter((c) => (c.category || '').toUpperCase() === 'UI').length}）
        </span>
      ),
      children: <DiscoverPreviewUITab cases={cases} selected={selected} onToggle={toggle} readOnly={readOnly} onEdit={setEditing} />,
    },
    {
      key: 'performance',
      label: (
        <span>
          <ThunderboltOutlined /> 性能测试（{cases.filter((c) => (c.category || '').toUpperCase() === 'PERFORMANCE').length}）
        </span>
      ),
      children: <DiscoverPreviewPerfTab cases={cases} selected={selected} onToggle={toggle} readOnly={readOnly} />,
    },
    {
      key: 'security',
      label: (
        <span>
          <SafetyOutlined /> 安全测试（{cases.filter((c) => ['SECURITY', 'REDTEAM'].includes((c.category || '').toUpperCase())).length}）
        </span>
      ),
      children: <DiscoverPreviewSecTab cases={cases} selected={selected} onToggle={toggle} readOnly={readOnly} />,
    },
    {
      key: 'dataflow',
      label: (
        <span>
          <ExperimentOutlined /> 数据流（{scenarios.length}）
        </span>
      ),
      children: <Table size="small" rowKey="name" columns={scColumns} dataSource={scenarios} pagination={{ pageSize: 10 }} />,
    },
    {
      key: 'dataset',
      label: (
        <span>
          <DatabaseOutlined /> 数据集（{datasets.length}）
        </span>
      ),
      children: <Table size="small" rowKey="name" columns={dsColumns} dataSource={datasets} pagination={{ pageSize: 10 }} />,
    },
    {
      key: 'heatmap',
      label: <span>覆盖率热力图</span>,
      children: <DiscoverCoverageHeatmap cases={cases} datasets={datasets} scenarios={scenarios} coverageTargets={payload?.coverage_targets} canonicalModules={payload?.canonical_modules} moduleAliases={payload?.module_aliases} />,
    },
  ]

  return (
    <div className="disc-panel" style={{ marginTop: 14 }}>
      {/* 六维度统计卡片 */}
      <DiscoverStatsCards
        cases={cases}
        datasets={datasets}
        scenarios={scenarios}
        confidence={confidence}
        replayedCount={replayedCount}
        unverifiedCount={unverifiedCount}
      />

      {/* 操作栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 10 }}>
        <Space size="large" wrap>
          {!readOnly && (
            <span style={{ color: C.dim, fontSize: 12 }}>
              已选用例：<strong style={{ color: C.text }}>{selected.size}</strong> 条
            </span>
          )}
        </Space>
        <Space>
          {!readOnly && (
            <Checkbox checked={autoExec} onChange={(e) => setAutoExec(e.target.checked)}>
              <span style={{ color: C.dim, fontSize: 12 }}>入库后自动执行（API_TEST）</span>
            </Checkbox>
          )}
          <Button
            icon={<ExportOutlined />}
            style={{ borderColor: C.panelBorder, color: C.dim }}
            onClick={doExport}
          >
            导出测试计划
          </Button>
          {!readOnly && (
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
          )}
        </Space>
      </div>

      {/* 模块标签 */}
      {Object.keys(modules).length > 0 && (
        <div style={{ marginBottom: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {Object.entries(modules).map(([m, n]) => (
            <Tag key={m} color="cyan">
              {m} · {n}
            </Tag>
          ))}
        </div>
      )}

      {/* 六维度 Tab */}
      <Tabs items={tabItems} defaultActiveKey="functional" />

      {/* 编辑用例弹窗 */}
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
            <Text style={{ color: C.dim, fontSize: 12 }}>用例标题</Text>
            <Input value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} style={{ background: '#0d1420', color: C.text }} />
            <Text style={{ color: C.dim, fontSize: 12 }}>请求路径</Text>
            <Input value={editing.request_spec?.path} onChange={(e) => setEditing({ ...editing, request_spec: { ...editing.request_spec, path: e.target.value } })} style={{ background: '#0d1420', color: C.text, fontFamily: MONO }} />
            <Text style={{ color: C.dim, fontSize: 12 }}>预期状态码</Text>
            <Input value={editing.request_spec?.expected_status} onChange={(e) => setEditing({ ...editing, request_spec: { ...editing.request_spec, expected_status: parseInt(e.target.value || '0', 10) } })} style={{ background: '#0d1420', color: C.text, fontFamily: MONO }} />
            {/* FE-12：DOM 选择器编辑（CSS/XPath 语法校验 + 截图点选取选择器） */}
            <Text style={{ color: C.dim, fontSize: 12 }}>DOM 选择器（CSS / XPath）</Text>
            <Space.Compact style={{ width: '100%' }}>
              <Input
                value={editing.dom_selector}
                placeholder="如 #username、input[name='user'] 或 //button[@type='submit']"
                onChange={(e) => setEditing({ ...editing, dom_selector: e.target.value })}
                style={{ background: '#0d1420', color: C.text, fontFamily: MONO }}
                status={validateSelector(editing.dom_selector) ? 'error' : undefined}
              />
              <Button
                icon={<AimOutlined />}
                onClick={() => setPickerOpen(true)}
                title="截图点选获取选择器"
                style={{ background: '#0d1420', color: C.text, borderColor: C.panelBorder }}
              >
                点选
              </Button>
            </Space.Compact>
            {validateSelector(editing.dom_selector) && (
              <Text style={{ color: C.red, fontSize: 12 }}>{validateSelector(editing.dom_selector)}</Text>
            )}
            {/* FE-13：性能用例配置可视化编辑（并发滑块 + RT/TPS 目标输入） */}
            {(editing.category || '').toUpperCase() === 'PERFORMANCE' && (
              <>
                <Text style={{ color: C.dim, fontSize: 12, marginTop: 8 }}>并发梯度（拖动调整峰值并发）</Text>
                <Slider
                  min={1}
                  max={500}
                  step={1}
                  value={editing.performance_config?.concurrency?.[editing.performance_config.concurrency.length - 1] || 50}
                  onChange={(v) => {
                    const cfg = { ...(editing.performance_config || {}) }
                    const base = cfg.concurrency && cfg.concurrency.length ? cfg.concurrency : [10, 25, 50]
                    cfg.concurrency = [Math.max(1, Math.floor(v * 0.2)), Math.max(2, Math.floor(v * 0.6)), v]
                    setEditing({ ...editing, performance_config: cfg })
                  }}
                  tooltip={{ formatter: (v) => `${v} 并发` }}
                />
                <Space size="small" style={{ width: '100%' }}>
                  <Text style={{ color: C.dim, fontSize: 12 }}>当前梯度：{(editing.performance_config?.concurrency || []).join(' / ')}</Text>
                </Space>
                <Space size="middle" wrap style={{ marginTop: 8 }}>
                  <span>
                    <Text style={{ color: C.dim, fontSize: 12 }}>持续时间(s) </Text>
                    <InputNumber
                      min={5}
                      max={3600}
                      value={editing.performance_config?.duration || 60}
                      onChange={(v) => setEditing({ ...editing, performance_config: { ...(editing.performance_config || {}), duration: v || 60 } })}
                      style={{ width: 90, background: '#0d1420' }}
                    />
                  </span>
                  <span>
                    <Text style={{ color: '#fa8c16', fontSize: 12 }}>P95(ms) </Text>
                    <InputNumber
                      min={10}
                      max={60000}
                      value={editing.performance_config?.target_rt_p95 || 500}
                      onChange={(v) => setEditing({ ...editing, performance_config: { ...(editing.performance_config || {}), target_rt_p95: v || 500 } })}
                      style={{ width: 90, background: '#0d1420' }}
                    />
                  </span>
                  <span>
                    <Text style={{ color: '#f5222d', fontSize: 12 }}>P99(ms) </Text>
                    <InputNumber
                      min={20}
                      max={120000}
                      value={editing.performance_config?.target_rt_p99 || 1000}
                      onChange={(v) => setEditing({ ...editing, performance_config: { ...(editing.performance_config || {}), target_rt_p99: v || 1000 } })}
                      style={{ width: 90, background: '#0d1420' }}
                    />
                  </span>
                  <span>
                    <Text style={{ color: C.cyan, fontSize: 12 }}>TPS </Text>
                    <InputNumber
                      min={1}
                      max={100000}
                      value={editing.performance_config?.target_tps || 100}
                      onChange={(v) => setEditing({ ...editing, performance_config: { ...(editing.performance_config || {}), target_tps: v || 100 } })}
                      style={{ width: 90, background: '#0d1420' }}
                    />
                  </span>
                </Space>
              </>
            )}
            <Button
              type="primary"
              style={{ background: C.cyan, borderColor: C.cyan, alignSelf: 'flex-end' }}
              disabled={!!validateSelector(editing.dom_selector)}
              onClick={() => {
                const cat = (editing.category || '').toUpperCase()
                const next = { ...editing }
                if (cat === 'UI' && next.dom_selector) {
                  next.steps = [
                    { seq: 1, action: 'click', target: next.dom_selector, config: { selector: next.dom_selector } },
                  ]
                }
                const orig = next._origTitle || next.title
                delete next._origTitle
                setCases((prev) => prev.map((c) => (c.title === orig ? next : c)))
                setSelected((prev) => {
                  const s = new Set(prev)
                  if (s.delete(orig)) s.add(next.title)
                  return s
                })
                setEditing(null)
              }}
            >
              完成
            </Button>
          </Space>
        )}
      </Modal>

      {/* FE-12：截图点选取选择器（热区叠加层） */}
      <DiscoverSelectorPicker
        open={pickerOpen && !!editing}
        jobId={jobId}
        uiElements={payload?.ui_elements || []}
        onPick={(sel) => {
          setEditing((prev) => (prev ? { ...prev, dom_selector: sel } : prev))
          setPickerOpen(false)
        }}
        onCancel={() => setPickerOpen(false)}
      />

      {/* 数据集预览抽屉 */}
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
