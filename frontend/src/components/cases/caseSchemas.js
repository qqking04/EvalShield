/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 用例内容模式定义（FE-1 核心）
// 用例类别 → content_schema（编辑器类型与字段），驱动 CasesTab 按类别动态渲染用例内容编辑区
export const CASE_CONTENT_SCHEMAS = {
  UI: { editor: 'step' },
  API: { editor: 'api' },
  HALLUCINATION: { editor: 'eval', fields: ['prompt', 'references'] },
  REDTEAM: { editor: 'eval', fields: ['prompt', 'threat'] },
  RAG: { editor: 'eval', fields: ['prompt', 'contexts', 'ground_truth'] },
  ETHICS: { editor: 'eval', fields: ['prompt', 'references'] },
  MULTITURN: { editor: 'eval', fields: ['sessions', 'fact_slots'] },
  MULTI_TURN: { editor: 'eval', fields: ['sessions', 'fact_slots'] },
  EVAL: { editor: 'eval', fields: ['prompt', 'rubric'] },
  PERFORMANCE: { editor: 'perf' },
  DATAFLOW: { editor: 'dataflow' },
  CASE_GEN: { editor: 'engineering' },
  SELF_HEAL: { editor: 'engineering' },
  DEFECT_PREDICT: { editor: 'engineering' },
  SECURITY: { editor: 'security' },
}

// 断言操作符枚举
export const ASSERT_OPS = [
  { value: 'eq', label: 'eq 等于' },
  { value: 'neq', label: 'neq 不等于' },
  { value: 'contains', label: 'contains 包含' },
  { value: 'not_contains', label: 'not_contains 不包含' },
  { value: 'gte', label: 'gte 大于等于' },
  { value: 'lte', label: 'lte 小于等于' },
  { value: 'notNull', label: 'notNull 非空' },
  { value: 'isNull', label: 'isNull 为空' },
  { value: 'in', label: 'in 属于集合' },
]

// 前置条件种类
export const PRECONDITION_KINDS = [
  { value: 'ENV', label: 'ENV 环境' },
  { value: 'DATA', label: 'DATA 数据' },
  { value: 'AUTH', label: 'AUTH 鉴权' },
  { value: 'STATE', label: 'STATE 状态' },
]

// 后置清理动作
export const CLEANUP_ACTIONS = [
  { value: 'reset_account', label: 'reset_account 重置账号' },
  { value: 'delete_record', label: 'delete_record 删除记录' },
  { value: 'restore_resource', label: 'restore_resource 恢复资源' },
  { value: 'custom_script', label: 'custom_script 自定义脚本' },
]

// 威胁类型（安全样本 threat_type）
export const THREAT_TYPES = [
  { value: 'direct_injection', label: '直接注入' },
  { value: 'roleplay_escape', label: '角色扮演逃逸' },
  { value: 'indirect_injection', label: '间接注入' },
  { value: 'delimiter_attack', label: '分隔符攻击' },
  { value: 'encoding_bypass', label: '编码绕过' },
  { value: 'horizontal_escalation', label: '横向越权' },
  { value: 'vertical_escalation', label: '纵向越权' },
  { value: 'identity_impersonation', label: '身份冒充' },
  { value: 'session_hijack', label: '会话劫持' },
  { value: 'param_pollution', label: '参数污染' },
  { value: 'cross_session_pollution', label: '跨会话污染' },
  { value: 'sensitive_memory', label: '敏感信息记忆' },
  { value: 'memory_poisoning', label: '记忆投毒' },
  { value: 'credential_leakage', label: '凭据泄漏' },
  { value: 'pii_leakage', label: 'PII 泄漏' },
]

// UI 引擎动作清单（8 种固定动作）
export const UI_ACTIONS = [
  { value: 'goto', label: 'goto 打开页面' },
  { value: 'click', label: 'click 点击元素' },
  { value: 'fill', label: 'fill 填写输入框' },
  { value: 'press', label: 'press 按键' },
  { value: 'wait', label: 'wait 等待' },
  { value: 'screenshot', label: 'screenshot 截图' },
  { value: 'assert_text', label: 'assert_text 断言文本' },
  { value: 'assert_visible', label: 'assert_visible 断言可见' },
]
