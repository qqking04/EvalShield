#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ES9-P-16：前端产物体积守门脚本（CI 断言用）。

规则：入口 chunk（frontend/dist/static/index-*.js）gzip 后必须 < 300 kB，
超标 exit 1。vendor 四组（vendor-react / vendor-router / vendor-antd /
vendor-echarts）为独立 chunk，不计入入口断言，但会一并打印供人工核对。

用法：
    python scripts/check_bundle_size.py            # 默认阈值 300 kB
    python scripts/check_bundle_size.py --limit-kb 300

前置：先在 frontend/ 下执行 npm run build 生成 dist/。
"""
import argparse
import gzip
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST_STATIC = REPO / "frontend" / "dist" / "static"


def gz_size(path: Path) -> int:
    """文件 gzip(level 9) 后的字节数。"""
    raw = path.read_bytes()
    return len(gzip.compress(raw, compresslevel=9))


def main() -> int:
    parser = argparse.ArgumentParser(description="入口 chunk gzip 体积断言")
    parser.add_argument("--limit-kb", type=float, default=300.0,
                        help="入口 chunk gzip 上限（kB），默认 300")
    parser.add_argument("--dist", type=Path, default=DIST_STATIC,
                        help="dist/static 目录路径")
    args = parser.parse_args()

    if not args.dist.is_dir():
        print(f"[FAIL] 产物目录不存在: {args.dist}（请先 npm run build）")
        return 1

    js_files = sorted(args.dist.glob("*.js"))
    if not js_files:
        print(f"[FAIL] {args.dist} 下没有 js 产物")
        return 1

    entries = [p for p in js_files if p.name.startswith("index-")]
    if not entries:
        print(f"[FAIL] 未找到入口 chunk（index-*.js）")
        return 1

    print(f"{'chunk':44s} {'raw(kB)':>10s} {'gzip(kB)':>10s}")
    print("-" * 68)
    total_gz = 0
    for p in js_files:
        raw = p.stat().st_size
        gz = gz_size(p)
        total_gz += gz
        print(f"{p.name:44s} {raw / 1024:10.1f} {gz / 1024:10.1f}")
    print("-" * 68)
    print(f"{'TOTAL (all js chunks)':44s} {'':10s} {total_gz / 1024:10.1f}")

    failed = False
    limit_bytes = args.limit_kb * 1024
    for p in entries:
        gz = gz_size(p)
        if gz >= limit_bytes:
            print(f"[FAIL] 入口 chunk {p.name} gzip={gz / 1024:.1f}kB >= {args.limit_kb:.0f}kB")
            failed = True
        else:
            print(f"[PASS] 入口 chunk {p.name} gzip={gz / 1024:.1f}kB < {args.limit_kb:.0f}kB")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
