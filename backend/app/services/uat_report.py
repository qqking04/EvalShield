# SPDX-License-Identifier: BUSL-1.1
"""ES9 UAT 验收报告聚合层（共享域 —— 禁止 import commercial）。

职责：把「已完成的测试任务 + 门禁规则 + 缺陷 + 环境指纹」聚合为 8 节纯 dict。
渲染层（uat_render）零业务逻辑，全部计算在本文件完成 —— 保证可单测。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import Defect, Report, TestTask
from ..errors import BizError
from .quality_gate import load_rules, task_metrics, gate_view, _CRITICAL_SEV

# 允许进入验收的任务终态（TaskStatus 实际口径：SUCCESS / COMPLETED_WITH_RISK）
_UAT_TASK_STATUS = {"SUCCESS", "COMPLETED_WITH_RISK"}


def _validate_tasks(db: Session, project_id: int, tenant_id: int,
                    task_ids: list[int]) -> list[TestTask]:
    """task_ids → TestTask 列表；空集/重复 400（ES9-UAT-0006）；
    查不到/不属于该项目/该租户 → 按不存在处理（ES9-UAT-0006，不泄露存在性）；
    非终态 → ES9-UAT-0006；gate_rules 缺失 → ES9-UAT-0001。"""
    if not task_ids or len(set(task_ids)) != len(task_ids):
        raise BizError("ES9-UAT-0006", "task_ids 不能为空且不得重复", http_status=400)
    tasks = (
        db.query(TestTask)
        .filter(
            TestTask.id.in_(task_ids),
            TestTask.project_id == project_id,
            TestTask.tenant_id == tenant_id,
            TestTask.deleted_at.is_(None),
        )
        .all()
    )
    if len(tasks) != len(task_ids):
        raise BizError("ES9-UAT-0006", "存在无效任务（不存在或无权访问）", http_status=400)
    for t in tasks:
        if t.status not in _UAT_TASK_STATUS:
            raise BizError(
                "ES9-UAT-0006",
                f"任务 {t.task_no} 状态为 {t.status}，仅终态任务可纳入验收",
                http_status=400,
            )
        if not load_rules(t.gate_rules):
            # 设计方案 §2-§5 硬校验：不静默跳过
            raise BizError(
                "ES9-UAT-0001",
                f"任务 {t.task_no} 未配置验收门禁（gate_rules 为空）",
                http_status=400,
            )
    return sorted(tasks, key=lambda x: x.task_no)


def _merge_criteria(tasks: list[TestTask],
                    override: list[dict] | None) -> list[dict]:
    """§2 验收标准：各任务 gate_rules 合并去重（同 metric+op 保留阈值更严者）；
    criteria_override 非空时整表替换（生成向导 Step2 覆写语义）。"""
    if override:
        return override
    merged: dict[tuple[str, str], dict] = {}
    for t in tasks:
        for r in load_rules(t.gate_rules):
            key = (r["metric"], r["op"])
            old = merged.get(key)
            if old is None:
                merged[key] = dict(r)
            else:
                # 更严：gte/gt 取大阈值，lt/lte 取小阈值
                stricter = (
                    r["threshold"] > old["threshold"]
                    if r["op"] in ("gte", "gt")
                    else r["threshold"] < old["threshold"]
                )
                if stricter:
                    merged[key] = dict(r)
    return list(merged.values())


def compute_report_hash(payload: dict) -> str:
    """规范化 JSON（sort_keys、去空白）sha256；尾注与审计链留档用。"""
    canon = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _latest_report_per_task(db: Session, tasks: list[TestTask]) -> dict[int, Report]:
    """每个 task 取最新一条 FULL 测试报告（§4/§6 数据源）。"""
    out: dict[int, Report] = {}
    for t in tasks:
        rep = (
            db.query(Report)
            .filter(Report.task_id == t.id,
                    Report.report_subtype.is_(None),   # 只要测试报告
                    Report.deleted_at.is_(None))
            .order_by(Report.generated_at.desc())
            .first()
        )
        if rep is not None:
            out[t.id] = rep
    return out


def build_uat_payload(db: Session, project_id: int, tenant_id: int,
                      task_ids: list[int], criteria_override: list[dict] | None = None,
                      contract_no: str | None = None,
                      defect_disposals: dict[int, dict] | None = None) -> dict:
    """8 节聚合（设计方案 §2 字段级定义逐项对应）。返回纯 dict，可直接 json 序列化。"""
    tasks = _validate_tasks(db, project_id, tenant_id, task_ids)
    reports = _latest_report_per_task(db, tasks)
    criteria = _merge_criteria(tasks, criteria_override)

    # ---- §4 执行结果：通过率按用例数加权 ----
    per_task, total_cases, weighted_pass = [], 0, 0.0
    for t in tasks:
        m = task_metrics(db, t)
        rep = reports.get(t.id)
        summary = (rep.summary or {}) if rep else {}
        cases = int(summary.get("total") or (t.summary or {}).get("total") or 0)
        weighted_pass += float(m.get("pass_rate") or 0.0) * cases
        total_cases += cases
        verdict = gate_view(t).get("verdict") if t.gate_rules else None
        per_task.append({
            "task_id": t.id,
            "task_no": t.task_no, "title": t.name, "cases": cases,
            "pass_rate": m.get("pass_rate"), "verdict": verdict,
            "started_at": _iso(getattr(t, "started_at", None)),
            "finished_at": _iso(getattr(t, "finished_at", None)),
        })
    agg_pass_rate = (weighted_pass / total_cases) if total_cases else 0.0

    # ---- §5 门禁结论：以合并标准逐条重判（跨任务口径） ----
    checks = []
    for r in criteria:
        actual = _agg_metric_value(r["metric"], per_task, tasks, db)
        passed = _cmp_value(r["op"], actual, r["threshold"])
        checks.append({**r, "actual": actual, "passed": passed})
    gate_verdict = "PASSED" if checks and all(c["passed"] for c in checks) else "FAILED"

    # ---- §6 性能与安全：跨任务加权合并（权重=用例数） ----
    perf = _merge_perf(reports, per_task)
    sec = _security_section(reports)

    # ---- §7 遗留缺陷（未闭环严重级缺陷，处置意见人工覆写） ----
    defects = _open_defects(db, project_id, tenant_id)
    for d in defects:
        d["disposal"] = (defect_disposals or {}).get(d.get("id") or -1, d.get("disposal"))

    # ---- §3/§8 与尾注 ----
    env = _merge_env(reports)
    payload: dict[str, Any] = {
        "uat_version": None,  # 落库时按版本链回填
        "task_ids": [t.id for t in tasks],
        "sections": {
            "s1_overview": {"project_id": project_id, "task_nos": [t.task_no for t in tasks]},
            "s2_scope": {"tasks": per_task, "criteria": criteria,
                         "criteria_source": "override" if criteria_override else "gate_rules",
                         "contract_no": contract_no or ""},
            "s3_environment": env,
            "s4_results": {"per_task": per_task, "total_cases": total_cases,
                           "agg_pass_rate": round(agg_pass_rate, 4)},
            "s5_gate": {"checks": checks, "verdict": gate_verdict},
            "s6_perf_security": {"performance": perf, "security": sec},
            "s7_defects": defects,
            "s8_conclusion": {"verdict_suggested": gate_verdict, "verdict": None,
                              "note": "", "signer_vendor": None, "signer_customer": None,
                              "finalized_at": None},
        },
        "audit_summary": _audit_summary(db, tasks),
    }
    payload["report_hash"] = compute_report_hash(payload)
    return payload


# ---------------------------------------------------------------------------
# 本文件私有工具（口径与 quality_gate._cmp 对齐；操作符仅 lt/lte/gt/gte）
# ---------------------------------------------------------------------------
def _iso(dt: datetime | None) -> str:
    """datetime → ISO 串（None → 空串，渲染层直接展示）。"""
    return dt.isoformat() if isinstance(dt, datetime) else ""


def _audit_summary(db: Session, tasks: list[TestTask]) -> dict:
    """全局审计轨迹摘要 + 任务时间窗（build_audit_trail_summary 实际签名无 task_ids，
    任务范围以 start/end 时间窗口径传入）。"""
    from .report_generator import build_audit_trail_summary  # 延迟 import 防环

    starts = [t.started_at for t in tasks if t.started_at]
    ends = [t.finished_at for t in tasks if t.finished_at]
    summary = build_audit_trail_summary(
        db,
        start_time=min(starts) if starts else None,
        end_time=max(ends) if ends else None,
    )
    summary["task_ids"] = [t.id for t in tasks]
    summary["task_nos"] = [t.task_no for t in tasks]
    return summary


def _cmp_value(op: str, actual, threshold) -> bool:
    if actual is None:
        return False
    if op == "lt":
        return actual < threshold
    if op == "lte":
        return actual <= threshold
    if op == "gt":
        return actual > threshold
    if op == "gte":
        return actual >= threshold
    return False


def _agg_metric_value(metric: str, per_task: list[dict], tasks, db) -> float | None:
    """聚合指标取值：pass_rate 跨任务按用例数加权；其余（计数/比率类）按任务求和。
    无法聚合的指标返回 None（判 not passed，宁严勿松）。"""
    if metric == "pass_rate":
        num = den = 0.0
        for row in per_task:
            num += float(row.get("pass_rate") or 0.0) * row["cases"]
            den += row["cases"]
        return (num / den) if den else None
    vals = []
    for t in tasks:
        m = task_metrics(db, t)
        if metric in m:
            vals.append(m[metric])
    if not vals:
        return None
    return sum(vals)  # 计数类默认求和；rt 类在 §6 单独加权展示


def _merge_perf(reports: dict[int, Report], per_task: list[dict]) -> dict:
    """rt_p50/p95/p99、tps、error_rate 加权合并（权重=用例数）。"""
    by_task_no = {r.task_no: r for r in reports.values() if r.task_no}
    acc: dict[str, float] = {}
    den = 0
    for row in per_task:
        rep = by_task_no.get(row["task_no"])
        pm = (rep.performance_metrics or {}) if rep else {}
        w = row["cases"] or 0
        den += w
        for k in ("rt_p50", "rt_p95", "rt_p99", "tps", "error_rate"):
            if pm.get(k) is not None:
                acc[k] = acc.get(k, 0.0) + float(pm[k]) * w
    return {k: (round(v / den, 4) if den else None) for k, v in acc.items()}


def _security_section(reports: dict[int, Report]) -> dict:
    """risk_level 取所选报告中最高级；risk_basis 拼接；红队覆盖率缺数据时如实 None。"""
    order = {"NONE": -1, "LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    top, bases = None, []
    for rep in reports.values():
        lvl = (rep.risk_level or "").strip()
        if not lvl:
            continue
        if top is None or order.get(lvl.upper(), -1) > order.get(top.upper(), -1):
            top = lvl
        if rep.risk_basis:
            bases.append(str(rep.risk_basis))
    return {"risk_level": top, "risk_basis": bases, "redteam_coverage": None}


def _open_defects(db, project_id, tenant_id) -> list[dict]:
    """未闭环的严重级缺陷（P0/CRITICAL/FATAL/严重/致命口径 + 状态未关闭 + 软删除外）。"""
    rows = (
        db.query(Defect)
        .filter(Defect.project_id == project_id,
                Defect.tenant_id == tenant_id,
                Defect.deleted_at.is_(None),
                Defect.severity.in_(tuple(sorted(_CRITICAL_SEV))),
                Defect.status.notin_(("CLOSED", "已关闭")))
        .order_by(Defect.created_at.desc())
        .all()
    )
    return [{"id": d.id, "defect_no": d.defect_no, "title": d.title,
             "severity": d.severity, "status": d.status,
             "task_id": d.task_id, "disposal": None} for d in rows]


def _merge_env(reports: dict[int, Report]) -> dict:
    """环境指纹：取最新报告的环境；多报告环境不一致时给出 distinct 计数供人工确认。"""
    envs = [dict(r.environment or {}) for r in reports.values()]
    merged = envs[-1] if envs else {}
    merged["distinct_env_count"] = len({json.dumps(e, sort_keys=True, default=str) for e in envs})
    return merged


def next_uat_no(db: Session, project_code: str) -> str:
    """报告编号 UAT-{project_code}-{seq}：按 project_code 前缀取最大序号 +1。"""
    prefix = f"UAT-{project_code}-"
    rows = (
        db.query(Report.report_no)
        .filter(Report.report_subtype == "UAT", Report.report_no.like(prefix + "%"))
        .all()
    )
    seq = 0
    for (no,) in rows:
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", no or "")
        if m:
            seq = max(seq, int(m.group(1)))
    return f"{prefix}{seq + 1:03d}"


def next_version(db: Session, parent_report_id: int | None) -> int:
    """版本链号：无 parent=1；有 parent 时取 parent.content.uat_version + 1。"""
    if parent_report_id is None:
        return 1
    parent = db.get(Report, parent_report_id)
    raw = (parent.content or {}).get("uat_version") if parent else None
    try:
        return int(raw) + 1
    except (TypeError, ValueError):  # 脏数据（无版本号）按首版后续处理
        return 2
