# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""ES11 §3.6：报告交付 2 接口（开发方案 W6）。

- GET  /api/reports/{id}/delivery-readiness：G4 检查清单，阻塞项带 {label, path}；
- POST /api/reports/{id}/freeze-conclusion：冻结结论（需 report:deliver，inti.sql §76.6
  权限种子），存在待复核时拒绝（ES11-G2-006）；冻结标记写 reports.summary._freeze
  （reports 表无 meta 列，§76 未新增，落 summary 为等价实现）；幂等。

报告内容字段只读：现库无 PUT/PATCH /reports/{id} 修改端点，冻结后天然不可改；
如后续新增报告编辑接口，须以 summary._freeze 存在为前置校验。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import AuthContext, ensure_data_scope, require_permission
from ..errors import BizError, NotFoundError, ok
from ..models import EvalRun, Report
from ..services import gate_service
from ..services.audit import write_audit

logger = logging.getLogger(__name__)
router = APIRouter()


def _load_report(db: Session, report_id: int, auth: AuthContext) -> Report:
    rep = db.get(Report, report_id)
    if rep is None or rep.deleted_at is not None:
        raise NotFoundError("ES-BIZ-REPORT-0001", "报告不存在")
    return rep


def _linked_run(db: Session, report_id: int) -> EvalRun | None:
    return (
        db.query(EvalRun)
        .filter(EvalRun.report_id == report_id, EvalRun.deleted_at.is_(None))
        .order_by(EvalRun.id.desc())
        .first()
    )


@router.get("/reports/{report_id}/delivery-readiness", response_model=dict)
async def report_delivery_readiness(
    report_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("report", "read")),
):
    """G4 交付清单（§3.6）：报告→关联运行→七项检查，阻塞项带修复入口。"""
    rep = _load_report(db, report_id, auth)
    await ensure_data_scope(auth, resource_tenant_id=rep.tenant_id)
    run = _linked_run(db, report_id)
    freeze = (rep.summary or {}).get("_freeze")
    if run is None:
        return ok({
            "report_id": int(rep.id), "run_id": None,
            "deliverable": False,
            "checklist": [{
                "code": "RUN_LINK", "status": "BLOCK",
                "reason": "报告未关联评测运行，无法执行 G4 判定",
                "action": {"label": "查看运行", "path": "/eval"},
            }],
            "freeze": freeze, "concluded": False,
        })
    await ensure_data_scope(auth, resource_tenant_id=run.tenant_id)
    g4 = gate_service.delivery_readiness(db, run, rep)
    return ok({
        "report_id": int(rep.id), "run_id": int(run.id),
        "run_no": run.run_no,
        "deliverable": g4["deliverable"],
        "checklist": g4["checklist"],
        "failure_mix": g4["failure_mix"],
        "freeze": freeze,
        "concluded": gate_service.concluded(db, run),
    })


@router.post("/reports/{report_id}/freeze-conclusion", response_model=dict)
async def freeze_conclusion(
    report_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("report", "deliver")),
):
    """冻结结论（§3.6，ES11-G2-006/G4-008）：待复核未清零一律拒绝；幂等。"""
    rep = _load_report(db, report_id, auth)
    await ensure_data_scope(auth, resource_tenant_id=rep.tenant_id)
    summary = dict(rep.summary or {})
    existing = summary.get("_freeze")
    if existing:
        return ok({**existing, "already_frozen": True})

    note = None
    run = _linked_run(db, report_id)
    if run is not None:
        await ensure_data_scope(auth, resource_tenant_id=run.tenant_id)
        prog = gate_service.review_progress(db, int(run.id))
        if prog["pending"]:
            raise BizError(
                "ES-BIZ-FREEZE-0001",
                f"存在 {prog['pending']} 条待复核项，结论不可冻结（请先完成人工复核）",
            )
    try:
        body = await request.json()
        if isinstance(body, dict):
            note = str(body.get("note") or "")[:500] or None
    except (json.JSONDecodeError, Exception):  # noqa: BLE001 空/非法 body 均按无备注
        note = None

    frozen = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "frozen_by": int(auth.user_id),
        "frozen_by_name": auth.username,
        "note": note,
    }
    summary["_freeze"] = frozen
    rep.summary = summary  # JSONB 整列重赋值触发 ORM 更新
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="report.freeze_conclusion", module="report", request=request,
        detail=f"冻结报告结论 {rep.report_no}",
    )
    db.commit()
    return ok({**frozen, "already_frozen": False,
               "g4": gate_service.delivery_readiness(db, run, rep)["deliverable"] if run else False})
