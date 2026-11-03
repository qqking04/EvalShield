/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 覆盖率热力图：模块 × 测试类型矩阵，直观展示覆盖盲区
// COV-P3：优先使用后端 payload.coverage_targets 的计数加权口径（维度分 = min(实际/目标, 1)），
// 行集合取 canonical_modules 全集（P0 归一后 API/UI 资产同键）；旧任务 payload 无该字段时回退布尔口径。
import { useMemo } from 'react'
import { Table, Tag, Tooltip } from 'antd'
import { C } from './consoleTheme'

const DIMS = [
  { key: 'functional', label: '功能', color: C.cyan },
  { key: 'ui', label: 'UI', color: '#722ed1' },
  { key: 'performance', label: '性能', color: '#fa8c16' },
  { key: 'security', label: '安全', color: '#f5222d' },
  { key: 'dataflow', label: '数据流', color: '#1890ff' },
  { key: 'compat', label: '兼容', color: '#52c41a' },
]

const CELL_STYLES = {
  covered: { background: 'rgba(19,194,194,0.25)', color: C.cyan, border: `1px solid ${C.cyan}` },
  partial: { background: 'rgba(255,214,102,0.15)', color: C.amber, border: `1px solid ${C.amber}` },
  missing: { background: 'rgba(255,77,79,0.08)', color: '#5c3a3a', border: '1px solid #3d2222' },
}

// 旧口径回退：布尔聚合（payload 无 coverage_targets 时）
function buildBooleanRows(cases, datasets, scenarios) {
  const m = {}
  for (const c of cases) {
    const mod = c.module || '未分类'
    if (!m[mod]) m[mod] = { functional: false, ui: false, performance: false, security: false, dataflow: false, compat: false }
    const cat = (c.category || '').toUpperCase()
    if (cat === 'API') m[mod].functional = true
    else if (cat === 'UI') m[mod].ui = true
    else if (cat === 'PERFORMANCE') m[mod].performance = true
    else if (cat === 'SECURITY' || cat === 'REDTEAM') m[mod].security = true
    else if (cat === 'DATAFLOW') m[mod].dataflow = true
    if (c.browser_config) m[mod].compat = true
  }
  for (const ds of datasets) { if (m[ds.module || '未分类']) m[ds.module || '未分类'].functional = true }
  for (const sc of scenarios) { if (m[sc.module || '未分类']) m[sc.module || '未分类'].dataflow = true }
  return m
}

export default function DiscoverCoverageHeatmap({ cases, datasets, scenarios, coverageTargets, canonicalModules, moduleAliases }) {
  // 菜单别名展示：规范模块 → 并入的菜单文本列表
  const aliasByModule = useMemo(() => {
    const map = {}
    for (const c of cases) {
      if (c.menu_text) {
        const mod = c.module || '未分类'
        if (!map[mod]) map[mod] = new Set()
        map[mod].add(c.menu_text)
      }
    }
    return map
  }, [cases])

  const useWeighted = coverageTargets && Object.keys(coverageTargets).length > 0

  const rows = useMemo(() => {
    if (!useWeighted) {
      const m = buildBooleanRows(cases, datasets, scenarios)
      return Object.entries(m).map(([mod, dims]) => {
        const covered = Object.values(dims).filter(Boolean).length
        return { module: mod, dims, scores: null, coverage: Math.round((covered / 6) * 100) }
      })
    }
    // 行集合：canonical 模块全集 + targets 中出现的其它模块（未归一的菜单真实盲区）
    // COV-P5：全局伪模块（如「安全评审」）不进入 coverage_targets，天然被剔除
    const mods = Array.from(new Set([...(canonicalModules || []), ...Object.keys(coverageTargets)]))
    return mods.filter((mod) => coverageTargets[mod]).map((mod) => {
      const t = coverageTargets[mod]
      const counts = t.counts || {}
      const targets = t.targets || {}
      const applicable = t.applicable || {}
      const dims = {}
      const scores = {}
      let sum = 0
      let denom = 0
      for (const d of DIMS) {
        const n = counts[d.key] || 0
        const target = targets[d.key] || 1
        const applies = applicable[d.key] !== false
        dims[d.key] = n > 0
        scores[d.key] = { n, target, score: Math.min(n / target, 1), applies }
        if (applies) {
          sum += Math.min(n / target, 1)
          denom += 1
        }
      }
      return { module: mod, dims, scores, coverage: denom ? Math.round((sum / denom) * 100) : 100 }
    })
  }, [cases, datasets, scenarios, coverageTargets, canonicalModules, useWeighted])

  const columns = [
    {
      title: '模块',
      dataIndex: 'module',
      width: 150,
      render: (m) => {
        const aliases = aliasByModule[m] ? Array.from(aliasByModule[m]) : []
        const tag = <Tag color="cyan">{m}</Tag>
        return aliases.length ? (
          <Tooltip title={`并入菜单：${aliases.join('、')}`}>{tag}</Tooltip>
        ) : tag
      },
    },
    ...DIMS.map((dim) => ({
      title: dim.label,
      dataIndex: dim.key,
      width: 78,
      align: 'center',
      render: (_has, row) => {
        const s = row.scores ? row.scores[dim.key] : null
        const has = s ? s.n > 0 : row.dims[dim.key]
        // COV-P5：不适用维度（纯 API 模块的 UI/兼容）渲染灰色 N/A，不计入分母
        if (s && s.applies === false && s.n === 0) {
          return (
            <Tooltip title={`${dim.label}：该模块无前端页面，维度不适用`}>
              <span
                style={{
                  display: 'inline-block', minWidth: 34, height: 22, lineHeight: '20px',
                  borderRadius: 4, fontSize: 11, fontWeight: 600, textAlign: 'center',
                  padding: '0 4px', color: '#4a5568', border: '1px solid #2d3748',
                }}
              >
                N/A
              </span>
            </Tooltip>
          )
        }
        let style = has ? CELL_STYLES.covered : CELL_STYLES.missing
        let label = has ? '✓' : '—'
        let tip = has ? `已覆盖 ${dim.label}测试` : `缺少${dim.label}测试`
        if (s) {
          if (s.n > 0 && s.score < 1) {
            style = CELL_STYLES.partial
            label = `${s.n}/${s.target}`
            tip = `${dim.label}：${s.n} 条，目标 ${s.target} 条（未达量）`
          } else if (s.n > 0) {
            label = `✓${s.n}`
            tip = `${dim.label}：${s.n} 条，已达目标 ${s.target} 条`
          } else {
            tip = `缺少${dim.label}测试（0/${s.target}）`
          }
        }
        return (
          <Tooltip title={tip}>
            <span
              style={{
                ...style,
                display: 'inline-block',
                minWidth: 34,
                height: 22,
                lineHeight: '20px',
                borderRadius: 4,
                fontSize: 12,
                fontWeight: 700,
                textAlign: 'center',
                padding: '0 4px',
              }}
            >
              {label}
            </span>
          </Tooltip>
        )
      },
    })),
    {
      title: '覆盖率',
      dataIndex: 'coverage',
      width: 100,
      render: (pct) => (
        <span
          style={{
            color: pct >= 80 ? C.green : pct >= 50 ? C.amber : C.red,
            fontWeight: 700,
            fontSize: 14,
          }}
        >
          {pct}%
        </span>
      ),
    },
  ]

  const dataSource = rows

  return (
    <div>
      <div style={{ marginBottom: 12, display: 'flex', gap: 16, fontSize: 12, flexWrap: 'wrap' }}>
        <span>
          <span style={{ ...CELL_STYLES.covered, display: 'inline-block', width: 14, height: 14, borderRadius: 3, marginRight: 4, verticalAlign: 'middle' }} />
          已覆盖（达目标量）
        </span>
        {useWeighted && (
          <span>
            <span style={{ ...CELL_STYLES.partial, display: 'inline-block', width: 14, height: 14, borderRadius: 3, marginRight: 4, verticalAlign: 'middle' }} />
            未达量（n/目标）
          </span>
        )}
        <span>
          <span style={{ ...CELL_STYLES.missing, display: 'inline-block', width: 14, height: 14, borderRadius: 3, marginRight: 4, verticalAlign: 'middle' }} />
          未覆盖
        </span>
        {useWeighted && (
          <span>
            <span style={{ display: 'inline-block', minWidth: 14, height: 14, borderRadius: 3, marginRight: 4, verticalAlign: 'middle', color: '#4a5568', fontSize: 10 }}>N/A</span>
            不适用（无前端页面）
          </span>
        )}
        {useWeighted && (
          <span style={{ color: C.dim, marginLeft: 'auto' }}>
            口径：维度分 = min(用例数/目标数, 1)，覆盖率 = 适用维度均分；模块行含全部规范模块
          </span>
        )}
      </div>
      <Table
        size="small"
        rowKey="module"
        columns={columns}
        dataSource={dataSource}
        pagination={false}
        locale={{ emptyText: <span style={{ color: C.dim }}>暂无数据</span> }}
      />
    </div>
  )
}
