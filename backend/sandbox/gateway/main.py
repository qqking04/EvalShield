# -*- coding: utf-8 -*-
"""evalshield-sandbox 网关：接收执行任务并分发到隔离执行载体。

两种模式（SANDBOX_MODE，ES9-P-03）：
- pool（推荐）：分发到 compose 静态 worker 池（无 docker.sock）。
  任务经共享卷原子交接，agent 监听 /shared/agents/{worker_id}.sock；
  本进程内 _executions 状态机保留（get_execution 依赖，不可删）。
- legacy（默认，弃用兼容）：经挂载的 docker.sock 拉起一次性容器。
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class _UnixHTTPConnection(http.client.HTTPConnection):
    """经 Unix stream socket 收发标准 HTTP（pool 模式访问 worker agent）。"""

    def __init__(self, sock_path: str, timeout: float = 10.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self._sock_path = sock_path

    def connect(self) -> None:  # type: ignore[override]
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._sock_path)
        self.sock = sock


# ------------------------------------------------------------------
# 配置（环境变量驱动，与 backend 风格保持一致）
# ------------------------------------------------------------------
class _Settings:
    HOST: str = os.environ.get("SANDBOX_HOST", "0.0.0.0")
    PORT: int = int(os.environ.get("SANDBOX_PORT", "9000"))
    WORKER_IMAGE: str = os.environ.get("SANDBOX_WORKER_IMAGE", "sandbox-worker:latest")
    CPU_LIMIT: str = os.environ.get("SANDBOX_CPU_LIMIT", "1.0")
    MEM_LIMIT: str = os.environ.get("SANDBOX_MEM_LIMIT", "512m")
    PIDS_LIMIT: int = int(os.environ.get("SANDBOX_PIDS_LIMIT", "64"))
    TMPFS_SIZE: str = os.environ.get("SANDBOX_TMPFS_SIZE", "64m")
    SECCOMP_PROFILE: str = os.environ.get(
        "SANDBOX_SECCOMP_PROFILE", "/app/seccomp-default.json"
    )
    LOG_MAX_BYTES: int = int(os.environ.get("SANDBOX_LOG_MAX_BYTES", "2097152"))
    DATA_DIR: str = os.environ.get("SANDBOX_DATA_DIR", "/app/data/sandbox")
    # worker 容器数据卷：主机/daemon 侧有效（sandbox 容器内 /app/data 来自该命名卷）
    DATA_VOLUME: str = os.environ.get(
        "SANDBOX_DATA_VOLUME", "evalshield_evalshield_sandbox_data"
    )
    # ES9-P-03：pool | legacy（默认 legacy 保持向后兼容；compose 推荐 pool）
    MODE: str = os.environ.get("SANDBOX_MODE", "legacy").lower()
    SHARED_DIR: str = os.environ.get("SANDBOX_SHARED_DIR", "/shared")
    AGENT_TTL: int = int(os.environ.get("SANDBOX_AGENT_TTL", "15"))
    REVERSE_PROXY_BASE: str = os.environ.get("SANDBOX_REVERSE_PROXY_BASE", "")


settings = _Settings()
Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)

app = FastAPI(title="EvalShield Sandbox Gateway", version="1.0.0")
logger = logging.getLogger("sandbox")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ------------------------------------------------------------------
# 内存存储（生产环境可替换为 Redis + DB）
# ------------------------------------------------------------------
_executions: dict[str, dict[str, Any]] = {}


# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------
class ExecuteRequest(BaseModel):
    task_id: int = Field(..., gt=0)
    engine_code: str = Field(..., min_length=1, max_length=32)
    config: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=1, le=1800)
    artifacts_in: list[str] = Field(default_factory=list)


class ExecutionResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: dict[str, Any] | None = None


# ------------------------------------------------------------------
# WorkerPool（ES9-P-03 pool 模式：静态 worker 池，全程不触碰 docker.sock）
# ------------------------------------------------------------------
_WORKER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _mem_limit_mb() -> int | None:
    """解析 SANDBOX_MEM_LIMIT（如 512m / 2g）供前端展示内存水位分母。"""
    raw = settings.MEM_LIMIT.strip().lower()
    m = re.match(r"^(\d+)\s*([kmg]?)b?$", raw)
    if not m:
        return None
    val = int(m.group(1))
    factor = {"k": 1 / 1024, "m": 1, "g": 1024, "": 1 / (1024 * 1024)}[m.group(2)]
    return int(val * factor)


class WorkerPool:
    """发现并轮询 worker agent（共享卷注册文件 + unix socket 交接）。"""

    def __init__(self, shared_dir: str, ttl: int) -> None:
        self.root = Path(shared_dir)
        self.agents_dir = self.root / "agents"
        self.jobs_dir = self.root / "jobs"
        self.results_dir = self.root / "results"
        self.ttl = ttl

    # -- 发现与心跳 --
    def workers(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self.agents_dir.is_dir():
            return out
        now = time.time()
        for f in sorted(self.agents_dir.glob("*.json")):
            try:
                info = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            wid = str(info.get("worker_id") or f.stem)
            if not _WORKER_NAME_RE.match(wid):
                continue
            stale = (now - float(info.get("ts") or 0)) > self.ttl
            out.append(
                {
                    "worker_id": wid,
                    "status": "DEAD" if stale else str(info.get("status") or "IDLE"),
                    "current_tasks": int(info.get("current_tasks") or 0),
                    "mem_mb": info.get("mem_mb"),
                    "mem_limit_mb": _mem_limit_mb(),
                }
            )
        return out

    def pick(self) -> str | None:
        """轮询选一个健康且负载最低的 worker。"""
        alive = [w for w in self.workers() if w["status"] != "DEAD"]
        if not alive:
            return None
        alive.sort(key=lambda w: w["current_tasks"])
        return alive[0]["worker_id"]

    # -- 交接 --
    def enqueue(self, worker_id: str, job_id: str, payload: dict) -> None:
        """写任务到共享卷（原子 rename 交接，设计 §3.1.1-B）。"""
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.jobs_dir / f"{job_id}.json.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.jobs_dir / f"{job_id}.json")

    def post(self, worker_id: str, path: str, payload: dict | None = None,
             method: str = "POST") -> dict[str, Any]:
        conn = _UnixHTTPConnection(str(self.agents_dir / f"{worker_id}.sock"))
        try:
            body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json", "Connection": "close"}
            if method == "GET":
                conn.request("GET", path, headers=headers)
            else:
                conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read().decode("utf-8")
            return {"_status": resp.status, **json.loads(raw)} if raw else {"_status": resp.status}
        finally:
            conn.close()

    def await_result(self, job_id: str, timeout_seconds: int) -> dict[str, Any]:
        """轮询结果文件直到 worker 写完或超时。"""
        out = self.results_dir / f"{job_id}.json"
        deadline = time.monotonic() + timeout_seconds + 10
        while time.monotonic() < deadline:
            if out.exists():
                try:
                    return json.loads(out.read_text(encoding="utf-8"))
                except Exception:
                    pass  # 半写状态（极少见，原子写兜底），下一轮重试
            time.sleep(0.5)
        return {
            "job_id": job_id,
            "status": "TIMEOUT",
            "logs": "",
            "error": f"等待 worker 结果超过 {timeout_seconds} 秒",
        }


worker_pool = WorkerPool(settings.SHARED_DIR, settings.AGENT_TTL)


def _run_pool(
    execution_no: str,
    task_id: int,
    engine_code: str,
    config: dict,
    timeout_seconds: int,
) -> dict[str, Any]:
    """pool 模式执行：交给静态 worker 池，网关不创建容器。"""
    result: dict[str, Any] = {
        "execution_no": execution_no,
        "worker_id": None,
        "sandbox_id": None,
        "mode": "pool",
        "status": "RUNNING",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": None,
        "exit_code": None,
        "logs": "",
        "artifacts": [],
        "result_payload": {},
        "error_msg": None,
    }
    worker_id = worker_pool.pick()
    if not worker_id:
        result["status"] = "FAILED"
        result["ended_at"] = datetime.now(timezone.utc).isoformat()
        result["error_msg"] = (
            "worker 池无在线实例（请确认 compose --profile sandbox 已启动 sandbox-worker）"
        )
        return result

    result["worker_id"] = worker_id
    result["sandbox_id"] = worker_id
    script = (
        f"python -u /app/run.py "
        f"{Path(settings.SHARED_DIR) / 'jobs' / (execution_no + '.json')} "
        f"{Path(settings.SHARED_DIR) / 'results' / execution_no}"
    )
    worker_pool.enqueue(
        worker_id,
        execution_no,
        {
            "job_id": execution_no,
            "task_id": task_id,
            "engine_code": engine_code,
            "config": config,
            "timeout_seconds": timeout_seconds,
        },
    )
    try:
        ack = worker_pool.post(
            worker_id,
            "/exec",
            {"job_id": execution_no, "script": script, "timeout_s": timeout_seconds},
        )
        if ack.get("_status", 0) >= 400:
            result["status"] = "FAILED"
            result["error_msg"] = f"worker 拒绝任务：{ack.get('error') or ack}"
            result["ended_at"] = datetime.now(timezone.utc).isoformat()
            return result
    except Exception as exc:
        logger.exception("[%s] worker dispatch failed", execution_no)
        result["status"] = "FAILED"
        result["error_msg"] = f"worker 分发失败: {exc}"
        result["ended_at"] = datetime.now(timezone.utc).isoformat()
        return result

    payload = worker_pool.await_result(execution_no, timeout_seconds)
    result["status"] = str(payload.get("status") or "FAILED")
    result["logs"] = payload.get("logs") or ""
    result["exit_code"] = payload.get("exit_code")
    result["error_msg"] = payload.get("error")
    # 与 legacy 路径同构：解析 run.py stdout 最后一行 JSON 作为引擎结果
    for line in reversed(result["logs"].strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                inner = json.loads(line)
            except json.JSONDecodeError:
                continue
            result["result_payload"] = inner.get("summary") or inner
            if inner.get("status"):
                result["status"] = str(inner["status"])
            if inner.get("error"):
                result["error_msg"] = inner["error"]
            break
    artifacts_dir = Path(settings.SHARED_DIR) / "results" / execution_no
    if artifacts_dir.is_dir():
        for f in artifacts_dir.iterdir():
            if f.is_file():
                result["artifacts"].append(
                    {"name": f.name, "size": f.stat().st_size, "path": str(f)}
                )
    result["ended_at"] = datetime.now(timezone.utc).isoformat()
    return result


# ------------------------------------------------------------------
# Docker 运行辅助（legacy 模式：经挂载的 docker.sock，已弃用）
# ------------------------------------------------------------------
def _run_docker(
    execution_no: str,
    task_id: int,
    engine_code: str,
    config: dict,
    timeout_seconds: int,
) -> dict[str, Any]:
    """启动隔离容器并等待结果。"""
    sandbox_id = f"se-{uuid.uuid4().hex[:12]}"
    work_dir = Path(settings.DATA_DIR) / execution_no
    work_dir.mkdir(parents=True, exist_ok=True)

    # 写入任务描述文件（供 worker 读取）
    task_file = work_dir / "task.json"
    task_payload = {
        "execution_no": execution_no,
        "task_id": task_id,
        "engine_code": engine_code,
        "config": config,
        "timeout_seconds": timeout_seconds,
    }
    task_file.write_text(json.dumps(task_payload, ensure_ascii=False), encoding="utf-8")

    # 产物输出目录
    artifacts_dir = work_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        sandbox_id,
        "--network",
        "none",
        "--read-only",
        "--user",
        "1000:1000",
        "--cpus",
        settings.CPU_LIMIT,
        "--memory",
        settings.MEM_LIMIT,
        "--memory-swap",
        settings.MEM_LIMIT,
        "--pids-limit",
        str(settings.PIDS_LIMIT),
        "--cap-drop",
        "ALL",
        "--cap-add",
        "SETUID",
        "--cap-add",
        "SETGID",
        "--security-opt",
        f"seccomp={settings.SECCOMP_PROFILE}",
        "--tmpfs",
        f"/tmp:noexec,nosuid,size={settings.TMPFS_SIZE}",
        "--tmpfs",
        f"/var/tmp:noexec,nosuid,size={settings.TMPFS_SIZE}",
        "-v",
        f"{settings.DATA_VOLUME}:/app/data:rw",
        # note: worker 容器内通过 /app/data 命名卷访问 task.json 与 artifacts，
        # 避免容器内 docker daemon 把 -v 左侧路径误解析为宿主机路径
        settings.WORKER_IMAGE,
        "python",
        "-u",
        "/app/run.py",
        str(Path("/app/data/sandbox") / execution_no / "task.json"),
        str(Path("/app/data/sandbox") / execution_no / "artifacts"),
    ]

    logger.info("[%s] docker cmd: %s", execution_no, " ".join(cmd))

    result = {
        "execution_no": execution_no,
        "sandbox_id": sandbox_id,
        "status": "RUNNING",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": None,
        "exit_code": None,
        "logs": "",
        "artifacts": [],
        "result_payload": {},
        "error_msg": None,
    }

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            stdout, _ = proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()
            result["status"] = "TIMEOUT"
            result["error_msg"] = f"执行超过 {timeout_seconds} 秒，已强制终止"
        else:
            # 截断超大日志
            if len(stdout.encode("utf-8")) > settings.LOG_MAX_BYTES:
                stdout = stdout[: settings.LOG_MAX_BYTES // 2] + "\n...[truncated]\n"
            result["logs"] = stdout
            result["exit_code"] = proc.returncode

            if proc.returncode == 0:
                # 尝试解析最后一行 JSON 作为结果
                lines = stdout.strip().splitlines()
                for line in reversed(lines):
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            parsed = json.loads(line)
                            result["result_payload"] = parsed
                            break
                        except json.JSONDecodeError:
                            continue
                result["status"] = "SUCCESS"
            elif proc.returncode == 137:
                result["status"] = "OOM_KILLED"
                result["error_msg"] = "容器因内存不足被系统终止 (exit 137)"
            else:
                result["status"] = "FAILED"
                result["error_msg"] = f"进程异常退出，exit_code={proc.returncode}"

            # 采集产物列表
            for f in artifacts_dir.iterdir():
                if f.is_file():
                    result["artifacts"].append(
                        {
                            "name": f.name,
                            "size": f.stat().st_size,
                            "path": str(f),
                        }
                    )
    except Exception as exc:
        logger.exception("[%s] docker run failed", execution_no)
        result["status"] = "FAILED"
        result["error_msg"] = str(exc)

    result["ended_at"] = datetime.now(timezone.utc).isoformat()
    return result


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------
@app.post("/sandbox/execute", response_model=ExecutionResponse)
async def execute(req: ExecuteRequest):
    execution_no = f"SE-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    _executions[execution_no] = {
        "execution_no": execution_no,
        "status": "PENDING",
        "task_id": req.task_id,
        "engine_code": req.engine_code,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    # 同步执行（后续可改为后台线程/队列）；按模式分发（ES9-P-03）
    runner = _run_pool if settings.MODE == "pool" else _run_docker
    result = runner(
        execution_no=execution_no,
        task_id=req.task_id,
        engine_code=req.engine_code,
        config=req.config,
        timeout_seconds=req.timeout_seconds,
    )
    _executions[execution_no].update(result)
    return ExecutionResponse(
        data={
            "execution_no": execution_no,
            "status": result["status"],
            "started_at": result["started_at"],
            "worker_id": result.get("worker_id"),
            "sandbox_id": result.get("sandbox_id"),
        }
    )


@app.get("/sandbox/pool/status", response_model=ExecutionResponse)
async def pool_status():
    """ES9-P-03：worker 池状态（backend /api/sandbox/pool/status 代理至此）。

    legacy 模式下 workers 为空数组，backend 按 SANDBOX_MODE 决定是否 404。
    """
    workers = worker_pool.workers() if settings.MODE == "pool" else []
    return ExecutionResponse(
        data={"mode": settings.MODE, "workers": workers}
    )


@app.get("/sandbox/execution/{execution_no}", response_model=ExecutionResponse)
async def get_execution(execution_no: str):
    if execution_no not in _executions:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return ExecutionResponse(data=_executions[execution_no])


@app.get("/health")
async def health():
    return {"code": 0, "message": "ok", "data": {"status": "UP"}}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
