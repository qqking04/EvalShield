# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""模型网关路由（自 business.py 拆分，BUG-006 纯重构：路由 URL 与 openapi 完全不变）。

包含：/model-configs 增删改查、连通性测试、Ollama 本机模型列表拉取（router）、
模型用量统计 G-3（stats_router，business.py 原位聚合以保持注册顺序）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    AuthContext,
    authenticate_request,
    ensure_data_scope,
    require_permission,
)
from ..errors import BizError, NotFoundError
from ..limits import check_limit
from ..models import (
    ModelConfig,
    ModelGatewayRecord,
)
from ..schemas import (
    ModelConfigCreate,
    ModelConfigTestRequest,
    ModelConfigUpdate,
)
from ..services.audit import write_audit
from ..services.crypto import encrypt_api_key, is_masked, mask_api_key, decrypt_api_key
from ..services.llm_client import test_connection as llm_test_connection
from ..utils.no import gen_no


router = APIRouter()
stats_router = APIRouter()
from ._business_common import *  # noqa: F401,F403
# ---------------------------------------------------------------------------
# 模型网关
# ---------------------------------------------------------------------------
@router.get("/model-configs", response_model=dict)
async def list_model_configs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "read")),
):
    base_query = db.query(ModelConfig).filter(ModelConfig.deleted_at.is_(None))
    if not auth.is_super_admin:
        base_query = base_query.filter(ModelConfig.tenant_id == auth.tenant_id)
    total = base_query.count()
    rows = base_query.order_by(ModelConfig.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    items = [
            {
                "code": m.code,
                "name": m.name,
                "provider": m.provider,
                "base_url": m.base_url,
                "model": m.model,
                "api_key_env": m.api_key_env,
                # ES9-P-05：GET 只回掩码（sk-****abcd），禁止输出密文/明文
                "api_key_masked": mask_api_key(decrypt_api_key(m.api_key_enc)),
                "timeout_sec": m.timeout_sec,
                "max_tokens": m.max_tokens,
                "temperature": m.temperature,
                "seed": m.seed,
                "is_default": m.is_default,
                "status": m.status,
                "usage": m.usage,
                "is_system": m.is_system,
                "input_price_per_mtok": m.input_price_per_mtok,
                "output_price_per_mtok": m.output_price_per_mtok,
                "created_at": m.created_at,
                "updated_at": m.updated_at,
                "tenant_id": m.tenant_id,
            }
            for m in rows
        ]
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": items, "total": total},
    }


@router.post("/model-configs", response_model=dict)
async def create_model_config(
    body: ModelConfigCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "create")),
):
    # B5：社区版关闭本地私有模型接入（仅 LOCAL provider，云端模型不受影响）
    if str(body.provider or "").upper() == "LOCAL":
        check_limit("local_llm", db, auth)
    # T2/§4.2：同 tenant 同 usage 的 is_default 唯一（应用层校验，双默认 → 409）
    if body.is_default:
        usage = body.usage or "CHAT"
        dup_q = db.query(ModelConfig).filter(
            ModelConfig.deleted_at.is_(None),
            ModelConfig.is_default == True,  # noqa: E712
            ModelConfig.usage == usage,
        )
        if not auth.is_super_admin:
            dup_q = dup_q.filter(ModelConfig.tenant_id == auth.tenant_id)
        if dup_q.first():
            raise BizError(
                "ES-BIZ-0072",
                f"同用途（{usage}）仅允许一个默认模型，请先取消原默认位",
                http_status=409,
            )
    m = ModelConfig(
        code=gen_no("MG"),
        name=body.name,
        provider=body.provider,
        base_url=body.base_url,
        model=body.model,
        # ES9-P-05：UI 托管密钥与 env 名互斥——提交 api_key 时不落 env 名
        api_key_env=(None if body.api_key else body.api_key_env),
        api_key_enc=encrypt_api_key(body.api_key) if body.api_key else None,
        timeout_sec=body.timeout_sec or 60,
        max_tokens=body.max_tokens or 2048,
        temperature=body.temperature if body.temperature is not None else 0.2,
        seed=body.seed,
        is_default=body.is_default,
        usage=body.usage or "CHAT",
        input_price_per_mtok=body.input_price_per_mtok or 0.0,
        output_price_per_mtok=body.output_price_per_mtok or 0.0,
        tenant_id=auth.tenant_id,
        created_by=auth.user_id,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="model.create",
        module="model",
        request=request,
        detail=f"创建模型配置：{m.name}（{m.code}，provider={m.provider}，model={m.model}）",
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {"code": m.code, "name": m.name, "is_default": m.is_default},
    }


@router.put("/model-configs/{config_code}", response_model=dict)
async def update_model_config(
    config_code: str,
    body: ModelConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "update")),
):
    m = (
        db.query(ModelConfig)
        .filter(ModelConfig.code == config_code, ModelConfig.deleted_at.is_(None))
        .first()
    )
    if m is None:
        raise NotFoundError("ES-BIZ-0010", "模型配置不存在")
    await ensure_data_scope(auth, resource_tenant_id=m.tenant_id)
    # B5：社区版禁止把模型配置保存/改为 LOCAL provider
    if str(body.provider or "").upper() == "LOCAL" or m.provider == "LOCAL":
        check_limit("local_llm", db, auth)
    if (body.is_default is True) and not m.is_default:
        # T2/§4.2：同用途唯一默认（更新时同样校验，双默认 → 409）
        usage = body.usage or m.usage or "CHAT"
        dup_q = db.query(ModelConfig).filter(
            ModelConfig.deleted_at.is_(None),
            ModelConfig.is_default == True,  # noqa: E712
            ModelConfig.usage == usage,
            ModelConfig.code != config_code,
        )
        if not auth.is_super_admin:
            dup_q = dup_q.filter(ModelConfig.tenant_id == auth.tenant_id)
        if dup_q.first():
            raise BizError(
                "ES-BIZ-0072",
                f"同用途（{usage}）仅允许一个默认模型，请先取消原默认位",
                http_status=409,
            )
        # 仅清除「同用途」的旧默认位（此前误清除全部用途默认，设 EMBEDDING 默认会连带清掉 CHAT 默认）
        clear_q = db.query(ModelConfig).filter(
            ModelConfig.is_default == True,  # noqa: E712
            ModelConfig.usage == usage,
        )
        if not auth.is_super_admin:
            clear_q = clear_q.filter(ModelConfig.tenant_id == auth.tenant_id)
        clear_q.update({"is_default": False})
    # ES9-P-05：库内密文与 env 名互斥；含 **** 的回写视为未修改
    if body.api_key and not is_masked(body.api_key):
        m.api_key_enc = encrypt_api_key(body.api_key)
        m.api_key_env = None
        body.api_key_env = None
    if body.api_key_env:
        m.api_key_enc = None
    fields = {
        "name": body.name,
        "provider": body.provider,
        "base_url": body.base_url,
        "model": body.model,
        "api_key_env": body.api_key_env,
        "timeout_sec": body.timeout_sec,
        "max_tokens": body.max_tokens,
        "temperature": body.temperature,
        "seed": body.seed,
        "is_default": body.is_default,
        "status": body.status,
        "usage": body.usage,
        "input_price_per_mtok": body.input_price_per_mtok,
        "output_price_per_mtok": body.output_price_per_mtok,
    }
    for key, val in fields.items():
        if val is not None:
            setattr(m, key, val)
    db.commit()
    db.refresh(m)
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="model.update",
        module="model",
        request=request,
        detail=f"更新模型配置：{m.name}（{m.code}）",
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {"code": m.code, "name": m.name, "is_default": m.is_default},
    }


@router.post("/model-configs/{config_code}/test", response_model=dict)
async def test_model_config(
    config_code: str,
    request: Request,
    body: ModelConfigTestRequest | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "test")),
):
    """测试模型连通性：走真实 LLM 最小请求；body.api_key 为临时密钥（不落库）。"""
    m = (
        db.query(ModelConfig)
        .filter(ModelConfig.code == config_code, ModelConfig.deleted_at.is_(None))
        .first()
    )
    if m is None:
        raise NotFoundError("ES-BIZ-0010", "模型配置不存在")
    await ensure_data_scope(auth, resource_tenant_id=m.tenant_id)
    result = llm_test_connection(
        provider=m.provider,
        base_url=m.base_url,
        model=m.model,
        api_key_env=m.api_key_env,
        api_key_enc=m.api_key_enc,
        explicit_key=(body.api_key if body else None),
        temperature=m.temperature,
        max_tokens=16,
        timeout_sec=m.timeout_sec or 30,
    )
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="model.test",
        module="model",
        request=request,
        result="SUCCESS" if result.get("ok") else "FAILED",
        error_msg=None if result.get("ok") else result.get("error"),
        detail=f"测试模型连接：{m.code}（provider={m.provider}，model={m.model}），延迟 {result.get('latency_ms')}ms",
    )
    return {"code": 0, "message": "ok", "data": result}


@router.post("/model-configs/{config_code}/pull-ollama", response_model=dict)
async def pull_ollama_models(
    config_code: str,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "update")),
):
    """从 LOCAL 提供商（Ollama）拉取本机已安装的模型列表。

    Ollama 容器内访问宿主机: http://host.docker.internal:11434/api/tags
    若该配置未关联实际 Ollama 实例，返回中文提示。
    """
    # B5：社区版关闭本地私有模型接入（本端点仅服务 LOCAL/Ollama）
    check_limit("local_llm", db, auth)
    import httpx

    m = (
        db.query(ModelConfig)
        .filter(ModelConfig.code == config_code, ModelConfig.deleted_at.is_(None))
        .first()
    )
    if m is None:
        raise NotFoundError("ES-BIZ-0010", "模型配置不存在")
    if m.provider != "LOCAL":
        raise BizError(
            "ES-BIZ-0060", "仅 LOCAL（本地 Ollama）提供商支持拉取本机模型列表"
        )
    # base_url 未填或非 Ollama 地址时使用容器内宿主机默认地址
    target_url = (m.base_url or "http://host.docker.internal:11434").rstrip("/")
    url = f"{target_url}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            raise BizError(
                "ES-BIZ-0061",
                f"拉取 Ollama 模型失败：HTTP {resp.status_code}，请确认 Ollama 已启动并监听 11434 端口",
            )
        raw = resp.json()
        models = raw.get("models", [])
        items = [
            {
                "model_name": mm.get("name", ""),
                "size": mm.get("size"),
                "details": mm.get("details", {}),
                "modified_at": mm.get("modified_at"),
            }
            for mm in models
        ]
    except httpx.ConnectError:
        raise BizError(
            "ES-BIZ-0062",
            f"无法连接 Ollama（{target_url}），请确认宿主机已启动 Ollama 并开放 11434 端口",
            http_status=502,
        )
    except httpx.TimeoutException:
        raise BizError(
            "ES-BIZ-0064",
            f"连接 Ollama 超时（{target_url}）",
            http_status=502,
        )
    except Exception as e:
        raise BizError("ES-BIZ-0063", f"拉取 Ollama 模型异常：{str(e)}", http_status=500)

    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="model.pull_ollama",
        module="model",
        request=request,
        result="SUCCESS",
        detail=f"从 {config_code}（{target_url}）拉取 {len(items)} 个本地模型",
    )
    return {"code": 0, "message": "ok", "data": {"models": items, "count": len(items)}}


@router.delete("/model-configs/{config_code}", response_model=dict)
async def delete_model_config(
    config_code: str,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "delete")),
):
    m = (
        db.query(ModelConfig)
        .filter(ModelConfig.code == config_code, ModelConfig.deleted_at.is_(None))
        .first()
    )
    if m is None or m.deleted_at is not None:
        raise NotFoundError("ES-BIZ-0010", "模型配置不存在")
    await ensure_data_scope(auth, resource_tenant_id=m.tenant_id)
    m.deleted_at = datetime.now(timezone.utc)
    m.status = "DISABLED"
    db.commit()
    write_audit(
        db,
        user_id=auth.user_id,
        username=auth.username,
        tenant_id=auth.tenant_id,
        action="model.delete",
        module="model",
        request=request,
        detail=f"删除模型配置：{m.name}（{m.code}）",
    )
    return {"code": 0, "message": "ok", "data": None}
# ---------------------------------------------------------------------------
# G-3：模型配置用量统计（聚合 model_gateway_records）
# ---------------------------------------------------------------------------

@stats_router.get("/model-configs/{config_code}/stats", response_model=dict)
async def model_config_stats(
    config_code: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """模型配置用量统计（按 model_gateway_records 聚合）。"""
    m = db.query(ModelConfig).filter(
        ModelConfig.code == config_code, ModelConfig.deleted_at.is_(None)
    ).first()
    if m is None:
        raise NotFoundError("ES-BIZ-0010", "模型配置不存在")

    # 聚合（字段以 ModelGatewayRecord 实际定义为准：prompt_tokens/completion_tokens/total_cost）
    rows = (
        db.query(
            func.count(ModelGatewayRecord.id).label("call_count"),
            func.coalesce(func.sum(ModelGatewayRecord.latency_ms), 0).label(
                "total_latency_ms"
            ),
            func.coalesce(func.sum(ModelGatewayRecord.prompt_tokens), 0).label(
                "input_tokens"
            ),
            func.coalesce(func.sum(ModelGatewayRecord.completion_tokens), 0).label(
                "output_tokens"
            ),
            func.coalesce(func.sum(ModelGatewayRecord.total_cost), 0.0).label(
                "total_cost"
            ),
            func.coalesce(
                func.sum(case((ModelGatewayRecord.status == "SUCCESS", 1), else_=0)), 0
            ).label("success_count"),
            func.coalesce(
                func.sum(case((ModelGatewayRecord.status == "FAILED", 1), else_=0)), 0
            ).label("fail_count"),
        )
        .filter(ModelGatewayRecord.model_code == config_code)
        .one()
    )

    call_count = rows.call_count or 0
    total_lat = rows.total_latency_ms or 0

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "call_count": call_count,
            "total_latency_ms": total_lat,
            "avg_latency_ms": round(total_lat / max(1, call_count), 2),
            "input_tokens": rows.input_tokens or 0,
            "output_tokens": rows.output_tokens or 0,
            "total_cost": round(rows.total_cost or 0.0, 4),
            "success_count": rows.success_count or 0,
            "fail_count": rows.fail_count or 0,
        },
    }
