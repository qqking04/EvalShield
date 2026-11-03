# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES9-P-12 事实源配置路由（优化9设计方案 §4.4）。

- /api/fact-sources CRUD：auth 凭据统一经 app/services/crypto.py
  （Fernet，兼容存量 aes$ 密文）加密落库，GET 出参仅回掩码
  ``sk-****abcd``（联动 ES8-SEC-01 密文断言）；
- SSRF 防护定稿（§4.4）：scheme ∉ {http,https} 拒绝；host ∈ RFC1918 /
  loopback / link-local（含 169.254.169.254 元数据地址）/ IPv6 ULA 拒绝；
  解析后对 IP 复校验。残余风险：DNS 重绑定（TOCTOU）——缓解措施为连通性
  测试与引擎调用侧各自独立复校验 + 超时收紧；彻底免疫需 connect-hook 级
  IP pin（httpx transport 层），已列入后续窗口。
- POST /{id}/test 契约：{ok, status: REACHABLE|TIMEOUT|UNCONFIGURED,
  latency_ms, error}（前端三态 toast）。
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import AuthContext, require_permission
from ..errors import BizError, NotFoundError
from ..models import EvalRun, FactSource
from ..services.audit import write_audit
from ..services.ssrf_guard import validate_base_url

logger = logging.getLogger(__name__)
router = APIRouter()


# ------------------------------------------------------------- 加密统一入口 ----
# ES9 遗留项：统一走 app/services/crypto.py（Fernet，兼容存量 aes$ 密文透明解密）；
# cryptography 为硬依赖，不再 try-import 降级。

from ..services.crypto import decrypt_secret, encrypt_secret


def _mask_auth(plain: str | None) -> str | None:
    """凭据掩码：sk-****abcd（尾 4 位可见）；空值返回 None。"""
    if not plain:
        return None
    tail = plain[-4:] if len(plain) > 4 else plain
    return f"sk-****{tail}"


# SSRF 校验已抽取至 app/services/ssrf_guard.py（BUG-003 共享模块，
# 存量细码 ES-FS-0001~0006 口径不变），此处经顶部 import 复用。


# ------------------------------------------------------------ 档位守卫 ----

def _require_fact_module(auth: AuthContext = Depends(require_permission("model", "read"))):
    """fact_sources 属 ENTERPRISE_ONLY（§1.4 plans.py）：community 形态 404。"""
    if settings.EDITION == "community":
        raise NotFoundError("ES-FS-0007", "事实源模块在当前形态不可用")
    return auth


class FactSourceBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    type: str = Field("kb_api", max_length=24)
    base_url: str | None = Field(None, max_length=2000)
    auth: str | None = Field(None, max_length=4096, description="凭据明文，落库即加密")


class FactSourceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    base_url: str | None = Field(None, max_length=2000)
    auth: str | None = Field(None, max_length=4096, description="留空=不变更凭据")
    status: str | None = Field(None, max_length=16)


def _out(fs: FactSource, usage_count: int = 0) -> dict:
    plain = None
    if fs.auth_cipher:
        try:
            plain = decrypt_secret(fs.auth_cipher)
        except Exception:  # 密文损坏不阻断列表
            plain = None
    return {
        "id": fs.id,
        "name": fs.name,
        "type": fs.type,
        "base_url": fs.base_url,
        "auth": _mask_auth(plain),
        "has_auth": bool(fs.auth_cipher),
        "status": fs.status,
        "usage_count": usage_count,  # ES10-P-01：被评测引用次数（软引用计数）
        "created_at": fs.created_at,
        "updated_at": fs.updated_at,
    }


def _get_fs(db: Session, fs_id: int, auth: AuthContext) -> FactSource:
    q = db.query(FactSource).filter(FactSource.id == fs_id, FactSource.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(FactSource.tenant_id == auth.tenant_id)
    fs = q.first()
    if fs is None:
        raise NotFoundError("ES-FS-0008", "事实源不存在或不属于当前租户")
    return fs


# ---------------------------------------------------------------- 端点 ----

@router.get("/fact-sources", response_model=dict)
async def list_fact_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(_require_fact_module),
):
    q = db.query(FactSource).filter(FactSource.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(FactSource.tenant_id == auth.tenant_id)
    total = q.count()
    rows = (
        q.order_by(FactSource.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    # ES10-P-01：一次 group-by 批量统计被评测引用次数（软引用，无外键）
    usage_q = (
        db.query(EvalRun.fact_source_id, func.count(EvalRun.id))
        .filter(EvalRun.fact_source_id.isnot(None), EvalRun.deleted_at.is_(None))
    )
    if not auth.is_super_admin:
        usage_q = usage_q.filter(EvalRun.tenant_id == auth.tenant_id)
    usage = dict(usage_q.group_by(EvalRun.fact_source_id).all())
    return {
        "code": 0,
        "message": "ok",
        "data": {"items": [_out(r, usage.get(r.id, 0)) for r in rows], "total": total},
    }


@router.post("/fact-sources", response_model=dict)
async def create_fact_source(
    body: FactSourceBody,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "create")),
):
    if settings.EDITION == "community":
        raise NotFoundError("ES-FS-0007", "事实源模块在当前形态不可用")
    if body.base_url:
        validate_base_url(body.base_url)
    fs = FactSource(
        tenant_id=auth.tenant_id or 1,
        name=body.name.strip(),
        type=(body.type or "kb_api").strip()[:24],
        base_url=(body.base_url or "").strip() or None,
        auth_cipher=encrypt_secret(body.auth) if body.auth else None,
    )
    db.add(fs)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BizError("ES-FS-0009", f"事实源名称 {body.name!r} 已存在", http_status=409)
    db.refresh(fs)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="fact_source.create", module="fact_sources", request=request,
        detail=f"id={fs.id} name={fs.name}",
    )
    return {"code": 0, "message": "ok", "data": _out(fs)}


@router.put("/fact-sources/{fs_id}", response_model=dict)
async def update_fact_source(
    fs_id: int,
    body: FactSourceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "update")),
):
    fs = _get_fs(db, fs_id, auth)
    if body.name is not None and body.name.strip() and body.name.strip() != fs.name:
        fs.name = body.name.strip()[:128]
    if body.base_url is not None:
        bu = body.base_url.strip()
        if bu:
            validate_base_url(bu)
        fs.base_url = bu or None
    if body.auth:  # 留空=不变更
        fs.auth_cipher = encrypt_secret(body.auth)
    if body.status in ("active", "disabled"):
        fs.status = body.status
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BizError("ES-FS-0009", f"事实源名称 {fs.name!r} 已存在", http_status=409)
    db.refresh(fs)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="fact_source.update", module="fact_sources", request=request,
        detail=f"id={fs.id}",
    )
    return {"code": 0, "message": "ok", "data": _out(fs)}


@router.delete("/fact-sources/{fs_id}", response_model=dict)
async def delete_fact_source(
    fs_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "delete")),
):
    from datetime import datetime, timezone

    fs = _get_fs(db, fs_id, auth)
    fs.deleted_at = datetime.now(timezone.utc)
    db.add(fs)
    db.commit()
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="fact_source.delete", module="fact_sources", request=request,
        detail=f"id={fs.id} name={fs.name}",
    )
    return {"code": 0, "message": "ok", "data": {"id": fs_id}}


@router.post("/fact-sources/{fs_id}/test", response_model=dict)
async def test_fact_source(
    fs_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("model", "test")),
):
    """连通性测试（三态：REACHABLE / TIMEOUT / UNCONFIGURED）。

    仅探测 base_url 根路径（GET，跟随重定向关死，8s 上限）；
    发起请求前再次 SSRF 复校验——保存后 host 的 DNS 可能已变更。
    """
    fs = _get_fs(db, fs_id, auth)
    if not fs.base_url:
        return {"code": 0, "message": "ok", "data": {
            "ok": False, "status": "UNCONFIGURED", "latency_ms": 0,
            "error": "未配置 base_url",
        }}
    try:
        validate_base_url(fs.base_url)
    except BizError as e:
        return {"code": 0, "message": "ok", "data": {
            "ok": False, "status": "UNCONFIGURED", "latency_ms": 0,
            "error": e.message,
        }}
    import httpx

    headers = {}
    if fs.auth_cipher:
        try:
            headers["Authorization"] = f"Bearer {decrypt_secret(fs.auth_cipher)}"
        except Exception:
            pass
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            r = await client.get(fs.base_url, headers=headers)
        latency = int((time.monotonic() - t0) * 1000)
        ok = r.status_code < 500
        return {"code": 0, "message": "ok", "data": {
            "ok": ok, "status": "REACHABLE" if ok else "UNCONFIGURED",
            "latency_ms": latency,
            "error": None if ok else f"HTTP {r.status_code}",
        }}
    except httpx.TimeoutException:
        latency = int((time.monotonic() - t0) * 1000)
        return {"code": 0, "message": "ok", "data": {
            "ok": False, "status": "TIMEOUT", "latency_ms": latency,
            "error": "连接超时（8s）",
        }}
    except Exception as e:  # 网络不可达 / DNS 失败等
        latency = int((time.monotonic() - t0) * 1000)
        logger.info("fact_source test failed id=%s: %s", fs_id, e)
        return {"code": 0, "message": "ok", "data": {
            "ok": False, "status": "UNCONFIGURED", "latency_ms": latency,
            "error": str(e)[:200],
        }}


__all__ = ["router", "validate_base_url"]
