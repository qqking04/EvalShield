/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// FE-12：截图点选取选择器 —— 探测页面截图 + 可交互元素透明热区，点击回填 dom_selector
import { useMemo, useState } from 'react'
import { Modal, Empty, Tag, Input, Space, Typography } from 'antd'
import { C, MONO } from './consoleTheme'

const { Text } = Typography

/**
 * @param {object} props
 * @param {boolean} props.open
 * @param {number} props.jobId            探测任务 ID（截图服务路径参数）
 * @param {Array}  props.uiElements       payload.ui_elements：[{page_url,menu,screenshot,viewport:{width,height},elements:[{tag,label,css,x,y,w,h}]}]
 * @param {Function} props.onPick          点选回调 (selector) => void
 * @param {Function} props.onCancel
 */
export default function DiscoverSelectorPicker({ open, jobId, uiElements = [], onPick, onCancel }) {
  const pages = useMemo(() => uiElements.filter((p) => p.screenshot), [uiElements])
  const [pageIdx, setPageIdx] = useState(0)
  const [hover, setHover] = useState(-1)
  const [keyword, setKeyword] = useState('')

  const page = pages[pageIdx] || pages[0]
  const vw = page?.viewport?.width || 1280
  const vh = page?.viewport?.height || 800

  const filtered = useMemo(() => {
    const els = page?.elements || []
    const kw = keyword.trim().toLowerCase()
    if (!kw) return els
    return els.filter((e) => `${e.label} ${e.css} ${e.tag}`.toLowerCase().includes(kw))
  }, [page, keyword])

  if (!open) return null

  return (
    <Modal
      open={open}
      onCancel={onCancel}
      footer={null}
      width={920}
      title="截图点选 · 获取 DOM 选择器"
      styles={{ content: { background: C.panel, border: `1px solid ${C.panelBorder}` }, header: { background: 'transparent', borderBottom: `1px solid ${C.panelBorder}` } }}
    >
      {pages.length === 0 ? (
        <Empty
          description={<span style={{ color: C.dim }}>本次探测未产出页面截图（Swagger 通道或浏览器采集失败），可手动输入选择器</span>}
        />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size="small">
          {/* 页面切换 + 元素搜索 */}
          <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
            <Space wrap size={4}>
              {pages.map((p, i) => (
                <Tag
                  key={p.page_url + i}
                  color={i === pageIdx ? 'cyan' : 'default'}
                  style={{ cursor: 'pointer' }}
                  onClick={() => { setPageIdx(i); setHover(-1) }}
                >
                  {p.menu || p.page_url?.slice(-28) || `页面${i + 1}`}
                </Tag>
              ))}
            </Space>
            <Input
              size="small"
              placeholder="搜索元素（label/选择器/标签）"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              style={{ width: 220, background: '#0d1420', color: C.text }}
              allowClear
            />
          </Space>

          {/* 截图 + 热区叠加层（按视口原始坐标等比缩放） */}
          <div style={{ position: 'relative', width: '100%', border: `1px solid ${C.panelBorder}`, borderRadius: 6, overflow: 'hidden', background: '#000' }}>
            <img
              key={page?.screenshot}
              src={`/api/ai/discover/${jobId}/screenshot?name=${encodeURIComponent(page?.screenshot || '')}&token=${encodeURIComponent(localStorage.getItem('es_token') || '')}`}
              alt="探测页面截图"
              style={{ display: 'block', width: '100%', height: 'auto' }}
              onError={(e) => { e.currentTarget.style.display = 'none' }}
            />
            {/* 热区层：以视口 vw 为基准等比缩放（百分比定位） */}
            <div style={{ position: 'absolute', inset: 0 }}>
              {filtered.map((el, i) => {
                const left = (el.x / vw) * 100
                const top = (el.y / vh) * 100
                const width = (el.w / vw) * 100
                const height = (el.h / vh) * 100
                if (left > 100 || top > 100) return null
                return (
                  <div
                    key={el.css + el.x + el.y + i}
                    onMouseEnter={() => setHover(i)}
                    onMouseLeave={() => setHover((h) => (h === i ? -1 : h))}
                    onClick={() => onPick?.(el.css)}
                    title={`${el.label} → ${el.css}`}
                    style={{
                      position: 'absolute',
                      left: `${left}%`,
                      top: `${top}%`,
                      width: `${Math.min(width, 100 - left)}%`,
                      height: `${Math.min(height, 100 - top)}%`,
                      border: hover === i ? `2px solid ${C.cyan}` : '2px solid transparent',
                      background: hover === i ? 'rgba(19,194,194,0.18)' : 'transparent',
                      cursor: 'crosshair',
                      boxSizing: 'border-box',
                      transition: 'background 0.12s',
                    }}
                  />
                )
              })}
            </div>
          </div>

          {/* 元素清单（与热区双向 hover 联动） */}
          <div style={{ maxHeight: 140, overflowY: 'auto', border: `1px solid ${C.panelBorder}`, borderRadius: 6, padding: 6 }}>
            {filtered.length === 0 ? (
              <Text style={{ color: C.dim, fontSize: 12 }}>无匹配元素</Text>
            ) : (
              filtered.map((el, i) => (
                <div
                  key={el.css + el.x + el.y + i}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover((h) => (h === i ? -1 : h))}
                  onClick={() => onPick?.(el.css)}
                  style={{
                    display: 'flex', justifyContent: 'space-between', gap: 8, padding: '2px 6px',
                    cursor: 'pointer', borderRadius: 4, background: hover === i ? 'rgba(19,194,194,0.12)' : 'transparent',
                  }}
                >
                  <span style={{ color: C.text, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    <Tag style={{ marginRight: 6 }}>{el.tag}</Tag>{el.label}
                  </span>
                  <span className="disc-mono" style={{ color: '#722ed1', fontSize: 11, fontFamily: MONO, flexShrink: 0 }}>{el.css}</span>
                </div>
              ))
            )}
          </div>
          <Text style={{ color: C.dim, fontSize: 11 }}>点击截图中高亮区域或下方清单条目，即可回填 DOM 选择器（坐标基于探测视口 {vw}×{vh}）</Text>
        </Space>
      )}
    </Modal>
  )
}
