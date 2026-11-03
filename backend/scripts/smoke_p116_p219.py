# -*- coding: utf-8 -*-
"""P1-16 / P2-19 接口冒烟自测（对 8011 临时实例）。"""
import json
import sys

import httpx

BASE = "http://127.0.0.1:8000"
WH = {"X-Webhook-Token": "EvalShield-webhook-secret-dev"}
PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} {extra}")


c = httpx.Client(timeout=30)
r = c.post(f"{BASE}/api/auth/login", json={"username": "test111", "password": "123456"})
tok = r.json()["data"]["access_token"]
H = {"Authorization": f"Bearer {tok}"}

# 取一条用例
rows = c.get(f"{BASE}/api/cases", params={"page": 1, "page_size": 1}, headers=H).json()["data"]
row = (rows.get("rows") or rows.get("items"))[0]
cid, pid = row["id"], row["project_id"]
print(f"case id={cid} project={pid}")

# P2-19 快照 v1
s1 = c.post(f"{BASE}/api/projects/{pid}/assets/CASE/{cid}/snapshot",
            json={"change_note": "冒烟v1"}, headers=H).json()
check("snapshot v1", s1.get("code") == 0 and s1["data"]["seq"] >= 1, json.dumps(s1)[:200])
seq1 = s1["data"]["seq"]

# 修改标题
old_title = row["title"]
new_title = (old_title or "用例") + "·冒烟改"
u = c.put(f"{BASE}/api/cases/{cid}", json={"title": new_title}, headers=H).json()
check("update case title", u.get("code") == 0, json.dumps(u)[:200])

# 快照 v2 + diff
s2 = c.post(f"{BASE}/api/projects/{pid}/assets/CASE/{cid}/snapshot",
            json={"change_note": "冒烟v2"}, headers=H).json()
seq2 = s2["data"]["seq"]
check("snapshot v2", s2.get("code") == 0 and seq2 == seq1 + 1, json.dumps(s2)[:200])

d = c.get(f"{BASE}/api/projects/{pid}/assets/CASE/{cid}/versions/compare",
          params={"from_seq": seq1, "to_seq": seq2}, headers=H).json()
check("compare has title diff", d.get("code") == 0 and any(
    x["field"] == "title" for x in d["data"]["diffs"]), json.dumps(d)[:300])

# 回滚 v1
rb = c.post(f"{BASE}/api/projects/{pid}/assets/CASE/{cid}/versions/{seq1}/rollback", headers=H).json()
check("rollback v1", rb.get("code") == 0, json.dumps(rb)[:200])
cur = c.get(f"{BASE}/api/cases/{cid}", headers=H).json()["data"]
check("title restored", cur["title"] == old_title, f"got={cur['title']!r} want={old_title!r}")

# 版本列表
vl = c.get(f"{BASE}/api/projects/{pid}/assets/CASE/{cid}/versions", headers=H).json()
check("versions list >=3", vl.get("code") == 0 and len(vl["data"]) >= 3, f"count={len(vl.get('data') or [])}")

# P1-16 JUnit/Allure：找已有报告
rp = c.get(f"{BASE}/api/reports", params={"page": 1, "page_size": 1}, headers=H).json()["data"]
rrows = rp.get("rows") or rp.get("items") or []
if rrows:
    rid = rrows[0]["id"]
    x = c.get(f"{BASE}/api/reports/{rid}/export-junit", headers=H)
    check("junit xml", x.status_code == 200 and "<testsuite" in x.text, x.text[:150])
    a = c.get(f"{BASE}/api/reports/{rid}/export-allure", headers=H)
    check("allure json", a.status_code == 200 and isinstance(a.json(), list), a.text[:150])
    # CI Token 免登录导出
    x2 = c.get(f"{BASE}/api/reports/{rid}/export-junit", headers=WH)
    check("junit via webhook token", x2.status_code == 200, str(x2.status_code))
else:
    print("[SKIP] 无报告，JUnit/Allure 未验证")

# P1-16 ci-status（不存在任务 404；token 校验 400）
st = c.get(f"{BASE}/api/webhook/ci-status/999999", headers=WH)
check("ci-status 404", st.status_code == 404, st.text[:150])
st2 = c.get(f"{BASE}/api/webhook/ci-status/1")
check("ci-status no-token 401/400", st2.status_code in (400, 401), str(st2.status_code))

print(f"\nRESULT PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
