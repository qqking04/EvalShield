#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES9-P-15 日配额口径重算（rezone）工具（优化9 §6 P-15）。

背景：DB 会话时区统一切为 UTC 后，``community_usage_daily.usage_date``
（列注释：服务器本地日）的新写入按 UTC 日归属，而存量行按旧服务器时区
（北京 +08:00）写入，每日 00:00–08:00（北京时间）窗口的用量归属日存在
口径差。本工具将各行按其 ``updated_at``（UTC 时刻）换算北京时间重算
"应归属日"（new_date），与存量 ``usage_date``（old_date）做新旧口径对照。

口径假设（见 docs/architecture/time-handling.md §4，工具注释同步）：
- 行级时间戳仅有 created_at/updated_at，无法拆分单日内多次增量；
  以 updated_at（最近一次计数时刻）的北京日作为整行重算归属日，
  属近似口径——适用于切换窗口附近的纠偏，不适用于历史长尾精算。
- 唯一约束 (tenant_id, user_id, kind, usage_date)：--apply 时多行
  并入同一 new_date 需先 SUM(cnt) 再 upsert，并删除源行。

用法：
  python scripts/rezone_recalc.py                # dry-run：打印对照表，不写库
  python scripts/rezone_recalc.py --apply        # 按对照结果合并重写（幂等）

退出码：0 成功；非 0 失败。
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# 复用后端配置与模型（backend/ 目录直接可 import，不依赖安装包）
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(_BACKEND))

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import engine  # noqa: E402
from app.models import CommunityUsageDaily  # noqa: E402

_UTC8 = timezone(timedelta(hours=8))


def beijing_date(ts: datetime | None, fallback: date | None) -> date:
    """UTC timestamp → 北京日历日；无时间戳时回退存量 usage_date。"""
    if ts is None:
        return fallback if fallback is not None else date.min
    if ts.tzinfo is None:  # 防御：视为 UTC naive
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_UTC8).date()


def collect_recalc(db: Session) -> list[dict]:
    """返回新旧口径对照行：{tenant_id,user_id,kind,old_date,new_date,cnt,affected}。"""
    rows = db.execute(
        select(
            CommunityUsageDaily.id,
            CommunityUsageDaily.tenant_id,
            CommunityUsageDaily.user_id,
            CommunityUsageDaily.kind,
            CommunityUsageDaily.usage_date,
            CommunityUsageDaily.cnt,
            CommunityUsageDaily.updated_at,
        ).order_by(
            CommunityUsageDaily.tenant_id,
            CommunityUsageDaily.user_id,
            CommunityUsageDaily.kind,
            CommunityUsageDaily.usage_date,
        )
    ).all()
    out = []
    for r in rows:
        new_date = beijing_date(r.updated_at, r.usage_date)
        out.append(
            {
                "id": r.id,
                "tenant_id": r.tenant_id,
                "user_id": r.user_id,
                "kind": r.kind,
                "old_date": r.usage_date,
                "new_date": new_date,
                "cnt": r.cnt,
                "affected": new_date != r.usage_date,
            }
        )
    return out


def print_table(rows: list[dict]) -> None:
    header = f"{'id':>6}  {'tenant':>6}  {'user':>5}  {'kind':<16}  {'old_date':<10}  {'new_date':<10}  {'cnt':>6}  affected"
    print(header)
    print("-" * len(header))
    for r in rows:
        mark = "  ← 需重算" if r["affected"] else ""
        print(
            f"{r['id']:>6}  {r['tenant_id']:>6}  {r['user_id']:>5}  {r['kind']:<16}  "
            f"{r['old_date'].isoformat():<10}  {r['new_date'].isoformat():<10}  {r['cnt']:>6}{mark}"
        )
    total = len(rows)
    affected = sum(1 for r in rows if r["affected"])
    moved_cnt = sum(r["cnt"] for r in rows if r["affected"])
    print(
        f"\n汇总：共 {total} 行，其中 {affected} 行新旧口径归属日不同"
        f"（涉及用量 {moved_cnt}）；未变更 {total - affected} 行。"
    )


def apply_recalc(db: Session, rows: list[dict]) -> int:
    """按 new_date 聚合合并重写受影响行（幂等：仅处理 old!=new 的行）。"""
    affected = [r for r in rows if r["affected"]]
    if not affected:
        print("无受影响行，跳过 apply。")
        return 0
    merged: dict[tuple, int] = defaultdict(int)
    ids: dict[tuple, list[int]] = defaultdict(list)
    for r in affected:
        key = (r["tenant_id"], r["user_id"], r["kind"], r["new_date"])
        merged[key] += r["cnt"]
        ids[key].append(r["id"])
    with db.begin():
        # 1) 源行清零标记：直接删除受影响行
        db.execute(
            delete(CommunityUsageDaily).where(
                CommunityUsageDaily.id.in_([r["id"] for r in affected])
            )
        )
        # 2) 目标行 upsert 语义：同键存量行（此前已按新口径写入的）需累加而非覆盖
        for key, cnt in sorted(merged.items()):
            tenant_id, user_id, kind, new_date = key
            existing = db.execute(
                select(CommunityUsageDaily)
                .where(
                    CommunityUsageDaily.tenant_id == tenant_id,
                    CommunityUsageDaily.user_id == user_id,
                    CommunityUsageDaily.kind == kind,
                    CommunityUsageDaily.usage_date == new_date,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if existing is not None:
                existing.cnt = existing.cnt + cnt
                existing.updated_at = func.now()
            else:
                db.add(
                    CommunityUsageDaily(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        kind=kind,
                        usage_date=new_date,
                        cnt=cnt,
                    )
                )
    print(f"已重算 {len(affected)} 行，合并为 {len(merged)} 个归属键。")
    return len(affected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ES9-P-15 community_usage_daily 新旧口径重算")
    parser.add_argument("--apply", action="store_true", help="写库执行合并重算（默认 dry-run）")
    args = parser.parse_args(argv)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[rezone_recalc] 模式={mode}  目标表=community_usage_daily  口径=updated_at→北京日")
    with Session(engine) as db:
        rows = collect_recalc(db)
        print_table(rows)
        if args.apply:
            apply_recalc(db, rows)
        else:
            print("\n（dry-run：未写库。确认对照表后加 --apply 执行。）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
