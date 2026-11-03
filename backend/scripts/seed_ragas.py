# -*- coding: utf-8 -*-
"""RAGAS 评测集 seed 脚本：向 EvalSet 写入首批 6 条 RAG 基准用例。"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from app.database import SessionLocal
from app.models import EvalSet
from app.utils.no import gen_no


def seed() -> None:
    db = SessionLocal()
    try:
        # ---- 第 2 模块：RAGAS 评测集 seed ----
        db.add(
            EvalSet(
                code=gen_no("EVS"),
                name="RAG 正确性基准（首批 6 条）",
                category="RAG",
                source="MANUAL",
                item_count=6,
                items=[
                    {
                        "no": "RAG-001",
                        "prompt": "EvalShield 支持哪些报告格式？",
                        "contexts": [
                            "EvalShield 支持 PDF、JSON、Markdown 三种报告格式。",
                            "报告由 report_generator 统一生成。",
                        ],
                        "ground_truth": "EvalShield 支持 PDF、JSON、Markdown 三种报告格式。",
                        "labeled_passages": [0],
                    },
                    {
                        "no": "RAG-002",
                        "prompt": "EvalShield 的硬性约束有哪些？",
                        "contexts": [
                            "系统无外键，业务编号关联 gen_no。",
                            "表采用软删除 deleted_at 与租户隔离 tenant_id。",
                        ],
                        "ground_truth": "无外键、软删除、租户隔离。",
                        "labeled_passages": [0, 1],
                    },
                    {
                        "no": "RAG-003",
                        "prompt": "引擎如何自动注册？",
                        "contexts": ["引擎类继承 BaseEngine，通过反射扫描自动注册。"],
                        "ground_truth": "引擎继承 BaseEngine 并注册到 registry。",
                        "labeled_passages": [0],
                    },
                    {
                        "no": "RAG-004",
                        "prompt": "后端技术栈是什么？",
                        "contexts": [
                            "后端为 Python 3.13 + FastAPI + SQLAlchemy 2.0 + PostgreSQL 16。"
                        ],
                        "ground_truth": "Python 3.13、FastAPI、SQLAlchemy 2.0、PostgreSQL 16。",
                        "labeled_passages": [0],
                    },
                    {
                        "no": "RAG-005",
                        "prompt": "LLM 调用支持哪些配置？",
                        "contexts": [
                            "LLM 调用走 llm_client，OpenAI 兼容，支持 5 个 provider。"
                        ],
                        "ground_truth": "OpenAI 兼容，5 个 provider。",
                        "labeled_passages": [0],
                    },
                    {
                        "no": "RAG-006",
                        "prompt": "响应格式规范是什么？",
                        "contexts": ['统一响应格式 {"code":0,"data":...}。'],
                        "ground_truth": "响应格式 code=0 表示成功。",
                        "labeled_passages": [0],
                    },
                ],
                tenant_id=1,
            )
        )
        db.commit()
        print("[seed_ragas] RAGAS 评测集 6 条已写入。")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
