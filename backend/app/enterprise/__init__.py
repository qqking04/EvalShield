# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""EvalShield 企业版闭源层（Open Core 分层：community < saas < enterprise）。

本目录承载变现能力（license 校验、多租户、SSO、中文法条库、盖章报告导出），
仅在 enterprise 版本镜像中打包；开源发布脚本（scripts/release_oss.sh）会整体剥离本目录。

安全约定：
- license.py 为「验签 + 机器指纹」核心闸门，本章（enterprise/）为 PyArmor 混淆对象。
- 私有化授权私钥绝不进入本目录/镜像，仅存于签发者本机的 license_cli.py 同侧密钥目录。
"""