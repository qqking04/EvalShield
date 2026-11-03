#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ES8-BUG-009 性能基线回归检查。

读取 verification/perf-baselines/<scenario>-*.json 基线（文件名含日期，
取最近两份做对比；也可 --current/--baseline 显式指定），
P95 回归幅度 > 20% 时打印 warning 并以非 0 退出。

用法:
  python scripts/check_perf_baseline.py                    # 无参数 → 打印 usage
  python scripts/check_perf_baseline.py --all              # 检查全部 4 场景
  python scripts/check_perf_baseline.py --scenario quality
  python scripts/check_perf_baseline.py --current a.json --baseline b.json

退出码: 0 = 通过/信息不足仅提示; 1 = 检测到 P95 回归 > 20%; 2 = 参数错误
"""
import argparse
import glob
import json
import os
import re
import sys

REGRESSION_THRESHOLD = 0.20  # P95 回归 >20% 告警
SCENARIOS = ("quality", "platform", "ingest", "retention")
BASELINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "verification", "perf-baselines",
)

USAGE = __doc__


def _date_key(path: str):
    """按文件名末尾 <date>.json 排序（yyyyMMdd），同日按 mtime。"""
    m = re.search(r"-(\d{8})\.json$", os.path.basename(path))
    return (m.group(1) if m else "0", os.path.getmtime(path))


def latest_pair(scenario: str):
    files = sorted(
        glob.glob(os.path.join(BASELINE_DIR, f"{scenario}-*.json")), key=_date_key
    )
    if len(files) < 2:
        return None, files[-1] if files else None
    return files[-2], files[-1]


def check_pair(current_path: str, baseline_path: str) -> int:
    with open(current_path, encoding="utf-8-sig") as f:
        cur = json.load(f)
    with open(baseline_path, encoding="utf-8-sig") as f:
        base = json.load(f)
    scenario = cur.get("scenario", "?")
    if "p95_ms" not in cur or "p95_ms" not in base:
        print(f"[INFO] {scenario}: 文件缺少 p95_ms 字段，跳过对比")
        return 0
    cur_p95, base_p95 = float(cur["p95_ms"]), float(base["p95_ms"])
    if base_p95 <= 0:
        print(f"[INFO] {scenario}: 基线 P95 非正值，跳过对比")
        return 0
    delta = (cur_p95 - base_p95) / base_p95
    if delta > REGRESSION_THRESHOLD:
        print(
            f"WARNING [{scenario}] P95 回归 {delta:+.1%}"
            f"（基线 {base_p95:.0f}ms → 当前 {cur_p95:.0f}ms，阈值 {REGRESSION_THRESHOLD:.0%}）"
        )
        return 1
    print(
        f"OK [{scenario}] P95 {cur_p95:.0f}ms vs 基线 {base_p95:.0f}ms"
        f"（{delta:+.1%}，阈值内）"
    )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="ES8 性能基线 P95 回归检查（详见 --help 顶部说明）",
        add_help=True,
    )
    parser.add_argument("--scenario", choices=SCENARIOS, help="单场景检查")
    parser.add_argument("--all", action="store_true", help="检查全部 4 场景")
    parser.add_argument("--current", help="显式指定当前基线 JSON 路径")
    parser.add_argument("--baseline", help="显式指定对比基准 JSON 路径")
    # 无参数时先输出 usage 再退出 0（任务口径：不做破坏性默认行为）
    if len(sys.argv) == 1:
        print(USAGE)
        return 0
    args = parser.parse_args(argv)

    if args.current or args.baseline:
        if not (args.current and args.baseline):
            parser.error("--current 与 --baseline 需成对提供")
        return check_pair(args.current, args.baseline)

    scenarios = SCENARIOS if args.all else (args.scenario,) if args.scenario else ()
    if not scenarios:
        print(USAGE)
        return 2

    rc = 0
    for sc in scenarios:
        base_path, cur_path = latest_pair(sc)
        if not cur_path:
            print(f"[INFO] {sc}: 未找到基线文件（{BASELINE_DIR}\\{sc}-*.json），先运行 run_perf_baseline")
            continue
        if not base_path:
            print(f"[INFO] {sc}: 仅一份基线 {os.path.basename(cur_path)}，无历史可对比")
            continue
        rc = max(rc, check_pair(cur_path, base_path))
    return rc


if __name__ == "__main__":
    sys.exit(main())
