#!/usr/bin/env bash
# EvalShield 后端容器入口：等待数据库就绪 → 幂等初始化（建表+种子）→ 启动服务
set -euo pipefail

echo "[entrypoint] waiting for database ${DB_HOST}:${DB_PORT} ..."
for i in $(seq 1 60); do
    if (echo > "/dev/tcp/${DB_HOST}/${DB_PORT}") >/dev/null 2>&1; then
        echo "[entrypoint] database is ready"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "[entrypoint] ERROR: database not reachable after 60 attempts" >&2
        exit 1
    fi
    sleep 2
done

echo "[entrypoint] running db migrate (idempotent)..."
python scripts/docker_db_migrate.py || true
echo "[entrypoint] running seed (idempotent)..."
python scripts/seed.py
# 模型网关配置（DeepSeek 公有云 + 本地 GPU/Ollama），幂等
python scripts/seed_models.py

echo "[entrypoint] starting uvicorn..."
exec "$@"