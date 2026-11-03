/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 数据加载 hooks 集合（统一 d.items || d || [] 兜底 + console.warn 错误可观测 + fetchAll 全量拉取防截断）
import { useEffect, useState, useCallback } from 'react'
import http from '../api/http'
import fetchAll from '../utils/fetchAll'

export function useModelConfigs() {
  const [list, setList] = useState([])
  const [loading, setLoading] = useState(false)
  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const d = await fetchAll(http, '/model-configs', { page_size: 200 })
      setList(d)
    } catch (e) { console.warn('[useModelConfigs]', e); setList([]) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { reload() }, [reload])
  return { list, loading, reload }
}

export function useDatasets() {
  const [list, setList] = useState([])
  const reload = useCallback(async () => {
    try {
      const d = await fetchAll(http, '/datasets', { page_size: 200 })
      setList(d)
    } catch (e) { console.warn('[useDatasets]', e); setList([]) }
  }, [])
  useEffect(() => { reload() }, [reload])
  return { list, reload }
}

export function useCases(projectId) {
  const [list, setList] = useState([])
  const reload = useCallback(async () => {
    if (!projectId) { setList([]); return }
    try {
      const d = await fetchAll(http, '/cases', { project_id: projectId, page_size: 200 })
      setList(d)
    } catch (e) { console.warn('[useCases]', e); setList([]) }
  }, [projectId])
  useEffect(() => { reload() }, [reload])
  return { list, reload }
}
