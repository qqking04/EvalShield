# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M12 数据保留与注销服务（方案 §13 M12）。

两条链路：
1. 日清理 run_retention_purge(db)：按 retention_policies 逐策略扫描过期数据，
   每策略每轮最多删除 BATCH_LIMIT(=5000) 行（分批防长事务锁表），
   每轮写一条审计（action=retention.purge，module=retention）。
2. 注销到期匿名化 run_anonymization(db)：扫描 subscriptions.anonymize_after
   到期且 status=CANCELED 的订阅，把该租户内容列置 NULL（NOT NULL 列置固定
   占位符），保留墓碑行（行不删、可审计计数），同样分批 + 每轮审计。

【硬约束——audit_logs 永不触碰】
审计日志是不可篡改的合规底线（见 services/audit.py 链式哈希设计）：
- 写入侧：router 创建/更新策略时 validate_policy() 抛
  BizError("ES8-RET-0002", ...)；
- 执行侧：本模块 purge 循环内对 artifact_type=audit_logs 再次硬拒
  （防御直插库的历史脏数据），绝不允许任何保留策略清理审计日志。
文档注释与单测（tests/test_es8_retention.py）双向写死该约束。

分批实现：先 SELECT id ... ORDER BY id LIMIT :batch 取主键集，
再 WHERE id IN (...) 删除/更新——避免 DELETE ... LIMIT 方言差异，
PG / 测试环境行为一致；每批独立 commit，失败回滚本批不中断其余策略。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..errors import BizError
from ..models import (
    EvalRun,
    RetentionPolicy,
    Subscription,
    SystemUser,
    TaskArtifact,
    Tenant,
    TestRecording,
    Trace,
)
from .audit import write_audit

logger = logging.getLogger("evalshield.retention")

# 每轮（每策略）删除/更新行数上限——防长事务（方案 §13 M12：分批 ≤5000 行/轮）
BATCH_LIMIT = 5000

# audit_logs 硬拒错误码（方案 §13 M12 明文规定；写入侧与执行侧共用）
RET_AUDIT_LOGS_FORBIDDEN = "ES8-RET-0002"

# 匿名化占位符：NOT NULL 内容列无法置 NULL，用固定不可辨识串覆盖（墓碑行保留）
ANON_PLACEHOLDER = "ANONYMIZED"

# artifact_type → (模型, 过期判定时间列, 是否支持 archive_ref 软删)
# traces 用 occurred_at（对话发生时间，命中 ix_traces_tenant_occurred）；
# 其余表用 created_at（均有 tenant_id 普通索引，分批扫描够用）。
ARTIFACT_TABLES: dict[str, tuple[type, str, bool]] = {
    RetentionPolicy.ARTIFACT_TRACES: (Trace, "occurred_at", False),
    RetentionPolicy.ARTIFACT_RUNS: (EvalRun, "created_at", True),
    RetentionPolicy.ARTIFACT_RECORDINGS: (TestRecording, "created_at", False),
    RetentionPolicy.ARTIFACT_ATTACHMENTS: (TaskArtifact, "created_at", True),
}

# 匿名化列集（内容列 → 覆盖值；None=置 NULL，str=置占位符）。
# 原则：可空内容列置 NULL；NOT NULL 内容列置占位符；
# 结构性列（id/tenant_id/编号/状态/时间戳）一律保留，墓碑行可计数不可辨识。
ANON_SPECS: list[tuple[type, dict[str, object]]] = [
    # 留痕：请求/响应正文（NOT NULL Text → 占位符）、评分快照、模型元信息
    (Trace, {
        "request": ANON_PLACEHOLDER, "response": ANON_PLACEHOLDER,
        "scores": "{}", "model": None, "external_ref": None,
    }),
    # 评测运行：逐项结果/汇总/可复现快照（JSONB 可空 → NULL）
    (EvalRun, {"item_results": None, "summary": None, "run_snapshot": None}),
    # 录制：steps 在 DDL 中是 JSONB NOT NULL DEFAULT '[]' → 置空数组而非 NULL；name NOT NULL → 占位符
    (TestRecording, {"steps": [], "name": ANON_PLACEHOLDER}),
    # 附件：file_name/file_path NOT NULL → 占位符（物理文件由运维另行清理）
    (TaskArtifact, {"file_name": ANON_PLACEHOLDER, "file_path": ANON_PLACEHOLDER}),
    # 租户用户：个人标识内容列（可空 → NULL；NOT NULL → 唯一化占位防冲突）
    (SystemUser, {
        "email": None, "phone": None, "display_name": ANON_PLACEHOLDER,
        "avatar": None, "title": None, "last_login_ip": None,
        "mfa_secret": None, "pwd_reset_token": None,
    }),
    # 租户主数据：名称/联系方式（name NOT NULL → 带 id 占位防重名歧义）
    (Tenant, {"contact_email": None, "note": None}),
]


def validate_policy(artifact_type: str, purge_action: str | None = None) -> None:
    """策略写入/执行前的统一校验闸口。

    - artifact_type 必须落在枚举内（ES8-RET-0001）；
    - audit_logs 永不触碰：直接抛 BizError("ES8-RET-0002")——
      路由创建/更新调用本函数，purge 循环对脏数据也走本函数兜底。
    """
    if artifact_type not in RetentionPolicy.ARTIFACT_TYPES:
        raise BizError("ES8-RET-0001", f"未知的数据保留类型：{artifact_type}")
    if artifact_type == RetentionPolicy.ARTIFACT_AUDIT_LOGS:
        raise BizError(
            RET_AUDIT_LOGS_FORBIDDEN,
            "审计日志受合规保护，任何保留策略均不可清理 audit_logs",
        )
    if purge_action is not None and purge_action not in RetentionPolicy.PURGE_ACTIONS:
        raise BizError("ES8-RET-0003", f"未知的清理动作：{purge_action}")


def _purge_one_policy(db: Session, policy: RetentionPolicy, now: datetime) -> dict:
    """单策略一轮清理：≤BATCH_LIMIT 行，返回 {"affected": n, "action": ...}。

    delete：物理删除；archive_ref：目标表有 deleted_at 则软删标记归档
    （写 deleted_at=now），无 deleted_at 的表（traces/recordings）等价于
    delete（方案 §13：archive_ref 对无软删列的表退化为删除，语义在 DDL
    COMMENT 与本注释双向写明）。
    """
    spec = ARTIFACT_TABLES.get(policy.artifact_type)
    if spec is None:  # 含 audit_logs 脏数据：硬拒（正常路径已在 router 拦截）
        validate_policy(policy.artifact_type)
        return {"affected": 0, "action": "skipped"}
    model, date_attr, supports_archive = spec
    date_col = getattr(model, date_attr)
    cutoff = now - timedelta(days=policy.days)
    soft = supports_archive and policy.purge_action == RetentionPolicy.PURGE_ARCHIVE_REF

    # 分批：取主键 → IN 删除/软删（独立小事务，防长事务锁表）
    ids = [
        row[0]
        for row in db.query(model.id)
        .filter(model.tenant_id == policy.tenant_id, date_col < cutoff)
        .order_by(model.id)
        .limit(BATCH_LIMIT)
        .all()
    ]
    if not ids:
        return {"affected": 0, "action": "soft" if soft else "hard"}
    if soft:
        affected = (
            db.query(model)
            .filter(model.id.in_(ids), model.deleted_at.is_(None))
            .update({model.deleted_at: now}, synchronize_session=False)
        )
    else:
        affected = db.query(model).filter(model.id.in_(ids)).delete(
            synchronize_session=False
        )
    db.commit()
    return {"affected": affected, "action": "soft" if soft else "hard"}


def run_retention_purge(db: Session, *, now: datetime | None = None) -> dict:
    """日清理入口：遍历全部策略执行一轮分批清理（scheduler 与测试共用）。

    返回汇总 {"policies": 处理策略数, "deleted": 总影响行数, "details": [...]}。
    每有实际删除即写一条审计；单策略异常回滚后跳过，不中断其余策略。
    """
    now = now or datetime.now(timezone.utc)
    policies = db.query(RetentionPolicy).order_by(RetentionPolicy.id).all()
    total = 0
    details: list[dict] = []
    for p in policies:
        try:
            result = _purge_one_policy(db, p, now)
        except BizError:
            # audit_logs 脏策略：记审计拒绝留痕后跳过
            db.rollback()
            logger.warning("retention 策略 %s 类型 %s 被硬拒（audit_logs 永不触碰）",
                           p.id, p.artifact_type)
            write_audit(
                db, user_id=None, username="system", tenant_id=p.tenant_id,
                action="retention.policy.rejected", module="retention",
                result="FAILED",
                error_msg=f"{RET_AUDIT_LOGS_FORBIDDEN}: artifact_type={p.artifact_type} 永不执行",
                detail=f"policy_id={p.id}",
            )
            continue
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("retention 策略 %s 执行异常（跳过该策略）", p.id)
            continue
        if result["affected"]:
            write_audit(
                db, user_id=None, username="system", tenant_id=p.tenant_id,
                action="retention.purge", module="retention",
                detail=(
                    f"policy_id={p.id} artifact_type={p.artifact_type} "
                    f"days={p.days} mode={result['action']} affected={result['affected']}"
                ),
            )
            total += result["affected"]
            details.append({
                "policy_id": p.id, "artifact_type": p.artifact_type,
                "affected": result["affected"], "mode": result["action"],
            })
    return {"policies": len(policies), "deleted": total, "details": details}


def _anonymize_one_tenant(db: Session, tenant_id: int, now: datetime) -> int:
    """单租户一轮匿名化：每表 ≤BATCH_LIMIT 行内容列覆盖，返回影响行数。

    username 是 NOT NULL + unique：置 'anon_u{id}_{ts}'（截 64，
    id 保唯一，重跑也不冲突）；租户 name 同理带 id 后缀。
    行保留（墓碑），审计可计数。
    """
    affected = 0
    ts = now.strftime("%Y%m%d%H%M%S")
    for model, cols in ANON_SPECS:
        # Tenant 主行没有 tenant_id 列（主键 id 即租户 id），作用域列单独选择
        scope_col = model.id if model is Tenant else model.tenant_id
        ids = [
            row[0]
            for row in db.query(model.id)
            .filter(scope_col == tenant_id)
            .order_by(model.id)
            .limit(BATCH_LIMIT)
            .all()
        ]
        if not ids:
            continue
        values = dict(cols)
        if model is SystemUser:
            # unique NOT NULL 列单独构造：防批量重跑时 username 唯一键冲突
            values["username"] = None  # 占位标记，下面按行覆写
            rows = db.query(model).filter(model.id.in_(ids)).all()
            for u in rows:
                u.username = f"anon_u{u.id}_{ts}"[:64]
                for k, v in cols.items():
                    setattr(u, k, v)
            affected += len(rows)
        elif model is Tenant:
            t = db.query(model).filter(model.id == tenant_id).first()
            if t is not None:
                t.name = f"ANONYMIZED-{t.id}"[:128]
                for k, v in cols.items():
                    setattr(t, k, v)
                affected += 1
        else:
            affected += (
                db.query(model)
                .filter(model.id.in_(ids))
                .update(values, synchronize_session=False)
            )
    db.commit()
    return affected


def run_anonymization(db: Session, *, now: datetime | None = None) -> dict:
    """注销到期匿名化入口（saas 日任务与测试共用，scheduler 侧自门控形态）。

    条件：status=CANCELED 且 anonymize_after 非空且已到期。
    完成一批后把该订阅 anonymize_after 置回 None 防止重复跑
    （墓碑行本身即"已匿名化"的持久留痕，无需新增状态列）。
    """
    now = now or datetime.now(timezone.utc)
    subs = (
        db.query(Subscription)
        .filter(
            Subscription.status == Subscription.STATUS_CANCELED,
            Subscription.anonymize_after.isnot(None),
            Subscription.anonymize_after <= now,
        )
        .order_by(Subscription.id)
        .limit(50)  # 每轮最多 50 个到期租户，防单日积压时超长事务
        .all()
    )
    done = 0
    total = 0
    for s in subs:
        try:
            n = _anonymize_one_tenant(db, s.tenant_id, now)
            s.anonymize_after = None  # 完成标记（置 NULL 防重跑）
            db.commit()
            write_audit(
                db, user_id=None, username="system", tenant_id=s.tenant_id,
                action="billing.subscription_anonymized", module="billing",
                detail=f"subscription_id={s.id} 内容列匿名化完成（分批上限 {BATCH_LIMIT}/表），affected={n}",
            )
            done += 1
            total += n
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("租户 %s 注销匿名化异常（下轮重试）", s.tenant_id)
    return {"due": len(subs), "anonymized": done, "affected": total}
