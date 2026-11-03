# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""ES11：缺陷闭环路由（开发方案 §3.4/§4，G3 门禁）。

timeline / remediation / retest / verify / reopen 五接口；
defect_events 只追加（services/defect_events.py），CLOSED 仅经 verify 产生。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import AuthContext, authenticate_request, ensure_data_scope, require_permission
from ..errors import BizError, NotFoundError
from ..models import Defect, EvalRun, EvalRunItem, Question, QuestionBank
from ..services import bank_executor, defect_events, gate_service
from ..utils.no import gen_no

logger = logging.getLogger(__name__)
router = APIRouter()


def _load_defect(db: Session, defect_id: int, auth: AuthContext) -> Defect:
    d = db.get(Defect, defect_id)
    if d is None or d.deleted_at is not None:
        raise NotFoundError("ES-BIZ-DEFECT-0001", "缺陷不存在")
    return d


async def _defect_in_scope(db: Session, defect_id: int, auth: AuthContext) -> Defect:
    d = _load_defect(db, defect_id, auth)
    await ensure_data_scope(auth, resource_tenant_id=d.tenant_id)
    return d


# ------------------------------------------------------------------ timeline


@router.get("/defects/{defect_id}/timeline", response_model=dict)
def defect_timeline(
    defect_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """闭环时间线（§3.4）：defect_events 全量 + 实体链接（运行/报告/复测）。

    同步 def：函数体为阻塞 SQLAlchemy，async 会串行化事件循环（ES11-PERF-006）。
    """
    d = asyncio.run(_defect_in_scope(db, defect_id, auth))
    evs = defect_events.timeline(db, int(d.id))
    run_ids = {int(e.run_id) for e in evs if e.run_id}
    runs = {}
    if run_ids:
        for r in db.query(EvalRun).filter(EvalRun.id.in_(run_ids)).all():
            runs[int(r.id)] = {
                "id": r.id, "run_no": r.run_no, "status": r.status,
                "run_purpose": r.run_purpose, "verdict": r.verdict,
            }
    origin = None
    if d.origin_type == "RUN_ITEM" and d.origin_id:
        it = db.get(EvalRunItem, int(d.origin_id))
        if it is not None:
            origin = {"type": "RUN_ITEM", "item_id": it.id, "run_id": it.run_id,
                      "question_id": it.question_id, "final_verdict": it.final_verdict}
    elif d.origin_type == "TRACE" and d.origin_id:
        origin = {"type": "TRACE", "trace_id": d.origin_id}
    elif d.origin_type == "SRC" and d.origin_id:
        origin = {"type": "SRC", "finding_id": d.origin_id}
    events = [
        {
            "id": e.id, "event_type": e.event_type,
            "status_from": e.status_from, "status_to": e.status_to,
            "run": runs.get(int(e.run_id)) if e.run_id else None,
            "project_version_id": e.project_version_id,
            "note": e.note, "evidence": e.evidence,
            "actor_id": e.actor_id, "actor_name": e.actor_name,
            "created_at": e.created_at,
        }
        for e in evs
    ]
    return {"code": 0, "message": "ok", "data": {
        "defect": {"id": d.id, "defect_no": d.defect_no, "title": d.title,
                   "status": d.status, "severity": d.severity,
                   "origin": origin, "report_id": d.report_id,
                   "target_version_id": d.target_version_id},
        "events": events,
        "close_conditions": [
            {"code": c, "desc": t} for c, t in gate_service.CLOSE_CONDITIONS
        ],
        "unmet": gate_service.check_close_conditions(db, d, verifier="?"),
    }}


# --------------------------------------------------------------- remediation


@router.post("/defects/{defect_id}/remediation", response_model=dict)
def defect_remediation(
    defect_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """提交整改（§3.4）：变更引用至少一项 → 状态 FIXED + REMEDIATED 事件。"""
    d = asyncio.run(_defect_in_scope(db, defect_id, auth))
    if d.status in ("CLOSED",):
        raise BizError("ES-BIZ-DEFECT-0003", "已关闭缺陷不能提交整改（请先重开）")
    refs = body.get("change_refs") or {}
    if isinstance(refs, list):
        refs = {"refs": refs}
    if not any(str(refs.get(k) or "").strip() for k in ("commit", "version", "ticket", "refs")):
        raise BizError("ES-BIZ-DEFECT-0010",
                       "整改必须提供变更引用（commit/版本/工单至少一项），否则无法追溯修复内容")
    status_from = d.status
    d.status = "FIXED"
    if body.get("target_version_id"):
        d.target_version_id = int(body["target_version_id"])
    defect_events.append(
        db,
        defect_id=int(d.id), event_type="REMEDIATED",
        actor_id=auth.user_id, actor_name=auth.username, tenant_id=d.tenant_id or 1,
        status_from=status_from, status_to="FIXED",
        project_version_id=d.target_version_id,
        note=str(body.get("note") or "")[:2000] or None,
        evidence={
            "change_refs": refs,
            "impact_scope": body.get("impact_scope"),
            "attachments": body.get("attachments") or [],
            "suggested_retest_scope": body.get("suggested_retest_scope"),
        },
    )
    db.commit()
    return {"code": 0, "message": "ok", "data": {"defect_id": d.id, "status": d.status}}


# --------------------------------------------------------------------- retest


@router.post("/defects/{defect_id}/retest", response_model=dict)
def defect_retest(
    defect_id: int,
    body: dict | None = Body(default=None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """发起真实复测（§3.4）：继承原运行配置创建 RETEST 运行，绑定原失败题。

    真实调用被测系统（判分重放不算）；状态 VERIFYING + RETEST_STARTED 事件。
    """
    d = asyncio.run(_defect_in_scope(db, defect_id, auth))
    if d.status not in ("FIXED", "VERIFYING", "OPEN", "REOPENED"):
        raise BizError("ES-BIZ-DEFECT-0003", f"当前状态 {d.status} 不能发起复测")

    # 题目来源：手选 question_ids 优先，否则原缺陷来源运行项
    q_ids = [int(x) for x in (body or {}).get("question_ids") or []]
    origin_run: EvalRun | None = None
    if not q_ids:
        if d.origin_type != "RUN_ITEM" or not d.origin_id:
            raise BizError("ES-BIZ-DEFECT-0013",
                           "缺陷无来源运行项，请手选复测题目（question_ids）")
        item = db.get(EvalRunItem, int(d.origin_id))
        if item is None:
            raise BizError("ES-BIZ-DEFECT-0013", "缺陷来源运行项不存在，无法自动绑定复测题目")
        q_ids = [int(item.question_id)] if item.question_id else []
        origin_run = db.get(EvalRun, int(item.run_id))
        if not q_ids:
            raise BizError("ES-BIZ-DEFECT-0013",
                           "来源题目已被删除，请手选复测题目（question_ids）")
    if origin_run is None and (body or {}).get("parent_run_id"):
        origin_run = db.get(EvalRun, int(body["parent_run_id"]))

    questions = [_question_payload(q) for q in
                 _load_questions(db, q_ids)]
    bank = db.get(QuestionBank, int(questions[0]["bank_id"]))
    if bank is None or bank.deleted_at is not None:
        raise NotFoundError("ES-QB-001", "题目来源题库不存在")

    run = EvalRun(
        run_no=gen_no("EV"),
        eval_set_id=int(origin_run.eval_set_id or 0) if origin_run else 0,
        question_bank_id=int(bank.id),
        fact_source_id=origin_run.fact_source_id if origin_run else None,
        target_type=(origin_run.target_type if origin_run else "MODEL"),
        target_id=(origin_run.target_id if origin_run else str((body or {}).get("target_id") or "")),
        judge_mode=(origin_run.judge_mode if origin_run else "RULE"),
        judge_model=(origin_run.judge_model if origin_run else None),
        engine_code=origin_run.engine_code if origin_run else None,
        status="RUNNING",
        started_at=datetime.now(timezone.utc),
        created_by=auth.user_id,
        tenant_id=d.tenant_id or 1,
        run_purpose="RETEST",
        parent_run_id=int(origin_run.id) if origin_run else None,
        project_version_id=d.target_version_id or (origin_run.project_version_id if origin_run else None),
    )
    if not run.target_id:
        raise BizError("ES-BIZ-DEFECT-0013", "复测缺少被测系统（原运行无 target_id 且未手选）")
    db.add(run)
    db.flush()

    seed = gate_service_question_seed(questions)
    plan = {"sampled": len(questions), "strata": [], "retest_for_defect": int(d.id)}
    from ..services import judge_pipeline, target_gateway

    target = target_gateway.load_target(db, run.target_id, tenant_id=run.tenant_id or 1)
    judge_cfg = (
        judge_pipeline.resolve_judge_model_cfg(db, run.judge_model, tenant_id=run.tenant_id or 1)
        if (run.judge_mode or "RULE") in ("MODEL", "HYBRID") else None
    )
    _, prompt_hash = judge_pipeline.load_prompt(f"judge/{judge_pipeline.PROMPT_VERSION}")
    run.run_snapshot = bank_executor.build_snapshot(
        seed=seed, plan=plan, sample_size=len(questions), judge_cfg=judge_cfg,
        target_mode="API" if target else "INTERNAL_DEMO", prompt_hash=prompt_hash,
        # 优化12 §4.4 铁律7：派生复测 run 继承源 run 快照口径值（旧 run 无键 → None 视为旧口径）；
        # activity_id 按请求透传（复测默认不加入活动，除非请求显式携带）
        standards_ver=(origin_run.run_snapshot or {}).get("standards_ver") if origin_run else None,
        activity_id=(body or {}).get("activity_id") if isinstance(body, dict) else None,
    )
    status_from = d.status
    d.status = "VERIFYING"
    defect_events.append(
        db,
        defect_id=int(d.id), event_type="RETEST_STARTED",
        actor_id=auth.user_id, actor_name=auth.username, tenant_id=d.tenant_id or 1,
        status_from=status_from, status_to="VERIFYING",
        run_id=int(run.id),
        note=f"真实复测 {len(questions)} 题（继承运行 {origin_run.run_no if origin_run else '-'} 配置）",
        evidence={"question_ids": q_ids},
    )
    db.commit()

    # 后台线程执行真实复测（ES11-HTTP：长任务不占请求线程，2-worker 下防超时）；
    # 前端经复测运行详情轮询状态（RUNNING → PASSED/FAILED）
    _spawn_retest(int(run.id), q_ids, int(d.id))
    return {"code": 0, "message": "ok", "data": {
        "defect_id": d.id, "status": d.status,
        "retest_run": {"id": run.id, "run_no": run.run_no, "status": run.status,
                       "verdict": run.verdict, "run_purpose": run.run_purpose},
        "async": True,
    }}


def _load_questions(db: Session, q_ids: list[int]) -> list[Question]:
    out = []
    for qid in q_ids:
        qq = db.get(Question, qid)
        if qq is None or qq.deleted_at is not None:
            raise BizError("ES-BIZ-DEFECT-0013", f"题目 {qid} 不存在或已删除")
        out.append(qq)
    return out


def _question_payload(qq: Question) -> dict:
    return {
        "question_id": int(qq.id), "bank_id": int(qq.bank_id), "seq": qq.seq,
        "text": qq.text, "category": qq.category, "sub_category": qq.sub_category,
        "attack_vector": qq.attack_vector, "split": qq.split,
        "expected_behavior": qq.expected_behavior,
        "expected_answer": qq.expected_answer, "language": qq.language,
        "meta": qq.meta if isinstance(qq.meta, dict) else {},
    }


def _spawn_retest(run_id: int, q_ids: list[int], defect_id: int) -> None:
    """复测后台执行：独立 SessionLocal；异常兜底置 FAILED（不留僵尸 RUNNING）。"""

    def _worker():
        from ..database import SessionLocal

        db = SessionLocal()
        try:
            run = db.get(EvalRun, run_id)
            if run is None or run.status != "RUNNING":
                return
            questions = [_question_payload(q)
                         for q in _load_questions(db, q_ids)]
            bank = db.get(QuestionBank, int(run.question_bank_id))
            if not questions or bank is None:
                raise BizError("ES-BIZ-DEFECT-0013", "复测题目/题库不可用")
            seed = gate_service_question_seed(questions)
            plan = {"sampled": len(questions), "strata": [],
                    "retest_for_defect": defect_id}
            bank_executor.run_questions(
                db, run, bank, questions, seed=seed, plan=plan,
                sample_size=len(questions))
        except Exception:
            logger.exception("retest 后台执行失败 run=%s", run_id)
            try:
                db.rollback()
                run = db.get(EvalRun, run_id)
                if run is not None and run.status == "RUNNING":
                    run.status = "FAILED"
                    run.finished_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:
                db.rollback()
        finally:
            db.close()

    threading.Thread(target=_worker, daemon=True,
                     name=f"defect-retest-{run_id}").start()


def gate_service_question_seed(questions: list[dict]) -> int:
    """复测运行 seed：题目集合确定性哈希（重放可复现），不依赖随机。"""
    import hashlib

    joined = ",".join(str(q.get("question_id")) for q in questions)
    return int(hashlib.md5(joined.encode()).hexdigest()[:6], 16)


# --------------------------------------------------------------------- verify


@router.post("/defects/{defect_id}/verify", response_model=dict)
def defect_verify(
    defect_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("defect", "verify")),
):
    """验证（§3.4/§4.2）：PASS→六条件全满足才 CLOSED；FAIL→REOPENED。

    只认 run_purpose=RETEST 的真实复测运行（判分重放不算证据）。
    """
    d = asyncio.run(_defect_in_scope(db, defect_id, auth))
    result = str(body.get("result") or "").upper()
    if result not in ("PASS", "FAIL"):
        raise BizError("ES-BIZ-VERIFY-0001", "result 必须为 PASS 或 FAIL")
    if d.status not in ("VERIFYING", "FIXED"):
        raise BizError("ES-BIZ-VERIFY-0001", f"当前状态 {d.status} 不可验证（需先提交整改并发起复测）")

    run = gate_service.latest_retest_run(db, d)
    if run is None or run.run_purpose != "RETEST":
        raise BizError("ES-BIZ-VERIFY-0001",
                       "缺少真实复测运行（run_purpose=RETEST）：重新判分不能作为验证证据")

    note = str(body.get("note") or "")[:2000] or None
    if result == "FAIL":
        status_from = d.status
        d.status = "REOPENED"
        defect_events.append(
            db, defect_id=int(d.id), event_type="REOPENED",
            actor_id=auth.user_id, actor_name=auth.username, tenant_id=d.tenant_id or 1,
            status_from=status_from, status_to="REOPENED", run_id=int(run.id),
            note=note or "验证失败", evidence={"verify_result": "FAIL"},
        )
        db.commit()
        return {"code": 0, "message": "ok", "data": {"defect_id": d.id, "status": d.status}}

    unmet = gate_service.check_close_conditions(db, d, verifier=auth.username)
    if unmet:
        raise BizError("ES-BIZ-VERIFY-0001",
                       f"关闭六条件未满足：{','.join(unmet)}（复测需成功终态且原失败项达标）")
    # 职责分离标记：整改人==验证人（租户策略可豁免，仅留痕）
    rem = [e for e in defect_events.timeline(db, int(d.id)) if e.event_type == "REMEDIATED"]
    duty_unseparated = bool(rem and int(rem[-1].actor_id) == int(auth.user_id))
    status_from = d.status
    d.status = "CLOSED"
    defect_events.append(
        db, defect_id=int(d.id), event_type="VERIFIED",
        actor_id=auth.user_id, actor_name=auth.username, tenant_id=d.tenant_id or 1,
        status_from=status_from, status_to="CLOSED", run_id=int(run.id),
        project_version_id=d.target_version_id,
        note=note,
        evidence={
            "verify_result": "PASS", "unmet": [],
            "retest_run_no": run.run_no,
            "duty_unseparated": duty_unseparated,
        },
    )
    db.commit()
    return {"code": 0, "message": "ok", "data": {
        "defect_id": d.id, "status": d.status,
        "duty_unseparated": duty_unseparated,
    }}


# --------------------------------------------------------------------- reopen


@router.post("/defects/{defect_id}/reopen", response_model=dict)
def defect_reopen(
    defect_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """CLOSED 后重开（§3.4）：必须填原因，追加事件，不改写旧事件。"""
    d = asyncio.run(_defect_in_scope(db, defect_id, auth))
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise BizError("ES-BIZ-DEFECT-0003", "重开缺陷必须填写原因")
    if d.status != "CLOSED":
        raise BizError("ES-BIZ-DEFECT-0003", f"仅 CLOSED 缺陷可重开（当前 {d.status}）")
    d.status = "REOPENED"
    defect_events.append(
        db, defect_id=int(d.id), event_type="REOPENED",
        actor_id=auth.user_id, actor_name=auth.username, tenant_id=d.tenant_id or 1,
        status_from="CLOSED", status_to="REOPENED",
        note=reason[:2000],
        evidence={"reopen_reason": reason[:2000]},
    )
    db.commit()
    return {"code": 0, "message": "ok", "data": {"defect_id": d.id, "status": d.status}}


# --------------------------------------------------------------------- waive


@router.post("/defects/{defect_id}/waive", response_model=dict)
def defect_waive(
    defect_id: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("defect", "verify")),
):
    """风险接受（§2.2 G4 / ES11-G4-004）：不闭环但豁免 G4 阻断，必须填原因。

    只追加 WAIVED 事件、不改缺陷状态——缺陷保持未闭环可继续走整改环；
    后续如产生更新的 REOPENED 事件，豁免自动失效（gate 取最近处置事件）。
    权限口径与验证关闭同级（处置权 = defect:verify）。
    """
    d = asyncio.run(_defect_in_scope(db, defect_id, auth))
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise BizError("ES-BIZ-DEFECT-0015", "风险接受必须填写原因（豁免人与依据随事件留痕）")
    if d.status == "CLOSED":
        raise BizError("ES-BIZ-DEFECT-0015", "缺陷已关闭，无需风险接受")
    deadline = str(body.get("deadline") or "").strip()[:64] or None
    defect_events.append(
        db, defect_id=int(d.id), event_type="WAIVED",
        actor_id=auth.user_id, actor_name=auth.username, tenant_id=d.tenant_id or 1,
        status_from=d.status, status_to=d.status,
        note=reason[:2000],
        evidence={"waive_reason": reason[:2000], "deadline": deadline},
    )
    db.commit()
    return {"code": 0, "message": "ok", "data": {
        "defect_id": int(d.id), "status": d.status, "waived": True,
        "deadline": deadline,
    }}


# P5 超期口径：按严重度的闭环 SLA（自然日）
_SLA_DAYS = {"P0": 1, "P1": 3, "P2": 7, "P3": 14, "P4": 30}
# 当前阶段展示（状态 → 闭环阶段）
_STAGE_LABEL = {
    "NEW": "发现待指派", "OPEN": "处理中", "FIXED": "已整改待复测",
    "VERIFYING": "复测验证中", "REOPENED": "重开待整改", "CLOSED": "已关闭",
}
_NEXT_ACTION = {
    "NEW": "指派处理", "OPEN": "提交整改", "FIXED": "发起复测",
    "VERIFYING": "验证复测结论", "REOPENED": "提交整改", "CLOSED": "-",
}


@router.get("/defect-loop-board", response_model=dict)
def defect_loop_board(
    ids: str = Query(..., min_length=1, max_length=4000,
                     description="逗号分隔缺陷 ID（当前页），单页 ≤200"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """P5 缺陷列表增列的闭环富化（只读）：来源/阶段/整改版本/复测结论/超期/下一动作。"""
    try:
        wanted = sorted({int(x) for x in ids.split(",") if x.strip()})
    except ValueError:
        raise BizError("ES-BIZ-DEFECT-0001", "ids 必须为逗号分隔整数")
    if not wanted or len(wanted) > 200:
        raise BizError("ES-BIZ-DEFECT-0001", "ids 数量须在 1~200 之间")
    rows = db.query(Defect).filter(Defect.id.in_(wanted)).all()
    if not auth.is_super_admin:
        rows = [d for d in rows if d.tenant_id == auth.tenant_id]
    dids = [int(d.id) for d in rows]

    evs_by_defect: dict[int, list] = {}
    for e in defect_events.timeline_bulk(db, dids):
        evs_by_defect.setdefault(int(e.defect_id), []).append(e)

    # 来源运行与版本（RUN_ITEM → 运行编号 + 数据集版本）
    origin_run: dict[int, dict] = {}
    run_item_ids = [int(d.origin_id) for d in rows
                    if d.origin_type == "RUN_ITEM" and d.origin_id]
    if run_item_ids:
        for it, r in (db.query(EvalRunItem, EvalRun)
                      .join(EvalRun, EvalRun.id == EvalRunItem.run_id)
                      .filter(EvalRunItem.id.in_(run_item_ids)).all()):
            origin_run[int(it.id)] = {
                "run_id": r.id, "run_no": r.run_no,
                "version": (r.run_snapshot or {}).get("dataset_version")
                or r.dataset_version,
                "target_id": r.target_id,
            }

    now = datetime.now(timezone.utc)
    items = []
    for d in rows:
        evs = evs_by_defect.get(int(d.id), [])
        last_rem = next((e for e in reversed(evs) if e.event_type == "REMEDIATED"), None)
        last_ver = next((e for e in reversed(evs)
                         if e.event_type in ("VERIFIED", "REOPENED")), None)
        overdue = None
        if d.status != "CLOSED" and d.created_at is not None:
            sla = _SLA_DAYS.get(d.severity, 14)
            created = d.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            overdue = max(0, (now - created).days - sla)
        origin = None
        if d.origin_type == "RUN_ITEM" and d.origin_id:
            origin = origin_run.get(int(d.origin_id))
        rem_refs = (last_rem.evidence or {}).get("change_refs") if last_rem else None
        items.append({
            "defect_id": d.id,
            "origin_type": d.origin_type,
            "origin_run": origin,
            "stage": _STAGE_LABEL.get(d.status, d.status),
            "last_remediation": {
                "version": (rem_refs or {}).get("version")
                or (rem_refs or {}).get("commit")
                or (f"v{d.target_version_id}" if d.target_version_id else None),
                "at": last_rem.created_at if last_rem else None,
                "by": last_rem.actor_name if last_rem else None,
            } if last_rem else None,
            "last_retest": {
                "event_type": last_ver.event_type,
                "result": (last_ver.evidence or {}).get("verify_result") if last_ver else None,
                "note": last_ver.note if last_ver else None,
                "at": last_ver.created_at if last_ver else None,
            } if last_ver else None,
            "overdue_days": overdue,
            "next_action": _NEXT_ACTION.get(d.status, "-"),
        })
    return {"code": 0, "message": "ok", "data": {"items": items}}
