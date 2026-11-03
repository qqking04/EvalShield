# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M10：OIDC Authorization Code + PKCE 手撸实现（方案 §11 M10，不引 authlib）。

仅用 stdlib(secrets/hashlib/base64) + 既有依赖 httpx / python-jose：
- discovery：拉取 {issuer}/.well-known/openid-configuration（内存缓存带 TTL）
- JWKS：拉取 jwks_uri（内存缓存带 TTL），按 id_token 头 kid 选 key RS256 验签
- id_token 校验：iss/aud 精确匹配 + nonce 强一致 + exp（leeway 60s）
- PKCE：S256（challenge = base64url(sha256(verifier)) 去 padding）

企微/飞书：同 start/callback 骨架——本项目按「网关产品暴露标准 OIDC 端点」
接入（issuer 指其 OIDC 前缀即可），差异收敛在 discovery 文档本身，
故取用户信息端点无需单独实现（SCIM/SAML 不做，见方案）。
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any

import httpx
from jose import jwt

from ..config import settings

# discovery / JWKS 内存缓存 TTL（秒）
_DISCOVERY_TTL = 600
_JWKS_TTL = 300
# state/nonce/verifier 中转 cookie 有效期（秒）
_RELAY_TTL = 600
# id_token 时钟偏差容忍
_LEEWAY = 60
_HTTP_TIMEOUT = 10.0

_DISCOVERY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
# 已消费的中转 jti（防同一 state cookie 重放；进程内小型集合，超限即整表清理）
_USED_JTIS: set[str] = set()


def clear_caches() -> None:
    """清空 discovery/JWKS 缓存与已用 jti 集合（测试与配置变更后复用）。"""
    _DISCOVERY_CACHE.clear()
    _JWKS_CACHE.clear()
    _USED_JTIS.clear()


# ── PKCE ──────────────────────────────────────────────────────────────
def gen_pkce() -> tuple[str, str]:
    """返回 (code_verifier, code_challenge[S256])。"""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


# ── 中转 cookie（state + nonce + verifier，HS256 签名，无服务端会话） ──
def make_relay_token(config_id: int, state: str, nonce: str, verifier: str) -> str:
    """签发短 TTL 中转令牌：把 CSRF state、id_token nonce、PKCE verifier 打包。"""
    now = int(time.time())
    payload = {
        "cfg": config_id,
        "st": state,
        "nc": nonce,
        "cv": verifier,
        "jti": secrets.token_hex(8),
        "iat": now,
        "exp": now + _RELAY_TTL,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def read_relay_token(token: str, config_id: int) -> dict[str, Any] | None:
    """解析并消费中转令牌：验签 + 过期 + 绑定 config_id + jti 一次性。

    校验失败或重放（jti 已消费）返回 None，调用方按 state 校验失败处理。
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except Exception:  # noqa: BLE001 —— 签名/格式错误统一按无效处理
        return None
    if int(payload.get("cfg", -1)) != config_id:
        return None
    jti = payload.get("jti") or ""
    if not jti or jti in _USED_JTIS:
        return None
    if len(_USED_JTIS) > 10000:  # 容量兜底：超限整表清理，避免无界增长
        _USED_JTIS.clear()
    _USED_JTIS.add(jti)
    return payload


# ── discovery / JWKS ─────────────────────────────────────────────────
def discover(issuer: str) -> dict[str, Any]:
    """拉取并缓存 openid-configuration（TTL 内命中缓存不发请求）。"""
    base = (issuer or "").strip().rstrip("/")
    if not base:
        raise ValueError("issuer 未配置")
    cached = _DISCOVERY_CACHE.get(base)
    if cached and cached[0] > time.time():
        return cached[1]
    resp = httpx.get(f"{base}/.well-known/openid-configuration", timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    doc = resp.json()
    _DISCOVERY_CACHE[base] = (time.time() + _DISCOVERY_TTL, doc)
    return doc


def _jwks(jwks_uri: str) -> dict[str, Any]:
    cached = _JWKS_CACHE.get(jwks_uri)
    if cached and cached[0] > time.time():
        return cached[1]
    resp = httpx.get(jwks_uri, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    doc = resp.json()
    _JWKS_CACHE[jwks_uri] = (time.time() + _JWKS_TTL, doc)
    return doc


def _find_jwk(jwks_uri: str, kid: str) -> dict[str, Any] | None:
    """按 kid 匹配公钥；kid 未命中时强制刷新一次缓存再找。"""
    doc = _jwks(jwks_uri)
    for key in doc.get("keys", []):
        if key.get("kid") == kid:
            return key
    _JWKS_CACHE.pop(jwks_uri, None)
    doc = _jwks(jwks_uri)
    for key in doc.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def verify_id_token(id_token: str, *, issuer: str, client_id: str, nonce: str) -> dict[str, Any]:
    """RS256 验签 + iss/aud/nonce/exp 校验（leeway 60s），返回 claims。

    验签失败 / 声明不符一律抛 ValueError，由路由层转 BizError。
    """
    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid") or ""
    doc = discover(issuer)
    jwks_uri = doc.get("jwks_uri") or ""
    if not jwks_uri:
        raise ValueError("discovery 文档缺少 jwks_uri")
    jwk = _find_jwk(jwks_uri, kid)
    if jwk is None:
        raise ValueError("JWKS 无匹配 kid")
    try:
        # 注意：python-jose 的 decode 不支持 leeway 参数，exp 校验手动做（见下）
        claims = jwt.decode(
            id_token,
            jwk,  # python-jose 接受 JWK dict 作为 RS256 验签 key
            algorithms=["RS256"],
            audience=client_id,
            issuer=doc.get("issuer", issuer.rstrip("/")),
            options={"verify_exp": False},
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"id_token 校验失败：{exc}") from exc
    exp = claims.get("exp")
    if exp is not None and time.time() > int(exp) + _LEEWAY:
        raise ValueError("id_token 已过期")
    if claims.get("nonce") != nonce:
        raise ValueError("id_token nonce 不匹配（疑似重放）")
    return claims


# ── authorize / token ────────────────────────────────────────────────
def build_authorize_url(
    doc: dict[str, Any], *, client_id: str, redirect_uri: str, scope: str,
    state: str, nonce: str, code_challenge: str,
) -> str:
    """组装 authorization_endpoint 跳转 URL（response_type=code + PKCE S256）。"""
    endpoint = doc.get("authorization_endpoint") or ""
    if not endpoint:
        raise ValueError("discovery 文档缺少 authorization_endpoint")
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope or "openid",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{endpoint}?{urlencode(params)}"


def exchange_code(
    doc: dict[str, Any], *, client_id: str, client_secret: str, code: str,
    redirect_uri: str, code_verifier: str,
) -> dict[str, Any]:
    """code 换 token（POST token_endpoint，form 编码）。"""
    endpoint = doc.get("token_endpoint") or ""
    if not endpoint:
        raise ValueError("discovery 文档缺少 token_endpoint")
    resp = httpx.post(
        endpoint,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": code_verifier,
        },
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("id_token"):
        # 部分 provider 只在响应给 access_token：走 userinfo 兜底取 sub/email
        userinfo_endpoint = doc.get("userinfo_endpoint") or ""
        if data.get("access_token") and userinfo_endpoint:
            ur = httpx.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {data['access_token']}"},
                timeout=_HTTP_TIMEOUT,
            )
            ur.raise_for_status()
            data["userinfo"] = ur.json()
    return data


def resolve_redirect_uri(cfg: Any) -> str:
    """回调地址精确匹配白名单：配置了 redirect_uri 用之，否则按 API 基址构造。"""
    configured = (getattr(cfg, "redirect_uri", "") or "").strip()
    if configured:
        return configured
    base = settings.API_DEFAULT_BASE_URL.rstrip("/")
    return f"{base}/api/auth/sso/callback"
