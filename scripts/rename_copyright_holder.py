# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""D-3/D-4 主体定名一键替换工具（法务提供注册主体后执行）。

把 decisions.md D-4「定名后动作清单」1~3 步收敛为一条命令：
  1. 全仓文本中占位主体 → 正式主体（代码版权头、LICENSE、docs/business 模板）；
  2. 六份商务模板签署栏「签约主体名称（定名后统一替换）」→ 正式主体；
     既有两份「武汉XX数字科技有限公司（定名后替换）」→ 正式主体；
  3. 新四份模板抬头「乙方：__________」→「乙方：<正式主体>」（甲方留空线不动）；
  4. scripts/add_headers.py 的 COPYRIGHT_HOLDER 常量同步（后续新文件自动用新主体）。

安全口径：
- 默认 dry-run 只列命中清单；--apply 才写入；写前对每文件做编码探测，
  非 UTF-8 / 二进制一律跳过并告警（防误伤）；
- docs/internal/decisions.md 属决策留痕（记录占位历史）**永不改写**；
- 本工具不臆测主体名：--holder 为唯一事实输入，缺省即拒绝执行；
- 替换完成后需人工/CI 复核：grep 占位串 0 命中（decisions.md 除外）、
  全量 pytest、release_oss.sh 链路。

用法（仓库根）：
    python scripts/rename_copyright_holder.py --holder "武汉某某科技有限公司" --holder-en "Wuhan Moumou Technology Co., Ltd."
    python scripts/rename_copyright_holder.py ... --apply

退出码：0=成功；1=无命中或校验不通过；2=参数/环境错误。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 占位口径（与仓库现状逐字一致；两变体顺序 = add_headers.py / LICENSE 现行文本）
PLACEHOLDER_FULL = "武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.)"
PLACEHOLDER_CN = "武汉XX数字科技有限公司"
BUSINESS_SIGNED = "武汉XX数字科技有限公司（定名后替换）"
BUSINESS_GENERIC = "签约主体名称（定名后统一替换）"
PARTY_B_BLANK = "乙方：__________"

# 永不改写（决策留痕记录占位历史；本工具自身含占位串作为替换源，亦跳过）
NEVER_TOUCH = {
    REPO / "docs" / "internal" / "decisions.md",
    Path(__file__).resolve(),
}

TEXT_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".sql",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".html", ".sh", ".ps1", ".bat",
}


def iter_files() -> list[Path]:
    """作用域 = git 受版本管理的文件（tracked + 已暂存），杜绝误伤 .tmp 等临时区。"""
    out: list[Path] = []
    r = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if r.returncode != 0:
        raise RuntimeError(f"git ls-files 失败：{r.stderr}")
    for rel in r.stdout.split("\0"):
        if not rel:
            continue
        p = (REPO / rel).resolve()
        if not p.is_file():
            continue
        if p in NEVER_TOUCH:
            continue
        # 根 LICENSE 无扩展名，按名纳入
        if p.suffix.lower() not in TEXT_SUFFIXES and p.name != "LICENSE":
            continue
        out.append(p)
    return out


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def build_mapping(holder_cn: str, holder_en: str | None) -> list[tuple[str, str]]:
    en = holder_en or ""
    full_new = f"{holder_cn} ({en})" if en else holder_cn
    return [
        (BUSINESS_SIGNED, holder_cn),
        (BUSINESS_GENERIC, holder_cn),
        (PARTY_B_BLANK, f"乙方：{holder_cn}"),
        (PLACEHOLDER_FULL, full_new),   # 全形式优先于裸中文形式
        (PLACEHOLDER_CN, holder_cn),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="D-3/D-4 主体定名一键替换")
    ap.add_argument("--holder", required=True, help="注册主体中文全称（法务提供）")
    ap.add_argument("--holder-en", default=None, help="注册主体英文名（可省略）")
    ap.add_argument("--apply", action="store_true", help="真正写入（默认 dry-run）")
    args = ap.parse_args(argv)

    holder = args.holder.strip()
    if not holder or holder == PLACEHOLDER_CN or "XX" in holder:
        print("[失败] --holder 疑似占位/臆测值，拒绝执行（D-4：不得编造公司名）")
        return 2
    mapping = build_mapping(holder, (args.holder_en or "").strip() or None)

    touched = 0
    total_hits = 0
    for path in iter_files():
        rel = path.relative_to(REPO)
        txt = _read(path)
        if txt is None:
            print(f"[跳过] 非 UTF-8/不可读：{rel}")
            continue
        new = txt
        hits: list[str] = []
        for old, rep in mapping:
            if old in new:
                hits.append(f"{old[:18]}…×{new.count(old)}")
                new = new.replace(old, rep)
        if new == txt:
            continue
        total_hits += len(hits)
        touched += 1
        print(f"[{'改' if args.apply else '拟改'}] {rel}: {'; '.join(hits)}")
        if args.apply:
            path.write_text(new, encoding="utf-8", newline="")

    if touched == 0:
        print("[结果] 无命中——占位主体已不存在？（grep 复核后再定）")
        return 1

    # 复核：除 NEVER_TOUCH 外，全仓占位串应为 0 命中
    if args.apply:
        residual = 0
        for path in iter_files():
            txt = _read(path)
            if txt and PLACEHOLDER_CN in txt:
                print(f"[告警] 仍含占位：{path.relative_to(REPO)}")
                residual += 1
        if residual:
            return 1
        print(f"[OK] 替换 {touched} 文件；残留占位 0。后续必做："
              f"①全量 pytest ②scripts/release_oss.sh ③勾销 checklist 第1项"
              f"④decisions.md 手工追加定名关闭记录（本工具不改写决策留痕）")
    else:
        print(f"[dry-run] 拟改 {touched} 文件；--apply 执行（建议先 git 干净工作区）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
