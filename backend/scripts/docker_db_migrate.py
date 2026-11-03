# -*- coding: utf-8 -*-
"""Docker 库结构对齐：幂等补齐 billing_quotas / model_configs 缺失列。

用法（在 backend 容器内执行）：
    python scripts/docker_db_migrate.py
仅执行 ADD COLUMN IF NOT EXISTS，不破坏已有数据。
"""

from __future__ import annotations

import sys

from sqlalchemy import text
from sqlalchemy.engine import create_engine
from sqlalchemy.orm import Session

# 与 app/database.py 相同的环境读取方式
import os

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "EvalShield")
DB_USER = os.environ.get("DB_USER", "EvalShield")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "EvalShield")

URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

STATEMENTS = [
    # billing_quotas：token 预算列
    "ALTER TABLE billing_quotas ADD COLUMN IF NOT EXISTS "
    "token_budget BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE billing_quotas ADD COLUMN IF NOT EXISTS "
    "token_used BIGINT NOT NULL DEFAULT 0",
    # model_configs：价格列
    "ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS "
    "input_price_per_mtok FLOAT NOT NULL DEFAULT 0.0",
    "ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS "
    "output_price_per_mtok FLOAT NOT NULL DEFAULT 0.0",
    "ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS "
    "deleted_at TIMESTAMPTZ NULL DEFAULT NULL",
    "ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS "
    "is_system BOOLEAN NOT NULL DEFAULT FALSE",
    # audit_logs：校验链字段（Hash-chain 完整性校验）
    "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64)",
    "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS self_hash VARCHAR(64)",
    "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS chain_index INTEGER",
    "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ",
    # model_configs：模型用途（CHAT/EMBEDDING，embedding 引擎代码依赖此列）
    "ALTER TABLE model_configs ADD COLUMN IF NOT EXISTS "
    "usage VARCHAR(16) NOT NULL DEFAULT 'CHAT'",
    # heal_records：自愈记录增量列（软删除 + 更新时间）
    "ALTER TABLE heal_records ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    "ALTER TABLE heal_records ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL DEFAULT NULL",
    # test_cases：测试用例功能优化五段式结构列
    "ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS content_schema JSONB",
    "ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS preconditions JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS test_data JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS assertions JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS extract_vars JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS post_cleanup JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS requirement_id VARCHAR(64)",
    # eval_sets：条目 content_schema（EVAL/安全样本等条目结构描述）
    "ALTER TABLE eval_sets ADD COLUMN IF NOT EXISTS content_schema JSONB",
    # test_datasets：参数列定义 + 数据行定义（数据驱动测试）
    "ALTER TABLE test_datasets ADD COLUMN IF NOT EXISTS "
    "parameters JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE test_datasets ADD COLUMN IF NOT EXISTS "
    "data_rows JSONB NOT NULL DEFAULT '[]'::jsonb",
]

# 存量列宽修正（需先查 information_schema 再 ALTER，不能 IF NOT EXISTS）
COLUMN_WIDTH_FIXES = [
    # (表, 列, 目标长度)：llm_cache_entries.cache_key 历史 DDL 为 varchar(64)，
    # 与 models.py/inti.sql 的 128 不一致导致缓存写入静默失败（同 backend/migrations/m_002）
    ("llm_cache_entries", "cache_key", 128),
]


def main() -> int:
    engine = create_engine(URL)
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            try:
                conn.execute(text(stmt))
                print(f"[OK] {stmt.splitlines()[0][:80]}")
            except Exception as exc:  # noqa: BLE001
                print(f"[SKIP] {stmt.splitlines()[0][:60]} -> {exc}")
        for tbl, col, width in COLUMN_WIDTH_FIXES:
            cur = conn.execute(
                text(
                    "SELECT character_maximum_length FROM information_schema.columns "
                    "WHERE table_name=:t AND column_name=:c"
                ),
                {"t": tbl, "c": col},
            ).fetchone()
            if cur is None:
                print(f"[SKIP] {tbl}.{col} 不存在（新库由 inti.sql 保证）")
            elif cur[0] is not None and cur[0] < width:
                conn.execute(text(
                    f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE VARCHAR({width})"
                ))
                print(f"[OK] {tbl}.{col}: VARCHAR({cur[0]}) -> VARCHAR({width})")
            else:
                print(f"[OK] {tbl}.{col} 已 >= VARCHAR({width})")
    # 校验
    with Session(engine) as session:
        for tbl, colss in (
            ("billing_quotas", ["token_budget", "token_used"]),
            ("model_configs", ["input_price_per_mtok", "output_price_per_mtok"]),
        ):
            rows = session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name=:t"
                ),
                {"t": tbl},
            ).fetchall()
            cols = {r[0] for r in rows}
            missing = [c for c in colss if c not in cols]
            print(f"{tbl}: {len(cols)} columns | missing={missing or 'NONE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
