# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""m_003 租户回刷：存量无 ``t<tenant>_`` 前缀的静态附件/证据文件改名 + DB 引用重写。

背景（F-01 已知限制收口，见工单 docs/security/tenant-backfill-work-order.md）：
secure_static 的 Bearer 通道按文件名 ``t<tenant>_`` 前缀做租户校验；修复上线前的
存量上传文件名无前缀，只能"仅登录放行"。本脚本将存量文件统一改名为
``t<tenant>_<origname>``，并同步重写 DB 中的引用字符串，消除该限制。

归属判定优先级（文件名本身不含租户线索，只能靠引用方推导）：
1. defects.attachments / defects.evidence 引用 → 该缺陷行 tenant_id
2. reports.content 内截图路径引用 → 该报告行 tenant_id
3. 无任何行引用的孤儿附件 → 默认租户（tenants 表最小 id，通常为 1）并告警

安全性与幂等：
- 磁盘改名与 DB 重写**必须成对执行**，故 DB 侧不做独立 SQL 迁移
  （inti.sql 仅登记台账表 es_tenant_backfill_map，见工单说明）；
- 已带 ``t\\d+_`` 前缀的文件整体跳过；改名目标已存在则告警跳过（防覆盖）；
- 台账 (kind, orig_name) 唯一 + ON CONFLICT DO NOTHING，二次执行零变化；
- 支持 --dry-run 预览；JSONB 重写采用等值字符串替换（旧串==引用原文才替换），
  不会误改正文中同名普通文本以外的路径片段。

执行：
    python backend/migrations/m_003_static_tenant_backfill.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402

# 与 secure_static._TENANT_PREFIX_RE 保持同一口径
_TENANT_PREFIX_RE = re.compile(r"^t(\d+)_")
# /api/attachments/<name> 或 /api/evidence/<name>（无查询串、无前缀判定在调用处做）
_REF_URL_RE = re.compile(r"^/api/(attachments|evidence)/([^/?#]+)$")
_URL_KIND_DIR = {"attachments": "att", "evidence": "evi"}


def _tenant_prefixed(name: str) -> bool:
    return _TENANT_PREFIX_RE.match(name) is not None


def _basename(s: str) -> str:
    return re.split(r"[\\/]", s)[-1]


def _ref_target(leaf: str, dirs: dict[str, Path]) -> tuple[str, str] | None:
    """引用字符串 → (kind, 磁盘文件名)。仅当文件确实存在于对应目录才返回。

    支持两种落库形态：
    - URL 形态：``/api/attachments/<name>``、``/api/evidence/<name>``
    - 绝对路径形态（reports.content 截图）：任意目录分隔路径，按文件名落在
      att/evi 两个目录中探测归属。
    """
    if not isinstance(leaf, str) or not leaf:
        return None
    m = _REF_URL_RE.match(leaf)
    if m:
        kind = _URL_KIND_DIR[m.group(1)]
        name = m.group(2)
        return (kind, name) if (dirs[kind] / name).is_file() else None
    if "\\" in leaf or "/" in leaf:
        name = _basename(leaf)
        for kind in ("att", "evi"):
            if (dirs[kind] / name).is_file():
                return (kind, name)
    return None


def _rewrite_leaf(leaf: str, kind: str, new_name: str) -> str:
    """等值重写单条引用：保持原形态（URL/路径），仅替换文件名部分。"""
    head = leaf[: len(leaf) - len(_basename(leaf))]
    return head + new_name


def _walk_strings(value):
    """深度遍历 JSONB 值中的所有字符串叶子（含 dict 的 value）。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)


def _refresh_json(value, renames: dict[str, str]):
    if isinstance(value, str):
        return renames.get(value, value)
    if isinstance(value, list):
        return [_refresh_json(v, renames) for v in value]
    if isinstance(value, dict):
        return {k: _refresh_json(v, renames) for k, v in value.items()}
    return value


def _default_tenant_id(db: Session) -> int:
    row = db.execute(text("SELECT min(id) FROM tenants")).fetchone()
    return int(row[0]) if row and row[0] is not None else 1


def _ledger_insert(db: Session, rows: list[tuple], dry_run: bool) -> None:
    """台账登记（幂等 ON CONFLICT DO NOTHING）。dry-run 不落库。"""
    if dry_run or not rows:
        return
    db.execute(
        text(
            """
            INSERT INTO es_tenant_backfill_map
                (kind, orig_name, new_name, tenant_id, source, ref_id)
            VALUES (:kind, :orig, :new, :tenant, :source, :ref_id)
            ON CONFLICT (kind, orig_name) DO NOTHING
            """
        ),
        [
            {"kind": k, "orig": o, "new": n, "tenant": t, "source": s, "ref_id": rid}
            for (k, o, n, t, s, rid) in rows
        ],
    )


def run(db: Session, *, dry_run: bool = False,
        attach_dir: str | None = None, evidence_dir: str | None = None) -> dict:
    """执行回刷。返回汇总统计（自测脚本据此断言）。"""
    dirs = {
        "att": Path(attach_dir or settings.ATTACH_DIR),
        "evi": Path(evidence_dir or settings.EVIDENCE_DIR),
    }
    default_tenant = _default_tenant_id(db)
    summary = {"renamed": 0, "rewritten_rows": 0, "orphans": 0, "skipped": [], "dry_run": dry_run}
    done_names: set[tuple[str, str]] = set()  # (kind, orig) 本轮已处理，防重复改名

    # 台账表自愈建表（与 database/inti.sql section 75 同一 DDL）
    if not dry_run:
        db.execute(text(
            """
            CREATE TABLE IF NOT EXISTS es_tenant_backfill_map (
                id          BIGSERIAL PRIMARY KEY,
                kind        VARCHAR(8)   NOT NULL,
                orig_name   VARCHAR(256) NOT NULL,
                new_name    VARCHAR(264) NOT NULL,
                tenant_id   BIGINT       NOT NULL,
                source      VARCHAR(16)  NOT NULL,
                ref_id      BIGINT,
                migrated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
                CONSTRAINT uq_es_tenant_backfill UNIQUE (kind, orig_name)
            )
            """
        ))

    def _rename_one(kind: str, name: str, tenant_id: int, source: str, ref_id: int | None) -> str | None:
        """改名单个文件；返回新文件名，目标冲突/源缺失返回 None（告警跳过）。"""
        key = (kind, name)
        if key in done_names:
            return None
        new_name = f"t{tenant_id}_{name}"
        src, dst = dirs[kind] / name, dirs[kind] / new_name
        if dst.exists():
            summary["skipped"].append(f"{kind}:{name} -> {new_name} 目标已存在，跳过")
            return None
        if not dry_run:
            src.rename(dst)
        done_names.add(key)
        summary["renamed"] += 1
        _ledger_insert(db, [(kind, name, new_name, tenant_id, source, ref_id)], dry_run)
        print(f"  [{'DRY' if dry_run else 'OK'}] {kind}/{name} -> {kind}/{new_name} (tenant={tenant_id}, via {source})")
        return new_name

    # ---- 1. defects.attachments / evidence 引用驱动 ----
    defects = db.execute(text(
        "SELECT id, tenant_id, attachments::text, evidence::text FROM defects WHERE deleted_at IS NULL"
    )).fetchall()
    for d_id, d_tenant, attachments_raw, evidence_raw in defects:
        renames: dict[str, str] = {}
        for raw in (attachments_raw, evidence_raw):
            if not raw:
                continue
            try:
                items = json.loads(raw)
            except (TypeError, ValueError):
                continue
            for leaf in _walk_strings(items):
                target = _ref_target(leaf, dirs)
                if target is None:
                    continue
                kind, name = target
                if _tenant_prefixed(name):
                    continue
                new_name = _rename_one(kind, name, int(d_tenant), "defect", int(d_id))
                if new_name:
                    renames[leaf] = _rewrite_leaf(leaf, kind, new_name)
        if not renames:
            continue
        for col in ("attachments", "evidence"):
            cur = db.execute(
                text(f"SELECT {col}::text FROM defects WHERE id = :id"), {"id": d_id}
            ).fetchone()
            if not cur or not cur[0]:
                continue
            refreshed = _refresh_json(json.loads(cur[0]), renames)
            if not dry_run:
                db.execute(
                    text(f"UPDATE defects SET {col} = CAST(:v AS jsonb) WHERE id = :id"),
                    {"v": json.dumps(refreshed, ensure_ascii=False), "id": d_id},
                )
        summary["rewritten_rows"] += 1

    # ---- 2. reports.content 截图路径引用驱动 ----
    reports = db.execute(
        text("SELECT id, tenant_id, content::text FROM reports WHERE deleted_at IS NULL AND content IS NOT NULL")
    ).fetchall()
    for r_id, r_tenant, content_raw in reports:
        if not content_raw:
            continue
        try:
            content = json.loads(content_raw)
        except (TypeError, ValueError):
            continue
        renames = {}
        for leaf in _walk_strings(content):
            target = _ref_target(leaf, dirs)
            if target is None:
                continue
            kind, name = target
            if _tenant_prefixed(name):
                continue
            new_name = _rename_one(kind, name, int(r_tenant), "report", int(r_id))
            if new_name:
                renames[leaf] = _rewrite_leaf(leaf, kind, new_name)
        if not renames:
            continue
        refreshed = _refresh_json(content, renames)
        if not dry_run:
            db.execute(
                text("UPDATE reports SET content = CAST(:v AS jsonb) WHERE id = :id"),
                {"v": json.dumps(refreshed, ensure_ascii=False), "id": r_id},
            )
        summary["rewritten_rows"] += 1

    # ---- 3. 无引用孤儿（附件目录）→ 默认租户兜底 ----
    if dirs["att"].is_dir():
        for f in sorted(dirs["att"].iterdir()):
            if not f.is_file() or _tenant_prefixed(f.name):
                continue
            if ("att", f.name) in done_names:
                continue
            summary["orphans"] += 1
            print(f"  ⚠️ 孤儿附件无 DB 引用，归属默认租户 {default_tenant}: {f.name}")
            _rename_one("att", f.name, default_tenant, "orphan_default", None)

    if not dry_run:
        db.commit()
    else:
        db.rollback()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="m_003 租户回刷（静态附件/证据前缀化）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不改盘不写库")
    args = parser.parse_args()

    from app.database import SessionLocal

    db = SessionLocal()
    print("=" * 60)
    print(f"MIGRATION: m_003_static_tenant_backfill (dry_run={args.dry_run})")
    print("=" * 60)
    try:
        result = run(db, dry_run=args.dry_run)
        print("-" * 60)
        print(
            f"renamed={result['renamed']} rewritten_rows={result['rewritten_rows']} "
            f"orphans={result['orphans']} skipped={len(result['skipped'])}"
        )
        for line in result["skipped"]:
            print(f"  ⚠️ {line}")
        print("✅ 回刷完成" if not args.dry_run else "✅ dry-run 完成（未落盘）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
