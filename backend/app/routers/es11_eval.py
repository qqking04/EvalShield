# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""ES11：准备度（G0）、统一运行工作台、基线与回归差异路由（开发方案 §3.1-§3.3）。

服务文件不属于 engines 目录（AGENTS.md 锁 1）。全部接口 authenticate_request
+ 租户范围校验；响应统一 {code, message, data}。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import AuthContext, authenticate_request, ensure_data_scope, require_permission
from ..errors import BizError, NotFoundError
from ..models import AuditLog, Defect, EvalRun, EvalRunItem, Report
from ..services import gate_service

router = APIRouter()

TRUNC = 512


def _load_run(db: Session, run_id: int, auth: AuthContext) -> EvalRun:
    run = db.get(EvalRun, run_id)
    if run is None or run.deleted_at is not None:
        raise NotFoundError(message=f"运行 {run_id} 不存在")
    return run


async def _run_in_scope(db: Session, run_id: int, auth: AuthContext) -> EvalRun:
    run = _load_run(db, run_id, auth)
    await ensure_data_scope(auth, resource_tenant_id=run.tenant_id)
    return run


def _clip(s: str | None) -> str | None:
    if s is None:
        return None
    return s if len(s) <= TRUNC else s[:TRUNC] + "…"


# --------------------------------------------------------------------- G0


@router.post("/eval-runs/readiness", response_model=dict)
def eval_run_readiness(
    payload: dict,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """G0 准备度预检（§3.1）：只读检查，不落库、不抛错（BLOCK 也正常返回）。"""
    out = gate_service.check_readiness(db, payload or {}, auth)
    return {"code": 0, "message": "ok", "data": out}


# ------------------------------------------------------------- 运行工作台


@router.get("/eval-runs/{run_id}/workspace", response_model=dict)
def eval_run_workspace(
    run_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """统一运行工作台聚合（§3.2）：run/snapshot/gates/review/defects/baseline/report。

    同步 def：聚合查询为阻塞 IO，交给 Starlette 线程池并发执行
    （ES11-PERF-002：async 端点内直跑 SQLAlchemy 会串行化事件循环，压测 P95 超标）。
    """
    run = _load_run(db, run_id, auth)
    asyncio.run(ensure_data_scope(auth, resource_tenant_id=run.tenant_id))
    snap = run.run_snapshot or {}
    # G0：创建时固化的 readiness 摘要（存量运行无 → UNKNOWN）
    readiness = snap.get("readiness")
    if readiness is None:
        g0 = "UNKNOWN"
    else:
        g0 = "PASS" if readiness.get("ready") else "BLOCKED"

    mix = gate_service.failure_mix(db, int(run.id))
    prog = gate_service.review_progress(db, int(run.id))
    g2 = gate_service.g2_gate(db, run)

    tenant_id = run.tenant_id or 1
    d_q = db.query(Defect).filter(
        Defect.tenant_id == tenant_id, Defect.deleted_at.is_(None)
    )
    defects_total = d_q.count()
    open_p0p1 = (
        d_q.filter(Defect.severity.in_(("P0", "P1")),
                   Defect.status.in_(("NEW", "OPEN", "FIXED", "VERIFYING", "REOPENED")))
        .count()
    )
    fixed_unverified = d_q.filter(Defect.status.in_(("FIXED", "VERIFYING"))).count()

    # 基线差异摘要：优先 run.baseline_run_id，否则同题库最近 is_baseline 运行
    baseline = None
    if run.baseline_run_id:
        baseline = db.get(EvalRun, int(run.baseline_run_id))
    if baseline is None:
        baseline = (
            db.query(EvalRun)
            .filter(
                EvalRun.tenant_id == tenant_id, EvalRun.deleted_at.is_(None),
                EvalRun.id != run.id,
                EvalRun.run_snapshot["is_baseline"].astext == "true",
            )
            .order_by(EvalRun.id.desc())
            .first()
        )
    baseline_diff = None
    if baseline is not None:
        comparable, reasons = gate_service.baseline_comparable(run, baseline)
        counts = _compare_counts(db, run, baseline) if comparable else None
        baseline_diff = {
            "baseline_run_id": int(baseline.id),
            "comparable": comparable,
            "diff_reasons": reasons,
            "new_fail": (counts or {}).get("NEW_FAIL", 0),
            "fixed": (counts or {}).get("FIXED", 0),
            "still_fail": (counts or {}).get("STILL_FAIL", 0),
        }

    report = db.get(Report, int(run.report_id)) if run.report_id else None
    deliverable = None
    if report is not None:
        deliverable = gate_service.delivery_readiness(db, run, report)["deliverable"]

    # ES11 P3：红队运行的攻击轨迹页签数据（仅 JAILBREAK/REDTEAM_TEST 引擎组装；
    # 口径与 redteam.campaigns 一致——detail.bypassed 或 verdict==BYPASSED 计绕过）
    is_redteam = str(run.engine_code or "").upper() in ("JAILBREAK", "REDTEAM_TEST")
    redteam = None
    if is_redteam:
        # ES11 修复：按 seq 反查 eval_run_items 补题级 ID，红队轨迹转缺陷
        # 同口径携带 RUN_ITEM 血缘（复测自动绑题依赖该血缘）
        item_id_by_seq = {
            int(it.seq): int(it.id)
            for it in db.query(EvalRunItem).filter(EvalRunItem.run_id == run.id).all()
        }
        traces: list[dict] = []
        bypassed_n = 0
        for idx, row in enumerate(run.item_results or []):
            detail = row.get("detail") if isinstance(row, dict) else None
            if not isinstance(detail, dict):
                continue
            is_by = bool(detail.get("bypassed")) or str(row.get("verdict") or "") == "BYPASSED"
            bypassed_n += 1 if is_by else 0
            traces.append({
                "seq": idx + 1,
                "item_id": item_id_by_seq.get(idx + 1),
                "framework_code": str(detail.get("framework_code") or ""),
                "payload": str(detail.get("prompt") or row.get("prompt") or "")[:TRUNC],
                "verdict": str(row.get("verdict") or ""),
                "bypassed": is_by,
                "rounds": detail.get("rounds") if isinstance(detail.get("rounds"), int) else None,
            })
        redteam = {
            "traces": traces[:200],  # 单运行投递上限口径；超出部分不逐条展示
            "totals": {"attempts": len(traces), "bypassed": bypassed_n},
        }

    # ES11 P3：运行审计页签——与本运行路径相关的操作日志（冻结/基线/复核等写操作）
    a_q = db.query(AuditLog).filter(
        AuditLog.tenant_id == tenant_id,
        text("path ILIKE :p").bindparams(p=f"%runs/{run.id}%"),
    )
    audit_total = a_q.count()
    audit_items = [
        {
            "log_no": a.log_no, "username": a.username, "action": a.action,
            "module": a.module, "method": a.method, "path": a.path,
            "result": a.result, "ip": a.ip, "error_msg": a.error_msg,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in a_q.order_by(AuditLog.id.desc()).limit(50).all()
    ]

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "run": {
                "id": run.id, "run_no": run.run_no, "status": run.status,
                "run_purpose": run.run_purpose, "verdict": run.verdict,
                "target_id": run.target_id, "target_type": run.target_type,
                "judge_mode": run.judge_mode, "judge_model": run.judge_model,
                "question_bank_id": run.question_bank_id,
                "project_version_id": run.project_version_id,
                "parent_run_id": run.parent_run_id,
                "overall_score": run.overall_score, "summary": run.summary,
                "started_at": run.started_at, "finished_at": run.finished_at,
                "concluded": gate_service.concluded(db, run),
            },
            "snapshot": snap,
            "gates": {
                "G0": g0,
                "G1": mix,
                "G2": {"pending_review": prog["pending"], "status": g2},
                "G3": {"open_p0p1": open_p0p1},
                "G4": "PASS" if deliverable else "BLOCKED" if deliverable is False else "NO_REPORT",
            },
            "review_progress": prog,
            "judge_health": gate_service.judge_health(db, run),
            "rag": gate_service.rag_summary(db, int(run.id)),
            "redteam": redteam,
            "audit": {"items": audit_items, "total": audit_total},
            "defects": {"total": defects_total, "open_p0p1": open_p0p1,
                        "fixed_unverified": fixed_unverified},
            "baseline_diff": baseline_diff,
            "report": None if report is None else {
                "id": report.id, "report_no": report.report_no,
                "status": report.status, "deliverable": deliverable,
            },
        },
    }


@router.get("/eval-runs/{run_id}/dimension-coverage", response_model=dict)
def eval_run_dimension_coverage(
    run_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("eval", "read")),
):
    """五维度双轨覆盖矩阵（优化12 §8.3/§8.7）：旧口径 run 返回 coverage:null。

    同步 def（PERF-003）：阻塞 SQLAlchemy；判定唯一实现在 services/dimension_coverage。
    功能权限口径 TC-M3-009：eval:read 守卫（BUG-001 修复），数据面另有租户隔离。
    """
    from ..services import dimension_coverage

    run = _load_run(db, run_id, auth)
    asyncio.run(ensure_data_scope(auth, resource_tenant_id=run.tenant_id))
    ver = dimension_coverage.resolve_effective_standards_ver(db, run)
    cov = dimension_coverage.coverage_matrix(db, run, auth=auth)
    return {"code": 0, "message": "ok", "data": {
        "standards_ver": ver, "coverage": cov,
    }}


@router.get("/eval-runs/{run_id}/items", response_model=dict)
def eval_run_items(
    run_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    verdict: str | None = None,
    failure_class: str | None = Query(None, pattern="^(CONFIG|INFRA|QUALITY)$"),
    needs_review: bool | None = None,
    rag: str | None = Query(
        None, pattern="^(NO_HIT|LOW_RECALL|LOW_FAITH|CITATION_ERROR|ACL|UNGROUNDED)$"),
    item_id: int | None = None,
    full: bool = False,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """题级明细分页（§3.2）：单页 ≤50；长文本默认截断 512，full=1 且单条才回全文。

    同步 def：函数体为阻塞 SQLAlchemy，async 会串行化事件循环（ES11-PERF-003）。
    """
    run = asyncio.run(_run_in_scope(db, run_id, auth))
    q = db.query(EvalRunItem).filter(EvalRunItem.run_id == run.id)
    if verdict:
        q = q.filter(EvalRunItem.final_verdict == verdict.upper())
    if failure_class:
        q = q.filter(EvalRunItem.evidence_payload["failure_class"].astext == failure_class)
    if needs_review is True:
        q = q.filter(EvalRunItem.review_status == "pending")
    elif needs_review is False:
        q = q.filter(EvalRunItem.review_status != "pending")
    if rag:
        # RAG 阶段诊断过滤（P7）：谓词与 rag_summary 单源（gate_service.RAG_PREDICATES）
        q = q.filter(text(gate_service.RAG_PREDICATES[rag]))
    if item_id:
        q = q.filter(EvalRunItem.id == item_id)
    total = q.count()
    rows = q.order_by(EvalRunItem.seq.asc(), EvalRunItem.id.asc()).offset((page - 1) * page_size).limit(page_size).all()
    single_full = bool(full and item_id)
    items = []
    for it in rows:
        d = {
            "id": it.id, "seq": it.seq, "question_id": it.question_id,
            "split": it.split, "category": it.category,
            "prompt": it.prompt if single_full else _clip(it.prompt),
            "response": it.response if single_full else _clip(it.response),
            "response_ref": it.response_ref,
            "rule_verdict": it.rule_verdict, "judge_verdict": it.judge_verdict,
            "final_verdict": it.final_verdict, "verdict_reason": it.verdict_reason,
            "judge_model": it.judge_model, "judge_prompt_hash": it.judge_prompt_hash,
            "judge_agreement": it.judge_agreement,
            "review_status": it.review_status, "latency_ms": it.latency_ms,
            "evidence_payload": it.evidence_payload, "evidence_ref": it.evidence_ref,
        }
        if not single_full and isinstance(d["evidence_payload"], dict):
            ep = dict(d["evidence_payload"])
            for k in ("retrieval", "citations", "spans"):
                if k in ep:
                    ep[k] = _clip(str(ep[k]))
            d["evidence_payload"] = ep
        items.append(d)
    return {"code": 0, "message": "ok", "data": {
        "items": items, "total": total, "page": page, "page_size": page_size,
    }}


# --------------------------------------------------------- 基线与回归差异


@router.put("/eval-runs/{run_id}/baseline", response_model=dict)
def set_baseline(
    run_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """设为基线（§3.3）：G2 未过抛 ES-BIZ-BASE-0001；同租户同题库旧基线取消标记。"""
    run = asyncio.run(_run_in_scope(db, run_id, auth))
    if gate_service.g2_gate(db, run) != gate_service.PASS:
        raise BizError("ES-BIZ-BASE-0001", "强制复核未全部完成，该运行不能作为基线（G2 未通过）")
    if run.status not in ("PASSED", "SUCCESS", "FAILED"):
        raise BizError("ES-BIZ-BASE-0001", f"运行未完成（{run.status}），不能作为基线")
    snap = dict(run.run_snapshot or {})
    snap["is_baseline"] = True
    run.run_snapshot = snap
    # 取消同租户同题库的旧基线标记
    old_rows = (
        db.query(EvalRun)
        .filter(EvalRun.tenant_id == run.tenant_id, EvalRun.deleted_at.is_(None),
                EvalRun.id != run.id, EvalRun.question_bank_id == run.question_bank_id)
        .all()
    )
    for r in old_rows:
        s = r.run_snapshot or {}
        if s.get("is_baseline"):
            s2 = dict(s)
            s2["is_baseline"] = False
            r.run_snapshot = s2
    db.commit()
    return {"code": 0, "message": "ok", "data": {"run_id": run.id, "is_baseline": True}}


@router.put("/eval-runs/{run_id}/link-report", response_model=dict)
def link_report(
    run_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """关联产出报告（ES11 E2E 修复）：写 eval_runs.report_id，打通 G4 交付判定。

    任务链自动报告由 task_runner 回填；题库直发运行此前无任何关联手段，
    G4 delivery-readiness 恒 RUN_LINK BLOCK。本端点为人工/前端补链入口，
    幂等覆盖（重新出报告指向新报告）。
    """
    run = asyncio.run(_run_in_scope(db, run_id, auth))
    report_id = body.get("report_id")
    if not report_id:
        raise BizError("ES-BIZ-LINK-0001", "缺少 report_id")
    rep = db.get(Report, int(report_id))
    if rep is None or rep.deleted_at is not None:
        raise NotFoundError("ES-BIZ-REPORT-0001", "报告不存在")
    asyncio.run(ensure_data_scope(auth, resource_tenant_id=rep.tenant_id))
    run.report_id = int(rep.id)
    db.commit()
    return {"code": 0, "message": "ok", "data": {
        "run_id": int(run.id), "report_id": int(rep.id),
        "report_no": rep.report_no,
    }}


def _verdict_bucket(v: str | None) -> str:
    return "PASS" if (v or "").upper() == "PASS" else "FAIL"


def _item_map(db: Session, run_id: int) -> dict:
    """题项轻量映射（PERF-005）：仅取对齐/摘要所需列，避免 1 万题 ORM 全量实例化。"""
    out: dict = {}
    rows = (
        db.query(EvalRunItem.id, EvalRunItem.seq, EvalRunItem.question_id,
                 EvalRunItem.prompt, EvalRunItem.final_verdict,
                 EvalRunItem.evidence_payload)
        .filter(EvalRunItem.run_id == run_id)
        .all()
    )
    for row in rows:
        out[gate_service.item_key(row)] = row
    return out


def _compare_counts(db: Session, run: EvalRun, baseline: EvalRun) -> dict[str, int]:
    cur = _item_map(db, int(run.id))
    base = _item_map(db, int(baseline.id))
    c = {"NEW_FAIL": 0, "FIXED": 0, "STILL_FAIL": 0, "STILL_PASS": 0,
         "NEW_SAMPLE": 0, "REMOVED_SAMPLE": 0}
    for k, it in cur.items():
        if k not in base:
            c["NEW_SAMPLE"] += 1
            continue
        b, a = _verdict_bucket(base[k].final_verdict), _verdict_bucket(it.final_verdict)
        if b == "FAIL" and a == "FAIL":
            c["STILL_FAIL"] += 1
        elif b == "FAIL":
            c["FIXED"] += 1
        elif a == "FAIL":
            c["NEW_FAIL"] += 1
        else:
            c["STILL_PASS"] += 1
    for k in base:
        if k not in cur:
            c["REMOVED_SAMPLE"] += 1
    return c


@router.get("/eval-runs/{run_id}/compare", response_model=dict)
def compare_run(
    run_id: int,
    baseline_run_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """基线对比（§3.3）：七类差异 + same_condition + diff_reasons。

    同步 def（PERF-005）：函数体为阻塞 SQLAlchemy，async 会串行化事件循环；
    ensure_data_scope 为纯内存校验，用 asyncio.run 包裹。
    """
    run = asyncio.run(_run_in_scope(db, run_id, auth))
    baseline = _load_run(db, baseline_run_id, auth)
    asyncio.run(ensure_data_scope(auth, resource_tenant_id=baseline.tenant_id))
    comparable, reasons = gate_service.baseline_comparable(run, baseline)
    if not comparable:
        data: dict = {
            "same_condition": False, "diff_reasons": reasons,
            "categories": {"NOT_COMPARABLE": None},  # 差值统一 null（§9.4-3）
            "items": [],
        }
        # 优化12 §9.4：standards_ver 口径不一致时护栏注记必现 + 双列透出
        if "standards_ver" in reasons:
            from ..services import dimension_coverage

            cur_ver = dimension_coverage.resolve_effective_standards_ver(db, run)
            base_ver = dimension_coverage.resolve_effective_standards_ver(db, baseline)
            data["standards_ver"] = {"current": cur_ver, "baseline": base_ver}
            data["caliber_note"] = (
                f"基线运行按 {base_ver or '旧口径'} 口径出具，与本次 "
                f"{cur_ver or '旧口径'} 口径不可直接比较，"
                "合格率差异不构成功能回归结论"
            )
        return {"code": 0, "message": "ok", "data": data}
    cur = _item_map(db, int(run.id))
    base = _item_map(db, int(baseline.id))
    cats: dict[str, list[dict]] = {k: [] for k in
                                   ("NEW_FAIL", "FIXED", "STILL_FAIL", "STILL_PASS",
                                    "NEW_SAMPLE", "REMOVED_SAMPLE")}
    for k, it in cur.items():
        b = base.get(k)
        if b is None:
            cats["NEW_SAMPLE"].append(_brief(it))
            continue
        bv, av = _verdict_bucket(b.final_verdict), _verdict_bucket(it.final_verdict)
        if bv == "FAIL" and av == "FAIL":
            cats["STILL_FAIL"].append(_brief(it))
        elif bv == "FAIL":
            cats["FIXED"].append(_brief(it))
        elif av == "FAIL":
            cats["NEW_FAIL"].append(_brief(it))
        else:
            cats["STILL_PASS"].append(_brief(it))
    for k, b in base.items():
        if k not in cur:
            cats["REMOVED_SAMPLE"].append(_brief(b))
    counts = {k: len(v) for k, v in cats.items()}
    return {"code": 0, "message": "ok", "data": {
        "same_condition": True, "diff_reasons": [],
        "counts": counts, "categories": cats,
    }}


def _brief(it: EvalRunItem) -> dict:
    return {
        "id": it.id, "seq": it.seq, "question_id": it.question_id,
        "final_verdict": it.final_verdict,
        "failure_class": (it.evidence_payload or {}).get("failure_class"),
        "prompt": _clip(it.prompt),
    }


# ------------------------------------------------------- 题库治理视图（§17.2）


@router.get("/question-banks/{bank_id}/governance", response_model=dict)
def bank_governance(
    bank_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """题库治理聚合（优化11.md §17.2，R1 补充）：只读派生，无新表新列。

    四块：usage（使用活动/基线）、layering（分层与类别覆盖）、
    hygiene（生产回流占比 + 重复样本）、defects（关联缺陷与最近复测）。
    同步 def（PERF-003）。
    """
    from ..models import DefectEvent, Question, QuestionBank

    bank = db.get(QuestionBank, bank_id)
    if bank is None or getattr(bank, "deleted_at", None) is not None:
        raise NotFoundError(message=f"题库 {bank_id} 不存在")
    asyncio.run(ensure_data_scope(auth, resource_tenant_id=bank.tenant_id))

    run_ids = [
        int(r[0])
        for r in db.query(EvalRun.id)
        .filter(EvalRun.question_bank_id == bank_id, EvalRun.deleted_at.is_(None))
        .all()
    ]
    recent_rows = (
        db.query(EvalRun.id, EvalRun.run_no, EvalRun.run_purpose, EvalRun.status,
                 EvalRun.created_at)
        .filter(EvalRun.question_bank_id == bank_id, EvalRun.deleted_at.is_(None))
        .order_by(EvalRun.id.desc()).limit(8).all()
    )
    baseline_runs = (
        db.query(func.count(EvalRun.id))
        .filter(EvalRun.id.in_(run_ids),
                EvalRun.run_snapshot["is_baseline"].astext == "true")
        .scalar()
    ) if run_ids else 0
    used_as_baseline = (
        db.query(func.count(EvalRun.id))
        .filter(EvalRun.baseline_run_id.in_(run_ids), EvalRun.deleted_at.is_(None))
        .scalar()
    ) if run_ids else 0

    # 分层与类别：直接按题库题目聚合（split 含 HOLDOUT=生产回流默认分层）
    split_rows = (
        db.query(Question.split, func.count(Question.id))
        .filter(Question.bank_id == bank_id, Question.deleted_at.is_(None))
        .group_by(Question.split).all()
    )
    splits = {str(s or "UNKNOWN"): int(c) for s, c in split_rows}
    q_total = sum(splits.values())
    cat_rows = (
        db.query(Question.category, func.count(Question.id))
        .filter(Question.bank_id == bank_id, Question.deleted_at.is_(None))
        .group_by(Question.category)
        .order_by(func.count(Question.id).desc()).limit(10).all()
    )
    reflow_count = (
        db.query(func.count(Question.id))
        .filter(Question.bank_id == bank_id, Question.deleted_at.is_(None),
                text("meta ? 'source_trace_id'"))
        .scalar()
    )
    dup = db.execute(text(
        "SELECT count(*) AS groups, COALESCE(sum(n),0) AS items FROM ("
        " SELECT md5(text) AS k, count(*) AS n FROM question"
        " WHERE bank_id=:b AND deleted_at IS NULL GROUP BY md5(text) HAVING count(*)>1"
        ") t"), {"b": bank_id}).first()

    # 关联缺陷：origin=RUN_ITEM 且来源运行使用本库；附最近复测/验证事件
    d_items: list[dict] = []
    open_p0p1 = 0
    if run_ids:
        d_rows = (
            db.query(Defect.id, Defect.defect_no, Defect.title, Defect.severity,
                     Defect.status, Defect.origin_id)
            .filter(
                Defect.deleted_at.is_(None),
                Defect.origin_type == "RUN_ITEM",
                Defect.origin_id.in_(
                    db.query(EvalRunItem.id).filter(EvalRunItem.run_id.in_(run_ids))
                ),
            )
            .order_by(Defect.id.desc()).limit(10).all()
        )
        open_st = ("NEW", "OPEN", "FIXED", "VERIFYING", "REOPENED")
        for row in d_rows:
            if row.severity in ("P0", "P1") and row.status in open_st:
                open_p0p1 += 1
            ev = (
                db.query(DefectEvent.event_type, DefectEvent.created_at)
                .filter(DefectEvent.defect_id == row.id,
                        DefectEvent.event_type.in_(("RETEST_STARTED", "VERIFIED")))
                .order_by(DefectEvent.id.desc()).first()
            )
            d_items.append({
                "id": row.id, "defect_no": row.defect_no, "title": _clip(row.title),
                "severity": row.severity, "status": row.status,
                "last_retest_event": ev[0] if ev else None,
                "last_retest_at": ev[1] if ev else None,
            })

    return {"code": 0, "message": "ok", "data": {
        "bank": {"id": bank.id, "name": bank.name,
                 "question_count": bank.question_count},
        "usage": {
            "total_runs": len(run_ids),
            "baseline_runs": int(baseline_runs or 0),
            "used_as_baseline": int(used_as_baseline or 0),
            "recent": [
                {"id": r[0], "run_no": r[1], "run_purpose": r[2], "status": r[3],
                 "created_at": r[4]} for r in recent_rows
            ],
        },
        "layering": {
            "splits": splits, "total": q_total,
            "categories": [{"category": str(c[0] or "未分类"), "count": int(c[1])}
                           for c in cat_rows],
        },
        "hygiene": {
            "reflow_count": int(reflow_count or 0),
            "reflow_rate": round((reflow_count or 0) / q_total, 4) if q_total else None,
            "duplicate_groups": int(dup[0] or 0),
            "duplicate_items": int(dup[1] or 0),
        },
        "defects": {"total": len(d_items), "open_p0p1": open_p0p1, "items": d_items},
    }}
