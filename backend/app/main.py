# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""FastAPI 应用入口：挂载中间件、异常处理器、全局路由与能力路由。

统一响应约定：{"code":0,"data":...,"message":"ok"}；分页：{"code":0,"data":{"items":[],"total":N,...},"message":"ok"}
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# Windows 强制 ProactorEventLoopPolicy（WatchFiles 会把 asyncio 退化为 SelectorEventLoop，
# 导致 playwright.async_playwright.create_subprocess_exec → NotImplementedError）
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import settings
from fastapi.exceptions import RequestValidationError

from .errors import EvalError, eval_error_handler, unhandled_error_handler, validation_error_handler
from .logging_config import setup_logging
from .utils.no import gen_no

logger = logging.getLogger("evalshield.main")

# BUG-6：create_app（模块导入期）即打印 commercial-absent 等关键日志，
# 此时 lifespan 尚未执行 setup_logging → INFO 被 lastResort 丢弃。
# 提前初始化（内部 _CONFIGURED 幂等，lifespan 再调无副作用）。
setup_logging()


def _mount_commercial(app: FastAPI) -> bool:
    """商业模块唯一挂载入口。OSS 发布树无 app/commercial/ → ImportError 硬缺席。"""
    # community 形态（EDITION=community）：本地开发树可能带包，形态判定先行跳过
    if settings.EDITION == "community":
        logger.info("edition=community, skip mounting commercial")
        return False
    try:
        from .commercial.register import register_commercial
    except ImportError:
        logger.info("edition=commercial-absent (community build), skip mounting")
        return False
    return register_commercial(app)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：初始化日志目录与数据库表，启动 cron 调度器。"""
    setup_logging()
    settings.ensure_dirs()
    from .database import init_db

    # EM-01/A16：启动期 DB 不可用非致命——仅告警并保持进程存活，
    # 请求期由 get_db 显式探活统一降级为 5xx，避免 uvicorn 启动失败直接退出
    try:
        init_db()
    except Exception as exc:  # noqa: BLE001
        logger.warning("数据库不可用，启动继续（请求期将返回 5xx 降级）: %s", exc)

    # 网关限流规则热加载（gateway_rate_limits 表；失败不阻断启动）
    try:
        from .database import SessionLocal
        from .services.rate_limiter import rate_limiter_registry

        _s = SessionLocal()
        try:
            n = rate_limiter_registry.load_rules_from_db(_s)
            if n:
                logger.info("网关限流规则已加载 %d 条", n)
        finally:
            _s.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("网关限流规则加载失败（使用默认参数）: %s", exc)

    # License 能力位启动回放：进程重启后从 DB 恢复 ACTIVE license（否则企业能力会被误关）
    # 商业包物理隔离：community 构建无 app.commercial → ImportError 走下方 except 降级
    try:
        from .database import SessionLocal as _LS
        from .commercial.routers.license import restore_active_license

        _s2 = _LS()
        try:
            feats = restore_active_license(_s2)
            if feats is not None:
                logger.info("License 能力位已从数据库回放: %s", feats or "(无授权能力)")
        finally:
            _s2.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("License 回放失败（回退环境变量默认）: %s", exc)

    # DS-08：生产环境禁止配置 DISCOVER_ALLOWED_HOSTS_EXTRA（防开发白名单口子误带生产 → 拒绝启动）
    env = (os.getenv("ENV") or os.getenv("APP_ENV") or "").strip().lower()
    if env in ("prod", "production") and settings.DISCOVER_ALLOWED_HOSTS_EXTRA.strip():
        raise RuntimeError(
            "生产环境禁止配置 DISCOVER_ALLOWED_HOSTS_EXTRA（该口子仅限 dev/staging，生产必须留空）"
        )

    # DS-06：进程重启后回收无终态的进行中探测任务（asyncio 后台协程不跨进程，重启即丢失）
    # 商业包物理隔离：community 构建无该模块 → ImportError 静默跳过
    try:
        from .commercial.services.discover.job_manager import recover_inflight_jobs, start_stale_sweeper

        recover_inflight_jobs()
        # DS-06：周期扫描（30s）回收超时未推进的中间态任务
        start_stale_sweeper()
    except ImportError:
        pass

    # 优化12 BUG-007 配套：daemon 执行线程不跨进程，回收重启时悬挂的题库运行
    # （按 resume_run 差集续跑，后台线程执行；失败仅告警不阻断启动）
    try:
        from .services.bank_executor import recover_interrupted_runs

        recover_interrupted_runs()
    except Exception as exc:  # noqa: BLE001
        logger.warning("题库运行启动回收失败（可经续跑端点手动恢复）: %s", exc)

    # B7：community 版禁用 cron 调度器（定时/批量执行为付费能力）
    if settings.EDITION != "community":
        from .services.scheduler import start_scheduler

        start_scheduler()

    # SRC：内置规则首次启动幂等种子 + 僵死任务启动回收（失败不阻断启动）
    try:
        from .database import SessionLocal as _SL2
        from .commercial.services.src_audit import recover_stale_src_tasks, seed_builtin_rules

        _s3 = _SL2()
        try:
            n = seed_builtin_rules(_s3)
            if n:
                logger.info("SRC 内置规则已初始化 %d 条", n)
            r = recover_stale_src_tasks(_s3, reason="任务中断（启动回收）")
            if r:
                logger.info("SRC 僵死任务启动回收 %d 个", r)
        finally:
            _s3.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("SRC 内置规则初始化失败（可于首次调用时重试）: %s", exc)

    # ES9-P-13：引擎 fidelity 对账回写——类属性=单一事实源，
    # 启动即把 test_engines.fidelity 镜像成代码值（失败不阻断启动）
    try:
        from .database import SessionLocal as _FS
        from .engines.registry import sync_engine_fidelity

        _s4 = _FS()
        try:
            n = sync_engine_fidelity(_s4)
            if n:
                logger.info("引擎 fidelity 已回写 %d 行", n)
        finally:
            _s4.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("引擎 fidelity 回写失败（管理页展示可能滞后）: %s", exc)

    # ES9-P-04：引导 admin 账号——一次性口令仅 print 到 stdout 一次，禁止入 logger
    try:
        from .database import SessionLocal as _BS
        from .services.bootstrap import ensure_bootstrap_admin

        _s5 = _BS()
        try:
            _pwd, _created = ensure_bootstrap_admin(_s5)
            if _created:
                # 有意 print（非 logger）：供安装脚本捕获，进程日志不落盘明文
                print(f"INIT_ADMIN_ONCE_PASSWORD={_pwd}")
        finally:
            _s5.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("bootstrap admin 引导失败（可重启重试）: %s", exc)

    yield


def create_app() -> FastAPI:
    # ES9-P-06：生产口径默认关闭交互式文档入口（EXPOSE_DOCS=false → /api/docs、
    # /api/redoc、/api/openapi.json 全部 404，防攻击面暴露）
    app = FastAPI(
        title=settings.APP_NAME,
        version=__version__,
        description="EvalShield AI 系统测试服务平台",
        docs_url="/api/docs" if settings.EXPOSE_DOCS else None,
        redoc_url="/api/redoc" if settings.EXPOSE_DOCS else None,
        openapi_url="/api/openapi.json" if settings.EXPOSE_DOCS else None,
        lifespan=lifespan,
        redirect_slashes=False,
    )

    # CORS（前端开发与部署跨域）
    # F-09 收紧：methods / headers 显式枚举，不再使用 "*" 通配
    # （headers 依据 = 后端实际消费的自定义头：deps X-API-Key、main X-Request-Id、
    #   ci X-Webhook-Token、defect_sync X-Hub-Signature-256 / X-GitHub-Event）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-API-Key",
            "X-Request-Id",
            "X-Webhook-Token",
            "X-Hub-Signature-256",
            "X-GitHub-Event",
        ],
    )

    # 注册自定义异常 handler（必须在 middleware/include_router 之前）
    # FastAPI 内部 ExceptionMiddleware 会先于自定义 middleware 拦截 HTTPException，
    # 所以必须用 add_exception_handler 覆盖默认 handler，确保 BizError/AuthError
    # 等能按说明书约定返回 {"code":"ES-XXXX","message":"..."} 格式。
    app.add_exception_handler(EvalError, eval_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        """统一请求上下文：request_id、耗时、异常转统一响应。"""
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        start = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            return response
        except EvalError as exc:
            return JSONResponse(
                status_code=exc.http_status,
                content={
                    "code": exc.code,
                    "message": exc.message,
                    "data": None,
                    "request_id": request_id,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return await unhandled_error_handler(request, exc)

    # 优化7 T4：半态令牌（scope=pwd_change_only）全局拦截——
    # 白名单外的一切 /api 路由 403 ES-AUTH-PWD-REQUIRED，防「不改密也用」绕过。
    # ES9 BUG-004（D-03/PWD-01）定稿四条：change-password / logout / edition /
    # auth/me（改密页需回显当前账号信息）；实测扩展一条 /api/meta
    # （ES9-P-01/02：半态也需 flags 与升级对比页渲染导航）。
    _PWD_HALF_WHITELIST = (
        "/api/auth/change-password",
        "/api/auth/logout",
        "/api/edition",
        "/api/auth/me",
        "/api/meta",  # ES9-P-01/02：半态也需 flags 与升级对比页渲染导航
    )

    # 优化7 T5：License grace/revoked 只读锁白名单——改密/登出/License 激活放行；
    # 登录/刷新同样放行（否则宽限期会话过期后续证入口不可达，违反「续证必须可达」条款）
    _LIC_WRITE_WHITELIST = _PWD_HALF_WHITELIST + (
        "/api/license/activate",
        "/api/auth/login",
        "/api/auth/refresh",
    )
    _LIC_WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

    @app.middleware("http")
    async def pwd_half_session_middleware(request: Request, call_next):
        path = request.url.path
        if (
            path.startswith("/api")
            and not path.startswith(_PWD_HALF_WHITELIST)
            and request.method != "OPTIONS"
        ):
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                from .security import decode_token

                payload = decode_token(auth_header[7:])
                if payload and "pwd_change_only" in (payload.get("scope") or []):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "code": "ES-AUTH-PWD-REQUIRED",
                            "message": "首次登录必须修改初始密码后方可使用系统",
                            "data": None,
                        },
                    )

        # 优化7 T5：License grace/revoked 只读锁——写操作 403（GET 全通，不做破坏性锁定）；
        # phase 按存储的 expires_at 请求时动态重算（相变发生在运行期，不信启动快照）。
        if (
            request.method in _LIC_WRITE_METHODS
            and path.startswith("/api")
            and not path.startswith(_LIC_WRITE_WHITELIST)
        ):
            from .config import settings
            from .license_state import PHASE_GRACE, PHASE_REVOKED, resolve_license_state

            lic = resolve_license_state(
                getattr(request.app.state, "license_status", None),
                settings.LICENSE_GRACE_DAYS,
            )
            if lic.get("phase") in (PHASE_GRACE, PHASE_REVOKED):
                return JSONResponse(
                    status_code=403,
                    content={
                        "code": "ES-LIC-EXPIRED-GRACE",
                        "message": "授权已过期，系统处于只读宽限期，仅支持改密、登出与 License 激活",
                        "data": None,
                    },
                )
        return await call_next(request)

    # 健康检查
    @app.get("/api/health", tags=["system"])
    async def health():
        return {
            "code": 0,
            "message": "ok",
            "data": {"status": "UP", "name": settings.APP_NAME, "no": gen_no("HC")},
        }

    # 注册能力路由（auth / admin / business / engines / sandbox / reports 核心）
    from .routers import auth, admin, business, engines, sandbox, projects_ext, projects_quality, report_ext, targets, security, notify, monitors, review, traces, redteam, sso, retention, defect_sync, uat
    # U5：business.py 按域拆分（URL 零变更，与原 business router 同前缀注册）
    from .routers import projects_core, tasks_core, cases_core, health_core

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    # B8：版本形态契约（免登录，静态路径先于 business 注册避免路径参数抢占）
    from .routers import edition_core
    app.include_router(edition_core.router, prefix="/api", tags=["edition"])
    # ES9-P-01/02：元数据端点（feature-flags 登录态 / edition-matrix 免登录）
    from .routers import meta
    app.include_router(meta.router, prefix="/api/meta", tags=["meta"])
    # ES9-P-09/11/12：题库、事实源、交付四件套、标准对照（静态路径，先于 business 注册）
    from .routers import question_banks, fact_sources, delivery
    from .services.standards import build_meta_router
    app.include_router(question_banks.router, prefix="/api", tags=["question-banks"])
    app.include_router(fact_sources.router, prefix="/api", tags=["fact-sources"])
    app.include_router(delivery.router, prefix="/api", tags=["delivery"])
    app.include_router(build_meta_router(), prefix="/api", tags=["standards-meta"])
    # ES11：五道门禁/工作区/缺陷闭环/Trace 回流/报告交付/质量总览
    # （静态子路径先于 business 注册，避免 /{param} 抢占）
    from .routers import es11_dashboard, es11_defect, es11_eval, es11_report, es11_trace
    app.include_router(es11_eval.router, prefix="/api", tags=["es11-eval"])
    app.include_router(es11_defect.router, prefix="/api", tags=["es11-defect"])
    app.include_router(es11_trace.router, prefix="/api", tags=["es11-trace"])
    app.include_router(es11_report.router, prefix="/api", tags=["es11-report"])
    app.include_router(es11_dashboard.router, prefix="/api", tags=["es11-dashboard"])
    app.include_router(admin.router_public, prefix="/api/admin", tags=["admin-public"])
    app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
    # 商业模块唯一挂载点（billing / 组织 / 缺陷 / 合规 / SRC / CI / License 等 16 路由，
    # 顺序保持改造前相对位；community 构建物理缺席）
    app.state.commercial_mounted = _mount_commercial(app)
    # 静态路径在前，避免被 business 的 /{param} 路径参数路由抢先匹配
    app.include_router(projects_ext.router, prefix="/api", tags=["projects-ext"])
    # 优化4：项目质量视图（静态路径 /projects/{id}/quality-*）
    app.include_router(projects_quality.router, prefix="/api", tags=["projects-quality"])
    app.include_router(report_ext.router, prefix="/api", tags=["report-ext"])
    # ES9 UAT：验收报告（聚合/签核/分享/导出，router 自带 /api 前缀，先于 business 注册）
    app.include_router(uat.router, tags=["uat"])
    # 6 引擎改进 T1：被测系统门面（静态路径 /targets，先于 business 注册避免路径参数抢占）
    app.include_router(targets.router, prefix="/api", tags=["targets"])
    # ES8 M3：通知中心（独立前缀 /api/notify，渠道/规则/投递留痕）
    app.include_router(notify.router, prefix="/api/notify", tags=["notify"])
    # ES8 M4：定时监控与回归告警（独立前缀 /api/monitors）
    app.include_router(monitors.router, prefix="/api/monitors", tags=["monitors"])
    # ES8 M6：人工复核队列与 judge 校准（独立前缀 /api/review）
    app.include_router(review.router, prefix="/api/review", tags=["review"])
    # ES8 M8：在线评测最小闭环（trace 摄入 + 采样评分 + 回流，独立前缀 /api/traces）
    app.include_router(traces.router, prefix="/api/traces", tags=["traces"])
    # ES8 M9：生成式红队（样本池/审批 + 载荷变异 + 框架覆盖 + 防护建议包，独立前缀 /api/redteam）
    app.include_router(redteam.router, prefix="/api/redteam", tags=["redteam"])
    # ES8 M10：SSO 单点登录（公开链路与 auth 同前缀 /api/auth/sso；管理端点 /api/admin/sso）
    app.include_router(sso.router, prefix="/api/auth/sso", tags=["sso"])
    app.include_router(sso.router_admin, prefix="/api/admin/sso", tags=["sso-admin"])
    # ES8 M12：数据保留策略（独立前缀 /api/retention；注销端点在 billing 商业路由）
    app.include_router(retention.router, prefix="/api/retention", tags=["retention"])
    # ES8 M11：缺陷工单同步（目标管理 + webhook 收端 /api/defect-sync；推送端点挂 /api 下）
    app.include_router(defect_sync.router, prefix="/api/defect-sync", tags=["defect-sync"])
    app.include_router(defect_sync.push_router, prefix="/api", tags=["defect-sync"])
    app.include_router(tasks_core.router, prefix="/api", tags=["business"])
    app.include_router(projects_core.router, prefix="/api", tags=["business"])
    app.include_router(cases_core.router, prefix="/api", tags=["business"])
    app.include_router(health_core.router, prefix="/api", tags=["business"])
    app.include_router(business.router, prefix="/api", tags=["business"])
    app.include_router(engines.router, prefix="/api/engines", tags=["engines"])
    app.include_router(sandbox.router, prefix="/api", tags=["sandbox"])
    # 安全能力：A06 组件漏洞版本表查看/热更新（v2.0 推荐方案 #1）
    app.include_router(security.router, prefix="/api/security", tags=["security"])

    # F-01 修复：缺陷附件静态服务（ATTACH_DIR，E 盘）——裸 StaticFiles 无鉴权，
    # 改为 Bearer JWT 或 ?es_exp&es_sig 短时效签名双通道放行（secure_static.py）
    from .secure_static import SignedStaticFiles

    _attach_dir = Path(settings.ATTACH_DIR)
    _attach_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/api/attachments",
        SignedStaticFiles(kind="att", directory=str(_attach_dir)),
        name="attachments",
    )

    # v2.0 BUG-008：UI 截图证据静态服务（EVIDENCE_DIR）——同上，F-01 鉴权改造
    _evidence_dir = Path(settings.EVIDENCE_DIR)
    _evidence_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/api/evidence",
        SignedStaticFiles(kind="evi", directory=str(_evidence_dir)),
        name="evidence",
    )

    # RPT-07: 审计日志查询端点（单文件路由，不拆模块）
    # F-08 修复：与 /api/admin/audit-logs 同口径 RBAC（admin:log），不再仅登录态放行
    from .database import get_db
    from .deps import require_permission
    from .models import AuditLog
    from sqlalchemy.orm import Session
    from fastapi import Depends, Query

    @app.get("/api/audit-logs")
    async def list_audit_logs(
        page: int = 1, page_size: int = 20,
        action: str | None = None,
        db: Session = Depends(get_db),
        auth=Depends(require_permission("admin", "log")),
    ):
        q = db.query(AuditLog).filter(AuditLog.tenant_id == auth.tenant_id)
        if action:
            q = q.filter(AuditLog.action.like(f"%{action}%"))
        total = q.count()
        rows = q.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        items = []
        for r in rows:
            try:
                items.append({
                    "id": r.id,
                    "action": r.action,
                    "module": r.module,
                    "username": r.username,
                    "request_path": r.request_path,
                    "detail": r.detail,
                    "result": r.result,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                })
            except Exception:
                items.append({"raw": str(r)[:200]})
        return {"code": 0, "message": "ok", "data": {"items": items, "total": total}}

    # ES9-P-14：监控指标暴露（/metrics）。METRICS_ENABLED=false 或 prometheus
    # 可选依赖缺失时静默跳过；启用时按 METRICS_TOKEN 做 Bearer 校验。
    from .services.metrics import instrument_app

    instrument_app(app)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app", host=settings.SERVER_HOST, port=settings.SERVER_PORT, reload=False
    )
