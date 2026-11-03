# -*- coding: utf-8 -*-
"""P1 AI 检测精度升级：种子数据初始化脚本（幂等）。

用法：python scripts/seed_p1.py
- 幂等执行：已存在的数据自动跳过，不重复插入。
- 依赖：backend/app 包必须可导入。
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    EthicRegulation,
    ModelConfig,
)
from app.utils.no import gen_no  # noqa: E402


# ---------------------------------------------------------------------------
# 默认伦理法规库（与 ethics_test.py _DEFAULT_REGULATIONS 保持一致）
# ---------------------------------------------------------------------------
DEFAULT_REGULATIONS: list[dict] = [
    {
        "regulation_no": "REG-001",
        "regulation_name": "中华人民共和国民法典（节选）",
        "version": "v2024.1",
        "effective_date": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "clauses": [
            {"clause_no": "8.1", "text": "不得侵害他人名誉权、隐私权"},
            {"clause_no": "8.2", "text": "不得生成虚假信息用于商业欺诈"},
        ],
        "region": "CN",
        "global_flag": True,
        "status": "ACTIVE",
    },
    {
        "regulation_no": "REG-002",
        "regulation_name": "生成式人工智能服务管理暂行办法（节选）",
        "version": "v2024.9",
        "effective_date": datetime(2024, 9, 1, tzinfo=timezone.utc),
        "clauses": [
            {"clause_no": "4.1", "text": "提供者应采取有效措施防止用户过度依赖或沉迷"},
            {
                "clause_no": "4.2",
                "text": "不得生成含有暴力、淫秽、色情等不良信息的内容",
            },
            {"clause_no": "4.3", "text": "应建立投诉举报机制并及时处理"},
        ],
        "region": "CN",
        "global_flag": True,
        "status": "ACTIVE",
    },
    {
        "regulation_no": "REG-002",
        "regulation_name": "生成式人工智能服务管理暂行办法（节选）",
        "version": "v2025.1",
        "effective_date": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "clauses": [
            {"clause_no": "4.1", "text": "提供者应采取有效措施防止用户过度依赖或沉迷"},
            {
                "clause_no": "4.2",
                "text": "不得生成含有暴力、淫秽、色情等不良信息的内容",
            },
            {"clause_no": "4.3", "text": "应建立投诉举报机制并及时处理"},
            {"clause_no": "4.4", "text": "应定期发布安全评估报告"},
        ],
        "region": "CN",
        "global_flag": True,
        "status": "ACTIVE",
    },
    {
        "regulation_no": "REG-003",
        "regulation_name": "广告法（节选）",
        "version": "v2021.1",
        "effective_date": datetime(2021, 1, 1, tzinfo=timezone.utc),
        "clauses": [
            {"clause_no": "1.1", "text": "不得使用虚假或者引人误解的宣传"},
            {"clause_no": "1.2", "text": "不得贬低其他生产经营者的商品或服务"},
        ],
        "region": "CN",
        "global_flag": False,
        "status": "ACTIVE",
    },
]


# ---------------------------------------------------------------------------
# Embedding 模型配置（文档要求支持 usage=EMBEDDING）
# ---------------------------------------------------------------------------
EMBEDDING_CONFIGS: list[dict] = [
    {
        "code": "EMB-BGE-SMALL",
        "name": "BGE-small-zh 本地 Embedding",
        "provider": "LOCAL",
        "model": "BAAI/bge-small-zh",
        "api_key_env": None,
        "base_url": None,
        "is_default": True,
        "is_system": True,
        "status": "ACTIVE",
        "input_price_per_mtok": 0.0,
        "output_price_per_mtok": 0.0,
    },
]


def seed_ethic_regulations(db) -> None:
    """伦理法规库种子数据（幂等）。"""
    added = 0
    skipped = 0
    for reg in DEFAULT_REGULATIONS:
        exists = (
            db.query(EthicRegulation)
            .filter(
                EthicRegulation.regulation_no == reg["regulation_no"],
                EthicRegulation.version == reg["version"],
                EthicRegulation.deleted_at.is_(None),
            )
            .first()
        )
        if exists:
            skipped += 1
            continue
        db.add(
            EthicRegulation(
                regulation_no=reg["regulation_no"],
                regulation_name=reg["regulation_name"],
                version=reg["version"],
                effective_date=reg["effective_date"],
                clauses=reg["clauses"],
                region=reg["region"],
                global_flag=reg["global_flag"],
                status=reg["status"],
                tenant_id=1,
                created_by=1,
            )
        )
        added += 1
    db.commit()
    print(
        f"[OK] 伦理法规库：新增 {added} 条，跳过 {skipped} 条，共 {db.query(EthicRegulation).filter(EthicRegulation.deleted_at.is_(None)).count()} 条"
    )


def seed_embedding_configs(db) -> None:
    """Embedding 模型配置种子（幂等）。"""
    added = 0
    skipped = 0
    for cfg in EMBEDDING_CONFIGS:
        exists = (
            db.query(ModelConfig)
            .filter(ModelConfig.code == cfg["code"], ModelConfig.deleted_at.is_(None))
            .first()
        )
        if exists:
            # 如果 usage 列已存在，更新为 EMBEDDING
            if hasattr(exists, "usage") and exists.usage != "EMBEDDING":
                exists.usage = "EMBEDDING"
                db.commit()
                print(f"[OK] Embedding 配置 {cfg['code']} usage 已更新为 EMBEDDING")
            skipped += 1
            continue
        db.add(
            ModelConfig(
                code=cfg["code"],
                name=cfg["name"],
                provider=cfg["provider"],
                model=cfg["model"],
                api_key_env=cfg["api_key_env"],
                base_url=cfg["base_url"],
                is_default=cfg["is_default"],
                is_system=cfg["is_system"],
                status=cfg["status"],
                input_price_per_mtok=cfg["input_price_per_mtok"],
                output_price_per_mtok=cfg["output_price_per_mtok"],
                tenant_id=1,
                created_by=1,
            )
        )
        added += 1
    db.commit()
    print(f"[OK] Embedding 配置：新增 {added} 条，跳过 {skipped} 条")


def main() -> None:
    db = SessionLocal()
    try:
        seed_ethic_regulations(db)
        seed_embedding_configs(db)
    finally:
        db.close()
    print("\nP1 种子数据初始化完成 ✓")


if __name__ == "__main__":
    main()
