# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES9-P-10：题库分层抽样（split × category 均匀）。

实现口径（设计方案 §4.1.2 / ES9-P-10）：
- 按 (split, category) 分层，SQL 用
  ROW_NUMBER() OVER (PARTITION BY split, category ORDER BY random()) <= k
  逐层取前 k 条；
- 随机性通过 ``SELECT setseed(seed)`` 播种，seed 由调用方持久化到
  eval_runs.run_snapshot->>'sample_seed'，同 seed 可复现同题集；
- 配额分配：层间尽量均匀（sample_size // 层数，余数轮流 +1），
  层内不足时把剩余额度回补给还有余量的层，保证总量最大化；
- 社区版 sensitivity_max 过滤（public 题库不含 internal/confidential 题）。
"""

from __future__ import annotations

import random
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Question

# sensitivity 有序档位（低→高）
_SENSITIVITY_ORDER = {"public": 0, "internal": 1, "confidential": 2}


def default_sample_size() -> int:
    """EVAL_SAMPLE_SIZE 默认 200（config.py 未落键时 getattr 兜底）。"""
    try:
        return int(getattr(settings, "EVAL_SAMPLE_SIZE", 200) or 200)
    except (TypeError, ValueError):
        return 200


def new_seed() -> int:
    return random.SystemRandom().randrange(1, 2**31 - 1)


def count_bank_questions(db: Session, bank_id: int, tenant_id: int | None = None) -> int:
    """题库未删题目总数（estimate 用；tenant 可选过滤）。"""
    sql = "SELECT COUNT(*) FROM question WHERE bank_id = :b AND deleted_at IS NULL"
    params: dict[str, Any] = {"b": bank_id}
    if tenant_id is not None:
        sql += " AND tenant_id = :t"
        params["t"] = tenant_id
    return int(db.execute(sa_text(sql), params).scalar() or 0)


def avg_question_len(db: Session, bank_id: int, tenant_id: int | None = None) -> int:
    """题面平均字符长度（estimate 粗估 token 用，空库返回 0）。"""
    sql = (
        "SELECT COALESCE(AVG(CHAR_LENGTH(text)), 0) FROM question "
        "WHERE bank_id = :b AND deleted_at IS NULL"
    )
    params: dict[str, Any] = {"b": bank_id}
    if tenant_id is not None:
        sql += " AND tenant_id = :t"
        params["t"] = tenant_id
    return int(db.execute(sa_text(sql), params).scalar() or 0)


def _seed_to_setseed(seed: int) -> float:
    """setseed 取值域 [-1, 1)，由业务 seed 稳定映射。"""
    return (seed % 2_000_000_000 - 1_000_000_000) / 1_000_000_000.0


def bank_strata(
    db: Session, bank_id: int, tenant_id: int, max_sensitivity: str | None = None
) -> list[dict[str, Any]]:
    """返回题库分层统计 [{split, category, count}]。"""
    sql = (
        "SELECT split, category, COUNT(*) AS cnt FROM question "
        "WHERE bank_id = :bank_id AND tenant_id = :tenant_id AND deleted_at IS NULL"
    )
    params: dict[str, Any] = {"bank_id": bank_id, "tenant_id": tenant_id}
    if max_sensitivity and max_sensitivity in _SENSITIVITY_ORDER:
        sql += (
            " AND sensitivity IN ("
            + ",".join(
                f":s{i}"
                for i, s in enumerate(
                    [k for k, v in _SENSITIVITY_ORDER.items() if v <= _SENSITIVITY_ORDER[max_sensitivity]]
                )
            )
            + ")"
        )
        for i, s in enumerate(
            [k for k, v in _SENSITIVITY_ORDER.items() if v <= _SENSITIVITY_ORDER[max_sensitivity]]
        ):
            params[f"s{i}"] = s
    sql += " GROUP BY split, category ORDER BY split, category"
    rows = db.execute(sa_text(sql), params).mappings().all()
    return [{"split": r["split"], "category": r["category"], "count": int(r["cnt"])} for r in rows]


def _allocate(strata: list[dict[str, Any]], sample_size: int) -> list[int]:
    """层间均匀配额分配（不足回补），返回与 strata 对齐的 quota 列表。"""
    n = len(strata)
    counts = [s["count"] for s in strata]
    total = sum(counts)
    if total <= 0:
        return [0] * n
    target = min(sample_size, total)
    quota = [0] * n
    base, rem = divmod(target, n)
    for i in range(n):
        quota[i] = min(base + (1 if i < rem else 0), counts[i])
    # 回补：还有剩余额度且某层未取满
    left = target - sum(quota)
    while left > 0:
        progressed = False
        for i in range(n):
            if left <= 0:
                break
            if quota[i] < counts[i]:
                quota[i] += 1
                left -= 1
                progressed = True
        if not progressed:
            break
    return quota


def _allocate_by_quota(
    strata: list[dict[str, Any]], category_quotas: dict[str, int]
) -> tuple[list[int], dict[str, int], dict[str, int]]:
    """优化12 §4.5 配额制分配：每类别独立取 min(quota, available)，**禁止跨类回补**。

    返回 (与 strata 对齐的层配额列表, by_category 实抽数, shortfall 缺口)。
    缺口只记 shortfall，绝不用其他类富余填补（GB/T 45654 每子类独立达标语义）。
    配额未覆盖的类别配额为 0（白名单语义）。类别内跨 split 均分+类内回补。
    """
    quotas = [0] * len(strata)
    by_category: dict[str, int] = {}
    shortfall: dict[str, int] = {}
    cat_idx: dict[str, list[int]] = {}
    for i, s in enumerate(strata):
        cat_idx.setdefault(str(s["category"]), []).append(i)

    for cat, idxs in cat_idx.items():
        if cat not in category_quotas:
            continue  # 白名单外类别 → 配额保持 0
        avail = sum(strata[i]["count"] for i in idxs)
        want = int(category_quotas[cat])
        take = min(want, avail)
        by_category[cat] = take
        if take < want:
            shortfall[cat] = want - take
        # 类内跨 split 分配（类内回补合法；跨类禁止）
        n = len(idxs)
        base, rem = divmod(take, n)
        for j, i in enumerate(idxs):
            quotas[i] = min(base + (1 if j < rem else 0), strata[i]["count"])
        left = take - sum(quotas[i] for i in idxs)
        while left > 0:
            progressed = False
            for i in idxs:
                if left <= 0:
                    break
                if quotas[i] < strata[i]["count"]:
                    quotas[i] += 1
                    left -= 1
                    progressed = True
            if not progressed:
                break

    # 配额里有但题库完全无题的类别 → 全量缺口
    for cat, want in category_quotas.items():
        if cat not in cat_idx:
            by_category[cat] = 0
            shortfall[cat] = int(want)
    return quotas, by_category, shortfall


def sample_questions(
    db: Session,
    bank_id: int,
    tenant_id: int,
    sample_size: int | None = None,
    seed: int | None = None,
    max_sensitivity: str | None = None,
    category_quotas: dict[str, int] | None = None,
    exclude_categories: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """分层抽题。

    返回 (questions, seed_used, plan)：
    - questions：QuestionPayload dict 列表（供执行链 EngineContext.questions）；
    - seed_used：本次播种 seed（调用方写入 run_snapshot.sample_seed）；
    - plan：{strata:[{split,category,count,quota}]} 抽样计划快照。

    优化12 §4.5：
    - category_quotas 非空 → 配额制抽样（每子类 min(quota, available)，禁止跨类回补，
      sample_size 被忽略，plan 增 by_category / shortfall 两键）；
      为空 → 行为与改造前完全一致（均分路径，存量调用零改动）；
    - exclude_categories：按类别排除（如「待分类-GBT45654」），两条路径均生效。
    """
    used_seed = seed if seed is not None else new_seed()
    strata = bank_strata(db, bank_id, tenant_id, max_sensitivity=max_sensitivity)
    if exclude_categories:
        excl = {str(c) for c in exclude_categories}
        strata = [s for s in strata if str(s["category"]) not in excl]
    quota_mode = bool(category_quotas)
    size = (
        sum(int(v) for v in category_quotas.values()) if quota_mode
        else (sample_size or default_sample_size())
    )
    if not strata:
        return [], used_seed, {"strata": [], "requested": size, "sampled": 0}
    if quota_mode:
        quotas, by_category, shortfall = _allocate_by_quota(strata, category_quotas or {})
    else:
        quotas = _allocate(strata, size)
    for s, q in zip(strata, quotas):
        s["quota"] = q

    # 单条 SQL：给每个 (split, category) 层绑定配额后 ROW_NUMBER 截断
    values_parts: list[str] = []
    params: dict[str, Any] = {
        "bank_id": bank_id,
        "tenant_id": tenant_id,
        "seed": _seed_to_setseed(used_seed),
    }
    for i, s in enumerate(strata):
        # 绑定名必须加括号再 cast：`:sp0::text` 会被 SQLAlchemy 误判为
        # 转义冒号而整段不编译（真实 PG 必现语法错误），`(:sp0)::text` 正常。
        values_parts.append(f"((:sp{i})::text, (:ct{i})::text, (:q{i})::int)")
        params[f"sp{i}"], params[f"ct{i}"], params[f"q{i}"] = s["split"], s["category"], s["quota"]

    sens_clause = ""
    if max_sensitivity and max_sensitivity in _SENSITIVITY_ORDER:
        allowed = [k for k, v in _SENSITIVITY_ORDER.items() if v <= _SENSITIVITY_ORDER[max_sensitivity]]
        sens_clause = " AND q.sensitivity = ANY(:sens)"
        params["sens"] = allowed

    sql = sa_text(
        f"""
WITH quota(split, category, k) AS (VALUES {",".join(values_parts)}),
ranked AS (
  SELECT q.*, ROW_NUMBER() OVER (
           PARTITION BY q.split, q.category ORDER BY random()
         ) AS rn
  FROM question q
  WHERE q.bank_id = :bank_id AND q.tenant_id = :tenant_id
    AND q.deleted_at IS NULL {sens_clause}
)
SELECT r.id, r.seq, r.category, r.sub_category, r.attack_vector, r.split,
       r.expected_behavior, r.expected_answer, r.language, r.text, r.tags, r.meta
FROM ranked r JOIN quota qq
  ON qq.split = r.split AND qq.category = r.category
WHERE r.rn <= qq.k
ORDER BY r.split, r.category, r.seq
"""
    )
    # setseed 与后续 random() 需同会话同事务，先播种
    db.execute(sa_text("SELECT setseed(:seed)"), {"seed": params["seed"]})
    params.pop("seed")
    rows = db.execute(sql, params).mappings().all()

    questions = [
        {
            "question_id": int(r["id"]),
            "bank_id": int(bank_id),
            "seq": int(r["seq"] or 0),
            "text": r["text"],
            "category": r["category"],
            "sub_category": r["sub_category"],
            "attack_vector": r["attack_vector"],
            "split": r["split"],
            "expected_behavior": r["expected_behavior"],
            "expected_answer": r["expected_answer"],
            "language": r["language"],
            "meta": r["meta"] if isinstance(r["meta"], dict) else {},
        }
        for r in rows
    ]
    plan = {
        "strata": [
            {"split": s["split"], "category": s["category"], "count": s["count"], "quota": s["quota"]}
            for s in strata
        ],
        "requested": size,
        "sampled": len(questions),
    }
    if quota_mode:
        # 优化12 §4.5：shortfall 是覆盖矩阵缺口的第一手证据（既有键内扩展，无新表无新列）
        plan["by_category"] = by_category
        plan["shortfall"] = shortfall
    return questions, used_seed, plan
