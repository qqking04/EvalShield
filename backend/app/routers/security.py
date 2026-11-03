# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""安全能力路由：A06 组件漏洞版本表查看、编辑与热更新（v2.0 推荐方案 #1）。"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from ..deps import AuthContext, authenticate_request, require_permission
from ..engines.security_test import _VULN_DB_PATH, load_vuln_db, refresh_vuln_db
from ..errors import BizError

router = APIRouter()


@router.get("/vuln-db", response_model=dict)
async def get_vuln_db(auth: AuthContext = Depends(authenticate_request)):
    """查看当前生效的组件漏洞版本表（外置文件 + 元信息）。"""
    patterns, meta = load_vuln_db()
    return {"code": 0, "message": "ok", "data": {
        "path": _VULN_DB_PATH, **meta,
        "patterns": [{"pattern": p, "desc": d} for p, d in patterns],
    }}


@router.post("/refresh-vuln-db", response_model=dict)
async def post_refresh_vuln_db(
    auth: AuthContext = Depends(authenticate_request),
    _: AuthContext = Depends(require_permission("admin", "*")),
):
    """热更新：重新读取 backend/data/vuln_components.json 并替换引擎匹配表（管理员）。"""
    meta = refresh_vuln_db()
    return {"code": 0, "message": "ok", "data": meta}


@router.put("/vuln-db", response_model=dict)
async def put_vuln_db(
    body: dict,
    auth: AuthContext = Depends(authenticate_request),
    _: AuthContext = Depends(require_permission("admin", "*")),
):
    """编辑保存（管理员）：patterns 写回外置文件并热更引擎匹配表，无需重启后端。"""
    patterns = body.get("patterns")
    if not isinstance(patterns, list) or not patterns:
        raise BizError("ES-SEC-0001", "patterns 不能为空")
    cleaned: list[dict] = []
    for i, p in enumerate(patterns):
        pat = str((p or {}).get("pattern") or "").strip()
        desc = str((p or {}).get("desc") or "").strip()
        if not pat:
            raise BizError("ES-SEC-0002", f"第 {i + 1} 条缺少 pattern")
        try:
            re.compile(pat)
        except re.error as exc:
            raise BizError("ES-SEC-0003", f"第 {i + 1} 条正则非法：{exc}")
        cleaned.append({"pattern": pat[:200], "desc": desc[:200]})
    data = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "EvalShield 内置 EOL/高危组件版本表（可手动更新；正则匹配 Server / X-Powered-By 响应头，小写）",
        "patterns": cleaned,
    }
    os.makedirs(os.path.dirname(_VULN_DB_PATH), exist_ok=True)
    with open(_VULN_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    meta = refresh_vuln_db()
    return {"code": 0, "message": "ok", "data": meta}
