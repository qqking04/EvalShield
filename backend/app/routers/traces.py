# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M8：在线评测路由——trace 摄入 + 列表/详情 + 采样策略。

- POST /api/traces/ingest：通用推送接口（API Key 认证，复用 authenticate_request
  的 X-API-Key 通道）；批量 ≤100 条/请求（超出 400）；租户日限额
  daily_cap×5（超限 429）；request/response 截断存。
- GET /api/traces：列表（trace:read），按 eval_status/source/日期过滤。
- GET /api/traces/{trace_id}：详情（trace:read）。
- GET/PUT /api/traces/policy：策略读取/保存（trace:read / trace:manage）。
路由顺序：/policy 必须声明在 /{trace_id} 之前（字面量优先匹配）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from sqlalchemy import JSON, cast, func, or_

from ..database import get_db
from ..deps import AuthContext, require_permission, require_scope
from ..errors import BizError, NotFoundError
from ..models import Defect, Project, TargetRegistry, Trace, TracePolicy
from ..services.trace_recording import truncate_text

router = APIRouter()

DEFAULT_DAILY_CAP = 2000  # 与 DDL 默认值同口径（无策略行时的日限额基数）


def _day_start_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _trace_out(t: Trace, *, full: bool = False) -> dict[str, Any]:
    """序列化：列表默认截断预览，详情给全文。"""
    scores: dict[str, Any] = {}
    try:
        scores = json.loads(t.scores or "{}")
    except (ValueError, TypeError):
        pass
    out: dict[str, Any] = {
        "id": t.id,
        "tenant_id": t.tenant_id,
        "source": t.source,
        "external_ref": t.external_ref,
        "model": t.model,
        "tokens": t.tokens,
        "latency_ms": t.latency_ms,
        "status": t.status,
        "occurred_at": t.occurred_at.isoformat() if t.occurred_at else None,
        "eval_status": t.eval_status,
        "scores": scores.get("scores", {}),
        "overall": scores.get("overall"),
        "reviewed": t.reviewed,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
    if full:
        out["request"] = t.request
        out["response"] = t.response
        out["details"] = scores.get("details", {})
    else:
        out["request_preview"] = (t.request or "")[:120]
        out["response_preview"] = (t.response or "")[:120]
    return out


def _policy_out(p: TracePolicy | None) -> dict[str, Any]:
    if p is None:  # 未配置：回显默认值（enabled=False）
        return {
            "tenant_id": None, "enabled": False, "sample_rate": 0.1,
            "judge_metrics": ["pii_leak", "injection", "hallucination"],
            "daily_cap": DEFAULT_DAILY_CAP, "low_score_threshold": 0.6,
        }
    try:
        metrics = json.loads(p.judge_metrics or "[]")
    except (ValueError, TypeError):
        metrics = []
    return {
        "tenant_id": p.tenant_id,
        "enabled": p.enabled,
        "sample_rate": p.sample_rate,
        "judge_metrics": metrics,
        "daily_cap": p.daily_cap,
        "low_score_threshold": p.low_score_threshold,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _risk_level(overall: Any) -> str | None:
    """ES11 P9 风险等级：由质量分派生（高分=安全）。未评分返回 None。"""
    if overall is None:
        return None
    try:
        v = float(overall)
    except (TypeError, ValueError):
        return None
    if v < 0.4:
        return "HIGH"
    if v < 0.6:
        return "MEDIUM"
    if v < 0.8:
        return "LOW"
    return "SAFE"


def _enrich_traces(
    db: Session,
    rows: list[Trace],
    *,
    tenant_id: int | None = None,
) -> list[dict[str, Any]]:
    """批量富化 trace 列表（ES11 P9 增列，防 N+1）：

    - project_name / target_name：软引用名称（批量 IN 查询）
    - session_ref / trace_payload 存在性
    - risk_level：由 overall 派生；trigger_rule：最低分指标
    - reflow：回流状态（reviewed / 关联缺陷数）
    - recurrence：同会话引用下低分 trace 是否 ≥2 条
    """
    if not rows:
        return []

    trace_ids = [int(t.id) for t in rows]
    out = [_trace_out(t) for t in rows]

    project_ids = {int(t.project_id) for t in rows if t.project_id}
    target_ids = {int(t.target_id) for t in rows if t.target_id}

    project_map: dict[int, str] = {}
    if project_ids:
        project_map = {
            int(p.id): p.name
            for p in db.query(Project.id, Project.name).filter(Project.id.in_(project_ids)).all()
        }
    target_map: dict[int, str] = {}
    if target_ids:
        target_map = {
            int(t.id): t.name
            for t in db.query(TargetRegistry.id, TargetRegistry.name)
            .filter(TargetRegistry.id.in_(target_ids)).all()
        }

    # 回流缺陷计数：缺陷与 Trace 经 origin_type=TRACE / origin_id 软关联
    defect_counts: dict[int, int] = {}
    dq = (
        db.query(Defect.origin_id, func.count(Defect.id))
        .filter(Defect.origin_type == "TRACE", Defect.origin_id.in_(trace_ids),
                Defect.deleted_at.is_(None))
        .group_by(Defect.origin_id)
    )
    defect_counts = {int(r[0]): int(r[1]) for r in dq.all()}

    # 低分阈值（复发/风险口径统一）
    low_thresh = 0.6
    if tenant_id is not None:
        pol = db.query(TracePolicy).filter(TracePolicy.tenant_id == tenant_id).first()
        if pol and pol.low_score_threshold is not None:
            low_thresh = float(pol.low_score_threshold)

    # 会话复发：同 session_ref（优先 session_id，缺省 external_ref）下低分 ≥2 条
    session_keys: set[str] = set()
    for t in rows:
        key = t.session_id or t.external_ref
        if key:
            session_keys.add(key)
    low_by_session: dict[str, int] = {}
    if session_keys:
        sc_rows = (
            db.query(Trace.session_id, Trace.external_ref, Trace.scores, Trace.eval_status)
            .filter(
                or_(Trace.session_id.in_(session_keys), Trace.external_ref.in_(session_keys)),
                Trace.eval_status == "SCORED",
            )
            .all()
        )
        for sid, ext, raw, _status in sc_rows:
            try:
                overall = json.loads(raw or "{}").get("overall")
                low = overall is not None and float(overall) < low_thresh
            except (ValueError, TypeError):
                low = False
            if not low:
                continue
            for key in (sid, ext):
                if key in session_keys:
                    low_by_session[key] = low_by_session.get(key, 0) + 1

    for i, t in enumerate(rows):
        item = out[i]
        item["project_name"] = project_map.get(int(t.project_id)) if t.project_id else None
        item["target_name"] = target_map.get(int(t.target_id)) if t.target_id else None
        item["session_ref"] = t.session_id or t.external_ref
        item["has_payload"] = bool(t.trace_payload)
        item["risk_level"] = _risk_level(item.get("overall"))
        scores = item.get("scores") or {}
        if scores:
            worst = min(scores.items(), key=lambda kv: (kv[1] is None, kv[1]))
            item["trigger_rule"] = worst[0] if worst[1] is not None and float(worst[1]) < low_thresh else None
        else:
            item["trigger_rule"] = None
        item["defect_count"] = defect_counts.get(int(t.id), 0)
        skey = t.session_id or t.external_ref
        item["recurrence"] = bool(skey and low_by_session.get(skey, 0) >= 2)
    return out


@router.post("/ingest")
def ingest_traces(
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_scope("traces:write")),
    db: Session = Depends(get_db),
):
    """批量摄入 trace（API Key 认证；外部系统手工推送通道）。

    请求体：{"traces": [{"request","response","model","tokens","latency_ms",
    "external_ref","occurred_at"(ISO8601 可选)}, ...]}，≤100 条。
    """
    items = payload.get("traces") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise BizError("ES-M8-0001", "traces 必须为非空数组")
    if len(items) > 100:
        raise BizError("ES-M8-0002", "单次批量上限 100 条")

    tenant_id = int(auth.tenant_id or 0)
    if tenant_id <= 0:
        raise BizError("ES-M8-0003", "凭证缺少租户上下文")

    # 租户日限额：daily_cap×5（无策略行按默认 2000×5）
    pol = db.query(TracePolicy).filter(TracePolicy.tenant_id == tenant_id).first()
    cap = (int(pol.daily_cap) if pol else DEFAULT_DAILY_CAP) * 5
    today_count = (
        db.query(Trace)
        .filter(Trace.tenant_id == tenant_id, Trace.created_at >= _day_start_utc())
        .count()
    )
    if today_count + len(items) > cap:
        raise BizError(
            "ES-M8-0004", f"超出租户日摄入限额（今日 {today_count}/{cap}）",
            http_status=429,
        )

    created_ids: list[int] = []
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            raise BizError("ES-M8-0005", f"traces[{idx}] 必须为对象")
        req = str(it.get("request") or "").strip()
        resp = str(it.get("response") or "")
        if not req:
            raise BizError("ES-M8-0006", f"traces[{idx}].request 必填")
        occurred = datetime.now(timezone.utc)
        raw_occ = it.get("occurred_at")
        if raw_occ:
            try:
                occurred = datetime.fromisoformat(str(raw_occ).replace("Z", "+00:00"))
                if occurred.tzinfo is None:
                    occurred = occurred.replace(tzinfo=timezone.utc)
            except ValueError:
                raise BizError("ES-M8-0007", f"traces[{idx}].occurred_at 非 ISO8601")
        row = Trace(
            tenant_id=tenant_id,
            source="ingest_api",
            external_ref=(str(it.get("external_ref"))[:64] if it.get("external_ref") else None),
            request=truncate_text(req),
            response=truncate_text(resp),
            model=(str(it["model"])[:64] if it.get("model") else None),
            tokens=int(it["tokens"]) if it.get("tokens") is not None else None,
            latency_ms=int(it["latency_ms"]) if it.get("latency_ms") is not None else None,
            status="OK",
            occurred_at=occurred,
            eval_status="PENDING",
        )
        db.add(row)
        db.flush()
        created_ids.append(int(row.id))
    db.commit()
    from ..errors import ok

    return ok({"accepted": len(created_ids), "trace_ids": created_ids})


@router.get("/policy")
def get_policy(
    auth: AuthContext = Depends(require_permission("trace", "read")),
    db: Session = Depends(get_db),
):
    """读取当前租户采样策略（未配置回显默认值）。"""
    from ..errors import ok

    pol = db.query(TracePolicy).filter(TracePolicy.tenant_id == auth.tenant_id).first()
    return ok(_policy_out(pol))


@router.put("/policy")
def save_policy(
    payload: dict[str, Any],
    auth: AuthContext = Depends(require_permission("trace", "manage")),
    db: Session = Depends(get_db),
):
    """保存（upsert）当前租户采样策略。"""
    from ..errors import ok

    def _num(key: str, default: float, lo: float, hi: float) -> float:
        v = payload.get(key, default)
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise BizError("ES-M8-0008", f"{key} 必须为数字")
        if not (lo <= f <= hi):
            raise BizError("ES-M8-0009", f"{key} 须在 [{lo}, {hi}] 区间")
        return f

    metrics = payload.get("judge_metrics")
    if isinstance(metrics, list):
        metrics_json = json.dumps([str(m) for m in metrics if m], ensure_ascii=False)
    elif metrics is None:
        metrics_json = '["pii_leak","injection","hallucination"]'
    else:
        raise BizError("ES-M8-0010", "judge_metrics 必须为数组")

    pol = db.query(TracePolicy).filter(TracePolicy.tenant_id == auth.tenant_id).first()
    if pol is None:
        pol = TracePolicy(tenant_id=auth.tenant_id)
        db.add(pol)
        db.flush()  # 物化列默认值，否则未配置字段为 None 会误报 ES-M8-0008
    pol.enabled = bool(payload.get("enabled", pol.enabled))
    pol.sample_rate = _num("sample_rate", pol.sample_rate, 0.0, 1.0)
    pol.low_score_threshold = _num("low_score_threshold", pol.low_score_threshold, 0.0, 1.0)
    cap = payload.get("daily_cap", pol.daily_cap)
    try:
        cap_i = int(cap)
    except (TypeError, ValueError):
        raise BizError("ES-M8-0011", "daily_cap 必须为整数")
    if cap_i < 1:
        raise BizError("ES-M8-0012", "daily_cap 须 ≥1")
    pol.daily_cap = cap_i
    pol.judge_metrics = metrics_json
    db.commit()
    db.refresh(pol)
    return ok(_policy_out(pol))


@router.get("", dependencies=[Depends(require_scope("traces:read"))])
def list_traces(
    eval_status: str | None = Query(None, pattern=r"^(PENDING|SCORED|SKIPPED|FAILED)$"),
    source: str | None = Query(None, pattern=r"^(gateway|ingest_api)$"),
    low_only: bool = Query(False, description="只看低分（overall < 阈值或 reviewed）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    auth: AuthContext = Depends(require_permission("trace", "read")),
    db: Session = Depends(get_db),
):
    """trace 列表（租户隔离 + 过滤 + 分页）。

    ES11 P9 增列富化：项目/被测系统名称、会话引用、风险等级、触发规则、
    回流状态（缺陷/题目/回归计数）、是否复发（同会话低分）；批量查询防 N+1。
    """
    from ..errors import ok

    q = db.query(Trace)
    if not auth.is_super_admin:
        q = q.filter(Trace.tenant_id == auth.tenant_id)
    if eval_status:
        q = q.filter(Trace.eval_status == eval_status)
    if source:
        q = q.filter(Trace.source == source)
    if low_only:
        # Q-7：口径与 Query 描述一致——overall < 租户阈值（无策略行默认 0.6，
        # 与 _enrich_traces/_policy_out 同源）或已复核回流 reviewed=True。
        # scores 为 JSON 文本列，跨方言（PG/SQLite）用 JSON 访问器提取 overall。
        thresh = 0.6
        if not auth.is_super_admin:
            pol = db.query(TracePolicy).filter(TracePolicy.tenant_id == auth.tenant_id).first()
            if pol and pol.low_score_threshold is not None:
                thresh = float(pol.low_score_threshold)
        overall_low = cast(Trace.scores, JSON)["overall"].as_numeric() < thresh
        q = q.filter(or_(overall_low, Trace.reviewed.is_(True)))
    total = q.count()
    rows = (
        q.order_by(Trace.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    tenant_id = None if auth.is_super_admin else auth.tenant_id
    enriched = _enrich_traces(db, rows, tenant_id=tenant_id)
    return ok({
        "total": total, "page": page, "page_size": page_size,
        "items": enriched,
    })


@router.get("/{trace_id}", dependencies=[Depends(require_scope("traces:read"))])
def get_trace(
    trace_id: int,
    auth: AuthContext = Depends(require_permission("trace", "read")),
    db: Session = Depends(get_db),
):
    """trace 详情（request/response 全文 + 评分明细）。"""
    from ..errors import ok

    t = db.get(Trace, trace_id)
    if t is None:
        raise NotFoundError("ES-M8-0013", "trace 不存在")
    if not auth.is_super_admin and t.tenant_id != auth.tenant_id:
        raise NotFoundError("ES-M8-0013", "trace 不存在")  # 跨租户不暴露存在性
    return ok(_trace_out(t, full=True))
