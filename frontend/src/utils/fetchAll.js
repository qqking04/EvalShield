/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// -*- coding: utf-8 -*-
/** 全量分页加载：循环翻页直到 total 拉满，返回完整 items 数组。
 *
 * 用法：
 *   import fetchAll from '@/utils/fetchAll'
 *   const all = await fetchAll(http, '/cases', { project_id: 1, severity: 'P0' })
 *
 * 约定（与 http.js 拦截器对齐）：
 *   http 拦截器已把 {code,message,data} 解包为 body.data，
 *   所以 fetchAll 内部拿到的 resp 直接是 {items, total, ...}。
 */

const MAX_PAGE_SIZE = 500

export default async function fetchAll(http, url, baseParams = {}) {
  const pageSize = Math.min(Number(baseParams.page_size) || MAX_PAGE_SIZE, MAX_PAGE_SIZE)
  const paramsNoPage = { ...baseParams }
  delete paramsNoPage.page
  delete paramsNoPage.page_size

  const all = []
  let page = 1
  let total = Infinity

  while (all.length < total) {
    try {
      const resp = await http.get(url, {
        params: { ...paramsNoPage, page, page_size: pageSize },
      })
      const items = resp?.items || []
      total = resp?.total ?? items.length
      all.push(...items)
      // 最后一页不足 page_size，或 total 为 0
      if (items.length === 0 || items.length < pageSize) break
      page += 1
      // 防止异常死循环（后端 total 算错时）
      if (page > 1000) {
        console.warn('[fetchAll] page 超过 1000 强制停止', url)
        break
      }
    } catch (e) {
      console.warn('[fetchAll] 循环翻页中断，返回已拉取部分:', url, e?.message || e)
      break
    }
  }
  return all
}
