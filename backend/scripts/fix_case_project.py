# -*- coding: utf-8 -*-
"""修 test_cases.project_id 关联到真实存在的项目 + 验证码处理。"""
import sys
sys.path.insert(0, "/app")
from app.database import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    # 1) 查最小有效 project_id
    pid = db.execute(text("SELECT min(id) FROM projects WHERE deleted_at IS NULL")).fetchone()[0]
    print(f"当前最小有效 project_id: {pid}")
    # 2) 修 test_cases
    r = db.execute(text(f"UPDATE test_cases SET project_id={pid} WHERE project_id NOT IN (SELECT id FROM projects WHERE deleted_at IS NULL)"))
    db.commit()
    print(f"修正 test_cases.project_id：{r.rowcount} 行")
    # 3) 验证
    rows = db.execute(text(f"SELECT id, project_id, title FROM test_cases")).fetchall()
    for r2 in rows:
        print(f"  test_cases.id={r2[0]} project_id={r2[1]} title={r2[2]!r}")
