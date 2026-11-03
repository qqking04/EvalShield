# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""M4 报告可视化扩展路由（开源面保留端点）。

- 内部端点（登录态）：GET charts / PUT shares / DELETE shares / GET sections

版本隔离改造（B13）：GET compare、POST/GET shares、public 读取/解锁
已剪切迁出至 app/commercial/routers/{report_compare,report_shares}.py（URL 不变）。
"""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import AuthContext, authenticate_request
from ..errors import DataScopeError, NotFoundError
from ..models import Report, ReportShare, TaskStep
from ..secure_static import sign_static_url

# ---------------------------------------------------------------------------
# 请求/响应 Schema
# ---------------------------------------------------------------------------


class ShareUpdateIn(BaseModel):
    is_enabled: bool


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _build_charts(report: Report, db: Session) -> dict[str, Any]:
    """从 Report.content / Report.summary / TaskStep 聚合图表数据。

    兜底链（从最可靠到次之）：
    1. Report.summary 里显式写的 total/passed/failed —— 新报告都有
    2. content.step_details 里各 step 的 summary 重新聚合 —— 历史/异常修复后
    3. TaskStep.result_summary 重新聚合 —— 最原始数据，永不丢失
    """
    content = report.content or {}
    summary = report.summary or {}

    # ----- 汇总：三级兜底 -----
    total = int(summary.get("total") or 0)
    passed = int(summary.get("passed") or 0)
    failed = int(summary.get("failed") or 0)

    def _from_step_details() -> tuple[int, int, int]:
        """从 content.step_details 重新聚合。"""
        st = content.get("step_details") or content.get("step_results") or []
        if not isinstance(st, list):
            return 0, 0, 0
        t = p = f = 0
        for s in st:
            if not isinstance(s, dict):
                continue
            sm = s.get("summary") or {}
            t += int(sm.get("total") or 0)
            p += int(sm.get("passed") or 0)
            f += int(sm.get("failed") or 0)
            # step.details.results 里的单条 PASS/FAIL 也计入（某些引擎 summary 为 0 但 results 里有判定）
            for g in (s.get("details") or {}).get("results") or []:
                if isinstance(g, dict):
                    r = str(g.get("result") or "").upper()
                    if r == "PASS":
                        p += 1; t += 1
                    elif r == "FAIL":
                        f += 1; t += 1
        return t, p, f

    def _from_task_steps() -> tuple[int, int, int]:
        """从 TaskStep.result_summary 重新聚合。"""
        t = p = f = 0
        for step in db.query(TaskStep).filter(TaskStep.task_id == report.task_id).all():
            sm = step.result_summary or {}
            t += int(sm.get("total") or 0)
            p += int(sm.get("passed") or 0)
            f += int(sm.get("failed") or 0)
        return t, p, f

    # 如果 summary 全 0，依次尝试从 step_details、TaskStep 兜底
    if total == 0 and passed == 0 and failed == 0:
        t2, p2, f2 = _from_step_details()
        if t2 > 0 or p2 > 0 or f2 > 0:
            total, passed, failed = t2, p2, f2
        else:
            t3, p3, f3 = _from_task_steps()
            if t3 > 0 or p3 > 0 or f3 > 0:
                total, passed, failed = t3, p3, f3

    pass_rate = float(summary.get("pass_rate")) if summary.get("pass_rate") is not None else (
        round(passed / total, 4) if total > 0 else 0.0
    )
    # v2.0 BUG-012：风险等级优先取落库字段（英文枚举），历史报告兜底重算
    risk_level = (report.risk_level or "").strip()
    risk_basis = (report.risk_basis or "").strip()
    if not risk_level or risk_level == "none" and (total > 0 and passed < total):
        fatal_count = 0
        _FATAL = {"CRITICAL", "FATAL", "P0", "严重", "致命", "高危"}
        if isinstance(content.get("defects"), list):
            for d in content["defects"]:
                if not isinstance(d, dict):
                    continue
                sev = str(d.get("severity", "")).strip()
                if sev.upper() in _FATAL or sev in _FATAL:
                    fatal_count += 1
        if fatal_count > 0 or (total > 0 and pass_rate < 0.6):
            risk_level = "high"
        elif total > 0 and pass_rate < 0.85:
            risk_level = "medium"
        else:
            risk_level = "low"
        if not risk_basis:
            risk_basis = f"通过率 {round(pass_rate * 100, 2)}%，按历史兜底规则判定"
    # TC-007：历史 100% 通过报告落库 basis 为空时兜底补全判定依据
    if not risk_basis:
        if total == 0:
            # 报告尚未生成完成（无执行数据），不输出误导性通过率
            risk_basis = "报告暂无执行数据，待生成完成后判定风险等级"
        elif risk_level == "none" or passed >= total:
            risk_level = risk_level or "none"
            risk_basis = f"通过率 {round(pass_rate * 100, 2)}% 且无失败用例，判定为无风险项"
        else:
            risk_basis = f"通过率 {round(pass_rate * 100, 2)}%，按历史兜底规则判定"

    # ----- 雷达图（六维指标，[{name, value}] 数组格式，BUG-001） -----
    default_indicators = ["功能正确性", "稳定性", "安全性", "性能", "合规性", "可恢复性"]
    indicators = summary.get("indicators") or content.get("indicators") or default_indicators
    values = summary.get("indicator_values") or content.get("indicator_values") or [0] * len(indicators)
    radar = [{"name": str(n), "value": float(v)} for n, v in zip(indicators, values)]

    # ----- 饼图：缺陷严重程度分布（[{name, value}]，BUG-001） -----
    # 数据源修正：content.defects 在新报告中恒为空，改为优先取 Defect 表真实严重度分布，
    # 兜底再取 content.defects，最后用 通过/失败/跳过 结果分布保证饼图非空白
    severity_dist: dict[str, int] = {}
    try:
        from ..models import Defect as _Defect
        for sev, cnt in (
            db.query(_Defect.severity, func.count(_Defect.id))
            .filter(_Defect.report_id == report.id, _Defect.deleted_at.is_(None))
            .group_by(_Defect.severity)
            .all()
        ):
            severity_dist[str(sev or "未知")] = int(cnt)
        if not severity_dist and report.task_id:
            for sev, cnt in (
                db.query(_Defect.severity, func.count(_Defect.id))
                .filter(_Defect.task_id == report.task_id, _Defect.deleted_at.is_(None))
                .group_by(_Defect.severity)
                .all()
            ):
                severity_dist[str(sev or "未知")] = int(cnt)
    except Exception:  # noqa: BLE001
        severity_dist = {}
    if not severity_dist and isinstance(content.get("defects"), list):
        for d in content["defects"]:
            if not isinstance(d, dict):
                continue
            sev = str(d.get("severity") or "未知")
            severity_dist[sev] = severity_dist.get(sev, 0) + 1
    if severity_dist:
        pie = [{"name": k, "value": v} for k, v in severity_dist.items()]
    else:
        # 无缺陷单时用执行结果分布兜底（BUG-001：结果分布图非空白）
        skipped = max(total - passed - failed, 0)
        pie = [
            {"name": "通过", "value": passed},
            {"name": "失败", "value": failed},
        ]
        if skipped > 0:
            pie.append({"name": "跳过", "value": skipped})
        if passed == 0 and failed == 0 and skipped == 0:
            pie = []

    # ----- 柱状图：各引擎缺陷数量（[{name, value}]，BUG-001） -----
    engine_counts: dict[str, int] = {}
    task_steps = db.query(TaskStep).filter(TaskStep.task_id == report.task_id).all()
    for step in task_steps:
        result = step.result_summary or {}
        defects = 0
        if isinstance(result.get("defects"), list):
            defects = len(result["defects"])
        elif result.get("failed") is not None:
            defects = int(result.get("failed") or 0)
        engine_counts[step.engine_name or step.engine_code] = (
            engine_counts.get(step.engine_name or step.engine_code, 0) + defects
        )
    bar = [{"name": c, "value": int(v)} for c, v in engine_counts.items()]

    # ----- 趋势图：本项目通过率趋势（最近 10 次报告；键名 trend → line，[{name, value}]，BUG-001） -----
    trend_reports = (
        db.query(Report)
        .filter(
            Report.project_id == report.project_id,
            Report.deleted_at.is_(None),
            Report.status == "DONE",
        )
        .order_by(Report.generated_at.desc())
        .limit(10)
        .all()
    )
    trend_reports.reverse()
    line: list[dict[str, Any]] = []
    for rp in trend_reports:
        rp_summary = rp.summary or {}
        rp_total = int(rp_summary.get("total") or 0)
        rp_passed = int(rp_summary.get("passed") or 0)
        rp_rate = float(rp_summary.get("pass_rate")) if rp_summary.get("pass_rate") is not None else (
            round(rp_passed / rp_total, 4) if rp_total > 0 else 0.0
        )
        ts = rp.generated_at or rp.created_at
        line.append({"name": ts.strftime("%Y-%m-%d") if ts else "", "value": round(rp_rate * 100, 2)})

    return {
        "radar": radar,
        "pie": pie,
        "bar": bar,
        "line": line,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(pass_rate, 4),
            "risk_level": risk_level,
            "risk_basis": risk_basis,
        },
    }


def _serialize_share(share: ReportShare) -> dict[str, Any]:
    return {
        "id": share.id,
        "report_id": share.report_id,
        "share_token": share.share_token,
        "has_password": bool(share.password_hash),
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        "is_permanent": share.expires_at is None,
        "view_count": share.view_count,
        "max_views": share.max_views,
        "is_enabled": share.is_enabled,
        "last_view_ip": share.last_view_ip,
        "created_at": share.created_at.isoformat(),
        "updated_at": share.updated_at.isoformat(),
    }


def _ensure_report_visible(report: Report, auth: AuthContext) -> None:
    if auth.is_super_admin:
        return
    if report.tenant_id != auth.tenant_id:
        raise DataScopeError("ES-DATA-0001", "无权访问该报告")


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
router = APIRouter()


# -------- 1. GET /api/reports/{report_id}/charts --------
@router.get("/reports/{report_id}/charts")
async def get_report_charts(
    report_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """报告可视化图表（六维雷达 / 缺陷严重度饼 / 引擎缺陷柱 / 项目通过率趋势 + 汇总）。"""
    report = db.get(Report, report_id)
    if report is None or report.deleted_at is not None:
        raise NotFoundError("ES-COMMON-0004", "报告不存在")
    _ensure_report_visible(report, auth)
    charts = _build_charts(report, db)
    return {"code": 0, "data": charts, "message": "ok"}


# -------- 2. PUT /api/shares/{share_id} --------
@router.put("/shares/{share_id}")
async def toggle_share(
    share_id: int,
    body: ShareUpdateIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    share = db.get(ReportShare, share_id)
    if share is None:
        raise NotFoundError("ES-COMMON-0004", "分享不存在")
    if share.tenant_id != auth.tenant_id and not auth.is_super_admin:
        raise DataScopeError("ES-DATA-0001", "无权操作该分享")
    share.is_enabled = body.is_enabled
    db.add(share)
    db.commit()
    db.refresh(share)
    return {"code": 0, "data": _serialize_share(share), "message": "ok"}


# -------- 3. DELETE /api/shares/{share_id} --------
@router.delete("/shares/{share_id}")
async def delete_share(
    share_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    share = db.get(ReportShare, share_id)
    if share is None:
        raise NotFoundError("ES-COMMON-0004", "分享不存在")
    if share.tenant_id != auth.tenant_id and not auth.is_super_admin:
        raise DataScopeError("ES-DATA-0001", "无权操作该分享")
    db.delete(share)
    db.commit()
    return {"code": 0, "data": None, "message": "已删除"}


# -------- 4. GET /api/reports/{report_id}/sections （AI 测试优化 B12 四节结构化） --------
def _evidence_url(path: str, tenant_id: int) -> str:
    """将截图绝对/相对路径转为 /api/evidence/{filename} 可访问 URL（v2.0 BUG-003）。

    F-01 修复：静态目录已加鉴权，此处附加 ?es_exp&es_ten&es_sig 短时效签名，
    供浏览器原生 GET（<img>）放行；签名绑定请求者租户，跨租户不可复用。
    """
    if not path:
        return ""
    name = PureWindowsPath(path).name if "\\" in path else PurePosixPath(path).name
    return sign_static_url(f"/api/evidence/{name}", tenant_id)


@router.get("/reports/{report_id}/sections")
async def get_report_sections(
    report_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """报告四节结构化：功能覆盖 / 数据流执行 / 页面·接口明细 / BUG 清单。"""
    report = db.get(Report, report_id)
    if report is None or report.deleted_at is not None:
        raise NotFoundError("ES-COMMON-0004", "报告不存在")
    _ensure_report_visible(report, auth)

    from ..models import Defect, TestCase

    content = report.content or {}

    # 1) 功能覆盖：按 module 聚合用例数 + 执行次数（对应当前项目用例）
    coverage: list[dict] = []
    qc = db.query(
        TestCase.module,
        func.count(TestCase.id).label("cnt"),
        func.sum(func.coalesce(TestCase.run_count, 0)).label("runs"),
    ).filter(
        TestCase.project_id == report.project_id, TestCase.deleted_at.is_(None)
    )
    if not auth.is_super_admin:
        qc = qc.filter(TestCase.tenant_id == auth.tenant_id)
    for m, cnt, runs in qc.group_by(TestCase.module).all():
        coverage.append({"module": m or "未分类", "case_count": int(cnt or 0), "run_count": int(runs or 0)})

    # 2) 数据流执行：报告任务步骤链摘要
    dataflow: list[dict] = []
    for step in db.query(TaskStep).filter(TaskStep.task_id == report.task_id).all():
        sm = step.result_summary or {}
        dataflow.append({
            "engine": step.engine_name or step.engine_code,
            "status": step.status or sm.get("status", ""),
            "summary": sm,
        })

    # 3) 页面·接口明细：report.content.step_details（与既有可读明细一致）
    pages = content.get("step_details") or content.get("step_results") or []

    # 4) BUG 清单：本报告关联缺陷（缺失时从 content.defects 兜底）
    #    v2.0 BUG-007：补 assignee / fix_suggestion / severity_basis / requirement_id
    bugs: list[dict] = []
    for d in db.query(Defect).filter(Defect.report_id == report.id, Defect.deleted_at.is_(None)).all():
        bugs.append({
            "id": d.id, "defect_no": d.defect_no, "title": d.title,
            "severity": d.severity, "priority": d.priority, "status": d.status,
            "module": d.module, "case_id": d.case_id, "task_id": d.task_id,
            "assignee": d.assignee_name or "",
            "fix_suggestion": d.fix_suggestion or "",
            "severity_basis": d.severity_basis or "",
            "requirement_id": d.requirement_id or f"REQ-{d.project_id}-{d.defect_no}",
            "reproduce_steps": d.reproduce_steps or [],
        })
    if not bugs and isinstance(content.get("defects"), list):
        bugs = [dict(x) for x in content["defects"] if isinstance(x, dict)]

    # 5) v2.0 失败明细区块（BUG-003/004/006）：从 step_details 提取 FAIL 用例
    failures: list[dict] = []
    screenshots: list[dict] = []
    reproduction: list[dict] = []
    # 批量取失败用例的步骤（复现步骤用）
    case_ids = {
        g.get("case_id")
        for step in (pages if isinstance(pages, list) else [])
        if isinstance(step, dict)
        for g in (step.get("details") or {}).get("results") or []
        if isinstance(g, dict) and str(g.get("result") or "").upper() != "PASS" and g.get("case_id")
    }
    case_steps_map: dict[Any, list] = {}
    if case_ids:
        for tc in db.query(TestCase).filter(TestCase.id.in_(list(case_ids))).all():
            case_steps_map[tc.id] = tc.steps or []
    for step in pages if isinstance(pages, list) else []:
        if not isinstance(step, dict):
            continue
        for g in (step.get("details") or {}).get("results") or []:
            if not isinstance(g, dict):
                continue
            _res = str(g.get("result") or "").upper()
            # 失败明细口径与风险判定（total-passed）一致：FAIL 或 SKIP 但带 failures
            if _res == "PASS" or (not g.get("failures") and _res not in ("FAIL", "ERROR")):
                continue
            shot = g.get("screenshot") or ""
            shot_url = _evidence_url(shot, auth.tenant_id)
            failure_detail = {
                "case_no": g.get("case_no"),
                "title": g.get("title"),
                "failures": g.get("failures") or [],
                "http_status": g.get("status_code"),
                "response_preview": g.get("response_preview"),
                "request": g.get("request") or {},
                "response": g.get("response") or {},
                "traceback": g.get("traceback") or "",
                "trace_id": g.get("trace_id") or "",
                "request_id": g.get("request_id") or "",
                "timestamp": g.get("timestamp") or "",
                "duration_ms": g.get("duration_ms"),
            }
            failures.append({
                "case_id": g.get("case_id"),
                "case_no": g.get("case_no"),
                "title": g.get("title"),
                "engine": step.get("engine"),
                "failure_detail": failure_detail,
                "screenshots": ([{"case_id": g.get("case_id"), "path": shot, "url": shot_url}] if shot else []),
            })
            if shot:
                screenshots.append({"case_id": g.get("case_id"), "path": shot, "url": shot_url})
            # 复现步骤（BUG-004）：由用例 steps + 失败断言生成人工可照做步骤
            steps_raw = case_steps_map.get(g.get("case_id")) or g.get("steps") or []
            fail_msgs = [str(x) for x in (g.get("failures") or [])]
            repro_steps = []
            for i, s in enumerate(steps_raw or [], 1):
                if isinstance(s, dict):
                    repro_steps.append({
                        "no": i,
                        "action": f"{s.get('action', '')} {s.get('target', '')}".strip(),
                        "expected": s.get("value") or s.get("expected") or "",
                        "actual": fail_msgs[i - 1] if i - 1 < len(fail_msgs) else "通过",
                    })
            if repro_steps:
                reproduction.append({
                    "case_id": g.get("case_id"),
                    "case_no": g.get("case_no"),
                    "probability": "必现",
                    "occurrence": f"本次执行 {len(fail_msgs)} 项断言失败",
                    "steps": repro_steps,
                })

    return {"code": 0, "data": {"sections": [
        {"key": "coverage", "title": "功能覆盖", "items": coverage},
        {"key": "dataflow", "title": "数据流执行", "items": dataflow},
        {"key": "pages", "title": "页面/接口明细", "items": pages},
        {"key": "bugs", "title": "BUG 清单", "items": bugs},
        {"key": "failures", "title": "失败明细", "items": failures},
        {"key": "screenshots", "title": "失败截图", "items": screenshots},
        {"key": "reproduction", "title": "复现步骤", "items": reproduction},
    ]}, "message": "ok"}
