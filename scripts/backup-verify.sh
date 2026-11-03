#!/usr/bin/env bash
# ES9-P-14：备份巡检脚本 —— 校验最新备份的 sha256 + 产物可解析性（不落地恢复）
#
# 校验项：
#   1) 备份目录存在且包含 db.dump / evidence.tar / sha256sums.txt
#   2) sha256sum -c 完整性
#   3) pg_restore --list 能列出 db.dump 对象清单（tar/dump 未损坏的轻量证明）
#   4) tar -tf 能列出证据卷条目
#   5) 备份新鲜度：最新备份距今 <= MAX_AGE_HOURS 小时
#
# 用法：./scripts/backup-verify.sh          # 校验最新一份
#       BACKUP_DIR=/mnt/bk ./scripts/backup-verify.sh evalshield-2026...
# 退出码：0 全部通过；1 任一失败（可由 cron 接 watchdog 推送）
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$ROOT_DIR/.env" ]] && { set -a; . "$ROOT_DIR/.env" 2>/dev/null || true; set +a; }

BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-26}"   # 日备 + 2h 容差
FAIL=0

pass() { echo "  PASS  $1"; }
fail() { echo "  FAIL  $1"; FAIL=1; }

# 目标备份目录
if [[ $# -ge 1 && -d "$1" ]]; then
  SRC="$1"
else
  SRC="$(ls -1dt "$BACKUP_DIR"/evalshield-*/ 2>/dev/null | head -n1 || true)"
fi
[[ -n "${SRC:-}" ]] || { echo "  FAIL  $BACKUP_DIR 下无任何备份"; exit 1; }
SRC="${SRC%/}"
echo "[backup-verify] 检查 $SRC"

# 1) 产物齐全
for f in db.dump evidence.tar sha256sums.txt; do
  if [[ -f "$SRC/$f" ]]; then pass "$f 存在"; else fail "$f 缺失"; fi
done

# 2) sha256
if ( cd "$SRC" && sha256sum -c --quiet sha256sums.txt ) 2>/dev/null; then
  pass "sha256 校验一致"
else
  fail "sha256 校验失败"
fi

# 3) db.dump 可解析（pg_restore --list；优先容器内工具，回退宿主机）
if docker exec evalshield-db pg_restore --list < "$SRC/db.dump" > /dev/null 2>&1; then
  pass "pg_restore --list 可解析"
else
  fail "pg_restore --list 解析失败（db.dump 可能损坏）"
fi

# 4) evidence.tar 可列目录
if tar -tf "$SRC/evidence.tar" > /dev/null 2>&1; then
  pass "evidence.tar 条目可列"
else
  fail "evidence.tar 不可读"
fi

# 5) 新鲜度（目录名 UTC 时间戳 evalshield-YYYYMMDDTHHMMSSZ）
STAMP="$(basename "$SRC" | sed -E 's/^evalshield-([0-9]{8}T[0-9]{6}Z)$/\1/')"
if [[ "$STAMP" =~ ^[0-9]{8}T[0-9]{6}Z$ ]]; then
  TS="${STAMP:0:4}-${STAMP:4:2}-${STAMP:6:2} ${STAMP:9:2}:${STAMP:11:2}:${STAMP:13:2} UTC"
  BAK_EPOCH="$(date -u -d "$TS" +%s 2>/dev/null || echo 0)"
  NOW_EPOCH="$(date -u +%s)"
  AGE_H=$(( (NOW_EPOCH - BAK_EPOCH) / 3600 ))
  if [[ "$BAK_EPOCH" -gt 0 && "$AGE_H" -le "$MAX_AGE_HOURS" ]]; then
    pass "备份新鲜度 ${AGE_H}h <= ${MAX_AGE_HOURS}h"
  else
    fail "备份过期：${AGE_H}h > ${MAX_AGE_HOURS}h"
  fi
else
  fail "备份目录名无法解析时间戳: $(basename "$SRC")"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "[backup-verify] OK"
  exit 0
fi
echo "[backup-verify] FAIL（见上）" >&2
exit 1
