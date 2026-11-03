# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""ES11 §3.7：质量总览聚合（开发方案 W6，ES11-DASH-001/PERF-001）。

GET /api/dashboard/quality —— 单接口九项指标，全部走聚合 SQL（COUNT/SUM/MIN/AVG
+ GROUP BY，命中既有租户/时间/状态索引），禁止逐行 N+1；每项附下钻查询参数。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Numeric, case, cast, func, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import AuthContext, require_permission
from ..errors import ok
from ..models import Defect, DefectEvent, EvalRun, ReviewItem, Trace
from ..services import calibration

logger = logging.getLogger(__name__)
router = APIRouter()

TERMINAL = ("PASSED", "SUCCESS", "FAILED")
LOW_SCORE = 0.5  # 线上低分阈值（scores.overall < 0.5）


@router.get("/dashboard/quality", response_model=dict)
def quality_overview(
    days: int = Query(30, ge=1, le=365, description="统计窗口（天）"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("eval", "read")),
):
    """质量总览九指标（§3.7）：可交付/阻塞/待复核/P0P1/整改未验证/回归/关闭率/Judge/低分复发。"""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    tenant = auth.tenant_id

    def _t(q):
        return q if auth.is_super_admin else q.filter(EvalRun.tenant_id == tenant)

    # --- 运行轨（窗口内终态运行）：needs_review / 演示模式 / 可交付 ---
    needs_review = EvalRun.summary["needs_review"].astext == "true"
    demo = EvalRun.run_snapshot["target_mode"].astext == "INTERNAL_DEMO"
    run_base = _t(
        db.query(
            func.count(EvalRun.id),
            func.sum(case((needs_review, 1), else_=0)),
            func.sum(case((demo, 1), else_=0)),
            func.sum(case((or_(needs_review, demo), 1), else_=0)),
        )
    ).filter(EvalRun.deleted_at.is_(None), EvalRun.status.in_(TERMINAL), EvalRun.created_at >= start)
    total_runs, review_runs, demo_runs, blocked_runs = [int(x or 0) for x in run_base.one()]

    # --- 未闭环 P0/P1（租户级，与 G4 P0P1_CLOSED 同口径）---
    def _dt(q):
        return q if auth.is_super_admin else q.filter(Defect.tenant_id == tenant)

    open_p0p1 = int(
        _dt(db.query(func.count(Defect.id))).filter(
            Defect.deleted_at.is_(None),
            Defect.severity.in_(("P0", "P1")),
            Defect.status.in_(("NEW", "OPEN", "FIXED", "VERIFYING", "REOPENED")),
        ).scalar() or 0
    )
    deliverable_runs = (total_runs - blocked_runs) if open_p0p1 == 0 else 0

    # --- 待复核队列：数量 + 最老等待时长 ---
    def _rt(q):
        return q if auth.is_super_admin else q.filter(ReviewItem.tenant_id == tenant)

    pending_cnt, oldest = _rt(
        db.query(func.count(ReviewItem.id), func.min(ReviewItem.created_at))
    ).filter(ReviewItem.status.in_(("OPEN", "ASSIGNED"))).one()
    oldest_wait_hours = (
        round((now - oldest).total_seconds() / 3600, 1) if oldest else None
    )

    # --- 已整改未验证（FIXED 停留态）---
    remediated_unverified = int(
        _dt(db.query(func.count(Defect.id))).filter(
            Defect.deleted_at.is_(None), Defect.status == "FIXED"
        ).scalar() or 0
    )

    # --- 最近版本回归数（窗口内 REGRESSION 运行）---
    regression_runs = int(
        _t(db.query(func.count(EvalRun.id)))
        .filter(
            EvalRun.deleted_at.is_(None),
            EvalRun.run_purpose == "REGRESSION",
            EvalRun.created_at >= start,
        ).scalar() or 0
    )

    # --- 缺陷验证关闭率：有 VERIFIED 事件的缺陷中当前 CLOSED 占比 ---
    vsub = (
        (db.query(func.distinct(DefectEvent.defect_id).label("did"))
         if auth.is_super_admin else
         db.query(func.distinct(DefectEvent.defect_id).label("did")).filter(DefectEvent.tenant_id == tenant))
        .filter(DefectEvent.event_type == "VERIFIED")
        .subquery()
    )
    verified_total = int(
        _dt(db.query(func.count(Defect.id))).join(vsub, vsub.c.did == Defect.id)
        .filter(Defect.deleted_at.is_(None)).scalar() or 0
    )
    verified_closed = int(
        _dt(db.query(func.count(Defect.id))).join(vsub, vsub.c.did == Defect.id)
        .filter(Defect.deleted_at.is_(None), Defect.status == "CLOSED").scalar() or 0
    )
    close_rate = round(verified_closed / verified_total, 4) if verified_total else None

    # --- Judge 健康：Kappa（租户级 12 周复核样本）+ 窗口内双轨一致率均值 ---
    rep = calibration.calibration_report(db, tenant, weeks=12)
    overall = rep.get("overall") or {}
    agr = (
        _t(db.query(func.avg(cast(EvalRun.summary["judge_agreement_rate"].astext, Numeric))))
        .filter(
            EvalRun.deleted_at.is_(None), EvalRun.status.in_(TERMINAL),
            EvalRun.created_at >= start,
            EvalRun.summary["judge_agreement_rate"].isnot(None),
        ).scalar()
    )
    disagreement_rate = round(1.0 - float(agr), 4) if agr is not None else None

    # --- 线上低分 Trace 复发：同请求文本低分（overall<0.5）出现 ≥2 次的簇 ---
    def _tt(q):
        return q if auth.is_super_admin else q.filter(Trace.tenant_id == tenant)

    overall_expr = cast(cast(Trace.scores, JSONB)["overall"].astext, Numeric)
    low_sub = (
        _tt(db.query(func.count(Trace.id).label("n")))
        .filter(
            Trace.eval_status == "SCORED", Trace.occurred_at >= start,
            overall_expr.isnot(None), overall_expr < LOW_SCORE,
        )
        .group_by(Trace.request)
        .having(func.count(Trace.id) >= 2)
        .subquery()
    )
    recur_clusters = int(db.query(func.count()).select_from(low_sub).scalar() or 0)
    recur_traces = int(db.query(func.coalesce(func.sum(low_sub.c.n), 0)).select_from(low_sub).scalar() or 0)

    return ok({
        "window_days": days,
        "generated_at": now.isoformat(),
        "metrics": {
            "deliverable_runs": {"value": deliverable_runs, "terminal_runs": total_runs,
                                 "drill": {"path": "/eval", "query": {"status": "TERMINAL"}}},
            "blocked_runs": {"value": blocked_runs, "review": int(review_runs), "demo": int(demo_runs),
                             "drill": {"path": "/eval", "query": {"blocked": "true"}}},
            "pending_review_items": {"value": int(pending_cnt or 0),
                                     "oldest_wait_hours": oldest_wait_hours,
                                     "drill": {"path": "/review", "query": {"status": "OPEN"}}},
            "open_p0p1_defects": {"value": open_p0p1,
                                  "drill": {"path": "/defects", "query": {"severity": "P0,P1", "status": "OPEN"}}},
            "remediated_unverified": {"value": remediated_unverified,
                                      "drill": {"path": "/defects", "query": {"status": "FIXED"}}},
            "recent_regression_runs": {"value": regression_runs,
                                       "drill": {"path": "/eval", "query": {"run_purpose": "REGRESSION"}}},
            "defect_verified_close_rate": {"value": close_rate, "verified_total": verified_total,
                                           "verified_closed": verified_closed,
                                           "drill": {"path": "/defects", "query": {"verified": "true"}}},
            "judge_health": {"kappa": overall.get("kappa"), "sample": int(overall.get("n") or 0),
                             "sufficient": bool(overall.get("sufficient", int(overall.get("n") or 0) >= 10)),
                             "threshold": calibration.KAPPA_WARN,
                             "disagreement_rate": disagreement_rate,
                             "drill": {"path": "/review", "query": {"tab": "judge"}}},
            "low_score_trace_recurrence": {"value": recur_clusters, "traces": recur_traces,
                                           "threshold": LOW_SCORE,
                                           "drill": {"path": "/traces", "query": {"low_score": "true"}}},
        },
    })
