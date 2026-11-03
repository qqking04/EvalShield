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
from ..services.report_sections import (
    cn_no,
    compliance_conclusion,
    next_section_no,
    redteam_sections,
    security_sections,
    _cn_severity,
    _cn_verdict,
    _cn_engine,
    _cn_detection_result,
)

VECTOR_CN = {"DIRECT": "直接注入", "INDIRECT": "间接注入"}
STEP_STATUS_EXPORT_CN = {
    "SUCCESS": "成功", "PASSED": "通过", "FAILED": "失败", "SKIPPED": "已跳过",
    "RUNNING": "执行中", "PENDING": "待执行", "ERROR": "执行异常",
}
#: 步骤摘要 / 指标 JSON 键名中文化（MD / HTML / PDF 导出共用）
SUMMARY_KEYS_CN = {
    "key": "指标", "total": "用例总数", "passed": "通过数", "failed": "失败数",
    "warned": "警告数", "skipped": "跳过数", "pass_rate": "通过率",
    "threshold": "判定阈值", "avg_similarity": "平均语义相似度",
    "embedding_degraded": "向量模型降级", "severity_distribution": "严重度分布",
    "LOW": "低", "MEDIUM": "中", "HIGH": "高", "CRITICAL": "严重", "PASS": "通过",
    "NONE": "无", "hallucination_score": "幻觉得分", "redteam_safety_rate": "红队安全率",
    "score": "得分", "count": "数量", "items": "条目",
}


def _summary_cn(obj):
    """步骤摘要 → 中文键名与枚举值（嵌套 dict 递归，列表逐项，字符串叶子同表映射）。"""
    if isinstance(obj, dict):
        return {SUMMARY_KEYS_CN.get(str(k), str(k)): _summary_cn(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_summary_cn(i) for i in obj]
    if isinstance(obj, str):
        return SUMMARY_KEYS_CN.get(obj, obj)
    return obj


def _refs_cn(refs) -> str:
    """证据引用串 → 中文（ENGINE:XXX / STEP:FAILED 形态）。"""
    import re as _re

    def one(s: str) -> str:
        def _sub(m):
            kind, val = m.group(1).upper(), m.group(2)
            if kind == "ENGINE":
                return f"引擎:{_cn_engine(val)}"
            return f"步骤:{STEP_STATUS_EXPORT_CN.get(val.upper(), val)}"

        return _re.sub(r"(ENGINE|STEP):([A-Z_]+)", _sub, str(s))

    return ", ".join(one(r) for r in (refs or [])[:3]) or "-"


THREAT_TYPE_EXPORT_CN = {
    "direct_injection": "直接注入", "indirect_injection": "间接注入",
    "roleplay_escape": "角色扮演逃逸", "delimiter_attack": "分隔符攻击",
    "encoding_bypass": "编码绕过", "horizontal_escalation": "横向越权",
    "vertical_escalation": "纵向越权", "identity_impersonation": "身份冒充",
    "session_hijack": "会话劫持", "param_pollution": "参数污染",
    "cross_session_pollution": "跨会话污染", "sensitive_memory": "敏感信息记忆",
    "memory_poisoning": "记忆投毒", "credential_leakage": "凭据泄漏",
    "pii_leakage": "PII 泄漏",
    "direct_jailbreak": "直接越狱", "harmful_content": "有害内容",
    "data_leakage": "数据泄露", "prompt_injection": "提示注入",
}
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


def _plain_json(value):
    """把 Pydantic 模型/嵌套结构递归转成纯 JSON 可序列化对象（JSONB 落库前调用）。

    兼容 None / 原始 dict / list / 标量，避免 Object of type X is not JSON serializable。
    """
    if value is None:
        return None
    if isinstance(value, list):
        return [_plain_json(v) for v in value]
    if hasattr(value, "model_dump"):
        return _plain_json(value.model_dump(exclude_none=True))
    if isinstance(value, dict):
        return {k: _plain_json(v) for k, v in value.items()}
    return value


def _cov_row(m: str) -> dict:
    return {"module": m, "case_count": 0, "run_count": 0, "pass_rate": 0.0,
            "dataset_count": 0, "scenario_count": 0, "eval_set_count": 0}


def _dataset_module_from_name(name: str, candidates: list[str]) -> str:
    for c in candidates:
        if c != "未分类" and (c in name or name in c):
            return c
    return "未分类"


# ---------------------------------------------------------------------------
# P2-08：场景步骤类型扩展（if / loop / parallel）
# ---------------------------------------------------------------------------
_SCENARIO_NESTED_ACTIONS = {"if", "loop", "parallel"}


_SCENARIO_MAX_DEPTH = 2            # 嵌套动作最多 2 层（顶层 + 1 层内嵌）


_SCENARIO_LOOP_MAX_ITER = 100      # 单循环展开上限，防步骤爆炸


_SCENARIO_PARALLEL_MAX_BRANCHES = 8


_COND_OPS = {"eq", "neq", "contains", "not_contains", "gt", "lt", "gte", "lte", "not_empty", "exists", "in"}


_COND_OP_ALIAS = {"==": "eq", "!=": "neq", ">=": "gte", "<=": "lte", ">": "gt", "<": "lt"}


def _scenario_err(msg: str) -> BizError:
    """P2-08：场景编排非法 → ES-BIZ-0015（编译期拦截，避免运行期静默）。"""
    return BizError("ES-BIZ-0015", msg)


def _parse_condition_str(text) -> tuple[str, str, object]:
    """解析 "{{var}} == 5" 这类简写条件为 (left, op, right)。"""
    raw = str(text or "").strip()
    for sym in ("==", "!=", ">=", "<=", ">", "<"):
        if sym in raw:
            left, right = raw.split(sym, 1)
            return left.strip(), _COND_OP_ALIAS[sym], right.strip()
    return raw, "not_empty", None  # 仅左值 → 判非空/存在


def _normalize_condition(cond) -> dict:
    """把 if 步骤的条件归一为 {left, op, right}；非法运算符抛 ES-BIZ-0015。"""
    if isinstance(cond, dict):
        left = cond.get("left")
        op = str(cond.get("op") or "eq").strip().lower()
        right = cond.get("right")
    else:
        left, op, right = _parse_condition_str(cond)
    if op not in _COND_OPS:
        raise _scenario_err(f"if 步骤条件运算符 {op!r} 不支持（可用：{sorted(_COND_OPS)}）")
    if left in (None, ""):
        raise _scenario_err("if 步骤缺少条件左值（left）")
    return {"left": str(left), "op": op, "right": right}


def _int_or_err(value, label: str, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise _scenario_err(f"{label} 必须为整数")
    if v < lo or v > hi:
        raise _scenario_err(f"{label} 必须在 {lo}~{hi} 之间")
    return v


def _compile_nested(act: str, s: dict, cfg: dict, depth: int) -> dict:
    """编译单个嵌套动作（if/loop/parallel）为引擎可执行节点（P2-08）。"""
    if act == "if":
        then = _scenario_steps_to_engine(s.get("then") or [], depth + 1)
        els = _scenario_steps_to_engine(s.get("else") or [], depth + 1)
        if not then and not els:
            raise _scenario_err("if 步骤至少需要一个 then 或 else 分支步骤")
        raw_cond = s.get("cond") if s.get("cond") is not None else cfg
        return {"action": "branch", "cond": _normalize_condition(raw_cond), "then": then, "else": els}

    if act == "loop":
        inner = _scenario_steps_to_engine(s.get("steps") or [], depth + 1)
        if not inner:
            raise _scenario_err("loop 步骤必须包含至少一个循环体步骤")
        node = {
            "action": "loop",
            "steps": inner,
            "max_iter": _int_or_err(
                s.get("max_iter", cfg.get("max_iter", 20)), "loop max_iter", 1, _SCENARIO_LOOP_MAX_ITER
            ),
            "item_var": str(s.get("item_var") or "item")[:64],
        }
        over = s.get("over") or cfg.get("over")
        times = s.get("times", cfg.get("times"))
        if over:
            node["over"] = str(over)[:64]
        elif times is not None:
            node["times"] = _int_or_err(times, "loop times", 1, _SCENARIO_LOOP_MAX_ITER)
        else:
            raise _scenario_err("loop 步骤必须指定 times（次数）或 over（遍历变量）")
        return node

    # parallel
    raw_branches = s.get("branches")
    if not isinstance(raw_branches, list) or len(raw_branches) < 2:
        raise _scenario_err("parallel 步骤至少需要 2 个分支")
    if len(raw_branches) > _SCENARIO_PARALLEL_MAX_BRANCHES:
        raise _scenario_err(f"parallel 分支数不能超过 {_SCENARIO_PARALLEL_MAX_BRANCHES}")
    branches = []
    for bi, br in enumerate(raw_branches):
        nodes = _scenario_steps_to_engine(br or [], depth + 1)
        if not nodes:
            raise _scenario_err(f"parallel 第 {bi + 1} 个分支为空")
        branches.append(nodes)
    return {"action": "parallel", "branches": branches, "fail_fast": bool(s.get("fail_fast", True))}


def _scenario_steps_to_engine(steps, depth: int = 0) -> list[dict]:
    """把场景编辑器纵向步骤递归编译为引擎可执行节点（P2-08）。

    线性动作（request/assert/extract/delay/db_query）→ http/sleep 节点；
    嵌套动作 if/loop/parallel → branch/loop/parallel 节点（子步骤递归编译）。
    嵌套层级超过 _SCENARIO_MAX_DEPTH 或配置非法 → 抛 ES-BIZ-0015。
    """
    if depth > _SCENARIO_MAX_DEPTH:
        raise _scenario_err(f"场景嵌套层级超过上限 {_SCENARIO_MAX_DEPTH}")
    out: list[dict] = []
    cur: dict | None = None

    def flush():
        nonlocal cur
        if cur:
            if not cur.get("assertions"):
                cur["assertions"] = []
            if not cur.get("path"):
                # 空路径 HTTP 步骤视为校验动作，命中基于响应；无抓手时置为 SKIP 级 no-op
                cur = {"action": "http", "path": "", "assertions": []}
            out.append(cur)
            cur = None

    def start_http(method, path):
        return {"action": "http", "method": method, "path": path, "expected_status": None,
                "assertions": []}

    for s in steps or []:
        if not isinstance(s, dict):
            continue
        act = (s.get("action") or "").strip().lower()
        cfg = s.get("config") or ({} if isinstance(s.get("config"), dict) else {})

        # ===== P2-08：嵌套动作分支（if/loop/parallel）=====
        if act in _SCENARIO_NESTED_ACTIONS:
            flush()
            out.append(_compile_nested(act, s, cfg, depth))
            continue

        if act in ("request", "get", "post", "put", "delete", "patch", "http"):
            flush()
            method = (cfg.get("method") or
                      ("GET" if act in ("http", "request") else act.upper())).upper()
            cur = start_http(method, s.get("target") or "")
            if cfg.get("expected_status") is not None:
                cur["expected_status"] = int(cfg["expected_status"])
            h = cfg.get("headers")
            if h:
                cur["headers"] = h if isinstance(h, dict) else h
            if cfg.get("body"):
                cur["body"] = cfg.get("body")
            if cfg.get("assert_type"):
                if cfg["assert_type"] == "status" and cfg.get("expected") is not None:
                    cur["expected_status"] = int(cfg["expected"])
                else:
                    cur["assertions"].append(_assert_row(cfg, s.get("target")))
            if cfg.get("extract_type") and cfg.get("pattern"):
                cur["extract"] = {str(s.get("extract") or "v"): cfg["pattern"]}
        elif act == "assert":
            if cfg.get("assert_type") == "status" and cfg.get("expected") is not None:
                if cur is None:
                    cur = start_http("GET", "")
                cur["expected_status"] = int(cfg["expected"])
            else:
                if cur is None:
                    cur = start_http("GET", "")
                cur["assertions"].append(_assert_row(cfg, s.get("target")))
        elif act == "extract":
            if cur is None:
                cur = start_http("GET", "")
            cur.setdefault("extract", {})[str(s.get("extract") or "v")] = (
                cfg.get("pattern") or s.get("target") or ""
            )
        elif act == "delay":
            flush()
            out.append({"action": "sleep", "value": int(cfg.get("ms") or s.get("target") or 0)})
        elif act == "db_query":
            flush()
            out.append({"action": "http", "path": cfg.get("sql") or "", "assertions": []})
        else:
            flush()
            out.append({"action": act or "noop", "target": s.get("target", "")})
    flush()
    return out


def _assert_row(cfg: dict, fallback_path: str | None) -> dict:
    """场景断言 → 引擎 {json_path, op, expected}，op 走 _op_ok 白名单。"""
    op_map = {"equals": "eq", "eq": "eq", "contains": "contains", "regex": "regex"}
    op = op_map.get(str(cfg.get("assert_type") or "").lower(), "eq")
    return {"path": cfg.get("path") or fallback_path or "", "op": op,
            "expected": cfg.get("expected")}


class _CaseBulkCreate(BaseModel):
    items: list[CaseCreate]


# ---------------------------------------------------------------------------
# P2-08：Playwright 录制导入 → 数据流场景
# ---------------------------------------------------------------------------
_RECORDING_ACTION_MAP = {
    "goto": "goto", "navigate": "goto",
    "click": "click",
    "fill": "fill",
    "expect": "expect", "assert": "expect",
}


def _recording_actions_to_steps(actions: list) -> tuple[list[dict], list[str]]:
    """P2-08：Playwright 录制动作 → 场景步骤（request/assert）。

    支持 goto/navigate、click、fill、expect/assert 四类；其余类型计入 warnings 并忽略。
    """
    steps: list[dict] = []
    warnings: list[str] = []
    for i, a in enumerate(actions or [], 1):
        if not isinstance(a, dict):
            warnings.append(f"第 {i} 条动作格式非法，已忽略")
            continue
        raw = str(a.get("type") or a.get("action") or "").strip().lower()
        kind = _RECORDING_ACTION_MAP.get(raw)
        if kind is None:
            warnings.append(f"第 {i} 条动作类型 {raw or '未知'} 不支持，已忽略")
            continue
        selector = str(a.get("selector") or a.get("target") or "")
        url = str(a.get("url") or "")
        value = a.get("value", a.get("text"))
        if kind == "goto":
            if not url:
                warnings.append(f"第 {i} 条 goto 缺少 url，已忽略")
                continue
            steps.append({"action": "request", "target": url, "config": {"method": "GET"}, "ui_action": "goto"})
        elif kind == "click":
            steps.append({"action": "request", "target": selector or "/", "config": {"method": "POST"}, "ui_action": "click"})
        elif kind == "fill":
            steps.append({
                "action": "request", "target": selector or "/",
                "config": {"method": "POST", "body": json.dumps({"selector": selector, "value": value}, ensure_ascii=False)},
                "ui_action": "fill",
            })
        else:  # expect
            steps.append({
                "action": "assert", "target": selector or url or "",
                "config": {"assert_type": "contains", "expected": "" if value is None else value},
                "ui_action": "expect",
            })
    return steps, warnings


# v2.0 P2：评测集批量导入合法类别（与种子集/引擎 category 契约一致）
_IMPORT_EVAL_SET_CATEGORIES = {
    "HALLUCINATION", "ETHICS", "REDTEAM", "RAG", "SECURITY", "MULTI_TURN",
}


def _injection_vector_items(payload: dict) -> list[dict]:
    """从报告 step_details 提取 PROMPT_INJECTION 用例级注入向量明细（无则空列表）。"""
    items: list[dict] = []
    for sr in payload.get("step_details") or []:
        if sr.get("engine") != "PROMPT_INJECTION":
            continue
        for r in (sr.get("details") or {}).get("items") or []:
            if r.get("injection_vector"):
                items.append(r)
    return items


def _render_markdown(r: Report, payload: dict) -> str:
    """报告 → Markdown 文本（含合规对齐声明）。"""
    lines = [
        f"# {payload.get('title', r.title)}",
        "",
        f"- 报告编号：{payload.get('report_no', r.report_no)}",
        f"- 任务编号：{payload.get('task_no', r.task_no)}",
        f"- 项目编号：{payload.get('project_code', '-')}",
        f"- 生成时间：{payload.get('generated_at', '')}",
        "",
        "## 汇总指标",
        "| 指标 | 数值 |",
        "| --- | --- |",
    ]
    sm = payload.get("summary") or r.summary or {}
    _metric_cn = {"total": "用例总数", "passed": "通过数", "failed": "失败数", "pass_rate": "通过率"}
    for k in ("total", "passed", "failed", "pass_rate"):
        lines.append(f"| {_metric_cn[k]} | {sm.get(k, '-')} |")
    lines.append("")

    # 分步结果
    steps = (sm or {}).get("step_results") or []
    if steps:
        lines.append("## 分步结果")
        for s in steps:
            lines.append(
                f"- **{_cn_engine(s.get('engine'))}**：{STEP_STATUS_EXPORT_CN.get(str(s.get('status') or '').upper(), s.get('status', '-'))} {s.get('conclusion', '')}"
            )
            if s.get("summary"):
                lines.append(
                    f"  - 摘要：{json.dumps(_summary_cn(s['summary']), ensure_ascii=False)}"
                )
        lines.append("")

    # ---- 注入向量审计（直接/间接注入分组，仅 PROMPT_INJECTION 报告输出）----
    vec_items = _injection_vector_items(payload)
    if vec_items:
        direct = [i for i in vec_items if i.get("injection_vector") == "DIRECT"]
        indirect = [i for i in vec_items if i.get("injection_vector") == "INDIRECT"]
        lines.append("## 注入向量审计（直接/间接注入）")
        lines.append(
            f"- 直接注入风险：**{sum(1 for i in direct if i.get('verdict') == 'RISK')}** / "
            f"共 {len(direct)} 条；间接注入风险："
            f"**{sum(1 for i in indirect if i.get('verdict') == 'RISK')}** / 共 {len(indirect)} 条"
        )
        lines.append("")
        lines.append("| 用例 | 注入向量 | 威胁类型 | 判定 | 严重度 | 说明 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for i in vec_items:
            lines.append(
                f"| {i.get('item_no', '-')} | {VECTOR_CN.get(i.get('injection_vector'), i.get('injection_vector', '-'))} | "
                f"{THREAT_TYPE_EXPORT_CN.get(i.get('threat_type'), i.get('threat_type', '-'))} | "
                f"{_cn_verdict(i.get('verdict'))} | "
                f"{_cn_severity(i.get('severity'))} | {(i.get('title') or '-')[:40]} |"
            )
        lines.append("")

    # ---- 合规对齐声明（新增）----
    alignments = payload.get("compliance_alignment") or []
    lines.append("## 三、合规对齐声明")
    lines.append("")
    lines.append("### 3.1 检测范围与依据")
    lines.append(f"- 框架版本：**框架 3.0**")
    lines.append(f"- 条款清单：共覆盖 **{len(alignments)}** 项条款")
    lines.append("- 口径说明：本章「风险发现等级」为测试发现项的风险定位，不构成法规违规定性；"
                 "是否存在监管法规不符合项，以第四章合规结论为准。")
    lines.append("")

    if alignments:
        lines.append("### 3.2 逐项对齐结果")
        lines.append("| 条款编号 | 风险大类 | 条款标题 | 风险发现等级 | 证据 | 整改建议 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for item in alignments:
            refs = _refs_cn(item.get("evidence_refs"))
            rec = (item.get("recommendation", "") or "-")[:40]
            lines.append(
                f"| {item.get('clause_number', '-')} | {item.get('risk_category', '-')} | "
                f"{item.get('clause_title', '-')} | **{_cn_detection_result(item.get('detection_result'))}** | "
                f"{refs} | {rec} |"
            )
        lines.append("")

        # 整改建议（按优先级）
        critical_high = [
            a for a in alignments if a.get("detection_result") in ("CRITICAL", "HIGH")
        ]
        if critical_high:
            lines.append("### 3.3 整改建议（按优先级排序）")
            for idx, item in enumerate(critical_high, 1):
                lines.append(
                    f"{idx}. **[{item.get('clause_number')}] {item.get('clause_title')}** "
                    f"（{_cn_detection_result(item.get('detection_result'))}）：{item.get('recommendation', '待补充')}"
                )
            lines.append("")

    # 审计轨迹声明
    lines.append("### 3.4 审计轨迹声明")
    lines.append("- 日志完整性：本报告关联的审计日志与执行日志均保存在平台审计系统中。")
    lines.append("- 报告哈希：报告内容经结构化签名，可作为合规自证材料。")
    lines.append("")

    # ---- P1：合规结论章节（违规项 → 法规映射 + 整改建议 + 落款）----
    cc = payload.get("compliance_conclusion") or {}
    if cc:
        lines.extend(compliance_conclusion(cc))
    # W4：越狱/PII 独立专节（MD 与 HTML 同源——_md_to_html 全量转换下方行）
    lines.extend(security_sections(payload.get("step_details") or []))
    # ES8 M9：国际框架覆盖 / 防护建议两节（数据由 build_report 注入 payload，未启用不渲染）
    lines.extend(redteam_sections(payload, payload.get("step_details") or []))

    return "\n".join(lines)


def _md_to_html(md: str) -> str:
    """报告 Markdown → HTML 片段（轻量转换：标题/表格/列表/加粗，全部先转义）。"""
    import re as _re
    from html import escape as _esc

    def inline(text: str) -> str:
        t = _esc(text)
        t = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        return t

    out: list[str] = []
    lines = md.split("\n")
    i = 0
    in_ul = False

    def close_ul():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            close_ul()
            # 收集整张表格
            tbl: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tbl.append(lines[i].strip())
                i += 1
            cells = [
                [inline(c.strip()) for c in row.strip("|").split("|")] for row in tbl
            ]
            # 第二行为分隔行（--- | ---）时首行视为表头
            has_head = len(cells) >= 2 and all(
                _re.fullmatch(r":?-{2,}:?", c.replace(" ", "") or "---") for c in cells[1]
            )
            out.append("<table>")
            if has_head:
                out.append("<tr>" + "".join(f"<th>{c}</th>" for c in cells[0]) + "</tr>")
                body = cells[2:]
            else:
                body = cells
            for row in body:
                out.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
            out.append("</table>")
            continue
        m = _re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            close_ul()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
        elif _re.match(r"^[-*]\s+", stripped):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            item_text = _re.sub(r"^[-*]\s+", "", stripped)
            out.append(f"<li>{inline(item_text)}</li>")
        elif stripped == "":
            close_ul()
        else:
            close_ul()
            out.append(f"<p>{inline(stripped)}</p>")
        i += 1
    close_ul()
    return "\n".join(out)


def _render_html(r: Report, payload: dict) -> str:
    """报告 HTML 导出：自包含单文件（内联样式），与 Markdown 渲染同构，可直接打开/打印。"""
    body = _md_to_html(_render_markdown(r, payload))
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{r.report_no}</title>
<style>
 body{{font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:#1f2937;margin:0;background:#f5f7fa}}
 .page{{max-width:960px;margin:0 auto;padding:32px 40px;background:#fff}}
 h1{{font-size:24px;border-bottom:3px solid #13c2c2;padding-bottom:10px}}
 h2{{font-size:17px;margin-top:28px;border-left:4px solid #13c2c2;padding-left:8px}}
 h3{{font-size:15px;margin-top:18px}}
 table{{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}}
 th,td{{border:1px solid #d9dee5;padding:6px 8px;text-align:left;word-break:break-all}}
 th{{background:#eef2f6}}
 ul{{padding-left:22px}} p{{margin:6px 0;font-size:13px}}
 footer{{margin-top:32px;text-align:center;color:#94a3b8;font-size:12px}}
 @media print{{.page{{padding:0}} body{{background:#fff}}}}
</style></head><body><div class="page">
{body}
<footer>Generated by EvalShield · {r.report_no}</footer>
</div></body></html>"""


# ---- TC-U15：报告导出共享口径（Word / PDF / 安全报告渲染统一使用）----

#: P0/P1 严重度集合（与 services.risk._SEV_CRITICAL、report_ext._FATAL 同口径）
_SEV_P0 = {"P0", "CRITICAL", "FATAL", "严重", "致命"}
_SEV_P1 = {"P1", "HIGH", "MAJOR", "高危"}


def _fmt_gen_date(value) -> str:
    """TC-U15-12/21：封面生成日期 → YYYY-MM-DD。ISO 字符串/datetime 均兼容，解析失败原样返回。"""
    if value is None:
        return ""
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return str(value)
    return value.strftime("%Y-%m-%d")


def _p0_p1_counts(payload: dict) -> tuple[int, int]:
    """TC-U15-18：P0/P1 问题数（数据源 = 合规结论违规项 + 合规对齐检测结果）。"""
    sevs: list[str] = []
    cc = payload.get("compliance_conclusion") or {}
    for v in cc.get("violations") or []:
        sevs.append(str(v.get("severity") or "").upper())
    for a in payload.get("compliance_alignment") or []:
        sevs.append(str(a.get("detection_result") or "").upper())
    p0 = sum(1 for s in sevs if s in _SEV_P0)
    p1 = sum(1 for s in sevs if s in _SEV_P1)
    return p0, p1


def _p0_issues(payload: dict) -> list[dict]:
    """TC-U15-11/19：附录仅列 P0 级问题（合规结论违规项中 severity ∈ P0 集合）。"""
    cc = payload.get("compliance_conclusion") or {}
    return [
        v for v in (cc.get("violations") or [])
        if str(v.get("severity") or "").upper() in _SEV_P0
    ]


def _appendix_rows(payload: dict) -> list[list[str]]:
    """附录表格数据行（不含表头）：无 P0 问题时返回占位行。"""
    issues = _p0_issues(payload)
    if not issues:
        return [["-", "-", "-", "无 P0 级问题"]]
    rows = []
    for v in issues[:50]:
        rows.append(
            [
                str(v.get("item_no") or "-"),
                _cn_engine(v.get("source_engine")),
                _cn_severity(v.get("severity")),
                str(v.get("description") or "-")[:60],
            ]
        )
    return rows


def _cost_metric_rows(cost_data: dict) -> list[list[str]]:
    """成本分析「指标名称 | 数值」汇总行（不含表头）。"""
    return [
        ["总成本（元）", f"{cost_data.get('total_cost', 0):.4f}"],
        ["调用次数", str(cost_data.get("call_count", 0))],
        ["平均延迟（ms）", str(cost_data.get("avg_latency_ms", 0))],
        ["缓存命中率（%）", str(cost_data.get("cache_hit_rate", 0))],
    ]


def _cost_model_rows(cost_data: dict) -> list[list[str]]:
    """成本分析分模型明细行（不含表头）。"""
    rows = []
    for it in (cost_data.get("items") or [])[:50]:
        rows.append(
            [
                str(it.get("label") or "-"),
                str(it.get("model_code") or "-"),
                str(it.get("total_tokens", 0)),
                f"{it.get('total_cost', 0):.4f}",
                str(it.get("call_count", 0)),
                str(it.get("avg_latency_ms", 0)),
                str(it.get("cache_hit_rate", 0)),
            ]
        )
    return rows


def _assert_verdict(a: dict) -> str:
    """断言评测结果：显式 passed 布尔优先；缺失时按 op 简单反推（TC-U15-08）。"""
    p = a.get("passed")
    if isinstance(p, bool):
        return "PASS" if p else "FAIL"
    op = str(a.get("op") or "eq")
    exp, act = a.get("expected"), a.get("actual")
    if op in ("not_empty", "notEmpty", "exists"):
        return "PASS" if act not in (None, "", [], {}, "-") else "FAIL"
    return "PASS" if str(exp) == str(act) else "FAIL"


def _report_cost_data(db: Session, r: Report) -> dict | None:
    """报告关联任务的成本聚合（services.cost 同口径，model 粒度）。

    任务未关联 / 查询异常 → None（渲染层省略「成本分析」章节）。
    """
    if r.task_id is None:
        return None
    try:
        from ..commercial.services.cost import aggregate_cost_summary

        return aggregate_cost_summary(db, r.tenant_id, "model", task_id=r.task_id)
    except Exception:  # noqa: BLE001（sqlite 测试库无基表等场景优雅降级）
        logger.warning("报告成本数据聚合失败（成本章节省略）", exc_info=True)
        return None


# W4：列宽表扩到 8 列并循环兜底——原 [20,18,15,22,45,45] 6 项切片在 7/8 列专节表上会直接 ValueError（隐患修复）
_PDF_COLW_MM = [20, 18, 15, 22, 45, 45, 30, 30] + [25] * 10

#: A4 正文可用宽度（mm）：210 - 左右边距各 18
_PDF_AVAIL_MM = 174


def _pdf_cell_text(v):
    """单元格文本 → Paragraph 可解析内容。

    reportlab Paragraph 走 mini-XML 解析：脱敏片段里的 & < > 与尖括号占位符
    （如 `<未获取>`）会被当作标签导致整页渲染抛错或丢字，必须先转义。
    """
    from xml.sax.saxutils import escape as _xesc

    s = "" if v is None else str(v)
    # 控制字符（PDF 文本无法显示，且会让 Paragraph 解析异常）
    s = "".join(ch if (ch == "\n" or ord(ch) >= 32) else " " for ch in s)
    return _xesc(s).replace("\n", "<br/>")


def _make_pdf_table(rows, col_widths_mm, avail_mm, cell_style, head_style):
    """PDF 表格统一构建：单元格用 Paragraph 包裹（长中文自动换行），
    列宽按比例缩放到正文可用宽度（防止 7/8 列专节表溢出页宽）。"""
    from reportlab.lib import colors
    from reportlab.lib.units import mm as _mm
    from reportlab.platypus import Paragraph, Table, TableStyle

    n = max((len(r) for r in rows), default=0)
    widths = list(col_widths_mm[:n])
    widths += [25] * max(0, n - len(widths))
    total = sum(widths) or 1
    scale = avail_mm / total
    data = []
    for ri, r in enumerate(rows):
        pad = [""] * (n - len(r))
        style = head_style if ri == 0 else cell_style
        data.append([Paragraph(_pdf_cell_text(c), style) for c in list(r) + pad])
    t = Table(data, colWidths=[w * scale * _mm for w in widths])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9AA7B4")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#F2F6FA")],
                ),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t


def _md_rows_to_pdf(story, md_lines, h2, h3, body, mm, FONT):
    """W4：合规结论/专节 MD 行 → PDF story 元素（自 _render_pdf 抽出复用，逻辑逐字保留）。"""
    import re as _re

    from html import escape as _esc
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    def _pdf_text(line: str) -> str:
        return _esc(line.replace("**", ""))

    i = 0
    while i < len(md_lines):
        ln = md_lines[i].strip()
        if ln.startswith("|"):
            rows: list[list[str]] = []
            while i < len(md_lines) and md_lines[i].strip().startswith("|"):
                rows.append([_pdf_text(c.strip()) for c in md_lines[i].strip().strip("|").split("|")])
                i += 1
            data_rows = [
                r for r in rows
                if not all(_re.fullmatch(r":?-{2,}:?", c.replace(" ", "") or "---") for c in r)
            ]
            if data_rows:
                from reportlab.lib.styles import ParagraphStyle as _PS

                cell_s = _PS("zhCell", parent=body, fontSize=8, leading=11)
                head_s = _PS("zhCellH", parent=cell_s, textColor=colors.white)
                t = _make_pdf_table(data_rows, _PDF_COLW_MM, _PDF_AVAIL_MM, cell_s, head_s)
                story += [t, Spacer(1, 6)]
            continue
        if ln.startswith("## "):
            story.append(Paragraph(_pdf_text(ln[3:]), h2))
        elif ln.startswith("### "):
            story.append(Paragraph(_pdf_text(ln[4:]), h3))
        elif ln.startswith("- "):
            story.append(Paragraph(_pdf_text(ln[2:]), body))
        elif ln:
            story.append(Paragraph(_pdf_text(ln), body))
        i += 1


def _render_pdf(r: Report, payload: dict, *, cost_data: dict | None = None) -> bytes:
    """报告 → PDF（reportlab + 黑体 TrueType，支持中文）。

    cost_data：services.cost.aggregate_cost_summary 产出（model 粒度）；
    None 时省略「六、成本分析」章节（保持既有测试与无成本数据场景兼容）。
    """
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    # 自动探测中文字体路径（容器优先 wqy-zenhei，宿主机回退 simhei）
    font_candidates = [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    FONT = "STSong-Light"
    for fp in font_candidates:
        try:
            if fp.lower().endswith(".ttc"):
                pdfmetrics.registerFont(TTFont("WQY", fp, subfontIndex=0))
                FONT = "WQY"
            else:
                pdfmetrics.registerFont(TTFont("SimHei", fp))
                FONT = "SimHei"
            break
        except Exception:
            continue
    else:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

    buf = BytesIO()
    # 左右边距与 topMargin 对齐（默认 1 英寸会致正文可用宽仅 ~159mm，表格溢出页宽）
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
    )
    base = getSampleStyleSheet()
    title_s = ParagraphStyle(
        "zhTitle", parent=base["Title"], fontName=FONT, fontSize=18, alignment=TA_CENTER
    )
    h2 = ParagraphStyle("zhH2", parent=base["Heading2"], fontName=FONT, fontSize=13)
    h3 = ParagraphStyle("zhH3", parent=base["Heading3"], fontName=FONT, fontSize=11)
    body = ParagraphStyle(
        "zhBody", parent=base["BodyText"], fontName=FONT, fontSize=9.5, leading=14
    )
    small = ParagraphStyle("zhSmall", parent=body, fontSize=8.5, leading=12)
    cell_s = ParagraphStyle("zhCell", parent=body, fontSize=8, leading=11)
    head_s = ParagraphStyle("zhCellH", parent=cell_s, textColor=colors.white)

    story = [
        Paragraph(payload.get("title", r.title), title_s),
        Spacer(1, 6),
        Paragraph(
            f"报告编号：{payload.get('report_no', r.report_no)}　"
            f"任务编号:{payload.get('task_no', r.task_no)}<br/>"
            f"项目编号:{payload.get('project_code', '-')}　"
            f"生成日期：{_fmt_gen_date(payload.get('generated_at') or r.created_at)}",
            small,
        ),
        Spacer(1, 10),
        Paragraph("一、汇总指标", h2),
    ]
    sm = payload.get("summary") or r.summary or {}
    # TC-U15-13/18：表头「指标名称」+ P0/P1 问题数行（与 Word 执行摘要同口径）
    _p0, _p1 = _p0_p1_counts(payload)
    metric_rows = [["指标名称", "数值"]]
    for k in ("total", "passed", "failed", "pass_rate"):
        metric_rows.append([SUMMARY_KEYS_CN.get(k, k), str(sm.get(k, "-"))])
    metric_rows.append(["P0级问题数", str(_p0)])
    metric_rows.append(["P1级问题数", str(_p1)])
    t = _make_pdf_table(metric_rows, [70, 100], _PDF_AVAIL_MM, cell_s, head_s)
    story += [t, Spacer(1, 10), Paragraph("二、分步结果", h2)]
    steps = (sm or {}).get("step_results") or []
    if not steps:
        story.append(Paragraph("（无分步结果）", small))
    for s in steps:
        summary_txt = json.dumps(_summary_cn(s.get("summary") or {}), ensure_ascii=False)
        story.append(
            Paragraph(
                f"<b>[{_cn_engine(s.get('engine'))}]</b> {STEP_STATUS_EXPORT_CN.get(str(s.get('status') or '').upper(), s.get('status', ''))} — {s.get('conclusion', '')}",
                body,
            )
        )
        story.append(Paragraph(f"摘要：{summary_txt[:300]}", small))
        story.append(Spacer(1, 4))
    story.append(Spacer(1, 8))

    # ---- 注入向量审计（直接/间接注入分组，仅 PROMPT_INJECTION 报告输出）----
    vec_items = _injection_vector_items(payload)
    if vec_items:
        _direct = [i for i in vec_items if i.get("injection_vector") == "DIRECT"]
        _indirect = [i for i in vec_items if i.get("injection_vector") == "INDIRECT"]
        story.append(Paragraph("注入向量审计（直接/间接注入）", h2))
        story.append(
            Paragraph(
                f"直接注入风险：<b>{sum(1 for i in _direct if i.get('verdict') == 'RISK')}</b>"
                f"（共 {len(_direct)} 条）；间接注入风险："
                f"<b>{sum(1 for i in _indirect if i.get('verdict') == 'RISK')}</b>"
                f"（共 {len(_indirect)} 条）",
                body,
            )
        )
        story.append(Spacer(1, 4))
        vec_rows = [["用例", "注入向量", "威胁类型", "判定", "严重度", "说明"]]
        for i in vec_items:
            vec_rows.append(
                [
                    i.get("item_no", "-"),
                    VECTOR_CN.get(i.get("injection_vector"), i.get("injection_vector", "-")),
                    (THREAT_TYPE_EXPORT_CN.get(i.get("threat_type"), i.get("threat_type") or "-"))[:18],
                    _cn_verdict(i.get("verdict")),
                    _cn_severity(i.get("severity")),
                    (i.get("title") or "-")[:24],
                ]
            )
        vec_table = _make_pdf_table(
            vec_rows, [22, 20, 34, 16, 20, 48], _PDF_AVAIL_MM, cell_s, head_s
        )
        story += [vec_table, Spacer(1, 8)]

    # ---- 三、合规对齐声明（新增）----
    alignments = payload.get("compliance_alignment") or []
    story.append(Paragraph("三、合规对齐声明", h2))
    story.append(Spacer(1, 4))
    story.append(Paragraph("3.1 检测范围与依据", h3))
    story.append(
        Paragraph(
            f"框架版本：<b>框架 3.0</b>；覆盖条款数：<b>{len(alignments)}</b>。"
            "口径说明：本章「风险发现等级」为测试发现项的风险定位，不构成法规违规定性；"
            "是否存在监管法规不符合项，以第四章合规结论为准。",
            body,
        )
    )
    story.append(Spacer(1, 6))

    if alignments:
        story.append(Paragraph("3.2 逐项对齐结果", h3))
        comp_rows = [["条款编号", "风险大类", "条款标题", "风险发现等级", "证据"]]
        for item in alignments:
            refs = _refs_cn(item.get("evidence_refs"))
            comp_rows.append(
                [
                    item.get("clause_number", "-"),
                    item.get("risk_category", "-"),
                    item.get("clause_title", "-")[:20],
                    _cn_detection_result(item.get("detection_result")),
                    refs,
                ]
            )
        comp_table = _make_pdf_table(
            comp_rows, [25, 25, 50, 20, 50], _PDF_AVAIL_MM, cell_s, head_s
        )
        story += [comp_table, Spacer(1, 8)]

        # 整改建议
        critical_high = [
            a for a in alignments if a.get("detection_result") in ("CRITICAL", "HIGH")
        ]
        if critical_high:
            story.append(Paragraph("3.3 整改建议（按优先级排序）", h3))
            for idx, item in enumerate(critical_high, 1):
                story.append(
                    Paragraph(
                        f"{idx}. <b>[{item.get('clause_number')}] {item.get('clause_title')}</b> "
                        f"（{_cn_detection_result(item.get('detection_result'))}）：{item.get('recommendation', '待补充')}",
                        body,
                    )
                )
            story.append(Spacer(1, 6))

    # 审计轨迹声明
    story.append(Paragraph("3.4 审计轨迹声明", h3))
    story.append(
        Paragraph(
            "本报告关联的审计日志与执行日志均保存在平台审计系统中。报告内容经结构化签名，可作为合规自证材料。",
            body,
        )
    )
    story.append(Spacer(1, 10))

    # ---- P1：合规结论章节（TC-U6-02：与 MD/HTML 同源，复用 report_sections.compliance_conclusion）----
    cc = payload.get("compliance_conclusion") or {}
    _sec_lines = security_sections(payload.get("step_details") or [])
    # ES8 M9：国际框架覆盖 / 防护建议两节（与 MD/HTML 同源，未启用不渲染）
    _rt_lines = redteam_sections(payload, payload.get("step_details") or [])
    if cc:
        _md_rows_to_pdf(story, compliance_conclusion(cc), h2, h3, body, mm, FONT)
        story.append(Spacer(1, 8))
    if _sec_lines:
        _md_rows_to_pdf(story, _sec_lines, h2, h3, body, mm, FONT)
        story.append(Spacer(1, 8))
    if _rt_lines:
        _md_rows_to_pdf(story, _rt_lines, h2, h3, body, mm, FONT)
        story.append(Spacer(1, 8))

    # ---- TC-U15-19：附录（仅列 P0 级问题）；W4：编号随专节动态顺延 ----
    _apx_no = next_section_no(payload.get("step_details") or [], payload)
    story.append(Paragraph(f"{cn_no(_apx_no)}、附录（P0 级问题）", h2))
    story.append(Spacer(1, 4))
    apx_rows = [["用例编号", "来源引擎", "严重度", "说明"]] + _appendix_rows(payload)
    apx_table = _make_pdf_table(apx_rows, [25, 25, 18, 92], _PDF_AVAIL_MM, cell_s, head_s)
    story += [apx_table, Spacer(1, 8)]

    # ---- TC-U15-20：成本分析（services.cost 聚合口径；无数据则省略；W4：编号动态顺延）----
    if cost_data:
        story.append(Paragraph(f"{cn_no(_apx_no + 1)}、成本分析", h2))
        story.append(Spacer(1, 4))
        cm_rows = [["指标名称", "数值"]] + _cost_metric_rows(cost_data)
        cm_table = _make_pdf_table(cm_rows, [70, 100], _PDF_AVAIL_MM, cell_s, head_s)
        story += [cm_table, Spacer(1, 6)]
        model_rows = (
            [["模型", "模型编码", "总Token", "成本(元)", "调用次数", "平均延迟(ms)", "缓存命中率(%)"]]
            + _cost_model_rows(cost_data)
        )
        md_table = _make_pdf_table(
            model_rows, [28, 18, 20, 20, 18, 24, 22], _PDF_AVAIL_MM, cell_s, head_s
        )
        story += [md_table, Spacer(1, 8)]

    story.append(Paragraph("— EvalShield AI 系统测试服务平台 —", small))

    # v2.0 P3：演示模式（INTERNAL_DEMO）PDF 水印（Helvetica 无中文字形，用 ASCII 文本）
    def _demo_watermark(canv, doc_):
        canv.saveState()
        canv.setFont("Helvetica-Bold", 60)
        canv.setFillColor(colors.Color(1, 0.65, 0, alpha=0.22))
        canv.translate(A4[0] / 2, A4[1] / 2)
        canv.rotate(45)
        canv.drawCentredString(0, 0, "DEMO")
        canv.restoreState()

    _steps = payload.get("step_details") or (payload.get("summary") or {}).get("step_results") or []
    _demo = payload.get("demo_mode") or any(
        (s or {}).get("target_mode") == "INTERNAL_DEMO" for s in _steps
    )
    if _demo:
        doc.build(story, onFirstPage=_demo_watermark, onLaterPages=_demo_watermark)
    else:
        doc.build(story)
    return buf.getvalue()


def _bump_eval_set_version(es: "EvalSet") -> None:
    """A8/T3：items 变化 → version v{n} → v{n+1}，并写 meta.version_history。"""
    import hashlib
    import json as _json

    old_v = es.version or "v1"
    try:
        n = int(old_v.lstrip("vV") or 1)
    except ValueError:
        n = 1
    es.version = f"v{n + 1}"
    meta = dict(es.meta or {})
    hist = list(meta.get("version_history") or [])
    digest = hashlib.sha256(
        _json.dumps(es.items or [], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    hist.append({"version": es.version, "item_count": es.item_count, "sha256": digest[:16]})
    meta["version_history"] = hist[-20:]
    es.meta = meta


# ---------------------------------------------------------------------------
# 项目成员（GET / POST / PUT / DELETE）
# ---------------------------------------------------------------------------
def _is_project_admin(db: Session, auth: AuthContext, project_id: int) -> bool:
    """项目成员鉴权：SUPER_ADMIN 或 project_members.role=OWNER 放行。"""
    if auth.is_super_admin:
        return True
    row = (
        db.query(ProjectMembers)
        .filter(
            ProjectMembers.project_id == project_id,
            ProjectMembers.user_id == auth.user_id,
            ProjectMembers.role == "OWNER",
            ProjectMembers.deleted_at.is_(None),
        )
        .first()
    )
    return row is not None


# ---------------------------------------------------------------------------
# G-1：计费套餐 + 充值
# ---------------------------------------------------------------------------
def _is_admin_ctx(auth: AuthContext) -> bool:
    """是否管理员（SUPER_ADMIN 或 roles 含 ADMIN/SUPER_ADMIN）。"""
    if auth.is_super_admin:
        return True
    return any(r in ("ADMIN", "SUPER_ADMIN") for r in (auth.roles or []))


__all__ = [
    '_plain_json',
    '_cov_row',
    '_dataset_module_from_name',
    '_SCENARIO_NESTED_ACTIONS',
    '_SCENARIO_MAX_DEPTH',
    '_SCENARIO_LOOP_MAX_ITER',
    '_SCENARIO_PARALLEL_MAX_BRANCHES',
    '_COND_OPS',
    '_COND_OP_ALIAS',
    '_scenario_err',
    '_parse_condition_str',
    '_normalize_condition',
    '_int_or_err',
    '_compile_nested',
    '_scenario_steps_to_engine',
    '_assert_row',
    '_CaseBulkCreate',
    '_RECORDING_ACTION_MAP',
    '_recording_actions_to_steps',
    '_IMPORT_EVAL_SET_CATEGORIES',
    '_injection_vector_items',
    '_fmt_gen_date',
    '_p0_p1_counts',
    '_p0_issues',
    '_appendix_rows',
    '_cost_metric_rows',
    '_cost_model_rows',
    '_assert_verdict',
    '_report_cost_data',
    '_render_markdown',
    '_md_to_html',
    '_render_html',
    '_render_pdf',
    '_make_pdf_table',
    '_PDF_AVAIL_MM',
    '_bump_eval_set_version',
    '_is_project_admin',
    '_is_admin_ctx',
]
