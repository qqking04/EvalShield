# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M5：CI 质量门禁（方案 §6.2）。

语义：task.gate_rules 存 JSON 数组
    [{"metric": "pass_rate", "op": "gte", "threshold": 0.9}, ...]
每条规则是一个**必须满足的通过条件**：op(actual, threshold) 成立则该条通过；
任一不成立 → verdict=FAILED；全部成立 → PASSED；
规则涉及的指标本任务均未产出（如无幻觉引擎步骤）→ NOT_EVALUATED。
gate_rules 为空数组的任务视为非门禁任务，不评估、gate_result 保持 NULL。

指标口径与 M4 monitor._batch_metrics 对齐（单任务版）：
- pass_rate：summary.pass_rate（缺省按 Σpassed/Σtotal 回算）
- injection_success_rate：summary.step_results[*].summary key=prompt_injection_safe_rate
  的 pass_rate 原值均值（安全率，越高越好）
- hallucination_rate：1 - key=hallucination_score 的 pass_rate 均值
- critical_defects：defects 表按 task_id 关联、severity 命中 P0 兼容集合的计数
  （口径与 services.risk._SEV_CRITICAL / _business_common._SEV_P0 同集合）
"""

from __future__ import annotations

import json
import logging

from ..errors import BizError
from ..models import Defect, TestTask

logger = logging.getLogger("evalshield.gate")

# 门禁指标白名单（方案 §6.2；前端下拉与此一致）
GATE_METRICS = (
    "pass_rate",
    "critical_defects",
    "hallucination_rate",
    "injection_success_rate",
)

# 比较算子白名单
GATE_OPS = ("lt", "lte", "gt", "gte")

# 严重缺陷兼容集合（与 services.risk._SEV_CRITICAL 同口径，防口径漂移另立一份会引入环依赖）
_CRITICAL_SEV = {"P0", "CRITICAL", "FATAL", "严重", "致命"}

# 结论枚举（gate_result 列值；NULL=未评估）
VERDICT_PASSED = "PASSED"
VERDICT_FAILED = "FAILED"
VERDICT_NOT_EVALUATED = "NOT_EVALUATED"


def load_rules(raw: str | None) -> list[dict]:
    """宽松解析 gate_rules（评估/展示侧）：非法 JSON / 缺字段 / 白名单外的条目直接丢弃。"""
    try:
        arr = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(arr, list):
        return []
    return [
        r
        for r in arr
        if isinstance(r, dict)
        and r.get("metric") in GATE_METRICS
        and str(r.get("op") or "") in GATE_OPS
        and _as_float(r.get("threshold")) is not None
    ]


def validate_gate_rules(value) -> str:
    """API 侧严格校验（POST/PUT /tasks）：返回规范化 JSON 字符串，非法抛 BizError。

    入参兼容 list（JSON 数组）与 str（前端序列化后的 JSON 文本）；None/空 = "[]"。
    """
    if value is None:
        return "[]"
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except (TypeError, ValueError):
            raise BizError("ES-GATE-0001", "gate_rules 必须是合法 JSON 数组") from None
    if not isinstance(raw, list):
        raise BizError("ES-GATE-0001", "gate_rules 必须是 JSON 数组")
    out: list[dict] = []
    for i, r in enumerate(raw, 1):
        if not isinstance(r, dict):
            raise BizError("ES-GATE-0002", f"gate_rules 第 {i} 条必须是对象")
        metric = r.get("metric")
        if metric not in GATE_METRICS:
            raise BizError(
                "ES-GATE-0003",
                f"gate_rules 第 {i} 条 metric 非法（可选：{'/'.join(GATE_METRICS)}）",
            )
        op = str(r.get("op") or "")
        if op not in GATE_OPS:
            raise BizError(
                "ES-GATE-0004",
                f"gate_rules 第 {i} 条 op 非法（可选：{'/'.join(GATE_OPS)}）",
            )
        threshold = _as_float(r.get("threshold"))
        if threshold is None:
            raise BizError("ES-GATE-0005", f"gate_rules 第 {i} 条 threshold 必须是数字")
        out.append({"metric": str(metric), "op": op, "threshold": threshold})
    if len(out) > 20:
        raise BizError("ES-GATE-0006", "gate_rules 最多 20 条")
    return json.dumps(out, ensure_ascii=False)


def _as_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cmp(op: str, actual: float, threshold: float) -> bool:
    """规则通过条件：op(actual, threshold) 成立即 ok。"""
    if op == "lt":
        return actual < threshold
    if op == "lte":
        return actual <= threshold
    if op == "gt":
        return actual > threshold
    if op == "gte":
        return actual >= threshold
    return False


def _critical_defects(db, task: TestTask) -> int:
    """按 task_id 关联统计严重缺陷数（软删除外；severity 归一后命中 P0 兼容集合）。"""
    rows = (
        db.query(Defect.severity)
        .filter(
            Defect.task_id == task.id,
            Defect.tenant_id == task.tenant_id,
            Defect.deleted_at.is_(None),
        )
        .all()
    )
    return sum(1 for (sev,) in rows if str(sev or "").strip().upper() in _CRITICAL_SEV)


def task_metrics(db, task: TestTask) -> dict[str, float]:
    """单任务门禁指标面（口径映射见模块 docstring）。"""
    s = task.summary if isinstance(task.summary, dict) else {}
    metrics: dict[str, float] = {}
    # pass_rate：优先 summary 直取，缺省按 Σpassed/Σtotal 回算
    pr = _as_float(s.get("pass_rate"))
    if pr is None:
        total = int(s.get("total") or 0)
        passed = int(s.get("passed") or 0)
        if total > 0:
            pr = round(passed / total, 4)
    if pr is not None:
        metrics["pass_rate"] = pr
    # 引擎步骤指标：与 monitor._batch_metrics 同 key 匹配
    inj_vals: list[float] = []
    hal_vals: list[float] = []
    for sr in s.get("step_results") or []:
        es = (sr or {}).get("summary") or {}
        key = es.get("key")
        val = _as_float(es.get("pass_rate"))
        if val is None:
            continue
        if key == "prompt_injection_safe_rate":
            inj_vals.append(val)
        elif key == "hallucination_score":
            # 引擎产出为非幻觉通过率，幻觉率取反
            hal_vals.append(round(1.0 - val, 4))
    if inj_vals:
        metrics["injection_success_rate"] = round(sum(inj_vals) / len(inj_vals), 4)
    if hal_vals:
        metrics["hallucination_rate"] = round(sum(hal_vals) / len(hal_vals), 4)
    # critical_defects：恒可产出（0 也是有效值）
    metrics["critical_defects"] = float(_critical_defects(db, task))
    return metrics


def evaluate_gate(db, task: TestTask) -> dict | None:
    """任务终态门禁评估：解析规则 → 逐条判定 → 写 gate_result。

    返回 {verdict, checks:[{metric,op,threshold,actual,ok}]}；
    非门禁任务（gate_rules 空）返回 None 且不落库。
    """
    rules = load_rules(task.gate_rules)
    if not rules:
        return None
    metrics = task_metrics(db, task)
    checks: list[dict] = []
    any_data = False
    any_fail = False
    for r in rules:
        threshold = float(r["threshold"])
        actual = metrics.get(str(r["metric"]))
        if actual is None:
            # 该指标本任务未产出：不参与判定（记 skip），全部缺数据才 NOT_EVALUATED
            checks.append(
                {
                    "metric": r["metric"],
                    "op": r["op"],
                    "threshold": threshold,
                    "actual": None,
                    "ok": None,
                    "skipped": True,
                }
            )
            continue
        any_data = True
        ok = _cmp(str(r["op"]), actual, threshold)
        if not ok:
            any_fail = True
        checks.append(
            {
                "metric": r["metric"],
                "op": r["op"],
                "threshold": threshold,
                "actual": actual,
                "ok": ok,
            }
        )
    verdict = (
        VERDICT_NOT_EVALUATED if not any_data else (VERDICT_FAILED if any_fail else VERDICT_PASSED)
    )
    task.gate_result = verdict
    db.add(task)
    db.commit()
    logger.info("gate 评估：task=%s verdict=%s checks=%s", task.id, verdict, len(checks))
    return {"verdict": verdict, "checks": checks}


def gate_view(task: TestTask) -> dict:
    """ci-status / 前端的门禁视图（向后兼容新增结构，不改旧字段）。

    verdict：PASSED|FAILED|NOT_EVALUATED；NULL（未评估/非门禁）时返回 None，
    CI 侧标准用法：verdict == "FAILED" → exit 1（未评估不阻断）。
    """
    rules = load_rules(getattr(task, "gate_rules", None))
    return {
        "enabled": bool(rules),
        "verdict": task.gate_result if rules else None,
        "rules": rules,
    }
