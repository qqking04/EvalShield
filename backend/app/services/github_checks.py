# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M5：GitHub Checks API 回写（可选增强，方案 §6.2）。

启用模式与 M2 支付 provider 一致：env GITHUB_APP_ID / GITHUB_APP_INSTALLATION_ID /
GITHUB_APP_PRIVATE_KEY 三项齐全才启用，缺任一即完全跳过（返回 None，不报错、不阻断）。

流程：App 私钥签发 RS256 JWT → POST /app/installations/{id}/access_tokens 换安装态
token → POST /repos/{owner}/{repo}/check-runs 创建名为 "EvalShield Quality Gate" 的
Check Run（PASSED→success / FAILED→failure / 其他→neutral）。

仓库与提交定位：任务 config.github = {"owner","repo","sha"}（CI 触发时透传），
缺 sha/owner/repo 时跳过回写。HTTP 统一走 httpx（既有依赖），测试 monkeypatch 可测。
"""

from __future__ import annotations

import logging
import time

import httpx
from jose import jwt

from ..config import settings
from ..models import TestTask
from .quality_gate import VERDICT_FAILED, VERDICT_PASSED

logger = logging.getLogger("evalshield.github_checks")

CHECK_NAME = "EvalShield Quality Gate"
_HTTP_TIMEOUT = 10.0


def enabled() -> bool:
    """三项 env 齐全才启用（缺 KEY → 跳过模式）。"""
    return bool(
        settings.GITHUB_APP_ID
        and settings.GITHUB_APP_INSTALLATION_ID
        and settings.GITHUB_APP_PRIVATE_KEY
    )


def _api_base() -> str:
    return (settings.GITHUB_CHECKS_API_BASE or "https://api.github.com").rstrip("/")


def _app_jwt(now: float | None = None) -> str:
    """GitHub App 身份 JWT（RS256，60s 时钟偏移容忍，有效期 9 分钟）。"""
    iat = int(now if now is not None else time.time())
    payload = {
        "iat": iat - 60,
        "exp": iat + 9 * 60,
        "iss": settings.GITHUB_APP_ID,
    }
    return jwt.encode(payload, settings.GITHUB_APP_PRIVATE_KEY, algorithm="RS256")


def _installation_token(client: httpx.Client) -> str | None:
    """App JWT 换 installation access token。失败返回 None（调用方跳过）。"""
    url = f"{_api_base()}/app/installations/{settings.GITHUB_APP_INSTALLATION_ID}/access_tokens"
    resp = client.post(
        url,
        headers={"Authorization": f"Bearer {_app_jwt()}", "Accept": "application/vnd.github+json"},
        json={},
    )
    if resp.status_code >= 400:
        logger.warning("GitHub installation token 获取失败：%s", resp.status_code)
        return None
    try:
        return str(resp.json()["token"])
    except (ValueError, KeyError, TypeError):
        logger.warning("GitHub installation token 响应缺少 token 字段")
        return None


def _conclusion(verdict: str) -> str:
    if verdict == VERDICT_PASSED:
        return "success"
    if verdict == VERDICT_FAILED:
        return "failure"
    return "neutral"


def publish_gate_check(task: TestTask, gate: dict) -> dict | None:
    """门禁结论回写 GitHub Check Run。返回创建的 check run 摘要；条件不满足返回 None。

    任何网络/配置异常都在内部吞掉并记日志（旁挂语义，不影响任务主流程）。
    """
    if not enabled():
        return None
    cfg = (task.config or {}).get("github") if isinstance(task.config, dict) else None
    if not isinstance(cfg, dict):
        return None
    owner, repo, sha = str(cfg.get("owner") or ""), str(cfg.get("repo") or ""), str(cfg.get("sha") or "")
    if not (owner and repo and sha):
        logger.info("task %s config.github 缺 owner/repo/sha，跳过 Checks 回写", task.id)
        return None
    verdict = str(gate.get("verdict") or "")
    checks = gate.get("checks") or []
    fails = [c for c in checks if c.get("ok") is False]
    summary = f"任务 {task.task_no}（{task.name}）质量门禁 {verdict}"
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            token = _installation_token(client)
            if token is None:
                return None
            resp = client.post(
                f"{_api_base()}/repos/{owner}/{repo}/check-runs",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={
                    "name": CHECK_NAME,
                    "head_sha": sha,
                    "status": "completed",
                    "conclusion": _conclusion(verdict),
                    "output": {
                        "title": summary,
                        "summary": "；".join(
                            f"{c['metric']}={c['actual']}（要求 {c['op']} {c['threshold']}）"
                            for c in checks
                            if c.get("actual") is not None
                        )
                        or "无可评估指标",
                        "text": "\n".join(
                            f"- FAIL {c['metric']}={c['actual']} 要求 {c['op']} {c['threshold']}"
                            for c in fails
                        )
                        or "全部规则通过",
                    },
                },
            )
            if resp.status_code >= 400:
                logger.warning("GitHub Check Run 创建失败：%s %s", resp.status_code, resp.text[:200])
                return None
            data = resp.json()
            logger.info("GitHub Check Run 已创建：%s/%s sha=%s conclusion=%s", owner, repo, sha, _conclusion(verdict))
            return {"id": data.get("id"), "html_url": data.get("html_url"), "conclusion": _conclusion(verdict)}
    except Exception as exc:  # noqa: BLE001 —— 可选回写：任何异常吞掉不阻断
        logger.warning("GitHub Checks 回写异常（忽略）: %s", exc)
        return None
