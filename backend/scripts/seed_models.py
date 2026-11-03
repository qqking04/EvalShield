# -*- coding: utf-8 -*-
"""初始化模型网关配置：DeepSeek（公有云）+ 本地 GPU 模型（Ollama OpenAI 兼容端点）。

幂等：已存在同 code 则跳过（避免重复种子）。运行：
  python backend/scripts/seed_models.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 容器内（DB_HOST=db）访问宿主 Ollama 需用 host.docker.internal；本机用 127.0.0.1
_LOCAL_OLLAMA_BASE = (
    "http://host.docker.internal:11434/v1"
    if os.environ.get("DB_HOST", "127.0.0.1") == "db"
    else "http://127.0.0.1:11434/v1"
)

from app.database import SessionLocal  # noqa: E402
from app.models import ModelConfig  # noqa: E402
from app.utils.no import gen_no  # noqa: E402


def upsert(db, seed: dict, is_default: bool) -> str:
    row = (
        db.query(ModelConfig)
        .filter(ModelConfig.code == seed["code"], ModelConfig.deleted_at.is_(None))
        .first()
    )
    if row is not None:
        return f"skip (已存在 {seed['code']})"
    m = ModelConfig(
        code=seed["code"],
        name=seed["name"],
        provider=seed["provider"],
        base_url=seed.get("base_url"),
        model=seed["model"],
        api_key_env=seed.get("api_key_env"),
        timeout_sec=seed.get("timeout_sec", 60),
        max_tokens=seed.get("max_tokens", 2048),
        temperature=seed.get("temperature", 0.2),
        is_default=is_default,
        status="ACTIVE",
        is_system=True,
        tenant_id=1,
        input_price_per_mtok=seed.get("input_price_per_mtok", 0.0),
        output_price_per_mtok=seed.get("output_price_per_mtok", 0.0),
    )
    db.add(m)
    db.commit()
    return f"insert {seed['code']}（{seed['provider']} / {seed['model']}）"


def main() -> int:
    seeds = [
        {
            "code": "MG-DEEPSEEK-DEFAULT",
            "name": "DeepSeek Chat（公有云）",
            "provider": "DEEPSEEK",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key_env": "DEEPSEEK_API_KEY",
            "timeout_sec": 60,
            "max_tokens": 2048,
            "temperature": 0.2,
            "is_default": True,
            "input_price_per_mtok": 2.0,
            "output_price_per_mtok": 8.0,
        },
        {
            "code": "MG-LOCAL-OLLAMA",
            "name": "本地 GPU 模型（Ollama）",
            "provider": "LOCAL",
            "base_url": _LOCAL_OLLAMA_BASE,
            "model": "qwen2.5:7b",
            "api_key_env": None,
            "timeout_sec": 120,
            "max_tokens": 2048,
            "temperature": 0.2,
            "input_price_per_mtok": 0.0,
            "output_price_per_mtok": 0.0,
        },
        {
            "code": "MG-LOCAL-EMBEDDING",
            "name": "本地 GPU Embedding（Ollama bge-m3）",
            "provider": "LOCAL",
            "base_url": _LOCAL_OLLAMA_BASE,
            "model": "bge-m3:latest",
            "api_key_env": None,
            "timeout_sec": 60,
            "max_tokens": 512,
            "temperature": 0.0,
            "input_price_per_mtok": 0.0,
            "output_price_per_mtok": 0.0,
        },
    ]
    db = SessionLocal()
    try:
        # 清掉旧的默认标记，重新按种子设定
        db.query(ModelConfig).filter(ModelConfig.is_default == True).update(  # noqa: E712
            {"is_default": False}
        )
        for i, s in enumerate(seeds):
            print(upsert(db, s, is_default=(i == 0)))
        # 若种子均跳过，确保 DeepSeek 仍是默认
        default = db.query(ModelConfig).filter(ModelConfig.is_default == True).first()  # noqa: E712
        if default is None:
            ds = (
                db.query(ModelConfig)
                .filter(
                    ModelConfig.code == "MG-DEEPSEEK-DEFAULT",
                    ModelConfig.deleted_at.is_(None),
                )
                .first()
            )
            if ds is not None:
                ds.is_default = True
                db.commit()
        db.commit()
        print("模型网关配置初始化完成")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())