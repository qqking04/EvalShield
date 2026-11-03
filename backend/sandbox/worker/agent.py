# -*- coding: utf-8 -*-
"""sandbox-worker mini-agent（ES9-P-03 pool 模式）。

极简单进程 HTTP 服务（仅标准库，不导入任何 Docker SDK）：
- 监听共享卷 Unix socket：/shared/agents/{WORKER_ID}.sock
- 心跳注册：每 5s 原子写 /shared/agents/{WORKER_ID}.json
  （gateway 经同一共享卷读取，无需 dockerd / docker.sock）
- POST /exec：body {job_id, script, timeout_s, mem_mb}，subprocess 在自身
  容器内执行（容器已由 compose 施加 no-new-privileges + seccomp + rlimits），
  结果原子写 /shared/results/{job_id}.json 与 {job_id}.log
- GET /status/{job_id}；DELETE /jobs/{job_id}（SIGKILL 进程组）

拓扑前提：worker 容器 network_mode: none / read_only / cap_drop: ALL，
出网（被测目标）全部经 gateway 反向代理，worker 无网络栈。
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import AF_UNIX, SOCK_STREAM
from socketserver import UnixStreamServer

SHARED = Path(os.environ.get("SANDBOX_SHARED_DIR", "/shared"))
AGENT_DIR = SHARED / "agents"
JOBS_DIR = SHARED / "jobs"
RESULTS_DIR = SHARED / "results"
# 注册名匹配：字母/数字/下划线/中划线，防路径注入
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

WORKER_ID = os.environ.get("WORKER_ID") or f"sandbox-worker-{os.uname().nodename[:12]}"
SOCK_PATH = AGENT_DIR / f"{WORKER_ID}.sock"
HEARTBEAT_TTL = int(os.environ.get("SANDBOX_AGENT_TTL", "15"))

_jobs_lock = threading.Lock()
_jobs: dict[str, subprocess.Popen] = {}


def _atomic_write(path: Path, payload: str) -> None:
    """同目录 tmp + os.replace 原子交接（设计 §3.1.1-B）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _read_mem_mb() -> int | None:
    """best-effort 读取 cgroup 内存水位（MB）。"""
    try:
        cur = Path("/sys/fs/cgroup/memory.current")
        if cur.exists():
            return int(cur.read_text().strip()) // (1024 * 1024)
        stat = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
        if stat.exists():
            return int(stat.read_text().strip()) // (1024 * 1024)
    except Exception:
        pass
    return None


def _heartbeat_loop() -> None:
    while True:
        try:
            with _jobs_lock:
                running = sum(1 for p in _jobs.values() if p.poll() is None)
            _atomic_write(
                AGENT_DIR / f"{WORKER_ID}.json",
                json.dumps(
                    {
                        "worker_id": WORKER_ID,
                        "status": "RUNNING",
                        "current_tasks": running,
                        "mem_mb": _read_mem_mb(),
                        "ts": time.time(),
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception:
            pass
        time.sleep(5)


class Agent(UnixStreamServer):
    allow_reuse_address = True

    def __init__(self, path: Path, handler: type) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        super().__init__(str(path), handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默，避免污染 stdout 协议行
        pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/exec":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception as exc:
            return self._send(400, {"error": f"bad request: {exc}"})
        job_id = str(req.get("job_id") or "")
        script = req.get("script") or ""
        if not NAME_RE.match(job_id):
            return self._send(400, {"error": "invalid job_id"})
        timeout_s = int(req.get("timeout_s") or 300)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        def _run() -> None:
            out_path = RESULTS_DIR / f"{job_id}.json"
            log_path = RESULTS_DIR / f"{job_id}.log"
            try:
                popen_kwargs: dict = {
                    "cwd": "/tmp",
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.STDOUT,
                    "text": True,
                }
                if os.name == "posix":
                    popen_kwargs["start_new_session"] = True
                with _jobs_lock:
                    proc = _jobs.setdefault(job_id, subprocess.Popen(script, shell=True, **popen_kwargs))
                try:
                    stdout, _ = proc.communicate(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    _kill(proc)
                    stdout, _ = proc.communicate()
                    payload = {"job_id": job_id, "status": "TIMEOUT",
                               "error": f"执行超过 {timeout_s} 秒，已强制终止"}
                else:
                    payload = {"job_id": job_id, "status": "SUCCESS" if proc.returncode == 0 else "FAILED",
                               "exit_code": proc.returncode}
                log_path.write_text(stdout or "", encoding="utf-8")
                payload["logs"] = stdout or ""
                _atomic_write(out_path, json.dumps(payload, ensure_ascii=False))
            except Exception as exc:  # agent 内部兜底：结果必须可查
                _atomic_write(
                    out_path,
                    json.dumps({"job_id": job_id, "status": "FAILED", "error": str(exc)}, ensure_ascii=False),
                )
            finally:
                with _jobs_lock:
                    _jobs.pop(job_id, None)

        threading.Thread(target=_run, daemon=True).start()
        self._send(202, {"job_id": job_id, "status": "RUNNING", "worker_id": WORKER_ID})

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, {"status": "UP", "worker_id": WORKER_ID})
        if self.path.startswith("/status/"):
            job_id = self.path[len("/status/"):]
            if not NAME_RE.match(job_id):
                return self._send(400, {"error": "invalid job_id"})
            out = RESULTS_DIR / f"{job_id}.json"
            if out.exists():
                try:
                    return self._send(200, json.loads(out.read_text(encoding="utf-8")))
                except Exception:
                    pass
            with _jobs_lock:
                if job_id in _jobs:
                    return self._send(200, {"job_id": job_id, "status": "RUNNING"})
            return self._send(404, {"job_id": job_id, "status": "PENDING"})
        return self._send(404, {"error": "not found"})

    def do_DELETE(self):
        if not self.path.startswith("/jobs/"):
            return self._send(404, {"error": "not found"})
        job_id = self.path[len("/jobs/"):]
        if not NAME_RE.match(job_id):
            return self._send(400, {"error": "invalid job_id"})
        with _jobs_lock:
            proc = _jobs.get(job_id)
        if proc is not None:
            _kill(proc)
        for d in (JOBS_DIR, RESULTS_DIR):
            for suffix in (".json", ".log"):
                f = d / f"{job_id}{suffix}"
                if f.exists():
                    try:
                        f.unlink()
                    except OSError:
                        pass
        self._send(200, {"job_id": job_id, "status": "KILLED"})


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix" and hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> int:
    for d in (AGENT_DIR, JOBS_DIR, RESULTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    # 心跳文件在 serve_forever 前先清一次陈旧 sock
    if SOCK_PATH.exists():
        SOCK_PATH.unlink()
    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    srv = Agent(SOCK_PATH, Handler)
    os.chmod(SOCK_PATH, 0o660)
    print(json.dumps({"worker_id": WORKER_ID, "agent": str(SOCK_PATH), "status": "UP"}))
    try:
        srv.serve_forever()
    finally:
        try:
            (AGENT_DIR / f"{WORKER_ID}.json").unlink(missing_ok=True)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
