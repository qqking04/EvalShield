# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M11 Jira 适配器（出站单向推送，不做回写，方案 §12.3）。

REST v2（httpx Bearer PAT，POST {base}/rest/api/3/issue）；
config：{base_url, project_key, personal_token_enc, issue_type: "Bug", site_url?}
**能力差异如实声明**：fetch_state 恒返回 None（UI 配置页标注"单向"）。
"""

from __future__ import annotations

from .base import PUSH_TIMEOUT, SyncResult, resolve_token


def _base(config: dict) -> str:
    return str((config or {}).get("base_url") or "").rstrip("/")


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}


def push(payload: dict, config: dict) -> SyncResult:
    """创建 Jira Issue。成功回 (issue key, 站内可见 URL)。"""
    import httpx

    base = _base(config)
    project_key = str((config or {}).get("project_key") or "")
    token = resolve_token(config)
    if not base or not project_key:
        return SyncResult(ok=False, error="缺少 base_url / project_key 配置", retryable=False)
    if not token:
        return SyncResult(ok=False, error="缺少个人访问令牌", retryable=False)
    issue_type = str((config or {}).get("issue_type") or "Bug")
    try:
        resp = httpx.post(
            f"{base}/rest/api/3/issue",
            headers=_headers(token),
            json={
                "fields": {
                    "project": {"key": project_key},
                    "issuetype": {"name": issue_type},
                    "summary": payload["subject"],
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [{"type": "paragraph", "content": [
                            {"type": "text", "text": payload["body"]},
                        ]}],
                    },
                },
            },
            timeout=PUSH_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return SyncResult(ok=False, error=f"Jira 请求失败: {exc.__class__.__name__}: {exc}", retryable=True)
    if resp.status_code >= 400:
        return SyncResult(
            ok=False,
            error=f"Jira 响应 {resp.status_code}: {resp.text[:200]}",
            retryable=resp.status_code >= 500,
        )
    try:
        data = resp.json()
        key = str(data["key"])
        return SyncResult(
            ok=True, external_id=key,
            external_url=str(data.get("self") or f"{base}/browse/{key}"),
        )
    except (ValueError, KeyError, TypeError) as exc:
        return SyncResult(ok=False, error=f"Jira 响应解析失败: {exc}", retryable=False)


def fetch_state(external_id: str, config: dict) -> str | None:
    """Jira 出站单向：不做回写，恒返回 None（方案 §12.3 能力差异声明）。"""
    return None


def probe(config: dict) -> SyncResult:
    """连通探测：GET /rest/api/3/project/{key}（验证 PAT 与项目可达）。"""
    import httpx

    base = _base(config)
    project_key = str((config or {}).get("project_key") or "")
    token = resolve_token(config)
    if not base or not project_key:
        return SyncResult(ok=False, error="缺少 base_url / project_key 配置", retryable=False)
    if not token:
        return SyncResult(ok=False, error="缺少个人访问令牌", retryable=False)
    try:
        resp = httpx.get(f"{base}/rest/api/3/project/{project_key}", headers=_headers(token), timeout=PUSH_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        return SyncResult(ok=False, error=f"Jira 请求失败: {exc.__class__.__name__}: {exc}", retryable=True)
    if 200 <= resp.status_code < 300:
        return SyncResult(ok=True)
    return SyncResult(
        ok=False,
        error=f"Jira 响应 {resp.status_code}: {resp.text[:200]}",
        retryable=resp.status_code >= 500,
    )
