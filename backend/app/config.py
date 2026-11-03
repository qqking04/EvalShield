# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""全局配置加载。

约定（硬性）：
- 数据库：PostgreSQL，主机 127.0.0.1，端口 5432，库/用户/密码均 EvalShield，UTF-8。
- 优先读取环境变量；未设置时读取 backend/.env；再未设置时使用本文件默认值。
- 所有配置项在此集中定义，禁止模块内散落硬编码。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# .env 简单解析（不引入 python-dotenv 之外的依赖开销）
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(_ENV_FILE)


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _get_int(key: str, default: int) -> int:
    try:
        return int(_get(key, str(default)))
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    try:
        return float(_get(key, str(default)))
    except ValueError:
        return default


def _get_bool(key: str, default: bool) -> bool:
    val = _get(key, "true" if default else "false").lower()
    return val in ("1", "true", "yes", "on")


class Settings:
    """应用配置（唯一事实源）。"""

    # ---- 应用 ----
    APP_NAME: str = "EvalShield AI系统测试服务平台"
    # 发版时与 git tag v<APP_VERSION> 一一对应（BUSL Change Date 锚点见根 LICENSE）
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = _get_bool("DEBUG", True)
    # 发行形态（版本隔离，见《版本隔离与商业模块改造方案》§2-B3）：
    # community=OSS 剥离树（无 app/commercial 包）；saas=商业路由+订阅依赖；enterprise=私有化+License 闸门。
    # 默认 enterprise：内部全量树开发/部署保持现状行为。
    EDITION: str = _get("EDITION", "community").lower()
    API_PREFIX: str = "/api/v1"
    SERVER_HOST: str = _get("SERVER_HOST", "127.0.0.1")
    SERVER_PORT: int = _get_int("SERVER_PORT", 8000)
    # F-02 修复：不提供可用的硬编码默认密钥；未配置时各形态按 fail-fast 拒绝启动
    SECRET_KEY: str = _get("SECRET_KEY", "")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = _get_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 8)
    REFRESH_TOKEN_EXPIRE_DAYS: int = _get_int("REFRESH_TOKEN_EXPIRE_DAYS", 7)

    # ---- ES9-P-01：导航收敛（feature-flags）----
    # focused=按档位矩阵收敛入口；full=全部入口可达（开发/维护口径，能力不删）
    NAV_PROFILE: str = _get("NAV_PROFILE", "focused").lower()
    # ---- ES9-P-06：文档端点暴露（生产默认关闭 docs/redoc/openapi）----
    EXPOSE_DOCS: bool = _get_bool("EXPOSE_DOCS", False)
    # ---- ES9-P-04：首装引导管理员口令（留空=一次性强随机口令打印 stdout）----
    INIT_ADMIN_PASSWORD: str = _get("INIT_ADMIN_PASSWORD", "")
    # ---- ES9-P-10：评估抽样规模（题库覆盖度评估单集抽样上限）----
    EVAL_SAMPLE_SIZE: int = _get_int("EVAL_SAMPLE_SIZE", 200)
    # ---- ES9 D-15：标准对照配置缺失/损坏时的降级开关（默认关闭=fail-fast 拒绝交付）----
    STD_ALLOW_DEGRADED: bool = _get_bool("STD_ALLOW_DEGRADED", False)
    # ---- 优化12 §8.5：阈值未核定 STRICT kill switch（默认 on=BLOCK/出包硬抛；
    # off=降级 WARN + 草稿水印，使用须按锁 4 记录 docs/internal/decisions.md）----
    STANDARDS_STRICT_MODE: str = _get("STANDARDS_STRICT_MODE", "on").lower()

    # ---- 优化7 T5：License 到期宽限天数（active → grace → revoked 状态机）----
    LICENSE_GRACE_DAYS: int = _get_int("LICENSE_GRACE_DAYS", 30)

    # ---- ES8 M1：SaaS 自助注册试用天数 / 平台运营白名单用户 ----
    TRIAL_DAYS: int = _get_int("TRIAL_DAYS", 14)
    PLATFORM_ADMIN_USER_IDS: str = _get("PLATFORM_ADMIN_USER_IDS", "")

    # ---- ES8 M2：支付渠道（mock 起步；wechat/alipay 待真实 KEY 后启用）----
    PAYMENT_PROVIDER: str = _get("PAYMENT_PROVIDER", "mock").lower()
    WECHAT_PAY_MCHID: str = _get("WECHAT_PAY_MCHID", "")
    WECHAT_PAY_APPID: str = _get("WECHAT_PAY_APPID", "")
    WECHAT_PAY_CERT_PATH: str = _get("WECHAT_PAY_CERT_PATH", "")
    WECHAT_PAY_KEY_PATH: str = _get("WECHAT_PAY_KEY_PATH", "")
    ALIPAY_APPID: str = _get("ALIPAY_APPID", "")
    ALIPAY_PRIVATE_KEY: str = _get("ALIPAY_PRIVATE_KEY", "")
    ALIPAY_PUBLIC_KEY: str = _get("ALIPAY_PUBLIC_KEY", "")

    # ---- ES8 M5：GitHub Checks 回写（可选增强，模式同 M2 provider：缺配置即跳过）----
    # 三项齐全（APP_ID / INSTALLATION_ID / PRIVATE_KEY）才启用；PRIVATE_KEY 为 PEM 文本。
    GITHUB_APP_ID: str = _get("GITHUB_APP_ID", "")
    GITHUB_APP_INSTALLATION_ID: str = _get("GITHUB_APP_INSTALLATION_ID", "")
    GITHUB_APP_PRIVATE_KEY: str = _get("GITHUB_APP_PRIVATE_KEY", "")
    #  Checks 回写的仓库（owner/repo）与提交 SHA 由任务 config.github 提供
    GITHUB_CHECKS_API_BASE: str = _get("GITHUB_CHECKS_API_BASE", "https://api.github.com")

    # ---- 数据库（UTF-8，中文支持；无外键策略在模型层执行）----
    DB_HOST: str = _get("DB_HOST", "127.0.0.1")
    DB_PORT: int = _get_int("DB_PORT", 5432)
    DB_NAME: str = _get("DB_NAME", "EvalShield")
    DB_USER: str = _get("DB_USER", "EvalShield")
    DB_PASSWORD: str = _get("DB_PASSWORD", "EvalShield")

    @property
    def DATABASE_URL(self) -> str:
        # client_encoding=utf8 强制 UTF-8，杜绝中文乱码
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?client_encoding=utf8"
        )

    # ---- 登录安全策略（U-06）----
    # 2026-11-01 调整：5 次/30 分钟对演示与日常使用过严（误触即锁半小时），
    # 放宽为 10 次/5 分钟——爆破防护靠"失败即冷却"的时间成本，短窗口同样有效且误伤小。
    LOGIN_FAIL_LIMIT: int = _get_int("LOGIN_FAIL_LIMIT", 10)
    LOGIN_LOCK_MINUTES: int = _get_int("LOGIN_LOCK_MINUTES", 5)
    PASSWORD_EXPIRE_DAYS: int = _get_int("PASSWORD_EXPIRE_DAYS", 90)
    PASSWORD_MIN_LENGTH: int = _get_int("PASSWORD_MIN_LENGTH", 8)

    # ---- 模型网关（FR-15）----
    MODEL_PROVIDERS: str = _get("MODEL_PROVIDERS", "{}")
    MODEL_CACHE_POLICY: str = _get("MODEL_CACHE_POLICY", "CONTENT_HASH")
    GATEWAY_REQUEST_LIMIT_PER_MIN: int = _get_int("GATEWAY_REQUEST_LIMIT_PER_MIN", 60)

    # ---- ES9-P-14：监控 / 告警 / 备份 ----
    # 指标采集总开关（关闭时 /metrics 与 instrumentator 均不挂载，业务指标为 no-op）
    METRICS_ENABLED: bool = _get_bool("METRICS_ENABLED", False)
    # /metrics 端点 Bearer 令牌（空 = 不校验，仅限受信内网；生产务必设置强随机值）
    METRICS_TOKEN: str = _get("METRICS_TOKEN", "")
    # watchdog / 告警推送的企业微信机器人 webhook（留空 = 仅本地日志）
    NOTIFY_WEBHOOK_URL: str = _get("NOTIFY_WEBHOOK_URL", "")

    # ---- 任务/执行 ----
    TASK_TIMEOUT_SECONDS: int = _get_int("TASK_TIMEOUT_SECONDS", 900)
    ENGINE_REDTEAM_STRICT: bool = _get_bool("ENGINE_REDTEAM_STRICT", True)
    ENABLE_LOCAL_MODELS: bool = _get_bool("ENABLE_LOCAL_MODELS", False)
    # ES9 遗留项：双轨判定一致率阈值（judge_pipeline.agreement_threshold 消费，
    # 一致率低于该值 → run 附 needs_review=true）
    JUDGE_AGREEMENT_THRESHOLD: float = _get_float("JUDGE_AGREEMENT_THRESHOLD", 0.85)

    # ---- 本地 Ollama Embedding（私有化默认通道，数据不出网）----
    OLLAMA_BASE_URL: str = _get(
        "OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1"
    )
    OLLAMA_EMBEDDING_MODEL: str = _get("OLLAMA_EMBEDDING_MODEL", "bge-m3")
    OLLAMA_EMBEDDING_ENABLED: bool = _get_bool("OLLAMA_EMBEDDING_ENABLED", True)

    # ---- 通知（FR-20）----
    SMTP_HOST: str = _get("SMTP_HOST", "")
    SMTP_PORT: int = _get_int("SMTP_PORT", 465)
    SMTP_USER: str = _get("SMTP_USER", "")
    SMTP_PASSWORD: str = _get("SMTP_PASSWORD", "")
    WEBHOOK_SECRET: str = _get("WEBHOOK_SECRET", "EvalShield-webhook-secret-dev")
    # O-3（越权修复）：X-Webhook-Token 免登录导出通道的数据作用域。
    # Webhook token 本身无租户上下文，按配置绑定校验范围：
    # - WEBHOOK_TENANT_ID：该通道归属租户（与 ci_trigger 审计归属一致，默认 1）；
    #   导出报告的 tenant_id 必须与之相符，否则 403。
    # - WEBHOOK_PROJECT_IDS：逗号分隔的项目白名单（空 = 不限项目）。
    WEBHOOK_TENANT_ID: int = _get_int("WEBHOOK_TENANT_ID", 1)
    WEBHOOK_PROJECT_IDS: str = _get("WEBHOOK_PROJECT_IDS", "")

    # ---- 文件/证据 ----
    EVIDENCE_DIR: str = _get(
        "EVIDENCE_DIR",
        str(Path(__file__).resolve().parent.parent / "data" / "evidence"),
    )
    REPORT_DIR: str = _get(
        "REPORT_DIR", str(Path(__file__).resolve().parent.parent / "data" / "reports")
    )
    # 缺陷附件上传目录（不写入 C 盘，随项目数据落在 E 盘）
    ATTACH_DIR: str = _get(
        "ATTACH_DIR",
        str(Path(__file__).resolve().parent.parent / "data" / "attachments"),
    )
    # SRC 源代码审计：ZIP 上传与工作解压目录（随项目数据落在 E 盘）
    SRC_UPLOAD_DIR: str = _get(
        "SRC_UPLOAD_DIR",
        str(Path(__file__).resolve().parent.parent / "data" / "src"),
    )
    # SRC 上传包大小上限（MB）
    SRC_MAX_UPLOAD_MB: int = _get_int("SRC_MAX_UPLOAD_MB", 50)
    # SRC 扫描任务僵死回收阈值（秒）：中间态超过该时长无更新置 FAILED
    SRC_STALE_TIMEOUT_SEC: int = _get_int("SRC_STALE_TIMEOUT_SEC", 1800)
    # ES9 遗留项：题库导入文件大小上限（MB，question_banks 导入链消费）
    QUESTION_IMPORT_MAX_MB: int = _get_int("QUESTION_IMPORT_MAX_MB", 50)
    # ES9 遗留项：交付四件套在 REPORT_DIR 下的目录名（services/delivery.py 消费）
    DELIVERY_DIR_NAME: str = _get("DELIVERY_DIR_NAME", "delivery")
    # ES9-P-08：外部扫描器二进制（semgrep/gitleaks）路径与规则目录
    # 缺二进制时任务以 FAILED + 明确 error_message 降级，不伪造结果
    SEMGREP_BIN: str = _get("SEMGREP_BIN", "semgrep")
    GITLEAKS_BIN: str = _get("GITLEAKS_BIN", "gitleaks")
    SEMGREP_RULES_DIR: str = _get(
        "SEMGREP_RULES_DIR",
        str(Path(__file__).resolve().parent.parent / "data" / "src" / "semgrep-rules"),
    )

    # ---- 前端 ----
    CORS_ORIGINS: str = _get(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # ---- 审计日志防篡改（第 2 章）----
    AUDIT_LOG_SEPARATE_DB: bool = _get_bool("AUDIT_LOG_SEPARATE_DB", False)
    AUDIT_LOG_DB_URL: str = _get("AUDIT_LOG_DB_URL", "")
    AUDIT_LOG_VERIFY_CHAIN: bool = _get_bool("AUDIT_LOG_VERIFY_CHAIN", True)

    # WORM 归档
    AUDIT_LOG_WORM_BACKEND: str = _get("AUDIT_LOG_WORM_BACKEND", "none")
    AUDIT_LOG_S3_BUCKET: str = _get("AUDIT_LOG_S3_BUCKET", "")
    AUDIT_LOG_S3_PREFIX: str = _get("AUDIT_LOG_S3_PREFIX", "audit-worm/")
    AUDIT_LOG_S3_ACCESS_KEY: str = _get("AUDIT_LOG_S3_ACCESS_KEY", "")
    AUDIT_LOG_S3_SECRET_KEY: str = _get("AUDIT_LOG_S3_SECRET_KEY", "")
    AUDIT_LOG_S3_ENDPOINT: str = _get("AUDIT_LOG_S3_ENDPOINT", "")
    AUDIT_LOG_WORM_LOCAL_PATH: str = _get("AUDIT_LOG_WORM_LOCAL_PATH", "")

    @property
    def AUDIT_DATABASE_URL(self) -> str:
        """审计日志数据库连接串（独立库或回退主库）。"""
        if self.AUDIT_LOG_SEPARATE_DB and self.AUDIT_LOG_DB_URL:
            return self.AUDIT_LOG_DB_URL
        return self.DATABASE_URL

    # ---- 沙箱隔离（Sandbox） ----
    SANDBOX_ENABLED: bool = _get_bool("SANDBOX_ENABLED", False)
    # ES9-P-03：沙箱拓扑模式
    #   docker_socket = 遗留模式（backend 直读 docker.sock 拉起一次性容器，已弃用）
    #   pool          = 静态 worker 池 + 共享卷 unix socket（不给 worker docker.sock）
    SANDBOX_MODE: str = _get("SANDBOX_MODE", "docker_socket").lower()
    SANDBOX_HOST: str = _get("SANDBOX_HOST", "evalshield-sandbox")
    SANDBOX_PORT: int = _get_int("SANDBOX_PORT", 9000)
    SANDBOX_UNIX_SOCKET: str = _get(
        "SANDBOX_UNIX_SOCKET", "/var/run/evalshield/sandbox.sock"
    )
    SANDBOX_USE_UNIX_SOCKET: bool = _get_bool("SANDBOX_USE_UNIX_SOCKET", False)
    SANDBOX_REQUEST_TIMEOUT: int = _get_int("SANDBOX_REQUEST_TIMEOUT", 30)
    SANDBOX_WORKER_IMAGE: str = _get("SANDBOX_WORKER_IMAGE", "sandbox-worker:latest")
    SANDBOX_CPU_LIMIT: str = _get("SANDBOX_CPU_LIMIT", "1.0")
    SANDBOX_MEM_LIMIT: str = _get("SANDBOX_MEM_LIMIT", "512m")
    SANDBOX_PIDS_LIMIT: int = _get_int("SANDBOX_PIDS_LIMIT", 64)
    SANDBOX_TMPFS_SIZE: str = _get("SANDBOX_TMPFS_SIZE", "64m")
    SANDBOX_SECCOMP_PROFILE: str = _get(
        "SANDBOX_SECCOMP_PROFILE", "/app/seccomp-default.json"
    )
    SANDBOX_DEFAULT_TIMEOUT: int = _get_int("SANDBOX_DEFAULT_TIMEOUT", 300)
    SANDBOX_MAX_TIMEOUT: int = _get_int("SANDBOX_MAX_TIMEOUT", 1800)
    SANDBOX_LOG_MAX_BYTES: int = _get_int("SANDBOX_LOG_MAX_BYTES", 2 * 1024 * 1024)

    # ---- 真实工具链（引擎真实执行）----
    # 浏览器二进制目录（Playwright），默认指向 E 盘，避免写入 C:\Users\...\AppData\Local\ms-playwright
    PLAYWRIGHT_BROWSERS_PATH: str = _get(
        "PLAYWRIGHT_BROWSERS_PATH", os.getenv("HOME", "") + "/.evalshield/ms-playwright"
    )
    # JMeter 安装目录（含 bin/jmeter.bat）
    JMETER_HOME: str = _get(
        "JMETER_HOME", os.getenv("JMETER_HOME", "/opt/jmeter")
    )
    # JMeter 压测执行超时（秒）
    JMETER_TIMEOUT_SECONDS: int = _get_int("JMETER_TIMEOUT_SECONDS", 600)
    # UI 引擎默认被测前端地址
    UI_DEFAULT_BASE_URL: str = _get("UI_DEFAULT_BASE_URL", "http://127.0.0.1:8891")
    # API/DATAFLOW 引擎默认被测后端地址
    API_DEFAULT_BASE_URL: str = _get(
        "API_DEFAULT_BASE_URL", "http://127.0.0.1:8000"
    )

    # ---- AI 自测化测试（自动探测，《AI自测化测试详细开发.md》v2.0 §2.1）----
    # 白名单唯一来源：test_environments 表（Project.environments 为遗留字段，不参与）
    DISCOVER_TARGET_SOURCE: str = _get(
        "DISCOVER_TARGET_SOURCE", "TEST_ENVIRONMENTS"
    )  # R3 白名单来源：TEST_ENVIRONMENTS（唯一来源）
    DISCOVER_ALLOWED_HOSTS_EXTRA: str = _get("DISCOVER_ALLOWED_HOSTS_EXTRA", "")  # 开发环境临时放行，生产恒空
    DISCOVER_VALIDATE_REDIRECT: bool = _get_bool("DISCOVER_VALIDATE_REDIRECT", True)
    # A9（CFG-03/04/07/15）：SSRF 与写保护契约配置
    DISCOVER_BLOCK_PRIVATE_NETWORKS: bool = _get_bool("DISCOVER_BLOCK_PRIVATE_NETWORKS", True)
    DISCOVER_RESOLVE_THEN_VALIDATE: bool = _get_bool("DISCOVER_RESOLVE_THEN_VALIDATE", True)
    DISCOVER_WRITE_CONFIRM_REQUIRED: bool = _get_bool("DISCOVER_WRITE_CONFIRM_REQUIRED", True)
    DISCOVER_EXECUTOR: str = _get("DISCOVER_EXECUTOR", "ASYNCIO")  # R1 架构裁决：asyncio，无 Celery
    DISCOVER_MODE_DEFAULT: str = _get("DISCOVER_MODE_DEFAULT", "DISCOVER")
    DISCOVER_ALLOW_DELETE: bool = False                       # 恒 False，任何模式不真实删除
    DISCOVER_MAX_ROUTES_PER_JOB: int = _get_int("DISCOVER_MAX_ROUTES_PER_JOB", 50)
    DISCOVER_DATASET_MAX_ROWS: int = _get_int("DISCOVER_DATASET_MAX_ROWS", 100)  # D-04：数据集入库截断上限（原硬编码 100）
    DISCOVER_LLM_MAX_MODULES: int = _get_int("DISCOVER_LLM_MAX_MODULES", 30)
    DISCOVER_HTTP_TIMEOUT: int = _get_int("DISCOVER_HTTP_TIMEOUT", 15)
    DISCOVER_PLAYWRIGHT_HEADLESS: bool = _get_bool("DISCOVER_PLAYWRIGHT_HEADLESS", False)
    DISCOVER_HUMAN_WAIT_TIMEOUT: int = _get_int("DISCOVER_HUMAN_WAIT_TIMEOUT", 300)
    DISCOVER_HUMAN_MAX_ATTEMPTS: int = _get_int("DISCOVER_HUMAN_MAX_ATTEMPTS", 3)  # 验证类输入失败的重试上限（通用）
    DISCOVER_SESSION_TTL: int = _get_int("DISCOVER_SESSION_TTL", 7200)
    # 阶段超时（DS-05）：发现阶段固定超时；生成阶段动态 = max(base, 60+20×模块数) 上限 300s；硬上限用于中间态回收（DS-06）
    DISCOVER_DISCOVERING_TIMEOUT: int = _get_int("DISCOVER_DISCOVERING_TIMEOUT", 120)
    DISCOVER_GENERATING_TIMEOUT_BASE: int = _get_int("DISCOVER_GENERATING_TIMEOUT_BASE", 120)
    DISCOVER_HARD_TIMEOUT: int = _get_int("DISCOVER_HARD_TIMEOUT", 600)
    # ---- 自动化浏览器登录适配层（无人值守复测）----
    # 无人值守模式：检测到验证码/短信/弹框等人工组件时不等待人工，直接快速失败并给出明确提示。
    # 默认 False（保持人机协作交互流程）；CI/定时无人值守复测场景置 True。
    DISCOVER_AUTH_AUTO_ONLY: bool = _get_bool("DISCOVER_AUTH_AUTO_ONLY", False)
    # 登录页 URL（默认取目标根地址）；目标系统登录表单不在首页时显式指定，如
    # DISCOVER_LOGIN_URL=http://124.222.46.36:9091/#/login
    DISCOVER_LOGIN_URL: str = _get("DISCOVER_LOGIN_URL", "")
    # 登录表单选择器（空 = 走通用识别规则：input[type=text]/input[type=password]/submit 按钮）；
    # 目标系统使用自定义组件（非标准 input）时显式配置，保障无人值守全自动登录命中。
    DISCOVER_LOGIN_USERNAME_SELECTOR: str = _get("DISCOVER_LOGIN_USERNAME_SELECTOR", "")
    DISCOVER_LOGIN_PASSWORD_SELECTOR: str = _get("DISCOVER_LOGIN_PASSWORD_SELECTOR", "")
    DISCOVER_LOGIN_SUBMIT_SELECTOR: str = _get("DISCOVER_LOGIN_SUBMIT_SELECTOR", "")
    # 工作区/租户输入框选择器（可选；空 = 通用识别 placeholder/name 关键字）。
    # 目标登录页含"工作区/租户/组织"字段时，配合创建任务表单的「工作区」自动填充。
    DISCOVER_LOGIN_TENANT_SELECTOR: str = _get("DISCOVER_LOGIN_TENANT_SELECTOR", "")

    def ensure_dirs(self) -> None:
        for d in (self.EVIDENCE_DIR, self.REPORT_DIR, self.ATTACH_DIR, self.SRC_UPLOAD_DIR):
            Path(d).mkdir(parents=True, exist_ok=True)

    # T1 生产配置 fail-fast（见优化7说明书 §1；EDITION 非法值即 raise 的同一纪律推广到密钥）
    _INSECURE = {
        "EvalShield-dev-secret-change-me-in-prod-2026",
        "EvalShield-webhook-secret-dev",
    }

    def assert_production_safe(self) -> None:
        # F-02 修复：SECRET_KEY 是 JWT 与静态签名的信任根，任何 EDITION 下
        # 空值 / 命中开发默认黑名单 / 短于 32 位一律拒绝启动（community 不放行）。
        if (
            not self.SECRET_KEY
            or self.SECRET_KEY in self._INSECURE
            or len(self.SECRET_KEY) < 32
        ):
            raise RuntimeError(
                f"拒绝启动（EDITION={self.EDITION}）：SECRET_KEY 未配置为强随机值"
                "（禁止空值/开发默认值/短于 32 位）。"
                "请运行 scripts/deploy/gen-env.ps1 生成 .env"
            )
        if self.EDITION in ("enterprise", "saas"):
            bad = [
                k for k in ("WEBHOOK_SECRET",)
                if getattr(self, k) in self._INSECURE or len(getattr(self, k)) < 32
            ]
            if bad:
                raise RuntimeError(
                    f"生产形态 {self.EDITION} 拒绝启动：{','.join(bad)} 未配置为强随机值。"
                    "请运行 scripts/deploy/gen-env.ps1 生成 .env"
                )
        # community 的 WEBHOOK_SECRET 放行（开源用户开箱可跑，风险自负——GitLab OMNIBUS 同款口径）


settings = Settings()
settings.ensure_dirs()

# EDITION 值域校验（非法值启动即 raise，见方案 §2-B3）
if settings.EDITION not in ("community", "saas", "enterprise"):
    raise RuntimeError(
        f"EDITION 非法值: {settings.EDITION!r}（允许 community/saas/enterprise）"
    )

# T1 密钥 fail-fast（EDITION 校验后执行，见优化7说明书 §1）
settings.assert_production_safe()

# 让 Playwright 在 import 时即读到 E 盘浏览器目录（尊重环境变量，setdefault 兜底）
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", settings.PLAYWRIGHT_BROWSERS_PATH)
