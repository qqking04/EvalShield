# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES9-P-11 交付四件套路由（设计方案 §4.3.2）。

- POST /api/reports/{run_id}/delivery-package：一键生成四件套
  （run_id = eval_runs.id；门面化收尾约束：无 target_id 的纯基座自评
  非交付级 → 422 ES-REPORT-NO-TARGET）；
- GET  /api/delivery-packages?run_id=：台账列表（含 items sha256 供页面核对）；
- GET  /api/delivery-packages/{id}/download?kind=：单件下载（限本租户包、
  文件必须位于本次生成的 delivery 目录内）。

注意：delivery_packages 无 deleted_at 列（inti.sql §69），台账不做软删。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import AuthContext, require_permission
from ..errors import BizError, NotFoundError, ok
from ..models import Defect, DefectEvent, DeliveryPackage, EvalRun, EvalRunItem
from ..services import delivery
from ..services.audit import write_audit

logger = logging.getLogger(__name__)
router = APIRouter()

_MEDIA = {
    "pdf": "application/pdf",
    "zip": "application/zip",
    "csv": "text/csv; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}


def _load_run(db: Session, run_id: int, auth: AuthContext) -> EvalRun:
    run = db.get(EvalRun, run_id)
    if run is None or run.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0009", "评测运行不存在")
    if not auth.is_super_admin and run.tenant_id != auth.tenant_id:
        raise NotFoundError("ES-BIZ-0009", "评测运行不存在")
    return run


def _pkg_out(p: DeliveryPackage) -> dict:
    return {
        "id": int(p.id),
        "run_id": int(p.run_id),
        "package_no": p.package_no,
        "items": [
            {
                "kind": it.get("kind"),
                "file_name": os.path.basename(str(it.get("file_path") or "")),
                "sha256": it.get("sha256"),
                "size": it.get("size"),
            }
            for it in (p.items or [])
        ],
        "standards_ver": p.standards_ver,
        "status": p.status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _defect_verification(db: Session, run: EvalRun) -> list[dict]:
    """ES11 §3.6：正式包 manifest 的缺陷验证记录摘要。

    来源=本运行题级项的缺陷（origin_type=RUN_ITEM），附各自最近一次
    闭环事件（VERIFIED/REOPENED/WAIVED）；无缺陷时为空列表。
    """
    item_ids = db.query(EvalRunItem.id).filter(EvalRunItem.run_id == run.id)
    defects = (
        db.query(Defect)
        .filter(
            Defect.deleted_at.is_(None),
            Defect.origin_type == "RUN_ITEM",
            Defect.origin_id.in_(item_ids),
        )
        .order_by(Defect.id)
        .all()
    )
    out: list[dict] = []
    for d in defects:
        ev = (
            db.query(DefectEvent)
            .filter(
                DefectEvent.defect_id == d.id,
                DefectEvent.event_type.in_(("VERIFIED", "REOPENED", "WAIVED")),
            )
            .order_by(DefectEvent.id.desc())
            .first()
        )
        out.append(
            {
                "defect_id": int(d.id),
                "defect_no": d.defect_no,
                "title": d.title,
                "severity": d.severity,
                "status": d.status,
                "last_event": ev.event_type if ev else None,
                "last_event_at": ev.created_at.isoformat() if ev else None,
                "last_event_by": ev.actor_name if ev else None,
            }
        )
    return out


@router.post("/reports/{run_id}/delivery-package", response_model=dict)
async def create_delivery_package(
    run_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("report", "export")),
):
    """一键生成交付四件套（技术支撑报告.pdf / 证据链包.zip / 整改建议清单.csv / 复测点列表.md）。"""
    run = _load_run(db, run_id, auth)
    # 门面化收尾（§4.2 末条）：纯基座自评无被测目标 → 非交付级，阻断出件
    if not (run.target_id or "").strip():
        raise BizError(
            "ES-REPORT-NO-TARGET",
            "该运行未指定被测目标（纯基座自评），不属交付级，禁止生成交付四件套",
            http_status=422,
        )
    # ES11 §3.6：G4 未通过只出带"草稿/未冻结"水印预览包
    from ..services import gate_service

    g4 = gate_service.delivery_readiness(db, run)
    # 优化12 §8.6-3 出包收口单点兜底：SCREENING 恒出草稿水印包——口径由运行目的
    # 决定，不由门禁偶然全绿决定（SCREENING 跳过 DIMENSION_COVERAGE/STD_THRESHOLDS
    # 两项，其余 8 项全绿时 g4.deliverable 可能为 True）。不改 gate_service 语义。
    deliverable = g4["deliverable"]
    if (run.run_purpose or "").upper() == "SCREENING":
        deliverable = False
    jh = gate_service.judge_health(db, run)
    delivery_meta = {
        "run_no": run.run_no,
        "project_version_id": run.project_version_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "defect_verification": _defect_verification(db, run),
        "manual_review": gate_service.review_progress(db, int(run.id)),
        "judge_health": jh,
        "risk_acceptance": gate_service.risk_acceptance_records(db, run.tenant_id or 1),
        "g4": {"deliverable": deliverable},
    }
    pkg = delivery.generate_package(
        db, run, created_by=auth.user_id,
        deliverable=deliverable, delivery_meta=delivery_meta,
    )
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="report.delivery_package",
        module="report",
        request=request,
        detail=f"生成交付四件套 {pkg.package_no}（run {run.run_no}）",
    )
    db.commit()
    return ok(_pkg_out(pkg))


@router.get("/delivery-packages", response_model=dict)
async def list_delivery_packages(
    run_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("report", "read")),
):
    """交付包台账（sha256 供页面核对）。"""
    q = db.query(DeliveryPackage)
    if not auth.is_super_admin:
        q = q.filter(DeliveryPackage.tenant_id == auth.tenant_id)
    if run_id:
        q = q.filter(DeliveryPackage.run_id == run_id)
    total = q.count()
    rows = (
        q.order_by(DeliveryPackage.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ok({"items": [_pkg_out(p) for p in rows], "total": total})


@router.get("/delivery-packages/{package_id}/download", response_model=None)
async def download_delivery_item(
    package_id: int,
    request: Request,
    kind: str = Query(..., pattern="^(pdf|zip|csv|md)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("report", "export")),
):
    """单件下载：文件路径只认台账记录且必须位于交付目录内（防路径逃逸）。"""
    pkg = db.get(DeliveryPackage, package_id)
    if pkg is None:
        raise NotFoundError("ES-DELIV-001", "交付包不存在")
    if not auth.is_super_admin and pkg.tenant_id != auth.tenant_id:
        raise NotFoundError("ES-DELIV-001", "交付包不存在")
    target = next(
        (it for it in (pkg.items or []) if it.get("kind") == kind), None
    )
    if not target:
        raise NotFoundError("ES-DELIV-002", f"交付包缺少 {kind} 件")
    file_path = os.path.realpath(str(target.get("file_path") or ""))
    root = os.path.realpath(settings.REPORT_DIR)
    if not file_path.startswith(root + os.sep) or not os.path.isfile(file_path):
        raise BizError("ES-DELIV-003", "交付文件缺失或路径非法（请重新生成）", http_status=410)
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="report.delivery_download",
        module="report",
        request=request,
        detail=f"下载交付件 {pkg.package_no}/{kind}",
    )
    db.commit()
    return FileResponse(
        file_path,
        media_type=_MEDIA[kind],
        filename=delivery.KINDS[kind],
    )
