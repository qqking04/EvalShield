/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// Command Console 主题令牌：AI 自动探测页专用（局部 scoped，不影响全局 antd 主题）
export const C = {
  bg: '#0b0f14',
  panel: '#10161f',
  panelBorder: '#1d2733',
  text: '#d8e3ee',
  dim: '#7a8a9c',
  cyan: '#13c2c2',
  amber: '#ffd666',
  red: '#ff4d4f',
  green: '#52c41a',
  gray: '#8c8c8c',
}

export const MONO = "'JetBrains Mono', 'Cascadia Code', Consolas, 'Courier New', monospace"

// 页面级样式（一次性注入，类名前缀 disc- 避免冲突）
export function injectConsoleStyle() {
  if (document.getElementById('disc-console-style')) return
  const el = document.createElement('style')
  el.id = 'disc-console-style'
  el.textContent = `
.disc-page { background:${C.bg}; color:${C.text}; border-radius:8px; padding:20px 22px; min-height:calc(100vh - 120px);
  background-image: radial-gradient(circle at 15% 10%, rgba(19,194,194,.06), transparent 40%),
    radial-gradient(circle at 85% 90%, rgba(19,194,194,.04), transparent 45%); }
.disc-title { font-size:20px; font-weight:700; letter-spacing:1px; color:${C.text}; margin:0 0 4px; }
.disc-sub { color:${C.dim}; font-size:12px; margin-bottom:16px; font-family:${MONO}; }
.disc-panel { background:${C.panel}; border:1px solid ${C.panelBorder}; border-radius:8px; padding:14px 16px; }
.disc-label { color:${C.dim}; font-size:12px; margin-bottom:6px; display:block; }
.disc-mono { font-family:${MONO}; }
.disc-terminal { background:#070b10; border:1px solid ${C.panelBorder}; border-radius:6px; padding:10px 12px;
  font-family:${MONO}; font-size:12px; line-height:1.75; height:260px; overflow-y:auto; color:#9fb4c8; }
.disc-terminal .t-info { color:#9fb4c8; }
.disc-terminal .t-ok { color:${C.green}; }
.disc-terminal .t-warn { color:${C.amber}; }
.disc-terminal .t-err { color:${C.red}; }
.disc-terminal .t-time { color:#4f6377; margin-right:8px; }
.disc-log-in { animation: discSlideIn .18s ease-out; }
@keyframes discSlideIn { from { opacity:0; transform:translateY(4px);} to { opacity:1; transform:none;} }
.disc-step-reveal { opacity:0; animation: discReveal .4s ease-out forwards; }
@keyframes discReveal { from { opacity:0; transform:translateY(10px);} to { opacity:1; transform:none;} }
.disc-bar { height:8px; border-radius:4px; background:#16202c; overflow:hidden; position:relative; }
.disc-bar-inner { height:100%; background:linear-gradient(90deg,${C.cyan},#43e8e8,${C.cyan}); background-size:200% 100%;
  animation: discFlow 1.6s linear infinite; transition: width .5s ease; border-radius:4px; }
@keyframes discFlow { from { background-position:200% 0;} to { background-position:0 0;} }
.disc-badge { position:fixed; right:26px; top:78px; z-index:100; font-family:${MONO}; font-size:12px;
  padding:4px 10px; border-radius:12px; border:1px solid ${C.panelBorder}; background:${C.panel}; color:${C.dim}; }
.disc-badge.waiting { border-color:${C.amber}; color:${C.amber}; box-shadow:0 0 10px rgba(255,214,102,.25); }
.disc-badge.running { border-color:${C.cyan}; color:${C.cyan}; }
.disc-badge.failed { border-color:${C.red}; color:${C.red}; }
.disc-badge.cancelled { border-color:#8c8c8c; color:#8c8c8c; }
`
  document.head.appendChild(el)
}

export const STAGE_LABEL = {
  PENDING: '待开始',
  LOGINNING: '登录中',
  WAITING_HUMAN: '等待人工输入',
  DISCOVERING: '发现接口',
  GENERATING: '生成用例',
  VALIDATE: '回放校验',
  PREVIEW: '待确认',
  CONFIRMED: '已入库',
  FAILED: '失败',
  CANCELLED: '已取消',
}

export const STATUS_COLOR = {
  PENDING: C.dim,
  LOGINNING: C.cyan,
  WAITING_HUMAN: C.amber,
  DISCOVERING: C.cyan,
  GENERATING: C.cyan,
  VALIDATE: C.cyan,
  PREVIEW: C.amber,
  CONFIRMED: C.green,
  FAILED: C.red,
  CANCELLED: C.gray,
}
