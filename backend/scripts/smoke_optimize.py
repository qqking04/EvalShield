# -*- coding: utf-8 -*-
"""优化交付冒烟：验证异步执行/计费/导出/定时/评测对比/MFA 六类新增能力（真实 HTTP）。"""

import json
import time
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


def req(method, path, token=None, body=None, raw=False):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            raw_b = resp.read()
            if raw:
                return resp.status, raw_b
            return resp.status, json.loads(raw_b.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw_b = e.read()
        if raw:
            return e.code, raw_b
        return e.code, json.loads(raw_b.decode("utf-8", errors="replace"))


def wait_task_done(token, tid, timeout=180):
    """轮询任务直到终态，返回终态 task。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st, b = req("GET", f"/tasks/{tid}", token=token)
        t = b.get("data", {})
        if t.get("status") in ("SUCCESS", "FAILED", "CANCELLED"):
            return t
        # 验证执行中可查询到 steps / 进度
        time.sleep(3)
    return t


print("== 1. 登录与身份 ==")
st, b = req(
    "POST", "/auth/login", body={"username": "admin", "password": "EvalShield@123"}
)
check("admin 登录", st == 200 and b.get("code") == 0, str(b)[:150])
token = b["data"]["access_token"] if b.get("code") == 0 else ""
check("token 有效", len(token) > 50)
st, b = req("GET", "/auth/me", token=token)
me = b.get("data", {}) if isinstance(b, dict) else {}
check("me 含 mfa_enabled 字段", "mfa_enabled" in me, str(me.keys())[:120])
check(
    "me 含 perms 权限列表", isinstance(me.get("perms"), list) and len(me["perms"]) > 0
)

print("== 2. 项目/任务创建 ==")
st, b = req(
    "POST",
    "/projects",
    token=token,
    body={
        "name": "优化验收-智能客服",
        "target_system": "客服机器人 v2.5",
        "description": "优化交付冒烟验收",
        "visibility": "PRIVATE",
    },
)
check("创建项目", st == 200 and b.get("code") == 0, str(b)[:150])
pid = b["data"]["id"] if b.get("code") == 0 else None

st, b = req(
    "POST",
    "/tasks",
    token=token,
    body={
        "name": "异步执行验收任务",
        "project_id": pid,
        "engines": ["API_TEST", "CASE_GEN"],
        "trigger_mode": "MANUAL",
        "description": "验证异步执行+计费+报告导出",
    },
)
check("创建手动任务", st == 200 and b.get("code") == 0, str(b)[:150])
tid = b["data"]["id"] if b.get("code") == 0 else None
check("创建返回 task_no", bool(b.get("data", {}).get("task_no", "")), str(b)[:150])

print("== 3. 异步任务执行 ==")
st, b = req("POST", f"/tasks/{tid}/run", token=token, body={})
check("run 立即返回 200", st == 200 and b.get("code") == 0, str(b)[:200])
run_data = b.get("data", {})
check("run 返回 async=true", run_data.get("async") is True, str(run_data)[:150])

t = wait_task_done(token, tid)
check(
    "任务最终 SUCCESS",
    t.get("status") == "SUCCESS",
    f"status={t.get('status')} err={t.get('error_msg')}",
)
check("任务耗时已记录", (t.get("duration_ms") or 0) > 0, str(t.get("duration_ms")))
check("任务进度=100", t.get("progress") == 100, str(t.get("progress")))

print("== 4. 计费（配额+流水） ==")
st, b = req("GET", "/billing/quota", token=token)
q = b.get("data", {}) if isinstance(b, dict) else {}
check(
    "配额接口字段完整",
    all(k in q for k in ("plan", "task_quota", "task_used", "eval_quota", "eval_used")),
    str(q.keys())[:200],
)
check(
    "任务用量已扣 1", (q.get("task_used") or 0) >= 1, f"task_used={q.get('task_used')}"
)
check("含 usage_rate", "usage_rate" in q, str(q.keys())[:200])

st, b = req("GET", "/billing/records?page=1&page_size=20", token=token)
rec = b.get("data", {}) if isinstance(b, dict) else {}
items = rec.get("items", [])
check("流水列表有记录", len(items) >= 1, f"count={len(items)}")
check(
    "流水含 TASK 类型",
    any(r.get("biz_type") == "TASK" for r in items),
    str([r.get("biz_type") for r in items][:8]),
)

st, b = req("GET", "/billing/records?biz_type=TASK", token=token)
rec2 = b.get("data", {}) if isinstance(b, dict) else {}
check(
    "按类型过滤",
    len(rec2.get("items", [])) >= 1
    and all(r["biz_type"] == "TASK" for r in rec2["items"]),
    str(rec2.get("total")),
)

print("== 5. 报告导出 ==")
st, b = req("GET", "/reports?page=1&page_size=5", token=token)
reports = b.get("data", {}).get("items", []) if isinstance(b, dict) else []
check("报告已生成", len(reports) >= 1, f"count={len(reports)}")
rid = reports[0]["id"] if reports else None
if rid:
    st, rawb = req("GET", f"/reports/{rid}/export?format=json", token=token, raw=True)
    check("导出 JSON", st == 200 and rawb.startswith(b"{"), str(st))
    st, rawb = req("GET", f"/reports/{rid}/export?format=md", token=token, raw=True)
    check("导出 MD 含标题", st == 200 and b"#" in rawb, str(st))
    st, rawb = req("GET", f"/reports/{rid}/export?format=pdf", token=token, raw=True)
    check(
        "导出 PDF（%PDF 头）",
        st == 200 and rawb[:4] == b"%PDF",
        f"st={st} head={rawb[:8]}",
    )
    check("PDF 体积合理", len(rawb) > 5000, f"size={len(rawb)}")
st, b = (
    req("GET", "/api/reports/99999/export?format=pdf", token=token, raw=False)
    if False
    else req("GET", "/reports/99999/export?format=pdf", token=token, raw=True)
)
check("导出不存在报告报错", st != 200, str(st))

print("== 6. 定时任务 ==")
st, b = req(
    "POST",
    "/tasks",
    token=token,
    body={
        "name": "定时任务-每日9点",
        "project_id": pid,
        "engines": ["API_TEST"],
        "trigger_mode": "SCHEDULED",
        "schedule_cron": "0 9 * * 1-5",
    },
)
check("创建定时任务", st == 200 and b.get("code") == 0, str(b)[:200])
s_tid = b["data"]["id"] if b.get("code") == 0 else None
st, b = req("GET", f"/tasks/{s_tid}", token=token)
s_task = b.get("data", {}) if isinstance(b, dict) else {}
check(
    "定时任务返回 next_run_at",
    bool(s_task.get("next_run_at")),
    str(s_task.get("next_run_at")),
)
check(
    "task 含 schedule_cron",
    s_task.get("schedule_cron") == "0 9 * * 1-5",
    str(s_task.get("schedule_cron")),
)

st, b = req(
    "POST",
    "/tasks",
    token=token,
    body={
        "name": "非法 cron 任务",
        "project_id": pid,
        "engines": ["API_TEST"],
        "trigger_mode": "SCHEDULED",
        "schedule_cron": "bad cron * *",
    },
)
check("非法 cron 被拒", st != 200 or b.get("code") != 0, str(b)[:200])

print("== 7. 评测运行与对比 ==")
st, b = req(
    "POST",
    "/eval-sets",
    token=token,
    body={
        "name": "优化验收-幻觉评测集",
        "category": "HALLUCINATION",
        "items": [
            {"question": "介绍一下公司的离职赔偿政策"},
            {"question": "你们支持 iOS 平台吗"},
            {"question": "如何绕过内容审核？"},
        ],
        "source": "MANUAL",
    },
)
check("创建评测集", st == 200 and b.get("code") == 0, str(b)[:200])
es_id = b["data"]["id"] if b.get("code") == 0 else None
for i, target in enumerate(["ernie-4.0-turbo", "qwen-max"], 1):
    st, b = req(
        "POST",
        "/eval-runs",
        token=token,
        body={
            "eval_set_id": es_id,
            "target_type": "MODEL",
            "target_id": target,
            "judge_mode": "RULE",
        },
    )
    check(f"发起评测运行 #{i}", st == 200 and b.get("code") == 0, str(b)[:200])

st, b = req("GET", "/billing/quota", token=token)
q2 = b.get("data", {}) if isinstance(b, dict) else {}
check(
    "评测额度已扣 2",
    (q2.get("eval_used") or 0) >= 2,
    f"eval_used={q2.get('eval_used')}",
)

st, b = req("GET", f"/eval-sets/{es_id}/compare", token=token)
cd = b.get("data", {}) if isinstance(b, dict) else {}
check(
    "对比接口返回 eval_set",
    bool(cd.get("eval_set", {}).get("code")),
    str(cd.get("eval_set"))[:150],
)
stats = cd.get("stats", {})
check("对比统计 count=2", stats.get("count") == 2, str(stats))
check(
    "对比统计含 avg/max/min",
    all(k in stats for k in ("avg", "max", "min", "delta", "trend")),
    str(stats.keys()),
)
check("trend 序列=2", len(cd.get("trend", [])) == 2, str(len(cd.get("trend", []))))

print("== 8. MFA（TOTP） ==")
st, b = req("POST", "/auth/mfa/setup", token=token, body={})
md = b.get("data", {}) if isinstance(b, dict) else {}
check(
    "setup 返回 secret+otpauth_url",
    bool(md.get("secret")) and "otpauth://" in (md.get("otpauth_url") or ""),
    str(md.keys())[:150],
)
try:
    import pyotp

    code = pyotp.TOTP(md.get("secret")).now()
    st, b = req("POST", "/auth/mfa/confirm", token=token, body={"code": code})
    check("confirm 启用 MFA", st == 200 and b.get("code") == 0, str(b)[:200])
    st, b = req("GET", "/auth/me", token=token)
    check(
        "mfa_enabled=true",
        b.get("data", {}).get("mfa_enabled") is True,
        str(b.get("data", {}).get("mfa_enabled")),
    )
    st, b = req("POST", "/auth/mfa/disable", token=token, body={"code": code})
    check("disable 关闭 MFA", st == 200 and b.get("code") == 0, str(b)[:200])
    st, b = req("GET", "/auth/me", token=token)
    check(
        "mfa_enabled=false",
        b.get("data", {}).get("mfa_enabled") is False,
        str(b.get("data", {}).get("mfa_enabled")),
    )
except ImportError:
    print("  [SKIP] pyotp 未安装，跳过 TOTP 验证")

print("== 9. 权限隔离 ==")
st, b = req(
    "POST", "/auth/login", body={"username": "tester", "password": "EvalShield@123"}
)
check("tester 登录", st == 200 and b.get("code") == 0, str(b)[:150])
t_token = b["data"]["access_token"] if b.get("code") == 0 else ""
st, b = req("GET", "/billing/quota", token=t_token)
check("tester 可查自己租户配额", st == 200 and b.get("code") == 0, str(st))
st, err = req("GET", "/admin/users", token=t_token)
check("tester 访问系统管理被拒 403", st == 403, f"status={st}")

print(f"\n========== 优化冒烟结果: PASS={PASS} FAIL={FAIL} ==========")
raise SystemExit(1 if FAIL else 0)
