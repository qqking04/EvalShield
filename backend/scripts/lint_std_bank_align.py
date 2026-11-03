# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""优化12 §7.3（T4）：CI lint —— tc260.yaml bank_category 与字典软对齐。

断言（v2.2 修正口径，§7.1 F19：字典基准 = 新增独立字典 bank_category_gbt45654，
**不引用 eval_category**）：
  1. yaml 全部子类 bank_category 全集 ⊆ 字典 item_value 全集 ∪ {待分类-GBT45654}；
  2. 字典 ext.sub_code（非空）↔ framework_items(GBT45654-2025).code 一一对应，
     且 framework.name == yaml bank_category（软对齐逐字一致）；
  3. 字典 item_value（除暂存态）== framework.name（一一对应）。

数据来源：直接解析 ``database/inti.sql`` section 78（与 §11.3 校验器共用解析函数，
单一实现，不连库、不重复写 SQL 文本）。

退出码：0 = 对齐；1 = 不一致（CI 阻断）。
用法（backend 目录）：python scripts/lint_std_bank_align.py [--yaml <路径>]
  --yaml：指定被检 yaml（fixture 正反例自测用，优化12 BUG-003）；缺省 = 生产候选序列。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import yaml  # noqa: E402

from scripts.sync_inti_sql import (  # noqa: E402
    parse_bank_dict_items_split,
    parse_framework_gbt45654_split,
)

STAGING = "待分类-GBT45654"
YAML_CANDIDATES = [
    _BACKEND.parent / "deploy" / "standards" / "tc260.yaml",
]


def yaml_bank_categories(candidates: list[Path] | None = None) -> list[tuple[str, str]]:
    """[(sub_code, bank_category)] —— 两级 mapping[].subs[]。"""
    path = next((p for p in (candidates or YAML_CANDIDATES) if p.exists()), None)
    if path is None:
        raise SystemExit("[错误] tc260.yaml 不存在：" + str(candidates or YAML_CANDIDATES))
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[tuple[str, str]] = []
    for dim in raw.get("mapping") or []:
        for sub in dim.get("subs") or []:
            sc, bc = str(sub.get("sub_code") or ""), str(sub.get("bank_category") or "")
            if sc and bc:
                out.append((sc, bc))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lint_std_bank_align",
        description="优化12 §7.3：tc260.yaml bank_category 与字典软对齐 lint")
    parser.add_argument("--yaml", dest="yaml_path", default=None,
                        help="指定被检 yaml 路径（fixture 自测）；缺省 = 生产候选序列")
    # argv 缺省为空列表：直接调用（如 pytest 内 lint_main()）不吞宿主进程 sys.argv。
    args, unknown = parser.parse_known_args(argv if argv is not None else [])
    if unknown:
        # 静默忽略未知参数曾造成 fixture 反例假绿（BUG-003），显式报错。
        print(f"[错误] 未知参数：{unknown}（fixture 检查请用 --yaml <路径>）", file=sys.stderr)
        return 2
    candidates = [Path(args.yaml_path)] if args.yaml_path else YAML_CANDIDATES

    dict_items = parse_bank_dict_items_split()        # {item_value: sub_code}（inti+data）
    fw_items = parse_framework_gbt45654_split()       # {code: name}（inti+data）
    if not dict_items:
        print("[错误] inti.sql/data.sql 未解析到 bank_category_gbt45654 字典项（section 78 缺失？）",
              file=sys.stderr)
        return 1
    if not fw_items:
        print("[错误] inti.sql/data.sql 未解析到 framework_items(GBT45654-2025) 种子行",
              file=sys.stderr)
        return 1

    errors: list[str] = []

    # 1) yaml bank_category ⊆ 字典 ∪ 暂存态
    dict_values = set(dict_items)
    for sc, bc in yaml_bank_categories(candidates):
        if bc not in dict_values:
            errors.append(f"yaml {sc}: bank_category「{bc}」不在字典 bank_category_gbt45654 中")

    # 2) 字典 ext.sub_code ↔ framework_items.code 一一对应 + 名称逐字一致
    dict_subcodes = {v: k for k, v in dict_items.items() if v}  # sub_code -> item_value
    if set(dict_subcodes) != set(fw_items):
        only_dict = set(dict_subcodes) - set(fw_items)
        only_fw = set(fw_items) - set(dict_subcodes)
        if only_dict:
            errors.append(f"字典 ext.sub_code 多出于 framework_items：{sorted(only_dict)}")
        if only_fw:
            errors.append(f"framework_items 多出于字典：{sorted(only_fw)}")
    # 3) 逐 sub_code：framework.name == 字典 item_value == yaml bank_category
    yaml_map = dict(yaml_bank_categories(candidates))
    for sc, value in sorted(dict_subcodes.items()):
        if fw_items.get(sc) != value:
            errors.append(f"{sc}: framework_items.name「{fw_items.get(sc)}」≠ 字典 item_value「{value}」")
        if sc in yaml_map and yaml_map[sc] != value:
            errors.append(f"{sc}: yaml bank_category「{yaml_map[sc]}」≠ 字典 item_value「{value}」")

    if errors:
        print(f"[FAIL] bank_category 对齐检查 {len(errors)} 项不一致：", file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        return 1
    print(f"[通过] yaml 子类 {len(yaml_map)} ⊆ 字典 {len(dict_values)} 项"
          f"（framework_items {len(fw_items)} 条，软对齐逐字一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
