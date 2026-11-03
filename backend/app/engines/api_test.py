# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""API 接口测试引擎：基于请求规格真实执行 REST/HTTP 用例（httpx）。

支持方法/路径/头/体、expected_status、响应字段断言、真实耗时与错误码。
工具缺失或请求失败时返回清晰失败，绝不仿真通过。
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from ..config import settings
from .base import BaseEngine, EngineContext, EngineResult, resolve_dataset_groups

# 极简 jsonpath：支持 a.b.c 与 a[0].b 逐层取值
_PATH_INDEX = re.compile(r"^([^.\[]+)(?:\[(\d+)\])?$")


def _json_get(data: Any, path: str) -> Any:
    """按极简 json.path 从字典/列表取值；支持 $ 前缀（如 $.a.b / $.a[0]）；不存在返回 _MISSING。"""
    if not path:
        return data
    path = path.strip()
    if path.startswith("$"):
        path = path[1:].lstrip(".")
    current = data
    if not path:
        return current
    for part in path.split("."):
        key = part
        idx: int | None = None
        m = _PATH_INDEX.match(part)
        if m:
            key = m.group(1)
            if m.group(2) is not None:
                idx = int(m.group(2))
        if isinstance(current, dict):
            if key not in current:
                return _MISSING
            current = current[key]
        elif isinstance(current, list):
            if idx is None:
                return _MISSING
            try:
                current = current[idx]
            except IndexError:
                return _MISSING
        else:
            return _MISSING
        # 若还有 [i] 但上面已处理，直接继续
        if idx is not None and m.group(2) is not None and not isinstance(
            current, (dict, list)
        ):
            return _MISSING
    return current


class _Missing:
    pass


_MISSING = _Missing()

# 14 种白名单 op（C8 / OP-01~14）
_VALID_OPS = {
    "eq", "neq", "contains", "not_contains", "regex",
    "gt", "gte", "lt", "lte",
    "notnull", "isnull", "in", "exists", "not_empty",
}

# OP-15 非法 op→白名单 op 归一表（LLM 常产出）
_OP_ALIASES: dict[str, str] = {
    # eq
    "equals": "eq", "equal": "eq", "equal_to": "eq", "is": "eq", "equal_to_": "eq",
    # neq
    "not_equal": "neq", "notequals": "neq", "ne": "neq", "!=": "neq", "ne_": "neq",
    # contains
    "contains_str": "contains", "includes": "contains", "contain": "contains",
    # not_contains
    "notcontains": "not_contains", "not_contain": "not_contains", "notincludes": "not_contains",
    # regex
    "match": "regex", "matches": "regex", "regex_match": "regex",
    # gt
    "greater": "gt", "greater_than": "gt",
    # gte
    "ge": "gte", "greater_equal": "gte", "gte_": "gte",
    # lt
    "less": "lt", "less_than": "lt",
    # lte
    "le": "lte", "less_equal": "lte", "lte_": "lte",
    # notNull
    "not_null": "notnull", "notnull_": "notnull", "has_value": "notnull",
    # isNull
    "is_null": "isnull", "null": "isnull",
    # in
    "in_list": "in", "within": "in", "in_": "in", "contains_in": "in",
    # exists
    "exist": "exists", "present": "exists", "field_exists": "exists",
    # not_empty
    "non_empty": "not_empty", "notempty": "not_empty", "has_content": "not_empty",
}


def normalize_op(op: str | None) -> str:
    """OP-15：LLM 产出的 op 字符串归一为白名单 op。未知 op 统一归一为 eq。"""
    if not op:
        return "eq"
    lo = str(op).strip().lower()
    if lo in _VALID_OPS:
        return lo
    if lo in _OP_ALIASES:
        return _OP_ALIASES[lo]
    return "eq"


def _op_ok(op: str, actual: Any, expected: Any) -> bool:
    """按 op 判定断言是否成立。OP-15：非法 op 自动归一。"""
    op = normalize_op(op)
    if op == "eq":
        return actual == expected
    if op == "neq":
        return actual != expected
    if op == "contains":
        return str(expected) in str(actual)
    if op == "not_contains":
        return str(expected) not in str(actual)
    if op == "regex":
        try:
            return re.search(str(expected), str(actual)) is not None
        except re.error:
            return False
    if op == "gt":
        try:
            return float(actual) > float(expected)
        except (TypeError, ValueError):
            return False
    if op == "gte":
        try:
            return float(actual) >= float(expected)
        except (TypeError, ValueError):
            return False
    if op == "lt":
        try:
            return float(actual) < float(expected)
        except (TypeError, ValueError):
            return False
    if op == "lte":
        try:
            return float(actual) <= float(expected)
        except (TypeError, ValueError):
            return False
    if op == "notnull":
        return actual is not _MISSING and actual is not None
    if op == "isnull":
        return actual is _MISSING or actual is None
    if op == "in":
        try:
            return str(actual) in [str(x) for x in expected]
        except (TypeError, ValueError):
            return False
    if op == "exists":
        return actual is not _MISSING
    if op == "not_empty":
        return actual not in (None, "", [], {})
    return False


def _inject_vars(obj: Any, variables: dict) -> Any:
    """对字符串/字典/列表做 {{var}} 注入（str.replace，禁止 .format() 避免 JSON {} 冲突）。

    返回 (替换结果, 未定义变量名列表)。未定义变量保持原样并计入警告，
    由调用方追加 E_VAR_UNDEFINED 失败信息。
    """
    variables = dict(variables or {})
    if isinstance(obj, str):
        out = obj
        for k, v in variables.items():
            out = out.replace("{{" + k + "}}", "" if v is None else str(v))
        return out, _find_undefined(out)
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        undefined: list[str] = []
        for k, v in obj.items():
            nv, nu = _inject_vars(v, variables)
            out[k] = nv
            undefined.extend(nu)
        return out, undefined
    if isinstance(obj, list):
        out_list: list[Any] = []
        undefined_list: list[str] = []
        for v in obj:
            nv, nu = _inject_vars(v, variables)
            out_list.append(nv)
            undefined_list.extend(nu)
        return out_list, undefined_list
    return obj, []


# 未定义变量占位符：{{ 变量名 }}
_VAR_PLACEHOLDER = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_\-]*\s*\}\}")


def _find_undefined(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    found: list[str] = []
    for m in _VAR_PLACEHOLDER.finditer(text):
        name = m.group(0).strip("{}").strip()
        if name and name not in found:
            found.append(name)
    return found


class ApiTestEngine(BaseEngine):
    engine_code = "API_TEST"
    engine_name = "API 接口测试引擎"
    engine_type = "TRADITIONAL"
    category = "API"
    version = "1.0.0"
    description = "真实执行 REST/HTTP 接口用例：方法/路径/头/体，断言状态码与响应字段。"
    fidelity = "real"

    def _load_cases(self, ctx: EngineContext) -> list:
        cases = ctx.config.get("cases") or ctx.extra.get("cases") or []
        if not cases and ctx.db is not None:
            from ..models import TestCase

            # 关键：每次执行前 expire session，确保拿到 DB 最新值（含用户刚 PUT 更新的断言）
            ctx.db.expire_all()
            # DISC-05：过滤软删用例（旧臆造路径用例已删仍被执行是任务44根因）；
            # case_ids 兼容 config 与 extra 双来源（task_runner 放在 extra）；
            # 无 case_ids 兜底取数时按 id 倒序，保证新入库用例优先。
            q = ctx.db.query(TestCase).filter(
                TestCase.project_id == ctx.project_id,
                TestCase.category == "API",
                TestCase.deleted_at.is_(None),
            )
            ids = ctx.config.get("case_ids") or ctx.extra.get("case_ids")
            if ids:
                q = q.filter(TestCase.id.in_(ids))
            cases = list(q.order_by(TestCase.id.desc()).limit(500).all())
        return cases

    def _execute_one(
        self,
        client: httpx.Client,
        base_url: str,
        spec: dict[str, Any],
        timeout: float,
        extra_assertions: list | None = None,
        variables: dict | None = None,
    ) -> tuple[list[str], dict[str, Any], list[dict[str, Any]]]:
        """真实执行单用例，返回 (failures, info, assertion_details)。"""
        failures: list[str] = []
        variables = dict(variables or {})
        spec, undefined = _inject_vars(spec, variables)
        for u in undefined:
            failures.append(f"E_VAR_UNDEFINED: 变量 {u!r} 未定义")
        method = (spec.get("method") or "GET").upper()
        path = (spec.get("path") or spec.get("url") or "").strip()
        if not path:
            return ["缺少请求路径"], {}, []
        url = base_url.rstrip("/") + "/" + path.lstrip("/")
        headers = spec.get("headers") or {}
        params = spec.get("params")
        json_body = spec.get("json") or spec.get("body") if isinstance(
            spec.get("json") or spec.get("body"), (dict, list)
        ) else None
        data_body = (
            spec.get("data")
            if isinstance(spec.get("data"), (dict, str))
            else None
        )
        content = spec.get("content") if isinstance(spec.get("content"), str) else None
        expected_code = spec.get("expected_status", 200)
        if not isinstance(expected_code, int) or expected_code <= 0:
            failures.append(f"expected_status 非法: {expected_code!r}")
            expected_code = 200

        start = time.perf_counter()
        try:
            resp = client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                data=data_body,
                content=content,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            return [f"E_API_TIMEOUT: {exc.__class__.__name__}: {exc}"], {}, []
        except httpx.HTTPError as exc:
            return [f"E_API_CONN: {exc.__class__.__name__}: {exc}"], {}, []
        duration_ms = int((time.perf_counter() - start) * 1000)

        info: dict[str, Any] = {
            "status_code": resp.status_code,
            "duration_ms": duration_ms,
        }
        try:
            resp_json = resp.json()
            info["response_preview"] = str(resp_json)[:500]
        except ValueError:
            resp_json = _MISSING
            info["response_preview"] = resp.text[:500]

        assertions = list(spec.get("assertions") or [])
        assertions.extend(extra_assertions or [])
        # DISC-04：用例若已声明显式状态断言（如权限矩阵 status in [401,403]），
        # 以断言为准，跳过 expected_status 单一值硬校验，避免双口径互斥误判 FAIL。
        _STATUS_KEYS = ("_status", "_status_code", "status", "status_code", "http_status")
        _has_status_assertion = any(
            isinstance(a, dict)
            and (a.get("json_path") or a.get("path") or a.get("jsonPath") or "") in _STATUS_KEYS
            for a in assertions
        )
        if resp.status_code != expected_code and not _has_status_assertion:
            failures.append(
                f"E_API_STATUS: 期望 {expected_code}，实际 {resp.status_code}"
            )

        assertion_details: list[dict[str, Any]] = []
        for i, a in enumerate(assertions, 1):
            if not isinstance(a, dict):
                continue
            jp = a.get("json_path") or a.get("path") or a.get("jsonPath") or ""
            op = a.get("op") or "eq"
            expected = a.get("expected")
            _is_status = jp in ("_status", "_status_code", "status", "status_code", "http_status")
            _is_latency = jp in ("_latency", "_duration", "latency", "duration")
            if _is_status:
                actual = resp.status_code
            elif _is_latency:
                actual = duration_ms
            elif not jp:
                # 空 path = 断言整个响应体（兼容非 JSON 文本响应）
                actual = resp.text
            else:
                actual = _json_get(resp_json, jp) if resp_json is not _MISSING else _MISSING
            passed = _op_ok(op, actual, expected)
            assertion_details.append({
                "path": jp, "op": op, "expected": expected,
                "actual": None if actual is _MISSING else actual,
                "passed": passed,
            })
            if not passed:
                actual_txt = "<缺失>" if actual is _MISSING else str(actual)[:120]
                failures.append(
                    f"E_API_ASSERT[{i}]: {jp} {op} {expected!r} 失败，实际={actual_txt}"
                )

        # 响应提取变量（供后置/后续数据分组使用）
        for e in spec.get("extract") or []:
            if isinstance(e, dict) and e.get("var"):
                var_name = e["var"]
                jp = e.get("path") or e.get("json_path") or ""
                val = (
                    resp.status_code
                    if jp in ("_status", "_status_code")
                    else duration_ms
                    if jp in ("_latency", "_duration")
                    else resp.text
                    if not jp
                    else _json_get(resp_json, jp)
                )
                if val is not _MISSING:
                    variables[var_name] = val

        info["variables"] = variables
        return failures, info, assertion_details

    def execute(self, ctx: EngineContext) -> EngineResult:
        cases = self._load_cases(ctx)
        base_url = (
            ctx.config.get("base_url")
            or ctx.extra.get("base_url")
            or settings.API_DEFAULT_BASE_URL
        )
        timeout = float(ctx.config.get("timeout_seconds", 30))
        # ---- 全局 auth：统一鉴权头（Bearer / Basic / Cookie / Custom Header）----
        auth_cfg = ctx.config.get("auth") or {}
        default_headers: dict[str, str] = {}
        default_cookies: dict[str, str] = {}
        if auth_cfg:
            if auth_cfg.get("bearer") or auth_cfg.get("token") or auth_cfg.get("access_token"):
                tok = auth_cfg.get("bearer") or auth_cfg.get("token") or auth_cfg.get("access_token")
                default_headers["Authorization"] = f"Bearer {tok}"
            elif auth_cfg.get("basic_user") and auth_cfg.get("basic_pass"):
                import base64 as _b64
                tok = _b64.b64encode(
                    f"{auth_cfg['basic_user']}:{auth_cfg['basic_pass']}".encode()
                ).decode()
                default_headers["Authorization"] = f"Basic {tok}"
            elif auth_cfg.get("username") and auth_cfg.get("password"):
                import base64 as _b64
                tok = _b64.b64encode(
                    f"{auth_cfg['username']}:{auth_cfg['password']}".encode()
                ).decode()
                default_headers["Authorization"] = f"Basic {tok}"
            if auth_cfg.get("custom_headers") and isinstance(auth_cfg["custom_headers"], dict):
                default_headers.update({str(k): str(v) for k, v in auth_cfg["custom_headers"].items()})
            # Cookie 支持（dict 或字符串 "k1=v1; k2=v2"）
            ck = auth_cfg.get("cookies")
            if ck:
                if isinstance(ck, str):
                    for pair in ck.split(";"):
                        if "=" in pair:
                            n, _, v = pair.partition("=")
                            default_cookies[n.strip()] = v.strip()
                elif isinstance(ck, dict):
                    default_cookies.update({str(k): str(v) for k, v in ck.items()})

        results: list[dict[str, Any]] = []
        cleanup_warnings: list[str] = []
        with httpx.Client(headers=default_headers or None, cookies=default_cookies or None) as client:
            for i, case in enumerate(cases, 1):
                title = (
                    getattr(case, "title", None)
                    or (case.get("title") if isinstance(case, dict) else "")
                    or f"接口用例{i}"
                )
                case_no = (
                    getattr(case, "case_no", None)
                    or (case.get("case_no") if isinstance(case, dict) else None)
                    or f"API-{i:04d}"
                )
                spec = (
                    getattr(case, "request_spec", None)
                    or (case.get("request_spec") if isinstance(case, dict) else None)
                    or {}
                )
                # 用例级断言集（合并到 request_spec 之上）
                case_assertions = getattr(case, "assertions", None)
                if case_assertions is None and isinstance(case, dict):
                    case_assertions = case.get("assertions")
                case_assertions = case_assertions or []
                # 数据驱动：test_data 非空则逐行展开为独立数据分组；
                # 否则若用例归属数据集（有 data_rows），按数据集数据行逐行展开
                test_data = getattr(case, "test_data", None)
                if test_data is None and isinstance(case, dict):
                    test_data = case.get("test_data")
                groups = (
                    test_data
                    or resolve_dataset_groups(case, ctx.db)
                    or [{"case": "默认", "params": {}}]
                )

                method = (spec.get("method") or "GET").upper()
                path = (spec.get("path") or spec.get("url") or "").strip()
                group_vars: dict[str, Any] = {}
                for g in groups:
                    params = dict((g.get("params") or {}) if isinstance(g, dict) else {})
                    failures, info, assertion_details = self._execute_one(
                        client, base_url, spec, timeout,
                        extra_assertions=case_assertions,
                        variables=params,
                    )
                    group_vars.update(info.get("variables") or {})
                    # 无任何断言 → SKIP（避免假通过）
                    has_assertion = bool((
                        spec.get("assertions") or []
                    ) + list(case_assertions))
                    result = "SKIP" if not has_assertion else ("PASS" if not failures else "FAIL")
                    results.append(
                        {
                            "case_no": case_no,
                            "case_id": getattr(case, "id", None),
                            "title": title,
                            "group": g.get("case") if isinstance(g, dict) else "默认",
                            "method": method,
                            "path": path,
                            "expected_status": spec.get("expected_status", 200),
                            "assertion_details": assertion_details,
                            "result": result,
                            "failures": failures,
                            "duration_ms": info.get("duration_ms", 0),
                            "status_code": info.get("status_code"),
                            "response_preview": info.get("response_preview"),
                        }
                    )

                # ---- BE-6 后置清理：用例执行完成后执行 ----
                post_cleanup = getattr(case, "post_cleanup", None)
                if post_cleanup is None and isinstance(case, dict):
                    post_cleanup = case.get("post_cleanup")
                if post_cleanup:
                    from ..services.post_cleanup import run_post_cleanup
                    cleanup_warnings.extend(run_post_cleanup(post_cleanup, group_vars))

        passed = sum(1 for r in results if r["result"] == "PASS")
        skipped = sum(1 for r in results if r["result"] == "SKIP")
        judged = len(results) - skipped  # 已判定的（非 SKIP）
        failed = judged - passed
        error = None
        if failed > 0:
            first_fail = next(r["failures"][0] for r in results if r["failures"])
            error = f"{failed} 条 API 用例失败，如: {first_fail}"
        return EngineResult(
            status="SUCCESS" if (failed == 0 and results) else ("FAILED" if failed else "SKIPPED"),
            summary={
                "total": len(results),
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "pass_rate": round(passed / judged, 4) if judged else 0.0,
                "key": "api_pass_rate",
            },
            report_payload={
                "engine": self.engine_code,
                "results": results,
                "cleanup_warnings": cleanup_warnings,
                "conclusion": "API 用例全部通过" if (failed == 0 and results) else error,
            },
            artifacts=[
                {"name": f"api_result_{ctx.step_no}", "type": "JSON", "payload": results}
            ],
            error=error,
        )