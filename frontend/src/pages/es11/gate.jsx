/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司. All rights reserved.
 * SPDX-License-Identifier: BUSL-1.1
 * ES11 门禁可视化基元（证据轨主题，方案 §5.1）。全站 G0-G4 唯一视觉语言。
 * 原则：状态永不单靠颜色——图标+文字+色三通道（合规截图/无障碍）。
 */
import { Tooltip, Typography } from 'antd'
import {
  CheckCircleFilled,
  ExclamationCircleFilled,
  StopFilled,
  ClockCircleOutlined,
} from '@ant-design/icons'

// 证据轨设计令牌（方案 §5.1）
export const ES = {
  bg: '#0B111A',
  line: '#1F2833',
  accent: '#13C2C2',
  ink: '#E6F7FF',
  sub: '#8BA3B5',
  PASS: '#3FB950',
  WARN: '#D29922',
  BLOCK: '#F85149',
  mono: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
}

const STATUS_META = {
  PASS: { color: ES.PASS, icon: <CheckCircleFilled />, label: '通过' },
  WARN: { color: ES.WARN, icon: <ExclamationCircleFilled />, label: '关注' },
  BLOCK: { color: ES.BLOCK, icon: <StopFilled />, label: '阻塞' },
  // 三类失败口径（G1）
  CONFIG: { color: ES.WARN, icon: <ExclamationCircleFilled />, label: '配置' },
  INFRA: { color: ES.BLOCK, icon: <StopFilled />, label: '基础设施' },
  QUALITY: { color: ES.BLOCK, icon: <StopFilled />, label: '质量' },
}

export function statusMeta(s) {
  return STATUS_META[s] || { color: ES.sub, icon: <ClockCircleOutlined />, label: s || '-' }
}

/** 单个门禁状态徽标：图标+文字+色，永不单靠颜色。 */
export function GateBadge({ status, text, reason, style }) {
  const m = statusMeta(status)
  const node = (
    <span
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5,
        color: m.color, fontWeight: 600, fontSize: 13, ...style,
      }}
    >
      {m.icon}
      {text ?? m.label}
    </span>
  )
  return reason ? <Tooltip title={reason}>{node}</Tooltip> : node
}

/** 门禁检查清单（G0 readiness / G4 delivery 共用）：逐条 code+status+reason，阻塞项带修复入口。 */
export function GateChecklist({ checks = [], onAction }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {checks.map((c) => {
        const m = statusMeta(c.status)
        return (
          <div
            key={c.code}
            style={{
              display: 'flex', alignItems: 'flex-start', gap: 10,
              padding: '8px 12px', border: `1px solid ${ES.line}`,
              borderLeft: `3px solid ${m.color}`, borderRadius: 6, background: '#0d1420',
            }}
          >
            <span style={{ color: m.color, marginTop: 2 }}>{m.icon}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Typography.Text style={{ color: ES.ink, fontSize: 13 }}>
                {c.reason || c.code}
              </Typography.Text>
              <div>
                <Typography.Text style={{ color: ES.sub, fontSize: 12, fontFamily: ES.mono }}>
                  {c.code}
                </Typography.Text>
              </div>
            </div>
            {c.action && onAction && (
              <a style={{ color: ES.accent, fontSize: 13, whiteSpace: 'nowrap' }}
                 onClick={() => onAction(c.action)}>
                {c.action.label} ›
              </a>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** 上线结论条（P1 首屏英雄区）：可交付 | 待复核 | 被阻塞，每段可点击下钻。 */
export function ShipVerdict({ segments = [], onSelect }) {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'stretch', gap: 0,
        background: ES.bg, border: `1px solid ${ES.line}`, borderRadius: 10, overflow: 'hidden',
      }}
    >
      {segments.map((s, i) => {
        const m = statusMeta(s.status || 'PASS')
        return (
          <div
            key={s.key || i}
            onClick={() => onSelect?.(s)}
            style={{
              flex: 1, padding: '18px 20px', cursor: s.drill ? 'pointer' : 'default',
              borderRight: i < segments.length - 1 ? `1px solid ${ES.line}` : 'none',
              transition: 'background .15s',
            }}
            onMouseEnter={(e) => s.drill && (e.currentTarget.style.background = '#0d1420')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={{ fontSize: 34, fontWeight: 700, color: m.color, lineHeight: 1, fontFamily: ES.mono }}>
                {s.value ?? 0}
              </span>
              <span style={{ color: ES.ink, fontSize: 14 }}>{s.label}</span>
            </div>
            {s.hint && (
              <div style={{ color: ES.sub, fontSize: 12, marginTop: 6 }}>{s.hint}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** 证据轨面板：深色底 + 等宽 ID，视觉隔离「原始证据」与「结论」。 */
export function EvidencePanel({ title, children, style }) {
  return (
    <div style={{ background: ES.bg, border: `1px solid ${ES.line}`, borderRadius: 8, padding: 14, ...style }}>
      {title && (
        <Typography.Text style={{ color: ES.sub, fontSize: 12, display: 'block', marginBottom: 8 }}>
          {title}
        </Typography.Text>
      )}
      {children}
    </div>
  )
}

/** 机器事实（run_no / hash / 证据编号）等宽展示。 */
export function Mono({ children, color = ES.accent }) {
  return <span style={{ fontFamily: ES.mono, color, fontSize: 12.5 }}>{children}</span>
}
