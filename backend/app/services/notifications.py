# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M3 通知中心统一入口（共享域 —— 禁止 import commercial）。

``emit(tenant_id, event, payload, *, severity="LOW")``：
1. 永远先写站内信 Notification（ref_no=payload.dedup_key 时按去重键防轰炸）；
2. 匹配 notify_rules（event 相等 + enabled + min_severity 门槛 + scope 过滤）；
3. 逐渠道 adapter.send()（同步 3s 超时；可重试类失败重试 1 次，仍败记 DEGRADED；
   配置类失败如解密/缺 URL 记 FAILED；渠道禁用记 SKIPPED）；
4. 全程写 notify_deliveries 留痕；
5. 整体吞异常，绝不抛回业务。

异步方式：规则匹配 + 外发放入 threading.Thread(daemon=True)，
对齐 task_runner.py launch_task_async 的既有线程模式；测试可直调 ``_emit_now`` 同步执行。
"""

from __future__ import annotations

import json
import logging
import threading

from ..database import SessionLocal
from ..models import (
    Notification,
    NotifyChannelConfig,
    NotifyDelivery,
    NotifyRule,
    Role,
    SystemUser,
    UserRole,
)
from ..security import decrypt_secret
from ..utils.no import gen_no
from .notify_adapters import ADAPTERS

logger = logging.getLogger(__name__)

# 事件语义面（§4.2 notify_rules.event 注释清单 + M2 fulfill 履约事件）
EVENTS = (
    "task.completed",
    "task.failed",
    "monitor.alert",
    "subscription.renewing",
    "subscription.activated",
    "defect.created",
    "review.assigned",
    "gate.verdict",
    "uat.finalized",
    "uat.rejected",
)

EVENT_LABELS = {
    "task.completed": "任务执行完成",
    "task.failed": "任务执行失败",
    "monitor.alert": "监控告警",
    "subscription.renewing": "订阅续费提醒",
    "subscription.activated": "订阅开通成功",
    "defect.created": "缺陷自动创建",
    "review.assigned": "评审指派",
    "gate.verdict": "质量门禁结论",
    "uat.finalized": "UAT 验收报告签核完成",
    "uat.rejected": "UAT 验收报告拒签",
    "channel.test": "渠道连通测试",
}

# 站内信 notif_type 映射（与 Notification 列注释一致：SYSTEM/TASK/ALERT/APPROVAL）
_EVENT_NOTIF_TYPE = {
    "task.completed": "TASK",
    "task.failed": "TASK",
    "monitor.alert": "ALERT",
    "defect.created": "TASK",
    "review.assigned": "APPROVAL",
    "subscription.renewing": "SYSTEM",
    "subscription.activated": "SYSTEM",
    "gate.verdict": "TASK",
    "channel.test": "SYSTEM",
}

# 严重级排序：LOW < MEDIUM < HIGH < CRITICAL
SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def render_message(event: str, payload: dict, severity: str) -> dict:
    """渲染统一消息（title/content 可被 payload 显式覆盖）。"""
    payload = payload or {}
    label = EVENT_LABELS.get(event, event)
    title = str(payload.get("title") or f"[EvalShield] {label}")
    content = payload.get("content")
    if not content:
        extras = {
            k: v
            for k, v in payload.items()
            if k not in ("title", "content", "dedup_key", "recipient_ids")
        }
        brief = "; ".join(f"{k}={v}" for k, v in list(extras.items())[:8])
        content = f"事件 {event}（级别 {severity}）" + (f"：{brief}" if brief else "")
    return {
        "event": event,
        "severity": severity,
        "title": title,
        "content": str(content),
        "payload": {
            k: v
            for k, v in payload.items()
            if k not in ("dedup_key", "recipient_ids", "title", "content")
        },
    }


def _tenant_recipient_ids(db, tenant_id: int, payload: dict) -> list[int]:
    """站内信收件人：payload.recipient_ids 指定者优先，并上租户管理员。

    共享域自实现（与 commercial/billing_cycle._tenant_admin_ids 同口径），
    不 import commercial —— 架构约束。
    """
    ids: set[int] = set()
    for uid in payload.get("recipient_ids") or []:
        try:
            ids.add(int(uid))
        except (TypeError, ValueError):
            continue
    rows = (
        db.query(SystemUser.id)
        .join(UserRole, UserRole.user_id == SystemUser.id)
        .join(Role, Role.id == UserRole.role_id)
        .filter(
            SystemUser.tenant_id == tenant_id,
            SystemUser.deleted_at.is_(None),
            SystemUser.status == "ACTIVE",
            Role.role_code.in_(("OWNER", "ADMIN", "SUPER_ADMIN")),
        )
        .distinct()
        .all()
    )
    ids.update(r[0] for r in rows)
    return sorted(ids)


def _write_inner_notice(db, tenant_id: int, event: str, payload: dict, msg: dict) -> None:
    """第 1 步：写站内信（现状机制不动；payload.dedup_key → ref_no 去重）。"""
    dedup_key = payload.get("dedup_key")
    if dedup_key:
        exists = (
            db.query(Notification.id)
            .filter(Notification.tenant_id == tenant_id, Notification.ref_no == str(dedup_key))
            .first()
        )
        if exists:
            return
    for uid in _tenant_recipient_ids(db, tenant_id, payload):
        db.add(
            Notification(
                notif_no=gen_no("NF"),
                user_id=uid,
                tenant_id=tenant_id,
                title=msg["title"][:256],
                content=msg["content"],
                notif_type=_EVENT_NOTIF_TYPE.get(event, "SYSTEM"),
                ref_no=str(dedup_key) if dedup_key else None,
            )
        )
    db.commit()


def _match_rules(db, tenant_id: int, event: str, severity: str, payload: dict) -> list[NotifyRule]:
    """第 2 步：匹配启用规则（event + min_severity 门槛 + scope 过滤）。"""
    rules = (
        db.query(NotifyRule)
        .filter(
            NotifyRule.tenant_id == tenant_id,
            NotifyRule.event == event,
            NotifyRule.enabled.is_(True),
        )
        .all()
    )
    sev = SEVERITY_ORDER.get(str(severity).upper(), 0)
    matched: list[NotifyRule] = []
    for r in rules:
        if sev < SEVERITY_ORDER.get((r.min_severity or "LOW").upper(), 0):
            continue  # 事件级别低于门槛：不外发（站内信已兜底）
        if not _scope_hit(r, payload):
            continue
        matched.append(r)
    return matched


def _scope_hit(rule: NotifyRule, payload: dict) -> bool:
    """scope JSON 过滤：{project_id?, suite_id?} 等值命中；空 scope = 全部。"""
    raw = (rule.scope or "").strip()
    if not raw:
        return True
    try:
        scope = json.loads(raw)
    except (ValueError, TypeError):
        return False
    if not isinstance(scope, dict) or not scope:
        return True
    for key in ("project_id", "suite_id"):
        if scope.get(key) is not None:
            if str((payload or {}).get(key)) != str(scope[key]):
                return False
    return True


def _record_delivery(db, tenant_id: int, rule_id: int | None, msg: dict, channel, status: str, error: str | None, attempts: int) -> None:
    """第 4 步：投递留痕（payload 存渲染摘要，截断防大对象）。"""
    db.add(
        NotifyDelivery(
            tenant_id=tenant_id,
            rule_id=rule_id,
            event=msg["event"],
            channel_kind=(channel.kind if channel is not None else "unknown"),
            channel_id=(channel.id if channel is not None else None),
            payload=json.dumps(
                {"title": msg["title"], "content": msg["content"][:500]},
                ensure_ascii=False,
            )[:4000],
            status=status,
            error=(str(error)[:2000] if error else None),
            attempts=attempts,
        )
    )
    db.commit()


def _deliver(db, tenant_id: int, rules: list[NotifyRule], msg: dict) -> None:
    """第 3 步：逐渠道发送（渠道去重，首个命中规则记 rule_id 留痕）。"""
    # 渠道 → 首个命中规则（同一事件同渠道只发一次）
    plan: dict[int, int | None] = {}
    for r in rules:
        try:
            cids = json.loads(r.channel_ids or "[]")
        except (ValueError, TypeError):
            continue
        for cid in cids:
            try:
                cid_i = int(cid)
            except (TypeError, ValueError):
                continue
            plan.setdefault(cid_i, r.id)
    if not plan:
        return
    for cid, rule_id in plan.items():
        ch = (
            db.query(NotifyChannelConfig)
            .filter(
                NotifyChannelConfig.id == cid,
                NotifyChannelConfig.tenant_id == tenant_id,
            )
            .first()
        )
        if ch is None:
            continue  # 渠道已删除：无实体可留痕对象，跳过
        if not ch.enabled:
            _record_delivery(db, tenant_id, rule_id, msg, ch, "SKIPPED", "渠道已禁用", 0)
            continue
        adapter = ADAPTERS.get(ch.kind)
        if adapter is None:
            _record_delivery(db, tenant_id, rule_id, msg, ch, "FAILED", f"未知渠道类型 {ch.kind}", 0)
            continue
        try:
            config = json.loads(decrypt_secret(ch.config))
            if not isinstance(config, dict):
                raise ValueError("渠道配置解密后不是 JSON 对象")
        except Exception as exc:  # noqa: BLE001 —— 解密/JSON 解析失败属配置类：FAILED 不重试
            _record_delivery(db, tenant_id, rule_id, msg, ch, "FAILED", f"配置解密失败: {exc}", 0)
            continue

        from .notify_adapters.base import SendResult  # 局部导入避免环

        result: SendResult = adapter(config, msg)
        attempts = 1
        if not result.ok and result.retryable:
            result = adapter(config, msg)  # 重试 1 次（§4.3）
            attempts = 2
        if result.ok:
            status = "SUCCESS"
        elif result.retryable:
            status = "DEGRADED"  # 网络/对端类：站内信已兜底，降级不阻断
        else:
            status = "FAILED"  # 配置类：不重试直接失败
        _record_delivery(db, tenant_id, rule_id, msg, ch, status, result.error, attempts)


def _emit_now(tenant_id: int, event: str, payload: dict, *, severity: str = "LOW") -> None:
    """同步执行完整 emit 流程（测试直调入口；整体吞异常）。"""
    db = SessionLocal()
    try:
        msg = render_message(event, payload or {}, severity)
        try:
            _write_inner_notice(db, tenant_id, event, payload or {}, msg)
        except Exception as exc:  # noqa: BLE001 —— 站内信失败不影响外发
            db.rollback()
            logger.warning("notify emit 站内信失败 tenant=%s event=%s: %s", tenant_id, event, exc)
        try:
            rules = _match_rules(db, tenant_id, event, severity, payload or {})
            if rules:
                _deliver(db, tenant_id, rules, msg)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("notify emit 外发失败 tenant=%s event=%s: %s", tenant_id, event, exc)
    finally:
        db.close()


def emit(tenant_id: int, event: str, payload: dict, *, severity: str = "LOW") -> None:
    """业务埋点统一入口：同步写站内信（保证兜底），规则匹配+外发放后台线程。

    任何异常均被吞掉并记日志，绝不影响主流程。
    """
    try:
        # 站内信 + 外发统一收敛到线程内顺序执行：
        # 1) 避免业务事务未提交时收件查询读脏（billing job 尾部才 commit 的场景）；
        # 2) 对齐 launch_task_async 的既有 daemon 线程模式（§4.3）。
        threading.Thread(
            target=_emit_safe,
            args=(tenant_id, event, dict(payload or {}), severity),
            name=f"notify-emit-{event}",
            daemon=True,
        ).start()
    except Exception as exc:  # noqa: BLE001 —— 线程启动失败也不能影响业务
        logger.warning("notify emit 启动线程失败 tenant=%s event=%s: %s", tenant_id, event, exc)


def _emit_safe(tenant_id: int, event: str, payload: dict, severity: str) -> None:
    try:
        _emit_now(tenant_id, event, payload, severity=severity)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify emit 线程异常 tenant=%s event=%s: %s", tenant_id, event, exc)
