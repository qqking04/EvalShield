# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""F-01 修复：证据/附件静态目录的鉴权访问（替代裸 StaticFiles mount）。

两种放行方式（任一即可）：
1. ``Authorization: Bearer <JWT>`` 请求头 —— fetch/XHR 通道（http 拦截器自动注入）；
2. ``?es_exp=<unix秒>&es_sig=<hmac>&es_ten=<tenant>`` 短时效签名查询参数 ——
   浏览器原生 GET（``<img>`` / ``<a>`` 无法携带请求头），签名由后端 URL 生产点附加：
   - report_ext._evidence_url（报告 sections 截图）
   - defects 列表/详情响应改写（缺陷附件）

F-01 租户绑定（BOLA 修复）：
- 签名通道：HMAC 消息包含租户 id，签名 URL 仅对本租户有效，跨租户伪造 es_ten
  会导致验签失败；
- Bearer 通道：文件名嵌入 ``t<tenant>_`` 前缀，校验 JWT payload["ten"] 与
  前缀一致；无前缀文件一律拒绝（存量已由 m_003 租户回刷脚本统一前缀化，
  见 docs/security/tenant-backfill-work-order.md）。

密钥复用 settings.SECRET_KEY（HS256 同源），时效默认 15 分钟。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from urllib.parse import parse_qs

from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from .config import settings
from .security import decode_token

SIG_TTL_SECONDS = 900

# URL 前缀 → 签名 kind（与 mount 点一一对应）
_MOUNT_KINDS = {"/api/attachments/": "att", "/api/evidence/": "evi"}

# F-01：文件名嵌入租户前缀 ``t<tenant>_``，Bearer 通道据此做租户校验；
# 无前缀（含回刷遗漏）一律拒绝——存量由 m_003 回刷，增量由上传处保证前缀。
_TENANT_PREFIX_RE = re.compile(r"^t(\d+)_")


def _sig(kind: str, name: str, exp: int, tenant_id: int) -> str:
    msg = f"{kind}:{name}:{exp}:{tenant_id}".encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def sign_static_url(path: str, tenant_id: int, ttl: int = SIG_TTL_SECONDS) -> str:
    """为 /api/attachments/ 或 /api/evidence/ 相对 URL 追加短时效签名（绑定租户）。

    非目标前缀或已含签名的 URL 原样返回（幂等，防双重签名）。
    """
    if not path or "es_sig=" in path:
        return path
    for prefix, kind in _MOUNT_KINDS.items():
        if path.startswith(prefix):
            name = path[len(prefix):].split("?")[0]
            exp = int(time.time()) + ttl
            return f"{path}?es_exp={exp}&es_ten={tenant_id}&es_sig={_sig(kind, name, exp, tenant_id)}"
    return path


def _bearer_allowed(bearer: str, name: str) -> bool:
    """Bearer 通道：JWT 有效 + 文件名嵌租户前缀且 payload["ten"] 与前缀一致。

    无前缀文件名一律拒绝（M-003 回刷后不再存在合法无前缀资源）。
    """
    if not bearer.startswith("Bearer "):
        return False
    payload = decode_token(bearer[7:])
    if not payload or payload.get("typ") != "access":
        return False
    m = _TENANT_PREFIX_RE.match(name)
    if m is None:
        return False  # 无前缀 = 无租户归属，拒绝
    try:
        file_tenant = int(m.group(1))
    except ValueError:
        return False
    token_tenant = payload.get("ten")
    # SUPER_ADMIN 令牌同租户体系下无独立标记，按 ten 相等校验；跨租户由业务层
    # ensure_data_scope 负责，这里保持与签名通道一致的严格租户口径。
    return isinstance(token_tenant, int) and token_tenant == file_tenant


def _verify_request(kind: str, bearer: str, route_path: str, query: str) -> bool:
    """校验单个静态文件请求：Bearer JWT（含租户前缀校验）或合法未过期租户签名。

    route_path 为 mount 剥离 root_path 后的剩余路径（形如 ``/filename``），
    与 ``sign_static_url`` 生成侧的 name（纯文件名）保持一致。
    """
    name = route_path.lstrip("/")
    if _bearer_allowed(bearer, name):
        return True
    params = parse_qs(query)
    exp_raw = (params.get("es_exp") or [""])[0]
    sig = (params.get("es_sig") or [""])[0]
    ten_raw = (params.get("es_ten") or [""])[0]
    if not exp_raw or not sig or not ten_raw:
        return False
    try:
        exp = int(exp_raw)
        tenant_id = int(ten_raw)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(sig, _sig(kind, name, exp, tenant_id))


class SignedStaticFiles(StaticFiles):
    """StaticFiles + 鉴权壳：未认证 / 签名缺失、失效一律 401。"""

    def __init__(self, *, kind: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._kind = kind

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await super().__call__(scope, receive, send)
            return
        bearer = ""
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                bearer = value.decode("latin-1")
                break
        path = scope.get("path", "")
        # mount 子应用中 scope["path"] 仍含挂载前缀，剥离后的剩余路径在 root_path 之后
        root_path = scope.get("root_path", "")
        route_path = path[len(root_path):] if path.startswith(root_path) else path
        query = scope.get("query_string", b"").decode("latin-1")
        if _verify_request(self._kind, bearer, route_path, query):
            await super().__call__(scope, receive, send)
            return
        response = JSONResponse(
            {"code": "ES-AUTH-0001", "data": None, "message": "未认证或链接签名无效/已过期"},
            status_code=401,
        )
        await response(scope, receive, send)
