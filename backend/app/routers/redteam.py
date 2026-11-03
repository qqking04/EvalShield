# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M9：生成式红队路由——样本池/审批、变异批任务、框架覆盖、防护建议包。

守卫范式照 monitors.py：每个端点函数内 capability "generative_redteam" 门控
（未点亮 403 ES-LIC-0003 置灰）+ require_permission("redteam", "manage")
（section 45.4 已种子权限点并绑定 SUPER_ADMIN/ADMIN）；
租户隔离：非超管一律按 auth.tenant_id 过滤，跨租户详情 404 不暴露存在性。
路由顺序：/samples/{id}/approve 等含字面量段的规则天然长于裸 /{param}，
且本模块不存在裸 /samples/{id}，无需额外排序规避。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import AuthContext, require_permission
from ..errors import BizError, NotFoundError, ok
from ..models import (
    Defect,
    EvalRun,
    EvalRunItem,
    FrameworkItem,
    JailbreakSample,
    RedteamSample,
    TestCase,
)
from ..services.audit import write_audit
from ..services.redteam_mutate import (
    DEFAULT_BATCH_COUNT,
    MUTATION_TYPES,
    batch_mode,
    generate_batch,
)

router = APIRouter()

MAX_MUTATION_COUNT = 50  # 方案 §10：每批默认 20，可配上限 50


def _guard_redteam_feature() -> None:
    """能力位闸门：generative_redteam 未点亮（community / enterprise 未授权）一律 403。"""
    from ..enterprise.features import feature_enabled

    if not feature_enabled("generative_redteam"):
        raise BizError(
            "ES-LIC-0003",
            "生成式红队为企业/SaaS 能力（generative_redteam），请先开通该能力",
            http_status=403,
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sample_out(s: RedteamSample) -> dict[str, Any]:
    """样本序列化（hit_stats JSON 串解析为对象回显）。"""
    try:
        hits = json.loads(s.hit_stats or "{}")
    except (ValueError, TypeError):
        hits = {}
    return {
        "id": s.id,
        "tenant_id": s.tenant_id,
        "framework_code": s.framework_code,
        "payload": s.payload,
        "mutation_of": s.mutation_of,
        "status": s.status,
        "hit_stats": hits if isinstance(hits, dict) else {},
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None,
    }


def _get_sample(db: Session, sample_id: int, auth: AuthContext) -> RedteamSample:
    """租户隔离取样本：不存在或跨租户一律 404（不暴露存在性）。"""
    s = db.get(RedteamSample, sample_id)
    if s is None:
        raise NotFoundError("ES-M9-0001", "红队样本不存在")
    if not auth.is_super_admin and s.tenant_id != auth.tenant_id:
        raise NotFoundError("ES-M9-0001", "红队样本不存在")
    return s


# ------------------------------------------------------------------ 样本池 ----

@router.get("/samples")
def list_samples(
    status: str | None = Query(None, pattern=r"^(DRAFT|APPROVED|REJECTED)$"),
    framework_code: str | None = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    auth: AuthContext = Depends(require_permission("redteam", "manage")),
    db: Session = Depends(get_db),
):
    """样本池列表（状态/框架过滤 + 分页，租户隔离）。"""
    _guard_redteam_feature()
    q = db.query(RedteamSample)
    if not auth.is_super_admin:
        q = q.filter(RedteamSample.tenant_id == auth.tenant_id)
    if status:
        q = q.filter(RedteamSample.status == status)
    if framework_code:
        q = q.filter(RedteamSample.framework_code == framework_code)
    total = q.count()
    rows = (
        q.order_by(RedteamSample.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ok({
        "total": total, "page": page, "page_size": page_size,
        "items": [_sample_out(s) for s in rows],
    })


@router.post("/samples")
def create_sample(
    payload: dict[str, Any],
    request: Request,
    auth: AuthContext = Depends(require_permission("redteam", "manage")),
    db: Session = Depends(get_db),
):
    """手工新建 DRAFT 样本（与变异产出同审批流，DRAFT 不参与执行）。"""
    _guard_redteam_feature()
    text = str(payload.get("payload") or "").strip()
    if not text:
        raise BizError("ES-M9-0002", "payload 不能为空")
    row = RedteamSample(
        tenant_id=auth.tenant_id,
        framework_code=str(payload.get("framework_code") or "")[:64],
        payload=text,
        mutation_of=None,  # 手工样本无源种子
        status="DRAFT",
        created_by=auth.user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="redteam.sample.create", module="redteam", request=request,
        detail=f"手工新建 DRAFT 样本 id={row.id}",
    )
    return ok(_sample_out(row))


def _transition(
    db: Session, request: Request, auth: AuthContext, sample_id: int, target: str,
) -> dict[str, Any]:
    """审批状态机：仅 DRAFT 可审 → APPROVED/REJECTED（REJECTED 终态）。"""
    s = _get_sample(db, sample_id, auth)
    if s.status != "DRAFT":
        raise BizError(
            "ES-M9-0003", f"样本当前状态 {s.status}，仅 DRAFT 可审批", http_status=409,
        )
    s.status = target
    s.reviewed_at = _now()
    db.commit()
    db.refresh(s)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action=f"redteam.sample.{target.lower()}", module="redteam", request=request,
        detail=f"样本 id={s.id} DRAFT→{target}",
    )
    return _sample_out(s)


@router.post("/samples/{sample_id}/approve")
def approve_sample(
    sample_id: int,
    request: Request,
    auth: AuthContext = Depends(require_permission("redteam", "manage")),
    db: Session = Depends(get_db),
):
    """审批通过：DRAFT→APPROVED（此后方可被 include_generated 注入执行）。"""
    _guard_redteam_feature()
    return ok(_transition(db, request, auth, sample_id, "APPROVED"))


@router.post("/samples/{sample_id}/reject")
def reject_sample(
    sample_id: int,
    request: Request,
    auth: AuthContext = Depends(require_permission("redteam", "manage")),
    db: Session = Depends(get_db),
):
    """审批驳回：DRAFT→REJECTED（终态，永不参与执行）。"""
    _guard_redteam_feature()
    return ok(_transition(db, request, auth, sample_id, "REJECTED"))


# ------------------------------------------------------------------ 变异批任务 ----

@router.post("/mutations")
def run_mutations(
    payload: dict[str, Any],
    request: Request,
    auth: AuthContext = Depends(require_permission("redteam", "manage")),
    db: Session = Depends(get_db),
):
    """载荷变异批任务（同步执行，逐条 DRAFT 入库并返回清单）。

    请求体：{"seed_ids": [jailbreak_samples.id...] 可选（缺省=租户内置种子随机）,
    "count": 条数（默认 20，≤50）, "mutation_types": 类型子集（默认 5 类全开）}。
    降级语义：无可用 LLM 时整批走内置模板变异，mode=TEMPLATE 明示返回。
    计费：按产出条数走 _charge(biz_type="REDTEAM") 配额流水（M2 范式）。
    """
    _guard_redteam_feature()

    # ---- 入参校验 ----
    raw_count = payload.get("count", DEFAULT_BATCH_COUNT)
    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        raise BizError("ES-M9-0004", "count 必须为整数")
    if count < 1 or count > MAX_MUTATION_COUNT:
        raise BizError("ES-M9-0005", f"count 须在 [1, {MAX_MUTATION_COUNT}] 区间")
    types = payload.get("mutation_types")
    if types is not None:
        if not isinstance(types, list) or not all(t in MUTATION_TYPES for t in types):
            raise BizError("ES-M9-0006", f"mutation_types 须为 {list(MUTATION_TYPES)} 子集")
        types = list(dict.fromkeys(types))  # 去重保序

    # ---- 装载种子（指定 id 或租户全量启用种子）----
    sq = db.query(JailbreakSample).filter(
        JailbreakSample.tenant_id == auth.tenant_id,
        JailbreakSample.is_active.is_(True),
        JailbreakSample.deleted_at.is_(None),
    )
    seed_ids = payload.get("seed_ids")
    if seed_ids:
        if not isinstance(seed_ids, list):
            raise BizError("ES-M9-0007", "seed_ids 必须为数组")
        sq = sq.filter(JailbreakSample.id.in_([int(i) for i in seed_ids]))
    seeds = sq.order_by(JailbreakSample.id.asc()).all()
    if not seeds:
        raise BizError("ES-M9-0008", "租户无可用种子样本，请先维护越狱样本库")

    # ---- 生成（纯内存，不落库；失败无副作用）----
    rows = generate_batch(
        db, tenant_id=auth.tenant_id, seeds=seeds, count=count,
        mutation_types=types,
    )

    # ---- 计费（saas 到期在 add 之前 raise，流水独立提交，不产生脏 DRAFT）----
    from ..services.task_runner import _charge

    _charge(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id,
        biz_type="REDTEAM", amount=float(len(rows)),
        description=f"红队载荷变异批任务 {len(rows)} 条（mode={batch_mode(rows)}）",
    )

    # ---- 逐条 DRAFT 入库 ----
    created: list[RedteamSample] = []
    for r in rows:
        s = RedteamSample(
            tenant_id=auth.tenant_id,
            framework_code=r["framework_code"],
            payload=r["payload"],
            mutation_of=r["mutation_of"],
            status="DRAFT",
            created_by=auth.user_id,
        )
        db.add(s)
        created.append(s)
    db.commit()
    for s in created:
        db.refresh(s)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="redteam.mutations.run", module="redteam", request=request,
        detail=f"变异批任务产出 {len(created)} 条 DRAFT（mode={batch_mode(rows)}）",
    )
    return ok({
        "mode": batch_mode(rows),  # LLM | TEMPLATE（降级语义可断言）
        "created": len(created),
        "items": [_sample_out(s) for s in created],
    })


# ------------------------------------------------------------------ 框架字典 ----

@router.get("/frameworks")
def list_frameworks(
    framework: str | None = Query(None, pattern=r"^(owasp_llm|atlas)$"),
    auth: AuthContext = Depends(require_permission("redteam", "manage")),
    db: Session = Depends(get_db),
):
    """国际框架条目列表（OWASP LLM Top10 2025 / MITRE ATLAS，全局共享数据字典）。"""
    _guard_redteam_feature()
    q = db.query(FrameworkItem)
    if framework:
        q = q.filter(FrameworkItem.framework == framework)
    rows = q.order_by(FrameworkItem.framework.asc(), FrameworkItem.code.asc()).all()
    return ok({
        "items": [
            {
                "code": r.code, "name": r.name, "framework": r.framework,
                "item_type": r.item_type, "tactic": r.tactic,
                "description": r.description,
            }
            for r in rows
        ],
    })


# ------------------------------------------------------------------ 覆盖归集 ----

def _collect_coverages(
    db: Session, run: EvalRun,
) -> dict[str, dict[str, int]]:
    """从 run.item_results 归集 framework_code → {attempts, bypassed}。

    双数据源（方案 §10）：
    A. 条目 detail.framework_code（越狱引擎 / 红队注入样本透传）；
    B. 条目关联用例（detail.case_id 或 detail.tags）tags 中
       "atlas:"/"owasp:" 前缀项（去前缀后即 framework_items.code）。
    同一条目对同一 code 只计一次 attempt，防双源重复。
    """
    cov: dict[str, dict[str, int]] = {}

    def _hit(code: str, bypassed: bool) -> None:
        c = cov.setdefault(code, {"attempts": 0, "bypassed": 0})
        c["attempts"] += 1
        if bypassed:
            c["bypassed"] += 1

    case_tag_cache: dict[int, list[str]] = {}
    for row in run.item_results or []:
        detail = row.get("detail") or {}
        if not isinstance(detail, dict):
            continue
        bypassed = bool(detail.get("bypassed")) or str(row.get("verdict") or "") == "BYPASSED"
        codes: set[str] = set()
        fc = str(detail.get("framework_code") or "").strip()
        if fc:
            codes.add(fc)
        tags: list[Any] = []
        if detail.get("tags"):
            tags = detail["tags"] if isinstance(detail["tags"], list) else []
        elif detail.get("case_id") is not None:
            cid = int(detail["case_id"])
            if cid not in case_tag_cache:
                case = db.get(TestCase, cid)
                case_tag_cache[cid] = list(case.tags) if case and isinstance(case.tags, list) else []
            tags = case_tag_cache[cid]
        for tg in tags:
            t = str(tg or "").strip()
            low = t.lower()
            if low.startswith("atlas:") or low.startswith("owasp:"):
                codes.add(t.split(":", 1)[1].strip())
        for code in sorted(codes):
            if code:
                _hit(code, bypassed)
    return cov


def coverage_data(db: Session, run: EvalRun) -> dict[str, Any]:
    """框架覆盖矩阵装配唯一实现（API 端点与报告「国际框架覆盖」节共用）。

    attempts=框架被投递用例数；bypassed=其中被绕过数；join framework_items
    补全名称（未知 code 原样展示）。数字全部来自 run.item_results，可单测断言。
    """
    cov = _collect_coverages(db, run)
    fw_rows = db.query(FrameworkItem).all()
    meta = {r.code: r for r in fw_rows}
    items = []
    for code in sorted(cov):
        c = cov[code]
        m = meta.get(code)
        items.append({
            "code": code,
            "name": m.name if m else code,
            "framework": m.framework if m else "",
            "item_type": m.item_type if m else "",
            "tactic": m.tactic if m else "",
            "attempts": c["attempts"],
            "bypassed": c["bypassed"],
        })
    return {
        "run_id": run.id,
        "items": items,
        "totals": {
            "attempts": sum(i["attempts"] for i in items),
            "bypassed": sum(i["bypassed"] for i in items),
            "codes_covered": len(items),
            "framework_items_total": len(fw_rows),
        },
    }


@router.get("/coverage")
def get_coverage(
    run_id: int = Query(..., ge=1),
    auth: AuthContext = Depends(require_permission("redteam", "manage")),
    db: Session = Depends(get_db),
):
    """国际框架覆盖矩阵：指定评测运行的 framework_code 归集计数。"""
    _guard_redteam_feature()
    run = db.get(EvalRun, run_id)
    if run is None:
        raise NotFoundError("ES-M9-0009", "评测运行不存在")
    if not auth.is_super_admin and run.tenant_id != auth.tenant_id:
        raise NotFoundError("ES-M9-0009", "评测运行不存在")
    return ok(coverage_data(db, run))


# ------------------------------------------------------------------ 攻击活动 ----


@router.get("/campaigns")
def list_campaigns(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    auth: AuthContext = Depends(require_permission("redteam", "manage")),
    db: Session = Depends(get_db),
):
    """ES11 P8：攻击活动台账——红队运行逐条富化（绕过统计/首绕路径/框架覆盖/转缺陷闭环态）。

    红队运行识别：engine_code ∈ {JAILBREAK, REDTEAM_TEST}（引擎注册表大写码）。
    投递样本数优先框架覆盖归集，归集为空时回退运行汇总 total（两者皆不可考 = null）。
    变异数取运行快照 mutation_count（越狱引擎 include_generated 注入数），快照缺失时为
    null（前端显示 "-"，不伪造）。
    """
    _guard_redteam_feature()
    q = (
        db.query(EvalRun)
        .filter(EvalRun.deleted_at.is_(None),
                EvalRun.engine_code.in_(("JAILBREAK", "REDTEAM_TEST")))
    )
    if not auth.is_super_admin:
        q = q.filter(EvalRun.tenant_id == auth.tenant_id)
    total = q.count()
    runs = (q.order_by(EvalRun.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())

    items: list[dict[str, Any]] = []
    for run in runs:
        cov = coverage_data(db, run)
        first_bypass = None
        rounds = None
        for row in run.item_results or []:
            detail = row.get("detail") or {}
            if isinstance(detail, dict) and detail.get("rounds"):
                rounds = detail.get("rounds")
            if first_bypass is None and isinstance(detail, dict) and (
                    bool(detail.get("bypassed"))
                    or str(row.get("verdict") or "") == "BYPASSED"):
                first_bypass = {
                    "framework_code": str(detail.get("framework_code") or ""),
                    "payload": str(detail.get("prompt") or row.get("prompt") or "")[:120],
                }
        item_ids = [
            int(i) for (i,) in db.query(EvalRunItem.id)
            .filter(EvalRunItem.run_id == run.id).all()
        ]
        d_total = d_open = d_closed = 0
        if item_ids:
            for d in (db.query(Defect)
                      .filter(Defect.deleted_at.is_(None),
                              Defect.origin_type == "RUN_ITEM",
                              Defect.origin_id.in_(item_ids)).all()):
                d_total += 1
                if d.status == "CLOSED":
                    d_closed += 1
                elif d.status in ("NEW", "OPEN", "REOPENED"):
                    d_open += 1
        snap = run.run_snapshot or {}
        # 投递样本数：优先框架覆盖归集（有 framework_code 的投递数）；
        # 无归集结果（历史运行未打框架标记）时回退运行汇总 total，仍不可考则 null
        samples = cov["totals"]["attempts"] or int((run.summary or {}).get("total") or 0) or None
        items.append({
            "run_id": run.id, "run_no": run.run_no, "status": run.status,
            "target_id": run.target_id,
            "version": snap.get("dataset_version") or run.dataset_version,
            "samples": samples,
            "mutations": snap.get("mutation_count"),
            "rounds": rounds if rounds is not None else snap.get("rounds"),
            "bypassed": cov["totals"]["bypassed"],
            "first_bypass": first_bypass,
            "framework_covered": cov["totals"]["codes_covered"],
            "framework_total": cov["totals"]["framework_items_total"],
            "defects": {"total": d_total, "open": d_open, "closed": d_closed},
            "created_at": run.created_at.isoformat() if run.created_at else None,
        })
    return ok({"items": items, "total": total,
               "page": page, "page_size": page_size})


# ------------------------------------------------------------------ 防护建议包 ----

def _bypassed_examples(db: Session, run: EvalRun | None, tenant_id: int) -> list[dict[str, Any]]:
    """高命中绕过样例两来源：run 内 BYPASSED 条目 + 租户样本 hit_stats.bypassed>0。"""
    examples: list[dict[str, Any]] = []
    if run is not None:
        for row in run.item_results or []:
            detail = row.get("detail") or {}
            if not isinstance(detail, dict):
                continue
            if bool(detail.get("bypassed")) or str(row.get("verdict") or "") == "BYPASSED":
                payload = str(detail.get("prompt") or row.get("prompt") or "")
                if payload:
                    examples.append({
                        "payload": payload,
                        "framework_code": str(detail.get("framework_code") or ""),
                    })
    for s in (
        db.query(RedteamSample)
        .filter(RedteamSample.tenant_id == tenant_id, RedteamSample.status == "APPROVED")
        .all()
    ):
        try:
            hits = json.loads(s.hit_stats or "{}")
        except (ValueError, TypeError):
            hits = {}
        if isinstance(hits, dict) and int(hits.get("bypassed") or 0) > 0:
            examples.append({
                "payload": s.payload,
                "framework_code": s.framework_code,
            })
    return examples


def build_guardrail_package(
    db: Session, *, run: EvalRun | None, tenant_id: int,
) -> dict[str, Any]:
    """防护建议包唯一实现（API 下载与报告「防护建议」节共用，同源同口径）。

    把高命中（bypassed>0）载荷归纳为护栏规则：pattern 取载荷特征片段并
    re.escape 防注入（消费侧 re.compile 必然成功且按字面匹配）；按
    (framework_code, pattern) 去重。
    """
    rules: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ex in _bypassed_examples(db, run, tenant_id):
        payload = " ".join(str(ex["payload"]).split())  # 压空白，取规范化片段
        if not payload:
            continue
        fragment = payload[:60]
        pattern = re.escape(fragment)
        key = (ex["framework_code"], pattern)
        if key in seen:
            continue
        seen.add(key)
        rules.append({
            "pattern": pattern,
            "action": "block",
            "example": payload[:200],
            "framework_code": ex["framework_code"],
        })
    return {
        "rules": rules,
        "generated_at": _now().isoformat(),
        "run_id": run.id if run is not None else None,
    }


@router.get("/guardrail-package")
def download_guardrail_package(
    run_id: int | None = Query(None, ge=1),
    auth: AuthContext = Depends(require_permission("redteam", "manage")),
    db: Session = Depends(get_db),
):
    """下载防护建议包（Content-Disposition attachment JSON）。

    run_id 可选：给定则并入该次运行的 BYPASSED 条目，否则仅租户样本 hit_stats。
    """
    _guard_redteam_feature()
    run = None
    if run_id is not None:
        run = db.get(EvalRun, run_id)
        if run is None:
            raise NotFoundError("ES-M9-0009", "评测运行不存在")
        if not auth.is_super_admin and run.tenant_id != auth.tenant_id:
            raise NotFoundError("ES-M9-0009", "评测运行不存在")
    pkg = build_guardrail_package(db, run=run, tenant_id=auth.tenant_id)
    body = json.dumps(pkg, ensure_ascii=False, indent=2)
    filename = f"guardrail-package-{run_id if run_id is not None else 'tenant'}"
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.json"',
        },
    )
