# -*- coding: utf-8 -*-
"""确保所有 test_cases 关联到有效的最近项目（让下拉框不会空）。"""
import sys
sys.path.insert(0, "/app")
from app.database import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    # 1) 所有 projects（含 deleted）
    all_projs = db.execute(text("SELECT id, code, name, tenant_id FROM projects ORDER BY id DESC LIMIT 5")).fetchall()
    print("=== 项目列表（前5）===")
    for p in all_projs: print(f"  id={p[0]} code={p[1]} tenant={p[3]}")

    # 2) 让所有 case 都关联到项目 id=1（最新有效）
    db.execute(text("UPDATE test_cases SET project_id=1 WHERE project_id NOT IN (SELECT id FROM projects)"))
    db.commit()

    # 3) 再检查 cases
    cases = db.execute(text("SELECT id, project_id, title, category FROM test_cases")).fetchall()
    print(f"\n=== test_cases（{len(cases)}条）===")
    for c in cases:
        print(f"  id={c[0]} pid={c[1]} cat={c[3]} title={c[2]!r}")

    # 4) 确保至少有 1 条 UI_TEST 类别 + 1 条 API_TEST 类别（让每个引擎的下拉都能选到）
    cats = {c[3] for c in cases}
    print(f"\n已覆盖类别: {cats}")
    if "UI" not in cats:
        db.execute(text("INSERT INTO test_cases (case_no, title, category, project_id, tenant_id, creator, request_spec, steps, created_at) VALUES ('UI-AUTO-1', 'UI自动登录演示', 'UI', 1, 1, 'admin', '{}', '[]', now())"))
        print("✓ 补了 1 条 UI 用例")
    if "API" not in cats:
        db.execute(text("INSERT INTO test_cases (case_no, title, category, project_id, tenant_id, creator, request_spec, created_at) VALUES ('API-AUTO-1', 'API健康检查', 'API', 1, 1, 'admin', '{\"method\":\"GET\",\"path\":\"/api/health\"}', now())"))
        print("✓ 补了 1 条 API 用例")
    db.commit()

    # 5) 最终验证
    cases2 = db.execute(text("SELECT id, project_id, title, category FROM test_cases")).fetchall()
    print(f"\n=== 最终 test_cases（{len(cases2)}条）===")
    for c in cases2:
        print(f"  id={c[0]} pid={c[1]} cat={c[3]} title={c[2]!r}")
