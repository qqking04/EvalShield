/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useRef, useState, useMemo } from 'react'
import {
  Table, Button, Card, Space, Tag, Modal, Form, Input, Select, App, Popconfirm, Typography, Progress,
  Alert, Tooltip, Tabs, Steps, Checkbox,
} from 'antd'
import { PlusOutlined, ReloadOutlined, ClearOutlined, PlayCircleOutlined, StopOutlined, ClockCircleOutlined, DeleteOutlined, WarningOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import http from '../api/http'
import { fmtTime } from '../utils'
import fetchAll from '../utils/fetchAll'
import TaskWizardStep1 from '../components/tasks/TaskWizardStep1'
import TaskWizardStep2 from '../components/tasks/TaskWizardStep2'
import TaskWizardStep3 from '../components/tasks/TaskWizardStep3'
import { ENGINE_CATEGORY_MAP, getEngineParams, AI_EVAL_ENGINES, targetKeyOf } from '../components/tasks/engineParams'
import { ENGINE_NAME_MAP, TASK_STATUS_MAP, TASK_STATUS_COLOR } from '../constants/enums'
import { useEdition } from '../edition/EditionContext'

export default function Tasks() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [rows, setRows] = useState([])
  const [projects, setProjects] = useState([])
  const [listProjectIdFilter, setListProjectIdFilter] = useState(null) // 列表过滤用的 project_id
  // ES10-P-02：来自 URL 的项目版本过滤（版本列表“任务数”跳转进入）
  const [pvFilterId, setPvFilterId] = useState(() => {
    const v = Number(searchParams.get('project_version_id'))
    return Number.isFinite(v) && v > 0 ? v : null
  })
  const [pvVersionNo, setPvVersionNo] = useState(null) // 反查到的版本号（查不到只显示 id）
  const [engines, setEngines] = useState([])
  const [allCases, setAllCases] = useState([])
  const [scenarios, setScenarios] = useState([])
  const [envs, setEnvs] = useState([])  // P0-1：项目环境列表（来自 TestEnvironment 新表）
  const [modelConfigs, setModelConfigs] = useState([])
  const [evalSets, setEvalSets] = useState([])
  const [targets, setTargets] = useState([])
  const [budgetMap, setBudgetMap] = useState({}) // engine -> {calls, estimated_cost} | 'loading' | null
  const [formTick, setFormTick] = useState(0) // 表单值变更计数：驱动预算条/演示提示随 target_code 重渲染
  // BUG-02 v2.0 P3：演示模式确认弹窗（受控 Modal + Checkbox 勾选后才能确认）
  const [demoConfirm, setDemoConfirm] = useState(null) // { engines: [...], body: {...} } | null
  const [demoAck, setDemoAck] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [loading, setLoading] = useState(false)
  // 列表筛选：keyword（任务名称模糊）+ statusFilter（后端 TaskStatus 枚举）
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState(null)
  const [statusFilter, setStatusFilter] = useState(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null) // 编辑的任务对象
  const [form] = Form.useForm()
  const [triggerMode, setTriggerMode] = useState('MANUAL')
  const [currentStep, setCurrentStep] = useState(0)
  const { message } = App.useApp()
  const pollTimer = useRef(null)
  // 3 秒轮询沿用最新筛选条件：用 ref 读取，避免 setInterval 闭包固化旧值
  const filterRef = useRef({ keyword: null, status: null })

  // 监听表单变化（用受控 state 而非 useWatch，规避字段因条件渲染卸载导致 useWatch 失效，
  // 避免第三步"请先返回上一步选择引擎"的误报）
  const [selectedProjectId, setSelectedProjectId] = useState()
  const [selectedEngines, setSelectedEngines] = useState([])

  // 根据选中的引擎，算出需要哪些 case category（合并去重）
  const requiredCategories = useMemo(() => {
    const cats = new Set()
    for (const eng of (selectedEngines || [])) {
      for (const c of (ENGINE_CATEGORY_MAP[eng] || [])) cats.add(c)
    }
    return [...cats]
  }, [selectedEngines])

  // 派生：按引擎 category 过滤后的 cases 列表
  const filteredCases = useMemo(() => {
    if (requiredCategories.length === 0) return allCases
    return allCases.filter((c) => requiredCategories.includes(c.category))
  }, [allCases, requiredCategories])

  // 是否有任意引擎需要任务级 case_ids
  const needsTaskCaseIds = useMemo(
    () => (selectedEngines || []).some((eng) => ENGINE_CATEGORY_MAP[eng]),
    [selectedEngines],
  )

  // 辅助：根据项目 ID 拿到完整项目对象（含 environments）
  const findProject = (pid) => projects.find((p) => p.id === pid)

  // ---------- 列表加载 ----------
  const load = async (p = page, ps = pageSize, pid = listProjectIdFilter, pvId = pvFilterId, kw = keyword, st = statusFilter) => {
    setLoading(true)
    try {
      const params = { page: p, page_size: ps }
      if (pid) params.project_id = pid
      if (pvId) params.project_version_id = pvId
      if (kw) params.keyword = kw
      if (st) params.status = st
      const data = await http.get('/tasks', { params })
      setRows(data.items || [])
      setTotal(data.total || 0)
      const hasRunning = (data.items || []).some((r) => r.status === 'RUNNING' || r.status === 'PENDING')
      if (hasRunning) startPolling()
      else stopPolling()
    } catch (e) {
      console.warn('[Tasks] 任务列表加载失败', e?.message || e)
      message.error('任务列表加载失败，请检查后端服务')
    } finally {
      setLoading(false)
    }
  }

  const startPolling = () => {
    if (pollTimer.current) return
    pollTimer.current = setInterval(
      () => load(page, pageSize, listProjectIdFilter, pvFilterId, filterRef.current.keyword, filterRef.current.status),
      3000,
    )
  }
  const stopPolling = () => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current)
      pollTimer.current = null
    }
  }

  // ---------- 初始加载 ----------
  useEffect(() => {
    const initialPid = searchParams.get('project_id')
    if (initialPid) {
      const pidNum = Number(initialPid)
      setListProjectIdFilter(pidNum)
      form.setFieldsValue({ project_id: pidNum })
    }
    const initialPv = (() => {
      const v = Number(searchParams.get('project_version_id'))
      return Number.isFinite(v) && v > 0 ? v : null
    })()

    load(1, pageSize, initialPid ? Number(initialPid) : null, initialPv)
    http.get('/projects', { params: { page_size: 200 } }).then((d) => setProjects(d.items || [])).catch((e) => console.warn(`[Tasks]`, e?.message || e))
    http.get('/engine-options').then((d) => setEngines(d?.items || d || [])).catch((e) => console.warn('[Tasks]', e?.message || e))
    // 加载辅助数据源
    http.get('/model-configs').then((d) => {
      const list = Array.isArray(d) ? d : (d.items || [])
      setModelConfigs(list.filter((m) => m.status === 'ACTIVE'))
    }).catch((e) => console.warn(`[Tasks]`, e?.message || e))
    http.get('/eval-sets').then((d) => {
      setEvalSets(Array.isArray(d) ? d : (d.items || []))
    }).catch((e) => console.warn(`[Tasks]`, e?.message || e))
    // §6.4：被测系统下拉（仅 ACTIVE）
    http.get('/targets', { params: { status: 'ACTIVE', page_size: 200 } }).then((d) => {
      const payload = d?.data || d
      setTargets(payload.items || (Array.isArray(payload) ? payload : []))
    }).catch((e) => console.warn('[Tasks] targets 加载失败', e?.message || e))

    return stopPolling
  }, [])

  // 加载用例 / 场景（按项目拉全量，前端再按引擎 category 过滤）
  const loadProjectResources = async (projectId) => {
    if (!projectId) {
      setAllCases([]); setScenarios([]); setEnvs([]); return
    }
    try {
      // FE-17：cases 用循环翻页避免 >500 截断；scenarios 保持单页（通常不会超）
      // P0-1：同时拉取项目环境列表（来自 TestEnvironment 新表）
      const [caseList, scenarioData, envList] = await Promise.all([
        fetchAll(http, '/cases', { project_id: projectId }).catch((e) => { console.warn('[Tasks] cases 加载失败', e?.message); return [] }),
        http.get('/scenarios', { params: { project_id: projectId } }).catch((e) => { console.warn('[Tasks] scenarios 加载失败', e?.message); return null }),
        http.get(`/projects/${projectId}/environments`).catch((e) => { console.warn('[Tasks] environments 加载失败', e?.message); return [] }),
      ])
      setAllCases(caseList)
      setScenarios(scenarioData ? (scenarioData.items || scenarioData || []) : [])
      setEnvs(Array.isArray(envList) ? envList : (envList?.items || []))
    } catch (e) {
      console.warn('[Tasks] loadProjectResources 异常', e?.message || e)
      setAllCases([]); setScenarios([])
    }
  }

  // ---------- 项目变化：加载用例/场景/环境（仅依赖 selectedProjectId，避免 setEnvs 新数组触发无限循环） ----------
  useEffect(() => {
    loadProjectResources(selectedProjectId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProjectId])

  // ---------- 环境列表就绪后：自动带默认 base_url + env_id（统一 TestEnvironment 新表） ----------
  useEffect(() => {
    if (editing) return
    // 统一：从 TestEnvironment 新表找 default（project.environments JSON 已废弃）
    const defaultEnv = (envs.find((e) => e.is_default) || envs[0]) || null

    if (defaultEnv) {
      const patch = {
        'config__UI_TEST__base_url': defaultEnv.base_url,
        'config__API_TEST__base_url': defaultEnv.base_url,
        'config__DATAFLOW_TEST__base_url': defaultEnv.base_url,
      }
      // env_id 字段：后端新表返回 env_id 字符串（= TestEnvironment.id）
      if (defaultEnv.env_id) patch.env_id = parseInt(defaultEnv.env_id, 10)
      form.setFieldsValue(patch)
    } else {
      form.setFieldsValue({ env_id: null })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [envs])

  // ES10-P-02：从已加载任务行反推项目，再拉该项目版本列表反查 version_no（查不到只显示 id）
  useEffect(() => {
    if (!pvFilterId || pvVersionNo != null || rows.length === 0) return
    const pid = rows.find((r) => r.project_id)?.project_id
    if (!pid) return
    http.get(`/projects/${pid}/versions`, { params: { page: 1, size: 100 } })
      .then((d) => {
        const wrapper = d?.data ?? d
        const v = (wrapper?.items || []).find((x) => x.id === pvFilterId)
        if (v) setPvVersionNo(v.version_no)
      })
      .catch((e) => console.warn('[Tasks] versions 反查失败', e?.message || e))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pvFilterId, rows])

  // ES10-P-02：移除版本过滤 Tag —— 清查询参数并刷新列表
  const clearPvFilter = () => {
    setPvFilterId(null)
    setPvVersionNo(null)
    const np = new URLSearchParams(searchParams)
    np.delete('project_version_id')
    setSearchParams(np, { replace: true })
    load(1, pageSize, listProjectIdFilter, null)
  }

  // ---------- 筛选：keyword / status（同步 state + filterRef，保证轮询不丢条件） ----------
  const applyTaskFilters = (next) => {
    const merged = { keyword: next.keyword ?? null, status: next.status ?? null }
    filterRef.current = merged
    setKeyword(merged.keyword)
    setStatusFilter(merged.status)
    setPage(1)
    load(1, pageSize, listProjectIdFilter, pvFilterId, merged.keyword, merged.status)
  }
  const handleSearchKeyword = () => {
    applyTaskFilters({ keyword: keywordInput.trim() || null, status: statusFilter })
  }
  const handleResetFilters = () => {
    setKeywordInput('')
    applyTaskFilters({ keyword: null, status: null })
  }

  // ---------- 新建 ----------
  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setTriggerMode('MANUAL')
    setCurrentStep(0)
    const initialPid = searchParams.get('project_id')
    if (initialPid) form.setFieldsValue({ project_id: Number(initialPid) })
    setModalOpen(true)
  }

  // ---------- 编辑 ----------
  const openEdit = async (row) => {
    try {
      const task = await http.get(`/tasks/${row.id}`)
      setEditing(task)
      setCurrentStep(0) // 编辑也从 Step 0 开始，和创建流程对齐

      // 先让 useWatch 感知 project_id 变化 → 触发 loadProjectResources
      if (task.project_id) {
        form.setFieldsValue({ project_id: task.project_id })
        loadProjectResources(task.project_id)
      }

      // 先选项目，等资源加载完再 setFieldsValue
      // ES8 M5：门禁规则回填（后端存 JSON 字符串，容错非法 JSON）
      let gateRules = []
      if (task.gate_rules) {
        try { gateRules = JSON.parse(task.gate_rules) } catch { gateRules = [] }
      }
      form.setFieldsValue({
        name: task.name,
        project_id: task.project_id,
        engines: task.engines,
        description: task.description,
        trigger_mode: task.trigger_mode || 'MANUAL',
        schedule_cron: task.schedule_cron,
        gate_rules: Array.isArray(gateRules) ? gateRules : [],
      })
      setTriggerMode(task.trigger_mode || 'MANUAL')
      // 关键修复（BUG-43）：setFieldsValue 不会触发 Form.onValuesChange，
      // 若不显式同步受控 state，第二步会误判 selectedEnginesArr 为空 → 错误提示"请先返回上一步选择引擎"
      if (task.project_id) setSelectedProjectId(task.project_id)
      setSelectedEngines(task.engines || [])

      // 回填 config（后端只存扁平 key，前端 submit 也只写扁平 key）
      const cfg = task.config || {}
      const patch = {}
      for (const engine of (task.engines || [])) {
        const params = getEngineParams(engine, engines)
        for (const p of params) {
          const v = cfg[p.key]
          if (v !== undefined && v !== null && v !== '') {
            patch[`config__${engine}__${p.key}`] = v
          }
        }
      }
      // 任务级 case_ids 回填（扁平 key，后端只存扁平）
      const taskCaseIds = cfg.case_ids
      if (taskCaseIds && taskCaseIds.length > 0) {
        patch.case_ids = taskCaseIds
      }
      // v2.0：被测系统版本指纹手填项回填
      for (const k of ['sut_version', 'sut_branch', 'sut_commit']) {
        if (cfg[k]) patch[k] = cfg[k]
      }
      form.setFieldsValue(patch)
      setModalOpen(true)
    } catch {
      message.error('获取任务详情失败')
    }
  }

  // ---------- submit ----------
  const submit = async () => {
    let values
    try {
      // v2.0修复：向导分步渲染会卸载前序步骤字段，validateFields() 仅返回"当前挂载"字段，
      // 导致 Step3 提交时拿不到 name/engines/config__*。校验可见字段 + 合并完整 store。
      const mounted = await form.validateFields()
      values = { ...form.getFieldsValue(true), ...mounted }
    } catch (err) {
      const fields = (err?.errorFields || []).map((f) => f.name?.join('.')).filter(Boolean).join('、')
      message.warning('请先补全必填项' + (fields ? `：${fields}` : '，再提交'))
      return
    }
    // 防御：杜绝"参数校验失败"式后端 422 —— 确保 name / engines / project_id 必带
    const name = (values.name || '').trim()
    const engines = Array.isArray(values.engines) ? values.engines.filter(Boolean) : []
    const projectId = Number(values.project_id)
    if (!name) { message.warning('任务名称不能为空，请返回第一步填写'); return }
    if (engines.length === 0) { message.warning('请至少选择一个测试引擎'); return }
    if (!projectId || projectId <= 0) { message.warning('请选择所属项目'); return }
    const base = {
      name,
      project_id: projectId,
      engines,
      description: values.description,
      trigger_mode: values.trigger_mode || 'MANUAL',
      schedule_cron: values.schedule_cron,
    }
    // 构造 config：扁平 key（后端 16 个引擎统一读 ctx.config.get('case_ids') 扁平 key）
    // 共享 case_ids + 最后一个引擎的专属参数组合成扁平 dict
    const config = {}
    // 1) 任务级共享 case_ids（所有 ENGINE_CATEGORY_MAP 引擎共用）
    if (Array.isArray(values.case_ids) && values.case_ids.length > 0) {
      config.case_ids = values.case_ids.map(Number).filter((n) => !Number.isNaN(n))
    }
    // 2) 从每个引擎收集专属参数（同一 key 后写覆盖前写——合理：多引擎同一被测系统 base_url 通常相同）
    // W1：threshold 为引擎专属参数，收敛进 config.engines[engine]（多引擎各有阈值，压平必互相覆盖）；
    // 其余参数（category/max_samples 等）按当前向导一次只填一份专属值，维持顶层扁平（存量任务兼容）
    const ENGINE_SEGMENT_KEYS = new Set(['threshold'])
    for (const engine of engines) {
      const params = getEngineParams(engine, engines)
      for (const p of params) {
        const formKey = `config__${engine}__${p.key}`
        let v = values[formKey]
        if (v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && v.length === 0)) {
          if (p.type === 'auth' && typeof v === 'string') {
            try { v = JSON.parse(v) } catch { /* 原样传 */ }
          }
          if (ENGINE_SEGMENT_KEYS.has(p.key)) {
            config.engines = { ...(config.engines || {}), [engine]: { ...(config.engines?.[engine] || {}), [p.key]: v } }
          } else {
            config[p.key] = v
          }
        }
      }
    }
    // P0-1：环境 env_id 直接存 task.config 顶层（后端 task_runner._resolve_env_config 从 cfg.env_id 读）
    if (values.env_id) config.env_id = Number(values.env_id)
    // v2.0：被测系统版本指纹手填项，写入 config 顶层供 _collect_environment 读取
    for (const k of ['sut_version', 'sut_branch', 'sut_commit']) {
      const v = values[k]
      if (v !== undefined && v !== null && String(v).trim() !== '') config[k] = String(v).trim()
    }

    const body = { ...base, config }
    // ES8 M5：门禁规则序列化（向导 Form.List 数组 → JSON 字符串；空数组=清空门禁）
    body.gate_rules = JSON.stringify(
      Array.isArray(values.gate_rules)
        ? values.gate_rules.filter((r) => r && r.metric && r.op && r.threshold !== undefined && r.threshold !== null)
        : [],
    )

    // v2.0 P5：多轮引擎必须绑定真实被测系统（兜底拦截；前置引导见 Step2 Alert + 提交按钮禁用）
    if (engines.includes('MULTI_TURN_TEST') && !values[targetKeyOf('MULTI_TURN_TEST', engines)]) {
      message.error('多轮一致性引擎必须选择被测系统，否则测试的是平台内置模型')
      return
    }

    // v2.0 P3：AI 引擎未绑定被测系统 → 演示模式二次确认（BUG-02：受控 Modal + Checkbox）
    const demoEngines = engines.filter(
      (e) => AI_EVAL_ENGINES.includes(e) && !values[targetKeyOf(e, engines)],
    )
    if (!editing && demoEngines.length > 0) {
      setDemoAck(false)
      setDemoConfirm({ engines: demoEngines, body })
      return
    }

    await doSubmit(body)
  }

  // BUG-02：演示模式确认后真正提交
  const doSubmit = async (body) => {
    try {
      if (editing) {
        await http.put(`/tasks/${editing.id}`, body)
        message.success('任务更新成功')
      } else {
        await http.post('/tasks', body)
        message.success('任务创建成功，可在列表点击"执行"开始测试')
      }
      setDemoConfirm(null)
      setModalOpen(false)
      load(editing ? page : 1)
    } catch {
      /* 拦截器已提示 */
    }
  }

  // ---------- 执行 / 取消 / 删除 ----------
  const runTask = async (id) => {
    try {
      const data = await http.post(`/tasks/${id}/run`, {})
      message.success(data && data.message ? data.message : '任务已提交，后台异步执行中')
      load(page)
    } catch { /* 拦截器已提示 */ }
  }
  const cancelTask = async (id) => {
    await http.post(`/tasks/${id}/cancel`)
    message.success('任务已取消')
    load(page)
  }
  const removeTask = async (id) => {
    await http.delete(`/tasks/${id}`)
    message.success('任务已删除')
    load(page)
  }
  // D-DEL-FE：批量删除任务
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const batchRemove = async () => {
    const ids = selectedRowKeys
    if (!ids.length) return
    try {
      const r = await http.post('/tasks/batch-delete', { ids })
      message.success(`已删除 ${r?.deleted ?? ids.length} 条任务`)
      setSelectedRowKeys([]); load(page)
    } catch (e) { console.warn(e) }
  }

  // §6.4 执行预算：POST /eval-runs/estimate → {calls, estimated_cost}
  const estimateEngineBudget = async (engine) => {
    if (!AI_EVAL_ENGINES.includes(engine)) return
    const evalSetId = form.getFieldValue(`config__${engine}__eval_set_id`)
    const judgeModel = form.getFieldValue(`config__${engine}__judge_model`) || form.getFieldValue(`config__${engine}__model_gateway`)
    setBudgetMap((m) => ({ ...m, [engine]: 'loading' }))
    try {
      const r = await http.post('/eval-runs/estimate', {
        engine_code: engine,
        eval_set_id: evalSetId || null,
        judge_model: judgeModel || undefined,
      })
      setBudgetMap((m) => ({ ...m, [engine]: r || null }))
    } catch (e) {
      console.warn('[Tasks] 预算估算失败', e?.message || e)
      setBudgetMap((m) => ({ ...m, [engine]: null }))
    }
  }

  // ---------- 表格列 ----------
  const columns = [
    { title: '任务编号', dataIndex: 'task_no', width: 200, render: (v, r) => <a onClick={() => navigate(`/tasks/${r.id}`)}>{v}</a> },
    { title: '任务名称', dataIndex: 'name', ellipsis: true },
    { title: '项目', dataIndex: 'project_code', width: 150, render: (v) => v || '-' },
    {
      title: '引擎',
      dataIndex: 'engines',
      width: 200,
      render: (v) => (v || []).map((e) => <Tag key={e}>{ENGINE_NAME_MAP[e] || e}</Tag>),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v, r) => (
        <Tooltip title={v === 'COMPLETED_WITH_RISK' ? (r.conclusion || '') : (r.error_msg || '')}>
          {/* BUG-04：未达阈值标签补警告图标 */}
          <Tag color={TASK_STATUS_COLOR[v]} icon={v === 'COMPLETED_WITH_RISK' ? <WarningOutlined /> : undefined}>{TASK_STATUS_MAP[v] || v}</Tag>
        </Tooltip>
      ),
    },
    {
      title: '结论',
      dataIndex: 'conclusion',
      width: 200,
      ellipsis: true,
      render: (v, r) => {
        if (r.status === 'COMPLETED_WITH_RISK') return <Typography.Text type="warning">{v || '质量未达标'}</Typography.Text>
        if (r.status === 'FAILED') return <Typography.Text type="danger">{r.error_msg || '执行异常'}</Typography.Text>
        return <Typography.Text type="secondary">-</Typography.Text>
      },
    },
    { title: '进度', dataIndex: 'progress', width: 120, render: (v, r) => (r.status === 'RUNNING' ? <Progress percent={v || 0} size="small" /> : v === 100 ? '已完成' : '-') },
    { title: '执行人', dataIndex: 'executor', width: 110, render: (v, r) => v || r.created_by_name || '-' },
    { title: '触发方式', dataIndex: 'trigger_mode', width: 100, render: (v) => <Tag color={v === 'SCHEDULED' ? 'purple' : 'default'}>{v === 'SCHEDULED' ? '定时' : '手动'}</Tag> },
    { title: '下次执行', dataIndex: 'next_run_at', width: 160, render: (v, r) => (r.trigger_mode === 'SCHEDULED' && r.status !== 'CANCELLED' ? <Space size={4}><ClockCircleOutlined style={{ color: '#888' }} />{v ? fmtTime(v) : '-'}</Space> : '-') },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v) => fmtTime(v) },
    {
      title: '操作',
      width: 340,
      fixed: 'right',
      render: (_, row) => {
        const isRunning = row.status === 'RUNNING'
        return (
          <Space wrap size={4}>
            <Button type="link" size="small" disabled={isRunning} icon={<PlayCircleOutlined />} onClick={() => runTask(row.id)}>
              执行
            </Button>
            {row.status === 'RUNNING' && (
              <Popconfirm title="确认取消该任务？" onConfirm={() => cancelTask(row.id)}>
                <Button type="link" size="small" danger icon={<StopOutlined />}>取消</Button>
              </Popconfirm>
            )}
            <Button type="link" size="small" onClick={() => navigate(`/tasks/${row.id}`)}>详情</Button>
            <Tooltip title={isRunning ? '运行中任务不可编辑' : ''}>
              <span style={{ display: 'inline-block' }}>
                <Button
                  type="link"
                  size="small"
                  disabled={isRunning}
                  onClick={() => openEdit(row)}
                >
                  编辑
                </Button>
              </span>
            </Tooltip>
            <Popconfirm
              title="确认删除该任务？"
              description="删除后关联报告将保留在报告中心，不可恢复。"
              okButtonProps={{ danger: true }}
              onConfirm={() => removeTask(row.id)}
            >
              <Button type="link" size="small" danger>删除</Button>
            </Popconfirm>
          </Space>
        )
      },
    },
  ]

  // ---------- 渲染 ----------
  const selectedEnginesArr = selectedEngines || []
  // BUG-03 v2.0 P5：MULTI_TURN_TEST 未选被测系统时禁用提交按钮（formTick 变更触发重渲染取最新值）
  void formTick
  const multiTurnMissingTarget =
    selectedEnginesArr.includes('MULTI_TURN_TEST') &&
    !form.getFieldValue(targetKeyOf('MULTI_TURN_TEST', engines))
  // F3：enabled_engines 驱动引擎白名单。清单未就绪（未加载/拉取失败/空数组）前不裁剪，
  // 拿到商业口径响应后再裁剪，社区部署下商业引擎不出现在下拉。
  const { enabled_engines: enabledEngines } = useEdition()
  const engineOptions = (engines || [])
    .filter((e) => !(enabledEngines && enabledEngines.length > 0) || enabledEngines.includes(e.engine_code))
    .map((e) => ({ value: e.engine_code, label: `${e.engine_name} (${e.engine_code})` }))

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <Space>
          <Typography.Title level={4} style={{ margin: 0 }}>任务中心</Typography.Title>
          {/* 项目筛选下拉 */}
          <Select
            allowClear
            showSearch
            placeholder="全部项目"
            value={listProjectIdFilter}
            style={{ minWidth: 260 }}
            options={projects.map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))}
            filterOption={(input, opt) => String(opt.label || '').toLowerCase().includes(String(input).toLowerCase())}
            onChange={(val) => {
              setListProjectIdFilter(val || null)
              setPage(1)
              // 同步 URL
              const np = new URLSearchParams(searchParams)
              if (val) np.set('project_id', val)
              else np.delete('project_id')
              setSearchParams(np, { replace: true })
              load(1, pageSize, val || null)
            }}
          />
          {pvFilterId && (
            <Tag
              closable
              color="cyan"
              onClose={(e) => { e.preventDefault(); clearPvFilter() }}
            >
              版本：{pvVersionNo ?? `#${pvFilterId}`}
            </Tag>
          )}
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
          <Popconfirm title={`确认批量删除选中的 ${selectedRowKeys.length} 条任务？`} disabled={!selectedRowKeys.length} onConfirm={batchRemove}>
            <Button danger icon={<DeleteOutlined />} disabled={!selectedRowKeys.length}>批量删除{selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length})` : ''}</Button>
          </Popconfirm>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建任务</Button>
        </Space>
      </div>
      <Card>
        <Space style={{ marginBottom: 16 }} wrap>
          <Input.Search
            placeholder="搜索任务名称"
            allowClear
            style={{ width: 220 }}
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            onSearch={handleSearchKeyword}
          />
          <Select
            allowClear
            placeholder="全部状态"
            style={{ width: 140 }}
            value={statusFilter}
            onChange={(val) => applyTaskFilters({ keyword, status: val || null })}
            options={Object.entries(TASK_STATUS_MAP).map(([value, label]) => ({ value, label }))}
          />
          <Button icon={<ClearOutlined />} onClick={handleResetFilters}>重置</Button>
        </Space>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={rows}
          rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
          scroll={{ x: 'max-content' }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true, showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => {
              setPage(p); setPageSize(ps); load(p, ps)
            },
          }}
        />
      </Card>

      {/* 新建/编辑任务 Modal — 三步向导 */}
      <Modal
        title={
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <span>{editing ? '编辑测试任务' : '新建测试任务'}</span>
            <Steps size="small" current={currentStep} items={[
              { title: '选引擎', description: '项目 + 引擎' },
              { title: '配参数', description: '引擎参数' },
              { title: '关联用例', description: '提交' },
            ]} />
          </Space>
        }
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        destroyOnHidden
        width={900}
        footer={
          <Space>
            <Button onClick={() => setModalOpen(false)}>取消</Button>
            {currentStep > 0 && <Button onClick={() => setCurrentStep((s) => s - 1)}>上一步</Button>}
            {currentStep < 2 && <Button type="primary" onClick={async () => {
              try {
                if (currentStep === 0) {
                  await form.validateFields(['name', 'project_id', 'engines'])
                } else if (currentStep === 1) {
                  const engCodes = selectedEnginesArr
                  const requiredKeys = []
                  for (const eng of engCodes) {
                    const params = getEngineParams(eng, engines)
                    for (const p of params) {
                      const isTargetField = p.key === 'target_code' || p.key === 'target' || p.type === 'target'
                      // v2.0 P5：多轮引擎被测系统强制必填（与 renderEngineParams 的 rules 保持一致）
                      if (p.required || (eng === 'MULTI_TURN_TEST' && isTargetField)) {
                        requiredKeys.push(`config__${eng}__${p.key}`)
                      }
                    }
                  }
                  if (requiredKeys.length > 0) {
                    await form.validateFields(requiredKeys)
                  }
                }
                if (currentStep === 0) {
                  // 下一步进入 Step 2（配参数）：对 AI 引擎触发预算估算
                  selectedEnginesArr.filter((e) => AI_EVAL_ENGINES.includes(e)).forEach((e) => estimateEngineBudget(e))
                }
                setCurrentStep((s) => s + 1)
              } catch (err) {
                message.warning('请补全必填参数：' + (err?.errorFields?.map(f => f.label || f.name?.join('.'))?.join(', ') || '未知字段'))
              }
            }}>下一步</Button>}
            {currentStep === 2 && (
              <Tooltip title={multiTurnMissingTarget ? '多轮一致性引擎必须选择被测系统后才能提交' : ''}>
                <Button type="primary" disabled={multiTurnMissingTarget} onClick={submit}>{editing ? '保存修改' : '提交任务'}</Button>
              </Tooltip>
            )}
          </Space>
        }
      >
        <Form
          form={form}
          layout="vertical"
          onValuesChange={(changed) => {
            if ('project_id' in changed) setSelectedProjectId(changed.project_id)
            if ('engines' in changed) setSelectedEngines(changed.engines || [])
            setFormTick((t) => t + 1)
          }}
        >
          {currentStep === 0 && (
            <TaskWizardStep1
              form={form}
              editing={editing}
              projects={projects}
              envs={envs}
              engineOptions={engineOptions}
              engines={engines}
              message={message}
            />
          )}
          {currentStep === 1 && (
            <TaskWizardStep2
              form={form}
              navigate={navigate}
              engines={engines}
              scenarios={scenarios}
              modelConfigs={modelConfigs}
              evalSets={evalSets}
              targets={targets}
              selectedProjectId={selectedProjectId}
              filteredCases={filteredCases}
              budgetMap={budgetMap}
              selectedEngines={selectedEngines}
              estimateEngineBudget={estimateEngineBudget}
            />
          )}
          {currentStep === 2 && (
            <TaskWizardStep3
              editing={editing}
              selectedEngines={selectedEngines}
              selectedProjectId={selectedProjectId}
              requiredCategories={requiredCategories}
              filteredCases={filteredCases}
              needsTaskCaseIds={needsTaskCaseIds}
              triggerMode={triggerMode}
              setTriggerMode={setTriggerMode}
            />
          )}
        </Form>
      </Modal>

      {/* BUG-02 v2.0 P3：演示模式二次确认（受控 Modal，勾选后才可确认） */}
      <Modal
        title="演示模式确认"
        open={!!demoConfirm}
        width={520}
        okText="确认创建演示任务"
        cancelText="返回选择被测系统"
        okButtonProps={{ disabled: !demoAck }}
        onOk={async () => { await doSubmit(demoConfirm.body) }}
        onCancel={() => setDemoConfirm(null)}
        destroyOnHidden
      >
        <Alert
          type="warning"
          showIcon
          message="演示模式结果不可作为交付依据"
          description={`${(demoConfirm?.engines || []).map((e) => ENGINE_NAME_MAP[e] || e).join('、')} 未选择被测系统，将使用平台内置模型自问自答。报告将标注"演示模式"横幅，PDF 导出带 DEMO 水印，不可用于客户验收。`}
        />
        <Checkbox
          checked={demoAck}
          onChange={(e) => setDemoAck(e.target.checked)}
          style={{ marginTop: 16 }}
        >
          我已了解，继续创建演示任务
        </Checkbox>
      </Modal>
    </Space>
  )
}
