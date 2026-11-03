# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""安全工具：密码哈希(MD5统一+bcrypt兼容迁移)、JWT、API Key、TOTP、AES-256-GCM加密、脱敏、密码策略。

硬性约束：C2 密码只能用 MD5（兼容 bcrypt 存量登录+自动迁移）。
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .config import settings
from .errors import BizError

# ---------------------------------------------------------------------------
# 安全策略常量
# ---------------------------------------------------------------------------
MAX_LOGIN_FAILS = settings.LOGIN_FAIL_LIMIT
LOCK_MINUTES = settings.LOGIN_LOCK_MINUTES
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

_MD5_PREFIX = "md5$"
_AES_PREFIX = "aes$"

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(key|token|secret|password|authorization)", re.IGNORECASE
)

# 脱敏正则
_RE_MOBILE = re.compile(r"1[3-9]\d{9}")
_RE_IDCARD = re.compile(r"\b\d{17}[\dXx]\b")
_RE_APIKEY = re.compile(r"(?i)(sk-|pk-)[A-Za-z0-9]{8,}")
_RE_EMAIL = re.compile(r"([A-Za-z0-9_.]{2})[A-Za-z0-9_.+-]+(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")


# ---------------------------------------------------------------------------
# C2 密码哈希（MD5 统一 + bcrypt 兼容迁移）
# ---------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    salt = secrets.token_hex(8)  # 16 位盐
    digest = hashlib.md5((salt + plain).encode("utf-8")).hexdigest()
    return f"{_MD5_PREFIX}{salt}${digest}"


def verify_password(plain: str, stored: str) -> bool:
    if stored.startswith(_MD5_PREFIX):
        parts = stored.split("$", 2)
        if len(parts) != 3:
            return False
        _, salt, digest = parts
        calc = hashlib.md5((salt + plain).encode("utf-8")).hexdigest()
        return secrets.compare_digest(calc, digest)
    # 存量 bcrypt 兼容
    if stored.startswith("$2"):
        try:
            from passlib.context import CryptContext
            legacy = CryptContext(schemes=["bcrypt"], deprecated="auto")
            return legacy.verify(plain, stored)
        except Exception:  # noqa: BLE001
            return False
    return False


def needs_rehash(stored: str) -> bool:
    # F-03 修复：md5$（C2 新建口令终态）与 bcrypt（存量兼容、强度高于 md5）
    # 均为可接受格式，不再把 bcrypt 判为"需迁移"——原实现会在 bcrypt 存量账号
    # 登录成功后将其覆写为 MD5，构成哈希强度降级。
    # 仅未知/不可校验格式才需 rehash（此类账号 verify_password 已失败，实际不可达）。
    return not (stored.startswith(_MD5_PREFIX) or stored.startswith("$2"))


def validate_password_policy(plain: str, policy: dict | None = None) -> None:
    """密码策略校验（优化7 T4 参数化）。

    policy 来自 get_pwd_policy(db)：min_length / complexity(alnum_sym)。
    默认（无 db 场景，如 seed）：≥10 位 + 大写/小写/数字/符号 四类中至少 3 类。
    不符合抛 BizError ES-AUTH-0012（message 回显具体规则）。
    """
    min_len = int((policy or {}).get("min_length", 10))
    if len(plain) < min_len:
        raise BizError("ES-AUTH-0012", f"密码不符合安全策略：至少 {min_len} 位", http_status=400)
    classes = 0
    if re.search(r"[A-Z]", plain):
        classes += 1
    if re.search(r"[a-z]", plain):
        classes += 1
    if re.search(r"[0-9]", plain):
        classes += 1
    if re.search(r"[^A-Za-z0-9]", plain):
        classes += 1
    if classes < 3:
        raise BizError(
            "ES-AUTH-0012",
            "密码不符合安全策略：须含大写字母、小写字母、数字、特殊符号中至少 3 类",
            http_status=400,
        )


def get_pwd_policy(db: Session) -> dict:
    """读取 pwd_policy 数据字典（缺失时用默认值，幂等安全）。"""
    from .models import DataDict, DictItem

    defaults = {
        "min_length": "10",
        "complexity": "alnum_sym",
        "history_keep": "5",
        "max_age_days": "180",
    }
    dd = (
        db.query(DataDict)
        .filter(DataDict.dict_code == "pwd_policy", DataDict.deleted_at.is_(None))
        .first()
    )
    if dd is None:
        return defaults
    rows = (
        db.query(DictItem)
        .filter(DictItem.dict_id == dd.id, DictItem.deleted_at.is_(None))
        .all()
    )
    for it in rows:
        val = (it.ext or {}).get("value") if isinstance(it.ext, dict) else None
        if val:
            defaults[it.item_value] = str(val)
    return defaults


def ensure_not_reused(user_id: int, new_plain: str, db: Session, history_keep: int = 5) -> None:
    """历史密码查重（最近 history_keep 条，默认 5）。命中抛 ES-AUTH-0015。

    ES7-F-1 修复：hash_password 每次用新随机盐，直接比较两条存储串的 digest
    永不命中；改为对候选明文按各存储串自身的盐重算摘要比对（verify_password 同款逻辑），
    并将用户当前口令一并纳入比对集。
    """
    from .models import PasswordHistory, SystemUser

    stored = [
        r[0]
        for r in db.query(PasswordHistory.password_hash)
        .filter(PasswordHistory.user_id == user_id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(max(1, history_keep))
        .all()
    ]
    current = db.query(SystemUser.password_hash).filter(SystemUser.id == user_id).scalar()
    if current and current not in stored:
        stored.insert(0, current)
    for s in stored:
        if s and verify_password(new_plain, s):
            raise BizError("ES-AUTH-0015", f"新密码不能与最近 {history_keep} 次使用的密码相同", http_status=400)


# ---------------------------------------------------------------------------
# JWT（不变）
# ---------------------------------------------------------------------------
def create_access_token(
    user_id: int,
    username: str,
    tenant_id: int,
    roles: list[str],
    perms: list[str],
    expires_minutes: int | None = None,
    scope: list[str] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "ten": tenant_id,
        "roles": roles,
        "perms": perms,
        "typ": "access",
        "iat": now,
        "exp": expire,
        "jti": secrets.token_hex(8),
    }
    if scope:
        # 优化7 T4：半态令牌（如 pwd_change_only），全局依赖拦截业务接口
        payload["scope"] = scope
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def create_refresh_token(user_id: int, tenant_id: int) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "ten": tenant_id,
        "typ": "refresh",
        "iat": now,
        "exp": expire,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        return None


def create_token_pair(
    user_id: int,
    tenant_id: int,
    roles: list[str] | None = None,
    perms: list[str] | None = None,
    scope: list[str] | None = None,
) -> tuple[str, str]:
    access = create_access_token(
        user_id=user_id,
        username="",
        tenant_id=tenant_id,
        roles=roles or [],
        perms=perms or [],
        scope=scope,
    )
    refresh = create_refresh_token(user_id=user_id, tenant_id=tenant_id)
    return access, refresh


# ---------------------------------------------------------------------------
# API Key（不变）
# ---------------------------------------------------------------------------
def hash_api_key(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return "es_" + secrets.token_hex(32)


# ---------------------------------------------------------------------------
# TOTP（不变）
# ---------------------------------------------------------------------------
def generate_totp_secret() -> str:
    import pyotp
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    import pyotp
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def build_totp_uri(secret: str, issuer: str = "EvalShield", account: str = "") -> str:
    import urllib.parse
    label = urllib.parse.quote(f"{issuer}:{account}")
    return (
        f"otpauth://totp/{label}?secret={secret}"
        f"&issuer={urllib.parse.quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    )


# ---------------------------------------------------------------------------
# C4.4.3 AES-256-GCM 敏感值加密
# ---------------------------------------------------------------------------
def _aes_key() -> bytes:
    return hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()


def _aesgcm():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(_aes_key())


def encrypt_secret(plain: str) -> str:
    """加密：返回 aes$<nonce_b64>$<cipher_b64>。"""
    aes = _aesgcm()
    nonce = secrets.token_bytes(12)
    ct = aes.encrypt(nonce, plain.encode("utf-8"), None)
    return f"{_AES_PREFIX}{base64.b64encode(nonce).decode()}${base64.b64encode(ct).decode()}"


def decrypt_secret(token: str) -> str:
    """解密 aes$...$...；非加密串原样返回。"""
    if not is_encrypted(token):
        return token
    _, nonce_b64, ct_b64 = token.split("$", 2)
    aes = _aesgcm()
    return aes.decrypt(
        base64.b64decode(nonce_b64), base64.b64decode(ct_b64), None
    ).decode("utf-8")


def is_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith(_AES_PREFIX)


def encrypt_sensitive_dict(d: dict | None) -> dict:
    """对 dict 中敏感键自动加密。键名含 key/token/secret/password/authorization 命中即加密。"""
    if not d:
        return {}
    out: dict = {}
    for k, v in d.items():
        if isinstance(v, str) and _SENSITIVE_KEY_PATTERN.search(k or "") and not is_encrypted(v):
            out[k] = encrypt_secret(v)
        else:
            out[k] = v
    return out


def mask_sensitive_value(value: str) -> str:
    """敏感值前端回显。明文：敏感键的值一律返回 ******；已加密也返回 ******。"""
    return "******" if value else value


# ---------------------------------------------------------------------------
# C4.4.4 通用脱敏（报告/公开分享）
# ---------------------------------------------------------------------------
def mask_sensitive(text: str) -> str:
    """文本脱敏：手机号/身份证/API Key/邮箱。"""
    if not isinstance(text, str):
        return text
    # 手机号：1[3-9]\d{9} → 保留前3后4
    text = _RE_MOBILE.sub(lambda m: m.group()[:3] + "****" + m.group()[-4:], text)
    # 身份证：保留前6后4
    text = _RE_IDCARD.sub(lambda m: m.group()[:6] + "********" + m.group()[-4:], text)
    # API Key：sk-xxxx / pk-xxxx → 前5+****
    text = _RE_APIKEY.sub(lambda m: m.group()[:5] + "****", text)
    # 邮箱：保留前2字符
    text = _RE_EMAIL.sub(lambda m: m.group(1) + "****" + m.group(2), text)
    return text


def mask_ip(ip: str | None) -> str | None:
    """IP 末段置 *。"""
    if not ip:
        return ip
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".*"
    return ip


def mask_data(obj: Any) -> Any:
    """递归脱敏任意 JSON 结构。"""
    if isinstance(obj, str):
        return mask_sensitive(obj)
    if isinstance(obj, list):
        return [mask_data(x) for x in obj]
    if isinstance(obj, dict):
        return {k: mask_data(v) for k, v in obj.items()}
    return obj
