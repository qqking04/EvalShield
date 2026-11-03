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

// 优化9 §2.1.3：导航 feature flags 契约消费层。
// 登录后 GET /api/meta/feature-flags（走 http 实例，自动带 Bearer 认证头），
// 响应 { version, edition, nav_profile, flags: { "nav.question_bank": true, ... } }。
// 5 分钟 TTL + 并发去重（与 EditionContext 同模式）。
// 拉取失败：按 flags 全 true 渲染完整入口（fail-open），并置 failed 供一次性提示。
const FLAGS_TTL_MS = 5 * 60 * 1000

// 已知 flag 全集（新增入口默认登记于此；未知 flag 亦按全 true 兜底）
export const KNOWN_NAV_FLAGS = [
  'nav.question_bank',
  'nav.targets',
  'nav.reports',
  'nav.lab.cost',
  'nav.lab.uat',
  'nav.lab.ci',
  'nav.lab.model_compare',
  'nav.lab.recordings',
  'nav.lab.perf',
  'nav.lab.src',
  'nav.lab.redteam',
  'nav.lab.monitor',
]

const OPEN_ALL = () => Object.fromEntries(KNOWN_NAV_FLAGS.map((k) => [k, true]))

// 模块级缓存：多个消费方共享一次请求，跨路由切换不重复拉取
let cache = { flags: OPEN_ALL(), navProfile: 'full', edition: null, version: null, loaded: false, failed: false }
let fetchedAt = 0
let inflight = null
const listeners = new Set()

function emit() {
  listeners.forEach((fn) => fn(cache))
}

async function fetchFeatureFlags() {
  const resp = await http.get('/meta/feature-flags')
  // http 响应拦截器已解包 body.data；兼容未解包形态
  const data = resp && typeof resp === 'object' && 'flags' in resp ? resp : resp?.data
  if (!data || typeof data !== 'object' || !data.flags || typeof data.flags !== 'object') {
    throw new Error('feature-flags malformed payload')
  }
  // 未知 flag 按全 true 兜底合并，保证 fail-open 语义
  const merged = { ...OPEN_ALL() }
  Object.entries(data.flags).forEach(([k, v]) => {
    merged[k] = v === true || v === false ? v : true
  })
  return {
    flags: merged,
    navProfile: typeof data.nav_profile === 'string' ? data.nav_profile : 'full',
    edition: typeof data.edition === 'string' ? data.edition : null,
    version: typeof data.version === 'string' ? data.version : null,
    loaded: true,
    failed: false,
  }
}

export function refreshFeatureFlags(force = false) {
  if (inflight) return inflight
  if (!force && cache.loaded && Date.now() - fetchedAt < FLAGS_TTL_MS) return Promise.resolve(cache)
  const task = fetchFeatureFlags()
    .then((next) => {
      cache = next
      fetchedAt = Date.now()
      return cache
    })
    .catch(() => {
      // 失败降级：全 true 完整入口 + failed 标记（消费方给一次性提示）
      cache = { flags: OPEN_ALL(), navProfile: 'full', edition: null, version: null, loaded: true, failed: true }
      fetchedAt = 0
      return cache
    })
    .finally(() => {
      inflight = null
      emit()
    })
  inflight = task
  return task
}

// 供拦截器/非 Hook 场景读取当前 flags 快照
export function getFeatureFlags() {
  return cache
}

export function useFeatureFlags() {
  const [state, setState] = useState(cache)
  useEffect(() => {
    listeners.add(setState)
    if (!state.loaded || Date.now() - fetchedAt > FLAGS_TTL_MS) refreshFeatureFlags()
    return () => {
      listeners.delete(setState)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return {
    ...state,
    refresh: () => refreshFeatureFlags(true),
  }
}

// 判定单个 flag（缺省视为 true，fail-open）
export function flagOn(flags, key) {
  if (!key) return true
  return flags?.[key] !== false
}
