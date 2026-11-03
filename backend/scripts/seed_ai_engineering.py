# -*- coding: utf-8 -*-
"""AI 工程化 seed 数据：为 CASE_GEN / SELF_HEAL / DEFECT_PREDICT 引擎准备初始数据。"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/evalshield",
)

from app.database import SessionLocal
from app.models import TestEngine


def seed() -> None:
    db = SessionLocal()
    try:
        engines = [
            {
                "engine_code": "CASE_GEN",
                "engine_name": "AI 用例生成",
                "engine_type": "ENGINEERING",
                "category": "CASE_GEN",
                "description": "基于 ReAct Agent 多步推理生成结构化测试用例（边界/异常/安全/AI 专项）",
                "version": "2.0.0",
                "entry_point": "app.engines.agent_case_gen.CaseGenEngine",
                "status": "ENABLED",
                "is_system": True,
            },
            {
                "engine_code": "SELF_HEAL",
                "engine_name": "脚本自愈",
                "engine_type": "ENGINEERING",
                "category": "SELF_HEAL",
                "description": "对执行失败的脚本分类诊断并自动修复重跑（最多 2 轮），产出自愈报告",
                "version": "2.0.0",
                "entry_point": "app.commercial.engines.self_heal.SelfHealEngine",
                "status": "ENABLED",
                "is_system": True,
            },
            {
                "engine_code": "DEFECT_PREDICT",
                "engine_name": "缺陷预测",
                "engine_type": "ENGINEERING",
                "category": "DEFECT_PREDICT",
                "description": "基于 5 维特征与可解释逻辑回归预测缺陷概率，输出 top 贡献与风险分级",
                "version": "2.0.0",
                "entry_point": "app.commercial.engines.defect_predict.DefectPredictEngine",
                "status": "ENABLED",
                "is_system": True,
            },
        ]
        for e in engines:
            existing = (
                db.query(TestEngine)
                .filter(TestEngine.engine_code == e["engine_code"])
                .first()
            )
            if existing:
                existing.engine_name = e["engine_name"]
                existing.description = e["description"]
                existing.version = e["version"]
                existing.entry_point = e["entry_point"]
                existing.status = e["status"]
            else:
                db.add(
                    TestEngine(
                        engine_code=e["engine_code"],
                        engine_name=e["engine_name"],
                        engine_type=e["engine_type"],
                        category=e["category"],
                        description=e["description"],
                        version=e["version"],
                        entry_point=e["entry_point"],
                        status=e["status"],
                        is_system=e["is_system"],
                    )
                )
        db.commit()
        print("seed_ai_engineering OK")
    except Exception as exc:
        db.rollback()
        print(f"seed_ai_engineering FAILED: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
