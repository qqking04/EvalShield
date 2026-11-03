# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M11 GitHub Issues 适配器（出站推送 + 状态查询，方案 §12.3）。

REST v3（httpx + ``Authorization: Bearer``）；内网自建 GitHub 通过
config.api_base 覆盖（缺省 https://api.github.com）。
config：{repo: "owner/name", token_enc, api_base?, webhook_secret?, site_url?}
回写收端在 routers/defect_sync.py（HMAC X-Hub-Signature-256 验签）。
"""

from __future__ import annotations

from .base import PUSH_TIMEOUT, SyncResult, resolve_token

DEFAULT_API_BASE = "https://api.github.com"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


def _issue_labels(severity: str) -> list[str]:
    """标签写死（方案 §12.3）：severity/{sev} + evalshield。"""
    return [f"severity/{(severity or 'P2').lower()}", "evalshield"]


def push(payload: dict, config: dict) -> SyncResult:
    """创建 GitHub Issue。成功回 (issue number, html_url)。"""
    import httpx

    repo = str((config or {}).get("repo") or "")
    token = resolve_token(config)
    if not repo or "/" not in repo:
        return SyncResult(ok=False, error="缺少 repo 配置（owner/name）", retryable=False)
    if not token:
        return SyncResult(ok=False, error="缺少访问令牌", retryable=False)
    base = str((config or {}).get("api_base") or DEFAULT_API_BASE).rstrip("/")
    try:
        resp = httpx.post(
            f"{base}/repos/{repo}/issues",
            headers=_headers(token),
            json={
                "title": payload["subject"],
                "body": payload["body"],
                "labels": _issue_labels(str(payload.get("severity") or "")),
            },
            timeout=PUSH_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 —— 网络类失败可重试
        return SyncResult(ok=False, error=f"GitHub 请求失败: {exc.__class__.__name__}: {exc}", retryable=True)
    if resp.status_code >= 400:
        return SyncResult(
            ok=False,
            error=f"GitHub 响应 {resp.status_code}: {resp.text[:200]}",
            retryable=resp.status_code >= 500,
        )
    try:
        data = resp.json()
        return SyncResult(
            ok=True,
            external_id=str(data["number"]),
            external_url=str(data.get("html_url") or f"{base}/repos/{repo}/issues/{data['number']}"),
        )
    except (ValueError, KeyError, TypeError) as exc:
        return SyncResult(ok=False, error=f"GitHub 响应解析失败: {exc}", retryable=False)


def fetch_state(external_id: str, config: dict) -> str | None:
    """查询 issue 状态 → "open"|"closed"|"reopened"；失败/未知返回 None。"""
    import httpx

    repo = str((config or {}).get("repo") or "")
    token = resolve_token(config)
    if not repo or not token:
        return None
    base = str((config or {}).get("api_base") or DEFAULT_API_BASE).rstrip("/")
    try:
        resp = httpx.get(
            f"{base}/repos/{repo}/issues/{external_id}",
            headers=_headers(token),
            timeout=PUSH_TIMEOUT,
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        state = str(data.get("state") or "")
        if state == "closed":
            return "closed"
        # GitHub 无独立 reopened 态；用 reopened 事件标记的 open issue 归为 open
        return "open" if state == "open" else None
    except Exception:  # noqa: BLE001 —— 轮询语义：失败静默，下轮再试
        return None


def probe(config: dict) -> SyncResult:
    """连通探测：GET 目标 repo（验证 token 与仓库可达）。"""
    import httpx

    repo = str((config or {}).get("repo") or "")
    token = resolve_token(config)
    if not repo or "/" not in repo:
        return SyncResult(ok=False, error="缺少 repo 配置（owner/name）", retryable=False)
    if not token:
        return SyncResult(ok=False, error="缺少访问令牌", retryable=False)
    base = str((config or {}).get("api_base") or DEFAULT_API_BASE).rstrip("/")
    try:
        resp = httpx.get(f"{base}/repos/{repo}", headers=_headers(token), timeout=PUSH_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        return SyncResult(ok=False, error=f"GitHub 请求失败: {exc.__class__.__name__}: {exc}", retryable=True)
    if 200 <= resp.status_code < 300:
        return SyncResult(ok=True)
    return SyncResult(
        ok=False,
        error=f"GitHub 响应 {resp.status_code}: {resp.text[:200]}",
        retryable=resp.status_code >= 500,
    )
