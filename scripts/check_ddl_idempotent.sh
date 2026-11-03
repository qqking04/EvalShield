#!/usr/bin/env bash
# ES8-BUG-012(a)：inti.sql 幂等性对账门禁
#
# 判据：向一次性临时库连跑两遍 database/inti.sql，
# 两遍各自 pg_dump --schema-only 快照 diff 必须为空——
# 第二次执行不得产生任何 schema 变化（DDL-06 幂等承诺）。
#
# 用法：
#   bash scripts/check_ddl_idempotent.sh [inti.sql 路径]
# 环境：
#   MAINT_PG_URI  维护连接串（默认本地 EvalShield 库，需 CREATEDB 权限）
# 说明：
#   本机无 psql/pg_dump 时无法真跑；CI（ubuntu + postgres service）执行。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SQL_FILE="${1:-$REPO_ROOT/database/inti.sql}"
MAINT_URI="${MAINT_PG_URI:-postgresql://EvalShield:EvalShield@127.0.0.1:5432/EvalShield}"
TMPDB="es_idem_check_$$"
TMP_URI="${MAINT_URI%/*}/${TMPDB}"
SNAP1="$(mktemp)"
SNAP2="$(mktemp)"

cleanup() {
  psql "$MAINT_URI" -q -c "DROP DATABASE IF EXISTS ${TMPDB}" || true
  rm -f "$SNAP1" "$SNAP2"
}
trap cleanup EXIT

[ -f "$SQL_FILE" ] || { echo "FATAL: inti.sql 不存在: $SQL_FILE" >&2; exit 1; }

echo "==> 建临时库 $TMPDB"
psql "$MAINT_URI" -v ON_ERROR_STOP=1 -q \
  -c "DROP DATABASE IF EXISTS ${TMPDB}" \
  -c "CREATE DATABASE ${TMPDB}"

echo "==> 第 1 遍执行 $(basename "$SQL_FILE")"
psql "$TMP_URI" -v ON_ERROR_STOP=1 -q -f "$SQL_FILE" >/dev/null
pg_dump --schema-only "$TMP_URI" > "$SNAP1"

echo "==> 第 2 遍执行（幂等验证）"
psql "$TMP_URI" -v ON_ERROR_STOP=1 -q -f "$SQL_FILE" >/dev/null
pg_dump --schema-only "$TMP_URI" > "$SNAP2"

echo "==> 比对两遍 schema 快照"
if diff -u "$SNAP1" "$SNAP2" > /dev/null; then
  echo "PASS: inti.sql 幂等（两遍执行 schema 零漂移）"
else
  echo "FAIL: 第二遍执行产生 schema 漂移：" >&2
  diff -u "$SNAP1" "$SNAP2" | head -80 >&2
  exit 1
fi
