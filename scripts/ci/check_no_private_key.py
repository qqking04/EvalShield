#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""KEY-01 · 私钥入仓门禁（优化14 §5.5.3-4 / §5.5.4，CI 必拦终态位）.

分层职责（§8 S-6）：本地 pre-commit 哨兵=第 0 层当次拦截（可旁路），
本脚本=CI 第 3 层终态必拦；断言④反向守护 pre-commit 哨兵在位。
gitleaks 保持 continue-on-error 非阻断现状，泛化泄露由它兜底、本脚本兜私钥。

四断言（判据=优化14详细开发 §4.2，基线首跑必绿）：
- ① 路径：git 跟踪文件不得命中 .pem/.key/.lic 或 .keys/ 目录
  （大小写不敏感——BUG-ES14-001 修复：大写扩展名 PUBLIC.PEM 不得逃逸）；
- ② 内容：跟踪的 *.py,*.js,*.json,*.yaml,*.yml 不得含私钥 PEM 块
