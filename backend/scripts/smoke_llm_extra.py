# -*- coding: utf-8 -*-
"""LLM 专项冒烟：模型测试连接、删除、审计联动、优雅降级。

覆盖：
1. POST /api/model-configs/{code}/test  — 真实 LLM 最小请求（本地无真模型时也返回 ok=False 而非报错）
2. DELETE /api/model-configs/{code}     — 软删 + 审计
3. GET  /api/admin/audit-logs           — 能查到 model.test / model.delete / model.create
4. 优雅降级：即使默认模型连不上，含 AI 引擎的任务仍正常执行（SUCCESS/SKIPPED，无 FAILED）

前置：需先跑 seed（内置模型配置），admin 账号可用。
"""

import sys
import time

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

PASS = 0
FAIL = 0
FAILED_MSGS: list[str] = []


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILED_MSGS.append(f"{name}: {detail}")
        print(f"  [FAIL] {name} -> {detail[:300]}")


def login(client: TestClient) -> dict:
    r = client.post(
        "/api/auth/login", json={"username": "admin", "password": "EvalShield@123"}
    )
    b = r.json()
    assert b["code"] == 0, r.text[:300]
    t = b["data"]["access_token"]
    return {"Authorization": f"Bearer {t}"}


def wait_task(client: TestClient, task_id: int, headers: dict, timeout: int = 60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/tasks/{task_id}", headers=headers)
        b = r.json()
        if b["code"] != 0:
            return None, r.text[:200]
        st = b["data"].get("status")
        if st in ("SUCCESS", "FAILED", "CANCELLED", "CANCELING"):
            return b["data"], ""
        time.sleep(1)
    return None, "等待超时"


def main():
    from app.main import app  # noqa: E402

    client = TestClient(app)
    H = login(client)

    # ---- 1. 测试连接（对内置/已有默认模型；不可达时返回 ok=False 也算 P）
    r = client.get("/api/model-configs", headers=H)
    b = r.json()
    check("模型列表可查", b["code"] == 0 and len(b["data"]) >= 1, r.text[:200])
    models = b["data"]
    default_m = next((m for m in models if m.get("is_default")), models[0])
    code = default_m["code"]
    check("模型返回业务编号 code", str(code).startswith("MG-"), str(code))
    r = client.post(f"/api/model-configs/{code}/test", headers=H, json={})
    b = r.json()
    check(
        "测试连接接口正常响应",
        b["code"] == 0 and "data" in b and "ok" in b["data"],
        r.text[:300],
    )
    check(
        "测试连接结果结构(latency_ms)",
        "latency_ms" in b.get("data", {}),
        str(b.get("data", {}))[:200],
    )
    if b["data"].get("ok"):
        print(f"        (真实 LLM 连通成功: {b['data'].get('reply', '')[:60]})")
    else:
        print(
            f"        (当前环境无可用模型端点, 接口优雅返回: {str(b['data'].get('error'))[:80]})"
        )

    # ---- 2. 建一个临时模型再删除
    payload = {
        "code": f"MG-TMP{int(time.time())}",
        "name": "临时冒烟模型",
        "provider": "LOCAL",
        "base_url": "http://127.0.0.1:9/v1",
        "model": "smoke-model",
        "api_key_env": "",
        "is_default": False,
    }
    r = client.post("/api/model-configs", headers=H, json=payload)
    b = r.json()
    check("创建临时模型", b["code"] == 0, r.text[:300])
    tmp_code = b["data"]["code"]
    r = client.delete(f"/api/model-configs/{tmp_code}", headers=H)
    b = r.json()
    check("删除临时模型(软删)", b["code"] == 0, r.text[:300])

    # ---- 3. 审计联动
    r = client.get("/api/admin/audit-logs", headers=H, params={"page_size": 50})
    b = r.json()
    check("审计日志接口可用", b["code"] == 0, r.text[:200])
    actions = [it.get("action") for it in b.get("data", {}).get("items", [])]
    check("审计含 model.test", "model.test" in actions, str(actions)[:200])
    check("审计含 model.create", "model.create" in actions, str(actions)[:200])
    check("审计含 model.delete", "model.delete" in actions, str(actions)[:200])

    # ---- 4. 优雅降级：单跑 AI 引擎任务（默认模型连不上时也不应 FAILED）
    r = client.post(
        "/api/projects",
        headers=H,
        json={"name": "LLM降级冒烟项目", "description": "验证模型不可用时代优雅降级"},
    )
    b = r.json()
    project_id = b["data"]["id"]
    r = client.post(
        "/api/tasks",
        headers=H,
        json={
            "project_id": project_id,
            "name": "AI引擎-模型降级验证",
            "engines": ["HALLUCINATION_TEST", "RAG_TEST", "ETHICS_TEST"],
            "config": {"model_args": {}},
        },
    )
    b = r.json()
    check("提交降级验证任务", b["code"] == 0, r.text[:300])
    task_id = b["data"]["id"]
    r = client.post(f"/api/tasks/{task_id}/run", headers=H, json={})
    check("提交任务执行(异步)", r.json().get("code") == 0, r.text[:300])
    data, err = wait_task(client, task_id, H, timeout=120)
    check("任务执行完成(SUCCESS/FAILED)", data is not None, err)
    if data:
        check(
            "任务整体 SUCCESS 或 SKIP",
            data.get("status") == "SUCCESS",
            str(data.get("status")),
        )
        r = client.get(f"/api/tasks/{task_id}", headers=H)
        steps = r.json()["data"]["steps"]
        fail_steps = [s["engine_code"] for s in steps if s["status"] == "FAILED"]
        check("AI 引擎无 FAILED(优雅降级)", fail_steps == [], str(fail_steps))
        conclusion = (
            r.json()["data"]
            .get("result", {})
            .get("report_payload", {})
            .get("items", [])
        )
        print(f"        (引擎步骤: {[(s['engine_code'], s['status']) for s in steps]})")

    print(f"\n==== LLM 专项冒烟：{PASS} 通过 / {FAIL} 失败 ====")
    if FAILED_MSGS:
        print("失败明细:")
        for m in FAILED_MSGS:
            print(" -", m)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
