#!/usr/bin/env bash
# ES9-P-14：EvalShield 恢复脚本 —— 建空库 → pg_restore 重放 → inti.sql 幂等补种 → 证据卷解包
#
# 用法：
#   ./scripts/restore.sh backups/evalshield-<STAMP>      # 指定备份目录
#   ./scripts/restore.sh                                 # 自动取最新一份
# 前置：evalshield-db / evalshield-backend 容器在跑；compose 网络可用。
# 退出码：0 成功；1 失败
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$ROOT_DIR/.env" ]] && { set -a; . "$ROOT_DIR/.env" 2>/dev/null || true; set +a; }
cd "$ROOT_DIR"

SRC="${1:-}"
if [[ -z "$SRC" ]]; then
  SRC="$(ls -1dt "$ROOT_DIR"/backups/evalshield-*/ 2>/dev/null | head -n1 || true)"
fi
[[ -n "$SRC" && -d "$SRC" ]] || { echo "[restore] FAIL: 备份目录不存在（用法: restore.sh <backup_dir>）" >&2; exit 1; }
SRC="${SRC%/}"

DB_CONTAINER="${DB_CONTAINER:-evalshield-db}"
DB_SUPER_USER="${DB_SUPER_USER:-EvalShield}"   # postgres 镜像初始化用户（=POSTGRES_USER）
DB_NAME="${DB_NAME:-EvalShield}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-evalshield-backend}"
INTI_SQL="${INTI_SQL:-database/inti.sql}"       # 相对仓库根的幂等种子
EVIDENCE_PATH="${EVIDENCE_PATH:-/app/data/evidence}"
REPORTS_PATH="${REPORTS_PATH:-/app/data/reports}"

echo "[restore] 来源: $SRC"
[[ -f "$SRC/db.dump" && -f "$SRC/evidence.tar" && -f "$SRC/sha256sums.txt" ]] || {
  echo "[restore] FAIL: 备份产物不全" >&2; exit 1; }

# --- 0) sha256 完整性校验 ---
echo "[restore] 0/4 sha256 校验"
( cd "$SRC" && sha256sum -c sha256sums.txt ) || { echo "[restore] FAIL: 校验和不匹配" >&2; exit 1; }

# --- 1) 建空库重放：drop/create database 后 pg_restore ---
echo "[restore] 1/4 重建空库 + pg_restore"
docker exec "$DB_CONTAINER" psql -U "$DB_SUPER_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB_NAME' AND pid<>pg_backend_pid();" \
  -c "DROP DATABASE IF EXISTS $DB_NAME WITH (FORCE);" \
  -c "CREATE DATABASE $DB_NAME ENCODING 'UTF8' TEMPLATE template0;"
docker exec -i "$DB_CONTAINER" pg_restore -U "$DB_SUPER_USER" -d "$DB_NAME" --no-owner < "$SRC/db.dump"

# --- 2) inti.sql 幂等补种（IF NOT EXISTS / 部分唯一索引，可安全重放；
#         补齐备份点之后新增的迁移节） ---
if [[ -f "$INTI_SQL" ]]; then
  echo "[restore] 2/4 重放 $INTI_SQL（幂等）"
  docker exec -i "$DB_CONTAINER" psql -U "$DB_SUPER_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 < "$INTI_SQL" \
    || { echo "[restore] FAIL: inti.sql 重放失败" >&2; exit 1; }
else
  echo "[restore] 2/4 跳过 inti.sql（文件不存在: $INTI_SQL）"
fi

# --- 3) 证据/报告卷解包（先清后解，恢复与备份点一致） ---
echo "[restore] 3/4 解包证据卷"
docker exec "$BACKEND_CONTAINER" sh -c "rm -rf $EVIDENCE_PATH $REPORTS_PATH && mkdir -p $EVIDENCE_PATH $REPORTS_PATH"
docker exec -i "$BACKEND_CONTAINER" tar -xf - -C / < "$SRC/evidence.tar"

# --- 4) 探活验证 ---
echo "[restore] 4/4 后端探活（healthz/readyz）"
sleep 3
if docker exec "$BACKEND_CONTAINER" sh -c 'curl -fsS http://127.0.0.1:8000/api/readyz' >/dev/null 2>&1; then
  echo "[restore] OK: readyz 通过，恢复完成"
else
  echo "[restore] WARN: readyz 未通过——请检查后端日志与 inti.sql 版本标记（INTI_SCHEMA_VERSION）" >&2
  exit 1
fi
