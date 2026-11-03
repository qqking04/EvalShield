/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// ---------- 引擎参数定义（U8-1：自 pages/Tasks.jsx 迁出，行为零变更） ----------
// auth/login_credentials 说明：
//   后端 Engine 会读取 config.auth dict，支持：
//   {
//     bearer / token / access_token:   string   Bearer Token（互斥，优先级最高）
//     username + password:             string   Basic Auth（或 UI 自动登录）
//     basic_user + basic_pass:         string   Basic Auth（显式写法）
//     cookies:                          str|dict  Cookie（"k1=v1; k2=v2" 或 {k:v}）
//     custom_headers:                  dict     额外请求头（所有 API/UI 请求自动带上）
//     --- 仅 UI_TEST 支持 ---
//     login_url:                        string   被测系统登录页 URL（配合 username/password 自动生成登录步骤）
//     username_selector / password_selector / login_button_selector: string  自定义选择器（不填用默认）
//     post_login_wait:                  number   登录后等待毫秒数（默认 2000）
//     pre_login_steps:                  array   自定义前置步骤（覆盖自动生成）
//   }
export const AUTH_TIP = '点击"登录 / 鉴权"输入 Bearer Token、Basic 账号密码、Cookie 或自动登录凭据'

// 引擎 → 用例 category 映射：选了该引擎就只拉该 category 的 case
// PERF_TEST / LOCUST_PERF / DATA_QUALITY 用 API/UI/DATAFLOW 类 case
// AI 安全引擎（HALLUCINATION/REDTEAM/RAG/ETHICS/PROMPT_INJECTION/PRIVILEGE_ESCALATION/MEMORY_LEAKAGE/MULTI_TURN）走 eval_set_id（Step 2 配置），
// 但 Step 3 仍允许关联同 category 的 case 做补充测试
export const ENGINE_CATEGORY_MAP = {
  UI_TEST:        ['UI'],
  API_TEST:       ['API'],
  PERF_TEST:      ['PERFORMANCE', 'API', 'UI'],
  LOCUST_PERF:    ['API', 'UI'],
  SECURITY_TEST:  ['SECURITY'],
  DATAFLOW_TEST:  ['DATAFLOW'],
  DATA_QUALITY:   ['DATAFLOW'],
  HALLUCINATION_TEST: ['HALLUCINATION'],
  REDTEAM_TEST:   ['REDTEAM'],
  RAG_TEST:       ['RAG'],
  ETHICS_TEST:    ['ETHICS'],
  MULTI_TURN_TEST: ['MULTI_TURN', 'MULTITURN'],
  PROMPT_INJECTION: ['SECURITY'],
  PRIVILEGE_ESCALATION: ['SECURITY'],
  MEMORY_LEAKAGE: ['SECURITY'],
  EVAL_ENGINE:    ['EVAL'],
  // 修复 2026-09-25 BUG-5：原空数组 [] 是 truthy，导致 needsTaskCaseIds 为 true
  // 但 requiredCategories 收集不到任何类别，filteredCases 回退为全部 11 类用例
  // → 改成 null（falsy），needsTaskCaseIds 为 false，正确隐藏 case_ids 字段
  CASE_GEN:       null,    // 工程化引擎，生成用例，不关联业务用例
  SELF_HEAL:      null,    // 工程化引擎，自愈失败用例，不关联业务用例
  DEFECT_PREDICT: null,    // 工程化引擎，预测缺陷，不关联业务用例
}

export const ENGINE_PARAMS = {
  UI_TEST: [
    { key: 'base_url', label: '被测系统地址', required: true },
    { key: 'auth', label: '登录 / 鉴权', type: 'auth', tip: AUTH_TIP },
  ],
  API_TEST: [
    { key: 'base_url', label: '被测系统地址', required: true },
    { key: 'auth', label: '全局鉴权（Bearer/Cookie/Headers）', type: 'auth', tip: AUTH_TIP },
  ],
  PERF_TEST: [
    { key: 'url', label: '压测目标地址', required: true },
    { key: 'concurrency', label: '并发数', type: 'number', min: 1, max: 10000, default: 10 },
    { key: 'total_requests', label: '总请求数', type: 'number', min: 1, max: 1000000, default: 100 },
    { key: 'ramp_up_seconds', label: '爬坡时间（秒）', type: 'number', min: 0, max: 3600, default: 1 },
    { key: 'p95_limit_ms', label: 'P95 延迟上限（ms）', type: 'number', min: 1, max: 600000, default: 500 },
    { key: 'target_qps', label: '目标 QPS', type: 'number', min: 0, max: 100000, default: 0 },
  ],
  DATAFLOW_TEST: [
    { key: 'scenario_id', label: '关联数据流场景', type: 'scenario', required: true },
    { key: 'base_url', label: '被测系统地址', required: true },
    { key: 'auth', label: '全局鉴权（Bearer/Cookie/Headers）', type: 'auth', tip: AUTH_TIP },
  ],
  HALLUCINATION_TEST: [
    { key: 'model_gateway', label: '模型网关', type: 'model_gateway', required: true },
    { key: 'eval_set_id', label: '关联评测集', type: 'eval_set', required: true },
  ],
  REDTEAM_TEST: [
    { key: 'model_gateway', label: '模型网关', type: 'model_gateway', required: true },
    { key: 'eval_set_id', label: '关联评测集', type: 'eval_set', required: true },
  ],
  RAG_TEST: [
    { key: 'model_gateway', label: '模型网关', type: 'model_gateway', required: true },
    { key: 'eval_set_id', label: '关联评测集', type: 'eval_set', required: true },
  ],
  ETHICS_TEST: [
    { key: 'model_gateway', label: '模型网关', type: 'model_gateway', required: true },
    { key: 'eval_set_id', label: '关联评测集', type: 'eval_set', required: true },
  ],
  MULTI_TURN_TEST: [
    { key: 'model_gateway', label: '模型网关', type: 'model_gateway', required: true },
    { key: 'eval_set_id', label: '关联评测集', type: 'eval_set', required: true },
  ],
  PROMPT_INJECTION: [
    { key: 'model_gateway', label: '模型网关', type: 'model_gateway', required: true },
    { key: 'target', label: '被测系统地址', required: true },
  ],
  PRIVILEGE_ESCALATION: [
    { key: 'model_gateway', label: '模型网关', type: 'model_gateway', required: true },
    { key: 'target', label: '被测系统地址', required: true },
  ],
  MEMORY_LEAKAGE: [
    { key: 'model_gateway', label: '模型网关', type: 'model_gateway', required: true },
    { key: 'target', label: '被测系统地址', required: true },
  ],
  CASE_GEN: [
    { key: 'model_gateway', label: '模型网关', type: 'model_gateway' },
    { key: 'case_count', label: '生成用例数量', type: 'number', min: 1, max: 50, default: 10 },
  ],
  SELF_HEAL: [
    { key: 'retry_limit', label: '自愈重试轮数', type: 'number', min: 0, max: 5, default: 2 },
  ],
  DEFECT_PREDICT: [], // 无参数
  // 优化二新增引擎（LOCAL fallback，后端 params_schema 优先）
  LOCUST_PERF: [
    { key: 'target_host', label: '被测服务地址', required: true },
    { key: 'scenario', label: '压测场景', required: true, type: 'select', options: ['health_check','echo','slow','status_200','status_404','status_500','chain','bearer_protected','basic_protected','cookie_protected','form_post','json_post','llm_chat'], default: 'health_check' },
    { key: 'users', label: '并发用户数', type: 'number', default: 10 },
    { key: 'spawn_rate', label: '启动速率(个/秒)', type: 'number', default: 1 },
    { key: 'run_time', label: '运行时长', default: '30s' },
    { key: 'auth_mode', label: '鉴权方式', type: 'select', options: ['NONE','BEARER','BASIC','COOKIE'], default: 'NONE' },
    { key: 'bearer_token', label: 'Bearer Token', type: 'password' },
    { key: 'is_llm', label: 'LLM 成本估算', type: 'boolean', default: false },
    { key: 'llm_cost_per_1k_tokens', label: '每千 token 成本(USD)', type: 'number', default: 0.002 },
  ],
  DATA_QUALITY: [
    { key: 'source_type', label: '数据源类型', required: true, type: 'select', options: ['CSV','DB_TABLE','EVAL_DATASET'], default: 'CSV' },
    { key: 'source_ref', label: '数据源路径/表名', required: true },
    { key: 'suite', label: '期望套件(JSON 数组)', required: true, type: 'textarea' },
    { key: 'severity', label: '严重级别', type: 'select', options: ['STRICT','NORMAL','LOOSE'], default: 'STRICT' },
  ],
  // 安全报告补全 P1：7 个安全检测引擎（LOCAL fallback，后端 params_schema 优先）
  HTTP_SECURITY_HEADERS: [
    { key: 'base_url', label: '被测系统地址', required: true },
    { key: 'timeout_seconds', label: '超时（秒）', type: 'number', default: 15 },
  ],
  TLS_CHECK: [
    { key: 'base_url', label: '被测系统地址（https://）', required: true },
    { key: 'timeout_seconds', label: '超时（秒）', type: 'number', default: 10 },
  ],
  STATIC_SECRET_SCAN: [
    { key: 'base_url', label: '被测系统地址', required: true },
    { key: 'timeout_seconds', label: '超时（秒）', type: 'number', default: 15 },
  ],
  RBAC_TEST: [
    { key: 'base_url', label: '被测系统地址', required: true },
    { key: 'roles', label: '角色 Token（JSON：[{name,bearer}]）', required: true, type: 'textarea' },
    { key: 'endpoints', label: '受保护接口（JSON：[{method,path,allow}]）', required: true, type: 'textarea' },
    { key: 'timeout_seconds', label: '超时（秒）', type: 'number', default: 15 },
  ],
  CREDENTIAL_STORAGE_TEST: [
    { key: 'login_url', label: '登录页地址', required: true },
    { key: 'username', label: '测试账号', required: true },
    { key: 'password', label: '测试密码', required: true, type: 'password' },
    { key: 'timeout_seconds', label: '超时（秒）', type: 'number', default: 30 },
  ],
  PUBLIC_ENDPOINT_TEST: [
    { key: 'base_url', label: '被测系统地址', required: true },
    { key: 'endpoints', label: '公开端点（JSON：[{method,path,valid_params,invalid_params}]）', required: true, type: 'textarea' },
    { key: 'timeout_seconds', label: '超时（秒）', type: 'number', default: 15 },
  ],
  FUNCTIONAL_DEFECT_TEST: [
    { key: 'login_url', label: '登录页地址', required: true },
    { key: 'username', label: '测试账号', required: true },
    { key: 'password', label: '测试密码', required: true, type: 'password' },
    { key: 'form_url', label: '业务表单页地址', required: true },
    { key: 'fields', label: '业务数据（JSON：[{selector,value}]）', required: true, type: 'textarea' },
    { key: 'timeout_seconds', label: '超时（秒）', type: 'number', default: 30 },
  ],
}

// 带默认值的 number 校验
export const makeNumberValidator = (min, max) => ({
  validator: (_, v) => {
    if (v === undefined || v === null || v === '') return Promise.resolve()
    if (Number(v) < min || Number(v) > max) return Promise.reject(new Error(`请输入 ${min} - ${max} 之间的数值`))
    return Promise.resolve()
  },
})

// 动态获取引擎参数 schema：
//   后端 params_schema（engine-options 返回） → 优先
//   本地 ENGINE_PARAMS（硬编码） → fallback
// 这样后端可以渐进式给每个引擎加 params_schema，前端无感升级
export const getEngineParams = (engineCode, engineList) => {
  const remote = (engineList || []).find((e) => e.engine_code === engineCode)?.params_schema
  if (Array.isArray(remote) && remote.length > 0) return remote
  return ENGINE_PARAMS[engineCode] || []
}

// 6 个 AI 评测引擎（走 eval_set/target/judge 控件 + 预算估算）
export const AI_EVAL_ENGINES = ['REDTEAM_TEST', 'ETHICS_TEST', 'HALLUCINATION_TEST', 'PROMPT_INJECTION', 'RAG_TEST', 'MULTI_TURN_TEST']

// v2.0 P3/P5：被测系统字段的实际 formKey（引擎 params_schema 可能用 target 或 target_code）
export const targetKeyOf = (engineCode, engineList) => {
  const params = getEngineParams(engineCode, engineList)
  const has = (k) => params.some((p) => p.key === k)
  return has('target_code') || !has('target')
    ? `config__${engineCode}__target_code`
    : `config__${engineCode}__target`
}
