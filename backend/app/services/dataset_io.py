# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES8 M7：数据集批量导入与版本化服务（方案 §8）。

三条数据管道 + 版本快照辅助：
- CSV/JSONL 解析（RFC4180 引号/换行边界由标准库 csv 保证）、列映射、预览前 20 行
- from_run：取评测运行 item_results 中 grade==FAIL 的用例建集
- from_review：接收评审条目数组直接建集（M6 未开发，仅预留函数签名与 API 面）
- diff_stats / snapshot_revision：编辑升版前旧 items 整文快照与行级差异统计
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from typing import Any

from ..errors import BizError
from ..models import EvalRun, EvalSet, EvalSetRevision
from ..utils.no import gen_no

# 预览行数上限（方案 §8.1：预览前 20 行）
PREVIEW_LIMIT = 20
# 单次导入条目上限（防超大文件拖垮建集事务）
IMPORT_MAX_ITEMS = 5000

# 列映射目标字段（源列 → 评测集条目字段）
MAP_TARGETS = ("question", "answer", "tags")
# question/answer/tags 在条目中的落点（与 EvalSet.items 契约 {no,prompt,expected,tags} 对齐）
_TARGET_TO_ITEM_KEY = {"question": "prompt", "answer": "expected", "tags": "tags"}
# 猜列时的同义词表（小写匹配）
_COLUMN_HINTS = {
    "question": ("question", "prompt", "问题", "题目", "query", "input"),
    "answer": ("answer", "expected", "答案", "期望", "期望答案", "reference", "output", "gold"),
    "tags": ("tags", "tag", "标签", "category", "主题"),
}


# ---------------------------------------------------------------------------
# 解析：CSV / JSONL
# ---------------------------------------------------------------------------
def parse_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """解析 CSV 文本（标准库 csv，天然满足 RFC4180 引号/换行/逗号转义）。

    返回 (表头列表, 行字典列表)；自动跳过全空行。
    """
    reader = csv.reader(io.StringIO(text, newline=""))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        raise BizError("ES-M7-0001", "CSV 内容为空或未解析出任何行")
    headers = [(h or "").strip() for h in rows[0]]
    if not any(headers):
        raise BizError("ES-M7-0002", "CSV 缺少表头行（首行须为列名）")
    out: list[dict[str, str]] = []
    for r in rows[1:]:
        # 行长不齐时按表头对齐补空，多余列丢弃
        padded = list(r) + [""] * (len(headers) - len(r))
        out.append({headers[i]: (padded[i] or "") for i in range(len(headers))})
    return headers, out


def parse_jsonl(text: str) -> tuple[list[str], list[dict[str, Any]]]:
    """解析 JSONL 文本（每行一个 JSON 对象，忽略空行）。返回 (并集表头, 行列表)。"""
    out: list[dict[str, Any]] = []
    headers: list[str] = []
    seen: set[str] = set()
    for ln, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue  # JSONL 边界：空行容忍
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BizError("ES-M7-0003", f"JSONL 第{ln}行解析失败：{exc}")
        if not isinstance(obj, dict):
            raise BizError("ES-M7-0004", f"JSONL 第{ln}行须为 JSON 对象")
        for k in obj:
            if k not in seen:
                seen.add(k)
                headers.append(k)
        out.append(obj)
    if not out:
        raise BizError("ES-M7-0001", "JSONL 内容为空或未解析出任何行")
    return headers, out


def parse_file(filename: str, raw: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    """按扩展名分派解析。仅支持 .csv / .jsonl / .json（JSON 数组等价单对象每行）。"""
    name = (filename or "").lower()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BizError("ES-M7-0005", "文件编码须为 UTF-8")
    if name.endswith(".csv"):
        return parse_csv(text)
    if name.endswith(".jsonl"):
        return parse_jsonl(text)
    if name.endswith(".json"):
        # JSON 数组文件按行拆开后复用 JSONL 校验
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BizError("ES-M7-0006", f"JSON 解析失败：{exc}")
        if not isinstance(data, list):
            raise BizError("ES-M7-0007", "JSON 文件须为数组格式")
        return parse_jsonl("\n".join(json.dumps(o, ensure_ascii=False) for o in data))
    raise BizError("ES-M7-0008", "不支持的文件格式，仅支持 CSV/JSONL/JSON")


# ---------------------------------------------------------------------------
# 列映射：源列 → question/answer/tags
# ---------------------------------------------------------------------------
def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    """按列名同义词猜映射：{"question": "源列名"|None, ...}。"""
    lowered = {h: (h or "").strip().lower() for h in headers}
    result: dict[str, str | None] = {t: None for t in MAP_TARGETS}
    for target in MAP_TARGETS:
        for h in headers:
            if lowered[h] in _COLUMN_HINTS[target]:
                result[target] = h
                break
    return result


def apply_mapping(headers: list[str], rows: list[dict], mapping: dict) -> list[dict]:
    """按映射把源行转为评测集条目 [{no, prompt, expected, tags, ...透传}]。

    mapping: {"question": 源列名, "answer": 源列名|null, "tags": 源列名|null}
    tags 列支持 , / | 分隔的字符串或多值数组；未映射列原样透传（避免信息丢失）。
    """
    q_col = (mapping or {}).get("question")
    if not q_col:
        raise BizError("ES-M7-0009", "列映射缺少必填项 question（问题列）")
    if q_col not in headers:
        raise BizError("ES-M7-0010", f"映射的问题列 {q_col!r} 不在表头中")
    a_col = (mapping or {}).get("answer")
    t_col = (mapping or {}).get("tags")
    used = {c for c in (q_col, a_col, t_col) if c}
    items: list[dict] = []
    for idx, row in enumerate(rows, 1):
        prompt = str(row.get(q_col) or "").strip()
        if not prompt:
            raise BizError("ES-M7-0011", f"第{idx}行问题列为空，无法导入")
        item: dict = {"no": f"IMP-{idx:04d}", "prompt": prompt}
        if a_col:
            av = row.get(a_col)
            item["expected"] = "" if av is None else str(av).strip()
        if t_col:
            tv = row.get(t_col)
            if isinstance(tv, list):
                item["tags"] = [str(s).strip() for s in tv if str(s).strip()]
            elif tv is None or str(tv).strip() == "":
                item["tags"] = []
            else:
                sep = "|" if "|" in str(tv) else ","
                item["tags"] = [s.strip() for s in str(tv).split(sep) if s.strip()]
        # 未映射列透传（键名冲突时以映射结果为准）
        for k, v in row.items():
            if k not in used and k not in item:
                item[k] = v
        items.append(item)
    if not items:
        raise BizError("ES-M7-0012", "映射后条目为空")
    if len(items) > IMPORT_MAX_ITEMS:
        raise BizError("ES-M7-0013", f"条目数超限：{len(items)} > {IMPORT_MAX_ITEMS}")
    return items


def preview_result(filename: str, raw: bytes, limit: int = PREVIEW_LIMIT, mapping: dict | None = None) -> dict:
    """解析 + 猜映射 + 预览前 limit 行（无状态：confirm 时携带 items 二次提交）。

    mapping 显式传入时以其为准（向导中用户手改列映射后重算），否则按列名猜测。
    """
    headers, rows = parse_file(filename, raw)
    mapping = mapping or suggest_mapping(headers)
    # 目标值容错：向导回传可能为 {"question": 列名|null}
    mapping = {t: (mapping or {}).get(t) for t in MAP_TARGETS}
    mapped: list[dict] | None = None
    error: str | None = None
    if mapping.get("question"):
        try:
            mapped = apply_mapping(headers, rows, mapping)
        except BizError as exc:
            error, mapped = exc.message, None
    return {
        "format": (filename or "").lower().rsplit(".", 1)[-1],
        "headers": headers,
        "row_count": len(rows),
        "truncated": len(rows) > limit,
        "preview_rows": rows[:limit],
        "suggested_mapping": mapping,
        "preview_items": (mapped or [])[:limit],
        # 映射成功时的全量条目（confirm 建集直接回传，不受预览 20 行截断）
        "all_items": mapped,
        "mapping_error": error,
    }


# ---------------------------------------------------------------------------
# 版本化：diff_stats 与旧内容整文快照
# ---------------------------------------------------------------------------
def _norm_line(item: Any) -> str:
    """条目 → 规范化 JSON 行（行级对比的粒度）。"""
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def compute_diff_stats(old_items: list, new_items: list) -> dict:
    """行级多重集对比：{"added":n,"removed":n,"unchanged":n}。

    同一内容出现多次按次数计（多重集），避免重复条目被误判为 unchanged 放大。
    """
    oc = Counter(_norm_line(x) for x in (old_items or []))
    nc = Counter(_norm_line(x) for x in (new_items or []))
    return {
        "added": sum((nc - oc).values()),
        "removed": sum((oc - nc).values()),
        "unchanged": sum((oc & nc).values()),
    }


def parse_set_version(version: str | None) -> int:
    """主表字符串版本 vN → 数字 N（异常兜底 1）。"""
    try:
        return int((version or "v1").lstrip("vV") or 1)
    except ValueError:
        return 1


def snapshot_revision(
    db, es: EvalSet, old_items: list, new_items: list, user_id: int | None
) -> EvalSetRevision:
    """升版前把旧 items 整文快照入 eval_set_revisions（与 _bump 前的旧版本号对齐）。

    调用方约定：本函数只 db.add，不 commit（与升版同事务，见 evals_core 更新路由）。
    """
    rev = EvalSetRevision(
        eval_set_id=es.id,
        version=parse_set_version(es.version),  # 旧内容所属版本 N（升版前）
        content=json.dumps(old_items or [], ensure_ascii=False),
        diff_stats=json.dumps(compute_diff_stats(old_items or [], new_items or [])),
        created_by=user_id,
    )
    db.add(rev)
    return rev


# ---------------------------------------------------------------------------
# from_run：取失败用例建集（grade == FAIL，SKIP/PASS 均剔除）
# ---------------------------------------------------------------------------
def fail_items_from_run(run: EvalRun) -> list[dict]:
    """item_results 过滤 grade==FAIL → 评测集条目（prompt/rubric 沿用留痕）。"""
    items: list[dict] = []
    for idx, r in enumerate(run.item_results or [], 1):
        if not isinstance(r, dict) or r.get("grade") != "FAIL":
            continue
        item = {
            "no": str(r.get("item_no") or f"FAIL-{idx:04d}"),
            "prompt": str(r.get("prompt") or ""),
        }
        if r.get("expected") is not None:
            item["expected"] = r.get("expected")
        if r.get("rubric") is not None:
            item["rubric"] = r.get("rubric")
        item["tags"] = ["from_run", run.run_no or ""]
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# from_review：评审条目数组 → 评测集条目（M6 未开发，仅预留归一化）
# ---------------------------------------------------------------------------
def items_from_review(entries: list) -> list[dict]:
    """评审回流：条目已是 {no,prompt,expected,...} 结构则透传，缺 no 自动补号。"""
    items: list[dict] = []
    for idx, e in enumerate(entries or [], 1):
        if not isinstance(e, dict) or not str(e.get("prompt") or "").strip():
            raise BizError("ES-M7-0014", f"回流条目{idx}缺少 prompt 字段")
        it = dict(e)
        it.setdefault("no", f"REV-{idx:04d}")
        items.append(it)
    if not items:
        raise BizError("ES-M7-0015", "回流条目为空")
    if len(items) > IMPORT_MAX_ITEMS:
        raise BizError("ES-M7-0013", f"条目数超限：{len(items)} > {IMPORT_MAX_ITEMS}")
    return items


def build_imported_set(
    db,
    *,
    name: str,
    category: str,
    items: list[dict],
    source: str,
    user_id: int | None,
    tenant_id: int,
    parent_set_id: int | None = None,
    meta_extra: dict | None = None,
) -> EvalSet:
    """统一建集入口（import/from_run/from_review 共用，source 区分血缘）。"""
    es = EvalSet(
        code=gen_no("EVS"),
        name=(name or "").strip()[:128] or "未命名评测集",
        category=category,
        items=items,
        item_count=len(items),
        version="v1",
        source=source,
        parent_set_id=parent_set_id,
        meta={"import_meta": meta_extra} if meta_extra else {},
        visibility="PRIVATE",
        created_by=user_id,
        tenant_id=tenant_id,
    )
    db.add(es)
    db.commit()
    db.refresh(es)
    return es
