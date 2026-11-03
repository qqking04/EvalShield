# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""性能测试引擎：动态生成 JMeter 计划，经 CLI 真实压测，解析 jtl 输出真实指标。

前置：JMETER_HOME 指向含 bin/jmeter.bat 的目录、Java 17+ 可运行。
工具缺失/压测失败时返回清晰 FAILED，绝不造假指标。
"""

from __future__ import annotations

import csv
import math
import os
import shutil
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from ..config import settings
from .base import BaseEngine, EngineContext, EngineResult

logger = __import__("logging").getLogger("evalshield.engine.perf")

# 时间窗压测的 success/failed 计数锁
_counter_lock = threading.Lock()


# ---------------------------------------------------------------------------
# JMeter .jmx 单位骨架（参数通过 -Jxxx 注入，避免 url/特殊字符转义）
# ---------------------------------------------------------------------------
_JMX_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.3">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" enabled="true">
      <stringProp name="TestPlan.comments"></stringProp>
      <boolProp name="TestPlan.functional_mode">false</boolProp>
      <boolProp name="TestPlan.serialize_threadgroups">false</boolProp>
    </TestPlan>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" enabled="true">
        <stringProp name="ThreadGroup.on_sample_error">continue</stringProp>
        <elementProp name="ThreadGroup.main_controller" elementType="LoopController" guiclass="LoopControlPanel" testclass="LoopController" testname="Loop Controller" enabled="true">
          <boolProp name="LoopController.continue_forever">false</boolProp>
          <stringProp name="LoopController.loops">${__P(loopcount,1)}</stringProp>
        </elementProp>
        <stringProp name="ThreadGroup.num_threads">${__P(threads,10)}</stringProp>
        <stringProp name="ThreadGroup.ramp_time">${__P(rampup,1)}</stringProp>
        <boolProp name="ThreadGroup.scheduler">false</boolProp>
      </ThreadGroup>
      <hashTree>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="HTTP Request" enabled="true">
          <boolProp name="HTTPSampler.postBodyRaw">false</boolProp>
          <stringProp name="HTTPSampler.domain">${__P(basehost,127.0.0.1)}</stringProp>
          <stringProp name="HTTPSampler.port">${__P(baseport,8000)}</stringProp>
          <stringProp name="HTTPSampler.connect_timeout"></stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
          <stringProp name="HTTPSampler.path">${__P(basepath,/api/health)}</stringProp>
          <stringProp name="HTTPSampler.protocol">${__P(protocol,http)}</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
        <ResultCollector guiclass="SummaryReport" testclass="ResultCollector" testname="Summary Report" enabled="true">
          <boolProp name="ResultCollector.create_table">false</boolProp>
          <boolProp name="ResultCollector.error_logging">false</boolProp>
          <objProp>
            <name>saveConfig</name>
            <value class="SampleSaveConfiguration">
              <time>true</time><latency>true</latency><timestamp>true</timestamp>
              <success>true</success><label>true</label><code>true</code><message>true</message>
              <threadName>true</threadName><dataType>true</dataType><encoding>false</encoding>
              <assertions>true</assertions><subresults>true</subresults><responseData>false</responseData>
              <samplerData>false</samplerData><xml>false</xml><fieldNames>true</fieldNames>
              <responseDataOnError>false</responseDataOnError><saveAssertionResultsFailureMessage>false</saveAssertionResultsFailureMessage>
              <assertionsResultsToSave>0</assertionsResultsToSave><bytes>true</bytes>
            </value>
          </objProp>
          <stringProp name="filename"></stringProp>
        </ResultCollector>
        <hashTree/>
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>
"""


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(math.ceil(len(sorted_values) * pct)) - 1)
    return sorted_values[max(idx, 0)]


class PerfTestEngine(BaseEngine):
    engine_code = "PERF_TEST"
    engine_name = "性能测试引擎"
    engine_type = "TRADITIONAL"
    category = "PERF"
    version = "1.0.0"
    description = "JMeter 真实压测：并发/总请求/QPS/延迟分位（p50/p95/p99）与错误率。"
    fidelity = "rule"

    def _jmeter_bat(self) -> str | None:
        jmeter_home = getattr(settings, "JMETER_HOME", "") or ""
        if not jmeter_home:
            return None
        bat = os.path.join(jmeter_home, "bin", "jmeter.bat")
        if os.name == "nt" and os.path.exists(bat):
            return bat
        sh = os.path.join(jmeter_home, "bin", "jmeter")
        if not os.name == "nt" and os.path.exists(sh):
            return sh
        return None

    def _java_ok(self) -> bool:
        java = shutil.which("java")
        if not java:
            return False
        try:
            proc = subprocess.run(
                [java, "-version"],
                capture_output=True, text=True, timeout=15,
            )
            return proc.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    @staticmethod
    def _write_jmx(path: str, threads: int, ramp_up: int, loop_count: int,
                   url: str) -> None:
        p = urlsplit(url)
        protocol = p.scheme or "http"
        host = p.hostname or "127.0.0.1"
        port = str(p.port or (443 if protocol == "https" else 80))
        basepath = p.path or "/"
        if p.query:
            basepath += "?" + p.query
        xml = _JMX_TEMPLATE
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        # 参数在命令行用 -J 注入；这里仅保留占位，便于后续微调
        _ = (threads, ramp_up, loop_count, protocol, host, port, basepath)

    @staticmethod
    def _parse_jtl(path: str) -> dict[str, Any]:
        elapsed: list[float] = []
        total = 0
        failed = 0
        first: float | None = None
        last: float | None = None
        with open(path, newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                # 表头行：跳过非数据行（含字段名，如 timeStamp）
                if row[0].strip().lower() in ("timestamp", "timestamp_ms"):
                    continue
                try:
                    ts = float(row[0])
                    elapsed_ms = float(row[1])
                    success = row[7].strip().lower() == "true"
                except (IndexError, ValueError):
                    continue
                total += 1
                if not success:
                    failed += 1
                elapsed.append(elapsed_ms)
                if first is None:
                    first = ts
                last = ts
        if total == 0:
            raise ValueError("jtl 无有效样本")
        elapsed_sorted = sorted(elapsed)
        duration_sec = ((last or 0) - (first or 0)) / 1000.0
        if duration_sec <= 0:
            duration_sec = 1.0
        return {
            "total": total,
            "failed": failed,
            "error_rate": round(failed / total, 4),
            "avg_latency_ms": round(sum(elapsed) / len(elapsed), 1),
            "p50_ms": round(_percentile(elapsed_sorted, 0.50), 1),
            "p90_ms": round(_percentile(elapsed_sorted, 0.90), 1),
            "p95_ms": round(_percentile(elapsed_sorted, 0.95), 1),
            "p99_ms": round(_percentile(elapsed_sorted, 0.99), 1),
            "min_ms": round(min(elapsed), 1),
            "max_ms": round(max(elapsed), 1),
            "qps": round(total / duration_sec, 2),
        }

    # ------------------------------------------------------------------
    # httpx 降级压测（JMeter 不可用时自动启用，同样发真实请求、出真实指标）
    # ------------------------------------------------------------------
    @staticmethod
    def _execute_httpx_mode(
        url: str,
        concurrency: int,
        total: int,
        p95_limit_ms: float,
        target_qps: float,
        cfg: dict,
        ctx: EngineContext,
        duration_sec: float | None = None,
    ) -> EngineResult:
        """用 httpx + ThreadPoolExecutor 做真实并发压测，输出与 JMeter 同口径的 metrics。

        duration_sec 非空时启用「时间窗持续压测」：按并发梯度在窗口内循环发压直到到点，
        使 P95/P99 在持续负载下统计（v2.0 §8 性能用例时长模式），total 参数此时忽略。
        """
        import httpx
        from concurrent.futures import ThreadPoolExecutor, as_completed

        p = urlsplit(url)
        timeout = float(cfg.get("timeout_seconds", 10))

        def _one() -> tuple[float, bool, int | None]:
            """单次请求，返回 (elapsed_ms, success, status_code)。"""
            start = time.perf_counter()
            try:
                with httpx.Client(timeout=timeout) as c:
                    resp = c.request(
                        method=(cfg.get("method") or "GET").upper(),
                        url=url,
                        headers=cfg.get("headers") or {},
                        json=cfg.get("json"),
                        data=cfg.get("data"),
                    )
                elapsed = int((time.perf_counter() - start) * 1000)
                return elapsed, resp.status_code < 500, resp.status_code
            except (httpx.TimeoutException, httpx.HTTPError) as exc:
                elapsed = int((time.perf_counter() - start) * 1000)
                logger.debug("httpx 压测失败: %s", exc)
                return elapsed, False, None

        elapsed_list: list[float] = []
        failed = 0
        success = 0

        start = time.perf_counter()
        if duration_sec and duration_sec > 0:
            # 时间窗模式：并发 worker 各自循环发压，到点统一停止
            deadline = start + duration_sec
            stop_event = threading.Event()

            def _worker_loop() -> None:
                while not stop_event.is_set() and time.perf_counter() < deadline:
                    e_ms, ok, _ = _one()
                    elapsed_list.append(e_ms)
                    # list.append 在 CPython 下线程安全；计数用锁保护
                    nonlocal failed, success
                    with _counter_lock:
                        if ok:
                            success += 1
                        else:
                            failed += 1

            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                workers = [pool.submit(_worker_loop) for _ in range(concurrency)]
                for w in workers:
                    try:
                        w.result(timeout=duration_sec + timeout + 5)
                    except Exception:  # noqa: BLE001
                        stop_event.set()
                stop_event.set()
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(_one) for _ in range(total)]
                for fut in as_completed(futures):
                    try:
                        e_ms, ok, _ = fut.result()
                        elapsed_list.append(e_ms)
                        if ok:
                            success += 1
                        else:
                            failed += 1
                    except Exception:  # noqa: BLE001
                        failed += 1
        exec_ms = int((time.perf_counter() - start) * 1000)
        duration_actual = exec_ms / 1000.0 if exec_ms > 0 else 1.0

        if not elapsed_list:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1},
                report_payload={"error": "httpx 压测未获得任何样本"},
                error="httpx 压测未获得任何样本",
            )

        elapsed_sorted = sorted(elapsed_list)
        total_req = success + failed
        metrics = {
            "mode": "httpx_fallback",
            "total": total_req,
            "failed": failed,
            "error_rate": round(failed / total_req, 4) if total_req else 1.0,
            "avg_latency_ms": round(sum(elapsed_list) / len(elapsed_list), 1),
            "p50_ms": round(_percentile(elapsed_sorted, 0.50), 1),
            "p90_ms": round(_percentile(elapsed_sorted, 0.90), 1),
            "p95_ms": round(_percentile(elapsed_sorted, 0.95), 1),
            "p99_ms": round(_percentile(elapsed_sorted, 0.99), 1),
            "min_ms": round(min(elapsed_list), 1),
            "max_ms": round(max(elapsed_list), 1),
            "qps": round(total_req / duration_actual, 2),
            "url": url,
            "concurrency": concurrency,
            "total_requests": total_req,
            "target_qps": target_qps,
            "p95_limit_ms": p95_limit_ms,
            "exec_duration_ms": exec_ms,
            "key": "perf_qps",
        }
        qps = metrics["qps"]
        p95 = metrics["p95_ms"]
        passed = bool(not target_qps or qps >= target_qps) and bool(p95 <= p95_limit_ms)
        return EngineResult(
            status="SUCCESS" if passed else "FAILED",
            summary={
                "total": metrics["total"],
                "passed": metrics["total"] - metrics["failed"],
                "failed": metrics["failed"],
                "pass_rate": round(1.0 - metrics["error_rate"], 4),
                "key": "perf_qps",
                "metrics": metrics,
            },
            report_payload={
                "engine": "PERF_TEST",
                "metrics": metrics,
                "conclusion": (
                    f"性能指标达标（httpx 模式）：QPS={qps}, P95={p95}ms"
                    if passed
                    else f"性能指标未达标：QPS={qps} (目标>{target_qps}), P95={p95}ms (limit={p95_limit_ms})"
                ),
            },
            error=None if passed else "性能指标未达标",
        )

    # ------------------------------------------------------------------
    # v2.0 用例驱动模式：逐条 PERFORMANCE 用例真实压测并按断言判定
    # ------------------------------------------------------------------
    def _execute_cases_mode(self, ctx: EngineContext, cfg: dict) -> EngineResult | None:
        """加载 category=PERFORMANCE 用例逐条压测；无用例时返回 None 回退单 URL 模式。"""
        if ctx.db is None or not ctx.project_id:
            return None
        from ..models import TestCase

        q = ctx.db.query(TestCase).filter(
            TestCase.project_id == ctx.project_id,
            TestCase.category == "PERFORMANCE",
            TestCase.status == "ACTIVE",
            TestCase.deleted_at.is_(None),  # DISC-05：过滤软删用例
        )
        if cfg.get("case_ids") or ctx.extra.get("case_ids"):
            ids = cfg.get("case_ids") or ctx.extra.get("case_ids")
            q = q.filter(TestCase.id.in_(ids))
        cases = q.limit(int(cfg.get("max_cases", 20))).all()
        if not cases:
            return None

        base_url = (
            cfg.get("base_url")
            or ctx.extra.get("base_url")
            or settings.API_DEFAULT_BASE_URL
        ).rstrip("/")
        headers = dict(cfg.get("headers") or {})
        results: list[dict[str, Any]] = []
        for case in cases:
            pc = case.performance_config or {}
            rs = case.request_spec or {}
            path = str(rs.get("path") or "")
            if not path:
                results.append({"case_no": case.case_no, "title": case.title, "result": "FAIL",
                                "failures": ["E_PERF_NO_PATH: 用例缺少 request_spec.path"], "metrics": {}})
                continue
            url = path if path.startswith("http") else base_url + path
            concurrency_list = pc.get("concurrency") or [int(pc.get("threads", 10))]
            if isinstance(concurrency_list, (int, float)):
                concurrency_list = [int(concurrency_list)]
            concurrency_list = [int(x) for x in concurrency_list if int(x) > 0] or [10]
            duration = int(pc.get("duration", 10))
            # v2.0 推荐方案 #2：并发梯度逐级压测——每档跑 duration/档数 秒，汇总 per-level 指标表；
            # max_duration_sec 封顶整条用例总窗口，防止任务过长
            total_window = min(duration, int(cfg.get("max_duration_sec", 30)))
            per_level = max(1, total_window // len(concurrency_list))
            failures: list[str] = []
            level_metrics: list[dict[str, Any]] = []
            worst: dict[str, Any] = {}
            for lvl in concurrency_list:
                total = max(10, lvl * max(1, per_level // 2))
                sub = PerfTestEngine._execute_httpx_mode(
                    url=url, concurrency=lvl, total=total,
                    p95_limit_ms=float(pc.get("target_rt_p95", 500)),
                    target_qps=float(pc.get("target_tps", 0)),
                    cfg={**cfg, "method": rs.get("method") or "GET", "headers": {**headers, **(rs.get("headers") or {})}},
                    ctx=ctx,
                    duration_sec=per_level,
                )
                m = (sub.summary or {}).get("metrics") or {}
                level_metrics.append({
                    "concurrency": lvl,
                    "total": m.get("total"), "qps": m.get("qps"),
                    "p95_ms": m.get("p95_ms"), "p99_ms": m.get("p99_ms"),
                    "error_rate": m.get("error_rate"),
                })
                # 以最高并发档作为断言判定基准（梯度压测关注高负载表现）
                if lvl == concurrency_list[-1]:
                    worst = m
            # 按用例断言判定（rt_p95/rt_p99/error_rate，取最高并发档指标）
            for a in case.assertions or []:
                if not isinstance(a, dict):
                    continue
                ap = str(a.get("path") or "")
                exp = a.get("expected")
                actual = {"rt_p95": worst.get("p95_ms"), "rt_p99": worst.get("p99_ms"),
                          "error_rate": worst.get("error_rate"), "tps": worst.get("qps")}.get(ap)
                if actual is None or exp is None:
                    continue
                op = str(a.get("op") or "lte")
                try:
                    ok = actual <= float(exp) if op == "lte" else actual >= float(exp) if op == "gte" else actual == float(exp)
                except (TypeError, ValueError):
                    ok = False
                if not ok:
                    failures.append(f"E_PERF_ASSERT: {ap} 实际 {actual} {op} {exp} 不满足（并发 {concurrency_list[-1]}）")
            results.append({
                "case_no": case.case_no, "case_id": case.id, "title": case.title,
                "result": "FAIL" if failures else "PASS",
                "failures": failures,
                "metrics": {k: worst.get(k) for k in ("p95_ms", "p99_ms", "qps", "error_rate", "total")},
                "levels": level_metrics,
                "concurrency": concurrency_list,
            })
        passed = sum(1 for r in results if r["result"] == "PASS")
        failed = len(results) - passed
        overall = "SUCCESS" if failed == 0 else "FAILED"
        return EngineResult(
            status=overall,
            summary={"total": len(results), "passed": passed, "failed": failed,
                     "pass_rate": round(passed / len(results), 4) if results else 0.0, "key": "perf_case_pass_rate"},
            report_payload={"engine": "PERF_TEST", "mode": "case_driven", "results": results,
                            "conclusion": f"性能用例 {passed}/{len(results)} 达标"},
            error=None if failed == 0 else f"{failed} 条性能用例未达标",
        )

    def execute(self, ctx: EngineContext) -> EngineResult:
        cfg = ctx.config or {}

        # v2.0 全维度：用例驱动模式——项目存在 category=PERFORMANCE 用例时，
        # 逐用例读取 performance_config + request_spec 真实压测并按断言判定
        case_result = self._execute_cases_mode(ctx, cfg)
        if case_result is not None:
            return case_result

        url = (
            cfg.get("url")
            or ctx.extra.get("base_url")
            or settings.API_DEFAULT_BASE_URL
        )
        concurrency = int(cfg.get("concurrency", 10))
        total = int(cfg.get("total_requests", 100))
        ramp_up = int(cfg.get("ramp_up_seconds", 1))
        p95_limit_ms = float(cfg.get("p95_limit_ms", 500))
        target_qps = float(cfg.get("target_qps", 0))

        if concurrency <= 0 or total <= 0:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1},
                report_payload={"error": "压测参数非法：concurrency/total_requests 必须为正"},
                error="压测参数非法：concurrency/total_requests 必须为正",
            )

        # ---- 强制真实 JMeter：工具缺失直接 FAILED，永不降级 ----
        jmeter_bat = self._jmeter_bat()
        java_ok = self._java_ok()
        if jmeter_bat is None or not java_ok:
            missing = []
            if jmeter_bat is None:
                missing.append("JMETER_HOME 未配置（需指向含 bin/jmeter.bat 的目录）")
            if not java_ok:
                missing.append("Java 运行时缺失（需 Java 17+，已装进 Docker openjdk-21）")
            err_msg = f"JMeter 不可用，性能压测无法执行。缺失: {'、'.join(missing)}"
            logger.error(err_msg)
            return EngineResult(
                engine_code="PERF_TEST",
                status="FAILED",
                metrics={"exec_seconds": 0},
                summary={"total": 0, "passed": 0, "failed": 1},
                report_payload={"error": err_msg},
                error=err_msg,
            )

        # ---- 生成 jmx / jtl 到 E 盘 ----
        work_dir = settings.REPORT_DIR
        os.makedirs(work_dir, exist_ok=True)
        step_tag = ctx.step_no or str(int(time.time()))
        jmx_path = os.path.join(work_dir, f"perf_{step_tag}.jmx")
        jtl_path = os.path.join(work_dir, f"perf_{step_tag}.jtl")
        loop_count = max(1, int(math.ceil(total / concurrency)))
        self._write_jmx(jmx_path, concurrency, ramp_up, loop_count, url)

        p = urlsplit(url)
        protocol = p.scheme or "http"
        host = p.hostname or "127.0.0.1"
        port = str(p.port or (443 if protocol == "https" else 80))
        basepath = (p.path or "/") + (("?" + p.query) if p.query else "")

        cmd = [
            jmeter_bat,
            "-n",
            "-t", jmx_path,
            "-l", jtl_path,
            f"-Jthreads={concurrency}",
            f"-Jloopcount={loop_count}",
            f"-Jrampup={ramp_up}",
            f"-Jprotocol={protocol}",
            f"-Jbasehost={host}",
            f"-Jbaseport={port}",
            f"-Jbasepath={basepath}",
        ]
        timeout = int(cfg.get("jmeter_timeout_seconds", settings.JMETER_TIMEOUT_SECONDS))

        start = time.perf_counter()
        try:
            if os.name == "nt":
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW（Windows）
                )
            else:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout,
                )
        except subprocess.TimeoutExpired:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1},
                report_payload={"error": f"JMeter 压测超时（>{timeout}s）"},
                error=f"JMeter 压测超时（>{timeout}s）",
            )
        exec_ms = int((time.perf_counter() - start) * 1000)

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-400:]
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1},
                report_payload={"error": f"jmeter 退出码 {proc.returncode}: {tail}"},
                error=f"jmeter 退出码 {proc.returncode}: {tail}",
                artifacts=[{"name": f"perf_log_{step_tag}", "type": "LOG", "path": None, "payload": tail}],
            )

        if not os.path.exists(jtl_path) or os.path.getsize(jtl_path) == 0:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1},
                report_payload={"error": "jmeter 未产出 jtl，压测失败"},
                error="jmeter 未产出 jtl，压测失败",
            )

        try:
            metrics = self._parse_jtl(jtl_path)
        except Exception as exc:  # noqa: BLE001
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1},
                report_payload={"error": f"解析 jtl 失败: {exc}"},
                error=f"解析 jtl 失败: {exc}",
            )

        metrics.update(
            {
                "url": url,
                "concurrency": concurrency,
                "total_requests": int(cfg.get("total_requests", total)) if "total_requests" not in metrics else metrics["total"],
                "target_qps": target_qps,
                "p95_limit_ms": p95_limit_ms,
                "exec_duration_ms": exec_ms,
                "key": "perf_qps",
            }
        )
        qps = metrics["qps"]
        p95 = metrics["p95_ms"]
        passed = bool(not target_qps or qps >= target_qps) and bool(p95 <= p95_limit_ms)
        return EngineResult(
            status="SUCCESS" if passed else "FAILED",
            summary={
                "total": metrics["total"],
                "passed": metrics["total"] - metrics["failed"],
                "failed": metrics["failed"],
                "pass_rate": round(1.0 - metrics["error_rate"], 4),
                "key": "perf_qps",
                "metrics": metrics,
            },
            report_payload={
                "engine": self.engine_code,
                "metrics": metrics,
                "conclusion": "性能指标达标" if passed else "性能指标未达标（QPS或P95超限）",
            },
            artifacts=[
                {"name": f"perf_metrics_{step_tag}", "type": "JSON", "payload": metrics},
                {"name": f"perf_jtl_{step_tag}", "type": "FILE", "path": jtl_path},
                {"name": f"perf_jmx_{step_tag}", "type": "FILE", "path": jmx_path},
            ],
            error=None if passed else "性能指标未达标",
        )