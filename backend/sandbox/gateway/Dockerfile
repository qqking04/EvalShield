# syntax=docker/dockerfile:1
FROM python:3.13-slim

WORKDIR /app

# 安装最小依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    strace curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 Docker CLI 静态二进制（用于通过挂载的 sock 操作宿主机 daemon）
# 实测：容器内直连 download.docker.com 会 TLS 中断（curl 35），改国内镜像优先、官方兜底
ARG DOCKER_CLI_VERSION=28.5.2
RUN set -eux; \
    ok=0; \
    for u in \
      "https://mirrors.aliyun.com/docker-ce/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
      "https://mirrors.huaweicloud.com/docker-ce/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
      "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz"; do \
      echo "trying $u"; \
      if curl -fsSL --retry 3 --max-time 300 "$u" -o /tmp/docker.tgz; then ok=1; break; fi; \
    done; \
    [ "$ok" = "1" ]; \
    tar xz -C /tmp -f /tmp/docker.tgz \
    && cp /tmp/docker/docker /usr/local/bin/docker \
    && chmod +x /usr/local/bin/docker \
    && rm -rf /tmp/docker /tmp/docker.tgz

# 安装 Python 依赖（网关需要 FastAPI + uvicorn）
RUN pip install --no-cache-dir fastapi uvicorn pydantic

# 复制网关代码
COPY sandbox/gateway/main.py /app/main.py
COPY sandbox/seccomp-default.json /app/seccomp-default.json

# 创建数据目录
RUN mkdir -p /app/data/sandbox

EXPOSE 9000

CMD ["python", "-u", "/app/main.py"]
