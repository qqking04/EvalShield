/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useState, useEffect, useMemo } from 'react'
import {
  InboxOutlined, FileTextOutlined, ThunderboltOutlined,
  AlertOutlined, BulbOutlined, WarningOutlined,
  EditOutlined, DeleteOutlined, CheckCircleOutlined
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  Button, Upload, Input, Select, Card, Row, Col, message, Typography,
  Space, Tag, Steps, Alert, Tooltip, Checkbox, Divider, Table, Spin,
  InputNumber, Popconfirm, Badge
} from 'antd'
import http from '../api/http'

const { Dragger } = Upload
const { Text, Paragraph } = Typography

const MAX_FILE_SIZE = 5 * 1024 * 1024  // 5MB
const ACCEPTED_EXTS = ['.pdf', '.docx', '.txt', '.md']

const CATEGORY_OPTIONS = [
  { value: 'FUNCTIONAL', label: '功能测试' },
  { value: 'API', label: 'API 测试' },
  { value: 'UI', label: 'UI 测试' },
  { value: 'PERF', label: '性能测试' },
  { value: 'HALLUCINATION', label: '幻觉检测' },
  { value: 'REDTEAM', label: '红队对抗' },
  { value: 'RAG', label: '检索增强 RAG' },
  { value: 'ETHICS', label: '伦理合规' },
  { value: 'DATAFLOW', label: '数据流测试' },
  { value: 'DATA_QUALITY', label: '数据质量' },
  { value: 'MULTI_TURN', label: '多轮对话' },
  { value: 'EVAL', label: '通用评测' },
  { value: 'CASE_GEN', label: '用例生成' },
  { value: 'SECURITY', label: '安全测试' },
  { value: 'DEFECT_PREDICT', label: '缺陷预测' },
  { value: 'SELF_HEAL', label: '自愈修复' },
]

// 引擎类型分组（与后端 engine_type 对齐）
const ENGINE_GROUPS = [
  { key: 'AI', label: 'AI 评测引擎', desc: '基于大模型的智能测试' },
  { key: 'TRADITIONAL', label: '传统测试引擎', desc: 'API/UI/性能/数据流' },
  { key: 'ENGINEERING', label: '工程辅助引擎', desc: '缺陷预测/自愈/用例生成' },
]

const ENGINE_TYPE_LABEL = ENGINE_GROUPS.reduce((acc, g) => {
  acc[g.key] = g.label
  return acc
}, {})

export default function DocumentImport() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)  // 0=上传配置, 1=预览草稿
  const [projectId, setProjectId] = useState(null)
  const [module, setModule] = useState('')
  const [category, setCategory] = useState('FUNCTIONAL')
  const [fileList, setFileList] = useState([])
  const [autoRun, setAutoRun] = useState(false)
  const [engine, setEngine] = useState('EVAL_ENGINE')
  const [loading, setLoading] = useState(false)
  const [parsing, setParsing] = useState(false)
  const [result, setResult] = useState(null)
  const [projects, setProjects] = useState([])
  const [engines, setEngines] = useState([])
  const [projectLoadError, setProjectLoadError] = useState(null)
  const [engineLoadError, setEngineLoadError] = useState(null)
  const [draftCases, setDraftCases] = useState([])
  const [editingKey, setEditingKey] = useState(null)

  // ===== 数据源加载 =====
  const loadData = async () => {
    try {
      const d = await http.get('/projects', { params: { page: 1, page_size: 200 } })
      setProjects((d?.items || []).map((p) => ({ value: p.id, label: p.name })))
      setProjectLoadError(null)
    } catch (e) {
      setProjectLoadError(e?.message || '项目列表加载失败')
    }
    try {
      const d = await http.get('/engines')
      setEngines(d?.items || [])
      setEngineLoadError(null)
    } catch (e) {
      setEngineLoadError(e?.message || '引擎列表加载失败')
    }
  }
  useEffect(() => { loadData() /* eslint-disable-next-line */ }, [])

  // ===== 引擎分组 =====
  const groupedEngines = useMemo(() => {
    const groups = {}
    engines.forEach((e) => {
      const t = e.engine_type || 'AI'
      if (!groups[t]) groups[t] = []
      groups[t].push({
        value: e.engine_code,
        label: e.engine_name || e.engine_code,
        description: e.description || '',
      })
    })
    return Object.entries(groups).map(([type, items]) => ({
      label: ENGINE_TYPE_LABEL[type] || type,
      options: items,
    }))
  }, [engines])

  const fallbackGroups = [{
    label: '默认引擎',
    options: [
      { value: 'EVAL_ENGINE', label: '通用评测引擎', description: '默认规则兜底' },
      { value: 'API_TEST', label: 'API 测试引擎', description: 'HTTP 接口自动化' },
      { value: 'HALLUCINATION_TEST', label: '幻觉检测', description: 'TruthfulQA 基准' },
    ],
  }]
  const engineGroups = groupedEngines.length > 0 ? groupedEngines : fallbackGroups

  // ===== beforeUpload 校验 =====
  const beforeUpload = (file) => {
    const ext = (file.name || '').substring((file.name || '').lastIndexOf('.')).toLowerCase()
    if (!ACCEPTED_EXTS.includes(ext)) {
      message.error(`不支持的文件格式 ${ext}，仅支持 ${ACCEPTED_EXTS.join(' / ')}`)
      return Upload.LIST_IGNORE
    }
    if (file.size > MAX_FILE_SIZE) {
      message.error(`文件大小超过 5MB（当前 ${(file.size / 1024 / 1024).toFixed(2)} MB）`)
      return Upload.LIST_IGNORE
    }
    return true
  }

  // ===== 草稿生成（在前端做预解析提示） =====
  const handleGenerateDraft = async () => {
    if (!projectId) return message.warning('请先选择项目')
    if (fileList.length === 0) return message.warning('请先上传文档')
    const file = fileList[0].originFileObj
    const ext = (file.name || '').substring((file.name || '').lastIndexOf('.')).toLowerCase()
    // PDF/DOCX 在浏览器里无法直接提取有效文本，跳过客户端预解析
    if (ext !== '.txt' && ext !== '.md') {
      setStep(1)
      setDraftCases([])
      message.info('📄 PDF/DOCX 文件将由后端解析，请在下一步直接确认入库（不支持客户端预览草稿）')
      return
    }
    setParsing(true)
    try {
      const content = await file.text()
      // 简单按双换行分割，模拟后端的分块逻辑
      const lines = content.split(/\n{2,}/).filter((s) => s.trim().length > 10)
      const chunkSize = Math.max(1, Math.ceil(lines.length / 20))
      const draft = []
      for (let i = 0; i < Math.min(lines.length, chunkSize * 20); i += chunkSize) {
        const segment = lines.slice(i, i + chunkSize).join('\n').trim().substring(0, 500)
        const title = (segment.split('\n')[0] || '文档导入用例').substring(0, 80).trim()
        draft.push({
          key: `draft-${i}`,
          title: `[文档] ${title}`,
          precondition: segment.substring(0, 200),
          expected: '功能执行符合业务预期，无报错',
        })
      }
      if (draft.length === 0) {
        message.warning('文档内容过短或格式异常，无法生成草稿。请确认文档内容是否包含有效的业务描述段落。')
        return
      }
      setDraftCases(draft)
      setStep(1)
      message.success(`✅ 预解析完成，生成 ${draft.length} 条草稿用例（可编辑/删除后确认入库）`)
    } catch (e) {
      message.error(`文档预解析失败：${e.message || '未知错误'}`)
    } finally {
      setParsing(false)
    }
  }

  // ===== 编辑草稿 =====
  const edit = (record) => { setEditingKey(record.key) }
  const save = (key, row) => {
    setDraftCases((prev) => prev.map((c) => c.key === key ? { ...c, ...row } : c))
    setEditingKey(null)
  }
  const cancel = () => { setEditingKey(null) }
  const removeDraft = (key) => {
    setDraftCases((prev) => prev.filter((c) => c.key !== key))
  }
  const addEmptyRow = () => {
    setDraftCases((prev) => [...prev, {
      key: `draft-manual-${Date.now()}`,
      title: '[手动新增] 待填写',
      precondition: '',
      expected: '',
    }])
  }

  // ===== 真正提交到后端 =====
  const handleSubmit = async () => {
    if (!projectId) return message.warning('请先选择项目')
    if (fileList.length === 0) return message.warning('请先上传文档')
    if (draftCases.length === 0) return message.warning('没有待入库的用例草稿')

    setLoading(true); setResult(null)
    try {
      const form = new FormData()
      form.append('file', fileList[0].originFileObj)
      form.append('project_id', projectId)
      form.append('category', category)
      if (module) form.append('module', module)
      if (autoRun) {
        form.append('auto_run', 'true')
        form.append('engine', engine)
      }
      // 传递编辑后的草稿提示（后端目前不支持修改入库，这里传空让后端按原逻辑处理）
      const d = await http.post('/documents/import', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      setResult(d)
      if (d.auto_run) {
        message.success(`✅ 成功生成 ${d.count} 条用例 → 已自动执行（任务 ${d.task_no}，状态 ${d.task_status}）`)
      } else {
        message.success(`✅ 成功从文档生成 ${d.count} 条测试用例`)
      }
    } catch (e) {
      message.error(e?.message || '导入失败')
    } finally {
      setLoading(false)
    }
  }

  const isEditing = (record) => record.key === editingKey

  const columns = [
    {
      title: '#',
      key: 'index',
      width: 40,
      render: (_, __, i) => <span style={{ color: '#869BAA' }}>{i + 1}</span>,
    },
    {
      title: '用例标题',
      dataIndex: 'title',
      width: 200,
      render: (text, record) => {
        if (isEditing(record)) {
          return <Input value={text} onChange={(e) => save(record.key, { ...record, title: e.target.value })} />
        }
        return <span>{text}</span>
      },
    },
    {
      title: '前置条件',
      dataIndex: 'precondition',
      render: (text, record) => {
        if (isEditing(record)) {
          return <Input.TextArea rows={2} value={text} onChange={(e) => save(record.key, { ...record, precondition: e.target.value })} />
        }
        return <span style={{ color: '#8ba3b5', fontSize: 13 }}>{text?.substring(0, 120)}{text?.length > 120 ? '...' : ''}</span>
      },
    },
    {
      title: '预期结果',
      dataIndex: 'expected',
      width: 160,
      render: (text, record) => {
        if (isEditing(record)) {
          return <Input value={text} onChange={(e) => save(record.key, { ...record, expected: e.target.value })} />
        }
        return <span style={{ color: '#8ba3b5', fontSize: 13 }}>{text}</span>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, record) => isEditing(record) ? (
        <Space size="small">
          <Button type="link" size="small" onClick={() => save(record.key, record)}>保存</Button>
          <Button type="link" size="small" onClick={cancel}>取消</Button>
        </Space>
      ) : (
        <Space size="small">
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => edit(record)}>编辑</Button>
          <Popconfirm title="确认删除这条草稿用例？" onConfirm={() => removeDraft(record.key)} okText="删除" cancelText="取消">
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: '0 auto' }}>
      <Card
        bordered={false}
        style={{ borderRadius: 4, background: 'linear-gradient(180deg, #11161d 0%, #0e1218 100%)' }}
        title={
          <Space size={12}>
            <div style={{
              width: 36, height: 36, borderRadius: 2,
              background: 'linear-gradient(135deg, #13c2c2 0%, #08979c 100%)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 0 20px rgba(19,194,194,0.3)',
            }}>
              <FileTextOutlined style={{ color: '#fff', fontSize: 20 }} />
            </div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 600, letterSpacing: 1 }}>文档导入 → AI 生成测试用例</div>
              <Text type="secondary" style={{ fontSize: 12 }}>两步流程：上传 + 预览草稿 → 编辑确认 → 一键入库</Text>
            </div>
          </Space>
        }
      >
        {/* ====== 加载失败告警 ====== */}
        {engineLoadError && (
          <Alert
            type="warning"
            showIcon
            icon={<AlertOutlined />}
            message="引擎列表加载失败，已使用默认 3 个引擎"
            description={engineLoadError}
            action={<Button size="small" onClick={loadData}>重试</Button>}
            style={{ marginBottom: 12 }}
          />
        )}
        {projectLoadError && (
          <Alert
            type="warning"
            showIcon
            icon={<AlertOutlined />}
            message="项目列表加载失败"
            description={projectLoadError}
            action={<Button size="small" onClick={loadData}>重试</Button>}
            style={{ marginBottom: 12 }}
          />
        )}

        {/* ====== Step 指示器 ====== */}
        <div style={{
          background: 'rgba(19,194,194,0.04)',
          border: '1px solid rgba(19,194,194,0.15)',
          borderRadius: 4,
          padding: '16px 24px',
          marginBottom: 20,
        }}>
          <Steps
            current={step}
            size="small"
            items={[
              { title: '上传文档 + 配置', description: '选择项目/模块/类别', icon: <InboxOutlined /> },
              { title: '预览草稿 + 编辑', description: '确认无误后入库', icon: <EditOutlined /> },
            ]}
          />
        </div>

        {/* ======================= STEP 0: 上传 + 配置 ======================= */}
        {step === 0 && (
          <>
            <Row gutter={16}>
              <Col span={8}>
                <Text strong>所属项目</Text>
                <Select
                  placeholder="请选择被测项目"
                  style={{ width: '100%', marginTop: 6 }}
                  showSearch
                  value={projectId}
                  options={projects}
                  onChange={setProjectId}
                  status={projectLoadError ? 'warning' : undefined}
                />
              </Col>
              <Col span={6}>
                <Text strong>模块（可选）</Text>
                <Input placeholder="如 登录/订单/支付" style={{ marginTop: 6 }} value={module}
                  onChange={(e) => setModule(e.target.value)} />
              </Col>
              <Col span={10}>
                <Text strong>用例类别</Text>
                <Select style={{ width: '100%', marginTop: 6 }} value={category} onChange={setCategory}
                  showSearch optionFilterProp="label" options={CATEGORY_OPTIONS} />
              </Col>
            </Row>

            {/* ===== 文件上传 ===== */}
            <div style={{ marginTop: 20 }}>
              <Dragger
                multiple={false}
                fileList={fileList}
                beforeUpload={beforeUpload}
                onChange={({ fileList: fl }) => setFileList(fl.slice(-1))}
                accept=".pdf,.docx,.txt,.md"
                maxCount={1}
              >
                <p className="ant-upload-drag-icon"><InboxOutlined style={{ color: '#13c2c2' }} /></p>
                <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
                <p className="ant-upload-hint">支持 PDF / DOCX / TXT / MD，单文件 ≤ 5MB</p>
              </Dragger>
            </div>

            {/* ===== 自动执行选项 ===== */}
            <Divider style={{ marginTop: 24, marginBottom: 16 }} />

            <Row gutter={16} align="middle">
              <Col span={6}>
                <Checkbox checked={autoRun} onChange={(e) => setAutoRun(e.target.checked)}>
                  <Space><ThunderboltOutlined style={{ color: '#13c2c2' }} />自动 AI 执行（跳过手动建任务）</Space>
                </Checkbox>
              </Col>
              {autoRun && (
                <Col span={10}>
                  <Text strong>执行引擎</Text>
                  <Select
                    style={{ width: '100%', marginTop: 6 }}
                    value={engine}
                    onChange={setEngine}
                    optionLabelProp="label"
                    options={engineGroups}
                    optionRender={(option) => {
                      const item = option.dataRef
                      return (
                        <Tooltip title={item?.description || '暂无描述'} placement="right">
                          <span>{option.label}</span>
                        </Tooltip>
                      )
                    }}
                  />
                </Col>
              )}
            </Row>

            {/* ===== 下一步按钮 ===== */}
            <div style={{ marginTop: 28, textAlign: 'center' }}>
              <Button
                type="primary"
                size="large"
                icon={<BulbOutlined />}
                loading={parsing}
                onClick={handleGenerateDraft}
                disabled={!projectId || fileList.length === 0 || parsing}
                style={{
                  height: 44, paddingLeft: 28, paddingRight: 28, fontSize: 14,
                  background: 'linear-gradient(135deg, #13c2c2 0%, #08979c 100%)',
                  borderColor: '#13c2c2',
                  boxShadow: '0 0 16px rgba(19,194,194,0.3)',
                }}
              >
                {parsing ? 'AI 正在预解析文档...' : '下一步：预览草稿用例'}
              </Button>
              <div style={{ marginTop: 8 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  💡 文档上传后，AI 会自动按段落分块生成测试用例草稿。你可以在下一步预览、编辑、删除不满意的用例后再确认入库。
                </Text>
              </div>
            </div>
          </>
        )}

        {/* ======================= STEP 1: 预览 + 编辑 ======================= */}
        {step === 1 && (
          <>
            <Alert
              type="info"
              showIcon
              message={
                <Space>
                  {draftCases.length > 0 ? (
                    <>
                      <span>已从文档预解析出 </span>
                      <Text strong style={{ color: '#13c2c2' }}>{draftCases.length}</Text>
                      <span> 条草稿用例</span>
                    </>
                  ) : (
                    <span>PDF/DOCX 文件 · 跳过客户端预览</span>
                  )}
                </Space>
              }
              description={
                <span style={{ fontSize: 12 }}>
                  {draftCases.length > 0
                    ? '💡 下方草稿为客户端预览（仅供参考），可以编辑/删除。点击"确认入库"后将由后端 AI 重新解析文档并正式创建用例。'
                    : '💡 点击"确认入库"后将由后端 AI 解析 PDF/DOCX 文档并正式创建用例。客户端不提供该格式的预览功能。'}
                </span>
              }
              style={{ marginBottom: 16 }}
            />

            <div style={{ marginBottom: 12, textAlign: 'right' }}>
              <Button type="dashed" onClick={addEmptyRow} icon={<BulbOutlined />}>手动新增用例草稿</Button>
            </div>

            <Table
              size="middle"
              dataSource={draftCases}
              columns={columns}
              pagination={{ pageSize: 10, size: 'small' }}
              rowKey="key"
              scroll={{ y: 360 }}
            />

            <div style={{ marginTop: 24, textAlign: 'center' }}>
              <Space size={16}>
                <Button onClick={() => setStep(0)}>← 返回修改上传配置</Button>
                <Button
                  type="primary"
                  size="large"
                  icon={autoRun ? <ThunderboltOutlined /> : <CheckCircleOutlined />}
                  loading={loading}
                  onClick={handleSubmit}
                  disabled={loading || draftCases.length === 0}
                  style={{
                    height: 44, paddingLeft: 28, paddingRight: 28, fontSize: 14,
                    background: autoRun ? undefined : 'linear-gradient(135deg, #13c2c2 0%, #08979c 100%)',
                    borderColor: autoRun ? undefined : '#13c2c2',
                  }}
                >
                  {autoRun ? '🚀 确认入库 + 自动 AI 执行' : '✅ 确认入库生成测试用例'}
                </Button>
              </Space>
            </div>
          </>
        )}

        {/* ====== 最终结果 ====== */}
        {result && (
          <div style={{ marginTop: 24 }}>
            <Alert
              type={result.auto_run ? (result.task_status === 'SUCCESS' ? 'success' : 'warning') : 'success'}
              showIcon
              icon={<CheckCircleOutlined />}
              message={
                <Space>
                  <span style={{ fontSize: 15, fontWeight: 500 }}>
                    {result.auto_run
                      ? `✅ 成功生成 ${result.count} 条用例 → 已自动执行（任务 ${result.task_no}，状态 ${result.task_status}）`
                      : `✅ 成功生成 ${result.count} 条测试用例`}
                  </span>
                </Space>
              }
              description={`提取文本 ${result.chars_extracted || '?'} 字符 · 来源标签 DOC_IMPORT`}
              style={{ marginBottom: 16 }}
            />

            {/* 生成的用例快速预览 */}
            <Card size="small" title={<Text strong>生成用例快速预览（前 20 条）</Text>} extra={
              result.auto_run && (
                <Space>
                  <Button onClick={() => navigate(`/tasks/${result.task_id}`)} type="link">任务详情 →</Button>
                  <Button onClick={() => navigate('/reports')} type="link">报告中心 →</Button>
                </Space>
              )
            }>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {(result.titles || []).map((t, i) => (
                  <Tag key={i} color="#13c2c2" style={{ margin: 0, maxWidth: 400 }}>
                    #{i + 1} {t}
                  </Tag>
                ))}
              </div>
            </Card>
          </div>
        )}
      </Card>
    </div>
  )
}
