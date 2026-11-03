# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""报告生成服务：统一入口，集成审计轨迹摘要。

在报告导出（PDF/JSON/MD）时，自动附加一页/一节「审计轨迹摘要」。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import DiscoverJob, TestCase
from ..utils.audit_chain import verify_chain

logger = logging.getLogger("evalshield.report")

# ES9-P-15：展示层统一按北京时间（UTC+8）标注，存储层保持 UTC 不变
_UTC8 = timezone(timedelta(hours=8))


def format_utc8(iso_ts: str) -> str:
    """将 UTC ISO 时间串换算为北京时间展示串（YYYY-MM-DD HH:MM:SS）。"""
    try:
        return datetime.fromisoformat(iso_ts).astimezone(_UTC8).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(iso_ts)


def build_ai_probe_summary(db: Session, project_id: int) -> dict[str, Any]:
    """A14/PO-09：AI 探测来源统计，供任务报告 summary 合并。

    - ai_case_count：项目内 source='AGENT_GEN'（AI 探测生成）用例数
    - ai_confidence：项目最近一次 DiscoverJob.preview_payload.confidence（无则 None）
    异常时回退默认值，绝不阻断报告主流程。
    """
    result: dict[str, Any] = {"ai_case_count": 0, "ai_confidence": None}
    try:
        result["ai_case_count"] = (
            db.query(TestCase)
            .filter(
                TestCase.project_id == project_id,
                TestCase.source == "AGENT_GEN",
                TestCase.deleted_at.is_(None),
            )
            .count()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("报告 AI 用例数统计失败（不影响主流程）: %s", exc)
        db.rollback()
    try:
        job = (
            db.query(DiscoverJob)
            .filter(
                DiscoverJob.project_id == project_id,
                DiscoverJob.deleted_at.is_(None),
            )
            .order_by(DiscoverJob.id.desc())
            .first()
        )
        payload = job.preview_payload if job and isinstance(job.preview_payload, dict) else {}
        if payload.get("confidence") is not None:
            result["ai_confidence"] = payload.get("confidence")
    except Exception as exc:  # noqa: BLE001
        logger.warning("报告 AI 置信度统计失败（不影响主流程）: %s", exc)
        db.rollback()
    return result


def build_audit_trail_summary(
    db: Session, start_time: datetime | None = None, end_time: datetime | None = None
) -> dict[str, Any]:
    """生成审计轨迹摘要字典，供 PDF/JSON/MD 模板填充。"""
    chain = verify_chain(db)
    summary = {
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "chain_valid": chain["valid"],
        "total_logs": chain["total"],
        "first_index": chain["first_index"],
        "last_index": chain["last_index"],
        "break_count": len(chain["breaks"]),
        "missing_count": len(chain["missing_indices"]),
        "breaks": chain["breaks"],
        "missing_indices": chain["missing_indices"],
    }
    if start_time or end_time:
        summary["time_range"] = {
            "start": start_time.isoformat() if start_time else None,
            "end": end_time.isoformat() if end_time else None,
        }
    return summary


def append_audit_to_json(report_data: dict, summary: dict) -> dict:
    """将审计轨迹摘要追加到 JSON 报告数据。"""
    report_data["audit_trail"] = summary
    return report_data


def append_audit_to_md(md_lines: list[str], summary: dict) -> list[str]:
    """将审计轨迹摘要追加到 Markdown 报告行列表。"""
    md_lines.extend(
        [
            "\n## 附录：审计轨迹摘要\n",
            f"- **检测时间**：{summary['detected_at']}（北京时间 {format_utc8(summary['detected_at'])} UTC+8）",
            f"- **日志总条数**：{summary['total_logs']}",
            f"- **链式序号范围**：{summary['first_index']} ~ {summary['last_index']}",
            f"- **校验链状态**：{'有效' if summary['chain_valid'] else '**断裂**'}",
        ]
    )
    if summary["breaks"]:
        md_lines.append("- **断裂明细**：")
        for b in summary["breaks"]:
            md_lines.append(f"  - index={b['chain_index']}: hash mismatch")
    return md_lines


# ---------------------------------------------------------------------------
# 安全报告补全 P2（差异测试 BUG-14）：报告 environment 事后回填
# ---------------------------------------------------------------------------
_DEFAULT_AUTHORIZATION = "已确认属用户自有系统并获授权"
_DEFAULT_TEST_METHOD = "HTTP 请求探测 + API 鉴权探测 + 静态资源分析"

# 引擎编码 → 检测方法片段（用于从任务步骤推导 test_method）
_ENGINE_METHOD_HINTS = {
    "CREDENTIAL_STORAGE_TEST": "浏览器自动化",
    "UI_TEST": "浏览器自动化",
    "HTTP_SECURITY_HEADERS": "HTTP 请求探测",
    "TLS_CHECK": "传输层加密探测",
    "STATIC_SECRET_SCAN": "静态资源分析",
    "RBAC_TEST": "API 鉴权探测",
    "SECURITY_TEST": "API 鉴权探测",
    "PROMPT_INJECTION": "模型对抗探测",
    "PRIVILEGE_ESCALATION": "API 鉴权探测",
    "REDTEAM_TEST": "模型对抗探测",
    "MEMORY_LEAKAGE": "多轮会话探测",
    "PUBLIC_ENDPOINT_TEST": "HTTP 请求探测",
    "FUNCTIONAL_DEFECT_TEST": "业务数据校验",
}


def enrich_report_environment(db: Session, report_id: int) -> dict[str, Any]:
    """报告生成后补全 environment（authorization / test_accounts / test_method）。

    - 数据来源：报告关联任务（TestTask）与步骤（TaskStep）的配置，逐层回填；
    - 幂等：已有值的键不覆盖，仅补空缺；重复调用结果一致；
    - 历史报告（environment 为空）也可回填。

    返回补全后的 environment 字典（报告不存在时返回空字典）。
    """
    from ..models import Report, TaskStep, TestTask

    report = db.get(Report, report_id)
    if report is None or report.deleted_at is not None:
        return {}

    env = dict(report.environment or {})

    task = db.get(TestTask, report.task_id) if report.task_id else None
    steps: list[TaskStep] = []
    if task is not None:
        steps = (
            db.query(TaskStep)
            .filter(TaskStep.task_id == task.id)
            .order_by(TaskStep.seq)
            .all()
        )

    cfg = dict(task.config or {}) if task else {}

    # 1) authorization：任务配置显式声明 > 步骤配置 > 平台默认声明
    if not env.get("authorization"):
        authorization = cfg.get("authorization")
        if not authorization:
            for s in steps:
                sc = dict(s.config or {})
                authorization = sc.get("authorization")
                if authorization:
                    break
        env["authorization"] = authorization or _DEFAULT_AUTHORIZATION

    # 2) test_accounts：任务配置 accounts 优先，其次步骤 config.auth.username（脱敏，不含密码）
    if not env.get("test_accounts"):
        accounts: list[dict[str, str]] = []
        raw = cfg.get("test_accounts") or cfg.get("accounts")
        if isinstance(raw, list):
            for a in raw:
                if isinstance(a, dict) and a.get("username"):
                    accounts.append({
                        "username": str(a.get("username")),
                        "display_name": str(a.get("display_name") or a.get("username")),
                        "role": str(a.get("role") or ""),
                    })
        if not accounts:
            seen: set[str] = set()
            for s in steps:
                sc = dict(s.config or {})
                auth_cfg = sc.get("auth") or {}
                if isinstance(auth_cfg, dict) and auth_cfg.get("username"):
                    uname = str(auth_cfg["username"])
                    if uname in seen:
                        continue
                    seen.add(uname)
                    accounts.append({
                        "username": uname,
                        "display_name": str(auth_cfg.get("display_name") or uname),
                        "role": str(auth_cfg.get("role") or ""),
                    })
        if accounts:
            env["test_accounts"] = accounts

    # 3) test_method：从任务引擎链推导；无任务信息时用默认描述
    if not env.get("test_method"):
        methods: list[str] = []
        engine_codes = list(task.engines or []) if task else []
        if not engine_codes:
            engine_codes = [s.engine_code for s in steps if s.engine_code]
        for code in engine_codes:
            hint = _ENGINE_METHOD_HINTS.get(str(code))
            if hint and hint not in methods:
                methods.append(hint)
        env["test_method"] = " + ".join(methods) if methods else _DEFAULT_TEST_METHOD

    # 4) sut_url：任务配置 base_url 兜底
    if not env.get("sut_url"):
        base_url = cfg.get("base_url") or cfg.get(f"config__HTTP_SECURITY_HEADERS__base_url")
        if base_url:
            env["sut_url"] = str(base_url)

    report.environment = env
    db.commit()
    db.refresh(report)
    return env
