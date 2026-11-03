# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES9-P-05：LLM 凭据落库加密与掩码（设计 §3.3-D）。

- UI 托管密钥统一 Fernet 加密存 ``model_configs.api_key_enc``（与 api_key_env 互斥）；
  密钥派生自 ``settings.SECRET_KEY``（sha256 → urlsafe base64，32B）。
- GET 接口一律返回掩码（``sk-****abcd``，保留末 4 位），禁止输出密文/明文。
- PUT 收到含 ``****`` 的值视为未修改（防回写掩码）。
- 旧明文透明升级：解密失败（非 Fernet 密文）时原样返回并按下次保存覆盖为密文。

ES9 遗留项（统一加密入口）：``encrypt_secret``/``decrypt_secret`` 为全仓
敏感值加解密唯一出口——新写入统一 Fernet（``fernet$`` 前缀），兼容读取
``app/security.py`` 的 AES-256-GCM 遗留密文（``aes$`` 前缀，透明解密）。
cryptography 为硬依赖（requirements.txt 钉死版本），不再 try-import 降级。
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from ..config import settings

_MASK_MARK = "****"
_FERNET_PREFIX = "fernet$"
_AES_PREFIX = "aes$"


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    )
    return Fernet(key)


def encrypt_api_key(plain: str | None) -> str | None:
    """明文密钥 → Fernet 密文（空值返回 None）。"""
    if not plain:
        return None
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_api_key(token: str | None) -> str | None:
    """密文 → 明文；非 Fernet 密文（旧明文遗留）原样返回（透明升级兼容）。"""
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001 - InvalidToken 等一律按旧明文处理
        return token


def mask_api_key(plain: str | None) -> str | None:
    """明文密钥 → 展示掩码：保留末 4 位，形如 ``sk-****abcd``。"""
    if not plain:
        return None
    if len(plain) <= 4:
        return _MASK_MARK
    head = "sk-" if plain.lower().startswith("sk-") else ""
    return f"{head}{_MASK_MARK}{plain[-4:]}"


def is_masked(value: str | None) -> bool:
    """PUT 回写检测：含 ``****`` 视为未修改。"""
    return _MASK_MARK in (value or "")


# ------------------------------------------------ 统一敏感值入口（ES9 遗留项）----

def encrypt_secret(plain: str | None) -> str | None:
    """敏感值 → Fernet 密文（``fernet$`` 前缀标识统一加密入口产物）。"""
    if not plain:
        return None
    return _FERNET_PREFIX + _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str | None) -> str | None:
    """统一解密：按前缀分派。

    - ``fernet$…`` → Fernet 解密（本模块产物）；
    - ``aes$…``    → 遗留 AES-256-GCM 密文，委托 ``app.security.decrypt_secret``
      （只读兼容存量数据；新写入一律走本模块 encrypt_secret）；
    - 其余        → 旧明文遗留，原样返回（下次保存时被覆盖为 Fernet 密文）。
    """
    if not token:
        return None
    if token.startswith(_FERNET_PREFIX):
        return _fernet().decrypt(token[len(_FERNET_PREFIX):].encode("ascii")).decode("utf-8")
    if token.startswith(_AES_PREFIX):
        from ..security import decrypt_secret as _aes_decrypt

        return _aes_decrypt(token)
    return token
