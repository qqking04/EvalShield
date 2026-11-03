# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M8：网关旁路留痕（trace 摄入第一步）。

- truncate_text：request/response 截断存——单条上限 8KB（8192 字符），
  超限存前 4KB + `…TRUNCATED: orig_len=N…` 标记 + 后 1KB。
- maybe_record_gateway_trace：target_gateway.respond API 成功路径的旁路写入，
  照 gateway_records.record_usage 容错范式：自开短会话、任何异常仅记日志，
  绝不阻断转发（留痕失败不影响业务调用返回）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("evalshield.trace_recording")

# 截断参数（§9.2：单条上限 8KB，超限存前4KB+标记+后1KB）
MAX_TEXT_LEN = 8192
HEAD_LEN = 4096
TAIL_LEN = 1024


def truncate_text(text: str | None) -> str:
    """截断存：≤8KB 原文直存；超限 = 前4KB + TRUNCATED 标记（含原始长度）+ 后1KB。"""
    s = text or ""
    if len(s) <= MAX_TEXT_LEN:
        return s
    marker = f"\n…TRUNCATED: orig_len={len(s)}…\n"
    return s[:HEAD_LEN] + marker + s[-TAIL_LEN:]


def _extract_tokens(raw: dict | None) -> int | None:
    """尽力从 OpenAI 兼容响应提取 total_tokens；提取不到返回 None。"""
    if not isinstance(raw, dict):
        return None
    usage = raw.get("usage")
    if isinstance(usage, dict):
        try:
            total = usage.get("total_tokens")
            if total is None:
                total = int(usage.get("prompt_tokens") or 0) + int(
                    usage.get("completion_tokens") or 0
                )
            return int(total) if total else None
        except (TypeError, ValueError):
            return None
    return None


def maybe_record_gateway_trace(
    target: dict[str, Any] | None,
    *,
    prompt: str,
    response: str,
    latency_ms: int,
    external_ref: str | None = None,
    tokens: int | None = None,
    status: str = "OK",
) -> None:
    """网关调用成功后旁路写 traces(source=gateway)。

    容错设计：db 自开短会话，全程 try/except，失败只记日志——
    留痕绝不阻断转发主流程（§9.3 边界声明）。
    """
    if target is None or not target.get("tenant_id"):
        return  # 无租户上下文（如平台侧内部调用）不留痕
    db = None
    try:
        from ..database import SessionLocal
        from ..models import Trace

        db = SessionLocal()
        db.add(
            Trace(
                tenant_id=int(target["tenant_id"]),
                source="gateway",
                external_ref=(str(external_ref)[:64] if external_ref else None),
                request=truncate_text(prompt),
                response=truncate_text(response),
                model=str(target.get("model") or target.get("code") or "")[:64] or None,
                tokens=tokens,
                latency_ms=int(latency_ms or 0),
                status=status,
                occurred_at=datetime.now(timezone.utc),
                eval_status="PENDING",
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 - 旁路留痕失败不阻断转发
        logger.exception("gateway trace 旁路留痕失败（不阻断转发）")
        if db is not None:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
    finally:
        if db is not None:
            db.close()
