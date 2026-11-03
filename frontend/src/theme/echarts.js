/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import tokens from './tokens'

// 统一 ECharts 暗色主题配置
export const echartsDarkTheme = {
  backgroundColor: 'transparent',
  textStyle: {
    color: tokens.text1,
  },
  title: {
    textStyle: { color: tokens.text1 },
    subtextStyle: { color: tokens.text2 },
  },
  legend: {
    textStyle: { color: tokens.text2 },
  },
  tooltip: {
    backgroundColor: '#161d26',
    borderColor: '#1f2833',
    borderWidth: 1,
    textStyle: { color: '#e6f7ff' },
  },
  grid: {
    borderColor: tokens.border,
  },
  color: ['#13c2c2', '#faad14', '#ff4d4f', '#52c41a', '#8ba3b5', '#722ed1'],
  xAxis: {
    axisLine: { lineStyle: { color: tokens.border } },
    axisLabel: { color: tokens.text2 },
    splitLine: { lineStyle: { color: tokens.border } },
  },
  yAxis: {
    axisLine: { lineStyle: { color: tokens.border } },
    axisLabel: { color: tokens.text2 },
    splitLine: { lineStyle: { color: tokens.border } },
  },
  radar: {
    axisLine: { lineStyle: { color: tokens.border } },
    splitLine: { lineStyle: { color: tokens.border } },
    splitArea: { show: false },
    axisName: { color: tokens.text2 },
  },
  pie: {
    label: { color: tokens.text2 },
  },
}

// ES9-P-09：覆盖热力图专用 teal 顺序色带（页面底色 → 主色 → 高亮），
// 缺口格另行以 danger 红 12% 底 + ∅ 符号渲染，不进入色带。
export const tealSequential = ['#0b0f14', '#13c2c2', '#7ff7f7']

export default echartsDarkTheme
