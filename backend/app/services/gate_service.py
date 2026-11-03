# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""ES11：五道门禁聚合服务（G0-G4，开发方案 §2）。

派生状态不落库：readiness 固化进 run_snapshot.readiness（创建时），
concluded / deliverable 由本服务实时计算。服务文件不属于 engines 目录
（AGENTS.md 锁 1：禁止在 backend/app/engines/ 新增 .py）。
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import cast, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..models import (
    Defect,
    DefectEvent,
    EvalRun,
    EvalRunItem,
    FactSource,
    QuestionBank,
    RedteamSample,
    Report,
    ReviewItem,
    TargetRegistry,
)
from . import calibration, judge_pipeline, question_sampler, target_gateway

logger = logging.getLogger(__name__)

PASS, WARN, BLOCK = "PASS", "WARN", "BLOCK"

# G1 三类失败口径关键词（§2.3）
_CONFIG_PAT = re.compile(
    r"(401|认证|auth|密钥|key 环境变量|不存在或非 ACTIVE|题库|事实源|知识源|response_path|配置)",
    re.IGNORECASE,
)
_INFRA_PAT = re.compile(
    r"(timeout|超时|429|限流|connection|connect|dns|network|网络|readtimeout|不可用|refused|remotedisconnect)",
    re.IGNORECASE,
)

BANK_MIN_SUGGEST = 20  # 题库题量建议值（低于为 WARN）


def _check(code: str, status: str, reason: str, action: dict | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "status": status, "reason": reason}
    if action:
        out["action"] = action
    return out


# --------------------------------------------------------------------- G0


def check_readiness(db: Session, cfg: dict[str, Any], auth, *,
                    skip_connectivity: bool = False) -> dict[str, Any]:
    """G0 准备度检查（§3.1）。cfg 与 POST /eval-runs 发起配置同构：
    {target_id, question_bank_id, sample_size, judge_mode, judge_model,
     fact_source_id, project_version_id, engine_code}
    skip_connectivity=True：创建时复校验不发起真实连通调用（预检接口已覆盖）。
    """
    checks: list[dict[str, Any]] = []
    tenant_id = auth.tenant_id

    # 1) 被测系统存在 + 启用
    target_code = str(cfg.get("target_id") or "").strip()
    tgt = None
    if not target_code:
        checks.append(_check("TARGET_EXISTS", WARN, "未指定被测系统（INTERNAL_DEMO 演示模式，不可正式交付）"))
    else:
        q = db.query(TargetRegistry).filter(
            TargetRegistry.code == target_code, TargetRegistry.deleted_at.is_(None)
        )
        if not auth.is_super_admin:
            q = q.filter(TargetRegistry.tenant_id == tenant_id)
        tgt = q.first()
        if tgt is None:
            checks.append(_check("TARGET_EXISTS", BLOCK, f"被测系统 {target_code} 不存在",
                                 {"label": "检查被测系统", "path": "/targets"}))
        elif tgt.status != "ACTIVE":
            checks.append(_check("TARGET_EXISTS", BLOCK, f"被测系统 {tgt.name} 已停用（{tgt.status}）",
                                 {"label": "启用被测系统", "path": "/targets"}))
        else:
            checks.append(_check("TARGET_EXISTS", PASS, f"被测系统 {tgt.name} 已启用"))

    # 2) 连通性（真实调用一次，offline/内置模型跳过；创建时复校验跳过）
    if tgt is not None:
        if skip_connectivity:
            checks.append(_check("TARGET_CONNECTIVITY", PASS, "创建时复校验不重复发起连通调用"))
        else:
            res = target_gateway.test_target(db, target_code, tenant_id=tenant_id)
            if res.get("skipped"):
                checks.append(_check("TARGET_CONNECTIVITY", PASS, "预置输出靶机：连通测试不适用"))
            elif res.get("ok"):
                checks.append(_check("TARGET_CONNECTIVITY", PASS, f"连通正常（{res.get('latency_ms')}ms）"))
            else:
                checks.append(_check("TARGET_CONNECTIVITY", BLOCK,
                                     f"被测系统连接测试失败（{res.get('error') or '未知错误'}）",
                                     {"label": "检查被测系统", "path": "/targets"}))

    # 3) 题库存在 + 题量
    bank_id = int(cfg.get("question_bank_id") or 0)
    if bank_id > 0:
        bq = db.query(QuestionBank).filter(QuestionBank.id == bank_id, QuestionBank.deleted_at.is_(None))
        if not auth.is_super_admin:
            bq = bq.filter(QuestionBank.tenant_id == tenant_id)
        bank = bq.first()
        if bank is None:
            checks.append(_check("BANK_NONEMPTY", BLOCK, f"题库 {bank_id} 不存在或越权",
                                 {"label": "检查题库", "path": "/question-banks"}))
        elif bank.status == "archived":
            checks.append(_check("BANK_NONEMPTY", BLOCK, f"题库 {bank.name} 已归档",
                                 {"label": "检查题库", "path": "/question-banks"}))
        else:
            n = question_sampler.count_bank_questions(db, bank_id, tenant_id=tenant_id)
            if n <= 0:
                checks.append(_check("BANK_NONEMPTY", BLOCK, "题库无题目",
                                     {"label": "导入题目", "path": "/question-banks"}))
            elif n < BANK_MIN_SUGGEST:
                checks.append(_check("BANK_NONEMPTY", WARN, f"题库题量 {n}，低于建议值 {BANK_MIN_SUGGEST}"))
            else:
                checks.append(_check("BANK_NONEMPTY", PASS, f"题库题量 {n}"))
    else:
        checks.append(_check("BANK_NONEMPTY", BLOCK, "必须选择题库",
                             {"label": "选择题库", "path": "/question-banks"}))

    # 4) Judge 模型可用（MODEL/HYBRID 时）
    judge_mode = str(cfg.get("judge_mode") or "RULE")
    if judge_mode in ("MODEL", "HYBRID"):
        judge_model = cfg.get("judge_model")
        cfgj = judge_pipeline.resolve_judge_model_cfg(db, judge_model, tenant_id=tenant_id)
        if cfgj is None:
            checks.append(_check("JUDGE_MODEL_AVAILABLE", BLOCK,
                                 f"裁判模型 {judge_model or judge_mode} 不可用（网关未配置或未启用）",
                                 {"label": "检查模型服务", "path": "/model-suite"}))
        else:
            checks.append(_check("JUDGE_MODEL_AVAILABLE", PASS,
                                 f"{cfgj.get('code') or cfgj.get('name')} 可用"))
    else:
        checks.append(_check("JUDGE_MODEL_AVAILABLE", PASS, "RULE 判定模式，无需裁判模型"))

    # 5) 事实源（仅配置了 fact_source_id 时检查，§ES11-G0-009）
    fs_id = int(cfg.get("fact_source_id") or 0)
    if fs_id > 0:
        fq = db.query(FactSource).filter(FactSource.id == fs_id, FactSource.deleted_at.is_(None))
        if not auth.is_super_admin:
            fq = fq.filter(FactSource.tenant_id == tenant_id)
        fs = fq.first()
        if fs is None:
            checks.append(_check("FACT_SOURCE_AVAILABLE", BLOCK, f"事实基准 {fs_id} 不存在或越权",
                                 {"label": "检查事实基准", "path": "/targets"}))
        elif fs.status != "active":
            checks.append(_check("FACT_SOURCE_AVAILABLE", BLOCK, f"事实基准 {fs.name} 状态 {fs.status}",
                                 {"label": "检查事实基准", "path": "/targets"}))
        else:
            checks.append(_check("FACT_SOURCE_AVAILABLE", PASS, f"事实基准 {fs.name} 可用"))

    # 6) 红队场景需已审批样本
    engine_code = str(cfg.get("engine_code") or "")
    if "REDTEAM" in engine_code.upper() or "JAILBREAK" in engine_code.upper():
        sq = db.query(RedteamSample).filter(
            RedteamSample.status == "APPROVED", RedteamSample.tenant_id == tenant_id
        )
        n = sq.count()
        if n == 0:
            checks.append(_check("REDTEAM_APPROVED_SAMPLES", BLOCK, "红队场景无已审批样本",
                                 {"label": "审批红队样本", "path": "/redteam"}))
        else:
            checks.append(_check("REDTEAM_APPROVED_SAMPLES", PASS, f"已审批样本 {n} 条"))

    # 7) 参数合法性
    ss = cfg.get("sample_size")
    if ss is not None:
        try:
            if int(ss) < 1:
                checks.append(_check("PARAMS_VALID", BLOCK, f"抽样数非法：{ss}"))
            else:
                checks.append(_check("PARAMS_VALID", PASS, "参数合法"))
        except (TypeError, ValueError):
            checks.append(_check("PARAMS_VALID", BLOCK, f"抽样数非法：{ss}"))
    else:
        checks.append(_check("PARAMS_VALID", PASS, "参数合法"))

    # 8) 版本归档标记（配置了 project_version_id 时）
    pv_id = int(cfg.get("project_version_id") or 0)
    if pv_id > 0:
        from ..models import ProjectVersion

        pv = db.get(ProjectVersion, pv_id)
        if pv is None:
            checks.append(_check("VERSION_ARCHIVED", WARN, f"项目版本 {pv_id} 不存在"))
        elif getattr(pv, "status", "") not in ("ARCHIVED", "archived", "RELEASED"):
            checks.append(_check("VERSION_ARCHIVED", WARN,
                                 f"版本 {pv.name} 未归档（状态 {pv.status}），结论归因可能漂移"))
        else:
            checks.append(_check("VERSION_ARCHIVED", PASS, f"版本 {pv.name} 已归档"))

    # 9) 执行权限（读-only 账号拦截；保留既有 eval:read 可发起的兼容）
    if auth.is_super_admin or "eval:run" in auth.perms or "eval:*" in auth.perms or "eval:read" in auth.perms:
        checks.append(_check("EXECUTE_PERMISSION", PASS, "具备执行权限"))
    else:
        checks.append(_check("EXECUTE_PERMISSION", BLOCK, "当前账号无评测执行权限",
                             {"label": "联系管理员授权", "path": "/admin/roles"}))

    # 10) 优化12 §4.3 ENGINE_CODE_VALID：engine_code 非空时必须命中注册表（BLOCK）
    if engine_code:
        from ..engines.registry import engine_registry

        if engine_code not in engine_registry.codes():
            checks.append(_check("ENGINE_CODE_VALID", BLOCK,
                                 f"引擎编码 {engine_code} 未在注册表中",
                                 {"label": "检查引擎配置", "path": "/engines"}))
        else:
            checks.append(_check("ENGINE_CODE_VALID", PASS, f"引擎 {engine_code} 已注册"))
    # engine_code 为空 → 不出项（存量调用 PASS 语义，不追加恒真条目）

    # 11) 优化12 §4.3 ENGINE_CATEGORY_MATCH：子类要求引擎 ∖ 本活动已规划引擎 → WARN（不阻断发起）
    # selected_categories = cfg.category_quotas 的 keys（v2.2 配额制对齐）
    category_quotas = cfg.get("category_quotas") or {}
    activity_id = cfg.get("activity_id")
    if category_quotas:
        from . import standards

        required: set[str] = set()
        for cat in category_quotas:
            required.update(standards.engine_codes_for_category(str(cat)))
        planned: set[str] = set()
        if activity_id:
            # 同 activity_id 下引擎 run 的 engine_code 集合（JSONB containment，零 DDL）
            pq = db.query(EvalRun.engine_code).filter(
                EvalRun.run_snapshot.contains({"activity_id": str(activity_id)}),
                EvalRun.engine_code.isnot(None),
            )
            if not auth.is_super_admin:
                pq = pq.filter(EvalRun.tenant_id == tenant_id)
            planned = {str(r[0]) for r in pq.all() if r[0]}
        gap = required - planned
        if required and gap:
            note = "（引擎轨尚未发起（非缺失证据））" if activity_id and not planned else ""
            checks.append(_check("ENGINE_CATEGORY_MATCH", WARN,
                                 f"子类要求但本活动未规划的引擎：{sorted(gap)}{note}"))
        elif required:
            checks.append(_check("ENGINE_CATEGORY_MATCH", PASS, "子类要求引擎均已规划"))
        # required 为空（类别无 tested_engines）→ 不出项

    # 12) 优化12 §4.5 QUOTA_ABOVE_MIN：抽题配额不得低于核定 min_questions（BLOCK）
    if category_quotas:
        from . import standards as _std

        bad = []
        for cat, quota in category_quotas.items():
            mn = _std.min_questions_for_category(str(cat))
            if mn is None:
                continue  # 未核定/未映射类别不在后端硬卡（向导提示口径）
            try:
                if int(quota) < mn:
                    bad.append(f"{cat}: 配额{quota} < 核定最小{mn}")
            except (TypeError, ValueError):
                bad.append(f"{cat}: 配额非法 {quota}")
        if bad:
            checks.append(_check("QUOTA_ABOVE_MIN", BLOCK,
                                 "抽题配额低于核定最小题量：" + "；".join(bad[:3]),
                                 {"label": "上调抽题配额", "path": "/eval-center"}))
        else:
            checks.append(_check("QUOTA_ABOVE_MIN", PASS, "抽题配额均不低于核定最小题量"))

    # 13) 优化12 §8.1a LIMIT_QUOTA_INSUFFICIENT：社区档档位预检（不信任前端）。
    # SCREENING 抽样探查降级出口豁免（探查合法、交付被门禁卡死）。
    if category_quotas and str(cfg.get("run_purpose") or "STANDARD").upper() != "SCREENING":
        from ..config import settings as _settings
        from ..limits import COMMUNITY_LIMITS

        if str(_settings.EDITION or "").lower() == "community":
            try:
                quota_sum = sum(int(v) for v in category_quotas.values())
            except (TypeError, ValueError):
                quota_sum = 0
            cap = int(COMMUNITY_LIMITS.get("question_total") or 0)
            if quota_sum > cap:
                checks.append(_check(
                    "LIMIT_QUOTA_INSUFFICIENT", BLOCK,
                    f"当前版本题量额度不足（需 {quota_sum} 题 / 档位上限 {cap} 题），"
                    "本次仅可发起抽样探查（SCREENING）",
                    {"label": "改走抽样探查", "path": "/eval-center"}))

    ready = not any(c["status"] == BLOCK for c in checks)
    return {"ready": ready, "checks": checks}


def revalidate_blocks(db: Session, cfg: dict[str, Any], auth) -> dict[str, Any]:
    """创建运行时服务端复校验（§3.1）：只重跑关键 BLOCK 项，不信任前端预检。

    返回完整 readiness 结果（供固化进 run_snapshot.readiness）；有 BLOCK 抛
    ES-BIZ-READY-0001。不发起真实连通调用（预检接口已覆盖，创建路径保持轻量）。
    """
    from ..errors import BizError

    out = check_readiness(db, cfg, auth, skip_connectivity=True)
    blocks = [c for c in out["checks"] if c["status"] == BLOCK]
    if blocks:
        raise BizError(
            "ES-BIZ-READY-0001",
            "服务端准备度复校验未通过：" + "；".join(f"{b['code']}:{b['reason']}" for b in blocks[:3]),
            # 优化12 §4.3（V0/V1 断言）：发起前参数/准备度拒绝统一 422
            http_status=422,
        )
    return out


# --------------------------------------------------------------------- G1


def classify_failure(
    *, error: str | None, output: str | None, final_verdict: str | None,
    want_judge: bool, judge_cfg: dict | None,
) -> str | None:
    """三类失败口径（§2.3）：CONFIG / INFRA / QUALITY；通过为 None。"""
    if error:
        if _INFRA_PAT.search(str(error)):
            return "INFRA"
        if _CONFIG_PAT.search(str(error)):
            return "CONFIG"
        # 被测调用异常且无回答 → 默认基础设施问题
        if not output:
            return "INFRA"
    if want_judge and judge_cfg is None:
        return "INFRA"  # Judge 模型不可用（§ES11-G1-005）
    if (final_verdict or "").upper() == "FAIL":
        return "QUALITY"
    return None


def build_evidence(
    *, failure_class: str | None, latency_ms: int | None,
    retrieval: list | None = None, citations: list | None = None,
    spans: list | None = None, extra: dict | None = None,
) -> dict[str, Any]:
    """evidence_payload schema v1.0（附录 B）。"""
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "failure_class": failure_class,
        "metrics": {"latency_ms": int(latency_ms or 0)},
    }
    if retrieval is not None:
        payload["retrieval"] = retrieval
    if citations is not None:
        payload["citations"] = citations
    if spans is not None:
        payload["spans"] = spans
    if extra:
        payload.update(extra)
    return payload


# ------------------------------------------------------- RAG 工作台（P7）

# 口径常量：检索首条分数低于该值判"低召回"；忠实度低于该值判"低忠实度"
RAG_LOW_SCORE = 0.3
RAG_LOW_FAITH = 0.6

# 五类阶段诊断谓词（单源）：summary 聚合与 items 过滤共用，SQL 方言 PostgreSQL
RAG_PREDICATES: dict[str, str] = {
    "NO_HIT": (
        "jsonb_typeof(evidence_payload->'retrieval')='array' "
        "AND jsonb_array_length(evidence_payload->'retrieval')=0"
    ),
    "LOW_RECALL": (
        f"jsonb_path_exists(evidence_payload, "
        f"'$.retrieval[0].score ? (@ < {RAG_LOW_SCORE})')"
    ),
    "LOW_FAITH": (
        f"jsonb_path_exists(evidence_payload, "
        f"'$.metrics.faithfulness ? (@ < {RAG_LOW_FAITH})')"
    ),
    "CITATION_ERROR": (
        "evidence_payload ? 'citations' AND evidence_payload ? 'retrieval' "
        "AND EXISTS (SELECT 1 FROM jsonb_array_elements(evidence_payload->'citations') c "
        "WHERE c ? 'doc_id' AND NOT EXISTS (SELECT 1 "
        "FROM jsonb_array_elements(evidence_payload->'retrieval') r "
        "WHERE r ? 'doc_id' AND r->>'doc_id' = c->>'doc_id'))"
    ),
    "ACL": (
        "jsonb_path_exists(evidence_payload, "
        "'$.retrieval[*].labels[*] ? (@ == \"acl_violation\")')"
    ),
    "UNGROUNDED": (
        "evidence_payload ? 'retrieval' AND evidence_payload ? 'citations' "
        "AND jsonb_typeof(evidence_payload->'citations')='array' "
        "AND jsonb_array_length(evidence_payload->'citations')=0"
    ),
}


def rag_summary(db: Session, run_id: int) -> dict[str, Any]:
    """运行级 RAG 遥测聚合（§5.4 P7 顶部指标，单条 SQL）。

    telemetry=0 表示无检索遥测（黑盒运行），前端显示"仅黑盒结论，无法定位检索阶段"。
    比率口径：分母恒为 telemetry 条目数。
    """
    cols = ", ".join(
        f"count(*) FILTER (WHERE {pred}) AS {key.lower()}"
        for key, pred in RAG_PREDICATES.items()
    )
    row = db.execute(
        text(
            f"SELECT count(*) AS total, "
            f"count(*) FILTER (WHERE evidence_payload ? 'retrieval') AS telemetry, "
            f"{cols} "
            "FROM eval_run_items WHERE run_id = :rid"
        ),
        {"rid": run_id},
    ).mappings().one()
    telemetry = int(row["telemetry"])
    def _rate(v: int) -> float | None:
        return round(int(v) / telemetry, 4) if telemetry else None
    return {
        "total": int(row["total"]),
        "telemetry": telemetry,
        "counts": {k: int(row[k.lower()]) for k in RAG_PREDICATES},  # PG 别名折叠小写
        "rates": {
            "retrieval_fail": _rate(row["no_hit"]),
            "low_recall": _rate(row["low_recall"]),
            "ungrounded": _rate(row["ungrounded"]),
            "acl_hit": _rate(row["acl"]),
            "conflict": _rate(row["low_faith"]),
            "citation_error": _rate(row["citation_error"]),
        },
        "thresholds": {"low_score": RAG_LOW_SCORE, "low_faith": RAG_LOW_FAITH},
    }


def failure_mix(db: Session, run_id: int) -> dict[str, int]:
    """按 evidence_payload.failure_class 统计三类失败。"""
    rows = (
        db.query(EvalRunItem.evidence_payload["failure_class"].astext, func.count())
        .filter(EvalRunItem.run_id == run_id)
        .group_by(EvalRunItem.evidence_payload["failure_class"].astext)
        .all()
    )
    mix = {"config": 0, "infra": 0, "quality": 0}
    for cls, n in rows:
        if cls and cls.lower() in mix:
            mix[cls.lower()] = int(n)
    return mix


# --------------------------------------------------------------------- G2


def review_progress(db: Session, run_id: int) -> dict[str, Any]:
    # context/source_ref 为 TEXT 存 JSON，cast 到 JSONB 后 contains 精确匹配
    ctx = cast(ReviewItem.context, JSONB)
    total = (
        db.query(func.count(ReviewItem.id))
        .filter(ReviewItem.source == "run_item", ctx.contains({"run_id": int(run_id)}))
    ).scalar() or 0
    done = (
        db.query(func.count(ReviewItem.id))
        .filter(ReviewItem.source == "run_item", ctx.contains({"run_id": int(run_id)}),
                ReviewItem.status.in_(("DONE", "DISCARDED")))
    ).scalar() or 0
    pending = int(total) - int(done)
    return {"total": int(total), "done": int(done), "pending": pending}


def g2_gate(db: Session, run: EvalRun) -> str:
    """G2：强制复核全部完成 → PASS；否则 BLOCK（结论未冻结）。"""
    prog = review_progress(db, int(run.id))
    return PASS if prog["pending"] == 0 else BLOCK


def concluded(db: Session, run: EvalRun) -> bool:
    """结论冻结派生态（§2.1）：强制复核全部完成 且 运行终态为成功类。"""
    if run.status not in ("PASSED", "SUCCESS", "FAILED"):
        return False
    return review_progress(db, int(run.id))["pending"] == 0


def judge_health(db: Session, run: EvalRun) -> dict[str, Any]:
    """运行级 Judge 健康：Kappa（租户级复核样本折算）+ 双轨一致率。"""
    rep = calibration.calibration_report(db, run.tenant_id, weeks=12)
    overall = rep.get("overall") or {}
    kappa = overall.get("kappa")
    n = int(overall.get("n") or 0)
    s = run.summary or {}
    return {
        "kappa": kappa,
        "sample": n,
        "sufficient": n >= 10,
        "agreement_rate": s.get("judge_agreement_rate"),
        "threshold": calibration.KAPPA_WARN,
    }


# --------------------------------------------------------------------- G3


CLOSE_CONDITIONS = [
    ("REMEDIATED_EVENT", "存在整改事件且变更引用非空"),
    ("RETEST_STARTED_EVENT", "存在真实复测事件"),
    ("RETEST_RUN", "关联复测运行 run_purpose=RETEST"),
    ("RETEST_TERMINAL", "复测运行到达成功终态"),
    ("RETEST_ITEMS_PASS", "原关联失败项在复测中达标"),
    ("VERIFY_EVIDENCE", "验证结论/验证人/时间齐备"),
]


def _defect_events(db: Session, defect_id: int) -> list[DefectEvent]:
    return (
        db.query(DefectEvent)
        .filter(DefectEvent.defect_id == defect_id)
        .order_by(DefectEvent.created_at.asc(), DefectEvent.id.asc())
        .all()
    )


def latest_retest_run(db: Session, defect: Defect) -> EvalRun | None:
    """缺陷最近一次复测运行（RETEST_STARTED 事件 run_id → EvalRun）。"""
    evs = [e for e in _defect_events(db, int(defect.id)) if e.event_type == "RETEST_STARTED" and e.run_id]
    if not evs:
        return None
    run = db.get(EvalRun, int(evs[-1].run_id))
    if run is None or run.deleted_at is not None:
        return None
    return run


def check_close_conditions(db: Session, defect: Defect, *, verifier: str | None = None) -> list[str]:
    """关闭六条件逐条断言（§4.2），返回未满足条件代码列表（空=可关闭）。"""
    unmet: list[str] = []
    events = _defect_events(db, int(defect.id))
    rem = [e for e in events if e.event_type == "REMEDIATED"]
    if not rem or not (rem[-1].evidence or {}).get("change_refs"):
        unmet.append("REMEDIATED_EVENT")
    rets = [e for e in events if e.event_type == "RETEST_STARTED"]
    if not rets:
        unmet.append("RETEST_STARTED_EVENT")
    run = latest_retest_run(db, defect)
    if run is None or run.run_purpose != "RETEST":
        unmet.append("RETEST_RUN")
        unmet.append("RETEST_TERMINAL")
        unmet.append("RETEST_ITEMS_PASS")
    else:
        if run.status not in ("PASSED", "SUCCESS"):
            unmet.append("RETEST_TERMINAL")
        # 原失败项在复测中达标：origin 指向原运行项时精确比对；否则按复测整体判定
        if run.verdict == "FAIL" or int((run.summary or {}).get("quality_fail") or 0) > 0:
            if defect.origin_type == "RUN_ITEM" and defect.origin_id:
                orig = db.get(EvalRunItem, int(defect.origin_id))
                if orig is not None:
                    re_item = (
                        db.query(EvalRunItem)
                        .filter(EvalRunItem.run_id == run.id,
                                EvalRunItem.question_id == orig.question_id)
                        .first()
                    )
                    if re_item is None or (re_item.final_verdict or "").upper() != "PASS":
                        unmet.append("RETEST_ITEMS_PASS")
    if verifier is None:
        unmet.append("VERIFY_EVIDENCE")
    return unmet


# --------------------------------------------------------------------- G4


def open_p0p1_with_waivers(db: Session, tenant_id: int) -> tuple[list[int], set[int]]:
    """G4 P0P1 口径单源：未闭环 P0/P1 缺陷 ID 列表 + 风险接受豁免集合。

    豁免判定（ES11-G4-004）：最近一次处置事件（WAIVED/REOPENED）为 WAIVED
    才生效；豁免后再重开自动失效——defect_events 只追加，不改写历史。
    交付包 manifest 的 risk_acceptance 与本函数同源（delivery.py）。
    """
    open_ids = [
        int(r[0])
        for r in db.query(Defect.id).filter(
            Defect.tenant_id == tenant_id,
            Defect.deleted_at.is_(None),
            Defect.severity.in_(("P0", "P1")),
            Defect.status.in_(("NEW", "OPEN", "FIXED", "VERIFYING", "REOPENED")),
        ).all()
    ]
    waived_ids: set[int] = set()
    if open_ids:
        last_disp = (
            db.query(DefectEvent.defect_id,
                     func.max(DefectEvent.id).label("max_id"))
            .filter(DefectEvent.defect_id.in_(open_ids),
                    DefectEvent.event_type.in_(("WAIVED", "REOPENED")))
            .group_by(DefectEvent.defect_id)
            .subquery()
        )
        waived_ids = {
            int(r[0])
            for r in db.query(DefectEvent.defect_id)
            .join(last_disp, DefectEvent.id == last_disp.c.max_id)
            .filter(DefectEvent.event_type == "WAIVED").all()
        }
    return open_ids, waived_ids


def risk_acceptance_records(db: Session, tenant_id: int) -> list[dict[str, Any]]:
    """交付包 manifest 的"风险接受记录"（§3.6 / G4-007）。

    与 open_p0p1_with_waivers 同源：取当前未闭环 P0/P1 中最近处置事件为
    WAIVED 的缺陷，附豁免人/原因/期限（读最近 WAIVED 事件的 note+evidence）。
    """
    open_ids, waived_ids = open_p0p1_with_waivers(db, tenant_id)
    if not waived_ids:
        return []
    recs: list[dict[str, Any]] = []
    for did in sorted(waived_ids):
        d = db.get(Defect, did)
        if d is None:
            continue
        ev = (
            db.query(DefectEvent)
            .filter(DefectEvent.defect_id == did,
                    DefectEvent.event_type == "WAIVED")
            .order_by(DefectEvent.id.desc())
            .first()
        )
        evd = (ev.evidence or {}) if ev else {}
        recs.append({
            "defect_id": did,
            "defect_no": d.defect_no,
            "title": d.title,
            "severity": d.severity,
            "status": d.status,
            "waived_by": ev.actor_name if ev else None,
            "waived_at": ev.created_at.isoformat() if (ev and ev.created_at) else None,
            "reason": evd.get("waive_reason") or (ev.note if ev else None),
            "deadline": evd.get("deadline"),
        })
    return recs


def delivery_readiness(db: Session, run: EvalRun, report: Report | None = None) -> dict[str, Any]:
    """G4 报告交付清单（§2.2/§3.6）。阻塞项带 {label, path} 修复入口。"""
    checklist: list[dict[str, Any]] = []

    # 1) 运行完成且无未解释 CONFIG/INFRA 阻塞
    if run.status not in ("PASSED", "SUCCESS", "FAILED"):
        checklist.append(_check("RUN_TERMINAL", BLOCK, f"运行未完成（{run.status}）",
                                {"label": "查看运行", "path": f"/eval/runs/{run.id}"}))
    else:
        checklist.append(_check("RUN_TERMINAL", PASS, f"运行终态 {run.status}"))
    mix = failure_mix(db, int(run.id))
    if mix["config"] or mix["infra"]:
        checklist.append(_check("FAILURE_EXPLAINED", WARN,
                                f"存在配置/基础设施失败 config={mix['config']} infra={mix['infra']}，需人工确认解释"))
    else:
        checklist.append(_check("FAILURE_EXPLAINED", PASS, "无配置/基础设施失败"))

    # 2) 强制复核完成
    prog = review_progress(db, int(run.id))
    if prog["pending"]:
        checklist.append(_check("REVIEW_DONE", BLOCK, f"待复核 {prog['pending']} 项",
                                {"label": "去复核", "path": "/review"}))
    else:
        checklist.append(_check("REVIEW_DONE", PASS, "强制复核全部完成"))

    # 3) Kappa 达标或豁免
    jh = judge_health(db, run)
    waived_k = bool((run.summary or {}).get("kappa_waived"))
    if not jh["sufficient"]:
        checklist.append(_check("KAPPA", WARN, "Judge 复核样本不足，无法评估 Kappa"))
    elif jh["kappa"] is not None and jh["kappa"] < jh["threshold"]:
        if waived_k:
            checklist.append(_check("KAPPA", PASS, f"Kappa {jh['kappa']} 低于阈值，已豁免"))
        else:
            checklist.append(_check("KAPPA", BLOCK, f"Kappa {jh['kappa']} < {jh['threshold']} 且无豁免",
                                    {"label": "查看 Judge 健康", "path": "/review"}))
    else:
        checklist.append(_check("KAPPA", PASS, f"Kappa {jh['kappa']} 达标"))

    # 4) P0/P1 缺陷已关闭或有风险接受（WAIVED 事件，ES11-G4-004）
    tenant_id = run.tenant_id or 1
    open_ids, waived_ids = open_p0p1_with_waivers(db, tenant_id)
    blocking = len(open_ids) - len(waived_ids)
    if blocking:
        checklist.append(_check("P0P1_CLOSED", BLOCK,
                                f"未闭环 P0/P1 缺陷 {blocking} 个"
                                + (f"（另 {len(waived_ids)} 个已风险接受）" if waived_ids else ""),
                                {"label": "处理缺陷", "path": "/defects"}))
    elif waived_ids:
        checklist.append(_check("P0P1_CLOSED", PASS,
                                f"无未闭环 P0/P1 缺陷（{len(waived_ids)} 个风险接受放行，"
                                "豁免人/原因见缺陷时间线）"))
    else:
        checklist.append(_check("P0P1_CLOSED", PASS, "无未闭环 P0/P1 缺陷"))

    # 5) 绑定完整（版本/目标/题库/快照）
    missing_bind = []
    if not (run.target_id or "").strip():
        missing_bind.append("被测系统")
    if not run.question_bank_id:
        missing_bind.append("题库")
    if not run.run_snapshot:
        missing_bind.append("运行快照")
    if missing_bind:
        checklist.append(_check("BINDINGS", BLOCK, "缺少绑定：" + "、".join(missing_bind),
                                {"label": "查看运行", "path": f"/eval/runs/{run.id}"}))
    else:
        checklist.append(_check("BINDINGS", PASS, "版本/目标/题库/快照绑定齐备"))

    # 6) 非演示模式
    snap = run.run_snapshot or {}
    if snap.get("target_mode") == "INTERNAL_DEMO" or not (run.target_id or "").strip():
        checklist.append(_check("NOT_DEMO", BLOCK, "演示模式（INTERNAL_DEMO）不得正式交付",
                                {"label": "配置被测系统", "path": "/targets"}))
    else:
        checklist.append(_check("NOT_DEMO", PASS, "非演示模式"))

    # 7) 交付包生成 + sha256
    from ..models import DeliveryPackage

    pkg = (
        db.query(DeliveryPackage)
        .filter(DeliveryPackage.run_id == run.id, DeliveryPackage.status == "ready")
        .order_by(DeliveryPackage.id.desc())
        .first()
    )
    if pkg is None:
        checklist.append(_check("PACKAGE", WARN, "尚未生成正式交付包",
                                {"label": "生成交付包", "path": f"/eval/runs/{run.id}"}))
    elif not (pkg.items or []):
        checklist.append(_check("PACKAGE", BLOCK, "交付包缺少 sha256 清单",
                                {"label": "重新生成", "path": f"/eval/runs/{run.id}"}))
    else:
        checklist.append(_check("PACKAGE", PASS, f"交付包 {pkg.package_no} 已生成"))

    # 8) ES11 修复 + 优化12 §8.5：TC260/GBT45654 监管阈值核定检查。
    # 新口径 run（standards_ver 以 GBT45654 开头）+ STANDARDS_STRICT_MODE=on →
    # 未核定 BLOCK（防未核定数字背书，ES9-P-11）；旧口径 run / strict=off →
    # 保持 WARN（存量断言不破，铁律 7）。SCREENING 跳过本项（§8.6 第 2 条）。
    from ..config import settings as _settings
    from . import dimension_coverage as _dc

    strict_on = str(getattr(_settings, "STANDARDS_STRICT_MODE", "on")) != "off"
    eff_ver = _dc.resolve_effective_standards_ver(db, run)
    new_caliber = _dc.is_new_caliber(eff_ver)
    is_screening = str(run.run_purpose or "").upper() == "SCREENING"
    if not is_screening:
        try:
            from .standards import missing_threshold_categories

            miss = missing_threshold_categories()
            if miss:
                if new_caliber and strict_on:
                    checklist.append(_check("STD_THRESHOLDS", BLOCK,
                                            "GBT45654 监管阈值未核定，禁止正式交付（交付人依 GB/T 45654 原文"
                                            "人工填入 tc260.yaml）：" + "、".join(miss[:8]),
                                            {"label": "查看被测标准", "path": "/targets"}))
                else:
                    checklist.append(_check("STD_THRESHOLDS", WARN,
                                            "TC260 阈值未核定（交付人依 GB/T 45654 原文人工填入 tc260.yaml）："
                                            + "、".join(miss[:8]),
                                            {"label": "查看被测标准", "path": "/targets"}))
            else:
                checklist.append(_check("STD_THRESHOLDS", PASS, "TC260 阈值已核定"))
        except Exception:  # noqa: BLE001 标准配置缺失（ES-STD-001/002）不影响 G4 其余项
            pass

    # 9) 优化12 §8.3：G4 第 10 项 DIMENSION_COVERAGE（仅新口径非 SCREENING run；
    # 旧口径不追加，保持原 9 项清单 → 存量 e2e 断言不破）
    if new_caliber and not is_screening:
        try:
            cov = _dc.coverage_matrix(db, run, auth=None)
        except Exception:  # noqa: BLE001 配置异常不拖挂 G4 其余项
            cov = None
        if cov is not None:
            if not cov["overall"]["block_items"]:
                # SCREENING 恒出草稿水印包的收口兜底在 routers/delivery.py（§8.6-3）
                if cov["overall"]["warn_items"]:
                    checklist.append(_check(
                        "DIMENSION_COVERAGE", WARN,
                        "；".join(cov["overall"]["warn_items"][:3])))
                else:
                    ref = cov.get("refusal") or {}
                    checklist.append(_check(
                        "DIMENSION_COVERAGE", PASS,
                        "五维度题级/引擎级覆盖达标"
                        + (f"（拒答合格率 {ref.get('refuse_pass_rate')} / "
                           f"误拒率 {ref.get('answer_false_refuse_rate')}）"
                           if ref.get("refuse_pass_rate") is not None else "")))
            else:
                blocks = cov["overall"]["block_items"]
                first_code = blocks[0].split("/")[0] if "/" in blocks[0] else None
                sub_code = None
                seg = blocks[0].split("/")[1] if first_code else None
                if seg:
                    sub_code = seg.split(" ")[0].strip() or None
                # OBS-003：深链统一为真实路由（QuestionBanksList.jsx L24 直接解析 ?sub=），
                # 不再经 /eval-center?tab=banks 重写链路，消除常量与路由表不一致的维护隐患。
                action_path = "/question-banks"
                if sub_code:
                    action_path += f"?sub={sub_code}"
                checklist.append(_check(
                    "DIMENSION_COVERAGE", BLOCK,
                    "；".join(blocks[:3]) + (f"（共 {len(blocks)} 项缺口）" if len(blocks) > 3 else ""),
                    {"label": "补题", "path": action_path}))

    deliverable = not any(c["status"] == BLOCK for c in checklist)
    return {"deliverable": deliverable, "checklist": checklist, "failure_mix": mix}


def baseline_comparable(run_a: EvalRun, run_b: EvalRun) -> tuple[bool, list[str]]:
    """同口径比较判定（§3.3）：任一要素不同即不可比。"""
    sa, sb = run_a.run_snapshot or {}, run_b.run_snapshot or {}
    reasons: list[str] = []
    pairs = (
        ("bank_version", run_a.question_bank_id, run_b.question_bank_id),
        ("dataset_version", run_a.dataset_version, run_b.dataset_version),
        ("seed", sa.get("sample_seed"), sb.get("sample_seed")),
        ("judge_model", sa.get("judge_model") or run_a.judge_model, sb.get("judge_model") or run_b.judge_model),
        ("judge_prompt_hash", sa.get("judge_prompt_hash"), sb.get("judge_prompt_hash")),
        ("fact_source", run_a.fact_source_id, run_b.fact_source_id),
        ("target_mode", sa.get("target_mode"), sb.get("target_mode")),
        # 优化12 §9.4 第八项：跨标准版本护栏（None 视为独立取值，
        # 与旧口径天然不等 → 自动判不可比，无需特判）
        ("standards_ver", sa.get("standards_ver"), sb.get("standards_ver")),
    )
    for name, va, vb in pairs:
        if va != vb:
            reasons.append(name)
    return (not reasons), reasons


def item_key(item: EvalRunItem) -> str:
    """题目稳定标识：question_id 优先，临时题按内容哈希（§3.3）。"""
    if item.question_id:
        return f"q:{item.question_id}"
    h = hashlib.md5((item.prompt or "").encode("utf-8")).hexdigest()
    return f"h:{h}"
