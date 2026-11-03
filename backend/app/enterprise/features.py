# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""企业能力开关唯一事实源（版本分层：community / saas / enterprise）。

开关判定优先级：license 授权覆盖（activate_license 后） > 环境变量显式配置 > EDITION 感知默认值。
community 版无 license，全部能力位默认关闭（且 env 显式配 true 也强制关，OSS 语义收口）。
ES8 M1：默认值由「全 false」改为按 EDITION 分流（见 _edition_default）。
"""

from __future__ import annotations

import os
from typing import Iterable


def _bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


# 当前版本定位：community | saas | enterprise
EDITION: str = os.getenv("EDITION", "community").lower()


def _edition_default(feature: str) -> bool:
    """EDITION 感知的能力位默认值（env 未显式配置时生效）。

    - community：恒 False（OSS 版不解锁任何商用能力位）
    - saas：平台运营侧默认开启的资源约束/运营能力位为 True
    - enterprise：默认 False（由 License payload 经 activate_license 覆盖点亮）
    """
    if EDITION == "community":
        return False
    if EDITION == "saas":
        return feature in {
            "multi_tenant",
            "monitor",
            "review_queue",
            "online_eval",
            "generative_redteam",
            "notify",
            "defect_sync",
        }
    return False


def _env_or_default(env_name: str, feature: str) -> bool:
    """env 显式配置优先；未配置时取 EDITION 感知默认值。"""
    raw = os.getenv(env_name)
    if raw is not None and raw.strip() != "":
        if EDITION == "community":
            return False  # community 强制关（env 显式配置仍不解锁）
        return _bool(raw)
    return _edition_default(feature)


# 能力位默认表（每位一个独立 env；ES8 M1 起默认值 EDITION 感知）
_ENV_FLAGS: dict[str, bool] = {
    "multi_tenant": _env_or_default("MULTI_TENANT_ENABLED", "multi_tenant"),
    "sso": _env_or_default("SSO_ENABLED", "sso"),
    "compliance_package": _env_or_default("COMPLIANCE_PACKAGE_ENABLED", "compliance_package"),
    "whitelabel": _env_or_default("WHITELABEL_ENABLED", "whitelabel"),
    # ES8 M1 新增能力位
    "self_register": _env_or_default("SELF_REGISTER_ENABLED", "self_register"),
    "monitor": _env_or_default("MONITOR_ENABLED", "monitor"),
    "review_queue": _env_or_default("REVIEW_QUEUE_ENABLED", "review_queue"),
    "online_eval": _env_or_default("ONLINE_EVAL_ENABLED", "online_eval"),
    "generative_redteam": _env_or_default("GENERATIVE_REDTEAM_ENABLED", "generative_redteam"),
    "notify": _env_or_default("NOTIFY_ENABLED", "notify"),
    "defect_sync": _env_or_default("DEFECT_SYNC_ENABLED", "defect_sync"),
}

# 运行时由 license 验签结果覆盖（进程内内存态，不落库）
_licensed_features: set[str] | None = None


def activate_license(features: Iterable[str]) -> None:
    """license 验签通过后，把授权能力位写入进程内存态。"""
    global _licensed_features
    _licensed_features = set(features or [])


def feature_enabled(name: str) -> bool:
    """查询某能力位是否开启。"""
    if _licensed_features is not None:
        return name in _licensed_features
    return bool(_ENV_FLAGS.get(name, False))