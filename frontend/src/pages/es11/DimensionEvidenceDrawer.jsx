/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
/*
 * 优化12 §10.3：子类证据抽屉——双轨覆盖矩阵行点击下钻。
 * 后端 /eval-runs/:id/items 无 category 过滤参数（T7 前端-only，不改后端），
 * 这里分页拉取后按 sub.bank_category 本地过滤；单题全文走 item_id + full=1。
 * 动效预算内的一处：抽屉滑出（prefers-reduced-motion 降级为无动画）。
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Drawer, Space, Typography, Table, Tag, Button, Alert, Spin, Empty, Descriptions,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import { getRunItems } from '../../api/es11'
import { usePrefersReducedMotion } from './usePrefersReducedMotion'
import { ES, GateBadge, EvidencePanel, Mono, statusMeta } from './gate'

const PAGE_SIZE = 50
const MAX_PAGES = 10 // 本地过滤上限 500 题，超出时提示用运行明细页全量检索

const VERDICT_STATUS = { PASS: 'PASS', FAIL: 'BLOCK', ERROR: 'BLOCK', REVIEW: 'WARN' }

function pct(v, digits = 1) {
  return v == null ? '-' : `${(v * 100).toFixed(digits)}%`
}

/**
 * @param {boolean} open
 * @param {object|null} sub 子类行（dimension_coverage.subs 元素）：
 *   {sub_code, bank_category, service_type, tested, pass, rate,
 *    min_questions, pass_threshold, status, engines[]}
 * @param {number|string|null} runId
 */
export default function DimensionEvidenceDrawer({ open, sub, runId, onClose }) {
  const navigate = useNavigate()
  const reduced = usePrefersReducedMotion()
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [capped, setCapped] = useState(false)
  const [picked, setPicked] = useState(null) // 单题全文
  const [pickedLoading, setPickedLoading] = useState(false)

  const category = sub?.bank_category || null

  useEffect(() => {
    if (!open || !runId || !category) {
      setRows([]); setTotal(0); setCapped(false); setPicked(null); return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    setPicked(null)
    ;(async () => {
      const hit = []
      let grand = 0
      try {
        for (let p = 1; p <= MAX_PAGES; p += 1) {
          // eslint-disable-next-line no-await-in-loop
          const d = await getRunItems(runId, { page: p, page_size: PAGE_SIZE })
          if (cancelled) return
          const items = d?.items || []
          grand = d?.total ?? grand
          items.forEach((it) => { if (it.category === category) hit.push(it) })
          if (items.length < PAGE_SIZE || p * PAGE_SIZE >= grand) {
            setRows(hit); setTotal(grand); setCapped(false); break
          }
          if (p === MAX_PAGES) { setRows(hit); setTotal(grand); setCapped(true) }
        }
      } catch (e) {
        if (!cancelled) setError(e?.message || '题目明细加载失败，请检查网络或稍后重试')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [open, runId, category])

  const columns = useMemo(() => [
    { title: '序号', dataIndex: 'seq', width: 70, render: (v) => <Mono color={ES.sub}>{v}</Mono> },
    {
      title: '问题', dataIndex: 'prompt', ellipsis: true,
      render: (v, r) => (
        <a style={{ color: ES.accent }} onClick={() => setPicked(r)}>
          {v || `题目 #${r.item_id ?? r.id}`}
        </a>
      ),
    },
    {
      title: '终判', dataIndex: 'final_verdict', width: 100,
      render: (v) => <GateBadge status={VERDICT_STATUS[v] || 'WARN'} text={v || '-'} />,
    },
    {
      title: '判定来源', dataIndex: 'judge_verdict', width: 110, ellipsis: true,
      render: (v) => <span style={{ color: ES.sub, fontSize: 12 }}>{v || '-'}</span>,
    },
  ], [])

  const openFull = async (row) => {
    setPicked(row)
    if (!runId) return
    setPickedLoading(true)
    try {
      const d = await getRunItems(runId, { page: 1, page_size: 1, item_id: row.item_id ?? row.id, full: 1 })
      const full = (d?.items || [])[0]
      if (full) setPicked({ ...row, ...full })
    } catch { /* 保留摘要态展示，不阻断 */ } finally {
      setPickedLoading(false)
    }
  }

  const meta = statusMeta(sub?.status)

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={720}
      placement="right"
      title={sub ? (
        <Space size={8}>
          <Mono color={ES.ink}>{sub.sub_code}</Mono>
          <GateBadge status={sub.status} />
        </Space>
      ) : '子类证据'}
      styles={{ body: { background: ES.bg } }}
      {...(reduced ? { transitionName: '', mask: false } : {})}
    >
      {sub && (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Descriptions
            size="small"
            column={2}
            labelStyle={{ color: ES.sub }}
            contentStyle={{ color: ES.ink }}
            items={[
              { key: 'cat', label: '题库分类', children: <Mono>{sub.bank_category}</Mono> },
              { key: 'svc', label: '服务类型', children: sub.service_type || '-' },
              {
                key: 'rate', label: '合格率（实测/核定）',
                children: (
                  <span style={{ color: meta.color, fontFamily: ES.mono }}>
                    {pct(sub.rate)} / {pct(sub.pass_threshold)}
                    <span style={{ color: ES.sub, fontSize: 12 }}>　{sub.pass}/{sub.tested} 题</span>
                  </span>
                ),
              },
              { key: 'eng', label: '要求引擎', children: (sub.engines || []).map((e) => e.code).join('、') || '-' },
            ]}
          />
          {error && (
            <Alert type="error" showIcon message="题目明细加载失败" description={error} />
          )}
          {capped && (
            <Alert
              type="warning"
              showIcon
              message={`本次仅在前 ${MAX_PAGES * PAGE_SIZE} 题内筛选该子类题目（运行共 ${total} 题），完整检索请去运行明细。`}
            />
          )}
          <div>
            <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>
              命中 {rows.length} 题{loading ? ' · 加载中' : ''}
            </Typography.Text>
            <Button
              size="small"
              type="link"
              onClick={() => navigate(`/eval/runs/${runId}?tab=items`)}
            >
              在运行明细中查看全部 ›
            </Button>
          </div>
          {loading && !rows.length ? (
            <Spin style={{ display: 'block', margin: '32px auto' }} />
          ) : rows.length === 0 && !error ? (
            <Empty
              description={
                <span style={{ color: ES.sub }}>
                  该运行中暂无分类为「{sub.bank_category}」的题目——覆盖结论以矩阵行为准，可发起补题后重跑。
                </span>
              }
            />
          ) : (
            <Table
              rowKey={(r) => r.id ?? r.item_id}
              size="small"
              columns={columns}
              dataSource={rows}
              pagination={false}
              scroll={{ y: picked ? 220 : 360 }}
              onRow={(r) => ({
                onClick: () => openFull(r),
                tabIndex: 0,
                onKeyDown: (e) => { if (e.key === 'Enter') openFull(r) },
                style: { cursor: 'pointer' },
              })}
              locale={{ emptyText: ' ' }}
            />
          )}
          {picked && (
            <EvidencePanel
              title={`单题全文 · seq ${picked.seq ?? ''}（${picked.final_verdict || '-'}）`}
            >
              {pickedLoading && <Spin size="small" style={{ marginRight: 8 }} />}
              <div style={{ color: ES.ink, fontSize: 13, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {picked.prompt || '（无题面文本）'}
              </div>
              <div style={{ marginTop: 10, borderTop: `1px solid ${ES.line}`, paddingTop: 10 }}>
                <Typography.Text style={{ color: ES.sub, fontSize: 12 }}>应答</Typography.Text>
                <div style={{ color: ES.ink, fontSize: 13, whiteSpace: 'pre-wrap', wordBreak: 'break-all', marginTop: 4 }}>
                  {picked.response || (pickedLoading ? '加载中…' : '（无应答记录）')}
                </div>
              </div>
              {picked.failure_class && (
                <div style={{ marginTop: 8 }}>
                  <Tag style={{ borderColor: ES.line }}><span style={{ color: ES.sub }}>失败口径</span> {picked.failure_class}</Tag>
                </div>
              )}
            </EvidencePanel>
          )}
        </Space>
      )}
    </Drawer>
  )
}
