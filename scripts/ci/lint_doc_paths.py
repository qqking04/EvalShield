#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CI 文档路径 lint（优化12 §11.4-2 / T9）：md 中引用的仓库路径做存在性校验。

背景：v1.0 方案曾把 CLI 写成 `scripts/set_tc260_thresholds.py`（实际在
backend/scripts/ 下）、`sync_inti_sql.py` 落点同类错误——文档路径漂移即此类问题。

口径：
  - 默认扫描本轮事实源 `优化12详细开发.md` 及已清理历史误引的相关文档
    （`优化12.md`、`优化12测试用例.md`、docs/release/checklist.md、
    docs/security/multi-tenancy.md、docs/AI自测化/差异系列——2026-10 收口时
    已逐处修复或列为 EXEMPT 教训引用）；未清理的历史版本文档不回填；
  - 只判带目录前缀的反引号路径（`backend/...` `frontend/...` `database/...`
    `deploy/...` `docs/...` `config/...`），避免把 `tests/xx.py` 之类裸文件名误判；
  - 路径后允许 `L32` 等行号尾注（正则截断到文件名止）；
  - 命中不存在路径 → 逐条打印 文件:行号 + 路径，退出码 1。

EXEMPT：文档中以反引号原样引用"历史错误路径"作教训说明的条目（键 = (文件, 路径)）。

退出码：0 = 全部存在；1 = 存在失效引用；2 = 环境错误（目标文件缺失）。
用法（仓库根）：python scripts/ci/lint_doc_paths.py [md路径 ...]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_TARGETS = [
    ROOT / "doc" / "优化12详细开发.md",
    ROOT / "doc" / "优化12.md",
    ROOT / "doc" / "优化12测试用例.md",
    ROOT / "docs" / "release" / "checklist.md",
    ROOT / "docs" / "security" / "multi-tenancy.md",
    ROOT / "docs" / "AI自测差异详细设计.md",
    ROOT / "docs" / "AI自测化测试详细设计.md",
    ROOT / "docs" / "AI自测化测试BUG.md",
    ROOT / "docs" / "AI自测化测试详细报告.md",
]

PATH_RE = re.compile(
    r"`((?:backend|frontend|database|deploy|docs|config|scripts)/[A-Za-z0-9_./\-]+?)`")

# 明确的历史错误引用（教训原文，不得视为漂移）：
EXEMPT: set[tuple[str, str]] = {
    ("优化12详细开发.md", "scripts/set_tc260_thresholds.py"),  # §11.4-2 引 v1.0 错误例
    ("优化12.md", "scripts/set_tc260_thresholds.py"),  # M6/勘误表引 v1.0 错误例
    ("优化12测试用例.md", "scripts/set_tc260_thresholds.py"),  # TC-M6-006 负样本写法
}


def check_file(path: Path) -> list[str]:
    """返回错误清单（纯文本行），空 = 通过。"""
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    for m in PATH_RE.finditer(text):
        ref = m.group(1)
        if (path.name, ref) in EXEMPT:
            continue
        if not (ROOT / ref).exists():
            line = text[:m.start()].count("\n") + 1
            errors.append(f"{path.name}:{line} 引用路径不存在：`{ref}`")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="md 引用仓库路径存在性 lint")
    ap.add_argument("targets", nargs="*", default=None, help="md 文件（缺省=本轮事实源）")
    args = ap.parse_args(argv)

    targets = [Path(t) for t in (args.targets or DEFAULT_TARGETS)]
    errors: list[str] = []
    scanned = 0
    for t in targets:
        p = t if t.is_absolute() else ROOT / t
        if not p.exists():
            print(f"[错误] 目标 md 缺失：{p}", file=sys.stderr)
            return 2
        hits = len(PATH_RE.findall(p.read_text(encoding="utf-8")))
        scanned += hits
        errors += check_file(p)

    if errors:
        print(f"[FAIL] 文档路径 lint：{len(errors)} 处失效引用：", file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        return 1
    print(f"[通过] 文档路径 lint：{len(targets)} 个文件、{scanned} 处带前缀路径引用全部存在"
          f"（EXEMPT 教训引用 {len(EXEMPT)} 条不计）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
