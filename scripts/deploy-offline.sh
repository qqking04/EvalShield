#!/usr/bin/env bash
# EvalShield 离线一键部署脚本（信创/无外网环境）
#
# 用途：在目标机（麒麟 V10 / 统信 UOS / 欧拉等）上加载 build-multiarch.sh
#       导出的镜像 tar，校验依赖资源后启动 docker compose 全栈。
#
# 用法：
#   ./scripts/deploy-offline.sh [镜像目录]         # 默认 ./dist/images
#
# 前置条件（离线包目录结构）：
#   dist/images/backend.tar / frontend.tar / sandbox.tar (+manifest.txt)
#   deploy/ms-playwright/    Playwright Chromium 离线浏览器包（UI 引擎依赖）
#   deploy/jmeter/           （可选）JMeter 压测工具链
#
# 退出码：0 成功；1 部署失败；2 前置检查不通过
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

IMG_DIR="${1:-$ROOT_DIR/dist/images}"
FAIL=0

echo "[1/5] 前置检查"
command -v docker >/dev/null 2>&1 || { echo "FAIL: 目标机未安装 docker"; exit 2; }
docker info >/dev/null 2>&1 || { echo "FAIL: docker 守护进程不可用（请用 root 或加入 docker 组）"; exit 2; }
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "FAIL: 未安装 docker compose"; exit 2
fi
[[ -d "$IMG_DIR" ]] || { echo "FAIL: 镜像目录不存在: $IMG_DIR"; exit 2; }
ls "$IMG_DIR"/*.tar >/dev/null 2>&1 || { echo "FAIL: $IMG_DIR 下无 *.tar 镜像包"; exit 2; }

# 校验包完整性（有 manifest 时逐一比对 sha256）
if [[ -f "$IMG_DIR/manifest.txt" ]]; then
  while read -r name size hash; do
    [[ "$name" == "#"* || -z "$name" ]] && continue
    actual="$(sha256sum "$IMG_DIR/$name" 2>/dev/null | cut -d' ' -f1 || true)"
    if [[ -n "$actual" && "$actual" == "$hash" ]]; then
      echo "  OK   $name sha256 校验通过"
    else
      echo "  FAIL $name sha256 校验失败（包可能损坏）"; FAIL=1
    fi
  done < "$IMG_DIR/manifest.txt"
  [[ "$FAIL" == "1" ]] && { echo "FAIL: 离线包校验未通过"; exit 2; }
fi

# 离线资源软检查（缺失只警告，UI/压测引擎功能降级但平台可启动）
[[ -d "$ROOT_DIR/deploy/ms-playwright" && -n "$(ls -A "$ROOT_DIR/deploy/ms-playwright" 2>/dev/null)" ]] \
  || echo "WARN: deploy/ms-playwright 为空 —— UI 自动化引擎将不可用（评测链路其余不受影响）"

# W2：关键变量前置校验（compose 层 ${VAR:?} 报错前的友好提示）
if [[ -f "$ROOT_DIR/.env" ]]; then
  grep -q '^EVALSHIELD_SECRET_KEY=.\+' "$ROOT_DIR/.env" \
    || echo "WARN: .env 缺少 EVALSHIELD_SECRET_KEY —— 将自动补随机值"
else
  echo "INFO: .env 不存在，[3/5] 将自动生成（密钥类请部署后轮换）"
fi
if grep -q 'sk-[A-Za-z0-9]\{20,\}' "$ROOT_DIR/.env" 2>/dev/null; then
  echo "WARN: .env 中检测到疑似真实 API Key 明文，请确认仅存于现场机器、不随包分发"
fi

# W3：JMeter 工具链软检查（缺失仅降级，不阻断部署）
if [[ -d "$ROOT_DIR/dist/deploy/jmeter" && -z "$(ls -A "$ROOT_DIR/deploy/jmeter" 2>/dev/null)" ]]; then
  mkdir -p "$ROOT_DIR/deploy" && cp -r "$ROOT_DIR/dist/deploy/jmeter" "$ROOT_DIR/deploy/jmeter"
  echo "  OK   jmeter 已解包到 deploy/jmeter/"
fi
[[ -n "$(ls -A "${JMETER_HOST_DIR:-$ROOT_DIR/deploy/jmeter}" 2>/dev/null)" ]] \
  || echo "WARN: JMeter 未随包提供 —— 性能压测将降级为内置模式（后端 JMETER_HOME 缺失容错）"

echo "[2/5] 加载镜像"
for f in "$IMG_DIR"/*.tar; do
  echo "  docker load < $(basename "$f")"
  docker load -i "$f"
done

echo "[3/5] 写入运行环境（.env 不存在则生成）"
if [[ ! -f "$ROOT_DIR/.env" ]]; then
  SK="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  cat > "$ROOT_DIR/.env" <<EOF
# EvalShield 部署环境变量（deploy-offline.sh 自动生成，请妥善保管）
EVALSHIELD_SECRET_KEY=${SK}
DEEPSEEK_API_KEY=
EVALSHIELD_DB_PASSWORD=EvalShield
EVALSHIELD_BACKEND_PORT=8000
EVALSHIELD_FRONTEND_PORT=8891
EVALSHIELD_SANDBOX_PORT=9000
EOF
  echo "  已生成 .env（随机 SECRET_KEY）"
else
  echo "  复用现有 .env"
fi

echo "[4/5] 启动全栈（db + backend + frontend + sandbox）"
$COMPOSE up -d

echo "[5/5] 启动等待（后端 entrypoint 会做建库与幂等 seed，最长等待 120s）"
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${EVALSHIELD_BACKEND_PORT:-8000}/api/health" >/dev/null 2>&1; then
    echo "PASS: 后端健康检查通过"
    break
  fi
  sleep 2
  [[ "$i" == "60" ]] && { echo "FAIL: 后端 120s 内未就绪，请查看 $($COMPOSE logs --tail 50 backend)"; exit 1; }
done

echo ""
echo "部署完成。随后请执行健康自检："
echo "  ./scripts/self-check.sh"
