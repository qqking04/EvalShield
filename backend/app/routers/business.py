# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""业务路由：项目、任务（创建/执行/取消/进度）、用例、数据集、场景、评测、报告、模型网关、通知、仪表盘。

任务执行采用同步模拟调度：创建 TaskStep → EngineRegistry 执行 → 汇总 summary → 生成报告。
（真实异步执行器可在 scripts/ 中扩展为后台 worker。）
"""

from __future__ import annotations

import hashlib
import json
import csv
import io
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO

logger = logging.getLogger(__name__)

# FE-02/FE-05：需要非空 base_url 才能执行的 HTTP 类引擎（后端空串兜底校验）
_HTTP_BASED_ENGINES = {
    "API_TEST",
    "UI_TEST",
    "DATAFLOW_TEST",
    "PERF_TEST",
    "LOCUST_PERF",
    "PRIVILEGE_ESCALATION",
    "SELF_HEAL",
}

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import String, case, cast, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    AuthContext,
    authenticate_request,
    ensure_data_scope,
    require_permission,
)
from ..engines import EngineContext, engine_registry, run_engine_step
from ..engines.registry import discover_engines
from ..errors import BizError, NotFoundError
from ..limits import COMMUNITY_LIMITS, check_limit, check_upload_bytes
from ..services.audit import write_audit
from ..services.report_sections import (
    cn_no,
    compliance_conclusion,
    next_section_no,
    redteam_sections,
    security_sections,
)
from ..models import (
    AuditLog,
    BillingPlan,
    BillingQuota,
    BillingTopUp,
    ComplianceClause,
    DataDict,
    DictItem,
    EvalRun,
    EvalSet,
    ModelConfig,
    ModelGatewayRecord,
    Notification,
    Project,
    ProjectMembers,
    Report,
    ReportComplianceAlignment,
    Scenario,
    SystemUser,
    TaskArtifact,
    TaskStep,
    TestCase,
    TestDataset,
    TestEngine,
    TestTask,
)
from ..schemas import (
    CaseCreate,
    CaseOut,
    CaseUpdate,
    DatasetCreate,
    DatasetGenerateRequest,
    DatasetOut,
    EvalRunCreate,
    EvalRunOut,
    EvalSetCreate,
    EngineOut,
    ModelConfigCreate,
    ModelConfigTestRequest,
    ModelConfigUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    ScenarioCreate,
    StepOut,
    TaskCreate,
    TaskOut,
    TaskRunRequest,
    VALID_CASE_CATEGORIES,
)
from ..services.llm_client import test_connection as llm_test_connection
from ..services.scheduler import next_run_at
from ..services.task_runner import is_running, launch_task_async
from ..utils.compat import run_cmd
from ..utils.cron import parse_cron
from ..utils.no import gen_no


router = APIRouter()
from . import models_gateway_core
from ._business_common import *  # noqa: F401,F403

# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
@router.get("/reports", response_model=dict)
async def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    task_id: int | None = None,
    project_id: int | None = None,
    report_type: str | None = None,
    test_type: str | None = Query(None, description="P1-15 按测试维度筛选：功能测试/UI 测试/性能测试/安全测试/数据流/兼容性"),
    task_no: str | None = None,
    source: str | None = None,
    status_filter: str | None = Query(None, alias="status", description="按报告状态筛选；支持逗号分隔多值（如 GENERATING,RUNNING 同义并集）"),
    start_time: str | None = None,
    end_time: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    q = db.query(Report).filter(Report.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(Report.tenant_id == auth.tenant_id)
    if task_id:
        q = q.filter(Report.task_id == task_id)
    if project_id:
        q = q.filter(Report.project_id == project_id)
    if report_type:
        q = q.filter(Report.report_type == report_type)
    if test_type:
        # P1-15：reports.summary 为 JSON 类型，cast 成 JSONB 后按 ->'dimension_stats' ? key 判定
        ds = cast(Report.summary, JSONB)["dimension_stats"]
        q = q.filter(ds.has_key(test_type))  # noqa: W601 -> JSONB -> ? 存在性判定
    if task_no:
        q = q.filter(Report.task_no == task_no)
    if status_filter:
        vals = [s.strip() for s in status_filter.split(",") if s.strip()]
        if vals:
            q = q.filter(Report.status.in_(vals))
    if source:
        # P2-09：按来源筛选（如 AGENT_GEN）——取本项目下含该来源用例的报告
        proj_ids = [
            row[0]
            for row in db.query(TestCase.project_id)
            .filter(TestCase.source == source, TestCase.deleted_at.is_(None))
            .distinct()
            .all()
        ]
        q = q.filter(Report.project_id.in_(proj_ids)) if proj_ids else q.filter(Report.id < 0)
    if start_time:
        try:
            st = datetime.fromisoformat(start_time)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="start_time 格式错误，请使用 ISO 8601 格式")
        q = q.filter(Report.created_at >= st)
    if end_time:
        try:
            et = datetime.fromisoformat(end_time)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="end_time 格式错误，请使用 ISO 8601 格式")
        q = q.filter(Report.created_at <= et)
    total = q.count()
    rows = (
        q.order_by(Report.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "id": r.id,
            "report_no": r.report_no,
            "task_no": r.task_no,
            "project_id": r.project_id,
            "title": r.title,
            "report_type": r.report_type,
            "format": r.format,
            "status": r.status,
            "file_size": r.file_size,
            "summary": r.summary,
            "risk_level": getattr(r, "risk_level", None) or "none",
            "risk_basis": getattr(r, "risk_basis", None) or "",
            "generated_at": r.generated_at,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": items, "total": total, "page": page, "page_size": page_size},
    }


def _review_view(db: Session, task_id: int | None) -> dict:
    """ES8 M6：报告详情的复核徽标视图。

    返回 {"runs":[{run_id, reviewable, items:{item_index: 复核摘要}}]}；
    reviewable=True 表示该 task 存在自动创建的 EvalRun 且逐项可定位
    （前端仅对报告明细与本 run items 同序的表展示徽标/标记按钮）。
    """
    import json as _json

    from ..models import EvalRun, ReviewItem

    empty = {"runs": [], "reviewable": False}
    if not task_id:
        return empty
    runs = db.query(EvalRun).filter(EvalRun.task_id == task_id).all()
    if not runs:
        return empty
    run_ids = {r.id for r in runs}
    by_run: dict[int, dict[int, dict]] = {r.id: {} for r in runs}
    from sqlalchemy import or_

    # source_ref 为 sort_keys 紧凑 JSON（{"item_index":N, "run_id":R}，run_id 恒为尾键），
    # 用「"run_id": R}」锚定 LIKE 粗筛避免全表扫描；精确解析比对仍在 Python 侧完成
    conds = [ReviewItem.source_ref.like(f'%"run_id": {rid}}}') for rid in run_ids]
    rows = (
        db.query(ReviewItem)
        .filter(ReviewItem.source == "run_item", or_(*conds))
        .order_by(ReviewItem.id.desc())
        .all()
    )
    for it in rows:  # 同 (run,idx) 多条历史时取 id 最大（新条目覆盖旧）
        try:
            ref = _json.loads(it.source_ref or "{}")
        except (TypeError, ValueError):
            continue
        rid, idx = ref.get("run_id"), ref.get("item_index")
        if rid in run_ids and isinstance(idx, int):
            by_run[rid].setdefault(idx, {
                "review_id": it.id,
                "status": it.status,
                "human_verdict": it.human_verdict,
                "auto_confidence": it.auto_confidence,
            })
    return {
        "runs": [
            {"run_id": r.id, "run_no": r.run_no, "items": by_run[r.id]}
            for r in runs
        ],
        "reviewable": True,
    }


@router.get("/reports/{report_id}", response_model=dict)
async def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    r = db.get(Report, report_id)
    if r is None or r.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0009", "报告不存在")
    await ensure_data_scope(auth, resource_tenant_id=r.tenant_id)

    # 兜底：报告 summary 全 0 时，从关联 TaskStep 重新聚合（历史报告/异常分支补全后）
    summary = r.summary or {}
    _t = int(summary.get("total") or 0)
    _p = int(summary.get("passed") or 0)
    _f = int(summary.get("failed") or 0)
    if _t == 0 and _p == 0 and _f == 0:
        from ..models import TaskStep
        t2 = p2 = f2 = 0
        for step in db.query(TaskStep).filter(TaskStep.task_id == r.task_id).all():
            sm = step.result_summary or {}
            t2 += int(sm.get("total") or 0)
            p2 += int(sm.get("passed") or 0)
            f2 += int(sm.get("failed") or 0)
        if t2 > 0 or p2 > 0 or f2 > 0:
            summary = {
                **summary,
                "total": t2, "passed": p2, "failed": f2,
                "pass_rate": round(p2 / t2, 4) if t2 > 0 else 0.0,
            }

    # ES8 M5：门禁徽章（报告详情头部用；关联任务不存在时给空视图）
    from ..models import TestTask
    from ..services.quality_gate import gate_view

    _task = db.get(TestTask, r.task_id)
    # ES8 M6：复核状态徽标（按 task 反查 EvalRun 与 review_items；
    # source_ref 是 TEXT 存 JSON，Python 侧解析比对，避免 SQL JSON 匹配）
    review_view = _review_view(db, r.task_id)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "id": r.id,
            "report_no": r.report_no,
            "task_no": r.task_no,
            "project_id": r.project_id,
            "title": r.title,
            "report_type": r.report_type,
            "format": r.format,
            "status": r.status,
            "content": r.content,
            "summary": summary,
            "environment": getattr(r, "environment", None) or {},
            "risk_level": getattr(r, "risk_level", None) or "none",
            "risk_basis": getattr(r, "risk_basis", None) or "",
            "file_path": getattr(r, "file_path", None),
            "file_size": getattr(r, "file_size", None),
            "generated_at": r.generated_at,
            "gate": gate_view(_task) if _task is not None else {"enabled": False, "verdict": None, "rules": []},
            "review": review_view,
            # ES10-P-01/P-02：报告口径「事实基准」「项目版本」提升到顶层（content 注入见 task_runner.build_report）
            "fact_source": (r.content or {}).get("fact_source"),
            "project_version": (r.content or {}).get("project_version"),
        },
    }


@router.get("/reports/{report_id}/export", response_model=dict)
async def export_report(
    report_id: int,
    request: Request,
    format: str = Query("json", pattern="^(word|pdf|json|md|html|compliance_package)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("report", "export")),
):
    """报告导出：pdf / json / md / compliance_package（ZIP 自证包）。"""
    r = db.get(Report, report_id)
    if r is None or r.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0009", "报告不存在")
    await ensure_data_scope(auth, resource_tenant_id=r.tenant_id)

    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="report.export",
        module="report",
        request=request,
        result="SUCCESS",
        detail=f"导出报告 {r.report_no}（{r.title}），格式 {format}",
    )

    payload = r.content or {}

    if format == "json":
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        return StreamingResponse(
            iter([content.encode("utf-8")]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={r.report_no}.json"},
        )

    if format == "md":
        md = _render_markdown(r, payload)
        return StreamingResponse(
            iter([md.encode("utf-8")]),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={r.report_no}.md"},
        )

    if format == "html":
        html_text = _render_html(r, payload)
        return StreamingResponse(
            iter([html_text.encode("utf-8")]),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={r.report_no}.html"},
        )

    if format == "pdf":
        pdf = _render_pdf(r, payload, cost_data=_report_cost_data(db, r))
        return StreamingResponse(
            iter([pdf]),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={r.report_no}.pdf"},
        )

    if format == "word":
        try:
            from docx import Document
            from docx.shared import Pt, Inches
            doc = Document()
            doc.add_heading(f"EvalShield 测试报告 {r.report_no}", level=0)
            # TC-U6-02：Report 模型无 project_name 字段，项目编号取 payload.project_code
            doc.add_paragraph(
                f"项目编号: {payload.get('project_code') or '-'}  "
                f"生成日期: {_fmt_gen_date(payload.get('generated_at') or r.created_at)}"
            )
            # TC-U15-13：执行摘要改为「用例执行概览」并以「指标名称 | 数值」表呈现
            doc.add_heading("用例执行概览", level=1)
            s = payload.get("summary", {})
            _p0, _p1 = _p0_p1_counts(payload)
            overview = doc.add_table(rows=1, cols=2)
            _oh = overview.rows[0].cells
            _oh[0].text = "指标名称"; _oh[1].text = "数值"
            for _name, _val in [
                ("总数", str(s.get("total", 0))),
                ("通过", str(s.get("passed", 0))),
                ("失败", str(s.get("failed", 0))),
                ("通过率", f"{(s.get('pass_rate', 0) * 100):.1f}%"),
                ("P0级问题数", str(_p0)),
                ("P1级问题数", str(_p1)),
            ]:
                _oc = overview.add_row().cells
                _oc[0].text = _name; _oc[1].text = _val
            # TC-U15-08：「评测执行记录」——补「用例编号」「评测结果」列；
            # 兼容真实嵌套结构（details.results[].assertion_details）与简化结构（sd.assertions）
            doc.add_heading("评测执行记录", level=1)
            tbl = doc.add_table(rows=1, cols=7)
            hdr = tbl.rows[0].cells
            for _ci, _cn in enumerate(["用例编号", "断言", "路径", "操作", "期望", "实际", "评测结果"]):
                hdr[_ci].text = _cn
            for sd in payload.get("step_details", []) or []:
                _items: list[tuple[str, dict, str]] = []
                _det = sd.get("details") or {}
                for c in (_det.get("results") or []):
                    for a in (c.get("assertion_details") or []):
                        _items.append((str(c.get("case_no") or "-"), a, str(c.get("title") or "")))
                if not _items:
                    for a in (sd.get("assertions") or []):
                        _items.append((str(sd.get("case_no") or sd.get("title") or "-"), a, str(sd.get("title") or "")))
                for _case_no, a, _title in _items:
                    row = tbl.add_row().cells
                    row[0].text = _case_no[:40]
                    row[1].text = _title[:40]
                    row[2].text = str(a.get("path", ""))[:40]
                    row[3].text = str(a.get("op", ""))
                    row[4].text = str(a.get("expected", ""))[:40]
                    row[5].text = str(a.get("actual", ""))[:40]
                    row[6].text = "通过" if _assert_verdict(a) == "PASS" else "不通过"
            # TC-U6-02（v5 纠偏）：与 MD/HTML/PDF 同源注入「四、合规结论」章节。
            # compliance_conclusion() 返回 Markdown 行，此处按行型映射为 Word 元素：
            # "## "→一级标题、"### "→二级标题、"| "→表格、"- "→列表段落、其余→正文。
            # W4：映射循环抽为 _emit_md 闭包，合规结论与越狱/PII 专节共用。
            def _emit_md(md_lines: list[str]):
                table_buf: list[list[str]] = []

                def _flush_table():
                    if not table_buf:
                        return
                    width = max(len(r_) for r_ in table_buf)
                    wtbl = doc.add_table(rows=0, cols=width)
                    for ri, row_cells in enumerate(table_buf):
                        cells = wtbl.add_row().cells
                        for ci in range(width):
                            cells[ci].text = (row_cells[ci] if ci < len(row_cells) else "").replace("**", "")
                        if ri == 0:
                            for ci in range(width):
                                for p_ in cells[ci].paragraphs:
                                    for run_ in p_.runs:
                                        run_.bold = True
                    table_buf.clear()

                for line in md_lines:
                    if line.startswith("|"):
                        cells = [c.strip() for c in line.strip().strip("|").split("|")]
                        if cells and set("".join(cells)) <= set("-: "):
                            continue  # Markdown 表格分隔行
                        table_buf.append(cells)
                        continue
                    _flush_table()
                    text = line.replace("**", "")
                    if line.startswith("## "):
                        doc.add_heading(text[3:], level=1)
                    elif line.startswith("### "):
                        doc.add_heading(text[4:], level=2)
                    elif line.startswith("- "):
                        doc.add_paragraph(text[2:], style="List Bullet")
                    elif text.strip():
                        doc.add_paragraph(text)
                _flush_table()

            cc = payload.get("compliance_conclusion") or {}
            if cc:
                _emit_md(compliance_conclusion(cc))
            _sec_lines = security_sections(payload.get("step_details") or [])
            if _sec_lines:
                _emit_md(_sec_lines)
            # ES8 M9：国际框架覆盖 / 防护建议两节（数据由 build_report 注入 payload）
            _emit_md(redteam_sections(payload, payload.get("step_details") or []))
            # TC-U15-11：附录（仅列 P0 级问题），与 PDF 同口径；W4：编号随专节动态顺延
            _apx_no = next_section_no(payload.get("step_details") or [], payload)
            doc.add_heading(f"{cn_no(_apx_no)}、附录（P0 级问题）", level=1)
            atbl = doc.add_table(rows=1, cols=4)
            _ah = atbl.rows[0].cells
            for _ci, _cn in enumerate(["用例编号", "来源引擎", "严重度", "说明"]):
                _ah[_ci].text = _cn
            for _row in _appendix_rows(payload):
                _ac = atbl.add_row().cells
                for _ci, _cv in enumerate(_row):
                    _ac[_ci].text = _cv
            # TC-U15-13：成本分析（services.cost 聚合口径；无数据则省略；W4：编号动态顺延）
            cost_data = _report_cost_data(db, r)
            if cost_data:
                doc.add_heading(f"{cn_no(_apx_no + 1)}、成本分析", level=1)
                ctbl = doc.add_table(rows=1, cols=2)
                _ch = ctbl.rows[0].cells
                _ch[0].text = "指标名称"; _ch[1].text = "数值"
                for _name, _val in _cost_metric_rows(cost_data):
                    _cc = ctbl.add_row().cells
                    _cc[0].text = _name; _cc[1].text = _val
                doc.add_heading("分模型明细", level=2)
                mtbl = doc.add_table(rows=1, cols=7)
                _mh = mtbl.rows[0].cells
                for _ci, _cn in enumerate(
                    ["模型", "模型编码", "总Token", "成本(元)", "调用次数", "平均延迟(ms)", "缓存命中率(%)"]
                ):
                    _mh[_ci].text = _cn
                for _row in _cost_model_rows(cost_data):
                    _mc = mtbl.add_row().cells
                    for _ci, _cv in enumerate(_row):
                        _mc[_ci].text = _cv
            buf = BytesIO()
            doc.save(buf); buf.seek(0)
            return StreamingResponse(iter([buf.read()]),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f"attachment; filename={r.report_no}.docx"}, )
        except ImportError:
            raise BizError("ES-BIZ-0010", "python-docx 未安装，Word 导出不可用")
        except Exception as e:  # noqa: BLE001
            # step_details 缺失等容错 — 输出最小化 doc（记录日志便于排障，不再静默吞错）
            logger.warning("Word 导出渲染异常，降级为最小化文档: %s", e, exc_info=True)
            fallback = Document()
            fallback.add_heading(f"EvalShield 测试报告 {r.report_no}", level=0)
            fallback.add_paragraph(f"(报告明细生成异常: {str(e)[:120]})")
            buf = BytesIO(); fallback.save(buf); buf.seek(0)
            return StreamingResponse(iter([buf.read()]),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f"attachment; filename={r.report_no}.docx"}, )

    # ---- compliance_package：ZIP 自证包 ----
    # 企业能力位闸门：合规自证包属 compliance_package 能力（规划 §12.4）
    from ..enterprise.features import feature_enabled as _feature_enabled

    if not _feature_enabled("compliance_package"):
        raise BizError(
            "ES-LIC-0003",
            "合规自证包为企业版能力（compliance_package），请先激活含该能力的 License",
            http_status=403,
        )
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1) PDF 主报告
        pdf_bytes = _render_pdf(r, payload, cost_data=_report_cost_data(db, r))
        zf.writestr("compliance_report.pdf", pdf_bytes)

        # 2) 审计轨迹 JSON
        # write_audit 将 detail（含报告编号）写入 request_body.detail；
        # AuditLog 无 ref_no 字段，这里按 JSON 序列化文本包含报告编号过滤。
        audit_logs = (
            db.query(AuditLog)
            .filter(
                AuditLog.tenant_id == r.tenant_id,
                cast(AuditLog.request_body, String).contains(r.report_no),
            )
            .order_by(AuditLog.created_at)
            .all()
        )
        audit_data = [
            {
                "log_no": a.log_no,
                "action": a.action,
                "module": a.module,
                "result": a.result,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in audit_logs
        ]
        zf.writestr(
            "audit_trail.json", json.dumps(audit_data, ensure_ascii=False, indent=2)
        )

        # 3) 链签名文件
        sig_payload = {
            "report_no": r.report_no,
            "task_no": r.task_no,
            "generated_at": payload.get("generated_at", ""),
            "sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest(),
            "signed_at": datetime.now(timezone.utc).isoformat(),
        }
        zf.writestr(
            "chain_signature.txt", json.dumps(sig_payload, ensure_ascii=False, indent=2)
        )

        # 4) evidence/ 目录：收集关联的 TaskArtifact
        alignments = payload.get("compliance_alignment") or []
        all_refs: set[str] = set()
        for item in alignments:
            all_refs.update(item.get("evidence_refs", []))

        evidence_files: list[str] = []
        if all_refs:
            artifacts = (
                db.query(TaskArtifact)
                .filter(
                    TaskArtifact.task_id == r.task_id,
                    TaskArtifact.artifact_no.in_(list(all_refs)),
                    TaskArtifact.deleted_at.is_(None),
                )
                .all()
            )
            for art in artifacts:
                file_name = f"evidence/{art.artifact_no}.{art.file_name.split('.')[-1] if '.' in art.file_name else 'txt'}"
                try:
                    with open(art.file_path, "rb") as f:
                        zf.writestr(file_name, f.read())
                except Exception:
                    zf.writestr(
                        f"evidence/{art.artifact_no}.placeholder.txt",
                        json.dumps({"artifact_no": art.artifact_no, "note": "原始证据文件不可读"}, ensure_ascii=False),
                    )
                evidence_files.append(file_name)

        # 5) v2.0 TC-008：manifest 清单（包内容自证）
        manifest = {
            "manifest_version": "1.0",
            "report_no": r.report_no,
            "task_no": r.task_no,
            "title": r.title,
            "generated_at": payload.get("generated_at", ""),
            "packaged_at": datetime.now(timezone.utc).isoformat(),
            "files": [
                {"name": "compliance_report.pdf", "desc": "合规主报告（PDF）"},
                {"name": "audit_trail.json", "desc": "审计轨迹"},
                {"name": "chain_signature.txt", "desc": "链签名（SHA-256）"},
            ] + [{"name": n, "desc": "证据文件"} for n in evidence_files],
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    zip_buf.seek(0)
    zip_name = f"compliance_package_{r.report_no}_{int(datetime.now(timezone.utc).timestamp())}.zip"
    return StreamingResponse(
        iter([zip_buf.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={zip_name}"},
    )


# ---------------------------------------------------------------------------
# 模型网关（BUG-006 拆分至 models_gateway_core.router，原位聚合保持注册顺序）
# ---------------------------------------------------------------------------
router.include_router(models_gateway_core.router)


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------
@router.get("/notifications", response_model=dict)
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    is_read: bool | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    q = db.query(Notification).filter(
        Notification.user_id == auth.user_id, Notification.deleted_at.is_(None)
    )
    if is_read is not None:
        q = q.filter(Notification.is_read == is_read)
    total = q.count()
    rows = (
        q.order_by(Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [
                {
                    "id": n.id,
                    "notif_no": n.notif_no,
                    "title": n.title,
                    "content": n.content,
                    "notif_type": n.notif_type,
                    "ref_no": n.ref_no,
                    "is_read": n.is_read,
                    "created_at": n.created_at,
                }
                for n in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


@router.post("/notifications/{notif_id}/read", response_model=dict)
async def mark_notification_read(
    notif_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    n = db.get(Notification, notif_id)
    if n is None or n.user_id != auth.user_id:
        raise NotFoundError("ES-BIZ-0011", "通知不存在")
    n.is_read = True
    n.read_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


# ---------------------------------------------------------------------------
# 报告（补：按报告编号查询 / 删除）
# ---------------------------------------------------------------------------
@router.get("/reports/by-no/{report_no}", response_model=dict)
async def get_report_by_no(
    report_no: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    r = (
        db.query(Report)
        .filter(Report.report_no == report_no, Report.deleted_at.is_(None))
        .first()
    )
    if r is None:
        raise NotFoundError("ES-BIZ-0009", "报告不存在")
    await ensure_data_scope(auth, resource_tenant_id=r.tenant_id)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "id": r.id,
            "report_no": r.report_no,
            "task_no": r.task_no,
            "project_id": r.project_id,
            "title": r.title,
            "report_type": r.report_type,
            "format": r.format,
            "status": r.status,
            "content": r.content,
            "summary": r.summary,
            "generated_at": r.generated_at,
        },
    }


@router.delete("/reports/{report_id}", response_model=dict)
async def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    r = db.get(Report, report_id)
    if r is None or r.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0009", "报告不存在")
    await ensure_data_scope(auth, resource_tenant_id=r.tenant_id)
    r.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.post("/reports/batch-delete", response_model=dict)
async def batch_delete_reports(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """D-DEL-07：批量删除报告（软删）。"""
    ids = [int(x) for x in (body.get("ids") or [])]
    if not ids:
        return {"code": 0, "message": "ok", "data": {"deleted": 0, "skipped": 0, "not_found": []}}
    now = datetime.now(timezone.utc)
    deleted = skipped = 0
    not_found: list[int] = []
    for rid in ids:
        r = db.get(Report, rid)
        if r is None or r.deleted_at is not None:
            not_found.append(rid); continue
        if r.tenant_id != auth.tenant_id:
            skipped += 1; continue
        r.deleted_at = now; deleted += 1
    db.commit()
    return {"code": 0, "message": "ok",
            "data": {"deleted": deleted, "skipped": skipped, "not_found": not_found}}


# ---------------------------------------------------------------------------
# 通知（补：全部已读 / 删除）
# ---------------------------------------------------------------------------
@router.post("/notifications/read-all", response_model=dict)
async def read_all_notifications(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    now = datetime.now(timezone.utc)
    updated = (
        db.query(Notification)
        .filter(
            Notification.user_id == auth.user_id,
            Notification.is_read == False,  # noqa: E712
            Notification.deleted_at.is_(None),
        )
        .update({"is_read": True, "read_at": now}, synchronize_session=False)
    )
    db.commit()
    return {"code": 0, "message": "ok", "data": {"updated": updated}}


@router.delete("/notifications/{notif_id}", response_model=dict)
async def delete_notification(
    notif_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    n = db.get(Notification, notif_id)
    if n is None or n.deleted_at is not None or n.user_id != auth.user_id:
        raise NotFoundError("ES-BIZ-0011", "通知不存在")
    n.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"code": 0, "message": "ok", "data": None}


# ---- 计费套餐（admin 管理） ----

@router.get("/billing/plans", response_model=dict)
async def list_billing_plans(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """计费套餐列表：普通用户仅看 ACTIVE，admin 看全部。"""
    q = db.query(BillingPlan).filter(BillingPlan.deleted_at.is_(None))
    if _is_admin_ctx(auth):
        pass  # admin 可看全部
    else:
        q = q.filter(BillingPlan.status == "ACTIVE")
    rows = q.order_by(BillingPlan.price_monthly.asc()).all()
    items = [
        {
            "id": p.id,
            "code": p.code,
            "name": p.name,
            "description": p.description,
            "price_monthly": p.price_monthly,
            "credits": p.credits,
            "max_tasks": p.max_tasks,
            "features": p.features,
            "status": p.status,
            "tenant_id": p.tenant_id,
        }
        for p in rows
    ]
    return {"code": 0, "message": "ok", "data": items}


@router.post("/billing/plans", response_model=dict)
async def create_billing_plan(
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """创建计费套餐（仅 admin）。"""
    if not _is_admin_ctx(auth):
        raise BizError("ES-PERM-0001", "仅管理员可创建计费套餐", http_status=403)

    code = (body.get("code") or "").strip()
    if not code:
        raise BizError("ES-BIZ-0025", "套餐编码不能为空")
    existing = db.query(BillingPlan).filter(BillingPlan.code == code).first()
    if existing is not None:
        raise BizError("ES-BIZ-0026", f"套餐编码 {code} 已存在")

    plan = BillingPlan(
        code=code,
        name=body.get("name") or code,
        description=body.get("description"),
        price_monthly=float(body.get("price_monthly") or 0.0),
        credits=float(body.get("credits") or 0.0),
        max_tasks=body.get("max_tasks"),
        features=body.get("features") or [],
        status=body.get("status") or "ACTIVE",
        created_by=auth.user_id,
        tenant_id=auth.tenant_id,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="CREATE",
        module="BILLING_PLAN",
        result="SUCCESS",
        detail=f"创建计费套餐 plan_id={plan.id} code={plan.code}",
    )
    return {"code": 0, "message": "ok", "data": {"id": plan.id, "code": plan.code}}


@router.put("/billing/plans/{plan_id}", response_model=dict)
async def update_billing_plan(
    plan_id: int,
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """更新计费套餐（仅 admin）。"""
    if not _is_admin_ctx(auth):
        raise BizError("ES-PERM-0001", "仅管理员可更新计费套餐", http_status=403)

    p = db.get(BillingPlan, plan_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0027", "计费套餐不存在")

    # code 变更需唯一性校验
    if body.get("code") and body["code"] != p.code:
        dup = db.query(BillingPlan).filter(BillingPlan.code == body["code"]).first()
        if dup is not None:
            raise BizError("ES-BIZ-0026", f"套餐编码 {body['code']} 已存在")
        p.code = body["code"]

    updatable = (
        "name",
        "description",
        "price_monthly",
        "credits",
        "max_tasks",
        "features",
        "status",
    )
    for k in updatable:
        if k in body and body[k] is not None:
            setattr(p, k, body[k])

    p.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(p)

    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="UPDATE",
        module="BILLING_PLAN",
        result="SUCCESS",
        detail=f"更新计费套餐 plan_id={plan_id}",
    )
    return {"code": 0, "message": "ok", "data": {"id": p.id, "code": p.code}}


@router.delete("/billing/plans/{plan_id}", response_model=dict)
async def delete_billing_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """软删除计费套餐（仅 admin，同时停用）。"""
    if not _is_admin_ctx(auth):
        raise BizError("ES-PERM-0001", "仅管理员可删除计费套餐", http_status=403)

    p = db.get(BillingPlan, plan_id)
    if p is None or p.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0027", "计费套餐不存在")

    now = datetime.now(timezone.utc)
    p.deleted_at = now
    p.status = "DISABLED"
    p.updated_at = now
    db.commit()

    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="DELETE",
        module="BILLING_PLAN",
        result="SUCCESS",
        detail=f"软删除计费套餐 plan_id={plan_id}",
    )
    return {"code": 0, "message": "ok", "data": None}


# ---- 充值申请 ----

@router.post("/billing/topup", response_model=dict)
async def apply_top_up(
    body: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """申请充值。

    规则：
    - 必须至少填 plan_id 或 amount 之一；
    - plan_id 存在时自动取套餐 price_monthly/credits 作为 amount/credits_add 兜底；
    - admin 可直接 SUCCESS 并累加 billing_quotas.credits；
    - 普通用户创建 PENDING，需 admin 审核；
    """
    now = datetime.now(timezone.utc)
    plan_id = body.get("plan_id")
    amount = body.get("amount")
    remark = body.get("remark")

    # 至少一个
    if plan_id is None and amount is None:
        raise BizError("ES-BIZ-0028", "必须填写 plan_id 或 amount 之一")

    credits_add = float(body.get("credits_add") or 0.0)

    # 解析 plan 引用
    plan = None
    if plan_id is not None:
        plan = db.get(BillingPlan, int(plan_id))
        if plan is None or plan.deleted_at is not None:
            raise NotFoundError("ES-BIZ-0029", "所选套餐不存在")

    # 兜底：从套餐推导
    if amount is None and plan is not None:
        amount = plan.price_monthly
    if credits_add == 0.0 and plan is not None:
        credits_add = plan.credits
    if amount is None:
        amount = 0.0

    code = f"TOP-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"

    topup = BillingTopUp(
        code=code,
        user_id=auth.user_id,
        plan_id=int(plan_id) if plan_id is not None else None,
        amount=float(amount),
        credits_add=float(credits_add),
        status="PENDING",
        channel=body.get("channel") or "USER",
        remark=remark,
    )

    # admin 直接审核通过
    if _is_admin_ctx(auth):
        topup.status = "SUCCESS"
        topup.channel = body.get("channel") or "ADMIN"

        # 累加 credits 到 BillingQuota（按租户）
        quota = db.query(BillingQuota).filter(
            BillingQuota.tenant_id == auth.tenant_id
        ).first()
        if quota is None:
            quota = BillingQuota(tenant_id=auth.tenant_id)
            db.add(quota)
            db.flush()
        quota.credits = float(quota.credits or 0.0) + float(credits_add)
        quota.updated_at = now

    db.add(topup)
    db.commit()
    db.refresh(topup)

    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="APPLY",
        module="BILLING_TOPUP",
        result="SUCCESS",
        detail=f"充值申请 code={code} amount={amount} credits_add={credits_add} status={topup.status}",
    )

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "code": topup.code,
            "status": topup.status,
            "amount": topup.amount,
            "credits_add": topup.credits_add,
        },
    }


@router.get("/billing/topups", response_model=dict)
async def list_top_ups(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    start_time: str | None = None,
    end_time: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """充值历史（当前用户；admin 可查全部）。"""
    q = db.query(BillingTopUp).filter(BillingTopUp.deleted_at.is_(None))

    # 租户隔离：默认查当前用户；如需全量可放开
    q = q.filter(BillingTopUp.user_id == auth.user_id)

    if start_time:
        try:
            st = datetime.fromisoformat(start_time)
            q = q.filter(BillingTopUp.created_at >= st)
        except ValueError:
            raise BizError("ES-BIZ-0030", "start_time 格式不正确（ISO 8601）")
    if end_time:
        try:
            et = datetime.fromisoformat(end_time)
            q = q.filter(BillingTopUp.created_at <= et)
        except ValueError:
            raise BizError("ES-BIZ-0031", "end_time 格式不正确（ISO 8601）")

    total = q.count()
    rows = (
        q.order_by(BillingTopUp.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "id": t.id,
            "code": t.code,
            "user_id": t.user_id,
            "plan_id": t.plan_id,
            "amount": t.amount,
            "credits_add": t.credits_add,
            "status": t.status,
            "channel": t.channel,
            "remark": t.remark,
            "created_at": t.created_at,
        }
        for t in rows
    ]
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": items, "total": total, "page": page, "page_size": page_size},
    }


@router.post("/billing/topups/{topup_id}/approve", response_model=dict)
async def approve_top_up(
    topup_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """审核通过充值申请（仅 admin）。"""
    if not _is_admin_ctx(auth):
        raise BizError("ES-PERM-0001", "仅管理员可审核充值", http_status=403)

    t = db.get(BillingTopUp, topup_id)
    if t is None or t.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0032", "充值单不存在")
    if t.status != "PENDING":
        raise BizError("ES-BIZ-0033", f"当前状态 {t.status} 不可审核")

    now = datetime.now(timezone.utc)
    t.status = "SUCCESS"
    t.updated_at = now

    # 按充值申请人所在租户累加 quota
    user = db.get(SystemUser, t.user_id)
    tenant_id = user.tenant_id if user is not None else auth.tenant_id
    quota = db.query(BillingQuota).filter(BillingQuota.tenant_id == tenant_id).first()
    if quota is None:
        quota = BillingQuota(tenant_id=tenant_id)
        db.add(quota)
        db.flush()
    quota.credits = float(quota.credits or 0.0) + float(t.credits_add or 0.0)
    quota.updated_at = now

    db.commit()

    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="APPROVE",
        module="BILLING_TOPUP",
        result="SUCCESS",
        detail=f"审核通过 topup_id={topup_id} code={t.code} credits_add={t.credits_add}",
    )

    return {"code": 0, "message": "ok", "data": {"code": t.code, "status": t.status}}


@router.post("/billing/topups/{topup_id}/cancel", response_model=dict)
async def cancel_top_up(
    topup_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """取消充值申请（admin 或 申请人本人）。"""
    t = db.get(BillingTopUp, topup_id)
    if t is None or t.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0032", "充值单不存在")

    is_owner = t.user_id == auth.user_id
    if not (_is_admin_ctx(auth) or is_owner):
        raise BizError("ES-PERM-0001", "仅申请人或管理员可取消", http_status=403)

    if t.status not in ("PENDING",):
        raise BizError("ES-BIZ-0034", f"当前状态 {t.status} 不可取消")

    t.status = "CANCELLED"
    t.updated_at = datetime.now(timezone.utc)
    db.commit()

    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="CANCEL",
        module="BILLING_TOPUP",
        result="SUCCESS",
        detail=f"取消充值 topup_id={topup_id} code={t.code}",
    )

    return {"code": 0, "message": "ok", "data": {"code": t.code, "status": t.status}}


# ---------------------------------------------------------------------------
# G-3：模型配置用量统计（BUG-006 拆分至 models_gateway_core.stats_router）
# ---------------------------------------------------------------------------
router.include_router(models_gateway_core.stats_router)


# ---------------------------------------------------------------------------
# 字典（前端下拉框数据源）
# ---------------------------------------------------------------------------
@router.get("/dicts", response_model=dict)
async def list_dicts(
    dict_code: str | None = Query(None, description="字典编码，如 case_category"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """查询字典项（前端下拉框数据源）。"""
    q = db.query(DataDict).filter(DataDict.deleted_at.is_(None))
    if dict_code:
        # 大小写不敏感匹配：前端传的 dict_code 统一小写，DB 里历史遗留有大写/小写
        q = q.filter(func.lower(DataDict.dict_code) == dict_code.lower())
    dicts = q.all()

    # 收集所有 dict_id，一次性查 DictItem
    dict_ids = [d.id for d in dicts]
    items_by_dict: dict[int, list] = {}
    if dict_ids:
        all_items = (
            db.query(DictItem)
            .filter(DictItem.dict_id.in_(dict_ids), DictItem.deleted_at.is_(None))
            .order_by(DictItem.sort_order.asc(), DictItem.id.asc())
            .all()
        )
        for it in all_items:
            items_by_dict.setdefault(it.dict_id, []).append(it)

    if dict_code:
        if not dicts:
            return {"code": 0, "message": "ok", "data": []}
        return {
            "code": 0,
            "message": "ok",
            "data": [
                {"value": it.item_value, "label": it.item_label, "sort": it.sort_order}
                for it in items_by_dict.get(dicts[0].id, [])
            ],
        }
    return {
        "code": 0,
        "message": "ok",
        "data": [
            {
                "code": d.dict_code,
                "name": d.dict_name,
                "items": [
                    {"value": it.item_value, "label": it.item_label, "sort": it.sort_order}
                    for it in items_by_dict.get(d.id, [])
                ],
            }
            for d in dicts
        ],
    }


# ===========================================================================
# 文档导入 → AI 生成测试用例（P1-新功能）
# ===========================================================================

@router.post("/documents/import", response_model=dict)
async def import_document(
    request: Request,
    file: UploadFile,
    project_id: int = Form(...),
    module: str | None = Form(None),
    category: str = Form("FUNCTIONAL"),
    auto_run: str = Form("false"),
    engine: str = Form("EVAL_ENGINE"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """上传 PDF/DOCX/TXT 文档 → 提取文本 → AI 生成测试用例草稿 → 可选自动执行。"""
    import tempfile, os as _os, re
    from ..errors import BizError
    auto_run_flag = auto_run.lower() in ("true", "1", "yes")

    # B5：社区版附件上限（Content-Length 快速拒绝）
    check_limit("upload_size_mb", db, auth, request=request)

    # 1. 读文件
    suffix = _os.path.splitext(file.filename or "")[1].lower()
    if suffix not in (".pdf", ".docx", ".txt", ".md"):
        raise BizError("ES-BIZ-0001", "仅支持 .pdf / .docx / .txt / .md 文件")
    content = await file.read()
    check_upload_bytes(len(content))  # B5：落盘前二次校验实际字节数
    if len(content) > 5 * 1024 * 1024:
        raise BizError("ES-BIZ-0001", "文件超过 5MB，请拆分后上传")

    # 2. 解析文本
    text = ""
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            tmp = tempfile.SpooledTemporaryFile()
            tmp.write(content); tmp.seek(0)
            reader = PdfReader(tmp)
            for page in reader.pages:
                text += page.extract_text() or ""
        elif suffix == ".docx":
            from docx import Document
            tmp = tempfile.SpooledTemporaryFile()
            tmp.write(content); tmp.seek(0)
            doc = Document(tmp)
            for p in doc.paragraphs:
                text += p.text + "\n"
        else:
            text = content.decode("utf-8", errors="ignore")
    except Exception as e:
        raise BizError("ES-BIZ-0001", f"文档解析失败: {e}")

    text = text.strip()
    if len(text) < 20:
        raise BizError("ES-BIZ-0001", "文档内容过短，无法生成测试用例")

    # 3. 规则生成用例草稿（最多 20 条）
    lines = [ln.strip() for ln in re.split(r"\n{2,}", text) if ln.strip()]
    cases_created = []
    case_ids = []
    chunk_size = max(1, len(lines) // 20)
    # B5：社区版用例总量（按本次实际生成条数校验）
    _planned_cases = len(range(0, min(len(lines), chunk_size * 20), chunk_size))
    check_limit("cases_total", db, auth, n=_planned_cases)
    for i in range(0, min(len(lines), chunk_size * 20), chunk_size):
        segment = "\n".join(lines[i:i + chunk_size]).strip()[:500]
        title_line = (segment.split("\n")[0][:80] or "文档导入用例").strip()
        c = TestCase(
            case_no=f"DOC-{gen_no('C')}",
            project_id=project_id,
            title=f"[文档] {title_line}",
            module=module,
            category=category,
            severity="P1", priority="HIGH",
            precondition=segment[:200],
            expected="功能执行符合业务预期，无报错",
            steps=[{"action": "打开文档描述的功能页面", "detail": segment[:150]}],
            assertions=[{"path": "status", "op": "eq", "expected": "正常"}],
            source="DOC_IMPORT",
            owner_id=auth.user_id, creator=auth.username, tenant_id=auth.tenant_id,
        )
        db.add(c)
        cases_created.append(title_line[:50])
    db.commit()
    # 拿到刚生成的 case_ids
    new_cases = db.query(TestCase).filter(TestCase.source == "DOC_IMPORT", TestCase.project_id == project_id).order_by(TestCase.id.desc()).limit(len(cases_created)).all()
    case_ids = [c.id for c in reversed(new_cases)]

    result_extra = {"count": len(cases_created), "titles": cases_created, "chars_extracted": len(text), "auto_run": False}

    # 4. 可选：自动 AI 执行（打通到 execute_task_chain）
    if auto_run_flag and case_ids:
        eng_code = engine if engine in engine_registry.codes() else "EVAL_ENGINE"
        p = db.get(Project, project_id)
        task = TestTask(
            task_no=gen_no("TSK"),
            project_id=project_id, project_code=p.code if p else "",
            name=f"文档导入自动-{file.filename or 'doc'}",
            description=text[:500], task_type="文档导入自动",
            engines=[eng_code], config={},
            trigger_mode="MANUAL", status="PENDING",
            executor=auth.username,
            created_by=auth.user_id, created_by_name=auth.username,
            tenant_id=auth.tenant_id,
        )
        db.add(task); db.commit(); db.refresh(task)
        from ..services.task_runner import execute_task_chain
        try:
            execute_task_chain(db, task, engines=[eng_code], config={})
        except Exception as e:
            task.status = "FAILED"; task.error_msg = str(e)[:500]; db.commit()
        result_extra.update({
            "auto_run": True, "task_id": task.id, "task_no": task.task_no,
            "task_status": task.status,
        })

    return {"code": 0, "message": "ok", "data": result_extra}


# ===========================================================================
# AI 自动化：CASE_GEN → 自动建任务 → 自动执行 → 返回报告（P1-新功能）
# ===========================================================================

@router.post("/ai/automation", response_model=dict)
async def ai_automation(
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """AI 自动化：输入业务描述 → 自动生成用例 → 自动建任务 → 自动执行 → 返回报告。"""
    project_id = body.get("project_id")
    prompt = (body.get("prompt") or "").strip()
    engine = body.get("engine") or "EVAL_ENGINE"
    use_existing = bool(body.get("use_existing_cases"))
    incoming_case_ids = body.get("case_ids") or []

    if not project_id:
        raise BizError("ES-BIZ-0001", "project_id 必填")
    if not use_existing and not prompt:
        raise BizError("ES-BIZ-0001", "请输入业务功能描述（或切换到使用已有用例）")
    if use_existing and not incoming_case_ids:
        raise BizError("ES-BIZ-0001", "已选择使用已有用例，请至少勾选 1 条用例")

    p = db.get(Project, project_id)
    if p is None:
        raise NotFoundError("ES-BIZ-0001", "项目不存在")

    # 确保引擎注册表已发现（/engines 列表也用同一个 registry）
    from ..engines.registry import discover_engines as _discover
    if not engine_registry.codes():
        _discover()
    engine_code = engine if engine in engine_registry.codes() else "EVAL_ENGINE"

    # ====== 预检查：引擎必需参数校验 ======
    # DATA_QUALITY 需要 source_ref + suite；LOCUST_PERF 需要 target_host + scenario；
    # 这些引擎无法从 ai_automation 页面推断出参数 → 提前报错而不是让 FAILED 默默发生
    _eng = engine_registry.get(engine_code)
    _required_keys = []
    if _eng and getattr(_eng, "params_schema", None):
        for _pk in _eng.params_schema:
            if _pk.get("required"):
                _required_keys.append(_pk["key"])
    _pre_cfg = body.get("config") or {}
    _missing = [k for k in _required_keys if not _pre_cfg.get(k)]
    if _missing:
        raise BizError(
            "ES-BIZ-0001",
            f"引擎 {engine_code} 需要参数 {', '.join(_missing)}，当前 ai/automation 页面无法自动提供。"
            f"请改用 /tasks 页面手工传 config，或切换到 EVAL_ENGINE（规则兜底 + 本地 LLM 自动生成评测集）。",
        )

    if use_existing:
        # ====== 模式 B：使用已有用例集 ======
        case_ids = list(incoming_case_ids)
        # 权限范围校验：确保传入的 case 确实属于当前租户和项目
        valid = db.query(TestCase.id).filter(
            TestCase.id.in_(case_ids),
            TestCase.project_id == project_id,
            TestCase.deleted_at.is_(None),
            TestCase.tenant_id == auth.tenant_id if not auth.is_super_admin else True,
        ).all()
        valid_ids = [int(r[0]) for r in valid]
        if not valid_ids:
            raise BizError("ES-BIZ-0001", "所选用例不存在或无权访问")
        # B5：社区版单任务用例数上限
        _b_cfg = body.get("config") or {}
        _b_scen = _b_cfg.get("scenario_ids") or []
        check_limit("cases_per_task", db, auth, n=len(valid_ids))
        check_limit("targets_per_task", db, auth, scenario_targets=len([x for x in _b_scen if x is not None]))

        task = TestTask(
            task_no=gen_no("TSK"),
            project_id=p.id,
            project_code=p.code,
            name=f"批量执行-{len(valid_ids)}条用例",
            description=f"使用已有用例集执行，共 {len(valid_ids)} 条",
            task_type="批量执行",
            engines=[engine_code],
            config=body.get("config") or {},
            trigger_mode="MANUAL",
            status="PENDING",
            executor=auth.username,
            created_by=auth.user_id,
            created_by_name=auth.username,
            tenant_id=auth.tenant_id,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        from ..services.task_runner import execute_task_chain
        try:
            execute_task_chain(db, task, engines=[engine_code], config=body.get("config") or {}, case_ids=valid_ids)
        except Exception as e:
            task.status = "FAILED"
            task.error_msg = str(e)[:500]
            db.commit()

        steps = db.query(TaskStep).filter(TaskStep.task_id == task.id).all()
        reports = db.query(Report).filter(Report.task_id == task.id).all()
        return {
            "code": 0,
            "message": "批量执行完成",
            "data": {
                "task_id": task.id,
                "task_no": task.task_no,
                "status": task.status,
                "case_ids": valid_ids,
                "case_count": len(valid_ids),
                "step_count": len(steps),
                "report_ids": [r.id for r in reports],
                "summary": f"批量执行 {len(valid_ids)} 条用例 + 引擎 {engine_code} + 任务 {task.id} 状态 {task.status}",
            },
        }

    # ====== 模式 A：prompt 生成新用例（原逻辑） ======
    # B5：社区版 AI 生成配额（每日次数通过后即累加 + 用例总量）
    check_limit("case_gen_per_day", db, auth)
    check_limit("cases_total", db, auth, n=1)
    # Step 1: 生成一条测试用例草稿（规则兜底）
    test_case = TestCase(
        case_no=f"AI-{gen_no('C')}",
        project_id=project_id,
        title=f"[AI自动] {prompt[:60]}",
        module="AI自动生成",
        category=engine.upper() if engine else "FUNCTIONAL",
        severity="P1",
        priority="HIGH",
        precondition=f"业务描述: {prompt}",
        expected="AI 自动验证结果符合预期",
        steps=[{"action": "执行 AI 自动测试流程", "detail": prompt[:300]}],
        assertions=[{"path": "result", "op": "eq", "expected": "pass"}],
        source="AI_GEN",
        owner_id=auth.user_id,
        creator=auth.username,
        tenant_id=auth.tenant_id,
    )
    db.add(test_case)
    db.commit()
    db.refresh(test_case)

    logger.info(
        "ai_automation Mode A 进入 Step 1.5 (tenant=%d, engine=%s, prompt_len=%d)",
        auth.tenant_id, engine_code, len(prompt),
    )

    # Step 1.5: 用本地 LLM（Ollama qwen2.5:7b）根据用户 prompt 生成评测集
    # 这样评测引擎就不是拿硬编码的"单元测试"rubric 去评测用户的登录场景了
    engine_config = body.get("config") or {}
    try:
        from ..services.engine_llm import resolve_model_config, llm_generate
        model = resolve_model_config(db, {}, tenant_id=auth.tenant_id)
        if model is not None and not engine_config.get("items"):
            gen_prompt = (
                f"基于以下业务描述，生成 3 条 AI 评测样本（JSON 数组）。\n"
                f"每条包含 prompt（要让被测模型回答的问题）和 rubric（评分标准关键词列表，用中文逗号分隔）。\n"
                f"业务描述：{prompt}\n"
                f"严格输出 JSON，格式：[{{\"prompt\":\"...\", \"rubric\":\"...\"}}, ...]，不要输出任何其他文字。"
            )
            raw = llm_generate(model, prompt=gen_prompt)
            if raw:
                import re
                from ..config import settings as _settings
                m = re.search(r'\[.*\]', raw, re.DOTALL)
                if m:
                    parsed = json.loads(m.group())
                    # B5：社区版单次生成条数上限（LLM 段异常被兜底吞掉，取截断而非拒绝）
                    _gen_cap = (
                        int(COMMUNITY_LIMITS["case_gen_per_call"])
                        if _settings.EDITION == "community"
                        else 4
                    )
                    items = []
                    for i, it in enumerate(parsed[:_gen_cap], 1):
                        if isinstance(it, dict) and it.get("prompt"):
                            items.append({
                                "no": f"AI-{i:02d}",
                                "prompt": it["prompt"][:300],
                                "rubric": (it.get("rubric") or "")[:300],
                            })
                    if items:
                        engine_config = {
                            **engine_config,
                            "judge_mode": engine_config.get("judge_mode", "MODEL"),
                            "threshold": engine_config.get("threshold", 0.6),
                            "items": items,
                        }
                        logger.info(
                            "ai_automation LLM 生成 %d 条评测集 (tenant=%d, engine=%s)",
                            len(items), auth.tenant_id, engine_code,
                        )
    except Exception as _llm_err:  # noqa: BLE001
        logger.warning("ai_automation LLM 生成评测集失败（引擎将用默认 items）: %s", _llm_err)

    # Step 2: 自动建任务
    task = TestTask(
        task_no=gen_no("TSK"),
        project_id=p.id,
        project_code=p.code,
        name=f"AI自动-{prompt[:30]}",
        description=prompt[:500],
        task_type="AI自动",
        engines=[engine_code],
        config=engine_config,
        trigger_mode="MANUAL",
        status="PENDING",
        executor=auth.username,
        created_by=auth.user_id,
        created_by_name=auth.username,
        tenant_id=auth.tenant_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    case_ids = [test_case.id]

    # Step 3: 同步执行
    from ..services.task_runner import execute_task_chain
    try:
        execute_task_chain(db, task, engines=[engine_code], config=engine_config)
    except Exception as e:
        task.status = "FAILED"
        task.error_msg = str(e)[:500]
        db.commit()

    # Step 4: 返回结果
    steps = db.query(TaskStep).filter(TaskStep.task_id == task.id).all()
    reports = db.query(Report).filter(Report.task_id == task.id).all()

    return {
        "code": 0,
        "message": "AI 自动化执行完成",
        "data": {
            "task_id": task.id,
            "task_no": task.task_no,
            "status": task.status,
            "case_id": test_case.id,
            "step_count": len(steps),
            "report_ids": [r.id for r in reports],
            "summary": f"用例 {test_case.id} + 引擎 {engine_code} + 任务 {task.id} 状态 {task.status}",
        },
    }


