# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M6：judge 校准报告（方案 §7.2.3）。

对 review_items 中 DONE 项（human_verdict 权威落点）按 ISO 周聚合，
产出「机判 vs 人判」混淆矩阵与 Cohen's Kappa（手算，不引新依赖）：

    po = 对角和 / n
    pe = Σ_k (行k合计 × 列k合计) / n²
    κ  = (po - pe) / (1 - pe)      （pe=1 时：po=1→κ=1，否则 κ=0）

判定值归一（_bucket）：引擎各表 verdict 口径不一（PASS/SAFE、FAIL/BYPASSED/
LEAK、grade PASS/FAIL 等），统一折算为 PASS / FAIL / PARTIAL 三分类，
无法识别的归 OTHER 并剔除出矩阵。复核台五档评分映射约定：
1-2→FAIL、3→PARTIAL、4-5→PASS（前端 Queue.jsx 提交时折算）。

周口径：按 DONE 项 updated_at 的 UTC 日期取 isocalendar()（ISO 周一起始）。
κ < 0.6 → 附 warning「评审 prompt 需调整」（引导 M9 prompt 版本管理）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import ReviewItem

# Kappa 警戒线（方案 §7.2.3）
KAPPA_WARN = 0.6
WARN_TEXT = "judge 一致性 Kappa 低于 0.6，评审 prompt 需调整（建议在 M9 做 prompt 版本管理）"

# ES11 P10：分组/整体样本量下限——低于该值不发布 Kappa，前端显示"样本不足"
MIN_SAMPLE = 10

# 三分类标签全集（矩阵行列顺序固定，前端渲染依赖）
LABELS = ("PASS", "FAIL", "PARTIAL")

_BUCKET_MAP = {
    # 通过族
    "PASS": "PASS", "SAFE": "PASS", "OK": "PASS", "TRUE": "PASS",
    "HIGH": "PASS", "PASSED": "PASS",
    # 失败族
    "FAIL": "FAIL", "BYPASSED": "FAIL", "LEAK": "FAIL", "FALSE": "FAIL",
    "LOW": "FAIL", "FAILED": "FAIL", "CRITICAL": "FAIL",
    # 部分达成族
    "PARTIAL": "PARTIAL", "PARTIALLY_SAFE": "PARTIAL", "WARN": "PARTIAL",
    "MEDIUM": "PARTIAL", "SKIP": "PARTIAL",
}


def bucket(value: str | None) -> str | None:
    """判定值归一：未知口径返回 None（调用方剔除出矩阵）。"""
    return _BUCKET_MAP.get((value or "").strip().upper())


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """手算 Cohen's Kappa；pairs=[(机判桶, 人判桶)]。空集返回 None。"""
    n = len(pairs)
    if n == 0:
        return None
    cats = sorted({c for p in pairs for c in p})
    diag = sum(1 for a, b in pairs if a == b)
    po = diag / n
    pe = 0.0
    for c in cats:
        row = sum(1 for a, _ in pairs if a == c) / n
        col = sum(1 for _, b in pairs if b == c) / n
        pe += row * col
    if pe >= 1.0:  # 单一类别退化
        return 1.0 if po >= 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


def _iso_week(dt: datetime | None) -> str:
    """DONE 时间 → ISO 周键 "YYYY-Www"（UTC 口径；updated_at 为终态写入不再变）。"""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    y, w, _ = dt.astimezone(timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


def _matrix(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """混淆矩阵 {机判桶: {人判桶: 计数}}，行列覆盖 LABELS 全集（含 0）。"""
    m: dict[str, dict[str, int]] = {a: {b: 0 for b in LABELS} for a in LABELS}
    for a, b in pairs:
        m[a][b] += 1
    return m


def calibration_report(db: Session, tenant_id: int | None, weeks: int = 12) -> dict[str, Any]:
    """按 ISO 周聚合 DONE 复核项 → judge 一致性报告。

    tenant_id=None 仅超管口径（跨租户）；返回：
    {weeks:[{week,n,agreement,kappa,matrix}], overall:{n,agreement,kappa},
     warning, threshold}
    周序列取数据实际覆盖的最近 `weeks` 个 ISO 周（不足不补空周）。
    """
    q = db.query(ReviewItem).filter(ReviewItem.status == "DONE")
    if tenant_id is not None:
        q = q.filter(ReviewItem.tenant_id == tenant_id)
    rows = q.order_by(ReviewItem.updated_at.asc()).all()

    by_week: dict[str, list[tuple[str, str]]] = {}
    skipped = 0
    # ES11 P10 治理分组：每维 key → 归一成功对 [(机判桶, 人判桶)] 与 UNKNOWN 计数
    raw_total = 0
    raw_unknown = 0
    group_pairs: dict[str, dict[str, list[tuple[str, str]]]] = {
        "category": {}, "judge_model": {}, "prompt_hash": {},
    }
    group_unknown: dict[str, dict[str, int]] = {
        "category": {}, "judge_model": {}, "prompt_hash": {},
    }

    def _group_keys(r: ReviewItem) -> dict[str, str]:
        try:
            ctx = json.loads(r.context) if r.context else {}
        except (TypeError, ValueError):
            ctx = {}
        return {
            "category": str(ctx.get("category") or "未分类"),
            "judge_model": str(r.judge_model or "未知模型"),
            "prompt_hash": (str(r.judge_prompt_hash)[:8] if r.judge_prompt_hash else "未知"),
        }

    for r in rows:
        raw_total += 1
        keys = _group_keys(r)
        a, b = bucket(r.auto_verdict), bucket(r.human_verdict)
        if a is None or b is None:
            skipped += 1
            raw_unknown += 1
            for dim, key in keys.items():
                group_unknown[dim][key] = group_unknown[dim].get(key, 0) + 1
            continue
        by_week.setdefault(_iso_week(r.updated_at), []).append((a, b))
        for dim, key in keys.items():
            group_pairs[dim].setdefault(key, []).append((a, b))

    # 最近 N 周：按 ISO 周键数值排序取尾部
    ordered = sorted(by_week.keys(), key=lambda k: (int(k.split("-W")[0]), int(k.split("-W")[1])))
    picked = ordered[-max(1, min(weeks, 104)):]

    week_out = []
    all_pairs: list[tuple[str, str]] = []
    for wk in picked:
        pairs = by_week[wk]
        all_pairs.extend(pairs)
        n = len(pairs)
        agree = sum(1 for a, b in pairs if a == b)
        k = cohen_kappa(pairs)
        week_out.append({
            "week": wk,
            "n": n,
            "agreement": round(agree / n, 4) if n else None,
            "kappa": None if k is None else round(k, 4),
            "matrix": _matrix(pairs),
        })

    n_all = len(all_pairs)
    agree_all = sum(1 for a, b in all_pairs if a == b)
    k_all = cohen_kappa(all_pairs)
    overall = {
        "n": n_all,
        "agreement": round(agree_all / n_all, 4) if n_all else None,
        "kappa": None if k_all is None else round(k_all, 4),
        "sufficient": n_all >= MIN_SAMPLE,
    }

    # ES11 P10：治理分组视图（按场景/模型/prompt 哈希三维）
    # 每组：样本数 n、一致率、Kappa（样本不足时 kappa=None，前端显示"样本不足"）、
    # UNKNOWN 率（组内原始机判值归一失败占比）。
    def _build_groups(dim: str) -> list[dict[str, Any]]:
        out = []
        keys = set(group_pairs[dim]) | set(group_unknown[dim])
        for key in keys:
            pairs = group_pairs[dim].get(key, [])
            unk = group_unknown[dim].get(key, 0)
            n = len(pairs)
            total = n + unk
            agree = sum(1 for a, b in pairs if a == b)
            k = cohen_kappa(pairs)
            out.append({
                "key": key,
                "n": n,
                "agreement": round(agree / n, 4) if n else None,
                "kappa": None if (n < MIN_SAMPLE or k is None) else round(k, 4),
                "sufficient": n >= MIN_SAMPLE,
                "unknown_rate": round(unk / total, 4) if total else None,
            })
        out.sort(key=lambda g: -g["n"])
        return out

    groups = {
        "by_category": _build_groups("category"),
        "by_judge_model": _build_groups("judge_model"),
        "by_prompt_hash": _build_groups("prompt_hash"),
    }
    return {
        "weeks": week_out,
        "overall": overall,
        "groups": groups,
        "min_sample": MIN_SAMPLE,
        "unknown_rate": round(raw_unknown / raw_total, 4) if raw_total else None,
        "skipped_unknown_verdicts": skipped,
        "threshold": KAPPA_WARN,
        "warning": (
            WARN_TEXT
            if k_all is not None and k_all < KAPPA_WARN and n_all > 0
            else None
        ),
    }
