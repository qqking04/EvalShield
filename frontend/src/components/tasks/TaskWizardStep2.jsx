/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// U8-1：新建/编辑任务向导 — Step 2「配参数」（自 pages/Tasks.jsx 抽出，行为零变更）
// 含原 renderEngineParams 动态参数渲染逻辑
import { Alert, Collapse, Form, Input, InputNumber, Select, Space, Switch, Tag, Tooltip } from 'antd'
import { FileDoneOutlined, GlobalOutlined } from '@ant-design/icons'
import { ENGINE_NAME_MAP } from '../../constants/enums'
import { AI_EVAL_ENGINES, getEngineParams, makeNumberValidator, targetKeyOf } from './engineParams'

// ---------- 辅助：渲染引擎参数分组 ----------
function renderEngineParams(engineCode, ctx) {
  const {
    form, navigate, engines, scenarios, modelConfigs, evalSets, targets,
    selectedProjectId, filteredCases, estimateEngineBudget,
  } = ctx
  const params = getEngineParams(engineCode, engines)
  if (!params || params.length === 0) {
    return <Alert type="info" showIcon message="该引擎无额外参数，将使用默认配置执行" />
  }

  const rows = params.map((p) => {
    const formKey = `config__${engineCode}__${p.key}`
    const rules = []
    const isTargetField = p.key === 'target_code' || p.key === 'target' || p.type === 'target'
    // v2.0 P5：多轮引擎的被测系统强制必填（红色星号 + 表单校验）
    const forcedRequired = p.required || (engineCode === 'MULTI_TURN_TEST' && isTargetField)
    if (forcedRequired) rules.push({ required: true, message: `${p.label}不能为空` })
    if (p.type === 'number') rules.push(makeNumberValidator(p.min, p.max))

    if (p.type === 'case_ids') {
      return (
        <Form.Item key={formKey} name={formKey} label={p.label} rules={rules}>
          <Select
            mode="multiple"
            allowClear
            placeholder={selectedProjectId ? '选择关联用例' : '请先选择项目'}
            disabled={!selectedProjectId}
            optionFilterProp="label"
            options={filteredCases.map((c) => ({ value: c.id, label: `${c.case_no || c.id} ${c.title || ''}` }))}
            suffixIcon={<FileDoneOutlined />}
          />
        </Form.Item>
      )
    }
    if (p.type === 'scenario') {
      return (
        <Form.Item key={formKey} name={formKey} label={p.label} rules={rules} extra={!selectedProjectId ? '请先在上方选择所属项目' : ''}>
          <Select
            allowClear
            placeholder={selectedProjectId ? '选择数据流场景' : '请先选择项目'}
            disabled={!selectedProjectId}
            options={scenarios.map((s) => ({ value: s.id, label: `${s.name || s.id}` }))}
          />
        </Form.Item>
      )
    }
    if (p.type === 'model_gateway') {
      return (
        <Form.Item key={formKey} name={formKey} label={p.label} rules={rules}>
          <Select
            allowClear
            placeholder="选择模型网关"
            options={modelConfigs.map((m) => ({
              value: m.code,
              label: `${m.name || m.code} (${m.model || m.provider || ''})`,
            }))}
          />
        </Form.Item>
      )
    }
    if (p.type === 'eval_set') {
      // §6.4：选项按 schema.category 过滤；MULTI_TURN_TEST 用 ['MULTI_TURN','MULTITURN'] 双值（F1 前端侧）
      let cats = p.category ? (Array.isArray(p.category) ? p.category : [p.category]) : null
      if (engineCode === 'MULTI_TURN_TEST' && cats && cats.includes('MULTI_TURN') && !cats.includes('MULTITURN')) cats = cats.concat('MULTITURN')
      if (engineCode === 'MULTI_TURN_TEST' && cats && cats.includes('MULTITURN') && !cats.includes('MULTI_TURN')) cats = cats.concat('MULTI_TURN')
      if (engineCode === 'MULTI_TURN_TEST' && !cats) cats = ['MULTI_TURN', 'MULTITURN']
      const opts = (cats ? evalSets.filter((e) => cats.includes(e.category)) : evalSets)
        .map((e) => ({ value: e.id, label: `${e.name || e.id}${e.category ? `（${e.category}）` : ''}` }))
      return (
        <Form.Item key={formKey} name={formKey} label={p.label} rules={rules}
          extra={cats ? `仅显示 ${cats.join(' / ')} 类评测集` : undefined}>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="选择评测集"
            options={opts}
            onChange={() => estimateEngineBudget(engineCode)}
          />
        </Form.Item>
      )
    }
    if (p.type === 'target') {
      // §6.4：被测系统下拉（含「不配置=内置模型演示」空选项）+ 管理链接
      return (
        <Form.Item
          key={formKey}
          name={formKey}
          label={p.label}
          rules={rules}
          extra={(
            <Space size={8}>
              <span>留空 = 不配置被测系统，测的是平台内置模型（INTERNAL_DEMO）</span>
              <a onClick={() => navigate('/models?tab=targets')}>管理被测系统</a>
            </Space>
          )}
        >
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="不配置 = 内置模型演示"
            options={targets.map((t) => ({
              value: t.code,
              label: `${t.name}（${t.code}）｜${t.target_type === 'LLM_API' ? '大模型API' : t.target_type === 'APP_API' ? '应用端点' : '内置模型(演示)'}`,
            }))}
            onChange={() => estimateEngineBudget(engineCode)}
          />
        </Form.Item>
      )
    }
    if (p.type === 'model_config') {
      // §6.4：判定模型下拉，按 schema.usage 过滤（无 usage 字段的旧配置视为 CHAT）
      const usage = p.usage || 'CHAT'
      const opts = modelConfigs
        .filter((m) => (m.usage || 'CHAT') === usage)
        .map((m) => ({ value: m.code, label: `${m.name || m.code}（${m.model || m.provider || ''}｜${usage}）` }))
      return (
        <Form.Item key={formKey} name={formKey} label={p.label} rules={rules} extra={`仅列出用途为 ${usage} 的启用模型`}>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder={usage === 'EMBEDDING' ? '选择向量模型' : '选择判定模型'}
            options={opts}
            onChange={() => estimateEngineBudget(engineCode)}
          />
        </Form.Item>
      )
    }
    if (p.type === 'select') {
      const opts = (p.options || []).map((o) => (typeof o === 'string' ? { value: o, label: o } : o))
      return (
        <Form.Item key={formKey} name={formKey} label={p.label} rules={rules} initialValue={p.default}>
          <Select allowClear options={opts} />
        </Form.Item>
      )
    }
    if (p.type === 'boolean') {
      return (
        <Form.Item key={formKey} name={formKey} label={p.label} valuePropName="checked" initialValue={p.default}>
          <Switch />
        </Form.Item>
      )
    }
    if (p.type === 'textarea') {
      return (
        <Form.Item key={formKey} name={formKey} label={p.label} rules={rules}>
          <Input.TextArea rows={3} placeholder={`请输入 ${p.label}`} />
        </Form.Item>
      )
    }
    if (p.type === 'number') {
      return (
        <Form.Item
          key={formKey}
          name={formKey}
          label={p.label}
          rules={rules}
          initialValue={p.default}
          extra={(p.min != null || p.max != null)
            ? `范围 ${p.min} ~ ${p.max}${p.default !== undefined ? `，默认 ${p.default}` : ''}`
            : (p.default !== undefined ? `默认 ${p.default}` : undefined)}
        >
          <InputNumber style={{ width: '100%' }} min={p.min} max={p.max} />
        </Form.Item>
      )
    }
    if (p.type === 'auth') {
      // P1-1: 结构化鉴权辅助 — 先选模式，自动填 JSON 模板
      const authModeSelect = (
        <div style={{ marginBottom: 8 }}>
          <span style={{ color: '#8ba3b5', fontSize: 12, marginRight: 8 }}>快捷模式：</span>
          <Select
            size="small"
            style={{ width: 200 }}
            allowClear
            placeholder="选择后自动填充模板"
            onChange={(mode) => {
              if (!mode) return
              const templates = {
                BEARER: { bearer: 'eyJhbGciOi...' },
                BASIC: { basic_user: 'admin', basic_pass: 'password' },
                COOKIE: { cookies: 'session=abc123; tenant=t001' },
                AUTO_LOGIN: {
                  login_url: 'http://your-app.com/login',
                  username: 'admin',
                  password: '123456',
                  username_selector: 'input[name="user"]',
                  password_selector: 'input[type="password"]',
                  login_button_selector: 'button[type="submit"]',
                  captcha_mode: 'skip',
                  post_login_wait: 2000,
                },
                CUSTOM_HEADERS: { custom_headers: { 'X-Request-ID': 'abc', Authorization: 'Bearer ...' } },
              }
              const next = JSON.stringify(templates[mode], null, 2)
              form.setFieldValue(formKey, next)
            }}
            options={[
              { value: 'BEARER', label: 'Bearer Token' },
              { value: 'BASIC', label: 'Basic Auth' },
              { value: 'COOKIE', label: 'Cookie 字符串' },
              { value: 'AUTO_LOGIN', label: 'UI 自动登录' },
              { value: 'CUSTOM_HEADERS', label: '自定义 Headers' },
            ]}
          />
          <span style={{ color: '#869BAA', fontSize: 11, marginLeft: 8 }}>
            选一个自动填模板，再改具体值
          </span>
        </div>
      )
      const authHelp = (
        <div style={{ maxWidth: 520, whiteSpace: 'pre-wrap', fontSize: 12 }}>
{`支持以下字段（任选其一即可）：

Bearer Token（优先级最高）：
  {"bearer": "eyJhbGciOi..."}

Basic Auth：
  {"username": "admin", "password": "pass"}

Cookie 字符串：
  {"cookies": "session=abc123; tenant=t001"}

自定义登录（仅 UI_TEST 自动登录）：
  {"login_url": "http://xxx.com/login",
   "username": "admin",
   "password": "123456"}

额外请求头（API/UI 都自动带）：
  {"custom_headers": {"X-Request-ID": "abc"}}`}
        </div>
      )
      return (
        <>
          <Form.Item key={`${formKey}-label`} label={p.label} extra={p.tip}>
            {authModeSelect}
          </Form.Item>
          <Form.Item
            key={formKey}
            name={formKey}
            label={<Tooltip title={authHelp} placement="topLeft">鉴权 JSON 配置</Tooltip>}
            style={{ marginTop: -8 }}
          >
            <Input.TextArea
              rows={3}
              placeholder={'选择上方快捷模式自动填充，或手动粘贴 JSON'}
            />
          </Form.Item>
        </>
      )
    }
    // 普通文本输入
    return (
      <Form.Item key={formKey} name={formKey} label={p.label} rules={rules}>
        <Input placeholder={`请输入 ${p.label}`} prefix={p.key.includes('url') || p.key.includes('base_url') || p.key === 'target' ? <GlobalOutlined /> : null} />
      </Form.Item>
    )
  })
  return rows
}

export default function TaskWizardStep2({
  // 注：formTick 由父级 onValuesChange 递增驱动父组件重渲染，本组件随之取到最新表单值
  form,
  navigate,
  engines,
  scenarios,
  modelConfigs,
  evalSets,
  targets,
  selectedProjectId,
  filteredCases,
  budgetMap,
  selectedEngines,
  estimateEngineBudget,
}) {
  const selectedEnginesArr = selectedEngines || []
  const ctx = {
    form, navigate, engines, scenarios, modelConfigs, evalSets, targets,
    selectedProjectId, filteredCases, estimateEngineBudget,
  }
  return (
    <>
      {/* v2.0 P5（BUG-03）：多轮引擎使用说明前置引导 */}
      {selectedEnginesArr.includes('MULTI_TURN_TEST') && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="多轮引擎使用说明"
          description="多轮引擎用于测试被测客服/对话系统的回归测试，必须绑定真实target。请确保已配置被测系统。"
        />
      )}
      {/* §6.4 成本预估 + INTERNAL_DEMO 提示（BUG-06：Alert 标题"成本预估"，4行信息） */}
      {selectedEnginesArr.some((e) => AI_EVAL_ENGINES.includes(e)) && (
        <Space direction="vertical" size={8} style={{ width: '100%', marginBottom: 12 }}>
          {selectedEnginesArr.filter((e) => AI_EVAL_ENGINES.includes(e)).map((eng) => {
            const b = budgetMap[eng]
            const targetCode = form.getFieldValue(targetKeyOf(eng, engines))
            return (
              <div key={eng}>
                {b === 'loading' && <Alert type="info" showIcon message={`${ENGINE_NAME_MAP[eng] || eng}：成本预估中...`} />}
                {b && b !== 'loading' && (
                  <Alert
                    type="info"
                    showIcon
                    message={`成本预估 — ${ENGINE_NAME_MAP[eng] || eng}`}
                    description={
                      <div style={{ lineHeight: 1.8 }}>
                        <div>样本数量：{b.item_count ?? '-'} 条</div>
                        <div>预计 LLM 调用：≈ <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }}>{b.calls ?? '-'}</span> 次</div>
                        <div>预计成本：≈ <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }}>¥{b.estimated_cost != null ? Number(b.estimated_cost).toFixed(2) : '-'}</span>（按判定模型单价）</div>
                        <div>预计耗时：≈ <span style={{ fontFamily: 'JetBrains Mono, Consolas, monospace' }}>{b.estimated_minutes ?? '-'} 分钟</span></div>
                      </div>
                    }
                  />
                )}
                {!targetCode && (
                  <Alert
                    type="warning"
                    showIcon
                    style={{ marginTop: 6 }}
                    message={`${ENGINE_NAME_MAP[eng] || eng}：未配置被测系统，当前测的是平台内置模型`}
                  />
                )}
              </div>
            )
          })}
        </Space>
      )}
      {selectedEnginesArr.length > 0 ? (
        <Form.Item label={`引擎参数（按所选引擎动态渲染）— 所选 ${selectedEnginesArr.length} 个引擎共享同一份 config`}
          extra={selectedEnginesArr.length > 1 ? <span style={{ color: '#faad14' }}>⚠️ 多引擎同 key 参数（如 base_url）后填覆盖前填，请确认下方值是期望的</span> : null}>
          <Collapse defaultActiveKey={selectedEnginesArr}
            items={selectedEnginesArr.map((eng) => ({
              key: eng,
              label: <span><Tag color="blue">{eng}</Tag><span style={{ marginLeft: 6 }}>{ENGINE_NAME_MAP[eng] || eng} 参数配置</span></span>,
              children: <Space direction="vertical" size={12} style={{ width: '100%' }}>{renderEngineParams(eng, ctx)}</Space>,
            }))}
          />
        </Form.Item>
      ) : (
        <Alert type="info" showIcon message="请先返回上一步选择引擎" />
      )}
    </>
  )
}
