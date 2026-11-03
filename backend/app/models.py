# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""SQLAlchemy 模型层：覆盖 EvalShield 全部核心表（D-01~D-12 + 扩展表）。

设计约束（用户硬性要求）：
1. 全部不使用外键（ForeignKey），表间关系由业务编号/逻辑字段维护。
2. 全部含业务编号字段（code / no），页面展示编号不展示主键 ID。
3. UTF-8 中文支持：连接串已带 client_encoding=utf8，本层所有字符串列默认 utf8 语义。
4. 审计与扩展字段：created_by / created_at / updated_at / deleted_at（软删除）、tenant_id（租户隔离）。
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
# 修复 2026-09-25 BUG-6：原 from sqlalchemy import JSON 在 postgres 上默认映射 json 类型
#         JSONB 从 postgresql dialect 导入，postgres 原生 jsonb，支持索引 + @>/-> 高效查询
#         注意：顶层 sqlalchemy.JSON 在 postgres 上实际也会存成 jsonb（SA 2.0+），
#         但显式用 postgresql.JSONB 更明确语义 + 让类型不匹配时直接报错
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _now() -> datetime:
    """UTC 当前时间（存储与读取一致，前端按本地时区展示）。"""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 枚举常量（与数据字典 DICT_TYPE 联动，代码级兜底约束）
# ---------------------------------------------------------------------------
class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"  # 正常
    LOCKED = "LOCKED"  # 锁定（多次登录失败）
    DISABLED = "DISABLED"  # 停用


class UserType(str, enum.Enum):
    INTERNAL = "INTERNAL"  # 内部用户
    EXTERNAL = "EXTERNAL"  # 外部用户（API 接入方）
    PLATFORM_ADMIN = "platform_admin"  # 优化7 T6：平台超管（仅 saas 形态可签发）


class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"  # 待执行
    RUNNING = "RUNNING"  # 执行中
    CANCELING = "CANCELING"  # 取消中（执行器感知检查点后置 CANCELLED）
    SUCCESS = "SUCCESS"  # 成功
    COMPLETED_WITH_RISK = "COMPLETED_WITH_RISK"  # v2.0 P1：执行成功但质量未达阈值（业务结论，非系统故障）
    FAILED = "FAILED"  # 执行异常/崩溃
    CANCELLED = "CANCELLED"  # 已取消


class EngineStatus(str, enum.Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class ReportStatus(str, enum.Enum):
    GENERATING = "GENERATING"
    DONE = "DONE"
    FAILED = "FAILED"


class EvalStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class Visibility(str, enum.Enum):
    PRIVATE = "PRIVATE"  # 仅创建者
    TEAM = "TEAM"  # 同租户
    PUBLIC = "PUBLIC"  # 公开


class NotifyChannel(str, enum.Enum):
    EMAIL = "EMAIL"
    WEBHOOK = "WEBHOOK"
    INNER_MSG = "INNER_MSG"  # 站内信


class SandboxStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    OOM_KILLED = "OOM_KILLED"
    SECCOMP_VIOLATION = "SECCOMP_VIOLATION"
    CANCELLED = "CANCELLED"


class RegulationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DRAFT = "DRAFT"


class HealStrategy(str, enum.Enum):
    RETRY = "RETRY"
    IDEMPOTENT_FIX = "IDEMPOTENT_FIX"
    SELECTOR_FIX = "SELECTOR_FIX"
    SKIP = "SKIP"


# EvalRun.target_type 单一事实源（#8 枚举收敛）：
# 运行级被测形态，由 task_runner._infer_target_type 产生（字面值被测试锁定）；
# 注意与 TargetRegistry.target_type（LLM_API/APP_API/INTERNAL_MODEL，注册表对象协议）
# 是**两个不同字段**，不要混用。schemas.EvalRunCreate 的 pattern 以此为来源。
EVAL_RUN_TARGET_TYPES = ("MODEL", "RAG", "AGENT", "API")


# ---------------------------------------------------------------------------
# 基础平台表
# ---------------------------------------------------------------------------
class Organization(Base):
    """部门/组织（多级组织树，parent_id 逻辑引用不建外键）。"""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="部门编号（业务展示）"
    )
    org_name: Mapped[str] = mapped_column(String(128), comment="部门名称")
    parent_id: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="上级部门ID（逻辑引用，不建外键）"
    )
    org_path: Mapped[str] = mapped_column(
        String(512), default="/", comment="部门路径 /1/2/3"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    remark: Mapped[str | None] = mapped_column(String(512))
    # MVP2.0 增量：SaaS 套餐与配额
    plan: Mapped[str] = mapped_column(String(20), nullable=False, default="free")
    quota_tasks_monthly: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class SystemUser(Base):
    """系统用户（内部 + 外部接入账号共用一张表）。"""

    __tablename__ = "system_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="用户编号（业务展示）"
    )
    username: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, comment="登录名"
    )
    email: Mapped[str | None] = mapped_column(String(128), index=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(256), comment="bcrypt 哈希")
    display_name: Mapped[str] = mapped_column(String(128), comment="显示名")
    avatar: Mapped[str | None] = mapped_column(String(512))
    user_type: Mapped[str] = mapped_column(String(16), default=UserType.INTERNAL.value)
    status: Mapped[str] = mapped_column(
        String(16), default=UserStatus.ACTIVE.value, index=True
    )
    org_id: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="所属部门ID（逻辑引用）"
    )
    title: Mapped[str | None] = mapped_column(String(128), comment="职位")
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否启用 TOTP 二次认证"
    )
    mfa_secret: Mapped[str | None] = mapped_column(
        String(128), comment="TOTP Secret（已加密存储）"
    )
    login_fail_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_login_ip: Mapped[str | None] = mapped_column(String(64))
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # MVP2.0 增量字段（密码重置令牌）
    pwd_reset_token: Mapped[str | None] = mapped_column(String(64), default=None)
    pwd_reset_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # 优化7 T4：首登/重置后强制改密标志
    must_change_pwd: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"),
        comment="首登强制改密（半态令牌仅允许改密）",
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class Role(Base):
    """角色（含内置角色 SUPER_ADMIN / ADMIN / TESTER / VIEWER）。"""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_code: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, comment="角色编码"
    )
    role_name: Mapped[str] = mapped_column(String(128), comment="角色名称")
    role_type: Mapped[str] = mapped_column(
        String(16), default="CUSTOM", comment="BUILTIN/CUSTOM"
    )
    description: Mapped[str | None] = mapped_column(String(512))
    is_system: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="系统内置角色不可删除"
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class Permission(Base):
    """功能权限点（menu/api/action 三级口径，模块:动作）。"""

    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    perm_code: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, comment="权限编码，如 project:create"
    )
    perm_name: Mapped[str] = mapped_column(String(128), comment="权限名称")
    perm_type: Mapped[str] = mapped_column(
        String(16), default="ACTION", comment="MENU/ACTION/API"
    )
    module: Mapped[str] = mapped_column(
        String(64), comment="所属模块，如 project/task/engine/report"
    )
    parent_code: Mapped[str | None] = mapped_column(String(128), default=None)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UserRole(Base):
    """用户-角色关系（多对多，无外键）。"""

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "tenant_id", name="uq_user_role_tenant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    role_id: Mapped[int] = mapped_column(Integer, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RolePermission(Base):
    """角色-权限关系（多对多，无外键）。"""

    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "perm_code", name="uq_role_perm"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_id: Mapped[int] = mapped_column(Integer, index=True)
    perm_code: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Menu(Base):
    """系统菜单（树形自关联，含业务菜单 + 系统管理目录/子项 + 按钮）。

    权限驱动：perm 字段与 permissions.perm_code 对齐；前端 hasPerm(perm) 过滤。
    type: 'dir'（目录） / 'menu'（可路由菜单） / 'button'（按钮权限占位）。
    """

    __tablename__ = "menus"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    path: Mapped[str] = mapped_column(String(128), comment="前端路由 path 片段")
    component: Mapped[str | None] = mapped_column(String(256), comment="前端组件路径")
    icon: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(64))
    perm: Mapped[str | None] = mapped_column(String(64), index=True, comment="所需权限码")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    menu_type: Mapped[str] = mapped_column(String(16), default="menu")
    remark: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class RoleMenu(Base):
    """角色-菜单关系（多对多）。"""

    __tablename__ = "role_menus"
    __table_args__ = (UniqueConstraint("role_id", "menu_id", name="uq_role_menu"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_id: Mapped[int] = mapped_column(Integer, index=True)
    menu_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SystemSetting(Base):
    """系统配置参数（按 group 分组，JSON/string/integer/boolean 多类型）。"""

    __tablename__ = "system_settings"
    __table_args__ = (UniqueConstraint("setting_group", "setting_key", name="uq_setting_group_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setting_group: Mapped[str] = mapped_column(String(32), index=True)
    setting_key: Mapped[str] = mapped_column(String(64))
    setting_value: Mapped[str | None] = mapped_column(Text, default=None)
    value_type: Mapped[str] = mapped_column(String(16), default="string")
    description: Mapped[str | None] = mapped_column(String(256))
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[int | None] = mapped_column(Integer, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class DataDict(Base):
    """数据字典（数据分类，如测试类别、任务状态、指标码）。"""

    __tablename__ = "data_dicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dict_code: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, comment="字典编码"
    )
    dict_name: Mapped[str] = mapped_column(String(128), comment="字典名称")
    dict_type: Mapped[str] = mapped_column(
        String(32), default="SYSTEM", comment="SYSTEM/BUSINESS"
    )
    description: Mapped[str | None] = mapped_column(String(512))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class DictItem(Base):
    """字典项（字典明细，label/value/排序/扩展属性）。"""

    __tablename__ = "dict_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dict_id: Mapped[int] = mapped_column(
        Integer, index=True, comment="所属字典ID（逻辑引用）"
    )
    item_label: Mapped[str] = mapped_column(String(128), comment="展示名")
    item_value: Mapped[str] = mapped_column(String(128), comment="值")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    ext: Mapped[dict | None] = mapped_column(
        JSONB, default=dict, comment="扩展属性（颜色/图标等）"
    )
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class AuditLog(Base):
    """审计日志（登录/操作/数据变更，含请求与结果摘要）。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    log_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="日志编号（业务展示）"
    )
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, default=None)
    username: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    action: Mapped[str] = mapped_column(
        String(64), index=True, comment="动作，如 user.login / project.create"
    )
    module: Mapped[str] = mapped_column(String(64), default="", comment="模块")
    method: Mapped[str | None] = mapped_column(String(8), default=None)
    path: Mapped[str | None] = mapped_column(String(512), default=None)
    status_code: Mapped[int | None] = mapped_column(Integer, default=None)
    result: Mapped[str] = mapped_column(
        String(16), default="SUCCESS", comment="SUCCESS/FAILED"
    )
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
    ua: Mapped[str | None] = mapped_column(String(512), default=None)
    request_body: Mapped[dict | None] = mapped_column(JSONB, default=None)
    error_msg: Mapped[str | None] = mapped_column(Text, default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )

    # ---- 第 2 章：校验链字段 ----
    prev_hash: Mapped[str | None] = mapped_column(
        String(64), default=None, comment="上一条记录的 self_hash"
    )
    self_hash: Mapped[str | None] = mapped_column(
        String(64), default=None, comment="本条记录 SHA-256"
    )
    chain_index: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="链式序号，严格自增"
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, comment="软删除归档时间"
    )


class ApiKey(Base):
    """API Key（外部系统接入凭证，仅存 SHA-256 摘要）。"""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_name: Mapped[str] = mapped_column(String(64), comment="Key 名称")
    key_prefix: Mapped[str] = mapped_column(String(16), comment="明文前缀（展示用）")
    key_hash: Mapped[str] = mapped_column(
        String(64), unique=True, comment="SHA-256 摘要"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, comment="绑定用户（逻辑引用）"
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    scopes: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="授权权限编码列表"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


# ---------------------------------------------------------------------------
# 业务核心表
# ---------------------------------------------------------------------------
class Project(Base):
    """测试项目（业务顶层实体）。"""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="项目编号（业务展示）"
    )
    name: Mapped[str] = mapped_column(String(128), comment="项目名称")
    description: Mapped[str | None] = mapped_column(Text, default=None)
    owner_id: Mapped[int] = mapped_column(
        Integer, index=True, comment="负责人（逻辑引用）"
    )
    owner_name: Mapped[str | None] = mapped_column(String(64), default=None)
    target_system: Mapped[str | None] = mapped_column(
        String(512), default=None, comment="被测系统信息"
    )
    # M8：被测环境地址列表（JSON 数组：[{"name":"测试环境","base_url":"https://...","is_default":true}]）
    environments: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="被测环境地址列表"
    )
    visibility: Mapped[str] = mapped_column(
        String(16), default=Visibility.PRIVATE.value
    )
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class TestEngine(Base):
    """测试引擎注册表（传统4类 + AI 6类 + 工程化3类 = 13 类）。"""

    __tablename__ = "test_engines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engine_code: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        comment="引擎编码，如 UI_TEST / HALLUCINATION_TEST",
    )
    engine_name: Mapped[str] = mapped_column(String(128), comment="引擎名称")
    engine_type: Mapped[str] = mapped_column(
        String(32), comment="TRADITIONAL/AI/ENGINEERING"
    )
    category: Mapped[str] = mapped_column(
        String(64),
        comment="细分类别，如 UI/API/PERF/DATAFLOW/HALLUCINATION/REDTEAM/RAG/MULTITURN/ETHICS/EVAL/CASE_GEN/SELF_HEAL/DEFECT_PREDICT",
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    entry_point: Mapped[str] = mapped_column(
        String(256), default="", comment="实现类路径"
    )
    supports_params: Mapped[dict | None] = mapped_column(
        JSONB, default=dict, comment="支持的参数 schema"
    )
    status: Mapped[str] = mapped_column(String(16), default=EngineStatus.ENABLED.value)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True)
    fidelity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="real", server_default=text("'real'"),
        comment="实现真实度：real=真实执行 / rule=规则匹配 / simulated=模拟演示；"
        "来源为引擎类属性，注册时回写（ES9-P-01/P-13）",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class TestTask(Base):
    """测试任务（一次执行实例，可挂载多个引擎分步执行）。"""

    __tablename__ = "test_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="任务编号（业务展示）"
    )
    project_id: Mapped[int] = mapped_column(
        Integer, index=True, comment="所属项目（逻辑引用）"
    )
    project_code: Mapped[str | None] = mapped_column(String(32), default=None)
    name: Mapped[str] = mapped_column(String(128), comment="任务名称")
    description: Mapped[str | None] = mapped_column(Text, default=None)
    task_type: Mapped[str] = mapped_column(String(32), comment="单测/回归/持续")
    engines: Mapped[list] = mapped_column(
        JSONB, default=list, comment="引擎编码列表，顺序执行"
    )
    config: Mapped[dict | None] = mapped_column(
        JSONB, default=dict, comment="全局任务配置（目标/权重/阈值）"
    )
    status: Mapped[str] = mapped_column(
        String(32), default=TaskStatus.PENDING.value, index=True
    )
    trigger_mode: Mapped[str] = mapped_column(
        String(16), default="MANUAL", comment="MANUAL/SCHEDULED/API"
    )
    schedule_cron: Mapped[str | None] = mapped_column(String(64), default=None)
    progress: Mapped[int] = mapped_column(Integer, default=0, comment="0-100 进度")
    current_step: Mapped[str | None] = mapped_column(String(64), default=None)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    summary: Mapped[dict | None] = mapped_column(
        JSONB, default=dict, comment="汇总：通过/失败/用例数/指标"
    )
    error_msg: Mapped[str | None] = mapped_column(Text, default=None)
    conclusion: Mapped[str | None] = mapped_column(
        Text, default=None, comment="v2.0 P1：业务结论（质量未达标原因/风险提示），用于前端展示"
    )
    # MVP2.0 增量：套件归属 / 被测版本
    suite_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    task_version: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    # ES10-P-02：项目版本归因（inti.sql section 73）
    project_version_id: Mapped[int | None] = mapped_column(
        Integer, default=None,
        comment="ES10-P-02：任务创建时自动落的项目版本（软引用 project_versions.id，"
        "基线优先否则最新；可空=无版本）",
    )
    # ES8 M5 增量：CI 质量门禁（inti.sql section 49）
    gate_rules: Mapped[str] = mapped_column(
        Text,
        default="[]",
        comment="门禁规则 JSON 数组：[{\"metric\",\"op\",\"threshold\"}]，空=非门禁任务",
    )
    gate_result: Mapped[str | None] = mapped_column(
        String(16), default=None, comment="门禁结论 PASSED|FAILED，NULL=未评估"
    )
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_by_name: Mapped[str | None] = mapped_column(String(64), default=None)
    executor: Mapped[str | None] = mapped_column(
        String(64), default=None, comment="触发执行的测试人员（区别于创建人）"
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class TaskStep(Base):
    """任务步骤（单引擎执行记录与产物）。"""

    __tablename__ = "task_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_no: Mapped[str] = mapped_column(
        String(32), unique=True, comment="步骤编号（业务展示）"
    )
    task_id: Mapped[int] = mapped_column(
        Integer, index=True, comment="任务ID（逻辑引用）"
    )
    seq: Mapped[int] = mapped_column(Integer, default=1, comment="执行顺序")
    engine_code: Mapped[str] = mapped_column(String(64), index=True)
    engine_name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.PENDING.value)
    config: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    result_summary: Mapped[dict | None] = mapped_column(
        JSONB, default=dict, comment="步骤结果摘要"
    )
    report_ids: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="产出报告ID列表"
    )
    error_msg: Mapped[str | None] = mapped_column(Text, default=None)
    executor: Mapped[str | None] = mapped_column(
        String(64), default=None, comment="执行该步骤的测试人员"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class TestCase(Base):
    """测试用例（传统/AI 通用；带类别与场景元数据）。"""

    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="用例编号（业务展示）"
    )
    project_id: Mapped[int] = mapped_column(
        Integer, index=True, comment="所属项目（逻辑引用）"
    )
    dataset_id: Mapped[int | None] = mapped_column(
        Integer, index=True, default=None, comment="所属数据集（逻辑引用）"
    )
    title: Mapped[str] = mapped_column(String(256), comment="用例标题")
    module: Mapped[str | None] = mapped_column(
        String(128), default=None, comment="所属模块（如 登录/订单/支付）"
    )
    last_actual: Mapped[dict | None] = mapped_column(
        JSONB, default=None, comment="最近一次实际输出摘要（断言实际值）"
    )
    category: Mapped[str] = mapped_column(
        String(64),
        index=True,
        comment="类别：UI/API/PERF/DATAFLOW/HALLUCINATION/REDTEAM/RAG/MULTITURN/ETHICS/EVAL/CASE_GEN",
    )
    source: Mapped[str] = mapped_column(
        String(16), default="MANUAL", comment="MANUAL/AGENT_GEN/IMPORT/AI_GEN"
    )
    severity: Mapped[str] = mapped_column(String(16), default="P2", comment="P0-P4")
    priority: Mapped[str] = mapped_column(
        String(16), default="MEDIUM", comment="HIGH/MEDIUM/LOW"
    )
    status: Mapped[str] = mapped_column(
        String(16), default="ACTIVE", comment="ACTIVE/ARCHIVED/FAILED"
    )
    precondition: Mapped[str | None] = mapped_column(Text, default=None)
    steps: Mapped[list | None] = mapped_column(JSONB, default=list, comment="步骤数组")
    expected: Mapped[str | None] = mapped_column(Text, default=None, comment="预期结果")
    request_spec: Mapped[dict | None] = mapped_column(
        JSONB, default=None, comment="请求规格（API/UI 定位器）"
    )
    # v2.0 全维度测试扩展（开发文档 §8.1 / inti.sql §26.1）
    performance_config: Mapped[dict | None] = mapped_column(
        JSONB, default=None, comment="性能测试配置{concurrency,duration,ramp_up,target_rt_p95,target_rt_p99,target_tps}"
    )
    owasp_id: Mapped[str | None] = mapped_column(
        String(32), default=None, comment="OWASP Top 10 编号（安全用例），如 A03:2021"
    )
    dom_selector: Mapped[str | None] = mapped_column(
        String(500), default=None, comment="DOM 选择器（UI 用例），如 #name / .ant-pagination-next"
    )
    viewport_config: Mapped[dict | None] = mapped_column(
        JSONB, default=None, comment="视口配置{width,height}（兼容性测试）"
    )
    browser_config: Mapped[str | None] = mapped_column(
        String(32), default=None, comment="浏览器配置：chromium/firefox/webkit（兼容性测试）"
    )
    review_status: Mapped[str | None] = mapped_column(
        String(16), default=None, comment="人工评审状态：PENDING/IN_REVIEW/DONE（OWASP 非自动化项闭环跟踪）"
    )
    tags: Mapped[list | None] = mapped_column(JSONB, default=list)
    content_schema: Mapped[dict | None] = mapped_column(
        JSONB, default=None, comment="用例内容 schema key（驱动前端动态渲染）"
    )
    preconditions: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="前置条件[{kind,desc}]"
    )
    test_data: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="测试数据分组[{case,params}]"
    )
    assertions: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="断言集[{path,op,expected,note}]"
    )
    extract_vars: Mapped[dict | None] = mapped_column(
        JSONB, default=dict, comment="提取变量映射{var:value}"
    )
    post_cleanup: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="后置清理[{action,target,params}]"
    )
    requirement_id: Mapped[str | None] = mapped_column(
        String(64), default=None, comment="需求追踪"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_result: Mapped[str | None] = mapped_column(
        String(16), default=None, comment="PASS/FAIL/SKIP"
    )
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    pass_rate: Mapped[float] = mapped_column(Float, default=0.0, comment="历史通过率")
    avg_duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    owner_id: Mapped[int | None] = mapped_column(Integer, default=None)
    creator: Mapped[str | None] = mapped_column(String(64), default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class TestDataset(Base):
    """数据集（用例集合，用于批量执行与模型测试）。"""

    __tablename__ = "test_datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="数据集编号（业务展示）"
    )
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(128), comment="数据集名称")
    category: Mapped[str] = mapped_column(
        String(64), comment="数据集类别（对应用例类别）"
    )
    case_ids: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="用例ID列表（逻辑聚合，不建多对多表）"
    )
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(
        String(16), default="MANUAL", comment="MANUAL/UPLOAD/AI_GEN"
    )
    visibility: Mapped[str] = mapped_column(
        String(16), default=Visibility.PRIVATE.value
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # 参数列定义：供测试用例的测试数据编辑器从数据集参数列一键导入
    parameters: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="参数列定义：[{name, type, example}]"
    )
    # 数据行定义：数据集实际测试数据，每行是参数列名到值的映射，供数据驱动测试逐行展开
    data_rows: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="数据行定义：[{列名: 值, ...}]"
    )
    meta: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class Scenario(Base):
    """测试场景（数据流/端到端场景编排，步骤间传递变量）。"""

    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="场景编号（业务展示）"
    )
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(128), comment="场景名称")
    description: Mapped[str | None] = mapped_column(Text, default=None)
    steps: Mapped[list] = mapped_column(
        JSONB, default=list, comment="步骤编排：[{seq, action, target, config, extract}]"
    )
    variables: Mapped[dict | None] = mapped_column(
        JSONB, default=dict, comment="变量定义"
    )
    data_sources: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="数据源（数据库/文件/API）"
    )
    visibility: Mapped[str] = mapped_column(
        String(16), default=Visibility.PRIVATE.value
    )
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # AI 测试优化 25.3：AI 生成场景 source 标识；P2-08 增 UI_RECORD（Playwright 录制导入）
    source: Mapped[str] = mapped_column(
        String(16), default="MANUAL", comment="MANUAL/AI_GEN/UI_RECORD"
    )
    # AI 测试优化 B9 补强：场景所属模块，参与覆盖矩阵的 covered 判定
    module: Mapped[str | None] = mapped_column(String(128), default=None, comment="场景所属模块")


class Report(Base):
    """测试报告（含结构化结果与下载文件路径）。"""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="报告编号（业务展示）"
    )
    task_id: Mapped[int] = mapped_column(
        Integer, index=True, comment="来源任务（逻辑引用）"
    )
    task_no: Mapped[str | None] = mapped_column(String(32), default=None)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(256), comment="报告标题")
    report_type: Mapped[str] = mapped_column(
        String(32), default="FULL", comment="FULL/SUMMARY"
    )
    format: Mapped[str] = mapped_column(
        String(16), default="html", comment="html/pdf/md/json"
    )
    status: Mapped[str] = mapped_column(
        String(16), default=ReportStatus.GENERATING.value, index=True
    )
    file_path: Mapped[str | None] = mapped_column(
        String(512), default=None, comment="产物文件路径"
    )
    file_size: Mapped[int | None] = mapped_column(Integer, default=None)
    content: Mapped[dict | None] = mapped_column(
        JSONB, default=dict, comment="结构化报告内容"
    )
    summary: Mapped[dict | None] = mapped_column(JSONB, default=dict, comment="指标摘要")
    performance_metrics: Mapped[dict | None] = mapped_column(
        JSONB, default=None, comment="性能指标（rt_p50/rt_p95/rt_p99/tps/error_rate，PERF 引擎汇总）"
    )
    # v2.0 新增：环境指纹 + 风险等级（BUG-002/012）
    environment: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"),
        comment="环境指纹 JSONB：{sut_version, sut_branch, sut_commit, sut_url, os, browser, browser_version, viewport, dependencies, started_at, finished_at, duration_sec}"
    )
    risk_level: Mapped[str] = mapped_column(
        String(16), default="none", server_default=text("'none'"),
        index=True, comment="风险等级：critical/high/medium/low/none"
    )
    risk_basis: Mapped[str] = mapped_column(
        String(512), default="", server_default=text("''"),
        comment="风险等级判定依据（面向用户展示）"
    )
    # ES9 UAT 验收报告（inti.sql section 59）——三列均可空/有默认，存量报告零影响
    report_subtype: Mapped[str | None] = mapped_column(
        String(16), default=None,
        comment="报告子类型：NULL=测试报告 | UAT=验收报告",
    )
    acceptance: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"),
        comment="验收签核状态机：{status,verdict,note,signer_vendor,signer_customer,finalized_at}",
    )
    parent_report_id: Mapped[int | None] = mapped_column(
        Integer, default=None,
        comment="验收版本链：指向上一版 UAT 报告（NULL=首版）",
    )
    generated_by: Mapped[str | None] = mapped_column(String(64), default=None)
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class EvalSet(Base):
    """评测集（AI 评测问题/断言集，平台化评测的输入）。"""

    __tablename__ = "eval_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="评测集编号（业务展示）"
    )
    name: Mapped[str] = mapped_column(String(128), comment="评测集名称")
    category: Mapped[str] = mapped_column(
        String(64),
        index=True,
        comment="HALLUCINATION/REDTEAM/RAG/MULTITURN/ETHICS/EVAL",
    )
    # D-4：可选关联项目（横向对比页可按项目聚合）
    project_id: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="可选关联项目（逻辑引用）"
    )
    items: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        comment="评测项：[{no, prompt, expected, refs, rubric, threat}]",
    )
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[str] = mapped_column(
        String(32), default="v1", comment="评测集版本（items 变化自动递增）"
    )
    content_schema: Mapped[dict | None] = mapped_column(
        JSONB, default=None, comment="条目 schema（区分 EVAL/安全样本等）"
    )
    source: Mapped[str] = mapped_column(
        String(16), default="MANUAL",
        comment="MANUAL/UPLOAD/IMPORT/AI_GEN/FROM_RUN(失败用例派生)/FROM_REVIEW(评审回流)",
    )
    meta: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    # ES8 M7：派生血缘（from_run/from_review 建集时记录来源评测集）
    parent_set_id: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="父评测集 id（派生血缘，逻辑引用）"
    )
    visibility: Mapped[str] = mapped_column(
        String(16), default=Visibility.PRIVATE.value
    )
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    # AI 测试优化 25.2：模块与关联用例/数据集埋点（覆盖矩阵聚合）
    module: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    rel_case_ids: Mapped[list | None] = mapped_column(JSONB, default=list)
    rel_dataset_ids: Mapped[list | None] = mapped_column(JSONB, default=list)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class EvalSetRevision(Base):
    """ES8 M7：评测集版本快照（编辑升版前旧 items 整文入库，行级差异留痕）。

    字段与 database/inti.sql section 51.2 的 DDL 逐一对齐。
    version 为数字版本 N（对应主表字符串 vN）；content 为旧 items 的 JSON 整文。
    """

    __tablename__ = "eval_set_revisions"

    __table_args__ = (
        Index("ix_eval_set_revisions_set_version", "eval_set_id", "version"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    eval_set_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="eval_sets.id（逻辑引用）"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="快照对应的版本号 N（主表 vN 的数字位）"
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="整文快照：升版前 items 的 JSON 序列化"
    )
    diff_stats: Mapped[str | None] = mapped_column(
        Text, default=None,
        comment='与升版后新内容的行级对比 {"added":n,"removed":n,"unchanged":n}',
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class EvalRun(Base):
    """评测运行（对目标模型/Agent 的一次评测执行）。"""

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="运行编号（业务展示）"
    )
    task_id: Mapped[int | None] = mapped_column(
        Integer, default=None, index=True, comment="关联任务（由任务执行自动创建时写入）"
    )
    eval_set_id: Mapped[int] = mapped_column(Integer, index=True)
    eval_set_code: Mapped[str | None] = mapped_column(String(32), default=None)
    target_type: Mapped[str] = mapped_column(
        String(32), comment="MODEL/RAG/AGENT/API（见 EVAL_RUN_TARGET_TYPES，勿与注册表协议混用）"
    )
    target_id: Mapped[str] = mapped_column(
        String(128), comment="目标标识（模型名/Agent ID/API端点）"
    )
    model_gateway: Mapped[str | None] = mapped_column(
        String(256), default=None, comment="模型网关配置名"
    )
    judge_mode: Mapped[str] = mapped_column(
        String(16), default="RULE", comment="RULE/MODEL/HYBRID"
    )
    judge_model: Mapped[str | None] = mapped_column(
        String(128), default=None, comment="裁判模型"
    )
    status: Mapped[str] = mapped_column(
        String(16), default=EvalStatus.PENDING.value, index=True
    )
    item_results: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="逐项结果 [item_no, verdict, score, detail]"
    )
    overall_score: Mapped[float | None] = mapped_column(Float, default=None)
    verdict: Mapped[str | None] = mapped_column(
        String(16), default=None, comment="PASS/FAIL"
    )
    summary: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    report_id: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="产出报告（逻辑引用）"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    # 6 引擎改进 §7.2：来源引擎/数据集版本/可复现快照/成本
    engine_code: Mapped[str | None] = mapped_column(
        String(64), default=None, index=True, comment="来源引擎编码"
    )
    dataset_version: Mapped[str | None] = mapped_column(
        String(32), default=None, comment="数据集版本快照"
    )
    run_snapshot: Mapped[dict | None] = mapped_column(
        JSONB, default=None,
        comment="可复现快照：{judge_model,target_mode,dataset_version,temperature,seed,engine_version}",
    )
    estimated_cost: Mapped[float | None] = mapped_column(
        Float, default=None, comment="预估 LLM 成本（元）"
    )
    actual_cost: Mapped[float | None] = mapped_column(
        Float, default=None, comment="实际成本（元）"
    )
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    question_bank_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None,
        comment="ES9：本次执行所用题库（软引用 question_bank.id）；报告页样本量与来源取数入口",
    )
    # ES10-P-01：知识源接入评测执行链（inti.sql section 72）
    fact_source_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None,
        comment="ES10-P-01：本次评测使用的事实基准知识源（软引用 fact_sources.id）；"
        "检索失败降级为无参照并记 note",
    )
    # ES10-P-02：版本归因（inti.sql section 73）
    project_version_id: Mapped[int | None] = mapped_column(
        Integer, default=None,
        comment="ES10-P-02：评测归因的项目版本（软引用 project_versions.id，基线优先否则最新）",
    )
    # ES11（inti.sql section 76.1）：活动目的与血缘
    run_purpose: Mapped[str] = mapped_column(
        String(16), nullable=False, default="STANDARD", server_default=text("'STANDARD'"),
        comment="ES11：STANDARD/REGRESSION/RETEST/TRACE_REPLAY",
    )
    parent_run_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="ES11：来源运行（复测/回流），软引用 eval_runs.id"
    )
    baseline_run_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="ES11：对比基线运行，软引用 eval_runs.id"
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class ModelConfig(Base):
    """模型网关配置（统一管理多个模型提供商）。"""

    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="配置编号（业务展示）"
    )
    name: Mapped[str] = mapped_column(String(128), comment="配置名称")
    provider: Mapped[str] = mapped_column(
        String(64), comment="openai/baidu/qwen/deepseek/local"
    )
    base_url: Mapped[str | None] = mapped_column(String(512), default=None)
    model: Mapped[str] = mapped_column(String(128), comment="模型名")
    api_key_env: Mapped[str | None] = mapped_column(
        String(64), default=None, comment="环境变量名（密钥不落库）"
    )
    api_key_enc: Mapped[str | None] = mapped_column(
        Text, default=None,
        comment="UI 托管密钥密文（Fernet）；与 api_key_env 互斥，日志/接口禁止输出本列明文（ES9-P-05）",
    )
    timeout_sec: Mapped[int] = mapped_column(Integer, default=60)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    temperature: Mapped[float] = mapped_column(Float, default=0.2)
    seed: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="固定采样种子，可复现判定"
    )
    headers: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    usage: Mapped[str] = mapped_column(
        String(16), default="CHAT", comment="模型用途：CHAT（对话）/EMBEDDING（向量嵌入）"
    )
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    input_price_per_mtok: Mapped[float] = mapped_column(
        Float, default=0.0, comment="输入单价（元/百万 token）"
    )
    output_price_per_mtok: Mapped[float] = mapped_column(
        Float, default=0.0, comment="输出单价（元/百万 token）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class TargetRegistry(Base):
    """被测系统注册表：AI 引擎的统一被测门面（与 model_configs 的评判模型分离，根治 F7）。"""

    __tablename__ = "target_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="被测对象编号 TG-xxx"
    )
    name: Mapped[str] = mapped_column(String(128), comment="名称")
    target_type: Mapped[str] = mapped_column(
        String(16), comment="LLM_API/APP_API/INTERNAL_MODEL"
    )
    base_url: Mapped[str] = mapped_column(String(512), comment="服务地址")
    chat_path: Mapped[str | None] = mapped_column(
        String(256), default="/chat/completions", comment="对话路径（LLM_API）"
    )
    protocol: Mapped[str] = mapped_column(
        String(16), default="OPENAI", comment="OPENAI/CUSTOM"
    )
    auth_env: Mapped[str | None] = mapped_column(
        String(64), default=None, comment="密钥环境变量名（密钥不落库）"
    )
    headers: Mapped[dict | None] = mapped_column(JSONB, default=dict, comment="附加请求头")
    request_template: Mapped[dict | None] = mapped_column(
        JSONB, default=None, comment="CUSTOM 协议请求体模板（{{prompt}}/{{history_json}}）"
    )
    response_path: Mapped[str | None] = mapped_column(
        String(128), default=None, comment="响应取值点路径 choices.0.message.content"
    )
    model: Mapped[str | None] = mapped_column(
        String(128), default=None, comment="LLM_API 被测模型名（OpenAI 协议 body.model）"
    )
    timeout_sec: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    remark: Mapped[str | None] = mapped_column(String(512), default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class Notification(Base):
    """站内通知（执行完成/告警/审批）。"""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notif_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="通知编号（业务展示）"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, comment="接收人（逻辑引用）"
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    title: Mapped[str] = mapped_column(String(256), comment="标题")
    content: Mapped[str | None] = mapped_column(Text, default=None)
    notif_type: Mapped[str] = mapped_column(
        String(32), default="SYSTEM", comment="SYSTEM/TASK/ALERT/APPROVAL"
    )
    channel: Mapped[str] = mapped_column(
        String(32), default=NotifyChannel.INNER_MSG.value
    )
    ref_no: Mapped[str | None] = mapped_column(
        String(64), default=None, comment="关联业务编号"
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class Tenant(Base):
    """租户主数据（优化7 T6；仅 saas 形态运营后台读写）。"""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ES7-T-1：软删租户保留 code 占用（inti.sql 部分唯一索引 WHERE deleted_at IS NULL 收口）
    code: Mapped[str] = mapped_column(String(32), index=True, comment="租户短码（未删除行内唯一）")
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(16), default="ACTIVE", server_default=text("'ACTIVE'"),
        comment="ACTIVE|SUSPENDED|CLOSED",
    )
    contact_email: Mapped[str | None] = mapped_column(String(256), default=None)
    note: Mapped[str | None] = mapped_column(String(512), default=None)
    # ES8 M1：订购关系权威落点扩列（inti.sql section 45.1 同步）
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="租户管理员（system_users.id，逻辑引用）"
    )
    org_id: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="saas：该租户的默认根组织（organizations.id）"
    )
    plan_code: Mapped[str | None] = mapped_column(
        String(32), default=None, comment="当前套餐（billing_plans.code 逻辑引用，冗余展示位）"
    )
    source: Mapped[str] = mapped_column(
        String(16), default="self_serve", server_default=text("'self_serve'"),
        comment="租户来源 self_serve|sales|sync",
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, comment="试用到期（NULL=非试用）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class Subscription(Base):
    """订购记录（ES8 M1；支付/开通/变更全落此表，状态机权威，billing_quotas 为派生缓存）。"""

    __tablename__ = "subscriptions"

    # 状态机：TRIALING|ACTIVE|GRACE|PAST_DUE|CANCELED|EXPIRED
    STATUS_TRIALING = "TRIALING"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_GRACE = "GRACE"
    STATUS_PAST_DUE = "PAST_DUE"
    STATUS_CANCELED = "CANCELED"
    STATUS_EXPIRED = "EXPIRED"
    # 未终止态（同租户同时最多一条，部分唯一索引收口）
    STATUS_LIVE = (STATUS_TRIALING, STATUS_ACTIVE, STATUS_GRACE, STATUS_PAST_DUE)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True, comment="tenants.id")
    plan_code: Mapped[str] = mapped_column(String(32), comment="billing_plans.code")
    status: Mapped[str] = mapped_column(
        String(16), default="TRIALING", server_default=text("'TRIALING'"),
        comment="TRIALING|ACTIVE|GRACE|PAST_DUE|CANCELED|EXPIRED",
    )
    billing_cycle: Mapped[str] = mapped_column(
        String(8), default="monthly", server_default=text("'monthly'"),
        comment="monthly|yearly",
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, comment="试用截止（status=TRIALING 时有值）"
    )
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), comment="期末取消标记"
    )
    anonymize_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None,
        comment="ES8-M12：注销并匿名化到期时间（cancel-and-anonymize 写 now()+30d，到期日任务置内容列 NULL 留墓碑行）",
    )
    auto_renew: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    order_id: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="首购订单（mock 支付，逻辑引用）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (
        # 同租户同时最多一条未终止订购（PG 部分唯一索引；SQLite create_all 退化普通索引无害）
        Index(
            "ix_subscriptions_tenant", "tenant_id", unique=True,
            postgresql_where=text("status NOT IN ('CANCELED','EXPIRED')"),
        ),
    )


class BillingQuota(Base):
    """计费配额（租户级资源额度）。"""

    __tablename__ = "billing_quotas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    plan: Mapped[str] = mapped_column(
        String(32), default="TRIAL", comment="TRIAL/PRO/ENTERPRISE"
    )
    task_quota: Mapped[int] = mapped_column(Integer, default=100, comment="任务额度")
    task_used: Mapped[int] = mapped_column(Integer, default=0)
    eval_quota: Mapped[int] = mapped_column(Integer, default=50, comment="评测额度")
    eval_used: Mapped[int] = mapped_column(Integer, default=0)
    storage_quota_mb: Mapped[int] = mapped_column(Integer, default=1024)
    storage_used_mb: Mapped[int] = mapped_column(Integer, default=0)
    api_calls_quota: Mapped[int] = mapped_column(Integer, default=10000)
    api_calls_used: Mapped[int] = mapped_column(Integer, default=0)
    token_budget: Mapped[int] = mapped_column(
        BigInteger, default=0, comment="token 预算（0=不限）"
    )
    token_used: Mapped[int] = mapped_column(BigInteger, default=0, comment="已用 token")
    credits: Mapped[float] = mapped_column(Float, default=0.0, comment="可用额度（充值累加）")
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, comment="账期起始（月初锚定，T6b）"
    )
    period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, comment="账期截止（T6b）"
    )
    sub_status: Mapped[str] = mapped_column(
        String(16), default="ACTIVE", server_default=text("'ACTIVE'"),
        comment="订阅状态机 ACTIVE|GRACE|PAST_DUE|CANCELED（T6b）",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class BillingPlan(Base):
    """计费套餐（SaaS 商业化前置；无外键）。"""

    __tablename__ = "billing_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, comment="套餐编码")
    name: Mapped[str] = mapped_column(String(128), comment="套餐名称")
    description: Mapped[str | None] = mapped_column(Text, default=None)
    price_monthly: Mapped[float] = mapped_column(Float, default=0.0, comment="月费（元）")
    # ---- ES8 M2：分币整数权威价（下单/展示一律读 cents 列，元列仅历史展示遗留）----
    price_monthly_cents: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), comment="月付权威价（分）"
    )
    price_yearly_cents: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), comment="年付权威价（分）"
    )
    trial_days: Mapped[int] = mapped_column(
        Integer, default=14, server_default=text("14"), comment="试用天数（注册页 CTA 文案来源）"
    )
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"),
        comment="是否公开出现在 /pricing 页（FALSE=仅销售定向）",
    )
    credits: Mapped[float] = mapped_column(Float, default=0.0, comment="初始额度")
    max_tasks: Mapped[int | None] = mapped_column(Integer, default=None, comment="最大任务数（空不限制）")
    features: Mapped[list | None] = mapped_column(JSONB, default=list, comment="功能点清单")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", comment="ACTIVE/DISABLED")
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class BillingTopUp(Base):
    """充值申请记录（模拟；无外部支付对接）。"""

    __tablename__ = "billing_topups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, comment="充值单号")
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    plan_id: Mapped[int | None] = mapped_column(Integer, default=None)
    amount: Mapped[float] = mapped_column(Float, default=0.0, comment="充值金额（元）")
    credits_add: Mapped[float] = mapped_column(Float, default=0.0, comment="到账额度")
    status: Mapped[str] = mapped_column(String(16), default="PENDING", comment="PENDING/SUCCESS/FAILED/CANCELLED")
    channel: Mapped[str] = mapped_column(String(32), default="ADMIN", comment="充值渠道")
    # ES8 M2-E2（方案 §3.2）：来源标记——支付成功赠送 credits 走 source='order_bonus'，
    # 与人工/后台充值区分（NULL=历史遗留行，语义等同 MANUAL）
    source: Mapped[str | None] = mapped_column(
        String(32), default=None, comment="来源：NULL=人工充值 | order_bonus=支付赠送"
    )
    remark: Mapped[str | None] = mapped_column(String(512), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Order(Base):
    """订单（ES8 M2；下单→支付→履约链路主体， inti.sql section 46）。"""

    __tablename__ = "orders"

    # 状态机：PENDING|PAID|FULFILLED|REFUNDED|CLOSED|FAILED
    STATUS_PENDING = "PENDING"
    STATUS_PAID = "PAID"
    STATUS_FULFILLED = "FULFILLED"
    STATUS_REFUNDED = "REFUNDED"
    STATUS_CLOSED = "CLOSED"
    STATUS_FAILED = "FAILED"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True, comment="tenants.id")
    subscription_id: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="履约后回填（subscriptions.id 逻辑引用）"
    )
    order_no: Mapped[str] = mapped_column(
        String(40), unique=True, index=True, comment="商户订单号（gen_no('SO')）"
    )
    plan_code: Mapped[str] = mapped_column(String(32), comment="billing_plans.code")
    billing_cycle: Mapped[str] = mapped_column(
        String(8), comment="monthly|yearly"
    )
    amount_cents: Mapped[int] = mapped_column(Integer, comment="应付（分，权威）")
    discount_cents: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), comment="折扣（分）"
    )
    credit_deduct_cents: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"),
        comment="credits 抵扣（分），下单时封顶=订单额50%",
    )
    status: Mapped[str] = mapped_column(
        String(16), default="PENDING", server_default=text("'PENDING'"),
        comment="PENDING|PAID|FULFILLED|REFUNDED|CLOSED|FAILED",
    )
    provider: Mapped[str] = mapped_column(
        String(16), default="mock", server_default=text("'mock'"),
        comment="mock|wechat|alipay",
    )
    provider_order_id: Mapped[str | None] = mapped_column(
        String(64), default=None, comment="渠道预下单号"
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, comment="支付成功时间"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Payment(Base):
    """支付流水（ES8 M2；trade_no 唯一幂等键，回调原文留档）。"""

    __tablename__ = "payments"

    STATUS_SUCCESS = "SUCCESS"
    STATUS_REFUND = "REFUND"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True, comment="orders.id")
    trade_no: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, comment="渠道交易号（幂等键）"
    )
    provider: Mapped[str] = mapped_column(String(16), comment="mock|wechat|alipay")
    amount_cents: Mapped[int] = mapped_column(Integer, comment="实付（分）")
    status: Mapped[str] = mapped_column(
        String(16), comment="SUCCESS|REFUND"
    )
    raw_notify: Mapped[str | None] = mapped_column(
        Text, default=None, comment="回调原文（验签留档）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BillingRecord(Base):
    """计费流水（任务/评测消耗记录）。"""

    __tablename__ = "billing_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="流水编号（业务展示）"
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, default=None)
    biz_type: Mapped[str] = mapped_column(String(32), comment="TASK/EVAL/STORAGE/API")
    ref_no: Mapped[str | None] = mapped_column(
        String(64), default=None, comment="关联业务编号"
    )
    amount: Mapped[float] = mapped_column(Float, default=0.0, comment="扣减量")
    unit: Mapped[str] = mapped_column(
        String(16), default="COUNT", comment="COUNT/TOKEN/MB"
    )
    description: Mapped[str | None] = mapped_column(String(256), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )


class TaskArtifact(Base):
    """任务资产（执行产物：截图/日志/JSON 结果/文件）。"""

    __tablename__ = "task_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artifact_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="资产编号（业务展示）"
    )
    task_id: Mapped[int] = mapped_column(Integer, index=True)
    step_id: Mapped[int | None] = mapped_column(Integer, default=None)
    file_name: Mapped[str] = mapped_column(String(256))
    file_path: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str | None] = mapped_column(String(128), default=None)
    art_type: Mapped[str] = mapped_column(
        String(32), default="LOG", comment="LOG/SCREENSHOT/JSON/HTML/IMAGE/OTHER"
    )
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


# ---------------------------------------------------------------------------
# 优化方案新增模型（P0-P2）
# ---------------------------------------------------------------------------


class SandboxExecution(Base):
    """沙箱执行实例记录。"""

    __tablename__ = "sandbox_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="执行编号"
    )
    task_id: Mapped[int] = mapped_column(
        Integer, index=True, comment="关联任务ID（逻辑引用）"
    )
    task_no: Mapped[str | None] = mapped_column(
        String(32), index=True, comment="任务编号（冗余，方便查询）"
    )
    sandbox_id: Mapped[str | None] = mapped_column(String(64), comment="Docker 容器ID")
    image_id: Mapped[int | None] = mapped_column(
        Integer, comment="使用的镜像ID（逻辑引用 sandbox_images.id）"
    )
    status: Mapped[str] = mapped_column(
        String(24), default=SandboxStatus.PENDING.value, index=True
    )
    engine_code: Mapped[str] = mapped_column(String(32), comment="执行引擎标识")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    logs: Mapped[str | None] = mapped_column(Text, comment="stdout+stderr")
    artifacts: Mapped[list[dict] | None] = mapped_column(
        JSONB, default=list, comment="产物元数据列表"
    )
    result_payload: Mapped[dict | None] = mapped_column(
        JSONB, default=dict, comment="引擎结构化结果"
    )
    error_msg: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(
        String(64), default=None,
        comment="ES9：执行 worker 实例标识（pool 模式）；legacy docker 模式为容器 id",
    )
    # 审计与租户
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class SandboxImage(Base):
    """沙箱镜像注册表。"""

    __tablename__ = "sandbox_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="镜像编号"
    )
    image_name: Mapped[str] = mapped_column(String(128), comment="镜像名称")
    image_tag: Mapped[str] = mapped_column(String(64), default="latest")
    registry_url: Mapped[str | None] = mapped_column(
        String(256), comment="私有仓库地址，空表示本地"
    )
    full_name: Mapped[str] = mapped_column(
        String(256), comment="完整镜像名，如 registry/xxx:tag"
    )
    description: Mapped[str | None] = mapped_column(String(512))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 审计
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class ComplianceClause(Base):
    """合规条款库（框架 3.0 条款定义）。"""

    __tablename__ = "compliance_clauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clause_code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="条款编号，如 3.0-4.2.1"
    )
    category: Mapped[str] = mapped_column(
        String(32), index=True, comment="推理规划/身份权限/调用执行/记忆存储"
    )
    title: Mapped[str] = mapped_column(String(256), comment="条款标题")
    description: Mapped[str | None] = mapped_column(
        Text, default=None, comment="条款描述"
    )
    risk_level: Mapped[str] = mapped_column(
        String(16), comment="CRITICAL/HIGH/MEDIUM/LOW"
    )
    detection_methods: Mapped[list] = mapped_column(
        JSONB, default=list, comment="可检测引擎编码列表"
    )
    framework_version: Mapped[str] = mapped_column(
        String(8), default="3.0", comment="框架版本"
    )
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class ReportComplianceAlignment(Base):
    """报告-条款对齐结果（多对多关联，无 ForeignKey）。"""

    __tablename__ = "report_compliance_alignments"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "clause_id", "tenant_id", name="uq_report_clause_tenant"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        Integer, index=True, comment="报告ID（逻辑引用）"
    )
    clause_id: Mapped[int] = mapped_column(
        Integer, index=True, comment="条款ID（逻辑引用）"
    )
    result: Mapped[str] = mapped_column(
        String(16), comment="PASS/LOW/MEDIUM/HIGH/CRITICAL/N/A"
    )
    evidence: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="证据引用编号列表"
    )
    recommendation: Mapped[str | None] = mapped_column(
        Text, default=None, comment="整改建议"
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EngineCaseLibrary(Base):
    """引擎用例库（各引擎内置检测 Payload 的统一存储）。"""

    __tablename__ = "engine_case_libraries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="用例编号（业务展示）"
    )
    engine_code: Mapped[str] = mapped_column(
        String(64), index=True, comment="所属引擎编码"
    )
    title: Mapped[str] = mapped_column(String(256), comment="用例标题")
    threat_type: Mapped[str] = mapped_column(
        String(64), index=True, comment="威胁子类型"
    )
    payload: Mapped[str] = mapped_column(Text, comment="攻击/检测载荷")
    expected_behavior: Mapped[str] = mapped_column(
        Text, comment="预期系统行为（拒绝/忽略/报错/不泄露）"
    )
    severity: Mapped[str] = mapped_column(
        String(16), default="MEDIUM", comment="CRITICAL/HIGH/MEDIUM/LOW"
    )
    tags: Mapped[list | None] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class HallucinationEmbedding(Base):
    """幻觉检测嵌入向量落库（默认不落库；store_embeddings=True 时写入，D-13）。"""

    __tablename__ = "hallucination_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    embedding_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="向量记录编号（业务展示）"
    )
    task_no: Mapped[str] = mapped_column(String(32), index=True)
    step_no: Mapped[str] = mapped_column(String(32))
    item_no: Mapped[str] = mapped_column(String(32))
    prompt: Mapped[str] = mapped_column(Text)
    prompt_embedding: Mapped[list] = mapped_column(JSONB, comment="问题向量")
    ref_embedding: Mapped[list] = mapped_column(JSONB, comment="参考向量列表")
    model_name: Mapped[str] = mapped_column(String(128), comment="embedding 模型名")
    dim: Mapped[int] = mapped_column(Integer, comment="向量维度")
    score: Mapped[float] = mapped_column(Float, comment="综合相似度分数")
    severity: Mapped[str] = mapped_column(String(16), comment="幻觉等级")
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class RagasMetricRecord(Base):
    """RAGAS 三指标评测明细（D-14）。"""

    __tablename__ = "ragas_metric_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ragas_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    task_no: Mapped[str] = mapped_column(String(32), index=True)
    step_no: Mapped[str] = mapped_column(String(32))
    item_no: Mapped[str] = mapped_column(String(32))
    faithfulness: Mapped[float] = mapped_column(Float)
    answer_relevance: Mapped[float] = mapped_column(Float)
    context_recall: Mapped[float] = mapped_column(Float)
    ragas_score: Mapped[float] = mapped_column(Float)
    grade: Mapped[str] = mapped_column(
        String(16), comment="EXCELLENT/GOOD/FAIR/POOR/CRITICAL"
    )
    retrieval_recall: Mapped[float | None] = mapped_column(Float, default=None)
    retrieval_precision: Mapped[float | None] = mapped_column(Float, default=None)
    judge_rationale: Mapped[dict] = mapped_column(
        JSONB, default=dict, comment="judge 原始返回与证据"
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class ConversationTrace(Base):
    """多轮一致性测试会话轨迹（D-15）。"""

    __tablename__ = "conversation_traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    task_no: Mapped[str] = mapped_column(String(32), index=True)
    step_no: Mapped[str] = mapped_column(String(32))
    session_no: Mapped[str] = mapped_column(String(32), index=True)
    session_topic: Mapped[str] = mapped_column(String(255))
    rounds: Mapped[int] = mapped_column(Integer, default=0)
    contradiction_count: Mapped[int] = mapped_column(Integer, default=0)
    resolve_count: Mapped[int] = mapped_column(Integer, default=0)
    context_drift_score: Mapped[float] = mapped_column(Float, default=1.0)
    consistency_score: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(16), comment="PASS/CONTRADICTED/DRIFT")
    trace: Mapped[list] = mapped_column(JSONB, comment="可回放会话轨迹")
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class EthicRegulation(Base):
    """动态法规库（D-16-1）：版本化、按生效日期切换、按地区适用。"""

    __tablename__ = "ethic_regulations"
    __table_args__ = (UniqueConstraint("regulation_no", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    regulation_no: Mapped[str] = mapped_column(String(32), index=True)
    regulation_name: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(32))
    effective_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    clauses: Mapped[list] = mapped_column(JSONB, comment="[{clause_no, text}, ...]")
    region: Mapped[str] = mapped_column(String(32), default="CN")
    global_flag: Mapped[bool] = mapped_column("global", Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class EthicAuditRecord(Base):
    """伦理审计明细（D-16-2）。"""

    __tablename__ = "ethic_audit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    task_no: Mapped[str] = mapped_column(String(32), index=True)
    step_no: Mapped[str] = mapped_column(String(32))
    item_no: Mapped[str] = mapped_column(String(32))
    regulation_no: Mapped[str] = mapped_column(String(32))
    regulation_version: Mapped[str] = mapped_column(String(32))
    overall_severity: Mapped[str] = mapped_column(String(16))
    compliance_score: Mapped[float] = mapped_column(Float)
    violations: Mapped[list] = mapped_column(JSONB, default=list)
    scores_json: Mapped[dict] = mapped_column(JSONB, default=dict, comment="v1 6 维兼容")
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class GatewayRateLimit(Base):
    """网关限流规则（TENANT/MODEL 两级）。"""

    __tablename__ = "gateway_rate_limits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    limit_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    scope: Mapped[str] = mapped_column(String(16), default="MODEL")
    scope_key: Mapped[str] = mapped_column(String(128))
    qps: Mapped[float] = mapped_column(Float, default=2.0)
    concurrency: Mapped[int] = mapped_column(Integer, default=4)
    per_minute: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class LLMCacheEntry(Base):
    """LLM 响应缓存（精确 + 语义统一存储）。"""

    __tablename__ = "llm_cache_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cache_key: Mapped[str] = mapped_column(
        String(128), index=True, comment="缓存键：[命名空间:]SHA-256（产品优化3 U4）"
    )
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128), index=True)
    normalized_msgs: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="规范化消息序列（缓存校验用）"
    )
    response_text: Mapped[str] = mapped_column(Text)
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=86400)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="过期时间（UTC）"
    )
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_hit_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class LLMCacheSemantic(Base):
    """语义缓存向量（仅启用 embedding 功能时写入）。"""

    __tablename__ = "llm_cache_semantics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        Integer, index=True, comment="关联 LLMCacheEntry.id（逻辑引用）"
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    model: Mapped[str] = mapped_column(String(128), index=True)
    prompt_text: Mapped[str] = mapped_column(Text)
    embedding_json: Mapped[list] = mapped_column(
        JSONB, comment="embedding 向量（list[float]）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class ModelGatewayRecord(Base):
    """模型网关调用明细（usage 明细表，P2 成本核算核心表）。"""

    __tablename__ = "model_gateway_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="流水编号（业务展示）"
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, default=None)
    task_id: Mapped[int | None] = mapped_column(Integer, default=None)
    step_id: Mapped[int | None] = mapped_column(Integer, default=None)
    ref_no: Mapped[str | None] = mapped_column(String(64), default=None)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128), index=True)
    model_code: Mapped[str | None] = mapped_column(String(32), default=None)
    request_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    input_price_per_mtok: Mapped[float] = mapped_column(Float, default=0.0)
    output_price_per_mtok: Mapped[float] = mapped_column(Float, default=0.0)
    input_cost: Mapped[float] = mapped_column(Float, default=0.0)
    output_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="SUCCESS")
    error_code: Mapped[str | None] = mapped_column(String(32), default=None)
    error_msg: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )


class EngineCase(Base):
    """CASE_GEN 产物：AI 生成用例（ReAct Agent 落库）。"""

    __tablename__ = "engine_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    task_id: Mapped[int | None] = mapped_column(Integer, default=None)
    project_id: Mapped[int | None] = mapped_column(Integer, default=None)
    object_type: Mapped[str] = mapped_column(String(16), default="API")
    source: Mapped[str] = mapped_column(String(16), default="AI_GEN")
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    dimension: Mapped[str] = mapped_column(String(16), index=True)
    method: Mapped[str | None] = mapped_column(String(8), default=None)
    path: Mapped[str | None] = mapped_column(String(255), default=None)
    input_json: Mapped[dict | None] = mapped_column(JSONB, default=None)
    expected_json: Mapped[dict | None] = mapped_column(JSONB, default=None)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, default=None)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_info: Mapped[dict | None] = mapped_column(JSONB, default=None)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class HealRecord(Base):
    """SELF_HEAL 自愈记录。"""

    __tablename__ = "heal_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    heal_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    task_id: Mapped[int | None] = mapped_column(Integer, default=None)
    step_id: Mapped[int | None] = mapped_column(Integer, default=None)
    trace_id: Mapped[str | None] = mapped_column(String(64), default=None)
    script_code: Mapped[str] = mapped_column(String(255))
    failure_class: Mapped[str] = mapped_column(String(16), index=True)
    strategy_used: Mapped[str] = mapped_column(String(24))
    attempt_no: Mapped[int] = mapped_column(Integer, default=0)
    successful: Mapped[bool] = mapped_column(Boolean, default=False)
    fix_detail: Mapped[dict | None] = mapped_column(JSONB, default=None)
    impact: Mapped[dict | None] = mapped_column(JSONB, default=None)
    report: Mapped[dict | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class ProjectMembers(Base):
    """项目成员关系（项目内 OWNER/MEMBER/VIEWER 三角色；无外键）。"""

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", "tenant_id", name="uq_project_user_tenant"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(
        String(16), default="MEMBER", comment="OWNER/MEMBER/VIEWER"
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


# ---------------------------------------------------------------------------
# MVP 2.0 增量表（说明书第三章 H-1 ~ H-7）
# ---------------------------------------------------------------------------


class OrgInvitation(Base):
    """H-1 组织邀请（邮件邀请成员，令牌 7 天有效）。"""

    __tablename__ = "org_invitations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="TESTER")
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invited_by: Mapped[int | None] = mapped_column(Integer, default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class TestSuite(Base):
    """H-2 测试套件（套件编排 / 定时表达式预留）。"""

    __tablename__ = "test_suites"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    suite_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    exec_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="SEQUENTIAL")
    cron_expr: Mapped[str | None] = mapped_column(String(100), default=None)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class TestSuiteItem(Base):
    """H-3 套件明细（套件-任务关联，项目内防重复）。"""

    __tablename__ = "test_suite_items"
    __table_args__ = (UniqueConstraint("suite_id", "task_id", name="uq_suite_item"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    suite_id: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProjectVersion(Base):
    """H-4 项目版本（语义化版本 / 基线唯一）。"""

    __tablename__ = "project_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    version_no: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), default=None)
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    baseline_reason: Mapped[str | None] = mapped_column(String(500), default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AssetVersion(Base):
    """P2-19 测试资产版本快照（用例/数据集/场景全量内容快照，基于 project_versions 关联）。"""

    __tablename__ = "asset_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    project_version_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="CASE/DATASET/SCENARIO")
    asset_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    asset_no: Mapped[str | None] = mapped_column(String(32), default=None)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="资产内版本序号")
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, comment="资产全量字段快照")
    change_note: Mapped[str | None] = mapped_column(String(500), default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReportShare(Base):
    """H-5 报告分享（只读链接 / 可选密码 / 有效期 / 访问统计）。"""
    __tablename__ = "report_shares"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    share_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(128), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_views: Mapped[int | None] = mapped_column(Integer, default=None)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_view_ip: Mapped[str | None] = mapped_column(String(64), default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class LoginAttempt(Base):
    """H-6 登录尝试（失败锁定审计；公开分享密码错误复用本表，username 存 share:{token}）。"""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fail_reason: Mapped[str | None] = mapped_column(String(200), default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PasswordHistory(Base):
    """H-7 密码历史（禁止复用最近 5 次密码）。"""

    __tablename__ = "password_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ============================================================================
# 优化二：真实工具链 + License 合规
# ============================================================================

class DataQualityExpectation(Base):
    """GE 期望套件资产表（CSV / DB_TABLE / EVAL_DATASET 三种源）。"""

    __tablename__ = "data_quality_expectations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    expect_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    dataset_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="CSV")
    source_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    suite_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="STRICT")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DataQualityRun(Base):
    """GE 验证结果（引擎执行后持久化）。"""

    __tablename__ = "data_quality_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    expectation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    total_checks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_checks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_checks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1)


class LicenseLedger(Base):
    """License 合规台账（SBOM）。"""

    __tablename__ = "license_ledger"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="ENGINE", index=True)
    declared_license: Mapped[str | None] = mapped_column(String(100), nullable=True)
    choosealicense_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    choosealicense_status: Mapped[str] = mapped_column(String(32), nullable=False, default="待复核", index=True)
    integration_level: Mapped[str] = mapped_column(String(8), nullable=False)
    isolation_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="LOW", index=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    tenant_id: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ===========================================================================
# P3-9 缺陷管理 / P3-11 环境管理 / P3-12 UI 录制 增量模型（2026-09-29）
# ===========================================================================

class Defect(Base):
    """缺陷管理（Bug 跟踪，无外键）。"""

    __tablename__ = "defects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    defect_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="缺陷编号（业务展示）"
    )
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    task_id: Mapped[int | None] = mapped_column(Integer, default=None)
    case_id: Mapped[int | None] = mapped_column(Integer, default=None)
    report_id: Mapped[int | None] = mapped_column(Integer, default=None)
    title: Mapped[str] = mapped_column(String(500), comment="缺陷标题")
    severity: Mapped[str] = mapped_column(String(16), default="P2", comment="P0-P4")
    status: Mapped[str] = mapped_column(
        String(16), default="NEW", comment="NEW/OPEN/FIXED/CLOSED"
    )
    actual: Mapped[str | None] = mapped_column(Text, default=None, comment="实际表现")
    expected: Mapped[str | None] = mapped_column(Text, default=None, comment="预期表现")
    evidence: Mapped[list | None] = mapped_column(
        JSONB, default=list, comment="证据链（截图/日志）"
    )
    category: Mapped[str | None] = mapped_column(
        String(32), default=None, comment="AI 归因：ENV/ASSERT/BIZ/CODE"
    )
    ai_reason: Mapped[str | None] = mapped_column(Text, default=None, comment="AI 归因说明")
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_by_name: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # AI 测试优化 25.1：缺陷专业化（Jira/禅道最小集）——仅当部署后存在对应业务列时由 DDL 提供
    priority: Mapped[str] = mapped_column(String(16), default="MEDIUM", comment="HIGH/MEDIUM/LOW")
    module: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    reproduce_steps: Mapped[list | None] = mapped_column(JSONB, default=list)
    assignee_id: Mapped[int | None] = mapped_column(Integer, default=None)
    assignee_name: Mapped[str | None] = mapped_column(String(64), default=None)
    attachments: Mapped[list | None] = mapped_column(JSONB, default=list)
    # v2.0 新增：缺陷专业化字段（BUG-007）
    fix_suggestion: Mapped[str | None] = mapped_column(Text, default=None, comment="修复建议（AI 辅助生成 + 人工补充）")
    severity_basis: Mapped[str | None] = mapped_column(String(512), default=None, comment="定级依据（关联的判定规则或证据描述）")
    requirement_id: Mapped[str | None] = mapped_column(String(64), default=None, comment="关联需求号（无需求系统时自动映射 REQ-{project_id}-{defect_no}）")
    # ES11（inti.sql section 76.3）：来源与整改目标版本
    origin_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="MANUAL", server_default=text("'MANUAL'"),
        comment="ES11：RUN_ITEM/REPORT/TRACE/SRC/MANUAL",
    )
    origin_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="ES11：来源实体 ID（按 origin_type 解释），软引用"
    )
    target_version_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="ES11：整改目标项目版本，软引用 project_versions.id"
    )


class DefectEvent(Base):
    """ES11（inti.sql section 76.4）：缺陷闭环审计事件，仅追加。

    服务层不提供 UPDATE/DELETE 路径；仓储只暴露 append。
    event_type：CREATED/ASSIGNED/REMEDIATED/RETEST_STARTED/VERIFIED/REOPENED/WAIVED/CORRECTION。
    """

    __tablename__ = "defect_events"

    __table_args__ = (
        Index("ix_defect_events_defect", "defect_id", "created_at"),
        Index("ix_defect_events_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    defect_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="软引用 defects.id")
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status_from: Mapped[str | None] = mapped_column(String(16), default=None)
    status_to: Mapped[str | None] = mapped_column(String(16), default=None)
    run_id: Mapped[int | None] = mapped_column(BigInteger, default=None, comment="复测运行，软引用 eval_runs.id")
    project_version_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    evidence: Mapped[dict | None] = mapped_column(JSONB, default=None)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_name: Mapped[str | None] = mapped_column(String(64), default=None)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class TestEnvironment(Base):
    """测试环境管理（项目可配置多套环境 base_url/auth）。"""

    __tablename__ = "test_environments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="所属项目（NULL=全局环境）"
    )
    name: Mapped[str] = mapped_column(String(128), comment="环境名称（如 开发/测试/预发）")
    base_url: Mapped[str] = mapped_column(String(500), comment="被测系统地址")
    auth: Mapped[dict | None] = mapped_column(
        JSONB, default=dict, comment="鉴权配置（Bearer/Basic/Cookie/自定义 Headers）"
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(String(500), default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class TestRecording(Base):
    """UI 录制回放（录制的 steps JSON 落库，供前端复现/重编辑）。"""

    __tablename__ = "test_recordings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rec_no: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, comment="录制编号（业务展示）"
    )
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    case_id: Mapped[int | None] = mapped_column(Integer, default=None)
    name: Mapped[str] = mapped_column(String(200), comment="录制名称")
    steps: Mapped[list] = mapped_column(JSONB, default=list, comment="录制步骤数组")
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# ORM 自动编号：task_no / case_no / step_no / rec_no 业务编号
#   设计：before_insert 事件触发，若字段为空（None / 空串），按表名+时间戳+短码自动生成。
#   幂等：已填编号的行不覆盖。并发安全：唯一索引兜底。
# ---------------------------------------------------------------------------
def _biz_no(prefix: str, length: int = 8) -> str:
    """生成业务编号：{prefix}-{YYYYMMDDHHMMSS}-{length位随机码}"""
    import secrets
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand = secrets.token_hex(length // 2).upper()[:length]
    return f"{prefix}-{ts}-{rand}"


@event.listens_for(TestTask, "before_insert")
def _auto_test_task_no(mapper, connection, target):
    if not target.task_no:
        target.task_no = _biz_no("TSK")


@event.listens_for(TestCase, "before_insert")
def _auto_test_case_no(mapper, connection, target):
    if not target.case_no:
        target.case_no = _biz_no("TC")


@event.listens_for(TaskStep, "before_insert")
def _auto_task_step_no(mapper, connection, target):
    if not target.step_no:
        target.step_no = _biz_no("STP")


@event.listens_for(TestRecording, "before_insert")
def _auto_test_rec_no(mapper, connection, target):
    if not target.rec_no:
        target.rec_no = _biz_no("REC")


# ---------------------------------------------------------------------------
# AI 自测化测试：自动探测任务（《AI自测化测试详细开发.md》v2.0 §3.1）
# ---------------------------------------------------------------------------
class DiscoverJob(Base):
    """AI 自动探测任务（URL+账密 → 登录 → 发现接口 → 生成用例/数据集/场景 → 预览 → 确认入库）。"""

    __tablename__ = "discover_jobs"

    # DS-10：与 database/inti.sql §15 对齐（部分索引 postgresql_where，仅索引未删除行；started_at DESC）
    __table_args__ = (
        Index("idx_dj_project", "project_id", postgresql_where=text("deleted_at IS NULL")),
        Index("idx_dj_status", "status", postgresql_where=text("deleted_at IS NULL")),
        Index("idx_dj_tenant", "tenant_id", postgresql_where=text("deleted_at IS NULL")),
        Index("idx_dj_time", text("started_at DESC"), postgresql_where=text("deleted_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_no: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, comment="任务编号（gen_no('DJ')）"
    )
    project_id: Mapped[int] = mapped_column(Integer, comment="所属项目（逻辑引用）")
    url: Mapped[str] = mapped_column(String(500), comment="目标系统地址（白名单内）")
    auth_type: Mapped[str] = mapped_column(
        String(16), default="USERPASS", comment="USERPASS/COOKIE/TOKEN"
    )
    discover_mode: Mapped[str] = mapped_column(
        String(16), default="DISCOVER", comment="READONLY/DISCOVER/MUTATE"
    )
    target_snapshot: Mapped[dict] = mapped_column(
        JSONB, default=dict, comment="目标快照：discovered_routes/modules/login_method"
    )
    llm_model: Mapped[str] = mapped_column(String(64), default="MG-DEEPSEEK-DEFAULT")
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0, comment="0-100")
    total_routes: Mapped[int] = mapped_column(Integer, default=0)
    total_modules: Mapped[int] = mapped_column(Integer, default=0)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    dataset_count: Mapped[int] = mapped_column(Integer, default=0)
    scenario_count: Mapped[int] = mapped_column(Integer, default=0)
    preview_payload: Mapped[dict] = mapped_column(
        JSONB, default=dict, comment="PREVIEW 态完整生成数据（含 confidence/confidence_map）"
    )
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    created_by: Mapped[int | None] = mapped_column(Integer, default=None)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class DiscoverJobRoute(Base):
    """探测路由明细（每条被探接口一行；预览与 VALIDATE 的依据）。"""

    __tablename__ = "discover_job_routes"

    # DS-10：与 inti.sql §15 对齐（job+method+path 唯一；job_id/module 索引）
    __table_args__ = (
        UniqueConstraint("job_id", "method", "path", name="uq_djr_job_method_path"),
        Index("idx_djr_job", "job_id"),
        Index("idx_djr_mod", "module"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, comment="所属任务（逻辑引用）")
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(500))
    full_url: Mapped[str | None] = mapped_column(String(1000), default=None)
    module: Mapped[str | None] = mapped_column(String(128), default=None)
    summary: Mapped[str | None] = mapped_column(String(500), default=None)
    swagger_tag: Mapped[str | None] = mapped_column(String(128), default=None)
    from_swagger: Mapped[bool] = mapped_column(Boolean, default=False)
    response_sample: Mapped[dict] = mapped_column(JSONB, default=dict)
    action_code: Mapped[str | None] = mapped_column(
        String(16), default=None, comment="READ/CREATE/UPDATE/DELETE/OTHER"
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


# ---------------------------------------------------------------------------
# 产品详细功能规划 P0/P1：越狱样本库 / PII 规则库 / 中文法条库 / 行业模板
# ---------------------------------------------------------------------------
class JailbreakSample(Base):
    """越狱样本库（P0：JAILBREAK 引擎数据源，无外键、租户隔离）。"""

    __tablename__ = "jailbreak_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str] = mapped_column(
        String(64), index=True, comment="ROLEPLAY/ENCODING/CONTEXT_POISON"
    )
    attack_vector: Mapped[str] = mapped_column(String(128), comment="攻击向量描述（中文）")
    prompt_template: Mapped[str] = mapped_column(Text, comment="越狱提示模板")
    severity: Mapped[str] = mapped_column(String(16), default="HIGH")
    source: Mapped[str | None] = mapped_column(String(64), default=None, comment="来源标注")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class PIIRule(Base):
    """PII 识别规则库（P0：PII_LEAK 引擎数据源，正则+脱敏）。"""

    __tablename__ = "pii_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int] = mapped_column(Integer, default=1)
    pii_type: Mapped[str] = mapped_column(
        String(64), index=True, comment="ID_CARD/PHONE/BANK_CARD/EMAIL/API_KEY 等"
    )
    rule_name: Mapped[str] = mapped_column(String(128), comment="规则名称（中文）")
    regex_pattern: Mapped[str] = mapped_column(Text, comment="正则表达式")
    description: Mapped[str | None] = mapped_column(Text, default=None)
    severity: Mapped[str] = mapped_column(String(16), default="HIGH")
    context_keywords: Mapped[list | None] = mapped_column(
        JSONB, default=None,
        comment="上下文佐证词（命中位置前后 30 字符窗口内出现才计入，对齐 Presidio score boosting；空=不校验）",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class ComplianceRegulation(Base):
    """中文法规条文库（P1：合规风险库，报告法条映射数据源）。"""

    __tablename__ = "compliance_regulations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int] = mapped_column(Integer, default=1)
    regulation_name: Mapped[str] = mapped_column(String(256), comment="法规名称")
    article_number: Mapped[str] = mapped_column(String(64), comment="条文编号")
    article_content: Mapped[str] = mapped_column(Text, comment="条文内容")
    violation_consequence: Mapped[str | None] = mapped_column(
        Text, default=None, comment="违反后果"
    )
    effective_date: Mapped[date | None] = mapped_column(Date, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class RiskToRegulationMapping(Base):
    """风险项 → 法规映射（P1：regulation_id 逻辑引用，无外键）。"""

    __tablename__ = "risk_to_regulation_mapping"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int] = mapped_column(Integer, default=1)
    risk_category: Mapped[str] = mapped_column(
        String(64), index=True, comment="POLITICAL/VIOLENCE/PORNOGRAPHY/PRIVACY 等"
    )
    regulation_id: Mapped[int] = mapped_column(Integer, comment="关联法规 ID（逻辑引用）")
    mapping_description: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class IndustryTemplate(Base):
    """行业评估模板（P1：5 行业引擎组合+阈值，一键套用）。"""

    __tablename__ = "industry_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int] = mapped_column(Integer, default=1)
    industry_name: Mapped[str] = mapped_column(
        String(64), index=True, comment="GOVERNMENT/FINANCE/MEDICAL/EDUCATION/MEDIA"
    )
    template_name: Mapped[str] = mapped_column(String(128), comment="模板名称（中文）")
    engine_config: Mapped[dict] = mapped_column(
        JSONB, comment='{"engines": [...], "thresholds": {...}}'
    )
    sample_package_id: Mapped[int | None] = mapped_column(Integer, default=None)
    report_template_id: Mapped[int | None] = mapped_column(Integer, default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


# ---------------------------------------------------------------------------
# SRC 源代码安全审计（SAST + SCA）：扫描任务 / 规则库 / 发现项 / 组件 / 组件漏洞
# 无外键（逻辑引用）、租户隔离、软删、业务编号，对齐《SRC源代码安全审计功能设计方案》
# ---------------------------------------------------------------------------
class SrcScanTask(Base):
    """SRC 扫描任务（代码接入 + 扫描状态机）。"""

    __tablename__ = "src_scan_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_no: Mapped[str] = mapped_column(
        String(64), unique=True, comment="业务编号 SRC-YYYYMMDD..."
    )
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int] = mapped_column(Integer, default=1)
    project_id: Mapped[int | None] = mapped_column(
        Integer, default=None, comment="关联项目 ID（逻辑引用）"
    )
    name: Mapped[str] = mapped_column(String(256), comment="任务名称（中文）")
    source_type: Mapped[str] = mapped_column(
        String(16), default="upload", comment="upload/git"
    )
    source_url: Mapped[str | None] = mapped_column(
        String(1000), default=None, comment="ZIP 存储名或 git 地址"
    )
    workdir: Mapped[str | None] = mapped_column(
        String(1000), default=None, comment="解压后源码根目录"
    )
    commit_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    branch: Mapped[str | None] = mapped_column(String(128), default=None)
    language_stats: Mapped[dict] = mapped_column(
        JSONB, default=dict, comment='{"python": 文件数, ...}'
    )
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    total_lines: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(16), default="PENDING", index=True,
        comment="PENDING/SCANNING/COMPLETED/FAILED",
    )
    scan_backend: Mapped[str] = mapped_column(
        String(16), nullable=False, default="builtin", server_default=text("'builtin'"),
        comment="ES9：builtin=内置规则 / semgrep=外接编排；报告页据此标注能力层级",
    )
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    summary: Mapped[dict] = mapped_column(
        JSONB, default=dict,
        comment='{"total":N,"critical":N,"high":N,"medium":N,"low":N,"sca":N}',
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class SrcRule(Base):
    """SRC 检测规则库（内置 + 自定义；正则/文本模式，Phase 1）。"""

    __tablename__ = "src_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_no: Mapped[str] = mapped_column(String(64), unique=True, comment="业务编号")
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int] = mapped_column(Integer, default=1)
    rule_id: Mapped[str] = mapped_column(
        String(128), unique=True, comment="规则标识，如 CWE-89-SQLI-PY"
    )
    name: Mapped[str] = mapped_column(String(256), comment="规则名称（中文）")
    description: Mapped[str | None] = mapped_column(Text, default=None)
    severity: Mapped[str] = mapped_column(
        String(16), default="HIGH", comment="CRITICAL/HIGH/MEDIUM/LOW"
    )
    language: Mapped[str] = mapped_column(
        String(32), default="*", comment="python/java/javascript/go/*（全语言）"
    )
    category: Mapped[str] = mapped_column(
        String(64), default="INJECTION", comment="INJECTION/SECRET/CRYPTO/..."
    )
    rule_type: Mapped[str] = mapped_column(
        String(16), default="REGEX", comment="REGEX/TAIN"
    )
    pattern: Mapped[str] = mapped_column(Text, comment="正则表达式（TAIN 规则为污点源模式）")
    cwe_id: Mapped[str | None] = mapped_column(String(32), default=None)
    owasp_category: Mapped[str | None] = mapped_column(String(64), default=None)
    remediation: Mapped[str | None] = mapped_column(Text, default=None, comment="修复建议（中文）")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[str] = mapped_column(String(16), default="1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class SrcFinding(Base):
    """SRC 扫描发现项（SAST 命中结果，scan_task_id/rule 逻辑引用）。"""

    __tablename__ = "src_findings"

    __table_args__ = (
        Index("idx_src_findings_task", "scan_task_id"),
        Index("idx_src_findings_sev", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_no: Mapped[str] = mapped_column(String(64), unique=True, comment="业务编号")
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int] = mapped_column(Integer, default=1)
    scan_task_id: Mapped[int] = mapped_column(Integer, comment="扫描任务 ID（逻辑引用）")
    rule_ref: Mapped[str] = mapped_column(String(128), comment="命中规则 rule_id（逻辑引用）")
    rule_name: Mapped[str] = mapped_column(String(256), default="")
    file_path: Mapped[str] = mapped_column(String(1000), comment="相对源码根路径")
    line_start: Mapped[int] = mapped_column(Integer, default=1)
    line_end: Mapped[int] = mapped_column(Integer, default=1)
    severity: Mapped[str] = mapped_column(String(16), default="HIGH", index=True)
    confidence: Mapped[str] = mapped_column(
        String(16), default="MEDIUM", comment="HIGH/MEDIUM/LOW"
    )
    message: Mapped[str] = mapped_column(Text, comment="问题描述（中文）")
    code_snippet: Mapped[str | None] = mapped_column(Text, default=None)
    remediation: Mapped[str | None] = mapped_column(Text, default=None)
    cwe_id: Mapped[str | None] = mapped_column(String(32), default=None)
    owasp_category: Mapped[str | None] = mapped_column(String(64), default=None)
    status: Mapped[str] = mapped_column(
        String(16), default="OPEN", index=True,
        comment="OPEN/FIXED/FALSE_POSITIVE/SUPPRESSED",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class ScaComponent(Base):
    """SCA 依赖组件清单（SBOM，来源：requirements.txt / package.json）。"""

    __tablename__ = "sca_components"

    __table_args__ = (
        Index("idx_sca_comp_task", "scan_task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_no: Mapped[str] = mapped_column(String(64), unique=True, comment="业务编号")
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int] = mapped_column(Integer, default=1)
    scan_task_id: Mapped[int] = mapped_column(Integer, comment="扫描任务 ID（逻辑引用）")
    name: Mapped[str] = mapped_column(String(256), index=True)
    version: Mapped[str | None] = mapped_column(String(64), default=None)
    ecosystem: Mapped[str] = mapped_column(
        String(32), default="pypi", comment="pypi/npm"
    )
    license_name: Mapped[str | None] = mapped_column(String(128), default=None)
    license_risk: Mapped[str | None] = mapped_column(
        String(16), default=None, comment="NONE/LOW/HIGH（GPL 等强 copyleft 为 HIGH）"
    )
    direct: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否直接依赖")
    dependency_path: Mapped[str | None] = mapped_column(
        String(1000), default=None, comment="依赖路径，如 requirements.txt"
    )
    cve_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class ScaVulnerability(Base):
    """SCA 组件漏洞（CVE 本地库匹配结果）。"""

    __tablename__ = "sca_vulnerabilities"

    __table_args__ = (
        Index("idx_sca_vuln_task", "scan_task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vuln_no: Mapped[str] = mapped_column(String(64), unique=True, comment="业务编号")
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_by: Mapped[int] = mapped_column(Integer, default=1)
    scan_task_id: Mapped[int] = mapped_column(Integer, comment="扫描任务 ID（逻辑引用）")
    component_id: Mapped[int] = mapped_column(Integer, comment="组件 ID（逻辑引用）")
    component_name: Mapped[str] = mapped_column(String(256), default="")
    component_version: Mapped[str | None] = mapped_column(String(64), default=None)
    cve_id: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="HIGH")
    cvss_score: Mapped[float | None] = mapped_column(Float, default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None, comment="中文描述")
    fixed_version: Mapped[str | None] = mapped_column(
        String(64), default=None, comment="修复版本（>=）"
    )
    references: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class CommunityUsageDaily(Base):
    """社区版按日用量计数器（版本隔离改造新增；仅 EDITION=community 读写）。

    字段与 database/inti.sql section 40 的 DDL 逐一对齐。
    计数写入走 INSERT ... ON CONFLICT (tenant_id,user_id,kind,usage_date)
    DO UPDATE SET cnt=cnt+1。
    """

    __tablename__ = "community_usage_daily"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "kind", "usage_date",
            name="uq_cud_tenant_user_kind_date",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="计数类型，如 case_gen"
    )
    usage_date: Mapped[date] = mapped_column(Date, nullable=False, comment="服务器本地日")
    cnt: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="当日已用量")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class RedteamSample(Base):
    """ES8 M9：生成式红队样本池（变异载荷，DRAFT 不参与执行，APPROVED 后方可注入评测）。

    字段与 database/inti.sql section 53.1 的 DDL 逐一对齐。
    mutation_of 逻辑引用 jailbreak_samples.id（内置原生种子为空）。
    """

    __tablename__ = "redteam_samples"

    __table_args__ = (
        Index("ix_redteam_samples_tenant_status", "tenant_id", "status"),
        Index("ix_redteam_samples_framework", "framework_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="归属租户"
    )
    framework_code: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=text("''"),
        comment="映射条目 code（如 LLM01:2025 / AML.T0051），可空串",
    )
    payload: Mapped[str] = mapped_column(
        Text, nullable=False, comment="变异后的攻击载荷文本"
    )
    mutation_of: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="源种子样本 id（逻辑引用，原生/手工为空）"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="DRAFT", server_default=text("'DRAFT'"),
        comment="状态机：DRAFT→APPROVED|REJECTED；REJECTED 为终态",
    )
    hit_stats: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default=text("'{}'"),
        comment='命中统计 JSON：{"attempts":N,"bypassed":N}，报告/护栏建议数据源',
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="创建人 user_id"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="审批时刻（APPROVED/REJECTED 时写入）"
    )


class FrameworkItem(Base):
    """ES8 M9：国际安全框架条目（OWASP LLM Top10 2025 + MITRE ATLAS）。

    字段与 database/inti.sql section 53.2 的 DDL 逐一对齐；种子数据由 SQL 内置。
    报告「国际框架覆盖」节与前端框架下拉的数据字典。
    """

    __tablename__ = "framework_items"

    __table_args__ = (
        UniqueConstraint("code", name="uk_framework_items_code"),
        Index("ix_framework_items_framework", "framework"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    framework: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="框架：owasp_llm=OWASP LLM Top10 2025 / atlas=MITRE ATLAS",
    )
    code: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="全局唯一编码：LLM01:2025 / AML.T0051 等"
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    item_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="risk", server_default=text("'risk'"),
        comment="条目类型：risk=OWASP 风险 / technique=ATLAS 技术 / tactic=ATLAS 战术",
    )
    tactic: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=text("''")
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False,
        # 与 inti.sql 53.2 的 DEFAULT now() 对齐（CURRENT_TIMESTAMP 为 PG/sqlite 通用写法）
        server_default=text("CURRENT_TIMESTAMP"),
    )


class NotifyChannelConfig(Base):
    """ES8 M3：通知渠道（租户级；config 为 encrypt_secret 加密后的 JSON 串）。

    字段与 database/inti.sql section 47.1 的 DDL 逐一对齐。
    """

    __tablename__ = "notify_channels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="email|dingtalk|feishu|wecom|slack|webhook",
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    config: Mapped[str] = mapped_column(
        Text, nullable=False, comment="AES-GCM 加密的 JSON 配置（decrypt_secret 解密）"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_probe_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, comment="最近一次发送测试时间"
    )
    last_probe_ok: Mapped[bool | None] = mapped_column(
        Boolean, default=None, comment="TRUE=可用 / FALSE=失败 / NULL=未探测"
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class DefectSyncTarget(Base):
    """ES8 M11：缺陷工单同步目标（GitHub/Gitee/Jira 租户级配置）。

    字段与 database/inti.sql section 55.1 的 DDL 逐一对齐。
    config 为 JSONB：github/gitee={repo, token_enc}，
    jira={base_url, project_key, personal_token_enc, issue_type}；
    其中 *_enc 为 app/security.py encrypt_secret 密文，出参仅回 ****+后4位。
    """

    __tablename__ = "defect_sync_targets"

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="defect_sync_targets_tenant_id_name_key"),
        Index("idx_dst_tenant_enabled", "tenant_id", "enabled"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="github|gitee|jira"
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'"),
        comment="连接参数（token 以 encrypt_secret 密文内嵌 token_enc）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE")
    )
    last_probe_ok: Mapped[bool | None] = mapped_column(
        Boolean, default=None, comment="最近一次连通探测结果（NULL=未探测过）"
    )
    last_probe_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, onupdate=_now
    )


class DefectSyncLink(Base):
    """ES8 M11：缺陷 ↔ 外部工单映射（幂等推送唯一键载体）。

    字段与 database/inti.sql section 55.2 的 DDL 逐一对齐。
    双唯一索引：ix_dsl_target_external（webhook 回写按外部单号定位）、
    ix_dsl_defect_target（同一缺陷同一目标只推一次）。
    """

    __tablename__ = "defect_sync_links"

    __table_args__ = (
        Index("ix_dsl_target_external", "target_id", "external_id", unique=True),
        Index("ix_dsl_defect_target", "defect_id", "target_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    defect_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    external_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="GH/Gitee issue number 或 Jira issue key"
    )
    external_url: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(
        String(8), nullable=False, default="out", server_default=text("'out'"),
        comment="out=本系统推送建立",
    )
    sync_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="SYNCED", server_default=text("'SYNCED'"),
        comment="SYNCED|EXTERNAL_CLOSED|LOCAL_CLOSED|FAILED",
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    fail_reason: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, onupdate=_now
    )


class NotifyRule(Base):
    """ES8 M3：通知规则（事件订阅 + 严重级门槛 + 范围过滤）。

    字段与 database/inti.sql section 47.2 的 DDL 逐一对齐。
    scope / channel_ids 为 JSON 字符串（TEXT 列），空 = 全部。
    """

    __tablename__ = "notify_rules"

    __table_args__ = (
        Index("ix_notify_rules_tenant_event", "tenant_id", "event"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event: Mapped[str] = mapped_column(
        String(48), nullable=False,
        comment="task.completed|task.failed|monitor.alert|subscription.renewing|defect.created|review.assigned",
    )
    scope: Mapped[str | None] = mapped_column(
        Text, default=None, comment="JSON: {project_id?, suite_id?}；空=全部"
    )
    channel_ids: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'[]'"),
        comment="JSON 数组：notify_channels.id 列表",
    )
    template_key: Mapped[str | None] = mapped_column(
        String(48), default=None, comment="模板预留（本期未启用）"
    )
    min_severity: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'LOW'"),
        comment="LOW|MEDIUM|HIGH|CRITICAL",
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class NotifyDelivery(Base):
    """ES8 M3：通知投递留痕（每次渠道发送一条记录）。

    字段与 database/inti.sql section 47.3 的 DDL 逐一对齐。
    """

    __tablename__ = "notify_deliveries"

    __table_args__ = (
        Index("ix_notify_deliveries_tenant_created", "tenant_id", "created_at"),
        Index("ix_notify_deliveries_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="notify_rules.id；渠道直发测试时为 NULL"
    )
    event: Mapped[str] = mapped_column(String(48), nullable=False)
    channel_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    payload: Mapped[str | None] = mapped_column(Text, default=None, comment="发送内容摘要（JSON）")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="SUCCESS|FAILED|DEGRADED|SKIPPED"
    )
    error: Mapped[str | None] = mapped_column(Text, default=None, comment="失败原因")
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"),
        comment="实际尝试次数（含重试 1 次）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class Monitor(Base):
    """ES8 M4：定时监控（套件 + cron + 阈值告警，挂 scheduler tick）。

    字段与 database/inti.sql section 48.1 的 DDL 逐一对齐。
    alert_conditions / baseline_metrics 为 JSON 字符串（TEXT 列）。
    """

    __tablename__ = "monitors"

    __table_args__ = (
        Index("ix_monitors_due", "enabled", "next_fire_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0"),
        comment="冗余组织位（无组织体系时 0）",
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    suite_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="test_suites.id（逻辑引用）"
    )
    cron: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="5 段表达式（utils/cron.py 解析）"
    )
    baseline_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'LAST_RUN'"),
        comment="LAST_RUN=自存上次 run 快照 / FIXED=固定基线",
    )
    baseline_metrics: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'{}'"),
        comment='JSON：上次 run 指标快照 {"pass_rate":0.9,...}',
    )
    alert_conditions: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'[]'"),
        comment='JSON 数组：[{"metric","op":"lt|gt","threshold"}]',
    )
    notify_rule_event: Mapped[str] = mapped_column(
        String(48), nullable=False, server_default=text("'monitor.alert'")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="FALSE 时 tick 不再调度（已 FIRING 告警保留）",
    )
    last_run_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="最近触发批次代表任务 id（test_tasks.id）"
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, comment="tick 抢占时间戳（条件 UPDATE 防并发）"
    )
    next_fire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, comment="cron 求得的下次触发时刻"
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class MonitorAlert(Base):
    """ES8 M4：监控告警时间线（FIRING|RESOLVED，同 metric 收敛不重复建）。

    字段与 database/inti.sql section 48.2 的 DDL 逐一对齐。
    """

    __tablename__ = "monitor_alerts"

    __table_args__ = (
        Index("ix_monitor_alerts_monitor", "monitor_id", "state"),
        Index("ix_monitor_alerts_fired", "monitor_id", "fired_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="monitors.id（逻辑引用）"
    )
    run_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="触发告警的批次代表任务 id"
    )
    metric: Mapped[str] = mapped_column(String(48), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False, comment="实际指标值")
    threshold: Mapped[float] = mapped_column(Float, nullable=False, comment="条件阈值")
    op: Mapped[str] = mapped_column(String(4), nullable=False, comment="lt|gt")
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="FIRING=告警中 / RESOLVED=已恢复"
    )
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, comment="指标回阈值内的恢复时间"
    )
    notified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE"),
        comment="是否已 emit monitor.alert 事件",
    )


class ReviewItem(Base):
    """ES8 M6：人工复核队列（judge 校准数据源）。

    字段与 database/inti.sql section 50.1 的 DDL 逐一对齐。
    幂等入队靠 PG 部分唯一索引 ix_review_items_src（OPEN 态下
    (source, source_ref) 唯一）；DONE 不回写 run 表——人工结论
    权威落点就是 human_verdict 本身，报告展示时按 source_ref 关联。
    """

    __tablename__ = "review_items"

    __table_args__ = (
        Index(
            "ix_review_items_src", "source", "source_ref",
            unique=True, postgresql_where=text("status='OPEN'"),
        ),
        Index("ix_review_items_tenant_status", "tenant_id", "status"),
        Index("ix_review_items_assignee", "assignee_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0"),
        comment="organizations.id（逻辑引用，对齐 M4 惯例）",
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="run_item|trace|defect"
    )
    source_ref: Mapped[str] = mapped_column(
        Text, nullable=False, comment='JSON：{"run_id":..,"item_index":..}'
    )
    context: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'{}'"),
        comment="样本快照 JSON（prompt/score/verdict 等），复制而非引用",
    )
    auto_verdict: Mapped[str | None] = mapped_column(String(24), default=None)
    auto_confidence: Mapped[float | None] = mapped_column(
        Float, default=None, comment="机判置信度；无原生字段时为 score 贴近阈值的代理值"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="OPEN", server_default=text("'OPEN'"),
        comment="OPEN|ASSIGNED|DONE|DISCARDED",
    )
    assignee_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="复核员 users.id"
    )
    human_verdict: Mapped[str | None] = mapped_column(
        String(24), default=None, comment="人工结论（校准混淆矩阵人工列）"
    )
    human_note: Mapped[str | None] = mapped_column(Text, default=None)
    judge_prompt_hash: Mapped[str | None] = mapped_column(
        String(40), default=None, comment="ES9：裁判 prompt 模板 sha256 前 40 位（与 eval_run_items 对齐）"
    )
    judge_model: Mapped[str | None] = mapped_column(
        String(96), default=None, comment="ES9：裁判模型标识"
    )
    run_item_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="ES9：软引用 eval_run_items.id，复核与条目级判定互通"
    )
    priority: Mapped[str | None] = mapped_column(
        String(4), default=None,
        comment="ES9：入队定级 P0=低一致 / P1=纯裁判判负 / P2=needs_review 全量",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class Trace(Base):
    """ES8 M8：在线对话留痕（网关旁路 + ingestion API）。

    字段与 database/inti.sql section 52.1 的 DDL 逐一对齐。
    request/response 截断存（单条上限 8KB，见 trace_recording.truncate_text）；
    scores 为各指标 0-1 质量分 JSON（高=安全），overall=min(values)。
    """

    __tablename__ = "traces"

    __table_args__ = (
        Index("ix_traces_tenant_eval", "tenant_id", "eval_status"),
        Index("ix_traces_tenant_occurred", "tenant_id", "occurred_at", postgresql_ops={"occurred_at": "DESC"}),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="organizations.id（逻辑引用，对齐 M4 惯例）"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="gateway=网关旁路 | ingest_api=推送接口"
    )
    external_ref: Mapped[str | None] = mapped_column(
        String(64), default=None, comment="网关请求 id（可空）"
    )
    request: Mapped[str] = mapped_column(
        Text, nullable=False, comment="请求文本，截断存（≤8KB，超限=前4KB+标记+后1KB）"
    )
    response: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(64), default=None)
    tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    status: Mapped[str | None] = mapped_column(
        String(16), default=None, comment="OK|ERROR（对齐网关返回语义）"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="对话发生时间"
    )
    eval_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default=text("'PENDING'"),
        comment="PENDING|SCORED|SKIPPED|FAILED",
    )
    scores: Mapped[str] = mapped_column(
        Text, default="{}", server_default=text("'{}'"),
        comment="评分 JSON：各指标 0-1 质量分（高=安全）",
    )
    reviewed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE"),
        comment="低分回流 review_items 后置 TRUE，防重复入队",
    )
    # ES11（inti.sql section 76.5）：归属与处理轨迹
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="ES11：归属项目，软引用 projects.id"
    )
    target_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="ES11：被测系统，软引用 targets 表"
    )
    session_id: Mapped[str | None] = mapped_column(
        String(128), default=None, comment="ES11：会话聚合标识"
    )
    trace_payload: Mapped[dict | None] = mapped_column(
        JSONB, default=None, comment="ES11：可选 spans/retrieval/tools 处理轨迹"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class TracePolicy(Base):
    """ES8 M8：在线评测采样策略（租户级一条，唯一索引 uq_trace_policies_tenant）。

    字段与 database/inti.sql section 52.2 的 DDL 逐一对齐。
    judge 模型走租户已配的模型网关（resolve_model_config 通道），零外网依赖。
    """

    __tablename__ = "trace_policies"

    __table_args__ = (
        Index("uq_trace_policies_tenant", "tenant_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE"),
        comment="采样评分总开关",
    )
    sample_rate: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.1, server_default=text("0.1"),
        comment="抽样率 0-1",
    )
    judge_metrics: Mapped[str] = mapped_column(
        Text, nullable=False,
        default='["pii_leak","injection","hallucination"]',
        server_default=text("'[\"pii_leak\",\"injection\",\"hallucination\"]'"),
        comment="启用的单轮评分指标 JSON 数组（复用现有引擎子逻辑）",
    )
    daily_cap: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2000, server_default=text("2000"),
        comment="judge 评分日上限（成本闸门，当日 SCORED+FAILED 计数）",
    )
    low_score_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.6, server_default=text("0.6"),
        comment="overall 质量分低于该值 → 回流 review_items（source=trace）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class SsoConfig(Base):
    """ES8 M10：单点登录配置（租户级；client_secret 为 encrypt_secret 密文）。

    字段与 database/inti.sql section 54 的 DDL 逐一对齐。
    kind=oidc 走标准 OIDC Auth Code + PKCE；wecom/feishu 复用同骨架、
    差异在取用户信息端点（见 services/sso_oidc.py）。
    """

    __tablename__ = "sso_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="oidc|wecom|feishu"
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    issuer: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''"),
        comment="OIDC issuer 前缀；企微/飞书留空走内置端点",
    )
    client_id: Mapped[str] = mapped_column(
        String(256), nullable=False, default="", server_default=text("''")
    )
    client_secret_enc: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''"),
        comment="AES-256-GCM 密文（app/security.py encrypt_secret），出参仅回 ****+后4位",
    )
    scopes: Mapped[str] = mapped_column(
        String(512), nullable=False,
        default="openid profile email",
        server_default=text("'openid profile email'"),
        comment="scope 串（空格分隔）",
    )
    redirect_uri: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''"),
        comment="回调地址（精确匹配白名单），留空按 API 基址自动构造",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE")
    )
    auto_provision: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE"),
        comment="首次登录无匹配用户时自动建号入租户",
    )
    default_role: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'MEMBER'"),
        comment="auto_provision 建号绑定的角色编码",
    )
    org_binding_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'none'"),
        comment="组织绑定模式：none|name（按 claim 部门名解析组织）",
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class QuestionBank(Base):
    """ES9-P-09：题库一等实体。

    字段与 database/inti.sql section 66 的 DDL 逐一对齐。
    社区/专业/企业版按 is_builtin+限额差异化放开（口径见设计方案 §1.4）。
    """

    __tablename__ = "question_bank"

    __table_args__ = (
        Index(
            "uq_question_bank_code", "tenant_id", "code",
            unique=True, postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="题库编号（业务展示）")
    description: Mapped[str | None] = mapped_column(Text, default=None)
    category_system: Mapped[str] = mapped_column(
        String(32), nullable=False, default="TC260", server_default=text("'TC260'"),
        comment="分类体系：TC260 / OWASP_LLM / CUSTOM",
    )
    bank_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="1.0.0", server_default=text("'1.0.0'")
    )
    question_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="冗余计数，导入/编辑后重算（同 eval_sets 口径）",
    )
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE"),
        comment="内置题库随 inti.sql 种子发布（社区版只放开应拒答集子集）",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default=text("'active'"),
        comment="active / archived",
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class Question(Base):
    """ES9-P-09：题目（题库内单条样本）。

    字段与 database/inti.sql section 66 的 DDL 逐一对齐。
    bank_id 软引用 question_bank.id（C1 无物理外键）；
    查重唯一键 uq_question_dedup 为 (bank_id, category, md5(btrim(text))) 部分索引，
    应用层查重同口径（设计方案 §4.1.2）。
    """

    __tablename__ = "question"

    __table_args__ = (
        Index(
            "uq_question_bank_seq", "bank_id", "seq",
            unique=True, postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_question_split", "bank_id", "split", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_question_cat", "category", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_question_tenant", "tenant_id", postgresql_where=text("deleted_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bank_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="软引用 question_bank.id（C1 无物理外键）"
    )
    seq: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="题库内序号，导入保序",
    )
    category: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="国标风险分类编码（framework_items.code 对齐）"
    )
    sub_category: Mapped[str | None] = mapped_column(String(64), default=None)
    attack_vector: Mapped[str | None] = mapped_column(
        String(48), default=None,
        comment="direct / jailbreak_role / prompt_injection / induction_leak / pii / none",
    )
    split: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ANSWER", server_default=text("'ANSWER'"),
        comment="三集：REFUSE(应拒答) / ANSWER(应回答) / ATTACK(攻击集)",
    )
    expected_behavior: Mapped[str] = mapped_column(
        String(16), nullable=False, default="REFUSE", server_default=text("'REFUSE'"),
        comment="REFUSE / ANSWER / SAFE_REFUSE",
    )
    expected_answer: Mapped[str | None] = mapped_column(
        Text, default=None, comment="ANSWER 集参考答案（供事实性核对）"
    )
    language: Mapped[str] = mapped_column(
        String(16), nullable=False, default="zh-CN", server_default=text("'zh-CN'")
    )
    source: Mapped[str] = mapped_column(
        String(48), nullable=False, default="manual", server_default=text("'manual'"),
        comment="manual / csv_import / jsonl_import / ai_generated / vendor_licensed",
    )
    sensitivity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="internal", server_default=text("'internal'"),
        comment="public / internal / confidential（confidential 禁止进 saas 形态，见设计方案 §1.4）",
    )
    tags: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="出处、审核人、批次等",
    )
    # 注意：本列必须声明在类体末尾——类属性名 `text` 会遮蔽 sqlalchemy 的 text()，
    # 若置于中间，其后任何 server_default=text(...) 都会取到 MappedColumn 而报错。
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class QuestionImportJob(Base):
    """ES9-P-09：题目批量导入作业。

    字段与 database/inti.sql section 66 的 DDL 逐一对齐。
    CSV 入口强制经 csv_guard 反向校验 + 行数/字段校验（设计方案 §4.1.2）。
    """

    __tablename__ = "question_import_job"

    __table_args__ = (
        Index("ix_qimport_bank", "bank_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bank_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    format: Mapped[str] = mapped_column(
        String(8), nullable=False, default="csv", server_default=text("'csv'"),
        comment="csv / jsonl",
    )
    file_path: Mapped[str] = mapped_column(
        Text, nullable=False, comment="落 EVIDENCE_DIR/import/ 下，防原始上传面暴露"
    )
    total_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    inserted: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    duplicated: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    rejected: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    errors: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="[{row, code, message}] 最多留 200 条",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default=text("'pending'"),
        comment="pending / running / succeeded / failed",
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class EvalRunItem(Base):
    """ES9-P-09/P-10：执行明细 sidecar（题目级判定与复核的单一事实源）。

    字段与 database/inti.sql section 67 的 DDL 逐一对齐。
    run_id/question_id/bank_id 均为软引用（C1 无物理外键）；
    双轨判定 rule_verdict/judge_verdict → final_verdict（规则优先）。
    """

    __tablename__ = "eval_run_items"

    __table_args__ = (
        Index("ix_items_run", "run_id", "seq"),
        Index(
            "ix_items_review", "review_status",
            postgresql_where=text("review_status <> 'none'"),
        ),
        Index("ix_items_stats", "run_id", "split", "final_verdict"),
        # 优化12 §11.2 本轮唯一 DDL：按子类（category）聚合索引；
        # ix_items_stats 无法支撑子类口径（F14）。三方同步：
        # database/inti.sql section 78.3 + 运行库（T4 应用步骤）
        Index("ix_items_dim", "run_id", "category", "final_verdict"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="软引用 eval_runs.id")
    question_id: Mapped[int | None] = mapped_column(
        BigInteger, default=None, comment="软引用 question.id（非题库任务可为 NULL）"
    )
    bank_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    split: Mapped[str | None] = mapped_column(
        String(16), default=None, comment="冗余自 question，统计免 JOIN"
    )
    category: Mapped[str | None] = mapped_column(String(64), default=None)
    # 本次题库运行的声明引擎标签，不是该题实际执行引擎，不得作为覆盖矩阵维度（优化12 F2 / TC-X-008）。
    # 注：仅行尾注释，不加列 comment=——避免 DDL 对账（sync_inti_sql / TC-M6-001）漂移。
    engine_code: Mapped[str | None] = mapped_column(String(64), default=None)
    prompt: Mapped[str | None] = mapped_column(Text, default=None)
    response: Mapped[str | None] = mapped_column(
        Text, default=None, comment="被测系统原始回答（超长截断+evidence 文件引用）"
    )
    response_ref: Mapped[str | None] = mapped_column(
        Text, default=None, comment="EVIDENCE_DIR 下全文路径（>32KB 时）"
    )
    rule_verdict: Mapped[str | None] = mapped_column(
        String(16), default=None, comment="PASS / FAIL / UNKNOWN（规则轨）"
    )
    judge_verdict: Mapped[str | None] = mapped_column(
        String(16), default=None, comment="PASS / FAIL / UNKNOWN（LLM 裁判轨）"
    )
    final_verdict: Mapped[str | None] = mapped_column(
        String(16), default=None, comment="双轨合成：规则优先"
    )
    verdict_reason: Mapped[str | None] = mapped_column(Text, default=None)
    judge_model: Mapped[str | None] = mapped_column(String(96), default=None)
    judge_prompt_hash: Mapped[str | None] = mapped_column(
        String(40), default=None, comment="sha256(prompt 模板+样例) 前 40 位"
    )
    judge_seed: Mapped[int | None] = mapped_column(BigInteger, default=None)
    judge_agreement: Mapped[bool | None] = mapped_column(
        Boolean, default=None, comment="双裁判/二次采样一致性（可空=未抽中）"
    )
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default=text("'none'"),
        comment="none / pending / approved / rejected / promoted",
    )
    reviewer_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    token_usage: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="{prompt_tokens, completion_tokens}",
    )
    seq: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # ES11（inti.sql section 76.2）：标准化题级证据
    evidence_payload: Mapped[dict | None] = mapped_column(
        JSONB, default=None,
        comment="ES11：标准化证据 {schema_version,metrics,retrieval,citations,attack,tools,spans,failure_class}",
    )
    evidence_ref: Mapped[str | None] = mapped_column(
        Text, default=None, comment="ES11：超大证据文件引用（签名 URL 相对路径）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class GlobalRefusalRule(Base):
    """ES9-P-10 / D-13（BUG-002）：全局拒答判定规则库（promote 回流目标）。

    字段与 database/inti.sql section 71 的 DDL 逐一对齐。
    全局共享、跨租户可见：规则属产品行为词表而非租户数据（对齐
    judge_pipeline 内置 _GLOBAL_REFUSE_KEYWORDS 的定性），故不设 tenant_id
    隔离列（项目多租户惯例：租户数据必须带 tenant_id，全局种子如
    framework_items 同为此形态）。
    keyword 为全局唯一去重键（部分唯一索引，软删释放位）；
    source=promote:{question_id} 标记复核回流来源。
    """

    __tablename__ = "global_refusal_rules"

    __table_args__ = (
        Index(
            "uq_global_refusal_keyword", "keyword",
            unique=True, postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    keyword: Mapped[str] = mapped_column(
        Text, nullable=False, comment="拒答特征关键词（全局唯一去重键）"
    )
    source: Mapped[str] = mapped_column(
        String(128), nullable=False, default="manual", server_default=text("'manual'"),
        comment="promote:{question_id}（复核回流）/ manual",
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None, comment="备注")
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class DeliveryPackage(Base):
    """ES9-P-11：交付物包台账（四件套）。

    字段与 database/inti.sql section 69 的 DDL 逐一对齐。
    """

    __tablename__ = "delivery_packages"

    __table_args__ = (
        Index(
            "uq_delivery_no", "tenant_id", "package_no",
            unique=True, postgresql_where=text("status <> 'discarded'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    package_no: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="ES9-DELIV-20261020-001"
    )
    items: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="[{kind: pdf|zip|csv|md, file_path, sha256, size}]",
    )
    standards_ver: Mapped[str | None] = mapped_column(
        String(32), default=None, comment="tc260.yaml 版本快照"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="building", server_default=text("'building'"),
        comment="building / ready / delivered",
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class FactSource(Base):
    """ES9-P-12：事实源配置（RAG/幻觉检测知识源，凭据密文化掩码返回）。

    字段与 database/inti.sql section 70 的 DDL 逐一对齐。
    auth_cipher 为 Fernet 密文，GET 出参仅回掩码（联动 ES8-SEC-01）。
    """

    __tablename__ = "fact_sources"

    __table_args__ = (
        Index(
            "uq_fact_source_name", "tenant_id", "name",
            unique=True, postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="kb_api", server_default=text("'kb_api'")
    )
    base_url: Mapped[str | None] = mapped_column(
        Text, default=None, comment="保存与连通性测试须过 SSRF 校验（拒内网/回环/元数据地址）"
    )
    auth_cipher: Mapped[str | None] = mapped_column(
        Text, default=None, comment="Fernet 加密（复用 model_configs 既有加密工具）"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class RetentionPolicy(Base):
    """ES8 M12：数据保留策略（租户级，每产物类型至多一条）。

    字段与 database/inti.sql section 56 的 DDL 逐一对齐。
    artifact_type 取值：traces|runs|recordings|attachments|audit_logs；
    其中 audit_logs 仅在枚举中出现用于"硬拒"校验——代码层
    （services/retention.py）永远拒绝该类型的策略写入与执行，
    审计日志在任何保留策略下都不允许被清理（合规底线）。
    purge_action：delete=物理删除；archive_ref=归档引用
    （有 deleted_at 的表软删标记，其余表等价于 delete）。
    """

    __tablename__ = "retention_policies"

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "artifact_type",
            name="retention_policies_tenant_id_artifact_type_key",
        ),
    )

    # 产物类型枚举（audit_logs = 豁免类型，写入即 BizError("ES8-RET-0002")）
    ARTIFACT_TRACES = "traces"
    ARTIFACT_RUNS = "runs"
    ARTIFACT_RECORDINGS = "recordings"
    ARTIFACT_ATTACHMENTS = "attachments"
    ARTIFACT_AUDIT_LOGS = "audit_logs"
    ARTIFACT_TYPES = (
        ARTIFACT_TRACES, ARTIFACT_RUNS, ARTIFACT_RECORDINGS,
        ARTIFACT_ATTACHMENTS, ARTIFACT_AUDIT_LOGS,
    )
    # 可实际执行的产物类型（audit_logs 永久豁免，不在其中）
    PURGEABLE_TYPES = (
        ARTIFACT_TRACES, ARTIFACT_RUNS, ARTIFACT_RECORDINGS, ARTIFACT_ATTACHMENTS,
    )
    # 清理动作枚举
    PURGE_DELETE = "delete"
    PURGE_ARCHIVE_REF = "archive_ref"
    PURGE_ACTIONS = (PURGE_DELETE, PURGE_ARCHIVE_REF)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="traces|runs|recordings|attachments|audit_logs（audit_logs 代码层硬拒）",
    )
    days: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="保留天数（>0），早于 now()-days 的数据过期"
    )
    purge_action: Mapped[str] = mapped_column(
        String(16), nullable=False, default="delete", server_default=text("'delete'"),
        comment="delete=物理删除 | archive_ref=归档引用（有 deleted_at 软删，其余等价删除）",
    )
    archive_ref: Mapped[str | None] = mapped_column(
        String(256), default=None, comment="archive_ref 动作的归档位置指针（可空）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
