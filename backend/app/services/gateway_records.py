# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
# backend/app/services/gateway_records.py
"""网关调用记账：usage 明细 + token 预算扣减 + 计费流水联动。

设计要点：
- calculate_cost：纯函数计价，输入/输出分开。
- check_budget：调用前预检（token_budget=0 时不限，向后兼容既有租户）。
- record_usage：调用后记账；全程容错，失败仅记录日志与 mark 指标（不阻断主流程）。
- quota 联动：写 model_gateway_records + billing_quotas.token_used 累加 + BillingRecord(unit="TOKEN")。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import BillingQuota, BillingRecord
from ..utils.no import gen_no

logger = logging.getLogger("evalshield.gateway_records")

# 估算因子（用于预算预检时对未返回 token 数的提前预估；max_tokens 为输出上限）
PROMPT_TOKEN_EST_PER_CHAR = 0.6  # 中文/英文混合经验值：平均每字符约 0.6 token


def calculate_cost(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    input_price_per_mtok: float,
    output_price_per_mtok: float,
) -> dict[str, float]:
    """输入/输出分开计价（单位：元）。"""
    input_cost = (
        float(prompt_tokens or 0) / 1_000_000 * float(input_price_per_mtok or 0)
    )
    output_cost = (
        float(completion_tokens or 0) / 1_000_000 * float(output_price_per_mtok or 0)
    )
    return {
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(input_cost + output_cost, 6),
    }


def estimate_prompt_tokens(text: str) -> int:
    """估算 prompt 的输入 token 数（无 usage 返回时用于预算预检）。"""
    return int(len(text or "") * PROMPT_TOKEN_EST_PER_CHAR) + 1


def check_budget(
    db: Session, *, tenant_id: int, estimate_total_tokens: int
) -> tuple[bool, dict[str, Any]]:
    """调用前预算预检。返回 (是否放行, 上下文)。"""
    quota = db.query(BillingQuota).filter(BillingQuota.tenant_id == tenant_id).first()
    if quota is None or (quota.token_budget or 0) <= 0:
        return True, {"token_budget": 0, "token_used": 0, "remaining": -1}
    used = quota.token_used or 0
    budget = quota.token_budget or 0
    remaining = budget - used
    if remaining < max(int(estimate_total_tokens), 1):
        return False, {
            "token_budget": budget,
            "token_used": used,
            "remaining": max(remaining, 0),
        }
    return True, {
        "token_budget": budget,
        "token_used": used,
        "remaining": remaining,
    }


def record_usage(
    db: Session | None,
    *,
    tenant_id: int,
    user_id: int | None = None,
    task_id: int | None = None,
    step_id: int | None = None,
    ref_no: str | None = None,
    provider: str,
    model: str,
    model_code: str | None = None,
    request_hash: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    input_price_per_mtok: float = 0.0,
    output_price_per_mtok: float = 0.0,
    cache_hit: bool = False,
    latency_ms: int = 0,
    status: str = "SUCCESS",
    error_code: str | None = None,
    error_msg: str | None = None,
) -> None:
    """调用后记账：usage 明细 + token 预算 + 计费流水（容错，不抛异常）。"""
    _own_session = False
    if db is None:
        # 引擎路径通常不传 db；此处自开短会话，保证网关记账不缺失
        from ..database import SessionLocal

        db = SessionLocal()
        _own_session = True
    try:
        from ..models import ModelGatewayRecord

        total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)
        cost = calculate_cost(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            input_price_per_mtok=input_price_per_mtok,
            output_price_per_mtok=output_price_per_mtok,
        )
        record = ModelGatewayRecord(
            record_no=gen_no("GWR"),
            tenant_id=tenant_id,
            user_id=user_id,
            task_id=task_id,
            step_id=step_id,
            ref_no=ref_no,
            provider=provider,
            model=model,
            model_code=model_code,
            request_hash=request_hash,
            prompt_tokens=int(prompt_tokens or 0),
            completion_tokens=int(completion_tokens or 0),
            total_tokens=total_tokens,
            input_price_per_mtok=float(input_price_per_mtok or 0),
            output_price_per_mtok=float(output_price_per_mtok or 0),
            input_cost=cost["input_cost"],
            output_cost=cost["output_cost"],
            total_cost=cost["total_cost"],
            cache_hit=bool(cache_hit),
            latency_ms=int(latency_ms or 0),
            status=status,
            error_code=error_code,
            error_msg=error_msg,
        )
        db.add(record)
        # token 预算扣减 + 计费流水（unit="TOKEN"）
        if total_tokens > 0 or status != "SUCCESS":
            quota = (
                db.query(BillingQuota)
                .filter(BillingQuota.tenant_id == tenant_id)
                .first()
            )
            if quota is None:
                quota = BillingQuota(tenant_id=tenant_id)
                db.add(quota)
                db.flush()
            quota.token_used = (quota.token_used or 0) + total_tokens
            db.add(
                BillingRecord(
                    record_no=gen_no("BL"),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    biz_type="API",
                    ref_no=ref_no,
                    amount=float(total_tokens),
                    unit="TOKEN",
                    description=(
                        f"LLM 调用：{provider}/{model}"
                        f"{'（缓存命中）' if cache_hit else ''}"
                    ),
                )
            )
        db.commit()
    except Exception:  # noqa: BLE001 - 记账失败不阻断主流程
        logger.exception("网关记账失败（不影响 LLM 调用主流程）")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass


def gateway_stats(db: Session, *, tenant_id: int) -> dict[str, Any]:
    """网关用量汇总：调用量 / token / 成本 / 缓存命中（供计费页与可观测）。"""
    from ..models import ModelGatewayRecord

    try:
        rows = (
            db.query(ModelGatewayRecord)
            .filter(ModelGatewayRecord.tenant_id == tenant_id)
            .order_by(ModelGatewayRecord.id.desc())
            .limit(10000)
            .all()
        )
        total_calls = len(rows)
        success = sum(1 for r in rows if r.status == "SUCCESS")
        cache_hits = sum(1 for r in rows if r.cache_hit)
        prompt_tokens = sum(r.prompt_tokens for r in rows)
        completion_tokens = sum(r.completion_tokens for r in rows)
        total_cost = round(sum(r.total_cost for r in rows), 4)
        return {
            "total_calls": total_calls,
            "success_calls": success,
            "failed_calls": total_calls - success,
            "cache_hits": cache_hits,
            "cache_hit_ratio": round(cache_hits / total_calls, 4)
            if total_calls
            else 0.0,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "total_cost": total_cost,
            "avg_latency_ms": (
                round(sum(r.latency_ms for r in rows) / max(total_calls, 1))
                if total_calls
                else 0
            ),
        }
    except Exception:  # noqa: BLE001
        logger.exception("网关统计失败")
        return {}
