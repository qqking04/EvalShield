# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M6：人工复核队列入队与状态机服务（方案 §7.2）。

三个入队来源共用 `enqueue()`（部分唯一索引兜底幂等，OPEN 态下同
(source, source_ref) 不建双份）：
1. run 终态低置信自动入队 —— `enqueue_from_run()`（task_runner 旁挂）；
2. 用户报告详情标记「判分不对」—— `enqueue_from_report_mark()`；
3. monitor 告警关联批次的最低分样本 —— `enqueue_from_monitor_batch()`。

低置信代理口径（方案 §7.2.1 的 auto_confidence 在现有引擎中缺原生字段）：
- 条目自带 confidence（0-1，JAILBREAK 等引擎 detail 内嵌）→ 直接采用；
- 否则以「得分与判分阈值 0.7 的距离」线性映射：
  confidence = min(|score - 0.7| / (2 × 模糊带宽 0.1), 1.0)
  —— 恰在阈值上为 0（最不确定），偏离 ≥0.2 视为完全确信。
  统一按 confidence < 0.7 触发入队（即 |score-0.7| < 0.14 模糊区）。

状态机：OPEN →(指派)→ ASSIGNED →(提交结论)→ DONE；
OPEN/ASSIGNED →(废弃)→ DISCARDED。DONE 要求 human_verdict 非空；
DONE 不回写 run 表——人工结论权威落点就是本表 human_verdict。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import EvalRun, ReviewItem
from .notifications import emit as notify_emit

logger = logging.getLogger("evalshield.review")

# 判分阈值（与 EVAL_ENGINE 默认 threshold=0.7 同口径）与低置信入队阈值
JUDGE_THRESHOLD = 0.7
REVIEW_THRESHOLD = 0.7
# 无原生 confidence 时，得分-阈值距离映射到确信度的模糊带宽
AMBIGUITY_BAND = 0.1

# monitor 告警入队取样条数（任务书 N=5 常量）
MONITOR_TOPN = 5

# source 枚举（DDL 注释同口径）
SRC_RUN_ITEM = "run_item"
SRC_TRACE = "trace"
SRC_DEFECT = "defect"

# 状态枚举
ST_OPEN = "OPEN"
ST_ASSIGNED = "ASSIGNED"
ST_DONE = "DONE"
ST_DISCARDED = "DISCARDED"
TERMINAL_STATES = {ST_DONE, ST_DISCARDED}


# ---------------------------------------------------------------------------
# item_results 双形态归一（task_runner {no,prompt,verdict,score,detail} /
# 评测中心引擎原始 items {item_no,prompt,rubric,score,grade,judge_mode}）
# ---------------------------------------------------------------------------
def _num(value) -> float | None:
    """宽松数值化：非数字/bool 返回 None。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_row(row: Any) -> dict | None:
    """单行 item_results → {no, prompt, verdict, score, confidence}；非法行返回 None。"""
    if not isinstance(row, dict):
        return None
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    score = _num(row.get("score"))
    raw_conf = _num(row.get("confidence"))
    if raw_conf is None:
        raw_conf = _num(detail.get("confidence"))
    return {
        "no": str(row.get("no") or row.get("item_no") or ""),
        "prompt": str(row.get("prompt") or row.get("question") or ""),
        "verdict": str(row.get("grade") or row.get("verdict") or ""),
        "score": score,
        "confidence": raw_conf,
    }


def item_confidence(norm: dict) -> float | None:
    """条目确信度：原生 confidence 优先；否则按得分距阈值线性映射（见模块 docstring）。"""
    if norm["confidence"] is not None:
        return max(0.0, min(1.0, norm["confidence"]))
    if norm["score"] is None:
        return None
    return min(abs(norm["score"] - JUDGE_THRESHOLD) / (2 * AMBIGUITY_BAND), 1.0)


def make_source_ref(run_id: int, item_index: int) -> str:
    """OPEN 唯一约束的定位键：紧凑 JSON（键序固定，保证幂等比对稳定）。"""
    return json.dumps({"run_id": int(run_id), "item_index": int(item_index)}, sort_keys=True)


# ---------------------------------------------------------------------------
# 基础入队（幂等：OPEN 态重复直接返回既有行）
# ---------------------------------------------------------------------------
def find_open(db: Session, source: str, source_ref: str) -> ReviewItem | None:
    return (
        db.query(ReviewItem)
        .filter(ReviewItem.source == source, ReviewItem.source_ref == source_ref)
        .first()
    )


def enqueue(
    db: Session,
    *,
    tenant_id: int,
    source: str,
    run_id: int,
    item_index: int,
    context: dict,
    auto_verdict: str | None = None,
    auto_confidence: float | None = None,
    reason: str | None = None,
) -> ReviewItem | None:
    """入队一条复核项；OPEN 幂等（应用层查重 + 部分唯一索引双保险）。

    返回新建行；已存在 OPEN/其它状态行或并发冲突时返回 None。
    context 内嵌 reason 便于复核台展示入队原因。
    """
    ctx = dict(context or {})
    if reason:
        ctx["enqueue_reason"] = reason
    ref = make_source_ref(run_id, item_index)
    existing = find_open(db, source, ref)
    if existing is not None and existing.status not in TERMINAL_STATES:
        return None  # 队列中（OPEN/ASSIGNED）不重复入
    item = ReviewItem(
        tenant_id=tenant_id,
        org_id=0,
        source=source,
        source_ref=ref,
        context=json.dumps(ctx, ensure_ascii=False),
        auto_verdict=str(auto_verdict)[:24] if auto_verdict else None,
        auto_confidence=auto_confidence,
        status=ST_OPEN,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:  # 并发下另一路已入同项：回滚后静默跳过
        db.rollback()
        return None
    db.refresh(item)
    return item


def _row_context(run: EvalRun, idx: int, norm: dict) -> dict:
    """队列快照上下文（复制而非引用，保证 run 行不再可变时队列仍可复现）。"""
    return {
        "run_id": run.id,
        "run_no": run.run_no,
        "task_id": run.task_id,
        "item_index": idx,
        "no": norm["no"],
        "prompt": norm["prompt"],
        "score": norm["score"],
        "verdict": norm["verdict"],
    }


# ---------------------------------------------------------------------------
# 来源 1：run 终态低置信自动入队（task_runner 旁挂）
# ---------------------------------------------------------------------------
def enqueue_from_run(db: Session, run: EvalRun, threshold: float = REVIEW_THRESHOLD) -> int:
    """扫描 run.item_results，confidence < threshold 逐项入队，返回新入队数。"""
    enqueued = 0
    for idx, row in enumerate(run.item_results or []):
        norm = normalize_row(row)
        if norm is None:
            continue
        conf = item_confidence(norm)
        if conf is None or conf >= threshold:
            continue
        if enqueue(
            db, tenant_id=run.tenant_id or 1, source=SRC_RUN_ITEM,
            run_id=run.id, item_index=idx,
            context=_row_context(run, idx, norm),
            auto_verdict=norm["verdict"], auto_confidence=round(conf, 4),
            reason="low_confidence",
        ) is not None:
            enqueued += 1
    if enqueued:
        logger.info("run %s 低置信自动入队 %d 条", run.run_no, enqueued)
    return enqueued


# ---------------------------------------------------------------------------
# 来源 2：用户标记「判分不对」（报告详情按钮）
# ---------------------------------------------------------------------------
def enqueue_from_report_mark(
    db: Session, run: EvalRun, item_index: int, note: str | None = None
) -> ReviewItem:
    """按 (run_id, item_index) 取快照入队（不论置信度）；重复标记幂等。"""
    rows = run.item_results or []
    if not isinstance(item_index, int) or item_index < 0 or item_index >= len(rows):
        from ..errors import BizError

        raise BizError("ES-M6-0001", f"item_index 越界：{item_index}（本 run 共 {len(rows)} 项）")
    norm = normalize_row(rows[item_index]) or {
        "no": "", "prompt": "", "verdict": "", "score": None, "confidence": None,
    }
    ctx = _row_context(run, item_index, norm)
    if note:
        ctx["user_note"] = str(note)[:500]
    conf = item_confidence(norm)
    item = enqueue(
        db, tenant_id=run.tenant_id or 1, source=SRC_RUN_ITEM,
        run_id=run.id, item_index=item_index,
        context=ctx, auto_verdict=norm["verdict"],
        auto_confidence=round(conf, 4) if conf is not None else None,
        reason="user_mark_wrong",
    )
    if item is None:
        # 幂等：已有在队项则返回既有行（OPEN 语义对调用方等价）
        item = find_open(db, SRC_RUN_ITEM, make_source_ref(run.id, item_index))
        if item is None:
            from ..errors import BizError

            raise BizError("ES-M6-0002", "复核项状态冲突，请刷新后重试")
    return item


# ---------------------------------------------------------------------------
# 来源 3：monitor 告警批次的最低分样本（monitor FIRING 旁挂）
# ---------------------------------------------------------------------------
def enqueue_from_monitor_batch(db: Session, task_rep_id: int | None, tenant_id: int) -> int:
    """monitor.last_run_id 是批次代表任务 id（test_tasks.id）→ 按 task_id 反查 EvalRun，
    取各 run 得分最低的 MONITOR_TOPN 条入队。异常由调用方吞掉。"""
    if not task_rep_id:
        return 0
    total = 0
    runs = db.query(EvalRun).filter(EvalRun.task_id == int(task_rep_id)).all()
    for run in runs:
        scored = []
        for idx, row in enumerate(run.item_results or []):
            norm = normalize_row(row)
            if norm is not None and norm["score"] is not None:
                scored.append((norm["score"], idx, norm))
        scored.sort(key=lambda t: (t[0], t[1]))
        for score, idx, norm in scored[:MONITOR_TOPN]:
            if enqueue(
                db, tenant_id=run.tenant_id or tenant_id, source=SRC_RUN_ITEM,
                run_id=run.id, item_index=idx,
                context=_row_context(run, idx, norm),
                auto_verdict=norm["verdict"], auto_confidence=None,
                reason="monitor_low_score",
            ) is not None:
                total += 1
    if total:
        logger.info("monitor 批次代表任务 %s 低分入队 %d 条", task_rep_id, total)
    return total


# ---------------------------------------------------------------------------
# 状态机（API 层调用；非法转移抛 BizError）
# ---------------------------------------------------------------------------
def _ensure_mutable(item: ReviewItem) -> None:
    from ..errors import BizError

    if item.status in TERMINAL_STATES:
        raise BizError("ES-M6-0003", f"复核项已处于终态 {item.status}，不可再变更")


def assign_item(db: Session, item: ReviewItem, assignee_id: int) -> ReviewItem:
    """指派 → ASSIGNED，并 emit review.assigned（M3 定向送达复核员）。"""
    _ensure_mutable(item)
    item.assignee_id = assignee_id
    item.status = ST_ASSIGNED
    db.add(item)
    db.commit()
    db.refresh(item)
    try:
        notify_emit(
            item.tenant_id,
            "review.assigned",
            {
                "review_id": item.id,
                "source": item.source,
                "recipient_ids": [assignee_id],
                "title": f"复核任务 #{item.id} 已指派给你",
                "content": f"来源 {item.source}，请前往人工复核队列处理。",
                "dedup_key": f"REVA|{item.id}|{assignee_id}",
            },
            severity="MEDIUM",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("review.assigned 通知失败（忽略）: %s", exc)
    return item


def complete_item(
    db: Session, item: ReviewItem, human_verdict: str, human_note: str | None
) -> ReviewItem:
    """提交人工结论 → DONE（权威落点；不回写 run 表）。OPEN 可直接 DONE。"""
    _ensure_mutable(item)
    verdict = (human_verdict or "").strip()
    if not verdict:
        from ..errors import BizError

        raise BizError("ES-M6-0004", "完成复核必须提交 human_verdict")
    item.human_verdict = verdict[:24]
    item.human_note = (human_note or None) and str(human_note)[:2000]
    item.status = ST_DONE
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def discard_item(db: Session, item: ReviewItem) -> ReviewItem:
    """废弃 → DISCARDED（终态，释放 OPEN 唯一约束位）。"""
    _ensure_mutable(item)
    item.status = ST_DISCARDED
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
