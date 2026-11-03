# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES9-P-09：题目批量导入器（csv / jsonl 流式解析）。

设计方案 §4.1.2-B：
- 列 schema：category,sub_category,attack_vector,split,text,expected_behavior,
  expected_answer,language,source,tags；
- 行级校验失败进 errors（[{row, code, message}]，最多 200 条）不中断；
- 批内去重后 INSERT … ON CONFLICT DO NOTHING（命中 uq_question_dedup
  部分唯一索引 (bank_id, category, md5(btrim(text)))）+ 回读计数；
- 结束重算 question_bank.question_count；
- CSV 反向 csv_guard：单元格以 ``'`` 前缀的导入时剥离转义符还原原文。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from ..models import QuestionBank, QuestionImportJob

logger = logging.getLogger("evalshield.question_import")

MAX_ERROR_SAMPLES = 200
_CHUNK = 500

_SPLITS = {"REFUSE", "ANSWER", "ATTACK"}
_BEHAVIORS = {"REFUSE", "ANSWER", "SAFE_REFUSE"}
_SOURCES = {"manual", "csv_import", "jsonl_import", "ai_generated", "vendor_licensed"}
_LANGS = {"zh-CN", "zh-TW", "en", "ja", "ko", "other"}
_SPLIT_DEFAULT_BEHAVIOR = {"REFUSE": "REFUSE", "ANSWER": "ANSWER", "ATTACK": "SAFE_REFUSE"}


def unescape_cell(value: Any) -> Any:
    """csv_guard 反向：剥离导出时注入的 ``'`` 前缀还原原文。"""
    if isinstance(value, str) and value[:1] == "'":
        return value[1:]
    return value


def _norm_row(raw: dict[str, Any], row_no: int, fmt: str) -> dict[str, Any]:
    """行级校验，返回规范化 dict；失败抛 ValueError(code, message)。"""
    text_val = (raw.get("text") or "").strip()
    if not text_val:
        raise ValueError(("ES-QB-ROW-001", "text 为空"))
    category = (raw.get("category") or "").strip()
    if not category:
        raise ValueError(("ES-QB-ROW-002", "category 为空"))

    split = (raw.get("split") or "").strip().upper() or "ANSWER"
    if split not in _SPLITS:
        raise ValueError(("ES-QB-ROW-003", f"split 非法：{split}"))

    behavior = (raw.get("expected_behavior") or "").strip().upper() or _SPLIT_DEFAULT_BEHAVIOR[split]
    if behavior not in _BEHAVIORS:
        raise ValueError(("ES-QB-ROW-004", f"expected_behavior 非法：{behavior}"))

    source = (raw.get("source") or "").strip() or (f"{fmt}_import" if fmt in ("csv", "jsonl") else "manual")
    if source not in _SOURCES:
        source = f"{fmt}_import"

    language = (raw.get("language") or "zh-CN").strip() or "zh-CN"

    tags_raw = raw.get("tags")
    tags: list[str] = []
    if isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    elif isinstance(tags_raw, str) and tags_raw.strip():
        body = tags_raw.strip()
        if body.startswith("["):
            try:
                parsed = json.loads(body)
                if isinstance(parsed, list):
                    tags = [str(t).strip() for t in parsed if str(t).strip()]
            except (ValueError, TypeError):
                tags = [t.strip() for t in body.strip("[]").split(",") if t.strip()]
        else:
            tags = [t.strip() for t in body.split(",") if t.strip()]

    return {
        "row_no": row_no,
        "category": category[:64],
        "sub_category": ((raw.get("sub_category") or "").strip() or None),
        "attack_vector": ((raw.get("attack_vector") or "").strip() or None),
        "split": split,
        "expected_behavior": behavior,
        "expected_answer": raw.get("expected_answer") or None,
        "language": language[:16],
        "source": source[:48],
        "tags": tags,
        "text": text_val,
        "dedup_key": (category, hashlib.md5(text_val.strip().encode("utf-8")).hexdigest()),
    }


def iter_rows(file_path: str, fmt: str) -> Iterator[tuple[int, dict[str, Any]]]:
    """流式产出行（行号从 2 起算便于用户对照文件；jsonl 从 1 起算按行）。"""
    if fmt == "jsonl":
        with open(file_path, "r", encoding="utf-8-sig") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    yield i, {"__parse_error__": "JSON 解析失败"}
                    continue
                if not isinstance(obj, dict):
                    yield i, {"__parse_error__": "非对象行"}
                    continue
                yield i, {k: unescape_cell(v) if isinstance(v, str) else v for k, v in obj.items()}
        return
    # csv：DictReader 流式
    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 2):
            yield i, { (k or "").strip(): unescape_cell(v) for k, v in row.items() }


def _flush_chunk(db: Session, bank: QuestionBank, rows: list[dict[str, Any]], base_seq: int) -> int:
    """批量 INSERT … ON CONFLICT DO NOTHING，返回实际插入数。"""
    if not rows:
        return 0
    values_parts, params = [], {}
    for j, r in enumerate(rows):
        pk = f"p{j}"
        values_parts.append(
            f"(:tenant_id, :bank_id, :seq{j}, :cat{pk}, :sub{pk}, :av{pk}, :split{pk}, "
            f":eb{pk}, :ea{pk}, :lang{pk}, :src{pk}, :tags{pk}::jsonb, '{{}}'::jsonb, :text{pk})"
        )
        params.update({
            "tenant_id": bank.tenant_id,
            "bank_id": bank.id,
            f"seq{j}": base_seq + r["row_no"],
            f"cat{pk}": r["category"],
            f"sub{pk}": r["sub_category"],
            f"av{pk}": r["attack_vector"],
            f"split{pk}": r["split"],
            f"eb{pk}": r["expected_behavior"],
            f"ea{pk}": r["expected_answer"],
            f"lang{pk}": r["language"],
            f"src{pk}": r["source"],
            f"tags{pk}": json.dumps(r["tags"], ensure_ascii=False),
            f"text{pk}": r["text"],
        })
    sql = sa_text(
        "INSERT INTO question (tenant_id, bank_id, seq, category, sub_category, attack_vector, "
        "split, expected_behavior, expected_answer, language, source, tags, meta, text) VALUES "
        + ",".join(values_parts)
        + " ON CONFLICT (bank_id, category, md5(btrim(text))) WHERE deleted_at IS NULL DO NOTHING"
    )
    result = db.execute(sql, params)
    return result.rowcount or 0


def run_import_job(db: Session, job_id: int) -> None:
    """后台任务入口：执行导入并落 job 进度/结果（独立提交，容错）。"""
    job = db.get(QuestionImportJob, job_id)
    if job is None or job.status in ("succeeded", "failed"):
        return
    job.status = "running"
    db.add(job)
    db.commit()

    bank = db.get(QuestionBank, job.bank_id)
    errors: list[dict[str, Any]] = []
    total = inserted = duplicated = rejected = 0
    try:
        if bank is None or bank.deleted_at is not None:
            raise RuntimeError("题库不存在或已删除")
        fmt = job.format or "csv"
        if not os.path.isfile(job.file_path):
            raise RuntimeError("导入文件不存在")
        # 直接 SQL 取当前最大 seq 作为批内序号基准
        base_seq = int(
            db.execute(
                sa_text("SELECT COALESCE(MAX(seq), 0) FROM question WHERE bank_id = :b"),
                {"b": bank.id},
            ).scalar() or 0
        )
        seen: set[tuple[str, str]] = set()
        chunk: list[dict[str, Any]] = []

        def flush(rows: list[dict[str, Any]]) -> None:
            nonlocal inserted, duplicated, chunk
            n = _flush_chunk(db, bank, rows, base_seq)
            inserted += n
            duplicated += len(rows) - n
            chunk = []
            db.commit()

        for row_no, raw in iter_rows(job.file_path, fmt):
            total += 1
            if raw.get("__parse_error__"):
                rejected += 1
                if len(errors) < MAX_ERROR_SAMPLES:
                    errors.append({"row": row_no, "code": "ES-QB-ROW-000", "message": raw["__parse_error__"]})
                continue
            try:
                norm = _norm_row(raw, row_no, fmt)
            except ValueError as exc:
                rejected += 1
                if len(errors) < MAX_ERROR_SAMPLES:
                    code, msg = exc.args[0]
                    errors.append({"row": row_no, "code": code, "message": msg})
                continue
            if norm["dedup_key"] in seen:
                duplicated += 1
                continue
            seen.add(norm["dedup_key"])
            chunk.append(norm)
            if len(chunk) >= _CHUNK:
                flush(chunk)

        flush(chunk)

        # 回读计数并重算题库冗余计数
        real_count = int(
            db.execute(
                sa_text("SELECT COUNT(*) FROM question WHERE bank_id = :b AND deleted_at IS NULL"),
                {"b": bank.id},
            ).scalar() or 0
        )
        bank.question_count = real_count
        bank.updated_at = datetime.now(timezone.utc)
        db.add(bank)

        job.total_rows = total
        job.inserted = inserted
        job.duplicated = duplicated
        job.rejected = rejected
        job.errors = errors
        job.status = "succeeded"
        job.finished_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()
    except Exception as exc:  # noqa: BLE001 —— 后台任务兜底落 failed
        logger.exception("question import job %s failed", job_id)
        db.rollback()
        job = db.get(QuestionImportJob, job_id)
        if job is not None:
            job.status = "failed"
            job.total_rows = total
            job.inserted = inserted
            job.duplicated = duplicated
            job.rejected = rejected
            if len(errors) < MAX_ERROR_SAMPLES:
                errors.append({"row": 0, "code": "ES-QB-IMPORT-ERR", "message": str(exc)[:300]})
            job.errors = errors
            job.finished_at = datetime.now(timezone.utc)
            db.add(job)
            db.commit()


__all__ = ["run_import_job", "iter_rows", "unescape_cell"]
