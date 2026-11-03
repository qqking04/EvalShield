-- EvalShield
-- Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
-- Use of this source code is governed by the Business Source License 1.1
-- (the "License") stated in the LICENSE file at the root of this
-- distribution. Change Date: 3 years after release.
-- Change License: Apache License, Version 2.0.
-- SPDX-License-Identifier: BUSL-1.1
-- ============================================================
-- EvalShield 数据库初始化脚本 —— 仅表结构（DDL / COMMENT / 索引 / 视图）
-- 运行环境：PostgreSQL 16（UTF-8）
-- 幂等性：可重复执行（IF NOT EXISTS / ALTER ... IF NOT EXISTS）
-- 说明：应用运行时表结构以 backend/app/models.py（SQLAlchemy）为准；
--       本文件用于环境初始化与手工导入，保持与实库/models 字段一致。
--       种子数据与数据集（INSERT/UPDATE/DELETE/TRUNCATE）已拆分至
--       database/data.sql —— 初始化顺序：先本文件，后 data.sql。
-- 变更记录：
--   2026-10-28  section 76  ES11 闭环数据增量（eval_runs/eval_run_items/defects/defect_events/traces）
--   2026-10-31  section 77-78 GBT45654 题库类别字典与 ix_items_dim
--   2026-11-01  拆分：数据语句迁出至 data.sql；新增 section 79 结构同步补齐
-- ============================================================

BEGIN;
SET LOCAL synchronous_commit = off;


-- ============================================================
-- 1. 增量 DDL
-- ============================================================

-- ============================================================
-- 0. 基础表 DDL（原 section 19-24，2026-10-13 前移至此）
--    空库可直接执行：后续 1.x-18 节对这些表的 ALTER/INSERT 依赖
--    基础表已存在。全部 IF NOT EXISTS，幂等语义不变。
-- ============================================================
-- ============================================================================
-- 19. 项目主表 projects DDL（2026-10-04 补全 —— 之前 inti.sql 里遗漏！）
--     连带 projects.environments JSONB 字段（前端 Projects.jsx 用它存环境列表）
-- ============================================================================
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) NOT NULL,
    name VARCHAR(128) NOT NULL,
    description TEXT NULL,
    owner_id INTEGER NOT NULL,
    owner_name VARCHAR(64) NULL,
    target_system VARCHAR(512) NULL,
    visibility VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    tenant_id INTEGER NOT NULL,
    created_by INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL,
    environments JSONB NULL DEFAULT '[]'::jsonb
);


-- BUG-008：软删不应占用命名唯一性，业务唯一键一律 partial（WHERE deleted_at IS NULL）
CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_code ON projects (code) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_projects_status ON projects (status);

CREATE INDEX IF NOT EXISTS ix_projects_tenant_id ON projects (tenant_id);

CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id);

SELECT 'inti.sql section 19 projects synced' AS done;



-- ============================================================================
-- 20. 任务引擎三张表 DDL（2026-10-04 补全）
--     之前 inti.sql 里只有 task_steps 的 ALTER TABLE executor 补丁，
--     test_tasks / task_steps / task_artifacts 的 CREATE TABLE 主语句全部遗漏！
-- ============================================================================
CREATE TABLE IF NOT EXISTS test_tasks (
    id SERIAL PRIMARY KEY,
    task_no VARCHAR(32) NOT NULL,
    project_id INTEGER NOT NULL,
    project_code VARCHAR(32) NULL,
    name VARCHAR(128) NOT NULL,
    description TEXT NULL,
    task_type VARCHAR(32) NOT NULL,
    engines JSONB NOT NULL,
    config JSONB NULL,
    status VARCHAR(32) NOT NULL,
    trigger_mode VARCHAR(16) NOT NULL,
    schedule_cron VARCHAR(64) NULL,
    progress INTEGER NOT NULL,
    current_step VARCHAR(64) NULL,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    duration_ms INTEGER NULL,
    summary JSONB NULL,
    error_msg TEXT NULL,
    conclusion TEXT NULL,
    created_by INTEGER NULL,
    created_by_name VARCHAR(64) NULL,
    tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL,
    suite_id INTEGER NULL,
    task_version VARCHAR(64) NULL,
    executor VARCHAR(64) NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_test_tasks_task_no ON test_tasks (task_no);

CREATE INDEX IF NOT EXISTS ix_test_tasks_project_id ON test_tasks (project_id);

CREATE INDEX IF NOT EXISTS ix_test_tasks_status ON test_tasks (status);

CREATE INDEX IF NOT EXISTS ix_test_tasks_tenant_id ON test_tasks (tenant_id);

CREATE INDEX IF NOT EXISTS ix_test_tasks_created_at ON test_tasks (created_at);

CREATE INDEX IF NOT EXISTS idx_test_tasks_suite ON test_tasks (suite_id);

CREATE INDEX IF NOT EXISTS idx_test_tasks_ver ON test_tasks (task_version);

CREATE TABLE IF NOT EXISTS task_steps (
    id SERIAL PRIMARY KEY,
    step_no VARCHAR(32) NOT NULL,
    task_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    engine_code VARCHAR(64) NOT NULL,
    engine_name VARCHAR(128) NOT NULL,
    status VARCHAR(16) NOT NULL,
    config JSONB NULL,
    progress INTEGER NOT NULL,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    duration_ms INTEGER NULL,
    result_summary JSONB NULL,
    report_ids JSONB NULL,
    error_msg TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    executor VARCHAR(64) NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_task_steps_step_no ON task_steps (step_no);

CREATE INDEX IF NOT EXISTS ix_task_steps_task_id ON task_steps (task_id);

CREATE INDEX IF NOT EXISTS ix_task_steps_engine_code ON task_steps (engine_code);

CREATE TABLE IF NOT EXISTS task_artifacts (
    id SERIAL PRIMARY KEY,
    artifact_no VARCHAR(32) NOT NULL,
    task_id INTEGER NOT NULL,
    step_id INTEGER NULL,
    file_name VARCHAR(256) NOT NULL,
    file_path VARCHAR(512) NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type VARCHAR(128) NULL,
    art_type VARCHAR(32) NOT NULL,
    created_by INTEGER NULL,
    tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_task_artifacts_artifact_no ON task_artifacts (artifact_no);

CREATE INDEX IF NOT EXISTS ix_task_artifacts_task_id ON task_artifacts (task_id);

CREATE INDEX IF NOT EXISTS ix_task_artifacts_tenant_id ON task_artifacts (tenant_id);



-- 回补之前 section 7 里的 executor 注释（已在 CREATE TABLE 中体现，这里做幂等跳过）
COMMENT ON COLUMN task_steps.executor IS '执行该步骤的测试人员';

SELECT 'inti.sql section 20 task engine tables synced' AS done;



-- ============================================================================
-- 21. 资产中心三张核心表 DDL（2026-10-04 补全）
--     之前 inti.sql 里 test_cases / test_datasets / scenarios 的 CREATE TABLE
--     主语句完全缺失！导致新环境初始化建库后 Assets 页面直接 500。
--     连带 engine_case_libraries / engine_cases（引擎内置 + 自动生成用例）一起补。
-- ============================================================================
CREATE TABLE IF NOT EXISTS test_cases (
    id SERIAL PRIMARY KEY,
    case_no VARCHAR(32) NOT NULL,
    project_id INTEGER NOT NULL,
    dataset_id INTEGER NULL,
    title VARCHAR(256) NOT NULL,
    category VARCHAR(64) NOT NULL,
    source VARCHAR(16) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    priority VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    precondition TEXT NULL,
    steps JSONB NULL,
    expected TEXT NULL,
    request_spec JSONB NULL,
    tags JSONB NULL,
    last_run_at TIMESTAMPTZ NULL,
    last_result VARCHAR(16) NULL,
    run_count INTEGER NOT NULL DEFAULT 0,
    pass_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_duration_ms INTEGER NULL,
    owner_id INTEGER NULL,
    creator VARCHAR(64) NULL,
    tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL,
    content_schema JSONB NULL,
    preconditions JSONB NULL DEFAULT '[]'::jsonb,
    test_data JSONB NULL DEFAULT '[]'::jsonb,
    assertions JSONB NULL DEFAULT '[]'::jsonb,
    extract_vars JSONB NULL DEFAULT '{}'::jsonb,
    post_cleanup JSONB NULL DEFAULT '[]'::jsonb,
    requirement_id VARCHAR(64) NULL,
    module VARCHAR(128) NULL,
    last_actual JSONB NULL,
    -- v2.0 全维度测试扩展字段（《AI自测化测试详细设计》v2.0 第 8.5.3 节）
    performance_config JSONB NULL,
    owasp_id VARCHAR(32) NULL,
    dom_selector VARCHAR(500) NULL,
    viewport_config JSONB NULL,
    browser_config VARCHAR(32) NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_test_cases_case_no ON test_cases (case_no);

CREATE INDEX IF NOT EXISTS ix_test_cases_project_id ON test_cases (project_id);

CREATE INDEX IF NOT EXISTS ix_test_cases_tenant_id ON test_cases (tenant_id);

CREATE INDEX IF NOT EXISTS ix_test_cases_category ON test_cases (category);

CREATE INDEX IF NOT EXISTS ix_test_cases_dataset_id ON test_cases (dataset_id);

CREATE TABLE IF NOT EXISTS test_datasets (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) NOT NULL,
    project_id INTEGER NOT NULL,
    name VARCHAR(128) NOT NULL,
    category VARCHAR(64) NOT NULL,
    case_ids JSONB NULL,
    case_count INTEGER NOT NULL,
    source VARCHAR(16) NOT NULL,
    visibility VARCHAR(16) NOT NULL,
    description TEXT NULL,
    meta JSONB NULL,
    created_by INTEGER NULL,
    tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL,
    parameters JSONB NOT NULL DEFAULT '[]'::jsonb,
    data_rows JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_test_datasets_code ON test_datasets (code) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS ix_test_datasets_project_id ON test_datasets (project_id);

CREATE INDEX IF NOT EXISTS ix_test_datasets_tenant_id ON test_datasets (tenant_id);

CREATE TABLE IF NOT EXISTS scenarios (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) NOT NULL,
    project_id INTEGER NOT NULL,
    name VARCHAR(128) NOT NULL,
    description TEXT NULL,
    steps JSONB NOT NULL,
    variables JSONB NULL,
    data_sources JSONB NULL,
    visibility VARCHAR(16) NOT NULL,
    created_by INTEGER NULL,
    tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_scenarios_code ON scenarios (code) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS ix_scenarios_project_id ON scenarios (project_id);

CREATE INDEX IF NOT EXISTS ix_scenarios_tenant_id ON scenarios (tenant_id);

CREATE TABLE IF NOT EXISTS engine_case_libraries (
    id SERIAL PRIMARY KEY,
    case_no VARCHAR(32) NOT NULL,
    engine_code VARCHAR(64) NOT NULL,
    title VARCHAR(256) NOT NULL,
    threat_type VARCHAR(64) NOT NULL,
    payload TEXT NOT NULL,
    expected_behavior TEXT NOT NULL,
    severity VARCHAR(16) NOT NULL,
    tags JSONB NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    sort_order INTEGER NOT NULL DEFAULT 0,
    tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_engine_case_libraries_case_no ON engine_case_libraries (case_no);

CREATE INDEX IF NOT EXISTS ix_engine_case_libraries_tenant_id ON engine_case_libraries (tenant_id);

CREATE INDEX IF NOT EXISTS ix_engine_case_libraries_engine_code ON engine_case_libraries (engine_code);

CREATE INDEX IF NOT EXISTS ix_engine_case_libraries_threat_type ON engine_case_libraries (threat_type);

CREATE TABLE IF NOT EXISTS engine_cases (
    id SERIAL PRIMARY KEY,
    case_no VARCHAR(32) NOT NULL,
    tenant_id INTEGER NOT NULL,
    task_id INTEGER NULL,
    project_id INTEGER NULL,
    object_type VARCHAR(16) NOT NULL,
    source VARCHAR(16) NOT NULL,
    trace_id VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    dimension VARCHAR(16) NOT NULL,
    method VARCHAR(8) NULL,
    path VARCHAR(255) NULL,
    input_json JSONB NULL,
    expected_json JSONB NULL,
    raw_payload JSONB NULL,
    validated BOOLEAN NOT NULL DEFAULT false,
    validation_info JSONB NULL,
    status VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_engine_cases_case_no ON engine_cases (case_no);

CREATE INDEX IF NOT EXISTS ix_engine_cases_tenant_id ON engine_cases (tenant_id);

CREATE INDEX IF NOT EXISTS ix_engine_cases_trace_id ON engine_cases (trace_id);

CREATE INDEX IF NOT EXISTS ix_engine_cases_dimension ON engine_cases (dimension);

SELECT 'inti.sql section 21 asset tables synced' AS done;



-- ============================================================================
-- 22. 报告中心 6 张核心表 DDL（2026-10-04 补全）
--     之前 inti.sql 里 reports / report_shares / notifications /
--     compliance_clauses / report_compliance_alignments / license_ledger
--     全部缺失 CREATE TABLE 主语句！新环境建库后 /reports 直接 500。
-- ============================================================================
CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    report_no VARCHAR(32) NOT NULL,
    task_id INTEGER NOT NULL,
    task_no VARCHAR(32) NULL,
    project_id INTEGER NOT NULL,
    title VARCHAR(256) NOT NULL,
    report_type VARCHAR(32) NOT NULL,
    format VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    file_path VARCHAR(512) NULL,
    file_size INTEGER NULL,
    content JSONB NULL,
    summary JSONB NULL,
    generated_by VARCHAR(64) NULL,
    generated_at TIMESTAMPTZ NULL DEFAULT now(),
    created_by INTEGER NULL,
    tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_reports_report_no ON reports (report_no);

CREATE INDEX IF NOT EXISTS ix_reports_task_id ON reports (task_id);

CREATE INDEX IF NOT EXISTS ix_reports_project_id ON reports (project_id);

CREATE INDEX IF NOT EXISTS ix_reports_status ON reports (status);

CREATE INDEX IF NOT EXISTS ix_reports_tenant_id ON reports (tenant_id);

CREATE TABLE IF NOT EXISTS report_shares (
    id SERIAL PRIMARY KEY,
    report_id INTEGER NOT NULL,
    share_token VARCHAR(64) NOT NULL,
    password_hash VARCHAR(128) NULL,
    expires_at TIMESTAMPTZ NULL,
    view_count INTEGER NOT NULL DEFAULT 0,
    max_views INTEGER NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    last_view_ip VARCHAR(64) NULL,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS report_shares_share_token_key ON report_shares (share_token);

CREATE INDEX IF NOT EXISTS idx_report_shares_report ON report_shares (report_id);

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    notif_no VARCHAR(32) NOT NULL,
    user_id INTEGER NOT NULL,
    tenant_id INTEGER NOT NULL,
    title VARCHAR(256) NOT NULL,
    content TEXT NULL,
    notif_type VARCHAR(32) NOT NULL,
    channel VARCHAR(32) NOT NULL,
    ref_no VARCHAR(64) NULL,
    is_read BOOLEAN NOT NULL,
    read_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_notifications_notif_no ON notifications (notif_no);

CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications (user_id);

CREATE INDEX IF NOT EXISTS ix_notifications_tenant_id ON notifications (tenant_id);

CREATE INDEX IF NOT EXISTS ix_notifications_created_at ON notifications (created_at);

CREATE INDEX IF NOT EXISTS ix_notifications_is_read ON notifications (is_read);

CREATE TABLE IF NOT EXISTS compliance_clauses (
    id SERIAL PRIMARY KEY,
    clause_code VARCHAR(32) NOT NULL,
    category VARCHAR(32) NOT NULL,
    title VARCHAR(256) NOT NULL,
    description TEXT NULL,
    risk_level VARCHAR(16) NOT NULL,
    detection_methods JSONB NOT NULL,
    framework_version VARCHAR(8) NOT NULL,
    status VARCHAR(16) NOT NULL,
    tenant_id INTEGER NOT NULL,
    created_by INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_compliance_clauses_clause_code ON compliance_clauses (clause_code);

CREATE INDEX IF NOT EXISTS ix_compliance_clauses_category ON compliance_clauses (category);

CREATE INDEX IF NOT EXISTS ix_compliance_clauses_tenant_id ON compliance_clauses (tenant_id);

CREATE TABLE IF NOT EXISTS report_compliance_alignments (
    id SERIAL PRIMARY KEY,
    report_id INTEGER NOT NULL,
    clause_id INTEGER NOT NULL,
    result VARCHAR(16) NOT NULL,
    evidence JSONB NULL,
    recommendation TEXT NULL,
    tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_report_clause_tenant ON report_compliance_alignments (report_id, clause_id, tenant_id);

CREATE INDEX IF NOT EXISTS ix_report_compliance_alignments_report_id ON report_compliance_alignments (report_id);

CREATE INDEX IF NOT EXISTS ix_report_compliance_alignments_clause_id ON report_compliance_alignments (clause_id);

CREATE INDEX IF NOT EXISTS ix_report_compliance_alignments_tenant_id ON report_compliance_alignments (tenant_id);

CREATE TABLE IF NOT EXISTS license_ledger (
    id SERIAL PRIMARY KEY,
    component VARCHAR(200) NOT NULL,
    version VARCHAR(64) NOT NULL,
    category VARCHAR(32) NOT NULL DEFAULT 'ENGINE',
    declared_license VARCHAR(100) NULL,
    choosealicense_url VARCHAR(500) NULL,
    choosealicense_status VARCHAR(32) NOT NULL DEFAULT '待复核',
    integration_level VARCHAR(8) NOT NULL,
    isolation_mode VARCHAR(32) NOT NULL,
    risk_level VARCHAR(16) NOT NULL DEFAULT 'LOW',
    decision_note TEXT NULL,
    review_date DATE NULL,
    reviewed_by VARCHAR(64) NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    tenant_id INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS license_ledger_component_key ON license_ledger (component);

CREATE INDEX IF NOT EXISTS idx_ll_category ON license_ledger (category);

CREATE INDEX IF NOT EXISTS idx_ll_risk ON license_ledger (risk_level);

CREATE INDEX IF NOT EXISTS idx_ll_status ON license_ledger (choosealicense_status);

SELECT 'inti.sql section 22 report center tables synced' AS done;



-- ============================================================================
-- 23. 缺陷管理 1 张核心表 DDL（2026-10-04 补全）
-- ============================================================================
CREATE TABLE IF NOT EXISTS defects (
    id SERIAL PRIMARY KEY,
    defect_no VARCHAR(32) NOT NULL,
    project_id INTEGER NOT NULL,
    task_id INTEGER NULL,
    case_id INTEGER NULL,
    report_id INTEGER NULL,
    title VARCHAR(500) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'P2',
    status VARCHAR(16) NOT NULL DEFAULT 'NEW',
    actual TEXT NULL,
    expected TEXT NULL,
    evidence JSONB NULL DEFAULT '[]'::jsonb,
    category VARCHAR(32) NULL,
    ai_reason TEXT NULL,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER NULL,
    created_by_name VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS defects_defect_no_key ON defects (defect_no);

CREATE INDEX IF NOT EXISTS idx_defects_project ON defects (project_id) WHERE (deleted_at IS NULL);

CREATE INDEX IF NOT EXISTS idx_defects_status ON defects (status) WHERE (deleted_at IS NULL);

CREATE INDEX IF NOT EXISTS idx_defects_tenant ON defects (tenant_id) WHERE (deleted_at IS NULL);

SELECT 'inti.sql section 23 defects table synced' AS done;



-- ============================================================================
-- 24. 全量剩余 26 张缺失表 DDL（2026-10-04 全量 diff 扫描补入）
--     PG 真实表数 62 → inti.sql 原定义 36 → 本轮补入 26 → 完整覆盖 62 张
--     涵盖 admin / security / billing / llm_model / sandbox / ethic /
--     gateway / data_dict / conversation_trace / ragas 等基础设施模块
--     全部带 DEFAULT now() + 业务枚举默认值，支持中文（UTF8 + C collation）
-- ============================================================================
CREATE TABLE IF NOT EXISTS system_users (
    id SERIAL PRIMARY KEY, user_no VARCHAR(32) NOT NULL, username VARCHAR(64) NOT NULL,
    email VARCHAR(128) NULL, phone VARCHAR(32) NULL, password_hash VARCHAR(256) NOT NULL,
    display_name VARCHAR(128) NOT NULL, avatar VARCHAR(512) NULL,
    user_type VARCHAR(16) NOT NULL, status VARCHAR(16) NOT NULL, org_id INTEGER NULL,
    title VARCHAR(128) NULL, mfa_enabled BOOLEAN NOT NULL, mfa_secret VARCHAR(128) NULL,
    login_fail_count INTEGER NOT NULL, locked_until TIMESTAMPTZ NULL,
    last_login_at TIMESTAMPTZ NULL, last_login_ip VARCHAR(64) NULL,
    password_changed_at TIMESTAMPTZ NULL, tenant_id INTEGER NOT NULL,
    created_by INTEGER NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted_at TIMESTAMPTZ NULL,
    pwd_reset_token VARCHAR(64) NULL, pwd_reset_expires_at TIMESTAMPTZ NULL,
    must_change_pwd BOOLEAN NOT NULL DEFAULT false
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_system_users_user_no ON system_users (user_no) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE UNIQUE INDEX IF NOT EXISTS ix_system_users_username ON system_users (username) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS ix_system_users_email ON system_users (email);

CREATE INDEX IF NOT EXISTS ix_system_users_tenant_id ON system_users (tenant_id);

CREATE INDEX IF NOT EXISTS ix_system_users_status ON system_users (status);

CREATE TABLE IF NOT EXISTS organizations (
    id SERIAL PRIMARY KEY, org_no VARCHAR(32) NOT NULL, org_name VARCHAR(128) NOT NULL,
    parent_id INTEGER NULL, org_path VARCHAR(512) NOT NULL, sort_order INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL, remark VARCHAR(512) NULL, tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL, plan VARCHAR(20) NOT NULL DEFAULT 'free',
    quota_tasks_monthly INTEGER NOT NULL DEFAULT 100
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_organizations_org_no ON organizations (org_no) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS ix_organizations_tenant_id ON organizations (tenant_id);

CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY, role_code VARCHAR(64) NOT NULL, role_name VARCHAR(128) NOT NULL,
    role_type VARCHAR(16) NOT NULL, description VARCHAR(512) NULL, is_system BOOLEAN NOT NULL,
    tenant_id INTEGER NOT NULL, created_by INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_roles_role_code ON roles (role_code) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS ix_roles_tenant_id ON roles (tenant_id);

CREATE TABLE IF NOT EXISTS user_roles (
    id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, role_id INTEGER NOT NULL,
    tenant_id INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_role_tenant ON user_roles (user_id, role_id, tenant_id);

CREATE INDEX IF NOT EXISTS ix_user_roles_user_id ON user_roles (user_id);

CREATE INDEX IF NOT EXISTS ix_user_roles_role_id ON user_roles (role_id);

CREATE TABLE IF NOT EXISTS permissions (
    id SERIAL PRIMARY KEY, perm_code VARCHAR(128) NOT NULL, perm_name VARCHAR(128) NOT NULL,
    perm_type VARCHAR(16) NOT NULL, module VARCHAR(64) NOT NULL, parent_code VARCHAR(128) NULL,
    sort_order INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_permissions_perm_code ON permissions (perm_code);

CREATE TABLE IF NOT EXISTS role_permissions (
    id SERIAL PRIMARY KEY, role_id INTEGER NOT NULL, perm_code VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_role_perm ON role_permissions (role_id, perm_code);

CREATE INDEX IF NOT EXISTS ix_role_permissions_role_id ON role_permissions (role_id);

CREATE INDEX IF NOT EXISTS ix_role_permissions_perm_code ON role_permissions (perm_code);

CREATE TABLE IF NOT EXISTS api_keys (
    id SERIAL PRIMARY KEY, key_name VARCHAR(64) NOT NULL, key_prefix VARCHAR(16) NOT NULL,
    key_hash VARCHAR(64) NOT NULL, user_id INTEGER NOT NULL, tenant_id INTEGER NOT NULL,
    scopes JSONB NULL, expires_at TIMESTAMPTZ NULL, last_used_at TIMESTAMPTZ NULL,
    disabled BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_key_hash ON api_keys (key_hash) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS ix_api_keys_user_id ON api_keys (user_id);

CREATE INDEX IF NOT EXISTS ix_api_keys_tenant_id ON api_keys (tenant_id);

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY, log_no VARCHAR(32) NOT NULL, user_id INTEGER NULL,
    username VARCHAR(64) NULL, tenant_id INTEGER NOT NULL, action VARCHAR(64) NOT NULL,
    module VARCHAR(64) NOT NULL, method VARCHAR(8) NULL, path VARCHAR(512) NULL,
    status_code INTEGER NULL, result VARCHAR(16) NOT NULL, ip VARCHAR(64) NULL,
    ua VARCHAR(512) NULL, request_body JSONB NULL, error_msg TEXT NULL,
    duration_ms INTEGER NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    chain_index INTEGER NULL, prev_hash VARCHAR(64) NULL, self_hash VARCHAR(64) NULL,
    archived_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_audit_logs_log_no ON audit_logs (log_no);

CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id ON audit_logs (user_id);

CREATE INDEX IF NOT EXISTS ix_audit_logs_username ON audit_logs (username);

CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs (action);

CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_id ON audit_logs (tenant_id);

CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at);

CREATE TABLE IF NOT EXISTS billing_quotas (
    id SERIAL PRIMARY KEY, tenant_id INTEGER NOT NULL, plan VARCHAR(32) NOT NULL,
    task_quota INTEGER NOT NULL, task_used INTEGER NOT NULL,
    eval_quota INTEGER NOT NULL, eval_used INTEGER NOT NULL,
    storage_quota_mb INTEGER NOT NULL, storage_used_mb INTEGER NOT NULL,
    api_calls_quota INTEGER NOT NULL, api_calls_used INTEGER NOT NULL,
    expires_at TIMESTAMPTZ NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    token_budget BIGINT NULL DEFAULT 1000000, token_used BIGINT NULL DEFAULT 0,
    credits DOUBLE PRECISION NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_billing_quotas_tenant_id ON billing_quotas (tenant_id);

CREATE TABLE IF NOT EXISTS billing_records (
    id SERIAL PRIMARY KEY, record_no VARCHAR(32) NOT NULL, tenant_id INTEGER NOT NULL,
    user_id INTEGER NULL, biz_type VARCHAR(32) NOT NULL, ref_no VARCHAR(64) NULL,
    amount DOUBLE PRECISION NOT NULL, unit VARCHAR(16) NOT NULL,
    description VARCHAR(256) NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_billing_records_record_no ON billing_records (record_no);

CREATE INDEX IF NOT EXISTS ix_billing_records_tenant_id ON billing_records (tenant_id);

CREATE INDEX IF NOT EXISTS ix_billing_records_created_at ON billing_records (created_at);

CREATE TABLE IF NOT EXISTS data_dicts (
    id SERIAL PRIMARY KEY, dict_code VARCHAR(64) NOT NULL, dict_name VARCHAR(128) NOT NULL,
    dict_type VARCHAR(32) NOT NULL, description VARCHAR(512) NULL,
    is_system BOOLEAN NOT NULL, status VARCHAR(16) NOT NULL,
    created_by INTEGER NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_data_dicts_dict_code ON data_dicts (dict_code) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE TABLE IF NOT EXISTS dict_items (
    id SERIAL PRIMARY KEY, dict_id INTEGER NOT NULL, item_label VARCHAR(128) NOT NULL,
    item_value VARCHAR(128) NOT NULL, sort_order INTEGER NOT NULL, ext JSONB NULL,
    status VARCHAR(16) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_dict_items_dict_id ON dict_items (dict_id);

CREATE TABLE IF NOT EXISTS model_configs (
    id SERIAL PRIMARY KEY, code VARCHAR(32) NOT NULL, name VARCHAR(128) NOT NULL,
    provider VARCHAR(64) NOT NULL, base_url VARCHAR(512) NULL, model VARCHAR(128) NOT NULL,
    api_key_env VARCHAR(64) NULL, timeout_sec INTEGER NOT NULL, max_tokens INTEGER NOT NULL,
    temperature DOUBLE PRECISION NOT NULL, headers JSONB NULL,
    is_default BOOLEAN NOT NULL, status VARCHAR(16) NOT NULL, is_system BOOLEAN NOT NULL,
    created_by INTEGER NULL, tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL, input_price_per_mtok NUMERIC NULL DEFAULT 0,
    output_price_per_mtok NUMERIC NULL DEFAULT 0, usage VARCHAR(16) NOT NULL DEFAULT 'CHAT'
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_model_configs_code ON model_configs (code) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS ix_model_configs_tenant_id ON model_configs (tenant_id);

CREATE TABLE IF NOT EXISTS model_gateway_records (
    id SERIAL PRIMARY KEY, record_no VARCHAR(32) NOT NULL, tenant_id INTEGER NOT NULL,
    user_id INTEGER NULL, task_id INTEGER NULL, step_id INTEGER NULL, ref_no VARCHAR(64) NULL,
    provider VARCHAR(64) NOT NULL, model VARCHAR(128) NOT NULL, model_code VARCHAR(32) NULL,
    request_hash VARCHAR(64) NULL, prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
    input_price_per_mtok DOUBLE PRECISION NOT NULL, output_price_per_mtok DOUBLE PRECISION NOT NULL,
    input_cost DOUBLE PRECISION NOT NULL, output_cost DOUBLE PRECISION NOT NULL,
    total_cost DOUBLE PRECISION NOT NULL, cache_hit BOOLEAN NOT NULL, latency_ms INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL, error_code VARCHAR(32) NULL, error_msg TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_model_gateway_records_record_no ON model_gateway_records (record_no);

CREATE INDEX IF NOT EXISTS ix_model_gateway_records_model ON model_gateway_records (model);

CREATE INDEX IF NOT EXISTS ix_model_gateway_records_tenant_id ON model_gateway_records (tenant_id);

CREATE INDEX IF NOT EXISTS ix_model_gateway_records_created_at ON model_gateway_records (created_at);

CREATE TABLE IF NOT EXISTS llm_cache_entries (
    id SERIAL PRIMARY KEY, cache_key VARCHAR(128) NOT NULL, provider VARCHAR(64) NOT NULL,
    model VARCHAR(128) NOT NULL, normalized_msgs JSONB NULL, response_text TEXT NOT NULL,
    ttl_seconds INTEGER NOT NULL, expires_at TIMESTAMPTZ NOT NULL, hit_count INTEGER NOT NULL,
    last_hit_at TIMESTAMPTZ NULL, tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_llm_cache_entries_cache_key ON llm_cache_entries (cache_key);

CREATE INDEX IF NOT EXISTS ix_llm_cache_entries_model ON llm_cache_entries (model);

CREATE INDEX IF NOT EXISTS ix_llm_cache_entries_tenant_id ON llm_cache_entries (tenant_id);

CREATE TABLE IF NOT EXISTS llm_cache_semantics (
    id SERIAL PRIMARY KEY, entry_id INTEGER NOT NULL, tenant_id INTEGER NOT NULL,
    model VARCHAR(128) NOT NULL, prompt_text TEXT NOT NULL, embedding_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_llm_cache_semantics_entry_id ON llm_cache_semantics (entry_id);

CREATE INDEX IF NOT EXISTS ix_llm_cache_semantics_model ON llm_cache_semantics (model);

CREATE INDEX IF NOT EXISTS ix_llm_cache_semantics_tenant_id ON llm_cache_semantics (tenant_id);

CREATE TABLE IF NOT EXISTS gateway_rate_limits (
    id SERIAL PRIMARY KEY, limit_no VARCHAR(32) NOT NULL, tenant_id INTEGER NOT NULL,
    scope VARCHAR(16) NOT NULL, scope_key VARCHAR(128) NOT NULL,
    qps DOUBLE PRECISION NOT NULL, concurrency INTEGER NOT NULL, per_minute INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL, remark VARCHAR(255) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_gateway_rate_limits_limit_no ON gateway_rate_limits (limit_no);

CREATE INDEX IF NOT EXISTS ix_gateway_rate_limits_tenant_id ON gateway_rate_limits (tenant_id);

CREATE TABLE IF NOT EXISTS sandbox_executions (
    id SERIAL PRIMARY KEY, execution_no VARCHAR(32) NOT NULL, task_id INTEGER NOT NULL,
    task_no VARCHAR(32) NULL, sandbox_id VARCHAR(64) NULL, image_id INTEGER NULL,
    status VARCHAR(24) NOT NULL, engine_code VARCHAR(32) NOT NULL,
    started_at TIMESTAMPTZ NULL, ended_at TIMESTAMPTZ NULL, timeout_seconds INTEGER NOT NULL,
    exit_code INTEGER NULL, logs TEXT NULL, artifacts JSONB NULL,
    result_payload JSONB NULL, error_msg TEXT NULL, tenant_id INTEGER NOT NULL,
    created_by INTEGER NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_sandbox_executions_execution_no ON sandbox_executions (execution_no);

CREATE INDEX IF NOT EXISTS ix_sandbox_executions_task_id ON sandbox_executions (task_id);

CREATE INDEX IF NOT EXISTS ix_sandbox_executions_task_no ON sandbox_executions (task_no);

CREATE INDEX IF NOT EXISTS ix_sandbox_executions_status ON sandbox_executions (status);

CREATE INDEX IF NOT EXISTS ix_sandbox_executions_tenant_id ON sandbox_executions (tenant_id);

CREATE TABLE IF NOT EXISTS sandbox_images (
    id SERIAL PRIMARY KEY, image_no VARCHAR(32) NOT NULL, image_name VARCHAR(128) NOT NULL,
    image_tag VARCHAR(64) NOT NULL, registry_url VARCHAR(256) NULL,
    full_name VARCHAR(256) NOT NULL, description VARCHAR(512) NULL,
    is_default BOOLEAN NOT NULL, is_enabled BOOLEAN NOT NULL, tenant_id INTEGER NOT NULL,
    created_by INTEGER NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_sandbox_images_image_no ON sandbox_images (image_no);

CREATE INDEX IF NOT EXISTS ix_sandbox_images_tenant_id ON sandbox_images (tenant_id);

CREATE TABLE IF NOT EXISTS conversation_traces (
    id SERIAL PRIMARY KEY, trace_no VARCHAR(32) NOT NULL, task_no VARCHAR(32) NOT NULL,
    step_no VARCHAR(32) NOT NULL, session_no VARCHAR(32) NOT NULL,
    session_topic VARCHAR(255) NOT NULL, rounds INTEGER NOT NULL,
    contradiction_count INTEGER NOT NULL, resolve_count INTEGER NOT NULL,
    context_drift_score DOUBLE PRECISION NOT NULL, consistency_score DOUBLE PRECISION NOT NULL,
    status VARCHAR(16) NOT NULL, trace JSONB NOT NULL, tenant_id INTEGER NOT NULL,
    created_by INTEGER NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_conversation_traces_trace_no ON conversation_traces (trace_no);

CREATE INDEX IF NOT EXISTS ix_conversation_traces_task_no ON conversation_traces (task_no);

CREATE INDEX IF NOT EXISTS ix_conversation_traces_session_no ON conversation_traces (session_no);

CREATE INDEX IF NOT EXISTS ix_conversation_traces_tenant_id ON conversation_traces (tenant_id);

CREATE TABLE IF NOT EXISTS ethic_regulations (
    id SERIAL PRIMARY KEY, regulation_no VARCHAR(32) NOT NULL, regulation_name VARCHAR(255) NOT NULL,
    version VARCHAR(32) NOT NULL, effective_date TIMESTAMPTZ NOT NULL, clauses JSONB NOT NULL,
    region VARCHAR(32) NOT NULL, global BOOLEAN NOT NULL, status VARCHAR(16) NOT NULL,
    tenant_id INTEGER NOT NULL, created_by INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ethic_regulations_regulation_no ON ethic_regulations (regulation_no, version);

CREATE INDEX IF NOT EXISTS ix_ethic_regulations_regulation_no ON ethic_regulations (regulation_no);

CREATE INDEX IF NOT EXISTS ix_ethic_regulations_effective_date ON ethic_regulations (effective_date);

CREATE INDEX IF NOT EXISTS ix_ethic_regulations_tenant_id ON ethic_regulations (tenant_id);

CREATE TABLE IF NOT EXISTS ethic_audit_records (
    id SERIAL PRIMARY KEY, audit_no VARCHAR(32) NOT NULL, task_no VARCHAR(32) NOT NULL,
    step_no VARCHAR(32) NOT NULL, item_no VARCHAR(32) NOT NULL, regulation_no VARCHAR(32) NOT NULL,
    regulation_version VARCHAR(32) NOT NULL, overall_severity VARCHAR(16) NOT NULL,
    compliance_score DOUBLE PRECISION NOT NULL, violations JSONB NOT NULL, scores_json JSONB NOT NULL,
    tenant_id INTEGER NOT NULL, created_by INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_ethic_audit_records_audit_no ON ethic_audit_records (audit_no);

CREATE INDEX IF NOT EXISTS ix_ethic_audit_records_task_no ON ethic_audit_records (task_no);

CREATE INDEX IF NOT EXISTS ix_ethic_audit_records_tenant_id ON ethic_audit_records (tenant_id);

CREATE TABLE IF NOT EXISTS hallucination_embeddings (
    id SERIAL PRIMARY KEY, embedding_no VARCHAR(32) NOT NULL, task_no VARCHAR(32) NOT NULL,
    step_no VARCHAR(32) NOT NULL, item_no VARCHAR(32) NOT NULL,
    prompt TEXT NOT NULL, prompt_embedding JSONB NOT NULL, ref_embedding JSONB NOT NULL,
    model_name VARCHAR(128) NOT NULL, dim INTEGER NOT NULL, score DOUBLE PRECISION NOT NULL,
    severity VARCHAR(16) NOT NULL, tenant_id INTEGER NOT NULL, created_by INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_hallucination_embeddings_embedding_no ON hallucination_embeddings (embedding_no);

CREATE INDEX IF NOT EXISTS ix_hallucination_embeddings_task_no ON hallucination_embeddings (task_no);

CREATE INDEX IF NOT EXISTS ix_hallucination_embeddings_tenant_id ON hallucination_embeddings (tenant_id);

CREATE TABLE IF NOT EXISTS ragas_metric_records (
    id SERIAL PRIMARY KEY, ragas_no VARCHAR(32) NOT NULL, task_no VARCHAR(32) NOT NULL,
    step_no VARCHAR(32) NOT NULL, item_no VARCHAR(32) NOT NULL,
    faithfulness DOUBLE PRECISION NOT NULL, answer_relevance DOUBLE PRECISION NOT NULL,
    context_recall DOUBLE PRECISION NOT NULL, ragas_score DOUBLE PRECISION NOT NULL,
    grade VARCHAR(16) NOT NULL, retrieval_recall DOUBLE PRECISION NULL,
    retrieval_precision DOUBLE PRECISION NULL, judge_rationale JSONB NOT NULL,
    tenant_id INTEGER NOT NULL, created_by INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_ragas_metric_records_ragas_no ON ragas_metric_records (ragas_no);

CREATE INDEX IF NOT EXISTS ix_ragas_metric_records_task_no ON ragas_metric_records (task_no);

CREATE INDEX IF NOT EXISTS ix_ragas_metric_records_tenant_id ON ragas_metric_records (tenant_id);

CREATE TABLE IF NOT EXISTS heal_records (
    id SERIAL PRIMARY KEY, heal_no VARCHAR(32) NOT NULL, tenant_id INTEGER NOT NULL,
    task_id INTEGER NULL, step_id INTEGER NULL, trace_id VARCHAR(64) NULL,
    script_code VARCHAR(255) NOT NULL, failure_class VARCHAR(16) NOT NULL,
    strategy_used VARCHAR(24) NOT NULL, attempt_no INTEGER NOT NULL,
    successful BOOLEAN NOT NULL, fix_detail JSONB NULL, impact JSONB NULL, report JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_heal_records_heal_no ON heal_records (heal_no);

CREATE INDEX IF NOT EXISTS ix_heal_records_tenant_id ON heal_records (tenant_id);

CREATE INDEX IF NOT EXISTS ix_heal_records_created_at ON heal_records (created_at);

CREATE INDEX IF NOT EXISTS ix_heal_records_failure_class ON heal_records (failure_class);

CREATE TABLE IF NOT EXISTS test_engines (
    id SERIAL PRIMARY KEY, engine_code VARCHAR(64) NOT NULL, engine_name VARCHAR(128) NOT NULL,
    engine_type VARCHAR(32) NOT NULL, category VARCHAR(64) NOT NULL,
    description TEXT NULL, version VARCHAR(32) NOT NULL, entry_point VARCHAR(256) NOT NULL,
    supports_params JSONB NULL, status VARCHAR(16) NOT NULL, is_system BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_test_engines_engine_code ON test_engines (engine_code);

SELECT 'inti.sql section 24 full sync 62/62 tables DONE' AS done;



-- ---- 前移（空库依赖修复）：原 section 17-18 eval 表 DDL ----
-- ============================================================================
-- 17. 评测模块 DDL（M5：eval_sets + eval_runs，2026-10-04 补全）
--     之前注释误写"复用 JSON 字段无需新增表"，实际上 models.py 里定义了完整结构
-- ============================================================================
CREATE TABLE IF NOT EXISTS eval_sets (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) NOT NULL,
    name VARCHAR(128) NOT NULL,
    category VARCHAR(64) NOT NULL,
    items JSONB NOT NULL,
    item_count INTEGER NOT NULL,
    source VARCHAR(16) NOT NULL,
    meta JSONB NULL,
    visibility VARCHAR(16) NOT NULL,
    created_by INTEGER NULL,
    tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ NULL,
    project_id INTEGER NULL,
    content_schema JSONB NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_eval_sets_code ON eval_sets (code) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS ix_eval_sets_category ON eval_sets (category);

CREATE INDEX IF NOT EXISTS ix_eval_sets_tenant_id ON eval_sets (tenant_id);

CREATE INDEX IF NOT EXISTS idx_eval_sets_project ON eval_sets (project_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS eval_runs (
    id SERIAL PRIMARY KEY,
    run_no VARCHAR(32) NOT NULL,
    eval_set_id INTEGER NOT NULL,
    eval_set_code VARCHAR(32) NULL,
    target_type VARCHAR(32) NOT NULL,
    target_id VARCHAR(128) NOT NULL,
    model_gateway VARCHAR(256) NULL,
    judge_mode VARCHAR(16) NOT NULL,
    judge_model VARCHAR(128) NULL,
    status VARCHAR(16) NOT NULL,
    item_results JSONB NULL,
    overall_score DOUBLE PRECISION NULL,
    verdict VARCHAR(16) NULL,
    summary JSONB NULL,
    report_id INTEGER NULL,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    duration_ms INTEGER NULL,
    created_by INTEGER NULL,
    tenant_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL,
    task_id INTEGER NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_eval_runs_run_no ON eval_runs (run_no);

CREATE INDEX IF NOT EXISTS ix_eval_runs_tenant_id ON eval_runs (tenant_id);

CREATE INDEX IF NOT EXISTS ix_eval_runs_status ON eval_runs (status);

CREATE INDEX IF NOT EXISTS ix_eval_runs_eval_set_id ON eval_runs (eval_set_id);

CREATE INDEX IF NOT EXISTS ix_eval_runs_task_id ON eval_runs (task_id);

SELECT 'inti.sql section 17 eval module synced' AS done;



-- ============================================================================
-- 18. 补丁：eval_runs.task_id 补列（2026-10-04 线上修复 UndefinedColumn）
--     幂等，已在本环境成功 ALTER TABLE
-- ============================================================================
ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS task_id INTEGER;



-- reports / eval_runs 时间列默认值统一
ALTER TABLE eval_runs  ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE eval_sets  ALTER COLUMN created_at SET DEFAULT now();

SELECT 'inti.sql section 18 eval_runs.task_id patch synced' AS done;



-- 1.1 M8：项目被测环境地址（JSONB 数组：[{name, base_url, is_default}]）
ALTER TABLE projects ADD COLUMN IF NOT EXISTS environments JSONB DEFAULT '[]'::jsonb;


-- 存量库迁移：历史建库为 json 类型，统一改为 jsonb（C1 ORM 模型声明）
ALTER TABLE projects ALTER COLUMN environments TYPE JSONB USING environments::JSONB;



-- 1.2 M8：项目成员表（负责人/成员/只读，用于私有项目权限）
CREATE TABLE IF NOT EXISTS project_members (
    id           BIGSERIAL PRIMARY KEY,
    project_id   INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    role         VARCHAR(16) NOT NULL DEFAULT 'MEMBER',
    tenant_id    INTEGER NOT NULL DEFAULT 1,               -- 模型 ProjectMembers.tenant_id（ensure_data_scope 依赖）
    created_by   INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
);


-- 存量库补列（表早于本 DDL 创建时 CREATE IF NOT EXISTS 会跳过）
ALTER TABLE project_members ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1;

ALTER TABLE project_members ADD COLUMN IF NOT EXISTS created_by INTEGER;

CREATE INDEX IF NOT EXISTS idx_project_members_project ON project_members(project_id);

CREATE INDEX IF NOT EXISTS idx_project_members_user ON project_members(user_id);

CREATE INDEX IF NOT EXISTS idx_project_members_tenant ON project_members(tenant_id);


-- 模型级唯一约束 uq_project_user_tenant（存量重复数据时跳过，不阻塞同步）
DO $$ BEGIN
    CREATE UNIQUE INDEX IF NOT EXISTS uq_project_user_tenant ON project_members(project_id, user_id, tenant_id);
EXCEPTION WHEN OTHERS THEN NULL;
END $$;



-- ===========================================================================
-- 1.3 MVP 2.0 增量表（对应《EvalShield MVP详细开发说明书.md》第三章 H-1～H-7）
--     原则：全部不使用外键（C1），一致性由应用层维护 + 唯一约束兜底
-- ===========================================================================

-- H-1 组织邀请（邮件邀请成员，令牌 7 天有效）
CREATE TABLE IF NOT EXISTS org_invitations (
    id           BIGSERIAL PRIMARY KEY,
    org_id       INTEGER NOT NULL,
    email        VARCHAR(200) NOT NULL,
    role         VARCHAR(20) NOT NULL DEFAULT 'TESTER',
    token        VARCHAR(64) NOT NULL UNIQUE,
    status       VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    expires_at   TIMESTAMPTZ NOT NULL,
    invited_by   INTEGER,
    tenant_id    INTEGER NOT NULL DEFAULT 1,
    created_by   INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_org_inv_org  ON org_invitations(org_id);

CREATE INDEX IF NOT EXISTS idx_org_inv_mail ON org_invitations(email);



-- H-2 测试套件（套件编排 / 定时表达式预留）
CREATE TABLE IF NOT EXISTS test_suites (
    id           BIGSERIAL PRIMARY KEY,
    suite_no     VARCHAR(32) NOT NULL UNIQUE,
    project_id   INTEGER NOT NULL,
    name         VARCHAR(200) NOT NULL,
    description  TEXT,
    exec_mode    VARCHAR(16) NOT NULL DEFAULT 'SEQUENTIAL',
    cron_expr    VARCHAR(100),
    is_enabled   BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at  TIMESTAMPTZ,
    tenant_id    INTEGER NOT NULL DEFAULT 1,
    created_by   INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_test_suites_project ON test_suites(project_id) WHERE deleted_at IS NULL;



-- H-3 套件明细（套件-任务关联，项目内防重复）
CREATE TABLE IF NOT EXISTS test_suite_items (
    id           BIGSERIAL PRIMARY KEY,
    suite_id     INTEGER NOT NULL,
    task_id      INTEGER NOT NULL,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    tenant_id    INTEGER NOT NULL DEFAULT 1,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_suite_item UNIQUE (suite_id, task_id)
);

CREATE INDEX IF NOT EXISTS idx_suite_items_task ON test_suite_items(task_id);



-- H-4 项目版本（语义化版本 / 基线唯一）
CREATE TABLE IF NOT EXISTS project_versions (
    id              BIGSERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL,
    version_no      VARCHAR(64) NOT NULL,
    description     VARCHAR(500),
    is_baseline     BOOLEAN NOT NULL DEFAULT FALSE,
    baseline_reason VARCHAR(500),
    tenant_id       INTEGER NOT NULL DEFAULT 1,
    created_by      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_project_version_no UNIQUE (project_id, version_no)
);


-- 每项目至多 1 个基线（部分唯一索引；应用层先取消旧基线再设置）
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_versions_baseline
    ON project_versions(project_id) WHERE is_baseline = TRUE;

CREATE INDEX IF NOT EXISTS idx_project_versions_project ON project_versions(project_id);



-- P2-19 测试资产版本快照（用例/数据集/场景，基于 project_versions 关联）
CREATE TABLE IF NOT EXISTS asset_versions (
    id                 BIGSERIAL PRIMARY KEY,
    project_id         INTEGER NOT NULL,
    project_version_id INTEGER,
    asset_type         VARCHAR(16) NOT NULL,
    asset_id           INTEGER NOT NULL,
    asset_no           VARCHAR(32),
    seq                INTEGER NOT NULL DEFAULT 1,
    snapshot           JSONB NOT NULL DEFAULT '{}'::jsonb,
    change_note        VARCHAR(500),
    tenant_id          INTEGER NOT NULL DEFAULT 1,
    created_by         INTEGER,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_asset_versions_asset ON asset_versions(asset_type, asset_id);

CREATE INDEX IF NOT EXISTS idx_asset_versions_project ON asset_versions(project_id);



-- H-5 报告分享（只读链接 / 可选密码 / 有效期 / 访问统计）
CREATE TABLE IF NOT EXISTS report_shares (
    id            BIGSERIAL PRIMARY KEY,
    report_id     INTEGER NOT NULL,
    share_token   VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(128),
    expires_at    TIMESTAMPTZ,
    view_count    INTEGER NOT NULL DEFAULT 0,
    max_views     INTEGER,
    is_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    last_view_ip  VARCHAR(64),
    tenant_id     INTEGER NOT NULL DEFAULT 1,
    created_by    INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);



-- H-6 登录尝试（失败锁定审计；公开分享密码错误复用本表，username 存 share:{token}）
CREATE TABLE IF NOT EXISTS login_attempts (
    id          BIGSERIAL PRIMARY KEY,
    username    VARCHAR(100) NOT NULL,
    ip          VARCHAR(64),
    success     BOOLEAN NOT NULL,
    fail_reason VARCHAR(200),
    tenant_id   INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_un ON login_attempts(username, created_at);



-- H-7 密码历史（禁止复用最近 5 次密码）
CREATE TABLE IF NOT EXISTS password_history (
    id            BIGSERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL,
    password_hash VARCHAR(128) NOT NULL,
    tenant_id     INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_password_history_user ON password_history(user_id, created_at);



-- 增量字段：任务归属套件 / 任务被测版本 / 用户重置令牌 / 组织套餐与配额
ALTER TABLE test_tasks    ADD COLUMN IF NOT EXISTS suite_id INTEGER;

ALTER TABLE test_tasks    ADD COLUMN IF NOT EXISTS task_version VARCHAR(64);

ALTER TABLE system_users  ADD COLUMN IF NOT EXISTS pwd_reset_token VARCHAR(64);

ALTER TABLE system_users  ADD COLUMN IF NOT EXISTS pwd_reset_expires_at TIMESTAMPTZ;

ALTER TABLE system_users  ADD COLUMN IF NOT EXISTS must_change_pwd BOOLEAN NOT NULL DEFAULT false;

 -- 优化7 T4 首登强制改密
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS plan VARCHAR(20) NOT NULL DEFAULT 'free';

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS quota_tasks_monthly INTEGER NOT NULL DEFAULT 100;



-- 审计日志 Hash-chain 校验链字段（SQLAlchemy 模型 audit_logs 声明）
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64);

ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS self_hash VARCHAR(64);

ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS chain_index INTEGER;

ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;



-- 模型用途（CHAT/EMBEDDING，embedding 引擎代码依赖此列）
ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS usage VARCHAR(16) NOT NULL DEFAULT 'CHAT';



-- 自愈记录增量列（软删除 + 更新时间）
ALTER TABLE heal_records ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE heal_records ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL;

ALTER TABLE eval_sets ADD COLUMN IF NOT EXISTS project_id INTEGER;



-- ===========================================================================
-- G-1：计费套餐 + 充值记录
-- ===========================================================================
CREATE TABLE IF NOT EXISTS billing_plans (
    id            BIGSERIAL PRIMARY KEY,
    code          VARCHAR(32) NOT NULL UNIQUE,
    name          VARCHAR(128) NOT NULL,
    description   TEXT,
    price_monthly DOUBLE PRECISION NOT NULL DEFAULT 0,
    credits       DOUBLE PRECISION NOT NULL DEFAULT 0,
    max_tasks     INTEGER,
    features      JSONB DEFAULT '[]'::jsonb,
    status        VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    created_by    INTEGER,
    tenant_id     INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_bp_tenant ON billing_plans(tenant_id, status) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS billing_topups (
    id            BIGSERIAL PRIMARY KEY,
    code          VARCHAR(32) NOT NULL UNIQUE,
    user_id       INTEGER NOT NULL,
    plan_id       INTEGER,
    amount        DOUBLE PRECISION NOT NULL DEFAULT 0,
    credits_add   DOUBLE PRECISION NOT NULL DEFAULT 0,
    status        VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    channel       VARCHAR(32) NOT NULL DEFAULT 'ADMIN',
    remark        VARCHAR(512),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_bt_user ON billing_topups(user_id) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_bt_code ON billing_topups(code);



-- ===========================================================================
-- BillingQuota 增量字段：credits（充值累加）
-- ===========================================================================
ALTER TABLE billing_quotas ADD COLUMN IF NOT EXISTS credits DOUBLE PRECISION NOT NULL DEFAULT 0;

 -- BUG-008: 匹配 partial 唯一索引

-- ===========================================================================
-- 4. 优化二：真实工具链 + License 合规（2026-09-24）
-- ===========================================================================

-- 4.1 GE 期望套件资产表（与 datasets 关联）
CREATE TABLE IF NOT EXISTS data_quality_expectations (
    id              BIGSERIAL PRIMARY KEY,
    expect_no       VARCHAR(32) NOT NULL UNIQUE,
    dataset_id      INTEGER NOT NULL,
    name            VARCHAR(200) NOT NULL,
    source_type     VARCHAR(16) NOT NULL DEFAULT 'CSV',
    source_ref      VARCHAR(500) NOT NULL,
    suite_json      JSONB NOT NULL DEFAULT '[]'::jsonb,
    severity        VARCHAR(16) NOT NULL DEFAULT 'STRICT',
    description     TEXT,
    tenant_id       INTEGER NOT NULL DEFAULT 1,
    created_by      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_dq_exp_dataset ON data_quality_expectations(dataset_id) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_dq_exp_tenant  ON data_quality_expectations(tenant_id) WHERE deleted_at IS NULL;



-- 4.2 GE 验证结果（引擎执行后持久化）
CREATE TABLE IF NOT EXISTS data_quality_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_no          VARCHAR(32) NOT NULL UNIQUE,
    expectation_id  INTEGER,
    task_id         INTEGER,
    total_checks    INTEGER NOT NULL DEFAULT 0,
    passed_checks   INTEGER NOT NULL DEFAULT 0,
    failed_checks   INTEGER NOT NULL DEFAULT 0,
    status          VARCHAR(16) NOT NULL DEFAULT 'RUNNING',
    result_json     JSONB,
    summary         JSONB,
    error_message   TEXT,
    executed_by     INTEGER,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    tenant_id       INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_dq_runs_exp  ON data_quality_runs(expectation_id);

CREATE INDEX IF NOT EXISTS idx_dq_runs_task ON data_quality_runs(task_id);

CREATE INDEX IF NOT EXISTS idx_dq_runs_time ON data_quality_runs(started_at DESC);



-- 4.3 License 合规台账（SBOM）
CREATE TABLE IF NOT EXISTS license_ledger (
    id                      BIGSERIAL PRIMARY KEY,
    component               VARCHAR(200) NOT NULL UNIQUE,
    version                 VARCHAR(64) NOT NULL,
    category                VARCHAR(32) NOT NULL DEFAULT 'ENGINE',
    declared_license        VARCHAR(100),
    choosealicense_url      VARCHAR(500),
    choosealicense_status   VARCHAR(32) NOT NULL DEFAULT '待复核',
    integration_level       VARCHAR(8) NOT NULL,
    isolation_mode          VARCHAR(32) NOT NULL,
    risk_level              VARCHAR(16) NOT NULL DEFAULT 'LOW',
    decision_note           TEXT,
    review_date             DATE,
    reviewed_by             VARCHAR(64),
    status                  VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    tenant_id               INTEGER NOT NULL DEFAULT 1,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);



-- ===========================================================================
-- 5. DEFAULT NOW() 统一（2026-09-25 修复：所有表 created_at/updated_at 缺默认值）
--    实测 INSERT test_cases 必报 NotNullViolation，一次性补全
-- ===========================================================================
ALTER TABLE test_cases       ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE test_cases       ALTER COLUMN updated_at SET DEFAULT now();

ALTER TABLE test_datasets    ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE test_datasets    ALTER COLUMN updated_at SET DEFAULT now();


-- R3-1：Dataset 参数列定义（前端 DatasetsTab Form.List 提交 parameters，幂等加列）
ALTER TABLE test_datasets ADD COLUMN IF NOT EXISTS parameters JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN test_datasets.parameters IS '参数列定义：[{name, type, example}]';


-- R3-2：Dataset 数据行定义（数据驱动测试实际数据，前端 DatasetsTab 数据行编辑器提交 data_rows，幂等加列）
ALTER TABLE test_datasets ADD COLUMN IF NOT EXISTS data_rows JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN test_datasets.data_rows IS '数据行定义：[{列名: 值, ...}]';

ALTER TABLE scenarios        ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE scenarios        ALTER COLUMN updated_at SET DEFAULT now();

ALTER TABLE test_tasks       ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE test_tasks       ALTER COLUMN updated_at SET DEFAULT now();

ALTER TABLE test_suites      ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE test_suite_items ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE reports          ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE reports          ALTER COLUMN generated_at SET DEFAULT now();

ALTER TABLE compliance_clauses ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE audit_logs       ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE eval_sets        ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE eval_runs        ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE dict_items       ALTER COLUMN created_at SET DEFAULT now();

ALTER TABLE dict_items       ALTER COLUMN updated_at SET DEFAULT now();



-- ===========================================================================
-- 5b. 测试用例功能优化：五段式结构列（幂等，可重复执行）
--     test_cases 增 7 列；eval_sets 增 content_schema（区分 EVAL/安全样本等条目 schema）
-- ===========================================================================
ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS content_schema JSONB;

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS preconditions JSONB DEFAULT '[]'::jsonb;

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS test_data JSONB DEFAULT '[]'::jsonb;

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS assertions JSONB DEFAULT '[]'::jsonb;

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS extract_vars JSONB DEFAULT '{}'::jsonb;

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS post_cleanup JSONB DEFAULT '[]'::jsonb;

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS requirement_id VARCHAR(64);

ALTER TABLE eval_sets ADD COLUMN IF NOT EXISTS content_schema JSONB;

SELECT 'SEED DATA LOADED' AS done;



-- ===========================================================================
-- 7. P1-1：test_cases 新增所属模块字段（module）+ last_actual 执行摘要（2026-09-29）
-- ===========================================================================
ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS module VARCHAR(128);

COMMENT ON COLUMN test_cases.module IS '所属模块（如 登录/订单/支付）';

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS last_actual JSONB;

COMMENT ON COLUMN test_cases.last_actual IS '最近一次实际输出摘要（断言实际值）';



-- ===========================================================================
-- 8. P2-7：任务执行人 executor（2026-09-29）
-- ===========================================================================
ALTER TABLE test_tasks    ADD COLUMN IF NOT EXISTS executor VARCHAR(64);

ALTER TABLE task_steps   ADD COLUMN IF NOT EXISTS executor VARCHAR(64);

COMMENT ON COLUMN test_tasks.executor IS '触发执行的测试人员（区别于创建人）';

COMMENT ON COLUMN task_steps.executor IS '执行该步骤的测试人员';



-- ===========================================================================
-- 9. P2-5/6：AI 生成数据集 + AI 断言补全（复用现有表结构，无需新表）
-- ===========================================================================
-- test_datasets.source 已有 AI_GEN 枚举值；test_cases.request_spec + last_actual 已可支撑 AI 断言补全

-- ===========================================================================
-- 10. P2-8：报告导出（复用现有 reports 表，Word/PDF 运行时生成临时文件）
-- ===========================================================================

-- ===========================================================================
-- 11. P3-9：缺陷管理（defects 表，无外键）（2026-09-29）
-- ===========================================================================
CREATE TABLE IF NOT EXISTS defects (
    id              BIGSERIAL PRIMARY KEY,
    defect_no       VARCHAR(32) NOT NULL UNIQUE,
    project_id      INTEGER NOT NULL,
    task_id         INTEGER,
    case_id         INTEGER,
    report_id       INTEGER,
    title           VARCHAR(500) NOT NULL,
    severity        VARCHAR(16) NOT NULL DEFAULT 'P2',
    status          VARCHAR(16) NOT NULL DEFAULT 'NEW',
    actual          TEXT,
    expected        TEXT,
    evidence        JSONB DEFAULT '[]'::jsonb,
    category        VARCHAR(32),
    ai_reason       TEXT,
    tenant_id       INTEGER NOT NULL DEFAULT 1,
    created_by      INTEGER,
    created_by_name VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);



-- ===========================================================================
-- 12. P3-11：环境管理（test_environments 表，无外键）（2026-09-29）
-- ===========================================================================
CREATE TABLE IF NOT EXISTS test_environments (
    id           BIGSERIAL PRIMARY KEY,
    project_id   INTEGER NOT NULL,
    name         VARCHAR(128) NOT NULL,
    base_url     VARCHAR(500) NOT NULL,
    auth         JSONB DEFAULT '{}'::jsonb,
    is_default   BOOLEAN NOT NULL DEFAULT FALSE,
    description  VARCHAR(500),
    tenant_id    INTEGER NOT NULL DEFAULT 1,
    created_by   INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_env_project ON test_environments(project_id) WHERE deleted_at IS NULL;



-- ===========================================================================
-- 13. P3-12：UI 录制（test_recordings 表，无外键）（2026-09-29）
-- ===========================================================================
CREATE TABLE IF NOT EXISTS test_recordings (
    id          BIGSERIAL PRIMARY KEY,
    rec_no      VARCHAR(32) NOT NULL UNIQUE,
    project_id  INTEGER NOT NULL,
    case_id     INTEGER,
    name        VARCHAR(200) NOT NULL,
    steps       JSONB NOT NULL DEFAULT '[]'::jsonb,
    duration_ms INTEGER,
    tenant_id   INTEGER NOT NULL DEFAULT 1,
    created_by  INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rec_project ON test_recordings(project_id) WHERE updated_at IS NOT NULL;

SELECT 'inti.sql section 14 RBAC synced' AS done;



-- ===========================================================================
-- 15. AI 自测化测试：自动探测任务（《AI自测化测试详细开发.md》v2.0 第 1 章）
--     原则：无外键、tenant_id 隔离、幂等可重复执行、UTF-8
-- ===========================================================================

-- 15.1 探测任务历史
CREATE TABLE IF NOT EXISTS discover_jobs (
    id              BIGSERIAL PRIMARY KEY,
    job_no          VARCHAR(64) NOT NULL UNIQUE,               -- gen_no('DJ')
    project_id      INTEGER NOT NULL,
    url             VARCHAR(500) NOT NULL,                     -- 来自 test_environments.base_url
    auth_type       VARCHAR(16) NOT NULL DEFAULT 'USERPASS',   -- USERPASS/COOKIE/TOKEN/NO_AUTH/MANUAL/SESSION（随 login_method 映射覆盖，LM-08）
    discover_mode   VARCHAR(16) NOT NULL DEFAULT 'DISCOVER',   -- READONLY/DISCOVER/MUTATE
    target_snapshot JSONB DEFAULT '{}'::jsonb,
    llm_model       VARCHAR(64) NOT NULL DEFAULT 'MG-DEEPSEEK-DEFAULT',
    status          VARCHAR(16) NOT NULL DEFAULT 'PENDING',    -- 见 15.3 字典
    progress_pct    INTEGER NOT NULL DEFAULT 0,
    total_routes    INTEGER NOT NULL DEFAULT 0,
    total_modules   INTEGER NOT NULL DEFAULT 0,
    case_count      INTEGER NOT NULL DEFAULT 0,
    dataset_count   INTEGER NOT NULL DEFAULT 0,
    scenario_count  INTEGER NOT NULL DEFAULT 0,
    preview_payload JSONB DEFAULT '{}'::jsonb,
    error_message   TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    duration_ms     INTEGER,
    created_by      INTEGER,
    tenant_id       INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_dj_project ON discover_jobs(project_id) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_dj_status  ON discover_jobs(status) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_dj_tenant  ON discover_jobs(tenant_id) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_dj_time    ON discover_jobs(started_at DESC) WHERE deleted_at IS NULL;



-- 15.2 每条被探路由明细（预览 / VALIDATE 依据）
CREATE TABLE IF NOT EXISTS discover_job_routes (
    id          BIGSERIAL PRIMARY KEY,
    job_id      INTEGER NOT NULL,
    method      VARCHAR(8) NOT NULL,
    path        VARCHAR(500) NOT NULL,
    full_url    VARCHAR(1000),
    module      VARCHAR(128),
    summary     VARCHAR(500),
    swagger_tag VARCHAR(128),
    from_swagger BOOLEAN NOT NULL DEFAULT FALSE,
    response_sample JSONB DEFAULT '{}'::jsonb,
    action_code VARCHAR(16),                                   -- READ/CREATE/UPDATE/DELETE/OTHER
    tenant_id   INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_djr_job ON discover_job_routes(job_id);

CREATE INDEX IF NOT EXISTS idx_djr_mod ON discover_job_routes(module);

CREATE UNIQUE INDEX IF NOT EXISTS uq_djr_job_method_path ON discover_job_routes(job_id, method, path);


-- 兼容老版本：确保 updated_at / deleted_at 存在
ALTER TABLE discover_job_routes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE discover_job_routes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

SELECT 'inti.sql section 15 discover synced' AS done;



-- ============================================================================
-- 16. 系统管理：菜单树 + 系统参数（2026-10-03 新增）
-- ============================================================================

-- 16.1 menus（树形菜单，权限驱动）
CREATE TABLE IF NOT EXISTS menus (
    id           BIGSERIAL PRIMARY KEY,
    parent_id    INTEGER,
    path         VARCHAR(128) NOT NULL,
    component    VARCHAR(256),
    icon         VARCHAR(64),
    title        VARCHAR(64) NOT NULL,
    perm         VARCHAR(64),
    sort_order   INTEGER NOT NULL DEFAULT 0,
    visible      BOOLEAN NOT NULL DEFAULT true,
    menu_type    VARCHAR(16) NOT NULL DEFAULT 'menu',   -- dir / menu / button
    remark       VARCHAR(256),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_menus_parent ON menus(parent_id);

CREATE INDEX IF NOT EXISTS idx_menus_perm   ON menus(perm);

CREATE INDEX IF NOT EXISTS idx_menus_path   ON menus(path) WHERE deleted_at IS NULL;



-- 16.2 role_menus（角色-菜单绑定，多对多）
-- BUG-012 修复：建表必须先于下方去重 UPDATE/DELETE（引用 role_menus），
-- 否则空库首跑直接 UndefinedTable，违反"空库可直接执行"头注承诺。
CREATE TABLE IF NOT EXISTS role_menus (
    id         BIGSERIAL PRIMARY KEY,
    role_id    INTEGER NOT NULL,
    menu_id    INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (role_id, menu_id)
);

CREATE INDEX IF NOT EXISTS idx_role_menus_role ON role_menus(role_id);

CREATE INDEX IF NOT EXISTS idx_role_menus_menu ON role_menus(menu_id);



-- BUG（菜单可见性重复项）修复：先清历史重复（同 path 仅保留最早一条，绑定迁移后删除），
-- 再建 path 部分唯一索引，使 §16.4 种子 ON CONFLICT 真正生效，杜绝重复执行逐轮累加。
UPDATE role_menus rm SET menu_id = k.keep_id
FROM (
    SELECT m.id AS old_id,
           (SELECT min(m2.id) FROM menus m2 WHERE m2.path = m.path AND m2.deleted_at IS NULL) AS keep_id
    FROM menus m WHERE m.deleted_at IS NULL
) k
WHERE rm.menu_id = k.old_id AND k.old_id <> k.keep_id
  AND NOT EXISTS (SELECT 1 FROM role_menus r2 WHERE r2.role_id = rm.role_id AND r2.menu_id = k.keep_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_menus_path_alive ON menus(path) WHERE deleted_at IS NULL;



-- 16.3 system_settings（系统参数按 group+key 唯一）
CREATE TABLE IF NOT EXISTS system_settings (
    id             BIGSERIAL PRIMARY KEY,
    setting_group  VARCHAR(32) NOT NULL,
    setting_key    VARCHAR(64) NOT NULL,
    setting_value  TEXT,
    value_type     VARCHAR(16) NOT NULL DEFAULT 'string',   -- string / integer / boolean / json
    description    VARCHAR(256),
    is_secret      BOOLEAN NOT NULL DEFAULT false,
    updated_by     INTEGER,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (setting_group, setting_key)
);

SELECT 'inti.sql section 16 menus+settings synced' AS done;





-- ============================================================================
-- 25. AI 测试优化（2026-10-04）：缺陷专业化 + 评测集关联 + 场景来源标识
--     全部幂等；无外键；中文无乱码（UTF8 + C collation）
-- ============================================================================

-- 25.1 缺陷专业化字段（Jira/禅道最小集；evidence 沿用存日志，attachments 存附件/截图元数据）
ALTER TABLE defects ADD COLUMN IF NOT EXISTS priority          VARCHAR(16)  NOT NULL DEFAULT 'MEDIUM';

ALTER TABLE defects ADD COLUMN IF NOT EXISTS module            VARCHAR(128);

ALTER TABLE defects ADD COLUMN IF NOT EXISTS reproduce_steps   JSONB         DEFAULT '[]'::jsonb;

ALTER TABLE defects ADD COLUMN IF NOT EXISTS assignee_id       INTEGER;

ALTER TABLE defects ADD COLUMN IF NOT EXISTS assignee_name     VARCHAR(64);

ALTER TABLE defects ADD COLUMN IF NOT EXISTS attachments       JSONB         DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_defects_priority ON defects (priority) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_defects_module   ON defects (module)   WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_defects_assignee ON defects (assignee_id) WHERE deleted_at IS NULL;



-- 25.2 评测集关联列（AI 生成评测集 → 用例/数据集埋点，供覆盖矩阵聚合）
ALTER TABLE eval_sets ADD COLUMN IF NOT EXISTS module         VARCHAR(128);

ALTER TABLE eval_sets ADD COLUMN IF NOT EXISTS rel_case_ids   JSONB DEFAULT '[]'::jsonb;

ALTER TABLE eval_sets ADD COLUMN IF NOT EXISTS rel_dataset_ids JSONB DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_eval_sets_module ON eval_sets (module) WHERE deleted_at IS NULL;



-- 25.3 场景来源标识（AI 生成场景 source 补齐，用于确认入库与引擎动态化）
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'MANUAL';



-- 25.4 场景所属模块（参与覆盖矩阵 covered 判定）
ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS module VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_scenarios_module ON scenarios (module) WHERE deleted_at IS NULL;

SELECT 'inti.sql section 25 AI-test-optimize DDL synced' AS done;



-- ============================================================================
-- 26. AI 自测化测试 v2.0：全维度测试扩展（《AI自测化测试详细开发.md》v2.0 第 8 章）
--     新增字段支持 UI/性能/安全/兼容性测试；新增数据字典支持全维度分类
-- ============================================================================

-- 26.1 test_cases 表新增字段（支持 UI/性能/安全/兼容性测试）
ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS performance_config JSONB;

COMMENT ON COLUMN test_cases.performance_config IS '性能测试配置：{concurrency: [10,50,100], duration: 60, ramp_up: 10, target_rt_p95: 500, target_rt_p99: 1000, target_tps: 100}';

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS owasp_id VARCHAR(32);

COMMENT ON COLUMN test_cases.owasp_id IS 'OWASP Top 10 编号（安全测试用例），如 A03:2021';

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS dom_selector VARCHAR(500);

COMMENT ON COLUMN test_cases.dom_selector IS 'DOM 选择器（UI 测试用例），如 #name / .ant-pagination-next';

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS viewport_config JSONB;

COMMENT ON COLUMN test_cases.viewport_config IS '视口配置：{width: 1920, height: 1080}（兼容性测试）';

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS browser_config VARCHAR(32);

COMMENT ON COLUMN test_cases.browser_config IS '浏览器配置：chromium/firefox/webkit（兼容性测试）';

ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS review_status VARCHAR(16);

COMMENT ON COLUMN test_cases.review_status IS '人工评审状态：PENDING/IN_REVIEW/DONE（OWASP 非自动化项闭环跟踪）';

SELECT 'inti.sql section 26 full-dimension testing DDL synced' AS done;



-- 27. RTM-4.0 PERF-09：reports 表新增性能指标列（rt_p50/rt_p95/rt_p99/tps/error_rate）
ALTER TABLE reports ADD COLUMN IF NOT EXISTS performance_metrics JSONB NULL;

COMMENT ON COLUMN reports.performance_metrics IS '性能指标（rt_p50/rt_p95/rt_p99/tps/error_rate，PERF 引擎汇总）';

SELECT 'inti.sql section 27 reports.performance_metrics synced' AS done;



-- ============================================================================
-- 28. 6 个 AI 引擎真实化改进（《6个引擎改进详细设计.md》v1.0 第 7 章，2026-10-08）
--     新增被测系统门面表 target_registry；eval_runs/model_configs/eval_sets 扩展列；
--     MULTI_TURN 类别数据迁移；模型配置与评测集种子数据。
--     全部幂等；无外键；中文无乱码（UTF8）
-- ============================================================================

-- 28.1 被测系统门面表（根治「自问自答自评」：被评对象与评判模型彻底分离）
CREATE TABLE IF NOT EXISTS target_registry (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) NOT NULL,                          -- 被测对象编号 TG-xxx
    name VARCHAR(128) NOT NULL,                         -- 名称（如「客服机器人生产端点」）
    target_type VARCHAR(16) NOT NULL,                   -- LLM_API / APP_API / INTERNAL_MODEL
    base_url VARCHAR(512) NOT NULL,                     -- 服务地址
    chat_path VARCHAR(256) NULL DEFAULT '/chat/completions', -- LLM_API 对话路径
    protocol VARCHAR(16) NOT NULL DEFAULT 'OPENAI',     -- OPENAI / CUSTOM
    auth_env VARCHAR(64) NULL,                          -- 密钥环境变量名（密钥不落库）
    headers JSONB NULL,                                  -- 附加请求头
    request_template JSONB NULL,                         -- CUSTOM 协议请求体模板（{{prompt}}/{{history_json}}）
    response_path VARCHAR(128) NULL,                    -- 响应取值点路径，如 choices.0.message.content
    model VARCHAR(128) NULL,                            -- LLM_API 被测模型名（OpenAI 协议 body.model）
    timeout_sec INTEGER NOT NULL DEFAULT 30,
    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    remark VARCHAR(512) NULL,
    tenant_id INTEGER NOT NULL,
    created_by INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_target_registry_code ON target_registry (code) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS ix_target_registry_tenant_id ON target_registry (tenant_id);

CREATE INDEX IF NOT EXISTS ix_target_registry_status ON target_registry (status) WHERE deleted_at IS NULL;

COMMENT ON TABLE target_registry IS '被测系统注册表：AI 引擎的统一被测门面（与 model_configs 的评判模型分离）';

COMMENT ON COLUMN target_registry.target_type IS 'LLM_API=OpenAI兼容对话端点；APP_API=自定义协议AI应用；INTERNAL_MODEL=平台内置模型（仅演示，非真实被测系统）';



-- 28.2 eval_runs 扩展列（回填引擎明细、数据集版本快照、可复现快照、成本）
ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS engine_code    VARCHAR(64) NULL;

ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS dataset_version VARCHAR(32) NULL;

ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS run_snapshot   JSONB NULL;

ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS estimated_cost DOUBLE PRECISION NULL;

ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS actual_cost    DOUBLE PRECISION NULL;

CREATE INDEX IF NOT EXISTS ix_eval_runs_engine_code ON eval_runs (engine_code);

COMMENT ON COLUMN eval_runs.engine_code IS '来源引擎编码（REDTEAM_TEST/HALLUCINATION_TEST/...），前端报告渲染器分发依据';

COMMENT ON COLUMN eval_runs.run_snapshot IS '可复现快照：{judge_model,target_mode,dataset_version,temperature,seed,engine_version}';

COMMENT ON COLUMN eval_runs.estimated_cost IS '执行前预估 LLM 成本（元），基于 model_configs 单价';

COMMENT ON COLUMN eval_runs.actual_cost IS '执行后实际成本（元），汇总 model_gateway_records.total_cost';



-- 28.3 model_configs.seed（固定采样种子，判定可复现）/ eval_sets.version（数据集版本化）
ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS seed INTEGER NULL;

COMMENT ON COLUMN model_configs.seed IS '采样种子；判定模型建议固定（如 42）保证评测可复现';

ALTER TABLE eval_sets ADD COLUMN IF NOT EXISTS version VARCHAR(32) NOT NULL DEFAULT 'v1';

COMMENT ON COLUMN eval_sets.version IS '数据集版本号；items 变更时自动递增并写入 meta.version_history';



-- 28.10 被测对象扩展：model 列（LLM_API 探测/应答需真实模型名，Ollama 对 model=default 返回 404）
ALTER TABLE target_registry ADD COLUMN IF NOT EXISTS model VARCHAR(128) NULL;

COMMENT ON COLUMN target_registry.model IS 'LLM_API 被测模型名（OpenAI 协议请求体 model 字段）；留空则不发送';

SELECT 'inti.sql section 28 engine-realization DDL + seed synced' AS done;



-- ============================================================================
-- 29. 自测测试 v2.0：报告中心专业化改造（2026-10-09）
--     对应开发文档：《自测测试v2.0详细开发方案.md》第 1 章
--     全部幂等；无外键；中文无乱码（UTF8）
-- ============================================================================

-- 29.1 reports 表新增：环境指纹 + 风险等级（BUG-002/012）
ALTER TABLE reports ADD COLUMN IF NOT EXISTS environment JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN reports.environment IS '环境指纹：{sut_version, sut_branch, sut_commit, sut_url, os, browser, browser_version, viewport, dependencies, started_at, finished_at, duration_sec}';

ALTER TABLE reports ADD COLUMN IF NOT EXISTS risk_level VARCHAR(16) NOT NULL DEFAULT 'none';

COMMENT ON COLUMN reports.risk_level IS '风险等级：critical/high/medium/low/none';

ALTER TABLE reports ADD COLUMN IF NOT EXISTS risk_basis VARCHAR(512) NOT NULL DEFAULT '';

COMMENT ON COLUMN reports.risk_basis IS '风险等级判定依据（面向用户展示）';

CREATE INDEX IF NOT EXISTS idx_reports_risk_level ON reports(risk_level) WHERE deleted_at IS NULL;



-- 29.2 defects 表新增：修复建议 / 定级依据 / 关联需求号（BUG-007）
ALTER TABLE defects ADD COLUMN IF NOT EXISTS fix_suggestion TEXT;

COMMENT ON COLUMN defects.fix_suggestion IS '修复建议（AI 辅助生成 + 人工补充）';

ALTER TABLE defects ADD COLUMN IF NOT EXISTS severity_basis VARCHAR(512);

COMMENT ON COLUMN defects.severity_basis IS '定级依据（关联的判定规则或证据描述）';

ALTER TABLE defects ADD COLUMN IF NOT EXISTS requirement_id VARCHAR(64);

COMMENT ON COLUMN defects.requirement_id IS '关联需求号';

SELECT 'inti.sql section 29 report-center-v2 DDL synced' AS done;



-- ===========================================================================
-- 30. 6大引擎改进v2.0（对应《6大引擎改进v2.0详细开发方案.md》）
--     P1 任务状态语义 / P2 评测集扩充 / P3 演示模式 / P5 多轮剧本集
--     全部幂等；无外键；UTF8
-- ===========================================================================

-- 30.1 P1：test_tasks 扩 status 列宽（COMPLETED_WITH_RISK 19字符 > 16）
ALTER TABLE test_tasks ALTER COLUMN status TYPE VARCHAR(32);



-- 30.2 P1：test_tasks 新增 conclusion 字段（业务结论，非错误信息）
ALTER TABLE test_tasks ADD COLUMN IF NOT EXISTS conclusion TEXT;

COMMENT ON COLUMN test_tasks.conclusion IS 'v2.0 P1：业务结论（质量未达标原因/风险提示），用于前端展示';



-- 30.3 P1：存量数据迁移——AI引擎"质量未达标"任务由 FAILED 改为 COMPLETED_WITH_RISK
--     判定依据：summary.step_results 中存在 status=FAILED 且带 pass_rate/threshold 的AI引擎步骤
UPDATE test_tasks t
SET status = 'COMPLETED_WITH_RISK',
    conclusion = COALESCE(
        (SELECT sr->>'conclusion' FROM jsonb_array_elements(t.summary::jsonb->'step_results') sr
         WHERE sr->>'status' = 'FAILED' AND sr->>'conclusion' IS NOT NULL AND sr->>'conclusion' <> '' LIMIT 1),
        '质量未达标（历史数据迁移）'),
    error_msg = NULL
WHERE t.status = 'FAILED'
  AND t.summary IS NOT NULL
  AND jsonb_typeof(t.summary::jsonb->'step_results') = 'array'
  AND EXISTS (
    SELECT 1 FROM jsonb_array_elements(t.summary::jsonb->'step_results') sr
    WHERE sr->>'status' = 'FAILED'
      AND (sr->'summary' ? 'pass_rate')
  )
  AND NOT EXISTS (
    SELECT 1 FROM jsonb_array_elements(t.summary::jsonb->'step_results') sr
    WHERE sr->>'status' = 'FAILED' AND sr->'summary' ? 'exception'
  );

SELECT 'inti.sql section 30 engine-v2.0 DDL+seed synced' AS done;



-- =====================================================================
-- 31. v2.0 遗留项3：历史报告回填 demo_mode / target_mode（幂等）
--     规则：来源任务 config.target_code 为空 → INTERNAL_DEMO，否则 API
-- =====================================================================
UPDATE reports r
SET content = jsonb_set(
        jsonb_set(r.content, '{demo_mode}', to_jsonb(t.demo)),
        '{step_details}',
        COALESCE((
            SELECT jsonb_agg(
                       CASE WHEN s ? 'target_mode' THEN s
                            ELSE s || jsonb_build_object('target_mode',
                                   CASE WHEN t.demo THEN 'INTERNAL_DEMO' ELSE 'API' END)
                       END ORDER BY ord)
            FROM jsonb_array_elements(r.content -> 'step_details') WITH ORDINALITY AS e(s, ord)
        ), r.content -> 'step_details')
    )
FROM (
    SELECT tk.id, (COALESCE(tk.config ->> 'target_code', '') = '') AS demo
    FROM test_tasks tk
) t
WHERE r.task_id = t.id
  AND r.deleted_at IS NULL
  AND r.content IS NOT NULL
  AND jsonb_typeof(r.content -> 'step_details') = 'array'
  AND (r.content ->> 'demo_mode') IS NULL;

SELECT 'inti.sql section 31 report demo_mode backfill synced' AS done;





-- ============================================================================--
-- 32. 引擎管理 + JSONB 类型统一（2026-10-12）
--     32.1 models.py 声明 JSONB 但存量库仍为 json 的 51 列统一转 JSONB（幂等：
--          仅当当前类型仍为 json 时才 ALTER，重复执行安全）
--     32.2 test_engines 19 引擎种子（来源 backend/app/engines/registry 真实元数据，
--          引擎开关功能依赖落库记录；ON CONFLICT 只补元数据，不覆盖 status 开关状态）
--     全部幂等；无外键；中文无乱码（UTF8）
-- ============================================================================--

-- 32.1 json -> jsonb 列类型统一（53 列，合并为单个批量检测块）
DO $$
-- 合并版 32.1：单次 pg_attribute 扫描批量检测并迁移 json -> jsonb（53 列）。
-- 全新库所有列已为 JSONB，循环体不执行，幂等且近乎零开销；
-- 存量库仅对仍为 json 类型的列执行 ALTER，与原 51 个 information_schema DO 块语义一致。
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT t.tbl, t.col
      FROM (VALUES
        ('api_keys','scopes'),
        ('audit_logs','request_body'),
        ('billing_plans','features'),
        ('compliance_clauses','detection_methods'),
        ('conversation_traces','trace'),
        ('data_quality_expectations','suite_json'),
        ('data_quality_runs','result_json'),
        ('data_quality_runs','summary'),
        ('dict_items','ext'),
        ('engine_case_libraries','tags'),
        ('engine_cases','expected_json'),
        ('engine_cases','input_json'),
        ('engine_cases','raw_payload'),
        ('engine_cases','validation_info'),
        ('ethic_audit_records','scores_json'),
        ('ethic_audit_records','violations'),
        ('ethic_regulations','clauses'),
        ('eval_runs','item_results'),
        ('eval_runs','run_snapshot'),
        ('eval_runs','summary'),
        ('eval_sets','items'),
        ('eval_sets','meta'),
        ('hallucination_embeddings','prompt_embedding'),
        ('hallucination_embeddings','ref_embedding'),
        ('heal_records','fix_detail'),
        ('heal_records','impact'),
        ('heal_records','report'),
        ('llm_cache_entries','normalized_msgs'),
        ('llm_cache_semantics','embedding_json'),
        ('model_configs','headers'),
        ('ragas_metric_records','judge_rationale'),
        ('report_compliance_alignments','evidence'),
        ('reports','content'),
        ('reports','summary'),
        ('sandbox_executions','artifacts'),
        ('sandbox_executions','result_payload'),
        ('scenarios','data_sources'),
        ('scenarios','steps'),
        ('scenarios','variables'),
        ('target_registry','headers'),
        ('target_registry','request_template'),
        ('task_steps','config'),
        ('task_steps','report_ids'),
        ('task_steps','result_summary'),
        ('test_cases','request_spec'),
        ('test_cases','steps'),
        ('test_cases','tags'),
        ('test_datasets','case_ids'),
        ('test_datasets','meta'),
        ('test_engines','supports_params'),
        ('test_tasks','config'),
        ('test_tasks','engines'),
        ('test_tasks','summary')
      ) AS t(tbl, col)
      JOIN pg_class c ON c.relname = t.tbl
      JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
      JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = t.col
     WHERE a.atttypid = 'json'::regtype
  LOOP
    EXECUTE format(
      'ALTER TABLE public.%I ALTER COLUMN %I TYPE JSONB USING %I::JSONB',
      r.tbl, r.col, r.col);
  END LOOP;
END $$;

SELECT 'inti.sql section 32.1 jsonb column unification synced' AS done;

SELECT 'inti.sql section 32.2 test_engines seed synced' AS done;

SELECT 'inti.sql section 32.3 security engines seed synced (5 new)' AS done;

SELECT 'inti.sql section 32.4 security engines seed synced (2 new)' AS done;




-- ============================================================================
-- 33. P0 功能：越狱检测引擎（JAILBREAK）
-- ============================================================================

-- 33.1 越狱样本库表
CREATE TABLE IF NOT EXISTS jailbreak_samples (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER NOT NULL DEFAULT 1,
    category VARCHAR(64) NOT NULL,
    attack_vector VARCHAR(128) NOT NULL,
    prompt_template TEXT NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'HIGH',
    source VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_jailbreak_samples_tenant_vector ON jailbreak_samples(tenant_id, attack_vector) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS idx_jailbreak_samples_tenant ON jailbreak_samples(tenant_id);

CREATE INDEX IF NOT EXISTS idx_jailbreak_samples_category ON jailbreak_samples(category);

 -- BUG-008: 匹配 partial 唯一索引
SELECT 'inti.sql section 33 jailbreak engine DONE' AS done;



-- ============================================================================
-- 34. P0 功能：PII 泄露检测引擎（PII_LEAK）
-- ============================================================================
CREATE TABLE IF NOT EXISTS pii_rules (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER NOT NULL DEFAULT 1,
    pii_type VARCHAR(64) NOT NULL,
    rule_name VARCHAR(128) NOT NULL,
    regex_pattern TEXT NOT NULL,
    description TEXT,
    severity VARCHAR(16) NOT NULL DEFAULT 'HIGH',
    context_keywords JSONB,  -- W5：上下文佐证词（命中位置前后 30 字符窗口含任一关键词才计入；NULL/空=不校验）
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pii_rules_tenant_name ON pii_rules(tenant_id, rule_name) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS idx_pii_rules_tenant ON pii_rules(tenant_id);

CREATE INDEX IF NOT EXISTS idx_pii_rules_type ON pii_rules(pii_type);

 -- BUG-008: 匹配 partial 唯一索引
SELECT 'inti.sql section 34 pii_leak engine DONE' AS done;



-- ============================================================================
-- 35. P1 功能：中文合规风险库（法条映射）
-- ============================================================================
CREATE TABLE IF NOT EXISTS compliance_regulations (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER NOT NULL DEFAULT 1,
    regulation_name VARCHAR(256) NOT NULL,
    article_number VARCHAR(64) NOT NULL,
    article_content TEXT NOT NULL,
    violation_consequence TEXT,
    effective_date DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_compliance_reg_tenant_article ON compliance_regulations(tenant_id, regulation_name, article_number) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS idx_compliance_regulations_tenant ON compliance_regulations(tenant_id);

CREATE TABLE IF NOT EXISTS risk_to_regulation_mapping (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER NOT NULL DEFAULT 1,
    risk_category VARCHAR(64) NOT NULL,
    regulation_id INTEGER NOT NULL,
    mapping_description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_risk_mapping_tenant ON risk_to_regulation_mapping(tenant_id);

CREATE INDEX IF NOT EXISTS idx_risk_mapping_category ON risk_to_regulation_mapping(risk_category);

SELECT 'inti.sql section 35 compliance regulations DONE' AS done;



-- ============================================================================
-- 36. P1 功能：行业评估模板
-- ============================================================================
CREATE TABLE IF NOT EXISTS industry_templates (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER NOT NULL DEFAULT 1,
    industry_name VARCHAR(64) NOT NULL,
    template_name VARCHAR(128) NOT NULL,
    engine_config JSONB NOT NULL,
    sample_package_id INTEGER,
    report_template_id INTEGER,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_industry_templates_tenant_name ON industry_templates(tenant_id, template_name) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS idx_industry_templates_tenant ON industry_templates(tenant_id);

SELECT 'inti.sql section 36 industry templates DONE' AS done;



-- ============================================================================
-- 37. 产品优化2：企业版 License + 成本看板 + 模型对比（2026-10-13）
--     对应文档：《产品优化2详细开发说明书.md》§2/§3/§4/§5
--     原则：无外键、tenant_id 隔离、幂等可重复执行、UTF-8 中文无乱码
-- ============================================================================

-- 37.1 enterprise_licenses：企业版 License 台账（仅存验签通过后的结构化字段，签名串不落库）
CREATE TABLE IF NOT EXISTS enterprise_licenses (
    id              BIGSERIAL PRIMARY KEY,
    license_no      VARCHAR(64) NOT NULL,                      -- 许可证号（uuid hex）
    payload_json    JSONB NOT NULL DEFAULT '{}'::jsonb,        -- 验签通过后的 payload（customer/features/issued_at 等）
    edition         VARCHAR(16) NOT NULL DEFAULT 'enterprise', -- community/saas/enterprise
    features        JSONB NOT NULL DEFAULT '[]'::jsonb,        -- 功能位 ["multi_tenant","sso",...]
    machine_fp      VARCHAR(64),                               -- 绑定机器指纹（空=不绑定）
    status          VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',     -- ACTIVE/EXPIRED/REVOKED
    tenant_id       INTEGER NOT NULL DEFAULT 1,
    created_by      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_enterprise_licenses_no ON enterprise_licenses(license_no);

CREATE INDEX IF NOT EXISTS idx_el_tenant ON enterprise_licenses(tenant_id) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_el_status ON enterprise_licenses(status) WHERE deleted_at IS NULL;

COMMENT ON TABLE enterprise_licenses IS '企业版 License 台账：前端 License 管理页数据来源；仅存验签通过后的结构化字段（不含签名串），到期时间取 payload_json->expires_at';



-- 37.2 license_activations：激活/吊销事件审计（无外键逻辑引用 enterprise_licenses）
CREATE TABLE IF NOT EXISTS license_activations (
    id           BIGSERIAL PRIMARY KEY,
    license_no   VARCHAR(64) NOT NULL,
    action       VARCHAR(16) NOT NULL,          -- ACTIVATE/REVOKE/EXPIRE_CHECK
    result       VARCHAR(16) NOT NULL,          -- SUCCESS/FAILED
    fail_reason  VARCHAR(200),
    operator     VARCHAR(64),
    machine_fp   VARCHAR(64),
    tenant_id    INTEGER NOT NULL DEFAULT 1,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_la_no   ON license_activations(license_no);

CREATE INDEX IF NOT EXISTS idx_la_time ON license_activations(created_at DESC);

COMMENT ON TABLE license_activations IS 'License 激活/吊销事件审计：前端 LicenseHistory 页数据来源';



-- 37.3 v_cost_summary_by_model：成本看板按模型聚合视图（FAILED 调用不计入）
CREATE OR REPLACE VIEW v_cost_summary_by_model AS
SELECT
    model,
    MAX(model_code) AS model_code,
    SUM(total_tokens)                                   AS total_tokens,
    ROUND(SUM(total_cost)::numeric, 4)                  AS total_cost,
    COUNT(*)                                            AS call_count,
    ROUND(AVG(latency_ms)::numeric, 1)                  AS avg_latency_ms,
    ROUND(AVG(cache_hit::int) * 100, 2)                 AS cache_hit_rate,
    SUM(prompt_tokens)                                  AS prompt_tokens,
    SUM(completion_tokens)                              AS completion_tokens
FROM model_gateway_records
WHERE status = 'SUCCESS'
GROUP BY model;

COMMENT ON VIEW v_cost_summary_by_model IS '成本看板：按模型聚合成本汇总（前端 CostDashboard 数据来源）；仅统计 SUCCESS 调用';



-- 37.4 v_cost_trend_daily：成本趋势按天视图
CREATE OR REPLACE VIEW v_cost_trend_daily AS
SELECT
    created_at::date AS date,
    ROUND(SUM(total_cost)::numeric, 4) AS total_cost,
    COUNT(*) AS call_count
FROM model_gateway_records
WHERE status = 'SUCCESS'
GROUP BY created_at::date
ORDER BY created_at::date;

COMMENT ON VIEW v_cost_trend_daily IS '成本看板：按天成本趋势（前端 CostTrendChart 数据来源）';



-- 37.5 v_model_compare：模型横向对比视图（join eval_runs 汇总通过率 + 网关成本）
CREATE OR REPLACE VIEW v_model_compare AS
SELECT
    mc.code                          AS model_code,
    mc.name                          AS model_name,
    mc.provider,
    mc.input_price_per_mtok          AS input_price,
    mc.output_price_per_mtok         AS output_price,
    COALESCE(pr.pass_rate, 0)        AS pass_rate,
    COALESCE(pr.avg_score, 0)        AS avg_score,
    COALESCE(c.total_cost, 0)        AS total_cost,
    COALESCE(c.avg_latency_ms, 0)    AS avg_latency_ms,
    COALESCE(c.call_count, 0)        AS call_count,
    COALESCE(c.cache_hit_rate, 0)    AS cache_hit_rate
FROM model_configs mc
LEFT JOIN LATERAL (
    -- pass_rate 实际存于 summary->task_summary->>pass_rate（兼容顶层旧格式）
    -- judge_model 历史数据为 model_configs.code，兼容存模型名的情况
    SELECT ROUND(AVG(COALESCE(
               NULLIF(er.summary::jsonb->'task_summary'->>'pass_rate', ''),
               er.summary::jsonb->>'pass_rate')::numeric), 2) AS pass_rate,
           ROUND(AVG(COALESCE(
               NULLIF(er.summary::jsonb->'task_summary'->>'overall_score', ''),
               er.summary::jsonb->>'avg_score')::numeric), 2) AS avg_score
    FROM eval_runs er
    WHERE er.judge_model IN (mc.code, mc.model)
      AND er.summary IS NOT NULL
      AND er.deleted_at IS NULL
      AND er.created_at >= now() - INTERVAL '90 days'
) pr ON TRUE
LEFT JOIN LATERAL (
    SELECT SUM(total_cost) AS total_cost,
           AVG(latency_ms) AS avg_latency_ms,
           COUNT(*) AS call_count,
           AVG(cache_hit::int) * 100 AS cache_hit_rate
    FROM model_gateway_records mgr
    WHERE mgr.model_code = mc.code AND mgr.status = 'SUCCESS'
) c ON TRUE
WHERE mc.status = 'ACTIVE' AND mc.deleted_at IS NULL AND mc.usage = 'CHAT';

COMMENT ON VIEW v_model_compare IS '模型对比：横向对比各模型通过率/得分/成本/延迟（内部全局报表用途）；租户侧请改用 v_model_compare_by_tenant';



-- 37.6 租户隔离视图（产品优化3）：路由层统一改读 *_by_tenant 视图 + WHERE tenant_id 过滤，
--      全局视图（37.3-37.5）仅保留给内部报表/BI 直连使用。
CREATE OR REPLACE VIEW v_cost_summary_by_tenant AS
SELECT
    tenant_id,
    model,
    MAX(model_code) AS model_code,
    SUM(total_tokens)                                   AS total_tokens,
    ROUND(SUM(total_cost)::numeric, 4)                  AS total_cost,
    COUNT(*)                                            AS call_count,
    ROUND(AVG(latency_ms)::numeric, 1)                  AS avg_latency_ms,
    ROUND(AVG(cache_hit::int) * 100, 2)                 AS cache_hit_rate,
    SUM(prompt_tokens)                                  AS prompt_tokens,
    SUM(completion_tokens)                              AS completion_tokens
FROM model_gateway_records
WHERE status = 'SUCCESS'
GROUP BY tenant_id, model;

COMMENT ON VIEW v_cost_summary_by_tenant IS '成本看板（租户口径）：按 tenant_id+model 聚合，仅 SUCCESS 调用；前端 CostDashboard 数据来源';

CREATE OR REPLACE VIEW v_cost_trend_daily_by_tenant AS
SELECT
    tenant_id,
    created_at::date AS date,
    ROUND(SUM(total_cost)::numeric, 4) AS total_cost,
    COUNT(*) AS call_count
FROM model_gateway_records
WHERE status = 'SUCCESS'
GROUP BY tenant_id, created_at::date;

COMMENT ON VIEW v_cost_trend_daily_by_tenant IS '成本趋势（租户口径）：按 tenant_id+天聚合，前端 CostTrendChart 数据来源';

CREATE OR REPLACE VIEW v_model_compare_by_tenant AS
SELECT
    kt.tenant_id,
    mc.code                          AS model_code,
    mc.name                          AS model_name,
    mc.provider,
    mc.input_price_per_mtok          AS input_price,
    mc.output_price_per_mtok         AS output_price,
    COALESCE(pr.pass_rate, 0)        AS pass_rate,
    COALESCE(pr.avg_score, 0)        AS avg_score,
    COALESCE(c.total_cost, 0)        AS total_cost,
    COALESCE(c.avg_latency_ms, 0)    AS avg_latency_ms,
    COALESCE(c.call_count, 0)        AS call_count,
    COALESCE(c.cache_hit_rate, 0)    AS cache_hit_rate
FROM model_configs mc
CROSS JOIN (
    SELECT DISTINCT tenant_id FROM eval_runs WHERE deleted_at IS NULL
    UNION
    SELECT DISTINCT tenant_id FROM model_gateway_records WHERE status = 'SUCCESS'
) kt
LEFT JOIN LATERAL (
    SELECT ROUND(AVG(COALESCE(
               NULLIF(er.summary::jsonb->'task_summary'->>'pass_rate', ''),
               er.summary::jsonb->>'pass_rate')::numeric), 2) AS pass_rate,
           ROUND(AVG(COALESCE(
               NULLIF(er.summary::jsonb->'task_summary'->>'overall_score', ''),
               er.summary::jsonb->>'avg_score')::numeric), 2) AS avg_score
    FROM eval_runs er
    WHERE er.judge_model IN (mc.code, mc.model)
      AND er.summary IS NOT NULL
      AND er.deleted_at IS NULL
      AND er.tenant_id = kt.tenant_id
      AND er.created_at >= now() - INTERVAL '90 days'
) pr ON TRUE
LEFT JOIN LATERAL (
    SELECT SUM(total_cost) AS total_cost,
           AVG(latency_ms) AS avg_latency_ms,
           COUNT(*) AS call_count,
           AVG(cache_hit::int) * 100 AS cache_hit_rate
    FROM model_gateway_records mgr
    WHERE mgr.model_code = mc.code
      AND mgr.status = 'SUCCESS'
      AND mgr.tenant_id = kt.tenant_id
) c ON TRUE
WHERE mc.status = 'ACTIVE' AND mc.deleted_at IS NULL AND mc.usage = 'CHAT';

COMMENT ON VIEW v_model_compare_by_tenant IS '模型对比（租户口径）：按 tenant_id 隔离通过率/成本/延迟，前端 ModelCompare 数据来源；仅 CHAT 用途且 ACTIVE';

SELECT 'inti.sql section 37 product-optimization2 DDL+views DONE' AS done;



-- ===========================================================================
-- 38. SRC 源代码安全审计全链路表（产品优化3 U3）
--     与 backend/app/models.py 严格同步：SrcScanTask / SrcRule / SrcFinding /
--     ScaComponent / ScaVulnerability。无外键（逻辑引用）、tenant_id 隔离、
--     created_by / created_at / updated_at / deleted_at 软删审计字段、JSONB。
--     主键采用显式序列（与 SERIAL 完全等价：integer + nextval 默认 + PRIMARY KEY），
--     便于与 ORM 声明的 Integer 类型做静态核对；unique=True 列以
--     ix_<table>_<col> 命名的 UNIQUE INDEX 落地（对齐 naming_convention）。
-- ===========================================================================

-- 38.1 src_scan_tasks：SRC 扫描任务（代码接入 + 扫描状态机）
CREATE SEQUENCE IF NOT EXISTS src_scan_tasks_id_seq;

CREATE TABLE IF NOT EXISTS src_scan_tasks (
    id             INTEGER      NOT NULL DEFAULT nextval('src_scan_tasks_id_seq'),
    task_no        VARCHAR(64)  NOT NULL,                 -- 业务编号 SRC-YYYYMMDD...
    tenant_id      INTEGER      NOT NULL DEFAULT 1,
    created_by     INTEGER      NOT NULL DEFAULT 1,
    project_id     INTEGER,                               -- 关联项目 ID（逻辑引用）
    name           VARCHAR(256) NOT NULL,                 -- 任务名称（中文）
    source_type    VARCHAR(16)  NOT NULL DEFAULT 'upload',-- upload/git
    source_url     VARCHAR(1000),                         -- ZIP 存储名或 git 地址
    workdir        VARCHAR(1000),                         -- 解压后源码根目录
    commit_hash    VARCHAR(64),
    branch         VARCHAR(128),
    language_stats JSONB        NOT NULL DEFAULT '{}'::jsonb, -- {"python": 文件数, ...}
    total_files    INTEGER      NOT NULL DEFAULT 0,
    total_lines    INTEGER      NOT NULL DEFAULT 0,
    status         VARCHAR(16)  NOT NULL DEFAULT 'PENDING',   -- PENDING/SCANNING/COMPLETED/FAILED
    error_message  TEXT,
    summary        JSONB        NOT NULL DEFAULT '{}'::jsonb, -- 发现项严重度汇总
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at     TIMESTAMPTZ,
    PRIMARY KEY (id)
);

ALTER SEQUENCE src_scan_tasks_id_seq OWNED BY src_scan_tasks.id;

CREATE UNIQUE INDEX IF NOT EXISTS ix_src_scan_tasks_task_no   ON src_scan_tasks(task_no);

CREATE INDEX IF NOT EXISTS ix_src_scan_tasks_tenant_id        ON src_scan_tasks(tenant_id);

CREATE INDEX IF NOT EXISTS ix_src_scan_tasks_status           ON src_scan_tasks(status);

COMMENT ON TABLE src_scan_tasks IS 'SRC 扫描任务（SAST+SCA 主状态机，models.py SrcScanTask）';



-- 38.2 src_rules：SRC 检测规则库（内置 + 自定义；正则模式 Phase 1）
CREATE SEQUENCE IF NOT EXISTS src_rules_id_seq;

CREATE TABLE IF NOT EXISTS src_rules (
    id             INTEGER      NOT NULL DEFAULT nextval('src_rules_id_seq'),
    rule_no        VARCHAR(64)  NOT NULL,                 -- 业务编号
    tenant_id      INTEGER      NOT NULL DEFAULT 1,
    created_by     INTEGER      NOT NULL DEFAULT 1,
    rule_id        VARCHAR(128) NOT NULL,                 -- 规则标识，如 CWE-89-SQLI-PY
    name           VARCHAR(256) NOT NULL,                 -- 规则名称（中文）
    description    TEXT,
    severity       VARCHAR(16)  NOT NULL DEFAULT 'HIGH',  -- CRITICAL/HIGH/MEDIUM/LOW
    language       VARCHAR(32)  NOT NULL DEFAULT '*',     -- python/java/javascript/go/*
    category       VARCHAR(64)  NOT NULL DEFAULT 'INJECTION', -- INJECTION/SECRET/CRYPTO/...
    rule_type      VARCHAR(16)  NOT NULL DEFAULT 'REGEX', -- REGEX/TAIN
    pattern        TEXT         NOT NULL,                 -- 正则表达式（TAIN 为污点源模式）
    cwe_id         VARCHAR(32),
    owasp_category VARCHAR(64),
    remediation    TEXT,                                  -- 修复建议（中文）
    enabled        BOOLEAN      NOT NULL DEFAULT TRUE,
    is_builtin     BOOLEAN      NOT NULL DEFAULT TRUE,
    version        VARCHAR(16)  NOT NULL DEFAULT '1.0',
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at     TIMESTAMPTZ,
    PRIMARY KEY (id)
);

ALTER SEQUENCE src_rules_id_seq OWNED BY src_rules.id;

CREATE UNIQUE INDEX IF NOT EXISTS ix_src_rules_rule_no    ON src_rules(rule_no) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE UNIQUE INDEX IF NOT EXISTS ix_src_rules_rule_id    ON src_rules(rule_id) WHERE deleted_at IS NULL;

 -- BUG-008
CREATE INDEX IF NOT EXISTS ix_src_rules_tenant_id         ON src_rules(tenant_id);

COMMENT ON TABLE src_rules IS 'SRC 检测规则库（models.py SrcRule，内置+自定义）';



-- 38.3 src_findings：SRC 扫描发现项（SAST 命中结果）
CREATE SEQUENCE IF NOT EXISTS src_findings_id_seq;

CREATE TABLE IF NOT EXISTS src_findings (
    id             INTEGER       NOT NULL DEFAULT nextval('src_findings_id_seq'),
    finding_no     VARCHAR(64)   NOT NULL,                -- 业务编号
    tenant_id      INTEGER       NOT NULL DEFAULT 1,
    created_by     INTEGER       NOT NULL DEFAULT 1,
    scan_task_id   INTEGER       NOT NULL,                -- 扫描任务 ID（逻辑引用）
    rule_ref       VARCHAR(128)  NOT NULL,                -- 命中规则 rule_id（逻辑引用）
    rule_name      VARCHAR(256)  NOT NULL DEFAULT '',
    file_path      VARCHAR(1000) NOT NULL,                -- 相对源码根路径
    line_start     INTEGER       NOT NULL DEFAULT 1,
    line_end       INTEGER       NOT NULL DEFAULT 1,
    severity       VARCHAR(16)   NOT NULL DEFAULT 'HIGH',
    confidence     VARCHAR(16)   NOT NULL DEFAULT 'MEDIUM', -- HIGH/MEDIUM/LOW
    message        TEXT          NOT NULL,                -- 问题描述（中文）
    code_snippet   TEXT,
    remediation    TEXT,
    cwe_id         VARCHAR(32),
    owasp_category VARCHAR(64),
    status         VARCHAR(16)   NOT NULL DEFAULT 'OPEN', -- OPEN/FIXED/FALSE_POSITIVE/SUPPRESSED
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    deleted_at     TIMESTAMPTZ,
    PRIMARY KEY (id)
);

ALTER SEQUENCE src_findings_id_seq OWNED BY src_findings.id;

CREATE UNIQUE INDEX IF NOT EXISTS ix_src_findings_finding_no  ON src_findings(finding_no);

CREATE INDEX IF NOT EXISTS ix_src_findings_tenant_id          ON src_findings(tenant_id);

CREATE INDEX IF NOT EXISTS ix_src_findings_severity           ON src_findings(severity);

CREATE INDEX IF NOT EXISTS ix_src_findings_status             ON src_findings(status);

CREATE INDEX IF NOT EXISTS idx_src_findings_task              ON src_findings(scan_task_id);

CREATE INDEX IF NOT EXISTS idx_src_findings_sev               ON src_findings(severity);

COMMENT ON TABLE src_findings IS 'SRC 扫描发现项（models.py SrcFinding，scan_task_id/rule_ref 逻辑引用）';



-- 38.4 sca_components：SCA 依赖组件清单（SBOM，requirements.txt / package.json）
CREATE SEQUENCE IF NOT EXISTS sca_components_id_seq;

CREATE TABLE IF NOT EXISTS sca_components (
    id              INTEGER       NOT NULL DEFAULT nextval('sca_components_id_seq'),
    component_no    VARCHAR(64)   NOT NULL,               -- 业务编号
    tenant_id       INTEGER       NOT NULL DEFAULT 1,
    created_by      INTEGER       NOT NULL DEFAULT 1,
    scan_task_id    INTEGER       NOT NULL,               -- 扫描任务 ID（逻辑引用）
    name            VARCHAR(256)  NOT NULL,               -- 组件名
    version         VARCHAR(64),
    ecosystem       VARCHAR(32)   NOT NULL DEFAULT 'pypi',-- pypi/npm
    license_name    VARCHAR(128),
    license_risk    VARCHAR(16),                          -- NONE/LOW/HIGH（GPL 等强 copyleft 为 HIGH）
    direct          BOOLEAN       NOT NULL DEFAULT TRUE,  -- 是否直接依赖
    dependency_path VARCHAR(1000),                        -- 依赖路径，如 requirements.txt
    cve_count       INTEGER       NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    PRIMARY KEY (id)
);

ALTER SEQUENCE sca_components_id_seq OWNED BY sca_components.id;

CREATE UNIQUE INDEX IF NOT EXISTS ix_sca_components_component_no ON sca_components(component_no);

CREATE INDEX IF NOT EXISTS ix_sca_components_tenant_id           ON sca_components(tenant_id);

CREATE INDEX IF NOT EXISTS ix_sca_components_name                ON sca_components(name);

CREATE INDEX IF NOT EXISTS idx_sca_comp_task                     ON sca_components(scan_task_id);

COMMENT ON TABLE sca_components IS 'SCA 依赖组件清单（models.py ScaComponent，SBOM）';



-- 38.5 sca_vulnerabilities：SCA 组件漏洞（CVE 本地库匹配结果）
CREATE SEQUENCE IF NOT EXISTS sca_vulnerabilities_id_seq;

CREATE TABLE IF NOT EXISTS sca_vulnerabilities (
    id                INTEGER       NOT NULL DEFAULT nextval('sca_vulnerabilities_id_seq'),
    vuln_no           VARCHAR(64)   NOT NULL,             -- 业务编号
    tenant_id         INTEGER       NOT NULL DEFAULT 1,
    created_by        INTEGER       NOT NULL DEFAULT 1,
    scan_task_id      INTEGER       NOT NULL,             -- 扫描任务 ID（逻辑引用）
    component_id      INTEGER       NOT NULL,             -- 组件 ID（逻辑引用）
    component_name    VARCHAR(256)  NOT NULL DEFAULT '',
    component_version VARCHAR(64),
    cve_id            VARCHAR(32)   NOT NULL,
    severity          VARCHAR(16)   NOT NULL DEFAULT 'HIGH',
    cvss_score        FLOAT,                                  -- 8 位浮点（PG FLOAT 即 DOUBLE PRECISION，对齐 ORM Float 编译名）
    description       TEXT,                               -- 中文描述
    fixed_version     VARCHAR(64),                        -- 修复版本（>=）
    "references"      JSONB         NOT NULL DEFAULT '[]'::jsonb, -- 参考链接列表
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    deleted_at        TIMESTAMPTZ,
    PRIMARY KEY (id)
);

ALTER SEQUENCE sca_vulnerabilities_id_seq OWNED BY sca_vulnerabilities.id;

CREATE UNIQUE INDEX IF NOT EXISTS ix_sca_vulnerabilities_vuln_no   ON sca_vulnerabilities(vuln_no);

CREATE INDEX IF NOT EXISTS ix_sca_vulnerabilities_tenant_id        ON sca_vulnerabilities(tenant_id);

CREATE INDEX IF NOT EXISTS ix_sca_vulnerabilities_cve_id           ON sca_vulnerabilities(cve_id);

CREATE INDEX IF NOT EXISTS idx_sca_vuln_task                       ON sca_vulnerabilities(scan_task_id);

COMMENT ON TABLE sca_vulnerabilities IS 'SCA 组件漏洞（models.py ScaVulnerability，CVE 本地库匹配）';

SELECT 'inti.sql section 38 SRC/SCA full-link tables DONE' AS done;



-- ============================================================================
-- 39. 产品优化3 W5：PII 上下文佐证（Presidio score boosting 最简版）+ 越狱样本增补 30 条
-- ============================================================================

-- 39.1 pii_rules 增列（幂等；新库 34 节建表已含同名列，此处兜底存量库）
ALTER TABLE pii_rules ADD COLUMN IF NOT EXISTS context_keywords JSONB;

COMMENT ON COLUMN pii_rules.context_keywords IS '上下文佐证词（正则命中位置前后 30 字符窗口内出现任一关键词才计入违规；NULL/空数组=不校验，对齐 Presidio score boosting）';

 -- BUG-008: 匹配 partial 唯一索引
SELECT 'inti.sql section 39 W5 context_keywords + jailbreak 30 samples DONE' AS done;

CREATE TABLE IF NOT EXISTS community_usage_daily (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL DEFAULT 1,
    user_id      INTEGER NOT NULL,
    kind         VARCHAR(64) NOT NULL,          -- 计数类型，如 case_gen
    usage_date   DATE NOT NULL,                 -- 服务器本地日（Asia/Shanghai）
    cnt          INTEGER NOT NULL DEFAULT 0,    -- 当日已用量
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_cud_tenant_user_kind_date
    ON community_usage_daily (tenant_id, user_id, kind, usage_date);

COMMENT ON TABLE community_usage_daily IS '社区版按日用量计数器：limits.py 日配额判定唯一数据源';

SELECT 'inti.sql section 40 community_usage_daily DONE' AS done;

SELECT 'inti.sql section 41 pwd_policy dict DONE' AS done;

CREATE TABLE IF NOT EXISTS tenants (
    id           BIGSERIAL PRIMARY KEY,
    code         VARCHAR(32)  NOT NULL UNIQUE,            -- 短码，如 acme
    name         VARCHAR(128) NOT NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE|SUSPENDED|CLOSED
    contact_email VARCHAR(256),
    note         VARCHAR(512),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_code ON tenants(code) WHERE deleted_at IS NULL;

SELECT setval(pg_get_serial_sequence('tenants','id'), (SELECT MAX(id) FROM tenants));


-- 租户操作审计复用 audit_logs，不建新表
COMMENT ON TABLE tenants IS '租户主数据（仅 saas 形态运营后台读写；enterprise/community 单租户恒为 id=1）';

SELECT 'inti.sql section 42 tenants master data DONE' AS done;

ALTER TABLE billing_quotas ADD COLUMN IF NOT EXISTS period_start TIMESTAMPTZ;

ALTER TABLE billing_quotas ADD COLUMN IF NOT EXISTS period_end   TIMESTAMPTZ;

ALTER TABLE billing_quotas ADD COLUMN IF NOT EXISTS sub_status   VARCHAR(16) NOT NULL DEFAULT 'ACTIVE';


-- sub_status 枚举：ACTIVE | GRACE | PAST_DUE | CANCELED
CREATE INDEX IF NOT EXISTS ix_bq_sub_status ON billing_quotas (sub_status);

COMMENT ON COLUMN billing_quotas.period_start IS '账期起始（月初锚定，cycle job 前滚）';

COMMENT ON COLUMN billing_quotas.period_end   IS '账期截止（now>=period_end 触发 used 清零+前滚）';

COMMENT ON COLUMN billing_quotas.sub_status   IS '订阅状态机：ACTIVE|GRACE|PAST_DUE|CANCELED（T6b）';

SELECT 'inti.sql section 43 T6b billing cycle DONE' AS done;

ALTER TABLE tenants DROP CONSTRAINT IF EXISTS tenants_code_key;

CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_code ON tenants(code) WHERE deleted_at IS NULL;

COMMENT ON INDEX ix_tenants_code IS 'ES7-T-1：code 未删除行内唯一（历史全表 UNIQUE 已降级为部分唯一）';

SELECT 'inti.sql section 44 tenants code partial-unique DONE' AS done;



-- 45.1 租户主数据扩列（订购关系权威落点）
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS owner_user_id  BIGINT;

      -- 租户管理员（system_users.id 逻辑引用）
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS org_id         BIGINT;

      -- saas：该租户默认根组织（organizations.id）
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS plan_code      VARCHAR(32);

 -- 当前套餐（billing_plans.code 逻辑引用，冗余展示位）
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS source         VARCHAR(16) NOT NULL DEFAULT 'self_serve';

 -- self_serve|sales|sync
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS trial_ends_at  TIMESTAMPTZ;

 -- 试用到期（NULL=非试用）
COMMENT ON COLUMN tenants.owner_user_id IS 'ES8：租户管理员（system_users.id，逻辑引用）';

COMMENT ON COLUMN tenants.org_id        IS 'ES8：saas 形态该租户默认根组织（organizations.id，业务树挂这里）';

COMMENT ON COLUMN tenants.plan_code     IS 'ES8：当前套餐 code（billing_plans.code 冗余展示位，权威见 subscriptions）';

COMMENT ON COLUMN tenants.source        IS 'ES8：租户来源 self_serve(自助注册)|sales(运营开通)|sync(存量清洗)';

COMMENT ON COLUMN tenants.trial_ends_at IS 'ES8：试用截止时间（NULL=非试用）';


-- users 隔离键语义收口（不动列型，脏数据值域迁移见 45.3；实际表名 system_users）
COMMENT ON COLUMN system_users.tenant_id IS 'ES8：租户主键（tenants.id）；历史脏数据=组织id，45.3 迁移清洗';

COMMENT ON COLUMN system_users.org_id    IS '组织主键（organizations.id，业务归属）；与 tenant_id 解耦';



-- 45.2 订购记录表（支付/开通/变更全落此表，可审计可续费追溯）
CREATE TABLE IF NOT EXISTS subscriptions (
    id                   BIGSERIAL PRIMARY KEY,
    tenant_id            BIGINT      NOT NULL,                    -- tenants.id
    plan_code            VARCHAR(32) NOT NULL,                    -- billing_plans.code
    status               VARCHAR(16) NOT NULL DEFAULT 'TRIALING', -- TRIALING|ACTIVE|GRACE|PAST_DUE|CANCELED|EXPIRED
    billing_cycle        VARCHAR(8)  NOT NULL DEFAULT 'monthly',  -- monthly|yearly
    trial_ends_at        TIMESTAMPTZ,
    current_period_start TIMESTAMPTZ NOT NULL,
    current_period_end   TIMESTAMPTZ NOT NULL,
    cancel_at_period_end BOOLEAN     NOT NULL DEFAULT FALSE,
    auto_renew           BOOLEAN     NOT NULL DEFAULT TRUE,
    order_id             BIGINT,                                  -- 首购订单（mock 支付，逻辑引用）
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_subscriptions_tenant_id ON subscriptions (tenant_id);


-- 同租户同时最多一条未终止订购（部分唯一）
CREATE UNIQUE INDEX IF NOT EXISTS ix_subscriptions_tenant
    ON subscriptions (tenant_id) WHERE status NOT IN ('CANCELED','EXPIRED');

COMMENT ON TABLE  subscriptions               IS 'ES8 M1：订购关系权威（状态机；billing_quotas 为本表派生缓存）';

COMMENT ON COLUMN subscriptions.status        IS '状态机 TRIALING|ACTIVE|GRACE|PAST_DUE|CANCELED|EXPIRED';

COMMENT ON COLUMN subscriptions.current_period_end IS '当前账期截止（周期 job / License 有效期对齐）';



-- 45.3 存量清洗（幂等）：历史 system_users.tenant_id=org.id → 建 sync 租户行并重指
--     口径：凡 tenant_id 不在 tenants.id 值域、且等于某 organizations.id 的脏值，
--     为该 org 生成一条 source='sync' 的 tenants 行，随后批量重指；
--     映射落 es8_tenant_migration_map 备份表，二次执行零变化。
CREATE TABLE IF NOT EXISTS es8_tenant_migration_map (
    id          BIGSERIAL PRIMARY KEY,
    org_id      INTEGER NOT NULL UNIQUE,          -- 脏值来源 organizations.id
    tenant_id   BIGINT  NOT NULL,                 -- 重指目标 tenants.id
    migrated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE es8_tenant_migration_map IS 'ES8 M1 45.3：脏 tenant_id 迁移映射备份（org_id → 新租户），审计追溯用';

UPDATE system_users u
SET tenant_id = m.tenant_id
FROM es8_tenant_migration_map m
WHERE u.tenant_id = m.org_id
  AND NOT EXISTS (SELECT 1 FROM tenants t WHERE t.id = u.tenant_id);



-- 同步 organizations.tenant_id 归位（脏 org 自身也指向新租户，保持 org↔tenant 一致）
UPDATE organizations o
SET tenant_id = m.tenant_id
FROM es8_tenant_migration_map m
WHERE o.id = m.org_id
  AND o.tenant_id = m.org_id;



-- 45.3 插入的 tenants 行走 BIGSERIAL，防与历史显式 id 撞号，序列对齐
SELECT setval(pg_get_serial_sequence('tenants','id'), (SELECT MAX(id) FROM tenants));

SELECT 'inti.sql section 45 ES8-M1 provisioning & subscription DONE' AS done;



-- 46.1 订单表（下单→支付→履约链路的交易主体）
CREATE TABLE IF NOT EXISTS orders (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           BIGINT       NOT NULL,                    -- tenants.id
    subscription_id     BIGINT,                                   -- 履约后回填（逻辑引用）
    order_no            VARCHAR(40)  NOT NULL UNIQUE,             -- 商户订单号（gen_no('SO')）
    plan_code           VARCHAR(32)  NOT NULL,                    -- billing_plans.code
    billing_cycle       VARCHAR(8)   NOT NULL,                    -- monthly|yearly
    amount_cents        INTEGER      NOT NULL,                    -- 应付（分，权威）
    discount_cents      INTEGER      NOT NULL DEFAULT 0,          -- 折扣（分）
    credit_deduct_cents INTEGER      NOT NULL DEFAULT 0,          -- credits 抵扣（分，≤订单额50%）
    status              VARCHAR(16)  NOT NULL DEFAULT 'PENDING',  -- PENDING|PAID|FULFILLED|REFUNDED|CLOSED|FAILED
    provider            VARCHAR(16)  NOT NULL DEFAULT 'mock',     -- mock|wechat|alipay
    provider_order_id   VARCHAR(64),                              -- 渠道预下单号
    paid_at             TIMESTAMPTZ,                              -- 支付成功时间
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_orders_tenant_id ON orders (tenant_id);

CREATE INDEX IF NOT EXISTS ix_orders_status    ON orders (status);

COMMENT ON TABLE  orders                IS 'ES8 M2：订单（下单/支付/履约状态机主体）';

COMMENT ON COLUMN orders.status         IS 'PENDING|PAID|FULFILLED|REFUNDED|CLOSED|FAILED';

COMMENT ON COLUMN orders.credit_deduct_cents IS 'credits 抵扣金额（分），下单时封顶=订单额50%';



-- 支付流水表（渠道回调原文留档，trade_no 幂等键）
CREATE TABLE IF NOT EXISTS payments (
    id           BIGSERIAL PRIMARY KEY,
    order_id     BIGINT      NOT NULL,                            -- orders.id
    trade_no     VARCHAR(64) NOT NULL UNIQUE,                     -- 渠道交易号（幂等键）
    provider     VARCHAR(16) NOT NULL,                            -- mock|wechat|alipay
    amount_cents INTEGER     NOT NULL,                            -- 实付（分）
    status       VARCHAR(16) NOT NULL,                            -- SUCCESS|REFUND
    raw_notify   TEXT,                                            -- 回调原文（验签留档）
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_payments_order_id ON payments (order_id);

COMMENT ON TABLE  payments         IS 'ES8 M2：支付流水（trade_no 唯一，重复回调幂等去重）';

COMMENT ON COLUMN payments.status  IS 'SUCCESS|REFUND';



-- 46.2 套餐表扩列：分币整数权威价 + 试用天数 + 公开标记
ALTER TABLE billing_plans ADD COLUMN IF NOT EXISTS price_yearly_cents  BIGINT  NOT NULL DEFAULT 0;

ALTER TABLE billing_plans ADD COLUMN IF NOT EXISTS price_monthly_cents BIGINT  NOT NULL DEFAULT 0;

ALTER TABLE billing_plans ADD COLUMN IF NOT EXISTS trial_days          INTEGER NOT NULL DEFAULT 14;

ALTER TABLE billing_plans ADD COLUMN IF NOT EXISTS is_public           BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN billing_plans.price_yearly_cents  IS 'ES8 M2：年付权威价（分，整数；0=未回填见 46.3）';

COMMENT ON COLUMN billing_plans.price_monthly_cents IS 'ES8 M2：月付权威价（分，整数；0=未回填见 46.3）';

COMMENT ON COLUMN billing_plans.trial_days          IS 'ES8 M2：该套餐试用天数（默认14，注册页 CTA 文案来源）';

COMMENT ON COLUMN billing_plans.is_public           IS 'ES8 M2：是否公开出现在 /pricing 页（FALSE=仅销售定向）';

SELECT 'inti.sql section 46 ES8-M2 orders/payments & plan cents DONE' AS done;



-- 47.1 通知渠道表（租户级；config 为 encrypt_secret 加密后的 JSON 串）
CREATE TABLE IF NOT EXISTS notify_channels (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT       NOT NULL,                        -- tenants.id
    kind            VARCHAR(16)  NOT NULL,                        -- email|dingtalk|feishu|wecom|slack|webhook
    name            VARCHAR(128) NOT NULL,
    config          TEXT         NOT NULL,                        -- 加密 JSON（app/security.py encrypt_secret）
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    last_probe_at   TIMESTAMPTZ,                                  -- 最近一次「发送测试」时间
    last_probe_ok   BOOLEAN,                                      -- 最近一次探测是否成功
    created_by      BIGINT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_notify_channels_tenant_id ON notify_channels (tenant_id);

COMMENT ON TABLE  notify_channels            IS 'ES8 M3：通知渠道（租户级，config 加密存储）';

COMMENT ON COLUMN notify_channels.kind       IS 'email|dingtalk|feishu|wecom|slack|webhook';

COMMENT ON COLUMN notify_channels.config     IS 'AES-GCM 加密的 JSON 配置原文（decrypt_secret 解密）';

COMMENT ON COLUMN notify_channels.last_probe_ok IS 'TRUE=可用(teal) / FALSE=失败(红) / NULL=未探测';



-- 47.2 通知规则表（事件 → 渠道订阅）
CREATE TABLE IF NOT EXISTS notify_rules (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT       NOT NULL,
    event         VARCHAR(48)  NOT NULL,                          -- task.completed|task.failed|monitor.alert|subscription.renewing|defect.created|review.assigned
    scope         TEXT,                                           -- JSON: {project_id?, suite_id?} 空/NULL=全部
    channel_ids   TEXT         NOT NULL DEFAULT '[]',             -- JSON 数组：notify_channels.id 列表
    template_key  VARCHAR(48),                                    -- 模板预留（本期未启用）
    min_severity  VARCHAR(16)  NOT NULL DEFAULT 'LOW',            -- LOW<MEDIUM<HIGH<CRITICAL
    enabled       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_notify_rules_tenant_event ON notify_rules (tenant_id, event);

COMMENT ON TABLE  notify_rules              IS 'ES8 M3：通知规则（事件订阅 + 严重级门槛 + 范围过滤）';

COMMENT ON COLUMN notify_rules.min_severity IS 'LOW|MEDIUM|HIGH|CRITICAL，事件 severity 低于此值不触发外部渠道';



-- 47.3 投递留痕表
CREATE TABLE IF NOT EXISTS notify_deliveries (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT       NOT NULL,
    rule_id       BIGINT,                                         -- notify_rules.id（渠道直发测试时为 NULL）
    event         VARCHAR(48)  NOT NULL,
    channel_kind  VARCHAR(16)  NOT NULL,
    channel_id    BIGINT,
    payload       TEXT,                                           -- 发送内容摘要（JSON）
    status        VARCHAR(16)  NOT NULL,                          -- SUCCESS|FAILED|DEGRADED|SKIPPED
    error         TEXT,                                           -- 失败原因
    attempts      INTEGER      NOT NULL DEFAULT 1,                -- 实际尝试次数（含重试 1 次）
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_notify_deliveries_tenant_created ON notify_deliveries (tenant_id, created_at);

CREATE INDEX IF NOT EXISTS ix_notify_deliveries_status         ON notify_deliveries (status);

COMMENT ON TABLE  notify_deliveries      IS 'ES8 M3：通知投递留痕（每次渠道发送一条记录）';

COMMENT ON COLUMN notify_deliveries.status IS 'SUCCESS=发送成功 / FAILED=配置类失败 / DEGRADED=重试后仍败(站内信兜底) / SKIPPED=渠道被禁用等跳过';

SELECT 'inti.sql section 47 ES8-M3 notify center DONE' AS done;



-- 48.1 监控表（套件定时 + 阈值告警；alert_conditions/baseline_metrics JSON 存 TEXT）
CREATE TABLE IF NOT EXISTS monitors (
    id                 BIGSERIAL PRIMARY KEY,
    tenant_id          BIGINT       NOT NULL,                        -- tenants.id
    org_id             BIGINT       NOT NULL DEFAULT 0,              -- 冗余组织位（无组织体系时 0）
    name               VARCHAR(128) NOT NULL,
    suite_id           BIGINT       NOT NULL,                        -- test_suites.id（逻辑引用）
    cron               VARCHAR(32)  NOT NULL,                        -- 5 段表达式（utils/cron.py 解析）
    baseline_mode      VARCHAR(16)  NOT NULL DEFAULT 'LAST_RUN',     -- LAST_RUN|FIXED
    baseline_metrics   TEXT         NOT NULL DEFAULT '{}',           -- {"pass_rate":0.9,...} 上次 run 指标快照
    alert_conditions   TEXT         NOT NULL DEFAULT '[]',           -- [{"metric":"pass_rate","op":"lt","threshold":0.85}]
    notify_rule_event  VARCHAR(48)  NOT NULL DEFAULT 'monitor.alert',
    enabled            BOOLEAN      NOT NULL DEFAULT TRUE,
    last_run_id        BIGINT,                                       -- 最近触发批次代表任务 id（test_tasks.id）
    last_checked_at    TIMESTAMPTZ,                                  -- tick 抢占时间戳（条件 UPDATE 防并发）
    next_fire_at       TIMESTAMPTZ,                                  -- cron 求得的下次触发时刻
    created_by         BIGINT,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_monitors_tenant_id    ON monitors (tenant_id);

CREATE INDEX IF NOT EXISTS ix_monitors_due          ON monitors (enabled, next_fire_at);

CREATE INDEX IF NOT EXISTS ix_monitors_suite_id     ON monitors (suite_id);

COMMENT ON TABLE  monitors                  IS 'ES8 M4：定时监控（套件+cron+阈值告警，挂 scheduler tick）';

COMMENT ON COLUMN monitors.baseline_mode    IS 'LAST_RUN=自存上次 run 快照 / FIXED=固定基线';

COMMENT ON COLUMN monitors.alert_conditions IS 'JSON 数组：[{"metric","op":"lt|gt","threshold"}]，metric ∈ pass_rate|injection_success_rate|hallucination_rate';

COMMENT ON COLUMN monitors.last_run_id      IS '最近触发批次代表任务 id（批次=test_tasks 中 suite_id 相同且 created_at 相同的一组克隆）';



-- 48.2 告警时间线表（FIRING 建一行；恢复回填 resolved_at+RESOLVED；同 metric FIRING 中收敛）
CREATE TABLE IF NOT EXISTS monitor_alerts (
    id          BIGSERIAL PRIMARY KEY,
    monitor_id  BIGINT       NOT NULL,                               -- monitors.id（逻辑引用）
    run_id      BIGINT,                                              -- 触发告警的批次代表任务 id
    metric      VARCHAR(48)  NOT NULL,
    value       REAL         NOT NULL,                               -- 实际指标值
    threshold   REAL         NOT NULL,                               -- 条件阈值
    op          VARCHAR(4)   NOT NULL,                               -- lt|gt
    state       VARCHAR(16)  NOT NULL,                               -- FIRING|RESOLVED
    fired_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    notified    BOOLEAN      NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS ix_monitor_alerts_monitor ON monitor_alerts (monitor_id, state);

CREATE INDEX IF NOT EXISTS ix_monitor_alerts_fired   ON monitor_alerts (monitor_id, fired_at);

COMMENT ON TABLE  monitor_alerts      IS 'ES8 M4：监控告警时间线（同 monitor+metric 仅一条 FIRING，收敛防轰炸）';

COMMENT ON COLUMN monitor_alerts.state IS 'FIRING=告警中（红点） / RESOLVED=指标回阈值内已恢复';

SELECT 'inti.sql section 48 ES8-M4 monitors DONE' AS done;



-- 49.1 门禁规则：JSON 数组 [{"metric","op","threshold"}]，
--      metric ∈ pass_rate|critical_defects|hallucination_rate|injection_success_rate，
--      op ∈ lt|lte|gt|gte；空数组 = 非门禁任务（不评估）
ALTER TABLE test_tasks ADD COLUMN IF NOT EXISTS gate_rules TEXT NOT NULL DEFAULT '[]';



-- 49.2 门禁结论：PASSED|FAILED（评估后写入；NULL = 未评估）
ALTER TABLE test_tasks ADD COLUMN IF NOT EXISTS gate_result VARCHAR(16);

COMMENT ON COLUMN test_tasks.gate_rules  IS 'ES8 M5：质量门禁规则 JSON 数组，空=非门禁任务';

COMMENT ON COLUMN test_tasks.gate_result IS 'ES8 M5：门禁结论 PASSED|FAILED，NULL=未评估';

SELECT 'inti.sql section 49 ES8-M5 quality gate DONE' AS done;



-- 51.1 主表扩列：派生血缘（from_run/from_review 建集时记录来源评测集）
ALTER TABLE eval_sets ADD COLUMN IF NOT EXISTS parent_set_id INTEGER;

COMMENT ON COLUMN eval_sets.parent_set_id IS 'ES8 M7：父评测集 id（派生血缘，逻辑引用 eval_sets.id）';



-- 51.2 版本快照表：编辑升版前旧 items 整文入库，行级差异留痕
--      与 backend/app/models.py EvalSetRevision 逐字段对齐
--      id 用 BIGSERIAL（对齐全库惯例，模型 BigInteger PK）
CREATE TABLE IF NOT EXISTS eval_set_revisions (
    id          BIGSERIAL PRIMARY KEY,
    eval_set_id INTEGER      NOT NULL,                    -- eval_sets.id（逻辑引用）
    version     INTEGER      NOT NULL,                    -- 快照对应的版本号 N（主表 vN 的数字位）
    content     TEXT         NOT NULL,                    -- 整文快照：升版前 items 的 JSON 序列化
    diff_stats  TEXT,                                     -- 行级对比 JSON {"added":n,"removed":n,"unchanged":n}
    created_by  BIGINT,                                   -- 操作人 user_id
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_eval_set_revisions_set_version
    ON eval_set_revisions (eval_set_id, version);

COMMENT ON TABLE  eval_set_revisions         IS 'ES8 M7：评测集版本快照（编辑即升版，旧内容整文留痕）';

COMMENT ON COLUMN eval_set_revisions.version IS '快照版本号 N，对应主表 eval_sets.version 字符串 vN';

COMMENT ON COLUMN eval_set_revisions.content IS '升版前 items 的 JSON 整文，供历史查看与两版本 diff';

COMMENT ON COLUMN eval_set_revisions.diff_stats IS '与升版后新内容的行级对比 {"added":n,"removed":n,"unchanged":n}';

SELECT 'inti.sql section 51 ES8-M7 dataset versioning DONE' AS done;



-- 50.1 复核队列表：低置信/人工标记/监控告警三路入队，复核员状态机流转
--      与 backend/app/models.py ReviewItem 逐字段对齐
CREATE TABLE IF NOT EXISTS review_items (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT       NOT NULL,
    org_id           BIGINT       NOT NULL DEFAULT 0,          -- 逻辑引用 organizations.id（对齐 M4 惯例）
    source           VARCHAR(16)  NOT NULL,                    -- run_item|trace|defect
    source_ref       TEXT         NOT NULL,                    -- JSON：{"run_id":..,"item_index":..}
    context          TEXT         NOT NULL DEFAULT '{}',       -- 快照 JSON：prompt/score/verdict 等（复制而非引用，保证队列可复现）
    auto_verdict     VARCHAR(24),                              -- 机判结论（grade/verdict 值）
    auto_confidence  REAL,                                     -- 机判置信度（无原生字段时为 score 贴近阈值的代理值）
    status           VARCHAR(16)  NOT NULL DEFAULT 'OPEN',     -- OPEN|ASSIGNED|DONE|DISCARDED
    assignee_id      BIGINT,                                   -- 复核员 user_id（逻辑引用 users.id）
    human_verdict    VARCHAR(24),                              -- 人工结论（DONE 权威落点，不回写 run 表）
    human_note       TEXT,                                     -- 复核备注
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);



-- 幂等入队：同一 (source, source_ref) 只允许一条 OPEN；DONE/DISCARDED 后可再入
CREATE UNIQUE INDEX IF NOT EXISTS ix_review_items_src
    ON review_items (source, source_ref) WHERE status = 'OPEN';

CREATE INDEX IF NOT EXISTS ix_review_items_tenant_status
    ON review_items (tenant_id, status);

CREATE INDEX IF NOT EXISTS ix_review_items_assignee
    ON review_items (assignee_id, status);

COMMENT ON TABLE  review_items                  IS 'ES8 M6：人工复核队列（judge 校准数据源，DONE 不回写 run 表）';

COMMENT ON COLUMN review_items.source           IS '入队来源：run_item=评测逐项 / trace=M8 采样 / defect=缺陷联动';

COMMENT ON COLUMN review_items.source_ref       IS '定位 JSON：{"run_id":..,"item_index":..}，OPEN 态下 (source,source_ref) 唯一';

COMMENT ON COLUMN review_items.context          IS '样本快照 JSON（prompt/score/verdict 等），不引用 run 行';

COMMENT ON COLUMN review_items.auto_confidence  IS '机判置信度；引擎无 confidence 字段时为 score 贴近判分阈值的代理值';

COMMENT ON COLUMN review_items.status           IS '状态机：OPEN→ASSIGNED→DONE；OPEN/ASSIGNED→DISCARDED';

COMMENT ON COLUMN review_items.human_verdict    IS '人工结论（PASS/FAIL 等），校准混淆矩阵的人工列';

SELECT 'inti.sql section 50 ES8-M6 review queue DONE' AS done;



-- 52.1 traces：对话留痕表（gateway 旁路写 / ingest_api 推送）
CREATE TABLE IF NOT EXISTS traces (
    id             BIGSERIAL    PRIMARY KEY,
    tenant_id      BIGINT       NOT NULL,
    org_id         BIGINT,                                     -- organizations.id（逻辑引用，对齐 M4 惯例）
    source         VARCHAR(16)  NOT NULL,                      -- gateway=自有网关旁路 / ingest_api=外部推送
    external_ref   VARCHAR(64),                                -- 网关请求 id（可空）
    request        TEXT         NOT NULL,                      -- 截断存：≤8KB 原文，超限存前4KB+标记+后1KB
    response       TEXT         NOT NULL,                      -- 同上
    model          VARCHAR(64),                                -- 目标模型/靶机编码
    tokens         INTEGER,                                    -- 用量（可得则记）
    latency_ms     INTEGER,                                    -- 网关调用耗时
    status         VARCHAR(16),                                -- OK|ERROR（对齐网关返回语义）
    occurred_at    TIMESTAMPTZ  NOT NULL,                      -- 对话发生时间
    eval_status    VARCHAR(16)  NOT NULL DEFAULT 'PENDING',    -- PENDING|SCORED|SKIPPED|FAILED
    scores         TEXT          DEFAULT '{}',                 -- 评分 JSON：{"pii_leak":0-1,...}
    reviewed       BOOLEAN      NOT NULL DEFAULT FALSE,       -- 是否已回流复核
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_traces_tenant_eval     ON traces (tenant_id, eval_status);

CREATE INDEX IF NOT EXISTS ix_traces_tenant_occurred ON traces (tenant_id, occurred_at DESC);

COMMENT ON TABLE  traces              IS 'ES8 M8：在线对话留痕（网关旁路 + ingestion API），采样评分数据源';

COMMENT ON COLUMN traces.source       IS '留痕来源：gateway=自有网关旁路 / ingest_api=通用推送接口';

COMMENT ON COLUMN traces.request      IS '请求文本，截断存（单条上限 8KB，超限=前4KB+TRUNCATED标记+后1KB）';

COMMENT ON COLUMN traces.eval_status  IS '评分状态机：PENDING→SCORED/FAILED；未抽样/熔断=SKIPPED 或直接留 PENDING';

COMMENT ON COLUMN traces.scores       IS '自动评分 JSON：各指标 0-1 质量分（高=安全），overall=min(values)';

COMMENT ON COLUMN traces.reviewed     IS '低分回流 review_items 后置 TRUE，防重复入队';



-- 52.2 trace_policies：租户级采样评分策略（每租户一条，缺省即关闭）
CREATE TABLE IF NOT EXISTS trace_policies (
    id                  BIGSERIAL    PRIMARY KEY,
    tenant_id           BIGINT       NOT NULL,
    enabled             BOOLEAN      NOT NULL DEFAULT FALSE,   -- 采样评分总开关
    sample_rate         REAL         NOT NULL DEFAULT 0.1,     -- 抽样率 0-1
    judge_metrics       TEXT         NOT NULL DEFAULT '["pii_leak","injection","hallucination"]',  -- 复用现有引擎的轻量单轮评分子逻辑
    daily_cap           INTEGER      NOT NULL DEFAULT 2000,    -- judge 评分日上限（成本闸门，本地熔断）
    low_score_threshold REAL         NOT NULL DEFAULT 0.6,     -- overall 低于此值回流 review_items
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_trace_policies_tenant ON trace_policies (tenant_id);

COMMENT ON TABLE  trace_policies                   IS 'ES8 M8：在线评测采样策略（租户级一条）';

COMMENT ON COLUMN trace_policies.daily_cap         IS '当日已评分（SCORED+FAILED）条数上限，超则本 tick 熔断跳过';

COMMENT ON COLUMN trace_policies.low_score_threshold IS 'overall 质量分低于该阈值 → 入 review_items（source=trace）';

SELECT 'inti.sql section 52 ES8-M8 online traces DONE' AS done;



-- 53.1 生成式红队样本池（变异器产出的载荷，须审批 APPROVED 后方可参与评测执行）
CREATE TABLE IF NOT EXISTS redteam_samples (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      BIGINT       NOT NULL,
    framework_code VARCHAR(64)  NOT NULL DEFAULT '',
    payload        TEXT         NOT NULL,
    mutation_of    BIGINT,
    status         VARCHAR(16)  NOT NULL DEFAULT 'DRAFT',
    hit_stats      TEXT         NOT NULL DEFAULT '{}',
    created_by     BIGINT,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    reviewed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_redteam_samples_tenant_status
    ON redteam_samples (tenant_id, status);

CREATE INDEX IF NOT EXISTS ix_redteam_samples_framework
    ON redteam_samples (framework_code);

COMMENT ON TABLE  redteam_samples                IS 'ES8 M9：生成式红队样本池（变异载荷，DRAFT 不参与执行）';

COMMENT ON COLUMN redteam_samples.framework_code IS '映射条目 code（如 LLM01:2025 / AML.T0051），可空串';

COMMENT ON COLUMN redteam_samples.mutation_of    IS '源种子样本 id（逻辑引用 redteam_samples.id，原生种子为空）';

COMMENT ON COLUMN redteam_samples.status         IS '状态机：DRAFT→APPROVED|REJECTED；REJECTED 为终态';

COMMENT ON COLUMN redteam_samples.hit_stats      IS '命中统计 JSON：{"attempts":N,"bypassed":N}，报告/护栏建议数据源';



-- 53.2 国际框架条目表（OWASP LLM Top 10 2025 + MITRE ATLAS tactics/techniques 精选种子）
CREATE TABLE IF NOT EXISTS framework_items (
    id           BIGSERIAL PRIMARY KEY,
    framework    VARCHAR(32)  NOT NULL,
    code         VARCHAR(64)  NOT NULL,
    name         VARCHAR(256) NOT NULL,
    item_type    VARCHAR(16)  NOT NULL DEFAULT 'risk',
    tactic       VARCHAR(64)  NOT NULL DEFAULT '',
    description  TEXT         NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uk_framework_items_code UNIQUE (code)
);

CREATE INDEX IF NOT EXISTS ix_framework_items_framework
    ON framework_items (framework);

COMMENT ON TABLE  framework_items            IS 'ES8 M9：国际安全框架条目（owasp_llm / atlas），报告覆盖节数据源';

COMMENT ON COLUMN framework_items.framework  IS '框架：owasp_llm=OWASP LLM Top10 2025 / atlas=MITRE ATLAS';

COMMENT ON COLUMN framework_items.code       IS '全局唯一编码：LLM01:2025 / AML.T0051 / AML.TA01 等';

COMMENT ON COLUMN framework_items.item_type  IS '条目类型：risk=OWASP 风险 / technique=ATLAS 技术 / tactic=ATLAS 战术';

SELECT 'inti.sql section 53 ES8-M9 generative redteam DONE' AS done;

CREATE TABLE IF NOT EXISTS sso_configs (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT       NOT NULL,
    kind             VARCHAR(16)  NOT NULL,
    name             VARCHAR(128) NOT NULL,
    issuer           TEXT         NOT NULL DEFAULT '',
    client_id        VARCHAR(256) NOT NULL DEFAULT '',
    client_secret_enc TEXT        NOT NULL DEFAULT '',
    scopes           VARCHAR(512) NOT NULL DEFAULT 'openid profile email',
    redirect_uri     TEXT         NOT NULL DEFAULT '',
    enabled          BOOLEAN      NOT NULL DEFAULT TRUE,
    auto_provision   BOOLEAN      NOT NULL DEFAULT FALSE,
    default_role     VARCHAR(64)  NOT NULL DEFAULT 'MEMBER',
    org_binding_mode VARCHAR(32)  NOT NULL DEFAULT 'none',
    created_by       BIGINT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sso_configs_tenant ON sso_configs (tenant_id, enabled);

COMMENT ON TABLE sso_configs IS 'ES8-M10 单点登录配置（OIDC/企微/飞书），client_secret 以 AES-GCM 密文存储';

COMMENT ON COLUMN sso_configs.kind IS '身份源类型：oidc | wecom | feishu';

COMMENT ON COLUMN sso_configs.issuer IS 'OIDC issuer（.well-known/openid-configuration 前缀），企微/飞书留空走内置端点';

COMMENT ON COLUMN sso_configs.client_secret_enc IS 'AES-256-GCM 加密后的 client_secret（app/security.py encrypt_secret），出参仅回 ****+后4位';

COMMENT ON COLUMN sso_configs.scopes IS 'OIDC scope 串（空格分隔），默认 openid profile email';

COMMENT ON COLUMN sso_configs.redirect_uri IS '回调地址（精确匹配白名单），留空则按 API 基址自动构造';

COMMENT ON COLUMN sso_configs.auto_provision IS '首次登录无匹配用户时是否自动建号入租户';

COMMENT ON COLUMN sso_configs.default_role IS 'auto_provision 建号时绑定的角色编码';

COMMENT ON COLUMN sso_configs.org_binding_mode IS '组织绑定模式：none | name（按 claim 中部门名解析组织）';

SELECT 'inti.sql section 54 ES8-M10 sso DONE' AS done;



-- 55.1 工单同步目标（租户级配置：provider + 连接参数密文 + 探测态）
CREATE TABLE IF NOT EXISTS defect_sync_targets (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT       NOT NULL,
    provider         VARCHAR(16)  NOT NULL,                -- github|gitee|jira
    name             VARCHAR(128) NOT NULL,
    config           JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- github/gitee:{repo,token_enc} jira:{base_url,project_key,personal_token_enc,issue_type}
    enabled          BOOLEAN      NOT NULL DEFAULT TRUE,
    last_probe_ok    BOOLEAN,
    last_probe_at    TIMESTAMPTZ,
    created_by       BIGINT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ,
    UNIQUE (tenant_id, name)
);

CREATE INDEX IF NOT EXISTS idx_dst_tenant_enabled ON defect_sync_targets (tenant_id, enabled);

COMMENT ON TABLE defect_sync_targets IS 'ES8-M11 缺陷工单同步目标（GitHub/Gitee/Jira），token 以 AES-GCM 密文存于 config.token_enc';

COMMENT ON COLUMN defect_sync_targets.provider IS '工单平台类型：github | gitee | jira';

COMMENT ON COLUMN defect_sync_targets.config IS '连接参数 JSONB，token_enc 为 app/security.py encrypt_secret 密文，出参仅回 ****+后4位';

COMMENT ON COLUMN defect_sync_targets.last_probe_ok IS '最近一次连通探测结果（NULL=未探测过）';



-- 55.2 缺陷 ↔ 外部工单映射（幂等推送的唯一键载体）
CREATE TABLE IF NOT EXISTS defect_sync_links (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT       NOT NULL,
    target_id        BIGINT       NOT NULL,                        -- 逻辑关联 defect_sync_targets.id（无外键）
    defect_id        BIGINT       NOT NULL,                        -- 逻辑关联 defects.id（无外键）
    external_id      VARCHAR(64)  NOT NULL,                -- GH/Gitee issue number 或 Jira issue key
    external_url     TEXT         NOT NULL,
    direction        VARCHAR(8)   NOT NULL DEFAULT 'out',  -- out=本系统推送建立
    sync_status      VARCHAR(16)  NOT NULL DEFAULT 'SYNCED',  -- SYNCED|EXTERNAL_CLOSED|LOCAL_CLOSED|FAILED
    last_synced_at   TIMESTAMPTZ,
    fail_reason      TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ
);



-- 幂等双唯一索引：同一目标外部单号唯一（webhook 回写定位）、同一缺陷同一目标只推一次
CREATE UNIQUE INDEX IF NOT EXISTS ix_dsl_target_external ON defect_sync_links (target_id, external_id);

CREATE UNIQUE INDEX IF NOT EXISTS ix_dsl_defect_target  ON defect_sync_links (defect_id, target_id);

COMMENT ON TABLE defect_sync_links IS 'ES8-M11 缺陷与外部工单映射（幂等推送：重复 push-target 命中唯一索引直接回已有链接）';

COMMENT ON COLUMN defect_sync_links.sync_status IS 'SYNCED=同步中 | EXTERNAL_CLOSED=外部已关单 | LOCAL_CLOSED=随缺陷关闭 | FAILED=推送失败';

SELECT 'inti.sql section 55 ES8-M11 defect sync DONE' AS done;



-- 56.1 数据保留策略表（每租户每产物类型至多一条）
CREATE TABLE IF NOT EXISTS retention_policies (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT       NOT NULL,
    artifact_type VARCHAR(32)  NOT NULL,                -- traces|runs|recordings|attachments|audit_logs
    days          INTEGER      NOT NULL CHECK (days > 0),
    purge_action  VARCHAR(16)  NOT NULL DEFAULT 'delete'
                               CHECK (purge_action IN ('delete', 'archive_ref')),
    archive_ref   VARCHAR(256),                          -- archive_ref 动作的归档引用（外部存储指针，可空）
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, artifact_type)
);

CREATE INDEX IF NOT EXISTS idx_retention_policies_tenant ON retention_policies (tenant_id);

COMMENT ON TABLE retention_policies IS 'ES8-M12 数据保留策略（日清理任务按此扫描过期数据，每轮分批 ≤5000 行）';

COMMENT ON COLUMN retention_policies.artifact_type IS '产物类型：traces=留痕 | runs=评测运行 | recordings=测试录制 | attachments=任务附件 | audit_logs=审计日志（代码层硬拒，永不生效）';

COMMENT ON COLUMN retention_policies.days IS '保留天数：早于 now()-days 的数据视为过期';

COMMENT ON COLUMN retention_policies.purge_action IS '清理动作：delete=物理删除 | archive_ref=归档引用（有 deleted_at 的表软删标记，其余等价删除）';

COMMENT ON COLUMN retention_policies.archive_ref IS 'archive_ref 动作的归档位置指针（预留外部对象存储路径，可空）';



-- 56.2 订阅表扩展：注销后到期匿名化时间戳（cancel-and-anonymize 端点写入 now()+30d）
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS anonymize_after TIMESTAMPTZ;

COMMENT ON COLUMN subscriptions.anonymize_after IS 'ES8-M12：注销并匿名化请求的到期时间；日任务到期后把该租户内容列置 NULL（墓碑行保留），NULL=未申请';

SELECT 'inti.sql section 56 ES8-M12 retention DONE' AS done;

ALTER TABLE framework_items ALTER COLUMN created_at SET DEFAULT now();

SELECT 'inti.sql section 57 framework_items created_at DEFAULT DONE' AS done;

ALTER TABLE billing_topups ADD COLUMN IF NOT EXISTS source VARCHAR(32);

COMMENT ON COLUMN billing_topups.source IS '来源：NULL=人工充值 | order_bonus=支付赠送';

CREATE INDEX IF NOT EXISTS idx_bt_source ON billing_topups(source) WHERE source IS NOT NULL;

SELECT 'inti.sql section 58 billing_topups.source DONE' AS done;

ALTER TABLE reports ADD COLUMN IF NOT EXISTS report_subtype VARCHAR(16) DEFAULT NULL;

ALTER TABLE reports ADD COLUMN IF NOT EXISTS acceptance JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE reports ADD COLUMN IF NOT EXISTS parent_report_id INTEGER DEFAULT NULL;

COMMENT ON COLUMN reports.report_subtype IS '报告子类型：NULL=测试报告 | UAT=验收报告';

COMMENT ON COLUMN reports.acceptance IS '验收签核状态机：{status,verdict,note,signer_vendor,signer_customer,finalized_at}';

COMMENT ON COLUMN reports.parent_report_id IS '验收版本链：指向上一版 UAT 报告（NULL=首版）';

CREATE INDEX IF NOT EXISTS idx_reports_subtype ON reports(report_subtype) WHERE report_subtype = 'UAT';

CREATE INDEX IF NOT EXISTS idx_reports_parent ON reports(parent_report_id) WHERE parent_report_id IS NOT NULL;

SELECT 'inti.sql section 59 reports UAT columns DONE' AS done;

SELECT 'inti.sql section 60 UAT report-center menu seed DONE' AS done;

ALTER TABLE test_engines ADD COLUMN IF NOT EXISTS fidelity VARCHAR(16) NOT NULL DEFAULT 'real';

COMMENT ON COLUMN test_engines.fidelity IS '实现真实度：real=真实执行 / rule=规则匹配 / simulated=模拟演示；来源为引擎类属性，注册时回写';

SELECT 'inti.sql section 61 ES9-P-01 fidelity DONE' AS done;

ALTER TABLE sandbox_executions ADD COLUMN IF NOT EXISTS worker_id VARCHAR(64) NULL;

COMMENT ON COLUMN sandbox_executions.worker_id IS 'ES9：执行 worker 实例标识（pool 模式）；legacy docker 模式为容器 id';

SELECT 'inti.sql section 62 ES9-P-03 sandbox worker_id DONE' AS done;

            -- 无法区分示例哈希时保守全部要求改密（一次性动作）
-- 注：如确认种子哈希为公开示例值，改为精确匹配哈希值再执行（开发时按 inti.sql 实际种子定稿）
SELECT 'inti.sql section 63 ES9-P-04 seed pwd DONE' AS done;

ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS api_key_enc TEXT NULL;

COMMENT ON COLUMN model_configs.api_key_enc IS 'UI 托管密钥密文（Fernet）；与 api_key_env 互斥，日志/接口禁止输出本列明文';

SELECT 'inti.sql section 64 ES9-P-05 model key enc DONE' AS done;

ALTER TABLE src_scan_tasks ADD COLUMN IF NOT EXISTS scan_backend VARCHAR(16) NOT NULL DEFAULT 'builtin';

COMMENT ON COLUMN src_scan_tasks.scan_backend IS 'ES9：builtin=内置规则 / semgrep=外接编排；报告页据此标注能力层级';

SELECT 'inti.sql section 65 ES9-P-08 src backend DONE' AS done;

CREATE TABLE IF NOT EXISTS question_bank (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    name            VARCHAR(128) NOT NULL,
    code            VARCHAR(64) NOT NULL,
    description     TEXT,
    category_system VARCHAR(32) NOT NULL DEFAULT 'TC260',  -- 分类体系：TC260 / OWASP_LLM / CUSTOM
    bank_version    VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    question_count  INT NOT NULL DEFAULT 0,                -- 冗余计数，导入/编辑后重算（同 eval_sets 口径）
    is_builtin      BOOLEAN NOT NULL DEFAULT FALSE,        -- 内置题库随 inti.sql 种子发布（社区版只放开应拒答集子集）
    status          VARCHAR(16) NOT NULL DEFAULT 'active', -- active / archived
    created_by      BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_question_bank_code
    ON question_bank (tenant_id, code) WHERE deleted_at IS NULL;

COMMENT ON TABLE question_bank IS 'ES9-P-09：题库一等实体；社区/专业/企业版按 is_builtin+限额差异化放开';

CREATE TABLE IF NOT EXISTS question (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         BIGINT NOT NULL,
    bank_id           BIGINT NOT NULL,                      -- 软引用 question_bank.id（C1 无物理外键）
    seq               INT NOT NULL DEFAULT 0,               -- 题库内序号，导入保序
    category          VARCHAR(64) NOT NULL,                 -- 国标风险分类编码（framework_items.code 对齐，如 TC260-A1.1）
    sub_category      VARCHAR(64),
    attack_vector     VARCHAR(48),                          -- direct / jailbreak_role / prompt_injection / induction_leak / pii / none
    split             VARCHAR(16) NOT NULL DEFAULT 'ANSWER',-- 三集：REFUSE(应拒答) / ANSWER(应回答) / ATTACK(攻击集)
    text              TEXT NOT NULL,
    expected_behavior VARCHAR(16) NOT NULL DEFAULT 'REFUSE',-- REFUSE / ANSWER / SAFE_REFUSE
    expected_answer   TEXT,                                 -- ANSWER 集可给出参考答案（供事实性核对）
    language          VARCHAR(16) NOT NULL DEFAULT 'zh-CN',
    source            VARCHAR(48) NOT NULL DEFAULT 'manual',-- manual / csv_import / jsonl_import / ai_generated / vendor_licensed
    sensitivity       VARCHAR(16) NOT NULL DEFAULT 'internal', -- public / internal / confidential（分级口径见 §1.4：社区=public / 专业≤internal / 企业可 confidential；confidential 禁止进 saas 形态）
    tags              JSONB NOT NULL DEFAULT '[]'::jsonb,
    meta              JSONB NOT NULL DEFAULT '{}'::jsonb,   -- 出处、审核人、批次等
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at        TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_question_bank_seq ON question (bank_id, seq) WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_question_dedup    ON question (bank_id, category, md5(btrim(text))) WHERE deleted_at IS NULL;

 -- 查重：同库同类同文本唯一（软删可重导）
CREATE INDEX IF NOT EXISTS ix_question_split   ON question (bank_id, split) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_question_cat     ON question (category) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_question_tenant  ON question (tenant_id) WHERE deleted_at IS NULL;

COMMENT ON COLUMN question.split IS 'ES9：三集组织——REFUSE 拒答合格率 / ANSWER 非拒答误拒率 / ATTACK 攻击成功率 ASR 的统计维度';

COMMENT ON COLUMN question.source IS 'ES9：来源标注，覆盖率报告同时展示"来源多样性"防模板化灌水（W3 风险条款）';

CREATE TABLE IF NOT EXISTS question_import_job (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL,
    bank_id       BIGINT NOT NULL,
    format        VARCHAR(8) NOT NULL DEFAULT 'csv',       -- csv / jsonl
    file_path     TEXT NOT NULL,                            -- 落 EVIDENCE_DIR/import/ 下，防原始上传面暴露
    total_rows    INT NOT NULL DEFAULT 0,
    inserted      INT NOT NULL DEFAULT 0,
    duplicated    INT NOT NULL DEFAULT 0,
    rejected      INT NOT NULL DEFAULT 0,
    errors        JSONB NOT NULL DEFAULT '[]'::jsonb,       -- [{row, code, message}] 最多留 200 条
    status        VARCHAR(16) NOT NULL DEFAULT 'pending',   -- pending / running / succeeded / failed
    created_by    BIGINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_qimport_bank ON question_import_job (bank_id, created_at DESC);

COMMENT ON TABLE question_import_job IS 'ES9-P-09：批量导入作业；CSV 入口强制经 csv_guard 反向校验 + 行数/字段校验';



-- eval_runs 挂接题库（软引用，历史任务保持 NULL 可跑）
ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS question_bank_id BIGINT;

COMMENT ON COLUMN eval_runs.question_bank_id IS 'ES9：本次执行所用题库；报告页"样本量与来源"区块取数入口';

SELECT 'inti.sql section 66 ES9-P-09 question bank DONE' AS done;

CREATE TABLE IF NOT EXISTS eval_run_items (
    id               BIGSERIAL PRIMARY KEY,
    run_id           BIGINT NOT NULL,                       -- 软引用 eval_runs.id
    question_id      BIGINT,                                -- 软引用 question.id（非题库任务可为 NULL）
    bank_id          BIGINT,
    split            VARCHAR(16),                           -- 冗余自 question，统计免 JOIN
    category         VARCHAR(64),
    engine_code      VARCHAR(64),
    prompt           TEXT,
    response         TEXT,                                  -- 被测系统原始回答（超长截断+evidence 文件引用）
    response_ref     TEXT,                                  -- EVIDENCE_DIR 下全文路径（>32KB 时）
    rule_verdict     VARCHAR(16),                           -- PASS / FAIL / UNKNOWN（规则轨）
    judge_verdict    VARCHAR(16),                           -- PASS / FAIL / UNKNOWN（LLM 裁判轨）
    final_verdict    VARCHAR(16),                           -- 双轨合成：规则优先
    verdict_reason   TEXT,
    judge_model      VARCHAR(96),
    judge_prompt_hash CHAR(40),                             -- sha256(prompt 模板+样例) 前 40 位
    judge_seed       BIGINT,
    judge_agreement  BOOLEAN,                               -- 双裁判/二次采样一致性（可空=未抽中）
    review_status    VARCHAR(16) NOT NULL DEFAULT 'none',   -- none / pending / approved / rejected / promoted
    reviewer_id      BIGINT,
    reviewed_at      TIMESTAMPTZ,
    latency_ms       INT,
    token_usage      JSONB NOT NULL DEFAULT '{}'::jsonb,    -- {prompt_tokens, completion_tokens}
    seq              INT NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_items_run     ON eval_run_items (run_id, seq);

CREATE INDEX IF NOT EXISTS ix_items_review  ON eval_run_items (review_status) WHERE review_status <> 'none';

CREATE INDEX IF NOT EXISTS ix_items_stats   ON eval_run_items (run_id, split, final_verdict);

COMMENT ON TABLE eval_run_items IS 'ES9-P-10：双轨判定与人工复核的条目级事实源；报告指标全部由本表聚合';

SELECT 'inti.sql section 67 ES9-P-09 eval_run_items DONE' AS done;


-- 列名与 eval_run_items.judge_prompt_hash 对齐（复核联查 JOIN 不歧义）
ALTER TABLE review_items ADD COLUMN IF NOT EXISTS judge_prompt_hash VARCHAR(40);

ALTER TABLE review_items ADD COLUMN IF NOT EXISTS judge_model       VARCHAR(96);

ALTER TABLE review_items ADD COLUMN IF NOT EXISTS run_item_id       BIGINT;

ALTER TABLE review_items ADD COLUMN IF NOT EXISTS priority          VARCHAR(4);

        -- P0/P1/P2（工作台 1-5 键映射）
COMMENT ON COLUMN review_items.priority IS 'ES9：入队规则定级——低一致=P0 / 纯裁判判负=P1 / needs_review 全量=P2';

COMMENT ON COLUMN review_items.run_item_id IS 'ES9：软引用 eval_run_items.id，复核与条目级判定互通';

SELECT 'inti.sql section 68 ES9-P-10 review extend DONE' AS done;

CREATE TABLE IF NOT EXISTS delivery_packages (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL,
    run_id        BIGINT NOT NULL,
    package_no    VARCHAR(64) NOT NULL,                     -- ES9-DELIV-20261020-001
    items         JSONB NOT NULL DEFAULT '[]'::jsonb,       -- [{kind: pdf|zip|csv|md, file_path, sha256, size}]
    standards_ver VARCHAR(32),                              -- tc260.yaml 版本快照
    status        VARCHAR(16) NOT NULL DEFAULT 'building',  -- building / ready / delivered
    created_by    BIGINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_delivery_no ON delivery_packages (tenant_id, package_no) WHERE status <> 'discarded';

SELECT 'inti.sql section 69 ES9-P-11 delivery_packages DONE' AS done;

CREATE TABLE IF NOT EXISTS fact_sources (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     BIGINT NOT NULL,
    name          VARCHAR(128) NOT NULL,
    type          VARCHAR(24) NOT NULL DEFAULT 'kb_api',
    base_url      TEXT,
    auth_cipher   TEXT,                                     -- Fernet 加密（复用 model_configs 既有加密工具）
    status        VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_source_name ON fact_sources (tenant_id, name) WHERE deleted_at IS NULL;

SELECT 'inti.sql section 70 ES9-P-12 fact_sources DONE' AS done;

CREATE TABLE IF NOT EXISTS global_refusal_rules (
    id            BIGSERIAL PRIMARY KEY,
    keyword       TEXT NOT NULL,                             -- 拒答特征关键词（全局唯一去重键）
    source        VARCHAR(128) NOT NULL DEFAULT 'manual',    -- promote:{question_id} / manual
    created_by    BIGINT,
    description   TEXT,                                      -- 备注
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_global_refusal_keyword ON global_refusal_rules (keyword) WHERE deleted_at IS NULL;

COMMENT ON TABLE global_refusal_rules IS 'ES9-P-10/D-13：全局拒答规则库（复核 promote 回流，跨租户生效；models.py GlobalRefusalRule）';

SELECT 'inti.sql section 71 ES9-P-10 global_refusal_rules DONE' AS done;

ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS fact_source_id BIGINT;

COMMENT ON COLUMN eval_runs.fact_source_id IS
  'ES10-P-01：本次评测使用的事实基准知识源（软引用 fact_sources.id）；报告"样本量与来源"展示，检索失败降级为无参照并记 note';

CREATE INDEX IF NOT EXISTS ix_eval_runs_fact_source_id ON eval_runs (fact_source_id) WHERE fact_source_id IS NOT NULL;

SELECT 'inti.sql section 72 ES10-P-01 eval_runs.fact_source_id DONE' AS done;

ALTER TABLE test_tasks ADD COLUMN IF NOT EXISTS project_version_id INTEGER;

ALTER TABLE eval_runs  ADD COLUMN IF NOT EXISTS project_version_id INTEGER;

COMMENT ON COLUMN test_tasks.project_version_id IS 'ES10-P-02：任务归因的项目版本（软引用 project_versions.id，创建时取基线/最新已发布，可空）';

COMMENT ON COLUMN eval_runs.project_version_id  IS 'ES10-P-02：由任务透传的版本归因（报告脚注、compare 按版本过滤取数入口）';

CREATE INDEX IF NOT EXISTS ix_test_tasks_project_version_id ON test_tasks (project_version_id) WHERE project_version_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_eval_runs_project_version_id  ON eval_runs  (project_version_id)  WHERE project_version_id  IS NOT NULL;

SELECT 'inti.sql section 73 ES10-P-02 version attribution DONE' AS done;

COMMENT ON COLUMN api_keys.scopes IS
  'ES10-P-04：权限范围字符串数组（资源:动作，如 traces:write）；NULL=旧 Key 全量兼容；认证层 deps.require_scope 校验，缺 scope 403 ES-SCOPE-0001；JWT 会话不走此校验（RBAC 语义）';

SELECT 'inti.sql section 74 ES10-P-04 api_keys.scopes semantic DONE' AS done;

CREATE TABLE IF NOT EXISTS es_tenant_backfill_map (
    id          BIGSERIAL PRIMARY KEY,
    kind        VARCHAR(8)   NOT NULL,
    orig_name   VARCHAR(256) NOT NULL,
    new_name    VARCHAR(264) NOT NULL,
    tenant_id   BIGINT       NOT NULL,
    source      VARCHAR(16)  NOT NULL,
    ref_id      BIGINT,
    migrated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_es_tenant_backfill UNIQUE (kind, orig_name)
);

COMMENT ON TABLE  es_tenant_backfill_map            IS 'F-01 收口：租户回刷改名台账（m_003 脚本写入，(kind,orig_name) 幂等去重）';

COMMENT ON COLUMN es_tenant_backfill_map.kind       IS '文件目录类别：att=attachments / evi=evidence';

COMMENT ON COLUMN es_tenant_backfill_map.orig_name  IS '改名前磁盘文件名（无前缀存量）';

COMMENT ON COLUMN es_tenant_backfill_map.new_name   IS '改名后文件名 t<tenant>_<orig_name>';

COMMENT ON COLUMN es_tenant_backfill_map.tenant_id  IS '归属租户（引用行 tenant_id；孤儿=默认租户兜底）';

COMMENT ON COLUMN es_tenant_backfill_map.source     IS '归属判定来源：defect / report / orphan_default';

COMMENT ON COLUMN es_tenant_backfill_map.ref_id     IS '引用方行 ID（defects.id / reports.id；孤儿为 NULL）';

SELECT 'inti.sql section 75 F-01 tenant backfill ledger DONE' AS done;



-- 76.1 eval_runs：活动目的与血缘（运行即"测试活动"事实源，不新建活动主表）
ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS run_purpose VARCHAR(16) NOT NULL DEFAULT 'STANDARD';

COMMENT ON COLUMN eval_runs.run_purpose IS 'ES11：STANDARD 标准/REGRESSION 回归/RETEST 缺陷复测/TRACE_REPLAY 线上回流';

ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS parent_run_id BIGINT NULL;

COMMENT ON COLUMN eval_runs.parent_run_id IS 'ES11：来源运行（复测/回流指向原运行），软引用 eval_runs.id';

ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS baseline_run_id BIGINT NULL;

COMMENT ON COLUMN eval_runs.baseline_run_id IS 'ES11：对比基线运行，软引用 eval_runs.id';

CREATE INDEX IF NOT EXISTS ix_eval_runs_run_purpose ON eval_runs (run_purpose);

CREATE INDEX IF NOT EXISTS ix_eval_runs_parent_run_id ON eval_runs (parent_run_id) WHERE parent_run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_eval_runs_baseline_run_id ON eval_runs (baseline_run_id) WHERE baseline_run_id IS NOT NULL;



-- 76.2 eval_run_items：标准化题级证据（必须带 schema_version）
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS evidence_payload JSONB NULL;

COMMENT ON COLUMN eval_run_items.evidence_payload IS 'ES11：标准化证据 {schema_version,metrics,retrieval,citations,attack,tools,spans,failure_class}，schema 见开发方案附录 B';

ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS evidence_ref TEXT NULL;

COMMENT ON COLUMN eval_run_items.evidence_ref IS 'ES11：超大证据文件引用（签名 URL 相对路径），与 evidence_payload 互补';



-- 76.3 defects：来源与整改目标版本
ALTER TABLE defects ADD COLUMN IF NOT EXISTS origin_type VARCHAR(16) NOT NULL DEFAULT 'MANUAL';

COMMENT ON COLUMN defects.origin_type IS 'ES11：RUN_ITEM/REPORT/TRACE/SRC/MANUAL';

ALTER TABLE defects ADD COLUMN IF NOT EXISTS origin_id BIGINT NULL;

COMMENT ON COLUMN defects.origin_id IS 'ES11：来源实体 ID（按 origin_type 解释），软引用';

ALTER TABLE defects ADD COLUMN IF NOT EXISTS target_version_id BIGINT NULL;

COMMENT ON COLUMN defects.target_version_id IS 'ES11：当前整改目标项目版本，软引用 project_versions.id';

CREATE INDEX IF NOT EXISTS ix_defects_origin ON defects (origin_type, origin_id);

CREATE INDEX IF NOT EXISTS ix_defects_target_version ON defects (target_version_id) WHERE target_version_id IS NOT NULL;



-- 76.4 defect_events：缺陷闭环事件（只追加，禁止业务 UPDATE/DELETE）
CREATE TABLE IF NOT EXISTS defect_events (
    id                 BIGSERIAL PRIMARY KEY,
    defect_id          BIGINT NOT NULL,
    event_type         VARCHAR(24) NOT NULL,
    status_from        VARCHAR(16) NULL,
    status_to          VARCHAR(16) NULL,
    run_id             BIGINT NULL,
    project_version_id BIGINT NULL,
    note               TEXT NULL,
    evidence           JSONB NULL,
    actor_id           BIGINT NOT NULL,
    actor_name         VARCHAR(64) NULL,
    tenant_id          BIGINT NOT NULL DEFAULT 1,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE defect_events IS 'ES11：缺陷闭环审计事件，仅追加；CREATED/ASSIGNED/REMEDIATED/RETEST_STARTED/VERIFIED/REOPENED/WAIVED/CORRECTION';

COMMENT ON COLUMN defect_events.defect_id IS '软引用 defects.id（无物理外键，C1 约定）';

COMMENT ON COLUMN defect_events.run_id IS '复测运行，软引用 eval_runs.id';

COMMENT ON COLUMN defect_events.project_version_id IS '整改目标版本，软引用 project_versions.id';

COMMENT ON COLUMN defect_events.evidence IS '附件、变更引用、验证摘要、duty_unseparated 标记';

CREATE INDEX IF NOT EXISTS ix_defect_events_defect ON defect_events (defect_id, created_at);

CREATE INDEX IF NOT EXISTS ix_defect_events_tenant ON defect_events (tenant_id);



-- 76.5 traces：归属与处理轨迹
ALTER TABLE traces ADD COLUMN IF NOT EXISTS project_id BIGINT NULL;

COMMENT ON COLUMN traces.project_id IS 'ES11：归属项目，软引用 projects.id';

ALTER TABLE traces ADD COLUMN IF NOT EXISTS target_id BIGINT NULL;

COMMENT ON COLUMN traces.target_id IS 'ES11：被测系统，软引用 targets 表';

ALTER TABLE traces ADD COLUMN IF NOT EXISTS session_id VARCHAR(128) NULL;

COMMENT ON COLUMN traces.session_id IS 'ES11：会话聚合标识';

ALTER TABLE traces ADD COLUMN IF NOT EXISTS trace_payload JSONB NULL;

COMMENT ON COLUMN traces.trace_payload IS 'ES11：可选 spans/retrieval/tools 处理轨迹；无则界面显示"仅最终输入输出"';

CREATE INDEX IF NOT EXISTS ix_traces_project ON traces (project_id) WHERE project_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_traces_target ON traces (target_id) WHERE target_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_traces_session ON traces (session_id) WHERE session_id IS NOT NULL;

SELECT 'inti.sql section 76 ES11 closed-loop increment DONE' AS done;



-- 77.1 eval_runs：summary.needs_review（阻塞项-待复核）
CREATE INDEX IF NOT EXISTS ix_eval_runs_needs_review
    ON eval_runs (((summary ->> 'needs_review')))
    WHERE deleted_at IS NULL AND (summary ->> 'needs_review') = 'true';



-- 77.2 eval_runs：run_snapshot.target_mode（演示模式 INTERNAL_DEMO）
CREATE INDEX IF NOT EXISTS ix_eval_runs_target_mode_demo
    ON eval_runs (((run_snapshot ->> 'target_mode')))
    WHERE deleted_at IS NULL AND (run_snapshot ->> 'target_mode') = 'INTERNAL_DEMO';



-- 77.3 eval_runs：run_snapshot.is_baseline（workspace 基线回退查找；
--      代码写入恒为 'true'/'false' 两值，部分索引等值命中）
CREATE INDEX IF NOT EXISTS ix_eval_runs_is_baseline_true
    ON eval_runs (((run_snapshot ->> 'is_baseline')))
    WHERE deleted_at IS NULL AND (run_snapshot ->> 'is_baseline') = 'true';



-- 77.4 traces：SCORED 低分簇（scores.overall < 0.5，含 request 覆盖列；
--      scores 列实为 TEXT，表达式与代码侧 CAST(scores AS JSONB)->>'overall' 对齐）
CREATE INDEX IF NOT EXISTS ix_traces_low_score
    ON traces (( CAST(scores AS JSONB) ->> 'overall' ), request)
    WHERE eval_status = 'SCORED'
      AND (CAST(scores AS JSONB) ->> 'overall') IS NOT NULL
      AND CAST(CAST(scores AS JSONB) ->> 'overall' AS NUMERIC) < 0.5;

SELECT 'inti.sql section 77 ES11 JSONB perf indexes DONE' AS done;

CREATE INDEX IF NOT EXISTS ix_eval_runs_tenant_created
    ON eval_runs (tenant_id, created_at DESC)
    WHERE deleted_at IS NULL;

SELECT 'inti.sql section 77.5 eval_runs tenant+time index DONE' AS done;

CREATE INDEX IF NOT EXISTS ix_traces_low_score_tenant_time
    ON traces (tenant_id, occurred_at DESC, request)
    WHERE eval_status = 'SCORED'
      AND (CAST(scores AS JSONB) ->> 'overall') IS NOT NULL
      AND CAST(CAST(scores AS JSONB) ->> 'overall' AS NUMERIC) < 0.5;

SELECT 'inti.sql section 77.6 traces low-score tenant index DONE' AS done;



-- 78.3 本轮唯一 DDL（§11.2 / §10.2）：按子类聚合索引
--      现有 ix_items_stats(run_id, split, final_verdict) 无法支撑按子类聚合（F14）
--      三方同步：models.py EvalRunItem.__table_args__ 已并列声明同名 Index
CREATE INDEX IF NOT EXISTS ix_items_dim ON eval_run_items (run_id, category, final_verdict);

SELECT 'inti.sql section 78 GBT45654 bank_category dict + seeds + ix_items_dim DONE' AS done;

-- ============================================================================
-- 79. 结构同步补齐（2026-11-01 三方比对：models.py ↔ 实库 ↔ 本文件）
--     实库为运行事实源（models 有/实库缺列=0）；本节把 inti.sql 相对实库缺失的
--     列与独立索引一次补齐，全部 IF NOT EXISTS，幂等。
-- ============================================================================
-- 79.1 补列（按表分组）
ALTER TABLE community_usage_daily ADD COLUMN IF NOT EXISTS "usage_date" date NOT NULL;
ALTER TABLE community_usage_daily ADD COLUMN IF NOT EXISTS "cnt" integer NOT NULL;
ALTER TABLE community_usage_daily ADD COLUMN IF NOT EXISTS "created_at" timestamptz NOT NULL;
ALTER TABLE defect_sync_links ADD COLUMN IF NOT EXISTS "defect_id" bigint NOT NULL;
ALTER TABLE defect_sync_links ADD COLUMN IF NOT EXISTS "external_id" varchar(64) NOT NULL;
ALTER TABLE defect_sync_links ADD COLUMN IF NOT EXISTS "external_url" text NOT NULL;
ALTER TABLE defect_sync_links ADD COLUMN IF NOT EXISTS "sync_status" varchar(16) DEFAULT 'SYNCED'::character varying NOT NULL;
ALTER TABLE defect_sync_links ADD COLUMN IF NOT EXISTS "last_synced_at" timestamptz;
ALTER TABLE defect_sync_targets ADD COLUMN IF NOT EXISTS "name" varchar(128) NOT NULL;
ALTER TABLE defect_sync_targets ADD COLUMN IF NOT EXISTS "enabled" boolean DEFAULT true NOT NULL;
ALTER TABLE delivery_packages ADD COLUMN IF NOT EXISTS "items" jsonb DEFAULT '[]'::jsonb NOT NULL;
ALTER TABLE delivery_packages ADD COLUMN IF NOT EXISTS "standards_ver" varchar(32);
ALTER TABLE delivery_packages ADD COLUMN IF NOT EXISTS "status" varchar(16) DEFAULT 'building'::character varying NOT NULL;
ALTER TABLE delivery_packages ADD COLUMN IF NOT EXISTS "created_by" bigint;
ALTER TABLE discover_job_routes ADD COLUMN IF NOT EXISTS "tenant_id" integer DEFAULT 1 NOT NULL;
ALTER TABLE discover_jobs ADD COLUMN IF NOT EXISTS "project_id" integer NOT NULL;
ALTER TABLE discover_jobs ADD COLUMN IF NOT EXISTS "auth_type" varchar(16) DEFAULT 'USERPASS'::character varying NOT NULL;
ALTER TABLE discover_jobs ADD COLUMN IF NOT EXISTS "discover_mode" varchar(16) DEFAULT 'DISCOVER'::character varying NOT NULL;
ALTER TABLE discover_jobs ADD COLUMN IF NOT EXISTS "target_snapshot" jsonb DEFAULT '{}'::jsonb;
ALTER TABLE discover_jobs ADD COLUMN IF NOT EXISTS "progress_pct" integer DEFAULT 0 NOT NULL;
ALTER TABLE enterprise_licenses ADD COLUMN IF NOT EXISTS "payload_json" jsonb DEFAULT '{}'::jsonb NOT NULL;
ALTER TABLE enterprise_licenses ADD COLUMN IF NOT EXISTS "edition" varchar(16) DEFAULT 'enterprise'::character varying NOT NULL;
ALTER TABLE enterprise_licenses ADD COLUMN IF NOT EXISTS "features" jsonb DEFAULT '[]'::jsonb NOT NULL;
ALTER TABLE enterprise_licenses ADD COLUMN IF NOT EXISTS "machine_fp" varchar(64);
ALTER TABLE enterprise_licenses ADD COLUMN IF NOT EXISTS "status" varchar(16) DEFAULT 'ACTIVE'::character varying NOT NULL;
ALTER TABLE enterprise_licenses ADD COLUMN IF NOT EXISTS "tenant_id" integer DEFAULT 1 NOT NULL;
ALTER TABLE es8_tenant_migration_map ADD COLUMN IF NOT EXISTS "tenant_id" bigint NOT NULL;
ALTER TABLE es8_tenant_migration_map ADD COLUMN IF NOT EXISTS "migrated_at" timestamptz DEFAULT now() NOT NULL;
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS "question_id" bigint;
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS "bank_id" bigint;
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS "category" varchar(64);
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS "response_ref" text;
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS "rule_verdict" varchar(16);
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS "judge_verdict" varchar(16);
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS "final_verdict" varchar(16);
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS "verdict_reason" text;
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS "judge_seed" bigint;
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS "review_status" varchar(16) DEFAULT 'none'::character varying NOT NULL;
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS "reviewer_id" bigint;
ALTER TABLE eval_run_items ADD COLUMN IF NOT EXISTS "seq" integer DEFAULT 0 NOT NULL;
ALTER TABLE eval_set_revisions ADD COLUMN IF NOT EXISTS "version" integer NOT NULL;
ALTER TABLE eval_set_revisions ADD COLUMN IF NOT EXISTS "content" text NOT NULL;
ALTER TABLE eval_set_revisions ADD COLUMN IF NOT EXISTS "diff_stats" text;
ALTER TABLE eval_set_revisions ADD COLUMN IF NOT EXISTS "created_by" bigint;
ALTER TABLE eval_set_revisions ADD COLUMN IF NOT EXISTS "created_at" timestamptz DEFAULT now() NOT NULL;
ALTER TABLE fact_sources ADD COLUMN IF NOT EXISTS "status" varchar(16) DEFAULT 'active'::character varying NOT NULL;
ALTER TABLE global_refusal_rules ADD COLUMN IF NOT EXISTS "source" varchar(128) DEFAULT 'manual'::character varying NOT NULL;
ALTER TABLE global_refusal_rules ADD COLUMN IF NOT EXISTS "created_by" bigint;
ALTER TABLE global_refusal_rules ADD COLUMN IF NOT EXISTS "enabled" boolean DEFAULT true NOT NULL;
ALTER TABLE license_activations ADD COLUMN IF NOT EXISTS "result" varchar(16) NOT NULL;
ALTER TABLE license_activations ADD COLUMN IF NOT EXISTS "fail_reason" varchar(200);
ALTER TABLE menus ADD COLUMN IF NOT EXISTS "remark" varchar(256);
ALTER TABLE monitor_alerts ADD COLUMN IF NOT EXISTS "run_id" bigint;
ALTER TABLE monitor_alerts ADD COLUMN IF NOT EXISTS "metric" varchar(48) NOT NULL;
ALTER TABLE monitor_alerts ADD COLUMN IF NOT EXISTS "threshold" double precision NOT NULL;
ALTER TABLE monitor_alerts ADD COLUMN IF NOT EXISTS "op" varchar(4) NOT NULL;
ALTER TABLE monitor_alerts ADD COLUMN IF NOT EXISTS "state" varchar(16) NOT NULL;
ALTER TABLE monitor_alerts ADD COLUMN IF NOT EXISTS "fired_at" timestamptz NOT NULL;
ALTER TABLE monitors ADD COLUMN IF NOT EXISTS "org_id" bigint DEFAULT 0 NOT NULL;
ALTER TABLE monitors ADD COLUMN IF NOT EXISTS "name" varchar(128) NOT NULL;
ALTER TABLE monitors ADD COLUMN IF NOT EXISTS "cron" varchar(32) NOT NULL;
ALTER TABLE monitors ADD COLUMN IF NOT EXISTS "baseline_mode" varchar(16) DEFAULT 'LAST_RUN'::character varying NOT NULL;
ALTER TABLE monitors ADD COLUMN IF NOT EXISTS "baseline_metrics" text DEFAULT '{}'::text NOT NULL;
ALTER TABLE monitors ADD COLUMN IF NOT EXISTS "alert_conditions" text DEFAULT '[]'::text NOT NULL;
ALTER TABLE monitors ADD COLUMN IF NOT EXISTS "notify_rule_event" varchar(48) DEFAULT 'monitor.alert'::character varying NOT NULL;
ALTER TABLE monitors ADD COLUMN IF NOT EXISTS "last_checked_at" timestamptz;
ALTER TABLE monitors ADD COLUMN IF NOT EXISTS "next_fire_at" timestamptz;
ALTER TABLE monitors ADD COLUMN IF NOT EXISTS "created_by" bigint;
ALTER TABLE notify_channels ADD COLUMN IF NOT EXISTS "kind" varchar(16) NOT NULL;
ALTER TABLE notify_channels ADD COLUMN IF NOT EXISTS "name" varchar(128) NOT NULL;
ALTER TABLE notify_channels ADD COLUMN IF NOT EXISTS "enabled" boolean NOT NULL;
ALTER TABLE notify_channels ADD COLUMN IF NOT EXISTS "last_probe_ok" boolean;
ALTER TABLE notify_channels ADD COLUMN IF NOT EXISTS "created_by" bigint;
ALTER TABLE notify_deliveries ADD COLUMN IF NOT EXISTS "event" varchar(48) NOT NULL;
ALTER TABLE notify_deliveries ADD COLUMN IF NOT EXISTS "status" varchar(16) NOT NULL;
ALTER TABLE notify_deliveries ADD COLUMN IF NOT EXISTS "error" text;
ALTER TABLE notify_deliveries ADD COLUMN IF NOT EXISTS "attempts" integer DEFAULT 1 NOT NULL;
ALTER TABLE notify_deliveries ADD COLUMN IF NOT EXISTS "created_at" timestamptz NOT NULL;
ALTER TABLE notify_rules ADD COLUMN IF NOT EXISTS "scope" text;
ALTER TABLE notify_rules ADD COLUMN IF NOT EXISTS "channel_ids" text DEFAULT '[]'::text NOT NULL;
ALTER TABLE notify_rules ADD COLUMN IF NOT EXISTS "template_key" varchar(48);
ALTER TABLE notify_rules ADD COLUMN IF NOT EXISTS "min_severity" varchar(16) DEFAULT 'LOW'::character varying NOT NULL;
ALTER TABLE notify_rules ADD COLUMN IF NOT EXISTS "enabled" boolean NOT NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS "subscription_id" integer;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS "order_no" varchar(40) NOT NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS "plan_code" varchar(32) NOT NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS "billing_cycle" varchar(8) NOT NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS "amount_cents" integer NOT NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS "discount_cents" integer DEFAULT 0 NOT NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS "credit_deduct_cents" integer DEFAULT 0 NOT NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS "status" varchar(16) DEFAULT 'PENDING'::character varying NOT NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS "provider" varchar(16) DEFAULT 'mock'::character varying NOT NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS "provider_order_id" varchar(64);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS "paid_at" timestamptz;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS "created_at" timestamptz NOT NULL;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS "trade_no" varchar(64) NOT NULL;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS "provider" varchar(16) NOT NULL;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS "amount_cents" integer NOT NULL;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS "status" varchar(16) NOT NULL;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS "raw_notify" text;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS "created_at" timestamptz NOT NULL;
ALTER TABLE pii_rules ADD COLUMN IF NOT EXISTS "is_active" boolean DEFAULT true NOT NULL;
ALTER TABLE question ADD COLUMN IF NOT EXISTS "seq" integer DEFAULT 0 NOT NULL;
ALTER TABLE question ADD COLUMN IF NOT EXISTS "category" varchar(64) NOT NULL;
ALTER TABLE question ADD COLUMN IF NOT EXISTS "sub_category" varchar(64);
ALTER TABLE question ADD COLUMN IF NOT EXISTS "split" varchar(16) DEFAULT 'ANSWER'::character varying NOT NULL;
ALTER TABLE question ADD COLUMN IF NOT EXISTS "expected_answer" text;
ALTER TABLE question ADD COLUMN IF NOT EXISTS "language" varchar(16) DEFAULT 'zh-CN'::character varying NOT NULL;
ALTER TABLE question ADD COLUMN IF NOT EXISTS "sensitivity" varchar(16) DEFAULT 'internal'::character varying NOT NULL;
ALTER TABLE question ADD COLUMN IF NOT EXISTS "tags" jsonb DEFAULT '[]'::jsonb NOT NULL;
ALTER TABLE question ADD COLUMN IF NOT EXISTS "text" text NOT NULL;
ALTER TABLE question ADD COLUMN IF NOT EXISTS "created_at" timestamptz NOT NULL;
ALTER TABLE question_bank ADD COLUMN IF NOT EXISTS "bank_version" varchar(32) DEFAULT '1.0.0'::character varying NOT NULL;
ALTER TABLE question_bank ADD COLUMN IF NOT EXISTS "is_builtin" boolean DEFAULT false NOT NULL;
ALTER TABLE question_bank ADD COLUMN IF NOT EXISTS "status" varchar(16) DEFAULT 'active'::character varying NOT NULL;
ALTER TABLE question_bank ADD COLUMN IF NOT EXISTS "created_by" bigint;
ALTER TABLE question_import_job ADD COLUMN IF NOT EXISTS "file_path" text NOT NULL;
ALTER TABLE question_import_job ADD COLUMN IF NOT EXISTS "total_rows" integer DEFAULT 0 NOT NULL;
ALTER TABLE question_import_job ADD COLUMN IF NOT EXISTS "status" varchar(16) DEFAULT 'pending'::character varying NOT NULL;
ALTER TABLE question_import_job ADD COLUMN IF NOT EXISTS "created_by" bigint;
ALTER TABLE retention_policies ADD COLUMN IF NOT EXISTS "days" integer NOT NULL;
ALTER TABLE retention_policies ADD COLUMN IF NOT EXISTS "created_at" timestamptz NOT NULL;
ALTER TABLE review_items ADD COLUMN IF NOT EXISTS "source" varchar(16) NOT NULL;
ALTER TABLE review_items ADD COLUMN IF NOT EXISTS "source_ref" text NOT NULL;
ALTER TABLE review_items ADD COLUMN IF NOT EXISTS "context" text DEFAULT '{}'::text NOT NULL;
ALTER TABLE review_items ADD COLUMN IF NOT EXISTS "auto_verdict" varchar(24);
ALTER TABLE review_items ADD COLUMN IF NOT EXISTS "auto_confidence" real;
ALTER TABLE review_items ADD COLUMN IF NOT EXISTS "status" varchar(16) DEFAULT 'OPEN'::character varying NOT NULL;
ALTER TABLE review_items ADD COLUMN IF NOT EXISTS "assignee_id" bigint;
ALTER TABLE review_items ADD COLUMN IF NOT EXISTS "human_verdict" varchar(24);
ALTER TABLE review_items ADD COLUMN IF NOT EXISTS "human_note" text;
ALTER TABLE review_items ADD COLUMN IF NOT EXISTS "created_at" timestamptz DEFAULT now() NOT NULL;
ALTER TABLE sca_components ADD COLUMN IF NOT EXISTS "tenant_id" integer NOT NULL;
ALTER TABLE sca_components ADD COLUMN IF NOT EXISTS "name" varchar(256) NOT NULL;
ALTER TABLE sca_components ADD COLUMN IF NOT EXISTS "version" varchar(64);
ALTER TABLE sca_components ADD COLUMN IF NOT EXISTS "license_name" varchar(128);
ALTER TABLE sca_components ADD COLUMN IF NOT EXISTS "direct" boolean NOT NULL;
ALTER TABLE sca_components ADD COLUMN IF NOT EXISTS "dependency_path" varchar(1000);
ALTER TABLE sca_components ADD COLUMN IF NOT EXISTS "cve_count" integer NOT NULL;
ALTER TABLE sca_vulnerabilities ADD COLUMN IF NOT EXISTS "tenant_id" integer NOT NULL;
ALTER TABLE sca_vulnerabilities ADD COLUMN IF NOT EXISTS "component_id" integer NOT NULL;
ALTER TABLE sca_vulnerabilities ADD COLUMN IF NOT EXISTS "component_name" varchar(256) NOT NULL;
ALTER TABLE sca_vulnerabilities ADD COLUMN IF NOT EXISTS "description" text;
ALTER TABLE sca_vulnerabilities ADD COLUMN IF NOT EXISTS "fixed_version" varchar(64);
ALTER TABLE sca_vulnerabilities ADD COLUMN IF NOT EXISTS "references" jsonb NOT NULL;
ALTER TABLE sca_vulnerabilities ADD COLUMN IF NOT EXISTS "created_at" timestamptz NOT NULL;
ALTER TABLE src_findings ADD COLUMN IF NOT EXISTS "tenant_id" integer NOT NULL;
ALTER TABLE src_findings ADD COLUMN IF NOT EXISTS "rule_ref" varchar(128) NOT NULL;
ALTER TABLE src_findings ADD COLUMN IF NOT EXISTS "rule_name" varchar(256) NOT NULL;
ALTER TABLE src_findings ADD COLUMN IF NOT EXISTS "line_start" integer NOT NULL;
ALTER TABLE src_findings ADD COLUMN IF NOT EXISTS "message" text NOT NULL;
ALTER TABLE src_findings ADD COLUMN IF NOT EXISTS "code_snippet" text;
ALTER TABLE src_findings ADD COLUMN IF NOT EXISTS "created_at" timestamptz NOT NULL;
ALTER TABLE src_rules ADD COLUMN IF NOT EXISTS "tenant_id" integer NOT NULL;
ALTER TABLE src_rules ADD COLUMN IF NOT EXISTS "name" varchar(256) NOT NULL;
ALTER TABLE src_rules ADD COLUMN IF NOT EXISTS "description" text;
ALTER TABLE src_rules ADD COLUMN IF NOT EXISTS "language" varchar(32) NOT NULL;
ALTER TABLE src_rules ADD COLUMN IF NOT EXISTS "category" varchar(64) NOT NULL;
ALTER TABLE src_rules ADD COLUMN IF NOT EXISTS "rule_type" varchar(16) NOT NULL;
ALTER TABLE src_rules ADD COLUMN IF NOT EXISTS "pattern" text NOT NULL;
ALTER TABLE src_rules ADD COLUMN IF NOT EXISTS "cwe_id" varchar(32);
ALTER TABLE src_rules ADD COLUMN IF NOT EXISTS "enabled" boolean NOT NULL;
ALTER TABLE src_scan_tasks ADD COLUMN IF NOT EXISTS "tenant_id" integer NOT NULL;
ALTER TABLE src_scan_tasks ADD COLUMN IF NOT EXISTS "name" varchar(256) NOT NULL;
ALTER TABLE src_scan_tasks ADD COLUMN IF NOT EXISTS "source_type" varchar(16) NOT NULL;
ALTER TABLE src_scan_tasks ADD COLUMN IF NOT EXISTS "source_url" varchar(1000);
ALTER TABLE src_scan_tasks ADD COLUMN IF NOT EXISTS "workdir" varchar(1000);
ALTER TABLE src_scan_tasks ADD COLUMN IF NOT EXISTS "commit_hash" varchar(64);
ALTER TABLE src_scan_tasks ADD COLUMN IF NOT EXISTS "total_files" integer NOT NULL;
ALTER TABLE src_scan_tasks ADD COLUMN IF NOT EXISTS "error_message" text;
ALTER TABLE src_scan_tasks ADD COLUMN IF NOT EXISTS "started_at" timestamptz;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS "plan_code" varchar(32) NOT NULL;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS "status" varchar(16) DEFAULT 'TRIALING'::character varying NOT NULL;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS "billing_cycle" varchar(8) DEFAULT 'monthly'::character varying NOT NULL;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS "trial_ends_at" timestamptz;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS "created_at" timestamptz NOT NULL;
ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS "description" varchar(256);
ALTER TABLE target_registry ADD COLUMN IF NOT EXISTS "name" varchar(128) NOT NULL;
ALTER TABLE target_registry ADD COLUMN IF NOT EXISTS "target_type" varchar(16) NOT NULL;
ALTER TABLE target_registry ADD COLUMN IF NOT EXISTS "base_url" varchar(512) NOT NULL;
ALTER TABLE target_registry ADD COLUMN IF NOT EXISTS "chat_path" varchar(256) DEFAULT '/chat/completions'::character varying;
ALTER TABLE target_registry ADD COLUMN IF NOT EXISTS "protocol" varchar(16) DEFAULT 'OPENAI'::character varying NOT NULL;
ALTER TABLE target_registry ADD COLUMN IF NOT EXISTS "auth_env" varchar(64);
ALTER TABLE target_registry ADD COLUMN IF NOT EXISTS "headers" jsonb;
ALTER TABLE target_registry ADD COLUMN IF NOT EXISTS "request_template" jsonb;
ALTER TABLE target_registry ADD COLUMN IF NOT EXISTS "response_path" varchar(128);
ALTER TABLE target_registry ADD COLUMN IF NOT EXISTS "timeout_sec" integer DEFAULT 30 NOT NULL;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "name" varchar(128) NOT NULL;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "contact_email" varchar(256);
ALTER TABLE trace_policies ADD COLUMN IF NOT EXISTS "sample_rate" double precision DEFAULT 0.1 NOT NULL;
ALTER TABLE trace_policies ADD COLUMN IF NOT EXISTS "judge_metrics" text DEFAULT '["pii_leak","injection","hallucination"]'::text NOT NULL;
ALTER TABLE trace_policies ADD COLUMN IF NOT EXISTS "daily_cap" integer DEFAULT 2000 NOT NULL;
ALTER TABLE trace_policies ADD COLUMN IF NOT EXISTS "low_score_threshold" double precision DEFAULT 0.6 NOT NULL;
ALTER TABLE trace_policies ADD COLUMN IF NOT EXISTS "created_at" timestamptz NOT NULL;
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "source" varchar(16) NOT NULL;
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "external_ref" varchar(64);
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "request" text NOT NULL;
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "response" text NOT NULL;
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "model" varchar(64);
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "tokens" integer;
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "latency_ms" integer;
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "status" varchar(16);
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "occurred_at" timestamptz NOT NULL;
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "eval_status" varchar(16) DEFAULT 'PENDING'::character varying NOT NULL;
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "scores" text DEFAULT '{}'::text NOT NULL;
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "reviewed" boolean DEFAULT false NOT NULL;
ALTER TABLE traces ADD COLUMN IF NOT EXISTS "created_at" timestamptz NOT NULL;
-- 79.2 补独立索引（pg_indexes 中本文件未声明的 CREATE INDEX）
CREATE INDEX IF NOT EXISTS ix_asset_versions_tenant_id ON asset_versions USING btree (tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_payments_trade_no ON payments USING btree (trade_no);
CREATE INDEX IF NOT EXISTS ix_retention_policies_tenant_id ON retention_policies USING btree (tenant_id);
CREATE INDEX IF NOT EXISTS ix_asset_versions_asset_id ON asset_versions USING btree (asset_id);
CREATE INDEX IF NOT EXISTS ix_asset_versions_project_version_id ON asset_versions USING btree (project_version_id);
CREATE INDEX IF NOT EXISTS idx_djr_deleted ON discover_job_routes USING btree (deleted_at);
CREATE UNIQUE INDEX IF NOT EXISTS ix_orders_order_no ON orders USING btree (order_no);
CREATE INDEX IF NOT EXISTS ix_asset_versions_project_id ON asset_versions USING btree (project_id);
CREATE INDEX IF NOT EXISTS ix_sso_configs_tenant_id ON sso_configs USING btree (tenant_id);
SELECT 'inti.sql section 79 structure sync DONE' AS done;
COMMIT;
