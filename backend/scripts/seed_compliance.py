# -*- coding: utf-8 -*-
"""合规条款库种子数据插入脚本（24 条预置条款）。

用法：
    cd backend
    python scripts/seed_compliance.py

幂等执行：已存在的条款编号（clause_code）会跳过。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, engine  # noqa: E402
from app.models import Base, ComplianceClause  # noqa: E402

# 24 条预置合规条款（框架 3.0）
COMPLIANCE_CLAUSES: list[dict] = [
    {
        "code": "3.0-4.1.1",
        "category": "推理规划",
        "title": "提示注入防护",
        "risk": "HIGH",
        "engines": ["REDTEAM_TEST", "ETHICS_TEST"],
    },
    {
        "code": "3.0-4.1.2",
        "category": "推理规划",
        "title": "越狱攻击检测",
        "risk": "HIGH",
        "engines": ["REDTEAM_TEST"],
    },
    {
        "code": "3.0-4.1.3",
        "category": "推理规划",
        "title": "间接提示注入",
        "risk": "HIGH",
        "engines": ["REDTEAM_TEST"],
    },
    {
        "code": "3.0-4.1.4",
        "category": "推理规划",
        "title": "角色扮演逃逸",
        "risk": "MEDIUM",
        "engines": ["REDTEAM_TEST"],
    },
    {
        "code": "3.0-4.1.5",
        "category": "推理规划",
        "title": "多步推理安全边界",
        "risk": "MEDIUM",
        "engines": ["HALLUCINATION_TEST", "MULTI_TURN_TEST"],
    },
    {
        "code": "3.0-4.2.1",
        "category": "身份权限",
        "title": "身份伪造检测",
        "risk": "CRITICAL",
        "engines": ["REDTEAM_TEST"],
    },
    {
        "code": "3.0-4.2.2",
        "category": "身份权限",
        "title": "权限提升防护",
        "risk": "CRITICAL",
        "engines": ["REDTEAM_TEST", "API_TEST"],
    },
    {
        "code": "3.0-4.2.3",
        "category": "身份权限",
        "title": "会话劫持检测",
        "risk": "HIGH",
        "engines": ["REDTEAM_TEST", "API_TEST"],
    },
    {
        "code": "3.0-4.2.4",
        "category": "身份权限",
        "title": "越权访问控制",
        "risk": "HIGH",
        "engines": ["API_TEST", "DATAFLOW_TEST"],
    },
    {
        "code": "3.0-4.2.5",
        "category": "身份权限",
        "title": "多租户隔离验证",
        "risk": "HIGH",
        "engines": ["API_TEST", "DATAFLOW_TEST"],
    },
    {
        "code": "3.0-4.3.1",
        "category": "调用执行",
        "title": "工具调用注入检测",
        "risk": "HIGH",
        "engines": ["REDTEAM_TEST", "API_TEST"],
    },
    {
        "code": "3.0-4.3.2",
        "category": "调用执行",
        "title": "外部 API 滥用防护",
        "risk": "HIGH",
        "engines": ["API_TEST", "PERF_TEST"],
    },
    {
        "code": "3.0-4.3.3",
        "category": "调用执行",
        "title": "代码执行沙箱化",
        "risk": "CRITICAL",
        "engines": ["REDTEAM_TEST"],
    },
    {
        "code": "3.0-4.3.4",
        "category": "调用执行",
        "title": "资源耗尽防护",
        "risk": "MEDIUM",
        "engines": ["PERF_TEST"],
    },
    {
        "code": "3.0-4.3.5",
        "category": "调用执行",
        "title": "链式调用完整性",
        "risk": "MEDIUM",
        "engines": ["DATAFLOW_TEST", "MULTI_TURN_TEST"],
    },
    {
        "code": "3.0-4.4.1",
        "category": "记忆存储",
        "title": "敏感数据泄露检测",
        "risk": "CRITICAL",
        "engines": ["REDTEAM_TEST", "ETHICS_TEST"],
    },
    {
        "code": "3.0-4.4.2",
        "category": "记忆存储",
        "title": "记忆注入攻击防护",
        "risk": "HIGH",
        "engines": ["REDTEAM_TEST", "MULTI_TURN_TEST"],
    },
    {
        "code": "3.0-4.4.3",
        "category": "记忆存储",
        "title": "隐私数据遗忘验证",
        "risk": "HIGH",
        "engines": ["ETHICS_TEST", "RAG_TEST"],
    },
    {
        "code": "3.0-4.4.4",
        "category": "记忆存储",
        "title": "上下文窗口污染",
        "risk": "MEDIUM",
        "engines": ["RAG_TEST", "MULTI_TURN_TEST"],
    },
    {
        "code": "3.0-4.4.5",
        "category": "记忆存储",
        "title": "持久化存储加密",
        "risk": "MEDIUM",
        "engines": ["ETHICS_TEST", "API_TEST"],
    },
    {
        "code": "3.0-4.1.6",
        "category": "推理规划",
        "title": "幻觉事实一致性",
        "risk": "HIGH",
        "engines": ["HALLUCINATION_TEST", "RAG_TEST"],
    },
    {
        "code": "3.0-4.1.7",
        "category": "推理规划",
        "title": "逻辑推理链完整性",
        "risk": "MEDIUM",
        "engines": ["HALLUCINATION_TEST", "EVAL_ENGINE"],
    },
    {
        "code": "3.0-4.3.6",
        "category": "调用执行",
        "title": "回调 URL 验证",
        "risk": "MEDIUM",
        "engines": ["API_TEST", "REDTEAM_TEST"],
    },
    {
        "code": "3.0-4.4.6",
        "category": "记忆存储",
        "title": "审计日志完整性",
        "risk": "HIGH",
        "engines": ["ETHICS_TEST", "DATAFLOW_TEST"],
    },
]


def seed_compliance_clauses(db) -> int:
    """初始化合规条款库（幂等），返回新增条数。"""
    added = 0
    for c in COMPLIANCE_CLAUSES:
        exists = (
            db.query(ComplianceClause)
            .filter(ComplianceClause.clause_code == c["code"])
            .first()
        )
        if not exists:
            db.add(
                ComplianceClause(
                    clause_code=c["code"],
                    category=c["category"],
                    title=c["title"],
                    risk_level=c["risk"],
                    detection_methods=c["engines"],
                    framework_version="3.0",
                    status="ACTIVE",
                    tenant_id=1,
                )
            )
            added += 1
    db.commit()
    return added


def main() -> None:
    # 确保表已创建（幂等）
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        added = seed_compliance_clauses(db)
        total = (
            db.query(ComplianceClause)
            .filter(ComplianceClause.deleted_at.is_(None))
            .count()
        )
        print(f"[OK] 合规条款库：新增 {added} 条，共 {total} 条")
    finally:
        db.close()


if __name__ == "__main__":
    main()
