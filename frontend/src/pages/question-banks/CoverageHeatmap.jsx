/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useMemo, useState } from 'react'
import { Button, Space, Typography, Empty, Spin } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import echartsDarkTheme, { tealSequential } from '../../theme/echarts'
import { exportCoverage } from '../../api/questionBanks'
import tokens from '../../theme/tokens'

// ES9-P-09（§4.1.3）：覆盖热力图 —— 行 = TC260 类别，列 = 引擎。
// 色带用 theme/echarts.js 的 tealSequential；缺口格以 danger 红 12% 底显示 ∅；
// hover Tooltip 给出类别/引擎/可执行覆盖题量。
export default function CoverageHeatmap({ coverage, loading, bankId, onRefresh }) {
  const [exporting, setExporting] = useState(false)

  const { categories, engines, cells, maxValue } = useMemo(() => {
    const list = coverage?.cells || []
    const cats = []
    const engs = []
    list.forEach((c) => {
      if (!cats.includes(c.category)) cats.push(c.category)
      if (!engs.includes(c.engine_code)) engs.push(c.engine_code)
    })
    const gapSet = new Set()
    ;(coverage?.gaps || []).forEach((g) => {
      ;(g.missing_engines || []).forEach((e) => gapSet.add(`${g.category}||${e}`))
    })
    const data = []
    let max = 0
    list.forEach((c) => {
      const x = engs.indexOf(c.engine_code)
      const y = cats.indexOf(c.category)
      if (x < 0 || y < 0) return
      max = Math.max(max, c.count || 0)
      data.push({ value: [x, y, c.count || 0], itemStyle: { borderWidth: 1, borderColor: tokens.border } })
    })
    // 缺口格：cells 未覆盖且 gaps 标缺的组合补 ∅ 格
    cats.forEach((cat, y) => {
      engs.forEach((eng, x) => {
        const covered = list.some((c) => c.category === cat && c.engine_code === eng)
        if (!covered && gapSet.has(`${cat}||${eng}`)) {
          data.push({
            value: [x, y, 0],
            __gap: true,
            label: { show: true, formatter: '∅', color: tokens.danger, fontSize: 12 },
            itemStyle: { color: 'rgba(255,77,79,0.12)', borderWidth: 1, borderColor: tokens.border },
          })
        }
      })
    })
    return { categories: cats, engines: engs, cells: data, maxValue: max }
  }, [coverage])

  const option = useMemo(() => {
    if (!categories.length || !engines.length) return null
    return {
      ...echartsDarkTheme,
      tooltip: {
        ...echartsDarkTheme.tooltip,
        formatter: (p) => {
          const cat = categories[p.value[1]]
          const eng = engines[p.value[0]]
          const isGap = p.data?.__gap
          return `${cat}<br/>引擎：${eng}<br/>${isGap ? '<span style="color:#ff4d4f">缺口：该引擎无可执行覆盖</span>' : `可执行覆盖 ${p.value[2]} 题`}`
        },
      },
      grid: { left: 160, right: 24, top: 12, bottom: 64, borderColor: tokens.border },
      xAxis: {
        type: 'category',
        data: engines,
        axisLabel: { color: tokens.text2, rotate: 30, fontSize: 11 },
        axisLine: { lineStyle: { color: tokens.border } },
        splitArea: { show: false },
      },
      yAxis: {
        type: 'category',
        data: categories,
        axisLabel: { color: tokens.text2, fontSize: 11 },
        axisLine: { lineStyle: { color: tokens.border } },
        splitArea: { show: false },
      },
      visualMap: {
        min: 0,
        max: Math.max(1, maxValue),
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 4,
        inRange: { color: tealSequential },
        textStyle: { color: tokens.text2 },
      },
      series: [
        {
          type: 'heatmap',
          data: cells,
          label: { show: true, color: tokens.text1, fontSize: 10, formatter: (p) => (p.data?.__gap ? '∅' : p.value[2] > 0 ? p.value[2] : '') },
          emphasis: { itemStyle: { shadowBlur: 6, shadowColor: 'rgba(19,194,194,0.4)' } },
        },
      ],
    }
  }, [categories, engines, cells, maxValue])

  const handleExport = async () => {
    if (!bankId) return
    setExporting(true)
    try {
      await exportCoverage(bankId)
    } catch {
      /* 拦截器已提示 */
    } finally {
      setExporting(false)
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin />
      </div>
    )
  }
  if (!option) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <Typography.Text style={{ color: tokens.text2 }}>
            暂无覆盖数据 —— 先在「题目列表」导入题库，或等待覆盖矩阵计算完成
          </Typography.Text>
        }
      >
        <Button onClick={() => onRefresh && onRefresh()}>刷新覆盖</Button>
      </Empty>
    )
  }
  return (
    <div data-testid="coverage-heatmap">
      <Space style={{ marginBottom: 8, width: '100%', justifyContent: 'space-between' }}>
        <Typography.Text style={{ color: tokens.text3, fontSize: 12 }}>
          行 = TC260 风险类别 · 列 = 评测引擎 · ∅ = 缺口（红底）
        </Typography.Text>
        <Button size="small" icon={<DownloadOutlined />} loading={exporting} onClick={handleExport}>
          导出缺口清单 CSV
        </Button>
      </Space>
      <ReactECharts
        option={option}
        theme="dark"
        style={{ height: Math.max(320, categories.length * 30 + 120) }}
        notMerge
        lazyUpdate
      />
    </div>
  )
}
