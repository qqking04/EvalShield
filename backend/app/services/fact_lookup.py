# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES10-P-01：知识源事实检索服务。

协议约定（与知识库/检索服务对接）：
    POST {base_url}/search  body={"query": str, "top_k": int}
    -> 200 {"items": [{"content": str}, ...]}

降级纪律：任何失败（未配置/超时/SSRF 拒绝/非 2xx/解析失败）返回 None，
调用方按"无参照"处理并在题级结果记 note —— **检索失败绝不阻断评测**。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..models import FactSource
from .crypto import decrypt_secret          # fact_sources.py 连通测试同款
from .ssrf_guard import validate_base_url   # L63-126，错误码由调用方注入

logger = logging.getLogger(__name__)

TIMEOUT_S = 5.0
TOP_K = 3


def lookup_references(
    db: Session,
    fact_source_id: int | None,
    tenant_id: int,
    query: str,
) -> tuple[list[str] | None, str | None]:
    """按知识源检索参照文本。

    返回 (refs, note)：
      - 命中：([content...], None)
      - 空命中：([], None)          —— 检索成功但知识库无匹配（非故障）
      - 未配置/失败：(None, "知识源检索失败：<原因>")  —— 调用方据此记 note
    """
    if not fact_source_id:
        return None, None
    fs = (
        db.query(FactSource)
        .filter(
            FactSource.id == fact_source_id,
            FactSource.tenant_id == tenant_id,
            FactSource.deleted_at.is_(None),
        )
        .first()
    )
    if fs is None or not fs.base_url:
        return None, "知识源不存在或未配置地址"
    try:
        validate_base_url(fs.base_url, error_code="ES-FS-SSRF")
    except Exception as exc:  # SSRF 复校验失败按降级处理，不抛出
        return None, f"知识源地址不合法：{exc}"
    headers = {}
    if fs.auth_cipher:
        headers["Authorization"] = f"Bearer {decrypt_secret(fs.auth_cipher)}"
    try:
        resp = httpx.post(
            f"{fs.base_url.rstrip('/')}/search",
            json={"query": query, "top_k": TOP_K},
            headers=headers,
            timeout=TIMEOUT_S,
        )
        if resp.status_code >= 400:
            return None, f"知识源返回 {resp.status_code}"
        items = (resp.json() or {}).get("items") or []
        refs = [str(i.get("content", ""))[:2000] for i in items if isinstance(i, dict) and i.get("content")]
        # ES10 裁定：空命中与检索故障两态拆开——空命中 ([], None)，故障 (None, note)
        return refs, None
    except httpx.TimeoutException:
        return None, f"知识源检索超时（>{int(TIMEOUT_S)}s）"
    except Exception as exc:
        logger.warning("[fact_lookup] 知识源 %s 检索异常: %s", fact_source_id, exc)
        return None, f"知识源检索异常：{exc.__class__.__name__}"


__all__ = ["lookup_references"]
