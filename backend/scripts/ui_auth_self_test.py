# -*- coding: utf-8 -*-
"""UI_TEST 真实 case + Cookie 持久化 + pre_login 验证。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engines.ui_test import UITestEngine
from app.engines.base import EngineContext

# 直接给 engine 猴子补丁 _load_cases，绕过 DB
_original_load = UITestEngine._load_cases


def fake_load(self, ctx):
    return [{
        "case_no": "UI-001",
        "title": "前端首页打开（验证 Cookie 持久化）",
        "steps": [
            {"action": "goto", "target": "http://evalshield-frontend", "timeout": 10000},
            {"action": "wait", "value": 2000},
            {"action": "assert_visible", "target": "body", "timeout": 5000},
        ],
    }]


UITestEngine._load_cases = fake_load

# 1) 带 Cookie 预置 + Bearer 的场景
ctx = EngineContext(
    task_id=0, task_no="CK", step_id=0, step_no="CK-1", project_id=0,
    engine_code="UI_TEST",
    config={
        "base_url": "http://evalshield-frontend",
        "auth": {
            "cookies": ["test_session=abc123", "tenant=t001"],
            "bearer": "test-token-xyz",
        },
    },
    db=None, extra={},
)
result = UITestEngine().execute(ctx)
print("=== UI_TEST 真实 case + Cookie/Bearer 预置 ===")
print(f"status: {result.status}")
print(f"summary: {result.summary}")
for r in (result.report_payload or {}).get("results", []):
    print(f"  case {r['case_no']}: {r['result']} ({r['duration_ms']}ms)")
    if r.get("failures"):
        print(f"    failures: {r['failures']}")
print(f"pre_login_errors: {result.report_payload.get('pre_login_errors')}")

# 2) pre_login 自动登录场景（登录页可能不存在，看错误处理是否优雅）
UITestEngine._load_cases = fake_load  # 保持同样的 case
ctx2 = EngineContext(
    task_id=0, task_no="L2", step_id=0, step_no="L2-1", project_id=0,
    engine_code="UI_TEST",
    config={
        "base_url": "http://evalshield-frontend",
        "auth": {
            "login_url": "http://evalshield-frontend",  # 用首页代替登录页
            "username": "admin",
            "password": "EvalShield@123",
        },
    },
    db=None, extra={},
)
result2 = UITestEngine().execute(ctx2)
print("\n=== UI_TEST pre_login 自动登录（错误处理验证）===")
print(f"status: {result2.status}")
print(f"summary: {result2.summary}")
print(f"pre_login_errors: {result2.report_payload.get('pre_login_errors')}")

# 恢复
UITestEngine._load_cases = _original_load
print("\n全部完成")
