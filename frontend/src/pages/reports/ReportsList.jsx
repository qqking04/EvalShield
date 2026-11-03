/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useMemo, useState } from 'react'
import { Space, Card, Button, Table, Tag, Input, Select, DatePicker, Drawer, Row, message, Modal, Popconfirm, Dropdown } from 'antd'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ReloadOutlined, EyeOutlined, FilePdfOutlined, FileWordOutlined, FileMarkdownOutlined, FileTextOutlined, FileZipOutlined, SearchOutlined, ClearOutlined, DeleteOutlined, ShareAltOutlined, FileProtectOutlined, MoreOutlined } from '@ant-design/icons'
import http, { downloadBlob } from '../../api/http'
import { fmtTime } from '../../utils'
import { REPORT_STATUS_MAP, REPORT_STATUS_COLOR, labelOf } from '../../constants/enums'
import useDict from '../../hooks/useDict'
import ReportDetail from './ReportDetail'
import ShareModal from './ShareModal'
import { RiskTag } from './charts'
import { ES } from '../es11/gate'

export const REPORT_TYPE_OPTIONS = [
  { value: '', label: '全部报告' },
  { value: 'FULL', label: '完整报告' },
  { value: 'SUMMARY', label: '摘要报告' },
]

// P1-15：按测试维度筛选（对应后端 summary.dimension_stats 的 JSONB 键）
export const TEST_TYPE_OPTIONS = [
  { value: '', label: '全部维度' },
  { value: '功能测试', label: '功能测试' },
  { value: 'UI 测试', label: 'UI 测试' },
  { value: '性能测试', label: '性能测试' },
  { value: '安全测试', label: '安全测试' },
  { value: '数据流', label: '数据流', },
]

// 报告状态筛选（后端 /reports?status= 支持逗号分隔多值；实库存量取值为 GENERATING/DONE，
// GENERATING 与 RUNNING 为同义状态，合并为一个「生成中」选项做并集过滤）
export const REPORT_STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'DONE', label: '已完成' },
  { value: 'GENERATING,RUNNING', label: '生成中' },
  { value: 'PENDING', label: '待生成' },
  { value: 'FAILED', label: '失败' },
]

// P2-09：按用例来源筛选（后端 /reports?source= 取含该来源用例的报告）
export const SOURCE_OPTIONS = [
  { value: '', label: '全部来源' },
  { value: 'AGENT_GEN', label: 'Agent 生成' },
  { value: 'AI_GEN', label: 'AI 生成' },
  { value: 'MANUAL', label: '手工创建' },
  { value: 'UPLOAD', label: 'Excel 导入' },
]

export default function ReportsList() {
  const [searchParams, setSearchParams] = useSearchParams()
  // ES11 P10：交付工作台深链入口
  const navigate = useNavigate()
  // 深链：?project_id= 由项目详情页「查看报告」生成；筛选下拉与其双向同步
  const [projectId, setProjectId] = useState(searchParams.get('project_id') || '')
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState('') // `${rowId}:${format}`，导出中按钮 loading
  const [detail, setDetail] = useState(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const [reportType, setReportType] = useState('')
  const [testType, setTestType] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [source, setSource] = useState('')
  const [taskNo, setTaskNo] = useState('')
  const [dateRange, setDateRange] = useState(null)
  // 用例来源下拉来源于 source 字典（接口异常时兜底硬编码 SOURCE_OPTIONS）
  const { items: sourceDict } = useDict('source')
  const sourceOptions = useMemo(() => {
    const items = sourceDict.length ? sourceDict.map((x) => ({ value: x.value, label: x.label })) : SOURCE_OPTIONS.filter((o) => o.value)
    return [{ value: '', label: '全部来源' }, ...items]
  }, [sourceDict])
  // 项目下拉与所属项目列
  const [projects, setProjects] = useState([])
  useEffect(() => { http.get('/projects', { params: { page_size: 500 } }).then((d) => setProjects((d?.items || d) || [])).catch(() => {}) }, [])
  const projectNameOf = (id) => { const p = projects.find((x) => String(x.id) === String(id)); return p ? `${p.code} - ${p.name}` : id || '-' }

  const load = async (p = page, rt = reportType, tn = taskNo, dr = dateRange, tt = testType, sc = source, pid = projectId, st = statusFilter) => {
    setLoading(true)
    try {
      const q = { page: p, page_size: 10 }
      if (pid) q.project_id = pid
      if (rt) q.report_type = rt
      if (tt) q.test_type = tt
      if (st) q.status = st
      if (sc) q.source = sc
      if (tn) q.task_no = tn
      if (dr && dr.length === 2) { q.start_time = dr[0].toISOString(); q.end_time = dr[1].toISOString() }
      const d = await http.get('/reports', { params: q })
      setRows(d.items || [])
      setTotal(d.total || 0)
    } finally { setLoading(false) }
  }

  useEffect(() => { load(1) /* eslint-disable-next-line */ }, [])

  // 项目筛选切换：同步 URL ?project_id，保持深链一致
  const handleProjectChange = (v) => {
    const pid = v || ''
    setProjectId(pid)
    setPage(1)
    const next = new URLSearchParams(searchParams)
    if (pid) next.set('project_id', pid); else next.delete('project_id')
    setSearchParams(next, { replace: true })
    load(1, reportType, taskNo, dateRange, testType, source, pid)
  }
  const handleSearch = () => { setPage(1); load(1, reportType, taskNo, dateRange, testType, source) }
  const handleReset = () => {
    setReportType(''); setTestType(''); setStatusFilter(''); setSource(''); setTaskNo(''); setDateRange(null); setProjectId('')
    const next = new URLSearchParams(searchParams); next.delete('project_id'); setSearchParams(next, { replace: true })
    setPage(1); load(1, '', '', null, '', '', '', '')
  }

  const openDetail = async (id) => {
    const d = await http.get(`/reports/${id}`)
    setDetail(d); setDetailOpen(true)
  }

  const exportReport = async (row, format) => {
    Modal.confirm({
      title: `导出报告（${format.toUpperCase()}）`,
      content: `将导出报告 ${row.report_no}，本次导出会记录审计日志。是否继续？`,
      okText: '导出', cancelText: '取消',
      onOk: async () => {
        setExporting(`${row.id}:${format}`)
        try {
          const ext = { pdf: 'pdf', word: 'docx', compliance_package: 'zip', json: 'json', md: 'md', html: 'html' }[format] || format
          await downloadBlob(`/reports/${row.id}/export`, { format }, `${row.report_no}.${ext}`)
          message.success('报告已导出')
        } catch { /* 错误已由拦截器/downloadBlob 提示 */ } finally {
          setExporting('')
        }
      },
    })
  }

  const handleDelete = async (row) => {
    try { await http.delete(`/reports/${row.id}`); message.success('报告已删除'); load(page) } catch { /* 静默 */ }
  }
  // D-DEL-FE：批量删除报告
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const batchRemove = async () => {
    const ids = selectedRowKeys
    if (!ids.length) return
    try {
      const r = await http.post('/reports/batch-delete', { ids })
      message.success(`已删除 ${r?.deleted ?? ids.length} 条报告`)
      setSelectedRowKeys([]); load(page)
    } catch (e) { console.warn(e) }
  }

  const columns = [
    { title: '报告编号', dataIndex: 'report_no', width: 200, className: 'mono-no' },
    { title: '报告标题', dataIndex: 'title', ellipsis: true },
    { title: '所属项目', dataIndex: 'project_id', width: 170, ellipsis: true, render: (v) => v ? projectNameOf(v) : '-' },
    { title: '关联任务', dataIndex: 'task_no', width: 200, className: 'mono-no' },
    { title: '类型', dataIndex: 'report_type', width: 100, render: (v) => <Tag>{REPORT_TYPE_OPTIONS.find((o) => o.value === v)?.label || v}</Tag> },
    { title: '源格式', dataIndex: 'format', width: 90, render: (fmt) => <Tag>{String(fmt || 'json').toUpperCase()}</Tag> },
    { title: '风险等级', dataIndex: 'risk_level', width: 100, render: (v) => v ? <RiskTag level={v} /> : '-' },
    { title: '状态', dataIndex: 'status', width: 100, render: (v) => <Tag color={REPORT_STATUS_COLOR[v] || 'default'}>{labelOf(REPORT_STATUS_MAP, v)}</Tag> },
    { title: '通过率', dataIndex: 'summary', width: 110, render: (v) => { if (!v || !v.pass_rate) return '-'; const pct = Math.round(v.pass_rate * 100); return <Tag color={pct >= 80 ? 'green' : pct >= 60 ? 'orange' : 'red'}>{pct}%</Tag> } },
    { title: '生成时间', dataIndex: 'generated_at', width: 170, render: (v) => fmtTime(v) },
    {
      title: '操作', width: 210, fixed: 'right',
      render: (_, row) => (
        <Space size={2} style={{ whiteSpace: 'nowrap' }}>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openDetail(row.id)}>查看</Button>
          <Dropdown trigger={['click']} menu={{
            items: [
              { key: 'delivery', icon: <FileProtectOutlined />, label: '交付工作台', onClick: () => navigate(`/reports/${row.id}/delivery`) },
              { key: 'share', icon: <ShareAltOutlined />, label: '分享', onClick: () => { setDetail(row); setShareOpen(true); setDetailOpen(true) } },
              { type: 'divider' },
              { key: 'pdf', icon: <FilePdfOutlined />, label: '导出 PDF', onClick: () => exportReport(row, 'pdf') },
              { key: 'word', icon: <FileWordOutlined />, label: '导出 Word', onClick: () => exportReport(row, 'word') },
              { key: 'md', icon: <FileMarkdownOutlined />, label: '导出 Markdown', onClick: () => exportReport(row, 'md') },
              { key: 'json', icon: <FileTextOutlined />, label: '导出 JSON', onClick: () => exportReport(row, 'json') },
              { key: 'zip', icon: <FileZipOutlined />, label: 'ZIP 自证包', onClick: () => exportReport(row, 'compliance_package') },
            ],
          }}>
            <Button type="link" size="small" icon={<MoreOutlined />} loading={exporting.startsWith(`${row.id}:`)}>更多</Button>
          </Dropdown>
          <Popconfirm title="确认删除该报告？" description="删除后不可恢复，实际产物文件可选择保留" okText="确认删除" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={() => handleDelete(row)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small" styles={{ body: { padding: '12px 16px' } }}>
        <Row gutter={[12, 8]} align="middle">
          <Space wrap>
            <span style={{ color: '#8b97a7' }}>项目：</span>
            <Select allowClear showSearch style={{ width: 200 }} placeholder="全部项目" value={projectId || undefined} onChange={(v) => handleProjectChange(v)} options={projects.map((p) => ({ value: String(p.id), label: `${p.code} - ${p.name}` }))} optionFilterProp="label" />
            <span style={{ color: '#8b97a7' }}>报告类型：</span>
            <Select style={{ width: 140 }} value={reportType} onChange={setReportType} options={REPORT_TYPE_OPTIONS} />
            <span style={{ color: ES.sub }}>状态：</span>
            <Select style={{ width: 120 }} value={statusFilter} onChange={setStatusFilter} options={REPORT_STATUS_OPTIONS} />
            <span style={{ color: '#8b97a7' }}>测试维度：</span>
            <Select style={{ width: 130 }} value={testType} onChange={setTestType} options={TEST_TYPE_OPTIONS} />
            <span style={{ color: '#8b97a7' }}>用例来源：</span>
            <Select style={{ width: 130 }} value={source} onChange={setSource} options={sourceOptions} />
            <span style={{ color: '#8b97a7' }}>关联任务：</span>
            <Input placeholder="输入任务编号 TSK-xxxx" value={taskNo} onChange={(e) => setTaskNo(e.target.value)} onPressEnter={handleSearch} style={{ width: 200 }} allowClear />
            <span style={{ color: '#8b97a7' }}>时间段：</span>
            <DatePicker.RangePicker showTime value={dateRange} onChange={setDateRange} />
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>筛选</Button>
            <Button icon={<ClearOutlined />} onClick={handleReset}>重置</Button>
            <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
            <Popconfirm title={`确认批量删除选中的 ${selectedRowKeys.length} 条报告？`} disabled={!selectedRowKeys.length} onConfirm={batchRemove}>
              <Button danger icon={<DeleteOutlined />} disabled={!selectedRowKeys.length}>批量删除{selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length})` : ''}</Button>
            </Popconfirm>
          </Space>
        </Row>
      </Card>
      <Table rowKey="id" loading={loading} columns={columns} dataSource={rows} scroll={{ x: 1920 }}
        rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
        pagination={{ current: page, total, pageSize: 10, showTotal: (t) => `共 ${t} 条`, onChange: (p) => { setPage(p); load(p) } }} />
      <Drawer title={detail?.title || '报告详情'} width={900} open={detailOpen} onClose={() => { setDetailOpen(false); setShareOpen(false) }}
        extra={detail && <Button type="primary" icon={<ShareAltOutlined />} onClick={() => setShareOpen(true)}>分享</Button>}>
        {detail && <ReportDetail report={detail} onShareClick={() => setShareOpen(true)} />}
      </Drawer>
      <ShareModal open={shareOpen} onClose={() => setShareOpen(false)} reportId={detail?.id} />
    </Space>
  )
}
