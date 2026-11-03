#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ES11 性能基线采集（nightly CI 入口）。

跑 backend/tests/perf 全套（-m perf），解析 stdout 中的
    [perf] <url> -> {json}          # in-process ASGI 样本
    [live-perf] <url> -> {json}     # 真实多 worker HTTP 样本
按用例归并（同用例多样本取最大 p95），写入
verification/perf-baselines/es11-<用例>-<yyyyMMdd>.json（含 p95_ms 字段，
与 ES8-BUG-009 check_perf_baseline.py 同格式），随后复用其判据：
P95 环比劣化 > 20% → exit 1。

用法（仓库根或任意目录均可，DB_* 环境变量按 backend 配置约定注入）：
    python scripts/collect_es11_perf.py
退出码: 0 = 采集+对比通过; 1 = 劣化超阈; 2 = pytest 套件失败/无样本
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BACKEND = os.path.join(ROOT, "backend")
BASELINE_DIR = os.path.join(ROOT, "verification", "perf-baselines")
sys.path.insert(0, HERE)
import check_perf_baseline as cpb  # noqa: E402

LINE_RE = re.compile(r"^\[(?:live-)?perf\] (\S+) -> (\{.*\})\s*$", re.M)

# URL → 用例名（PERF-001~006；live 样本与 in-process 同用例归并）
def _scenario(url: str):
    path = url.split("?", 1)[0]
    if path.startswith("/api/dashboard/quality"):
        return "es11-dashboard"
    if path.endswith("/workspace"):
        return "es11-workspace"
    if path.endswith("/items"):
        return "es11-items"
    if path == "/api/eval-runs":
        return "es11-activity"
    if path.endswith("/compare"):
        return "es11-compare"
    if path.endswith("/timeline"):
        return "es11-timeline"
    return None


def main() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/perf", "-m", "perf",
         "--no-cov", "-q", "-s"],
        cwd=BACKEND, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=3600)
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        print(out[-4000:])
        print(f"[collect] pytest perf 套件失败 rc={proc.returncode}，不写基线")
        return 2

    samples = {}
    for m in LINE_RE.finditer(out):
        scen = _scenario(m.group(1))
        if not scen:
            continue
        try:
            data = json.loads(m.group(2))
        except json.JSONDecodeError:
            continue
        samples.setdefault(scen, []).append((m.group(1), data))
    if not samples:
        print("[collect] 未解析到任何 [perf]/[live-perf] 样本")
        return 2

    os.makedirs(BASELINE_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    written = []
    for scen, rows in sorted(samples.items()):
        p95 = max(int(d["p95"]) for _, d in rows)
        payload = {
            "scenario": scen,
            "collected_at": datetime.now().isoformat(timespec="seconds"),
            "source": "backend/tests/perf (pytest -m perf)",
            "p95_ms": p95,
            "p50_ms": max(int(d["p50"]) for _, d in rows),
            "max_ms": max(int(d["max"]) for _, d in rows),
            "request_count": sum(int(d["n"]) for _, d in rows),
            "samples": [{"url": u, **d} for u, d in rows],
        }
        path = os.path.join(BASELINE_DIR, f"{scen}-{today}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        written.append(path)
        print(f"[collect] {scen}: P95={p95}ms（{len(rows)} 样本）→ {os.path.basename(path)}")

    rc = 0
    for path in written:
        scen = os.path.basename(path).rsplit("-", 1)[0]
        base_path, cur_path = cpb.latest_pair(scen)
        if not base_path:
            print(f"[INFO] {scen}: 首次基线，无历史可对比")
            continue
        rc = max(rc, cpb.check_pair(cur_path, base_path))
    return rc


if __name__ == "__main__":
    sys.exit(main())
