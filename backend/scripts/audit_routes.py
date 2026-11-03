# -*- coding: utf-8 -*-
"""审计全部路由：枚举所有 list 路由 vs detail 路由，找缺失。"""
import sys
sys.path.insert(0, "/app")
from app.main import app

list_routes = {}   # path_template -> set(methods)
for r in app.routes:
    try:
        path = getattr(r, "path", "")
        methods = getattr(r, "methods", None)
        if not path or not methods:
            continue
        list_routes.setdefault(path, set()).update(methods)
    except Exception:
        pass

print("=== 路由清单（只有 path+methods，无 prefix 扩展）===\n")
for path, methods in sorted(list_routes.items()):
    print(f"  {sorted(methods)}  {path}")

print("\n=== 缺失 GET by-id 检查 ===")
# 匹配模式：有 /xxx 但无 /xxx/{id}
import re
roots = {}
for path in list_routes:
    if re.match(r"^/api/\w+$", path):
        roots[path] = list_routes[path]

for root, methods in roots.items():
    detail = f"{root}/{{id}}"
    detail_caseid = f"{root}/{{case_id}}"
    detail_any = [p for p in list_routes if p.startswith(root + "/{")]
    has_get = any(list_routes.get(p, set()) & {"GET"} for p in detail_any)
    if "GET" in methods and not has_get:
        print(f"  [⚠] 缺少 GET {detail_any[0] if detail_any else root + '/{id}'}")
