# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES9 BUG-003（D-16/HAL-08）：SSRF 校验共享模块。

自 routers/fact_sources.py 抽取（优化9设计方案 §4.4 定稿），统一供
fact_sources / targets / notify_adapters.webhook 等出网入口复用：

- scheme ∉ {http,https} 拒绝；
- host ∈ RFC1918 / loopback / link-local（含 169.254.169.254 元数据地址）/
  IPv6 ULA / reserved / multicast 拒绝；
- DNS 解析后逐 IP 复校验（防域名指内网）。

残余风险：DNS 重绑定（TOCTOU）——缓解措施为连通性测试与调用侧各自独立
复校验 + 超时收紧；彻底免疫需 connect-hook 级 IP pin，已列入后续窗口。

``error_code`` 参数：指定时所有拒绝统一抛该错误码（如 ES-TARGET-SSRF），
缺省保持 fact_sources 存量细码 ES-FS-0001~0006 口径（不破坏既有契约）。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from ..errors import BizError

_DENIED_IPNetworkS = (
    ipaddress.ip_network("169.254.0.0/16"),   # link-local（含 169.254.169.254）
)
_META_HOSTS = {"169.254.169.254", "metadata.google.internal"}


def _ip_denied(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # 解析异常一律拒绝（fail-closed）
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return True
    if ip.is_unspecified or ip.is_multicast:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        # ULA fc00::/7（is_private 在 py3.9+ 已覆盖，双保险 + 兼容映射检查）
        if ip.ipv4_mapped is not None:
            return _ip_denied(str(ip.ipv4_mapped))
        if ip in ipaddress.ip_network("fc00::/7"):
            return True
        if str(ip).lower().startswith("fe80"):
            return True
    for net in _DENIED_IPNetworkS:
        if ip in net:
            return True
    return False


def validate_base_url(url: str, *, error_code: str | None = None) -> str:
    """SSRF 校验并归一；非法即 422。返回 strip 后的 URL。

    校验顺序：scheme → 字面 host 黑名单 → host 直连 IP 判定 →
    DNS 解析后逐 IP 复校验（防域名指内网）。
    ``error_code`` 指定时统一错误码（如 ES-TARGET-SSRF），否则保持
    fact_sources 存量细码 ES-FS-0001~0006 与原文案。
    """
    def _err(default_code: str, message: str, what: str | None = None) -> None:
        if error_code:
            raise BizError(
                error_code,
                f"SSRF 防护拒绝该地址：{what or message}",
                http_status=422,
            )
        raise BizError(default_code, message, http_status=422)

    u = (url or "").strip()
    if not u:
        _err("ES-FS-0001", "base_url 不能为空")
    try:
        p = urlparse(u)
    except ValueError:
        _err("ES-FS-0002", "base_url 无法解析")
    if p.scheme not in ("http", "https"):
        _err(
            "ES-FS-0003",
            f"scheme {p.scheme!r} 非法（仅允许 http/https）",
            what=f"scheme {p.scheme!r} 非法（仅允许 http/https）",
        )
    host = (p.hostname or "").strip().lower().rstrip(".")
    if not host:
        _err("ES-FS-0004", "base_url 缺少主机名")
    if host in _META_HOSTS:
        _err("ES-FS-0005", "拒绝元数据地址（SSRF 防护）", what=host)
    if _ip_denied_safe(host):  # host 是字面 IP 时直接判定，域名交给 DNS 分支
        _err(
            "ES-FS-0006",
            f"SSRF 防护拒绝该地址：{host}（内网/回环/链路本地/元数据地址不可达）",
            what=host,
        )
    # DNS 解析复校验（解析失败放行到 test 时报错——离线部署常见）
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError):
        infos = []
    for fam, _t, _p, _cn, sa in infos:
        try:
            addr = sa[0]
            if fam == socket.AF_INET6 and "%" in addr:
                addr = addr.split("%", 1)[0]
            if _ip_denied(addr):
                _err(
                    "ES-FS-0006",
                    f"SSRF 防护拒绝该地址：{host} → {addr}（内网/回环/链路本地/元数据地址不可达）",
                    what=f"{host} → {addr}",
                )
        except ValueError:
            _err(
                "ES-FS-0006",
                f"SSRF 防护拒绝该地址：{host}（内网/回环/链路本地/元数据地址不可达）",
                what=host,
            )
    return u


def _ip_denied_safe(host: str) -> bool:
    """host 为字面 IP 时判定，域名为 False（交给 DNS 分支）。"""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return _ip_denied(host)


__all__ = ["validate_base_url", "_ip_denied", "_ip_denied_safe"]
