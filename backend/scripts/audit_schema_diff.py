# -*- coding: utf-8 -*-
"""一次性审计：SQLAlchemy 模型列 vs PostgreSQL 实际列。

用法：在 backend 容器内执行：python scripts/audit_schema_diff.py
产出：缺失列（→ 需要 ALTER TABLE 补）、孤儿列（→ 模型里没声明）、缺表清单。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import Base, engine  # noqa: E402
from app import models  # noqa: E402,F401  —— 强制导入以注册全部 ORM 模型


def main() -> int:
    # 期望：全部 ORM 模型声明的列
    expected: dict[str, list[str]] = {}
    for mapper in Base.registry.mappers:
        tbl = mapper.mapper.class_.__tablename__
        expected[tbl] = sorted({c.name for c in mapper.mapper.columns})

    # 实际：数据库里每个表的列（排除视图）
    with Session(engine) as session:
        rows = session.execute(
            text(
                """
                SELECT c.table_name, c.column_name
                FROM information_schema.columns c
                JOIN information_schema.tables t
                  ON t.table_schema = c.table_schema AND t.table_name = c.table_name
                WHERE c.table_schema = 'public'
                  AND t.table_type = 'BASE TABLE'
                ORDER BY c.table_name, c.ordinal_position
                """
            )
        ).fetchall()

    actual: dict[str, list[str]] = {}
    for t, c in rows:
        actual.setdefault(t, []).append(c)

    report = []
    for tbl, exp_cols in sorted(expected.items()):
        act = set(actual.get(tbl, []))
        exp = set(exp_cols)
        missing = sorted(exp - act)
        orphan = sorted(act - exp)
        if missing or orphan or tbl not in actual:
            report.append(
                {
                    "table": tbl,
                    "in_db": tbl in actual,
                    "model_cols": len(exp_cols),
                    "db_cols": len(actual.get(tbl, [])),
                    "missing": missing,
                    "orphan": orphan,
                }
            )

    print(
        json.dumps(
            {
                "tables_in_model": sorted(expected.keys()),
                "tables_in_db": sorted(actual.keys()),
                "issues": report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
