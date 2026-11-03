#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""FRZ-02 依赖黑名单单源校验（方案 §8 FRZ-02 / §14 G5 / BUG-ES9-009）.

单源 = config/scope-freeze.yaml 的 dependency_blacklist 段
（本仓已有该文件，不再另建 freeze-blacklist.yaml，避免双源；任务书早期设想的
 config/freeze-blacklist.yaml 以本脚本读 scope-freeze.yaml 达成同效）。

两项断言：
  [1] 黑名单包不得出现在依赖事实源：
      scan_targets 逐一扫描；optional 目标（本仓无 pyproject.toml/uv.lock/
      pnpm-lock.yaml——依赖事实源为 requirements.txt，见 AGENTS.md 锁3 说明）
      不存在时跳过并登记。
  [2] 黑名单字面量不得内联复制进其他门禁脚本（防多源漂移）：
      scripts/ci/check_*.{sh,py} 中除本脚本外不得出现包名字面量；
      AGENTS.md 为 source_of_truth 允许含字面量（其检查命令示例）。

解析：优先 PyYAML（本机 6.0.3 实测可用）；导入失败降级为针对本文件
结构的正则解析（字段极简：path/kind/optional/包名列表）。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "scope-freeze.yaml"


def load_blacklist() -> dict:
    """返回 {frontend_packages, backend_packages, scan_targets[]}."""
    text = CONFIG.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        return data["dependency_blacklist"]
    except ImportError:
        # 降级解析：仅认本文件既定缩进结构
        blk: dict = {"frontend_packages": [], "backend_packages": [], "scan_targets": []}
        section = None
        cur: dict = {}
        for ln in text.splitlines():
            if re.match(r"^  frontend_packages:", ln):
                section, blk["frontend_packages"] = "fe", None
                continue
            if re.match(r"^  backend_packages:", ln):
                section = "be"
                continue
            if re.match(r"^  scan_targets:", ln):
                section, blk["scan_targets"], cur = "st", [], {}
                continue
            if section and re.match(r"^\S", ln):
                section = None
            if section in ("fe", "be"):
                m = re.match(r"^    - \"?'?([A-Za-z@0-9._/-]+)\"?'?$", ln)
                if m:
                    blk["frontend_packages" if section == "fe" else "backend_packages"].append(m.group(1))
            elif section == "st":
                m = re.match(r"^    - path: (.+)$", ln)
                if m:
                    if cur:
                        blk["scan_targets"].append(cur)
                    cur = {"path": m.group(1).strip()}
                    continue
                m = re.match(r"^      (\w+): (.+)$", ln)
                if m and cur is not None:
                    cur[m.group(1)] = True if m.group(2) == "true" else m.group(2)
        if cur:
            blk["scan_targets"].append(cur)
        return blk


def main() -> int:
    if not CONFIG.exists():
        print("FAIL: 单源文件 config/scope-freeze.yaml 缺失（FRZ-03 连锁）")
        return 1
    blk = load_blacklist()
    fe, be = set(blk["frontend_packages"]), set(blk["backend_packages"])
    allpkgs = fe | be
    if not (fe and be and blk["scan_targets"]):
        print("FAIL: dependency_blacklist 段解析为空或残缺（结构漂移）")
        return 1

    errs, skipped = [], []
    for tgt in blk["scan_targets"]:
        p = ROOT / tgt["path"]
        if not p.exists():
            if tgt.get("optional"):
                skipped.append(tgt["path"])
                continue
            errs.append(f"必需事实源缺失: {tgt['path']}")
            continue
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for n, ln in enumerate(lines, 1):
            low = ln.lower()
            for pkg in allpkgs:
                # requirements 行首锚定（AGENTS.md 锁3 口径）；npm 文件按包名 token 匹配
                if pkg.lower() in low:
                    if tgt["kind"] == "requirements" and not re.match(r"^\s*" + re.escape(pkg), ln, re.I):
                        continue
                    errs.append(f"{tgt['path']}:{n} 命中黑名单 {pkg}: {ln.strip()[:70]}")

    # [2] 字面量不内联到其他门禁脚本
    for f in sorted((ROOT / "scripts" / "ci").glob("check_*")):
        if f.name == Path(__file__).name:
            continue
        body = f.read_text(encoding="utf-8", errors="replace")
        for pkg in allpkgs:
            if pkg in body:
                errs.append(f"黑名单字面量 {pkg} 内联于 {f.name}（应引用单源）")

    if errs:
        print("FAIL: 依赖黑名单多源/命中（FRZ-02）：")
        [print("  -", e) for e in errs]
        return 1
    print(f"PASS: 黑名单单源（scope-freeze.yaml，前端 {len(fe)} 项/后端 {len(be)} 项；"
          f"扫描 {len(blk['scan_targets']) - len(skipped)} 源，optional 跳过 {skipped}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
