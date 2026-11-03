#!/usr/bin/env bash
# ES9-P-14：探活看门狗 —— cron 定时 curl healthz/readyz，失败推企业微信机器人
#
# 探测链：
#   1) GET /api/healthz  → 非 200/超时 = 存活异常
#   2) GET /api/readyz   → 非 200 = 就绪异常（inti.sql 版本漂移 / 迁移未应用）
#   3) 可选：GET /api/health（登录旁路的服务声明）仅记录不参与判定
# 告警通道：NOTIFY_WEBHOOK_URL（企业微信机器人 webhook，.env 配置；留空 = 仅本地日志）
# 防打扰：同一故障 COOLDOWN_MINUTES 分钟内不重复推送（状态文件记录上次告警时间）。
#
# cron 示例（每分钟）：
#   * * * * * /path/to/EvalShield/scripts/watchdog.sh >> /var/log/evalshield-watchdog.log 2>&1
# 退出码：0 全部正常；1 存在异常（已尝试推送告警）
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$ROOT_DIR/.env" ]] && { set -a; . "$ROOT_DIR/.env" 2>/dev/null || true; set +a; }

BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${EVALSHIELD_BACKEND_PORT:-8000}}"
NOTIFY_WEBHOOK_URL="${NOTIFY_WEBHOOK_URL:-}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-5}"
COOLDOWN_MINUTES="${COOLDOWN_MINUTES:-15}"
STATE_FILE="${STATE_FILE:-$ROOT_DIR/.watchdog-state}"

FAIL=0
MSG=""

probe() {  # probe <name> <url>
  local name="$1" url="$2" code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT_SECONDS" "$url" 2>/dev/null || echo 000)"
  if [[ "$code" == "200" ]]; then
    echo "[watchdog] $name OK ($url)"
  else
    echo "[watchdog] $name FAIL http=$code ($url)" >&2
    FAIL=1
    MSG="${MSG}- ${name}: HTTP ${code}\n"
  fi
}

probe healthz "$BACKEND_URL/api/healthz"
probe readyz  "$BACKEND_URL/api/readyz"

if [[ "$FAIL" -eq 0 ]]; then
  # 恢复通知（仅当上次处于告警态）
  if [[ -f "$STATE_FILE" ]]; then
    ALARMED="$(sed -n '1p' "$STATE_FILE" 2>/dev/null || echo 0)"
    if [[ "$ALARMED" == "1" && -n "$NOTIFY_WEBHOOK_URL" ]]; then
      curl -s -m 5 -X POST -H 'Content-Type: application/json' \
        -d "{\"msgtype\":\"markdown\",\"markdown\":{\"content\":\"EvalShield 探活恢复 OK\n<font color=\\\"info\\\">$(date '+%F %T')</font>\"}}" \
        "$NOTIFY_WEBHOOK_URL" > /dev/null || true
    fi
  fi
  echo "0 $(date -u +%s)" > "$STATE_FILE"
  exit 0
fi

# --- 告警（带冷却） ---
NOW="$(date -u +%s)"
LAST_TS=0
if [[ -f "$STATE_FILE" ]]; then
  LAST_TS="$(sed -n '2p' "$STATE_FILE" 2>/dev/null || echo 0)"
  [[ "$LAST_TS" =~ ^[0-9]+$ ]] || LAST_TS=0
fi
ELAPSED_MIN=$(( (NOW - LAST_TS) / 60 ))

echo -e "[watchdog] ALERT:\n$MSG" >&2
if [[ -n "$NOTIFY_WEBHOOK_URL" && "$ELAPSED_MIN" -ge "$COOLDOWN_MINUTES" ]]; then
  BODY="{\"msgtype\":\"markdown\",\"markdown\":{\"content\":\"EvalShield 探活告警\n$(echo -e "$MSG")\n主机: $(hostname)\n<font color=\\\"warning\\\">$(date '+%F %T %Z')</font>\"}}"
  if curl -s -m 5 -X POST -H 'Content-Type: application/json' -d "$BODY" "$NOTIFY_WEBHOOK_URL" > /dev/null 2>&1; then
    echo "[watchdog] 告警已推送 webhook"
    echo "1 $NOW" > "$STATE_FILE"
  else
    echo "[watchdog] WARN: webhook 推送失败" >&2
    echo "1 $LAST_TS" > "$STATE_FILE"   # 推送失败保留冷却窗口外重试机会
  fi
else
  if [[ -z "$NOTIFY_WEBHOOK_URL" ]]; then
    echo "[watchdog] NOTIFY_WEBHOOK_URL 未配置，仅本地日志"
  else
    echo "[watchdog] 冷却窗口内（${ELAPSED_MIN}min < ${COOLDOWN_MINUTES}min），跳过重复推送"
  fi
  echo "1 ${LAST_TS}" > "$STATE_FILE"
fi
exit 1
