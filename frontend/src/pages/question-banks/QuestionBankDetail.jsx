/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Card,
  Empty,
  Spin,
  Tabs,
  Table,
  Tag,
  Space,
  Typography,
  Button,
  Input,
  Select,
  Modal,
  Form,
  Popover,
  Popconfirm,
  Descriptions,
  message,
} from 'antd'
import { ArrowLeftOutlined, PlusOutlined, UploadOutlined, EditOutlined, DeleteOutlined, PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import * as api from '../../api/questionBanks'
import CoverageHeatmap from './CoverageHeatmap'
import ImportWizard from './ImportWizard'
import EvalRunLaunchModal from '../../components/EvalRunLaunchModal'
import tokens from '../../theme/tokens'
import { ES } from '../es11/gate'

// ES9-P-09：题库详情页（/question-banks/:id）——
// Tabs[题目列表 | 覆盖热力图 | 导入记录]；questions 表格行高 40、split Tag、文本截断+Popover、行编辑删除。

const SPLIT_META = {
  REFUSE: { color: 'red', label: 'REFUSE' },
  ANSWER: { color: 'green', label: 'ANSWER' },
  ATTACK: { color: 'orange', label: 'ATTACK' },
}

function QuestionsTab({ bankId }) {
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(false)
  const [query, setQuery] = useState({ page: 1, page_size: 20, split: undefined, keyword: undefined })
  const [edit, setEdit] = useState(null) // null | {mode:'create'} | {mode:'edit',record}
  const [form] = Form.useForm()

  const load = useCallback(() => {
    setLoading(true)
    api
      .listQuestions(bankId, query)
      .then((resp) => {
        const items = Array.isArray(resp) ? resp : resp?.items || []
        setData({ items, total: resp?.total ?? items.length })
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [bankId, query])

  useEffect(load, [load])

  const openEdit = (record) => {
    setEdit(record ? { mode: 'edit', record } : { mode: 'create' })
    form.setFieldsValue(
      record
        ? { ...record, tags: Array.isArray(record.tags) ? record.tags.join(',') : (record.tags ?? '') }
        : { split: 'REFUSE', language: 'zh', category: '', sub_category: '', attack_vector: '', text: '', expected_behavior: '', expected_answer: '', source: '', tags: '' },
    )
  }

  const save = async () => {
    const values = await form.validateFields()
    // 后端契约 tags: list[str]（QuestionCreate.tags）——表单逗号串需拆回数组，
    // 空串必须转 []，否则 pydantic 422（E2E-13：UI 新增/编辑题目必失败）
    if (typeof values.tags === 'string') {
      values.tags = values.tags.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
    } else if (values.tags == null) {
      values.tags = []
    }
    if (edit.mode === 'edit') {
      await api.updateQuestion(edit.record.id, values)
      message.success('题目已更新')
    } else {
      await api.createQuestion(bankId, values)
      message.success('题目已新增（重复内容将返回 ES-QB-DUP）')
    }
    setEdit(null)
    load()
  }

  const columns = [
    {
      title: '内容',
      dataIndex: 'text',
      key: 'text',
      ellipsis: true,
      render: (v) => (
        <Popover content={<div style={{ maxWidth: 480, whiteSpace: 'pre-wrap' }}>{v}</div>} trigger="hover">
          <Typography.Text ellipsis style={{ maxWidth: 420, color: tokens.text1 }}>
            {v}
          </Typography.Text>
        </Popover>
      ),
    },
    {
      title: '子集',
      dataIndex: 'split',
      key: 'split',
      width: 96,
      render: (v) => {
        const m = SPLIT_META[v] || { color: 'default', label: v }
        return <Tag color={m.color}>{m.label}</Tag>
      },
    },
    { title: '类别', dataIndex: 'category', key: 'category', width: 140, ellipsis: true },
    { title: '攻击向量', dataIndex: 'attack_vector', key: 'attack_vector', width: 140, ellipsis: true },
    { title: '来源', dataIndex: 'source', key: 'source', width: 110, ellipsis: true },
    {
      title: '操作',
      key: 'ops',
      width: 110,
      render: (_, record) => (
        <Space size={4}>
          <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          <Popconfirm
            title="删除该题？"
            onConfirm={async () => {
              await api.deleteQuestion(record.id)
              message.success('已删除')
              load()
            }}
          >
            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Space style={{ marginBottom: 12, flexWrap: 'wrap' }}>
        <Input.Search
          allowClear
          placeholder="搜索题目文本"
          style={{ width: 220 }}
          onSearch={(v) => setQuery((q) => ({ ...q, keyword: v || undefined, page: 1 }))}
        />
        <Select
          allowClear
          placeholder="子集"
          style={{ width: 130 }}
          value={query.split}
          onChange={(v) => setQuery((q) => ({ ...q, split: v, page: 1 }))}
          options={Object.keys(SPLIT_META).map((k) => ({ value: k, label: k }))}
        />
        <Button icon={<PlusOutlined />} type="primary" onClick={() => openEdit(null)}>
          新增题目
        </Button>
      </Space>
      <Table
        rowKey="id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={data.items}
        pagination={{
          current: query.page,
          pageSize: query.page_size,
          total: data.total,
          showSizeChanger: false,
          onChange: (p) => setQuery((q) => ({ ...q, page: p })),
        }}
        onRow={() => ({ style: { height: 40 } })}
        locale={{
          emptyText: (
            <Typography.Text style={{ color: tokens.text2 }}>
              暂无题目 —— 点「新增题目」单条录入，或到「导入记录」Tab 批量上传 CSV/JSONL
            </Typography.Text>
          ),
        }}
      />
      <Modal
        title={edit?.mode === 'edit' ? '编辑题目' : '新增题目'}
        open={!!edit}
        onOk={save}
        onCancel={() => setEdit(null)}
        destroyOnClose
        width={640}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="text" label="题目文本" rules={[{ required: true, message: '必填' }]}>
            <Input.TextArea rows={3} maxLength={4000} showCount />
          </Form.Item>
          <Space.Compact block>
            <Form.Item name="category" label="类别" rules={[{ required: true, message: '必填' }]} style={{ flex: 1, marginRight: 8 }}>
              <Input maxLength={64} placeholder="TC260 类别" />
            </Form.Item>
            <Form.Item name="sub_category" label="子类" style={{ flex: 1, marginRight: 8 }}>
              <Input maxLength={64} />
            </Form.Item>
            <Form.Item name="split" label="子集" rules={[{ required: true }]} style={{ width: 130 }}>
              <Select options={Object.keys(SPLIT_META).map((k) => ({ value: k, label: k }))} />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="attack_vector" label="攻击向量" style={{ flex: 1, marginRight: 8 }}>
              <Input maxLength={64} />
            </Form.Item>
            <Form.Item name="language" label="语言" style={{ width: 110 }}>
              <Select options={[{ value: 'zh' }, { value: 'en' }]} />
            </Form.Item>
            <Form.Item name="source" label="来源" style={{ flex: 1, marginLeft: 8 }}>
              <Input maxLength={128} />
            </Form.Item>
          </Space.Compact>
          {/* 后端契约为枚举（REFUSE/ANSWER/SAFE_REFUSE，question_banks.py _norm_split_behavior），
              自由文本必 422 ES-QB-013 —— 改枚举下拉，留空由后端按子集推导 */}
          <Form.Item name="expected_behavior" label="期望行为" extra="留空则按子集自动推导：REFUSE→REFUSE、ANSWER→ANSWER、ATTACK→SAFE_REFUSE">
            <Select
              allowClear
              placeholder="选择枚举（或留空）"
              options={[
                { value: 'REFUSE', label: 'REFUSE — 应拒绝' },
                { value: 'ANSWER', label: 'ANSWER — 应作答' },
                { value: 'SAFE_REFUSE', label: 'SAFE_REFUSE — 安全拒答' },
              ]}
            />
          </Form.Item>
          <Form.Item name="expected_answer" label="期望答案">
            <Input.TextArea rows={2} maxLength={2000} />
          </Form.Item>
          <Form.Item name="tags" label="标签">
            <Input maxLength={255} placeholder="逗号分隔" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

function ImportsTab() {
  // 后端契约仅提供 POST /imports + GET /question-imports/:job（无历史列表端点），
  // 本 Tab 承载入口引导与最近一次会话内作业状态。
  const [jobs, setJobs] = useState([])
  useEffect(() => {
    const fn = (e) => setJobs((prev) => [...prev, e.detail])
    window.addEventListener('es-question-import-done', fn)
    return () => window.removeEventListener('es-question-import-done', fn)
  }, [])
  return (
    <Table
      rowKey="id"
      size="middle"
      dataSource={jobs}
      columns={[
        { title: '作业', dataIndex: 'id', key: 'id', width: 90 },
        { title: '状态', dataIndex: 'status', key: 'status', width: 110, render: (v) => <Tag color={v === 'succeeded' ? 'green' : v === 'failed' ? 'red' : 'default'}>{v}</Tag> },
        { title: '导入', dataIndex: 'imported', key: 'imported', width: 90 },
        { title: '错误', dataIndex: 'errors', key: 'errors', width: 80, render: (v) => (Array.isArray(v) ? v.length : v ?? 0) },
        { title: '完成时间', dataIndex: 'done_at', key: 'done_at', width: 170, render: () => new Date().toLocaleString('zh-CN', { hour12: false }) },
      ]}
      locale={{
        emptyText: (
          <div style={{ color: tokens.text2 }}>
            本次会话暂无导入作业 —— 点右上「导入题目」上传 CSV / JSONL，进度与错误明细可在向导内查看
          </div>
        ),
      }}
    />
  )
}

// ES11-R1 治理视图（优化11.md §17.2）：回答四个问题——谁在用、样本结构、
// 资产卫生、风险挂账。数字与行均可下钻，空态给下一步动作；只读聚合，无编辑入口。
const PURPOSE_LABEL = { STANDARD: '标准评测', REGRESSION: '回归', RETEST: '复测', BASELINE: '基线', TRACE_REPLAY: '轨迹回放', MONITOR: '监控' }
const DEFECT_STATUS_META = {
  NEW: { color: 'default', label: '新建' }, OPEN: { color: 'blue', label: '待处理' },
  FIXED: { color: 'gold', label: '已整改' }, VERIFYING: { color: 'purple', label: '验证中' },
  CLOSED: { color: 'green', label: '已关闭' }, REOPENED: { color: 'red', label: '已重开' },
}
const GOV_SPLIT_META = { ...SPLIT_META, HOLDOUT: { color: 'purple', label: 'HOLDOUT' } }
const RETEST_EVENT_LABEL = { RETEST_STARTED: '复测已发起', VERIFIED: '验证已完成' }

function GovSection({ title, note, children }) {
  return (
    <div style={{ borderTop: `1px solid ${ES.line}`, paddingTop: 14, marginTop: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <Typography.Text strong style={{ color: ES.ink }}>{title}</Typography.Text>
        {note && <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>{note}</Typography.Text>}
      </div>
      {children}
    </div>
  )
}

function GovNum({ value, label, onClick }) {
  return (
    <span
      onClick={onClick}
      style={{ marginRight: 32, cursor: onClick ? 'pointer' : 'default' }}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}
    >
      <span style={{ fontFamily: ES.mono, fontSize: 20, color: ES.ink }}>{value ?? '-'}</span>
      <span style={{ color: ES.sub, fontSize: 12, marginLeft: 6 }}>{label}</span>
    </span>
  )
}

function GovernanceTab({ bankId }) {
  const navigate = useNavigate()
  const [gov, setGov] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    api
      .getGovernance(bankId)
      .then(setGov)
      .catch(() => setGov(null))
      .finally(() => setLoading(false))
  }, [bankId])

  useEffect(load, [load])

  if (loading) return <Spin style={{ display: 'block', margin: '56px auto' }} />
  if (!gov) {
    return (
      <Empty description="治理数据加载失败">
        <Button icon={<ReloadOutlined />} onClick={load}>重试</Button>
      </Empty>
    )
  }
  const { usage: u, layering: l, hygiene: h, defects: d } = gov
  const maxCat = Math.max(1, ...(l.categories || []).map((c) => c.count))

  return (
    <div>
      <GovSection title="使用与基线" note="题库是被哪些验收活动引用的长期资产">
        <div style={{ marginBottom: 10 }}>
          <GovNum value={u.total_runs} label="活动总数" />
          <GovNum value={u.baseline_runs} label="基线运行" />
          <GovNum value={u.used_as_baseline} label="被对比引用" />
        </div>
        {(u.recent || []).length === 0 ? (
          <Typography.Text style={{ color: ES.sub }}>
            本库尚未被任何活动使用 —— 点右上「用此库发起评测」完成首次验收。
          </Typography.Text>
        ) : (
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={u.recent}
            onRow={(r) => ({ onClick: () => navigate(`/eval/runs/${r.id}`), style: { cursor: 'pointer', height: 40 } })}
            columns={[
              { title: '运行编号', dataIndex: 'run_no', key: 'run_no', width: 180, render: (v) => <span style={{ fontFamily: ES.mono, color: ES.accent }}>{v}</span> },
              { title: '场景', dataIndex: 'run_purpose', key: 'run_purpose', width: 110, render: (v) => PURPOSE_LABEL[v] || v || '-' },
              { title: '状态', dataIndex: 'status', key: 'status', width: 100 },
              { title: '时间', dataIndex: 'created_at', key: 'created_at', render: (v) => (v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '-') },
            ]}
          />
        )}
      </GovSection>

      <GovSection title="分层与覆盖" note={`共 ${l.total} 题；HOLDOUT 为生产回流默认分层，不参与常规批量预览`}>
        <Space size={8} wrap style={{ marginBottom: 12 }}>
          {Object.entries(GOV_SPLIT_META).map(([k, m]) => (
            <Tag key={k} color={m.color}>{k} {l.splits?.[k] ?? 0}</Tag>
          ))}
        </Space>
        {(l.categories || []).length === 0 ? (
          <Typography.Text style={{ color: ES.sub }}>暂无类别分布 —— 到「题目列表」补全类别字段。</Typography.Text>
        ) : (
          l.categories.map((c) => (
            <div key={c.category} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
              <Typography.Text style={{ width: 180, color: ES.sub, fontSize: 12 }} ellipsis={{ tooltip: c.category }}>{c.category}</Typography.Text>
              <div style={{ flex: 1, height: 6, background: ES.line, borderRadius: 3, maxWidth: 420 }}>
                <div style={{ width: `${(c.count / maxCat) * 100}%`, height: 6, background: ES.accent, borderRadius: 3 }} />
              </div>
              <span style={{ fontFamily: ES.mono, color: ES.ink, fontSize: 12, width: 40, textAlign: 'right' }}>{c.count}</span>
            </div>
          ))
        )}
      </GovSection>

      <GovSection title="资产卫生" note="重复样本会污染通过率统计，建议尽快合并">
        <div style={{ marginBottom: 8 }}>
          <GovNum value={h.reflow_count} label="生产回流题" />
          <GovNum value={h.reflow_rate == null ? '-' : `${(h.reflow_rate * 100).toFixed(1)}%`} label="回流占比" />
        </div>
        {h.duplicate_groups > 0 ? (
          <Alert
            type="warning"
            showIcon
            message={`检测到 ${h.duplicate_groups} 组重复样本（共 ${h.duplicate_items} 题）—— 到「题目列表」按文本搜索后删除多余条目`}
          />
        ) : (
          <Typography.Text style={{ color: ES.sub }}>未发现重复样本。</Typography.Text>
        )}
      </GovSection>

      <GovSection title="关联缺陷与复测" note="来源运行使用本库的缺陷（最近 10 条）">
        {(d.items || []).length === 0 ? (
          <Typography.Text style={{ color: ES.sub }}>
            本库尚无关联缺陷 —— 在运行工作台「题级证据」将失败项转缺陷后，这里会自动出现。
          </Typography.Text>
        ) : (
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={d.items}
            onRow={(r) => ({ onClick: () => navigate(`/defects/${r.id}`), style: { cursor: 'pointer', height: 40 } })}
            columns={[
              { title: '缺陷编号', dataIndex: 'defect_no', key: 'defect_no', width: 170, render: (v) => <span style={{ fontFamily: ES.mono, color: ES.accent }}>{v}</span> },
              { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
              { title: '等级', dataIndex: 'severity', key: 'severity', width: 70, render: (v) => <Tag color={v === 'P0' || v === 'P1' ? 'red' : 'default'}>{v}</Tag> },
              {
                title: '状态', dataIndex: 'status', key: 'status', width: 90,
                render: (v) => {
                  const m = DEFECT_STATUS_META[v] || { color: 'default', label: v }
                  return <Tag color={m.color}>{m.label}</Tag>
                },
              },
              {
                title: '最近复测', dataIndex: 'last_retest_event', key: 'last_retest_event', width: 160,
                render: (v, r) => (v ? `${RETEST_EVENT_LABEL[v] || v} ${r.last_retest_at ? new Date(r.last_retest_at).toLocaleString('zh-CN', { hour12: false }) : ''}` : '未发起复测'),
              },
            ]}
          />
        )}
        {d.open_p0p1 > 0 && (
          <Alert style={{ marginTop: 10 }} type="error" showIcon
            message={`本库关联缺陷中有 ${d.open_p0p1} 个 P0/P1 未闭环，将阻塞引用这些运行的交付门禁（G3/G4）`}
          />
        )}
      </GovSection>
    </div>
  )
}

export default function QuestionBankDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [bank, setBank] = useState(null)
  const [coverage, setCoverage] = useState(null)
  const [covLoading, setCovLoading] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [launchOpen, setLaunchOpen] = useState(false)

  const loadBank = useCallback(() => {
    api.getBank(id).then(setBank).catch(() => {})
  }, [id])

  const loadCoverage = useCallback(() => {
    setCovLoading(true)
    api
      .getCoverage(id)
      .then(setCoverage)
      .catch(() => {})
      .finally(() => setCovLoading(false))
  }, [id])

  useEffect(loadBank, [loadBank])

  const gapCount = (coverage?.gaps || []).length

  return (
    <div>
      <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} type="text" onClick={() => navigate('/question-banks')} />
          <Typography.Title level={4} style={{ margin: 0 }}>
            {bank?.name || '题库详情'}
          </Typography.Title>
          {bank?.is_builtin && <Tag color="cyan">内置</Tag>}
        </Space>
        <Space>
          <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => setLaunchOpen(true)}>
            用此库发起评测
          </Button>
          <Button type="primary" icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>
            导入题目
          </Button>
        </Space>
      </Space>
      {bank && (
        <Descriptions size="small" column={4} style={{ marginBottom: 8 }}>
          <Descriptions.Item label="题量">{bank.question_count ?? 0}</Descriptions.Item>
          <Descriptions.Item label="REFUSE">
            <Tag color="red">{bank.stats?.split?.REFUSE ?? '-'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="ANSWER">
            <Tag color="green">{bank.stats?.split?.ANSWER ?? '-'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="ATTACK">
            <Tag color="orange">{bank.stats?.split?.ATTACK ?? '-'}</Tag>
          </Descriptions.Item>
        </Descriptions>
      )}
      <Card styles={{ body: { paddingTop: 0 } }}>
        <Tabs
          defaultActiveKey="questions"
          onChange={(k) => k === 'coverage' && !coverage && loadCoverage()}
          items={[
            { key: 'questions', label: '题目列表', children: <QuestionsTab bankId={id} /> },
            {
              key: 'coverage',
              label: `覆盖热力图${gapCount ? `（缺口 ${gapCount}）` : ''}`,
              children: <CoverageHeatmap coverage={coverage} loading={covLoading} bankId={id} onRefresh={loadCoverage} />,
            },
            { key: 'governance', label: '治理视图', children: <GovernanceTab bankId={id} /> },
            { key: 'imports', label: '导入记录', children: <ImportsTab /> },
          ]}
        />
      </Card>
      <ImportWizard
        open={importOpen}
        bankId={id}
        onClose={() => setImportOpen(false)}
        onDone={() => {
          loadBank()
          if (coverage) loadCoverage()
        }}
      />

      {bank && (
        <EvalRunLaunchModal
          open={launchOpen}
          onClose={() => setLaunchOpen(false)}
          initialQuestionBank={{ id: bank.id, name: bank.name, question_count: bank.question_count ?? 0 }}
        />
      )}
    </div>
  )
}
