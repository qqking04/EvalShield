#!/usr/bin/env bash
# EvalShield 多架构镜像构建脚本（信创/离线部署）
#
# 用途：为信创环境（麒麟 V10 / 统信 UOS / 欧拉，x86_64 与 aarch64 双架构）
#       构建 backend / frontend / sandbox 三个镜像，并导出为可离线分发的 tar 包。
#
# 用法：
#   ./scripts/build-multiarch.sh                    # 仅当前架构，导出到 ./dist/images
#   PLATFORMS=linux/amd64,linux/arm64 ./scripts/build-multiarch.sh
#
# 依赖：docker（带 buildx）、可选 jq
# 退出码：0 成功；1 环境或构建失败
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PLATFORMS="${PLATFORMS:-linux/$(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')}"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/dist/images}"
TAG="${TAG:-latest}"
REGISTRY_PREFIX="${REGISTRY_PREFIX:-evalshield}"   # 私有仓库前缀，留空则用本地名

echo "[1/4] 构建环境检查"
command -v docker >/dev/null 2>&1 || { echo "FAIL: 未安装 docker"; exit 1; }
docker info >/dev/null 2>&1 || { echo "FAIL: docker 守护进程不可用"; exit 1; }

# 多架构（含两种平台）时需要 buildx；单架构直接用经典构建兜底
MULTI=0
if [[ "$PLATFORMS" == *,* ]]; then
  if docker buildx version >/dev/null 2>&1; then
    MULTI=1
    docker buildx inspect evalshield-builder >/dev/null 2>&1 \
      || docker buildx create --name evalshield-builder --use >/dev/null
  else
    echo "WARN: 未装 buildx，多架构构建不可用，回退单架构 $(uname -m)"
    PLATFORMS="linux/$(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')"
  fi
fi

mkdir -p "$OUT_DIR"

build_one() {
  local name="$1" ctx="$2" dockerfile="$3"
  local image="${REGISTRY_PREFIX}/${name}:${TAG}"
  echo "[2/4] 构建 $image（$PLATFORMS）"
  if [[ "$MULTI" == "1" ]]; then
    # 多架构：buildx 直接导出 OCI tar（--output type=oci）
    docker buildx build \
      --platform "$PLATFORMS" \
      -f "$dockerfile" \
      -t "$image" \
      --output "type=oci,dest=$OUT_DIR/${name}.tar" \
      "$ctx"
  else
    docker build -f "$dockerfile" -t "$image" "$ctx"
    docker save "$image" -o "$OUT_DIR/${name}.tar"
  fi
}

build_one backend  ./backend  ./backend/Dockerfile
build_one frontend ./frontend ./frontend/Dockerfile
build_one sandbox  ./backend  ./backend/sandbox/gateway/Dockerfile

# sandbox-worker 是运行时按需构建的轻量镜像，一并导出
if [[ -f ./backend/sandbox/worker/Dockerfile ]]; then
  build_one sandbox-worker ./backend ./backend/sandbox/worker/Dockerfile || true
fi

echo "[3/4] 生成离线包清单 manifest.txt"
{
  echo "# EvalShield 离线镜像包清单"
  echo "# 构建时间: $(date '+%F %T %z')"
  echo "# 平台: $PLATFORMS"
  for f in "$OUT_DIR"/*.tar; do
    echo "$(basename "$f")  $(du -h "$f" | cut -f1)  $(sha256sum "$f" | cut -d' ' -f1)"
  done
} > "$OUT_DIR/manifest.txt"

echo "[4/4] 完成"
echo "PASS: 镜像包已导出到 $OUT_DIR"
echo "提示: 拷到目标机后执行 ./scripts/deploy-offline.sh $OUT_DIR 完成离线部署"
