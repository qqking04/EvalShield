# -*- coding: utf-8 -*-
"""
ES8-BUG-009 独立性能基线 locustfile（4 场景 taskset，locust tag 区分）。

与 backend/app/commercial/engines/locust_perf.py（LOCUST_PERF 引擎插件，禁改区）
完全独立：本文件面向 EvalShield 自身 API 的回归基线采集，判据口径对齐
backend/tests/test_es8_perf_baseline.py：

  tag=quality    质量视图聚合（GET /api/projects/{id}/quality-overview?days=30）
                 判据 P95 < 2000ms（千任务 30d 聚合口径，HTTP 侧近似）
  tag=platform   SaaS 看板 4 端点（overview/revenue/funnel/usage-top）
                 判据 单次 < 2000ms
  tag=ingest     批量摄入 100 条（POST /api/traces/ingest，X-API-Key 认证）
                 判据 < 5000ms
  tag=retention  保留策略读取（GET /api/retention/policies）
                 口径详见 docs/internal/retention-purge-baseline.md
                 说明：5000 行 purge 为服务内部定时任务（BATCH_LIMIT=5000），
                 无 HTTP 触发端点（见 test_es8_perf_baseline.py PERF-04），
                 此处以策略读取端点近似保留链路的 HTTP 开销。

运行示例（短压 10s）：
  $env:ES8_TOKEN="<JWT>"; $env:ES8_API_KEY="<ingest密钥>"
  locust -f scripts/locustfile_es8.py --headless -t 10s -u 5 -r 5 \
    --tags quality --host http://localhost:8000

环境变量：ES8_TARGET_HOST / ES8_PROJECT_ID / ES8_API_KEY / ES8_TOKEN
"""
import os
import time

from locust import HttpUser, between, tag, task

PROJECT_ID = int(os.environ.get("ES8_PROJECT_ID", "1"))
API_KEY = os.environ.get("ES8_API_KEY", "")
TOKEN = os.environ.get("ES8_TOKEN", "")

INGEST_BATCH = 100  # 与 PERF-03 判据同档：100 条/请求


def _build_traces(n: int):
    """通用推送 payload：{traces:[{request,response,model,tokens}]}（≤100 条/请求）。

    tokens 为整数（与 PERF-03 测试口径 / server ingest 契约一致：
    backend/tests/test_es8_perf_baseline.py 用 "tokens": 10；
    server traces.py 对 tokens 执行 int()，故必须发 int 而非 dict）。
    """
    ts = int(time.time())
    return {
        "traces": [
            {
                "request": f"es8 perf probe {ts}-{i}",
                "response": "ok",
                "model": "es8-perf-probe",
                "tokens": 20,
            }
            for i in range(n)
        ]
    }


class Es8BaselineUser(HttpUser):
    """4 场景共享一个 User 类，用 --tags 挑选 taskset。"""

    host = os.environ.get("ES8_TARGET_HOST", "http://localhost:8000")
    wait_time = between(0.1, 0.3)

    def on_start(self):
        headers = {}
        if TOKEN:
            headers["Authorization"] = f"Bearer {TOKEN}"
        self.auth_headers = headers
        self.ingest_headers = dict(headers)
        if API_KEY:
            self.ingest_headers["X-API-Key"] = API_KEY

    # ------------------------------------------------------------------
    @tag("quality")
    @task
    def quality_overview(self):
        """PERF-01 近似：千任务质量视图聚合，判据 P95 < 2000ms。"""
        self.client.get(
            f"/api/projects/{PROJECT_ID}/quality-overview",
            params={"days": 30},
            headers=self.auth_headers,
            name="/api/projects/{id}/quality-overview",
        )

    # ------------------------------------------------------------------
    @tag("platform")
    @task(1)
    def platform_overview(self):
        """PERF-02：看板端点单次 < 2s（4 端点各挂独立 task）。"""
        self.client.get("/api/platform/overview", headers=self.auth_headers)

    @tag("platform")
    @task(1)
    def platform_revenue(self):
        self.client.get(
            "/api/platform/revenue", params={"months": 12}, headers=self.auth_headers
        )

    @tag("platform")
    @task(1)
    def platform_funnel(self):
        self.client.get(
            "/api/platform/funnel", params={"weeks": 12}, headers=self.auth_headers
        )

    @tag("platform")
    @task(1)
    def platform_usage_top(self):
        self.client.get(
            "/api/platform/usage/top",
            params={"days": 30, "limit": 10},
            headers=self.auth_headers,
        )

    # ------------------------------------------------------------------
    @tag("ingest")
    @task
    def ingest_batch100(self):
        """PERF-03：批量 100 条摄入，判据 < 5000ms。"""
        self.client.post(
            "/api/traces/ingest",
            json=_build_traces(INGEST_BATCH),
            headers=self.ingest_headers,
        )

    # ------------------------------------------------------------------
    @tag("retention")
    @task
    def retention_policies(self):
        """口径详见 docs/internal/retention-purge-baseline.md
        PERF-04 近似：purge 无 HTTP 端点（服务内 BATCH_LIMIT=5000），
        以策略读取覆盖保留链路 HTTP 开销。"""
        self.client.get(
            "/api/retention/policies", headers=self.auth_headers
        )
