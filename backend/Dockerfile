# EvalShield 后端镜像（Python 3.13 + PostgreSQL 16）
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 系统依赖 + OpenJDK 21（Debian trixie 仅有 21/25，JMeter 5.6.3 完全支持 Java 21）
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        fonts-wqy-zenhei \
        fonts-wqy-microhei \
        openjdk-21-jre-headless \
    && rm -rf /var/lib/apt/lists/*
# JAVA_HOME 用符号链接统一 amd64/arm64 路径差异（信创多架构镜像共用同一 ENV）
RUN ln -sfn "$(ls -d /usr/lib/jvm/java-21-openjdk-* | head -1)" /usr/lib/jvm/java-21-openjdk-current
ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-current
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# 安装 Python 依赖（PyPI 官方源 + 清华镜像兜底，规避 build 时 DNS 抖动）
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && pip install --retries 10 --timeout 180 \
        -i https://pypi.org/simple \
        --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
        -r requirements.txt

# 真实工具链：Playwright Chromium 浏览器使用离线包挂载，构建阶段不再访问 Google CDN
# PLAYWRIGHT_BROWSERS_PATH 指向容器内路径，由 docker-compose.yml 的 volume 提供
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# 仅安装 Chromium 运行所需的 Linux 系统依赖（不下载浏览器二进制）
# 离线包由 docker-compose volume 挂载；deps 失败不致命（首次 build 已装好）
RUN python -m playwright install-deps chromium 2>/dev/null || true && rm -rf /var/lib/apt/lists/*

# 拷贝应用代码（data：运行时数据文件如 security_recommendations.json；tests：容器内自测回归）
# sandbox：网关源码（test_sandbox.py 需 import main）；database/inti.sql 由 compose 只读挂载提供
COPY app ./app
COPY scripts ./scripts
COPY data ./data
COPY tests ./tests
COPY sandbox ./sandbox

# 容器启动入口：等待数据库就绪 → 幂等 seed → 启动 uvicorn
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]