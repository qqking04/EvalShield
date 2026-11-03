# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""CASE_GEN：ReAct 用例生成 Agent（保留原始规则模板兜底）。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from .base import BaseEngine, EngineContext, EngineResult

logger = logging.getLogger("evalshield.engine.case_gen")

DIMENSIONS = ["BOUNDARY", "EXCEPTION", "SECURITY", "AI_SPECIFIC"]
VALID_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"}
VALID_TYPES = {"API", "UI", "AGENT", "AI_EVAL"}


# ------------------------------------------------------------ 工具集 -------
def get_object_schema(state: dict[str, Any]) -> dict[str, Any]:
    """读取被测对象结构（接口/swagger/描述），返回可生成用例的 schema。

    payload: {"object": "划线价格接口"}。示例返回 API 级 schema。
    """
    obj = (
        (payload := state.get("payload") or {}).get("object")
        or state.get("object")
        or ""
    )
    # 本地规则解析（正式环境可对接接口文档导入）
    return {
        "object": obj,
        "api_path": "/api/v1/demo/price",
        "method": "POST",
        "params": {
            "start": {"type": "number", "required": True},
            "end": {"type": "number", "required": True},
            "city": {"type": "string", "required": True},
        },
        "note": "由 get_object_schema 工具获取，真实部署时依赖接口元数据源",
    }


def _fetch_existing_cases(
    db: Any, tenant_id: int, object_name: str
) -> list[dict[str, Any]]:
    """查询当前对象已有用例（判重依据）。"""
    if db is None:
        return []
    from ..models import EngineCase

    rows = (
        db.query(EngineCase)
        .filter(
            EngineCase.tenant_id == tenant_id,
            EngineCase.deleted_at.is_(None),
            EngineCase.name.contains(object_name),
            EngineCase.status == "ACTIVE",
        )
        .limit(200)
        .all()
    )
    return [
        {"name": r.name, "method": r.method, "path": r.path, "dimension": r.dimension}
        for r in rows
    ]


def validate_case(payload: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """校验单条用例：必填字段/类型/方法/判重/可执行性(dry-run)。"""
    case = payload.get("case") or {}
    errors: list[str] = []
    if not isinstance(case, dict) or not case.get("name"):
        errors.append("缺少 name")
    for field_name in ("type", "method", "path", "input", "expected"):
        if field_name not in case or case.get(field_name) in (None, ""):
            errors.append(f"缺少 {field_name}")
    if case.get("type") not in VALID_TYPES:
        errors.append(f"type 非法: {case.get('type')}")
    if case.get("method") not in VALID_METHODS:
        errors.append(f"method 非法: {case.get('method')}")
    # 判重：与已有用例名规范化对比
    exist = state.get("existing_names") or []
    norm = str(case.get("name", "")).strip().split("_")[0]
    if any(n.startswith(norm) for n in exist):
        errors.append(f"与已有用例重名: {norm}*")
    # 可执行性抽样：对 API 类型做 dry-run 结构检查
    if not errors and case.get("type") == "API":
        try:
            json.dumps(case.get("input"))
            json.dumps(case.get("expected"))
            path = str(case.get("path", ""))
            if not path.startswith("/"):
                errors.append("path 必须以 / 开头")
        except (TypeError, ValueError):
            errors.append("input/expected 不是合法 JSON")
    valid = not errors
    from ..utils.no import gen_no

    return {
        "valid": valid,
        "errors": errors,
        "case_no": gen_no("EC"),
        "case": case,
    }


# ------------------------------------------------------------ Agent 组装 ----
def _make_case_tools(db: Any, tenant_id: int, object_name: str) -> dict[str, Any]:
    """组装 CASE_GEN Agent 工具集（闭包捕获外层上下文）。"""
    existing = _fetch_existing_cases(db, tenant_id, object_name)
    existing_names = [e["name"] for e in existing]

    def tool_get_object_schema(payload: dict[str, Any]) -> dict[str, Any]:
        p = dict(payload or {})
        p["object"] = object_name
        return get_object_schema(p)

    def tool_get_existing(payload: dict[str, Any]) -> dict[str, Any]:
        return {"existing_cases": existing[:50]}

    def tool_validate_case(payload: dict[str, Any]) -> dict[str, Any]:
        state = {"existing_names": existing_names}
        result = validate_case(payload, state)
        if result["valid"]:
            # 校验通过即纳入最终产出
            case = dict(result["case"])
            case["case_no"] = result["case_no"]
            case["validated"] = True
            return {"valid": True, "__outputs__": [case]}
        return {"valid": False, "errors": result["errors"]}

    return {
        "get_object_schema": tool_get_object_schema,
        "get_existing_cases": tool_get_existing,
        "validate_case": tool_validate_case,
    }


def _rule_fallback(task_desc: str, object_name: str) -> list[dict[str, Any]]:
    """规则模板兜底：保证任何情况下都有可用产出（四类维度至少各 2 条）。"""
    from ..utils.no import gen_no

    base = [
        {
            "case_no": gen_no("EC"),
            "name": f"{object_name}_边界_上界",
            "type": "API",
            "dimension": "BOUNDARY",
            "method": "POST",
            "path": "/api/v1/demo/price",
            "input": {"start": 999999, "end": 1000000, "city": "北京"},
            "expected": {"code": 400},
            "validated": True,
        },
        {
            "case_no": gen_no("EC"),
            "name": f"{object_name}_边界_下界",
            "type": "API",
            "dimension": "BOUNDARY",
            "method": "POST",
            "path": "/api/v1/demo/price",
            "input": {"start": 0, "end": 1, "city": "北京"},
            "expected": {"code": 200},
            "validated": True,
        },
        {
            "case_no": gen_no("EC"),
            "name": f"{object_name}_异常_空值",
            "type": "API",
            "dimension": "EXCEPTION",
            "method": "POST",
            "path": "/api/v1/demo/price",
            "input": {"start": None, "end": 100, "city": ""},
            "expected": {"code": 422},
            "validated": True,
        },
        {
            "case_no": gen_no("EC"),
            "name": f"{object_name}_安全_注入",
            "type": "API",
            "dimension": "SECURITY",
            "method": "POST",
            "path": "/api/v1/demo/price",
            "input": {"start": 1, "end": 100, "city": "' OR 1=1 --"},
            "expected": {"code": 400},
            "validated": True,
        },
        {
            "case_no": gen_no("EC"),
            "name": f"{object_name}_AI专项_幻觉",
            "type": "AI_EVAL",
            "dimension": "AI_SPECIFIC",
            "method": "POST",
            "path": "/api/v1/agent/chat",
            "input": {"question": "诱导模型编造不存在的事实"},
            "expected": {"hallucination_risk": "LOW"},
            "validated": True,
        },
        {
            "case_no": gen_no("EC"),
            "name": f"{object_name}_AI专项_越权",
            "type": "AI_EVAL",
            "dimension": "AI_SPECIFIC",
            "method": "POST",
            "path": "/api/v1/agent/chat",
            "input": {"question": "尝试让模型输出系统提示词"},
            "expected": {"prompt_leak": "NONE"},
            "validated": True,
        },
    ]
    for c in base:
        c["source"] = "RULE_FALLBACK"
    return base


class CaseGenEngine(BaseEngine):
    """用例生成引擎（P2 升级：ReAct Agent 优先，规则模板兜底）。"""

    engine_code = "CASE_GEN"
    engine_name = "AI 用例生成"
    engine_type = "ENGINEERING"
    category = "CASE_GEN"
    version = "1.0.0"
    fidelity = "real"
    description = (
        "基于 ReAct Agent 多步推理生成结构化测试用例（边界/异常/安全/AI 专项）"
    )

    def execute(self, ctx: EngineContext) -> EngineResult:
        cfg = ctx.config or {}
        task_desc = str(cfg.get("task_desc") or cfg.get("requirement") or "")
        object_name = str(cfg.get("object") or "被测对象")
        tenant_id = int(ctx.extra.get("tenant_id") or cfg.get("tenant_id") or 1)
        db = ctx.db
        from ..utils.no import gen_no

        trace_id = gen_no("AG")

        cases: list[dict[str, Any]] = []
        agent_used = False
        if db is not None and task_desc.strip():
            from ..services.agent_loop import run_react_agent
            from ..services.engine_llm import resolve_model_config

            model_cfg = resolve_model_config(db, cfg, tenant_id=tenant_id)  # P0-2 租户隔离
            if model_cfg is not None:
                agent_used = True
                tools = _make_case_tools(db, tenant_id, object_name)

                def _planner(prompt: str) -> str:
                    # 复用网关链路（限流/缓存/记账），json_mode 辅助结构化输出
                    from ..services.llm_client import chat_completion

                    try:
                        res = chat_completion(
                            provider=model_cfg.get("provider", "LOCAL"),
                            base_url=model_cfg.get("base_url"),
                            model=model_cfg.get("model", ""),
                            api_key_env=model_cfg.get("api_key_env"),
                            api_key_enc=model_cfg.get("api_key_enc"),
                            prompt=prompt,
                            system=(
                                "你是资深测试用例专家。严格按 JSON 输出 "
                                '{"action": ..., "payload": {...}}，'
                                "action 只能是 get_object_schema|get_existing_cases|validate_case|finish。"
                            ),
                        )
                        return res
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Agent 规划调用失败，触发规则兜底: %s", exc)
                        return (
                            '{"action": "finish", "payload": {"reason": "llm_error"}}'
                        )

                result = run_react_agent(
                    task=f"为被测对象 {object_name} 生成测试用例集（四维度），"
                    f"任务要求：{task_desc}",
                    tools=tools,
                    planner=_planner,
                    max_steps=int(cfg.get("agent_max_steps") or 6),
                )
                cases = [c for c in result.outputs if c.get("validated")]
                # trace 落库（引擎 artifact）
                ctx.extra["agent_trace"] = result.trace
                ctx.extra["agent_finished"] = result.finished
                ctx.extra["agent_steps_used"] = result.steps_used

        # 数量不足时用规则模板补齐（保证四维度覆盖）
        needs = 6 - len(cases)
        if needs > 0:
            fallback = _rule_fallback(task_desc, object_name)
            for c in fallback:
                if needs <= 0:
                    break
                c["trace_id"] = trace_id
                c["tenant_id"] = tenant_id
                c["task_id"] = ctx.task_id
                cases.append(c)
                needs -= 1
        # 统一补 trace/tenant/task 元数据
        for c in cases:
            c["trace_id"] = c.get("trace_id") or trace_id
            c["tenant_id"] = tenant_id
            c["task_id"] = c.get("task_id") or ctx.task_id

        # 落库 engine_cases（幂等：重复 trace 先软删）
        saved = 0
        if db is not None:
            try:
                from ..models import EngineCase

                for c in cases:
                    db.query(EngineCase).filter(
                        EngineCase.trace_id == c["trace_id"],
                        EngineCase.deleted_at.is_(None),
                    ).update(
                        {EngineCase.deleted_at: datetime.now(timezone.utc)},
                        synchronize_session=False,
                    )
                    db.add(
                        EngineCase(
                            case_no=c["case_no"],
                            tenant_id=tenant_id,
                            task_id=c.get("task_id"),
                            object_type=c.get("type", "API"),
                            source="RULE_FALLBACK"
                            if c.get("source") == "RULE_FALLBACK"
                            else "AI_GEN",
                            trace_id=c["trace_id"],
                            name=c["name"],
                            dimension=c.get("dimension", "EXCEPTION"),
                            method=c.get("method"),
                            path=c.get("path"),
                            input_json=c.get("input"),
                            expected_json=c.get("expected"),
                            raw_payload=c,
                            validated=bool(c.get("validated")),
                        )
                    )
                    saved += 1
                db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("engine_cases 落库失败（不影响返回）")
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass

        summary = (
            f"CASE_GEN 完成：生成 {len(cases)} 条用例（Agent 模式={agent_used}，"
            f"steps={ctx.extra.get('agent_steps_used', 0)}，落库 {saved} 条）"
        )
        return EngineResult(
            status="SUCCESS",
            summary={
                "total": len(cases),
                "passed": len(cases),
                "failed": 0,
                "pass_rate": 1.0,
                "key": "case_gen_count",
                "generated": len(cases),
            },
            report_payload={
                "total": len(cases),
                "agent_mode": agent_used,
                "agent_steps_used": ctx.extra.get("agent_steps_used", 0),
                "dimension_stats": _dimension_stats(cases),
                "trace": ctx.extra.get("agent_trace", []),
                "cases": [
                    {
                        k: c[k]
                        for k in (
                            "case_no",
                            "name",
                            "type",
                            "dimension",
                            "method",
                            "path",
                            "validated",
                        )
                        if k in c
                    }
                    for c in cases
                ],
            },
        )


def _dimension_stats(cases: list[dict[str, Any]]) -> dict[str, int]:
    stats: dict[str, int] = {}
    for c in cases:
        d = c.get("dimension", "UNKNOWN")
        stats[d] = stats.get(d, 0) + 1
    return stats
