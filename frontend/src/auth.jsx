/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { createContext, useContext, useEffect, useRef, useState } from 'react'
import http from './api/http'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [licensed, setLicensed] = useState(false)   // 企业版能力门控：license ACTIVE 且非社区版
  const isLoggingIn = useRef(false)          // 标记登录中，阻初始 fetchMe 清 token
  const fetchSeq = useRef(0)                 // fetchMe 版本号，防旧响写新状态

  useEffect(() => {
    if (!user) {
      setLicensed(false)
      return
    }
    http
      // BUG-017：saas 形态该端点按设计 404（.lic 不可达）→ silent 探测，
      // 失败静默降级为社区版处理，不弹全局错误提示
      .get('/license/status', { silent: true })
      .then((d) => {
        if (!d || (d.edition !== 'enterprise' && d.edition !== 'saas')) {
          setLicensed(false)
          return
        }
        // 优化7 T5：grace/revoked 期企业菜单与 /license 续证入口必须可达
        // （只读锁由后端写拦截保证，前端不做隐藏）
        setLicensed(d.status === 'ACTIVE' || d.phase === 'grace' || d.phase === 'revoked')
      })
      .catch(() => setLicensed(false)) // 接口异常按社区版处理（隐藏企业菜单）
  }, [user])

  const fetchMe = async (silent = false) => {
    const token = localStorage.getItem('es_token')
    if (!token) {
      if (!silent) setLoading(false)
      return null
    }
    const seq = ++fetchSeq.current
    try {
      const data = await http.get('/auth/me')
      // 只接受最新版本的响应
      if (seq === fetchSeq.current) {
        setUser(data)
        if (!silent) setLoading(false)
      }
      return data
    } catch (e) {
      if (seq === fetchSeq.current) {
        // 登录流程中的 401 不清 token（交由 login() 的 await fetchMe() 同步判断）
        // 优化7 T4：半态令牌下 /auth/me 返回 PWD-REQUIRED 也不清 token（改密页需要它）
        if (!isLoggingIn.current && e?.code !== 'ES-AUTH-PWD-REQUIRED') {
          localStorage.removeItem('es_token')
          localStorage.removeItem('es_refresh')
          setUser(null)
        }
        console.warn('[Auth] fetchMe failed', e?.message || e)
        if (!silent) setLoading(false)
      }
      return null
    }
  }

  useEffect(() => {
    fetchMe()
  }, [])

  const login = async (username, password, totpCode) => {
    isLoggingIn.current = true
    try {
      const data = await http.post('/auth/login', {
        username,
        password,
        totp_code: totpCode || undefined,
      })
      localStorage.setItem('es_token', data.access_token)
      localStorage.setItem('es_refresh', data.refresh_token || '')
      // 清掉并发的初始 fetchMe 响应
      fetchSeq.current++
      await fetchMe()
      return data
    } finally {
      isLoggingIn.current = false
    }
  }

  // 直接设置 token（用于组织切换等场景）
  const setToken = async (accessToken, refreshToken) => {
    if (accessToken) localStorage.setItem('es_token', accessToken)
    if (refreshToken) localStorage.setItem('es_refresh', refreshToken)
    fetchSeq.current++
    await fetchMe()
  }

  const logout = async () => {
    try {
      await http.post('/auth/logout')
    } catch (e) {
      /* 登出接口异常不影响本地清理 */
      console.warn('[Auth] logout failed', e?.message || e)
    }
    localStorage.removeItem('es_token')
    localStorage.removeItem('es_refresh')
    setUser(null)
  }

  const hasPerm = (code) => {
    if (!user) return false
    if (user.is_super_admin) return true
    const perms = user.perms || []
    const [module] = code.split(':')
    return perms.includes(code) || perms.includes(`${module}:*`)
  }

  return (
    <AuthContext.Provider
      value={{ user, loading, licensed, login, logout, setToken, fetchMe, hasPerm }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}