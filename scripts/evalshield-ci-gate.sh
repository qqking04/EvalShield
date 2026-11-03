#!/bin/bash
# EvalShield CI 门禁 CLI 工具（U7：转调 Python SDK evalshield_cli.py gate，逻辑统一收敛到 CLI）
# 用法: EVALSHIELD_API_KEY=<token> ./evalshield-ci-gate.sh <target_code> [engines_json] [async]
#   第 3 参传 "async" 时使用异步模式：提交任务后轮询 /ci-gate/status，避免长任务 HTTP 超时
#   （默认 async，与历史行为一致）
# exit_code: 0=门禁通过 1=未通过 2=执行/调用异常

set -u
EVALSHIELD_URL=${EVALSHIELD_URL:-"http://localhost:8000"}
API_KEY=${EVALSHIELD_API_KEY:-""}
TARGET_CODE=${1:-""}
ENGINES=${2:-'["JAILBREAK", "PII_LEAK"]'}
MODE=${3:-"async"}
POLL_INTERVAL=${POLL_INTERVAL:-10}
POLL_TIMEOUT=${POLL_TIMEOUT:-1800}

if [ -z "$TARGET_CODE" ]; then
  echo "Usage: $0 <target_code> [engines_json] [sync|async]"
  exit 2
fi

# 定位 Python CLI（与本脚本同仓库：backend/scripts/evalshield_cli.py）
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
CLI="$SCRIPT_DIR/../backend/scripts/evalshield_cli.py"
if [ ! -f "$CLI" ]; then
  echo "❌ 未找到 evalshield_cli.py（期望路径：$CLI）"
  exit 2
fi
PYTHON=${PYTHON:-python3}

ARGS=(gate --url "$EVALSHIELD_URL" --target "$TARGET_CODE" --engines "$ENGINES"
      --interval "$POLL_INTERVAL" --timeout "$POLL_TIMEOUT")
[ -n "$API_KEY" ] && ARGS+=(--token "$API_KEY")
[ "$MODE" = "sync" ] && ARGS+=(--sync)

# 转调 Python CLI：透传 exit code（0=通过 1=未通过 2=异常），摘要由 CLI 打印
exec "$PYTHON" "$CLI" "${ARGS[@]}"
