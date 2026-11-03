# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""沙箱管理路由：注册镜像、查询执行状态。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..config import settings
from ..database import get_db
from ..deps import authenticate_request
from ..errors import NotFoundError
from ..models import SandboxExecution, SandboxImage, SandboxStatus
from ..services.sandbox import sandbox_client
from ..utils.no import gen_no

router = APIRouter()

# ES9-P-03：pool 模式加固项声明（compose 静态 worker 池语义，只读清单）
_POOL_HARDENING = [
    "network_mode:none",
    "read_only",
    "cap_drop:ALL",
    "no-new-privileges",
    "tmpfs:/tmp,noexec",
    "pids_limit",
    "seccomp",
    "无 docker.sock",
]


@router.post("/sandbox/execute", response_model=schemas.ApiResponse[dict[str, Any]])
async def sandbox_execute(
    req: schemas.SandboxExecuteRequest,
    db: Session = Depends(get_db),
    user=Depends(authenticate_request),
):
    """提交沙箱执行任务（backend 代理到沙箱网关）。"""
    # 本地落库记录
    execution_no = gen_no("SE")
    db_record = SandboxExecution(
        execution_no=execution_no,
        task_id=req.task_id,
        engine_code=req.engine_code,
        status=SandboxStatus.PENDING.value,
        timeout_seconds=req.timeout_seconds,
        tenant_id=user.tenant_id,
        created_by=user.user_id,
    )
    db.add(db_record)
    db.commit()
    db.refresh(db_record)

    # 调用沙箱网关
    try:
        data = sandbox_client.submit_execution(
            task_id=req.task_id,
            engine_code=req.engine_code,
            config=req.config,
            timeout_seconds=req.timeout_seconds,
            artifacts_in=req.artifacts_in,
        )
        db_record.status = SandboxStatus.RUNNING.value
        db_record.started_at = data.get("started_at")
        # ES9-P-03：执行载体标识（pool 模式=worker 实例；legacy=一次性容器 id）
        db_record.worker_id = data.get("worker_id") or data.get("sandbox_id")
        db.commit()
        return schemas.ApiResponse(data={"execution_no": execution_no, **data})
    except Exception as exc:
        db_record.status = SandboxStatus.FAILED.value
        db_record.error_msg = str(exc)
        db.commit()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/sandbox/execution/{execution_no}",
    response_model=schemas.ApiResponse[schemas.SandboxExecutionDetail],
)
async def get_execution(
    execution_no: str,
    db: Session = Depends(get_db),
    user=Depends(authenticate_request),
):
    """查询执行详情（优先本地 DB，若状态未完成则回查网关）。"""
    record = (
        db.query(SandboxExecution)
        .filter(
            SandboxExecution.execution_no == execution_no,
            SandboxExecution.tenant_id == user.tenant_id,
            SandboxExecution.deleted_at.is_(None),
        )
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="执行记录不存在")

    # 若未结束，回查网关刷新
    if record.status in (SandboxStatus.PENDING.value, SandboxStatus.RUNNING.value):
        try:
            remote = sandbox_client.get_execution(execution_no)
            record.status = remote.get("status", record.status)
            record.ended_at = remote.get("ended_at") or record.ended_at
            record.exit_code = remote.get("exit_code")
            record.logs = remote.get("logs")
            record.artifacts = remote.get("artifacts")
            record.result_payload = remote.get("result_payload")
            record.error_msg = remote.get("error_msg")
            if not record.worker_id:
                # ES9-P-03：网关回查补齐执行载体标识
                record.worker_id = (
                    remote.get("worker_id") or remote.get("sandbox_id")
                )
            db.commit()
            db.refresh(record)
        except Exception:
            pass  # 网关不可达时返回本地缓存状态

    return schemas.ApiResponse(
        data=schemas.SandboxExecutionDetail.model_validate(record)
    )


@router.get(
    "/sandbox/pool/status", response_model=schemas.ApiResponse[dict[str, Any]]
)
async def pool_status(
    user=Depends(authenticate_request),
):
    """ES9-P-03：worker 池状态（HealthCheck 部署验收页消费）。

    - SANDBOX_MODE != pool：返回 404（前端显示"pool 模式未启用（legacy docker 模式）"）
    - pool 模式：代理网关 /sandbox/pool/status，聚合 {mode, workers, hardening}
    """
    if settings.SANDBOX_MODE != "pool":
        raise NotFoundError(
            "ES-SANDBOX-0404",
            "pool 模式未启用（当前 SANDBOX_MODE=%s）" % settings.SANDBOX_MODE,
        )
    data = sandbox_client.pool_status()
    workers = data.get("workers")
    if workers is None:
        # 网关未上报 worker 明细时以空池透出（mode/hardening 仍可验收）
        workers = []
    return schemas.ApiResponse(
        data={
            "mode": data.get("mode") or "pool",
            "workers": workers,
            "hardening": data.get("hardening") or _POOL_HARDENING,
        }
    )


@router.post(
    "/sandbox/images", response_model=schemas.ApiResponse[schemas.SandboxImageOut]
)
async def create_image(
    req: schemas.SandboxImageCreate,
    db: Session = Depends(get_db),
    user=Depends(authenticate_request),
):
    """注册沙箱镜像。"""
    full_name = (
        f"{req.registry_url.rstrip('/')}/{req.image_name}:{req.image_tag}"
        if req.registry_url
        else f"{req.image_name}:{req.image_tag}"
    )
    image = SandboxImage(
        image_no=gen_no("SI"),
        image_name=req.image_name,
        image_tag=req.image_tag,
        registry_url=req.registry_url,
        full_name=full_name,
        description=req.description,
        is_default=req.is_default,
        tenant_id=user.tenant_id,
        created_by=user.user_id,
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return schemas.ApiResponse(data=schemas.SandboxImageOut.model_validate(image))


@router.get(
    "/sandbox/images", response_model=schemas.PageResponse[schemas.SandboxImageOut]
)
async def list_images(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(authenticate_request),
):
    """镜像列表。"""
    q = db.query(SandboxImage).filter(
        SandboxImage.tenant_id == user.tenant_id,
        SandboxImage.deleted_at.is_(None),
    )
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return schemas.PageResponse(
        data=schemas.PageData(
            items=[schemas.SandboxImageOut.model_validate(i) for i in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    )
