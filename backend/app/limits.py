# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""社区版配额后端强制（版本隔离改造 B5，方案 §2-B5）。

设计（与方案逐字对齐）：
- community 全 kind 生效；saas / enterprise 仅题库两 kind（question_bank_total、
  question_total）按商业档位限额拦截（优化9测试方案 §9 MX-09：专业
  10库/5000题、企业不限、saas 订阅 ACTIVE=企业），其余 kind 直通
  （任务/性能类配额由 BillingQuota 计费体系承担，不走本文件）。
- kind 未实现直接 raise（开发期自检，杜绝"注入了但没实现"的静默失效）。
- 按日计数（case_gen_per_day）走 community_usage_daily 表，
  INSERT ... ON CONFLICT DO UPDATE 单语句原子累加（§3.1）。
- 累计类（projects_total、cases_total）实时 SELECT COUNT(*) 查业务表，不进计数表。
- 布尔类（self_register、local_llm、scheduler）开关型：值 False 即拒绝。

错误码（§6 T5/T13-T17 断言口径）：
- ES-LIMIT-0001 用量/条数超限
- ES-LIMIT-0002 注册关闭
- ES-LIMIT-0003 本地模型关闭
- ES-LIMIT-0004 附件超限
- ES-LIMIT-0005 定时/批量关闭
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .deps import AuthContext, authenticate_request
from .errors import BizError
from .models import BillingQuota, CommunityUsageDaily, Project, Question, QuestionBank, TestCase

# 社区版配额上限（方案 §2-B5 逐字）
COMMUNITY_LIMITS: dict[str, Any] = {
    "case_gen_per_call": 3,      # 上位方案 §2.4：单次 AI 生成 ≤3 条
    "case_gen_per_day": 10,      # 每日 10 次（查 community_usage_daily，§3.1）
    "cases_per_task": 100,
    "targets_per_task": 1,
    "projects_total": 3,
    "cases_total": 300,
    "question_total": 200,       # ES9-P-02/§1.4：题库题目总量（question 表）
    "question_bank_total": 1,    # ES9-P-02/§1.4：题库数量（question_bank 表）
    "perf_concurrency": 10, "perf_duration_s": 60,
    "upload_size_mb": 50,        # 上位方案 §2.4 附件上限
    "self_register": False,      # 上位方案 §2.4 单用户体系
    "local_llm": False,          # 上位方案 §2.4 本地私有模型接入关闭
    "scheduler": False,          # B7 批量/定时回归关闭
}

# 超限拒绝文案（kind → (code, message)），0001 为通用用量文案
_KIND_DENY: dict[str, tuple[str, str]] = {
    "self_register": ("ES-LIMIT-0002", "社区版为单用户系统，多用户协作在商业版开放"),
    "local_llm": ("ES-LIMIT-0003", "社区版不开放本地私有模型接入，请在商业版启用"),
    "scheduler": ("ES-LIMIT-0005", "定时/批量回归为商业版能力，社区版请使用单任务执行入口"),
}

# ES9-P-02（§2.2.3）：kind → 升级建议档位（单一事实源，前端不重复维护；
# 口径引用 plans.py §1.4：专业档解锁题库多库/成本/UAT 等，企业档解锁多租户）
SUGGEST_PLAN: dict[str, str] = {
    "case_gen_per_call": "professional",
    "case_gen_per_day": "professional",
    "cases_per_task": "professional",
    "targets_per_task": "professional",
    "projects_total": "professional",
    "cases_total": "professional",
    "question_total": "professional",
    "question_bank_total": "professional",
    "perf_concurrency": "professional",
    "perf_duration_s": "professional",
    "upload_size_mb": "professional",
    "self_register": "professional",
    "local_llm": "professional",
    "scheduler": "professional",
    # 企业专属（预留：multi_tenant / orgs / platform 类拒绝口径）
    "tenants": "enterprise",
    "orgs": "enterprise",
    "platform": "enterprise",
    "multi_tenant": "enterprise",
}

# 累计型 kind → 计量对象中文名/单位（结构化 detail 渲染用）
_KIND_UNIT: dict[str, str] = {
    "projects_total": "个",
    "cases_total": "条",
    "question_total": "题",
    "question_bank_total": "个",
}


def _over(
    code: str,
    message: str,
    *,
    kind: str | None = None,
    limit: Any = None,
    used: Any = None,
    unit: str | None = None,
) -> BizError:
    """ES9-P-02（§2.2.1）：超限拒绝携带结构化 detail。

    BizError 不支持 detail 形参，构造后挂 .detail 属性（HTTP 403 +
    ``{"code","message","detail":{kind,limit,used,unit,suggest_plan}}``，
    信封渲染由 eval_error_handler 完成；保持 BizError 类型兼容存量测试）。
    """
    detail: dict[str, Any] | None = None
    if kind is not None:
        detail = {"kind": kind}
        if limit is not None:
            detail["limit"] = limit
        if used is not None:
            detail["used"] = used
        detail["unit"] = unit or _KIND_UNIT.get(kind, "次")
        detail["suggest_plan"] = SUGGEST_PLAN.get(kind, "professional")
    exc = BizError(code, message, http_status=403)
    exc.detail = detail  # eval_error_handler 透出 {"code","message","detail"}
    return exc


def _count_today(db: Session, tenant_id: int, user_id: int, kind: str) -> int:
    """当日已用量（服务器本地日）；无记录返回 0。"""
    row = (
        db.query(CommunityUsageDaily.cnt)
        .filter(
            CommunityUsageDaily.tenant_id == tenant_id,
            CommunityUsageDaily.user_id == user_id,
            CommunityUsageDaily.kind == kind,
            CommunityUsageDaily.usage_date == datetime.now(timezone.utc).astimezone().date(),
        )
        .first()
    )
    return int(row[0]) if row else 0


def bump_daily(db: Session, tenant_id: int, user_id: int, kind: str, n: int = 1) -> None:
    """按日计数 +n（仅 community 写；INSERT..ON CONFLICT 单语句原子，§3.1）。"""
    if settings.EDITION != "community":
        return
    db.execute(
        text(
            "INSERT INTO community_usage_daily "
            "(tenant_id, user_id, kind, usage_date, cnt, created_at, updated_at) "
            "VALUES (:t, :u, :k, CURRENT_DATE, :n, now(), now()) "
            "ON CONFLICT (tenant_id, user_id, kind, usage_date) "
            "DO UPDATE SET cnt = community_usage_daily.cnt + :n, updated_at = now()"
        ),
        {"t": tenant_id, "u": user_id, "k": kind, "n": n},
    )
    db.commit()


def _business_total(db: Session, kind: str, auth: AuthContext) -> int:
    """累计类实时 COUNT(*)（不带软删行）。"""
    if kind == "projects_total":
        model = Project
    elif kind == "cases_total":
        model = TestCase
    elif kind == "question_total":
        model = Question
    elif kind == "question_bank_total":
        model = QuestionBank
    else:
        raise RuntimeError(f"limits.py 未知累计 kind: {kind!r}")
    q = db.query(func.count(model.id)).filter(model.deleted_at.is_(None))
    if not auth.is_super_admin:
        q = q.filter(model.tenant_id == auth.tenant_id)
    return int(q.scalar() or 0)


# ---------------------------------------------------------------------------
# 核心守卫：在端点体内调用（带业务参数；EDITION != community 直通）
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# BUG-018（优化9测试方案 §9 L422）：商业形态题库档位限额
#   专业 10库/5000题、企业不限（None）、saas 订阅 ACTIVE/GRACE=企业不限；
#   档位判定镜像 scripts/issue_license.py 签发口径（enterprise features=["*"]、
#   professional=PROFESSIONAL_SET 子集）与 plans.py 常量。
#   limits.py 属 OSS 共享域：commercial 包依赖必须函数内延迟导入
#   （community 构建物理缺席时顶层 import 即 ImportError）。
# ---------------------------------------------------------------------------

_BANK_KIND_KEY = {"question_bank_total": "banks", "question_total": "questions"}


def _commercial_bank_limit(db: Session, auth: AuthContext, kind: str) -> int | None:
    """saas / enterprise 形态下题库 kind 的当前档位限额（None=不限）。

    - enterprise：License 有效但未细分档位（_licensed_features=None）或含
      "*" → 企业不限；专业子集 → PRO 档位；
    - saas：BillingQuota 订阅相位 ACTIVE/GRACE → 不限（=enterprise）；
      缺行 / PAST_DUE / CANCELED → PRO 档位（MX-13 口径：共享域缺订阅行
      不得判死，回退专业限额即可）。
    """
    from .plans import ENT_PLAN_BANK_LIMITS, PRO_PLAN_BANK_LIMITS

    key = _BANK_KIND_KEY[kind]
    if settings.EDITION == "enterprise":
        from .enterprise import features

        licensed = features._licensed_features
        if licensed is None or "*" in licensed:
            return ENT_PLAN_BANK_LIMITS[key]
        return PRO_PLAN_BANK_LIMITS[key]
    # saas：订阅相位 ACTIVE/GRACE → 企业不限；其余 → 专业档位
    from .commercial.services.billing_cycle import (
        SUB_ACTIVE, SUB_GRACE, resolve_sub_status)

    q = (
        db.query(BillingQuota)
        .filter(BillingQuota.tenant_id == auth.tenant_id)
        .first()
    )
    if q is not None and resolve_sub_status(q) in (SUB_ACTIVE, SUB_GRACE):
        return ENT_PLAN_BANK_LIMITS[key]
    return PRO_PLAN_BANK_LIMITS[key]


def check_limit(
    kind: str,
    db: Session,
    auth: AuthContext,
    *,
    request: Request | None = None,
    n: int = 1,
    config: dict | None = None,
    scenario_targets: int | None = None,
) -> None:
    """按 kind 校验配额，超限 raise EvalError(403, detail)。

    community：全 kind 按 COMMUNITY_LIMITS 拦截；
    saas / enterprise：仅题库两 kind 按商业档位限额拦截（BUG-018，
    方案 §9 MX-09），其余 kind 直通（任务/性能类配额走 BillingQuota）。

    n：本次增量（bulk 导入条数、生成条数等，默认 1）；
    config：perf 类校验用的任务 config dict；
    scenario_targets：场景所含目标数。
    """
    if settings.EDITION != "community":
        # BUG-018：商业形态题库档位分支（方案 §9 L422：专业 10库/5000题、
        # 企业不限、saas 订阅态=企业）；其余 kind 维持直通行。
        if kind in _BANK_KIND_KEY:
            limit = _commercial_bank_limit(db, auth, kind)
            if limit is None:
                return
            used = _business_total(db, kind, auth)
            if used + n > int(limit):
                obj = {"question_total": "题目", "question_bank_total": "题库"}[kind]
                raise _over(
                    "ES-LIMIT-0001",
                    f"当前档位{obj}总量上限 {limit}，已无法新增。升级档位解除限制",
                    kind=kind, limit=int(limit), used=used,
                )
        return
    if kind not in COMMUNITY_LIMITS:
        raise RuntimeError(f"limits.enforce 未知 kind: {kind!r}（开发期自检）")
    limit = COMMUNITY_LIMITS[kind]

    # ---- 开关型 ----
    if kind in ("self_register", "local_llm", "scheduler"):
        if limit is False:
            code, msg = _KIND_DENY[kind]
            raise _over(code, msg, kind=kind, limit=0, used=1, unit="次")
        return

    # ---- 按日计数型（case_gen_per_day：校验 + 通过后即累加） ----
    if kind == "case_gen_per_day":
        used = _count_today(db, auth.tenant_id, auth.user_id, "case_gen")
        if used + n > int(limit):
            raise _over(
                "ES-LIMIT-0001",
                f"社区版每日 AI 生成上限 {limit} 次，请明日再试或升级商业版",
                kind=kind, limit=int(limit), used=used, unit="次",
            )
        bump_daily(db, auth.tenant_id, auth.user_id, "case_gen", n)
        return

    # ---- 单次条数型 ----
    if kind == "case_gen_per_call":
        if n > int(limit):
            raise _over(
                "ES-LIMIT-0001",
                f"社区版单次最多生成 {limit} 条用例。升级商业版解锁批量生成",
                kind=kind, limit=int(limit), used=n, unit="条",
            )
        return

    # ---- 累计型（现存量 + 本次增量） ----
    if kind in ("projects_total", "cases_total", "question_total", "question_bank_total"):
        used = _business_total(db, kind, auth)
        if used + n > int(limit):
            obj = {
                "projects_total": "项目",
                "cases_total": "用例",
                "question_total": "题目",
                "question_bank_total": "题库",
            }[kind]
            raise _over(
                "ES-LIMIT-0001",
                f"社区版{obj}总量上限 {limit}，当前已无法新增。升级商业版解除限制",
                kind=kind, limit=int(limit), used=used,
            )
        return

    # ---- 任务规模型 ----
    if kind == "cases_per_task":
        if n > int(limit):
            raise _over(
                "ES-LIMIT-0001",
                f"社区版单任务用例数上限 {limit} 条（本次 {n} 条）。升级商业版解除限制",
                kind=kind, limit=int(limit), used=n, unit="条",
            )
        return
    if kind == "targets_per_task":
        m = n if scenario_targets is None else scenario_targets
        if m > int(limit):
            raise _over(
                "ES-LIMIT-0001",
                f"社区版单任务被测系统上限 {limit} 个（本次 {m} 个）。升级商业版解除限制",
                kind=kind, limit=int(limit), used=m, unit="个",
            )
        return

    # ---- 性能压测型（从 config 提取并发/时长） ----
    if kind in ("perf_concurrency", "perf_duration_s"):
        cfg = config or {}
        if kind == "perf_concurrency":
            conc_raw = cfg.get("concurrency") or cfg.get("threads") or 0
            vals = conc_raw if isinstance(conc_raw, list) else [conc_raw]
            peak = max([int(v) for v in vals if str(v).isdigit()] or [0])
            if peak > int(limit):
                raise _over(
                    "ES-LIMIT-0001",
                    f"社区版压测并发上限 {limit}（本次 {peak}）。升级商业版解除限制",
                    kind=kind, limit=int(limit), used=peak, unit="并发",
                )
        else:
            dur = int(cfg.get("duration") or cfg.get("duration_sec") or cfg.get("max_duration_sec") or 0)
            if dur > int(limit):
                raise _over(
                    "ES-LIMIT-0001",
                    f"社区版压测时长上限 {limit} 秒（本次 {dur} 秒）。升级商业版解除限制",
                    kind=kind, limit=int(limit), used=dur, unit="秒",
                )
        return

    # ---- 附件型（Content-Length 快速拒绝；落盘前二次校验见 check_upload_bytes） ----
    if kind == "upload_size_mb":
        if request is not None:
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > int(limit) * 1024 * 1024:
                raise _over(
                    "ES-LIMIT-0004",
                    f"社区版附件上限 {limit}MB（本次 {int(int(cl) / 1024 / 1024)}MB）。升级商业版解除限制",
                    kind=kind, limit=int(limit), used=int(int(cl) / 1024 / 1024), unit="MB",
                )
        return

    raise RuntimeError(f"limits.enforce kind {kind!r} 未实现（开发期自检）")


def check_upload_bytes(n_bytes: int) -> None:
    """落盘/解析前对实际读取字节数的二次校验（Content-Length 可缺失或造假）。"""
    if settings.EDITION != "community":
        return
    limit = int(COMMUNITY_LIMITS["upload_size_mb"])
    if n_bytes > limit * 1024 * 1024:
        raise _over(
            "ES-LIMIT-0004",
            f"社区版附件上限 {limit}MB（本次约 {n_bytes // 1024 // 1024}MB）。升级商业版解除限制",
            kind="upload_size_mb", limit=limit, used=n_bytes // 1024 // 1024, unit="MB",
        )


# ---------------------------------------------------------------------------
# 题库配额入口（ES9-P-02/§1.4：question 总量与 question_bank 数量）
# ---------------------------------------------------------------------------

def check_question_total(
    db: Session, auth: AuthContext, *, n: int = 1
) -> None:
    """题目总量校验（社区 200 题，超限 403 + 结构化 detail）。"""
    check_limit("question_total", db, auth, n=n)


def check_question_bank_total(
    db: Session, auth: AuthContext, *, n: int = 1
) -> None:
    """题库数量校验（社区 1 库，超限 403 + 结构化 detail）。"""
    check_limit("question_bank_total", db, auth, n=n)


# ---------------------------------------------------------------------------
# 路由依赖工厂（无业务参数的开关/入口型注入点）
# ---------------------------------------------------------------------------

def enforce_limit(kind: str):
    """依赖工厂：``Depends(enforce_limit("scheduler"))``。

    仅社区生效；perf 双限、cases/bulk 条数累加、case_gen 双限等需要业务参数
    的注入点在端点体内直接调用 :func:`check_limit`。
    """

    def _dep(
        db: Session = Depends(get_db),
        auth: AuthContext = Depends(authenticate_request),
    ) -> None:
        check_limit(kind, db, auth)

    return _dep
