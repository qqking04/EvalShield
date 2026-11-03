/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
import { Fragment, useEffect, useState } from 'react'
import {
  Table, Button, Space, Tag, Modal, Form, Input, Select, App, Popconfirm, Card, Alert, InputNumber, Row, Col, Empty, Tooltip, Switch, Upload, Divider,
} from 'antd'
import { PlusOutlined, DeleteOutlined, ReloadOutlined, SearchOutlined, PlayCircleOutlined, RobotOutlined, UploadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import http from '../../api/http'
import { fmtTime } from '../../utils'
import { VISIBILITY_MAP } from '../../constants/enums'

// 数据流场景的步骤动作
const SCENARIO_ACTIONS = [
  { value: 'request', label: '发起请求' },
  { value: 'assert', label: '断言' },
  { value: 'extract', label: '提取变量' },
  { value: 'db_query', label: '数据库查询' },
  { value: 'delay', label: '等待' },
  // P2-08：嵌套结构动作
  { value: 'if', label: '条件分支' },
  { value: 'loop', label: '循环' },
  { value: 'parallel', label: '并行分支' },
]

// 线性动作（沿用原有 config 白名单行为）；if/loop/parallel 为嵌套结构动作
const LINEAR_ACTIONS = ['request', 'assert', 'extract', 'db_query', 'delay']

// P2-08：if 条件运算符（与后端 _COND_OPS 对齐）
const COND_OPS = [
  { value: 'eq', label: '等于' },
  { value: 'neq', label: '不等于' },
  { value: 'contains', label: '包含' },
  { value: 'not_contains', label: '不包含' },
  { value: 'gt', label: '大于' },
  { value: 'lt', label: '小于' },
  { value: 'gte', label: '大于等于' },
  { value: 'lte', label: '小于等于' },
  { value: 'not_empty', label: '非空' },
  { value: 'exists', label: '存在' },
  { value: 'in', label: '属于(in)' },
]
const COND_OP_LABEL = Object.fromEntries(COND_OPS.map((o) => [o.value, o.label]))

// FE-04：每个动作合法的配置字段白名单（切换动作时清空非本动作字段，提交时按此过滤）
const ACTION_CONFIG_KEYS = {
  request: ['method', 'headers', 'body'],
  assert: ['assert_type', 'expected'],
  extract: ['extract_type', 'pattern'],
  db_query: ['sql'],
  delay: ['ms'],
}
const ALL_STEP_CONFIG_KEYS = Object.values(ACTION_CONFIG_KEYS).flat()

// BUG-004（C20）：数据流 DAG 预览 —— 节点=步骤，边=顺序箭头，extract 产物与 {{变量}} 引用标注
const ACTION_META = {
  request: { color: '#13c2c2', label: '请求' },
  extract: { color: '#b37feb', label: '提取' },
  assert: { color: '#fa8c16', label: '断言' },
  db_query: { color: '#52c41a', label: 'DB查询' },
  delay: { color: '#40a9ff', label: '等待' },
  // P2-08：嵌套结构动作（独立配色）
  if: { color: '#eb2f96', label: '条件分支' },
  loop: { color: '#722ed1', label: '循环' },
  parallel: { color: '#fa541c', label: '并行分支' },
}

const arrayLen = (v) => (Array.isArray(v) ? v.length : 0)

// P2-08：DAG 节点摘要（兼容 if/loop/parallel 嵌套动作，缺失子数组不抛错）
const dagSummary = (s) => {
  if (!s || !s.action) return ''
  if (s.action === 'delay') return `${s.ms || 1000}ms`
  if (s.action === 'if') {
    const op = COND_OP_LABEL[s.cond?.op] || s.cond?.op || '等于'
    const right = s.cond?.right === undefined || s.cond?.right === '' ? '' : ` ${s.cond.right}`
    return `${s.cond?.left || '(空)'} ${op}${right}`.trim()
  }
  if (s.action === 'loop') {
    const spec = s.mode === 'over' ? `遍历 {{${s.over || ''}}}` : `重复 ${s.times ?? 1} 次`
    return `${spec}（最多 ${s.max_iter ?? 20}）`
  }
  if (s.action === 'parallel') return `${arrayLen(s.branches)} 个并行分支`
  return s.target || s.method || ''
}

const childActionLabels = (list) => (Array.isArray(list) ? list : [])
  .filter((x) => x && x.action)
  .map((x) => (ACTION_META[x.action] || {}).label || x.action)

function ScenarioDagPreview({ steps = [] }) {
  const valid = (steps || []).filter((s) => s && s.action)
  if (!valid.length) {
    return <Alert type="info" showIcon message="添加步骤后，此处实时展示数据流 DAG 预览（节点→边；extract 产物以 {{变量名}} 标注，可被后续步骤引用）" />
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, background: '#141923', border: '1px solid #253042', borderRadius: 6, padding: 12 }}>
      {valid.map((s, i) => {
        const meta = ACTION_META[s.action] || { color: '#869BAA', label: s.action }
        const isExtract = s.action === 'extract' && s.extract
        const refs = [...String(s.target || '').matchAll(/\{\{([^}]+)\}\}/g)].map((m) => m[1])
        const summary = dagSummary(s)
        const nested = s.action === 'if'
          ? [...childActionLabels(s.then), ...childActionLabels(s.else)]
          : (s.action === 'loop' ? childActionLabels(s.steps) : [])
        return (
          <Fragment key={`${s.action}-${i}`}>
            {i > 0 && <span style={{ color: '#8b97a7', fontSize: 16 }}>→</span>}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '8px 10px', border: `1px solid ${meta.color}`, borderRadius: 6, minWidth: 132, maxWidth: 260 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: meta.color }}>{meta.label} {i + 1}</span>
              {summary && <span style={{ fontSize: 12, color: '#e6ebf0', wordBreak: 'break-all' }}>{summary}</span>}
              {isExtract && <Tag color="purple" style={{ fontSize: 11, marginInlineEnd: 0 }}>提取 {'{{'}{s.extract}{'}}'}</Tag>}
              {s.action === 'if' && (
                <span style={{ fontSize: 11, color: '#ff85c0' }}>then {arrayLen(s.then)} 步 / else {arrayLen(s.else)} 步</span>
              )}
              {s.action === 'loop' && (
                <span style={{ fontSize: 11, color: '#b37feb' }}>循环体 {arrayLen(s.steps)} 步 · 变量 {s.item_var || 'item'}</span>
              )}
              {s.action === 'parallel' && (
                <span style={{ fontSize: 11, color: '#ff9c6e' }}>
                  {Array.isArray(s.branches) ? s.branches.map((b, bi) => `分支${bi + 1}:${arrayLen(b)}`).join(' · ') : '无分支'}
                </span>
              )}
              {nested.length > 0 && <span style={{ fontSize: 11, color: '#8b97a7', wordBreak: 'break-all' }}>↳ {nested.join(' · ')}</span>}
              {refs.length > 0 && (
                <span style={{ fontSize: 11, color: '#b37feb' }}>引用 {refs.map((r) => `{{${r}}}`).join(', ')}</span>
              )}
            </div>
          </Fragment>
        )
      })}
    </div>
  )
}

// 语义合并：target 标签语境化（request→请求路径 / assert→断言路径 / db_query→SQL·表名），delay 由 ConfigFields 提供
const TARGET_LABEL = { request: '请求路径', assert: '断言路径', db_query: 'SQL/表名' }
const TARGET_PLACEHOLDER = {
  request: '如 /api/login',
  assert: '如 .data.code',
  db_query: '如 SELECT … FROM users',
  extract: '如 .data.id',
}

// 根据动作类型渲染结构化 config 字段（P2-4: 替换原来的 JSON TextArea）
function StepConfigFields({ fieldPrefix, action }) {
  if (!action) return <Alert type="info" showIcon message="请先选择动作类型，下方将自动显示对应配置字段" />

  if (action === 'request') {
    return (
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Space wrap>
          <Form.Item name={[...fieldPrefix, 'method']} label="方法" initialValue="GET">
            <Select style={{ width: 110 }} options={[{ value: 'GET', label: 'GET' }, { value: 'POST', label: 'POST' }, { value: 'PUT', label: 'PUT' }, { value: 'DELETE', label: 'DELETE' }, { value: 'PATCH', label: 'PATCH' }]} />
          </Form.Item>
          <Form.Item name={[...fieldPrefix, 'headers']} label="额外请求头" extra="JSON，可选">
            <Input.TextArea rows={2} placeholder={'{"Authorization":"Bearer ..."}'} style={{ maxWidth: 400 }} />
          </Form.Item>
        </Space>
        <Form.Item name={[...fieldPrefix, 'body']} label="请求体" extra="JSON，POST/PUT 常用">
          <Input.TextArea rows={3} placeholder={'{"key":"value"}'} />
        </Form.Item>
      </Space>
    )
  }

  if (action === 'assert') {
    return (
      <Space wrap>
        <Form.Item name={[...fieldPrefix, 'assert_type']} label="断言方式" initialValue="equals">
          <Select style={{ width: 140 }} options={[{ value: 'equals', label: '等于' }, { value: 'contains', label: '包含' }, { value: 'regex', label: '正则匹配' }, { value: 'status', label: 'HTTP 状态码' }]} />
        </Form.Item>
        <Form.Item name={[...fieldPrefix, 'expected']} label="期望值 / 状态码">
          <Input style={{ width: 240 }} placeholder="如 200 或 success" />
        </Form.Item>
      </Space>
    )
  }

  if (action === 'extract') {
    return (
      <Space wrap>
        <Form.Item name={[...fieldPrefix, 'extract_type']} label="提取方式" initialValue="regex">
          <Select style={{ width: 140 }} options={[{ value: 'regex', label: '正则' }, { value: 'jsonpath', label: 'JSONPath' }, { value: 'header', label: '响应头' }]} />
        </Form.Item>
        <Form.Item name={[...fieldPrefix, 'pattern']} label="表达式 / 路径">
          <Input style={{ width: 260 }} placeholder="如 .data.id 或 (\d{6})" />
        </Form.Item>
      </Space>
    )
  }

  if (action === 'db_query') {
    return (
      <Form.Item name={[...fieldPrefix, 'sql']} label="SQL 语句">
        <Input.TextArea rows={3} placeholder={'SELECT id FROM users WHERE name = ?'} style={{ maxWidth: 500 }} />
      </Form.Item>
    )
  }

  if (action === 'delay') {
    return (
      <Form.Item name={[...fieldPrefix, 'ms']} label="等待毫秒数" rules={[{ type: 'number', min: 0, max: 600000 }]} initialValue={1000}>
        <InputNumber style={{ width: 180 }} min={0} step={500} />
      </Form.Item>
    )
  }

  return null
}

// 新建步骤的空白默认值
const emptyStep = () => ({ action: undefined, target: '', extract: '' })

// P2-08：把表单步骤递归序列化为后端 steps（线性动作打包 config，嵌套动作保留子数组）
const serializeStep = (s, idx = 0) => {
  if (!s || !s.action) return null

  if (s.action === 'if') {
    return {
      action: 'if',
      cond: {
        left: s.cond?.left ?? '',
        op: s.cond?.op || 'eq',
        right: s.cond?.right ?? '',
      },
      then: (s.then || []).map((x, i) => serializeStep(x, i)).filter(Boolean),
      else: (s.else || []).map((x, i) => serializeStep(x, i)).filter(Boolean),
    }
  }

  if (s.action === 'loop') {
    const mode = s.mode === 'over' ? 'over' : 'times'
    const node = {
      action: 'loop',
      mode,
      max_iter: s.max_iter ?? 20,
      item_var: s.item_var || 'item',
      steps: (s.steps || []).map((x, i) => serializeStep(x, i)).filter(Boolean),
    }
    if (mode === 'over') node.over = s.over || ''
    else node.times = s.times ?? 1
    return node
  }

  if (s.action === 'parallel') {
    return {
      action: 'parallel',
      fail_fast: s.fail_fast !== false,
      branches: (Array.isArray(s.branches) ? s.branches : []).map(
        (br) => (Array.isArray(br) ? br : []).map((x, i) => serializeStep(x, i)).filter(Boolean),
      ),
    }
  }

  // 线性动作：沿用原有 config 白名单
  const step = {
    action: s.action,
    target: s.target || '',
    extract: s.extract || undefined,
  }
  const cfg = {}
  const allowed = ACTION_CONFIG_KEYS[s.action] || []
  for (const k of allowed) {
    if (s[k] !== undefined && s[k] !== null && s[k] !== '') cfg[k] = s[k]
  }
  for (const k of ALL_STEP_CONFIG_KEYS) {
    if (!allowed.includes(k) && s[k] !== undefined && s[k] !== null && s[k] !== '') {
      console.warn(`[ScenariosTab] 步骤 ${idx + 1} 的配置字段 ${k} 与动作 ${s.action} 不匹配，已剔除`)
    }
  }
  if (Object.keys(cfg).length > 0) {
    step.config = cfg
  } else if (s._raw) {
    const raw = (s._raw || '').trim()
    if (raw) { try { step.config = JSON.parse(raw) } catch { step.config = raw } }
  }
  return step
}

// P2-08：加载场景时把后端 steps 反序列化为表单结构（保留 if/loop/parallel 子数组）
const deserializeStep = (s) => {
  if (!s || !s.action) return null

  if (s.action === 'if') {
    const cond = s.cond && typeof s.cond === 'object' ? s.cond : {}
    return {
      action: 'if',
      cond: { left: cond.left ?? '', op: cond.op || 'eq', right: cond.right ?? '' },
      then: Array.isArray(s.then) ? s.then.map(deserializeStep).filter(Boolean) : [],
      else: Array.isArray(s.else) ? s.else.map(deserializeStep).filter(Boolean) : [],
    }
  }

  if (s.action === 'loop') {
    return {
      action: 'loop',
      mode: s.mode === 'over' || s.over ? 'over' : 'times',
      times: s.times,
      over: s.over || '',
      max_iter: s.max_iter ?? 20,
      item_var: s.item_var || 'item',
      steps: Array.isArray(s.steps) ? s.steps.map(deserializeStep).filter(Boolean) : [],
    }
  }

  if (s.action === 'parallel') {
    return {
      action: 'parallel',
      fail_fast: s.fail_fast !== false,
      branches: Array.isArray(s.branches)
        ? s.branches.map((br) => (Array.isArray(br) ? br.map(deserializeStep).filter(Boolean) : []))
        : [],
    }
  }

  return {
    action: s.action,
    target: s.target || '',
    extract: s.extract || '',
    ...(typeof s.config === 'string' && s.config
      ? (() => { try { return JSON.parse(s.config) } catch { return { _raw: s.config } } })()
      : (s.config && typeof s.config === 'object' ? s.config : {})),
  }
}

// P2-08：提交前的嵌套结构语义校验（返回首个错误的中文提示，无错返回 null）
function validateStepNode(s, label = '步骤') {
  if (!s || !s.action) return null

  if (s.action === 'if') {
    const thenSteps = (s.then || []).filter((x) => x && x.action)
    const elseSteps = (s.else || []).filter((x) => x && x.action)
    if (!thenSteps.length && !elseSteps.length) return `${label}：条件分支至少需要填写一个 then 或 else 子步骤`
    const thenErr = (s.then || []).map((x, i) => validateStepNode(x, `${label} 的 then 第 ${i + 1} 步`)).find(Boolean)
    if (thenErr) return thenErr
    return (s.else || []).map((x, i) => validateStepNode(x, `${label} 的 else 第 ${i + 1} 步`)).find(Boolean) || null
  }

  if (s.action === 'loop') {
    const inner = (s.steps || []).filter((x) => x && x.action)
    if (!inner.length) return `${label}：循环必须包含至少一个循环体步骤`
    const mode = s.mode === 'over' ? 'over' : 'times'
    if (mode === 'times') {
      const t = Number(s.times)
      if (!Number.isInteger(t) || t < 1 || t > 100) return `${label}：循环次数必须为 1~100 的整数`
    } else if (!s.over) {
      return `${label}：遍历模式需填写遍历变量名`
    }
    const mi = Number(s.max_iter)
    if (s.max_iter !== undefined && s.max_iter !== null && (!Number.isInteger(mi) || mi < 1 || mi > 100)) {
      return `${label}：最大迭代次数必须为 1~100 的整数`
    }
    return (s.steps || []).map((x, i) => validateStepNode(x, `${label} 的循环体第 ${i + 1} 步`)).find(Boolean) || null
  }

  if (s.action === 'parallel') {
    const branches = Array.isArray(s.branches) ? s.branches : []
    if (branches.length < 2) return `${label}：并行分支至少需要 2 个分支`
    for (let bi = 0; bi < branches.length; bi += 1) {
      const br = Array.isArray(branches[bi]) ? branches[bi] : []
      if (!br.filter((x) => x && x.action).length) return `${label}：并行的第 ${bi + 1} 个分支为空，请补充步骤`
      const err = br.map((x, i) => validateStepNode(x, `${label} 的并行分支 ${bi + 1} 第 ${i + 1} 步`)).find(Boolean)
      if (err) return err
    }
    return null
  }

  return null
}

function validateStepList(steps) {
  return (steps || []).map((s, i) => validateStepNode(s, `步骤 ${i + 1}`)).find(Boolean) || null
}

// P2-08：递归步骤编辑器 —— 支持 if/loop/parallel 嵌套子步骤（顶部与所有嵌套数组复用）
function StepListEditor({ listName, absPath, steps, depth = 0 }) {
  const form = Form.useFormInstance()
  const list = Array.isArray(steps) ? steps : []

  return (
    <Form.List name={listName}>
      {(fields, { add, remove }) => (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {fields.map((field, idx) => {
            const step = list[idx] || {}
            const action = step.action
            const isLinear = !action || LINEAR_ACTIONS.includes(action)
            return (
              <Card key={field.key} size="small" title={`${depth === 0 ? '步骤' : '子步骤'} ${idx + 1}`}
                extra={<DeleteOutlined style={{ color: '#999' }} onClick={() => remove(field.name)} />}>
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Space wrap>
                    <Form.Item name={[field.name, 'action']} label="动作" rules={[{ required: true, message: '选择动作' }]}>
                      <Select style={{ width: 170 }} options={SCENARIO_ACTIONS} placeholder="选择动作"
                        onChange={(v) => {
                          // FE-04：清空该步骤中不属于新动作的配置字段（extract 变量名仅 extract 动作需要）
                          const allowed = new Set(ACTION_CONFIG_KEYS[v] || [])
                          const clearKeys = ALL_STEP_CONFIG_KEYS.filter((k) => !allowed.has(k))
                          if (v !== 'extract') clearKeys.push('extract')
                          clearKeys.forEach((k) => form.setFieldValue([...absPath, field.name, k], undefined))
                          // P2-08：切到并行时预置 2 个空分支
                          if (v === 'parallel') {
                            const cur = form.getFieldValue([...absPath, field.name, 'branches'])
                            if (!Array.isArray(cur) || cur.length < 2) {
                              form.setFieldValue([...absPath, field.name, 'branches'], [[emptyStep()], [emptyStep()]])
                            }
                          }
                        }} />
                    </Form.Item>
                    {/* 语义合并：target 标签语境化；delay/嵌套动作不显示 target */}
                    {isLinear && action !== 'delay' && (
                      <Form.Item name={[field.name, 'target']} label={TARGET_LABEL[action] || '目标值'}>
                        <Input style={{ width: 240 }} placeholder={TARGET_PLACEHOLDER[action] || '输入目标值'} />
                      </Form.Item>
                    )}
                    {action === 'extract' && (
                      <Form.Item name={[field.name, 'extract']} label="提取变量名">
                        <Input style={{ width: 180 }} placeholder="如 token" />
                      </Form.Item>
                    )}
                  </Space>

                  {/* 线性动作：沿用结构化配置字段 */}
                  {isLinear && <StepConfigFields fieldPrefix={[field.name]} action={action} />}

                  {/* if：条件 + then/else 嵌套子列表 */}
                  {action === 'if' && (
                    <Space direction="vertical" size={6} style={{ width: '100%' }}>
                      <Space wrap>
                        <Form.Item name={[field.name, 'cond', 'left']} label="条件左值" extra="可含 {{变量}}">
                          <Input style={{ width: 200 }} placeholder="如 {{count}}" />
                        </Form.Item>
                        <Form.Item name={[field.name, 'cond', 'op']} label="运算符" initialValue="eq">
                          <Select style={{ width: 130 }} options={COND_OPS} />
                        </Form.Item>
                        <Form.Item name={[field.name, 'cond', 'right']} label="条件右值">
                          <Input style={{ width: 200 }} placeholder="非空/存在 可留空" />
                        </Form.Item>
                      </Space>
                      <Divider orientation="left" plain style={{ margin: '2px 0' }}>then 分支</Divider>
                      <StepListEditor listName={[field.name, 'then']} absPath={[...absPath, field.name, 'then']} steps={step.then} depth={depth + 1} />
                      <Divider orientation="left" plain style={{ margin: '2px 0' }}>else 分支</Divider>
                      <StepListEditor listName={[field.name, 'else']} absPath={[...absPath, field.name, 'else']} steps={step.else} depth={depth + 1} />
                    </Space>
                  )}

                  {/* loop：次数/遍历变量 + 循环体嵌套子列表 */}
                  {action === 'loop' && (
                    <Space direction="vertical" size={6} style={{ width: '100%' }}>
                      <Space wrap>
                        <Form.Item name={[field.name, 'mode']} label="循环模式" initialValue="times">
                          <Select style={{ width: 150 }} options={[{ value: 'times', label: '按次数' }, { value: 'over', label: '遍历变量' }]} />
                        </Form.Item>
                        {(step.mode || 'times') === 'over' ? (
                          <Form.Item name={[field.name, 'over']} label="遍历变量名">
                            <Input style={{ width: 180 }} placeholder="如 items" />
                          </Form.Item>
                        ) : (
                          <Form.Item name={[field.name, 'times']} label="循环次数" initialValue={3}>
                            <InputNumber min={1} max={100} style={{ width: 150 }} />
                          </Form.Item>
                        )}
                        <Form.Item name={[field.name, 'max_iter']} label="最大迭代" initialValue={20}>
                          <InputNumber min={1} max={100} style={{ width: 150 }} />
                        </Form.Item>
                        <Form.Item name={[field.name, 'item_var']} label="元素变量名" initialValue="item">
                          <Input style={{ width: 150 }} placeholder="item" />
                        </Form.Item>
                      </Space>
                      <Divider orientation="left" plain style={{ margin: '2px 0' }}>循环体步骤</Divider>
                      <StepListEditor listName={[field.name, 'steps']} absPath={[...absPath, field.name, 'steps']} steps={step.steps} depth={depth + 1} />
                    </Space>
                  )}

                  {/* parallel：每个分支为一个嵌套子列表（至少 2 个） */}
                  {action === 'parallel' && (
                    <Space direction="vertical" size={6} style={{ width: '100%' }}>
                      <Form.Item name={[field.name, 'fail_fast']} label="快速失败（任一分支失败即终止）" valuePropName="checked" initialValue={true}>
                        <Switch />
                      </Form.Item>
                      <Form.List name={[field.name, 'branches']}>
                        {(branchFields, { add: addBranch, remove: removeBranch }) => (
                          <Space direction="vertical" size={8} style={{ width: '100%' }}>
                            {branchFields.map((bf, bi) => (
                              <Card key={bf.key} size="small" title={`分支 ${bi + 1}`}
                                extra={branchFields.length > 2
                                  ? <DeleteOutlined style={{ color: '#999' }} onClick={() => removeBranch(bf.name)} />
                                  : null}>
                                <StepListEditor listName={[bf.name]} absPath={[...absPath, field.name, 'branches', bf.name]} steps={(step.branches || [])[bi]} depth={depth + 1} />
                              </Card>
                            ))}
                            <Button type="dashed" block icon={<PlusOutlined />} onClick={() => addBranch([emptyStep()])}>
                              添加分支
                            </Button>
                          </Space>
                        )}
                      </Form.List>
                    </Space>
                  )}
                </Space>
              </Card>
            )
          })}
          <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add(emptyStep())}>
            添加步骤
          </Button>
        </Space>
      )}
    </Form.List>
  )
}

export default function ScenariosTab({ onDataChanged, initialProjectId }) {
  const [rows, setRows] = useState([])
  const [projects, setProjects] = useState([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const navigate = useNavigate()

  // P2-08：Playwright 录制导入
  const [importOpen, setImportOpen] = useState(false)
  const [importing, setImporting] = useState(false)
  const [recordText, setRecordText] = useState('')
  const [importForm] = Form.useForm()

  // 新增：筛选 + 分页
  const [projectFilter, setProjectFilter] = useState(initialProjectId || null)
  const [keywordFilter, setKeywordFilter] = useState('')
  const [pagination, setPagination] = useState({ current: 1, pageSize: 10, total: 0 })
  // FE-05：项目环境可用性缓存（project_id → { hasEnv, defaultBaseUrl }）
  const [projectEnvMap, setProjectEnvMap] = useState({})

  const load = (p = pagination, extraParams = {}) => {
    const params = { page: p.current, page_size: p.pageSize, ...extraParams }
    if (!('project_id' in extraParams) && projectFilter) params.project_id = projectFilter
    if (!('keyword' in extraParams)) {
      const kw = (keywordFilter || '').trim()
      if (kw) params.keyword = kw
    }
    http.get('/scenarios', { params })
      .then((d) => {
        const wrapper = d && d.data ? d.data : d
        setRows(wrapper.items || [])
        setPagination((pp) => ({ ...pp, total: wrapper.total || 0 }))
      })
      .catch((e) => { setRows([]); console.warn('[ScenariosTab] load failed', e?.message || e) })
  }

  useEffect(() => {
    load()
    http.get('/projects', { params: { page_size: 100 } }).then((d) => setProjects(d.items || [])).catch((e) => console.warn(`[ScenariosTab]`, e?.message || e))
  }, [])

  // FE-06：父组件项目筛选变化时，重置内部关键词筛选并回到第 1 页
  useEffect(() => {
    if (initialProjectId !== undefined) {
      setProjectFilter(initialProjectId || null)
      setKeywordFilter('')
      const np = { ...pagination, current: 1 }
      setPagination(np)
      // load 读取的是 state，用显式参数覆盖避免闭包旧值
      const params = { page: 1, page_size: np.pageSize }
      if (initialProjectId) params.project_id = initialProjectId
      http.get('/scenarios', { params })
        .then((d) => {
          const wrapper = d && d.data ? d.data : d
          setRows(wrapper.items || [])
          setPagination((pp) => ({ ...pp, total: wrapper.total || 0 }))
        })
        .catch((e) => { setRows([]); console.warn('[ScenariosTab] project switch load failed', e?.message || e) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialProjectId])

  // FE-05：加载项目被测环境（TestEnvironment 新表），判断是否有可用环境
  const loadProjectEnv = async (pid) => {
    try {
      const d = await http.get(`/projects/${pid}/environments`)
      const envs = (d && d.items) || (Array.isArray(d) ? d : [])
      const def = envs.find((e) => e.is_default) || envs[0]
      return { hasEnv: envs.length > 0, defaultBaseUrl: (def && (def.base_url || def.url)) || '' }
    } catch {
      // 拉取失败时按「未知」处理，不阻塞执行（base_url 必填规则仍会兜底）
      return { hasEnv: true, defaultBaseUrl: '' }
    }
  }

  // FE-05：预取当前列表场景所属项目的环境可用性，决定「执行」按钮是否可用
  useEffect(() => {
    const pids = [...new Set((rows || []).map((r) => r.project_id).filter((x) => x != null))]
    const missing = pids.filter((pid) => projectEnvMap[pid] === undefined)
    if (missing.length === 0) return
    let cancelled = false
    Promise.all(missing.map((pid) => loadProjectEnv(pid).then((info) => [pid, info])))
      .then((pairs) => { if (!cancelled) setProjectEnvMap((m) => ({ ...m, ...Object.fromEntries(pairs) })) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, projectEnvMap])

  const hasExtract = (steps = []) => steps.some((s) => s && s.action === 'extract')

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ steps: [{ action: undefined, target: '', extract: '' }] })
    setModalOpen(true)
  }

  const openEdit = async (row) => {
    setEditing(row)
    form.resetFields()
    try {
      const detail = await http.get(`/scenarios/${row.id}`)
      // P2-08：递归反序列化，保留 if/loop/parallel 的嵌套子数组
      const steps = (Array.isArray(detail.steps) ? detail.steps : []).map(deserializeStep).filter(Boolean)
      form.setFieldsValue({
        project_id: detail.project_id ?? row.project_id,
        name: detail.name ?? row.name,
        module: detail.module ?? row.module,
        description: detail.description ?? row.description,
        steps,
        variables: Object.entries(detail.variables || {}).map(([key, value]) => ({ key, value })),
      })
      setModalOpen(true)
    } catch (err) {
      message.error('加载场景详情失败：' + (err?.message || '未知错误'))
    }
  }

  const submit = async () => {
    const values = await form.validateFields()
    // P2-08：嵌套结构语义校验，非法则中止提交（不调用接口）
    const stepError = validateStepList(values.steps)
    if (stepError) {
      message.error(stepError)
      return
    }
    // P2-4/P2-08: 递归序列化 → 后端 steps（线性动作打包 config，嵌套动作保留子数组）
    const steps = (values.steps || []).map((s, idx) => serializeStep(s, idx)).filter(Boolean)

    // 变量定义（数组 [{key,value}]）→ 后端 dict 结构
    const variables = {}
    for (const v of values.variables || []) {
      if (v && v.key) variables[v.key] = v.value ?? ''
    }
    const payload = { ...values, steps, variables }

    if (editing) {
      await http.put(`/scenarios/${editing.id}`, payload)
      message.success('场景已更新')
    } else {
      await http.post('/scenarios', payload)
      message.success('场景创建成功')
    }
    setModalOpen(false)
    load()
    if (typeof onDataChanged === 'function') onDataChanged()
  }

  // P2-08：导入 Playwright 录制
  const SUPPORTED_RECORD_TYPES = new Set(['goto', 'navigate', 'click', 'fill', 'expect', 'assert'])
  const openImport = () => {
    setRecordText('')
    importForm.resetFields()
    setImportOpen(true)
  }
  const handleRecordFile = (file) => {
    const reader = new FileReader()
    reader.onload = () => setRecordText(String(reader.result || ''))
    reader.onerror = () => message.error('读取录制文件失败')
    reader.readAsText(file)
    return false
  }
  const submitImport = async () => {
    const values = await importForm.validateFields()
    if (!recordText.trim()) {
      message.error('请粘贴或上传录制 JSON')
      return
    }
    let actions
    try {
      const parsed = JSON.parse(recordText)
      const arr = Array.isArray(parsed)
        ? parsed
        : (parsed && Array.isArray(parsed.actions) ? parsed.actions : null)
      if (!arr) throw new Error('内容需为数组，或包含 actions 数组的对象')
      actions = arr.filter((it) => {
        if (!it || typeof it !== 'object') return false
        const t = String(it.type || it.action || '').toLowerCase()
        return SUPPORTED_RECORD_TYPES.has(t)
      })
    } catch (e) {
      message.error('录制 JSON 解析失败：' + (e?.message || '格式错误'))
      return
    }
    setImporting(true)
    try {
      const created = await http.post('/scenarios/import-recording', {
        project_id: values.project_id,
        name: values.name || undefined,
        module: values.module || undefined,
        actions,
      })
      const code = created?.code || created?.scenario?.code || ''
      message.success('录制导入成功' + (code ? `，场景编号：${code}` : ''))
      const warnings = created?.warnings
      if (Array.isArray(warnings) && warnings.length) message.warning(warnings.join('；'))
      setImportOpen(false)
      load()
      if (typeof onDataChanged === 'function') onDataChanged()
    } catch (e) {
      console.warn('[ScenariosTab] import recording failed', e?.message || e)
    } finally {
      setImporting(false)
    }
  }

  const remove = async (rowId) => {
    await http.delete(`/scenarios/${rowId}`)
    message.success('场景已删除')
    load()
    if (typeof onDataChanged === 'function') onDataChanged()
  }

  // D-DEL-FE：批量删除 数据流场景
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const batchRemove = async () => {
    const ids = selectedRowKeys
    if (!ids.length) return
    try {
      const r = await http.post('/scenarios/batch-delete', { ids })
      message.success(`已删除 ${r?.deleted ?? ids.length} 条数据流场景`)
      setSelectedRowKeys([]); load()
    } catch (e) { console.warn(e) }
  }

  // 执行场景：填写可选 base_url，POST /scenarios/{id}/run
  const [runOpen, setRunOpen] = useState(false)
  const [runScenario, setRunScenario] = useState(null)
  const [runLoading, setRunLoading] = useState(false)
  const [runForm] = Form.useForm()
  const openRun = async (row) => {
    setRunScenario(row)
    runForm.resetFields()
    // FE-05：回填项目默认环境地址（环境来自 TestEnvironment 新表）
    let info = projectEnvMap[row.project_id]
    if (!info) {
      info = await loadProjectEnv(row.project_id)
      setProjectEnvMap((m) => ({ ...m, [row.project_id]: info }))
    }
    runForm.setFieldsValue({ base_url: info?.defaultBaseUrl || '' })
    setRunOpen(true)
  }

  // FE-05：项目未登记被测环境时，「执行」按钮置灰并提示
  const renderRunButton = (row) => {
    const info = projectEnvMap[row.project_id]
    const hasEnv = info ? info.hasEnv : true
    const btn = (
      <Button type="link" size="small" icon={<PlayCircleOutlined />} disabled={!hasEnv}
        onClick={() => openRun(row)}>执行</Button>
    )
    return hasEnv ? btn : <Tooltip title="项目未配置被测环境"><span>{btn}</span></Tooltip>
  }
  const submitRun = async () => {
    if (!runScenario) return
    const values = await runForm.validateFields()
    setRunLoading(true)
    try {
      const r = await http.post(`/scenarios/${runScenario.id}/run`, { base_url: values.base_url })
      message.success('任务已创建：' + ((r && r.data && r.data.task_no) || '-'))
      setRunOpen(false)
    } catch (e) { console.warn('[ScenariosTab] run failed', e?.message || e) }
    finally { setRunLoading(false) }
  }

  const projectNameOf = (pid) => {
    const p = (projects || []).find((x) => x.id === pid)
    return p ? `${p.code} ${p.name}` : (pid ?? '-')
  }

  const columns = [
    { title: '场景编号', dataIndex: 'code', width: 190 },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '所属项目', dataIndex: 'project_id', width: 200, ellipsis: true, render: (v) => projectNameOf(v) },
    { title: '所属模块', dataIndex: 'module', width: 120, ellipsis: true, render: (v) => v || '-' },
    { title: '来源', dataIndex: 'source', width: 110, render: (v) => {
      if (v === 'MANUAL') return <Tag>手动</Tag>
      if (v === 'AI_GEN') return <Tag color="green">AI 生成</Tag>
      if (v === 'UI_RECORD') return <Tag color="geekblue">UI 录制</Tag>
      return (VISIBILITY_MAP[v] ? <Tag>{VISIBILITY_MAP[v]}</Tag> : (v ? <Tag>{v}</Tag> : '-'))
    } },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
    { title: '步骤数', dataIndex: 'steps_count', width: 90, align: 'center' },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v) => fmtTime(v) },
    {
      title: '操作', width: 180,
      render: (_, row) => (
        <Space size={0}>
          {renderRunButton(row)}
          <Button type="link" size="small" onClick={() => openEdit(row)}>编辑</Button>
          <Popconfirm title="确认删除该场景？" onConfirm={() => remove(row.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // 从 form 实时读取 steps，用于根据 action 动态渲染 config 字段
  const formSteps = Form.useWatch('steps', form) || []

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert type="info" showIcon
        message="数据流场景 = 多步骤接口/数据库编排（request→extract→assert→delay→db_query），步骤间通过 {{变量名}} 传递数据，常用于跨系统全链路测试。"
        description="快速体验：新建场景 → 添加「发起请求」步骤填 URL → 添加「提取变量」用正则/JSONPath 取响应值（如 .data.id）→ 添加「断言」验证结果 → 在变量定义处设置全局变量并可在后续步骤用 {{变量名}} 引用 → 保存后编辑/删除验证。" />
      {/* 新增：筛选 Card */}
      <Card size="small" style={{ marginBottom: 0 }}>
        <Row gutter={[12, 12]} align="middle">
          <Col xs={24} sm={12} md={8}>
            <Select allowClear placeholder="按所属项目筛选" style={{ width: '100%' }} options={(projects || []).map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))}
              value={projectFilter} onChange={(v) => { setProjectFilter(v); setPagination((p) => ({ ...p, current: 1 })) }} />
          </Col>
          <Col xs={24} sm={12} md={8}>
            <Input allowClear placeholder="搜索场景名称/描述" prefix={<SearchOutlined />} style={{ width: '100%' }}
              value={keywordFilter} onChange={(e) => setKeywordFilter(e.target.value)}
              onPressEnter={() => { const np = { ...pagination, current: 1 }; setPagination(np); load(np) }} />
          </Col>
          <Col>
            <Space>
              <Button icon={<SearchOutlined />} type="primary" onClick={() => { const np = { ...pagination, current: 1 }; setPagination(np); load(np) }}>筛选</Button>
              <Button onClick={() => { setProjectFilter(null); setKeywordFilter(''); const np = { ...pagination, current: 1 }; setPagination(np); load(np, { project_id: undefined, keyword: undefined }) }}>重置</Button>
            </Space>
          </Col>
        </Row>
      </Card>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
          <Popconfirm title={`确认批量删除选中的 ${selectedRowKeys.length} 条数据流场景？`} disabled={!selectedRowKeys.length} onConfirm={batchRemove}>
            <Button danger icon={<DeleteOutlined />} disabled={!selectedRowKeys.length}>批量删除{selectedRowKeys.length > 0 ? ` (${selectedRowKeys.length})` : ''}</Button>
          </Popconfirm>
          <Button icon={<UploadOutlined />} onClick={openImport}>导入录制</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建场景</Button>
        </Space>
      </div>
      <Table rowKey="id" columns={columns} dataSource={rows}
        rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
        locale={{ emptyText: <Empty description="暂无数据流场景" image={Empty.PRESENTED_IMAGE_SIMPLE}><Space wrap><Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建场景</Button><Button icon={<RobotOutlined />} onClick={() => navigate('/ai/discover')}>AI 生成</Button></Space></Empty> }}
        pagination={{ ...pagination, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }} onChange={(p) => { setPagination(p); load(p) }} />
      <Modal title={editing ? '编辑数据流场景' : '新建数据流场景'} open={modalOpen} onOk={submit} okText="保存" cancelText="取消" onCancel={() => setModalOpen(false)} destroyOnHidden width={900} styles={{ body: { maxHeight: '72vh', overflowY: 'auto' } }}>
        <Form form={form} layout="vertical">
          <Form.Item name="project_id" label="所属项目" rules={[{ required: true }]}>
            <Select options={(projects || []).map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))} />
          </Form.Item>
          <Form.Item name="name" label="场景名称" rules={[{ required: true }]}>
            <Input placeholder="如：订单提交-支付-回调全链路" />
          </Form.Item>
          <Form.Item name="module" label="所属模块">
            <Input placeholder="如：登录 / 订单，参与功能覆盖矩阵" />
          </Form.Item>
          <Form.Item name="description" label="场景描述">
            <Input.TextArea rows={2} placeholder="数据流场景说明" />
          </Form.Item>

          {/* BUG-004：DAG 流程图预览（随步骤增减实时刷新） */}
          <Form.Item label="数据流预览（DAG）">
            <ScenarioDagPreview steps={formSteps} />
          </Form.Item>

          <Form.Item label="变量定义" extra="全局变量，步骤中可用 {{变量名}} 引用">
            <Form.List name="variables">
              {(fields, { add, remove }) => (
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  {fields.map((field) => (
                    <Space key={field.key} align="baseline">
                      <Form.Item name={[field.name, 'key']} rules={[{ required: true, message: '请输入变量名' }]} noStyle>
                        <Input placeholder="变量名" style={{ width: 180 }} />
                      </Form.Item>
                      <Form.Item name={[field.name, 'value']} noStyle>
                        <Input placeholder="变量值" style={{ width: 260 }} />
                      </Form.Item>
                      <DeleteOutlined style={{ color: '#999' }} onClick={() => remove(field.name)} />
                    </Space>
                  ))}
                  <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add({ key: '', value: '' })}>
                    添加变量
                  </Button>
                </Space>
              )}
            </Form.List>
          </Form.Item>

          <Form.Item label="场景步骤">
            <StepListEditor listName={['steps']} absPath={['steps']} steps={formSteps} depth={0} />
          </Form.Item>

          {hasExtract(formSteps) && <Alert type="info" showIcon message="变量可在后续步骤中以 {{变量名}} 引用" />}
        </Form>
      </Modal>

      <Modal title={`执行场景 - ${runScenario?.name || runScenario?.code || ''}`} open={runOpen} confirmLoading={runLoading}
        okButtonProps={{ disabled: runScenario ? projectEnvMap[runScenario.project_id]?.hasEnv === false : false }}
        okText="创建并执行" cancelText="取消" onOk={submitRun} onCancel={() => setRunOpen(false)} destroyOnHidden width={600}>
        <Form form={runForm} layout="vertical">
          {runScenario && <Alert type="info" showIcon style={{ marginBottom: 12 }} message={`场景：${runScenario.name}（${runScenario.code || ''}）`} />}
          <Form.Item name="base_url" label="被测系统地址 base_url"
            rules={[{ required: true, message: '请填写被测系统地址' }]}
            extra="已自动取项目「环境」页签的默认地址；可临时改为其他地址，正式执行建议在项目环境中维护">
            <Input placeholder="如：https://api.example.com" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="导入 Playwright 录制" open={importOpen} onOk={submitImport} okText="导入" cancelText="取消"
        confirmLoading={importing} onCancel={() => setImportOpen(false)} destroyOnHidden width={640}>
        <Form form={importForm} layout="vertical">
          <Form.Item name="project_id" label="所属项目" rules={[{ required: true, message: '请选择所属项目' }]}>
            <Select options={(projects || []).map((p) => ({ value: p.id, label: `${p.code} - ${p.name}` }))} placeholder="选择目标项目" />
          </Form.Item>
          <Form.Item name="name" label="场景名称（可选）">
            <Input placeholder="留空则自动生成" />
          </Form.Item>
          <Form.Item name="module" label="所属模块（可选）">
            <Input placeholder="如：登录 / 订单" />
          </Form.Item>
          <Form.Item label="录制 JSON" extra="支持顶层数组，或包含 actions 数组的对象；支持 goto/click/fill/expect 等动作">
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Upload accept=".json" maxCount={1} showUploadList={false} beforeUpload={handleRecordFile}>
                <Button icon={<UploadOutlined />}>选择 JSON 文件</Button>
              </Upload>
              <Input.TextArea rows={8} value={recordText} onChange={(e) => setRecordText(e.target.value)}
                placeholder='粘贴录制 JSON，如 [{"type":"goto","url":"/login"},{"type":"click","selector":"#submit"}]' />
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
