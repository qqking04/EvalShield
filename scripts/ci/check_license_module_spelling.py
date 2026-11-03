#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LIC-02 拼写漂移 lint（方案 §8 LIC-02 / §14 脚本资产清单 / BUG-ES9-005）.

校验签发端 scripts/issue_license.py 与消费端 backend/app/enterprise/license.py
的 License payload 字段名集合一致，防止 "license_no / licence_no" 之类
单数字母漂移导致验签通过后字段静默丢失。

判据（先读码定事实）：
- 签发端 build_payload（L155-169）以 dict 字面量 + payload["k"]=... 写入；
- 消费端 verify_license（L154-177）以 payload.get("k") / payload["k"] 读取；
- 两侧用 ast 静态提取键名集合，断言"契约核心字段"
  {license_no, edition, features, expires_at, fp} 同时在两侧出现；
- 非核心字段（customer/issued_at/seats/issuer 为签发侧元数据、消费侧只读子集）
  不要求对称，但消费侧读取的每个键必须 ⊆ 签发侧写入键集（防消费幽灵字段）。
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ISSUER = ROOT / "scripts" / "issue_license.py"
VERIFIER = ROOT / "backend" / "app" / "enterprise" / "license.py"

CORE = {"license_no", "edition", "features", "expires_at", "fp"}


def literal_keys_from_func(tree: ast.Module, func_name: str) -> set[str]:
    """提取函数内 dict 字面量键 + obj['k']=... 形式下标字符串键."""
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict):
                    keys |= {k.value for k in sub.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str):
                            keys.add(t.slice.value)
    return keys


def consumed_keys(tree: ast.Module) -> set[str]:
    """verify 侧 payload.get("k") / payload["k"] / payload.get('k') 读取键."""
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == "payload" and node.args \
                and isinstance(node.args[0], ast.Constant):
            keys.add(node.args[0].value)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id == "payload" and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            keys.add(node.slice.value)
    return keys


def main() -> int:
    if not ISSUER.exists() or not VERIFIER.exists():
        print("FAIL: 契约文件缺失", ISSUER if not ISSUER.exists() else VERIFIER)
        return 1
    issued = literal_keys_from_func(ast.parse(ISSUER.read_text(encoding="utf-8")), "build_payload")
    verified = consumed_keys(ast.parse(VERIFIER.read_text(encoding="utf-8")))
    if not issued:
        print("FAIL: issue_license.py 未定位到 build_payload 键集（结构漂移，需人工更新脚本）")
        return 1
    errs = []
    missing_core_iss = CORE - issued
    missing_core_ver = CORE - verified
    if missing_core_iss:
        errs.append(f"签发端缺核心字段: {sorted(missing_core_iss)}")
    if missing_core_ver:
        errs.append(f"消费端缺核心字段: {sorted(missing_core_ver)}")
    ghost = verified - issued
    if ghost:
        errs.append(f"消费端读取幽灵字段（签发端从不写入）: {sorted(ghost)}")
    if errs:
        print("FAIL: License payload 字段拼写/契约漂移（LIC-02）：")
        [print("  -", e) for e in errs]
        return 1
    print(f"PASS: license 契约一致（核心 {sorted(CORE)} 双侧在位；"
          f"签发键集={sorted(issued)} ⊇ 消费键集={sorted(verified)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
