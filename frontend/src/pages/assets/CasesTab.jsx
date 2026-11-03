/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Fragment, useEffect, useState } from 'react'
import {
  Table, Button, Card, Space, Tag, Modal, Form, Input, Select, InputNumber, App, Popconfirm, Typography, Alert, Dropdown, Empty, Tooltip, Drawer, Timeline,
} from 'antd'
import { PlusOutlined, ReloadOutlined, DeleteOutlined, EditOutlined, PlayCircleOutlined, SearchOutlined, DownloadOutlined, UploadOutlined, EyeOutlined, SettingOutlined, RobotOutlined, HistoryOutlined, CameraOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import http from '../../api/http'
import { fmtTime } from '../../utils'
import fetchAll from '../../utils/fetchAll'
import { CASE_CATEGORY_MAP, CASE_SEVERITY_MAP, CASE_SEVERITY_COLOR, CASE_PRIORITY_MAP, CASE_STATUS_MAP, CASE_STATUS_COLOR, CASE_SOURCE_MAP } from '../../constants/enums'
import useDict from '../../hooks/useDict'
import { useEdition } from '../../edition/EditionContext'
import { CASE_CONTENT_SCHEMAS } from '../../components/cases/caseSchemas'
import StepEditor from '../../components/cases/StepEditor'
import ApiCaseEditor from '../../components/cases/ApiCaseEditor'
import DataGridEditor from '../../components/cases/DataGridEditor'
import PreconditionEditor from '../../components/cases/PreconditionEditor'
import PostCleanupEditor from '../../components/cases/PostCleanupEditor'
import EvalSetEditor from '../../components/cases/EvalSetEditor'
import SecuritySampleEditor from '../../components/cases/SecuritySampleEditor'
import AssertionRows from '../../components/cases/AssertionRows'
import CaseDetailDrawer from '../../components/cases/CaseDetailDrawer'
import CaseImportExport from '../../components/cases/CaseImportExport'

// FE-01：类别专属内容字段（切换类别时需清空，避免旧类别内容残留/错位）
const CONTENT_FIELD_KEYS = [
  'steps', 'request_spec', 'eval_items', 'security_samples',
  'perf_concurrency', 'perf_total', 'perf_ramp', 'perf_p95', 'perf_qps',
  'ai_model_gateway', 'ai_expect',
  'preconditions', 'test_data', 'assertions', 'post_cleanup',
]
// FE-01：各 editorType 提交时允许携带的内容字段（其余一律剔除）
const EDITOR_CONTENT_FIELDS = {
  step: ['steps', 'extract_vars'],
  api: ['request_spec'],
  perf: ['request_spec'],
  eval: ['eval_items', 'request_spec'],
  security: ['security_samples'],
  dataflow: [],
  engineering: [],
}
const ALL_PAYLOAD_CONTENT_FIELDS = ['steps', 'extract_vars', 'request_spec', 'eval_items', 'security_samples']

export default function CasesTab({ onDataChanged, initialProjectId }) {
  const { items: categoryOptions } = useDict('case_category')
  // 严重度/状态下拉来源于数据字典（接口异常时兜底原硬编码选项）
  const { items: severityDict } = useDict('severity')
  const { items: caseStatusDict } = useDict('case_status')
  const { items: priorityDict } = useDict('priority')
  const priorityFilterOptions = priorityDict.length ? priorityDict : [{ value: 'HIGH', label: '高' }, { value: 'MEDIUM', label: '中' }, { value: 'LOW', label: '低' }]
  const severityFilterOptions = severityDict.length ? severityDict : [{ value: 'P0', label: 'P0 致命' }, { value: 'P1', label: 'P1 严重' }, { value: 'P2', label: 'P2 重要' }, { value: 'P3', label: 'P3 一般' }, { value: 'P4', label: 'P4 轻微' }]
  const statusFilterOptions = caseStatusDict.length ? caseStatusDict : [{ value: 'ACTIVE', label: 'ACTIVE 启用' }, { value: 'DISABLED', label: 'DISABLED 禁用' }, { value: 'ARCHIVED', label: 'ARCHIVED 归档' }]
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [projects, setProjects] = useState([])
  const [modelConfigs, setModelConfigs] = useState([])
  const [datasets, setDatasets] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const { message, modal } = App.useApp()

  // 类别受控 state（避免使用 Form.useWatch 卸载字段导致 BUG-41 字段丢失）
  const [category, setCategory] = useState('')
  const [contentSchema, setContentSchema] = useState(null)
  const [contentDirty, setContentDirty] = useState(false)
  const projectIdWatch = Form.useWatch('project_id', form)

  // FE-02：项目环境可用性缓存（project_id → { hasEnv, defaultBaseUrl }）
  const [projectEnvMap, setProjectEnvMap] = useState({})

  const [filterCategory, setFilterCategory] = useState(null)
  const [filterProjectId, setFilterProjectId] = useState(initialProjectId || null)
  const [filterSeverity, setFilterSeverity] = useState(null)
  const [filterStatus, setFilterStatus] = useState(null)
  const [filterKeyword, setFilterKeyword] = useState('')
  const [filterModule, setFilterModule] = useState('')

  // 批量删除
  const [selectedRowKeys, setSelectedRowKeys] = useState([])

  // BUG-005：默认仅显示 8 个核心列（用例编号/标题/所属模块/类别/状态/严重度/优先级/操作），
  // 其余次要列默认隐藏，统一在「列设置」中按需开启
  const COLUMN_TOGGLE_OPTIONS = [
    { key: 'project_id', label: '所属项目' },
    { key: 'steps', label: '内容' },
    { key: 'assertions', label: '断言数' },
    { key: 'test_data', label: '数据分组' },
    { key: 'requirement_id', label: '需求编号' },
    { key: 'run_count', label: '执行次数' },
    { key: 'pass_rate', label: '通过率' },
    { key: 'created_at', label: '创建时间' },
  ]
  const [hiddenCols, setHiddenCols] = useState({ project_id: true, steps: true, assertions: true, test_data: true, requirement_id: true, run_count: true, pass_rate: true, created_at: true })
  const toggleableKeys = COLUMN_TOGGLE_OPTIONS.map((o) => o.key)
  const visibleToggleKeys = COLUMN_TOGGLE_OPTIONS.filter((o) => !hiddenCols[o.key]).map((o) => o.key)

  // 导入导出
  const [importOpen, setImportOpen] = useState(false)
  const [importText, setImportText] = useState('')
  const [importLoading, setImportLoading] = useState(false)
  const [importResult, setImportResult] = useState(null)

  const [quickRunOpen, setQuickRunOpen] = useState(false)
  const [quickRunCase, setQuickRunCase] = useState(null)
  const [quickRunLoading, setQuickRunLoading] = useState(false)
  const [quickRunForm] = Form.useForm()
  const [engines, setEngines] = useState([])
  // F3：enabled_engines 驱动引擎白名单。清单未就绪（未加载/拉取失败/空数组）前不裁剪，
  // 拿到商业口径响应后再裁剪，社区部署下商业引擎不出现在下拉。
  const { enabled_engines: enabledEngines } = useEdition()
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailCase, setDetailCase] = useState(null)

  // P2-19：资产版本历史（快照 / 列表 / diff / 回滚）
  const [verOpen, setVerOpen] = useState(false)
  const [verCase, setVerCase] = useState(null)
  const [verList, setVerList] = useState([])
  const [verLoading, setVerLoading] = useState(false)
  const [verDiff, setVerDiff] = useState(null)

  const loadVersions = async (pid, cid) => {
    setVerLoading(true)
    try {
      const d = await http.get(`/projects/${pid}/assets/CASE/${cid}/versions`)
      setVerList(Array.isArray(d) ? d : (d && d.items) || [])
    } catch { setVerList([]) } finally { setVerLoading(false) }
  }
  const openVersions = (row) => {
    const pid = row.project_id || filterProjectId
    if (!pid) { message.warning('缺少项目 ID，无法查看版本'); return }
    setVerCase({ ...row, _pid: pid })
    setVerDiff(null)
    setVerOpen(true)
    loadVersions(pid, row.id)
  }
  const doSnapshot = async () => {
    const { id, _pid } = verCase
    try {
      await http.post(`/projects/${_pid}/assets/CASE/${id}/snapshot`, { change_note: '手动快照' })
      message.success('已创建版本快照')
      loadVersions(_pid, id)
    } catch (e) { message.error('快照失败：' + (e?.message || e)) }
  }
  const doCompare = async (fromSeq, toSeq) => {
    const { id, _pid } = verCase
    try {
      const d = await http.get(`/projects/${_pid}/assets/CASE/${id}/versions/compare`,
        { params: { from_seq: fromSeq, to_seq: toSeq } })
      setVerDiff(d)
    } catch (e) { message.error('对比失败：' + (e?.message || e)) }
  }
  const doRollback = async (seq) => {
    const { id, _pid } = verCase
    try {
      await http.post(`/projects/${_pid}/assets/CASE/${id}/versions/${seq}/rollback`)
      message.success(`已回滚至 v${seq}`)
      setVerOpen(false)
      load(page)
      notifyChanged()
    } catch (e) { message.error('回滚失败：' + (e?.message || e)) }
  }

  const notifyChanged = () => { if (typeof onDataChanged === 'function') onDataChanged() }

  // FE-02：加载项目被测环境（TestEnvironment 新表），判断是否有可用环境
  const loadProjectEnv = async (pid) => {
    try {
      const d = await http.get(`/projects/${pid}/environments`)
      const envs = (d && d.items) || (Array.isArray(d) ? d : [])
      const def = envs.find((e) => e.is_default) || envs[0]
      return { hasEnv: envs.length > 0, defaultBaseUrl: (def && (def.base_url || def.url)) || '' }
    } catch {
      // 拉取失败时按「未知」处理，不阻塞执行（base_url 必填规则仍会兜底）
      return { hasEnv: true, defaultBaseUrl: '' }
    }
  }

  // FE-01：内容字段被用户修改后标记为「已编辑」，切换类别时用于二次确认
  const onFormValuesChange = (changed) => {
    if (Object.keys(changed || {}).some((k) => CONTENT_FIELD_KEYS.includes(k))) setContentDirty(true)
  }

  // FE-01：切换类别 → 清空旧类别内容字段；已有编辑内容时先确认
  const handleCategoryChange = (v) => {
    if (!v || v === category) return
    const doSwitch = () => {
      form.resetFields(CONTENT_FIELD_KEYS)
      setCategory(v)
      setContentSchema(null)
      setContentDirty(false)
    }
    if (contentDirty) {
      modal.confirm({
        title: '切换类别将清空已编辑内容，确认继续？',
        content: '切换后当前类别的内容字段（步骤 / 请求配置 / 评测条目 / 性能参数等）将被清空。',
        okText: '确认切换',
        cancelText: '取消',
        onOk: doSwitch,
        onCancel: () => { form.setFieldsValue({ category }) },
      })
    } else {
      doSwitch()
    }
  }

  const load = async (p = page, extraParams = {}) => {
    setLoading(true)
    try {
      const params = {
        page: p,
        page_size: 10,
        category: filterCategory || undefined,
        project_id: filterProjectId || undefined,
        severity: filterSeverity || undefined,
        status: filterStatus || undefined,
        keyword: (filterKeyword || '').trim() || undefined,
        module: (filterModule || '').trim() || undefined,
        ...extraParams,
      }
      const data = await http.get('/cases', { params })
      setRows(data.items || [])
      setTotal(data.total || 0)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!projectIdWatch) { setDatasets([]); return }
    http.get('/datasets', { params: { project_id: projectIdWatch, page_size: 200 } })
      .then((d) => setDatasets((d && d.items) || (Array.isArray(d) ? d : [])))
      .catch((e) => { setDatasets([]); console.warn('[CasesTab] datasets load failed', e?.message || e) })
  }, [projectIdWatch])

  // FE-02：预取当前列表用例所属项目的环境可用性，决定「执行」按钮是否可用
  useEffect(() => {
    const pids = [...new Set((rows || []).map((r) => r.project_id).filter((x) => x != null))]
    const missing = pids.filter((pid) => projectEnvMap[pid] === undefined)
    if (missing.length === 0) return
    let cancelled = false
    Promise.all(missing.map((pid) => loadProjectEnv(pid).then((info) => [pid, info])))
      .then((pairs) => { if (!cancelled) setProjectEnvMap((m) => ({ ...m, ...Object.fromEntries(pairs) })) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, projectEnvMap])

  useEffect(() => {
    load(1)
    http.get('/projects', { params: { page_size: 100 } }).then((d) => setProjects(d.items || [])).catch((e) => console.warn(`[CasesTab]`, e?.message || e))
    http.get('/model-configs').then((d) => {
      const items = d.items || d || []
      setModelConfigs(items.filter((m) => m.status === 'ACTIVE'))
    }).catch((e) => console.warn(`[CasesTab]`, e?.message || e))
    http.get('/engines').then((d) => {
      setEngines(d.items || d || [])
    }).catch((e) => console.warn(`[CasesTab] engines load failed`, e?.message || e))
  }, [])

  // FE-06：从父组件（Assets.jsx）接收的项目筛选变化时，重置内部筛选并刷新
  useEffect(() => {
    if (initialProjectId !== undefined && initialProjectId !== filterProjectId) {
      setFilterProjectId(initialProjectId || null)
      // 项目切换：清空关键词/模块/类别/严重度/状态等内部筛选，避免旧筛选残留
      setFilterKeyword('')
      setFilterModule('')
      setFilterCategory(null)
      setFilterSeverity(null)
      setFilterStatus(null)
      setPage(1)
      setSelectedRowKeys([])
      const pid = initialProjectId || undefined
      http.get('/cases', { params: { page: 1, page_size: 10, project_id: pid } })
        .then((d) => { setRows(d.items || []); setTotal(d.total || 0); setLoading(false) })
        .catch((e) => { setRows([]); setTotal(0); setLoading(false); console.warn('[CasesTab] project switch load failed', e?.message || e) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialProjectId])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setCategory('')
    setContentSchema(null)
    setContentDirty(false)
    form.setFieldsValue({ severity: 'P2', priority: 'MEDIUM' })
    setModalOpen(true)
  }

  const openEdit = async (row) => {
    setEditing(row)
    form.resetFields()
    if (row.project_id) {
      try {
        const dsData = await http.get('/datasets', { params: { project_id: row.project_id, page_size: 200 } })
        setDatasets((dsData && dsData.items) || (Array.isArray(dsData) ? dsData : []))
      } catch { /* ignore */ }
    }
    let detail = row
    try {
      const d = await http.get(`/cases/${row.id}`)
      detail = d && d.data ? d.data : (d || row)
    } catch { /* ignore */ }
    const rs = detail.request_spec ? (typeof detail.request_spec === 'string' ? safeParse(detail.request_spec) : detail.request_spec) : {}
    const cat = detail.category || ''
    const schema = detail.content_schema || CASE_CONTENT_SCHEMAS[cat] || null
    const isPerf = cat === 'PERFORMANCE'
    setCategory(cat)
    setContentSchema(schema)
    form.setFieldsValue({
      project_id: detail.project_id,
      title: detail.title,
      module: detail.module || '',
      category: cat,
      severity: detail.severity,
      priority: detail.priority,
      requirement_id: detail.requirement_id || '',
      precondition: detail.precondition,
      expected: detail.expected,
      dataset_id: detail.dataset_id || undefined,
      tags: detail.tags || [],
      steps: detail.steps || [],
      request_spec: (CASE_CONTENT_SCHEMAS[cat]?.editor === 'api' && rs) ? rs : undefined,
      eval_items: detail.eval_items || (Array.isArray(rs.prompts) ? rs.prompts.map((p) => ({ prompt: p })) : []),
      security_samples: detail.security_samples || [],
      preconditions: detail.preconditions || [],
      test_data: detail.test_data || [],
      assertions: detail.assertions || [],
      post_cleanup: detail.post_cleanup || [],
      perf_concurrency: rs.concurrency ?? 10,
      perf_total: rs.total_requests ?? 100,
      perf_ramp: rs.ramp_up_seconds ?? 1,
      perf_p95: rs.p95_limit_ms ?? 500,
      perf_qps: rs.target_qps ?? 0,
      ai_model_gateway: rs.model_gateway || undefined,
      ai_expect: rs.expect || '',
    })
    // FE-01：已有内容的用例视为「已编辑」，切换类别时需二次确认
    setContentDirty(!!((detail.steps || []).length || (detail.eval_items || []).length
      || (detail.security_samples || []).length || (rs && Object.keys(rs).length)))
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    const cat = values.category
    const editorType = CASE_CONTENT_SCHEMAS[cat]?.editor
    const payload = {
      project_id: values.project_id,
      title: values.title,
      module: (values.module || '').trim() || undefined,
      category: cat,
      severity: values.severity || 'P2',
      priority: values.priority || 'MEDIUM',
      precondition: values.precondition,
      expected: values.expected,
      source: 'MANUAL',
      ...(values.requirement_id ? { requirement_id: String(values.requirement_id).trim() } : {}),
      ...(values.dataset_id ? { dataset_id: values.dataset_id } : {}),
      tags: (values.tags || []).filter(Boolean),
    }

    // content_schema：优先沿用 detail，否则按类别生成
    if (contentSchema && contentSchema.editor) {
      payload.content_schema = { ...contentSchema, editor: editorType }
    } else if (values.category) {
      payload.content_schema = { editor: editorType, ...(CASE_CONTENT_SCHEMAS[cat]?.fields ? { fields: CASE_CONTENT_SCHEMAS[cat].fields } : {}) }
    }

    // 结构化新字段
    payload.preconditions = (values.preconditions || []).map((p) => ({ kind: p.kind, desc: p.desc || '' }))
    payload.test_data = (values.test_data || []).map((td) => ({
      case: td.case || '',
      params: Array.isArray(td.params)
        ? Object.fromEntries(td.params.filter((x) => x && x.key).map((x) => [x.key, x.value]))
        : (td.params && typeof td.params === 'object' ? td.params : {}),
    }))
    payload.assertions = (values.assertions || []).map((a) => ({ path: a.path, op: a.op, expected: a.expected, note: a.note }))
    payload.post_cleanup = (values.post_cleanup || []).map((c) => ({
      action: c.action, target: c.target || '', params: c.params ? safeParse(c.params) : {},
    }))

    if (editorType === 'step') {
      payload.steps = (values.steps || []).map((s) => ({
        action: s.action, target: s.target || '', value: s.value || '',
        ...(s.timeout ? { timeout: s.timeout } : {}),
        assertions: (s.assertions || []).map((a) => ({ path: a.path, op: a.op, expected: a.expected, note: a.note })),
        ...(s.extract && s.extract.var
          ? { extract: { var: s.extract.var, from: s.extract.from || 'page', path: s.extract.path || '' } }
          : {}),
      }))
      // extract_vars 对象：{ var: { from, path } }
      const extractVars = {}
      for (const s of payload.steps) {
        if (s.extract && s.extract.var) extractVars[s.extract.var] = { from: s.extract.from, path: s.extract.path }
      }
      payload.extract_vars = extractVars
    } else if (editorType === 'api') {
      const rs = values.request_spec && typeof values.request_spec === 'object' ? values.request_spec : {}
      payload.request_spec = {
        method: rs.method,
        path: rs.path || rs.url || '',
        headers: Object.fromEntries((headersOf(rs.headers) || []).filter((h) => h.key).map((h) => [h.key, h.value])),
        body: rs.body ? String(rs.body) : '',
        expected_status: rs.expected_status,
        assertions: (rs.assertions || []).map((a) => ({ path: a.path, op: a.op, expected: a.expected, note: a.note })),
      }
      // 校验请求体/断言参数 JSON
      if (payload.request_spec.body && payload.request_spec.body.trim()) {
        try { JSON.parse(payload.request_spec.body) } catch { message.error('接口请求体不是合法 JSON，请检查'); return }
      }
      for (const a of payload.request_spec.assertions) {
        if (a.expected !== '' && a.expected != null) {
          const t = String(a.expected).trim()
          if (t === 'true') { a.expected = true; continue }
          if (t === 'false') { a.expected = false; continue }
          const n = Number(t)
          if (!isNaN(n) && String(n) === t) a.expected = n
        }
      }
    } else if (editorType === 'perf') {
      payload.request_spec = {
        concurrency: values.perf_concurrency,
        total_requests: values.perf_total,
        ramp_up_seconds: values.perf_ramp,
        p95_limit_ms: values.perf_p95,
        target_qps: values.perf_qps,
      }
    } else if (editorType === 'eval') {
      const isMulti = cat === 'MULTITURN' || cat === 'MULTI_TURN'
      const items = (values.eval_items || []).map((it) => {
        const o = { ...it }
        if (isMulti) {
          for (const k of ['sessions', 'fact_slots']) {
            if (typeof o[k] === 'string' && o[k].trim()) {
              try { o[k] = JSON.parse(o[k]) } catch { /* 保留原样 */ }
            }
          }
        }
        return o
      })
      payload.eval_items = items
      payload.request_spec = {
        prompts: items.map((it) => it.prompt ?? it.question ?? '').filter(Boolean),
        model_gateway: values.ai_model_gateway,
        expect: values.ai_expect,
      }
    } else if (editorType === 'security') {
      payload.security_samples = (values.security_samples || []).map((s) => ({
        title: s.title || '', threat_type: s.threat_type, payload: s.payload || '',
        context: s.context ? safeParse(s.context) : {}, expected_behavior: s.expected_behavior || '',
      }))
    }
    // FE-01：仅提交与当前 editorType 匹配的内容字段，剔除类别切换后的残留字段
    const allowedContent = new Set(EDITOR_CONTENT_FIELDS[editorType] || [])
    for (const k of ALL_PAYLOAD_CONTENT_FIELDS) {
      if (!allowedContent.has(k) && payload[k] !== undefined) {
        console.warn(`[CasesTab] 已剔除与类别 ${cat} 不匹配的内容字段：${k}`)
        delete payload[k]
      }
    }
    if (editing) {
      await http.put(`/cases/${editing.id}`, payload)
      message.success('用例已更新')
    } else {
      await http.post('/cases', payload)
      message.success('用例创建成功')
    }
    setModalOpen(false)
    load(editing ? page : 1)
    notifyChanged()
  }

  const remove = async (rowId) => {
    await http.delete(`/cases/${rowId}`)
    message.success('用例已删除')
    load(page)
    notifyChanged()
  }

  // D-DEL-FE：批量删除 测试用例
  const batchRemove = async () => {
    const ids = selectedRowKeys
    if (!ids.length) return
    try {
      const r = await http.post('/cases/batch-delete', { ids })
      message.success(`已删除 ${r?.deleted ?? ids.length} 条测试用例`)
      setSelectedRowKeys([]); load(page); notifyChanged()
    } catch (e) { console.warn(e) }
  }

  // v2.0 推荐方案 #2：OWASP 人工评审项状态闭环跟踪（落库 review_status）
  const updateReviewStatus = async (row, val) => {
    try {
      await http.put(`/cases/${row.id}`, { review_status: val })
      message.success(`评审状态已更新为「${val}」`)
      load(page)
    } catch (err) {
      message.error('更新失败：' + (err?.message || '未知错误'))
    }
  }

  // ---- 导入 / 导出 ----
  // FE-17：循环翻页拉全量，避免 >500 条截断
  const fetchExportItems = async () => {
    const params = {
      project_id: filterProjectId || undefined,
      category: filterCategory || undefined,
      severity: filterSeverity || undefined,
      status: filterStatus || undefined,
      keyword: (filterKeyword || '').trim() || undefined,
      module: (filterModule || '').trim() || undefined,
    }
    Object.keys(params).forEach((k) => { if (params[k] === undefined) delete params[k] })
    return fetchAll(http, '/cases', params)
  }

  // FE-10：JSON 全量导出（含结构化字段）
  const exportFullJsonCases = async () => {
    try {
      const items = await fetchExportItems()
      if (items.length === 0) { message.info('当前筛选条件下没有可导出的用例'); return }
      const n = CaseImportExport.exportFullJson(items)
      message.success(`已全量导出 ${n} 条用例（JSON）`)
    } catch (err) {
      message.error('导出失败：' + (err?.message || '未知错误'))
    }
  }

  // CSV 基础视图导出（保留兼容）
  const exportCsvCases = async () => {
    try {
      const items = await fetchExportItems()
      if (items.length === 0) { message.info('当前筛选条件下没有可导出的用例'); return }
      const n = CaseImportExport.exportCsv(items)
      message.success(`已导出 ${n} 条用例（CSV）`)
    } catch (err) {
      message.error('导出失败：' + (err?.message || '未知错误'))
    }
  }

  const doImport = async () => {
    const raw = (importText || '').trim()
    if (!raw) { message.warning('请粘贴要导入的内容'); return }
    let parsed
    try {
      parsed = CaseImportExport.parseImportText(raw)
    } catch (e) {
      message.error('内容解析失败：' + (e?.message || '请提供合法 JSON 数组或 CSV'))
      return
    }
    const objs = parsed.objs || []
    if (objs.length === 0) { message.warning('没有可导入的行'); return }
    if (objs.length > 500) { message.error('单次导入最多 500 条，请拆分后重试'); return }
    const items = CaseImportExport.normalizeForBulk(objs)
    if (items.length === 0) { message.error('没有有效行：需包含 project_id(项目ID)、title(标题)、category(类别)'); return }
    setImportLoading(true)
    try {
      const res = await http.post('/cases/bulk', { items })
      const created = res?.created || res?.data?.created || 0
      setImportResult({ created, total: objs.length, valid: items.length })
      message.success(`成功导入 ${created} 条用例`)
      setImportOpen(false)
      setImportText('')
      load(1)
      notifyChanged()
    } catch (err) {
      message.error('导入失败：' + (err?.message || '未知错误'))
    } finally {
      setImportLoading(false)
    }
  }

  // 项目名映射（列表"所属项目"列展示用）
  const projectNameOf = (pid) => {
    const p = (projects || []).find((x) => x.id === pid)
    return p ? `${p.code} ${p.name}` : (pid ?? '-')
  }

  const openDetail = async (row) => {
    setDetailCase(row)
    setDetailOpen(true)
    try {
      const d = await http.get(`/cases/${row.id}`)
      const detail = d && d.data ? d.data : (d || row)
      setDetailCase({ ...row, ...detail })
    } catch (e) { console.warn('[CasesTab] 用例详情加载失败', e?.message || e) }
  }

  const openQuickRunCase = async (row) => {
    setQuickRunCase(row)
    quickRunForm.resetFields()
    // FE-02：环境来自 TestEnvironment 新表（项目列表不含 environments），据此回填默认地址
    let info = projectEnvMap[row.project_id]
    if (!info) {
      info = await loadProjectEnv(row.project_id)
      setProjectEnvMap((m) => ({ ...m, [row.project_id]: info }))
    }
    const preferred = defaultEnginesForCategory(row.category)
    const availableCodes = new Set((engines || []).map((e) => e.engine_code || e.code))
    const defaults = preferred.filter((c) => availableCodes.has(c))
    quickRunForm.setFieldsValue({ engines: defaults.length ? defaults : ['UI_TEST', 'API_TEST'] })
    quickRunForm.setFieldsValue({ base_url: info?.defaultBaseUrl || '' })
    setQuickRunOpen(true)
  }

  // FE-02：项目未登记被测环境时，「执行」按钮置灰并提示
  const renderRunButton = (row) => {
    const info = projectEnvMap[row.project_id]
    const hasEnv = info ? info.hasEnv : true
    const btn = (
      <Button type="link" size="small" icon={<PlayCircleOutlined />} disabled={!hasEnv}
        onClick={() => openQuickRunCase(row)}>执行</Button>
    )
    return hasEnv ? btn : <Tooltip title="项目未配置被测环境"><span>{btn}</span></Tooltip>
  }

  const submitQuickRun = async () => {
    if (!quickRunCase) return
    const values = await quickRunForm.validateFields()
    setQuickRunLoading(true)
    try {
      await http.post('/tasks', {
        name: `${quickRunCase.title || quickRunCase.case_no} - 快速执行`,
        project_id: quickRunCase.project_id,
        engines: values.engines,
        config: { case_ids: [quickRunCase.id], base_url: values.base_url },
      })
      message.success('任务创建成功，可前往任务中心执行')
      setQuickRunOpen(false)
    } catch (err) {
      message.error('任务创建失败：' + (err?.message || '未知错误'))
    } finally {
      setQuickRunLoading(false)
    }
  }

  const columns = [
    { title: '用例编号', dataIndex: 'case_no', width: 190 },
    { title: '标题', dataIndex: 'title', ellipsis: true, render: (v, row) => <a onClick={() => openDetail(row)}>{v || '-'}</a> },
    { title: '所属模块', dataIndex: 'module', width: 120, render: (v) => v || <span style={{ color: '#8c8c8c' }}>未设置</span> },
    { title: '所属项目', dataIndex: 'project_id', width: 200, ellipsis: true, render: (v) => projectNameOf(v) },
    { title: '类别', dataIndex: 'category', width: 130, render: (v) => <Tag>{CASE_CATEGORY_MAP[v] || v}</Tag> },
    { title: '状态', dataIndex: 'status', width: 110, render: (v) => <Tag color={CASE_STATUS_COLOR[v] || 'default'}>{CASE_STATUS_MAP[v] || v || '启用'}</Tag> },
    { title: '内容', dataIndex: 'steps', width: 110, align: 'center', render: (_, row) => contentSummaryOf(row) },
    { title: '断言数', dataIndex: 'assertions', width: 90, align: 'center', render: (v) => (Array.isArray(v) ? v.length : 0) },
    { title: '数据分组', dataIndex: 'test_data', width: 90, align: 'center', render: (v) => (Array.isArray(v) ? v.length : 0) },
    { title: '需求编号', dataIndex: 'requirement_id', width: 130, ellipsis: true, render: (v) => (v || '-') },
    {
      title: '评审状态', dataIndex: 'review_status', width: 130,
      render: (v, row) => (['SECURITY', 'REDTEAM'].includes((row.category || '').toUpperCase()) ? (
        <Select size="small" style={{ width: 110 }} value={v || 'PENDING'}
          onChange={(val) => updateReviewStatus(row, val)}
          options={[{ value: 'PENDING', label: '待评审' }, { value: 'IN_REVIEW', label: '评审中' }, { value: 'DONE', label: '已完成' }]} />
      ) : <span style={{ color: '#8c8c8c' }}>-</span>),
    },
    { title: '严重度', dataIndex: 'severity', width: 90, render: (v) => <Tag color={CASE_SEVERITY_COLOR[v] || 'default'}>{CASE_SEVERITY_MAP[v] || v}</Tag> },
    { title: '优先级', dataIndex: 'priority', width: 100, render: (v) => CASE_PRIORITY_MAP[v] || v },
    { title: '执行次数', dataIndex: 'run_count', width: 90, align: 'center' },
    { title: '通过率', dataIndex: 'pass_rate', width: 100, render: (v) => `${((v || 0) * 100).toFixed(1)}%` },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v) => fmtTime(v) },
    {
      title: '操作', width: 380, fixed: 'right',
      render: (_, row) => (
        <Space size={0} wrap>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openDetail(row)}>详情</Button>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          <Button type="link" size="small" icon={<HistoryOutlined />} onClick={() => openVersions(row)}>版本</Button>
          {renderRunButton(row)}
          {row.status !== 'ARCHIVED' && (
            <Popconfirm title="确认删除该用例？" onConfirm={() => remove(row.id)}>
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  const editorType = CASE_CONTENT_SCHEMAS[category]?.editor

  // 按「列设置」过滤次要列
  const displayColumns = columns.filter((c) => !toggleableKeys.includes(c.dataIndex) || !hiddenCols[c.dataIndex])

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert type="info" showIcon
        message="测试用例是执行测试的基本单元。新建用例时按「类别」选择编辑器（UI/API/性能/AI 等），结构化字段（前置条件/测试数据/断言/后置清理）按需填写；可通过「全量导出（JSON）」备份、「导入」批量重建、点「快速执行」试跑单个用例。"
        description="快速体验：点「新建用例」→ 类别选 UI → 填写标题与步骤（动作：goto/click/fill/press/wait/screenshot/assert_text/assert_visible）→ 保存 → 列表中「快速执行」选引擎试跑 → 完成后看执行次数/通过率回写。" />
      <Card size="small">
        <Space wrap>
          <Input placeholder="搜索标题关键字" allowClear prefix={<SearchOutlined />} style={{ width: 200 }} value={filterKeyword}
            onChange={(e) => setFilterKeyword(e.target.value)}
            onPressEnter={() => { setPage(1); load(1) }} />
          <Select placeholder="类别" allowClear style={{ width: 160 }} value={filterCategory} onChange={setFilterCategory} options={categoryOptions} />
          <Select placeholder="所属项目" allowClear style={{ width: 180 }} value={filterProjectId} onChange={setFilterProjectId}
            options={(projects || []).map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))} />
          <Select placeholder="严重度" allowClear style={{ width: 140 }} value={filterSeverity} onChange={setFilterSeverity}
            options={severityFilterOptions} />
          <Select placeholder="状态" allowClear style={{ width: 130 }} value={filterStatus} onChange={setFilterStatus}
            options={statusFilterOptions} />
          <Input placeholder="所属模块" allowClear style={{ width: 160 }} value={filterModule}
            onChange={(e) => setFilterModule(e.target.value)} />
          <Button type="primary" onClick={() => { setPage(1); load(1) }}>查询</Button>
          <Button onClick={() => { setFilterKeyword(''); setFilterCategory(null); setFilterProjectId(null); setFilterSeverity(null); setFilterStatus(null); setFilterModule(''); setPage(1); load(1, { category: undefined, project_id: undefined, severity: undefined, status: undefined, keyword: undefined, module: undefined }) }}>重置</Button>
        </Space>
      </Card>
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
        <Space>
          <Dropdown menu={{
            items: COLUMN_TOGGLE_OPTIONS.map((o) => ({ key: o.key, label: o.label })),
            selectedKeys: visibleToggleKeys,
            onClick: ({ key }) => setHiddenCols((h) => ({ ...h, [key]: !h[key] })),
          }}>
            <Button icon={<SettingOutlined />}>列设置</Button>
          </Dropdown>
          <Button icon={<ReloadOutlined />} onClick={() => { setPage(1); load(1) }}>刷新</Button>
          <Popconfirm title={`确认批量删除选中的 ${selectedRowKeys.length} 条测试用例？`} disabled={!selectedRowKeys.length} onConfirm={batchRemove}>
            <Button danger icon={<DeleteOutlined />} disabled={!selectedRowKeys.length}>批量删除{selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length})` : ''}</Button>
          </Popconfirm>
          <Button icon={<DownloadOutlined />} onClick={exportFullJsonCases}>全量导出（JSON）</Button>
          <Button icon={<DownloadOutlined />} onClick={exportCsvCases}>导出（CSV）</Button>
          <Button icon={<UploadOutlined />} onClick={() => { setImportResult(null); setImportText(''); setImportOpen(true) }}>导入</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用例</Button>
        </Space>
      </div>
      <Table rowKey="id" loading={loading} columns={displayColumns} dataSource={rows} scroll={{ x: 'max-content' }}
        locale={{ emptyText: <Empty description="暂无用例" image={Empty.PRESENTED_IMAGE_SIMPLE}><Space wrap><Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用例</Button><Button icon={<RobotOutlined />} onClick={() => navigate('/ai/discover')}>AI 生成</Button></Space></Empty> }}
        rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
        pagination={{ current: page, total, pageSize: 10, showTotal: (t) => `共 ${t} 条`, onChange: (p) => { setPage(p); load(p) } }} />

      <Modal title={editing ? '编辑测试用例' : '新建测试用例'} open={modalOpen} onOk={submit} okText="保存" cancelText="取消" onCancel={() => setModalOpen(false)} destroyOnHidden width={900} styles={{ body: { maxHeight: '72vh', overflowY: 'auto' } }}>
        <Form form={form} layout="vertical" onValuesChange={onFormValuesChange}>
          {/* ===== 公共元数据段 ===== */}
          <Typography.Title level={5} style={{ marginTop: 0, marginBottom: 8 }}>基本信息</Typography.Title>
          <Space wrap size={[8, 0]}>
            <Form.Item name="project_id" label="所属项目" rules={[{ required: true }]} style={{ width: 300 }}>
              <Select options={(projects || []).map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))} />
            </Form.Item>
            <Form.Item name="dataset_id" label="归属数据集" style={{ width: 300 }}>
              <Select allowClear placeholder={projectIdWatch ? '选择所属数据集（可选）' : '请先选择所属项目'}
                options={(datasets || []).map((d) => ({ value: d.id, label: `${d.code} ${d.name}` }))} disabled={!projectIdWatch} />
            </Form.Item>
            <Form.Item name="tags" label="标签" style={{ width: 300 }}>
              <Select mode="tags" allowClear placeholder="可输入自由标签，回车添加" style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="title" label="用例标题" rules={[{ required: true }]} style={{ width: 300 }}>
              <Input placeholder="如：验证登录接口在弱口令下返回 401" />
            </Form.Item>
            <Form.Item name="module" label="所属模块" style={{ width: 300 }}>
              <Input placeholder="如：登录、订单、支付" maxLength={128} />
            </Form.Item>
            <Form.Item name="requirement_id" label="需求编号" style={{ width: 300 }}>
              <Input placeholder="关联需求编号（可选）" />
            </Form.Item>
            <Form.Item name="category" label="类别" rules={[{ required: true }]} style={{ width: 300 }}>
              <Select options={categoryOptions} onChange={handleCategoryChange} />
            </Form.Item>
            <Form.Item name="severity" label="严重度" initialValue="P2" style={{ width: 140 }}>
              <Select options={severityFilterOptions} />
            </Form.Item>
            <Form.Item name="priority" label="优先级" initialValue="MEDIUM" style={{ width: 140 }}>
              <Select options={priorityFilterOptions} />
            </Form.Item>
          </Space>

          {/* ===== 类别专属段（按 content_schema.editor 动态渲染） ===== */}
          {editorType && (
            <Fragment key={category}>
              <Typography.Title level={5} style={{ marginBottom: 8 }}>用例内容</Typography.Title>
              {editorType === 'step' && (
                <>
                  <Alert type="info" showIcon style={{ marginBottom: 8 }} message="UI 用例按步骤执行：先写 goto 打开被测系统地址，再写点击/填写/断言。" />
                  <Form.Item name="steps" label="测试步骤" required><StepEditor /></Form.Item>
                </>
              )}
              {editorType === 'api' && (
                <>
                  <Alert type="info" showIcon style={{ marginBottom: 8 }} message="配置接口请求的方法、路径、请求头、请求体与断言，引擎按断言集判定。" />
                  <Form.Item name="request_spec" label="接口请求配置"><ApiCaseEditor /></Form.Item>
                </>
              )}
              {editorType === 'eval' && (
                <>
                  <Alert type="info" showIcon style={{ marginBottom: 8 }} message="按类别配置评测条目；模型网关与预期备注供引擎使用。" />
                  <Form.Item name="eval_items" label="评测条目" required><EvalSetEditor category={category} /></Form.Item>
                  <Space wrap align="baseline">
                    <Form.Item name="ai_model_gateway" label="模型网关">
                      <Select allowClear placeholder="留空使用项目默认网关" style={{ width: 320 }}
                        options={modelConfigs.map((m) => ({ value: m.code, label: `${m.name}（${m.code}）` }))} />
                    </Form.Item>
                    <Form.Item name="ai_expect" label="预期判定 / 备注" style={{ width: 380 }}>
                      <Input placeholder="如：不得输出敏感信息" />
                    </Form.Item>
                  </Space>
                </>
              )}
              {editorType === 'security' && (
                <Form.Item name="security_samples" label="安全样本" required><SecuritySampleEditor /></Form.Item>
              )}
              {editorType === 'perf' && (
                <>
                  <Alert type="info" showIcon style={{ marginBottom: 8 }} message="性能测试参数：后端使用 Locust/JMeter 引擎按并发数持续压测。" />
                  <Space wrap>
                    <Form.Item name="perf_concurrency" label="并发数" initialValue={10} rules={[{ required: true }]}><InputNumber min={1} max={10000} style={{ width: 160 }} /></Form.Item>
                    <Form.Item name="perf_total" label="总请求数" initialValue={100} rules={[{ required: true }]}><InputNumber min={1} max={1000000} style={{ width: 160 }} /></Form.Item>
                    <Form.Item name="perf_ramp" label="爬坡时间（秒）" initialValue={1}><InputNumber min={0} max={3600} style={{ width: 160 }} /></Form.Item>
                    <Form.Item name="perf_p95" label="P95 上限（ms）" initialValue={500}><InputNumber min={0} max={600000} style={{ width: 160 }} /></Form.Item>
                    <Form.Item name="perf_qps" label="目标 QPS" initialValue={0}><InputNumber min={0} max={1000000} style={{ width: 160 }} /></Form.Item>
                  </Space>
                </>
              )}
              {(editorType === 'dataflow' || editorType === 'engineering') && (
                <Alert type="info" showIcon message="该类别为工程化/数据流用例，由引擎或配置脚本驱动，无需额外内容编辑。" />
              )}
            </Fragment>
          )}

          {/* ===== 前置条件段 ===== */}
          <Typography.Title level={5} style={{ marginBottom: 8 }}>前置条件</Typography.Title>
          <Form.Item name="preconditions" label="结构化前置条件"><PreconditionEditor /></Form.Item>
          <Form.Item name="precondition" label="前置条件（旧字段，描述文本）"><Input placeholder="如：已登录管理员账号" /></Form.Item>

          {/* ===== 测试数据段 ===== */}
          <Typography.Title level={5} style={{ marginBottom: 8 }}>测试数据</Typography.Title>
          <Form.Item name="test_data" label="测试数据组" extra={projectIdWatch ? '可从数据集参数列导入生成参数模板' : '选择所属项目后可导入数据集参数列'}>
            <DataGridEditor datasets={datasets} projectId={projectIdWatch} />
          </Form.Item>

          {/* ===== 断言集段 ===== */}
          <Typography.Title level={5} style={{ marginBottom: 8 }}>断言集</Typography.Title>
          <Form.Item name="assertions" label="全局断言（UI/API 引擎按此判定）"><AssertionRows /></Form.Item>

          {/* ===== 后置清理段 ===== */}
          <Typography.Title level={5} style={{ marginBottom: 8 }}>后置清理</Typography.Title>
          <Form.Item name="post_cleanup" label="执行后清理动作"><PostCleanupEditor /></Form.Item>

          {/* ===== 兼容旧字段 ===== */}
          <Form.Item name="expected" label="预期结果"><Input.TextArea rows={2} placeholder="预期行为 / 通过标准" /></Form.Item>
        </Form>
      </Modal>

      <Modal title="导入测试用例" open={importOpen} okText="导入" cancelText="取消" confirmLoading={importLoading} onOk={doImport}
        onCancel={() => setImportOpen(false)} destroyOnHidden width={760}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {importResult ? (
            <Alert type="success" showIcon message={`导入完成：有效 ${importResult.valid} 条 / 总 ${importResult.total} 条，成功写入 ${importResult.created} 条`} />
          ) : (
            <>
              <Alert type="info" showIcon
                message={<>支持 JSON 数组（推荐，可含 steps/request_spec/assertions/test_data/post_cleanup 等完整字段），或 CSV（基础字段：project_id(项目ID)、title(标题)、category(类别)）。单次最多 500 条，项目 ID 必须是现存项目的数值编号。</>} />
              <Input.TextArea rows={10} value={importText} onChange={(e) => setImportText(e.target.value)}
                placeholder={'JSON 示例（全量）：\n[{"project_id":17,"title":"导入用例1","category":"API","severity":"P2","priority":"MEDIUM","request_spec":{"method":"GET","path":"/api/login"},"assertions":[{"path":"status","op":"eq","expected":200}]}]\n\nCSV 示例（基础）：\n项目ID,title,category,severity,priority\n17,导入用例1,API,P2,MEDIUM'} />
            </>
          )}
        </Space>
      </Modal>
      <Modal title={`快速执行用例 - ${quickRunCase?.case_no || ''}`} open={quickRunOpen} confirmLoading={quickRunLoading} okText="创建任务" cancelText="取消"
        okButtonProps={{ disabled: quickRunCase ? projectEnvMap[quickRunCase.project_id]?.hasEnv === false : false }}
        onOk={submitQuickRun} onCancel={() => setQuickRunOpen(false)} destroyOnHidden width={640}>
        <Form form={quickRunForm} layout="vertical">
          {quickRunCase && <Alert type="info" showIcon style={{ marginBottom: 12 }} message={`用例：${quickRunCase.title}（${quickRunCase.case_no}）`} />}
          <Form.Item name="engines" label="执行引擎" rules={[{ required: true, message: '请选择至少一个引擎' }]}>
            <Select mode="multiple" placeholder="选择执行引擎"
              options={(engines || [])
                .filter((e) => !(enabledEngines && enabledEngines.length > 0) || enabledEngines.includes(e.engine_code || e.code))
                .map((e) => ({ value: e.engine_code || e.code, label: e.engine_name || e.name || e.engine_code || e.code }))} />
          </Form.Item>
          <Form.Item name="base_url" label="被测系统地址（base_url）"
            rules={[{ required: true, message: '请填写被测系统地址' }]}
            extra="已自动取项目「环境」页签的默认地址；可临时改为其他地址，正式执行建议在项目环境中维护">
            <Input placeholder="如：https://api.example.com" />
          </Form.Item>
        </Form>
      </Modal>
      <CaseDetailDrawer open={detailOpen} data={detailCase} onClose={() => setDetailOpen(false)} />
      {/* P2-19：资产版本历史 Drawer（快照 / diff / 回滚） */}
      <Drawer title={`版本历史 · ${verCase?.case_no || ''}`} width={640} open={verOpen} onClose={() => setVerOpen(false)}
        extra={<Button icon={<CameraOutlined />} type="primary" size="small" onClick={doSnapshot}>创建快照</Button>}>
        {verLoading ? <Empty description="加载中…" /> : (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {verList.length === 0 && <Empty description="暂无版本快照，点右上「创建快照」保存当前内容" />}
            <Timeline
              items={verList.map((v, i) => ({
                key: v.id,
                children: (
                  <Space direction="vertical" size={2}>
                    <Typography.Text strong>v{v.seq} {v.project_version_no ? `（${v.project_version_no}）` : ''}</Typography.Text>
                    <Typography.Text type="secondary">{fmtTime(v.created_at)} {v.change_note ? `· ${v.change_note}` : ''}</Typography.Text>
                    <Space size={4}>
                      {i + 1 < verList.length && (
                        <Button size="small" type="link" onClick={() => doCompare(verList[i + 1].seq, v.seq)}>与上一版对比</Button>
                      )}
                      <Popconfirm title={`确认回滚至 v${v.seq}？当前内容将先自动快照`} onConfirm={() => doRollback(v.seq)}>
                        <Button size="small" type="link" danger>回滚</Button>
                      </Popconfirm>
                    </Space>
                  </Space>
                ),
              }))}
            />
            {verDiff && (
              <Card size="small" title={`差异 v${verDiff.from_seq} → v${verDiff.to_seq}（${verDiff.changed} 处）`}>
                {(verDiff.diffs || []).map((d) => (
                  <div key={d.field} style={{ marginBottom: 6 }}>
                    <Tag color={d.type === 'added' ? 'success' : d.type === 'removed' ? 'error' : 'warning'}>{d.type}</Tag>
                    <Typography.Text code>{d.field}</Typography.Text>
                    {d.type === 'changed' && (
                      <div style={{ marginLeft: 24, fontSize: 12, color: '#8c8c8c', wordBreak: 'break-all' }}>
                        <span style={{ color: '#d9404f' }}>{JSON.stringify(d.from)}</span>
                        {' → '}
                        <span style={{ color: '#3f9c3f' }}>{JSON.stringify(d.to)}</span>
                      </div>
                    )}
                  </div>
                ))}
              </Card>
            )}
          </Space>
        )}
      </Drawer>
    </Space>
  )
}

// helpers
function contentSummaryOf(row) {
  const cat = row.category
  if (cat === 'UI') return `步骤 ${(row.steps || []).length}`
  if (cat === 'API') return row.request_spec ? '1 请求' : '-'
  if (cat === 'PERFORMANCE') return '压测'
  const evalLike = ['HALLUCINATION', 'REDTEAM', 'RAG', 'ETHICS', 'MULTITURN', 'MULTI_TURN', 'EVAL', 'SECURITY'].includes(cat)
  if (evalLike) return '样本'
  return '-'
}

function defaultEnginesForCategory(cat) {
  const map = {
    API: ['API_TEST'],
    UI: ['UI_TEST'],
    PERFORMANCE: ['PERF_TEST'],
    HALLUCINATION: ['HALLUCINATION_TEST'],
    REDTEAM: ['REDTEAM_TEST'],
    RAG: ['RAG_TEST'],
    ETHICS: ['ETHICS_TEST'],
    DATAFLOW: ['DATAFLOW_TEST'],
    MULTITURN: ['MULTI_TURN_TEST'],
    MULTI_TURN: ['MULTI_TURN_TEST'],
    EVAL: ['EVAL_ENGINE'],
    CASE_GEN: ['CASE_GEN'],
    SELF_HEAL: ['SELF_HEAL'],
    DEFECT_PREDICT: ['DEFECT_PREDICT'],
    SECURITY: ['SECURITY_TEST'],
    FUNCTIONAL: ['API_TEST', 'UI_TEST'],
  }
  return map[cat] || ['UI_TEST', 'API_TEST']
}

function safeParse(text) {
  if (text == null || text === '') return {}
  if (typeof text === 'object') return text
  try { return JSON.parse(text) } catch { return {} }
}
function headersOf(headersObj) {
  if (!headersObj) return []
  if (Array.isArray(headersObj)) return headersObj
  return Object.keys(headersObj).map((k) => ({ key: k, value: headersObj[k] }))
}