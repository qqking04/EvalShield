/*
 * 401 语义回归：拦截器曾把「所有」401 一律渲染为「登录已过期，请重新登录」，
 * 导致登录页输错密码（后端 401 ES-AUTH-0001 用户名或密码错误）时提示与会话无关的文案，
 * 用户误以为系统故障反复重试，直至触发 5 次/30 分钟锁定。
 * 本测试锁死三条口径：认证入口透出后端原文、业务接口才做过期处理、登录页静默。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

vi.mock('antd', () => ({
  message: { error: vi.fn(), success: vi.fn(), warn: vi.fn() },
}))
vi.mock('../components/EditionLimitCard', () => ({
  showEditionLimitModal: vi.fn(),
}))

import http from './http'
import { message } from 'antd'

const rejected = http.interceptors.response.handlers[0].rejected

const authError = (url) => ({
  config: { url },
  response: { status: 401, data: { code: 'ES-AUTH-0001', message: '用户名或密码错误' } },
})

const setPathname = (path) => {
  Object.defineProperty(window, 'location', {
    value: { pathname: path, href: '' }, writable: true, configurable: true,
  })
}

describe('http 拦截器 401 分支', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.setItem('es_token', 'tok-keep-me')
    setPathname('/dashboard')
  })

  afterEach(() => localStorage.clear())

  it('登录接口 401：透出后端原文，不清 token、不跳转', async () => {
    await expect(rejected(authError('/auth/login'))).rejects.toThrow('用户名或密码错误')
    expect(message.error).toHaveBeenCalledWith('用户名或密码错误')
    expect(localStorage.getItem('es_token')).toBe('tok-keep-me')
    expect(window.location.href).toBe('')
  })

  it('业务接口 401 且不在登录页：判定会话过期，清 token 并跳 /login', async () => {
    const err = { config: { url: '/tasks' }, response: { status: 401, data: { code: 'ES-AUTH-0001' } } }
    await expect(rejected(err)).rejects.toThrow('登录已过期，请重新登录')
    expect(message.error).toHaveBeenCalledWith('登录已过期，请重新登录')
    expect(localStorage.getItem('es_token')).toBeNull()
    expect(window.location.href).toBe('/login')
  })

  it('业务接口 401 且已在登录页：静默失败（不清提示、不再跳转）', async () => {
    setPathname('/login')
    await expect(rejected({ config: { url: '/auth/me' }, response: { status: 401, data: {} } }))
      .rejects.toThrow()
    expect(message.error).not.toHaveBeenCalled()
    expect(localStorage.getItem('es_token')).toBeNull()
    expect(window.location.href).toBe('')
  })
})
