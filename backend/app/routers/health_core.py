# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""业务路由：项目、任务（创建/执行/取消/进度）、用例、数据集、场景、评测、报告、模型网关、通知、仪表盘。

任务执行采用同步模拟调度：创建 TaskStep → EngineRegistry 执行 → 汇总 summary → 生成报告。
（真实异步执行器可在 scripts/ 中扩展为后台 worker。）
"""

from __future__ import annotations

import hashlib
import json
import csv
import io
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO

logger = logging.getLogger(__name__)

# FE-02/FE-05：需要非空 base_url 才能执行的 HTTP 类引擎（后端空串兜底校验）
_HTTP_BASED_ENGINES = {
    "API_TEST",
    "UI_TEST",
    "DATAFLOW_TEST",
    "PERF_TEST",
    "LOCUST_PERF",
    "PRIVILEGE_ESCALATION",
    "SELF_HEAL",
}

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import String, case, cast, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    AuthContext,
    authenticate_request,
    ensure_data_scope,
    require_permission,
)
from ..engines import EngineContext, engine_registry, run_engine_step
from ..engines.registry import discover_engines
from ..errors import BizError, NotFoundError
from ..services.audit import write_audit
from ..services.report_sections import compliance_conclusion
from ..models import (
    AuditLog,
    BillingPlan,
    BillingQuota,
    BillingTopUp,
    ComplianceClause,
    DataDict,
    DictItem,
    EvalRun,
    EvalSet,
    ModelConfig,
    ModelGatewayRecord,
    Notification,
    Project,
    ProjectMembers,
    Report,
    ReportComplianceAlignment,
    Scenario,
    SystemUser,
    TaskArtifact,
    TaskStep,
    TestCase,
    TestDataset,
    TestEngine,
    TestTask,
)
from ..schemas import (
    CaseCreate,
    CaseOut,
    CaseUpdate,
    DatasetCreate,
    DatasetGenerateRequest,
    DatasetOut,
    EvalRunCreate,
    EvalRunOut,
    EvalSetCreate,
    EngineOut,
    ModelConfigCreate,
    ModelConfigTestRequest,
    ModelConfigUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    ScenarioCreate,
    StepOut,
    TaskCreate,
    TaskOut,
    TaskRunRequest,
    VALID_CASE_CATEGORIES,
)
from ..services.llm_client import test_connection as llm_test_connection
from ..services.scheduler import next_run_at
from ..services.task_runner import is_running, launch_task_async
from ..utils.compat import run_cmd
from ..utils.cron import parse_cron
from ..utils.no import gen_no


router = APIRouter()
from ._business_common import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# ES9-P-14：机器探活端点（免登录，供 compose healthcheck / 负载均衡使用）
# ---------------------------------------------------------------------------
import os
from sqlalchemy import text as sa_text
from fastapi.responses import JSONResponse
from ..config import settings
from ..errors import ok

# 代码期望的 inti.sql 结构版本（= 最后一个 `inti.sql section NN` 节号）。
# 纪律：向 database/inti.sql 追加新节时必须同步 +1，否则 readyz 503 阻断流量。
INTI_SCHEMA_VERSION: int = 79  # 优化13：section 79（结构同步节，无新产物表；探针沿用 75/76 表）

# 版本对应的最新迁移节产物表（DB 探针：该表存在 ≈ 末节已应用）
_INTI_PROBE_TABLE = "es_tenant_backfill_map"  # section 75（M-003 租户回刷台账）
_INTI_PROBE_TABLES = [_INTI_PROBE_TABLE, "defect_events"]  # ES11 section 76 追加探针


def _inti_sql_candidates() -> list:
    """inti.sql 候选路径：环境变量 → 容器挂载 → 仓库相对路径。"""
    from pathlib import Path as _P

    env = os.getenv("INTI_SQL_PATH", "")
    cands = []
    if env:
        cands.append(_P(env))
    cands.append(_P("/database/inti.sql"))  # compose 只读挂载
    cands.append(
        _P(__file__).resolve().parents[3] / "database" / "inti.sql"
    )  # 开发树 backend/app/routers → repo root
    return cands


def _inti_file_version() -> int | None:
    """解析 inti.sql 最大节号；文件不可读返回 None。"""
    import re

    for cand in _inti_sql_candidates():
        try:
            text = cand.read_text(encoding="utf-8")
        except OSError:
            continue
        nums = [int(m) for m in re.findall(r"inti\.sql section (\d+)", text)]
        return max(nums) if nums else None
    return None


def _probe_disk() -> tuple[str, str]:
    """EVIDENCE_DIR / REPORT_DIR 所在卷水位（<90% 为 PASS）。"""
    import shutil

    details = []
    worst = "PASS"
    for name, path in (("evidence", settings.EVIDENCE_DIR), ("reports", settings.REPORT_DIR)):
        try:
            du = shutil.disk_usage(path)
            pct = round(du.used / du.total * 100, 1) if du.total else 0.0
            free_gb = round(du.free / 1024**3, 1)
            status = "PASS" if pct < 90.0 else "FAIL"
            details.append(f"{name}={pct}% used,{free_gb}GB free:{status}")
            if status == "FAIL":
                worst = "FAIL"
        except OSError as exc:
            details.append(f"{name}=unreadable({exc}):FAIL")
            worst = "FAIL"
    return worst, "; ".join(details)


def _probe_redis() -> tuple[str, str]:
    """REDIS_URL 配置时可选项：未配置=skipped，配置则 TCP 探测。"""
    import socket
    from urllib.parse import urlparse

    url = os.getenv("REDIS_URL", "")
    if not url:
        return "SKIPPED", "REDIS_URL not configured"
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 6379
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        return "PASS", f"redis {host}:{port} reachable"
    except OSError as exc:
        return "FAIL", f"redis probe failed: {exc}"


def _probe_sandbox() -> tuple[str, str]:
    """沙箱 unix socket 可选项：未启用=skipped（Windows 开发机无 AF_UNIX 亦跳过）。"""
    import socket

    if not (settings.SANDBOX_ENABLED and settings.SANDBOX_USE_UNIX_SOCKET):
        return "SKIPPED", "sandbox unix socket not enabled"
    if not hasattr(socket, "AF_UNIX"):
        return "SKIPPED", "AF_UNIX unsupported on this platform"
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect(settings.SANDBOX_UNIX_SOCKET)
        sock.close()
        return "PASS", f"socket {settings.SANDBOX_UNIX_SOCKET} reachable"
    except OSError as exc:
        return "FAIL", f"sandbox socket probe failed: {exc}"


@router.get("/healthz", response_model=dict)
def healthz(db: Session = Depends(get_db)):
    """存活探测（免登录）：DB SELECT 1 + 磁盘水位 + 可选项（Redis/沙箱 socket）。

    任一必需项 FAIL → 503；可选项 SKIPPED 不影响总判定，FAIL 也只降级为 WARN 明细。

    同步 def：探测体为阻塞 IO（DB/磁盘/socket），async 会串行化事件循环，
    拖垮同进程其他请求的 P95（ES11 M19 压测实测 20 并发 P95 2.0s）。
    """
    checks: dict[str, dict] = {}
    overall = "ok"

    try:
        db.execute(sa_text("SELECT 1"))
        checks["db"] = {"status": "pass", "detail": "SELECT 1 ok"}
    except Exception as exc:  # noqa: BLE001
        checks["db"] = {"status": "fail", "detail": str(exc)[:200]}
        overall = "fail"

    disk_status, disk_detail = _probe_disk()
    checks["disk"] = {
        "status": "pass" if disk_status == "PASS" else "fail",
        "detail": disk_detail,
    }
    if disk_status != "PASS":
        overall = "fail"

    redis_status, redis_detail = _probe_redis()
    checks["redis"] = {
        "status": {"PASS": "pass", "FAIL": "warn", "SKIPPED": "skipped"}[redis_status],
        "detail": redis_detail,
    }

    sb_status, sb_detail = _probe_sandbox()
    checks["sandbox"] = {
        "status": {"PASS": "pass", "FAIL": "warn", "SKIPPED": "skipped"}[sb_status],
        "detail": sb_detail,
    }

    payload = ok({"overall": overall, "checks": checks})
    if overall == "fail":
        return JSONResponse(status_code=503, content=payload)
    return payload


@router.get("/readyz", response_model=dict)
def readyz(db: Session = Depends(get_db)):
    """就绪探测（免登录）：inti.sql 文件版本标记 == 代码期望版本，且末节产物表已在 DB。

    compose 滚动发布时先流量打到 healthz，readyz 通过才接入读流量。
    """
    checks: dict[str, dict] = {}
    overall = "ok"

    expected = INTI_SCHEMA_VERSION
    file_ver = _inti_file_version()
    if file_ver is None:
        checks["inti_sql"] = {
            "status": "fail",
            "detail": f"inti.sql not readable (candidates: {[str(c) for c in _inti_sql_candidates()]})",
        }
        overall = "fail"
    elif file_ver != expected:
        checks["inti_sql"] = {
            "status": "fail",
            "detail": f"inti.sql section version {file_ver} != code expected {expected}",
        }
        overall = "fail"
    else:
        checks["inti_sql"] = {"status": "pass", "detail": f"section {file_ver} == expected {expected}"}

    try:
        missing = []
        for t in _INTI_PROBE_TABLES:
            row = db.execute(
                sa_text(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
                ),
                {"t": t},
            ).first()
            if not row:
                missing.append(t)
        if not missing:
            checks["db_migrations"] = {
                "status": "pass",
                "detail": f"probe tables {','.join(_INTI_PROBE_TABLES)} present",
            }
        else:
            checks["db_migrations"] = {
                "status": "fail",
                "detail": f"probe table {','.join(missing)} missing (inti.sql not applied?)",
            }
            overall = "fail"
    except Exception as exc:  # noqa: BLE001
        checks["db_migrations"] = {"status": "fail", "detail": str(exc)[:200]}
        overall = "fail"

    payload = ok(
        {
            "overall": overall,
            "expected_schema_version": expected,
            "checks": checks,
        }
    )
    if overall == "fail":
        return JSONResponse(status_code=503, content=payload)
    return payload


@router.get("/health/check", response_model=dict)
async def health_check(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """v2.0 P4：部署卫生检查（Docker 容器 + 端口 + 登录接口 + 最近实跑任务）。

    环境感知：本检查可能运行在容器内（docker compose 部署）或宿主机（本机服务模式）。
    容器内 127.0.0.1 回环只有自身 8000，需按 compose 服务 DNS 探测（db / evalshield-frontend /
    evalshield-sandbox / host.docker.internal），并回退回环兜底；Ollama 为可选组件（未装记 WARN）。
    """
    import asyncio
    import socket
    from pathlib import Path as _Path

    checks: list[dict] = []

    async def _probe(host: str, port: int) -> bool:
        def _do() -> bool:
            try:
                sock = socket.create_connection((host, port), timeout=2)
                sock.close()
                return True
            except OSError:
                return False
        return await asyncio.to_thread(_do)

    # 1) Docker：容器内（存在 /.dockerenv）→ 容器化部署就绪；宿主机 → 枚举容器名
    if _Path("/.dockerenv").exists():
        checks.append({"name": "Docker", "status": "PASS",
                       "message": "运行于容器内（docker compose 部署），服务连通性见端口探测项"})
    else:
        try:
            out = await run_cmd(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0:
                names = [n for n in out.stdout.splitlines() if n.strip()]
                for name in ("evalshield-db", "evalshield-backend", "evalshield-frontend", "evalshield-sandbox"):
                    found = any(name in n for n in names)
                    checks.append({"name": f"容器 {name}", "status": "PASS" if found else "WARN",
                                   "message": "运行中" if found else "未运行（本机服务模式可忽略）"})
            else:
                checks.append({"name": "Docker", "status": "WARN", "message": "docker 命令不可用（本机服务模式可忽略）"})
        except Exception as exc:  # noqa: BLE001
            checks.append({"name": "Docker", "status": "WARN", "message": f"docker 不可用：{exc.__class__.__name__}"})

    # 2) 端口：每项给出多个候选 (host, port)，任一连通即 PASS；optional=True 时失败记 WARN
    from ..config import settings as _settings

    _frontend_host = _settings.UI_DEFAULT_BASE_URL.split("//")[-1].split("/")[0].split(":")[0]
    _checks_def = (
        ("PostgreSQL", 5432, [(_settings.DB_HOST, 5432), ("db", 5432), ("127.0.0.1", 5432)], False),
        ("后端 API", 8000, [("127.0.0.1", 8000)], False),
        ("Ollama", 11434, [("host.docker.internal", 11434), ("127.0.0.1", 11434)], True),
        ("前端", 8891, [(_frontend_host, 80 if "evalshield-frontend" in _frontend_host else 8891),
                       ("evalshield-frontend", 80), ("127.0.0.1", 8891)], False),
        ("RAG 沙箱", _settings.SANDBOX_PORT,
         [(_settings.SANDBOX_HOST, _settings.SANDBOX_PORT),
          ("evalshield-sandbox", _settings.SANDBOX_PORT), ("127.0.0.1", _settings.SANDBOX_PORT)], False),
    )

    async def _probe_multi(targets):
        results = await asyncio.gather(*(_probe(h, p) for h, p in targets))
        return any(results)

    port_results = await asyncio.gather(
        *(_probe_multi(targets) for _, _, targets, _opt in _checks_def)
    )
    for (desc, port, _targets, optional), ok in zip(_checks_def, port_results):
        if ok:
            status, msg = "PASS", "监听中"
        elif optional:
            status, msg = "WARN", "未监听（可选组件，本机服务模式可忽略）"
        else:
            status, msg = "FAIL", "未监听"
        checks.append({"name": f"端口 {port}（{desc}）", "status": status, "message": msg})

    # 3) 数据库连通
    try:
        from sqlalchemy import text as _sql_text

        db.execute(_sql_text("SELECT 1"))
        checks.append({"name": "数据库查询", "status": "PASS", "message": "可用"})
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "数据库查询", "status": "FAIL", "message": str(exc)[:120]})

    # 4) 最近实跑任务
    try:
        latest = (
            db.query(TestTask)
            .filter(TestTask.deleted_at.is_(None))
            .order_by(TestTask.created_at.desc())
            .first()
        )
        if latest is None:
            checks.append({"name": "实跑任务", "status": "WARN", "message": "无历史任务"})
        else:
            _st = "PASS" if latest.status in ("SUCCESS", "COMPLETED_WITH_RISK") else "WARN"
            checks.append({"name": "实跑任务", "status": _st,
                           "message": f"最近任务 {latest.task_no} 状态：{latest.status}"})
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "实跑任务", "status": "FAIL", "message": str(exc)[:120]})

    passed = sum(1 for c in checks if c["status"] == "PASS")
    failed = sum(1 for c in checks if c["status"] == "FAIL")
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "healthy": failed == 0,
            "checks": checks,
            "summary": f"{passed}/{len(checks)} 通过，{failed} 失败",
        },
    }


# ES9-P-06（§3.2.3/§3.4.3）：口令治理 + 传输安全合并检查（前端 HealthCheck deploy-check 契约：
# deploy.password.checks / deploy.transport.checks + transport.protocol / transport.rate_limiter）
_DEFAULT_PWD_CANDIDATES = ("EvalShield@123",)


@router.get("/health/deploy-check", response_model=dict)
async def deploy_check(
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(authenticate_request),
):
    """部署合规检查（ES9-P-04/P-06 合并口径）：口令治理组 + 传输安全组。"""
    from ..config import settings as _settings

    # ---- 口令治理组 ----
    pwd_checks: list[dict] = []
    admin = (
        db.query(SystemUser)
        .filter(SystemUser.username == "admin", SystemUser.deleted_at.is_(None))
        .first()
    )
    if admin is None:
        pwd_checks.append({"name": "admin 账号", "status": "FAIL",
                           "message": "未找到 admin 账号（请检查引导流程）"})
    else:
        from ..security import verify_password as _verify

        leaked = any(_verify(p, admin.password_hash) for p in _DEFAULT_PWD_CANDIDATES)
        pwd_checks.append({
            "name": "默认口令残留",
            "status": "FAIL" if leaked else "PASS",
            "message": "admin 仍在使用出厂默认口令，请立即改密" if leaked
            else "admin 未使用任何已知默认口令",
        })
        pwd_checks.append({
            "name": "强制改密策略",
            "status": "PASS",
            "message": "admin 处于首登强制改密态（策略生效中）" if admin.must_change_pwd
            else "admin 已完成改密",
        })
    if _settings.INIT_ADMIN_PASSWORD.strip():
        pwd_checks.append({"name": "引导口令透传", "status": "WARN",
                           "message": "INIT_ADMIN_PASSWORD 显式配置了固定口令，建议留空由系统随机生成"})
    else:
        pwd_checks.append({"name": "引导口令透传", "status": "PASS",
                           "message": "未配置固定引导口令（新部署将随机生成一次性口令）"})

    # ---- 传输安全组 ----
    transport_checks: list[dict] = []
    transport_checks.append({
        "name": "交互式文档入口",
        "status": "WARN" if _settings.EXPOSE_DOCS else "PASS",
        "message": "/api/docs 已开启（生产部署建议 EXPOSE_DOCS=false）" if _settings.EXPOSE_DOCS
        else "/api/docs、/api/redoc、/api/openapi.json 已关闭",
    })
    # 协议：反向代理透传 X-Forwarded-Proto 优先（compose 部署直连后端恒为 http）
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "http").split(",")[0].strip().lower()
    transport_checks.append({
        "name": "传输协议",
        "status": "PASS" if proto == "https" else "WARN",
        "message": "HTTPS（经反向代理透传）" if proto == "https"
        else "当前为 http 明文，建议经 nginx/caddy 反向代理启用 TLS",
    })
    from ..services.rate_limiter import rate_limiter_registry

    rl_mode = "redis" if rate_limiter_registry._redis_client is not None else "memory"
    transport_checks.append({
        "name": "登录限流器",
        "status": "PASS",
        "message": "Redis 分布式限流" if rl_mode == "redis"
        else "进程内存限流（未配置 REDIS_URL，单实例精度足够爆破防护）",
    })
    _cors_wild = "*" in [o.strip() for o in _settings.CORS_ORIGINS.split(",")]
    transport_checks.append({
        "name": "CORS 策略",
        "status": "FAIL" if _cors_wild else "PASS",
        "message": "CORS_ORIGINS 含通配 *，存在跨域泄露风险" if _cors_wild
        else f"白名单模式：{_settings.CORS_ORIGINS[:80]}",
    })

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "password": {"checks": pwd_checks},
            "transport": {"checks": transport_checks, "protocol": proto, "rate_limiter": rl_mode},
        },
    }


