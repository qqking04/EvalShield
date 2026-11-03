# -*- coding: utf-8 -*-
"""安全报告端到端冒烟脚本（差异测试 BUG-04/25 修复交付）。

设计约定（与真实契约对齐）：
- 顺序函数传参，非 pytest 用例（函数名不以 test_ 开头，避免被误收集）；
- 所有响应统一走统一包装层 ``["data"]`` 取数；
- 脚本头部自动探测服务（未启动则明确报错退出，不静默超时）；
- 引擎选择 HTTP_SECURITY_HEADERS：对平台自身 base_url 直接可测，无需预置用例。

运行：
    cd backend
    python scripts/smoke_security_report.py [--base-url http://localhost:8000]

退出码：0=全部通过；1=任一步骤失败。
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
TEST_USERNAME = "test111"
TEST_PASSWORD = "123456"

# 任务终态（与 task_runner 实际状态机一致）
_TERMINAL_STATUSES = {"SUCCESS", "FAILED", "COMPLETED_WITH_RISK", "CANCELLED"}

SECURITY_SECTIONS = [
    "report_meta", "detection_scope", "executive_summary", "findings_summary",
    "detailed_findings", "remediation_plan", "good_practices", "conclusion",
]


def _fail(msg: str) -> None:
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def probe_service(base_url: str) -> None:
    """探测服务可用性；未启动直接报错退出（方案原缺陷：无前置启动检查）。"""
    try:
        resp = httpx.get(f"{base_url}/api/health", timeout=5, trust_env=False)
    except httpx.HTTPError as exc:
        _fail(f"服务未启动或不可达：{base_url}（{exc.__class__.__name__}）。"
              f"请先执行：cd backend && python -m uvicorn app.main:app --port 8000")
        return
    if resp.status_code != 200:
        _fail(f"服务健康检查异常：GET /api/health -> {resp.status_code}")


def step_login(client: httpx.Client, base_url: str) -> str:
    print("步骤 1：登录系统")
    resp = client.post(
        f"{base_url}/api/auth/login",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        timeout=15,
    )
    if resp.status_code != 200:
        _fail(f"登录失败: {resp.status_code} {resp.text[:200]}")
    body = resp.json()
    # 统一响应包装：token 在 ["data"] 层（方案原缺陷：直接取顶层 access_token）
    data = body.get("data") or {}
    token = data.get("access_token")
    if not token:
        _fail(f"登录响应缺少 data.access_token: {list(body.keys())}")
    print(f"  [OK] 登录成功，token={token[:20]}...")
    return token


def step_create_project(client: httpx.Client, base_url: str, token: str) -> int:
    print("步骤 2：创建测试项目")
    resp = client.post(
        f"{base_url}/api/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": f"安全报告冒烟-{time.strftime('%Y%m%d%H%M%S')}",
            "description": "smoke_security_report.py 自动创建",
            "target_system": base_url,
        },
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        _fail(f"创建项目失败: {resp.status_code} {resp.text[:200]}")
    project_id = (resp.json().get("data") or {}).get("id")
    if not project_id:
        _fail("创建项目响应缺少 data.id")
    print(f"  [OK] 项目创建成功 id={project_id}")
    return project_id


def step_run_security_test(client: httpx.Client, base_url: str, token: str,
                           project_id: int) -> int:
    print("步骤 3：创建并执行安全检测任务（HTTP_SECURITY_HEADERS）")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        f"{base_url}/api/tasks",
        headers=headers,
        json={
            "project_id": project_id,
            "name": "冒烟-HTTP安全头检测",
            "engines": ["HTTP_SECURITY_HEADERS"],
            "config": {"base_url": base_url},
        },
        timeout=20,
    )
    if resp.status_code not in (200, 201):
        _fail(f"创建任务失败: {resp.status_code} {resp.text[:300]}")
    task_id = (resp.json().get("data") or {}).get("id")
    if not task_id:
        _fail("创建任务响应缺少 data.id")

    resp = client.post(f"{base_url}/api/tasks/{task_id}/run", headers=headers, timeout=20)
    if resp.status_code != 200:
        _fail(f"触发任务执行失败: {resp.status_code} {resp.text[:300]}")

    # 轮询任务状态直至终态
    deadline = time.time() + 120
    status = ""
    while time.time() < deadline:
        time.sleep(2)
        r = client.get(f"{base_url}/api/tasks/{task_id}", headers=headers, timeout=15)
        if r.status_code != 200:
            continue
        status = ((r.json().get("data") or {}).get("status")) or ""
        if status in _TERMINAL_STATUSES:
            break
    else:
        _fail(f"任务执行超时（120s），最后状态：{status}")
    if status not in {"SUCCESS", "COMPLETED_WITH_RISK", "FAILED"}:
        _fail(f"任务异常终止：{status}")
    print(f"  [OK] 任务 {task_id} 执行完成，状态={status}")
    return task_id


def step_fetch_report_id(client: httpx.Client, base_url: str, token: str, task_id: int) -> int:
    print("步骤 4：获取任务产出的报告")
    resp = client.get(
        f"{base_url}/api/reports",
        headers={"Authorization": f"Bearer {token}"},
        params={"task_id": task_id, "page_size": 10},
        timeout=15,
    )
    if resp.status_code != 200:
        _fail(f"查询报告列表失败: {resp.status_code} {resp.text[:200]}")
    items = (resp.json().get("data") or {}).get("items") or []
    if not items:
        _fail(f"任务 {task_id} 未产出报告")
    report_id = items[0].get("id")
    print(f"  [OK] 报告 id={report_id}（{items[0].get('report_no')}）")
    return report_id


def step_get_security_report(client: httpx.Client, base_url: str, token: str,
                             report_id: int) -> dict:
    print("步骤 5：获取安全报告并校验 8 章节")
    resp = client.get(
        f"{base_url}/api/reports/{report_id}/security",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if resp.status_code != 200:
        _fail(f"获取安全报告失败: {resp.status_code} {resp.text[:200]}")
    data = resp.json().get("data") or {}
    missing = [k for k in SECURITY_SECTIONS if k not in data]
    if missing:
        _fail(f"安全报告缺少章节: {missing}")
    print(f"  [OK] 8 章节齐全；风险等级={data['executive_summary'].get('overall_risk_level')}，"
          f"发现 {len(data['detailed_findings'])} 项，良好实践 {len(data['good_practices'])} 项")
    return data


def step_export(client: httpx.Client, base_url: str, token: str, report_id: int) -> None:
    print("步骤 6：四格式导出（md/html/pdf/word 均须 200）")
    headers = {"Authorization": f"Bearer {token}"}
    for fmt in ("md", "html", "pdf", "word"):
        resp = client.get(
            f"{base_url}/api/reports/{report_id}/security/export",
            headers=headers,
            params={"format": fmt},
            timeout=60,
        )
        if resp.status_code != 200:
            _fail(f"导出 {fmt} 失败: {resp.status_code} {resp.text[:200]}")
        if len(resp.content) < 100:
            _fail(f"导出 {fmt} 内容异常（{len(resp.content)} 字节）")
        print(f"  [OK] {fmt} 导出 {len(resp.content)} 字节")


def main() -> int:
    parser = argparse.ArgumentParser(description="安全报告端到端冒烟")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    print("=" * 60)
    print(f"EvalShield 安全报告端到端冒烟  base_url={base_url}")
    print("=" * 60)

    probe_service(base_url)
    # trust_env=False：忽略系统代理对 localhost 的劫持（Windows 环境代理常导致本地请求超时）
    with httpx.Client(trust_env=False) as client:
        token = step_login(client, base_url)
        project_id = step_create_project(client, base_url, token)
        task_id = step_run_security_test(client, base_url, token, project_id)
        report_id = step_fetch_report_id(client, base_url, token, task_id)
        step_get_security_report(client, base_url, token, report_id)
        step_export(client, base_url, token, report_id)

    print("\n" + "=" * 60)
    print("[PASS] 端到端冒烟全部通过")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
