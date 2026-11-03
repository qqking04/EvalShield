# -*- coding: utf-8 -*-
"""P0/P1 核心数据种子：越狱样本库 / PII 规则库 / 中文法条库 / 风险映射 / 行业模板。

数据随代码分发（对齐 Trivy / Dependency-Track 等开源项目"数据入库前置"的做法），
存放于 backend/data/seed_*.json，本脚本幂等：按业务唯一键查重，存在即跳过。

用法：
    cd backend && python -m scripts.seed_p0_p1_data
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import date, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
DATA_DIR = os.path.join(BACKEND_DIR, "data")

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    ComplianceRegulation,
    IndustryTemplate,
    JailbreakSample,
    PIIRule,
    RiskToRegulationMapping,
)


def _load(name: str):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def seed_jailbreak_samples(db) -> tuple[int, int]:
    items = _load("seed_jailbreak_samples.json")
    added = skipped = 0
    for it in items:
        exists = (
            db.query(JailbreakSample.id)
            .filter(
                JailbreakSample.category == it["category"],
                JailbreakSample.attack_vector == it["attack_vector"],
                JailbreakSample.prompt_template == it["prompt_template"],
                JailbreakSample.deleted_at.is_(None),
            )
            .first()
        )
        if exists:
            skipped += 1
            continue
        db.add(
            JailbreakSample(
                category=it["category"],
                attack_vector=it["attack_vector"],
                prompt_template=it["prompt_template"],
                severity=it.get("severity", "HIGH"),
                source=it.get("source"),
                is_active=it.get("is_active", True),
            )
        )
        added += 1
    db.commit()
    return added, skipped


def seed_pii_rules(db) -> tuple[int, int]:
    items = _load("seed_pii_rules.json")
    added = skipped = 0
    for it in items:
        exists = (
            db.query(PIIRule.id)
            .filter(
                PIIRule.pii_type == it["pii_type"],
                PIIRule.rule_name == it["rule_name"],
                PIIRule.deleted_at.is_(None),
            )
            .first()
        )
        if exists:
            skipped += 1
            continue
        db.add(
            PIIRule(
                pii_type=it["pii_type"],
                rule_name=it["rule_name"],
                regex_pattern=it["regex_pattern"],
                description=it.get("description"),
                severity=it.get("severity", "HIGH"),
                context_keywords=it.get("context_keywords"),
                is_active=it.get("is_active", True),
            )
        )
        added += 1
    db.commit()
    return added, skipped


def seed_regulations(db) -> tuple[int, int]:
    items = _load("seed_regulations.json")
    added = skipped = 0
    for it in items:
        exists = (
            db.query(ComplianceRegulation.id)
            .filter(
                ComplianceRegulation.regulation_name == it["regulation_name"],
                ComplianceRegulation.article_number == it["article_number"],
                ComplianceRegulation.deleted_at.is_(None),
            )
            .first()
        )
        if exists:
            skipped += 1
            continue
        eff = it.get("effective_date")
        db.add(
            ComplianceRegulation(
                regulation_name=it["regulation_name"],
                article_number=it["article_number"],
                article_content=it["article_content"],
                violation_consequence=it.get("violation_consequence"),
                effective_date=(
                    datetime.strptime(eff, "%Y-%m-%d").date() if eff else None
                ),
                is_active=it.get("is_active", True),
            )
        )
        added += 1
    db.commit()
    return added, skipped


def seed_risk_mappings(db) -> tuple[int, int]:
    """regulation_key = "法规名|条号"，运行时解析为 regulation_id（无外键）。"""
    items = _load("seed_risk_mappings.json")
    reg_ids: dict[str, int] = {}
    for r in db.query(ComplianceRegulation).filter(
        ComplianceRegulation.deleted_at.is_(None)
    ):
        reg_ids[f"{r.regulation_name}|{r.article_number}"] = r.id

    added = skipped = 0
    for it in items:
        rid = reg_ids.get(it["regulation_key"])
        if rid is None:
            print(f"[WARN] 映射未找到法规: {it['regulation_key']}")
            continue
        exists = (
            db.query(RiskToRegulationMapping.id)
            .filter(
                RiskToRegulationMapping.risk_category == it["risk_category"],
                RiskToRegulationMapping.regulation_id == rid,
                RiskToRegulationMapping.deleted_at.is_(None),
            )
            .first()
        )
        if exists:
            skipped += 1
            continue
        db.add(
            RiskToRegulationMapping(
                risk_category=it["risk_category"],
                regulation_id=rid,
                mapping_description=it.get("mapping_description"),
            )
        )
        added += 1
    db.commit()
    return added, skipped


def seed_industry_templates(db) -> tuple[int, int]:
    items = _load("seed_industry_templates.json")
    added = skipped = 0
    for it in items:
        exists = (
            db.query(IndustryTemplate.id)
            .filter(
                IndustryTemplate.industry_name == it["industry_name"],
                IndustryTemplate.template_name == it["template_name"],
                IndustryTemplate.deleted_at.is_(None),
            )
            .first()
        )
        if exists:
            skipped += 1
            continue
        db.add(
            IndustryTemplate(
                industry_name=it["industry_name"],
                template_name=it["template_name"],
                engine_config=it["engine_config"],
                description=it.get("description"),
                is_active=it.get("is_active", True),
            )
        )
        added += 1
    db.commit()
    return added, skipped


def main() -> int:
    db = SessionLocal()
    try:
        total_add = total_skip = 0
        for label, fn in [
            ("越狱样本", seed_jailbreak_samples),
            ("PII 规则", seed_pii_rules),
            ("法条库", seed_regulations),
            ("风险映射", seed_risk_mappings),
            ("行业模板", seed_industry_templates),
        ]:
            added, skipped = fn(db)
            total_add += added
            total_skip += skipped
            print(f"[OK] {label}: 新增 {added}，跳过 {skipped}")
        print(f"[DONE] P0/P1 种子完成：新增 {total_add}，跳过 {total_skip}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
