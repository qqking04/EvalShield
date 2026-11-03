# -*- coding: utf-8 -*-
"""核心业务模块链路冒烟测试。

覆盖：项目 CRUD、用例/数据集/场景资产、任务创建-执行-步骤-取消、
13 类引擎全链路执行、评测集/评测运行、报告生成、模型网关、通知、仪表盘。
"""

import sys
import time

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  -> {detail}")


def wait_task_done(headers: dict, task_id: int, timeout: int = 120):
    """任务 execution 已异步化：轮询 /tasks/{id} 直到终态，返回 task。"""
    t: dict = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/tasks/{task_id}", headers=headers)
        b = r.json()
        t = b.get("data", {})
        if t.get("status") in ("SUCCESS", "FAILED", "CANCELLED"):
            return t
        time.sleep(1)
    return t


r = client.post(
    "/api/auth/login", json={"username": "admin", "password": "EvalShield@123"}
)
token = r.json()["data"]["access_token"]
H = {"Authorization": f"Bearer {token}"}

# ---------------- 项目 ----------------
r = client.post(
    "/api/projects",
    headers=H,
    json={
        "name": "智能客服系统回归测试项目",
        "description": "面向大模型智能客服的中文回归测试",
        "target_system": "AI-CS-APP 智能客服",
        "visibility": "TEAM",
    },
)
b = r.json()
check("创建中文名项目", r.status_code == 200 and b["code"] == 0, r.text[:300])
project = b["data"]
project_id = project["id"]
check(
    "项目返回业务编号(PRJ-)",
    str(project["code"]).startswith("PRJ-"),
    str(project)[:200],
)

r = client.get(f"/api/projects/{project_id}", headers=H)
b = r.json()
check("查询项目详情", b["code"] == 0 and b["data"]["task_count"] == 0, r.text[:200])

# ---------------- 用例 / 数据集 / 场景 ----------------
r = client.post(
    "/api/cases",
    headers=H,
    json={
        "project_id": project_id,
        "title": "客服首响时长小于3秒-性能基线",
        "category": "PERFORMANCE",
        "severity": "P1",
        "priority": "HIGH",
        "expected": "首响 <= 3000ms",
        # 夹具调整：PERF_TEST 用例驱动模式要求 request_spec.path 非空，
        # 否则整条用例直接判 E_PERF_NO_PATH FAIL（"1 条性能用例未达标"）。
        # 用绝对 URL 指向冒烟 uvicorn 的 /api/health：
        # 引擎判定只看用例 assertions（此处不设严苛断言 → 夹具语义为"链路可压测即达标"）。
        "request_spec": {"method": "GET", "path": "http://127.0.0.1:8079/api/health"},
        "tags": ["性能", "基线"],
    },
)
b = r.json()
check("创建用例", b["code"] == 0, r.text[:300])
case = b["data"]
check("用例返回 case_no", str(case["case_no"]).startswith("C-"), str(case)[:150])

r = client.post(
    "/api/datasets",
    headers=H,
    json={
        "project_id": project_id,
        "name": "客服回归数据集",
        "category": "REGRESSION",
        "case_ids": [case["id"]],
        "description": "中文回归用例集",
    },
)
b = r.json()
check("创建数据集", b["code"] == 0, r.text[:300])
ds = b["data"]
check(
    "数据集返回编号+用例数",
    str(ds["code"]).startswith("DS-") and ds["case_count"] == 1,
    str(ds)[:200],
)

r = client.post(
    "/api/scenarios",
    headers=H,
    json={
        "project_id": project_id,
        "name": "多轮对话压测场景",
        "description": "20轮连续对话",
        "steps": [{"action": "chat", "content": "你好"}],
    },
)
b = r.json()
check("创建场景", b["code"] == 0, r.text[:300])

# ---------------- 模型网关 ----------------
r = client.post(
    "/api/model-configs",
    headers=H,
    json={
        "name": "千帆文心网关",
        "provider": "QIANFAN",
        "base_url": "https://qianfan.baidubce.com",
        "model": "ernie-4.0-turbo",
        "api_key_env": "QIANFAN_API_KEY",
        # 夹具调整：inti.sql 种子已有默认 CHAT 模型，再建默认会触发 ES-BIZ-0072 冲突
        "is_default": False,
    },
)
b = r.json()
check("创建模型网关", b["code"] == 0, r.text[:300])
gw_code = b["data"]["code"]
check(
    "模型网关返回业务编号",
    bool(gw_code) and str(gw_code).startswith("MG-"),
    r.text[:200],
)

r = client.get("/api/model-configs", headers=H)
b = r.json()
check("模型网关列表", b["code"] == 0 and len(b["data"]) >= 1, r.text[:200])

# ---------------- 任务与引擎执行 ----------------
ALL_ENGINES = [
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
]

# BUG-013：MULTI_TURN_TEST 服务端要求 config.target_code（v2.0 P5 校验）。
# 复用既有 target；干净环境没有则先创建一个冒烟专用 target。
r = client.get("/api/targets?page=1&page_size=50", headers=H)
b = r.json()
_items = (b.get("data") or {}).get("items") or []
target_code = next(
    (t["code"] for t in _items if t.get("code") == "TG-OFFLINE-001"),
    _items[0]["code"] if _items else None,
)
if not target_code:
    r = client.post(
        "/api/targets",
        headers=H,
        json={
            "name": "冒烟被测端点",
            "target_type": "LLM_API",
            "base_url": "https://demo.example.com",
            "model": "smoke-model",
        },
    )
    b = r.json()
    check("创建冒烟被测系统(target)", b["code"] == 0, r.text[:300])
    target_code = b["data"]["code"]
check("冒烟任务具备 target_code", bool(target_code), str(target_code))

r = client.post(
    "/api/tasks",
    headers=H,
    json={
        "project_id": project_id,
        "name": "全引擎回归执行-13类",
        "description": "验证全部 13 类引擎可被任务调度执行",
        "engines": ALL_ENGINES,
        "config": {
            "target_code": target_code,
            "target_url": "https://demo.example.com",
            "concurrency": 10,
            "duration_sec": 5,
            "scenario_steps": [
                {
                    "action": "POST",
                    "target": "/api/order/create",
                    "extract": ["order_id"],
                },
                {"action": "GET", "target": "/api/order/{order_id}"},
            ],
            "variables": {"order_id": "ORD-001"},
            "model_args": {
                "outputs_by_engine": {
                    # 夹具调整：引擎自动取最新 HALLUCINATION 评测集（HALLU-SET-002），
                    # 其第 1 条为 HC-011"中国最长的河流"，preset 下标 0 必须与其
                    # references 对齐，否则词面/语义判定判"存在幻觉输出" FAIL。
                    "HALLUCINATION_TEST": {
                        "0": "长江，全长约6300公里，是中国最长的河流"
                    },
                    "EVAL_ENGINE": {
                        "0": "单元测试的定义包含测试用例、隔离执行和自动化验证的概念，这是单元测试需要满足的要求"
                    },
                }
            },
        },
        "trigger_mode": "MANUAL",
    },
)
b = r.json()
check("创建任务(13引擎)", b["code"] == 0, r.text[:300])
task = b["data"]
task_id = task["id"]
check("任务返回 task_no", str(task["task_no"]).startswith("TSK-"), str(task)[:150])

# 引擎列表可选项
r = client.get("/api/engine-options", headers=H)
b = r.json()
codes = {e["engine_code"] for e in b["data"]}
check(
    "engine-options 全部 13 类在列",
    codes.issuperset(set(ALL_ENGINES)),
    str(sorted(codes))[:300],
)

r = client.post(f"/api/tasks/{task_id}/run", headers=H, json={})
b = r.json()
check("执行任务成功(异步提交)", b["code"] == 0, r.text[:400])
t = wait_task_done(H, task_id)
check(
    "任务异步执行至 SUCCESS",
    t["status"] == "SUCCESS",
    f"status={t.get('status')} err={t.get('error_msg')}",
)
check("任务进度 100", t["progress"] == 100, str(t.get("progress")))
total = (t.get("summary") or {}).get("total", 0)
passed = (t.get("summary") or {}).get("passed", 0)
check(
    "汇总 total>0 且 passed>0",
    total > 0 and passed > 0,
    str((t.get("summary") or {}))[:200],
)

# 任务详情含步骤
r = client.get(f"/api/tasks/{task_id}", headers=H)
b = r.json()
steps = b["data"]["steps"]
check(
    "任务详情含 13 步骤",
    b["code"] == 0 and len(steps) == 13,
    f"steps={len(steps)} {r.text[:200]}",
)
check(
    "全部步骤 SUCCESS/SKIPPED（无 FAILED）",
    all(s["status"] in ("SUCCESS", "SKIPPED") for s in steps),
    str([(s["engine_code"], s["status"]) for s in steps])[:300],
)
fail_steps = [s["engine_code"] for s in steps if s["status"] == "FAILED"]
check("无 FAILED 步骤", fail_steps == [], str(fail_steps))

# 报告
r = client.get("/api/reports", headers=H, params={"project_id": project_id})
b = r.json()
check("报告列表生成", b["code"] == 0 and b["data"]["total"] >= 1, r.text[:300])
rep = b["data"]["items"][0]
check("报告有编号", str(rep.get("report_no", "")).startswith("RPT-"), str(rep)[:200])
r = client.get(f"/api/reports/{rep['id']}", headers=H)
b = r.json()
check("报告详情", b["code"] == 0, r.text[:300])

# ---------------- 评测 ----------------
r = client.post(
    "/api/eval-sets",
    headers=H,
    json={
        "name": "客服回答质量评测集",
        # 夹具调整：'QA' 不在合法类别枚举中，改用 'EVAL'
        "category": "EVAL",
        "items": [
            {"question": "如何申请退款？", "expected": "包含退款流程"},
            {"question": "重置密码步骤", "expected": "包含密码重置"},
        ],
    },
)
b = r.json()
check("创建评测集", b["code"] == 0, r.text[:300])
eval_set_id = b["data"]["id"]

r = client.post(
    "/api/eval-runs",
    headers=H,
    json={
        "eval_set_id": eval_set_id,
        "target_type": "MODEL",
        "target_id": "ernie-4.0-turbo",
        "model_gateway": "QIANFAN",
        "judge_mode": "RULE",
    },
)
b = r.json()
check("运行评测", b["code"] == 0, r.text[:400])
run = b["data"]
# 评测集未接入真实模型输出 → 正确语义为 SKIPPED（而非 FAILED）
check(
    "评测状态不为 FAILED（SUCCESS 或 SKIPPED）",
    run["status"] in ("SUCCESS", "SKIPPED"),
    str(run)[:300],
)

# ---------------- 取消任务 ----------------
r = client.post(
    "/api/tasks",
    headers=H,
    json={"project_id": project_id, "name": "待取消任务", "engines": ["API_TEST"]},
)
b = r.json()
pend_task_id = b["data"]["id"]
r = client.post(f"/api/tasks/{pend_task_id}/cancel", headers=H)
b = r.json()
check("取消任务(非运行中走 CANCELLED 或跳过)", b["code"] == 0, r.text[:300])

# ---------------- 通知 / 仪表盘 / 资产列表 ----------------
r = client.get("/api/notifications", headers=H)
b = r.json()
check("通知列表", b["code"] == 0, r.text[:200])

r = client.get("/api/dashboard/stats", headers=H)
b = r.json()
check("仪表盘统计", b["code"] == 0, r.text[:300])

r = client.get("/api/artifacts", headers=H)
b = r.json()
check("任务产物列表", b["code"] == 0, r.text[:200])

print(f"\n==== 核心业务链路冒烟：{PASS} 通过 / {FAIL} 失败 ====")
sys.exit(1 if FAIL else 0)
