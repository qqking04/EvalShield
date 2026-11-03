/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ES8 M7：评测集版本历史抽屉 —— 快照列表 + 任选两项行级 diff 高亮（自写 LCS，无新依赖）
import { useEffect, useState } from 'react'
import { Alert, App, Button, Drawer, Space, Spin, Table, Tag, Typography } from 'antd'
import http from '../../api/http'
import { fmtTime } from '../../utils'

// 条目 → 规范化行文本（行级 diff 的粒度，与后端 diff_stats 的行语义对齐）
const itemLine = (it) => {
  try { return JSON.stringify(it) } catch { return String(it) }
}

// LCS 行 diff（≤30 行，无 diff 库依赖）：返回 [{t:'same'|'add'|'del', line}]
function diffLines(aLines, bLines) {
  const n = aLines.length, m = bLines.length
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = aLines[i] === bLines[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
  const out = []
  let i = 0, j = 0
  while (i < n && j < m) {
    if (aLines[i] === bLines[j]) { out.push({ t: 'same', line: aLines[i] }); i++; j++ }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ t: 'del', line: aLines[i] }); i++ }
    else { out.push({ t: 'add', line: bLines[j] }); j++ }
  }
  while (i < n) out.push({ t: 'del', line: aLines[i++] })
  while (j < m) out.push({ t: 'add', line: bLines[j++] })
  return out
}

const ROW_BG = { add: '#f6ffed', del: '#fff1f0', same: 'transparent' }
const ROW_PREFIX = { add: '+', del: '-', same: ' ' }

export default function EvalSetVersionDrawer({ open, onClose, evalSet, onChanged }) {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [revs, setRevs] = useState([])
  const [currentVersion, setCurrentVersion] = useState('v1')
  const [pair, setPair] = useState([]) // 选中的两个快照版本号
  const [diff, setDiff] = useState(null) // { fromLabel, toLabel, rows }
  const [diffLoading, setDiffLoading] = useState(false)

  const loadList = async () => {
    if (!evalSet) return
    setLoading(true)
    try {
      const d = await http.get(`/eval-sets/${evalSet.id}/revisions`)
      setRevs(d.items || [])
      setCurrentVersion(d.current_version || 'v1')
      setPair([]); setDiff(null)
    } catch (e) { console.warn('[EvalSetVersionDrawer]', e?.message || e) }
    finally { setLoading(false) }
  }

  useEffect(() => { if (open) loadList() }, [open, evalSet?.id])

  const runDiff = async () => {
    if (pair.length !== 2) { message.warning('请在列表勾选两个版本'); return }
    setDiffLoading(true)
    try {
      // 按版本号升序：旧版为 from，新版为 to
      const ordered = [...pair].sort((x, y) => Number(String(x).slice(1)) - Number(String(y).slice(1)))
      const [from, to] = await Promise.all(
        ordered.map((v) => http.get(`/eval-sets/${evalSet.id}/revisions/${v}`)),
      )
      setDiff({
        fromLabel: from.version,
        toLabel: to.version,
        rows: diffLines((from.items || []).map(itemLine), (to.items || []).map(itemLine)),
      })
    } catch (e) { console.warn('[EvalSetVersionDrawer] diff 失败', e?.message || e) }
    finally { setDiffLoading(false) }
  }

  const columns = [
    {
      title: '快照版本', dataIndex: 'version', width: 110,
      render: (v) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: '条数', dataIndex: 'item_count', width: 80, align: 'center',
    },
    {
      title: '变更（升版时对比下一版）', dataIndex: 'diff_stats', width: 200,
      render: (d) => d ? (
        <Space size={4}>
          <Tag color="green">+{d.added ?? 0}</Tag>
          <Tag color="red">-{d.removed ?? 0}</Tag>
          <Tag>={d.unchanged ?? 0}</Tag>
        </Space>
      ) : <Typography.Text type="secondary">—</Typography.Text>,
    },
    { title: '快照时间', dataIndex: 'created_at', width: 160, render: (v) => fmtTime(v) },
  ]

  return (
    <Drawer
      title={evalSet ? `${evalSet.name} — 版本历史（当前 ${currentVersion}）` : '版本历史'}
      width={860}
      open={open}
      onClose={onClose}
    >
      <Spin spinning={loading}>
        {revs.length === 0 ? (
          <Alert
            type="info"
            showIcon
            message="暂无历史快照"
            description={`当前版本 ${currentVersion}。编辑题项且内容有变时自动升版，旧内容将快照到这里。`}
          />
        ) : (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Table
              rowKey="version"
              size="small"
              columns={columns}
              dataSource={revs}
              pagination={{ pageSize: 10, showSizeChanger: false }}
              rowSelection={{
                type: 'radio',
                selectedRowKeys: pair,
                onSelect: (row) => setPair((prev) => (prev.includes(row.version) ? prev.filter((v) => v !== row.version) : [...prev, row.version].slice(-2))),
              }}
            />
            <Space>
              <Button type="primary" disabled={pair.length !== 2} loading={diffLoading} onClick={runDiff}>
                对比所选两版
              </Button>
              <Button onClick={() => onChanged?.()}>刷新列表</Button>
            </Space>
            {diff && (
              <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, overflow: 'auto', maxHeight: '48vh', fontFamily: 'monospace', fontSize: 12 }}>
                <div style={{ padding: '6px 10px', background: '#fafafa', position: 'sticky', top: 0 }}>
                  <Tag color="red">{diff.fromLabel}（旧）</Tag>
                  <Tag color="green">{diff.toLabel}（新）</Tag>
                  <Typography.Text type="secondary">行级差异（题项 JSON 逐行）</Typography.Text>
                </div>
                {diff.rows.map((r, idx) => (
                  <div key={idx} style={{ padding: '2px 10px', background: ROW_BG[r.t], whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                    {ROW_PREFIX[r.t]} {r.line}
                  </div>
                ))}
              </div>
            )}
          </Space>
        )}
      </Spin>
    </Drawer>
  )
}
