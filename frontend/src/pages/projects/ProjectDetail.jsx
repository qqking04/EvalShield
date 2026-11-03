/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { lazy, useEffect, useState } from 'react'
import { Card, Tabs, Table, Row, Col, Statistic, Button, Input, Select, Drawer, Space, App, Tooltip, Modal, Radio, Empty, Tag, Spin, Result, Alert, Popconfirm, Typography } from 'antd'
import { useParams, useNavigate, useSearchParams, Link } from 'react-router-dom'
import http from '../../api/http'
import Versions from './Versions'
import ProjectQualityView from './ProjectQualityView'
import UatReportList from '../uat/UatReportList'
import { useIsCommunity } from '../../edition/EditionContext'
import UpgradeEmpty from '../../components/UpgradeEmpty'
import CommercialGate from '../../components/CommercialGate'
import PageSuspense from '../../components/common/PageSuspense'

// F1 版本隔离：源代码审计属商业模块（OSS 构建整目录剔除 + 说明符改写），项目详情内嵌 Tab 按社区版门控
const SrcAuditPanel = lazy(() => import('../CommercialPlaceholder'))

// KV 编辑器（表形式两列 key/value，敏感值隐藏 ******）
function KvEditor({ value = [], onChange, sensitiveKeys = [] }) {
  const rows = [...value, { key: '', value: '' }]

  const handleChange = (i, field, v) => {
    const next = [...value]
    if (i >= value.length) {
      next.push({ key: '', value: '' })
    }
    next[i] = { ...next[i], [field]: v }
    const filtered = next.filter((r, idx) => idx === next.length - 1 ? (r.key || r.value) : true)
    onChange(filtered)
  }

  return (
    <div className="kv-editor">
      <table style={{ borderCollapse: 'separate', borderSpacing: '4px' }}>
        <thead>
          <tr style={{ color: '#8ba3b5', fontSize: 12 }}>
            <th style={{ textAlign: 'left', padding: '0 4px' }}>Key</th>
            <th style={{ textAlign: 'left', padding: '0 4px' }}>Value</th>
            <th style={{ width: 32 }}></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const isLast = i === rows.length - 1
            const isSensitive = sensitiveKeys.includes(r.key)
            const displayVal = isSensitive && !isLast ? '******' : r.value
            return (
              <tr key={i}>
                <td><Input placeholder="Key" value={r.key} onChange={(e) => handleChange(i, 'key', e.target.value)} /></td>
                <td>
                  <Input
                    placeholder="Value"
                    value={displayVal}
                    onChange={(e) => {
                      if (isSensitive && e.target.value === '******') return
                      handleChange(i, 'value', e.target.value)
                    }}
                  />
                </td>
                <td>
                  {!isLast && (
                    <Button
                      type="text"
                      danger
                      size="small"
                      onClick={() => {
                        const next = value.filter((_, idx) => idx !== i)
                        onChange(next)
                      }}
                    >
                      ×
                    </Button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div style={{ color: '#869BAA', fontSize: 12, marginTop: 8 }}>
        · 值为 ****** 表示已有敏感值，编辑处留空则保持不变 ·
      </div>
    </div>
  )
}

function CountUp({ to, duration = 800, suffix = '' }) {
  const [val, setVal] = useState(0)
  useEffect(() => {
    let start = null
    let raf
    const tick = (t) => {
      if (!start) start = t
      const p = Math.min(1, (t - start) / duration)
      setVal(Math.round(to * p))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [to, duration])
  return <span className="mono">{val}{suffix}</span>
}

export default function ProjectDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { message } = App.useApp()
  const isCommunity = useIsCommunity()
  const [overview, setOverview] = useState(null)
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  // 深链：?suite=<id> 由套件执行后生成，初始切到「测试套件」Tab 并消费该参数
  const [tab, setTab] = useState(() => (searchParams.get('suite') ? 'suites' : 'overview'))

  useEffect(() => {
    if (searchParams.has('suite')) {
      const next = new URLSearchParams(searchParams)
      next.delete('suite')
      setSearchParams(next, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 各 Tab 的数据 state（概览"最近 5" 用 tasks/reports 前 5 条）
  const [tasks, setTasks] = useState([])
  const [tasksLoading, setTasksLoading] = useState(false)
  const [tasksPage, setTasksPage] = useState(1)
  const [tasksTotal, setTasksTotal] = useState(0)

  const [reports, setReports] = useState([])
  const [reportsLoading, setReportsLoading] = useState(false)

  const [members, setMembers] = useState([])
  const [membersLoading, setMembersLoading] = useState(false)

  const [suites, setSuites] = useState([])
  const [suitesLoading, setSuitesLoading] = useState(false)

  const [envs, setEnvs] = useState([])
  const [envDrawerOpen, setEnvDrawerOpen] = useState(false)
  const [envEditing, setEnvEditing] = useState(null)
  const [envSaving, setEnvSaving] = useState(false)

  const loadOverview = async () => {
    setLoading(true)
    try {
      const data = await http.get(`/projects/${id}/overview`)
      setOverview(data)
    } catch {
      setOverview({})
    } finally {
      setLoading(false)
    }
  }

  const loadTasks = async (p = 1) => {
    setTasksLoading(true)
    try {
      const d = await http.get('/tasks', { params: { project_id: id, page: p, page_size: 10 } })
      setTasks(d?.items || [])
      setTasksTotal(d?.total || 0)
      setTasksPage(p)
    } catch {
      setTasks([]); setTasksTotal(0)
    } finally { setTasksLoading(false) }
  }

  const loadReports = async () => {
    setReportsLoading(true)
    try {
      const d = await http.get('/reports', { params: { project_id: id, page: 1, page_size: 10 } })
      setReports(d?.items || [])
    } catch { setReports([]) }
    finally { setReportsLoading(false) }
  }

  const loadMembers = async () => {
    setMembersLoading(true)
    try {
      const d = await http.get(`/projects/${id}/members`)
      setMembers(Array.isArray(d) ? d : (d?.items || []))
    } catch { setMembers([]) }
    finally { setMembersLoading(false) }
  }

  const loadSuites = async () => {
    setSuitesLoading(true)
    try {
      const d = await http.get(`/projects/${id}/suites`)
      setSuites(Array.isArray(d) ? d : (d?.items || []))
    } catch { setSuites([]) }
    finally { setSuitesLoading(false) }
  }

  useEffect(() => {
    loadOverview()
    // 项目基本信息（name/description/code 不在 overview 接口里，必须单独拉）
    http.get(`/projects/${id}`).then((d) => setProject(d)).catch((e) => { setProject(null); console.warn('[ProjectDetail] project load failed', e?.message || e) })
    // 概览 Tab 的"最近 5"只拉前 5 条
    http.get('/tasks', { params: { project_id: id, page_size: 5 } })
      .then((d) => setTasks(d?.items || []))
      .catch((e) => { setTasks([]); console.warn('[ProjectDetail] tasks load failed', e?.message || e) })
    http.get('/reports', { params: { project_id: id, page_size: 5 } })
      .then((d) => setReports(d?.items || []))
      .catch((e) => { setReports([]); console.warn('[ProjectDetail] reports load failed', e?.message || e) })
    http.get(`/projects/${id}/environments`)
      .then((d) => setEnvs(d?.items || d || []))
      .catch((e) => { setEnvs([]); console.warn('[ProjectDetail] environments load failed', e?.message || e) })
  }, [id])

  // Tab 切换时按需加载（避免同时拉 6 个接口）
  useEffect(() => {
    if (tab === 'tasks' && tasks.length === 0) loadTasks(1)
    if (tab === 'reports' && reports.length === 0) loadReports()
    if (tab === 'members' && members.length === 0) loadMembers()
    if (tab === 'suites' && suites.length === 0) loadSuites()
  }, [tab])

  const openEditEnv = (env) => {
    const normalizeKv = (kv) => {
      if (!kv) return []
      if (Array.isArray(kv)) return kv
      if (typeof kv === 'object') {
        return Object.entries(kv).map(([key, value]) => ({ key, value: value ?? '' }))
      }
      return []
    }
    if (env) {
      setEnvEditing({
        ...env,
        headers: normalizeKv(env.headers),
        variables: normalizeKv(env.variables),
      })
    } else {
      setEnvEditing({ name: '', base_url: '', headers: [], variables: [], is_default: envs.length === 0 })
    }
    setEnvDrawerOpen(true)
  }

  // KvEditor 数组 → 后端 dict；过滤空行；敏感值 ****** 保留为 null
  const kvArrayToDict = (arr) => {
    const out = {}
    for (const row of arr || []) {
      const k = row?.key?.trim()
      if (!k) continue
      const v = row?.value
      out[k] = v === '******' ? null : (v ?? '')
    }
    return out
  }

  const saveEnv = async () => {
    if (!envEditing?.name) { message.error('请填写名称'); return }
    setEnvSaving(true)
    try {
      const payload = {
        name: envEditing.name,
        base_url: envEditing.base_url || null,
        headers: kvArrayToDict(envEditing.headers),
        variables: kvArrayToDict(envEditing.variables),
        is_default: !!envEditing.is_default,
      }
      if (envEditing.env_id) {
        // PUT /projects/{id}/environments/{env_id}
        await http.put(`/projects/${id}/environments/${envEditing.env_id}`, payload)
      } else {
        // POST /projects/{id}/environments
        await http.post(`/projects/${id}/environments`, payload)
      }
      setEnvDrawerOpen(false)
      const fresh = await http.get(`/projects/${id}/environments`)
      setEnvs(Array.isArray(fresh) ? fresh : (fresh?.items || []))
      message.success('已保存')
    } catch {
      /* */
    } finally {
      setEnvSaving(false)
    }
  }

  const copyEnv = async (env) => {
    try {
      // POST /projects/{id}/environments/{env_id}/duplicate
      await http.post(`/projects/${id}/environments/${env.env_id}/duplicate`)
      message.success('已复制')
      const fresh = await http.get(`/projects/${id}/environments`)
      setEnvs(Array.isArray(fresh) ? fresh : (fresh?.items || []))
    } catch { /* */ }
  }

  const deleteEnv = async (env) => {
    Modal.confirm({
      title: '确认删除',
      content: `将删除环境「${env.name}」`,
      onOk: async () => {
        try {
          // DELETE /projects/{id}/environments/{env_id}
          await http.delete(`/projects/${id}/environments/${env.env_id}`)
          message.success('已删除')
          const fresh = await http.get(`/projects/${id}/environments`)
          setEnvs(Array.isArray(fresh) ? fresh : (fresh?.items || []))
        } catch { /* */ }
      },
    })
  }

  const statCards = [
    { key: 'tasks', title: '总任务数', value: overview?.task_total ?? overview?.task_count ?? 0, delay: 0, suffix: '' },
    { key: 'running', title: '运行中', value: overview?.task_running ?? 0, delay: 40 },
    { key: 'reports', title: '已生成报告', value: overview?.report_total ?? overview?.report_count ?? 0, delay: 80 },
    { key: 'envs', title: '环境数', value: overview?.env_count ?? 0, delay: 120 },
    { key: 'members', title: '成员数', value: overview?.member_count ?? 0, delay: 160 },
    { key: 'pass', title: '通过率', value: overview?.pass_rate ?? 0, delay: 200, suffix: '%' },
  ]

  return (
    <div>
      {/* 封面式头部 */}
      <Card
        style={{
          background: 'linear-gradient(135deg, #11161d 0%, #0b0f14 100%)',
          borderColor: '#1f2833',
          marginBottom: 16,
        }}
        bodyStyle={{ padding: '24px 28px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 16 }}
      >
        <div>
          <div style={{ color: '#869BAA', fontSize: 12, marginBottom: 4 }}>
            {project?.code ? `项目编号：${project.code}` : ' '}
          </div>
          <h1 style={{ margin: 0, fontSize: 24, color: '#e6f7ff', borderLeft: '3px solid #13c2c2', paddingLeft: 10 }}>
            {project?.name || '—'}
          </h1>
          <div style={{ marginTop: 8, color: '#8ba3b5', fontSize: 13 }}>
            {project?.description || '暂无项目描述'}
          </div>
          {/* 元信息行：被测系统、负责人、可见性、创建时间 */}
          <div style={{ marginTop: 12, display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12, color: '#7a8c9d' }}>
            {project?.target_system && (
              <span title="被测系统备注（仅展示，不参与执行）">🎯 {project.target_system}</span>
            )}
            {project?.owner_name && (
              <span title="负责人">👤 {project.owner_name}</span>
            )}
            {project?.visibility && (
              <span title="可见性">{project.visibility === 'PRIVATE' ? '🔒 私有' : project.visibility === 'TEAM' ? '👥 团队' : '🌐 公开'}</span>
            )}
            {project?.status && (
              <span title="状态">{project.status === 'ACTIVE' ? '✅ 启用' : '⏸️ 停用'}</span>
            )}
            {project?.created_at && (
              <span title="创建时间">📅 {new Date(project.created_at).toLocaleString('zh-CN', { hour12: false })}</span>
            )}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ color: '#8ba3b5', fontSize: 13, marginBottom: 4 }}>整体通过率</div>
          <div className="mono" style={{ fontSize: 28, color: '#13c2c2', fontWeight: 700 }}>
            <CountUp to={overview?.pass_rate ?? 0} duration={300} suffix="%" />
          </div>
        </div>
      </Card>

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'overview',
            label: '概览',
            children: (
              <Spin spinning={loading}>
                <div style={{ marginBottom: 12, textAlign: 'right' }}>
                  <Button size="small" onClick={() => setTab('quality')}>查看质量视图</Button>
                </div>
                {/* 统计卡 3x2 */}
                <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                  {statCards.map((c) => (
                    <Col key={c.key} xs={24} sm={12} lg={8} className="fadeUp" style={{ animationDelay: `${c.delay}ms` }}>
                      <Card size="small" style={{ background: '#11161d', borderColor: '#1f2833' }}>
                        <div className="stat-title">{c.title}</div>
                        <div className="mono stat-value" style={{ fontSize: 24 }}>
                          <CountUp to={c.value} duration={800} suffix={c.suffix} />
                        </div>
                      </Card>
                    </Col>
                  ))}
                </Row>

                <Row gutter={[16, 16]}>
                  <Col xs={24} lg={12}>
                    <Card
                      title={<span style={{ color: '#e6f7ff', borderLeft: '3px solid #13c2c2', paddingLeft: 10 }}>最近 5 任务</span>}
                      size="small"
                      style={{ background: '#11161d', borderColor: '#1f2833' }}
                    >
                      {tasks.length === 0 ? (
                        <Empty description="暂无任务" />
                      ) : (
                        <Table
                          rowKey="id"
                          size="small"
                          pagination={false}
                          dataSource={tasks}
                          columns={[
                            { title: '编号', dataIndex: 'task_no', render: (v) => <span className="mono">{v || '#'}</span> },
                            { title: '名称', dataIndex: 'name' },
                            {
                              title: '状态', dataIndex: 'status',
                              render: (s) => {
                                const map = { PENDING: 'blue', RUNNING: 'processing', SUCCESS: 'success', FAILED: 'error', SKIP: 'default', pending: 'blue', running: 'processing', success: 'success', failed: 'error', skip: 'default' }
                                return <Tag color={map[s] || 'default'}>{s || '-'}</Tag>
                              },
                            },
                            { title: '创建时间', dataIndex: 'created_at', render: (v) => (v || '').slice(0, 19).replace('T', ' ') },
                          ]}
                        />
                      )}
                    </Card>
                  </Col>
                  <Col xs={24} lg={12}>
                    <Card
                      title={<span style={{ color: '#e6f7ff', borderLeft: '3px solid #13c2c2', paddingLeft: 10 }}>最近 5 报告</span>}
                      size="small"
                      style={{ background: '#11161d', borderColor: '#1f2833' }}
                    >
                      {reports.length === 0 ? (
                        <Empty description="暂无报告" />
                      ) : (
                        <Table
                          rowKey="id"
                          size="small"
                          pagination={false}
                          dataSource={reports}
                          columns={[
                            { title: '编号', dataIndex: 'report_no', render: (v) => <span className="mono">{v || '#'}</span> },
                            { title: '名称', dataIndex: 'name' },
                            { title: '通过率', dataIndex: 'pass_rate', render: (v) => <span className="mono" style={{ color: '#13c2c2' }}>{(v ?? '—')}{v != null ? '%' : ''}</span> },
                            { title: '生成时间', dataIndex: 'generated_at', render: (v) => (v || '').slice(0, 19).replace('T', ' ') },
                          ]}
                        />
                      )}
                    </Card>
                  </Col>
                </Row>
              </Spin>
            ),
          },
          {
            key: 'quality',
            label: '质量视图',
            children: <ProjectQualityView id={Number(id)} onGoTab={setTab} />,
          },
          {
            key: 'tasks',
            label: '任务',
            children: (
              <Spin spinning={tasksLoading}>
                <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#8ba3b5', fontSize: 13 }}>共 {tasksTotal} 条</span>
                  <Space>
                    <Button type="link" onClick={() => navigate(`/assets?project_id=${id}`)}>去资产中心 →</Button>
                    <Button type="link" onClick={() => navigate(`/tasks?project_id=${id}`)}>去任务中心 →</Button>
                  </Space>
                </div>
                <Table
                  rowKey="id"
                  size="small"
                  loading={tasksLoading}
                  dataSource={tasks}
                  pagination={{ current: tasksPage, pageSize: 10, total: tasksTotal, onChange: loadTasks, showSizeChanger: false }}
                  locale={{ emptyText: <Empty description="该项目下暂无任务" /> }}
                  columns={[
                    { title: '任务编号', dataIndex: 'task_no', width: 200, render: (v) => <span className="mono">{v || '#'}</span> },
                    { title: '名称', dataIndex: 'name', ellipsis: true },
                    {
                      title: '状态', dataIndex: 'status', width: 100,
                      render: (s) => {
                        const map = { PENDING: 'blue', RUNNING: 'processing', SUCCESS: 'success', FAILED: 'error', SKIP: 'default', pending: 'blue', running: 'processing', success: 'success', failed: 'error', skip: 'default' }
                        return <Tag color={map[s] || 'default'}>{s || '-'}</Tag>
                      },
                    },
                    { title: '创建时间', dataIndex: 'created_at', width: 170, render: (v) => (v || '').slice(0, 19).replace('T', ' ') },
                    {
                      title: '操作', width: 100,
                      render: (_, row) => <a onClick={() => navigate(`/tasks/${row.id}`)}>详情</a>,
                    },
                  ]}
                />
              </Spin>
            ),
          },
          {
            key: 'reports',
            label: '报告',
            children: (
              <Spin spinning={reportsLoading}>
                <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#8ba3b5', fontSize: 13 }}>按项目筛选的报告</span>
                  <Button type="link" onClick={() => navigate(`/reports?project_id=${id}`)}>去报告中心 →</Button>
                </div>
                <Table
                  rowKey="id"
                  size="small"
                  loading={reportsLoading}
                  dataSource={reports}
                  pagination={false}
                  locale={{ emptyText: <Empty description="该项目下暂无报告" /> }}
                  columns={[
                    { title: '编号', dataIndex: 'report_no', width: 200, render: (v) => <span className="mono">{v || '#' + v}</span> },
                    { title: '名称', dataIndex: 'name', ellipsis: true },
                    { title: '通过率', dataIndex: 'pass_rate', width: 100, align: 'center', render: (v) => <span className="mono" style={{ color: v >= 80 ? '#52c41a' : v >= 50 ? '#faad14' : '#ff4d4f' }}>{v ?? '—'}%</span> },
                    { title: '生成时间', dataIndex: 'generated_at', width: 170, render: (v) => (v || '').slice(0, 19).replace('T', ' ') },
                    { title: '操作', width: 80, render: (_, row) => <a onClick={() => navigate(`/reports`)}>查看</a> },
                  ]}
                />
              </Spin>
            ),
          },
          {
            key: 'envs',
            label: '环境',
            children: (
              <div>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
                  这里是功能测试（UI/API/安全等引擎）的执行环境与鉴权配置，任务向导选择「执行环境」后自动注入被测地址；
                  AI 评测的应答来源请到 <Link to="/targets">被测系统</Link> 页注册，两者互不替代。
                </Typography.Paragraph>
                <div style={{ marginBottom: 12 }}>
                  <Button
                    type="primary"
                    onClick={() => openEditEnv(null)}
                    style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
                  >
                    + 新增环境
                  </Button>
                </div>
                <Row gutter={[16, 16]}>
                  {envs.length === 0 && (
                    <Col span={24}><Empty description="暂无环境" /></Col>
                  )}
                  {envs.map((env) => (
                    <Col xs={24} sm={12} lg={8} key={env.env_id || env.id || env.name}>
                      <Card size="small" style={{ background: '#11161d', borderColor: '#1f2833' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <div style={{ fontSize: 15, fontWeight: 600, color: '#e6f7ff' }}>
                            {env.is_default && <Tag color="cyan" style={{ marginRight: 6 }}>默认</Tag>}
                            {env.name}
                          </div>
                          <Space>
                            <Tooltip title="编辑"><Button size="small" onClick={() => openEditEnv(env)}>编辑</Button></Tooltip>
                            <Tooltip title="复制"><Button size="small" onClick={() => copyEnv(env)}>复制</Button></Tooltip>
                            <Tooltip title="删除"><Button size="small" danger onClick={() => deleteEnv(env)}>删除</Button></Tooltip>
                          </Space>
                        </div>
                        <div style={{ marginTop: 8, color: '#8ba3b5', fontSize: 12 }} className="mono">
                          {env.base_url || '—'}
                        </div>
                        <div style={{ marginTop: 4, color: '#869BAA', fontSize: 12 }}>
                          变量 {env.variables?.length || 0} 个 · Headers {env.headers?.length || 0} 个
                        </div>
                      </Card>
                    </Col>
                  ))}
                </Row>
              </div>
            ),
          },
          {
            key: 'members',
            label: `成员${members.length > 0 ? ` (${members.length})` : ''}`,
            children: (
              <Spin spinning={membersLoading}>
                <Table
                  rowKey={(r) => r.user_id || r.username || r.id}
                  size="small"
                  loading={membersLoading}
                  dataSource={members}
                  pagination={false}
                  locale={{ emptyText: <Empty description="该项目下暂无成员" /> }}
                  columns={[
                    { title: '用户', dataIndex: 'username', width: 140, render: (v, r) => <span>{r.display_name || v}</span> },
                    { title: '角色', dataIndex: 'role', width: 120, render: (v) => <Tag color={v === 'OWNER' ? 'gold' : v === 'ADMIN' ? 'blue' : 'default'}>{v}</Tag> },
                    { title: '邮箱', dataIndex: 'email', ellipsis: true },
                    { title: '加入时间', dataIndex: 'joined_at', width: 170, render: (v) => (v || '').slice(0, 19).replace('T', ' ') },
                  ]}
                />
              </Spin>
            ),
          },
          {
            key: 'versions',
            label: '版本基线',
            children: <Versions />,
          },
          {
            key: 'suites',
            label: `测试套件${suites.length > 0 ? ` (${suites.length})` : ''}`,
            children: (
              <Spin spinning={suitesLoading}>
                <Table
                  rowKey="id"
                  size="small"
                  loading={suitesLoading}
                  dataSource={suites}
                  pagination={false}
                  locale={{ emptyText: <Empty description="该项目下暂无测试套件" /> }}
                  columns={[
                    { title: '套件编号', dataIndex: 'code', width: 200, render: (v) => <span className="mono">{v || '#'}</span> },
                    { title: '名称', dataIndex: 'name', ellipsis: true },
                    { title: '包含用例数', dataIndex: 'case_count', width: 120, align: 'center' },
                    { title: '创建时间', dataIndex: 'created_at', width: 170, render: (v) => (v || '').slice(0, 19).replace('T', ' ') },
                  ]}
                />
              </Spin>
            ),
          },
          {
            key: 'uat',
            label: '验收报告',
            children: <UatReportList projectId={Number(id)} />,
          },
          {
            key: 'src',
            label: '源代码审计',
            children: isCommunity ? <UpgradeEmpty kind="src_audit" /> : (
              <CommercialGate kind="src_audit">
                <PageSuspense><SrcAuditPanel projectId={Number(id)} /></PageSuspense>
              </CommercialGate>
            ),
          },
        ]}
      />

      {/* 环境编辑 Drawer 640px */}
      <Drawer
        title={envEditing?.id ? '编辑环境' : '新增环境'}
        width={640}
        open={envDrawerOpen}
        onClose={() => setEnvDrawerOpen(false)}
        styles={{ body: { background: '#0b0f14' } }}
        footer={
          <Space style={{ justifyContent: 'flex-end', width: '100%' }}>
            <Button onClick={() => setEnvDrawerOpen(false)}>取消</Button>
            <Button
              type="primary"
              loading={envSaving}
              onClick={saveEnv}
              style={{ background: '#13c2c2', borderColor: '#13c2c2', color: '#0b0f14', borderRadius: 2 }}
            >
              保存
            </Button>
          </Space>
        }
      >
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: '#8ba3b5', fontSize: 12, marginBottom: 4 }}>名称</div>
          <Input
            value={envEditing?.name || ''}
            onChange={(e) => setEnvEditing({ ...envEditing, name: e.target.value })}
            placeholder="如：生产环境 / 预发环境"
          />
        </div>
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: '#8ba3b5', fontSize: 12, marginBottom: 4 }}>Base URL</div>
          <Input
            className="mono"
            value={envEditing?.base_url || ''}
            onChange={(e) => setEnvEditing({ ...envEditing, base_url: e.target.value })}
            placeholder="https://api.example.com"
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <div style={{ color: '#8ba3b5', fontSize: 12, marginBottom: 4 }}>设为默认环境</div>
          <Radio
            checked={!!envEditing?.is_default}
            onChange={(e) => setEnvEditing({ ...envEditing, is_default: e.target.checked })}
          >
            默认环境（请求未指定时使用）
          </Radio>
        </div>
        <div style={{ marginBottom: 8, color: '#8ba3b5', fontSize: 13, borderLeft: '3px solid #13c2c2', paddingLeft: 10 }}>
          Headers
        </div>
        <div style={{ marginBottom: 16 }}>
          <KvEditor
            value={envEditing?.headers || []}
            onChange={(v) => setEnvEditing({ ...envEditing, headers: v })}
            sensitiveKeys={['Authorization', 'X-Auth-Token', 'API-Key', 'X-API-Key']}
          />
        </div>
        <div style={{ marginBottom: 8, color: '#8ba3b5', fontSize: 13, borderLeft: '3px solid #13c2c2', paddingLeft: 10 }}>
          变量 Variables
        </div>
        <KvEditor
          value={envEditing?.variables || []}
          onChange={(v) => setEnvEditing({ ...envEditing, variables: v })}
          sensitiveKeys={['password', 'secret', 'token', 'api_key', 'API_KEY', 'SECRET', 'TOKEN']}
        />
      </Drawer>
    </div>
  )
}
