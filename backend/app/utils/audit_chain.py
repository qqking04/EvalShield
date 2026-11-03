# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""审计日志 SHA-256 校验链计算与验证引擎。

核心公式：
    self_hash = SHA256(prev_hash + '|' + chain_payload)
    chain_payload = '|'.join([log_no, action, module, username or '',
                               result, str(created_at), str(tenant_id)])
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings

if TYPE_CHECKING:
    from ..models import AuditLog

logger = logging.getLogger("evalshield.audit_chain")


# 公开常量：字段分隔符与空 hash 占位符
SEP = "|"
GENESIS_HASH = "0" * 64


def _canonical_ts(dt: datetime | None) -> str:
    """将时间戳统一转为 UTC ISO 格式字符串（带 Z）。"""
    if dt is None:
        return ""
    # 确保是 aware 对象并转 UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def build_chain_payload(log: AuditLog) -> str:
    """生成参与 hash 的业务内容串（顺序必须稳定，不可随意调整）。"""
    parts = [
        log.log_no or "",
        log.action or "",
        log.module or "",
        log.username or "",
        log.result or "",
        _canonical_ts(log.created_at),
        str(log.tenant_id) if log.tenant_id is not None else "",
    ]
    return SEP.join(parts)


def compute_hash(prev_hash: str | None, payload: str) -> str:
    """计算单条记录的 self_hash。"""
    prev = prev_hash if prev_hash else GENESIS_HASH
    raw = f"{prev}{SEP}{payload}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_log_hash(log: AuditLog, prev_hash: str | None) -> str:
    """根据日志对象计算 self_hash。"""
    return compute_hash(prev_hash, build_chain_payload(log))


def get_last_audit_meta(db: Session) -> tuple[int, str] | None:
    """返回当前最后一条有效审计日志的 (chain_index, self_hash)。

    返回 None 表示表为空（下一条为创世块）。
    """
    # 使用行号避免全表扫描；PostgreSQL 中可通过子查询优化
    # chain_index IS NOT NULL：跳过无链字段的历史记录（老表结构遗留），
    # 新记录从创世块继续计算，避免 int(None) 崩溃。
    row = db.execute(
        text(
            """
            SELECT chain_index, self_hash
            FROM audit_logs
            WHERE archived_at IS NULL AND chain_index IS NOT NULL
            ORDER BY chain_index DESC
            LIMIT 1
            """
        )
    ).fetchone()
    if row is None:
        return None
    return int(row.chain_index), str(row.self_hash)


def _max_chain_index_in_session(db: Session) -> tuple[int, str] | None:
    """扫描当前 session 中 pending 的 AuditLog，返回最大的 (chain_index, self_hash)。"""
    from ..models import AuditLog

    max_index = -1
    max_hash = GENESIS_HASH
    found = False
    for obj in db.new:
        if isinstance(obj, AuditLog) and obj.archived_at is None:
            if obj.chain_index is not None and obj.chain_index > max_index:
                max_index = obj.chain_index
                max_hash = obj.self_hash or GENESIS_HASH
                found = True
    if found:
        return max_index, max_hash
    return None


def assign_chain_fields(log: AuditLog, db: Session) -> None:
    """在 flush 前为日志对象分配 chain_index / prev_hash / self_hash。

    注意：本函数在事务内执行，chain_index 依赖数据库行锁（ SERIALIZABLE 语义由业务层保证单线程写审计）。
    """
    if not settings.AUDIT_LOG_VERIFY_CHAIN:
        log.chain_index = None
        log.prev_hash = None
        log.self_hash = None
        return

    # 合并数据库已提交记录与当前 session pending 记录，取最新链尾
    last_db = get_last_audit_meta(db)
    last_sess = _max_chain_index_in_session(db)

    if last_db is None and last_sess is None:
        prev_hash = GENESIS_HASH
        chain_index = 1
    elif last_sess is not None and (last_db is None or last_sess[0] >= last_db[0]):
        prev_hash = last_sess[1]
        chain_index = last_sess[0] + 1
    else:
        last_index, last_hash = last_db  # type: ignore[misc]
        prev_hash = last_hash
        chain_index = last_index + 1

    log.chain_index = chain_index
    log.prev_hash = prev_hash
    log.self_hash = compute_log_hash(log, prev_hash)


def verify_chain(db: Session, *, tenant_id: int | None = None) -> dict:
    """校验整条审计链完整性。

    返回结构：
        {
            "total": 总条数,
            "valid": True/False,
            "first_index": 首条 chain_index,
            "last_index": 末条 chain_index,
            "breaks": [
                {"chain_index": 3, "expected_hash": "...", "actual_hash": "..."},
            ],
            "missing_indices": [2, 5],  # 序号跳跃（理论上不应出现）
        }
    """
    from ..models import AuditLog

    q = db.query(AuditLog).filter(AuditLog.archived_at.is_(None))
    if tenant_id is not None:
        q = q.filter(AuditLog.tenant_id == tenant_id)
    rows = q.order_by(AuditLog.chain_index.asc().nulls_last(), AuditLog.id.asc()).all()

    # 无链字段的历史记录（审计链启用前写入，legacy）不参与 hash 比对
    legacy_count = sum(1 for r in rows if r.chain_index is None or r.self_hash is None)
    chained = [r for r in rows if r.chain_index is not None and r.self_hash is not None]

    total = len(rows)
    if not chained:
        return {
            "total": total,
            "legacy_count": legacy_count,
            "valid": True,
            "first_index": None,
            "last_index": None,
            "breaks": [],
            "missing_indices": [],
        }

    breaks = []
    missing = []
    expected_prev = GENESIS_HASH
    expected_index = chained[0].chain_index

    for log in chained:
        # 序号连续性检查
        if expected_index is None:
            expected_index = log.chain_index
        elif log.chain_index != expected_index:
            if log.chain_index is not None and expected_index is not None:
                missing.extend(range(expected_index, log.chain_index))
            elif log.chain_index is None:
                missing.append(expected_index)
            expected_index = log.chain_index

        # hash 一致性检查
        payload = build_chain_payload(log)
        actual = compute_hash(expected_prev, payload)
        if actual != log.self_hash:
            breaks.append(
                {
                    "chain_index": log.chain_index,
                    "expected_hash": actual,
                    "actual_hash": log.self_hash,
                }
            )

        expected_prev = log.self_hash
        if expected_index is not None:
            expected_index += 1

    return {
        "total": total,
        "legacy_count": legacy_count,
        "valid": len(breaks) == 0 and len(missing) == 0,
        "first_index": chained[0].chain_index,
        "last_index": chained[-1].chain_index,
        "breaks": breaks,
        "missing_indices": missing,
    }
