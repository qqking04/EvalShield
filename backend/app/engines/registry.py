# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""引擎注册表：社区 12 引擎自动发现 + 商业 16 引擎显式注册（版本隔离 §2-B4）。

隔离语义：discover_engines() 只 import app.engines 下的 12 个社区引擎；
商业引擎由 app/commercial/engines/ 经 register_commercial_engines() 注册——
OSS 发行包中该目录物理不存在，importlib 命中 ModuleNotFoundError 即静默跳过，
get_engine("JAILBREAK") 返回 None → 调用方"引擎不存在"分支自然拒绝，无需新增防御代码。
"""

from __future__ import annotations

import importlib
import logging

from .base import BaseEngine

logger = logging.getLogger("evalshield.engines.registry")


class EngineRegistry:
    """引擎注册表（进程内单例）。"""

    def __init__(self) -> None:
        self._engines: dict[str, BaseEngine] = {}

    def register(self, engine: BaseEngine) -> None:
        if not engine.engine_code:
            raise ValueError("engine_code 不能为空")
        self._engines[engine.engine_code] = engine

    def get(self, code: str) -> BaseEngine | None:
        return self._engines.get(code)

    def all(self) -> list[BaseEngine]:
        return list(self._engines.values())

    def codes(self) -> list[str]:
        return list(self._engines.keys())

    def meta_list(self) -> list[dict]:
        """导出注册表元数据（供 /api/engines 列表返回）。"""
        return [
            {
                "engine_code": e.engine_code,
                "engine_name": e.engine_name,
                "engine_type": e.engine_type,
                "category": e.category,
                "version": e.version,
                "description": e.description,
                "params_schema": e.params_schema,  # None 表示前端 fallback 到本地 ENGINE_PARAMS
                "fidelity": e.fidelity,  # ES9-P-01/P-13：类属性反射（非手填）
            }
            for e in self._engines.values()
        ]


# 进程级单例
engine_registry = EngineRegistry()


def get_engine(code: str) -> BaseEngine | None:
    """按编码获取引擎实例（社区引擎未加载时自动 discover）。"""
    if not _community_ready:
        discover_engines()
    return engine_registry.get(code)


# ---- 社区 12 引擎（随 OSS 发布）----
_COMMUNITY_MODULES = [
    "ui_test",
    "api_test",
    "perf_test",
    "security_test",
    "agent_case_gen",  # 方案表中的 case_gen 实为本模块（engine_code=CASE_GEN）
    "http_security_headers",  # 安全报告补全 P1.1：A1 响应头安全策略
    "tls_check",  # 安全报告补全 P1.2：A2 传输层加密
    "static_secret_scan",  # 安全报告补全 P1.3：A3 JS 硬编码密钥
    "rbac_test",  # 安全报告补全 P1.4：B1 平台级接口鉴权
    "credential_storage_test",  # 安全报告补全 P1.5：B3 凭证存储方式
    "public_endpoint_test",  # 安全报告补全 P1.6：B2 公开接口校验
    "functional_defect_test",  # 安全报告补全 P1.7：C3 业务数据功能缺陷
]

# ---- 商业 16 引擎（仅全量树存在；OSS 树 ImportError 静默）----
_COMMERCIAL_MODULES = [
    "dataflow_test",
    "locust_perf",  # 真实压测
    "data_quality_test",
    "hallucination_test",
    "redteam_test",
    "rag_test",  # AI 幻觉/红队/RAG
    "multi_turn_test",
    "ethics_test",
    "eval_engine",  # AI 多轮/伦理/评测
    "prompt_injection",
    "privilege_escalation",
    "memory_leakage",
    "jailbreak",  # P0：越狱检测
    "pii_leak",  # P0：PII 泄露检测
    "self_heal",
    "defect_predict",  # 工程化 3 类
]

_community_ready = False
_commercial_ready = False


def _register_from_module(mod) -> None:
    """注册模块内全部 BaseEngine 具体子类。"""
    for name in dir(mod):
        obj = getattr(mod, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseEngine)
            and obj is not BaseEngine
            and getattr(obj, "engine_code", None)
        ):
            engine_registry.register(obj())


def _load_engine_module(dotted: str) -> None:
    """按 dotted 路径导入引擎模块并注册；单模块失败仅告警（不拖垮全部引擎）。"""
    try:
        mod = importlib.import_module(dotted)
    except ImportError as exc:
        logger.warning("引擎模块缺失（跳过）: %s: %s", dotted, exc)
        return
    _register_from_module(mod)


def discover_engines() -> None:
    """导入 12 个社区引擎并注册（幂等）；全量树下自动补齐商业引擎。

    守卫只看 _community_ready：商业门面 register.py 会在启动时先行调用
    register_commercial_engines()，若以 registry 非空作守卫会导致
    enterprise/saas 形态下 12 个社区引擎永久缺席（create_task 拒绝 API_TEST）。
    """
    global _community_ready
    if _community_ready:
        return
    _community_ready = True
    for m in _COMMUNITY_MODULES:
        _load_engine_module(f"app.engines.{m}")
    # 保持改造前"28 引擎全注册"行为（get_engine 自动发现路径也覆盖商业引擎）；
    # OSS 树 app.commercial.engines.* 不存在 → _load_engine_module 静默跳过。
    register_commercial_engines()


def register_commercial_engines() -> None:
    """商业引擎注册（commercial/register.py 调用；社区构建全部缺失静默）。"""
    global _commercial_ready
    if _commercial_ready:
        return
    _commercial_ready = True
    for m in _COMMERCIAL_MODULES:
        _load_engine_module(f"app.commercial.engines.{m}")


def sync_engine_fidelity(db) -> int:
    """把引擎类属性 fidelity upsert 进 test_engines.fidelity（按 engine_code 匹配）。

    ES9-P-01/P-13 回写时机：main.py lifespan 紧跟引擎装载后执行。
    DB 列永远是代码镜像而非手填；未注册进 DB 的引擎编码跳过（不新建行，
    引擎行由 sync_engines 管理页链路负责）。返回实际更新行数。
    """
    from ..models import TestEngine

    discover_engines()
    rows = db.query(TestEngine).all()
    by_code = {r.engine_code: r for r in rows}
    updated = 0
    for meta in engine_registry.meta_list():
        row = by_code.get(meta["engine_code"])
        if row is not None and row.fidelity != meta["fidelity"]:
            row.fidelity = meta["fidelity"]
            updated += 1
    if updated:
        db.commit()
    return updated
