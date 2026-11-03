# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""优化12 §7.2（T4）：题库 question.category 旧值 → GBT45654 子类字典值迁移。

用法（backend 目录）：
    python scripts/migrate_bank_category_gbt45654.py [--bank-id N] [--apply] [--csv PATH]

- 默认 **dry-run**：只输出 bank_id × 旧类别 × 题数 × 拟迁子类 报表（stdout + csv），**零落库**；
- ``--apply``：UPDATE question SET category=? WHERE bank_id=? AND category=?（单事务，逐 bank 提交）；
- 字典基准 = inti.sql section 78 的 ``bank_category_gbt45654`` 字典项
  （与 ``database/inti.sql`` 同源；解析复用 sync_inti_sql 单一实现，不连库也可跑）；
- **绝不猜语义**（§7.2）：
  * 已是新字典值 → 不动（含 幻觉/提示注入/信息泄露——与新字典逐字一致）；
  * 已知旧类中文值 → 固定映射表 LEGACY_MAP（违法违规→违法违规-其他(A1h)、
    危害安全→违法违规-其他(A1h)、歧视→歧视-其他(A2i)，方案原文口径）；
  * 其余（未知/自定义值）→ 一律 ``待分类-GBT45654`` 暂存态兜底（不计入覆盖统计，
    缺口清单单列，由交付团队依报表逐题改类）；
- 幂等可重跑：第二次 apply 全部命中"已是新字典值"分支 → 0 changed；
- **铁律 7：绝不触碰 eval_run_items**（历史血缘冻结）——本脚本语句只涉及 question 表；
- 防查重唯一索引 uq_question_dedup(bank_id, category, md5(btrim(text))) 冲突：
  同库同文本跨旧类合并会撞唯一键，此类行 dry-run 报表标记 ``dedup_conflict``，
  --apply 时**跳过不落库**（保留旧类，待人工处置），不算迁移成功。

报表须经按子类抽样人工复核后方可 --apply（§7.2，人工动作，脚本不代办）。
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Callable

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import logging

from sqlalchemy import text as sa_text

from scripts.sync_inti_sql import parse_bank_dict_items_split

logger = logging.getLogger("migrate_bank_category_gbt45654")

# 暂存态兜底值（= section 78 字典第 34 项 item_value）
STAGING_CATEGORY = "待分类-GBT45654"

# 固定映射表（§7.2 原文口径；目标值 = 新字典 item_value，逐字一致）：
#   违法违规→A1h、危害安全→A1h、歧视→A2i。
#   信息泄露→A4g（或保留 Xq2）：新字典含「信息泄露」=Xq2，按"已是新字典值→不动"
#   分支保留原值（零猜测优先），A4g 归并属语义判断，留给交付团队逐题处理。
LEGACY_MAP: dict[str, str] = {
    "违法违规": "违法违规-其他",
    "危害安全": "违法违规-其他",
    "歧视": "歧视-其他",
}


def classify(category: str, dict_values: set[str]) -> tuple[str | None, str]:
    """旧类别 → (目标类别 | None=不动, 规则标记)。"""
    cat = (category or "").strip()
    if not cat:
        return STAGING_CATEGORY, "empty->staging"
    if cat in dict_values:
        return None, "already-new"
    if cat in LEGACY_MAP:
        target = LEGACY_MAP[cat]
        return (target, "legacy-map") if target in dict_values else (STAGING_CATEGORY, "legacy-target-missing->staging")
    return STAGING_CATEGORY, "unknown->staging"


def build_plan(session, dict_values: set[str], bank_id: int | None = None) -> list[dict[str, Any]]:
    """按 (bank_id, category) 分组统计并生成拟迁计划（只读，不落库）。"""
    sql = (
        "SELECT bank_id, category, COUNT(*) AS n FROM question "
        "WHERE deleted_at IS NULL"
    )
    params: dict[str, Any] = {}
    if bank_id is not None:
        sql += " AND bank_id = :bank_id"
        params["bank_id"] = bank_id
    sql += " GROUP BY bank_id, category ORDER BY bank_id, category"
    rows = session.execute(sa_text(sql), params).fetchall()

    plan: list[dict[str, Any]] = []
    for bid, cat, n in rows:
        target, rule = classify(str(cat), dict_values)
        plan.append({"bank_id": int(bid), "category": str(cat), "count": int(n),
                     "target": target or "", "rule": rule})
    _mark_dedup_conflicts(session, plan, bank_id)
    return plan


def _mark_dedup_conflicts(session, plan: list[dict[str, Any]], bank_id: int | None) -> None:
    """同库内：迁移目标相同的多个旧类若含相同 btrim(text) → uq_question_dedup 撞键风险。"""
    moves = [p for p in plan if p["target"] and p["target"] != p["category"]]
    grouped: dict[tuple[int, str], list[str]] = {}
    for p in moves:
        grouped.setdefault((p["bank_id"], p["target"]), []).append(p["category"])
    for (bid, target), cats in grouped.items():
        if len(cats) < 2:
            continue
        found = session.execute(sa_text(
            "SELECT DISTINCT category FROM question"
            " WHERE deleted_at IS NULL AND bank_id = :b AND category = ANY(:cats)"
            "   AND md5(btrim(text)) IN ("
            "     SELECT md5(btrim(text)) FROM question"
            "     WHERE deleted_at IS NULL AND bank_id = :b2 AND category = ANY(:cats2)"
            "     GROUP BY md5(btrim(text)) HAVING COUNT(DISTINCT category) > 1)"
        ), {"b": bid, "cats": cats, "b2": bid, "cats2": cats}).fetchall()
        if found:
            # 撞键组的旧类全部标记跳过（保留原类，人工处置）
            risky = {str(r[0]) for r in found}
            for p in moves:
                if p["bank_id"] == bid and p["category"] in risky:
                    p["rule"] = "dedup_conflict-skip"
                    p["target_conflict"] = True


def render_report(plan: list[dict[str, Any]]) -> str:
    lines = ["bank_id\tcategory\tcount\ttarget\trule"]
    for p in plan:
        lines.append(f"{p['bank_id']}\t{p['category']}\t{p['count']}\t"
                     f"{p['target'] or '(不动)'}\t{p['rule']}")
    staging = sum(p["count"] for p in plan if p["target"] == STAGING_CATEGORY)
    changed = sum(p["count"] for p in plan
                  if p["target"] and p["target"] != p["category"] and not p.get("target_conflict"))
    lines.append(f"-- 拟迁移 {changed} 题；暂存态兜底 {staging} 题（缺口清单单列，逐题人工改类）")
    return "\n".join(lines)


def write_csv(plan: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["bank_id", "category", "count", "target", "rule"])
        w.writeheader()
        for p in plan:
            w.writerow({k: p.get(k, "") for k in w.fieldnames})


def apply_plan(session, plan: list[dict[str, Any]],
               commit: Callable[[], None] | None = None) -> int:
    """执行 UPDATE（逐 bank 单事务）。返回迁移题数。铁律 7：只写 question 表。"""
    total = 0
    by_bank: dict[int, list[dict[str, Any]]] = {}
    for p in plan:
        if not p["target"] or p["target"] == p["category"] or p.get("target_conflict"):
            continue
        by_bank.setdefault(p["bank_id"], []).append(p)
    for bid, moves in sorted(by_bank.items()):
        try:
            for p in moves:
                res = session.execute(sa_text(
                    "UPDATE question SET category = :new, updated_at = now() "
                    "WHERE bank_id = :b AND category = :old AND deleted_at IS NULL"
                ), {"new": p["target"], "b": bid, "old": p["category"]})
                total += int(res.rowcount or 0)
            if commit is not None:
                commit()
            else:
                session.commit()
        except Exception:  # noqa: BLE001 —— 单 bank 失败回滚，不影响已提交 bank
            session.rollback()
            logger.exception("bank %s 迁移失败，已回滚该库", bid)
            raise
    return total


def load_dict_values() -> set[str]:
    """字典基准：inti.sql section 78 种子（优化13 拆分后原样迁移至 data.sql，
    两文件合并解析；单一事实源，与运行库种子同源）。"""
    return set(parse_bank_dict_items_split()) - {STAGING_CATEGORY}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="题库类别 → GBT45654 子类字典迁移（默认 dry-run）")
    ap.add_argument("--bank-id", type=int, default=None, help="仅迁移指定题库")
    ap.add_argument("--apply", action="store_true", help="真正落库（默认 dry-run 零落库）")
    ap.add_argument("--csv", type=Path, default=None, help="报表 CSV 输出路径")
    args = ap.parse_args(argv)

    from app.database import SessionLocal

    dict_values = load_dict_values()
    session = SessionLocal()
    try:
        plan = build_plan(session, dict_values, args.bank_id)
        print(render_report(plan))
        if args.csv:
            write_csv(plan, args.csv)
            print(f"[csv] 报表已写出：{args.csv}")
        if not args.apply:
            print("[dry-run] 未落库；复核报表后用 --apply 执行（§7.2：须按子类抽样人工复核）")
            return 0
        changed = apply_plan(session, plan)
        print(f"[apply] 迁移 {changed} 题（幂等：重跑应为 0）")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
