# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""Pydantic Schema：通用响应封装 + 认证/用户/角色/权限/字典/项目/任务等基础结构。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")


# ---------------------------------------------------------------------------
# 通用响应封装（与 errors.py 的 code=0 成功约定一致）
# ---------------------------------------------------------------------------
class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None
    request_id: str | None = None


class PageData(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 10


class PageResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: PageData[T] | None = None


# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64, description="登录名")
    password: str = Field(..., min_length=1, max_length=256, description="密码")
    totp_code: str | None = Field(
        default=None, max_length=16, description="TOTP 验证码（开启二次认证时必填）"
    )


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 7200
    user_id: int
    username: str
    display_name: str
    roles: list[str] = []
    perms: list[str] = []
    is_super_admin: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8, max_length=64)
    confirm_password: str


class MfaConfirmRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, description="TOTP 一次性验证码")


class MfaDisableRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, description="TOTP 一次性验证码")
    password: str | None = Field(
        default=None, description="密码（验证码方式失败时的兜底）"
    )


# ---------------------------------------------------------------------------
# 用户 / 角色 / 权限
# ---------------------------------------------------------------------------
class UserBase(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    org_id: int | None = None
    title: str | None = None
    user_type: str = "INTERNAL"
    status: str = "ACTIVE"


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=64)
    role_ids: list[int] = []


class UserUpdate(BaseModel):
    display_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    org_id: int | None = None
    title: str | None = None
    status: str | None = None
    role_ids: list[int] | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_no: str
    username: str
    display_name: str
    email: str | None
    phone: str | None
    user_type: str
    status: str
    org_id: int | None
    title: str | None
    mfa_enabled: bool
    roles: list[str] = []
    last_login_at: datetime | None
    created_at: datetime


class RoleCreate(BaseModel):
    role_code: str = Field(..., min_length=2, max_length=64)
    role_name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    perm_codes: list[str] = []
    menu_ids: list[int] = []


class RoleUpdate(BaseModel):
    role_name: str | None = None
    description: str | None = None
    perm_codes: list[str] | None = None
    menu_ids: list[int] | None = None


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role_code: str
    role_name: str
    role_type: str
    description: str | None
    is_system: bool
    perm_codes: list[str] = []
    menu_ids: list[int] = []
    created_at: datetime


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    perm_code: str
    perm_name: str
    perm_type: str
    module: str
    parent_code: str | None
    sort_order: int


# ---------------------------------------------------------------------------
# 数据字典
# ---------------------------------------------------------------------------
class DictItemIn(BaseModel):
    item_label: str = Field(..., min_length=1, max_length=128)
    item_value: str = Field(..., min_length=1, max_length=128)
    sort_order: int = 0
    ext: dict[str, Any] | None = None
    status: str = "ACTIVE"


class DictCreate(BaseModel):
    dict_code: str = Field(..., min_length=2, max_length=64)
    dict_name: str = Field(..., min_length=1, max_length=128)
    dict_type: str = "BUSINESS"
    description: str | None = None
    items: list[DictItemIn] = []


class DictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dict_code: str
    dict_name: str
    dict_type: str
    description: str | None
    is_system: bool
    status: str
    items: list[dict[str, Any]] = []
    created_at: datetime


# ---------------------------------------------------------------------------
# 项目
# ---------------------------------------------------------------------------
class ProjectCreate(BaseModel):
    """创建项目：同时接受字段名 name（代码内部）与 project_name（说明书约定）。"""
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=128, alias="project_name")
    description: str | None = None
    owner_id: int | None = None
    target_system: str | None = Field(default=None, max_length=512)
    visibility: str = "PRIVATE"


class ProjectUpdate(BaseModel):
    """更新项目：同 ProjectCreate，name/project_name 二选一。"""
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, alias="project_name")
    description: str | None = None
    owner_id: int | None = None
    target_system: str | None = None
    visibility: str | None = None
    status: str | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None
    owner_id: int
    owner_name: str | None
    target_system: str | None
    visibility: str
    status: str
    task_count: int = 0
    created_by: int | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# 引擎 / 任务
# ---------------------------------------------------------------------------
class EngineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    engine_code: str
    engine_name: str
    engine_type: str
    category: str
    description: str | None
    version: str
    status: str
    is_system: bool


class TaskCreate(BaseModel):
    project_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    engines: list[str] = Field(..., min_length=1, description="引擎编码列表，顺序执行")
    config: dict[str, Any] = Field(default_factory=dict)
    trigger_mode: str = "MANUAL"
    schedule_cron: str | None = None
    env_id: str | None = Field(default=None, description="环境ID（如 env_000001），可选")
    # ES10-P-02：显式指定项目版本（可选；不传则后端自动归因）
    project_version_id: int | None = Field(default=None, gt=0)
    # ES8 M5：质量门禁规则（JSON 数组或其字符串形态，router 内做结构校验）
    gate_rules: Any = Field(default=None, description="门禁规则 [{metric,op,threshold}]")


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_no: str
    project_id: int
    project_code: str | None
    project_version_id: int | None = None  # ES10-P-02：自动归因的项目版本（可空）
    name: str
    description: str | None
    task_type: str
    engines: list[str]
    config: dict[str, Any] | None
    status: str
    trigger_mode: str
    schedule_cron: str | None
    progress: int
    current_step: str | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    summary: dict[str, Any] | None
    error_msg: str | None
    conclusion: str | None = None  # v2.0 P1：业务结论（质量未达标原因/风险提示）
    executor: str | None = None
    created_by_name: str | None
    created_at: datetime
    # ES8 M5：质量门禁（gate_rules 原样 JSON 文本输出，前端/CI 各自解析）
    gate_rules: str | None = None
    gate_result: str | None = None


class TaskRunRequest(BaseModel):
    """手动触发/重跑任务的参数覆盖。"""

    config: dict[str, Any] | None = None
    engines: list[str] | None = None


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    step_no: str
    task_id: int
    seq: int
    engine_code: str
    engine_name: str
    status: str
    progress: int
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    result_summary: dict[str, Any] | None
    report_ids: list[int]
    error_msg: str | None
    executor: str | None = None


# ---------------------------------------------------------------------------
# 用例 / 数据集 / 场景
# ---------------------------------------------------------------------------
class CasePrecondition(BaseModel):
    """前置条件条目。kind: ENV/DATA/AUTH/STATE"""
    kind: str
    desc: str


class CaseTestDataRow(BaseModel):
    """数据驱动分组。case: 分组名，params: 参数映射。"""
    case: str
    params: dict[str, Any]


class CaseAssertion(BaseModel):
    """断言集条目。op: eq/neq/contains/not_contains/regex/gt/gte/lt/lte/notNull/isNull/in"""
    path: str
    op: str
    expected: Any = None
    note: str | None = None


class CaseExtract(BaseModel):
    """步骤提取变量。from_: response/state"""
    var: str
    from_: str = "response"
    path: str


class PostCleanupItem(BaseModel):
    """后置清理条目。action: reset_account/delete_record/restore_resource/custom_script"""
    action: str
    target: str | None = None
    params: dict[str, Any] | None = None


# 合法用例类别（与引擎 category / 数据字典 case_category 保持一致）
VALID_CASE_CATEGORIES: frozenset[str] = frozenset(
    {
        "FUNCTIONAL", "API", "UI", "PERFORMANCE", "HALLUCINATION", "REDTEAM",
        "RAG", "ETHICS", "DATAFLOW", "MULTITURN", "EVAL", "CASE_GEN",
        "SECURITY", "PERF", "DATA_QUALITY", "DEFECT_PREDICT", "MULTI_TURN",
        "SELF_HEAL",
    }
)


class CaseCreate(BaseModel):
    project_id: int = Field(..., gt=0)
    dataset_id: int | None = None
    title: str = Field(..., min_length=1, max_length=256)
    module: str | None = Field(default=None, max_length=128, description="所属模块（如 登录/订单/支付）")
    category: str = Field(..., min_length=1, max_length=64)
    source: str = "MANUAL"
    severity: str = "P2"
    priority: str = "MEDIUM"
    precondition: str | None = None
    steps: list[Any] | None = None
    expected: str | None = None
    request_spec: dict[str, Any] | None = None
    tags: list[str] | None = None
    content_schema: dict[str, Any] | None = None
    preconditions: list[CasePrecondition] | None = None
    test_data: list[CaseTestDataRow] | None = None
    assertions: list[CaseAssertion] | None = None
    extract_vars: dict[str, Any] | None = None
    post_cleanup: list[PostCleanupItem] | None = None
    requirement_id: str | None = None


class CaseUpdate(BaseModel):
    title: str | None = None
    module: str | None = Field(default=None, max_length=128)
    severity: str | None = None
    priority: str | None = None
    status: str | None = None
    precondition: str | None = None
    steps: list[Any] | None = None
    expected: str | None = None
    request_spec: dict[str, Any] | None = None
    tags: list[str] | None = None
    content_schema: dict[str, Any] | None = None
    preconditions: list[CasePrecondition] | None = None
    test_data: list[CaseTestDataRow] | None = None
    assertions: list[CaseAssertion] | None = None
    extract_vars: dict[str, Any] | None = None
    post_cleanup: list[PostCleanupItem] | None = None
    requirement_id: str | None = None
    review_status: str | None = Field(default=None, max_length=16)


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_no: str
    project_id: int
    dataset_id: int | None
    title: str
    module: str | None = None
    last_actual: dict[str, Any] | None = None
    category: str
    source: str
    severity: str
    priority: str
    status: str
    precondition: str | None
    steps: list[Any] | None
    expected: str | None
    request_spec: dict[str, Any] | None
    last_result: str | None
    run_count: int
    pass_rate: float
    tags: list[str] | None
    content_schema: dict[str, Any] | None
    preconditions: list[CasePrecondition] | None = None
    test_data: list[CaseTestDataRow] | None = None
    assertions: list[CaseAssertion] | None = None
    extract_vars: dict[str, Any] | None = None
    post_cleanup: list[PostCleanupItem] | None = None
    requirement_id: str | None = None
    review_status: str | None = None
    created_at: datetime


class DatasetCreate(BaseModel):
    project_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1, max_length=128)
    category: str = Field(..., min_length=1, max_length=64)
    description: str | None = None
    case_ids: list[int] = []
    # 参数列定义（DatasetsTab Form.List 提交）
    parameters: list[dict] = Field(default_factory=list, description="参数列定义：[{name, type, example}]")
    # 数据行定义（数据集实际测试数据，逐行展开数据驱动）
    data_rows: list[dict] = Field(default_factory=list, description="数据行定义：[{列名: 值, ...}]")
    source: str = "MANUAL"
    visibility: str = "PRIVATE"


class DatasetUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    case_ids: list[int] | None = None
    parameters: list[dict] | None = None
    data_rows: list[dict] | None = None
    source: str | None = None
    visibility: str | None = None


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    project_id: int
    name: str
    category: str
    case_count: int
    source: str
    visibility: str
    description: str | None
    parameters: list[dict] | None = None
    data_rows: list[dict] | None = None
    meta: dict[str, Any] | None = None
    created_at: datetime


class ScenarioCreate(BaseModel):
    project_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    steps: list[Any] = []
    variables: dict[str, Any] | None = None
    data_sources: list[Any] | None = None
    visibility: str = "PRIVATE"
    module: str | None = None


# ---------------------------------------------------------------------------
# 评测
# ---------------------------------------------------------------------------
class EvalSetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    category: str = Field(..., min_length=1, max_length=64)
    items: list[Any] = []
    source: str = "MANUAL"
    meta: dict[str, Any] | None = None
    visibility: str = "PRIVATE"
    project_id: int | None = None
    content_schema: dict[str, Any] | None = None


class EvalRunCreate(BaseModel):
    # ES9-P-10：题库执行分支下 eval_set_id 可为 0（question_bank_id>0 时忽略评测集）
    eval_set_id: int = Field(0, ge=0)
    question_bank_id: int | None = Field(None, gt=0, description="ES9：题库执行（抽题落 eval_run_items）")
    sample_size: int | None = Field(None, ge=1, le=5000, description="ES9：抽样题量（缺省 EVAL_SAMPLE_SIZE，社区版 clamp）")
    fact_source_id: int | None = Field(default=None, gt=0, description="ES10-P-01：事实基准知识源（软引用 fact_sources.id）")
    # #8：运行级被测形态枚举收敛（来源 models.EVAL_RUN_TARGET_TYPES，勿与注册表协议混用）
    target_type: str = Field(..., pattern="^(MODEL|RAG|AGENT|API)$")
    target_id: str = Field(..., min_length=1, max_length=128)
    model_gateway: str | None = None
    judge_mode: str = "RULE"
    judge_model: str | None = None
    engine_code: str | None = None
    # ES11：活动目的与血缘（run_purpose 缺省 STANDARD；优化12 §4.1：增 SCREENING 筛选性评估）
    run_purpose: str = Field("STANDARD", pattern="^(STANDARD|REGRESSION|RETEST|TRACE_REPLAY|SCREENING)$")
    parent_run_id: int | None = Field(None, gt=0, description="ES11：来源运行（复测/回流），软引用 eval_runs.id")
    baseline_run_id: int | None = Field(None, gt=0, description="ES11：对比基线运行，软引用 eval_runs.id")
    project_version_id: int | None = Field(None, gt=0, description="ES11：版本归因，软引用 project_versions.id")
    # 优化12 §4.1：评估活动聚合键（UUID 软键，落 run_snapshot.activity_id，零 DDL）
    activity_id: str | None = Field(None, description="评估活动聚合键（UUID）；同 activity_id 的题库 run 与引擎 run 构成一次活动")
    # 优化12 §4.5：按子类抽题配额（非空时替代均摊抽样，禁止跨类回补）
    category_quotas: dict[str, int] | None = Field(None, description="按子类抽题配额 {子类: 题数}；非空时 sample_size 被忽略")

    @field_validator("activity_id")
    @classmethod
    def _validate_activity_id(cls, v: str | None) -> str | None:
        # 非法 UUID → pydantic 校验失败（FastAPI 统一 422；
        # errors.py 处理器已剥离 ctx，异常对象不会被序列化）
        if v is None:
            return v
        try:
            return str(uuid.UUID(str(v)))
        except ValueError:
            raise ValueError("activity_id 不是合法 UUID")


class EvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_no: str
    task_id: int | None = None
    eval_set_id: int
    eval_set_code: str | None
    target_type: str
    target_id: str
    model_gateway: str | None
    judge_mode: str
    judge_model: str | None
    status: str
    overall_score: float | None
    verdict: str | None
    summary: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    created_at: datetime


# ---------------------------------------------------------------------------
# 模型网关 / 通知 / 审计
# ---------------------------------------------------------------------------
class ModelConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    provider: str = Field(..., min_length=1, max_length=64)
    base_url: str | None = None
    model: str = Field(..., min_length=1, max_length=128)
    api_key_env: str | None = None
    api_key: str | None = None  # ES9-P-05：UI 托管密钥（加密落 api_key_enc，与 env 名互斥）
    timeout_sec: int = 60
    max_tokens: int = 2048
    temperature: float = 0.2
    seed: int | None = None
    is_default: bool = False
    usage: str = "CHAT"
    input_price_per_mtok: float = 0.0
    output_price_per_mtok: float = 0.0


class ModelConfigUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    provider: str | None = Field(None, min_length=1, max_length=64)
    base_url: str | None = None
    model: str | None = Field(None, min_length=1, max_length=128)
    api_key_env: str | None = None
    api_key: str | None = None  # ES9-P-05：含 **** 视为未修改；非空则加密替换
    timeout_sec: int | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    seed: int | None = None
    is_default: bool | None = None
    status: str | None = None
    usage: str | None = None
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None


class ModelConfigTestRequest(BaseModel):
    """测试连接：可携带临时 api_key（仅内存使用，不落库）。"""

    api_key: str | None = None


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notif_no: str
    title: str
    content: str | None
    notif_type: str
    ref_no: str | None
    is_read: bool
    created_at: datetime


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    log_no: str
    username: str | None
    action: str
    module: str
    method: str | None
    path: str | None
    status_code: int | None
    result: str
    ip: str | None
    duration_ms: int | None
    error_msg: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# 沙箱隔离模块 Schema
# ---------------------------------------------------------------------------
class SandboxExecuteRequest(BaseModel):
    task_id: int = Field(..., gt=0)
    engine_code: str = Field(..., min_length=1, max_length=32)
    config: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=1, le=1800)
    artifacts_in: list[str] = Field(default_factory=list)


class SandboxExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_no: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    exit_code: int | None = None
    error_msg: str | None = None


class SandboxExecutionDetail(SandboxExecutionOut):
    logs: str | None = None
    artifacts: list[dict] | None = None
    result_payload: dict | None = None
    sandbox_id: str | None = None
    engine_code: str | None = None
    timeout_seconds: int = 300


class SandboxImageCreate(BaseModel):
    image_name: str = Field(..., min_length=1, max_length=128)
    image_tag: str = Field(default="latest", max_length=64)
    registry_url: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=512)
    is_default: bool = False


class SandboxImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image_no: str
    image_name: str
    image_tag: str
    full_name: str
    is_default: bool
    is_enabled: bool
    created_at: datetime


# ===========================================================================
# P3-9 缺陷管理 / P3-11 环境管理 / P3-12 UI 录制 Schema（2026-09-29）
# ===========================================================================

# --- 缺陷管理 ---
class DefectCreate(BaseModel):
    project_id: int = Field(..., gt=0)
    task_id: int | None = None
    case_id: int | None = None
    report_id: int | None = None
    title: str = Field(..., min_length=1, max_length=500)
    severity: str = "P2"
    priority: str = "MEDIUM"
    module: str | None = None
    reproduce_steps: list[Any] | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    attachments: list[Any] | None = None
    fix_suggestion: str | None = None
    severity_basis: str | None = None
    requirement_id: str | None = None
    actual: str | None = None
    expected: str | None = None
    evidence: list[Any] | None = None
    # ES11：来源血缘（题级转缺陷写 RUN_ITEM，复测自动绑题/关闭六条件依赖该口径）
    origin_type: str | None = Field(
        default=None, pattern="^(RUN_ITEM|REPORT|TRACE|SRC|MANUAL)$",
        description="ES11：来源类型；RUN_ITEM 时 origin_id=eval_run_items.id；SRC 时 origin_id=src_findings.id",
    )
    origin_id: int | None = Field(default=None, gt=0, description="ES11：来源实体 ID")


class DefectUpdate(BaseModel):
    project_id: int | None = Field(default=None, gt=0)
    task_id: int | None = None
    case_id: int | None = None
    report_id: int | None = None
    title: str | None = Field(default=None, max_length=500)
    severity: str | None = None
    priority: str | None = None
    module: str | None = None
    reproduce_steps: list[Any] | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    attachments: list[Any] | None = None
    fix_suggestion: str | None = None
    severity_basis: str | None = None
    requirement_id: str | None = None
    status: str | None = Field(default=None, description="NEW/OPEN/FIXED/CLOSED")
    actual: str | None = None
    expected: str | None = None
    evidence: list[Any] | None = None


class DefectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    defect_no: str
    project_id: int
    task_id: int | None = None
    case_id: int | None = None
    report_id: int | None = None
    title: str
    severity: str
    priority: str = "MEDIUM"
    module: str | None = None
    reproduce_steps: list[Any] | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    attachments: list[Any] | None = None
    fix_suggestion: str | None = None
    severity_basis: str | None = None
    requirement_id: str | None = None
    status: str
    actual: str | None
    expected: str | None
    evidence: list[Any] | None = None
    category: str | None = None
    ai_reason: str | None = None
    origin_type: str | None = None
    origin_id: int | None = None
    created_at: datetime


# --- 环境管理 ---
class EnvCreate(BaseModel):
    project_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1, max_length=128)
    base_url: str = Field(..., min_length=1, max_length=500)
    auth: dict[str, Any] | None = None
    is_default: bool = False
    description: str | None = None


class EnvUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    base_url: str | None = Field(default=None, max_length=500)
    auth: dict[str, Any] | None = None
    is_default: bool | None = None
    description: str | None = None


class EnvOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    base_url: str
    auth: dict[str, Any] | None = None
    is_default: bool
    description: str | None = None
    project_id: int
    created_at: datetime


# --- UI 录制 ---
class RecordingSaveRequest(BaseModel):
    project_id: int = Field(..., gt=0)
    case_id: int | None = None
    name: str = Field(..., min_length=1, max_length=200)
    steps: list[Any] = Field(default_factory=list)
    duration_ms: int | None = None


class RecordingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rec_no: str
    project_id: int
    case_id: int | None = None
    name: str
    steps: list[Any] | None = None
    duration_ms: int | None = None
    created_at: datetime


# --- P2-5 AI 生成数据集 ---
class DatasetGenerateRequest(BaseModel):
    project_id: int = Field(..., gt=0)
    category: str = Field(..., min_length=1, max_length=64)
    prompt: str = Field(..., min_length=5, max_length=2000, description="业务描述，如 登录场景，用户名密码")


# --- P2-6 AI 断言补全 ---
class AssertionCompleteRequest(BaseModel):
    case_id: int = Field(..., gt=0)
    use_last_actual: bool = True
