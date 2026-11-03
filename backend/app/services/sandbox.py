# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""SandboxClient：backend 与沙箱网关的通信客户端。"""

from __future__ import annotations

import json
import logging
import socket
import urllib.request
from typing import Any

from ..config import settings
from ..errors import EvalError
from ..utils.no import gen_no

logger = logging.getLogger(__name__)


class SandboxClient:
    """负责向 evalshield-sandbox 网关发送执行请求并轮询结果。"""

    def __init__(
        self,
        host: str = "",
        port: int = 0,
        use_unix_socket: bool = False,
        unix_socket_path: str = "",
        request_timeout: int = 0,
    ) -> None:
        self.host = host or settings.SANDBOX_HOST
        self.port = port or settings.SANDBOX_PORT
        self.use_unix_socket = use_unix_socket or settings.SANDBOX_USE_UNIX_SOCKET
        self.unix_socket_path = unix_socket_path or settings.SANDBOX_UNIX_SOCKET
        self.request_timeout = request_timeout or settings.SANDBOX_REQUEST_TIMEOUT
        self._base_url = self._build_base_url()

    def _build_base_url(self) -> str:
        if self.use_unix_socket:
            # Unix Socket 通过原生 urllib 适配
            return f"http+unix://{self.unix_socket_path.replace('/', '%2F')}"
        return f"http://{self.host}:{self.port}"

    # ------------------------------------------------------------------
    # 内部 HTTP helpers（使用标准库，不引入额外依赖）
    # ------------------------------------------------------------------
    def _http_post(self, path: str, payload: dict) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        if self.use_unix_socket:
            # 原生 Unix Socket HTTP 请求
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.request_timeout)
            try:
                sock.connect(self.unix_socket_path)
                req_line = (
                    f"POST {path} HTTP/1.1\r\n"
                    f"Host: localhost\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(data)}\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode("utf-8")
                sock.sendall(req_line + data)
                response = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                # 简单解析：取第一个 { 开始到末尾
                body_start = response.find(b"{")
                if body_start == -1:
                    raise EvalError("ES-SANDBOX-5001", "沙箱网关返回无效响应", 502)
                return json.loads(response[body_start:].decode("utf-8"))
            finally:
                sock.close()
        else:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))

    def _http_get(self, path: str) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {"Accept": "application/json"}

        if self.use_unix_socket:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.request_timeout)
            try:
                sock.connect(self.unix_socket_path)
                req_line = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: localhost\r\n"
                    f"Accept: application/json\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode("utf-8")
                sock.sendall(req_line)
                response = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                body_start = response.find(b"{")
                if body_start == -1:
                    raise EvalError("ES-SANDBOX-5001", "沙箱网关返回无效响应", 502)
                return json.loads(response[body_start:].decode("utf-8"))
            finally:
                sock.close()
        else:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))

    # ------------------------------------------------------------------
    # 业务方法
    # ------------------------------------------------------------------
    def submit_execution(
        self,
        task_id: int,
        engine_code: str,
        config: dict | None = None,
        timeout_seconds: int = 0,
        artifacts_in: list[str] | None = None,
    ) -> dict[str, Any]:
        """提交执行请求，返回沙箱网关的响应（含 execution_no）。"""
        payload = {
            "task_id": task_id,
            "engine_code": engine_code,
            "config": config or {},
            "timeout_seconds": timeout_seconds or settings.SANDBOX_DEFAULT_TIMEOUT,
            "artifacts_in": artifacts_in or [],
        }
        try:
            resp = self._http_post("/sandbox/execute", payload)
        except Exception as exc:
            logger.error("sandbox submit failed: %s", exc)
            raise EvalError("ES-SANDBOX-5001", f"沙箱网关调用失败: {exc}", 502) from exc
        if resp.get("code") != 0:
            raise EvalError(
                str(resp.get("code", "ES-SANDBOX-5001")),
                resp.get("message", "沙箱错误"),
                400,
            )
        return resp["data"]

    def get_execution(self, execution_no: str) -> dict[str, Any]:
        """查询执行状态与结果。"""
        try:
            resp = self._http_get(f"/sandbox/execution/{execution_no}")
        except Exception as exc:
            logger.error("sandbox query failed: %s", exc)
            raise EvalError("ES-SANDBOX-5001", f"沙箱查询失败: {exc}", 502) from exc
        if resp.get("code") != 0:
            raise EvalError(
                str(resp.get("code", "ES-SANDBOX-5001")),
                resp.get("message", "沙箱错误"),
                400,
            )
        return resp["data"]

    def pool_status(self) -> dict[str, Any]:
        """查询 worker 池状态（ES9-P-03 pool 模式，网关静态 worker 池）。"""
        try:
            resp = self._http_get("/sandbox/pool/status")
        except Exception as exc:
            logger.error("sandbox pool status failed: %s", exc)
            raise EvalError(
                "ES-SANDBOX-5001", f"沙箱 worker 池状态查询失败: {exc}", 502
            ) from exc
        if resp.get("code") != 0:
            raise EvalError(
                str(resp.get("code", "ES-SANDBOX-5001")),
                resp.get("message", "沙箱错误"),
                400,
            )
        return resp["data"] or {}


# 全局单例（可按需替换为连接池）
sandbox_client = SandboxClient()
