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
import { PRECONDITION_KINDS } from './caseSchemas'

// FE-5 前置条件编辑器（受控 value/onChange）
// 行 { kind 下拉, desc }，可增删；desc 支持 {{var}} 变量引用
export default function PreconditionEditor({ value = [], onChange }) {
  const rows = Array.isArray(value) ? value : []
  const update = (i, patch) => onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  const removeRow = (i) => onChange(rows.filter((_, idx) => idx !== i))
  const addRow = () => onChange([...rows, { kind: undefined, desc: '' }])

  return (
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      {rows.map((r, i) => (
        <Space key={i} align="baseline">
          <Select style={{ width: 180 }} placeholder="种类" options={PRECONDITION_KINDS} value={r.kind}
            onChange={(v) => update(i, { kind: v })} />
          <Input style={{ width: 380 }} placeholder="描述，支持 {{var}} 变量" value={r.desc || ''}
            onChange={(e) => update(i, { desc: e.target.value })} />
          <DeleteOutlined style={{ color: '#999' }} onClick={() => removeRow(i)} />
        </Space>
      ))}
      <Button type="dashed" block icon={<PlusOutlined />} onClick={addRow}>添加前置条件</Button>
    </Space>
  )
}