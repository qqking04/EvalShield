/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// §6.5.1-§6.5.8 reportRenderers.jsx — 引擎报告渲染器聚合入口 + 分发器
// 数据契约（§3.2/§5）：item_results 归一化为 {no, prompt, verdict, score, detail}，
// detail 为各引擎原始 item 的 JSON（MULTI_TURN 为会话 trace）。
// U8-2 拆分：EthicsReport 与各渲染器共用工具迁至 ./renderers/，
// 本文件保留其余引擎渲染器，并以 REPORT_RENDERERS 注册表统一分发（未知类型走 GenericItemTable 默认渲染）。
import { useState } from 'react'
import {
  Table, Tag, Space, Card, Alert, Empty, Typography, Tooltip, Progress, Drawer, Row, Col,
  Steps, Timeline,
} from 'antd'
import { SafetyCertificateOutlined, AlertOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { SEVERITY_COLOR, RAGAS_GRADE_COLOR, MONO_FONT, brandColor } from '../../theme'
import { THREAT_TYPES } from '../../components/cases/caseSchemas'
import {
  gaugeOption, severityBarOption, similarityScatter, stackScoreOption, ragasRadar, gradeDonut,
} from './engineCharts'
import { mergeItems, parseDetail, verdictTag, severityTag, mono, cnNote } from './renderers/shared'
import { RunBanner, GenericItemTable } from './renderers/generic'
import { EthicsReport } from './renderers/ethics'

// 共享工具 re-export（保持既有对外契约）
export { RunBanner, GenericItemTable, EthicsReport }

// ---------- §6.5.3 RedteamReport（红队矩阵） ----------
const REDTEAM_THREAT_CN = {
  direct_jailbreak: '直接越狱', roleplay_escape: '角色扮演逃逸', prompt_injection: '提示注入',
  harmful_content: '有害内容', data_leakage: '数据泄露', indirect_injection: '间接注入',
  instruction_hierarchy: '指令层级', suffix_attack: '后缀攻击',
  // 引擎模板与评测集用例中实际出现的其余威胁键（缺失会回退显示英文）
  ignore_previous: '忽略指令覆盖', roleplay_scientist: '专家角色扮演', roleplay_historian: '学者角色扮演',
  discrimination: '歧视内容', violence: '暴力内容',
  system_prompt_extraction: '系统提示词提取', pii_extraction: '个人信息提取',
  encoding_obfuscation: '编码混淆', multi_turn_injection: '多轮注入', harmful_request: '有害请求',
  custom: '自定义用例',
}

export function RedteamReport({ items = [], summary = {} }) {
  const rows = mergeItems(items)
  if (!rows.length) {
    return <Empty description="任务来源运行未回填明细，请重新执行引擎" />
  }
  // 任务自动创建的运行（TASK_AUTO）统计嵌在 summary.task_summary；平台发起的走顶层 summary
  const stats = summary.task_summary || summary
  const threats = [...new Set(rows.map((r) => r.threat).filter(Boolean))]
  const matrixColumns = [
    { title: '用例', dataIndex: 'item_no', width: 110, render: (v, _, i) => v || rows[i].no || `#${i + 1}` },
    ...threats.map((t) => ({
      title: REDTEAM_THREAT_CN[t] || t,
      align: 'center',
      width: 110,
      render: (_, r) => (r.threat !== t ? <span style={{ color: '#33415580' }}>·</span>
        : r.verdict === 'PASS'
          ? <SafetyCertificateOutlined style={{ color: SEVERITY_COLOR.PASS, fontSize: 18 }} />
          : <AlertOutlined style={{ color: SEVERITY_COLOR.CRITICAL, fontSize: 18 }} />),
    })),
    { title: '判定', dataIndex: 'verdict', width: 90, render: verdictTag },
    { title: '说明', dataIndex: 'note', ellipsis: true, render: (v) => cnNote(v) },
  ]
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Row gutter={12}>
        <Col span={10}>
          <Card size="small" title="拒绝率仪表">
            <ReactECharts option={gaugeOption(stats.pass_rate, stats.threshold)} style={{ height: 260 }} notMerge lazyUpdate />
          </Card>
        </Col>
        <Col span={14}>
          <Card size="small" title="威胁覆盖矩阵">
            <Table
              rowKey={(_, idx) => idx}
              size="small"
              columns={matrixColumns}
              dataSource={rows}
              pagination={{ pageSize: 8, showSizeChanger: false }}
              scroll={{ x: 'max-content' }}
            />
          </Card>
        </Col>
      </Row>
      <Card size="small" title="攻击明细">
        <Table
          rowKey={(_, idx) => idx}
          size="small"
          dataSource={rows}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          expandable={{
            expandedRowRender: (r) => (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Typography.Text type="secondary">模型输出（截断 2000 字）：</Typography.Text>
                <Typography.Paragraph
                  style={{ ...mono, fontSize: 12, whiteSpace: 'pre-wrap', maxHeight: 240, overflowY: 'auto', margin: 0, padding: 8, background: '#0f141b', borderRadius: 4, border: `1px solid ${r.partial_leak ? SEVERITY_COLOR.CRITICAL : '#253042'}` }}
                >
                  {r.model_output || '（空）'}
                </Typography.Paragraph>
                <Space wrap size={8}>
                  {r.note && <Tag color={r.verdict === 'PASS' ? 'green' : 'red'}>{r.note}</Tag>}
                  {r.judge_refused != null && <Tag>Judge 判定拒绝：{String(r.judge_refused)}</Tag>}
                  {r.partial_leak && <Tag color="red">部分泄漏</Tag>}
                  {(r.note || '').includes('规则降级') && <Tag color="orange">规则降级</Tag>}
                </Space>
              </Space>
            ),
          }}
          columns={[
            { title: '编号', dataIndex: 'item_no', width: 110, render: (v, _, i) => v || `#${i + 1}` },
            { title: '威胁类型', dataIndex: 'threat', width: 130, render: (v) => REDTEAM_THREAT_CN[v] || v || '-' },
            { title: '攻击提示词', dataIndex: 'prompt', ellipsis: true },
            { title: '拒绝', dataIndex: 'refused', width: 80, render: (v) => (v ? <Tag color="green">是</Tag> : <Tag color="red">否</Tag>) },
            { title: '判定', dataIndex: 'verdict', width: 90, render: verdictTag },
          ]}
        />
      </Card>
    </Space>
  )
}

// ---------- §6.5.4 HallucinationReport（相似度分布） ----------
export function HallucinationReport({ items = [], summary = {} }) {
  const rows = mergeItems(items)
  // TASK_AUTO 运行的统计嵌在 summary.task_summary（同 RedteamReport）
  const stats = summary.task_summary || summary
  const [drawerRow, setDrawerRow] = useState(null)
  const dist = {}
  rows.forEach((r) => { const s = r.severity || r.verdict || 'PASS'; dist[s] = (dist[s] || 0) + 1 })
  const columns = [
    { title: '编号', dataIndex: 'item_no', width: 100, render: (v, _, i) => v || `#${i + 1}` },
    { title: '提示词', dataIndex: 'prompt', ellipsis: true },
    { title: '得分', dataIndex: 'score', width: 140, render: (v) => (v == null ? '-' : <Progress percent={Math.round(v * 100)} size="small" />) },
    { title: '严重度', dataIndex: 'severity', width: 110, render: severityTag },
    { title: '判定', dataIndex: 'verdict', width: 90, render: verdictTag },
    {
      title: '说明', dataIndex: 'note', ellipsis: true,
      render: (v) => (
        <Space size={4}>
          <span>{cnNote(v)}</span>
          {(v || '').includes('规则降级') && <Tag color="orange">规则降级</Tag>}
          {(v || '').includes('embedding 降级') && <Tag color="gold">向量降级</Tag>}
        </Space>
      ),
    },
  ]
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {stats.embedding_degraded === true && (
        <Alert type="warning" showIcon message="向量模型不可用，本次为词面降级结果，分数仅供参考" />
      )}
      <Row gutter={12}>
        <Col span={12}>
          <Card size="small" title="严重度分布">
            <ReactECharts option={severityBarOption(dist)} style={{ height: 260 }} notMerge lazyUpdate />
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="相似度散点（按严重度着色）">
            <ReactECharts option={similarityScatter(rows, stats.threshold)} style={{ height: 260 }} notMerge lazyUpdate />
          </Card>
        </Col>
      </Row>
      <Card size="small" title="幻觉判定明细">
        <Table
          rowKey={(_, idx) => idx}
          size="small"
          columns={columns}
          dataSource={rows}
          onRow={(r) => ({ onClick: () => setDrawerRow(r), style: { cursor: 'pointer' } })}
          pagination={{ pageSize: 10, showSizeChanger: false }}
        />
      </Card>
      <Drawer title={drawerRow ? `题项 ${drawerRow.item_no || ''} 详情` : '题项详情'} width={620} open={!!drawerRow} onClose={() => setDrawerRow(null)}>
        {drawerRow && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Card size="small" title="提示词全文">
              <Typography.Paragraph style={{ ...mono, fontSize: 12, whiteSpace: 'pre-wrap', margin: 0 }}>{drawerRow.prompt || '-'}</Typography.Paragraph>
            </Card>
            <Card size="small" title={`参考答案（${(drawerRow.references || []).length} 条）`}>
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {(drawerRow.references || []).map((ref, i) => {
                  const best = drawerRow.best_reference && String(ref) === String(drawerRow.best_reference)
                  return (
                    <div
                      key={i}
                      style={{
                        padding: 8,
                        borderRadius: 4,
                        background: '#0f141b',
                        fontSize: 12,
                        fontFamily: MONO_FONT,
                        border: best ? `1px solid ${brandColor}` : '1px solid #253042',
                      }}
                    >
                      {best && <Tag color="cyan">最优命中</Tag>}
                      {String(ref)}
                    </div>
                  )
                })}
                {!drawerRow.references?.length && drawerRow.best_reference && (
                  <Typography.Paragraph style={{ ...mono, fontSize: 12 }}>{drawerRow.best_reference}</Typography.Paragraph>
                )}
              </Space>
            </Card>
            {drawerRow.note && <Alert type="info" showIcon message={cnNote(drawerRow.note)} />}
          </Space>
        )}
      </Drawer>
    </Space>
  )
}

// ---------- §6.5.6 InjectionReport（三层分数） ----------
const THREAT_CN = Object.fromEntries(THREAT_TYPES.map((t) => [t.value, t.label]))

const VECTOR_TAG = (v) =>
  v === 'DIRECT' ? <Tag color="volcano">直接注入</Tag>
    : v === 'INDIRECT' ? <Tag color="geekblue">间接注入</Tag>
    : '-'

export function InjectionReport({ items = [], summary = {} }) {
  const rows = mergeItems(items)
  const columns = [
    { title: '编号', dataIndex: 'item_no', width: 100, render: (v, _, i) => v || `#${i + 1}` },
    { title: '注入向量', dataIndex: 'injection_vector', width: 100, render: (v) => VECTOR_TAG(v) },
    { title: '威胁类型', dataIndex: 'threat_type', width: 130, render: (v) => THREAT_CN[v] || v || '-' },
    { title: '规则分', width: 80, render: (_, r) => <span style={mono}>{(r.scores?.rule ?? '-').toString()}</span> },
    { title: '语义分', width: 80, render: (_, r) => <span style={mono}>{(r.scores?.semantic ?? '-').toString()}</span> },
    { title: '行为分', width: 80, render: (_, r) => <span style={mono}>{(r.scores?.behavior ?? '-').toString()}</span> },
    { title: '综合', width: 80, render: (_, r) => <span style={{ ...mono, fontWeight: 600 }}>{(r.scores?.combined ?? '-').toString()}</span> },
    { title: '严重度', dataIndex: 'severity', width: 100, render: severityTag },
    { title: '判定', dataIndex: 'verdict', width: 90, render: verdictTag },
    {
      title: '探测状态', width: 120,
      render: (_, r) => {
        const p = r.probe || {}
        return p.up
          ? <Space size={4}><span style={{ width: 8, height: 8, borderRadius: 4, background: SEVERITY_COLOR.PASS, display: 'inline-block' }} />真实探测</Space>
          : (
            <Tooltip title={p.note || '无 target 配置，行为层为模拟降级结果'}>
              <Space size={4} style={{ cursor: 'help' }}><span style={{ width: 8, height: 8, borderRadius: 4, background: '#8c8c8c', display: 'inline-block' }} />降级模拟（无 target）</Space>
            </Tooltip>
          )
      },
    },
    {
      title: '泄漏标记', width: 100,
      render: (_, r) => (r.probe_leaked ? <Tag color="red">凭据泄漏</Tag> : '-'),
    },
  ]
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {(summary.direct_risk != null || summary.indirect_risk != null) && (
        <Space size={8}>
          <Tag color="volcano">直接注入风险 {summary.direct_risk ?? 0}</Tag>
          <Tag color="geekblue">间接注入风险 {summary.indirect_risk ?? 0}</Tag>
        </Space>
      )}
      <Card size="small" title="三层分数堆叠柱（规则 0.4 / 语义 0.3 / 行为 0.3 → 综合）">
        <ReactECharts option={stackScoreOption(rows)} style={{ height: 280 }} notMerge lazyUpdate />
      </Card>
      <Card size="small" title="注入攻击明细">
        <Table
          rowKey={(_, idx) => idx}
          size="small"
          columns={columns}
          dataSource={rows}
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          expandable={{
            expandedRowRender: (r) => (
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>探测输出（前 500 字）{r.probe?.status_code != null ? ` ｜ HTTP ${r.probe.status_code}` : ''}：</Typography.Text>
                <div style={{ ...mono, fontSize: 12, whiteSpace: 'pre-wrap', maxHeight: 200, overflowY: 'auto', padding: 8, background: '#0f141b', borderRadius: 4, border: '1px solid #253042' }}>
                  {String(r.probe?.output || '（无输出）').slice(0, 500)}
                </div>
              </Space>
            ),
          }}
        />
      </Card>
    </Space>
  )
}

// ---------- §6.5.7 RagReport（RAGAS 三指标） ----------
const METHOD_TAG = { cosine: { color: 'cyan', text: 'cosine' }, nli_llm: { color: 'blue', text: 'nli_llm' }, llm_fallback: { color: 'orange', text: 'llm_fallback（降级）' } }
const NLI_VERDICT_COLOR = { SUPPORTED: 'green', NOT_SUPPORTED: 'red', NOT_APPLICABLE: 'default' }
const NLI_VERDICT_CN = { SUPPORTED: '有据支持', NOT_SUPPORTED: '无据支持', NOT_APPLICABLE: '不适用' }

export function RagReport({ items = [], summary = {}, ragas }) {
  const rows = mergeItems(items)
  const r = ragas || summary?.ragas || rows.find((x) => x.ragas)?.ragas || {}
  const breakdown = r.breakdown || {}
  const gradeColor = RAGAS_GRADE_COLOR[r.grade] || '#8c8c8c'
  const methodTag = (m) => (m ? <Tag {...(METHOD_TAG[m] || { color: 'default', text: m })} style={{ fontSize: 11 }} /> : null)
  const metricCard = (label, m) => (
    <Card size="small" style={{ position: 'relative' }}>
      <Typography.Text type="secondary">{label}</Typography.Text>
      <div style={{ ...mono, fontSize: 24, fontWeight: 700, color: brandColor }}>{m?.value != null ? Number(m.value).toFixed(2) : '-'}</div>
      {m?.rationale && <Typography.Text type="secondary" style={{ fontSize: 11 }}>{m.rationale}</Typography.Text>}
      <div style={{ position: 'absolute', right: 8, bottom: 8 }}>{methodTag(m?.method)}</div>
    </Card>
  )
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Row gutter={12} align="middle">
        <Col span={6}>
          <Card size="small">
            <div style={{ ...mono, fontSize: 34, fontWeight: 700, color: gradeColor }}>{r.score != null ? Number(r.score).toFixed(2) : '-'}</div>
            <Tag style={{ background: gradeColor, color: '#0a0d12', fontWeight: 600, border: 'none' }}>{r.grade || 'N/A'}</Tag>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>RAGAS 总分</Typography.Text>
          </Card>
        </Col>
        <Col span={10}>
          <Card size="small" title="RAGAS 三指标雷达（虚线为阈值圈）">
            <ReactECharts option={ragasRadar(breakdown, summary.threshold)} style={{ height: 240 }} notMerge lazyUpdate />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" title="等级分布">
            <ReactECharts option={gradeDonut(summary.grade_distribution)} style={{ height: 240 }} notMerge lazyUpdate />
          </Card>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={8}>{metricCard('忠实度 Faithfulness', breakdown.faithfulness)}</Col>
        <Col span={8}>{metricCard('答案相关性 Answer Relevance', breakdown.answer_relevance)}</Col>
        <Col span={8}>{metricCard('上下文召回 Context Recall', breakdown.context_recall)}</Col>
      </Row>
      <Card size="small" title="RAG 用例明细">
        <Table
          rowKey={(_, idx) => idx}
          size="small"
          dataSource={rows}
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          expandable={{
            expandedRowRender: (rec) => (
              <Table
                rowKey={(_, i) => i}
                size="small"
                pagination={false}
                dataSource={rec.judgments || []}
                locale={{ emptyText: '该用例无 NLI 判定明细' }}
                columns={[
                  { title: '原文句子', dataIndex: 'statement', ellipsis: true },
                  { title: '判定', dataIndex: 'verdict', width: 140, render: (v) => <Tag color={NLI_VERDICT_COLOR[v] || 'default'}>{NLI_VERDICT_CN[v] || v}</Tag> },
                  { title: '证据', dataIndex: 'evidence', ellipsis: true },
                ]}
              />
            ),
          }}
          columns={[
            { title: '编号', dataIndex: 'item_no', width: 100, render: (v, _, i) => v || `#${i + 1}` },
            { title: '问题', dataIndex: 'prompt', ellipsis: true },
            { title: 'RAGAS 分', dataIndex: ['ragas', 'score'], width: 100, render: (v) => (v == null ? '-' : <span style={mono}>{Number(v).toFixed(2)}</span>) },
            {
              title: '等级', dataIndex: ['ragas', 'grade'], width: 100,
              render: (v) => (v ? <Tag style={{ background: RAGAS_GRADE_COLOR[v] || '#8c8c8c', color: '#0a0d12', fontWeight: 600, border: 'none' }}>{v}</Tag> : '-'),
            },
            { title: '忠实度', width: 90, render: (_, rec) => <span style={mono}>{rec.faithfulness?.value ?? '-'}</span> },
            { title: '相关性', width: 90, render: (_, rec) => <span style={mono}>{rec.answer_relevance?.value ?? '-'}</span> },
            { title: '召回', width: 90, render: (_, rec) => <span style={mono}>{rec.context_recall?.value ?? '-'}</span> },
          ]}
        />
      </Card>
    </Space>
  )
}

// ---------- §6.5.8 MultiTurnReport（对话时间线） ----------
const MT_STATES = ['INIT', 'CONVERSING', 'CONTRADICTED', 'RESOLVED', 'TERMINATED']
const MT_STATUS_COLOR = { CONSISTENT: 'green', CONTRADICTED: 'red', DRIFT: 'orange' }

export function MultiTurnReport({ items = [], summary = {} }) {
  const rows = mergeItems(items)
  const sessions = rows.map((r) => {
    let trace = r.trace
    if (!Array.isArray(trace)) {
      const d = parseDetail(r)
      trace = Array.isArray(d) ? d : (d?.trace || [])
    }
    return { ...r, trace }
  })
  if (!sessions.length || sessions.every((s) => !s.trace || s.trace.length === 0)) {
    // trace 缺失 → GenericItemTable 兜底
    return <GenericItemTable items={items} overall={summary?.overall_score} />
  }
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {sessions.map((s, idx) => {
        const stateIdx = MT_STATES.indexOf(s.state_end)
        return (
          <Card
            key={idx}
            size="small"
            title={(
              <Space wrap size={8}>
                <span>{s.topic || s.session_no || `会话 #${idx + 1}`}</span>
                <Tag color={MT_STATUS_COLOR[s.status] || 'default'}>{s.status || '-'}</Tag>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>一致性 <span style={mono}>{s.consistency_score != null ? Number(s.consistency_score).toFixed(2) : '-'}</span></Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>矛盾 <span style={mono}>{s.contradiction_count ?? 0}</span></Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>漂移 <span style={mono}>{s.context_drift_score != null ? Number(s.context_drift_score).toFixed(2) : '-'}</span></Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>轮次 <span style={mono}>{s.rounds_executed ?? (s.trace || []).length}</span></Typography.Text>
              </Space>
            )}
          >
            <Steps
              size="small"
              current={stateIdx < 0 ? 0 : stateIdx}
              status={s.status === 'CONTRADICTED' ? 'error' : 'process'}
              items={MT_STATES.map((st) => ({ title: st }))}
              style={{ marginBottom: 16 }}
            />
            <Timeline
              items={(s.trace || []).flatMap((t) => {
                const contradiction = t.verdict === 'CONTRADICTED' || t.verdict === 'CONTRADICTION' || t.verdict === 'FAIL'
                return [
                  {
                    color: 'gray',
                    children: <div style={{ fontSize: 12 }}><Tag>用户</Tag><span style={{ ...mono, fontSize: 12 }}>{`第${t.round ?? ''}轮 `}</span>{t.user}</div>,
                  },
                  {
                    color: contradiction ? 'red' : brandColor,
                    children: (
                      <div style={contradiction ? { borderLeft: `3px solid ${SEVERITY_COLOR.CRITICAL}`, paddingLeft: 8 } : undefined}>
                        <Space size={6} wrap>
                          <Tag color="cyan">助手</Tag>
                          {t.state && <Tag>{t.state}</Tag>}
                          {t.verdict && verdictTag(t.verdict)}
                        </Space>
                        <div style={{ fontSize: 12, margin: '2px 0' }}>{t.assistant}</div>
                        {contradiction && t.reason && <div style={{ color: SEVERITY_COLOR.CRITICAL, fontSize: 12 }}>矛盾：{t.reason}</div>}
                      </div>
                    ),
                  },
                ]
              })}
            />
          </Card>
        )
      })}
    </Space>
  )
}

// ---------- §6.5.1 分发器（注册表模式） ----------
// engine_code → 渲染器组件；未知类型（含 engine_code 为空的历史数据）走 default 兜底。
export const REPORT_RENDERERS = {
  REDTEAM_TEST: RedteamReport,
  HALLUCINATION_TEST: HallucinationReport,
  ETHICS_TEST: EthicsReport,
  PROMPT_INJECTION: InjectionReport,
  RAG_TEST: RagReport,
  MULTI_TURN_TEST: MultiTurnReport,
  default: GenericItemTable,
}

export function EngineReportView({ run }) {
  const items = run?.item_results || []
  const summary = run?.summary || {}
  const Renderer = REPORT_RENDERERS[run?.engine_code] || REPORT_RENDERERS.default
  if (Renderer === GenericItemTable) return <GenericItemTable items={items} overall={run?.overall_score} />
  return <Renderer items={items} summary={summary} ragas={run?.ragas} />
}
