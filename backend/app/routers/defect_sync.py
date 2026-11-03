# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M11 缺陷工单同步路由（方案 §12.4，共享域）。

两组路由：
- ``router``（前缀 /api/defect-sync）：targets CRUD + 探测、GitHub webhook 回写、
  links 查询；
- ``push_router``（前缀 /api）：POST /defects/{id}/push-target、
  POST /defects/batch-push。

安全约束：
- target 出参绝不回显 config 明文/密文，token 仅回 ****+后 4 位掩码；
- webhook 收端免登录，按 X-Hub-Signature-256 HMAC 验签（密钥取各 enabled
  github target 的 webhook_secret，兜底 settings.WEBHOOK_SECRET）。
能力位：defect_sync 未开启时 CRUD/推送一律 403。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import AuthContext, ensure_data_scope, require_permission
from ..errors import AuthError, BizError, NotFoundError
from ..models import Defect, DefectSyncLink, DefectSyncTarget
from ..security import decrypt_secret, encrypt_secret
from ..services.audit import write_audit
from ..services.defect_sync import ADAPTERS, PROVIDERS, SyncResult, apply_external_state, defect_payload

logger = logging.getLogger("evalshield.defect_sync.router")

router = APIRouter()
push_router = APIRouter()

_PROVIDER_PATTERN = "^(" + "|".join(PROVIDERS) + ")$"


def _guard_feature() -> None:
    """能力位闸门：defect_sync 未开启一律 403（同 monitors 范式）。"""
    from ..enterprise.features import feature_enabled

    if not feature_enabled("defect_sync"):
        raise BizError(
            "ES-LIC-0003",
            "缺陷工单同步为企业/SaaS 能力（defect_sync），请先开通该能力",
            http_status=403,
        )


# ---------------------------------------------------------------- 出参脱敏 ----

def _mask_token(plain: str) -> str:
    """令牌掩码：**** + 明文后 4 位（空则回 ****）。"""
    if not plain:
        return "****"
    return "****" + plain[-4:]


def _config_public(config: dict) -> dict:
    """出参 config：剔除 *_enc 密文键，附加 token_mask 供前端展示。"""
    cfg = config or {}
    out = {k: v for k, v in cfg.items() if not k.endswith("_enc") and k != "webhook_secret"}
    token_mask = ""
    for enc_key in ("token_enc", "personal_token_enc"):
        enc = cfg.get(enc_key)
        if isinstance(enc, str) and enc:
            try:
                token_mask = _mask_token(decrypt_secret(enc))
            except Exception:  # noqa: BLE001 —— 解密失败按无掩码处理
                token_mask = "****"
            break
    out["token_mask"] = token_mask
    return out


def _target_out(t: DefectSyncTarget) -> dict:
    return {
        "id": t.id,
        "tenant_id": t.tenant_id,
        "provider": t.provider,
        "name": t.name,
        "config": _config_public(t.config or {}),
        "enabled": t.enabled,
        "last_probe_ok": t.last_probe_ok,
        "last_probe_at": t.last_probe_at,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def _link_out(lk: DefectSyncLink) -> dict:
    return {
        "id": lk.id,
        "target_id": lk.target_id,
        "defect_id": lk.defect_id,
        "external_id": lk.external_id,
        "external_url": lk.external_url,
        "direction": lk.direction,
        "sync_status": lk.sync_status,
        "last_synced_at": lk.last_synced_at,
        "fail_reason": lk.fail_reason,
    }


def _get_target(db: Session, target_id: int) -> DefectSyncTarget:
    t = db.query(DefectSyncTarget).filter(DefectSyncTarget.id == target_id).first()
    if t is None:
        raise NotFoundError("ES-BIZ-0110", "工单同步目标不存在")
    return t


def _encrypt_incoming_config(cfg: dict) -> dict:
    """入站明文 config → 密文落库：token / personal_token 加密为 *_enc，
    webhook_secret 明文单独密文化存储。"""
    out = dict(cfg or {})
    for plain_key, enc_key in (("token", "token_enc"), ("personal_token", "personal_token_enc")):
        val = out.pop(plain_key, None)
        if isinstance(val, str) and val:
            out[enc_key] = encrypt_secret(val)
    ws = out.pop("webhook_secret", None)
    if isinstance(ws, str) and ws:
        out["webhook_secret_enc"] = encrypt_secret(ws)
    return out


# ---------------------------------------------------------------- 目标 CRUD ----

class TargetCreate(BaseModel):
    provider: str = Field(..., pattern=_PROVIDER_PATTERN)
    name: str = Field(..., min_length=1, max_length=128)
    config: dict = Field(default_factory=dict, description="连接参数明文（token 字段将加密落库）")
    enabled: bool = True


class TargetUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    config: dict | None = None
    enabled: bool | None = None


@router.get("/targets", response_model=dict)
async def list_targets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    provider: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("defect", "manage")),
):
    _guard_feature()
    q = db.query(DefectSyncTarget)
    if not auth.is_super_admin:
        q = q.filter(DefectSyncTarget.tenant_id == auth.tenant_id)
    if provider:
        q = q.filter(DefectSyncTarget.provider == provider)
    total = q.count()
    rows = q.order_by(DefectSyncTarget.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"code": 0, "message": "ok", "data": {"items": [_target_out(t) for t in rows], "total": total}}


@router.post("/targets", response_model=dict)
async def create_target(
    body: TargetCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("defect", "manage")),
):
    _guard_feature()
    exists = (
        db.query(DefectSyncTarget)
        .filter(DefectSyncTarget.tenant_id == auth.tenant_id, DefectSyncTarget.name == body.name)
        .first()
    )
    if exists is not None:
        raise BizError("ES-BIZ-0111", "同名工单目标已存在")
    t = DefectSyncTarget(
        tenant_id=auth.tenant_id,
        provider=body.provider,
        name=body.name,
        config=_encrypt_incoming_config(body.config or {}),
        enabled=body.enabled,
        created_by=auth.user_id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="defect_sync.target.create", module="defect", request=request,
        detail=f"新建工单同步目标：{t.name}（{t.provider}）",
    )
    return {"code": 0, "message": "ok", "data": _target_out(t)}


@router.put("/targets/{target_id}", response_model=dict)
async def update_target(
    target_id: int,
    body: TargetUpdate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("defect", "manage")),
):
    _guard_feature()
    t = _get_target(db, target_id)
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    if body.name is not None:
        t.name = body.name
    if body.config is not None:
        # 合并：保留原 *_enc（未重填 token 时不覆盖）
        merged = _encrypt_incoming_config(body.config)
        base_cfg = dict(t.config or {})
        for k, v in merged.items():
            base_cfg[k] = v
        # 明文 token 键若为空且 merged 未带密文，则保留原密文（不清空既有令牌）
        for enc_key in ("token_enc", "personal_token_enc", "webhook_secret_enc"):
            if enc_key not in merged and enc_key in (t.config or {}):
                base_cfg[enc_key] = t.config[enc_key]
        t.config = base_cfg
    if body.enabled is not None:
        t.enabled = body.enabled
    db.commit()
    db.refresh(t)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="defect_sync.target.update", module="defect", request=request,
        detail=f"更新工单同步目标：{t.name}（{t.id}）",
    )
    return {"code": 0, "message": "ok", "data": _target_out(t)}


@router.delete("/targets/{target_id}", response_model=dict)
async def delete_target(
    target_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("defect", "manage")),
):
    _guard_feature()
    t = _get_target(db, target_id)
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    name = t.name
    db.query(DefectSyncLink).filter(DefectSyncLink.target_id == t.id).delete(synchronize_session=False)
    db.delete(t)
    db.commit()
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="defect_sync.target.delete", module="defect", request=request,
        detail=f"删除工单同步目标：{name}（{target_id}）",
    )
    return {"code": 0, "message": "ok", "data": {"deleted": True}}


@router.post("/targets/{target_id}/test", response_model=dict)
async def test_target(
    target_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("defect", "manage")),
):
    """测试连接：解密配置 → 真实探测一次 → 更新 last_probe_*（探测失败降级不抛）。"""
    _guard_feature()
    t = _get_target(db, target_id)
    await ensure_data_scope(auth, resource_tenant_id=t.tenant_id)
    adapter = ADAPTERS.get(t.provider)
    error: str | None = None
    if adapter is None:
        probe_ok, error = False, f"不支持的平台：{t.provider}"
    else:
        result: SyncResult = adapter.probe(t.config or {})
        probe_ok = bool(result.ok)
        error = result.error
    t.last_probe_at = datetime.now(timezone.utc)
    t.last_probe_ok = probe_ok
    db.commit()
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=t.tenant_id,
        action="defect_sync.target.test", module="defect", request=request,
        detail=f"工单目标测试：{t.name} 结果={'成功' if probe_ok else '失败'}",
    )
    return {"code": 0, "message": "ok", "data": {"ok": probe_ok, "error": error, "last_probe_ok": probe_ok}}


# ---------------------------------------------------------------- 推送 ----

def _push_one(db: Session, defect: Defect, target: DefectSyncTarget) -> tuple[DefectSyncLink, bool]:
    """单缺陷推送（幂等）：已有 SYNCED link 直接返回不重复推送；
    FAILED link 允许重试（外部单未建成功，重试无重复单风险）。

    返回 (link, created)。推送失败落 sync_status=FAILED + fail_reason。
    """
    existing = (
        db.query(DefectSyncLink)
        .filter(DefectSyncLink.defect_id == defect.id, DefectSyncLink.target_id == target.id)
        .first()
    )
    if existing is not None and existing.sync_status != "FAILED":
        return existing, False
    adapter = ADAPTERS.get(target.provider)
    result: SyncResult | None = None
    if adapter is None:
        error = f"不支持的平台：{target.provider}"
    else:
        push_result: SyncResult = adapter.push(defect_payload(defect, target.config or {}), target.config or {})
        error = None if push_result.ok else (push_result.error or "推送失败")
        if push_result.ok:
            if existing is not None:  # FAILED 重试成功：原位更新
                existing.external_id = push_result.external_id or ""
                existing.external_url = push_result.external_url or ""
                existing.sync_status = "SYNCED"
                existing.fail_reason = None
                existing.last_synced_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(existing)
                return existing, False
            link = DefectSyncLink(
                tenant_id=defect.tenant_id, target_id=target.id, defect_id=defect.id,
                external_id=push_result.external_id or "", external_url=push_result.external_url or "",
                direction="out", sync_status="SYNCED",
                last_synced_at=datetime.now(timezone.utc),
            )
            db.add(link)
            db.commit()
            db.refresh(link)
            return link, True
        result = push_result
    # 失败路径：FAILED 重试原位刷新，否则新建 FAILED 行
    pending_id = f"pending-{defect.id}-{target.id}"
    if existing is not None:
        existing.external_id = pending_id
        existing.external_url = ""
        existing.sync_status = "FAILED"
        existing.fail_reason = error
        db.commit()
        db.refresh(existing)
        return existing, False
    link = DefectSyncLink(
        tenant_id=defect.tenant_id, target_id=target.id, defect_id=defect.id,
        external_id=pending_id, external_url="",
        direction="out", sync_status="FAILED", fail_reason=error,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link, True


class PushTargetIn(BaseModel):
    target_id: int


@push_router.post("/defects/{defect_id}/push-target", response_model=dict)
async def push_defect_to_target(
    defect_id: int,
    body: PushTargetIn,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("defect", "manage")),
):
    """单缺陷推送到指定工单目标（幂等：已 link 返回既有 link）。"""
    _guard_feature()
    defect = db.query(Defect).filter(Defect.id == defect_id, Defect.deleted_at.is_(None)).first()
    if defect is None:
        raise NotFoundError("ES-BIZ-0112", "缺陷不存在")
    await ensure_data_scope(auth, resource_tenant_id=defect.tenant_id)
    target = _get_target(db, body.target_id)
    await ensure_data_scope(auth, resource_tenant_id=target.tenant_id)
    link, created = _push_one(db, defect, target)
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="defect_sync.push", module="defect", request=request,
        detail=f"缺陷 {defect.defect_no} → {target.name}：{link.sync_status}",
    )
    return {"code": 0, "message": "ok", "data": {"link": _link_out(link), "created": created}}


class BatchPushIn(BaseModel):
    defect_ids: list[int] = Field(..., min_length=1, max_length=100, description="单次 ≤100（超限 422）")
    target_id: int


@push_router.post("/defects/batch-push", response_model=dict)
async def batch_push_defects(
    body: BatchPushIn,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("defect", "manage")),
):
    """批量推送（≤100/次，由 pydantic max_length 天然 422 拦截）。"""
    _guard_feature()
    target = _get_target(db, body.target_id)
    await ensure_data_scope(auth, resource_tenant_id=target.tenant_id)
    defects = (
        db.query(Defect)
        .filter(Defect.id.in_(body.defect_ids), Defect.deleted_at.is_(None))
        .all()
    )
    results: list[dict] = []
    ok_count = 0
    for d in defects:
        if not auth.is_super_admin and d.tenant_id != auth.tenant_id:
            continue
        link, created = _push_one(db, d, target)
        if link.sync_status == "SYNCED":
            ok_count += 1
        results.append({"defect_id": d.id, "sync_status": link.sync_status, "created": created,
                        "external_url": link.external_url})
    write_audit(
        db, user_id=auth.user_id, username=auth.username, tenant_id=auth.tenant_id,
        action="defect_sync.batch_push", module="defect", request=request,
        detail=f"批量推送 {len(results)} 条缺陷 → {target.name}（成功 {ok_count}）",
    )
    return {"code": 0, "message": "ok", "data": {"results": results, "ok": ok_count, "total": len(results)}}


# ---------------------------------------------------------------- 外联查询 ----

@router.get("/links", response_model=dict)
async def list_links(
    defect_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("defect", "read")),
):
    """缺陷详情侧栏外联列表（defect:read）。"""
    # 跨租户缺陷按"不存在"处理（404），避免 403 泄露资源存在性
    q = db.query(Defect).filter(Defect.id == defect_id, Defect.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(Defect.tenant_id == auth.tenant_id)
    defect = q.first()
    if defect is None:
        raise NotFoundError("ES-BIZ-0112", "缺陷不存在")
    rows = (
        db.query(DefectSyncLink)
        .filter(DefectSyncLink.defect_id == defect_id)
        .order_by(DefectSyncLink.id)
        .all()
    )
    return {"code": 0, "message": "ok", "data": {"items": [_link_out(lk) for lk in rows]}}


# ---------------------------------------------------------------- webhook 回写 ----

def _verify_github_signature(
    db: Session, raw_body: bytes, signature_header: str
) -> tuple[bool, DefectSyncTarget | None]:
    """校验 GitHub X-Hub-Signature-256，返回 (验签通过, 命中的 target)。

    遍历 enabled 的 github target 逐个解密 webhook_secret 做 HMAC-SHA256 比对，
    全部不命中再兜底 settings.WEBHOOK_SECRET（命中则 target=None）。
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False, None
    provided = signature_header[len("sha256="):]
    candidates: list[tuple[DefectSyncTarget | None, str]] = []
    targets = (
        db.query(DefectSyncTarget)
        .filter(DefectSyncTarget.provider == "github", DefectSyncTarget.enabled.is_(True))
        .all()
    )
    for t in targets:
        enc = (t.config or {}).get("webhook_secret_enc")
        if isinstance(enc, str) and enc:
            try:
                candidates.append((t, decrypt_secret(enc)))
            except Exception:  # noqa: BLE001 —— 解密失败的 target 跳过
                continue
    candidates.append((None, str(settings.WEBHOOK_SECRET)))
    for t, secret in candidates:
        digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(digest, provided):
            return True, t
    return False, None


@router.post("/webhook/github", response_model=dict)
async def github_webhook(request: Request, db: Session = Depends(get_db)):
    """GitHub issue 回写收端（免登录 + HMAC 验签，方案 §12.3）。

    仅处理 ``action in (closed, reopened, opened)`` 的 issues 事件：
    按 external_id=issue number（ix_dsl_target_external 载体）+ 仓库全名
    定位 link → apply_external_state 回写（closed→缺陷 CLOSED + 系统备注）。
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    ok, matched = _verify_github_signature(db, raw_body, signature)
    if not ok:
        raise AuthError("ES-DS-0001", "Webhook 验签失败", http_status=401)
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise BizError("ES-DS-0002", "Webhook 载荷不是合法 JSON")
    event = request.headers.get("X-GitHub-Event", "issues")
    if event != "issues" or not isinstance(payload, dict):
        return {"code": 0, "message": "ok", "data": {"ignored": True, "reason": "非 issues 事件"}}
    action = str(payload.get("action") or "")
    if action not in ("closed", "reopened", "opened"):
        return {"code": 0, "message": "ok", "data": {"ignored": True, "reason": f"action={action}"}}
    issue = payload.get("issue") or {}
    repo_full = str((payload.get("repository") or {}).get("full_name") or "")
    number = str(issue.get("number") or "")
    if not repo_full or not number:
        return {"code": 0, "message": "ok", "data": {"ignored": True, "reason": "缺 repo/number"}}
    state = "closed" if action == "closed" else ("reopened" if action == "reopened" else "open")
    rows = (
        db.query(DefectSyncLink, DefectSyncTarget, Defect)
        .join(DefectSyncTarget, DefectSyncTarget.id == DefectSyncLink.target_id)
        .join(Defect, Defect.id == DefectSyncLink.defect_id)
        .filter(
            DefectSyncTarget.provider == "github",
            DefectSyncLink.external_id == number,
            Defect.deleted_at.is_(None),
        )
        .all()
    )
    # 多目标同单号时按仓库全名精确定位（config.repo == payload.repository.full_name）
    hits = [(lk, t) for lk, t, _d in rows if str((t.config or {}).get("repo") or "") == repo_full] or [
        (lk, t) for lk, t, _d in rows
    ]
    defects_by_id = {int(d.id): d for _lk, _t, d in rows}
    changed = 0
    for lk, _t in hits:
        defect = defects_by_id.get(int(lk.defect_id))
        if defect is None:
            continue
        apply_external_state(db, defect, lk, state)
        changed += 1
    db.commit()
    write_audit(
        db, user_id=None, username="github-webhook", tenant_id=(matched.tenant_id if matched else 1),
        action="defect_sync.webhook", module="defect", request=request,
        result="SUCCESS",
        detail=f"GitHub webhook action={action} repo={repo_full} #{number} 回写 {changed} 条",
    )
    return {"code": 0, "message": "ok", "data": {"processed": changed, "action": action}}
