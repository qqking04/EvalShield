/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Button, Input, Select, Space, Typography } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'

const { Text } = Typography

// FE-4 测试数据编辑器（受控 value/onChange）
// 行 { case, params }，params 为键值对表格 {key, value}（可增删）
// 支持「从数据集参数列导入」生成 params 模板行
export default function DataGridEditor({ value = [], onChange, datasets = [], projectId }) {
  const raw = Array.isArray(value) ? value : []
  // 归一化：后端 params 可能为 {key:value} 对象，转为编辑用 {key,value} 数组
  const rows = raw.map((r) => ({
    ...r,
    params: Array.isArray(r?.params) ? r.params : Object.entries(r?.params || {}).map(([key, value]) => ({ key, value })),
  }))
  const update = (i, patch) => onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  const updateParam = (i, pi, patch) => {
    const params = rows[i].params.map((p, idx) => (idx === pi ? { ...p, ...patch } : p))
    update(i, { params })
  }
  const removeParam = (i, pi) => update(i, { params: rows[i].params.filter((_, idx) => idx !== pi) })
  const addParam = (i) => update(i, { params: [...(rows[i].params || []), { key: '', value: '' }] })
  const removeRow = (i) => onChange(rows.filter((_, idx) => idx !== i))
  const addRow = () => onChange([...rows, { case: '', params: [] }])

  // 从数据集 parameters 生成 params 模板行
  const importFromDataset = (dsId) => {
    const ds = (datasets || []).find((d) => String(d.id) === String(dsId))
    const cols = (ds && Array.isArray(ds.parameters) ? ds.parameters : []) || []
    return cols.map((p) => ({ key: p?.name || '', value: p?.example != null ? String(p.example) : '' }))
  }

  // 一键导入：无论当前有无数据组，都新增一个分组并填入数据集参数列模板
  const importNewGroup = (dsId) => {
    const params = importFromDataset(dsId)
    if (!params.length) return
    onChange([...rows, { case: `数据行${rows.length + 1}`, params }])
  }

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      {datasets.length > 0 && projectId && (
        <Space align="baseline" wrap>
          <Text type="secondary">从数据集导入参数列：</Text>
          <Select size="small" style={{ width: 320 }} placeholder="选择数据集，自动新增一组参数模板"
            value={undefined}
            onChange={importNewGroup}
            options={(datasets || []).map((d) => ({ value: d.id, label: `${d.code || ''} ${d.name}` }))} />
        </Space>
      )}
      {rows.map((r, i) => (
        <Space key={i} direction="vertical" size={4} style={{ width: '100%', padding: 8, border: '1px solid #1f2833', borderRadius: 4, background: '#0f141b' }}>
          <Space align="baseline" style={{ width: '100%' }}>
            <Input size="small" style={{ width: 200 }} placeholder="数据分组名称（case）" value={r.case || ''}
              onChange={(e) => update(i, { case: e.target.value })} />
            <Button size="small" type="link" icon={<DeleteOutlined />} onClick={() => removeRow(i)}>删除组</Button>
            {datasets.length > 0 && projectId && (
              <Select size="small" style={{ width: 220 }} placeholder="覆盖本组参数列"
                value={undefined}
                onChange={(dsId) => {
                  const params = importFromDataset(dsId)
                  if (params.length) update(i, { params })
                }}
                options={(datasets || []).map((d) => ({ value: d.id, label: `${d.code || ''} ${d.name}` }))} />
            )}
          </Space>
          {(r.params || []).map((p, pi) => (
            <Space key={pi} align="baseline">
              <Input size="small" style={{ width: 200 }} placeholder="参数 key" value={p.key || ''}
                onChange={(e) => updateParam(i, pi, { key: e.target.value })} />
              <Input size="small" style={{ width: 240 }} placeholder="值" value={p.value || ''}
                onChange={(e) => updateParam(i, pi, { value: e.target.value })} />
              <DeleteOutlined style={{ color: '#999' }} onClick={() => removeParam(i, pi)} />
            </Space>
          ))}
          <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => addParam(i)}>添加参数键值</Button>
        </Space>
      ))}
      <Button type="dashed" block icon={<PlusOutlined />} onClick={addRow}>添加数据组</Button>
    </Space>
  )
}