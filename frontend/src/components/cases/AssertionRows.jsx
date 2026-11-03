/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Button, Input, Select, Space } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { ASSERT_OPS } from './caseSchemas'

// 共享断言块编辑器（受控）：行 { path, op, expected, note }
// 用于 UI/API 用例步骤断言、全局断言集、ApiCaseEditor 断言列表
export default function AssertionRows({ value = [], onChange, size }) {
  const rows = Array.isArray(value) ? value : []
  const update = (idx, patch) => onChange(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  const removeRow = (idx) => onChange(rows.filter((_, i) => i !== idx))
  const addRow = () => onChange([...rows, { path: '', op: undefined, expected: '', note: '' }])

  return (
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      {rows.map((r, i) => (
        <Space key={i} align="baseline" style={{ display: 'flex', flexWrap: 'wrap', rowGap: 6 }}>
          <Input size={size} style={{ width: 180 }} placeholder="路径，如 data.status" value={r.path || ''}
            onChange={(e) => update(i, { path: e.target.value })} />
          <Select size={size} style={{ width: 180 }} placeholder="操作符" options={ASSERT_OPS} value={r.op}
            onChange={(v) => update(i, { op: v })} />
          <Input size={size} style={{ width: 150 }} placeholder="期望值" value={r.expected || ''}
            onChange={(e) => update(i, { expected: e.target.value })} />
          <Input size={size} style={{ width: 110 }} placeholder="备注" value={r.note || ''}
            onChange={(e) => update(i, { note: e.target.value })} />
          <DeleteOutlined style={{ color: '#999' }} onClick={() => removeRow(i)} />
        </Space>
      ))}
      <Button size={size} type="dashed" block icon={<PlusOutlined />} onClick={addRow}>添加断言</Button>
    </Space>
  )
}
