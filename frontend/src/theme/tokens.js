/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 工业暗色 Shield Teal 主题令牌
export const tokens = {
  bgPage: '#0b0f14',
  bgPanel: '#11161d',
  bgHover: '#161d26',
  border: '#1f2833',
  primary: '#13c2c2',
  primaryDim: 'rgba(19,194,194,0.12)',
  success: '#52c41a',
  warning: '#faad14',
  danger: '#ff4d4f',
  text1: '#e6f7ff',
  text2: '#8ba3b5',
  // UI-623a：#5a6c7d 对比度 3.59 < 4.5，提亮为 #869BAA（on bgPage/bgPanel ≥ 6:1）
  text3: '#869BAA',
}

export const themeTokens = {
  token: {
    colorPrimary: tokens.primary,
    colorBgBase: tokens.bgPage,
    colorBgContainer: tokens.bgPanel,
    colorBgLayout: tokens.bgPage,
    colorBorder: tokens.border,
    colorText: tokens.text1,
    colorTextSecondary: tokens.text2,
    borderRadius: 2,
    fontFamily:
      '"HarmonyOS Sans SC","PingFang SC","Microsoft YaHei",sans-serif',
  },
  components: {
    Button: { borderRadius: 2 },
    Card: { borderRadiusLG: 4, colorBorderSecondary: tokens.border },
    Table: { rowHoverBg: tokens.bgHover, borderColor: tokens.border },
    Modal: { contentBg: tokens.bgPanel, headerBg: tokens.bgPanel },
    Input: { colorBgContainer: tokens.bgPanel, colorBorder: tokens.border },
    Select: { colorBgContainer: tokens.bgPanel, colorBorder: tokens.border },
    Tag: { borderRadiusSM: 2 },
  },
}

export default tokens
