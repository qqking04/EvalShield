# -*- coding: utf-8 -*-
"""ES11 R-13：演示用「可交付」全链夹具的常驻 seed 脚本（M2 评审/演示可复跑）。

裁决口径（优化11BUG.md §5 R-13）：**不常驻库内数据**——常驻报告会污染
GET /api/dashboard/quality 的真实指标（deliverable_runs / open_p0p1 等），
故提供本脚本按需播种、用毕 --remove 清理（幂等）。

夹具构造法（沿用 R-9 实测闭环路径）：
  1. INSERT reports（report_no=ES11-DEMO-RPT）+ eval_runs（run_no=ES11-DEMO-RUN，
     status=SUCCESS、target_id/question_bank_id/run_snapshot.target_mode 满足 G4
     BINDINGS/NOT_DEMO 判据），run.report_id 关联；
  2. 临时关闭本租户未闭环 P0/P1（放行 P0P1_CLOSED，原状态记入 summary 快照）；
  3. 直调 gate_service 校验 deliverable=true，并把冻结标记写入 reports.summary._freeze
     （等价 POST /freeze-conclusion，避免依赖登录凭据）。

用法（backend 目录或任意 cwd）：
  python scripts/seed_es11_delivery_demo.py --tenant 1            # 播种
  python scripts/seed_es11_delivery_demo.py --tenant 1 --remove   # 清理（还原缺陷+删行）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import text  # noqa: E402
from app.database import SessionLocal  # noqa: E402

RPT_NO = "ES11-DEMO-RPT"
RUN_NO = "ES11-DEMO-RUN"
OPEN_STATUSES = ("NEW", "OPEN", "FIXED", "VERIFYING", "REOPENED")


def _seed(db, tenant: int, target_id: str, bank_id: int) -> None:
    if db.execute(text("SELECT id FROM reports WHERE report_no=:n"), {"n": RPT_NO}).fetchone():
        print("已存在，跳过播种（幂等）")
        return
    src = db.execute(text(
        "SELECT task_id, project_id FROM reports WHERE tenant_id=:t AND deleted_at IS NULL "
        "ORDER BY id DESC LIMIT 1"), {"t": tenant}).fetchone()
    if src is None:
        raise SystemExit(f"租户 {tenant} 无任何报告可借用 task_id/project_id，无法播种")
    # 缺陷临时关闭 + 快照写进报告 summary（--remove 依据此还原）
    rows = db.execute(text(
        "SELECT id, status FROM defects WHERE tenant_id=:t AND deleted_at IS NULL "
        "AND severity IN ('P0','P1') AND status = ANY(:st)"),
        {"t": tenant, "st": list(OPEN_STATUSES)}).fetchall()
    snap = {str(r[0]): r[1] for r in rows}
    db.execute(text(
        "UPDATE defects SET status='CLOSED' WHERE tenant_id=:t AND deleted_at IS NULL "
        "AND severity IN ('P0','P1') AND status = ANY(:st)"),
        {"t": tenant, "st": list(OPEN_STATUSES)})
    db.execute(text(
        "INSERT INTO reports (report_no, task_id, project_id, title, report_type, format,"
        " status, tenant_id, summary, created_at) VALUES (:n, :tk, :pj,"
        " 'ES11 可交付演示报告（seed 脚本管理，非真实交付物）', 'EVALUATION', 'PDF',"
        " 'GENERATED', :t, CAST(:s AS jsonb), now())"),
        {"n": RPT_NO, "tk": src[0], "pj": src[1], "t": tenant,
         "s": json.dumps({"_demo_seed": {"defect_status_before": snap}})})
    rpt_id = int(db.execute(text("SELECT id FROM reports WHERE report_no=:n"),
                            {"n": RPT_NO}).fetchone()[0])
    db.execute(text(
        "INSERT INTO eval_runs (run_no, eval_set_id, target_type, target_id, judge_mode,"
        " status, tenant_id, question_bank_id, run_snapshot, summary, report_id, created_at)"
        " VALUES (:n, 0, 'LLM_API', :tg, 'RULE', 'SUCCESS', :t, :b,"
        " CAST(:sn AS jsonb), CAST(:su AS jsonb), :r, now())"),
        {"n": RUN_NO, "tg": target_id, "t": tenant, "b": bank_id, "r": rpt_id,
         "sn": json.dumps({"target_mode": "API", "demo_seed": True}),
         "su": json.dumps({})})
    db.commit()

    # G4 自检 + 冻结（等价 POST /freeze-conclusion）
    from app.models import EvalRun, Report
    from app.services import gate_service
    run = db.query(EvalRun).filter(EvalRun.run_no == RUN_NO).one()
    rep = db.get(Report, rpt_id)
    g4 = gate_service.delivery_readiness(db, run, rep)
    if not g4["deliverable"]:
        bad = [c for c in g4["checklist"] if c["status"] == "BLOCK"]
        print("G4 未达可交付，回滚：", json.dumps(bad, ensure_ascii=False))
        _remove(db, tenant)
        raise SystemExit(2)
    rep.summary = {**(rep.summary or {}), "_freeze": {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "frozen_by": 0, "frozen_by_name": "seed_es11_delivery_demo",
        "note": "演示夹具冻结标记"}}
    db.commit()
    print(f"播种完成 report_id={rpt_id} run_id={int(run.id)} deliverable=True")


def _remove(db, tenant: int) -> None:
    row = db.execute(text("SELECT id, summary FROM reports WHERE report_no=:n"),
                     {"n": RPT_NO}).fetchone()
    db.execute(text("DELETE FROM eval_runs WHERE run_no=:n"), {"n": RUN_NO})
    if row:
        snap = ((row[1] or {}).get("_demo_seed") or {}).get("defect_status_before") or {}
        for did, st in snap.items():
            # 仅还原仍为演示期 CLOSED 的行，避免覆盖走查后的真实处置
            db.execute(text("UPDATE defects SET status=:s WHERE id=:i AND status='CLOSED'"
                            " AND tenant_id=:t"), {"s": st, "i": int(did), "t": tenant})
        db.execute(text("DELETE FROM reports WHERE report_no=:n"), {"n": RPT_NO})
    db.commit()
    print("清理完成（夹具行删除，缺陷状态按快照还原）")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant", type=int, default=1)
    ap.add_argument("--target-id", default="75", help="G4 BINDINGS 用被测系统 code/id 字符串")
    ap.add_argument("--bank-id", type=int, default=527, help="G4 BINDINGS 用题库 id")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        _remove(db, args.tenant) if args.remove else _seed(db, args.tenant, args.target_id, args.bank_id)
    finally:
        db.close()


if __name__ == "__main__":
    main()
