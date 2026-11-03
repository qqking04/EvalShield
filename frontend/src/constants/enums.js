/*
 * EvalShield
 * Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
 * Use of this source code is governed by the Business Source License 1.1
 * (the "License") stated in the LICENSE file at the root of this
 * distribution. Change Date: 3 years after release.
 * Change License: Apache License, Version 2.0.
 * SPDX-License-Identifier: BUSL-1.1
 */
// 引擎中文名映射（key 为后端 engine_registry 实际注册的 19 个 engine_code）
// 修复 2026-09-25 BUG-2：原缺 LOCUST_PERF/DATA_QUALITY（后端有），
//                      冗余 PENTEST/AGENT_TEST（后端无）
// 2026-10-12 补 SECURITY_TEST（v2.0 全维度安全引擎）
export const ENGINE_NAME_MAP = {
  UI_TEST: 'UI 测试',
  API_TEST: '接口测试',
  PERF_TEST: '性能测试',
  LOCUST_PERF: 'Locust 分布式压测',
  DATAFLOW_TEST: '数据流测试',
  SECURITY_TEST: '安全测试',
  DATA_QUALITY: '数据质量测试',
  HALLUCINATION_TEST: '幻觉测试',
  REDTEAM_TEST: '红队测试',
  RAG_TEST: 'RAG 检索测试',
  MULTI_TURN_TEST: '多轮测试',
  ETHICS_TEST: '伦理测试',
  EVAL_ENGINE: '评测引擎',
  PROMPT_INJECTION: '提示注入',
  PRIVILEGE_ESCALATION: '权限提升',
  MEMORY_LEAKAGE: '记忆泄漏',
  CASE_GEN: '用例生成',
  SELF_HEAL: '自愈修复',
  DEFECT_PREDICT: '缺陷预测',
  // 安全报告补全 P1：7 个安全检测引擎
  HTTP_SECURITY_HEADERS: 'HTTP 安全头检测',
  TLS_CHECK: '传输层加密检测',
  STATIC_SECRET_SCAN: '硬编码密钥扫描',
  RBAC_TEST: 'RBAC 鉴权检测',
  CREDENTIAL_STORAGE_TEST: '凭证存储检测',
  PUBLIC_ENDPOINT_TEST: '公开接口校验',
  FUNCTIONAL_DEFECT_TEST: '业务功能缺陷检测',
}

// 引擎类型映射（key 为后端 TestEngine.engine_type 三类，用于仪表盘分布展示）
export const ENGINE_TYPE_MAP = {
  TRADITIONAL: '传统测试',
  AI: 'AI 测试',
  ENGINEERING: 'AI 工程化',
}

// 用例类别映射（对齐后端 case_category 字典 14 项）
// 修复 2026-09-25 BUG-3：原仅 8 项，缺 DATAFLOW/MULTITURN/EVAL/CASE_GEN/SELF_HEAL/DEFECT_PREDICT
export const CASE_CATEGORY_MAP = {
  FUNCTIONAL: '功能测试',
  API: '接口测试',
  UI: 'UI 测试',
  PERFORMANCE: '性能测试',
  HALLUCINATION: '幻觉测试',
  REDTEAM: '红队测试',
  RAG: 'RAG 测试',
  ETHICS: '伦理测试',
  DATAFLOW: '数据流测试',
  MULTITURN: '多轮一致性',
  EVAL: '平台化评测',
  CASE_GEN: 'Agent 用例生成',
  SELF_HEAL: '脚本自愈',
  DEFECT_PREDICT: '缺陷预测',
}

// 用例严重度映射（对齐后端 severity 字典 P0~P4）
// 2026-09-28 资产中心列表中文化：前端 dict_code=severity 大小写不敏感
export const CASE_SEVERITY_MAP = {
  P0: '致命',
  P1: '严重',
  P2: '重要',
  P3: '一般',
  P4: '轻微',
}
export const CASE_SEVERITY_COLOR = {
  P0: 'red',
  P1: 'orange',
  P2: 'blue',
  P3: 'default',
  P4: 'default',
}

// 用例优先级映射（对齐后端 priority 字典）
export const CASE_PRIORITY_MAP = {
  HIGH: '高',
  MEDIUM: '中',
  LOW: '低',
}

// 用例状态映射（对齐后端 case_status 字典）
export const CASE_STATUS_MAP = {
  ACTIVE: '启用',
  DISABLED: '禁用',
  ARCHIVED: '归档',
}
export const CASE_STATUS_COLOR = {
  ACTIVE: 'green',
  DISABLED: 'orange',
  ARCHIVED: 'default',
}

// 用例来源映射（对齐后端 source 字典）
export const CASE_SOURCE_MAP = {
  MANUAL: '手工创建',
  UPLOAD: 'Excel 导入',
  AI_GEN: 'AI 生成',
  AGENT_GEN: 'Agent 生成',
}

// 数据集来源映射（对齐后端 dataset_source 字典）
export const DATASET_SOURCE_MAP = {
  MANUAL: '手工创建',
  UPLOAD: 'CSV 导入',
  AI_GEN: 'AI 生成',
}

// 可见性映射（对齐后端 visibility 字典）
export const VISIBILITY_MAP = {
  PRIVATE: '私有',
  PUBLIC: '公开',
  INTERNAL: '内部共享',
}

// 评测类别映射（对齐后端 eval_category 字典 6 项）
// 修复 2026-09-25 BUG-4：原错误定义 FACTUALITY/SAFETY（后端无），
//                      缺 MULTI_TURN/FUNCTIONAL（后端有）
export const EVAL_CATEGORY_MAP = {
  HALLUCINATION: '幻觉评测',
  RAG: 'RAG 正确性',
  REDTEAM: '越狱与安全红队',
  ETHICS: '伦理合规',
  MULTI_TURN: '多轮一致性',
  SECURITY: '提示注入/安全',
  FUNCTIONAL: '通用功能',
}

export const COMPLIANCE_SEVERITY_MAP = {
  CRITICAL: '严重',
  HIGH: '高',
  MEDIUM: '中',
  LOW: '低',
}

export const COMPLIANCE_SEVERITY_COLOR = {
  CRITICAL: 'red',
  HIGH: 'orange',
  MEDIUM: 'gold',
  LOW: 'green',
}

export const COMPLIANCE_STATUS_MAP = {
  ACTIVE: '生效中',
  DISABLED: '已停用',
  PENDING: '待审核',
}

export const COMPLIANCE_STATUS_COLOR = {
  ACTIVE: 'green',
  DISABLED: 'default',
  PENDING: 'cyan',
}

export const EVAL_SOURCE_MAP = {
  MANUAL: '手动创建',
  IMPORT: '批量导入',
  SYSTEM: '系统生成',
  UPLOAD: '文件上传',
  AI_GEN: 'AI 生成',
  FROM_RUN: '失败用例派生',
  FROM_REVIEW: '评审回流',
}

export const TASK_STATUS_MAP = {
  PENDING: '待执行',
  RUNNING: '执行中',
  SUCCESS: '成功',
  COMPLETED_WITH_RISK: '未达阈值',
  FAILED: '失败',
  CANCELLED: '已取消',
  SCHEDULED: '已调度',
}

export const TASK_STATUS_COLOR = {
  PENDING: 'default',
  RUNNING: 'processing',
  SUCCESS: 'success',
  COMPLETED_WITH_RISK: 'warning',
  FAILED: 'error',
  CANCELLED: 'warning',
  SCHEDULED: 'cyan',
}

export const REPORT_TYPE_MAP = {
  FULL: '完整报告',
  SUMMARY: '摘要报告',
}

export const REPORT_STATUS_MAP = {
  DONE: '已完成',
  RUNNING: '生成中',
  GENERATING: '生成中',
  FAILED: '失败',
  PENDING: '待生成',
}

// —— 报告页统一中文化映射（判定 / 严重度 / 步骤状态 / 合规风险等级） ——
export const VERDICT_CN_MAP = {
  PASS: '通过',
  SAFE: '通过',
  FAIL: '不通过',
  RISK: '存在风险',
  LEAK: '存在泄漏',
  BYPASSED: '被绕过',
  WARN: '警告',
  ATTEMPTED: '已尝试',
  SKIP: '跳过',
  SKIPPED: '跳过',
  CONTRADICTED: '存在矛盾',
  CONTRADICTION: '存在矛盾',
}

export const SEVERITY_CN_MAP = {
  PASS: '无',
  NONE: '无',
  MINOR: '轻微',
  LOW: '低',
  MODERATE: '中',
  MEDIUM: '中',
  P4: '轻微',
  P3: '一般',
  HIGH: '高',
  P2: '重要',
  MAJOR: '较重',
  CRITICAL: '严重',
  P1: '严重',
  P0: '致命',
}

export const STEP_STATUS_CN_MAP = {
  SUCCESS: '成功',
  PASSED: '通过',
  FAILED: '失败',
  SKIPPED: '已跳过',
  RUNNING: '执行中',
  PENDING: '待执行',
  ERROR: '执行异常',
}

export const COMPLIANCE_RISK_CN_MAP = {
  HIGH: '高风险',
  MEDIUM: '中风险',
  LOW: '低风险',
  NONE: '未发现不符合项（基本符合）',
}

export const REPORT_STATUS_COLOR = {
  DONE: 'success',
  RUNNING: 'processing',
  FAILED: 'error',
  PENDING: 'default',
}

export const PROJECT_STATUS_MAP = {
  ACTIVE: '启用',
  ARCHIVED: '已归档',
}

export const PROJECT_VISIBILITY_MAP = {
  PUBLIC: '公开',
  PRIVATE: '私有',
}

export const MEMBER_ROLE_MAP = {
  OWNER: '负责人',
  MEMBER: '成员',
  VIEWER: '只读',
}

export const MEMBER_ROLE_COLOR = {
  OWNER: 'gold',
  MEMBER: 'blue',
  VIEWER: 'default',
}

export const PROVIDER_MAP = {
  DEEPSEEK: 'DeepSeek 官方',
  OPENAI: 'OpenAI',
  ANTHROPIC: 'Anthropic',
  QWEN: '通义千问',
  LOCAL: '本地 Ollama',
  CUSTOM: '自定义',
}

// 通用：取中文 label；若找不到返回原值
export const labelOf = (map, key) => map?.[key] ?? key
export const colorOf = (map, key) => map?.[key] ?? 'default'
