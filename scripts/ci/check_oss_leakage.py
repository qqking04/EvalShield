#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# EvalShield
# SPDX-License-Identifier: Apache-2.0
"""OSS 发布树泄露自证扫描器（优化15 §5.1 O-2，六断言，纯标准库）。

定位：剥离是黑名单语义（EXCLUDES 清单），本扫描器是白名单自证——不依赖
"排除清单写全"，按内容特征扫发布树终态投影；边界外新增商业文件默认混入
的破口由本脚本封死（§12 T-6 发布事故型泄露的 L2 闸门）。

用法：
    python scripts/ci/check_oss_leakage.py <发布树目录>

退出码：0 干净；1 命中泄露/扫描面失效。输出格式仿 KEY-01：逐条 路径:行号: 内容前 100 字符。

六断言（对发布树全文件，跳过 node_modules/dist/__pycache__/.git）：
  ① 商业 SPDX 头        任一文件含商业 SPDX 标记（SPDX_MARKER，拼接构造防自指）
                         白名单：LICENSE（双许可正文须公开商业条款）、
                         release_oss.sh / add_headers.py（工具自身模式串，自指非泄露）
  ② 商业 import         *.py 模块级（行首无缩进）from .commercial / from app.commercial /
                         import app.commercial —— OSS 树必崩启动（B9 漏改）；
                         缩进的惰性 import（main.py 降级机理）不在判据内
  ③ 商业前端说明符      *.js(x) 引号包裹的相对说明符含 commercial/ 或 platform/
                         （strip_fe 改写遗漏；注释提及不算）
  ④ 商业实现字样        文本文件含 IMPL_MARKERS 三标记（saas 拒绝守卫 / SaaS 守卫模块名 /
                         商业注册函数，词边界；均拼接构造防自指）
                         白名单：backend/app/main.py（挂载降级 harness，§2.2 机理实体）；
                         词边界防 registry.py 社区函数 register_commercial_engines 误伤
  ⑤ 签发面文件名        basename 为 issue_license.py / license_cli.py，
                         或扩展名 .lic / .pem / .key（O-1 双保险 + 私钥面；
                         与 KEY-01 正交：本断言扫发布树文件面，KEY-01 扫私有仓跟踪面）
  ⑥ 哨兵自检            被扫文件数 == 0 → FAIL（防扫描面失效假绿，
                         对齐 publish-oss.ps1 L33 既有纪律）

注意：本文件所有匹配模式均以字符串拼接构造，避免扫描器自指命中。
"""

from __future__ import annotations

import os
import re
import sys

# ---------- 模式（拼接构造，防自指） ----------
SPDX_MARKER = "LicenseRef-EvalShield-" + "Commercial"
IMPL_MARKERS = (
    "_reject" + "_saas",
    "saas" + "_guard",
    re.compile(r"register_" + r"commercial\b"),  # 词边界：不匹配 register_commercial_engines
)

# ② 模块级商业 import：行首无缩进
MODLEVEL_COMMERCIAL = re.compile(
    r"^(from\s+(\.|app\.)commercial|import\s+app\.commercial)"
)

# ③ 引号包裹的相对说明符含 commercial/ 或 platform/（与 strip_fe SPEC_RE/PLATFORM_SPEC_RE 同口径）
FE_SPECIFIER = re.compile(
    r"""["'][^"']*(?:\.{1,2}/)[^"']*(""" + "commercial" + r"""|platform)/[\w-]+["']"""
)

SKIP_DIRS = {".git", "node_modules", "__pycache__", "dist", ".venv"}

# ① SPDX 白名单（相对发布树路径，POSIX 分隔符）
SPDX_ALLOW = {
    "LICENSE",
    "scripts/release_oss.sh",
    "scripts/add_headers.py",
}
# ④ 实现字样白名单：商业包挂载降级 harness（惰性 import，OSS 树 ImportError 即跳过）
IMPL_ALLOW = {
    "backend/app/main.py",
}
# ③ 前端说明符白名单：剥离工具自身的示例注释/正则（自指模式串，与 SPDX 工具白名单同理）
FE_SPEC_ALLOW = {
    "frontend/scripts/strip_fe.js",
}

TEXT_EXTS = {
    ".py", ".sh", ".ps1", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".md", ".yml", ".yaml", ".json", ".txt", ".sql", ".html", ".css",
    ".example", ".conf", ".toml", ".ini", ".csv", ".bat",
}
TEXT_NAMES = {"Dockerfile", "requirements.txt", "nginx.conf", "LICENSE", "VERSION"}


def _rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _is_text_file(name: str) -> bool:
    ext = os.path.splitext(name)[1].lower()
    return ext in TEXT_EXTS or name in TEXT_NAMES


def scan(root: str) -> list:
    """返回违规条目列表：(断言号, 相对路径, 行号, 内容前 100 字符)。"""
    findings = []
    scanned = 0

    def add(no, relpath, lineno, content):
        findings.append((no, relpath, lineno, content[:100]))

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = _rel(root, full)
            # ⑤ 签发面文件名（全文件面，含二进制）
            if fn in ("issue_" + "license.py", "license_cli.py"):
                add("⑤", rel, 0, "签发面残留文件")
            if os.path.splitext(fn)[1].lower() in (".lic", ".pem", ".key"):
                add("⑤", rel, 0, "私钥/License 文件面残留")
            if not _is_text_file(fn):
                continue
            try:
                # utf-8-sig：剥 UTF-8 BOM，防 BOM 前缀使 ② 的行首锚定正则逃逸
                with open(full, encoding="utf-8-sig", errors="strict") as f:
                    lines = f.read().splitlines()
            except (UnicodeDecodeError, OSError):
                continue  # 不可读文本不计入扫描面（scanned 仅在成功读取后自增）
            scanned += 1
            spdx_ok = rel in SPDX_ALLOW
            impl_ok = rel in IMPL_ALLOW
            fe_ok = rel in FE_SPEC_ALLOW
            for i, line in enumerate(lines, 1):
                # ① 商业 SPDX 头
                if not spdx_ok and SPDX_MARKER in line:
                    add("①", rel, i, line)
                # ② 模块级商业 import（仅 .py）
                if fn.endswith(".py") and MODLEVEL_COMMERCIAL.match(line):
                    add("②", rel, i, line)
                # ③ 商业前端说明符（仅 .js/.jsx；剥离工具自指白名单）
                if not fe_ok and fn.endswith((".js", ".jsx")) and FE_SPECIFIER.search(line):
                    add("③", rel, i, line)
                # ④ 商业实现字样
                if not impl_ok:
                    for m in IMPL_MARKERS:
                        if (m.search(line) if isinstance(m, re.Pattern) else m in line):
                            add("④", rel, i, line)
                            break
    # ⑥ 哨兵自检
    if scanned == 0:
        findings.append(("⑥", root, 0, "被扫文本文件数为 0（扫描面失效，拒绝假绿）"))
    return findings


def main(argv) -> int:
    if len(argv) != 2:
        print("用法: python check_oss_leakage.py <发布树目录>")
        return 2
    root = argv[1]
    if not os.path.isdir(root):
        print(f"FAIL: 发布树目录不存在: {root}")
        return 1
    findings = scan(root)
    if findings:
        print(f"FAIL: OSS 发布树泄露扫描命中 {len(findings)} 处（优化15 §5.1 O-2 六断言）：")
        for no, rel, lineno, content in findings[:50]:
            loc = f"{rel}:{lineno}" if lineno else rel
            print(f"  [{no}] {loc}: {content}")
        if len(findings) > 50:
            print(f"  ...（共 {len(findings)} 处，仅显示前 50）")
        return 1
    print("OK: check_oss_leakage 六断言 0 命中（发布树投影干净）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
