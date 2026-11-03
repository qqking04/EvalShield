/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Button, Card, Divider, Input, InputNumber, Select, Space, Typography } from 'antd'
import { DeleteOutlined, PlusOutlined, VideoCameraOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { UI_ACTIONS } from './caseSchemas'
import AssertionRows from './AssertionRows'
import TermTooltip from '../common/TermTooltip'

const { Text } = Typography
const TEAL = '#13c2c2'

// FE-2 步骤编辑器（受控 value/onChange）
// 每行步骤 UI 结构：{ action, target, value, timeout, assertions, extract }
// 每步支持「断言块」折叠展开区 +「提取变量」区
export default function StepEditor({ value = [], onChange }) {
  const steps = Array.isArray(value) ? value : []
  const update = (idx, patch) => onChange(steps.map((s, i) => (i === idx ? { ...s, ...patch } : s)))
  const removeStep = (idx) => onChange(steps.filter((_, i) => i !== idx))
  const addStep = () => onChange([
    ...steps,
    { action: undefined, target: '', value: '', timeout: 10000, assertions: [], extract: undefined },
  ])

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      {steps.map((s, idx) => (
        <StepCard key={idx} idx={idx} step={s} steps={steps} onChange={onChange} onRemove={() => removeStep(idx)} update={update} />
      ))}
      <Space style={{ width: '100%' }}>
        <Button type="dashed" icon={<PlusOutlined />} onClick={addStep} style={{ flex: 1 }}>添加步骤</Button>
        <Link to="/recordings" style={{ marginLeft: 8 }}>
          <Button icon={<VideoCameraOutlined />}>录制步骤</Button>
        </Link>
      </Space>
    </Space>
  )
}

function StepCard({ idx, step, steps, onChange, onRemove, update }) {
  // 已提取变量集合（本项目内所有 "extract.var"）
  const extractedVars = (steps || [])
    .map((s) => s?.extract?.var)
    .filter((v) => v && String(v).trim())
  const value = step.value || ''
  const varRefs = (value.match(/\{\{\s*([\w.]+)\s*\}\}/g) || []).map((m) => m.replace(/[{}]/g, '').trim())
  const missing = varRefs.filter((v) => !extractedVars.includes(v))

  return (
    <Card size="small" style={{ background: '#0f141b', border: `1px solid #1f2833` }}
      title={
        <Space>
          <Text type="secondary">步骤 {idx + 1}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>共 {step.timeout || step.timeout === 0 ? `${step.timeout}ms` : '—' } 超时</Text>
        </Space>
      }
      extra={<DeleteOutlined style={{ color: '#999' }} onClick={onRemove} />}
    >
      <Space wrap align="baseline" style={{ marginBottom: 8 }}>
        <Select style={{ width: 190 }} placeholder="动作" options={UI_ACTIONS} value={step.action}
          onChange={(v) => update(idx, { action: v })} />
        <Input style={{ width: 190 }} placeholder="选择器/地址" value={step.target || ''}
          onChange={(e) => update(idx, { target: e.target.value })} />
        <Input style={{ width: 160 }} placeholder="值/断言文本" value={value}
          onChange={(e) => update(idx, { value: e.target.value })} />
        <InputNumber style={{ width: 110 }} placeholder="超时ms" min={0} step={1000} value={step.timeout}
          onChange={(v) => update(idx, { timeout: v })} />
      </Space>
      {missing.length > 0 && (
        <div style={{ color: '#ff4d4f', fontSize: 12, marginBottom: 8 }}>
          <Text style={{ color: '#ff4d4f' }}>⚠️ 变量未在提取变量中定义：{missing.join('、')}（如需引用，请在提取区域先定义）</Text>
        </div>
      )}
      <Divider style={{ margin: '8px 0' }} />
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <ExtractRow step={step} update={(patch) => update(idx, patch)} />
      </Space>
      <div style={{ marginTop: 10, borderLeft: `3px solid ${TEAL}`, paddingLeft: 10 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          <TermTooltip term="断言" explain="预期输出的自动校验" example="响应里 $.code 应等于 0，即预期输出为 0">
            步骤断言
          </TermTooltip>
        </Text>
        <div style={{ marginTop: 6 }}>
          <AssertionRows value={step.assertions || []} size="small"
            onChange={(rows) => update(idx, { assertions: rows })} />
        </div>
      </div>
    </Card>
  )
}

function ExtractRow({ step, update }) {
  const ex = step.extract || {}
  return (
    <div>
      <Text type="secondary" style={{ fontSize: 12 }}>提取变量</Text>
      <Space align="baseline" style={{ display: 'flex', marginTop: 4 }}>
        <Input size="small" style={{ width: 140 }} placeholder="变量名，如 token" value={ex.var || ''}
          onChange={(e) => update({ extract: { ...ex, var: e.target.value } })} />
        <Select size="small" style={{ width: 130 }} placeholder="来源"
          options={[{ value: 'page', label: '页面' }, { value: 'response', label: '响应' }]}
          value={ex.from} onChange={(v) => update({ extract: { ...ex, from: v } })} />
        <Input size="small" style={{ width: 180 }} placeholder="JSON 路径 / 选择器" value={ex.path || ''}
          onChange={(e) => update({ extract: { ...ex, path: e.target.value } })} />
      </Space>
    </div>
  )
}