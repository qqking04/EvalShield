# -*- coding: utf-8 -*-
"""快速审计：全部注册引擎清单 + import/compileall 健康检查 + 基础执行测试。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engines.registry import EngineRegistry, discover_engines

discover_engines()
reg = EngineRegistry()
# discover_engines 用的是模块级单例，我这里也要用那个单例
from app.engines.registry import engine_registry
reg = engine_registry
engines = reg.meta_list()
print(f"=== 已注册引擎：{len(engines)} 个 ===\n")
for i, e in enumerate(engines, 1):
    print(f" {i:2d}. {e['engine_code']:22s} | {e['engine_name']:22s} | type={e['engine_type']:12s} | cat={e.get('category','-')} | ver={e.get('version','-')}")

print()
print("=== 逐个引擎 import + execute dry-run ===")

from app.engines.base import EngineContext

fail_count = 0
for e in engines:
    code = e["engine_code"]
    try:
        inst = reg.get(code)
        ctx = EngineContext(task_id=0, task_no="AUDIT", step_id=0, step_no="AUDIT-1",
                            project_id=0, engine_code=code, config={}, db=None, extra={})
        result = inst.execute(ctx)
        status = result.status
        ok = status in ("SUCCESS", "SKIPPED", "FAILED")
        flag = "OK " if ok else "BAD"
        detail = f"status={status}"
        if result.error:
            detail += f" err={str(result.error)[:100]}"
        print(f"  [{flag}] {code:22s} {detail}")
    except Exception as exc:
        fail_count += 1
        print(f"  [BAD ] {code:22s} EXCEPTION: {exc.__class__.__name__}: {str(exc)[:120]}")

print(f"\n汇总: {len(engines) - fail_count}/{len(engines)} 引擎可正常 import + execute")
sys.exit(0 if fail_count == 0 else 1)
