# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""统一业务编号生成器。

编号约定（硬性，页面展示一律使用编号不用 ID）：
- 前缀 + 年月日时分秒 + 4 位随机，如 PJ-20260915103012-8F3K
- 保证并发唯一。
"""

from __future__ import annotations

import random
import string
import time


def gen_no(prefix: str) -> str:
    ts = time.strftime("%Y%m%d%H%M%S")
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{ts}-{rand}"
