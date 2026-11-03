/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { useEffect, useRef } from 'react'
import { C, MONO } from './consoleTheme'

// 等宽终端日志流：SSE progress 帧追加渲染（FC-04）
export default function DiscoverTerminal({ logs }) {
  const boxRef = useRef(null)
  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
  }, [logs])

  const cls = (l) => (l.level === 'err' ? 't-err' : l.level === 'warn' ? 't-warn' : l.level === 'ok' ? 't-ok' : 't-info')

  return (
    <div className="disc-terminal" ref={boxRef}>
      {logs.length === 0 && <div className="t-time">// 等待任务事件…</div>}
      {logs.map((l, i) => (
        <div key={i} className={`disc-log-in ${cls(l)}`}>
          <span className="t-time">{l.t}</span>
          <span>[{l.stage || 'JOB'}]</span> {l.text}
        </div>
      ))}
    </div>
  )
}
