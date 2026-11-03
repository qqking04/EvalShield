#!/usr/bin/env bash
# EvalShield 企业版装机脚本（优化7 T8-1，Linux 客户机；docker compose 路线，沿用 deploy-offline.sh 骨架）
#
# 交付物（tar 解包后根目录）：
#   dist/images/*.tar (+manifest.txt)   后端/前端/沙箱离线镜像
#   deploy/*.lic                        客户许可证文件（装机后在页面上传激活，非本脚本职责）
#   scripts/deploy/                     本脚本 + gen-env 说明
#   docs/support-policy.md              支持政策一页纸（销售已填价签）
#
# 流程：sha256 校验 → 生成强随机 .env → 加载镜像 → 起 PG → 跑 inti.sql → 起服 → 装机自检
# 用法：./scripts/deploy/install-enterprise.sh [交付包根目录]   # 默认脚本上级两目录
# 退出码：0 成功；1 起服/自检失败；2 前置检查不通过
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
IMG_DIR="$ROOT_DIR/dist/images"
FAIL=0

echo "[1/6] 前置检查"
command -v docker >/dev/null 2>&1 || { echo "FAIL: 未安装 docker"; exit 2; }
docker info >/dev/null 2>&1 || { echo "FAIL: docker 守护进程不可用（root 或 docker 组）"; exit 2; }
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "FAIL: 未安装 docker compose"; exit 2
fi
[[ -d "$IMG_DIR" ]] || { echo "FAIL: 镜像目录不存在: $IMG_DIR"; exit 2; }
ls "$IMG_DIR"/*.tar >/dev/null 2>&1 || { echo "FAIL: $IMG_DIR 下无 *.tar"; exit 2; }
command -v openssl >/dev/null 2>&1 || { echo "FAIL: 缺少 openssl（生成随机密钥需要）"; exit 2; }

echo "[2/6] 交付包 sha256 校验（manifest.txt 存在时逐一比对）"
if [[ -f "$IMG_DIR/manifest.txt" ]]; then
  while read -r name size hash; do
    [[ "$name" == "#"* || -z "$name" ]] && continue
    actual="$(sha256sum "$IMG_DIR/$name" 2>/dev/null | cut -d' ' -f1 || true)"
    if [[ -n "$actual" && "$actual" == "$hash" ]]; then
      echo "  OK   $name"
    else
      echo "  FAIL $name sha256 不符（包损坏）"; FAIL=1
    fi
  done < "$IMG_DIR/manifest.txt"
  [[ "$FAIL" == "1" ]] && { echo "FAIL: 交付包校验未通过，请联系服务商重发包"; exit 2; }
else
  echo "  WARN: 无 manifest.txt，跳过完整性校验"
fi

echo "[3/6] 生成运行环境 .env（随机密钥，不写死默认值——T1 fail-fast 同款纪律）"
if [[ ! -f "$ROOT_DIR/.env" ]]; then
  DB_PW="$(openssl rand -hex 16)"
  # ES7-D-1 修复：超管一次性口令在此生成（chmod 600 的 .env 即工单同源载体），
  # 经 compose 透传注入 seed——seed 走 INIT_ADMIN_PASSWORD 分支，随机口令
  # 不再打印 stdout、不落 docker daemon 持久化日志。
  ADMIN_PW="$(openssl rand -base64 18 | tr -d '\n')"
  cat > "$ROOT_DIR/.env" <<EOF
# EvalShield 企业版装机生成（install-enterprise.sh，请妥善保管，勿随包分发）
EVALSHIELD_SECRET_KEY=$(openssl rand -hex 32)
EVALSHIELD_WEBHOOK_SECRET=$(openssl rand -hex 24)
EVALSHIELD_DB_PASSWORD=${DB_PW}
EDITION=enterprise
DEEPSEEK_API_KEY=
EVALSHIELD_BACKEND_PORT=8000
EVALSHIELD_FRONTEND_PORT=8891
EVALSHIELD_SANDBOX_PORT=9000
INIT_ADMIN_PASSWORD=${ADMIN_PW}
EOF
  chmod 600 "$ROOT_DIR/.env"
  echo "  已生成 .env（SECRET_KEY / DB 密码 / 超管一次性口令均为随机值）"
  echo "  超管一次性口令：仅存于 .env（chmod 600），请按 SOP 经加密通道交付，勿粘贴到工单正文/聊天"
  # 同步 compose 用的 db 密码（compose 读 .env 变量插值）
  grep -q '^POSTGRES_PASSWORD=' "$ROOT_DIR/.env" || echo "POSTGRES_PASSWORD=${DB_PW}" >> "$ROOT_DIR/.env"
else
  echo "  复用现有 .env"
  grep -q '^INIT_ADMIN_PASSWORD=' "$ROOT_DIR/.env" || echo "  WARN: 现有 .env 无 INIT_ADMIN_PASSWORD——首跑 seed 将走随机口令分支（不打印、不落日志），口令将不可交付，需人工补配后重跑 seed"
fi

echo "[4/6] 加载镜像"
for f in "$IMG_DIR"/*.tar; do
  echo "  docker load < $(basename "$f")"
  docker load -i "$f"
done

echo "[5/6] 启动全栈（db → inti.sql 幂等 seed → backend/frontend/sandbox）"
$COMPOSE up -d

echo "[6/6] 装机自检（等待后端就绪，最长 180s；entrypoint 首跑 inti.sql 较慢）"
BE_PORT="$(grep -E '^EVALSHIELD_BACKEND_PORT=' "$ROOT_DIR/.env" | cut -d= -f2 || true)"
BE_PORT="${BE_PORT:-8000}"
FE_PORT="$(grep -E '^EVALSHIELD_FRONTEND_PORT=' "$ROOT_DIR/.env" | cut -d= -f2 || true)"
FE_PORT="${FE_PORT:-8891}"
READY=0
for i in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${BE_PORT}/api/health" >/dev/null 2>&1; then READY=1; break; fi
  sleep 2
done
[[ "$READY" == "1" ]] || { echo "FAIL: 后端 180s 未就绪：$($COMPOSE logs --tail 50 backend)"; exit 1; }

CHECK_FAIL=0
check() { # 名称 命令...（命令执行成功即 PASS）
  if "${@:2}" >/dev/null 2>&1; then echo "  PASS $1"; else echo "  FAIL $1"; CHECK_FAIL=1; fi
}
check "health 200" curl -fsS "http://127.0.0.1:${BE_PORT}/api/health"
check "edition=enterprise" bash -c "curl -fsS http://127.0.0.1:${BE_PORT}/api/edition | grep -q enterprise"
check "登录页可达 (frontend :${FE_PORT})" curl -fsS "http://127.0.0.1:${FE_PORT}/"
check "license 激活入口可达" bash -c "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:${BE_PORT}/api/license/status | grep -Eq '200|401'"

if [[ "$CHECK_FAIL" == "1" ]]; then
  echo "FAIL: 装机自检未全绿，请附 $($COMPOSE ps) 输出联系服务商"
  exit 1
fi

echo ""
echo "=============================================================="
echo " EvalShield 企业版装机完成。"
echo "   访问地址：http://<本机IP>:${FE_PORT}"
echo "   超管一次性口令：见本机 .env 的 INIT_ADMIN_PASSWORD（chmod 600，加密通道交付——优化7 T4/D-1）"
echo "   下一步：登录 → 首页引导条「复制机器指纹」发服务商 → 上传 .lic 激活"
echo "   支持政策：docs/support-policy.md"
echo "   安全提醒：DeepSeek/模型网关 Key 请现场确认已吊销旧值、走新发通道"
echo "=============================================================="
