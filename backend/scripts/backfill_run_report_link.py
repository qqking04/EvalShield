# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""ES11 存量数据补链：按 task 关系回填 EvalRun.report_id（一次性运维脚本）。

背景：任务链历史版本生成报告后未回填 run.report_id，导致 G4 delivery-readiness
恒 RUN_LINK BLOCK。新任务已在 task_runner 内自动回填；本脚本处理存量。

口径：
- 仅回填 report_id IS NULL 且 task_id 非空的运行；
- 同任务多报告时取最新一张（id 最大）；
- 运行与报告租户必须一致，否则跳过并计数（防跨租户错链）；
- 默认 dry-run 只打印，--apply 才写库。

用法（backend 目录）：
    python scripts/backfill_run_report_link.py            # 预览
    python scripts/backfill_run_report_link.py --apply    # 执行
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import EvalRun, Report  # noqa: E402


def main(apply: bool) -> int:
    db = SessionLocal()
    try:
        runs = (
            db.query(EvalRun)
            .filter(
                EvalRun.report_id.is_(None),
                EvalRun.task_id.isnot(None),
                EvalRun.deleted_at.is_(None),
            )
            .order_by(EvalRun.id.asc())
            .all()
        )
        latest_by_task = dict(
            db.query(Report.task_id, func.max(Report.id))
            .filter(Report.deleted_at.is_(None))
            .group_by(Report.task_id)
            .all()
        )
        hit = skip_tenant = skip_none = 0
        orphans: list[tuple[int, str, object, str]] = []
        for run in runs:
            rep_id = latest_by_task.get(int(run.task_id))
            if rep_id is None:
                skip_none += 1
                orphans.append((int(run.id), run.run_no, run.task_id, run.status))
                continue
            rep = db.get(Report, int(rep_id))
            if (rep.tenant_id or 1) != (run.tenant_id or 1):
                skip_tenant += 1
                print(f"[SKIP-tenant] run={run.id} task={run.task_id} report={rep_id}")
                continue
            print(f"[{'APPLY' if apply else 'DRY'}] run={run.id}({run.run_no}) "
                  f"-> report={rep_id}({rep.report_no})")
            if apply:
                run.report_id = int(rep_id)
            hit += 1
        if apply and hit:
            db.commit()
        print(f"-- 共 {len(runs)} 条断链运行：可补 {hit}，任务无报告 {skip_none}，"
              f"租户不一致跳过 {skip_tenant}（{'已写库' if apply else 'dry-run 未写库'}）")
        if orphans:
            # 联合报表：任务无报告的断链运行，附任务状态供人工定性
            from app.models import TestTask

            print("\n-- 任务无报告运行明细（run → task 状态）--")
            for rid, rno, tid, st in orphans:
                t = db.get(TestTask, int(tid)) if tid else None
                tdesc = f"task#{tid}:{t.status if t else '任务不存在'}" if tid else "无task"
                print(f"   run={rid}({rno}) run_status={st} {tdesc}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
