# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
# backend/app/services/llm_cache.py
"""LLM 响应缓存：精确缓存（content-hash）+ 可选语义缓存（embedding 余弦相似度）。

设计要点：
- 进程内带热缓存（dict，容量上限），降低 DB 读放大；DB 为事实源。
- 幂等：get/set 全程 try/except，任何缓存异常不抛给上层（降级为直接调用 LLM）。
- 语义命中要求同 model + 余弦 >= threshold；查询失败（无 embedding 模型/向量缺失）自动退回精确缓存。
- 命中统计通过 hit_ratio 聚合函数暴露，供 /api/v1/gateway/cache/stats 消费。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Iterable

logger = logging.getLogger("evalshield.llm_cache")

DEFAULT_TTL_SECONDS: int = int(os.getenv("GATEWAY_CACHE_TTL_SECONDS", "86400"))
SEMANTIC_THRESHOLD: float = float(os.getenv("GATEWAY_CACHE_SEMANTIC_THRESHOLD", "0.95"))
HOT_CACHE_MAX: int = 4096  # 进程内热缓存条目上限


class LLMClientError(Exception):
    """占位：避免循环导入 llm_client；文档定义与 llm_client 一致。"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _strip_msg(msg: dict[str, str]) -> dict[str, str]:
    return {
        "role": str(msg.get("role", "user")).strip(),
        "content": str(msg.get("content", "")).strip(),
    }


def normalize_messages(
    prompt: str | None,
    system: str | None,
    history: Iterable[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """规范化消息序列：去空白、整理 role/content，语义上等价输入得到相同序列。"""
    msgs: list[dict[str, str]] = []
    if system and str(system).strip():
        msgs.append(_strip_msg({"role": "system", "content": str(system)}))
    for h in history or []:
        if isinstance(h, dict) and str(h.get("content", "")).strip():
            msgs.append(_strip_msg(h))
    if prompt and str(prompt).strip():
        msgs.append(_strip_msg({"role": "user", "content": str(prompt)}))
    return msgs


def build_cache_key(
    model: str, messages: list[dict[str, str]], namespace: str | None = None
) -> str:
    """缓存键：model + 规范化消息序列 -> SHA-256；可选引擎命名空间前缀。

    参考 GPTCache/LangCache 的 collection/namespace 隔离：namespace 非空时返回
    ``"<namespace>:<sha256hex>"``，供 invalidate_by_engine 按前缀精确失效；
    namespace 为 None 时返回纯 hash，与旧格式完全兼容（旧条目靠 TTL 自然过期）。
    """
    payload = json.dumps(
        [model] + messages, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    ns = str(namespace or "").strip()
    return f"{ns}:{digest}" if ns else digest


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """纯 Python 余弦相似度（避免引入 numpy；向量维度数百时性能足够）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na**0.5) * (nb**0.5))


class LLMCache:
    """缓存服务（进程单例）。"""

    def __init__(self) -> None:
        self._hot: dict[tuple[int, str], str] = {}  # (tenant_id, cache_key) -> response
        self._lock = threading.Lock()
        self._stats = {"hits": 0, "misses": 0, "semantic_hits": 0}
        self._embedding_fn = None  # 由 configure_embedding 注入

    # -- embedding 注入（可选） --------------------------------------------
    def configure_embedding(self, fn) -> None:
        """注入 embedding 计算函数 fn(prompt: str) -> list[float] | None。"""
        self._embedding_fn = fn

    def embedding_available(self) -> bool:
        return self._embedding_fn is not None

    # -- 查询 --------------------------------------------------------------
    def get(
        self,
        db,
        *,
        tenant_id: int,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        semantic_prompt: str | None = None,
        namespace: str | None = None,
    ) -> tuple[str, bool] | None:
        """按精确键查询；返回 (response_text, is_semantic_hit) 或 None。

        semantic_prompt 非空且语义缓存启用时，先做相似度查询。
        namespace 非空时按 ``<namespace>:<hash>`` 键查询（引擎命名空间隔离）。
        """
        key = build_cache_key(model, messages, namespace)
        hot_key = (tenant_id, key)
        try:
            with self._lock:
                cached = self._hot.get(hot_key)
            if cached is not None:
                self._touch(db, tenant_id=tenant_id, key=key, model=model)
                self._stats["hits"] += 1
                return cached, False
            hit = None
            if db is not None:
                hit = self._query_db(db, tenant_id=tenant_id, key=key, model=model)
            if hit is not None:
                with self._lock:
                    self._ensure_capacity()
                    self._hot[hot_key] = hit
                self._stats["hits"] += 1
                return hit, False
            if semantic_prompt and self.embedding_available():
                sem_hit = self._query_semantic(
                    db, tenant_id=tenant_id, model=model, prompt=semantic_prompt
                )
                if sem_hit is not None:
                    self._stats["semantic_hits"] += 1
                    self._stats["hits"] += 1
                    return sem_hit, True
            self._stats["misses"] += 1
            return None
        except Exception:  # noqa: BLE001 - 缓存任何异常都降级为未命中
            logger.exception("缓存查询异常，降级为未命中")
            self._stats["misses"] += 1
            return None

    # -- 写入 --------------------------------------------------------------
    def set(
        self,
        db,
        *,
        tenant_id: int,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        response_text: str,
        semantic_prompt: str | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        namespace: str | None = None,
    ) -> None:
        """写入缓存（含可选语义向量）。全程容错，失败不影响主流程。

        namespace 非空时以 ``<namespace>:<hash>`` 作为 cache_key 写入。
        """
        key = build_cache_key(model, messages, namespace)
        try:
            if db is not None:
                self._write_db(
                    db,
                    tenant_id=tenant_id,
                    provider=provider,
                    model=model,
                    messages=messages,
                    response_text=response_text,
                    key=key,
                    ttl_seconds=ttl_seconds,
                )
                if semantic_prompt and self.embedding_available():
                    self._write_semantic(
                        db,
                        tenant_id=tenant_id,
                        model=model,
                        prompt=semantic_prompt,
                        key=key,
                    )
                db.commit()
        except Exception:  # noqa: BLE001
            logger.warning(
                "缓存写入失败（降级：本次不缓存）key=%s tenant=%s", key, tenant_id, exc_info=True
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        # 热缓存始终写入（db 缺失时退化为纯内存缓存）
        with self._lock:
            self._ensure_capacity()
            self._hot[(tenant_id, key)] = response_text

    def _write_db(
        self,
        db,
        *,
        tenant_id: int,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        response_text: str,
        key: str,
        ttl_seconds: int,
    ) -> None:
        from ..models import LLMCacheEntry

        now = _utcnow()
        expires = now + timedelta(seconds=max(60, int(ttl_seconds)))
        row = (
            db.query(LLMCacheEntry)
            .filter(
                LLMCacheEntry.tenant_id == tenant_id,
                LLMCacheEntry.cache_key == key,
                LLMCacheEntry.model == model,
                LLMCacheEntry.deleted_at.is_(None),
            )
            .first()
        )
        if row is None:
            db.add(
                LLMCacheEntry(
                    cache_key=key,
                    provider=provider,
                    model=model,
                    normalized_msgs=messages,
                    response_text=response_text,
                    ttl_seconds=int(ttl_seconds),
                    expires_at=expires,
                    tenant_id=tenant_id,
                )
            )
        else:
            row.response_text = response_text
            row.expires_at = expires
            row.updated_at = now

    # -- 统计 --------------------------------------------------------------
    def hit_ratio(self) -> dict[str, Any]:
        total = self._stats["hits"] + self._stats["misses"]
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "semantic_hits": self._stats["semantic_hits"],
            "hit_ratio": round(self._stats["hits"] / total, 4) if total else 0.0,
            "hot_entries": len(self._hot),
        }

    def db_stats(self, db) -> dict[str, Any]:
        """DB 侧统计（今日写入量 / 待过期清理量）。"""
        from ..models import LLMCacheEntry

        try:
            now = _utcnow()
            total = (
                db.query(LLMCacheEntry)
                .filter(LLMCacheEntry.deleted_at.is_(None))
                .count()
            )
            expired = (
                db.query(LLMCacheEntry)
                .filter(
                    LLMCacheEntry.deleted_at.is_(None),
                    LLMCacheEntry.expires_at < now,
                )
                .count()
            )
            return {"db_entries": total, "expired_pending_cleanup": expired}
        except Exception:  # noqa: BLE001
            return {"db_entries": 0, "expired_pending_cleanup": 0}

    def cleanup_expired(self, db, *, limit: int = 200) -> int:
        """惰性清理过期缓存（软删除）。由调度器每小时调用一次。"""
        from ..models import LLMCacheEntry

        try:
            now = _utcnow()
            rows = (
                db.query(LLMCacheEntry)
                .filter(
                    LLMCacheEntry.deleted_at.is_(None),
                    LLMCacheEntry.expires_at < now,
                )
                .limit(limit)
                .all()
            )
            for r in rows:
                r.deleted_at = now
            db.commit()
            return len(rows)
        except Exception:  # noqa: BLE001
            logger.exception("清理过期缓存失败")
            return 0

    # -- 内部 --------------------------------------------------------------
    def _query_db(self, db, *, tenant_id: int, key: str, model: str) -> str | None:
        from ..models import LLMCacheEntry

        now = _utcnow()
        row = (
            db.query(LLMCacheEntry)
            .filter(
                LLMCacheEntry.tenant_id == tenant_id,
                LLMCacheEntry.cache_key == key,
                LLMCacheEntry.model == model,
                LLMCacheEntry.deleted_at.is_(None),
                LLMCacheEntry.expires_at >= now,
            )
            .first()
        )
        if row is None:
            return None
        self._touch(db, tenant_id=tenant_id, key=key, model=model)
        return row.response_text

    def _touch(self, db, *, tenant_id: int, key: str, model: str) -> None:
        """命中计数与半衰期续期（失败静默）。"""
        try:
            from ..models import LLMCacheEntry

            row = (
                db.query(LLMCacheEntry)
                .filter(
                    LLMCacheEntry.tenant_id == tenant_id,
                    LLMCacheEntry.cache_key == key,
                    LLMCacheEntry.model == model,
                    LLMCacheEntry.deleted_at.is_(None),
                )
                .first()
            )
            if row is None:
                return
            row.hit_count = (row.hit_count or 0) + 1
            row.last_hit_at = _utcnow()
            now = _utcnow()
            if (now - row.created_at).total_seconds() > (row.ttl_seconds or 86400) / 2:
                row.expires_at = now + timedelta(
                    seconds=max(60, int(row.ttl_seconds or DEFAULT_TTL_SECONDS))
                )
            db.commit()
        except Exception:  # noqa: BLE001
            pass

    def _query_semantic(
        self, db, *, tenant_id: int, model: str, prompt: str
    ) -> str | None:
        """embedding 相似度查询：返回 (response_text)。"""
        if self._embedding_fn is None:
            return None
        vec = self._embedding_fn(prompt)
        if not vec:
            return None
        from ..models import LLMCacheEntry, LLMCacheSemantic

        now = _utcnow()
        rows = (
            db.query(LLMCacheSemantic, LLMCacheEntry)
            .join(LLMCacheEntry, LLMCacheSemantic.entry_id == LLMCacheEntry.id)
            .filter(
                LLMCacheSemantic.tenant_id == tenant_id,
                LLMCacheSemantic.model == model,
                LLMCacheSemantic.deleted_at.is_(None),
                LLMCacheEntry.deleted_at.is_(None),
                LLMCacheEntry.expires_at >= now,
            )
            .limit(200)
            .all()
        )
        best_score = -1.0
        best: tuple[str, str] | None = None  # (cache_key, response)
        for sem, entry in rows:
            entry_vec = sem.embedding_json or []
            score = cosine_similarity(vec, entry_vec)
            if score > best_score:
                best_score = score
                best = (entry.cache_key, entry.response_text)
        if best is not None and best_score >= SEMANTIC_THRESHOLD:
            self._touch(db, tenant_id=tenant_id, key=best[0], model=model)
            with self._lock:
                self._ensure_capacity()
                self._hot[(tenant_id, best[0])] = best[1]
            return best[1]
        return None

    def _write_semantic(
        self, db, *, tenant_id: int, model: str, prompt: str, key: str
    ) -> None:
        if self._embedding_fn is None:
            return
        vec = self._embedding_fn(prompt)
        if not vec:
            return
        try:
            from ..models import LLMCacheEntry, LLMCacheSemantic

            entry = (
                db.query(LLMCacheEntry)
                .filter(
                    LLMCacheEntry.tenant_id == tenant_id,
                    LLMCacheEntry.cache_key == key,
                    LLMCacheEntry.deleted_at.is_(None),
                )
                .first()
            )
            if entry is None:
                return
            db.add(
                LLMCacheSemantic(
                    entry_id=entry.id,
                    tenant_id=tenant_id,
                    model=model,
                    prompt_text=prompt,
                    embedding_json=vec,
                )
            )
            # 同 prompt 只保留最新向量，避免语义表膨胀
            dup = (
                db.query(LLMCacheSemantic)
                .filter(
                    LLMCacheSemantic.tenant_id == tenant_id,
                    LLMCacheSemantic.model == model,
                    LLMCacheSemantic.prompt_text == prompt,
                    LLMCacheSemantic.deleted_at.is_(None),
                )
                .order_by(LLMCacheSemantic.id.desc())
                .offset(1)
                .all()
            )
            for d in dup:
                d.deleted_at = _utcnow()
            db.commit()
        except Exception:  # noqa: BLE001
            logger.warning("写入语义向量失败（不影响缓存功能）")

    def _ensure_capacity(self) -> None:
        if len(self._hot) < HOT_CACHE_MAX:
            return
        # FIFO 淘汰：删除最早插入的一半
        drop = len(self._hot) // 2
        for k in list(self._hot.keys())[:drop]:
            self._hot.pop(k, None)


# 进程级单例
llm_cache = LLMCache()


def _engine_key_prefix(engine_type: str) -> str:
    """引擎类型 -> cache_key 前缀约定（如 JAILBREAK -> jailbreak:）。

    说明：LLMCacheEntry 表无 engine_type 列（产品优化3说明书 U4 替代方案），
    失效按 cache_key 前缀 LIKE 匹配实现；前缀命名由调用侧在 build_cache_key
    时以 "<prefix>:<payload>" 约定注入。
    """
    return str(engine_type or "").strip().lower() + ":"


def invalidate_by_engine(db, engine_type: str, tenant_id: int) -> int:
    """按引擎类型失效 LLM 缓存（软删除 deleted_at IS NULL 的匹配条目）。

    - 匹配规则：cache_key 以约定前缀开头（如 "pii_leak:%"），兼容直接传入前缀。
    - 租户隔离：仅失效 tenant_id 指定租户的条目（BUG-002 修复）。
    - 同步清空进程内热缓存（热缓存键为不可逆 hash，无法按前缀精确剔除，
      整体清空以保证 CRUD 后不返回陈旧响应）。
    - 全程容错：任何异常仅记日志并返回 0，不向上抛出，不阻断主流程。
    """
    from ..models import LLMCacheEntry

    prefix = _engine_key_prefix(engine_type)
    try:
        now = _utcnow()
        n = (
            db.query(LLMCacheEntry)
            .filter(
                LLMCacheEntry.cache_key.like(f"{prefix}%"),
                LLMCacheEntry.deleted_at.is_(None),
                LLMCacheEntry.tenant_id == tenant_id,
            )
            .update(
                {
                    LLMCacheEntry.deleted_at: now,
                    LLMCacheEntry.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        try:
            with llm_cache._lock:
                llm_cache._hot.clear()
        except Exception:  # noqa: BLE001
            pass
        if n:
            logger.info("LLM 缓存失效：engine=%s，软删除 %d 条", engine_type, n)
        return int(n)
    except Exception:  # noqa: BLE001
        logger.warning("LLM 缓存失效异常（忽略，不阻断主流程）：engine=%s", engine_type, exc_info=True)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0


def configure_embedding_from_config(db) -> None:
    """按配置为 llm_cache 注入 embedding 函数（ModelConfig 中 GATEWAY_EMBEDDING_MODEL_CODE
    指向的配置可用时启用；不可用则保持精确缓存模式，静默降级）。"""
    model_code = os.getenv("GATEWAY_EMBEDDING_MODEL_CODE", "").strip()
    if not model_code:
        return
    if db is None:
        return

    def _embed(prompt: str) -> list[float] | None:
        try:
            from ..models import ModelConfig
            from .engine_llm import resolve_model_config

            row = (
                db.query(ModelConfig)
                .filter(
                    ModelConfig.code == model_code,
                    ModelConfig.deleted_at.is_(None),
                    ModelConfig.status == "ACTIVE",
                )
                .first()
            )
            if row is None:
                return None
            model = {
                "provider": row.provider,
                "base_url": row.base_url,
                "model": row.model,
                "api_key_env": row.api_key_env,
                "api_key_enc": row.api_key_enc,
                "temperature": 0.0,
                "max_tokens": 16,
                "timeout_sec": row.timeout_sec or 30,
            }
            from .llm_client import embedding_completion

            vec = embedding_completion(model, prompt=prompt)
            return vec
        except (LLMClientError, Exception):  # noqa: BLE001
            return None

    llm_cache.configure_embedding(_embed)
    logger.info("语义缓存已启用（embedding 模型 code=%s）", model_code)
