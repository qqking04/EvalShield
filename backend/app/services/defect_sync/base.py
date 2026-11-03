# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M11 缺陷工单同步适配器基础约定（方案 §12.3）。

所有适配器统一实现三个函数（按 provider 模块暴露，注册表分发）：
- ``push(payload, config) -> SyncResult``：把缺陷推送为外部工单；
- ``fetch_state(external_id, config) -> str | None``：查外部工单状态
  （"open"|"closed"|"reopened"；Jira 单向不回写，恒返回 None）；
- ``probe(config) -> SyncResult``：连通探测（真实请求一次，不抛异常）。

约定：
- config 为 defect_sync_targets.config JSONB 原样 dict，其中
  ``token_enc`` / ``personal_token_enc`` 为 encrypt_secret 密文，
  适配器内部经 resolve_token 解密使用，绝不出现在任何出参；
- 单次 HTTP 超时 10 秒；网络/对端类失败 retryable=True，
  配置类失败（缺 repo/token）retryable=False；
- 推送标题格式写死（方案 §12.3，避免实现漂移）：
  ``[EvalShield][{severity}] {title}``。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from ...security import decrypt_secret

logger = logging.getLogger("evalshield.defect_sync")

# 统一出站超时（秒），与 M3 通知适配器量级一致但留外部 API 余量
PUSH_TIMEOUT = 10.0

# config 明文键 → 密文键映射（入站加密 / 出站脱敏共用）
TOKEN_FIELDS = {"token": "token_enc", "personal_token": "personal_token_enc"}


@dataclass
class SyncResult:
    """适配器调用结果。

    push 成功时 external_id/external_url 必填；失败时 error 必填。
    retryable=True：网络/对端 5xx 类失败，调用方可提示重试；
    retryable=False：配置缺失/鉴权 4xx 类失败，重试无意义。
    """

    ok: bool
    external_id: str | None = None
    external_url: str | None = None
    error: str | None = None
    retryable: bool = False


def resolve_token(config: dict) -> str:
    """从 config 中取工单令牌明文（token_enc / personal_token_enc 解密）。

    兼容未加密存量明文（decrypt_secret 对非 aes$ 串原样返回）。
    """
    cfg = config or {}
    for enc_key in TOKEN_FIELDS.values():
        enc = cfg.get(enc_key)
        if isinstance(enc, str) and enc:
            return decrypt_secret(enc)
    return ""


def build_subject(defect) -> str:
    """外部工单标题（方案写死格式）：[EvalShield][{severity}] {title}。"""
    return f"[EvalShield][{defect.severity}] {defect.title}"


def build_body(defect, site_url: str = "") -> str:
    """外部工单正文：复现步骤 + 期望/实际 + 用例链接（站内 URL）+ 引擎标签。

    site_url 来自 target config 可选键 site_url（站内缺陷页绝对地址前缀），
    缺省用相对路径（内网自建 GitHub 场景站内可达即可，如实降级不编造域名）。
    """
    lines: list[str] = [f"缺陷编号：{defect.defect_no}", ""]
    steps = defect.reproduce_steps if isinstance(defect.reproduce_steps, list) else []
    if steps:
        lines.append("复现步骤：")
        for i, s in enumerate(steps, 1):
            text = s.get("text") if isinstance(s, dict) else str(s)
            lines.append(f"{i}. {text or s}")
        lines.append("")
    if defect.expected:
        lines.append(f"期望表现：{defect.expected}")
    if defect.actual:
        lines.append(f"实际表现：{defect.actual}")
    if defect.category:
        lines.append(f"AI 归因：{defect.category} {defect.ai_reason or ''}".rstrip())
    base = (site_url or "").rstrip("/")
    lines.append("")
    lines.append(f"用例链接：{base}/commercial/defects?no={defect.defect_no}")
    lines.append("来源：EvalShield 智能评测平台（标签 evalshield）")
    return "\n".join(lines)


def defect_payload(defect, config: dict) -> dict:
    """组装适配器入参（避免适配器直接依赖 ORM 对象，便于测试）。"""
    return {
        "defect_id": int(defect.id),
        "defect_no": defect.defect_no,
        "subject": build_subject(defect),
        "body": build_body(defect, str((config or {}).get("site_url") or "")),
        "severity": defect.severity,
        "status": defect.status,
    }


def append_system_note(defect, text: str) -> None:
    """向 evidence JSONB 追加系统备注条目（Defect 无独立备注字段的落点）。

    结构：{"kind":"system_note","text":...,"at":ISO8601}，
    整列重赋新 list（JSONB 原地 mutate 不会被 SQLAlchemy 感知）。
    """
    entry = {
        "kind": "system_note",
        "text": text,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    evidence = list(defect.evidence or [])
    evidence.append(entry)
    defect.evidence = evidence


def apply_external_state(db, defect, link, external_state: str) -> bool:
    """外部工单状态 → 本地回写（webhook 与 gitee 轮询共用，幂等）。

    映射（方案 §12.3）：
    - closed   → link=EXTERNAL_CLOSED，缺陷置 CLOSED + 系统备注；
    - reopened → link=SYNCED，缺陷置 REOPENED + 系统备注；
    - open     → link=SYNCED，仅当缺陷已 CLOSED 时回 OPEN + 系统备注。
    返回 True 表示缺陷状态发生了变更。
    """
    now = datetime.now(timezone.utc)
    link.last_synced_at = now
    if external_state == "closed":
        link.sync_status = "EXTERNAL_CLOSED"
        if defect.status != "CLOSED":
            defect.status = "CLOSED"
            append_system_note(defect, "外部工单已关闭，缺陷自动关闭（defect-sync）")
            return True
        return False
    if external_state == "reopened":
        link.sync_status = "SYNCED"
        if defect.status != "REOPENED":
            defect.status = "REOPENED"
            append_system_note(defect, "外部工单已重新打开，缺陷置 REOPENED（defect-sync）")
            return True
        return False
    if external_state == "open":
        link.sync_status = "SYNCED"
        if defect.status == "CLOSED":
            defect.status = "OPEN"
            append_system_note(defect, "外部工单处于打开态，缺陷回写 OPEN（defect-sync）")
            return True
        return False
    return False
