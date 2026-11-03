# -*- coding: utf-8 -*-
"""sandbox-worker 入口：在隔离容器内运行，负责加载引擎并执行任务。"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# 将 backend 包加入路径（镜像构建时已复制整个 app 包）
sys.path.insert(0, "/app")

from app.engines.base import BaseEngine, EngineContext, EngineResult  # noqa: E402
from app.engines.registry import get_engine  # noqa: E402


def main(task_path: str, artifacts_dir: str) -> int:
    task_file = Path(task_path)
    if not task_file.exists():
        print(
            json.dumps(
                {"error": f"task file not found: {task_path}"}, ensure_ascii=False
            )
        )
        return 1

    task = json.loads(task_file.read_text(encoding="utf-8"))
    engine_code: str = task["engine_code"]
    config: dict = task.get("config", {})
    timeout_seconds: int = task.get("timeout_seconds", 300)

    # 组装上下文（db 为 None，沙箱内不连主库）
    ctx = EngineContext(
        task_id=task["task_id"],
        task_no=task.get("task_no", ""),
        step_id=0,
        step_no="",
        project_id=0,
        engine_code=engine_code,
        config=config,
        db=None,
        extra={"artifacts_dir": artifacts_dir},
    )

    engine = get_engine(engine_code)
    if engine is None:
        print(
            json.dumps(
                {"error": f"engine not found: {engine_code}"}, ensure_ascii=False
            )
        )
        return 2

    start = time.perf_counter()
    try:
        result: EngineResult = engine.execute(ctx)
    except Exception:
        err = traceback.format_exc()
        result = EngineResult(status="FAILED", error=err)

    duration_ms = int((time.perf_counter() - start) * 1000)

    output = {
        "status": result.status,
        "summary": result.summary,
        "report_payload": result.report_payload,
        "artifacts": result.artifacts,
        "error": result.error,
        "duration_ms": duration_ms,
    }
    # 最后一行输出 JSON，供网关解析
    print(json.dumps(output, ensure_ascii=False))
    return 0 if result.status == "SUCCESS" else 3


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: run.py <task.json> <artifacts_dir>", file=sys.stderr)
        sys.exit(9)
    sys.exit(main(sys.argv[1], sys.argv[2]))
