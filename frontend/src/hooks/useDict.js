/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useState } from 'react'
import http from '../api/http'

// 全局字典缓存 + 30s TTL
const cache = {}

export default function useDict(dictCode, { autoRefresh = false } = {}) {
  const [items, setItems] = useState(
    cache[dictCode]?.items ?? []
  )
  const [loading, setLoading] = useState(cache[dictCode] ? false : true)

  useEffect(() => {
    const now = Date.now()
    const cached = cache[dictCode]
    if (cached && !autoRefresh && now - cached.ts < 30000) {
      setItems(cached.items)
      return
    }
    let cancelled = false
    setLoading(true)
    http.get('/dicts', { params: { dict_code: dictCode } })
      .then(r => {
        if (cancelled) return
        const list = r?.data ?? r ?? []
        // 兼容后端返回：[{value,label,sort}] 或 [{item_value,item_label}]
        const normalized = list.map(x => ({
          value: x.value ?? x.item_value,
          label: x.label ?? x.item_label,
          sort: x.sort ?? x.sort_order ?? 0,
        })).sort((a, b) => (a.sort || 0) - (b.sort || 0))
        cache[dictCode] = { items: normalized, ts: now }
        setItems(normalized)
      })
      .catch(() => {
        if (cancelled) return
        // 字典拉不到（接口异常）——静默降级返回空，不要弹红色错误
        setItems(cached?.items ?? [])
      })
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [dictCode, autoRefresh])

  return { items, loading, refresh: () => { delete cache[dictCode] } }
}
