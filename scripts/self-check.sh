#!/usr/bin/env bash
# EvalShield 部署健康自检脚本（信创/离线交付验收用）
#
# 用途：deploy-offline.sh 之后（或任意日常巡检）逐项验证
#       容器状态、端口连通、DB 就绪、后端健康、引擎路由注册、前端可访问。
#
# 用法：
#   ./scripts/self-check.sh
#
# 退出码：0 全部通过；1 存在 FAIL 项
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# W2：载入 .env（供 [6/6] 安全基线判定 SECRET_KEY / DB 口令是否仍为出厂值）
[[ -f "$ROOT_DIR/.env" ]] && { set -a; . "$ROOT_DIR/.env" 2>/dev/null || true; set +a; }

BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${EVALSHIELD_BACKEND_PORT:-8000}}"
FRONTEND_URL="${FRONTEND_URL:-http://127.0.0.1:${EVALSHIELD_FRONTEND_PORT:-8891}}"
FAIL=0
WARN_CNT=0

pass() { echo "  PASS  $1"; }
fail() { echo "  FAIL  $1"; FAIL=1; }

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  COMPOSE="docker-compose"
fi

echo "[1/5] 容器状态（db / backend / frontend / sandbox）"
for c in evalshield-db evalshield-backend evalshield-frontend evalshield-sandbox; do
  state="$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo missing)"
  if [[ "$state" == "running" ]]; then
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$c" 2>/dev/null)"
    if [[ "$health" == "unhealthy" ]]; then fail "$c running 但 healthcheck=unhealthy"; else pass "$c running${health:+ (health=$health)}"; fi
  else
    fail "$c 状态=$state"
  fi
done

echo "[2/5] 数据库连通"
if docker exec evalshield-db pg_isready -U EvalShield -d EvalShield >/dev/null 2>&1; then
  pass "pg_isready 就绪"
else
  fail "pg_isready 未就绪"
fi
# ES9-P-15：DB 会话时区必须为 UTC（存储层统一 UTC，展示层换算北京时间）
DB_TZ="$(docker exec evalshield-db psql -U EvalShield -d EvalShield -tAc 'SHOW timezone' 2>/dev/null | tr -d '[:space:]')"
if [[ "$DB_TZ" == "UTC" ]]; then
  pass "SHOW timezone = UTC"
else
  fail "SHOW timezone = ${DB_TZ:-查询失败}，期望 UTC（检查 compose db 服务 TZ 环境变量）"
fi

echo "[3/5] 后端健康检查 $BACKEND_URL"
if curl -fsS --max-time 10 "$BACKEND_URL/api/health" >/dev/null 2>&1; then
  pass "/api/health 200"
else
  fail "/api/health 不可达"
fi

echo "[4/5] 引擎与业务路由注册（openapi 探测）"
SPEC="$(curl -fsS --max-time 10 "$BACKEND_URL/api/openapi.json" 2>/dev/null || true)"
if [[ -z "$SPEC" ]]; then
  fail "/api/openapi.json 不可达，无法验证路由"
else
  for p in /api/engines /api/license/status /api/reports /api/compliance; do
    if printf '%s' "$SPEC" | grep -q "\"$p"; then pass "路由 $p 已注册"; else fail "路由 $p 缺失"; fi
  done
  # 6 大评测引擎在线情况（需要鉴权的接口只验证路由存在，不验证数据）
  cnt="$(printf '%s' "$SPEC" | grep -o '"/api/engines/[^"]*"' | sort -u | wc -l | tr -d ' ')"
  if [[ "${cnt:-0}" -ge 1 ]]; then pass "引擎路由共 $cnt 条"; else fail "未发现在线引擎路由"; fi
fi

echo "[5/5] 前端页面 $FRONTEND_URL"
if curl -fsS --max-time 10 -o /dev/null "$FRONTEND_URL/"; then
  pass "前端首页 200"
else
  fail "前端首页不可达"
fi

echo "[6/6] 安全基线（默认口令检测 —— WARN 不阻断）"
warn() { echo "  WARN  $1"; WARN_CNT=$((WARN_CNT+1)); }
# ① SECRET_KEY 出厂串
if grep -q 'EVALSHIELD_SECRET_KEY=EvalShield-dev-secret' "$ROOT_DIR/.env" 2>/dev/null; then
  warn "SECRET_KEY 仍为出厂默认串，请更换为 openssl rand -hex 32 产物"
fi
# ② DB 口令出厂值
if docker exec evalshield-db psql -U EvalShield -d EvalShield -tAc "SELECT 1" >/dev/null 2>&1 \
   && [[ "${EVALSHIELD_DB_PASSWORD:-EvalShield}" == "EvalShield" ]]; then
  warn "数据库口令仍为出厂值 EvalShield，交付验收前应改为强口令"
fi
# ③ admin 出厂口令可登录（seed.py 定义 EvalShield@123）
if curl -fsS -m 5 -X POST "$BACKEND_URL/api/auth/login" \
     -H 'Content-Type: application/json' \
     -d '{"username":"admin","password":"EvalShield@123"}' 2>/dev/null | grep -q '"token"'; then
  warn "admin 仍可使用出厂口令 EvalShield@123 登录，交付前必须改密"
fi
[[ "$WARN_CNT" == "0" ]] && echo "  PASS  未发现出厂默认口令"

echo ""
if [[ "$FAIL" == "0" && "$WARN_CNT" == "0" ]]; then
  echo "PASS: 健康自检全部通过（含安全基线）"
  exit 0
elif [[ "$FAIL" == "0" ]]; then
  echo "PASS: 功能自检通过；安全基线 ${WARN_CNT} 条 WARN，交付验收前请逐条处置"
  exit 0
else
  echo "FAIL: 存在未通过项，请检查上方 FAIL 行与 $($COMPOSE logs --tail 30 2>&1 | tail -30)"
  exit 1
fi
