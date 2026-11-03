#!/usr/bin/env bash
# ES9-P-14：EvalShield 备份脚本 —— pg_dump -Fc + 证据卷 tar + sha256 + 保留14份轮转
#
# 备份对象：
#   1) PostgreSQL 数据库（docker exec evalshield-db pg_dump -Fc）
#   2) 证据/报告卷（docker run --volumes-from 或 docker cp 方式 tar）
# 产物：$BACKUP_DIR/evalshield-<UTC时间戳>/  {db.dump, evidence.tar, sha256sums.txt}
# 轮转：仅保留最近 KEEP=14 份完整备份目录。
#
# 用法：
#   ./scripts/backup.sh                    # 默认备份到 ./backups
#   BACKUP_DIR=/mnt/bk ./scripts/backup.sh # 指定备份根目录
# 退出码：0 成功；1 失败
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$ROOT_DIR/.env" ]] && { set -a; . "$ROOT_DIR/.env" 2>/dev/null || true; set +a; }

BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
KEEP="${KEEP:-14}"
DB_CONTAINER="${DB_CONTAINER:-evalshield-db}"
DB_USER="${DB_USER:-EvalShield}"
DB_NAME="${DB_NAME:-EvalShield}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-evalshield-backend}"
# 卷内容路径（与 compose 挂载一致）
EVIDENCE_PATH="${EVIDENCE_PATH:-/app/data/evidence}"
REPORTS_PATH="${REPORTS_PATH:-/app/data/reports}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_DIR/evalshield-$STAMP"
mkdir -p "$DEST"

echo "[backup] 目标目录: $DEST"

# --- 1) 数据库 pg_dump -Fc（自定义压缩格式，restore 走 pg_restore） ---
echo "[backup] 1/3 pg_dump -Fc $DB_NAME"
if ! docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$DEST/db.dump"; then
  echo "[backup] FAIL: pg_dump 失败" >&2
  rm -rf "$DEST"
  exit 1
fi

# --- 2) 证据卷 + 报告卷 tar（经 backend 容器 exec tar 到 stdout） ---
echo "[backup] 2/3 tar 证据/报告卷"
if ! docker exec "$BACKEND_CONTAINER" tar -cf - "$EVIDENCE_PATH" "$REPORTS_PATH" 2>/dev/null > "$DEST/evidence.tar"; then
  echo "[backup] FAIL: tar 失败（容器未运行或路径缺失）" >&2
  rm -rf "$DEST"
  exit 1
fi

# --- 3) sha256 清单（恢复/巡检前完整性校验依据） ---
echo "[backup] 3/3 sha256"
( cd "$DEST" && sha256sum db.dump evidence.tar > sha256sums.txt )

# --- 轮转：保留最近 KEEP 份 ---
echo "[backup] 轮转（保留 $KEEP 份）"
# shellcheck disable=SC2012
ls -1dt "$BACKUP_DIR"/evalshield-*/ 2>/dev/null | tail -n "+$((KEEP + 1))" | while IFS= read -r old; do
  echo "[backup]   删除过期: $old"
  rm -rf "$old"
done

echo "[backup] OK: $DEST"
cat "$DEST/sha256sums.txt"
