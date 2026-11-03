# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""优化12 §6.1 / §14 T9（机制硬化）：tc260.yaml 形状 lint（只读，CI/pre-commit）。

§6.1 核定服务是"块定位 + 行级改写 min_questions / pass_threshold"，流式写法
（`- {sub_code: …}`）没有这两行可改写，核定必然失效；§5.1 同时禁止锚点/合并键
（`<<:`，核定行改写会破坏其语义）。本脚本把这些结构前提变成机器断言：

  1. `mapping:` 段内任一流式条目 `- {` → FAIL；
  2. 每个 `- sub_code:` / `- category_code:` 条目块缺 `min_questions:` 或
     `pass_threshold:` 行 → FAIL；
  3. 合并键 `<<:` 或列表项锚点 `- &` → FAIL。

纯行级正则（不依赖 YAML 解析器语义，流式条目 safe_load 后无法还原行形态）；
不写文件。退出码：0 = 形状合规；1 = FAIL；2 = 文件缺失/读取错误。
用法（backend 目录或仓库根）：python scripts/lint_std_yaml_shape.py [yaml路径]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_YAML = _BACKEND.parent / "deploy" / "standards" / "tc260.yaml"

_MAPPING_RE = re.compile(r"^mapping:[ \t]*(?:#.*)?$")
_TOP_KEY_RE = re.compile(r"^\S")
_FLOW_ITEM_RE = re.compile(r"^[ \t]*-[ \t]+\{")
_ENTRY_RE = re.compile(
    r"^(?P<indent>[ \t]*)-[ \t]+(?:sub_code|category_code):[ \t]*(?P<code>\S+)"
)
_DIM_ENTRY_RE = re.compile(r"^[ \t]*-[ \t]+dimension_code:")
_MIN_Q_RE = re.compile(r"^[ \t]+min_questions[ \t]*:")
_PASS_T_RE = re.compile(r"^[ \t]+pass_threshold[ \t]*:")
_MERGE_RE = re.compile(r"^[ \t]*(?:-[ \t]+)?<<[ \t]*:")
_ANCHOR_ITEM_RE = re.compile(r"^[ \t]*-[ \t]+&\S")


def check_text(text: str) -> tuple[list[str], int]:
    """返回 (errors, 条目数)。errors 元素含行号，纯函数零 IO。"""
    lines = text.splitlines()
    errors: list[str] = []

    start = next((i for i, ln in enumerate(lines) if _MAPPING_RE.match(ln)), None)
    if start is None:
        return (["mapping: 段不存在（两级结构 §5.1 未落位？）"], 0)
    end = next((i for i in range(start + 1, len(lines)) if _TOP_KEY_RE.match(lines[i])),
               len(lines))

    entries = 0
    cur: dict | None = None  # {code, indent, line, has_mq, has_pt}

    def close(block: dict | None) -> None:
        if block is None:
            return
        if not block["has_mq"]:
            errors.append(
                f"L{block['line'] + 1} {block['code']}: 缺 min_questions: 行"
                "（核定服务行级改写前提，§6.1）")
        if not block["has_pt"]:
            errors.append(
                f"L{block['line'] + 1} {block['code']}: 缺 pass_threshold: 行"
                "（核定服务行级改写前提，§6.1）")

    for i in range(start + 1, end):
        ln = lines[i]
        if _FLOW_ITEM_RE.match(ln):
            errors.append(f"L{i + 1}: 流式条目 `- {{…}}`（§5.1 要求一律块式，核定无法行级改写）")
            continue
        if _MERGE_RE.match(ln):
            errors.append(f"L{i + 1}: 合并键 `<<:`（§5.1 禁止，核定行改写会破坏其语义）")
            continue
        if _ANCHOR_ITEM_RE.match(ln):
            errors.append(f"L{i + 1}: 列表项锚点 `- &`（§5.1 禁止锚点复用，须逐行展开）")
            continue
        m = _ENTRY_RE.match(ln)
        if m:
            indent = len(m.group("indent"))
            if cur is not None and indent <= cur["indent"]:
                close(cur)
                cur = None
            cur = {"code": m.group("code"), "indent": indent, "line": i,
                   "has_mq": False, "has_pt": False}
            entries += 1
            continue
        if _DIM_ENTRY_RE.match(ln) and cur is not None:
            close(cur)
            cur = None
            continue
        if cur is not None:
            if _MIN_Q_RE.match(ln):
                cur["has_mq"] = True
            if _PASS_T_RE.match(ln):
                cur["has_pt"] = True
    close(cur)
    return errors, entries


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="tc260.yaml 块式形状 lint（§6.1/T9）")
    ap.add_argument("yaml_path", nargs="?", default=str(DEFAULT_YAML),
                    help="待检 yaml（缺省 deploy/standards/tc260.yaml）")
    args = ap.parse_args(argv)

    path = Path(args.yaml_path)
    if not path.exists():
        print(f"[错误] yaml 不存在：{path}", file=sys.stderr)
        return 2
    try:
        errors, entries = check_text(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"[错误] 读取失败：{exc}", file=sys.stderr)
        return 2

    if errors:
        print(f"[FAIL] {path.name} 形状检查 {len(errors)} 项违规：", file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        return 1
    print(f"[通过] {path.name}：mapping 条目 {entries} 个全部块式且含 "
          f"min_questions / pass_threshold 两键（无流式/锚点/合并键）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
