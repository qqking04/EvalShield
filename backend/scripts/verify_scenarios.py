# -*- coding: utf-8 -*-
"""验证 scenarios 路由 + 表存在。"""
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
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

_, data = req("POST", "/auth/login", {"username": "admin", "password": "EvalShield@123"})
token = json.loads(data)["data"]["access_token"]
h = {"Authorization": f"Bearer {token}"}

st, body = req("GET", "/scenarios?page=1&page_size=5", headers=h)
print(f"GET /scenarios -> {st}")
items = json.loads(body).get("data", {}).get("items", [])
print(f"  items: {len(items)}")
if items:
    sid = items[0]["id"]
    st2, body2 = req("GET", f"/scenarios/{sid}", headers=h)
    print(f"GET /scenarios/{sid} -> {st2}")
else:
    print("  无数据，尝试 GET /scenarios/1")
    st2, body2 = req("GET", "/scenarios/1", headers=h)
    print(f"GET /scenarios/1 -> {st2}")
