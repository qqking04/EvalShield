# -*- coding: utf-8 -*-
"""前后端联调冒烟：真实 HTTP 走 uvicorn 服务，验证登录/中文读写/任务执行/报告/评测/引擎注册。"""

import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000/api"
PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def req(method, path, token=None, body=None, expect200=True):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return e.code, raw


print("== 1. 认证 ==")
st, b = req(
    "POST", "/auth/login", body={"username": "admin", "password": "EvalShield@123"}
)
check("登录返回 code=0", st == 200 and b.get("code") == 0, str(b)[:200])
token = b["data"]["access_token"] if b.get("code") == 0 else ""
check("获取 access_token", len(token) > 50)

st, b = req("GET", "/auth/me", token=token)
me = b.get("data", {}) if isinstance(b, dict) else {}
check(
    "me 返回用户中文名",
    st == 200 and me.get("display_name") == "超级管理员",
    str(me.get("display_name")),
)
perms = me.get("perms", [])
check("me 返回权限列表", len(perms) > 0, f"perms={len(perms)}")
check("is_super_admin=true", me.get("is_super_admin") is True)

print("== 2. 中文读写（项目） ==")
st, b = req(
    "POST",
    "/projects",
    token=token,
    body={
        "name": "智能客服系统验收测试",
        "target_system": "客服机器人 v2.1",
        "description": "中文读写联调验证：幻觉测试+接口测试",
        "visibility": "PRIVATE",
    },
)
check("创建中文项目", st == 200 and b.get("code") == 0, str(b)[:200])
pid = b["data"]["id"] if b.get("code") == 0 else None
pcode = b["data"]["code"] if b.get("code") == 0 else ""
check("项目编号 PRJ- 前缀", pcode.startswith("PRJ-"), pcode)

st, b = req("GET", f"/projects/{pid}", token=token)
pd = b.get("data", {}) if isinstance(b, dict) else {}
check("读回中文名一致", pd.get("name") == "智能客服系统验收测试", str(pd.get("name")))
check(
    "读回中文描述一致",
    "幻觉测试" in (pd.get("description") or ""),
    str(pd.get("description")),
)

print("== 3. 引擎注册 ==")
st, b = req("GET", "/engine-options", token=token)
engines = b.get("data", []) if isinstance(b, dict) else []
codes = {e["engine_code"] for e in engines}
check("引擎列表 >= 13", len(engines) >= 13, f"count={len(engines)}")
for expect in [
    "UI_TEST",
    "API_TEST",
    "PERF_TEST",
    "DATAFLOW_TEST",
    "HALLUCINATION_TEST",
    "REDTEAM_TEST",
    "RAG_TEST",
    "MULTI_TURN_TEST",
    "ETHICS_TEST",
    "EVAL_ENGINE",
    "CASE_GEN",
    "SELF_HEAL",
    "DEFECT_PREDICT",
]:
    check(f"引擎已注册 {expect}", expect in codes)

print("== 4. 任务执行链路 ==")
st, b = req(
    "POST",
    "/tasks",
    token=token,
    body={
        "name": "客服系统回归-联调",
        "project_id": pid,
        "engines": ["API_TEST", "HALLUCINATION_TEST", "CASE_GEN"],
        "description": "联调冒烟任务",
        "trigger_mode": "MANUAL",
    },
)
check("创建任务", st == 200 and b.get("code") == 0, str(b)[:200])
task = b["data"]
tid = task["id"]
st, b = req("POST", f"/tasks/{tid}/run", token=token, body={})
check("执行任务", st == 200 and b.get("code") == 0, str(b)[:300])
t = b.get("data", {}).get("task", {}) if isinstance(b, dict) else {}
check(
    "任务状态 SUCCESS",
    t.get("status") == "SUCCESS",
    f"status={t.get('status')} err={t.get('error_msg')}",
)
summary = t.get("summary") or {}
check("汇总含通过率", "pass_rate" in summary)
st, b = req("GET", f"/tasks/{tid}/steps", token=token)
steps = b.get("data", []) if isinstance(b, dict) else []
check("步骤数=3", len(steps) >= 3, f"steps={len(steps)}")
check(
    "步骤全部通过/跳过",
    all(s.get("status") in ("SUCCESS", "SKIPPED") for s in steps),
    str([s.get("status") for s in steps]),
)

print("== 5. 报告 ==")
st, b = req("GET", "/reports", token=token)
reports = b.get("data", {}).get("items", []) if isinstance(b, dict) else []
check("报告已生成", len(reports) >= 1, f"count={len(reports)}")
if reports:
    check(
        "报告编号 RPT-",
        reports[0]["report_no"].startswith("RPT-"),
        reports[0]["report_no"],
    )

print("== 6. 评测链路 ==")
st, b = req(
    "POST",
    "/eval-sets",
    token=token,
    body={
        "name": "幻觉检测评测集-联调",
        "category": "HALLUCINATION",
        "items": [
            {"question": "介绍一下公司的离职赔偿政策"},
            {"question": "你们支持 iOS 平台吗"},
        ],
        "source": "MANUAL",
    },
)
check("创建评测集", st == 200 and b.get("code") == 0, str(b)[:200])
es_id = b["data"]["id"] if b.get("code") == 0 else None
st, b = req(
    "POST",
    "/eval-runs",
    token=token,
    body={
        "eval_set_id": es_id,
        "target_type": "MODEL",
        "target_id": "ernie-4.0-turbo",
        "judge_mode": "RULE",
    },
)
check("发起评测运行", st == 200 and b.get("code") == 0, str(b)[:300])

print("== 7. 数据字典与审计（admin 前缀 /api/admin） ==")
st, b = req("GET", "/admin/dicts", token=token)
dicts = b.get("data", []) if isinstance(b, dict) else []
check("数据字典 >= 7 组", len(dicts) >= 7, f"count={len(dicts)}")
st, b = req("GET", "/admin/audit-logs", token=token)
audit = b.get("data", {}).get("items", []) if isinstance(b, dict) else []
check("审计日志已记录", len(audit) >= 1, f"count={len(audit)}")

print("== 8. 权限与越权 ==")
st, b = req(
    "POST", "/auth/login", body={"username": "tester", "password": "EvalShield@123"}
)
check("tester 登录", st == 200 and b.get("code") == 0, str(b)[:150])
t_token = b["data"]["access_token"] if b.get("code") == 0 else ""
st, err = req("GET", "/admin/users", token=t_token)
check(
    "tester 访问用户管理被拒 403",
    st == 403,
    f"status={st}",
)

print(f"\n========== 联调结果: PASS={PASS} FAIL={FAIL} ==========")
raise SystemExit(1 if FAIL else 0)
