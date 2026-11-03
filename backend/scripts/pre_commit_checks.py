# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""优化12 §11.4 / §14 T9（机制硬化）：pre-commit 统一检查入口（Python，跨平台可测）。

由 `scripts/ci/pre-commit` 钩子调用（`install-hooks.ps1 -Local` 部署），也可手动
在仓库根执行：``python backend/scripts/pre_commit_checks.py``。

检查项（编号对应方案条款）：
  C1 inti.sql 只追加/骤减阻断（§11.4-1：该文件曾被清空为 0 字节）——
     staged diff 中出现删除行即 FAIL（新段只追加；等量改写也拒，修订走逃生门）；
  C2 tc260.yaml 块式形状 lint（§6.1/§5.1，import 复用 lint_std_yaml_shape.check_text，
     对 staged blob 判定，非工作区文本）；
  C3 bank_category 对齐 lint（§7.3，调 lint_std_bank_align.main，读工作区文件；
     仅当 inti.sql 或 tc260.yaml 在 staged 中时执行）；
  C4 三方一致性校验（§11.3，subprocess 跑 sync_inti_sql.py；仅当 schema 相关文件
     staged 时执行；DB 不可达时该脚本自动降级 two-way 并如实声明）；
  C5 锁 1 · engines/ 新增 .py 检测（AGENTS.md 锁 1 / FRZ-01；staged 新增 + untracked；
     提交信息豁免在 CI 面 check_engine_freeze.sh 逐 commit 判，本处用 FREEZE_EXEMPT 逃生门）；
  C6 锁 2/3 · 依赖黑名单（复用 scripts/ci/check_blacklist_single_source.py 单源判定，
     本脚本内不内联任何黑名单字面量——FRZ-02 [2] 同源要求）；仅当依赖事实源 staged 时执行。
  C7 ES 令牌执法扫描（§10.2/§11.4-3，V8 增量口径：仅扫 git 变更面新增行；
     node 不可用时降级 skip，CI 面 mechanism-lints 兜底）；仅当 frontend/src 下
     .js/.jsx staged 时执行。

逃生门（与既有钩子口径一致，例外须自行在提交信息注明原因）：
  EVALSHIELD_SKIP_PRECOMMIT=1  整体跳过（钩子层已实现）
  INTI_GATE_SKIP=1             仅放行 C1（人工修订 inti.sql 历史行时使用）
  FREEZE_EXEMPT=<工单号>       仅放行 C5（与 check_engine_freeze.sh 同名变量同义）

退出码：0 = 全绿；1 = 存在 FAIL；2 = 环境错误（git 不可用等）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

INTI_SQL_REL = "database/inti.sql"
TC260_YAML_REL = "deploy/standards/tc260.yaml"
ENGINES_REL = "backend/app/engines"
# C4 触发面：schema 相关文件 staged 即跑（models / inti.sql / DDL）
SCHEMA_TRIGGERS = (
    "backend/app/models.py", INTI_SQL_REL, "backend/scripts/p1_ddl.sql",
)
# C6 触发面：依赖事实源
DEP_TRIGGERS = ("backend/requirements.txt", "frontend/package.json")

sys.path.insert(0, str(BACKEND))


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def git_ok() -> bool:
    return _git("rev-parse", "--is-inside-work-tree").returncode == 0


def staged_paths() -> list[str]:
    out = _git("diff", "--cached", "--name-only")
    if out.returncode != 0:
        return []
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


# --------------------------------------------------------------- C1 inti.sql ----

_DIFF_FILE_RE = re.compile(r"^diff --git a/(?P<a>\S+) b/(?P<b>\S+)$")


def split_diff_for_path(diff_text: str, path: str) -> str:
    """从多文件 unified diff 中抽出目标路径的文件段（含 diff --git 头）。"""
    seg: list[str] = []
    keep = False
    for ln in diff_text.splitlines():
        m = _DIFF_FILE_RE.match(ln)
        if m:
            keep = m.group("b") == path
        if keep:
            seg.append(ln)
    return "\n".join(seg)


def inti_append_violations(diff_text: str) -> list[str]:
    """C1 纯函数：inti.sql 段内出现删除行（非 --- 头）即违规——该文件只允许追加。"""
    seg = split_diff_for_path(diff_text, INTI_SQL_REL)
    if not seg:
        return []
    deleted = [ln[1:].rstrip() for ln in seg.splitlines()
               if ln.startswith("-") and not ln.startswith("---")]
    if not deleted:
        return []
    errs = [f"inti.sql 只追加约定被破坏：staged diff 含 {len(deleted)} 条删除行"
            "（该文件曾被清空为 0 字节，§11.4-1）。追加段请用尾部新 section；"
            "确需修订历史行设 INTI_GATE_SKIP=1 并在提交信息注明原因"]
    for d in deleted[:5]:
        errs.append("  删除行: " + d[:90])
    return errs


def inti_shrink_violation(head_lines: int, staged_lines: int) -> list[str]:
    """C1 兜底：即便删除行判据被跳过，行数骤降（< HEAD 的 90%）仍 FAIL。"""
    if head_lines <= 0 or staged_lines >= int(head_lines * 0.9):
        return []
    return [f"inti.sql 行数骤降：HEAD {head_lines} 行 → staged {staged_lines} 行（阻断，§11.4-1）"]


def check_inti() -> tuple[str, list[str]]:
    diff = _git("diff", "--cached", "--", INTI_SQL_REL).stdout
    if not diff.strip():
        return ("skip", [])
    if os.environ.get("INTI_GATE_SKIP") == "1":
        return ("skip(INTI_GATE_SKIP=1)", [])
    errs = inti_append_violations(diff)
    head = _git("show", f"HEAD:{INTI_SQL_REL}")
    staged = _git("show", f":{INTI_SQL_REL}")
    if head.returncode == 0 and staged.returncode == 0:
        errs += inti_shrink_violation(
            len(head.stdout.splitlines()), len(staged.stdout.splitlines()))
    return ("fail" if errs else "pass"), errs


# ---------------------------------------------------------- C2 yaml 形状 lint ----

def check_yaml_shape() -> tuple[str, list[str]]:
    """对 staged blob 跑 §6.1 块式形状断言（无 staged 变更则跳过）。"""
    paths = staged_paths()
    if TC260_YAML_REL not in paths:
        return ("skip", [])
    blob = _git("show", f":{TC260_YAML_REL}")
    text = blob.stdout if blob.returncode == 0 else \
        (REPO / Path(TC260_YAML_REL)).read_text(encoding="utf-8")
    from scripts.lint_std_yaml_shape import check_text
    errors, _n = check_text(text)
    return ("fail" if errors else "pass"), [f"yaml 形状（§6.1）：{e}" for e in errors]


# ------------------------------------------------------------ C3/桥接 subprocess ----

def _run_script(argv: list[str], label: str) -> tuple[str, list[str]]:
    proc = subprocess.run(argv, cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode == 0:
        return "pass", []
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return "fail", [f"{label} 退出码 {proc.returncode}"] + ["  " + d for d in detail[:12]]


def check_bank_align() -> tuple[str, list[str]]:
    paths = set(staged_paths())
    if not (paths & {INTI_SQL_REL, TC260_YAML_REL}):
        return ("skip", [])
    return _run_script([sys.executable, "backend/scripts/lint_std_bank_align.py"],
                       "lint_std_bank_align（§7.3）")


def check_sync_inti() -> tuple[str, list[str]]:
    paths = set(staged_paths())
    if not (paths & set(SCHEMA_TRIGGERS)):
        return ("skip", [])
    return _run_script([sys.executable, "backend/scripts/sync_inti_sql.py"],
                       "sync_inti_sql（§11.3）")


# ------------------------------------------------------------------ C5 锁 1 ----

def engines_new_files(others_out: str, staged_added_out: str) -> list[str]:
    """C5 纯函数：untracked + staged 新增中命中 engines/*.py 的路径清单。

    git 输出恒为正斜杠相对路径（Windows 亦然），无需反斜杠分支。
    """
    hits = []
    prefix = ENGINES_REL + "/"
    for out in (others_out, staged_added_out):
        for ln in out.splitlines():
            p = ln.strip()
            if p.startswith(prefix) and p.endswith(".py"):
                hits.append(p)
    return sorted(set(hits))


def check_engine_freeze_lock() -> tuple[str, list[str]]:
    if os.environ.get("FREEZE_EXEMPT"):
        return ("skip(FREEZE_EXEMPT)", [])
    others = _git("ls-files", "--others", "--exclude-standard", "--", ENGINES_REL)
    added = _git("diff", "--cached", "--diff-filter=A", "--name-only", "--", ENGINES_REL)
    hits = engines_new_files(others.stdout, added.stdout)
    if hits:
        return "fail", ["锁 1（AGENTS.md/FRZ-01）：engines/ 出现新增 .py 文件"] + \
            ["  " + h for h in hits] + \
            ["  解冻须书面工单：提交带 freeze-exempt: <工单号>（CI 面判定）或本地 FREEZE_EXEMPT"]
    return "pass", []


# -------------------------------------------------------------- C6 锁 2/3 ----

def check_dependency_blacklist() -> tuple[str, list[str]]:
    paths = set(staged_paths())
    if not (paths & set(DEP_TRIGGERS)):
        return ("skip", [])
    return _run_script(
        [sys.executable, "scripts/ci/check_blacklist_single_source.py"],
        "依赖黑名单单源（锁 2/3，FRZ-02）")


# ------------------------------------------------------------------ C7 令牌扫描 ----

def check_es_tokens() -> tuple[str, list[str]]:
    staged = staged_paths()
    hit = [p for p in staged
           if p.startswith("frontend/src/") and p.endswith((".js", ".jsx"))]
    if not hit:
        return ("skip", [])
    try:
        proc = subprocess.run(
            ["node", "scripts/lint_es_tokens.mjs"],
            cwd=REPO / "frontend", capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        return ("skip(node 不可用，CI 面兜底)", [])
    if proc.returncode == 0:
        return "pass", []
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return "fail", ["lint_es_tokens（§10.2）退出码 %d" % proc.returncode] + \
        ["  " + d for d in detail[:12]]


CHECKS = (
    ("C1 inti.sql 只追加/骤减（§11.4-1）", check_inti),
    ("C2 tc260.yaml 块式形状（§6.1）", check_yaml_shape),
    ("C3 bank_category 对齐（§7.3）", check_bank_align),
    ("C4 三方一致性（§11.3）", check_sync_inti),
    ("C5 锁 1 引擎目录冻结", check_engine_freeze_lock),
    ("C6 锁 2/3 依赖黑名单（FRZ-02）", check_dependency_blacklist),
    ("C7 ES 令牌执法扫描（§10.2）", check_es_tokens),
)


def main() -> int:
    if not git_ok():
        print("[错误] 非 git 工作树或 git 不可用", file=sys.stderr)
        return 2
    fail = False
    for name, fn in CHECKS:
        try:
            status, errs = fn()
        except Exception as exc:  # noqa: BLE001 机制脚本单点异常不吞、显式 FAIL
            status, errs = "fail", [f"检查异常：{type(exc).__name__}: {exc}"]
        mark = {"pass": "PASS", "fail": "FAIL"}.get(status, status)
        print(f"[pre-commit] {mark:8s} {name}")
        for e in errs:
            print("  " + e)
        if status == "fail":
            fail = True
    if fail:
        print("pre-commit-checks: 违规即止（勿用 --no-verify 绕过；CI 面仍会拦截）",
              file=sys.stderr)
        return 1
    print("pre-commit-checks: 全部通过/跳过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
