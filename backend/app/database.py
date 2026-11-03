# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""数据库会话与建模基座。

约定（硬性，对应需求）：
- UTF-8 连接（client_encoding=utf8），保证中文无乱码。
- 全库不使用数据库外键（模型层不声明 ForeignKey 约束，仅保留逻辑关联列）。
- 主键均为自增。业务上对外展示一律使用「编号」字段（xx_no / xx_code）。
"""

from __future__ import annotations

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

# naming_convention：约束命名规范（配合无外键策略，仅通用 CHECK/唯一约束）
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING_CONVENTION)

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


class Base(DeclarativeBase):
    metadata = metadata

    # ES8-BUG-006：TestTask/TestCase 等模型名以 Test 开头，被导入测试模块时
    # 触发 pytest 误采集告警。dunder 属性 SQLAlchemy 不映射，pytest 全树尊重
    # __test__ = False（含继承），一处关闭全部模型类的采集。
    __test__ = False


def get_db():
    """FastAPI 依赖：请求级数据库会话。"""
    db = SessionLocal()
    try:
        db.connection()  # 显式检出连接（pool_pre_ping 探活）：DB 不可用立即抛错 → 统一 500（EM-01）
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表（幂等）。仅在首次启动或数据字典迁移时调用。"""
    # 延迟导入，确保模型全部注册进 metadata
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
