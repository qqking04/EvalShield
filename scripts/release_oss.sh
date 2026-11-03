#!/usr/bin/env bash
# EvalShield 开源发版剥离脚本（规划 §12.6）
#
# 用途：从当前工作树导出可公开发布的 OSS 发行包，剥离企业闭源实现与私有数据。
# 分层原则（§12.7）：
#   - 代码都在、没授权就关：feature 闸门与 license API 保留在开源包中；
#   - 闭源实现剥离：app/enterprise/license.py（验签核心）替换为 community 桩，
#     license_cli.py（签发工具，属签发者本机）整文件删除；
#   - 私有数据剥离：客户订单、商业文档、运行期上传、本机密钥路径。
#
# 用法：
#   ./scripts/release_oss.sh [输出目录]     # 默认 ./dist/oss
#
# 产物：
#   <输出目录>/evalshield-oss-<版本>/       # 剥离后的源码树
#   <输出目录>/evalshield-oss-<版本>.tar.gz # 发行包
#   <输出目录>/evalshield-oss-<版本>.tar.gz.sha256
#
# 退出码：0 成功；1 剥离/自检失败
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="${1:-$ROOT_DIR/dist/oss}"
# Git Bash/MSYS + Windows 原生 python/node 互操作：Msys 风格路径(/x/...)转 Windows 路径，
# 供 $PY / node 使用；tar 等 Msys 工具仍用原路径
to_winpath() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; return; fi
  case "$1" in
    /[a-zA-Z]/*) printf '%s:%s' "$(string_upper "$(printf '%s' "${1:1:1}")")" "${1:2}" ;;
    *) printf '%s' "$1" ;;
  esac
}
string_upper() { printf '%s' "$1" | tr '[:lower:]' '[:upper:]'; }
VERSION="$(grep -m1 'APP_VERSION:' backend/app/config.py 2>/dev/null | sed -E 's/.*"([^"]+)".*/\1/' || true)"
VERSION="${VERSION:-0.0.0-dev}"
PKG="evalshield-oss-${VERSION}"
STAGE="$OUT_DIR/$PKG"
# Windows 原生 python/node 使用的路径形态（Msys 工具继续用 "$STAGE"）
STAGE_WIN="$(to_winpath "$STAGE")"

echo "[1/7] 准备发布目录 $STAGE"
# OBS-2：失败运行不得残留被污染的半成品产物（后续 P4 段会扫到脏文件）
trap '[ "$?" -ne 0 ] && rm -rf "$STAGE"' EXIT
PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  if command -v python3 >/dev/null 2>&1; then PY=python3
  elif command -v python >/dev/null 2>&1; then PY=python
  else echo "FAIL: 需要 python3/python 用于剥离自检"; exit 1; fi
fi
rm -rf "$STAGE"
mkdir -p "$STAGE"

# 以工作树为单一事实源导出（enterprise/ 等闭源层按规划不入公共 git，
# 故不能用 git archive HEAD——那会漏掉待剥离的闭源文件本身）
EXCLUDES=(
  --exclude='./.git' --exclude='./.tmp' --exclude='./frontend/node_modules'
  --exclude='./node_modules'
  --exclude='./.tmp_walkthrough' --exclude='./frontend/.vitest-nav.json'
  --exclude='__pycache__' --exclude='./dist' --exclude='./.venv'
  --exclude='./frontend/dist' --exclude='./backend/data'
  --exclude='./work' --exclude='./scripts/content_gen/output'
  --exclude='.pytest_cache'
  --exclude='./backend/deploy/RUNBOOK.md'
  --exclude='./backend/data/attachments'
  --exclude='./backend/data/src' --exclude='./tests/_ui_shots'
  --exclude='./docs/qa' --exclude='./.env' --exclude='./backend/.env' --exclude='*.lic'
  --exclude='./backend/tests' --exclude='./tests'
  --exclude='./deploy/ms-playwright'
  --exclude='./backend/app/commercial'
  --exclude='./backend/app/enterprise/license.py'
  --exclude='./backend/scripts/license_cli.py'
  --exclude='./scripts/issue_license.py'
  --exclude='./scripts/ci/publish-oss.ps1'
  --exclude='./backend/scripts/real_tool_self_test.py'
  --exclude='./backend/scripts/self_test_model_gateway.py'
  --exclude='./backend/cov_report.txt'
  --exclude='./frontend/src/pages/commercial'
  --exclude='./frontend/src/pages/platform'
  --exclude='./.trae-html-share-packages'
  --exclude='*.log'
)
if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude='.git' --exclude='.tmp' --exclude='node_modules' --exclude='__pycache__' \
    --exclude='.tmp_walkthrough' --exclude='frontend/.vitest-nav.json' \
    --exclude='dist' --exclude='.venv' --exclude='frontend/dist' \
    --exclude='backend/data' --exclude='work' --exclude='scripts/content_gen/output' \
    --exclude='.pytest_cache' --exclude='backend/deploy/RUNBOOK.md' \
    --exclude='backend/data/attachments' --exclude='backend/data/src' \
    --exclude='tests/_ui_shots' --exclude='docs/qa' \
    --exclude='.env' --exclude='backend/.env' --exclude='*.lic' \
    --exclude='backend/tests' --exclude='tests' \
    --exclude='deploy/ms-playwright' \
    --exclude='backend/app/commercial' \
    --exclude='backend/app/enterprise/license.py' \
    --exclude='backend/scripts/license_cli.py' \
    --exclude='scripts/issue_license.py' \
    --exclude='scripts/ci/publish-oss.ps1' \
    --exclude='backend/scripts/real_tool_self_test.py' \
    --exclude='backend/scripts/self_test_model_gateway.py' \
    --exclude='backend/cov_report.txt' \
    --exclude='frontend/src/pages/commercial' \
    --exclude='frontend/src/pages/platform' \
    --exclude='.trae-html-share-packages' \
    --exclude='*.log' \
    "$ROOT_DIR/" "$STAGE/"
elif command -v tar >/dev/null 2>&1; then
  ( cd "$ROOT_DIR" && tar "${EXCLUDES[@]}" -cf - . ) | ( cd "$STAGE" && tar -xf - )
else
  echo "FAIL: 需要 rsync 或 tar 用于导出工作树"; exit 1
fi

echo "[2/7] 校验商业码物理缺席（版本隔离 B12-②：闸门=目录不存在，非桩替换）"
if [[ -e "$STAGE/backend/app/commercial" ]]; then
  echo "FAIL: backend/app/commercial 仍在导出树中（排除规则失效）"; exit 1
fi
# enterprise/license.py（闭源验签核心）不随包发布；features.py 能力位桩保留（开源面引用）
if [[ -e "$STAGE/backend/app/enterprise/license.py" ]]; then
  echo "FAIL: backend/app/enterprise/license.py 未剥离"; exit 1
fi
# O-1（优化15 §5.1）：签发 CLI 仅存签发机/私有仓，公共投影存在即 FAIL
if [[ -e "$STAGE/scripts/issue_license.py" ]]; then
  echo "FAIL: scripts/issue_license.py 未剥离（签发工具仅存签发机，§5.5.3-5 硬规）"; exit 1
fi
# 优化15 推荐项：发布通道脚本含本地绝对路径/流程细节，不入公共投影（Runbook §9 唯一通道=私有仓内执行）
if [[ -e "$STAGE/scripts/ci/publish-oss.ps1" ]]; then
  echo "FAIL: scripts/ci/publish-oss.ps1 未剥离（发布通道脚本仅存私有仓）"; exit 1
fi
# 优化15：内部分享包/运行日志存在即 FAIL（增量发布实测混入面，2026-11-03）
if [[ -e "$STAGE/.trae-html-share-packages" ]]; then
  echo "FAIL: .trae-html-share-packages 未剥离（内部研究报告分享包）"; exit 1
fi
if find "$STAGE" -name '*.log' -print -quit 2>/dev/null | grep -q .; then
  echo "FAIL: 发布树残留 *.log 运行日志"; find "$STAGE" -name '*.log' | head -10; exit 1
fi
# 优化15 D1：边界外商业页目录（saas-only platform 运营页）存在即 FAIL
if [[ -e "$STAGE/frontend/src/pages/platform" ]]; then
  echo "FAIL: frontend/src/pages/platform 未剥离（边界外商业页目录）"; exit 1
fi
rm -f  "$STAGE/backend/scripts/license_cli.py"
rm -rf "$STAGE/.github" "$STAGE/.gitlab-ci.yml"   # 私有仓 CI 资产不外发（OSS 投影，仓库清理方案 §2）
# O-3（优化15 §5.1）：公共仓自带最小自检 CI（L3 闸门），模板落 .github/workflows/ci.yml
mkdir -p "$STAGE/.github/workflows"
cp "$ROOT_DIR/scripts/oss-ci.yml" "$STAGE/.github/workflows/ci.yml"
echo "  - commercial/ 缺席 OK；license_cli.py 已移除；公共 CI 模板已注入"

echo "[2b/7] 前端商业页剥离（strip_fe.js，F-build 联动）"
if [[ -d "$STAGE/frontend" ]]; then
  node "$STAGE_WIN/frontend/scripts/strip_fe.js" "$STAGE_WIN/frontend" || { echo "FAIL: strip_fe.js 执行失败"; exit 1; }
else
  echo "FAIL: 导出树缺 frontend/"; exit 1
fi

echo "[2c/7] 开源面 app.commercial 引用扫描（B12-③，防 B9 漏改）"
HITS="$(grep -RnE "app\.commercial|from \.commercial" "$STAGE/backend/app" --include=*.py || true)"
if [[ -n "$HITS" ]]; then
  # 允许：函数/try 块内的惰性 import（缩进行，配 ImportError 降级）；
  # FAIL：任何模块级（未缩进）import —— 那会在 OSS 树直接崩启动
  BAD="$(printf '%s\n' "$HITS" | grep -E ':[0-9]+:(from|import)[[:space:]]|:[0-9]+:[a-zA-Z_]' || true)"
  if [[ -n "$BAD" ]]; then
    echo "FAIL: 开源面存在模块级 app.commercial import："; printf '%s\n' "$BAD"; exit 1
  fi
fi
echo "  - 无 commercial import 残留"

echo "[3/7] 剥离私有数据与运行期产物"
# 排除保险：无论导出工具语义如何，发布树内任何 .env（含真实密钥）一律物理删除
find "$STAGE" -maxdepth 2 -name '.env' -type f -print -delete 2>/dev/null || true
rm -f  "$STAGE/backend/scripts/customer_orders.csv"
rm -rf "$STAGE/doc"                      # 商业/合同/交付类内部文档
rm -rf "$STAGE/backend/data"             # 运行期数据全剥（attachments/src/evidence/reports/deliver_shots——含客户交付报告）
rm -rf "$STAGE/work"                     # 内部研究工作目录（行业报告草稿等过程文档）
rm -rf "$STAGE/scripts/content_gen/output"  # 营销内容生成产物（内部运营面，工具本体保留）
rm -rf "$STAGE/.pytest_cache" "$STAGE/backend/.pytest_cache"
rm -f  "$STAGE/backend/deploy/RUNBOOK.md"   # 内部部署/迁移记录（含交付项目编号）
rm -rf "$STAGE/tests/_ui_shots" "$STAGE/docs/qa"
# 优化15：运行数据/内部过程目录存在即 FAIL（排除规则回退兜底）
for D in "$STAGE/backend/data" "$STAGE/work" "$STAGE/scripts/content_gen/output"; do
  if [[ -e "$D" ]]; then echo "FAIL: 内部数据/过程目录未剥净：$D"; exit 1; fi
done
# 仓库清理 B 类（2026-10-18，见 仓库清理与开源发布方案.md §2）：
# 内部过程文档面全剥——根级 md 只留 README/LICENSE 类，工具与验证目录整体剥离
rm -rf "$STAGE/docs" "$STAGE/.trae" "$STAGE/tests" "$STAGE/verification"
rm -f  "$STAGE/_audit_schema_u3.py"
find "$STAGE" -maxdepth 1 -name '*.md' ! -name 'README*' -delete
# 剥离断言：根级 md 只允许 README 类残留（回潮即 FAIL，勿依赖人工复核）
STRAY_MD="$(find "$STAGE" -maxdepth 1 -name '*.md' ! -name 'README*' || true)"
if [[ -n "$STRAY_MD" ]]; then echo "FAIL: 根级内部 md 剥离失败:"; printf '%s\n' "$STRAY_MD"; exit 1; fi
LEAKY="$(grep -rlE '创业执行方案|商业纠纷|客户管理|回款登记' "$STAGE" --include='*.md' 2>/dev/null || true)"
if [[ -n "$LEAKY" ]]; then echo "FAIL: 产物内 md 含商业敏感字面量:"; printf '%s\n' "$LEAKY" | head -20; exit 1; fi
# 优化15：设计/方案类文档全树禁入公共投影（不只根级——子目录同样执法）
DESIGN_MD="$(find "$STAGE" -name '*.md' \( -name '优化*' -o -name 'AGENTS.md' -o -name '*方案*' -o -name 'SPEC*' -o -name 'spec*' \) 2>/dev/null || true)"
if [[ -n "$DESIGN_MD" ]]; then echo "FAIL: 设计类文档混入发布树:"; printf '%s\n' "$DESIGN_MD" | head -20; exit 1; fi
rm -f  "$STAGE/backend/.coverage"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '*.pyc' -delete 2>/dev/null || true
echo "  - 客户订单 / doc+docs 文档 / 内部过程 md / .trae / 上传数据 / 测试截图 / 缓存 已清理"

echo "[3b/7] 产物密钥自动脱敏（优化7 T2：剥离层兜底，命中回显计数=泄露面回归哨兵）"
REDACT_HITS=0
while IFS= read -r f; do
  if grep -qE 'sk-[a-f0-9]{32}' "$f"; then
    echo "  redact: $f ($(grep -cE 'sk-[a-f0-9]{32}' "$f") 处)"
    sed -i -E 's/sk-[a-f0-9]{32}/sk-REPLACE_ME__FILL_YOUR_OWN/g' "$f"
    REDACT_HITS=$((REDACT_HITS+1))
  fi
  if grep -q 'BEGIN.*PRIVATE KEY' "$f"; then
    echo "  redact(private key block): $f"
    sed -i -E '/BEGIN.*PRIVATE KEY/,/END.*PRIVATE KEY/c\___PRIVATE_KEY_REMOVED___' "$f"
    REDACT_HITS=$((REDACT_HITS+1))
  fi
done < <(find "$STAGE" -type f \( -name '*.md' -o -name '*.yml' -o -name '*.yaml' -o -name '*.json' -o -name '*.env*' -o -name '*.txt' -o -name '*.py' \) \
  -not -path '*/node_modules/*' -not -path '*/.git/*')
echo "  - 脱敏完成：$REDACT_HITS 个文件被改写（脱敏仅作用于发布投影，源仓不动）"

echo "[4/7] 中性化本机私有路径 + 校验 community 默认开关"
# 开发者本机绝对路径（E:\setup package\...）改写为环境变量驱动的中性默认值
"$PY" - "$STAGE_WIN" <<'PYEOF'
import re, sys, io
stage = sys.argv[1]

def patch(path, pairs):
    with io.open(path, encoding="utf-8") as f:
        src = f.read()
    for old, new in pairs:
        if old not in src:
            print(f"FAIL: {path} 未找到待改写片段: {old[:40]}...（源文件已变动，请同步更新 release_oss.sh）")
            sys.exit(1)
        src = src.replace(old, new)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print(f"  - 中性化 {path}")

patch(stage + "/backend/app/config.py", [
    (r'"PLAYWRIGHT_BROWSERS_PATH", r"E:\setup package\ms-playwright"',
     '"PLAYWRIGHT_BROWSERS_PATH", os.getenv("HOME", "") + "/.evalshield/ms-playwright"'),
    (r'"JMETER_HOME", r"E:\setup package\jmeter\apache-jmeter-5.6.3"',
     '"JMETER_HOME", os.getenv("JMETER_HOME", "/opt/jmeter")'),
])
patch(stage + "/docker-compose.yml", [
    ('# JMeter（真实性能压测工具链；开发机可 JMETER_HOST_DIR="E:/setup package/jmeter"，',
     '# JMeter（真实性能压测工具链；宿主机工具目录由 JMETER_HOST_DIR 指定，'),
])

# B12：开源发行树 EDITION 默认值改写为 community（私有树默认 enterprise 不回退）
import re as _re
cfg = stage + "/backend/app/config.py"
_c = io.open(cfg, encoding="utf-8").read()
_new, _n = _re.subn(r'(_get\("EDITION",\s*)"[A-Za-z]+"(\))', r'\1"community"\2', _c)
if _n == 0:
    print('FAIL: config.py EDITION 默认值未匹配（发布纪律：OSS 默认 community）'); sys.exit(1)
io.open(cfg, "w", encoding="utf-8", newline="").write(_new)
print("  - config.py EDITION 默认 -> community")

# 残留扫描：限代码与配置类文件（内部 .md 文档不在开源包发布范围，需人工复核）；
# 本脚本自身含匹配模式，跳过
leftover = []
import os
SELF = os.path.normpath(os.path.join(stage, "scripts", "release_oss.sh"))
for root, dirs, files in os.walk(stage):
    dirs[:] = [d for d in dirs if d not in (".git", ".trae", "node_modules", "__pycache__")]
    for fn in files:
        p = os.path.join(root, fn)
        if os.path.normpath(p) == SELF:
            continue
        if not fn.endswith((".py", ".sh", ".yml", ".yaml", ".js", ".jsx", ".sql", ".example", ".conf", ".json", ".txt")) and fn not in ("Dockerfile", "requirements.txt", "nginx.conf"):
            continue
        try:
            text = io.open(p, encoding="utf-8").read()
        except UnicodeDecodeError:
            continue
        if "setup package" in text or "E:\\" in text or "E:/" in text or "license_cli keygen" in text:
            leftover.append(p)
if leftover:
    print("FAIL: 本机私有路径残留:", *leftover[:20], sep="\n  ")
    sys.exit(1)
print("  - 无本机私有路径残留")

src = open(stage + "/backend/app/enterprise/features.py", encoding="utf-8").read()
bad = re.findall(r'getenv\("(EDITION|[A-Z_]+_ENABLED)",\s*"(?!false|community)[^"]+"\)', src)
if bad:
    print("FAIL: features.py 默认值非关闭:", bad); sys.exit(1)
print("  - features.py 默认全关 OK")
PYEOF

echo "[5/7] 剥离后自检：编译 + 路由基线对账（B12-④）"
"$PY" -m compileall -q "$STAGE_WIN/backend/app" >/dev/null
echo "  - compileall 通过"

BASELINE="$ROOT_DIR/scripts/oss_route_baseline.txt"
if [[ ! -f "$BASELINE" ]]; then
  echo "FAIL: 缺 scripts/oss_route_baseline.txt（生成：改造全量树内一次性执行，见开发方案 B12）"; exit 1
fi
ACTUAL="$( (cd "$STAGE/backend" && EDITION=community "$PY" - <<'PYEOF'
from app.main import create_app
app = create_app()
for p in sorted(app.openapi()["paths"].keys()):
    print(p)
PYEOF
) | grep '^/')"
# Windows 原生 python 的 stdout 带 \r\n，对账前统一剥除
DIFF="$(diff <(printf '%s\n' "$ACTUAL" | tr -d '\r' | LC_ALL=C sort) <(LC_ALL=C sort "$BASELINE") || true)"
if [[ -n "$DIFF" ]]; then
  echo "FAIL: OSS 路由集与基线不一致："; echo "$DIFF"; exit 1
fi
echo "  - 路由集与 oss_route_baseline.txt 一致"

echo "[6/7] 商业许可指纹校验（ES9-P-20：剥离产物不得含任何商业头/清单）"
# ① SPDX 商业标识必须 0 命中（add_headers.py --variant commercial 加注的头）
# 白名单：LICENSE=双许可正文（依法须公开商业条款）；release_oss.sh/add_headers.py=工具自身模式串（自指，非泄露）
SPDX_HITS="$(grep -rl 'LicenseRef-EvalShield-Commercial' "$STAGE" \
  --exclude=LICENSE --exclude=release_oss.sh --exclude=add_headers.py 2>/dev/null || true)"
if [[ -n "$SPDX_HITS" ]]; then
  echo "FAIL: 剥离产物含 LicenseRef-EvalShield-Commercial 头："; printf '%s\n' "$SPDX_HITS" | head -20; exit 1
fi
# ② 商业路由挂载清单文件（register.py 为 commercial 树独有，双保险防排除规则回退）
for MF in "$STAGE/backend/app/commercial" "$STAGE/frontend/src/pages/commercial"; do
  if [[ -e "$MF" ]]; then echo "FAIL: 商业清单未剥离：$MF"; exit 1; fi
done
echo "  - 商业许可指纹 0 命中；商业清单未带入"

echo "[7/7] 打包与校验和"
mkdir -p "$OUT_DIR"
tar -czf "$OUT_DIR/$PKG.tar.gz" -C "$OUT_DIR" "$PKG"
( cd "$OUT_DIR" && sha256sum "$PKG.tar.gz" > "$PKG.tar.gz.sha256" )
echo "[DONE] 开源发行包：$OUT_DIR/$PKG.tar.gz"
echo "       校验和：    $OUT_DIR/$PKG.tar.gz.sha256"
echo "后续：推送到公共镜像仓前请人工复核 git log 中是否含商业敏感信息（commit 历史不会随 archive 发布）。"
