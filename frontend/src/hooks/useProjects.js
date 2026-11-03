/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// useProjects: 跨页面复用的项目列表 hook
// 提供 projects + loading + reload + findById 四大能力
// 避免每个页面都写 http.get('/projects?page_size=200') + d.items || [] 重复代码
import { useEffect, useState, useCallback } from 'react'
import http from '../api/http'
import fetchAll from '../utils/fetchAll'

export default function useProjects() {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const d = await fetchAll(http, '/projects', { page_size: 200 })
      setProjects(d)
    } catch (e) {
      console.warn('[useProjects] fail', e?.message || e)
      setProjects([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { reload() }, [reload])

  const findById = useCallback((id) => projects.find((p) => p.id === id), [projects])

  return { projects, loading, reload, findById }
}
