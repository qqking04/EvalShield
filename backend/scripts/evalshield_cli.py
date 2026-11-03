# -*- coding: utf-8 -*-
"""P1-16 CLI 工具：本地触发 EvalShield 测试套件并轮询结果。

用法：
  python evalshield_cli.py run --base http://127.0.0.1:8000 --token <WEBHOOK_SECRET> \
      --suite 回归测试 [--project 25] [--task-id 1] [--timeout 900] [--out junit.xml]

依赖：httpx（后端已有）。退出码：0=全部通过，1=存在失败，2=触发/等待异常。
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx


def _gate_headers(token: str | None) -> dict:
    """门禁端点鉴权头：JWT（两段以上 . 分隔）走 Bearer，其余按 X-API-Key 发送。"""
    if not token:
        return {}
    if token.count(".") >= 2:
        return {"Authorization": f"Bearer {token}"}
    return {"X-API-Key": token}


def _print_verdict(data: dict, verbose: bool = False) -> int:
    """打印人类可读门禁摘要，返回服务端 exit_code 语义（0/1/2）。

    TC-U7-04：非 0 结果默认截断 summary（前 20 条明细 + "…共 N 条"），
    --verbose 才全量 dump JSON，避免 CI 日志噪音。
    """
    code = int(data.get("exit_code") if data.get("exit_code") is not None else 2)
    er_lines = []
    for er in data.get("engine_results") or []:
        sm = er.get("summary") or {}
        er_lines.append(
            f"   - {er.get('engine')}: {er.get('status')}"
            + (f"（failed={sm.get('failed', 0)}, pass_rate={sm.get('pass_rate', 'N/A')}）"
               if sm else "")
        )
    if code == 0:
        print(f"✅ CI 门禁通过（task={data.get('task_no')}, "
              f"report={data.get('report_id') or '无'}）")
    else:
        why = data.get("error") or ("执行异常" if code == 2 else "未通过")
        print(f"❌ CI 门禁{why}（task={data.get('task_no')}, exit_code={code}）")
    for line in er_lines:
        print(line)
    if code != 0 and data.get("summary"):
        summary = data["summary"]
        if verbose:
            print(json.dumps(summary, ensure_ascii=False, default=str))
        else:
            print(_truncate_summary(summary))
    return code if code in (0, 1, 2) else 2


def _truncate_summary(summary, limit: int = 20) -> str:
    """summary 截断：dict/list 中首个超长列表截到 limit 条并标注总数。"""
    if isinstance(summary, list):
        items = summary
    elif isinstance(summary, dict):
        items = None
        for key in ("failed_cases", "failures", "results", "cases"):
            v = summary.get(key)
            if isinstance(v, list) and len(v) > limit:
                items = v
                break
        if items is None:
            # 无超长列表：只打印标量键，省略嵌套明细
            scalars = {k: v for k, v in summary.items()
                       if not isinstance(v, (list, dict))}
            nested = [k for k, v in summary.items()
                      if isinstance(v, (list, dict))]
            text = json.dumps(scalars, ensure_ascii=False, default=str)
            if nested:
                text += f" …（嵌套明细省略：{', '.join(nested)}；--verbose 全量）"
            return text
    else:
        return json.dumps(summary, ensure_ascii=False, default=str)
    head = json.dumps(items[:limit], ensure_ascii=False, default=str)
    return f"{head}\n   …共 {len(items)} 条（默认截断 {limit} 条，--verbose 全量输出）"


def _apply_severity_gate(data: dict, max_critical: int, max_high: int) -> int:
    """本地严重度阈值：引擎 summary 里的 critical/high 计数超限时把通过改为不通过。"""
    if data.get("exit_code") != 0:
        return int(data.get("exit_code"))
    critical = high = 0
    for er in data.get("engine_results") or []:
        sm = er.get("summary") or {}
        critical += int(sm.get("critical") or 0)
        high += int(sm.get("high") or 0)
    if critical > max_critical or high > max_high:
        print(f"❌ CI 门禁未通过：严重度超限（critical={critical}>{max_critical} 或 "
              f"high={high}>{max_high}）")
        return 1
    return 0


def _gate_poll(url: str, headers: dict, task_id: int, interval: int, timeout: int) -> tuple[dict | None, str | None]:
    """轮询 /api/ci-gate/status/{task_id} 直至任务结束。返回 (data, 错误信息)。"""
    deadline = time.time() + timeout
    while True:
        try:
            r = httpx.get(f"{url}/api/ci-gate/status/{task_id}",
                          headers=headers, timeout=15)
            body = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            return None, f"轮询异常: {exc}"
        if body.get("code") != 0:
            return None, f"轮询失败: {body.get('message')}"
        data = body.get("data") or {}
        if not data.get("running"):
            return data, None
        print(f"   ... 门禁任务 #{task_id} 进行中"
              f"（status={data.get('task_status')}）")
        if time.time() >= deadline:
            return None, f"轮询超时（{timeout}s）"
        time.sleep(max(1, interval))


def _eval_report(rep: dict, max_critical: int, max_high: int) -> int:
    """按报告 summary/risk_level 评估严重度阈值，返回 exit 0/1。"""
    sm = rep.get("summary") or {}
    risk = str(rep.get("risk_level") or "none").lower()
    critical = int(sm.get("critical") or 0) + (1 if risk == "critical" else 0)
    high = int(sm.get("high") or 0) + (1 if risk == "high" else 0)
    if critical > max_critical or high > max_high:
        print(f"❌ CI 门禁未通过（report={rep.get('id')}, "
              f"critical={critical}>{max_critical} 或 high={high}>{max_high}）")
        return 1
    print(f"✅ CI 门禁通过（report={rep.get('id')}, task={rep.get('task_no') or '无'}）")
    return 0


def cmd_gate(args) -> int:
    """gate 子命令：触发 /api/ci-gate/run 或评估既有任务/报告，exit 0/1/2。"""
    url = args.url.rstrip("/")
    headers = _gate_headers(args.token)

    # 模式 1：按报告 ID 评估既有结果（不触发新任务）
    if args.report_id is not None:
        try:
            r = httpx.get(f"{url}/api/reports/{args.report_id}",
                          headers=headers, timeout=15)
            body = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            print(f"[gate] 网络/响应异常: {exc}", file=sys.stderr)
            return 2
        if body.get("code") != 0:
            print(f"[gate] 报告查询失败: {body.get('message')}", file=sys.stderr)
            return 2
        return _eval_report(body.get("data") or {}, args.max_critical, args.max_high)

    # 模式 2：查询既有门禁任务（数字 task_id 走轮询；TSK 编号经报告列表回退评估）
    if args.task_no:
        if args.task_no.isdigit():
            data, err = _gate_poll(url, headers, int(args.task_no),
                                   args.interval, args.timeout)
            if err:
                print(f"[gate] {err}", file=sys.stderr)
                return 2
            code = _print_verdict(data, verbose=getattr(args, "verbose", False))
            if code == 0:
                code = _apply_severity_gate(data, args.max_critical, args.max_high)
            return code
        try:
            r = httpx.get(f"{url}/api/reports",
                          params={"task_no": args.task_no, "page_size": 1},
                          headers=headers, timeout=15)
            body = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            print(f"[gate] 任务查询失败: {exc}", file=sys.stderr)
            return 2
        items = ((body.get("data") or {}).get("items")) or []
        if not items:
            print(f"[gate] 任务 {args.task_no} 无门禁报告（数字 task_id 可直接轮询）",
                  file=sys.stderr)
            return 2
        return _eval_report(items[0], args.max_critical, args.max_high)

    # 模式 3：触发新门禁（需要 --target）
    if not args.target:
        print("[gate] 参数错误：需提供 --target（触发新门禁）或 --task-no/--report-id（评估既有结果）",
              file=sys.stderr)
        return 2
    try:
        engines = json.loads(args.engines)
        if not isinstance(engines, list) or not all(isinstance(e, str) for e in engines):
            raise ValueError("engines 必须是字符串数组")
    except ValueError as exc:
        print(f"[gate] --engines 参数非法: {exc}", file=sys.stderr)
        return 2

    body = {
        "target_code": args.target,
        "engines": engines,
        "async_mode": not args.sync,
    }
    if args.project is not None:
        body["project_id"] = args.project
    try:
        r = httpx.post(f"{url}/api/ci-gate/run", json=body, headers=headers, timeout=60)
        resp = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"❌ EvalShield 无响应或返回异常（{url}）: {exc}", file=sys.stderr)
        return 2
    if resp.get("code") != 0:
        print(f"[gate] 门禁触发失败: {resp.get('message')}", file=sys.stderr)
        return 2
    data = resp.get("data") or {}
    if data.get("async"):
        task_id = int(data["task_id"])
        print(f"⏳ 门禁任务 #{task_id} 已提交，轮询状态"
              f"（间隔 {args.interval}s，超时 {args.timeout}s）...")
        data, err = _gate_poll(url, headers, task_id, args.interval, args.timeout)
        if err:
            print(f"❌ {err}", file=sys.stderr)
            return 2
    code = _print_verdict(data, verbose=getattr(args, "verbose", False))
    if code == 0:
        code = _apply_severity_gate(data, args.max_critical, args.max_high)
    return code


def main() -> int:
    ap = argparse.ArgumentParser(prog="evalshield", description="EvalShield CI CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="触发任务/套件执行并等待结果")
    run.add_argument("--base", default="http://127.0.0.1:8000", help="平台地址")
    run.add_argument("--token", required=True, help="Webhook Token（WEBHOOK_SECRET）")
    run.add_argument("--suite", default=None, help="测试套件名称")
    run.add_argument("--project", type=int, default=None, help="项目 ID（配合套件定位）")
    run.add_argument("--task-id", type=int, default=None, help="直接指定任务 ID")
    run.add_argument("--ref", default=None, help="Git 分支/tag（仅记录）")
    run.add_argument("--timeout", type=int, default=900, help="等待执行超时秒数")
    run.add_argument("--out", default=None, help="JUnit XML 落盘路径")

    gate = sub.add_parser(
        "gate", help="CI 安全门禁：触发/查询 /api/ci-gate 并给出 pass/fail 退出码"
    )
    gate.add_argument("--url", default="http://localhost:8000", help="平台地址")
    gate.add_argument("--token", default=None,
                      help="Bearer JWT 或 X-API-Key（可选，服务端鉴权需要时提供）")
    gate.add_argument("--target", default=None,
                      help="被测目标编码（触发新门禁时使用）")
    gate.add_argument("--engines", default='["JAILBREAK", "PII_LEAK"]',
                      help='引擎列表 JSON（默认 ["JAILBREAK", "PII_LEAK"]）')
    gate.add_argument("--project", type=int, default=None, help="项目 ID（可选）")
    gate.add_argument("--sync", action="store_true",
                      help="同步模式：服务端阻塞执行（默认异步+轮询，避免长任务 HTTP 超时）")
    gate.add_argument("--task-no", default=None,
                      help="查询既有门禁任务（TSK 编号或数字 task_id），不再触发新任务")
    gate.add_argument("--report-id", type=int, default=None,
                      help="按报告 ID 评估既有结果（不触发新任务）")
    gate.add_argument("--max-critical", type=int, default=0,
                      help="Critical 级问题数上限（默认 0）")
    gate.add_argument("--max-high", type=int, default=0,
                      help="High 级问题数上限（默认 0）")
    gate.add_argument("--interval", type=int, default=10, help="轮询间隔秒数")
    gate.add_argument("--timeout", type=int, default=1800, help="轮询超时秒数")
    gate.add_argument("--verbose", action="store_true",
                      help="门禁未通过时全量输出 summary JSON（默认截断前 20 条）")

    args = ap.parse_args()

    if args.cmd == "gate":
        return cmd_gate(args)
    if args.cmd != "run":
        ap.print_help()
        return 2

    body = {"suite_name": args.suite, "project_id": args.project,
            "task_id": args.task_id, "ref": args.ref}
    headers = {"X-Webhook-Token": args.token}
    try:
        resp = httpx.post(f"{args.base}/api/webhook/ci-trigger", json=body,
                          headers=headers, timeout=30)
        data = resp.json()
        if data.get("code") != 0:
            print(f"[CLI] 触发失败: {data.get('message')}", file=sys.stderr)
            return 2
        launched = data["data"]["launched"]
        if not launched:
            print("[CLI] 无任务被触发（可能正在运行）", file=sys.stderr)
            return 2
        print(f"[CLI] 已触发 {len(launched)} 个任务: "
              + ", ".join(x["task_no"] for x in launched))
    except (httpx.HTTPError, ValueError) as exc:
        print(f"[CLI] 触发异常: {exc}", file=sys.stderr)
        return 2

    # 轮询任务终态（Webhook Token 鉴权的免登录状态端点）
    deadline = time.time() + args.timeout
    task_ids = [x["task_id"] for x in launched]
    statuses: dict[int, str] = {}
    report_ids: dict[int, int] = {}
    while time.time() < deadline:
        done = True
        for tid in task_ids:
            try:
                r = httpx.get(f"{args.base}/api/webhook/ci-status/{tid}",
                              headers=headers, timeout=15)
                row = r.json().get("data") or {}
                st = row.get("status") or "UNKNOWN"
                statuses[tid] = st
                if row.get("report_id"):
                    report_ids[tid] = row["report_id"]
                if st not in ("SUCCESS", "FAILED", "CANCELLED", "PARTIAL"):
                    done = False
            except httpx.HTTPError:
                done = False
        if done:
            break
        time.sleep(5)
    else:
        print("[CLI] 等待超时", file=sys.stderr)
        return 2

    failed = [t for t, s in statuses.items() if s in ("FAILED", "CANCELLED")]
    print(f"[CLI] 执行完成：{len(statuses)} 个任务，失败 {len(failed)} 个")

    # 导出 JUnit（取最后一个有报告的任务）
    if args.out and report_ids:
        rid = list(report_ids.values())[-1]
        try:
            xml = httpx.get(f"{args.base}/api/reports/{rid}/export-junit",
                            headers=headers, timeout=30).text
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(xml)
            print(f"[CLI] JUnit XML 已写入 {args.out}")
        except (httpx.HTTPError, KeyError) as exc:
            print(f"[CLI] JUnit 导出失败（不影响判定）: {exc}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # TC-CLI-03：Ctrl+C 优雅中断，友好提示不抛 traceback，退出码 130（128+SIGINT 惯例）
        print("\n[gate] 已中断（Ctrl+C）")
        sys.exit(130)
