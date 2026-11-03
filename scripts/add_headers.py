#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EvalShield 版权头批量加注工具（版本隔离改造 B10，方案 §2-B10 / 上位方案 §6.4）。

幂等：文件前 30 行内已同时命中 ``EvalShield`` 与 ``Copyright`` 即跳过。
作用域（默认，相对仓库根）：
  - backend/app/**.py            （排除 app/commercial/**）
  - frontend/src/**.{js,jsx,css} （排除 src/pages/commercial/**）
  - database/inti.sql            （首行块）

变体：
  --variant oss          开源面：BUSL-1.1 头（默认）
  --variant commercial   私有树：Proprietary 头（对 app/commercial/** 批量执行）

用法：
  python scripts/add_headers.py [--dry-run] [--variant oss|commercial]
  python scripts/add_headers.py --root backend/app --exclude app/commercial

只做纯文本前缀插入，不改代码语义；.py 的 shebang / coding 声明行保留在头部之前。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

HEADER_WINDOW = 30  # 幂等检测窗口：前 30 行
_RE_EVALSHIELD = re.compile(r"EvalShield")
_RE_COPYRIGHT = re.compile(r"Copyright")
# .py 允许保留在版权头之前的前置行：shebang / 编码声明 / 空行
_RE_PY_KEEP = re.compile(r"^(#!.*|#.*coding[:=].*|#!\s*$|\s*)$")

COPYRIGHT_HOLDER = "武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.)"

VARIANTS = {
    "oss": {
        "lines": [
            "EvalShield",
            f"Copyright (c) 2025 {COPYRIGHT_HOLDER}. All rights reserved.",
            'Use of this source code is governed by the Business Source License 1.1',
            '(the "License") stated in the LICENSE file at the root of this',
            "distribution. Change Date: 3 years after release.",
            "Change License: Apache License, Version 2.0.",
            "SPDX-License-Identifier: BUSL-1.1",
        ],
        "marker": "BUSL-1.1",
    },
    "commercial": {
        "lines": [
            "EvalShield commercial module — Proprietary. All rights reserved.",
            f"Copyright (c) 2025 {COPYRIGHT_HOLDER}.",
            "Access to or use of this source code is governed by a commercial",
            "license agreement; no one else may copy, modify or distribute it.",
            "SPDX-License-Identifier: LicenseRef-EvalShield-Commercial",
        ],
        "marker": "LicenseRef-EvalShield-Commercial",
    },
}

STYLE_BY_EXT = {".py": "hash", ".js": "block", ".jsx": "block", ".css": "block", ".sql": "dash"}

DEFAULT_ROOTS_OSS = ["backend/app", "frontend/src", "database/inti.sql"]
DEFAULT_EXCLUDES_OSS = ["app/commercial", "pages/commercial"]


def _render_header(style: str, lines: list[str]) -> str:
    if style == "hash":
        return "".join(f"# {ln}\n" for ln in lines)
    if style == "dash":
        return "".join(f"-- {ln}\n" for ln in lines)
    body = "\n".join(f" * {ln}" for ln in lines)
    return f"/*\n{body}\n */\n"


def _has_header(path: Path) -> bool:
    """前 30 行内 EvalShield 与 Copyright 同现 → 认为已加注（幂等依据）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = "".join(f.readline() for _ in range(HEADER_WINDOW))
    except OSError:
        return False
    return bool(_RE_EVALSHIELD.search(head) and _RE_COPYRIGHT.search(head))


def _py_head_len(lines: list[str]) -> int:
    """.py：shebang / coding 声明 / 前置空行保留在版权头之前（容忍 UTF-8 BOM）。"""
    n = 0
    for ln in lines:
        if _RE_PY_KEEP.match(ln.lstrip("\ufeff").rstrip("\r\n")):
            n += 1
        else:
            break
    return n


def _add_to_file(path: Path, variant: dict, dry: bool) -> bool:
    """向单文件注入版权头；返回是否（将）修改。"""
    ext = path.suffix.lower()
    style = STYLE_BY_EXT.get(ext)
    if style is None or _has_header(path):
        return False
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    head_len = _py_head_len(lines) if ext == ".py" else 0
    header = _render_header(style, variant["lines"])
    new = "".join(lines[:head_len]) + header + "".join(lines[head_len:])
    if not dry:
        path.write_text(new, encoding="utf-8", newline="")
    return True


def _iter_targets(roots: list[str], excludes: list[str]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        p = (REPO_ROOT / root).resolve()
        if not p.exists():
            print(f"[warn] 路径不存在，跳过：{root}", file=sys.stderr)
            continue
        files = [p] if p.is_file() else sorted(
            f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in STYLE_BY_EXT
        )
        for f in files:
            try:
                rel = f.relative_to(REPO_ROOT).as_posix()
            except ValueError:  # 扫描根在仓库外时按绝对路径显示
                rel = f.as_posix()
            if any(x in rel for x in excludes):
                continue
            out.append(f)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="EvalShield 版权头批量加注（幂等）")
    ap.add_argument("--root", action="append", default=None,
                    help="扫描根（相对仓库根，可多次；默认按 --variant 选择）")
    ap.add_argument("--exclude", action="append", default=None,
                    help="排除子串（相对路径包含即排除，可多次）")
    ap.add_argument("--variant", choices=sorted(VARIANTS), default="oss")
    ap.add_argument("--dry-run", action="store_true", help="只列出将修改的文件")
    args = ap.parse_args(argv)

    variant = VARIANTS[args.variant]
    roots = args.root or (
        DEFAULT_ROOTS_OSS if args.variant == "oss" else ["backend/app/commercial"]
    )
    excludes = args.exclude or (DEFAULT_EXCLUDES_OSS if args.variant == "oss" else [])

    targets = _iter_targets(roots, excludes)
    changed, skipped = [], 0
    for f in targets:
        if _has_header(f):
            skipped += 1
            continue
        if _add_to_file(f, variant, args.dry_run):
            try:
                changed.append(f.relative_to(REPO_ROOT).as_posix())
            except ValueError:
                changed.append(f.as_posix())

    action = "将加注" if args.dry_run else "已加注"
    for c in changed:
        print(f"[{action}] {c}")
    print(f"共扫描 {len(targets)}，{action} {len(changed)}，已有头跳过 {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
