# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""TLS 传输层加密检测引擎（A2）。

对目标 HTTPS 端口建立 TLS 连接，检测：
- 协议版本（禁用 SSLv3/TLS1.0/1.1）
- 加密套件强度（弱算法 RC4/DES/3DES）
- 证书有效期与颁发者
"""

from __future__ import annotations

import logging
import socket
import ssl
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from ..config import settings
from .base import BaseEngine, EngineContext, EngineResult

logger = logging.getLogger("evalshield.engine.tls_check")

# 视为不安全的协议版本（收录 Python ssl 返回值与常见变体写法，BUG-13）
_INSECURE_PROTOCOLS = {"SSLv3", "TLSv1", "TLSv1.0", "TLSv1.1"}


def _normalize_protocol(version: str) -> str:
    """协议名归一化：去空格，'TLS 1.0'/'TLS1.0' 等变体统一为 TLSV1.0 写法判定。"""
    v = (version or "").replace(" ", "").upper()
    if v.startswith("TLS") and not v.startswith("TLSV"):
        v = "TLSV" + v[3:]
    return v


def _is_insecure_protocol(version: str) -> bool:
    v = _normalize_protocol(version)
    return v in {p.upper() for p in _INSECURE_PROTOCOLS}


# 视为弱的加密算法关键字
_WEAK_CIPHER_KEYS = ("RC4", "DES", "3DES", "NULL", "EXPORT", "MD5")


class TlsCheckEngine(BaseEngine):
    engine_code = "TLS_CHECK"
    engine_name = "传输层加密检测引擎"
    engine_type = "TRADITIONAL"
    category = "SECURITY"
    version = "1.0.0"
    description = "检测 HTTPS/TLS 配置：协议版本、加密套件强度、证书有效期。"
    fidelity = "rule"

    params_schema = [
        {"key": "base_url", "label": "被测系统地址（https://）", "type": "text", "required": True},
        {"key": "timeout_seconds", "label": "超时（秒）", "type": "number", "default": 10},
    ]

    def execute(self, ctx: EngineContext) -> EngineResult:
        base_url = (
            ctx.config.get("base_url")
            or ctx.config.get(f"config__{self.engine_code}__base_url")
            or ctx.extra.get("base_url")
            or settings.API_DEFAULT_BASE_URL
        )
        parsed = urlparse(base_url if "//" in base_url else f"https://{base_url}")
        host = parsed.hostname or ""
        port = parsed.port or 443
        timeout = float(ctx.config.get("timeout_seconds", 10))

        results: list[dict[str, Any]] = []
        if not host:
            return EngineResult(
                status="FAILED",
                summary={"total": 0, "passed": 0, "failed": 1, "pass_rate": 0.0},
                report_payload={"engine": self.engine_code, "results": []},
                error="E_TLS_NO_HOST: 无法从 base_url 解析主机名",
            )

        # 1) 默认上下文握手（校验证书链）
        tls_version = cipher = ""
        cert: dict[str, Any] = {}
        handshake_err = ""
        try:
            ctx_ssl = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=timeout) as sock:
                with ctx_ssl.wrap_socket(sock, server_hostname=host) as ss:
                    tls_version = ss.version() or ""
                    c = ss.cipher() or ()
                    cipher = c[0] if c else ""
                    cert = ss.getpeercert() or {}
        except ssl.SSLCertVerificationError as exc:
            handshake_err = f"证书校验失败: {exc.verify_message or exc}"
        except (ssl.SSLError, socket.timeout, OSError) as exc:
            return self._fail_result(results, f"TLS 握手失败（{host}:{port}）: {exc.__class__.__name__}: {exc}")

        # 2) 明文 HTTP 探测：若目标仅 HTTP 可达且 HTTPS 不可达 → 未启用传输加密
        if handshake_err:
            results.append({
                "case_no": "TLS-001", "title": "HTTPS 证书有效性", "owasp_id": "A02",
                "op_type": "传输加密", "method": "TLS", "path": f"https://{host}:{port}",
                "result": "FAIL", "risk_level": "critical",
                "failures": [f"E_TLS_CERT_INVALID: {handshake_err}"],
            })
        else:
            results.append({
                "case_no": "TLS-001", "title": "HTTPS 证书有效性", "owasp_id": "A02",
                "op_type": "传输加密", "method": "TLS", "path": f"https://{host}:{port}",
                "result": "PASS", "risk_level": "none", "failures": [],
            })
            # 协议版本
            insecure_proto = _is_insecure_protocol(tls_version)
            results.append({
                "case_no": "TLS-002", "title": f"TLS 协议版本（{tls_version}）", "owasp_id": "A02",
                "op_type": "传输加密", "method": "TLS", "path": f"https://{host}:{port}",
                "tls_version": tls_version,
                "result": "FAIL" if insecure_proto else "PASS",
                "risk_level": "high" if insecure_proto else "none",
                "failures": [f"E_TLS_INSECURE_PROTOCOL: 使用过时协议 {tls_version}，应升级 TLS 1.2+"]
                if insecure_proto else [],
            })
            # 加密套件
            weak_cipher = any(k in cipher.upper() for k in _WEAK_CIPHER_KEYS)
            results.append({
                "case_no": "TLS-003", "title": f"加密套件强度（{cipher}）", "owasp_id": "A02",
                "op_type": "传输加密", "method": "TLS", "path": f"https://{host}:{port}",
                "cipher": cipher,
                "result": "FAIL" if weak_cipher else "PASS",
                "risk_level": "high" if weak_cipher else "none",
                "failures": [f"E_TLS_WEAK_CIPHER: 弱加密算法 {cipher}"]
                if weak_cipher else [],
            })
            # 证书过期
            not_after = self._parse_cert_date(cert.get("notAfter", ""))
            expired = not_after is not None and not_after < datetime.now(timezone.utc)
            expiring_soon = (
                not_after is not None and not expired
                and (not_after - datetime.now(timezone.utc)).days <= 30
            )
            lvl = "critical" if expired else ("medium" if expiring_soon else "none")
            res = "PASS" if lvl == "none" else "FAIL"
            results.append({
                "case_no": "TLS-004", "title": f"证书有效期（{cert.get('notAfter', '未知')}）",
                "owasp_id": "A02", "op_type": "传输加密", "method": "TLS",
                "path": f"https://{host}:{port}",
                "result": res, "risk_level": lvl,
                "failures": (
                    [f"E_TLS_CERT_EXPIRED: 证书已过期（{cert.get('notAfter')}）"] if expired
                    else [f"E_TLS_CERT_EXPIRING: 证书 30 天内到期（{cert.get('notAfter')}）"]
                    if expiring_soon else []
                ),
            })

        passed = sum(1 for r in results if r["result"] == "PASS")
        failed = sum(1 for r in results if r["result"] == "FAIL")
        total = len(results)
        ok = failed == 0
        return EngineResult(
            status="SUCCESS" if ok else "FAILED",
            summary={
                "total": total, "passed": passed, "failed": failed,
                "pass_rate": round(passed / max(total, 1), 4),
                "key": "tls_pass_rate",
            },
            report_payload={
                "engine": self.engine_code,
                "engine_name": self.engine_name,
                "results": results,
                "conclusion": f"TLS 检测 {passed}/{total} 通过（协议 {tls_version or '不可达'}）",
            },
            error=None if ok else f"{failed} 项 TLS 配置不达标",
        )

    @staticmethod
    def _fail_result(results: list, error: str) -> EngineResult:
        results.append({
            "case_no": "TLS-000", "title": "TLS 连接可达性", "owasp_id": "A02",
            "op_type": "传输加密", "method": "TLS", "path": "",
            "result": "FAIL", "risk_level": "critical", "failures": [error],
        })
        return EngineResult(
            status="FAILED",
            summary={"total": 1, "passed": 0, "failed": 1, "pass_rate": 0.0},
            report_payload={"engine": "TLS_CHECK", "results": results, "conclusion": error},
            error=error,
        )

    @staticmethod
    def _parse_cert_date(s):
        """解析证书日期（如 'Dec 31 23:59:59 2026 GMT'）。非字符串（含 MagicMock 等）按无日期处理。"""
        if not s or not isinstance(s, str):
            return None
        try:
            return datetime.strptime(s, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
