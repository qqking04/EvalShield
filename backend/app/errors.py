# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""错误码与统一响应封装（附录 A-1）。

响应约定（见开发说明书 1.6）：
- 成功：{"code": 0, "data": ..., "message": "ok"}
- 失败：HTTP 状态码 + {"code": "ES-XXXX", "message": "人类可读说明", "detail": ...}
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class EvalError(HTTPException):
    """业务异常基类。"""

    def __init__(
        self, code: str, message: str, http_status: int = 400, detail: Any = None
    ):
        super().__init__(status_code=http_status, detail=detail)
        self.code = code
        self.message = message
        self.http_status = http_status


# 常见业务错误（与附录 A-1 对齐）
class AuthError(EvalError):
    def __init__(
        self,
        code: str = "ES-AUTH-0001",
        message: str = "未认证或凭证无效",
        http_status: int = 401,
    ):
        super().__init__(code, message, http_status)


class PermError(EvalError):
    def __init__(
        self,
        code: str = "ES-PERM-0001",
        message: str = "缺少功能权限",
        http_status: int = 403,
    ):
        super().__init__(code, message, http_status)


class DataScopeError(EvalError):
    def __init__(
        self,
        code: str = "ES-DATA-0001",
        message: str = "无权访问该资源",
        http_status: int = 403,
    ):
        super().__init__(code, message, http_status)


class NotFoundError(EvalError):
    def __init__(
        self,
        code: str = "ES-COMMON-0004",
        message: str = "资源不存在",
        http_status: int = 404,
    ):
        super().__init__(code, message, http_status)


class BizError(EvalError):
    def __init__(
        self,
        code: str = "ES-COMMON-0001",
        message: str = "业务处理失败",
        http_status: int = 400,
    ):
        super().__init__(code, message, http_status)


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    return {"code": 0, "data": data, "message": message}


def err(code: str, message: str, detail: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "detail": detail}


async def eval_error_handler(request: Request, exc: EvalError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content=err(exc.code, exc.message, exc.detail),
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # BUG-7：路径参数类型解析失败（如 GET /api/reports/compare 被
    # /api/reports/{report_id:int} 动态路由匹配后 "compare" 无法转 int）
    # 语义上是"路由不存在"，应返回 404 而非 422。
    # pydantic v2 底层 ValidationError.errors() 支持 include_context=False，但
    # FastAPI RequestValidationError.errors() 会重新注入 url/ctx（ctx 携带原始
    # 异常对象，JSONResponse 序列化直接 TypeError → 500），故按白名单剥离。
    errors = [
        {k: v for k, v in e.items() if k in ("loc", "msg", "type")}
        for e in exc.errors()
    ]
    if any(
        e.get("type") == "int_parsing" and e.get("loc", ())[:1] == ("path",)
        for e in errors
    ):
        return JSONResponse(
            status_code=404,
            content=err("ES-COMMON-0004", "资源不存在", None),
        )
    return JSONResponse(
        status_code=422,
        content=err("ES-COMMON-0001", "参数校验失败", errors[:5]),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """BUG-005：未捕获异常统一兜底。

    - 服务端日志记完整 traceback（含 SQLAlchemy 原始 SQL），便于排查；
    - HTTP 响应仅返回通用错误码 + trace_id，绝不把异常文本（SQL/表名/参数）透出到前端。
    """
    import logging
    import traceback
    import uuid

    trace_id = uuid.uuid4().hex[:16]
    logging.getLogger("uvicorn.error").error(
        "Unhandled error trace_id=%s path=%s\n%s",
        trace_id,
        request.url.path,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={
            "code": "ES-COMMON-0000",
            "message": "服务器内部错误，请稍后重试或联系管理员",
            "detail": None,
            "trace_id": trace_id,
        },
    )

