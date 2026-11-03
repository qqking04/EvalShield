# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ReAct Agent 循环：规划-执行-反思（用例生成专用）。

该模块不感知具体业务函数，通过注入 tools 与 planner 实现通用性；
CASE_GEN 引擎按 3.1.5 注入用例生成专用工具集。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("evalshield.agent_loop")

MAX_STEPS_DEFAULT = 6


@dataclass
class AgentStep:
    step: int
    action: str
    payload: dict[str, Any]
    result_summary: str


@dataclass
class AgentRunResult:
    finished: bool
    steps_used: int
    outputs: list[dict[str, Any]]
    trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finished": self.finished,
            "steps_used": self.steps_used,
            "outputs": self.outputs,
            "trace": self.trace,
        }


def run_react_agent(
    *,
    task: str,
    tools: dict[str, Callable],
    planner: Callable[[str], str],
    max_steps: int = MAX_STEPS_DEFAULT,
    finish_signal: str = "finish",
    extra_state: dict[str, Any] | None = None,
) -> AgentRunResult:
    """通用 ReAct 循环。

    - tools: {"get_object_schema": fn, ...}，fn(payload: dict) -> dict
    - planner: 输入 prompt 文本，输出模型响应文本（逐字 Promise 由调用方解析）或直接 dict。
      planner 约定返回 JSON 字符串：{"action": "...", "payload": {...}}
    - 循环保证次数上限，异常不外抛（记录后收敛）。
    """
    state: dict[str, Any] = dict(extra_state or {})
    scratchpad: list[str] = []
    outputs: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    finished = False
    step = 0

    for step in range(1, max_steps + 1):
        tool_desc = "\n".join(
            f"- {k}: {getattr(v, '__doc__', '') or ''}" for k, v in tools.items()
        )
        prompt = (
            f"任务：{task}\n"
            f"可用工具：\n{tool_desc}\n"
            f"已完成步骤（scratchpad）：\n{chr(10).join(scratchpad[-6:]) or '(无)'}\n"
            f"已产出且通过校验的用例：{json.dumps(outputs, ensure_ascii=False)[:2000]}\n"
            f"当前状态（内部）：{json.dumps(state, ensure_ascii=False)[:500]}\n"
            f'请输出 JSON：{{"action": "工具名 或 {finish_signal}", "payload": {{...}}}}'
        )
        raw = planner(prompt)
        action, payload = _parse_action(raw)
        if action is None:
            scratchpad.append(f"step{step}: 模型输出非法，忽略本轮")
            trace.append(
                {
                    "step": step,
                    "action": "PARSE_ERROR",
                    "payload": {},
                    "result": "模型输出不可解析",
                }
            )
            continue
        if action == finish_signal:
            finished = True
            trace.append(
                {"step": step, "action": "finish", "payload": {}, "result": "主动结束"}
            )
            scratchpad.append(f"step{step}: finish")
            break
        fn = tools.get(action)
        if fn is None:
            scratchpad.append(f"step{step}: 未知工具 {action}")
            trace.append(
                {
                    "step": step,
                    "action": action,
                    "payload": payload,
                    "result": "未知工具",
                }
            )
            continue
        try:
            result = fn(payload)
        except Exception as exc:  # noqa: BLE001
            result = {"error": str(exc)}
        # 工具若返回 {"__outputs__": [...]} 则并入最终 outputs（如 validate 通过列表）
        if isinstance(result, dict) and result.get("__outputs__"):
            outputs.extend(result["__outputs__"])
        summary = json.dumps(result, ensure_ascii=False)[:800]
        scratchpad.append(
            f"step{step}: {action}({json.dumps(payload, ensure_ascii=False)[:300]}) -> {summary}"
        )
        trace.append(
            {
                "step": step,
                "action": action,
                "payload": payload,
                "result": _safe_truncate(summary, 2000),
            }
        )

    return AgentRunResult(
        finished=finished,
        steps_used=min(step, max_steps),
        outputs=outputs,
        trace=trace,
    )


def _parse_action(raw: str | dict) -> tuple[str | None, dict[str, Any]]:
    """解析 planner 输出为 (action, payload)。支持 JSON 字符串或 dict。"""
    if isinstance(raw, dict):
        return str(raw.get("action") or ""), dict(raw.get("payload") or {})
    text = str(raw or "").strip()
    # 剥掉可能的 markdown 代码块
    if text.startswith("```"):
        text = text.strip("`")
        idx = text.find("\n")
        if idx != -1:
            text = text[idx + 1 :].strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return str(data.get("action") or ""), dict(data.get("payload") or {})
    except (json.JSONDecodeError, TypeError):
        pass
    return None, {}


def _safe_truncate(text: str, limit: int) -> str:
    return text[:limit] + ("..." if len(text) > limit else "")
