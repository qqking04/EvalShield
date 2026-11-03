/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * SPDX-License-Identifier: BUSL-1.1
 * 优化12 §10.3 动效预算配套：prefers-reduced-motion 探测（雷达展开/抽屉滑出降级用）。
 */
import { useEffect, useState } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(
    () => typeof window !== 'undefined' && !!window.matchMedia?.(QUERY).matches,
  )
  useEffect(() => {
    if (typeof window?.matchMedia !== 'function') return undefined
    const mq = window.matchMedia(QUERY)
    const on = (e) => setReduced(e.matches)
    mq.addEventListener?.('change', on)
    return () => mq.removeEventListener?.('change', on)
  }, [])
  return reduced
}

export default usePrefersReducedMotion
