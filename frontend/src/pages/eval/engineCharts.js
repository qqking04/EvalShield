/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// §6.5.9 engineCharts.js — ECharts option 工厂（全部中文轴名/legend）
// 统一签名 buildXxxOption(data, tokens)，tokens 来自 theme.js §3.3 色板。
// 禁止在页面内联写 option（收敛维护）。
import { SEVERITY_COLOR, RAGAS_GRADE_COLOR, brandColor } from '../../theme'

const MONO = 'JetBrains Mono, Consolas, monospace'

// 公共 base 配置
const base = {
  backgroundColor: 'transparent',
  textStyle: { color: 'rgba(255,255,255,0.85)' },
  tooltip: { trigger: 'item', confine: true },
  grid: { left: 48, right: 24, top: 36, bottom: 32 },
}

const AXIS = {
  axisLine: { lineStyle: { color: '#253042' } },
  axisLabel: { color: '#8b97a7', fontFamily: MONO },
  splitLine: { lineStyle: { color: '#1a2130' } },
  nameTextStyle: { color: '#8b97a7' },
}

const SEVERITY_ORDER = ['PASS', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
const SEVERITY_CN = { PASS: '通过', LOW: '低', MEDIUM: '中', HIGH: '高', CRITICAL: '严重' }
const GRADE_CN = { EXCELLENT: '优秀', GOOD: '良好', FAIR: '一般', POOR: '较差', CRITICAL: '危险' }

// 说明文本中的裸英文枚举 → 中文（与 renderers/shared.jsx cnNote 同规则）
const NOTE_TERM_CN = [
  [/\bembedding\b/gi, '向量模型'],
  [/\bHIGH\b/g, '高'],
  [/\bMEDIUM\b/g, '中'],
  [/\bLOW\b/g, '低'],
  [/\bCRITICAL\b/g, '严重'],
  [/\bPASS\b/g, '通过'],
  [/\bFAIL(?:ED)?\b/g, '失败'],
]
const cnNote = (v) => (typeof v === 'string' ? NOTE_TERM_CN.reduce((s, [re, cn]) => s.replace(re, cn), v) : v || '')

// 拒绝率/通过率仪表：0-60 红 / 60-90 橙 / 90-100 青绿，阈值 markLine
export function gaugeOption(passRate, threshold) {
  const value = passRate == null ? 0 : Math.round(Number(passRate) * 1000) / 10
  return {
    ...base,
    series: [{
      type: 'gauge',
      min: 0,
      max: 100,
      radius: '92%',
      center: ['50%', '60%'],
      axisLine: {
        lineStyle: {
          width: 14,
          color: [[0.6, '#f5222d'], [0.9, '#faad14'], [1, brandColor]],
        },
      },
      pointer: { itemStyle: { color: brandColor } },
      axisTick: { show: false },
      splitLine: { length: 6, lineStyle: { color: 'rgba(255,255,255,0.3)', width: 1 } },
      axisLabel: { color: '#8b97a7', distance: 18, fontFamily: MONO, fontSize: 10 },
      detail: {
        valueAnimation: true,
        formatter: '{value}%',
        color: '#e6ebf0',
        fontFamily: MONO,
        fontSize: 26,
        offsetCenter: [0, '38%'],
      },
      title: { offsetCenter: [0, '68%'], color: '#8b97a7', fontSize: 12 },
      data: [{
        value,
        name: '通过率',
        ...(threshold != null
          ? { markLine: {
              symbol: 'none',
              lineStyle: { color: '#fa541c', type: 'dashed', width: 2 },
              label: { formatter: `阈值 ${Math.round(Number(threshold) * 100)}%`, color: '#fa541c', position: 'start' },
              data: [{ xAxis: Math.round(Number(threshold) * 100) }],
            } }
          : {}),
      }],
    }],
  }
}

// severity 分布横向条形图：dist 可为 {PASS:3,...} 或 items 数组
export function severityBarOption(dist) {
  let counts = dist
  if (Array.isArray(dist)) {
    counts = {}
    dist.forEach((it) => {
      const s = it.severity || it.verdict || 'PASS'
      counts[s] = (counts[s] || 0) + 1
    })
  }
  const keys = Object.keys(counts || {}).length
    ? SEVERITY_ORDER.filter((k) => counts[k] != null).concat(Object.keys(counts || {}).filter((k) => !SEVERITY_ORDER.includes(k)))
    : SEVERITY_ORDER
  return {
    ...base,
    tooltip: { ...base.tooltip, formatter: (p) => `${p.name}：${p.value} 条` },
    grid: { left: 72, right: 32, top: 24, bottom: 28 },
    xAxis: { type: 'value', name: '用例数', ...AXIS, minInterval: 1 },
    yAxis: { type: 'category', name: '严重度', inverse: true, data: keys.map((k) => SEVERITY_CN[k] || k), ...AXIS },
    series: [{
      type: 'bar',
      barMaxWidth: 18,
      label: { show: true, position: 'right', color: '#e6ebf0', fontFamily: MONO },
      data: keys.map((k) => ({
        value: counts?.[k] || 0,
        itemStyle: { color: SEVERITY_COLOR[k] || '#8c8c8c' },
      })),
    }],
  }
}

// 相似度散点：x=用例序号，y=score(0-1)，按 severity 着色，threshold 参考线
export function similarityScatter(items, threshold) {
  const arr = Array.isArray(items) ? items : []
  const points = arr.map((it, idx) => ({
    value: [idx + 1, it.score == null ? null : Number(it.score)],
    itemStyle: { color: SEVERITY_COLOR[it.severity] || SEVERITY_COLOR.PASS },
    prompt: (it.prompt || it.question || '').slice(0, 40),
    note: cnNote(it.note || ''),
  })).filter((p) => p.value[1] != null)
  return {
    ...base,
    tooltip: {
      ...base.tooltip,
      formatter: (p) => `#${p.value[0]} 得分 ${p.value[1].toFixed(3)}<br/>${p.prompt ? `${p.prompt}…<br/>` : ''}${p.data.note || ''}`,
    },
    xAxis: { type: 'value', name: '用例序号', minInterval: 1, ...AXIS },
    yAxis: { type: 'value', name: '相似度得分', min: 0, max: 1, ...AXIS },
    series: [{
      type: 'scatter',
      symbolSize: 10,
      data: points,
      ...(threshold != null
        ? { markLine: {
            symbol: 'none',
            lineStyle: { color: '#fa541c', type: 'dashed' },
            label: { formatter: `阈值 ${threshold}`, color: '#fa541c' },
            data: [{ yAxis: Number(threshold) }],
          } }
        : {}),
    }],
  }
}

// 三层分数堆叠柱（rule/semantic/behavior，权重 0.4/0.3/0.3 展示 combined）
export function stackScoreOption(items) {
  const arr = Array.isArray(items) ? items : []
  const cats = arr.map((it) => it.item_no || it.no || '')
  const pick = (it, k) => {
    const s = it.scores || {}
    return s[k] == null ? 0 : Number(s[k])
  }
  const series = [
    { key: 'rule', name: '规则层', color: brandColor, weight: 0.4 },
    { key: 'semantic', name: '语义层', color: '#faad14', weight: 0.3 },
    { key: 'behavior', name: '行为层', color: '#fa541c', weight: 0.3 },
  ].map((s) => ({
    type: 'bar',
    name: s.name,
    stack: 'combined',
    barMaxWidth: 22,
    itemStyle: { color: s.color },
    data: arr.map((it) => Math.round(pick(it, s.key) * s.weight * 1000) / 1000),
  }))
  return {
    ...base,
    legend: { data: ['规则层', '语义层', '行为层'], textStyle: { color: '#8b97a7' }, top: 4 },
    tooltip: {
      ...base.tooltip,
      formatter: (p) => {
        const it = arr[p.dataIndex] || {}
        const s = it.scores || {}
        return `${p.name}<br/>规则 ${s.rule ?? '-'} / 语义 ${s.semantic ?? '-'} / 行为 ${s.behavior ?? '-'}<br/>综合 ${s.combined ?? '-'}`
      },
    },
    grid: { left: 48, right: 24, top: 40, bottom: 48 },
    xAxis: { type: 'category', name: '用例', data: cats, ...AXIS, axisLabel: { ...AXIS.axisLabel, rotate: 30 } },
    yAxis: { type: 'value', name: '加权分数', max: 1, ...AXIS },
    series,
  }
}

// RAGAS 三指标雷达 + 阈值圈（虚线 polygon）
export function ragasRadar(breakdown, threshold) {
  const b = breakdown || {}
  const v = (k) => (b[k]?.value == null ? 0 : Math.round(Number(b[k].value) * 100))
  const t = threshold == null ? null : Math.round(Number(threshold) * 100)
  return {
    ...base,
    tooltip: { ...base.tooltip },
    legend: { data: ['指标得分', '阈值'], textStyle: { color: '#8b97a7' }, top: 4 },
    radar: {
      indicator: [
        { name: '忠实度', max: 100 },
        { name: '答案相关性', max: 100 },
        { name: '上下文召回', max: 100 },
      ],
      radius: '62%',
      center: ['50%', '58%'],
      axisName: { color: '#8b97a7' },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: '#253042' } },
      splitLine: { lineStyle: { color: '#253042' } },
    },
    series: [{
      type: 'radar',
      data: [
        {
          name: '指标得分',
          value: [v('faithfulness'), v('answer_relevance'), v('context_recall')],
          areaStyle: { opacity: 0.3, color: brandColor },
          lineStyle: { color: brandColor },
          itemStyle: { color: brandColor },
        },
        ...(t != null
          ? [{
              name: '阈值',
              value: [t, t, t],
              symbol: 'none',
              lineStyle: { color: '#fa541c', type: 'dashed', width: 1.5 },
              areaStyle: { opacity: 0 },
              itemStyle: { color: 'transparent' },
            }]
          : []),
      ],
    }],
  }
}

// grade 环形图：dist = {EXCELLENT:2, GOOD:5, ...}
export function gradeDonut(dist) {
  const d = dist || {}
  const data = Object.keys(GRADE_CN)
    .filter((k) => d[k] != null && d[k] > 0)
    .map((k) => ({ name: GRADE_CN[k], value: d[k], itemStyle: { color: RAGAS_GRADE_COLOR[k] } }))
  return {
    ...base,
    tooltip: { ...base.tooltip, formatter: '{b}：{c} 条（{d}%）' },
    legend: { bottom: 0, textStyle: { color: '#8b97a7' } },
    series: [{
      type: 'pie',
      radius: ['45%', '68%'],
      center: ['50%', '46%'],
      avoidLabelOverlap: true,
      label: { color: '#8b97a7', formatter: '{b}\n{c}' },
      labelLine: { lineStyle: { color: '#253042' } },
      data,
    }],
  }
}

// 合规得分热力条（heatmap 单行，0 红 → 1 绿）
export function complianceHeat(items) {
  const arr = Array.isArray(items) ? items : []
  const cats = arr.map((it, idx) => it.item_no || it.no || `#${idx + 1}`)
  const data = arr.map((it, idx) => [idx, 0, it.compliance_score == null ? 0 : Number(it.compliance_score)])
  return {
    ...base,
    tooltip: { ...base.tooltip, formatter: (p) => `${cats[p.value[0]]} 合规分 ${Number(p.value[2]).toFixed(2)}` },
    grid: { left: 48, right: 24, top: 30, bottom: 56 },
    xAxis: { type: 'category', data: cats, ...AXIS, axisLabel: { ...AXIS.axisLabel, rotate: 45 } },
    yAxis: { type: 'category', data: ['合规分'], ...AXIS },
    visualMap: {
      min: 0,
      max: 1,
      calculable: false,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemWidth: 10,
      textStyle: { color: '#8b97a7' },
      inRange: { color: ['#f5222d', '#faad14', '#52c41a'] },
    },
    series: [{
      type: 'heatmap',
      data,
      label: { show: arr.length <= 20, color: '#0a0d12', fontFamily: MONO, formatter: (p) => Number(p.value[2]).toFixed(2) },
      itemStyle: { borderColor: '#0a0d12', borderWidth: 2 },
    }],
  }
}
