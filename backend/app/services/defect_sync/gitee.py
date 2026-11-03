# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M11 Gitee Issues 适配器（出站推送 + scheduler 日轮询回写，方案 §12.3）。

REST（httpx + ``access_token`` 参数，api.gitee.com/v5）；
config：{repo: "owner/name", token_enc, api_base?, site_url?}
回写靠 scheduler 日轮询 fetch_state（≤200 links/轮，见 run_gitee_poll_once），
UI 标注"延迟≤24h"。
"""

from __future__ import annotations

import logging

from .base import PUSH_TIMEOUT, SyncResult, apply_external_state, resolve_token

logger = logging.getLogger("evalshield.defect_sync.gitee")

DEFAULT_API_BASE = "https://gitee.com/api/v5"

# 单轮轮询上限（方案 §12.3：≤200 links/轮）
POLL_BATCH_LIMIT = 200


def _api_base(config: dict) -> str:
    return str((config or {}).get("api_base") or DEFAULT_API_BASE).rstrip("/")


def push(payload: dict, config: dict) -> SyncResult:
    """创建 Gitee Issue（POST /repos/{owner}/{repo}/issues）。"""
    import httpx

    repo = str((config or {}).get("repo") or "")
    token = resolve_token(config)
    if not repo or "/" not in repo:
        return SyncResult(ok=False, error="缺少 repo 配置（owner/name）", retryable=False)
    if not token:
        return SyncResult(ok=False, error="缺少访问令牌", retryable=False)
    owner, _, repo_name = repo.partition("/")
    base = _api_base(config)
    try:
        resp = httpx.post(
            f"{base}/repos/{owner}/{repo_name}/issues",
            params={
                "access_token": token,
                "title": payload["subject"],
                "body": payload["body"],
                "labels": f"severity-{(payload.get('severity') or 'P2').lower()},evalshield",
                "repo": repo,
            },
            timeout=PUSH_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return SyncResult(ok=False, error=f"Gitee 请求失败: {exc.__class__.__name__}: {exc}", retryable=True)
    if resp.status_code >= 400:
        return SyncResult(
            ok=False,
            error=f"Gitee 响应 {resp.status_code}: {resp.text[:200]}",
            retryable=resp.status_code >= 500,
        )
    try:
        data = resp.json()
        number = str(data["number"])
        return SyncResult(
            ok=True,
            external_id=number,
            external_url=str(data.get("html_url") or f"https://gitee.com/{repo}/issues/{number}"),
        )
    except (ValueError, KeyError, TypeError) as exc:
        return SyncResult(ok=False, error=f"Gitee 响应解析失败: {exc}", retryable=False)


def fetch_state(external_id: str, config: dict) -> str | None:
    """查询 issue 状态 → "open"|"closed"（Gitee 事件态含 reopened）；失败返回 None。"""
    import httpx

    repo = str((config or {}).get("repo") or "")
    token = resolve_token(config)
    if not repo or "/" not in repo or not token:
        return None
    owner, _, repo_name = repo.partition("/")
    base = _api_base(config)
    try:
        resp = httpx.get(
            f"{base}/repos/{owner}/{repo_name}/issues/{external_id}",
            params={"access_token": token},
            timeout=PUSH_TIMEOUT,
        )
        if resp.status_code >= 400:
            return None
        state = str(resp.json().get("state") or "")
        return state if state in ("open", "closed", "reopened") else None
    except Exception:  # noqa: BLE001 —— 轮询语义：失败静默，下轮再试
        return None


def probe(config: dict) -> SyncResult:
    """连通探测：GET repo 详情（验证 token 与仓库可达）。"""
    import httpx

    repo = str((config or {}).get("repo") or "")
    token = resolve_token(config)
    if not repo or "/" not in repo:
        return SyncResult(ok=False, error="缺少 repo 配置（owner/name）", retryable=False)
    if not token:
        return SyncResult(ok=False, error="缺少访问令牌", retryable=False)
    owner, _, repo_name = repo.partition("/")
    base = _api_base(config)
    try:
        resp = httpx.get(
            f"{base}/repos/{owner}/{repo_name}",
            params={"access_token": token},
            timeout=PUSH_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return SyncResult(ok=False, error=f"Gitee 请求失败: {exc.__class__.__name__}: {exc}", retryable=True)
    if 200 <= resp.status_code < 300:
        return SyncResult(ok=True)
    return SyncResult(
        ok=False,
        error=f"Gitee 响应 {resp.status_code}: {resp.text[:200]}",
        retryable=resp.status_code >= 500,
    )


def run_gitee_poll_once(db) -> int:
    """scheduler 日轮询入口：扫描 gitee 已 link 且未终态的行，回写本地状态。

    单轮 ≤ POLL_BATCH_LIMIT 条；每条独立 try，单条失败不中断本批。
    返回处理的 link 数。
    """
    from ...models import Defect, DefectSyncLink, DefectSyncTarget

    rows = (
        db.query(DefectSyncLink, DefectSyncTarget, Defect)
        .join(DefectSyncTarget, DefectSyncTarget.id == DefectSyncLink.target_id)
        .join(Defect, Defect.id == DefectSyncLink.defect_id)
        .filter(
            DefectSyncTarget.provider == "gitee",
            DefectSyncTarget.enabled.is_(True),
            DefectSyncLink.sync_status.in_(("SYNCED", "FAILED")),
            Defect.deleted_at.is_(None),
        )
        .order_by(DefectSyncLink.id)
        .limit(POLL_BATCH_LIMIT)
        .all()
    )
    processed = 0
    for link, target, defect in rows:
        processed += 1
        try:
            state = fetch_state(link.external_id, target.config or {})
            if state is None:
                continue  # 查询失败：不改状态，下轮再试
            if apply_external_state(db, defect, link, state):
                logger.info(
                    "gitee 轮询回写：defect %s ← issue %s (%s)",
                    defect.id, link.external_id, state,
                )
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("gitee 轮询 link %s 异常（跳过）", link.id)
    return processed
