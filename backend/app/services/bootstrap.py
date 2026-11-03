# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""引导管理员口令治理（优化9 ES9-P-04）。

唯一实现点：lifespan、scripts、Dockerfile ENTRYPOINT 钩子统一调用
``ensure_bootstrap_admin``，杜绝各处复制口令生成逻辑。

安全约束：
- 一次性口令只经返回值交给调用方 print() 到 stdout 一次，不进 logger；
- 新建/引导账号一律置 must_change_pwd=True，首登半态令牌强制改密
 （pwd_half_session_middleware 已有拦截闭环）。
"""

from __future__ import annotations

import secrets
import string

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Role, SystemUser, UserRole
from ..security import hash_password
from ..utils.no import gen_no

# 强随机口令字符集（大小写+数字+符号，剔除易混淆 I/l/1/O/0）
_ALPHABET = (
    string.ascii_letters.translate(str.maketrans("", "", "Il1Oo0"))
    + string.digits[2:]
    + "!@#$%^&*-_=+"
)


def generate_strong_password(length: int = 16) -> str:
    """密码学安全随机口令（保证含大写/小写/数字/符号四类）。"""
    while True:
        pwd = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if (
            any(c.isupper() for c in pwd)
            and any(c.islower() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in "!@#$%^&*-_=+" for c in pwd)
        ):
            return pwd


def ensure_bootstrap_admin(db: Session) -> tuple[str, bool]:
    """幂等引导 admin 账号，返回 (一次性口令, 是否新建)。

    - admin（未软删）已存在 → ("", False)，不重置既有口令；
    - 不存在 → 口令取 settings.INIT_ADMIN_PASSWORD（运维显式配置），
      留空则运行时生成 16 位强随机口令；哈希落库，明文仅经返回值
      交调用方打印一次。
    """
    existing = (
        db.query(SystemUser)
        .filter(SystemUser.username == "admin", SystemUser.deleted_at.is_(None))
        .first()
    )
    if existing is not None:
        return ("", False)

    password = settings.INIT_ADMIN_PASSWORD.strip() or generate_strong_password()
    user = SystemUser(
        user_no=gen_no("U"),
        username="admin",
        display_name="系统管理员",
        password_hash=hash_password(password),
        status="ACTIVE",
        must_change_pwd=True,
        tenant_id=1,
    )
    db.add(user)
    db.flush()
    role = (
        db.query(Role)
        .filter(Role.role_code == "SUPER_ADMIN", Role.deleted_at.is_(None))
        .first()
    )
    if role is not None:
        db.add(UserRole(user_id=user.id, role_id=role.id, tenant_id=1))
    db.commit()
    return (password, True)
