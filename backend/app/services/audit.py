# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""审计日志写入服务（防篡改版）。

所有写入统一走本服务，自动计算 chain_index / prev_hash / self_hash。
禁止任何路由直接 `db.add(AuditLog(...))` 或 `db.commit()` 审计日志。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import settings
from ..models import AuditLog
from ..utils.audit_chain import assign_chain_fields
from ..utils.no import gen_no

logger = logging.getLogger("evalshield.audit")


def write_audit(
    db: Session,
    *,
    user_id: int | None,
    username: str | None,
    tenant_id: int,
    action: str,
    module: str,
    request=None,
    method: str | None = None,
    path: str | None = None,
    result: str = "SUCCESS",
    error_msg: str | None = None,
    detail: str | None = None,
    ip: str | None = None,
    ua: str | None = None,
    duration_ms: int | None = None,
    status_code: int | None = None,
) -> AuditLog | None:
    """写审计日志（追加式 WAL，自动计算校验链）。

    返回写入后的 AuditLog 对象（不含 db.refresh，调用方如需完整字段需自行 refresh）；
    任何异常均被吞掉并回滚，避免审计失败影响主流程。
    """
    try:
        req_method, req_path, req_ip, req_ua = method, path, ip, ua
        if request is not None:
            req_method = request.method
            req_path = request.url.path
            try:
                req_ip = request.client.host if request.client else None
            except Exception:  # noqa: BLE001
                req_ip = None
            try:
                req_ua = request.headers.get("user-agent")
            except Exception:  # noqa: BLE001
                req_ua = None

        log = AuditLog(
            log_no=gen_no("AL"),
            user_id=user_id,
            username=username,
            tenant_id=tenant_id,
            action=action,
            module=module,
            method=req_method,
            path=req_path,
            status_code=status_code,
            result=result,
            ip=req_ip,
            ua=req_ua,
            request_body={"detail": detail} if detail else None,
            error_msg=error_msg,
            duration_ms=duration_ms,
            # 必须显式填充 created_at：assign_chain_fields 需要稳定的时间戳参与哈希，
            # 若依赖 ORM default（INSERT 时才生效），哈希计算时仍为 None 导致链不可验证。
            created_at=datetime.now(timezone.utc),
        )

        # 若启用链式校验则分配 hash；否则仅留空字段保持兼容
        if settings.AUDIT_LOG_VERIFY_CHAIN:
            assign_chain_fields(log, db)
        else:
            log.chain_index = None
            log.prev_hash = None
            log.self_hash = None

        db.add(log)
        db.commit()
        return log
    except Exception:  # noqa: BLE001
        logger.exception("写入审计日志失败（不影响主流程）")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None
