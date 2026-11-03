"""idempotent 迁移：llm_cache_entries.cache_key 列宽扩至 VARCHAR(128)

背景：运行库历史 DDL 为 VARCHAR(64)，与 models.py / inti.sql 的 String(128) 不一致，
build_cache_key 含 namespace 前缀（73 字符）导致缓存写入 StringDataRightTruncation 静默失败。

执行：python backend/migrations/m_002_cache_key_width.py
"""
import sys; sys.path.insert(0, r"e:\code\EvalShield\backend")
from app.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

print("=" * 60)
print("MIGRATION: m_002_cache_key_width (llm_cache_entries.cache_key -> VARCHAR(128))")
print("=" * 60)

row = db.execute(text("""
    SELECT character_maximum_length
    FROM information_schema.columns
    WHERE table_name = 'llm_cache_entries' AND column_name = 'cache_key'
""")).fetchone()

if row is None:
    print("⚠️  llm_cache_entries.cache_key 不存在（表可能未初始化），跳过；新库由 database/inti.sql 保证 128")
elif row[0] is not None and row[0] >= 128:
    print(f"✅ 已是 VARCHAR({row[0]})，无需迁移")
else:
    db.execute(text(
        "ALTER TABLE llm_cache_entries ALTER COLUMN cache_key TYPE VARCHAR(128)"
    ))
    db.commit()
    print(f"✅ 迁移完成：VARCHAR({row[0]}) -> VARCHAR(128)")

db.close()
