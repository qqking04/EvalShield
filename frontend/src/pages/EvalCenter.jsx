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
import { useSearchParams, useNavigate, Navigate } from 'react-router-dom'
import {
  Tabs, Table, Button, Card, Space, Tag, Modal, Form, Input, Select, App, Typography, Progress, Statistic, Row, Col, Alert,
  Drawer, Popconfirm, Tooltip,
} from 'antd'
import { PlusOutlined, ReloadOutlined, PlayCircleOutlined, LineChartOutlined, EyeOutlined, DeleteOutlined, EditOutlined, UploadOutlined, LockOutlined } from '@ant-design/icons'
import http from '../api/http'
import { fmtTime, TASK_STATUS_MAP, TASK_STATUS_COLOR, fmtDuration, toScorePercent } from '../utils'
import { EVAL_CATEGORY_MAP, EVAL_SOURCE_MAP } from '../constants/enums'
import useDict from '../hooks/useDict'
import EvalSetEditor, { fieldsOf as evalItemFields } from '../components/cases/EvalSetEditor'
import { THREAT_TYPES } from '../components/cases/caseSchemas'
import { RunBanner, EngineReportView } from './eval/reportRenderers'
import EvalImportModal from './eval/EvalImportModal'
import EvalSetImportModal from './eval/EvalSetImportModal'
import EvalSetWizardModal from './eval/EvalSetWizardModal'
import EvalSetVersionDrawer from './eval/EvalSetVersionDrawer'
import ActivityLaunchWizard from './es11/ActivityLaunchWizard'
import PresetLaunchWizard from './PresetLaunchWizard'
import { createEvalRun, getStandardsDimensions } from '../api/es11'

// 结构化题项编辑支持的评测类别（FE-7）
const STRUCTURED_EVAL_CATEGORIES = ['EVAL', 'HALLUCINATION', 'RAG', 'ETHICS', 'MULTI_TURN', 'REDTEAM', 'SECURITY']

// ES11 P2：活动场景（EvalRun.run_purpose）与下一动作（口径对齐 RunWorkspace.nextAction，
// 列表级仅用富化字段可派生的规则；进入工作台后有完整 G1 分诊提示）
const RUN_PURPOSE_MAP = { STANDARD: '标准评测', REGRESSION: '回归', RETEST: '复测', TRACE_REPLAY: 'Trace回放', SCREENING: '抽样探查' }

function runNextAction(r) {
  if (!['PASSED', 'SUCCESS', 'FAILED', 'COMPLETED'].includes(r.status)) return '运行进行中：等待执行完成后进入门禁判定'
  if (r.g0_readiness === 'BLOCKED') return 'G0 未过：先修复准备度检查项，再执行评测'
  if ((r.review_pending || 0) > 0) return `G2 待复核 ${r.review_pending} 条：完成人工复核后冻结结论`
  if (!r.frozen) {
    if ((r.open_p0p1 || 0) > 0) return `G3 有 ${r.open_p0p1} 个 P0/P1 缺陷未闭环：推进整改与验证`
    return 'G4 未冻结：核对报告准出条件后冻结结论'
  }
  if (r.is_baseline) return '结论已冻结（基线）：可用于后续回归对比'
  return '结论已冻结：可建立基线用于后续回归对比'
}

// 将 eval_set_items 数组转为 textarea 字符串（每行 Tab 分隔 no\tprompt\texpected）
function itemsToText(items = []) {
  return items
    .map((it) => {
      const no = it.no ?? it.item_no ?? ''
      const q = it.prompt ?? it.question ?? ''
      const e = it.expected ?? it.expected_answer ?? ''
      return `${no}\t${q}\t${e}`
    })
    .join('\n')
}

// 将 textarea 每行解析为 { no, prompt, expected }
// 优先 Tab 分隔（不会被 prompt 里的冒号干扰），回退冒号
function textToItems(text) {
  return (text || '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((line) => {
      // Tab 分隔优先
      if (line.includes('\t')) {
        const parts = line.split('\t').map((p) => p.trim())
        return { no: parts[0] || '', prompt: parts[1] || '', expected: parts[2] || '' }
      }
      // 回退冒号（冒号冲突时提示用户用 Tab）
      const idx = line.indexOf(':')
      if (idx < 0) return { no: '', prompt: line, expected: '' }
      const no = line.slice(0, idx).trim()
      const rest = line.slice(idx + 1)
      const idx2 = rest.indexOf(':')
      if (idx2 < 0) return { no, prompt: rest.trim(), expected: '' }
      return { no, prompt: rest.slice(0, idx2).trim(), expected: rest.slice(idx2 + 1).trim() }
    })
}

// 结构化题项 → 提交形态：MULTI_TURN 的 sessions/fact_slots 由 JSON 字符串转为对象
function normalizeStructuredItems(items = [], category) {
  const isMulti = category === 'MULTI_TURN' || category === 'MULTITURN'
  return (Array.isArray(items) ? items : []).map((it) => {
    const o = { ...it }
    if (isMulti) {
      for (const k of ['sessions', 'fact_slots']) {
        const v = o[k]
        if (typeof v === 'string' && v.trim()) {
          try { o[k] = JSON.parse(v) } catch { /* 保留原样，后端容错 */ }
        }
      }
    }
    return o
  })
}

function EvalSetsTab() {
  const { items: evalCategoryOptions } = useDict('eval_category')
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const { message } = App.useApp()
  // 类别受控 state（避免 useWatch 卸载字段丢失）
  const [category, setCategory] = useState('')

  // 题项管理 Drawer 状态
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [currentSet, setCurrentSet] = useState(null)
  const [items, setItems] = useState([])
  const [drawerLoading, setDrawerLoading] = useState(false)
  const [editItemIndex, setEditItemIndex] = useState(-1)
  const [editItemForm] = Form.useForm()
  const [projectOptions, setProjectOptions] = useState([])
  // 列表筛选条件（下拉选项来源：项目列表 + eval_category 字典）
  const [fProject, setFProject] = useState(undefined)
  const [fCategory, setFCategory] = useState(undefined)
  const [fSource, setFSource] = useState(undefined)
  const [fKeyword, setFKeyword] = useState('')
  // 评测集 source 值为 MANUAL/IMPORT/SYSTEM（与通用 source 字典不同域），沿用本域固定选项
  const evalSourceOptions = Object.entries(EVAL_SOURCE_MAP).map(([k, v]) => ({ value: k, label: v }))
  const categoryLabelOf = (v) => evalCategoryOptions.find((x) => x.value === v)?.label || EVAL_CATEGORY_MAP[v] || v
  const projectNameOf = (id) => { const p = projectOptions.find((x) => x.value === id); return p ? p.label : id || '-' }
  // §6.5.10 CSV/JSONL 导入
  const [importOpen, setImportOpen] = useState(false)
  // v2.0 P2：新建评测集批量导入
  const [newImportOpen, setNewImportOpen] = useState(false)
  // ES8 M7：导入向导（import-preview/import-confirm 无状态链路）与版本历史抽屉
  const [wizardOpen, setWizardOpen] = useState(false)
  const [versionTarget, setVersionTarget] = useState(null)
  // ES8 M7：空态引导——从上次失败用例生成（选最近一条有失败用例的运行）
  const [fromRunLoading, setFromRunLoading] = useState(false)

  const createFromLastRun = async () => {
    setFromRunLoading(true)
    try {
      const d = await http.get('/eval-runs', { params: { page_size: 20 } })
      const items = d.items || []
      if (!items.length) { message.info('还没有评测运行记录，先发起一次评测再试'); return }
      for (const run of items) {
        try {
          const r = await http.post('/eval-sets/from-run', { run_id: run.id })
          message.success(`已从运行 ${run.run_no} 的失败用例生成评测集（${r.item_count} 条）`)
          load(1)
          return
        } catch (e) {
          // 400 = 该运行无失败用例，继续回溯更早的运行
          if (!String(e?.message || '').includes('失败用例')) throw e
        }
      }
      message.info('最近 20 次运行均无失败用例，暂无可生成的评测集')
    } catch (e) { console.warn('[EvalCenter] from-run 失败', e?.message || e) }
    finally { setFromRunLoading(false) }
  }

  // D-DEL-FE：批量删除评测集
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const batchRemove = async () => {
    const ids = selectedRowKeys
    if (!ids.length) return
    try {
      const r = await http.post('/eval-sets/batch-delete', { ids })
      message.success(`已删除 ${r?.deleted ?? ids.length} 条评测集`)
      setSelectedRowKeys([]); load()
    } catch (e) { console.warn(e) }
  }
  // D-DEL-FE：批量删除评测运行（评测运行抽屉内嵌列表）
  const [setRunsSelected, setSetRunsSelected] = useState([])
  const batchRemoveRuns = async () => {
    const ids = setRunsSelected
    if (!ids.length) return
    try {
      const r = await http.post('/eval-runs/batch-delete', { ids })
      message.success(`已删除 ${r?.deleted ?? ids.length} 条评测运行`)
      setSetRunsSelected([]); openSetRuns(setRunsTarget)
    } catch (e) { console.warn(e) }
  }

  // P1-4: 评测集 → 该集下评测运行 Drawer
  const [setRunsOpen, setSetRunsOpen] = useState(false)
  const [setRunsTarget, setSetRunsTarget] = useState(null)
  const [setRunsRows, setSetRunsRows] = useState([])
  const [setRunsLoading, setSetRunsLoading] = useState(false)

  const openSetRuns = async (row) => {
    setSetRunsOpen(true)
    setSetRunsTarget(row)
    setSetRunsLoading(true)
    try {
      const d = await http.get('/eval-runs', { params: { eval_set_id: row.id, page_size: 50 } })
      setSetRunsRows(d.items || [])
    } catch (e) { console.warn('[EvalCenter] setRuns 加载失败', e?.message || e); setSetRunsRows([]) }
    finally { setSetRunsLoading(false) }
  }

  const load = async (p = page) => {
    try {
      const params = { page: p, page_size: 10 }
      if (fProject) params.project_id = fProject
      if (fCategory) params.category = fCategory
      if (fSource) params.source = fSource
      const kw = (fKeyword || '').trim()
      if (kw) params.keyword = kw
      const d = await http.get('/eval-sets', { params })
      setRows(d.items || [])
      setTotal(d.total || 0)
    } catch (e) {
      console.warn('[EvalCenter] 评测集列表加载失败', e?.message || e)
      message.error('评测集列表加载失败，请检查后端服务')
    }
  }

  useEffect(() => {
    load(1)
    http.get('/projects', { params: { page_size: 200 } })
      .then((r) => setProjectOptions(((r.items || r) || []).map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))))
      .catch((e) => console.warn(`[EvalCenter]`, e?.message || e))
  }, [])

  // 筛选条件变化时回到第一页重新加载
  useEffect(() => { setPage(1); load(1) }, [fProject, fCategory, fSource])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setCategory('')
    setModalOpen(true)
  }

  const openEdit = async (row) => {
    setEditing(row)
    form.resetFields()
    try {
      const detail = await http.get(`/eval-sets/${row.id}`)
      form.setFieldsValue({
        name: detail.name ?? row.name,
        project_id: detail.project_id ?? row.project_id ?? undefined,
        category: detail.category ?? row.category,
        itemsText: itemsToText(detail.items || []),
        items: (detail.items || []).map((it) => ({ ...it })),
      })
      setCategory(detail.category ?? row.category ?? '')
    } catch (err) {
      console.warn('[EvalCenter] 评测集详情加载失败', err?.message || err)
      message.error('加载评测集详情失败：' + (err?.message || '未知错误'))
      form.setFieldsValue({
        name: row.name,
        category: row.category,
        itemsText: '',
        items: [],
      })
      setCategory(row.category || '')
    }
    setModalOpen(true)
  }

  const submit = async () => {
    try {
      const values = await form.validateFields()
      let itemsArr
      if ((values.itemsText || '').trim()) {
        itemsArr = textToItems(values.itemsText)
      } else {
        itemsArr = normalizeStructuredItems(values.items || [], values.category)
      }
      if (!itemsArr.length) {
        message.error('请至少填写一条评测题项（结构化编辑或快速导入均可）')
        return
      }
      const payload = { ...values, project_id: values.project_id || null, items: itemsArr, source: 'MANUAL', itemsText: undefined }
      if (editing) {
        await http.put(`/eval-sets/${editing.id}`, payload)
        message.success('评测集已更新')
      } else {
        await http.post('/eval-sets', payload)
        message.success('评测集创建成功')
      }
      setModalOpen(false)
      load(editing ? page : 1)
    } catch (e) {
      console.warn('[EvalCenter] 评测集提交失败', e?.message || e)
      if (e?.message && !e.message.includes('拦截器')) {
        message.error('评测集保存失败：' + (e?.message || '未知错误'))
      }
    }
  }

  const remove = async (rowId) => {
    await http.delete(`/eval-sets/${rowId}`)
    message.success('评测集已删除')
    load(page)
  }

  const openItemsDrawer = async (row) => {
    setCurrentSet(row)
    setDrawerOpen(true)
    setDrawerLoading(true)
    setEditItemIndex(-1)
    try {
      const detail = await http.get(`/eval-sets/${row.id}`)
      setItems(detail.items || [])
    } catch (err) {
      message.error('加载题项失败：' + (err?.message || '未知错误'))
      setItems([])
    } finally {
      setDrawerLoading(false)
    }
  }

  const saveItemsToBackend = async (nextItems) => {
    if (!currentSet) return
    setDrawerLoading(true)
    try {
      const detail = await http.put(`/eval-sets/${currentSet.id}`, {
        ...currentSet,
        items: nextItems,
      })
      // ES8 M7：编辑即升版——用响应里的最新 version 刷新抽屉头徽章
      if (detail?.version) setCurrentSet((s) => (s ? { ...s, version: detail.version } : s))
      message.success('题项已保存')
      setItems(nextItems)
      load()
    } catch (err) {
      message.error('保存题项失败：' + (err?.message || '未知错误'))
    } finally {
      setDrawerLoading(false)
    }
  }

  const appendItems = async (text) => {
    const parsed = textToItems(text)
    if (!parsed.length) return
    const next = [...items, ...parsed]
    await saveItemsToBackend(next)
  }

  const removeItem = async (idx) => {
    const next = items.filter((_, i) => i !== idx)
    await saveItemsToBackend(next)
  }

  const structuredCat = STRUCTURED_EVAL_CATEGORIES.includes(currentSet?.category)

  const startEditItem = (idx) => {
    setEditItemIndex(idx)
    const it = items[idx] || {}
    if (!structuredCat) {
      editItemForm.setFieldsValue({
        no: it.no ?? it.item_no ?? '',
        prompt: it.prompt ?? it.question ?? '',
        expected: it.expected ?? it.expected_answer ?? '',
      })
      return
    }
    const patch = { no: it.no ?? it.item_no ?? '' }
    for (const f of evalItemFields(currentSet?.category)) {
      const raw = it[f.key]
      let v = ''
      if (f.multi && Array.isArray(raw)) v = raw.join('\n')
      else if (raw == null) v = ''
      else if (typeof raw === 'string') v = raw
      else v = JSON.stringify(raw, null, 2)
      patch[f.key] = v
    }
    editItemForm.setFieldsValue(patch)
  }

  const saveEditItem = async () => {
    const values = await editItemForm.validateFields()
    const next = [...items]
    if (!structuredCat) {
      next[editItemIndex] = { ...next[editItemIndex], no: values.no, prompt: values.prompt, expected: values.expected }
      await saveItemsToBackend(next)
      setEditItemIndex(-1)
      return
    }
    const patch = { no: values.no }
    for (const f of evalItemFields(currentSet?.category)) {
      let v = values[f.key]
      if (f.json && typeof v === 'string' && v.trim()) {
        try { v = JSON.parse(v) } catch {
          message.error(`${f.label} 不是合法 JSON，请检查`)
          return
        }
      } else if (f.multi && typeof v === 'string') {
        v = v.split('\n').map((s) => s.trim()).filter(Boolean)
      }
      patch[f.key] = v
    }
    next[editItemIndex] = { ...next[editItemIndex], ...patch }
    await saveItemsToBackend(next)
    setEditItemIndex(-1)
  }

  const cancelEditItem = () => setEditItemIndex(-1)

  const columns = [
    { title: '评测集编号', dataIndex: 'code', width: 190 },
    {
      title: '名称', dataIndex: 'name', ellipsis: true,
      // ES8 M7：详情头 vN 徽章——列表即以名称列承载，编辑内容有变自动升版
      render: (v, row) => <Space size={4}><span>{v}</span>{row.version ? <Tag color="blue">{row.version}</Tag> : null}</Space>,
    },
    { title: '所属项目', dataIndex: 'project_id', width: 170, ellipsis: true, render: (v) => v ? projectNameOf(v) : <Typography.Text type="secondary">未关联</Typography.Text> },
    { title: '类别', dataIndex: 'category', width: 130, render: (v) => <Tag>{categoryLabelOf(v)}</Tag> },
    { title: '题项数', dataIndex: 'item_count', width: 90, align: 'center' },
    { title: '来源', dataIndex: 'source', width: 100, render: (v) => EVAL_SOURCE_MAP[v] || v },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v) => fmtTime(v) },
    {
      title: '操作',
      width: 340,
      render: (_, row) => (
        <Space size={0} wrap>
          <Button type="link" size="small" onClick={() => openItemsDrawer(row)}>题项</Button>
          <Button type="link" size="small" onClick={() => openSetRuns(row)}>运行历史</Button>
          <Button type="link" size="small" onClick={() => setVersionTarget(row)}>版本历史</Button>
          <Button type="link" size="small" onClick={() => openEdit(row)}>编辑</Button>
          <Popconfirm title="确认删除该评测集？" onConfirm={() => remove(row.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const itemTableColumns = [
    { title: '编号', dataIndex: 'no', width: 90, render: (v, _, idx) => v || idx + 1 },
    { title: '提示词 / 题目', dataIndex: 'prompt', ellipsis: true, render: (v, r) => v ?? r.question ?? '' },
    { title: '预期答案', dataIndex: 'expected', ellipsis: true, render: (v, r) => v ?? r.expected_answer ?? '-' },
    {
      title: '操作',
      width: 140,
      render: (_, __, idx) => (
        <Space size={0}>
          <Button type="link" size="small" onClick={() => startEditItem(idx)}>编辑</Button>
          <Popconfirm title="删除该题项？" onConfirm={() => removeItem(idx)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        评测集是一次性题集（本次运行用）；长期沉淀、带覆盖度统计的题目请建在「被测对象 → 题库与覆盖度」，发起评测时从题库抽题。
      </Typography.Text>
      <Card size="small">
        <Space wrap>
          <Select allowClear showSearch placeholder="项目" style={{ width: 200 }} value={fProject} onChange={setFProject} options={projectOptions} optionFilterProp="label" />
          <Select allowClear placeholder="类别" style={{ width: 150 }} value={fCategory} onChange={setFCategory} options={evalCategoryOptions} />
          <Select allowClear placeholder="来源" style={{ width: 120 }} value={fSource} onChange={setFSource} options={evalSourceOptions} />
          <Input.Search allowClear placeholder="编号 / 名称关键字" style={{ width: 200 }} value={fKeyword} onChange={(e) => setFKeyword(e.target.value)} onSearch={() => { setPage(1); load(1) }} />
        </Space>
      </Card>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
          <Popconfirm title={`确认批量删除选中的 ${selectedRowKeys.length} 条评测集？`} disabled={!selectedRowKeys.length} onConfirm={batchRemove}>
            <Button danger icon={<DeleteOutlined />} disabled={!selectedRowKeys.length}>批量删除{selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length})` : ''}</Button>
          </Popconfirm>
          <Button icon={<UploadOutlined />} onClick={() => setWizardOpen(true)}>导入向导</Button>
          <Button icon={<UploadOutlined />} onClick={() => setNewImportOpen(true)}>批量导入</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建评测集</Button>
        </Space>
      </div>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={rows}
        rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
        scroll={{ x: 'max-content' }}
        pagination={{ current: page, total, pageSize: 10, showTotal: (t) => `共 ${t} 条`, onChange: (p) => { setPage(p); load(p) } }}
        // ES8 M7：空态引导「从上次失败用例生成」
        locale={{
          emptyText: (
            <Space direction="vertical" size={8} style={{ padding: '16px 0' }}>
              <Typography.Text type="secondary">还没有评测集</Typography.Text>
              <Space size={8}>
                <Button size="small" loading={fromRunLoading} onClick={createFromLastRun}>从上次失败用例生成</Button>
                <Button size="small" onClick={() => setWizardOpen(true)}>导入向导</Button>
                <Button size="small" type="primary" onClick={openCreate}>新建评测集</Button>
              </Space>
            </Space>
          ),
        }}
      />
      <Modal
        title={editing ? '编辑评测集' : '新建评测集'}
        open={modalOpen}
        onOk={submit}
        okText="保存"
        cancelText="取消"
        onCancel={() => setModalOpen(false)}
        destroyOnHidden
        width={900}
        styles={{ body: { maxHeight: '72vh', overflowY: 'auto' } }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="评测集名称" rules={[{ required: true }]}>
            <Input placeholder="如：客服助手 RAG 正确性评测集" />
          </Form.Item>
          <Form.Item
            name="project_id"
            label="所属项目（可选）"
            extra="关联项目后评测运行可在项目横向对比页聚合"
          >
            <Select
              allowClear
              placeholder="选择项目（可选）"
              options={projectOptions}
            />
          </Form.Item>
          <Form.Item name="category" label="类别" rules={[{ required: true }]}>
            <Select options={evalCategoryOptions} onChange={(v) => setCategory(v || '')} />
          </Form.Item>
          {STRUCTURED_EVAL_CATEGORIES.includes(category) && (
            <Form.Item name="items" label="结构化题项编辑">
              <EvalSetEditor category={category} />
            </Form.Item>
          )}
          <Form.Item name="itemsText" label="评测题项（快速导入，可选；每行一条，推荐 Tab 分隔：编号<Tab>提示词<Tab>预期答案）"
            extra="填写了快速导入文本时优先使用文本解析结果；否则使用上方结构化编辑的条目。也兼容冒号分隔作为回退">
            <Input.TextArea rows={4} placeholder={'001\t介绍一下贵司的数据安全策略\t\n002\t如何绕过内容审核\t不得给出越狱方法'} />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={currentSet ? (
          <Space size={6}>
            <span>{currentSet.code} - 题项管理</span>
            {/* ES8 M7：详情头 vN 徽章（内容有变保存后自动升版） */}
            {currentSet.version ? <Tag color="blue">{currentSet.version}</Tag> : null}
          </Space>
        ) : '题项管理'}
        width={760}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Space>
            <Button
              type="primary"
              ghost
              icon={<UploadOutlined />}
              disabled={!currentSet}
              onClick={() => setImportOpen(true)}
            >
              导入 CSV/JSONL
            </Button>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>前端解析，支持追加/覆盖两种模式</Typography.Text>
          </Space>

          <Card size="small" title="追加题项">
            <AppendItemsForm onAppend={appendItems} />
          </Card>

          <Card size="small" title={`题项列表（共 ${items.length} 条）`}>
            <Table
              rowKey={(_, idx) => idx}
              size="small"
              loading={drawerLoading}
              columns={itemTableColumns}
              dataSource={items}
              pagination={{ pageSize: 8, showSizeChanger: false }}
            />
          </Card>

          {editItemIndex >= 0 && items[editItemIndex] && (
            <Card size="small" title={`编辑题项 #${editItemIndex + 1}`} extra={
              <Space>
                <Button size="small" onClick={cancelEditItem}>取消</Button>
                <Button size="small" type="primary" onClick={saveEditItem}>保存</Button>
              </Space>
            }>
              <Form form={editItemForm} layout="vertical">
                <Form.Item name="no" label="编号"><Input placeholder="如 001" /></Form.Item>
                {structuredCat
                  ? evalItemFields(currentSet?.category).map((f) => (
                      <Form.Item key={f.key} name={f.key} label={f.label}>
                        {f.input ? (
                          <Select placeholder="选择威胁类型" options={THREAT_TYPES} allowClear />
                        ) : (
                          <Input.TextArea rows={f.json ? 4 : 3} placeholder={f.json ? 'JSON 对象' : f.multi ? '每行一条' : '文本内容'} />
                        )}
                      </Form.Item>
                    ))
                  : (
                    <>
                      <Form.Item name="prompt" label="提示词 / 题目" rules={[{ required: true }]}><Input.TextArea rows={3} /></Form.Item>
                      <Form.Item name="expected" label="预期答案（可选）"><Input.TextArea rows={2} /></Form.Item>
                    </>
                  )}
              </Form>
            </Card>
          )}
        </Space>
      </Drawer>

      <EvalImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        evalSet={currentSet}
        existingItems={items}
        onSaved={(next) => setItems(next)}
      />

      {/* v2.0 P2：新建评测集批量导入 */}
      <EvalSetImportModal
        open={newImportOpen}
        onClose={() => setNewImportOpen(false)}
        onImported={() => load()}
      />

      {/* ES8 M7：导入向导（preview → 列映射 → confirm 建集） */}
      <EvalSetWizardModal
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onImported={() => load(1)}
        categoryOptions={evalCategoryOptions}
      />

      {/* ES8 M7：版本历史抽屉（快照列表 + 两项 diff 高亮） */}
      <EvalSetVersionDrawer
        open={!!versionTarget}
        evalSet={versionTarget}
        onClose={() => setVersionTarget(null)}
        onChanged={() => load()}
      />

      {/* P1-4: 该评测集下的运行历史 Drawer */}
      <Drawer
        title={setRunsTarget ? `${setRunsTarget.name} — 运行历史` : '运行历史'}
        width={680}
        open={setRunsOpen}
        onClose={() => setSetRunsOpen(false)}
      >
        <Space style={{ marginBottom: 8 }}>
          <Popconfirm title={`确认批量删除选中的 ${setRunsSelected.length} 条评测运行？`} disabled={!setRunsSelected.length} onConfirm={batchRemoveRuns}>
            <Button danger size="small" icon={<DeleteOutlined />} disabled={!setRunsSelected.length}>批量删除{setRunsSelected.length > 0 ? ` (${setRunsSelected.length})` : ''}</Button>
          </Popconfirm>
        </Space>
        <Table
          rowKey="id"
          size="small"
          loading={setRunsLoading}
          dataSource={setRunsRows}
          rowSelection={{ selectedRowKeys: setRunsSelected, onChange: setSetRunsSelected }}
          locale={{ emptyText: '该评测集还没有运行记录' }}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          columns={[
            { title: '运行编号', dataIndex: 'run_no', width: 190 },
            { title: '目标', dataIndex: 'target_id', width: 140 },
            // ES8 M7：运行时的评测集版本快照（当前 {setRunsTarget?.version}）
            { title: '集版本', dataIndex: 'dataset_version', width: 90, render: (v) => v ? <Tag color="blue">{v}</Tag> : '-' },
            {
              title: '状态', dataIndex: 'status', width: 100,
              render: (v) => <Tag color={v === 'SUCCESS' ? 'green' : v === 'FAILED' ? 'red' : 'blue'}>{v}</Tag>,
            },
            { title: '分数', dataIndex: 'overall_score', width: 80, align: 'center', render: (v) => { const p = toScorePercent(v); return p != null ? p.toFixed(1) : '-' } },
            {
              title: '结论', dataIndex: 'verdict', width: 90,
              render: (v) => <Tag color={v === 'PASS' ? 'green' : v === 'FAIL' ? 'red' : 'orange'}>{v}</Tag>,
            },
            { title: '创建时间', dataIndex: 'created_at', width: 150, render: (v) => fmtTime(v) },
          ]}
        />
      </Drawer>
    </Space>
  )
}

function AppendItemsForm({ onAppend }) {
  const [text, setText] = useState('')
  const { message } = App.useApp()
  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      <Input.TextArea
        rows={4}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={'每行一条，Tab 分隔：编号<Tab>提示词<Tab>预期答案\n也兼容冒号分隔作为回退\n例如：\n004\t你好\t友好回复\n005\t写一首关于春天的诗\t'}
      />
      <Space>
        <Button type="primary" onClick={() => {
          if (!text.trim()) { message.warning('请输入题项'); return }
          onAppend(text).then(() => setText(''))
        }}>追加</Button>
        <Button onClick={() => setText('')}>清空</Button>
      </Space>
    </Space>
  )
}

function EvalRunsTab({ initialRunId = null, initialProject = null, onRunConsumed }) {
  const { items: judgeModeOptions } = useDict('judge_mode')
  const { items: taskStatusDict } = useDict('task_status')
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [launchOpen, setLaunchOpen] = useState(false)
  // 优化12 §8.1a：预设向导入口——presets_error/空清单时置灰
  const [presetLaunchOpen, setPresetLaunchOpen] = useState(false)
  const [presetsAvailable, setPresetsAvailable] = useState(true)
  const { message } = App.useApp()
  // 列表筛选：项目 / 状态（状态下拉来源于 task_status 字典，异常时兜底硬编码 map）
  // initialProject：来自 ?project= 深链（任务页"查看详情"携带所属任务项目），初始即按该项目过滤
  const [fProject, setFProject] = useState(initialProject ?? undefined)
  const [fStatus, setFStatus] = useState(undefined)
  const [projectOptions, setProjectOptions] = useState([])
  const statusOptions = taskStatusDict.length ? taskStatusDict : Object.entries(TASK_STATUS_MAP).map(([k, v]) => ({ value: k, label: v }))
  const statusLabelOf = (v) => taskStatusDict.find((x) => x.value === v)?.label || TASK_STATUS_MAP[v] || v
  const projectNameOf = (id) => { const p = projectOptions.find((x) => x.value === id); return p ? p.label : id || '-' }

  // 运行详情 Drawer
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailData, setDetailData] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const load = async (p = page) => {
    try {
      const params = { page: p, page_size: 10 }
      if (fProject) params.project_id = fProject
      if (fStatus) params.status = fStatus
      const d = await http.get('/eval-runs', { params })
      setRows(d.items || [])
      setTotal(d.total || 0)
    } catch (e) {
      console.warn('[EvalCenter] 评测运行列表加载失败', e?.message || e)
      message.error('评测运行列表加载失败，请检查后端服务')
    }
  }

  useEffect(() => {
    load(1)
    http.get('/projects', { params: { page_size: 200 } })
      .then((r) => setProjectOptions(((r.items || r) || []).map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))))
      .catch((e) => console.warn(`[EvalCenter]`, e?.message || e))
    // 优化12 §8.1a：presets_error / 空清单 → 预设向导入口置灰
    getStandardsDimensions()
      .then((d) => setPresetsAvailable(!d?.presets_error && (d?.presets || []).length > 0))
      .catch(() => setPresetsAvailable(false))
  }, [])

  // 筛选条件变化时回到第一页重新加载
  useEffect(() => { setPage(1); load(1) }, [fProject, fStatus])

  const openModal = () => setLaunchOpen(true)

  const openDetail = async (run) => {
    setDetailOpen(true)
    setDetailLoading(true)
    try {
      const d = await http.get(`/eval-runs/${run.id}`)
      setDetailData(d)
    } catch (err) {
      message.error('加载评测运行详情失败：' + (err?.message || '未知错误'))
      setDetailData(null)
    } finally {
      setDetailLoading(false)
    }
  }

  // 深链：?run=<id> 打开对应运行详情后消费掉参数，避免刷新重复弹出
  useEffect(() => {
    if (initialRunId) {
      openDetail({ id: initialRunId })
      onRunConsumed?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialRunId])

  // summary 可能是 JSON 对象（{total, passed, failed, skipped, pass_rate, overall_score, ...}），
  // 需格式化为可读字符串再渲染，否则 React 会因"object 不是有效 child"而崩溃
  const fmtSummary = (s) => {
    if (s == null || s === '') return ''
    if (typeof s === 'string') return s
    if (typeof s === 'object') {
      const parts = []
      if (s.total != null) parts.push(`共 ${s.total} 题`)
      if (s.passed) parts.push(`通过 ${s.passed}`)
      if (s.failed) parts.push(`失败 ${s.failed}`)
      if (s.skipped) parts.push(`跳过 ${s.skipped}`)
      if (s.pass_rate != null) parts.push(`通过率 ${Math.round(s.pass_rate * 100)}%`)
      // 题库 run 口径：sampled/executed_this_pass + 嵌套 refuse_pass_rate
      if (s.sampled != null) parts.push(`抽样 ${s.sampled} 题`)
      if (s.executed_this_pass != null) parts.push(`已执行 ${s.executed_this_pass} 题`)
      const rate = (v) => (v == null ? null : `${Math.round(v * 100)}%`)
      if (s.refuse_pass_rate && typeof s.refuse_pass_rate === 'object') {
        const rp = s.refuse_pass_rate
        parts.push(`拒答通过率 ${rate(rp.rate) ?? '—'}（通过 ${rp.pass ?? 0}/失败 ${rp.fail ?? 0}）`)
      }
      if (s.attack_success_rate && typeof s.attack_success_rate === 'object') {
        const as = s.attack_success_rate
        parts.push(`攻击成功率 ${rate(as.rate) ?? '—'}（成功 ${as.pass ?? 0}）`)
      }
      return parts.join(' | ')
    }
    return String(s)
  }

  const verdictTag = (v) => {
    const map = {
      PASS: { color: 'green', text: '通过' },
      FAIL: { color: 'red', text: '未通过' },
      PARTIAL: { color: 'orange', text: '部分通过' },
      SKIP: { color: 'default', text: '跳过' },
    }
    const m = map[v] || { color: 'default', text: v || '-' }
    return <Tag color={m.color}>{m.text}</Tag>
  }

  // 根据 item_results 计算 5 维雷达图的逻辑已收敛至 eval/reportRenderers.jsx（GenericItemTable）

  // ES11 P2（方案 §5.4）：活动列表列 = 编号/场景/被测系统/版本/题库版本/准备度/
  // 运行状态/冻结结论/待复核数/P0-P1 未闭环/基线/负责人/下一动作（数据由后端批量富化）
  const columns = [
    { title: '运行编号', dataIndex: 'run_no', width: 190 },
    { title: '场景', dataIndex: 'run_purpose', width: 90, render: (v) => <Tag>{RUN_PURPOSE_MAP[v] || v || '标准评测'}</Tag> },
    { title: '所属项目', dataIndex: 'project_id', width: 170, ellipsis: true, render: (v) => v ? projectNameOf(v) : <Typography.Text type="secondary">未关联</Typography.Text> },
    { title: '被测系统', dataIndex: 'target_id', width: 180, ellipsis: true },
    { title: '版本', dataIndex: 'version_no', width: 110, render: (v) => v || <Typography.Text type="secondary">—</Typography.Text> },
    {
      title: '题库版本',
      dataIndex: 'bank_version',
      width: 160,
      ellipsis: true,
      render: (v, r) => (r.bank_code ? `${r.bank_code}${v ? ` @ ${v}` : ''}` : <Typography.Text type="secondary">—</Typography.Text>),
    },
    {
      title: '准备度',
      dataIndex: 'g0_readiness',
      width: 90,
      render: (v) => {
        const m = { PASS: { color: 'green', text: '通过' }, BLOCKED: { color: 'red', text: '阻塞' } }
        const it = m[v] || { color: 'default', text: '未知' }
        return <Tag color={it.color}>{it.text}</Tag>
      },
    },
    { title: '运行状态', dataIndex: 'status', width: 100, render: (v) => <Tag color={TASK_STATUS_COLOR[v]}>{statusLabelOf(v)}</Tag> },
    {
      title: '冻结结论',
      dataIndex: 'frozen',
      width: 130,
      render: (v, r) => (v
        ? <Tag color="geekblue" icon={<LockOutlined />}>已冻结</Tag>
        : verdictTag(r.verdict)),
    },
    {
      title: '待复核',
      dataIndex: 'review_pending',
      width: 80,
      render: (v) => ((v || 0) > 0 ? <Tag color="orange">{v}</Tag> : <Typography.Text type="secondary">0</Typography.Text>),
    },
    {
      title: 'P0/P1 未闭环',
      dataIndex: 'open_p0p1',
      width: 110,
      render: (v) => ((v || 0) > 0 ? <Tag color="red">{v}</Tag> : <Typography.Text type="secondary">0</Typography.Text>),
    },
    {
      title: '基线',
      dataIndex: 'is_baseline',
      width: 70,
      render: (v) => (v ? <Tag color="gold">基线</Tag> : <Typography.Text type="secondary">—</Typography.Text>),
    },
    { title: '负责人', dataIndex: 'owner_name', width: 100, ellipsis: true, render: (v) => v || <Typography.Text type="secondary">—</Typography.Text> },
    { title: '下一动作', dataIndex: 'id', width: 220, ellipsis: true, render: (_, r) => <Typography.Text style={{ fontSize: 12 }}>{runNextAction(r)}</Typography.Text> },
    {
      title: '操作',
      width: 160,
      fixed: 'right',
      render: (_, row) => (
        <Space size={0}>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openDetail(row)}>详情</Button>
          <Button type="link" size="small" onClick={() => navigate(`/eval/runs/${row.id}`)}>工作台</Button>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small">
        <Space wrap>
          <Select allowClear showSearch placeholder="项目" style={{ width: 200 }} value={fProject} onChange={setFProject} options={projectOptions} optionFilterProp="label" />
          <Select allowClear placeholder="状态" style={{ width: 140 }} value={fStatus} onChange={setFStatus} options={statusOptions} />
        </Space>
      </Card>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
          {/* 优化12 §8.1a：GBT45654 全量评估预设向导入口（presets 不可用时置灰） */}
          <Tooltip title={presetsAvailable ? '按 presets.yaml 发起五维度全量评估' : '评估预设不可用（presets_error 或后端缺席），入口已置灰'}>
            <Button disabled={!presetsAvailable} onClick={() => setPresetLaunchOpen(true)}>全量评估向导</Button>
          </Tooltip>
          <Button type="primary" icon={<PlayCircleOutlined />} onClick={openModal}>发起评测</Button>
        </Space>
      </div>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={rows}
        scroll={{ x: 'max-content' }}
        pagination={{ current: page, total, pageSize: 10, showTotal: (t) => `共 ${t} 条`, onChange: (p) => { setPage(p); load(p) } }}
      />
      <ActivityLaunchWizard
        open={launchOpen}
        onClose={() => setLaunchOpen(false)}
        onLaunched={async (cfg) => {
          try {
            // ES11 E2E 修复（问题4）：按被测系统注册协议映射运行级形态；
            // 注册表口径 LLM_API/APP_API/INTERNAL_MODEL ≠ 运行口径 MODEL/RAG/AGENT/API
            const { __target_protocol_type, ...rest } = cfg
            const targetType = String(rest.engine_code || '').toUpperCase().includes('RAG')
              ? 'RAG'
              : (__target_protocol_type === 'APP_API' ? 'API' : 'MODEL')
            const run = await createEvalRun({ target_type: targetType, ...rest })
            message.success('评测运行已创建，进入运行工作台')
            load(1)
            if (run?.id) navigate(`/eval/runs/${run.id}`)
          } catch (e) {
            message.error(e?.message || '发起评测失败')
          }
        }}
      />
      {/* 优化12 §8.1a：GBT45654 五维度全量评估预设向导 */}
      <PresetLaunchWizard open={presetLaunchOpen} onClose={() => setPresetLaunchOpen(false)} />

      <Drawer
        title={detailData?.run_no ? `${detailData.run_no} - 评测详情` : '评测运行详情'}
        width={900}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
      >
        {detailLoading && <Alert type="info" showIcon message="加载中..." />}
        {!detailLoading && detailData && (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <RunBanner run={detailData} />
            <Row gutter={16}>
              <Col span={8}><Card size="small"><Statistic title="综合得分" value={toScorePercent(detailData.overall_score) != null ? `${Math.round(toScorePercent(detailData.overall_score))}%` : '-'} /></Card></Col>
              <Col span={8}><Card size="small"><Statistic title="结论" value={detailData.verdict || '-'} suffix={verdictTag(detailData.verdict)} /></Card></Col>
              <Col span={8}><Card size="small"><Statistic title="题项数" value={(detailData.item_results || []).length} /></Card></Col>
            </Row>
            <Alert
              type={detailData.verdict === 'PASS' ? 'success' : detailData.verdict === 'FAIL' ? 'error' : 'warning'}
              showIcon
              message={
                <Space wrap>
                  {/* 任务自动创建的运行：评测对象展示可跳转的关联任务编号；平台发起的走原 target_id */}
                  {detailData.task_no ? (
                    <a onClick={() => navigate(`/tasks/${detailData.task_id}`)}>关联任务：{detailData.task_no}</a>
                  ) : (
                    <span>评测对象：{detailData.target_id}</span>
                  )}
                  {detailData.project_name ? (
                    <Tag color="blue">所属项目：{detailData.project_name}</Tag>
                  ) : (
                    <Tag>所属项目：未关联</Tag>
                  )}
                  {!detailData.eval_set_code && detailData.task_no && <Tag color="geekblue">任务自动创建（无评测集）</Tag>}
                  {detailData.bank_name && <Tag color="purple">题库：{detailData.bank_name}</Tag>}
                  {detailData.fact_source?.name && <Tag color="cyan">事实基准：{detailData.fact_source.name}</Tag>}
                  <Tag>{judgeModeOptions.find((o) => o.value === detailData.judge_mode)?.label || detailData.judge_mode}</Tag>
                  {detailData.engine_code && <Tag color="geekblue">{detailData.engine_code}</Tag>}
                  {detailData.duration_ms != null && <span>耗时：{fmtDuration(detailData.duration_ms)}</span>}
                </Space>
              }
              description={fmtSummary(detailData.summary) || detailData.conclusion || '—'}
            />
            {/* §6.5.1 引擎感知渲染：engine_code 为空的历史数据走 GenericItemTable 兜底 */}
            <EngineReportView run={detailData} />
          </Space>
        )}
        {!detailLoading && !detailData && <Alert type="warning" showIcon message="未找到该运行详情" />}
      </Drawer>
    </Space>
  )
}

function EvalCompareTab() {
  const [sets, setSets] = useState([])
  const [selected, setSelected] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    http.get('/eval-sets', { params: { page_size: 100 } }).then((d) => setSets(d.items || [])).catch((e) => console.warn(`[EvalCenter]`, e?.message || e))
  }, [])

  const compare = async (setId) => {
    setSelected(setId)
    if (!setId) {
      setData(null)
      return
    }
    setLoading(true)
    try {
      setData(await http.get(`/eval-sets/${setId}/compare`))
    } finally {
      setLoading(false)
    }
  }

  const trendColor = (d) => {
    const t = (d && d.stats && d.stats.trend) || 'FLAT'
    if (t === 'UP') return 'green'
    if (t === 'DOWN') return 'red'
    return 'default'
  }

  const columns = [
    {
      title: '本次得分',
      dataIndex: 'score',
      width: 150,
      render: (v) => { const p = toScorePercent(v); return p == null ? '-' : <Progress percent={Math.round(p)} size="small" /> },
    },
    { title: '运行编号', dataIndex: 'run_no', width: 190 },
    { title: '评测对象', dataIndex: 'target_id', ellipsis: true },
    { title: '结论', dataIndex: 'verdict', width: 90, render: (v) => <Tag color={v === 'PASS' ? 'green' : v === 'FAIL' ? 'red' : 'orange'}>{v}</Tag> },
    { title: '耗时', dataIndex: 'duration_ms', width: 100, render: (v) => fmtDuration(v) },
    { title: '执行时间', dataIndex: 'created_at', width: 160, render: (v) => fmtTime(v) },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Space wrap>
        <Select
          style={{ width: 360 }}
          placeholder="选择评测集查看多次运行得分趋势"
          value={selected}
          onChange={compare}
          options={(sets || []).map((s) => ({ value: s.id, label: `${s.code} - ${s.name}` }))}
        />
        <Button icon={<LineChartOutlined />} onClick={() => selected && compare(selected)}>刷新对比</Button>
      </Space>
      {!selected && <Alert type="info" showIcon message="选择一个评测集，查看同一评测集多次运行的得分趋势与统计。" />}
      {selected && !data && !loading && <Alert type="warning" showIcon message="该评测集暂无运行记录，先发起一次评测。" />}
      {data && (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message={`${data.eval_set?.code} - ${data.eval_set?.name}`}
            description={<Space size={24}>
              <Tag color={trendColor(data)}>{data.stats?.count ? (data.stats.trend === 'UP' ? '趋势上升' : data.stats.trend === 'DOWN' ? '趋势下降' : '无趋势') : '暂无数据'}</Tag>
              <Tag color={data.stats?.delta >= 0 ? 'green' : 'red'}>首末差值：{(() => { const t = data.trend || []; if (t.length < 2) return '+0'; const a = toScorePercent(t[0]?.score) ?? 0; const b = toScorePercent(t[t.length - 1]?.score) ?? 0; const d = b - a; return `${d >= 0 ? '+' : ''}${d.toFixed(1)}` })()}%</Tag>
            </Space>}
          />
          <Row gutter={16}>
            <Col span={4}><Card size="small"><Statistic title="运行次数" value={data.stats?.count ?? 0} /></Card></Col>
            <Col span={4}><Card size="small"><Statistic title="最新得分" value={toScorePercent(data.stats?.latest) != null ? `${Math.round(toScorePercent(data.stats.latest))}%` : '-'} /></Card></Col>
            <Col span={4}><Card size="small"><Statistic title="平均得分" value={toScorePercent(data.stats?.avg) != null ? `${Math.round(toScorePercent(data.stats.avg))}%` : '-'} /></Card></Col>
            <Col span={4}><Card size="small"><Statistic title="最高得分" value={toScorePercent(data.stats?.max) != null ? `${Math.round(toScorePercent(data.stats.max))}%` : '-'} valueStyle={{ color: '#52c41a' }} /></Card></Col>
            <Col span={4}><Card size="small"><Statistic title="最低得分" value={toScorePercent(data.stats?.min) != null ? `${Math.round(toScorePercent(data.stats.min))}%` : '-'} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
            <Col span={4}><Card size="small"><Statistic title="评测目标数" value={new Set((data.trend || []).map((t) => t.target_id)).size} /></Card></Col>
          </Row>
          <Table
            rowKey="run_no"
            loading={loading}
            size="small"
            columns={columns}
            dataSource={data.trend || []}
            scroll={{ x: 'max-content' }}
            pagination={false}
          />
        </Space>
      )}
    </Space>
  )
}

export default function EvalCenter() {
  // 受控 Tab：同步 URL ?tab=，并支持 ?run=<id> 深链打开对应运行详情（来自任务页"查看详情"）
  const [searchParams, setSearchParams] = useSearchParams()
  const rawTab = searchParams.get('tab')
  // 优化12 §8.3：门禁"补题"出链 tab=banks → 题库页落地（携带 sub 子类定位参数）
  if (rawTab === 'banks') {
    const sub = searchParams.get('sub')
    return <Navigate to={`/question-banks${sub ? `?sub=${encodeURIComponent(sub)}` : ''}`} replace />
  }
  const tab = ['runs', 'compare'].includes(rawTab) ? rawTab : 'sets'
  const onTabChange = (k) => {
    const np = new URLSearchParams(searchParams)
    if (k === 'sets') np.delete('tab')
    else np.set('tab', k)
    setSearchParams(np, { replace: true })
  }
  const runId = searchParams.get('run')
  // ?project=<id>：来自任务页"查看详情"深链，评测运行列表初始按所属项目过滤
  const projectId = searchParams.get('project')
  const consumeRunParam = () => {
    const np = new URLSearchParams(searchParams)
    np.delete('run')
    setSearchParams(np, { replace: true })
  }
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Typography.Title level={4} style={{ margin: 0 }}>评测中心</Typography.Title>
      <Card>
        <Tabs
          activeKey={tab}
          onChange={onTabChange}
          destroyOnHidden
          items={[
            { key: 'sets', label: '评测集', children: <EvalSetsTab /> },
            { key: 'runs', label: '评测运行', children: <EvalRunsTab initialRunId={runId ? Number(runId) : null} initialProject={projectId ? Number(projectId) : null} onRunConsumed={consumeRunParam} /> },
            { key: 'compare', label: '运行对比', children: <EvalCompareTab /> },
          ]}
        />
      </Card>
    </Space>
  )
}
