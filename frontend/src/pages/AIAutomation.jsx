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
  RobotOutlined, ThunderboltOutlined, ExperimentOutlined,
  AlertOutlined, FileTextOutlined, CheckCircleOutlined,
  SettingOutlined, PlayCircleOutlined, FileDoneOutlined,
  BulbOutlined, DatabaseOutlined, CompassOutlined
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  Button, Select, Card, Row, Col, Input, Space, Tag, message,
  Typography, Steps, Badge, Alert, Tooltip, Radio, Checkbox,
  Divider, Table, Spin, Empty
} from 'antd'
import http from '../api/http'
import { useEdition } from '../edition/EditionContext'

const { Text, Paragraph, Title } = Typography
const { TextArea } = Input

// 引擎类型分组（与后端 engine_type 对齐）
const ENGINE_GROUPS = [
  { key: 'AI', label: 'AI 评测引擎', desc: '基于大模型的智能测试（幻觉/RAG/红队/伦理等）' },
  { key: 'TRADITIONAL', label: '传统测试引擎', desc: 'API/UI/性能/数据流等工程化引擎' },
  { key: 'ENGINEERING', label: '工程辅助引擎', desc: '缺陷预测、自愈修复、用例生成等 AI 工程工具' },
]

const ENGINE_TYPE_LABEL = ENGINE_GROUPS.reduce((acc, g) => {
  acc[g.key] = g.label
  return acc
}, {})

// Pipeline Stepper 定义
const PIPELINE_STEPS = [
  { title: '输入需求', icon: <BulbOutlined /> },
  { title: '生成用例', icon: <FileTextOutlined /> },
  { title: '创建任务', icon: <SettingOutlined /> },
  { title: '引擎执行', icon: <PlayCircleOutlined /> },
  { title: '生成报告', icon: <FileDoneOutlined /> },
]

// 根据执行结果推导当前完成到哪一步
function deriveStep(status) {
  if (!status) return 0
  if (status === 'FAILED') return 3  // 引擎执行阶段失败
  if (status === 'RUNNING' || status === 'PENDING') return 3
  return 5  // SUCCESS
}

export default function AIAutomation() {
  const navigate = useNavigate()
  const [projectId, setProjectId] = useState(null)
  const [prompt, setPrompt] = useState('')
  const [engine, setEngine] = useState('EVAL_ENGINE')
  const [mode, setMode] = useState('GENERATE')  // GENERATE | EXISTING
  const [selectedCaseIds, setSelectedCaseIds] = useState([])
  const [projects, setProjects] = useState([])
  const [engines, setEngines] = useState([])
  const [cases, setCases] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadingCases, setLoadingCases] = useState(false)
  const [projectLoadError, setProjectLoadError] = useState(null)
  const [engineLoadError, setEngineLoadError] = useState(null)
  const [result, setResult] = useState(null)
  const [activeStep, setActiveStep] = useState(0)

  // ===== 数据源加载 =====
  const loadProjects = async () => {
    try {
      const d = await http.get('/projects', { params: { page: 1, page_size: 200 } })
      setProjects((d?.items || []).map((p) => ({ value: p.id, label: p.name })))
      setProjectLoadError(null)
    } catch (e) {
      setProjectLoadError(e?.message || '项目列表加载失败')
    }
  }

  const loadEngines = async () => {
    try {
      const d = await http.get('/engines')
      setEngines(d?.items || [])
      setEngineLoadError(null)
    } catch (e) {
      setEngineLoadError(e?.message || '引擎列表加载失败')
    }
  }

  const loadCases = async (pid) => {
    if (!pid) return
    setLoadingCases(true)
    try {
      const d = await http.get('/cases', { params: { project_id: pid, page: 1, page_size: 200 } })
      setCases(d?.items || [])
      setSelectedCaseIds([])
    } catch {
      setCases([])
      setSelectedCaseIds([])
    } finally {
      setLoadingCases(false)
    }
  }

  useEffect(() => {
    loadProjects()
    loadEngines()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (mode === 'EXISTING' && projectId) {
      loadCases(projectId)
    }
  }, [mode, projectId])

  // ===== 引擎分组（OptGroup 格式） =====
  // F3：enabled_engines 白名单（未就绪/空清单前不裁剪）
  const { enabled_engines: enabledEngines } = useEdition()
  // AI 自动化页面只展示 AI + ENGINEERING 类型引擎
  // TRADITIONAL 引擎（DATA_QUALITY / LOCUST_PERF / UI_TEST 等）需要手工传入
  // source_ref / target_host 等参数，无法从 ai_automation 的 prompt/用例推断，
  // 必须走 /tasks 页面手工配置。这里直接隐藏，避免用户困惑。
  const groupedEngines = useMemo(() => {
    const groups = {}
    engines
      .filter((e) => (e.engine_type || 'AI') !== 'TRADITIONAL')
      .filter((e) => !(enabledEngines && enabledEngines.length > 0) || enabledEngines.includes(e.engine_code))
      .forEach((e) => {
        const t = e.engine_type || 'AI'
        if (!groups[t]) groups[t] = []
        groups[t].push({
          value: e.engine_code,
          label: e.engine_name || e.engine_code,
          description: e.description || '',
          engine_code: e.engine_code,
        })
      })
    return Object.entries(groups).map(([type, items]) => ({
      label: ENGINE_TYPE_LABEL[type] || type,
      options: items,
    }))
  }, [engines, enabledEngines])

  // 兜底引擎（加载失败时显示）
  const fallbackGroups = [{
    label: '默认引擎',
    options: [
      { value: 'EVAL_ENGINE', label: '通用评测引擎', description: '默认规则兜底' },
      { value: 'API_TEST', label: 'API 测试引擎', description: 'HTTP 接口自动化' },
      { value: 'HALLUCINATION_TEST', label: '幻觉检测', description: 'TruthfulQA 基准' },
    ],
  }]

  const engineGroups = groupedEngines.length > 0 ? groupedEngines : fallbackGroups

  // ===== 执行 =====
  const handleRun = async () => {
    if (!projectId) return message.warning('请先选择被测项目')

    if (mode === 'GENERATE') {
      if (!prompt.trim()) return message.warning('请输入业务功能描述或选择快捷模板')
    } else {
      if (selectedCaseIds.length === 0) return message.warning('请至少选择 1 条已有用例')
    }

    setLoading(true)
    setResult(null)
    setActiveStep(1)

    try {
      const payload = { project_id: projectId, engine }
      if (mode === 'GENERATE') {
        payload.prompt = prompt.trim()
      } else {
        payload.use_existing_cases = true
        payload.case_ids = selectedCaseIds
      }

      setActiveStep(2)
      const d = await http.post('/ai/automation', payload)
      setActiveStep(4)
      setResult(d)

      if (d.status === 'SUCCESS') {
        setActiveStep(5)
        message.success('✅ AI 自动化执行成功')
      } else if (d.status === 'FAILED') {
        message.error(`❌ 执行失败：${d.error_msg || d.summary || '引擎执行异常'}`)
      } else {
        message.info(`ℹ️ 执行完成，状态：${d.status}`)
      }
    } catch (e) {
      setActiveStep(3)
      message.error(`⚠️ ${e?.message || '执行失败'}（当前为规则兜底模式，未接入真实 LLM）`)
    } finally {
      setLoading(false)
    }
  }

  // ===== 已有用例列表列定义 =====
  const caseColumns = [{
    title: '选择',
    key: 'check',
    width: 50,
    render: (_, r) => (
      <Checkbox
        checked={selectedCaseIds.includes(r.id)}
        onChange={(e) => {
          if (e.target.checked) {
            setSelectedCaseIds((prev) => [...prev, r.id])
          } else {
            setSelectedCaseIds((prev) => prev.filter((x) => x !== r.id))
          }
        }}
      />
    ),
  }, {
    title: '用例标题',
    dataIndex: 'title',
    ellipsis: true,
  }, {
    title: '类别',
    dataIndex: 'category',
    width: 110,
    render: (v) => <Tag color="cyan">{v}</Tag>,
  }, {
    title: '来源',
    dataIndex: 'source',
    width: 110,
    render: (v) => {
      const color = v === 'AI_GEN' ? 'purple' : v === 'DOC_IMPORT' ? 'blue' : 'default'
      return <Tag color={color}>{v === 'MANUAL' ? '手动' : v}</Tag>
    },
  }]

  return (
    <div style={{ padding: 24, maxWidth: 1080, margin: '0 auto' }}>
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
              <RobotOutlined style={{ color: '#fff', fontSize: 20 }} />
            </div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 600, letterSpacing: 1 }}>AI 自动化流水线</div>
              <Text type="secondary" style={{ fontSize: 12 }}>一键 → 生成用例 → 自动执行 → 自动报告</Text>
            </div>
            <Badge.Ribbon text="本地 Ollama + 规则兜底" color="#13c2c2" style={{ position: 'relative', top: 2, marginLeft: 8 }} />
          </Space>
        }
        extra={
          <Tooltip title="当前用例生成走规则引擎兜底（按输入描述拼接基础用例 + 断言 eq:pass）。接入 LLM 后会自动切换为智能用例生成">
            <Space size={4}>
              <ExperimentOutlined style={{ color: '#faad14' }} />
              <Text type="secondary" style={{ fontSize: 12 }}>引擎 EVAL_ENGINE 为默认兜底</Text>
            </Space>
          </Tooltip>
        }
      >
        {/* ====== 引擎加载失败告警 ====== */}
        {engineLoadError && (
          <Alert
            type="warning"
            showIcon
            icon={<AlertOutlined />}
            message="引擎列表加载失败，已使用默认 3 个引擎"
            description={engineLoadError}
            action={<Button size="small" onClick={loadEngines}>重试</Button>}
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
            action={<Button size="small" onClick={loadProjects}>重试</Button>}
            style={{ marginBottom: 12 }}
          />
        )}

        {/* ====== Pipeline Stepper ====== */}
        <div style={{
          background: 'rgba(19,194,194,0.04)',
          border: '1px solid rgba(19,194,194,0.15)',
          borderRadius: 4,
          padding: '16px 24px',
          marginBottom: 20,
        }}>
          <Steps
            current={activeStep}
            status={result?.status === 'FAILED' ? 'error' : 'process'}
            size="small"
            items={PIPELINE_STEPS.map((s, i) => ({
              title: s.title,
              icon: s.icon,
              description: loading && activeStep === i && i > 0 ? (
                <Spin size="small" />
              ) : null,
            }))}
          />
        </div>

        {/* ====== 基本信息 ====== */}
        <Row gutter={16}>
          <Col span={12}>
            <Text strong>所属项目</Text>
            <Select
              placeholder="请选择被测项目"
              style={{ width: '100%', marginTop: 6 }}
              showSearch
              value={projectId}
              options={projects}
              onChange={(v) => { setProjectId(v); setSelectedCaseIds([]) }}
              status={projectLoadError ? 'warning' : undefined}
            />
          </Col>
          <Col span={12}>
            <Text strong>测试引擎</Text>
            <Select
              style={{ width: '100%', marginTop: 6 }}
              value={engine}
              onChange={setEngine}
              status={engineLoadError ? 'warning' : undefined}
              optionLabelProp="label"
              options={engineGroups}
              optionRender={(option) => {
                const item = option.dataRef
                return (
                  <Tooltip title={item?.description || '暂无描述'} placement="right">
                    <span>
                      {option.label}
                      {item?.engine_code === engine && (
                        <Tag color="#13c2c2" style={{ marginLeft: 6, marginRight: 0 }}>当前</Tag>
                      )}
                    </span>
                  </Tooltip>
                )
              }}
            />
          </Col>
        </Row>

        <Divider style={{ marginTop: 20, marginBottom: 12 }} />

        {/* ====== 模式切换 ====== */}
        <Radio.Group
          value={mode}
          onChange={(e) => {
            // D-02：第三模式「AI 自动探测」为跳转入口（设计 §4.2），不改变本页 mode
            if (e.target.value === 'DISCOVER') { navigate('/ai/discover'); return }
            setMode(e.target.value); setResult(null); setActiveStep(0)
          }}
          buttonStyle="solid"
          style={{ marginBottom: 16 }}
        >
          <Radio.Button value="GENERATE">
            <BulbOutlined /> 输入需求 → AI 生成新用例
          </Radio.Button>
          <Radio.Button value="EXISTING" disabled={!projectId}>
            <DatabaseOutlined /> 使用已有用例集（{projectId ? cases.length : '先选项目'} 条）
          </Radio.Button>
          <Radio.Button value="DISCOVER">
            <CompassOutlined /> AI 自动探测（URL+账密）
          </Radio.Button>
        </Radio.Group>

        {/* ====== GENERATE 模式 ====== */}
        {mode === 'GENERATE' && (
          <div>
            <Text strong>业务功能描述</Text>
            <TextArea
              style={{ marginTop: 6 }}
              rows={4}
              placeholder="例如：用户使用手机号+验证码登录系统，登录后进入个人中心查看订单列表，支持分页和搜索..."
              value={prompt}
              onChange={(e) => { setPrompt(e.target.value); setActiveStep(0) }}
            />
            <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              <Tag color="#13c2c2" style={{ cursor: 'pointer', margin: 0 }}
                onClick={() => setPrompt('用户使用手机号+验证码登录系统，登录后进入个人中心查看订单列表，支持分页和搜索功能')}>
                💡 登录 + 订单
              </Tag>
              <Tag color="#1890ff" style={{ cursor: 'pointer', margin: 0 }}
                onClick={() => setPrompt('商品搜索页支持按价格区间、品类和品牌多维筛选，结果实时更新')}>
                💡 商品搜索
              </Tag>
              <Tag color="#fa8c16" style={{ cursor: 'pointer', margin: 0 }}
                onClick={() => setPrompt('购物车添加商品后，选择优惠券并提交订单，支付成功后跳转订单详情')}>
                💡 购物车下单
              </Tag>
              <Tag color="#eb2f96" style={{ cursor: 'pointer', margin: 0 }}
                onClick={() => setPrompt('AI 助手聊天页面支持多轮上下文对话，能正确引用之前对话信息并回答用户问题')}>
                💡 AI 多轮对话
              </Tag>
              <Tag color="#13c2c2" style={{ cursor: 'pointer', margin: 0 }}
                onClick={() => setPrompt('用户支付流程：创建订单 → 选择支付方式 → 调用支付网关 → 回调更新订单状态，要求幂等且超时能自动回滚')}>
                💡 支付幂等
              </Tag>
            </div>
          </div>
        )}

        {/* ====== EXISTING 模式 ====== */}
        {mode === 'EXISTING' && (
          <div style={{ marginTop: 8 }}>
            {loadingCases ? (
              <div style={{ textAlign: 'center', padding: 40 }}><Spin tip="加载项目用例..." /></div>
            ) : cases.length === 0 ? (
              <Empty description="该项目暂无测试用例，请先在「资产 → 用例库」创建" />
            ) : (
              <>
                <div style={{ marginBottom: 8 }}>
                  <Checkbox
                    checked={selectedCaseIds.length === cases.length && cases.length > 0}
                    indeterminate={selectedCaseIds.length > 0 && selectedCaseIds.length < cases.length}
                    onChange={(e) => {
                      setSelectedCaseIds(e.target.checked ? cases.map((c) => c.id) : [])
                    }}
                  >
                    全选本项目用例（{cases.length} 条）
                    <Text type="secondary" style={{ marginLeft: 12 }}>已选 {selectedCaseIds.length} 条</Text>
                  </Checkbox>
                </div>
                <Table
                  size="small"
                  rowKey="id"
                  dataSource={cases}
                  columns={caseColumns}
                  pagination={{ pageSize: 8, size: 'small' }}
                  scroll={{ y: 320 }}
                />
              </>
            )}
          </div>
        )}

        <Divider style={{ marginTop: 24, marginBottom: 12 }} />

        {/* ====== 执行按钮 ====== */}
        <div style={{ textAlign: 'center' }}>
          <Button
            type="primary"
            size="large"
            icon={<ThunderboltOutlined />}
            loading={loading}
            onClick={handleRun}
            disabled={loading}
            style={{
              height: 48, paddingLeft: 32, paddingRight: 32, fontSize: 15,
              background: loading ? undefined : 'linear-gradient(135deg, #13c2c2 0%, #08979c 100%)',
              borderColor: loading ? undefined : '#13c2c2',
              boxShadow: loading ? undefined : '0 0 20px rgba(19,194,194,0.35)',
            }}
          >
            {loading ? 'AI 正在生成用例并执行...' : '🚀 一键 AI 自动化执行'}
          </Button>
          {loading && (
            <div style={{ marginTop: 12 }}>
              <Steps
                current={activeStep}
                size="small"
                items={[
                  { title: '准备中', status: activeStep >= 1 ? 'finish' : 'wait' },
                  { title: '生成用例', status: activeStep >= 2 ? 'finish' : 'wait' },
                  { title: '引擎执行', status: activeStep >= 3 ? 'process' : 'wait' },
                  { title: '生成报告', status: activeStep >= 4 ? 'process' : 'wait' },
                ]}
              />
            </div>
          )}
        </div>

        {/* ====== 结果展示 ====== */}
        {result && !loading && (
          <div style={{ marginTop: 28 }}>
            <Alert
              type={result.status === 'SUCCESS' ? 'success' : result.status === 'FAILED' ? 'error' : 'info'}
              showIcon
              icon={result.status === 'SUCCESS' ? <CheckCircleOutlined /> : <AlertOutlined />}
              message={
                <Space size={8}>
                  <span style={{ fontSize: 15, fontWeight: 500 }}>
                    AI 自动化 {result.status === 'SUCCESS' ? '执行成功' : result.status === 'FAILED' ? '执行失败' : '执行完成'}
                  </span>
                  <Tag color="#13c2c2" style={{ marginRight: 0 }}>任务 {result.task_no}</Tag>
                </Space>
              }
              description={result.summary}
              style={{ marginBottom: 16 }}
            />

            <Row gutter={[12, 12]}>
              <Col span={6}>
                <Card size="small" bordered style={{ background: 'rgba(19,194,194,0.03)' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>任务编号</Text>
                  <div style={{ fontSize: 16, fontWeight: 600, marginTop: 4, color: '#13c2c2' }}>
                    {result.task_no}
                  </div>
                </Card>
              </Col>
              <Col span={6}>
                <Card size="small" bordered style={{ background: 'rgba(19,194,194,0.03)' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>执行引擎</Text>
                  <div style={{ fontSize: 16, fontWeight: 600, marginTop: 4 }}>
                    {engine}
                  </div>
                </Card>
              </Col>
              <Col span={6}>
                <Card size="small" bordered style={{ background: 'rgba(19,194,194,0.03)' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>任务步骤</Text>
                  <div style={{ fontSize: 16, fontWeight: 600, marginTop: 4 }}>
                    {result.step_count} 步
                  </div>
                </Card>
              </Col>
              <Col span={6}>
                <Card size="small" bordered style={{ background: 'rgba(19,194,194,0.03)' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>生成报告</Text>
                  <div style={{ fontSize: 16, fontWeight: 600, marginTop: 4, color: result.report_ids?.length > 0 ? '#13c2c2' : '#8ba3b5' }}>
                    {result.report_ids?.length > 0 ? `${result.report_ids.length} 份` : '无'}
                  </div>
                </Card>
              </Col>
            </Row>

            {result.report_ids?.length > 0 && (
              <div style={{ marginTop: 16, textAlign: 'center' }}>
                <Space size={16}>
                  <Button type="primary" onClick={() => navigate(`/tasks/${result.task_id}`)} style={{ background: '#13c2c2', borderColor: '#13c2c2' }}>
                    查看任务详情 →
                  </Button>
                  <Button onClick={() => navigate('/reports')}>查看报告中心 →</Button>
                </Space>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
