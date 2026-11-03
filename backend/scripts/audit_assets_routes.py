# -*- coding: utf-8 -*-
"""Assets 页关键路由全验证（用 urllib，零依赖）。"""
import sys, json, urllib.request, urllib.parse, urllib.error, os
os.environ.setdefault("DB_HOST", "host.docker.internal")

BASE = "http://127.0.0.1:8000/api"

def req(method, path, body=None, headers=None):
    h = {"Content-Type": "application/json"}
    if headers: h.update(headers)
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)

# 登录
_, data = req("POST", "/auth/login", {"username": "admin", "password": "EvalShield@123"})
token = json.loads(data)["data"]["access_token"]
h = {"Authorization": f"Bearer {token}"}

endpoints = [
    ("GET", "/cases?page=1&page_size=5"),
    ("GET", "/cases/2"),
    ("POST", "/cases", {"case_no":"TEST-001","title":"t","category":"API","project_id":1,"request_spec":{}}),
    ("PUT", "/cases/2", {"title":"测试更新","category":"UI"}),
    ("DELETE", "/cases/TEST-001"),
    ("GET", "/datasets?page=1&page_size=5"),
    ("GET", "/datasets/1"),
    ("GET", "/scenarios"),
    ("GET", "/scenarios/1"),
]

ok = 0
for m, p, *rest in [tuple(e) + (None,) for e in endpoints if len(e)==2] + [tuple(e) for e in endpoints if len(e)==3]:
    st, body = req(m, p, rest[0] if rest[0] else None, h)
    bad = st in (404, 405) or st == 0
    tag = "FAIL" if bad else "OK"
    print(f"[{tag}] {m:5} {p:30s} -> {st}")
    if not bad: ok += 1

print(f"\nAssets 页关键路由: {ok}/{len(endpoints)} OK")
