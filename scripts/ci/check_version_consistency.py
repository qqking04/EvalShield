#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布门禁：版本一致性断言（docs/release/checklist.md §3，v2.0.0 演练补齐）。

判据（全等，任一不一致 FAIL）：
  1. 根目录 VERSION 文件
  2. backend/app/config.py  Settings.APP_VERSION
  3. CHANGELOG.md 顶部条目 ## [x.y.z]
附加（WARN，不阻断——tag 在发布动作时才打）：
  4. git tag v<VERSION> 是否存在

用法：python scripts/ci/check_version_consistency.py
退出码：0 = 三源一致; 1 = 不一致/缺文件
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def main() -> int:
    fails = []

    # 1. VERSION 文件
    vp = os.path.join(ROOT, "VERSION")
    version = None
    if os.path.isfile(vp):
        version = _read(vp).strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version or ""):
            fails.append(f"VERSION 文件格式非法: {version!r}（期望 x.y.z）")
    else:
        fails.append("缺少根目录 VERSION 文件")

    # 2. config.py APP_VERSION
    m = re.search(r'APP_VERSION:\s*str\s*=\s*"([^"]+)"',
                  _read(os.path.join(ROOT, "backend", "app", "config.py")))
    if not m:
        fails.append("backend/app/config.py 未找到 APP_VERSION")
    elif version and m.group(1) != version:
        fails.append(f"APP_VERSION={m.group(1)} != VERSION={version}")

    # 3. CHANGELOG.md 顶部条目
    cm = re.search(r"^## \[(\d+\.\d+\.\d+)\]",
                   _read(os.path.join(ROOT, "CHANGELOG.md")), re.M)
    if not cm:
        fails.append("CHANGELOG.md 顶部未找到 ## [x.y.z] 条目")
    elif version and cm.group(1) != version:
        fails.append(f"CHANGELOG 顶部={cm.group(1)} != VERSION={version}")

    for f in fails:
        print(f"FAIL {f}")
    if fails:
        return 1

    # 4. git tag（WARN）
    try:
        tags = subprocess.run(["git", "-C", ROOT, "tag", "-l", f"v{version}"],
                              capture_output=True, text=True).stdout.split()
        if not tags:
            print(f"WARN git tag v{version} 不存在（发布动作时补打）")
    except Exception as e:  # 非 git 环境不阻断
        print(f"WARN tag 检查跳过: {e}")

    print(f"OK 版本三源一致: {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
