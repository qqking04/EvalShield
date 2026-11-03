/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// vitest 全局初始化：jest-dom 断言 + antd 所需的浏览器 API 垫片
import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

if (!window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

if (!window.URL.createObjectURL) {
  window.URL.createObjectURL = vi.fn(() => 'blob:mock')
  window.URL.revokeObjectURL = vi.fn()
}

// jsdom 无真实布局，antd 响应式组件依赖 ResizeObserver
if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

// jsdom 无 IntersectionObserver（ES9 UAT 详情目录高亮依赖）
if (!window.IntersectionObserver) {
  window.IntersectionObserver = class {
    constructor() {}
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return []
    }
  }
}

// ES8-BUG-005：jsdom 对 getComputedStyle(elt, pseudoElt)（伪元素第二参数）
// 抛 "Not implemented"，rc-table/Drawer 滚动条测量路径触发大量 stderr 噪音。
// 兜底 shim：带伪元素参数时退化为无伪元素调用（jsdom 本就无样式级联精度承诺）。
const _origGetComputedStyle = window.getComputedStyle.bind(window)
window.getComputedStyle = (elt, pseudoElt) => {
  if (pseudoElt !== undefined && pseudoElt !== null) {
    try {
      return _origGetComputedStyle(elt)
    } catch {
      return new CSSStyleDeclaration()
    }
  }
  return _origGetComputedStyle(elt)
}
