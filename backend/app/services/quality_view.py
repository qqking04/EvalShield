# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""项目质量视图聚合服务（优化 4：实时聚合、不落库）。

单一数据源原则：`build_quality_payload` 同时供
- GET  /api/projects/{id}/quality-overview（前端质量视图 Tab）
- GET  /api/projects/{id}/quality-report/export（按需导出 pdf/word/md/html）
使用，保证"页面所见"与"导出所得"数字 100% 同源。

不新增任何表、不写任何库（导出审计除外，由路由层负责）。
详见 doc/优化4方案.md §4.1。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..models import Defect, Project, Report, TestTask

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 质量门禁阈值（优化4 §2；本期硬编码常量，配置化为下一期演进点）
# ---------------------------------------------------------------------------
QG_P0_OPEN_MAX = 0        # P0 未闭环缺陷数 ≤ 0（红线）
QG_P1_OPEN_MAX = 2        # P1 未闭环缺陷数 ≤ 2
QG_PASS_RATE_MIN = 90.0   # 近 30 天任务通过率 ≥ 90%
QG_NO_CRIT_RUNS = 3       # 最近 3 次完成任务不得出现 critical 风险（红线）

OPEN_DEFECT_STATUSES = ("NEW", "OPEN")          # 未闭环口径（FIXED/CLOSED=已闭环）
FINISHED_TASK_STATUSES = ("SUCCESS", "FAILED", "CANCELLED")
RUNNING_TASK_STATUSES = ("PENDING", "RUNNING", "CANCELING")

_GATE_LABELS = {
    "PASSED": "达标",
    "FAILED": "未达标",
    "WARN": "预警",
    "NO_DATA": "暂无数据",
}

_RISK_KEYS = ("critical", "high", "medium", "low", "none")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    """序列化到 JSON 层：统一归一 UTC（契约 C3），带 +00:00 后缀。"""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# 门禁判定（纯函数，便于单测）
# ---------------------------------------------------------------------------
def evaluate_gate(
    *,
    p0_open: int,
    p1_open: int,
    pass_rate_30d: float | None,
    finished_30d: int,
    crit_in_recent: int,
    recent_runs: int,
    task_finished_total: int,
) -> dict[str, Any]:
    """四态门禁结论：任一红线不过→FAILED；红线全过但其余不过→WARN；全过→PASSED。

    pass_rate_30d 为 None 表示近 30 天无完成任务（该项按"不满足"计入 WARN 判定，
    但整体若其它红线已过且全项目无完成任务，调用方以 NO_DATA 短路）。
    """
    pr_actual = pass_rate_30d if pass_rate_30d is not None else 0.0
    checks = [
        {
            "code": "P0_OPEN",
            "name": f"P0 未闭环缺陷 ≤ {QG_P0_OPEN_MAX}",
            "actual": p0_open,
            "threshold": QG_P0_OPEN_MAX,
            "passed": p0_open <= QG_P0_OPEN_MAX,
            "redline": True,
        },
        {
            "code": "P1_OPEN",
            "name": f"P1 未闭环缺陷 ≤ {QG_P1_OPEN_MAX}",
            "actual": p1_open,
            "threshold": QG_P1_OPEN_MAX,
            "passed": p1_open <= QG_P1_OPEN_MAX,
            "redline": False,
        },
        {
            "code": "PASS_RATE",
            "name": f"近30天任务通过率 ≥ {QG_PASS_RATE_MIN}%",
            "actual": pr_actual,
            "threshold": QG_PASS_RATE_MIN,
            # 30 天内无完成任务 → 该项无意义，视为通过（避免新项目被误判 WARN）
            "passed": finished_30d == 0 or pr_actual >= QG_PASS_RATE_MIN,
            "redline": False,
        },
        {
            "code": "CRIT_RUNS",
            "name": f"最近{QG_NO_CRIT_RUNS}次完成任务无 critical 风险",
            "actual": crit_in_recent,
            "threshold": 0,
            "passed": crit_in_recent == 0,
            "redline": True,
        },
    ]

    if task_finished_total == 0:
        conclusion = "NO_DATA"
    else:
        red_fail = any((not c["passed"]) and c["redline"] for c in checks)
        any_fail = any(not c["passed"] for c in checks)
        conclusion = "FAILED" if red_fail else ("WARN" if any_fail else "PASSED")

    return {"conclusion": conclusion, "conclusion_label": _GATE_LABELS[conclusion], "checks": checks}


# ---------------------------------------------------------------------------
# 聚合入口
# ---------------------------------------------------------------------------
def build_quality_payload(
    db: Session, project: Project, tenant_id: int, days: int = 90
) -> dict[str, Any]:
    """项目质量视图聚合（全部实时计算，不落库）。

    口径与 projects_ext.overview 一致：tenant_id + deleted_at IS NULL。
    days：趋势窗口与 PASS_RATE 无关（PASS_RATE 固定 30 天，见方案 §2）。
    """
    now = _now()
    window_from = now - timedelta(days=min(max(days, 7), 365))
    pid = project.id

    base_task = db.query(TestTask).filter(
        TestTask.project_id == pid,
        TestTask.tenant_id == tenant_id,
        TestTask.deleted_at.is_(None),
    )

    task_total = base_task.count()
    task_running = base_task.filter(TestTask.status.in_(RUNNING_TASK_STATUSES)).count()
    finished_q = base_task.filter(TestTask.status.in_(FINISHED_TASK_STATUSES))
    task_finished = finished_q.count()
    task_success = finished_q.filter(TestTask.status == "SUCCESS").count()
    pass_rate = round(task_success / task_finished * 100, 1) if task_finished else 0.0

    # 近 30 天通过率（门禁 PASS_RATE 项固定窗口，不随 days 变化）
    from30 = now - timedelta(days=30)
    fin30 = finished_q.filter(TestTask.finished_at >= from30)
    finished_30d = fin30.count()
    success_30d = fin30.filter(TestTask.status == "SUCCESS").count()
    pass_rate_30d = (
        round(success_30d / finished_30d * 100, 1) if finished_30d else None
    )

    # ---- 缺陷 ----
    base_def = db.query(Defect).filter(
        Defect.project_id == pid,
        Defect.tenant_id == tenant_id,
        Defect.deleted_at.is_(None),
    )
    defect_total = base_def.count()

    def _open_count(sev: str) -> int:
        return base_def.filter(
            Defect.severity == sev, Defect.status.in_(OPEN_DEFECT_STATUSES)
        ).count()

    p0_open, p1_open = _open_count("P0"), _open_count("P1")
    open_rows = (
        base_def.filter(Defect.status.in_(OPEN_DEFECT_STATUSES))
        .order_by(Defect.severity.asc(), Defect.created_at.desc())
        .limit(5)
        .all()
    )
    defect_open = base_def.filter(
        Defect.status.in_(OPEN_DEFECT_STATUSES)
    ).count()
    defect_closed = defect_total - defect_open
    closure_rate = round(defect_closed / defect_total * 100, 1) if defect_total else 0.0

    # ---- 报告（风险分布 / 最近报告 / 分引擎）----
    base_rep = db.query(Report).filter(
        Report.project_id == pid,
        Report.tenant_id == tenant_id,
        Report.deleted_at.is_(None),
    )
    report_total = base_rep.count()
    risk_distribution = {k: 0 for k in _RISK_KEYS}
    for lvl, cnt in (
        base_rep.with_entities(Report.risk_level, func.count(Report.id))
        .group_by(Report.risk_level)
        .all()
    ):
        key = str(lvl or "none").lower()
        # BUG-002：五档之外的异常值过滤，键集合恒为在册五档
        if key in risk_distribution:
            risk_distribution[key] += cnt

    recent_reports = (
        base_rep.order_by(Report.created_at.desc()).limit(5).all()
    )

    # 最近 N 次完成任务关联报告中的 critical 数（门禁 CRIT_RUNS 项）
    recent_finished = (
        finished_q.order_by(TestTask.finished_at.desc()).limit(QG_NO_CRIT_RUNS).all()
    )
    recent_task_ids = [t.id for t in recent_finished]
    crit_in_recent = 0
    if recent_task_ids:
        crit_in_recent = (
            db.query(func.count(Report.id))
            .filter(
                Report.task_id.in_(recent_task_ids),
                Report.risk_level == "critical",
                Report.deleted_at.is_(None),
            )
            .scalar()
            or 0
        )

    by_engine = _aggregate_by_engine(db, base_rep, pid, tenant_id)

    # ---- 趋势（按天，窗口内补 null 断点）----
    trend = _build_trend(db, pid, tenant_id, window_from, now)

    gate = evaluate_gate(
        p0_open=p0_open,
        p1_open=p1_open,
        pass_rate_30d=pass_rate_30d,
        finished_30d=finished_30d,
        crit_in_recent=crit_in_recent,
        recent_runs=len(recent_task_ids),
        task_finished_total=task_finished,
    )

    return {
        "project": {
            "id": pid,
            "code": project.code,
            "name": project.name,
            "owner_name": project.owner_name,
            "status": project.status,
            "updated_at": _iso(project.updated_at),
        },
        "gate": gate,
        "metrics": {
            "task_total": task_total,
            "task_finished": task_finished,
            "task_running": task_running,
            "pass_rate": pass_rate,
            "pass_rate_30d": pass_rate_30d,
            "report_total": report_total,
            "defect_total": defect_total,
            "defect_open": defect_open,
            "defect_closed": defect_closed,
            "p0_open": p0_open,
            "p1_open": p1_open,
            "closure_rate": closure_rate,
            "risk_distribution": risk_distribution,
            "top_open_defects": [
                {
                    "defect_no": d.defect_no,
                    "title": d.title,
                    "severity": d.severity,
                    "status": d.status,
                    "created_at": _iso(d.created_at),
                }
                for d in open_rows
            ],
        },
        "trend": trend,
        "by_engine": by_engine,
        "latest_reports": [
            {
                "id": r.id,
                "report_no": r.report_no,
                "task_no": r.task_no,
                "title": r.title,
                "risk_level": r.risk_level,
                "generated_at": _iso(r.generated_at or r.created_at),
            }
            for r in recent_reports
        ],
        "days": min(max(days, 7), 365),
        "generated_at": _iso(now),
    }


def _build_trend(
    db: Session, pid: int, tenant_id: int, window_from: datetime, now: datetime
) -> dict[str, Any]:
    """近 N 天按天趋势：完成任务通过率（无完成任务日= null）、缺陷新增/闭环数。"""
    # PG 会话时区可能非 UTC（如 Asia/Shanghai）：date_trunc 前先用
    # timezone('UTC', timestamptz) 归一为 UTC naive，保证分组键与窗口（契约 C3：UTC）同日。
    day_col = func.date_trunc("day", func.timezone("UTC", TestTask.finished_at)).label("d")
    rows = (
        db.query(
            day_col,
            func.count(TestTask.id).label("total"),
            func.sum(
                case((TestTask.status == "SUCCESS", 1), else_=0)
            ).label("succ"),
        )
        .filter(
            TestTask.project_id == pid,
            TestTask.tenant_id == tenant_id,
            TestTask.deleted_at.is_(None),
            TestTask.status.in_(FINISHED_TASK_STATUSES),
            TestTask.finished_at >= window_from,
        )
        .group_by(day_col)
        .all()
    ) if _supports_trunc(db) else _trend_fallback_python(
        db, pid, tenant_id, window_from
    )

    pass_map: dict[str, float | None] = {}
    for d, total, succ in rows:
        key = _date_key(d)
        pass_map[key] = round(int(succ or 0) / int(total) * 100, 1) if total else None

    new_map = _daily_counts(
        db, Defect.created_at, Defect, pid, tenant_id, window_from,
        deleted=Defect.deleted_at,
    )
    closed_map = _daily_counts(
        db, Defect.updated_at, Defect, pid, tenant_id, window_from,
        deleted=Defect.deleted_at,
        extra=lambda q: q.filter(Defect.status.in_(("FIXED", "CLOSED"))),
    )

    dates: list[str] = []
    pr: list[float | None] = []
    dn: list[int] = []
    dc: list[int] = []
    cur = window_from.date()
    end = now.date()
    while cur <= end:
        key = cur.isoformat()
        dates.append(key)
        pr.append(pass_map.get(key))
        dn.append(int(new_map.get(key, 0)))
        dc.append(int(closed_map.get(key, 0)))
        cur += timedelta(days=1)
    return {"dates": dates, "pass_rate": pr, "defect_new": dn, "defect_closed": dc}


def _supports_trunc(db: Session) -> bool:
    """date_trunc 是 PG 方言函数；sqlite 测试库下降级为 Python 分组。"""
    try:
        return db.bind.dialect.name == "postgresql"
    except Exception:  # noqa: BLE001
        return False


def _date_key(d: Any) -> str:
    if isinstance(d, str):
        return d[:10]
    return d.date().isoformat() if hasattr(d, "date") else str(d)[:10]


def _trend_fallback_python(
    db: Session, pid: int, tenant_id: int, window_from: datetime
) -> list[tuple]:
    """sqlite 测试库：Python 侧按天分组完成任务。"""
    tasks = (
        db.query(TestTask)
        .filter(
            TestTask.project_id == pid,
            TestTask.tenant_id == tenant_id,
            TestTask.deleted_at.is_(None),
            TestTask.status.in_(FINISHED_TASK_STATUSES),
            TestTask.finished_at >= window_from,
        )
        .all()
    )
    groups: dict[str, list[TestTask]] = {}
    for t in tasks:
        if t.finished_at is None:
            continue
        # 与 PG 分支同口径：aware 值先转 UTC 再取日期（契约 C3），naive 视为 UTC
        ft = t.finished_at
        ft = ft.astimezone(timezone.utc) if ft.tzinfo is not None else ft
        groups.setdefault(ft.date().isoformat(), []).append(t)
    return [
        (
            key,
            len(ts),
            sum(1 for x in ts if x.status == "SUCCESS"),
        )
        for key, ts in sorted(groups.items())
    ]


def _daily_counts(
    db: Session, col, table, pid: int, tenant_id: int,
    window_from: datetime, deleted=None, extra=None,
) -> dict[str, int]:
    """按天计数（Python 分组，兼容 sqlite/PG，窗口内数据量小）。"""
    q = db.query(col).filter(
        table.project_id == pid,
        table.tenant_id == tenant_id,
        col >= window_from,
    )
    if deleted is not None:
        q = q.filter(deleted.is_(None))
    if extra is not None:
        q = extra(q)
    out: dict[str, int] = {}
    for row in q.all():
        # 单列 Query 返回 Row（非 tuple 子类，SQLAlchemy 2.x）或标量——两种形态兼容
        dt = row[0] if not hasattr(row, "date") and not isinstance(row, datetime) else row
        if dt is None:
            continue
        # 分组键统一 UTC 口径（契约 C3）：PG 读回的 timestamptz 为会话时区 aware，
        # 需先转 UTC 再取日期，否则 +08 会话下凌晨时段会跨日错位。
        if isinstance(dt, datetime):
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            key = dt.date().isoformat()
        else:
            key = str(dt)[:10]
        out[key] = out.get(key, 0) + 1
    return out


def _aggregate_by_engine(
    db: Session, base_rep, pid: int, tenant_id: int
) -> list[dict[str, Any]]:
    """分引擎风险：取每引擎最新一次任务报告 step_details 结果（异常降级不阻塞）。"""
    try:
        reports = (
            base_rep.order_by(Report.created_at.asc()).limit(2000).all()
        )
        agg: dict[str, dict[str, Any]] = {}
        for r in reports:
            payload = r.content or {}
            steps = payload.get("step_details") or []
            for s in steps:
                eng = str(s.get("engine") or "-")
                if eng == "-":
                    continue
                issue_cnt = 0
                try:
                    summ = s.get("summary") or {}
                    details = s.get("details") or {}
                    items = details.get("items") if isinstance(details, dict) else None
                    if isinstance(items, list):
                        issue_cnt = sum(
                            1
                            for it in items
                            if isinstance(it, dict)
                            and str(it.get("verdict") or it.get("result") or "").upper()
                            in ("RISK", "FAIL", "RISKY")
                        )
                    else:
                        issue_cnt = int(
                            summ.get("failed")
                            or summ.get("risk_count")
                            or summ.get("fail")
                            or 0
                        )
                except Exception:  # noqa: BLE001
                    issue_cnt = 0
                entry = agg.setdefault(
                    eng, {"engine": eng, "runs": 0, "issues": 0, "latest_report_id": None}
                )
                entry["runs"] += 1
                entry["issues"] = issue_cnt  # 最新一次为准
                entry["latest_risk"] = str(r.risk_level or "none")
                entry["latest_report_id"] = r.id
        return sorted(agg.values(), key=lambda x: -x["runs"])
    except Exception:  # noqa: BLE001
        logger.warning("分引擎聚合失败（该区块前端隐藏）", exc_info=True)
        return []
