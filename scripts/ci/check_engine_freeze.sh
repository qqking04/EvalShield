#!/usr/bin/env bash
# FRZ-01（AGENTS.md 锁 1 + 方案 §8 FRZ-01 / §13 D-19 / BUG-ES9-005）
# 引擎目录冻结门禁：
#   A) backend/app/engines/ 下新增 .py 文件 → 对应 commit msg 必须含 "freeze-exempt:"
#   B) D-19：backend/app/engines/registry.py 登记表区域
#      （_COMMUNITY_MODULES / _COMMERCIAL_MODULES）登记行 +/- 变更 → 同锁
# 判据分三层（纯 git diff HEAD~1..HEAD 会漏工作区变更，纯 git diff 漏 untracked）：
#   [1] untracked：git ls-files --others --exclude-standard -- engines/
#   [2] 工作区已暂存/未暂存新增：git diff --diff-filter=A --name-only HEAD -- engines/
#   [3] commit 区间（默认 HEAD~1..HEAD，可 --since <rev> 覆盖）：
#       逐 commit 查新增引擎文件与 registry 登记行变更，豁免标记=该 commit msg
# 静态约束（目录/豁免标记/登记区）单源：config/scope-freeze.yaml engine_freeze 段。
# 本地逃生门：环境变量 FREEZE_EXEMPT=<工单号> 整体放行（仅供开发机调试，CI 不设）。
set -euo pipefail
export PYTHONIOENCODING=utf-8   # Windows 控制台 GBK 环境下内嵌 python 中文安全

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
cd "$REPO_ROOT"

SINCE="HEAD~1"
while [ $# -gt 0 ]; do
  case "$1" in
    --since) SINCE="$2"; shift 2 ;;
    *) echo "用法: $0 [--since <rev>]"; exit 2 ;;
  esac
done

ENGINE_DIR="backend/app/engines"
REGISTRY="$ENGINE_DIR/registry.py"
EXEMPT_MARKER="freeze-exempt:"
# 登记区名单与 config/scope-freeze.yaml engine_freeze.registry_regions 同步
# （脚本内不做 yaml 解析：该单源一致性由 check_blacklist_single_source.py /
#   test_es9_scope_freeze_file.py 把关，此处硬校验消费端行为）
REG_REGION_A="_COMMUNITY_MODULES"
REG_REGION_B="_COMMERCIAL_MODULES"

if [ "${FREEZE_EXEMPT:-}" != "" ]; then
  echo "SKIP: FREEZE_EXEMPT=${FREEZE_EXEMPT}（本地逃生门，CI 禁用）"
  exit 0
fi

FAIL=0
report() { echo "FAIL: $*"; FAIL=1; }

# ---- [1] untracked 新文件（工作区直接创建、未 commit） ----
UNTRACKED="$(git ls-files --others --exclude-standard -- "$ENGINE_DIR/" | grep '\.py$' || true)"
if [ -n "$UNTRACKED" ]; then
  report "engines/ 存在未跟踪新 .py 文件（锁 1 禁止新增引擎）："
  echo "$UNTRACKED" | sed 's/^/  /'
fi

# ---- [2] 工作区 vs HEAD 的新增（git add 未 commit 也算） ----
WORKDIFF="$(git diff --diff-filter=A --name-only HEAD -- "$ENGINE_DIR/" | grep '\.py$' || true)"
if [ -n "$WORKDIFF" ]; then
  report "工作区相对 HEAD 新增引擎文件："
  echo "$WORKDIFF" | sed 's/^/  /'
fi
# 工作区 registry 登记区变更：登记表为 list 字面量，逐字比对 HEAD vs 工作区
if git diff --quiet HEAD -- "$REGISTRY"; then
  : # registry 无任何改动，跳过登记区比对
else
  # 有改动：判断改动是否触及 _COMMUNITY_MODULES/_COMMERCIAL_MODULES 列表块
  if python - "$REGISTRY" <<'PYEOF'
import re, subprocess, sys
registry = sys.argv[1]
head = subprocess.run(["git", "show", "HEAD:" + registry],
                      capture_output=True, text=True, check=True).stdout
work = open(registry, encoding="utf-8").read()
def blocks(text):
    out = {}
    for name in ("_COMMUNITY_MODULES", "_COMMERCIAL_MODULES"):
        # 匹配 name = [ ... ] 列表块（登记项为字符串字面量行）
        m = re.search(rf"^{name}\s*=\s*\[.*?^\]", text, re.M | re.S)
        out[name] = m.group(0) if m else None
    return out
b1, b2 = blocks(head), blocks(work)
same = b1 == b2
if not same:
    for k in b1:
        if b1[k] != b2[k]:
            print("登记表差异: " + str(k))
sys.exit(0 if same else 1)
PYEOF
  then :; else report "registry.py 登记表（_COMMUNITY_MODULES/_COMMERCIAL_MODULES）工作区变更未带豁免（D-19）"; fi
fi

# ---- [3] commit 区间逐 commit 检查 ----
for sha in $(git rev-list "$SINCE..HEAD" 2>/dev/null || true); do
  msg="$(git log -1 --format='%B' "$sha")"
  if echo "$msg" | grep -q "$EXEMPT_MARKER"; then continue; fi
  added="$(git diff-tree --no-commit-id --name-status -r --diff-filter=A "$sha" -- "$ENGINE_DIR/" | grep '\.py' || true)"
  if [ -n "$added" ]; then
    report "commit $sha 新增引擎文件且 msg 无 $EXEMPT_MARKER："
    echo "$added" | sed 's/^/  /'
  fi
  # D-19：该 commit 对 registry 登记表 list 项行（字符串字面量行）的 +/- 变更
  regchg="$(git diff-tree -p "$sha" -- "$REGISTRY" \
    | python -c "
import re, sys
text = sys.stdin.read()
# 仅匹配登记表 list 元素行：以 +/- 开头且含 'xxx' 或 \"xxx\" 后接 , 或 ]
pat = re.compile(r'''['\"][A-Za-z0-9_]+['\"]\s*[,\]]''')
chg = [l for l in text.splitlines()
       if l[:1] in ('+', '-') and l[:3] not in ('+++', '---') and pat.search(l)]
print(chr(10).join(chg))
" || true)"
  if [ -n "$regchg" ]; then
    report "commit $sha 变更 registry.py 登记行且 msg 无 $EXEMPT_MARKER（D-19）："
    echo "$regchg" | sed 's/^/  /'
  fi
done

if [ "$FAIL" -eq 0 ]; then
  echo "PASS: 引擎冻结锁（FRZ-01 + D-19）——区间 $SINCE..HEAD 无违规新增/登记变更"
else
  echo "RESULT: FAIL（FRZ-01）"
  exit 1
fi
