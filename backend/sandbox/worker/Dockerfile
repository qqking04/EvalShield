# syntax=docker/dockerfile:1
FROM python:3.13-slim

WORKDIR /app

# 安装最小依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    strace \
    && rm -rf /var/lib/apt/lists/*

# 引擎用到的运行时依赖（base.py 引用 sqlalchemy，其余为 stdlib）
RUN pip install --no-cache-dir sqlalchemy

# 复制引擎代码与入口（保持 app 包结构，以支持引擎内部相对导入 ..services/..models）
COPY app /app/app
COPY sandbox/worker/run.py /app/run.py
# ES9-P-03 pool 模式：worker 内嵌 mini-agent（纯标准库，不触碰 docker.sock）
COPY sandbox/worker/agent.py /app/agent.py

# 创建非 root 用户
RUN groupadd -r sandboxuser -g 1000 && \
    useradd -r -g sandboxuser -u 1000 sandboxuser && \
    mkdir -p /app/artifacts /shared /tmp /var/tmp && \
    chown -R sandboxuser:sandboxuser /app /shared

USER 1000:1000

# pool 模式（默认）：常驻 agent，等待 gateway 经共享卷 unix socket 分发任务；
# legacy 模式由网关显式传入 "python -u /app/run.py ..." 参数覆盖 CMD
CMD ["python", "-u", "/app/agent.py"]
