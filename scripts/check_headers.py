#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EvalShield 版权头覆盖率检查（版本隔离改造 B10 配套，测试方案 H1/T10）。

扫描开源面文件（作用域与 add_headers.py 一致），统计缺少版权头的文件；
缺失率非 0（即覆盖率不足 100%）→ 退出码 1。

用法（与测试方案 H1 命令兼容）：
  python scripts/check_headers.py --root backend/app --root frontend/src \
      --exclude app/commercial --exclude src/pages/commercial
  python scripts/check_headers.py --sql database/inti.sql

说明：--root 指定的 .py/.js/.jsx/.css 文件递归扫描；--sql 显式指定 SQL 文件。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

HEADER_WINDOW = 30
_RE_EVALSHIELD = re.compile(r"EvalShield")
_RE_COPYRIGHT = re.compile(r"Copyright")
SCAN_EXTS = {".py", ".js", ".jsx", ".css", ".sql"}


def _has_header(path: Path) -> bool:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = "".join(f.readline() for _ in range(HEADER_WINDOW))
    except OSError:
        return False
    return bool(_RE_EVALSHIELD.search(head) and _RE_COPYRIGHT.search(head))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="EvalShield 版权头覆盖率检查")
    ap.add_argument("--root", action="append", default=[],
                    help="扫描根（相对仓库根，可多次）")
    ap.add_argument("--exclude", action="append", default=[],
                    help="排除子串（相对路径包含即排除，可多次）")
    ap.add_argument("--sql", action="append", default=[],
                    help="显式 SQL 文件（相对仓库根，可多次）")
    args = ap.parse_args(argv)

    files: list[Path] = []
    for root in args.root:
        p = (REPO_ROOT / root).resolve()
        if not p.exists():
            print(f"[error] 路径不存在：{root}", file=sys.stderr)
            return 2
        if p.is_file():
            files.append(p)
        else:
            files.extend(f for f in p.rglob("*")
                         if f.is_file() and f.suffix.lower() in SCAN_EXTS)
    for s in args.sql:
        p = (REPO_ROOT / s).resolve()
        if p.exists():
            files.append(p)

    targets = []
    seen: set[Path] = set()
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        try:
            rel = f.relative_to(REPO_ROOT).as_posix()
        except ValueError:  # 扫描根在仓库外时按绝对路径显示
            rel = f.as_posix()
        if any(x in rel for x in args.exclude):
            continue
        targets.append((rel, f))

    missing = [rel for rel, f in targets if not _has_header(f)]
    total, miss = len(targets), len(missing)
    for m in missing:
        print(f"[缺失] {m}")
    if total == 0:
        print("未扫描到任何文件", file=sys.stderr)
        return 1
    rate = (total - miss) / total * 100
    print(f"版权头覆盖：{total - miss}/{total}（{rate:.1f}%）")
    if miss:
        print(f"缺失 {miss} 个文件 → 退出码 1")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
