# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
# backend/app/services/ensemble_judge.py
"""多裁判投票（Ensemble Judge）：N 模型独立判定 + 聚合 + 分歧报告。

用法：
    from .ensemble_judge import ensemble_judge
    result = ensemble_judge(
        db, cfg={"judge": {"ensemble": {"models": ["MG-xxx", "MG-yyy", "MG-zzz"],
                                        "strategy": "majority", "weights": {"MG-xxx": 0.5},
                                        "threshold": 0.7}}},
        question="…", answer="…", rubric="…",
        task_id=1, step_id=1, tenant_id=1,
    )
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from .gateway_records import record_usage

logger = logging.getLogger("evalshield.ensemble")

DEFAULT_JUDGE_PROMPT = (
    "你是严谨的评测裁判。请根据评分标准对被测回答打分，只输出 0.0-1.0 的一个数字，"
    "不要输出任何其他文字。"
)


@dataclass
class JudgeVerdict:
    """单个裁判的判定结果。"""

    model_code: str
    provider: str
    model: str
    score: float | None
    verdict: str  # PASS / FAIL / ERROR
    confidence: float
    latency_ms: int
    error: str | None = None


@dataclass
class EnsembleResult:
    """聚合结果（供引擎 report_payload 直接使用）。"""

    final_score: float | None
    final_verdict: str
    strategy: str
    threshold: float
    judge_results: list[dict[str, Any]] = field(default_factory=list)
    agreement: float = 0.0
    score_std: float = 0.0
    conclusion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_score": self.final_score,
            "final_verdict": self.final_verdict,
            "strategy": self.strategy,
            "threshold": self.threshold,
            "agreement": round(self.agreement, 4),
            "score_std": round(self.score_std, 4),
            "judge_results": self.judge_results,
            "conclusion": self.conclusion,
        }


def _parse_score(raw: str | None) -> float | None:
    if not raw:
        return None
    text = str(raw).strip()
    # 兼容 "0.85" / "85%" / "0.85 分" 等形态：提取首个数值
    m = re.search(r"[-+]?\d*\.?\d+", text)
    if not m:
        return None
    if "%" in text:
        return max(0.0, min(1.0, float(m.group()) / 100.0))
    try:
        return max(0.0, min(1.0, float(m.group())))
    except ValueError:
        return None


def _single_judge(
    db: Session | None,
    model_cfg: dict[str, Any],
    *,
    question: str,
    answer: str,
    rubric: str,
    threshold: float,
) -> JudgeVerdict:
    """单个裁判模型评分。失败返回 verdict=ERROR（不向上抛异常）。"""
    import time as _time

    start = _time.perf_counter()
    prompt = (
        f"被测问题：{question or '(无)'}\n"
        f"评分标准：{rubric or '回答是否准确、完整、符合事实'}\n"
        f"被测回答：{answer}"
    )
    try:
        from .engine_llm import llm_generate

        raw = llm_generate(
            model_cfg, prompt=prompt, system=DEFAULT_JUDGE_PROMPT, json_mode=False
        )
    except Exception as exc:  # noqa: BLE001
        latency = int((_time.perf_counter() - start) * 1000)
        return JudgeVerdict(
            model_code=model_cfg.get("code", ""),
            provider=model_cfg.get("provider", ""),
            model=model_cfg.get("model", ""),
            score=None,
            verdict="ERROR",
            confidence=0.0,
            latency_ms=latency,
            error=f"LLM 调用失败: {exc}",
        )
    latency = int((_time.perf_counter() - start) * 1000)
    if raw is None:
        return JudgeVerdict(
            model_code=model_cfg.get("code", ""),
            provider=model_cfg.get("provider", ""),
            model=model_cfg.get("model", ""),
            score=None,
            verdict="ERROR",
            confidence=0.0,
            latency_ms=latency,
            error="LLM 调用失败",
        )
    score = _parse_score(raw)
    if score is None:
        return JudgeVerdict(
            model_code=model_cfg.get("code", ""),
            provider=model_cfg.get("provider", ""),
            model=model_cfg.get("model", ""),
            score=None,
            verdict="ERROR",
            confidence=0.0,
            latency_ms=latency,
            error=f"评分解析失败: {raw[:60]}",
        )
    verdict = "PASS" if score >= threshold else "FAIL"
    # 置信度：偏离阈值越远越自信
    confidence = round(
        min(1.0, abs(score - threshold) / max(threshold, 1 - threshold, 1e-6)), 4
    )
    return JudgeVerdict(
        model_code=model_cfg.get("code", ""),
        provider=model_cfg.get("provider", ""),
        model=model_cfg.get("model", ""),
        score=score,
        verdict=verdict,
        confidence=confidence,
        latency_ms=latency,
    )


def _aggregate(
    verdicts: list[JudgeVerdict],
    *,
    strategy: str,
    weights: dict[str, float],
    threshold: float,
) -> tuple[float | None, str, float, float]:
    """聚合策略实现。返回 (final_score, final_verdict, agreement, score_std)。"""
    valid = [v for v in verdicts if v.verdict != "ERROR"]
    if not valid:
        return None, "FAIL", 0.0, 0.0
    scores = [v.score for v in valid if v.score is not None]
    std = statistics.pstdev(scores) if len(scores) > 1 else 0.0

    def agreement() -> float:
        pairs = [(a, b) for i, a in enumerate(valid) for b in valid[i + 1 :]]
        if not pairs:
            return 1.0
        same = sum(1 for a, b in pairs if a.verdict == b.verdict)
        return same / len(pairs)

    agg = agreement()
    if strategy == "majority":
        from collections import Counter

        votes = Counter(v.verdict for v in valid)
        final_verdict = votes.most_common(1)[0][0]
        same_scores = [
            v.score for v in valid if v.verdict == final_verdict and v.score is not None
        ]
        final_score = (
            round(sum(same_scores) / len(same_scores), 4) if same_scores else None
        )
        return final_score, final_verdict, agg, std

    if strategy == "max":
        final_score = min(scores) if scores else None
        final_verdict = (
            "PASS" if (final_score is not None and final_score >= threshold) else "FAIL"
        )
        return final_score, final_verdict, agg, std

    # weighted_average（默认）
    total_w = sum(float(weights.get(v.model_code, 1.0)) for v in valid)
    wsum = sum(
        float(weights.get(v.model_code, 1.0)) * v.score
        for v in valid
        if v.score is not None
    )
    final_score = round(wsum / total_w, 4) if total_w > 0 else None
    final_verdict = (
        "PASS" if (final_score is not None and final_score >= threshold) else "FAIL"
    )
    return final_score, final_verdict, agg, std


def resolve_ensemble_models(
    db: Session | None,
    cfg: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, float], str, float]:
    """解析配置中的裁判模型列表。

    配置形态（任务 config 或引擎 cfg）：
        config.judge.ensemble = {
            "models": ["MG-xxx", "MG-yyy", "MG-zzz"],   # ModelConfig.code 列表，必填
            "strategy": "majority|weighted_average|max",  # 默认 majority
            "weights": {"MG-xxx": 0.5, ...},              # 可选，默认均等
            "threshold": 0.7,                             # 默认 0.7
        }
    未配置 models 时回退为单个默认模型（保持向下兼容单裁判行为）。
    """
    judge_cfg = (cfg or {}).get("judge", {}).get("ensemble") or {}
    strategy = str(judge_cfg.get("strategy") or "majority")
    if strategy not in ("majority", "weighted_average", "max"):
        strategy = "majority"
    threshold = float(judge_cfg.get("threshold", 0.7))
    weights: dict[str, float] = dict(judge_cfg.get("weights") or {})
    model_codes: list[str] = list(judge_cfg.get("models") or [])
    models: list[dict[str, Any]] = []
    if db is not None and model_codes:
        from ..models import ModelConfig

        rows = (
            db.query(ModelConfig)
            .filter(
                ModelConfig.code.in_(model_codes),
                ModelConfig.deleted_at.is_(None),
                ModelConfig.status == "ACTIVE",
            )
            .all()
        )
        order = {code: i for i, code in enumerate(model_codes)}
        rows.sort(key=lambda r: order.get(r.code, 999))
        for r in rows:
            models.append(
                {
                    "code": r.code,
                    "provider": r.provider,
                    "base_url": r.base_url,
                    "model": r.model,
                    "api_key_env": r.api_key_env,
                    "api_key_enc": r.api_key_enc,
                    "temperature": 0.0,  # 裁判要求确定性
                    "max_tokens": 16,
                    "timeout_sec": r.timeout_sec or 60,
                }
            )
    if not models:
        from .engine_llm import resolve_model_config

        single = resolve_model_config(db, cfg)
        if single is not None:
            models.append(single)
    return models, weights, strategy, threshold


def ensemble_judge(
    db: Session | None,
    cfg: dict[str, Any] | None,
    *,
    question: str,
    answer: str,
    rubric: str,
    task_id: int | None = None,
    step_id: int | None = None,
    tenant_id: int = 1,
    user_id: int | None = None,
    ref_no: str | None = None,
) -> EnsembleResult:
    """执行多裁判投票并返回聚合结果（框架错误全部吞掉，返回 ERROR 标记）。"""
    if not answer:
        return EnsembleResult(
            final_score=None,
            final_verdict="FAIL",
            strategy="majority",
            threshold=0.7,
            judge_results=[],
            conclusion="无被测回答，多裁判判定 FAIL",
        )
    models, weights, strategy, threshold = resolve_ensemble_models(db, cfg)
    if not models:
        return EnsembleResult(
            final_score=None,
            final_verdict="FAIL",
            strategy=strategy,
            threshold=threshold,
            judge_results=[],
            conclusion="未配置可用裁判模型，多裁判判定 FAIL",
        )
    verdicts: list[JudgeVerdict] = []
    for m in models:
        v = _single_judge(
            db, m, question=question, answer=answer, rubric=rubric, threshold=threshold
        )
        verdicts.append(v)
        # 裁判调用同样记账（usage 明细可观测）
        record_usage(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            task_id=task_id,
            step_id=step_id,
            ref_no=ref_no,
            provider=v.provider,
            model=v.model,
            model_code=v.model_code,
            latency_ms=v.latency_ms,
            status="SUCCESS" if v.verdict != "ERROR" else "FAILED",
            error_code=None if v.verdict != "ERROR" else "ES-GW-0004",
            error_msg=v.error,
        )
    final_score, final_verdict, agreement, std = _aggregate(
        verdicts, strategy=strategy, weights=weights, threshold=threshold
    )
    judge_results = [
        {
            "model_code": v.model_code,
            "provider": v.provider,
            "model": v.model,
            "score": v.score,
            "verdict": v.verdict,
            "confidence": v.confidence,
            "latency_ms": v.latency_ms,
            "error": v.error,
        }
        for v in verdicts
    ]
    err_count = sum(1 for v in verdicts if v.verdict == "ERROR")
    conclusion = (
        f"多裁判聚合[{strategy}]：最终{'PASS' if final_verdict == 'PASS' else 'FAIL'}"
        f"（{final_score} vs 阈值 {threshold}），"
        f"一致性 {agreement:.2f}，裁判 {len(verdicts)} 个、失败 {err_count} 个"
    )
    return EnsembleResult(
        final_score=final_score,
        final_verdict=final_verdict,
        strategy=strategy,
        threshold=threshold,
        judge_results=judge_results,
        agreement=agreement,
        score_std=std,
        conclusion=conclusion,
    )
