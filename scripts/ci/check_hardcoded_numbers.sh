#!/usr/bin/env bash
# STD-03 / G2（方案 §8 STD-03、§14 G2 硬编码监管数字 lint / BUG-ES9-005 关联）
# 监管数字必须走单源，禁止散落裸写：
#   - 裁判一致率阈值：backend/app/config.py JUDGE_AGREEMENT_THRESHOLD（唯一默认值出处）
#   - TC260 题量/百分比：deploy/standards/tc260.yaml，经 services/standards.py 加载
#     （standards.py 头注释自称"监管数字唯一入口"；其 L10/L198 的
#      "GB/T 45654 / TC260-003" 为加载器自身文档/错误文案 → 单源文件豁免）
#
# 判据（宁可保守，先读码定事实——2026-10 grep 全量定性）：
#   [a] backend/app 中含 0.85 的行，若同时呈"监管比较语义"
#       （pass_rate/agreement 与 < > >= <= 比较）→ 违规候选；
#   [b] engines 内 14 处 0.85 为评分算法常量（score/combined/ratio 上下文），
#       judge_pipeline L96/98 为 getattr 默认值/异常 fallback —— 模式豁免；
#   [c] frontend/src 命中仅 rgba 颜色、*.test.jsx mock、UI 文案 —— 扫描时排除；
#   [d] 已知待修违规入 BASELINE 基线豁免（登记已知，修复工单销项后必须从基线删除）：
#       backend/app/commercial/routers/report_shares.py  risk_level 兜底阈值 0.85/0.6
#       backend/app/routers/report_ext.py                同上
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
cd "$REPO_ROOT"

python - <<'PYEOF'
import re, sys
from pathlib import Path

root = Path(".")

# 单源文件（自身允许出现默认值/文案）
SOURCES = {"backend/app/config.py", "backend/app/services/standards.py"}

# 基线豁免（已知违规，带行内容指纹；文件再新增命中不会被基线吞掉）
BASELINE = {
    ("backend/app/commercial/routers/report_shares.py", "pass_rate < 0.85"),
    ("backend/app/commercial/routers/report_shares.py", "pass_rate < 0.6"),
    ("backend/app/routers/report_ext.py", "pass_rate < 0.85"),
    ("backend/app/routers/report_ext.py", "pass_rate < 0.6"),
}

# 监管比较语义：比率类变量与阈值字面量直接比较
REG_CMP = re.compile(r"(pass_rate|agreement_rate|consistency)\s*[<>]=?\s*0?\.\d")
# 模式豁免：getattr/except fallback/评分常量上下文
EXEMPT_PAT = re.compile(
    r"getattr\(|return 0\.85$|score\s*[=<>]|combined|ratio\s*>|"
    r"\(0\.85,|0\.85\s*\*|^\s*#"
)

violations, stale = [], set(BASELINE)
for py in sorted(root.glob("backend/app/**/*.py")):
    rel = py.as_posix()
    if rel in SOURCES:
        continue
    for n, ln in enumerate(py.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not re.search(r"0\.85|0\.6\b|TC260-\d|45654", ln):
            continue
        if not REG_CMP.search(ln):
            continue  # 非监管比较语义（engines 评分常量等）不属本门禁
        if EXEMPT_PAT.search(ln):
            continue
        key = (rel, ln.strip().rstrip(":"))
        hit = next((b for b in BASELINE if b[0] == rel and b[1] in ln), None)
        if hit:
            stale.discard(hit)
        else:
            violations.append(f"{rel}:{n}: {ln.strip()[:90]}")

# 反向断言：基线条目若已被修复删除而未更新基线 → 提示防基线腐化
if violations:
    print("FAIL: 监管数字硬编码（STD-03）：")
    [print("  " + v) for v in violations]
    sys.exit(1)
print(f"PASS: 硬编码监管数字 lint（单源 config.py/standards.py + 基线豁免 {len(BASELINE)} 条，"
      f"新增违规 0；其中 {len(stale)} 条基线已陈旧待清理——如为已修复项请同步删除基线）")
PYEOF
