/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

// 版本契约消费层（方案 §2-B8）：GET /api/edition 免登录探测，全局共享。
// 拉取失败按最保守降级：edition=null / commercial=false / enabled_engines=[]，
// 消费方在 edition=null 前不得裁剪能力（见 RequirePerm / Tasks 引擎下拉的判定）。
const EDITION_TTL_MS = 5 * 60 * 1000

const CONSERVATIVE = Object.freeze({
  edition: null,
  commercial: false,
  enabled_engines: [],
  limits: {},
  license: null,
  platform: null,
})

const EditionContext = createContext({
  ...CONSERVATIVE,
  loaded: false,
  refresh: async () => {},
})

async function fetchEditionInfo() {
  const resp = await fetch('/api/edition', { method: 'GET', headers: { Accept: 'application/json' } })
  if (!resp.ok) throw new Error(`edition probe failed: HTTP ${resp.status}`)
  const body = await resp.json()
  const data = body && typeof body === 'object' && 'code' in body ? body.data : body
  if (!data || typeof data !== 'object') throw new Error('edition probe malformed payload')
  return {
    edition: typeof data.edition === 'string' ? data.edition : null,
    commercial: data.commercial === true,
    enabled_engines: Array.isArray(data.enabled_engines) ? data.enabled_engines : [],
    limits: data.limits && typeof data.limits === 'object' ? data.limits : {},
    license: data.license ?? null,
    platform: data.platform ?? null, // 优化7 T6：平台运营区门控（仅 saas）
  }
}

export function EditionProvider({ children }) {
  const [info, setInfo] = useState(CONSERVATIVE)
  const [loaded, setLoaded] = useState(false)
  const fetchedAtRef = useRef(0)
  const inflightRef = useRef(null)

  const refresh = useCallback(async () => {
    // 5 分钟 TTL + 并发去重：多消费方同时 miss 时共享一次请求
    if (inflightRef.current) return inflightRef.current
    const task = fetchEditionInfo()
      .then((data) => {
        setInfo(data)
        fetchedAtRef.current = Date.now()
        return data
      })
      .catch(() => {
        // 失败保持最保守默认值，不弹错、不重试风暴
        setInfo(CONSERVATIVE)
        fetchedAtRef.current = 0
        return CONSERVATIVE
      })
      .finally(() => {
        inflightRef.current = null
        setLoaded(true)
      })
    inflightRef.current = task
    return task
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(() => {
      if (Date.now() - fetchedAtRef.current > EDITION_TTL_MS) refresh()
    }, 60 * 1000)
    return () => clearInterval(timer)
  }, [refresh])

  return (
    <EditionContext.Provider value={{ ...info, loaded, refresh }}>
      {children}
    </EditionContext.Provider>
  )
}

export function useEdition() {
  return useContext(EditionContext)
}

// 构建期形态（vite define __EDITION__，见 vite.config.js）：OSS 社区包为 'community'
export const IS_COMMUNITY_BUILD = typeof __EDITION__ !== 'undefined' && __EDITION__ === 'community'

// 明确探测到社区形态才为 true：edition=null（拉取失败）不降级，避免误伤商业部署。
// OBS-002：形态判定以服务端 /api/edition 实时值为准——服务端已明确返回非 community
// 形态（saas/enterprise）时，构建期常量 IS_COMMUNITY_BUILD 不再强制判社区
// （社区默认构建包部署到 saas 环境时曾恒显「当前为社区版」横幅）。
// 服务端不可达（edition=null）才回落构建期口径。
export function useIsCommunity() {
  const { edition, commercial } = useEdition()
  if (edition && edition !== 'community') return false
  return IS_COMMUNITY_BUILD || (edition === 'community' && !commercial)
}

export default EditionContext
