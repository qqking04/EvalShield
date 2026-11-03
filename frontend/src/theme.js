/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { theme } from 'antd'

// 工业深色风格主题：青色主色 + 深蓝灰底
export const themeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: '#13c2c2',
    colorBgBase: '#0a0d12',
    colorBgLayout: '#0a0d12',
    colorBgContainer: '#141923',
    colorBgElevated: '#1a2130',
    colorTextBase: '#e6ebf0',
    colorTextSecondary: '#8b97a7',
    // UI-623a：三级/说明文本统一提亮，#869BAA on #0a0d12 ≈ 7.4:1（WCAG AA 达标）
    colorTextTertiary: '#869BAA',
    colorTextDescription: '#869BAA',
    colorBorder: '#253042',
    colorSuccess: '#22c55e',
    colorWarning: '#f59e0b',
    colorError: '#ef4444',
    colorInfo: '#13c2c2',
    borderRadius: 6,
    fontSize: 14,
    fontFamily:
      '-apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  },
  components: {
    Layout: {
      headerBg: '#141923',
      headerHeight: 56,
      siderBg: '#0d1118',
      triggerBg: '#0d1118',
      bodyBg: '#0a0d12',
    },
    Menu: {
      darkItemBg: '#0d1118',
      darkSubMenuItemBg: '#0a0d12',
      darkItemSelectedBg: '#13c2c2',
      // UI-623a：选中菜单青底上白字对比度 2.21，改用深色文字（同 primary 按钮策略）
      darkItemSelectedColor: '#0b0f14',
      darkItemHoverBg: '#1a2130',
    },
    // UI-623b：link/danger 按钮文字色派生自 #ef4444 暗色板（实测 #ce3d3d 对比度 3.65），
    // 组件级提亮至 #ff6b6b（on 行底 ≈ 6.9:1），不波及全局 error 色板
    Button: { controlHeight: 32, primaryColor: '#0b0f14', colorError: '#ff6b6b' },
    Table: {
      headerBg: '#1a2130',
      headerColor: '#c8d1de',
      rowHoverBg: '#1e2736',
    },
    Card: {
      headerBg: '#141923',
    },
    Modal: {
      contentBg: '#141923',
      headerBg: '#141923',
    },
    Select: { controlHeight: 32 },
    Input: { controlHeight: 32 },
    InputNumber: { controlHeight: 32 },
    InputTextArea: { controlHeight: 32 },
  },
}

export const brandColor = '#13c2c2'

// §3.3 严重度/判定色板（供 6 个报告渲染器共用，禁止散落硬编码）
export const SEVERITY_COLOR = {
  PASS: '#52c41a', LOW: '#8db600', MEDIUM: '#faad14',
  HIGH: '#fa541c', CRITICAL: '#f5222d', NONE: '#8c8c8c',
  MINOR: '#8db600', MODERATE: '#faad14', MAJOR: '#fa541c',
}
export const VERDICT_COLOR = { PASS: 'green', RISK: 'red', FAIL: 'red', WARN: 'orange', SKIP: 'default', SAFE: 'green', BYPASSED: 'red', ATTEMPTED: 'orange', LEAK: 'red' }
export const RAGAS_GRADE_COLOR = { EXCELLENT: '#52c41a', GOOD: '#13c2c2', FAIR: '#faad14', POOR: '#fa541c', CRITICAL: '#f5222d' }

// 数字统一等宽字体（仪表盘读数质感）
export const MONO_FONT = 'JetBrains Mono, Consolas, monospace'
