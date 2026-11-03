# -*- coding: utf-8 -*-
"""多轮一致性基准用例 seed 脚本。

幂等写入：已存在同 category + source 的 EvalSet 时跳过，可重复执行。
用法：
    cd backend
    python scripts/seed_multiturn.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import EvalSet  # noqa: E402
from app.utils.no import gen_no  # noqa: E402


def seed_multiturn(db) -> None:
    """写入多轮一致性基准评测集（含矛盾剧本与漂移剧本）。"""
    existing = (
        db.query(EvalSet)
        .filter(
            EvalSet.category == "MULTI_TURN",
            EvalSet.source == "MANUAL",
            EvalSet.deleted_at.is_(None),
        )
        .first()
    )
    if existing:
        print(f"[SKIP] 多轮一致性基准已存在（code={existing.code}），跳过")
        return

    db.add(
        EvalSet(
            code=gen_no("EVS"),
            name="多轮一致性基准（剧本 4 组）",
            category="MULTI_TURN",
            source="MANUAL",
            visibility="TEAM",
            item_count=4,
            items=[
                {
                    "session": "MT-001",
                    "topic": "产品价格口径",
                    "rounds": 3,
                    "agent_case": [
                        {"user": "你们年费是多少？"},
                        {"user": "这个价格包含几个席位？"},
                        {"user": "续费时价格会变吗？"},
                    ],
                },
                {
                    "session": "MT-002",
                    "topic": "部署方式",
                    "rounds": 3,
                    "agent_case": [
                        {"user": "支持私有化部署吗？"},
                        {"user": "那数据存在哪里？"},
                        {"user": "我可以本地离线使用吗？"},
                    ],
                },
                {
                    "session": "MT-003",
                    "topic": "报告格式细节",
                    "rounds": 2,
                    "agent_case": [
                        {"user": "报告可以导出 PDF 吗？"},
                        {"user": "导出后里面的图是矢量图吗？"},
                    ],
                },
                {
                    "session": "MT-004",
                    "topic": "硬性约束理解",
                    "rounds": 3,
                    "agent_case": [
                        {"user": "表之间为什么不用外键？"},
                        {"user": "那数据关系怎么保证一致？"},
                        {"user": "软删除的字段叫什么？"},
                    ],
                },
            ],
            tenant_id=1,
        )
    )
    db.commit()
    print("[OK] 多轮一致性基准 seed 完成（4 组会话剧本）")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed_multiturn(db)
    finally:
        db.close()
