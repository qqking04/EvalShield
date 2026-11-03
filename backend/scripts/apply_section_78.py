# -*- coding: utf-8 -*-
"""一次性执行 inti.sql section 78（优化12 T4 应用到运行库，幂等）。

python backend/scripts/apply_section_78.py [--dry-run]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

INTI = REPO / "database" / "inti.sql"


def extract_section(text: str, header: str = "78. ") -> str:
    """截取 section 78 BEGIN..COMMIT 语句体（不含外层 BEGIN/COMMIT 拆分执行）。"""
    m = re.search(r"^-- 78\. ", text, re.MULTILINE)
    if not m:
        raise SystemExit("section 78 not found in inti.sql")
    tail = text[m.start():]
    begin = tail.index("BEGIN;")
    commit = tail.index("COMMIT;")
    body = tail[begin + len("BEGIN;"):commit]
    return body


def main() -> int:
    dry = "--dry-run" in sys.argv
    text = INTI.read_text(encoding="utf-8")
    body = extract_section(text)
    from sqlalchemy import create_engine, text as sa_text
    from app.config import settings

    eng = create_engine(settings.DATABASE_URL, connect_args={"connect_timeout": 5})
    with eng.begin() as conn:  # 单事务，与 section 语义一致
        for stmt in [s.strip() for s in body.split(";") if s.strip()]:
            if dry:
                print(stmt[:80].replace("\n", " ") + " ...")
                continue
            conn.execute(sa_text(stmt))
    eng.dispose()
    print("[OK] section 78 applied (dry-run)" if dry else "[OK] section 78 applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
