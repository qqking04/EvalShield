-- ============================================================
-- P1 AI 检测精度升级：全部 DDL（幂等，可重复执行）
-- 执行：psql -U EvalShield -d EvalShield -f backend/scripts/p1_ddl.sql
-- ============================================================

-- 1) model_configs.usage（模块 1 embedding 配置标记）
ALTER TABLE model_configs
    ADD COLUMN IF NOT EXISTS usage VARCHAR(16) NOT NULL DEFAULT 'CHAT';
COMMENT ON COLUMN model_configs.usage IS 'CHAT=对话模型 / EMBEDDING=文本向量模型';
UPDATE model_configs SET usage = 'CHAT' WHERE usage IS NULL;

-- 2) D-13 幻觉检测嵌入向量落库表（可选）
CREATE TABLE IF NOT EXISTS hallucination_embeddings (
    id               SERIAL PRIMARY KEY,
    embedding_no     VARCHAR(32) UNIQUE NOT NULL,
    task_no          VARCHAR(32) NOT NULL,
    step_no          VARCHAR(32) NOT NULL,
    item_no          VARCHAR(32) NOT NULL,
    prompt           TEXT,
    prompt_embedding JSON,
    ref_embedding    JSON,
    model_name       VARCHAR(128),
    dim              INTEGER,
    score            FLOAT,
    severity         VARCHAR(16),
    tenant_id        INTEGER DEFAULT 1,
    created_by       INTEGER,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    deleted_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_hallu_task ON hallucination_embeddings(task_no);
CREATE INDEX IF NOT EXISTS idx_hallu_tenant ON hallucination_embeddings(tenant_id);

-- 3) D-14 RAGAS 三指标评测明细表
CREATE TABLE IF NOT EXISTS ragas_metric_records (
    id                 SERIAL PRIMARY KEY,
    ragas_no           VARCHAR(32) UNIQUE NOT NULL,
    task_no            VARCHAR(32) NOT NULL,
    step_no            VARCHAR(32) NOT NULL,
    item_no            VARCHAR(32) NOT NULL,
    faithfulness       FLOAT,
    answer_relevance   FLOAT,
    context_recall     FLOAT,
    ragas_score        FLOAT,
    grade              VARCHAR(16),
    retrieval_recall   FLOAT,
    retrieval_precision FLOAT,
    judge_rationale    JSON DEFAULT '{}',
    tenant_id          INTEGER DEFAULT 1,
    created_by         INTEGER,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW(),
    deleted_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ragas_task ON ragas_metric_records(task_no);
CREATE INDEX IF NOT EXISTS idx_ragas_tenant ON ragas_metric_records(tenant_id);

-- 4) D-15 多轮一致性测试会话轨迹表
CREATE TABLE IF NOT EXISTS conversation_traces (
    id                  SERIAL PRIMARY KEY,
    trace_no            VARCHAR(32) UNIQUE NOT NULL,
    task_no             VARCHAR(32) NOT NULL,
    step_no             VARCHAR(32) NOT NULL,
    session_no          VARCHAR(32) NOT NULL,
    session_topic       VARCHAR(255),
    rounds              INTEGER DEFAULT 0,
    contradiction_count INTEGER DEFAULT 0,
    resolve_count       INTEGER DEFAULT 0,
    context_drift_score FLOAT DEFAULT 1.0,
    consistency_score   FLOAT DEFAULT 1.0,
    status              VARCHAR(16),
    dialog_json         JSON DEFAULT '[]',
    contradiction_log   JSON DEFAULT '[]',
    tenant_id           INTEGER DEFAULT 1,
    created_by          INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_trace_task ON conversation_traces(task_no);
CREATE INDEX IF NOT EXISTS idx_trace_session ON conversation_traces(session_no);
CREATE INDEX IF NOT EXISTS idx_trace_tenant ON conversation_traces(tenant_id);

-- 5) D-16-1 动态法规库（伦理合规）
CREATE TABLE IF NOT EXISTS ethic_regulations (
    id               SERIAL PRIMARY KEY,
    regulation_no    VARCHAR(32) NOT NULL,
    regulation_name  VARCHAR(255) NOT NULL,
    version          VARCHAR(32) NOT NULL,
    effective_date   TIMESTAMPTZ NOT NULL,
    clauses          JSON DEFAULT '[]',
    region           VARCHAR(32) DEFAULT 'CN',
    global           BOOLEAN DEFAULT FALSE,
    status           VARCHAR(16) DEFAULT 'ACTIVE',
    tenant_id        INTEGER DEFAULT 1,
    created_by       INTEGER,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    deleted_at       TIMESTAMPTZ,
    UNIQUE(regulation_no, version)
);
CREATE INDEX IF NOT EXISTS idx_ethic_reg_no ON ethic_regulations(regulation_no);
CREATE INDEX IF NOT EXISTS idx_ethic_eff_date ON ethic_regulations(effective_date);
CREATE INDEX IF NOT EXISTS idx_ethic_tenant ON ethic_regulations(tenant_id);

-- 6) D-16-2 伦理审计明细
CREATE TABLE IF NOT EXISTS ethic_audit_records (
    id                  SERIAL PRIMARY KEY,
    audit_no            VARCHAR(32) UNIQUE NOT NULL,
    task_no             VARCHAR(32) NOT NULL,
    step_no             VARCHAR(32) NOT NULL,
    item_no             VARCHAR(32) NOT NULL,
    regulation_no       VARCHAR(32),
    regulation_version  VARCHAR(32),
    overall_severity    VARCHAR(16),
    compliance_score    FLOAT,
    violations          JSON DEFAULT '[]',
    scores_json         JSON DEFAULT '{}',
    tenant_id           INTEGER DEFAULT 1,
    created_by          INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ethic_audit_task ON ethic_audit_records(task_no);
CREATE INDEX IF NOT EXISTS idx_ethic_audit_tenant ON ethic_audit_records(tenant_id);
