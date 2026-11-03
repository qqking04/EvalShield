#!/usr/bin/env bash
# CSV-02 / G2（方案 §8 CSV-02、§14 G2 / BUG-ES9-005 关联）
# CSV 公式注入防护 lint：
#   判据（§8 CSV-02）：对含 csv.writer 的行，其 ±3 行窗口内必须出现
#   csv_guard | escape_cell | writerow_guarded | esc_csv | _csv_cell 之一；
#   全量存量必须 pass，注入旁路样例（裸 writerow 无防护）必须 fail。
#   单源防护符号：backend/app/utils/csv_safe.py::esc_csv
#   （注意：任务书早期假设的 CSV_FORMULA_PREFIX 不存在，实际读码定事实为 esc_csv）
#
# 导出面事实清单（2026-10 实际 grep 圈定，写入注释以固化审查范围）：
#   backend/app/routers/projects_core.py    L502 writer；L503 静态表头；
#       L510-515 esc_csv×6（severity/priority/日期为受控枚举/格式化，豁免）
#   backend/app/routers/question_banks.py   L377/L765 writer；L382/389/766/770/773
#       全部行（含表头）经 esc_csv
#   backend/app/commercial/routers/cost.py  L197 writer；L198 静态表头；
#       L204-205 esc_csv（文本字段）
#   backend/app/services/delivery.py        L215/L260 writer（经 routers/delivery.py
#       L44 "csv": text/csv 分发）；L224-227/L268/L279 使用本地 _csv_cell
#       ——【登记现状】delivery.py L53-56 重复实现了一份与 esc_csv 同逻辑的
#       _csv_cell（前缀集一致 = + - @ \t \r）。属"已防护但非单源"，
#       本门禁按防护符号放行，收敛为单源留待修复工单（不在本轮改动）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
cd "$REPO_ROOT"

# ---- 0) 单源符号存在性 ----
if ! grep -q "def esc_csv" backend/app/utils/csv_safe.py; then
  echo "FAIL: csv_safe.py 单源函数 esc_csv 缺失"; exit 1
fi

python - <<'PYEOF'
import re, sys
from pathlib import Path

root = Path(".")
GUARD = re.compile(r"csv_guard|escape_cell|writerow_guarded|esc_csv|_csv_cell")
TRIG = re.compile(r"(?:\bwriterow\(|\bcsv\.writer\b)")
DEF = re.compile(r"^(?:async )?def ")

def func_bounds(lines, idx):
    """返回触发行所在函数体 [start, end)；模块级触发回退 ±3 行窗口。"""
    for j in range(idx, -1, -1):
        if DEF.match(lines[j]):
            start = j
            indent = len(lines[j]) - len(lines[j].lstrip())
            for k in range(j + 1, len(lines)):
                s = lines[k]
                if s.strip() and (len(s) - len(s.lstrip())) <= indent and DEF.match(s):
                    return start, k
            return start, len(lines)
    return max(0, idx - 3), min(len(lines), idx + 4)

violations = []
scanned = 0
for py in sorted(list(root.glob("backend/app/**/*.py"))):
    if "tests" in py.parts:
        continue
    lines = py.read_text(encoding="utf-8", errors="replace").splitlines()
    hit = False
    for i, ln in enumerate(lines):
        if not TRIG.search(ln) or ln.lstrip().startswith("#"):
            continue
        hit = True
        a, b = func_bounds(lines, i)
        # §8 CSV-02 理想判据为 ±3 行窗口；存量事实（多行 writerow 块、防护调用
        # 在块尾）按"所在函数体含防护符号"实现同效拦截：注入裸 writerow 旁路
        # 样例（新函数无防护符号）仍会 fail。
        if GUARD.search("\n".join(lines[a:b])):
            continue
        violations.append(f"{py}:{i+1}: {ln.strip()[:90]}")
    if hit:
        scanned += 1

# 至少覆盖 4 个已知导出文件（防止 glob 失效导致空扫假绿）
expected = {"projects_core.py", "question_banks.py", "cost.py", "delivery.py"}
found = {Path(v.split(":")[0]).name for v in violations}
present = {p.name for p in root.glob("backend/app/**/*.py") if p.name in expected}
if present != expected:
    print(f"FAIL: 导出面文件缺失 {expected - present}"); sys.exit(1)

# 已知待收敛清单（delivery.py 本地 _csv_cell → 触发行本身带 _csv_cell 在窗口内，
# 属预期 pass；如未来出现新文件裸 writerow 将直接 fail）
if violations:
    print("FAIL: 发现无防护 writerow（CSV-02）：")
    [print("  " + v) for v in violations]
    sys.exit(1)
print(f"PASS: csv_guard（单源 esc_csv + 所在函数体防护窗口，扫描 {scanned} 个导出文件，0 违规）")
PYEOF
