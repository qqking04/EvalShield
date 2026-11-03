# -*- coding: utf-8 -*-
"""清理乱码种子行（写回正确的中文内容）。"""
import sys
sys.path.insert(0, "/app")
from app.database import SessionLocal
from sqlalchemy import text

fixes = [
    # test_cases
    ("UPDATE test_cases SET title='提示注入-忽略指令' WHERE id=2 AND title LIKE '%??%'",),
    ("UPDATE test_cases SET expected='页面应显示 Example Domain，且无异常弹窗' WHERE id=2 AND expected LIKE '%??%'",),
    # reports
    ("UPDATE reports SET title='提示注入-UI测试 测试报告' WHERE id IN (5,6) AND title LIKE '%??%'",),
    # test_tasks
    ("UPDATE test_tasks SET name='提示注入-UI测试' WHERE id=5 AND name LIKE '%??%'",),
    # billing_records
    ("UPDATE billing_records SET description='任务执行：提示注入-UI测试' WHERE id IN (5,6) AND description LIKE '%??%'",),
    # test_suites / project_versions → 直接更新为测试/基线描述
    ("UPDATE test_suites SET name='回归测试套件（Demo）' WHERE id=1 AND name LIKE '%??%'",),
    ("UPDATE project_versions SET description='v1.0 首次基线' WHERE id=1 AND description LIKE '%??%'",),
    ("UPDATE project_versions SET description='v1.0.1 bug 修复' WHERE id=2 AND description LIKE '%??%'",),
    ("UPDATE project_versions SET description='v1.1 功能迭代' WHERE id=3 AND description LIKE '%??%'",),
]

with SessionLocal() as db:
    for (sql,) in fixes:
        try:
            r = db.execute(text(sql))
            db.commit()
            print(f"OK  ({r.rowcount} rows) {sql[:70]}")
        except Exception as e:
            db.rollback()
            print(f"FAIL {sql[:60]}: {e}")

print("\n=== 扫描剩余乱码 ===")
with SessionLocal() as db:
    for tbl, col in [("test_cases","title"),("reports","title"),("test_tasks","name"),
                     ("billing_records","description"),("test_suites","name"),("project_versions","description")]:
        try:
            rows = db.execute(text(f"SELECT id, {col} FROM {tbl} WHERE {col} LIKE '%??%'" )).fetchall()
            for r in rows:
                print(f"  [残留] {tbl}.{col} id={r[0]} val={r[1]!r}")
            if not rows:
                print(f"  ✓ {tbl}.{col} 已清理干净")
        except Exception as e:
            print(f"  ? {tbl}.{col}: {e}")
