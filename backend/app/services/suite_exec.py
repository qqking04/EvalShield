# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M4：套件执行抽取（原 routers/projects_ext.py::execute_suite 主体逻辑）。

路由手动执行与 monitor 定时触发共用本函数：
- 保留 check_limit("scheduler", ...) 商业限额检查（社区版拒绝批量执行）；
- 克隆套件内每个任务为一组新 TestTask（同 suite_id、同 created_at 视为一个批次）；
- 本函数只负责克隆落库并返回批次任务；是否真实执行（launch_task_async）由调用方决定：
  路由保持现状（只克隆），monitor 触发后逐个 launch。
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..deps import AuthContext
from ..errors import NotFoundError
from ..limits import check_limit
from ..models import TestSuite, TestSuiteItem, TestTask
from ..utils.no import gen_no


def _now() -> datetime:
    return datetime.now(timezone.utc)


def launch_suite(db: Session, suite_id: int, triggered_by: AuthContext) -> dict[str, Any]:
    """克隆套件条目为新任务批次；返回 {"created_task_ids": [...], "tasks": [...]}。

    triggered_by：触发身份（路由传请求 AuthContext；monitor 传合成的系统身份），
    租户隔离以其 tenant_id 为准。套件不存在/非本租户抛 NotFoundError。
    """
    # B7：手动批量执行归商业——社区版拒绝并提示单任务执行入口
    check_limit("scheduler", db, triggered_by)
    s = (
        db.query(TestSuite)
        .filter(
            TestSuite.id == suite_id,
            TestSuite.tenant_id == triggered_by.tenant_id,
            TestSuite.deleted_at.is_(None),
        )
        .first()
    )
    if s is None:
        raise NotFoundError(message="套件不存在")
    items = (
        db.query(TestSuiteItem)
        .filter(
            TestSuiteItem.suite_id == s.id,
            TestSuiteItem.tenant_id == triggered_by.tenant_id,
        )
        .order_by(TestSuiteItem.sort_order.asc())
        .all()
    )
    created: list[dict[str, Any]] = []
    batch_ts = _now()  # 批次统一时间戳：monitor 侧按 (suite_id, created_at) 归批
    for it in items:
        t = (
            db.query(TestTask)
            .filter(TestTask.id == it.task_id, TestTask.deleted_at.is_(None))
            .first()
        )
        if t is None:
            continue
        new_task = TestTask(
            task_no=gen_no("TK"),
            project_id=t.project_id,
            project_code=t.project_code,
            name=t.name,
            description=t.description,
            task_type=t.task_type,
            engines=list(t.engines or []),
            config=copy.deepcopy(t.config or {}),
            status="PENDING",
            trigger_mode="MANUAL",
            schedule_cron=None,
            progress=0,
            current_step=None,
            started_at=None,
            finished_at=None,
            duration_ms=None,
            summary=None,
            error_msg=None,
            suite_id=s.id,
            task_version=t.task_version,
            created_by=triggered_by.user_id,
            created_by_name=triggered_by.username,
            tenant_id=triggered_by.tenant_id,
            created_at=batch_ts,
            updated_at=batch_ts,
        )
        db.add(new_task)
        db.flush()
        created.append({"task_id": new_task.id, "task_no": new_task.task_no, "name": new_task.name})
    db.commit()
    # 更新套件最近运行时间
    s.last_run_at = _now()
    s.updated_at = _now()
    db.add(s)
    db.commit()
    return {"created_task_ids": [c["task_id"] for c in created], "tasks": created}
