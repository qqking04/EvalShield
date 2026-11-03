# -*- coding: utf-8 -*-
"""简化版：列出所有表 + 查乱码。"""
import sys
sys.path.insert(0, "/app")
from app.database import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    tables = db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).fetchall()
    print("=== 所有表 ===")
    for (t,) in tables:
        print(f"  {t}")

    print("\n=== 乱码行扫描（只查存在的表 + 带 name/title/text 字段）===")
    for (tbl,) in tables:
        try:
            cols = db.execute(text(f"SELECT column_name FROM information_schema.columns WHERE table_name='{tbl}' AND data_type IN ('text','character varying') ORDER BY ordinal_position")).fetchall()
            for (col,) in cols:
                try:
                    rows = db.execute(text(
                        f"SELECT id, {col} FROM {tbl} WHERE CAST({col} AS text) LIKE '%??%' LIMIT 5"
                    )).fetchall()
                    for r in rows:
                        print(f"[乱码] {tbl}.{col} id={r[0]} val={r[1]!r}")
                except Exception:
                    pass
        except Exception:
            pass
