# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""优化12 §7.4 后续环节：A.5 四子类「真实语料替换」一键工具（交付团队执行）。

背景：开发种子题（bank=QBNK-GBT45654-A5DEV，source=ai_generated、
meta.stage=dev-seed）仅为题量轨/缺口链路联调占位。正式出包前必须替换为
真实语料（vendor_licensed / manual）。本工具把「导入校验 → 幂等落库 →
dev-seed 下线 → coverage 复核」收敛为一条命令，可逆、留痕。

红线（不改动任何业务规则）：
- 本工具**不生成任何题目内容**——真实语料必须来自交付团队提供的文件；
- source 白名单仅 vendor_licensed / manual；ai_generated 一律拒收（dev-seed 专用）；
- category 必须逐字命中 tc260.yaml A.5 四行 bank_category；
- 不触碰 eval_run_items / eval_runs（铁律 7）；仅写 question / question_bank。

用法（backend 目录）：
    # 1) 导入真实题（默认 dry-run 只报计划；--apply 落库）
    python scripts/replace_gbt45654_a5_real.py --in corpus.csv --batch-id R-202611 [--apply]
    # 2) 替换语义：导入 + dev-seed 软下线 + 覆盖复核（推荐一步执行）
    python scripts/replace_gbt45654_a5_real.py --in corpus.json --batch-id R-1 --replace-dev --apply
    # 3) 仅复核当前库覆盖（不写）
    python scripts/replace_gbt45654_a5_real.py --check
    # 4) 回滚：撤销某批次导入 / 恢复 dev-seed
    python scripts/replace_gbt45654_a5_real.py --undo-import R-1 --apply
    python scripts/replace_gbt45654_a5_real.py --restore-dev --apply

输入格式（UTF-8；CSV 表头必需；JSON 为对象数组）：
    必填列：category, text, source
    可选列：split, expected_behavior, language, tags(逗号分隔), note
    - source ∈ {vendor_licensed, manual}
    - split/expected_behavior 缺省 REFUSE/REFUSE（A.5 = 应拒答集口径）
    - 同批次内 (category, 去空白 text) 查重；与库中现存可见题撞键即整批拒收
状态即数据库（无本地状态文件）：
    - 导入题：meta.stage='real-import'，meta.import_batch=<batch-id>
    - dev-seed 下线：deleted_at 软删（meta.stage='dev-seed' 可精确恢复）
退出码：0=成功（--check/--replace-dev 复核口径达标）；1=校验/复核不通过；2=环境错误。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import create_engine, text as sa_text

from app.config import settings

BANK_CODE = "QBNK-GBT45654-A5DEV"
TENANT_ID = 1
EXPECTED_PER_CAT = 50  # D-6 附录 B 读法：子类 ≥50 题

# 与 tc260.yaml A.5 四行 bank_category、seed_gbt45654_a5_dev.py 逐字一致
VALID_CATS = {
    "特定服务-场景A@医疗",
    "特定服务-场景B@金融",
    "特定服务-场景C@教育",
    "特定服务-场景D@智能客服",
}
ALLOWED_SOURCES = {"vendor_licensed", "manual"}


def _fail(msg: str, code: int = 1) -> int:
    print(f"[失败] {msg}")
    return code


def load_rows(path: Path) -> tuple[list[dict], list[str]]:
    """读取输入文件 → (行列表, 错误列表)。行 dict 已规范字段。"""
    errs: list[str] = []
    raw: list[dict] = []
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            return [], ["JSON 顶层必须是对象数组"]
        raw = data
    elif path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            cols = set(reader.fieldnames or [])
            missing = {"category", "text", "source"} - cols
            if missing:
                return [], [f"CSV 缺必填列：{sorted(missing)}"]
            raw = list(reader)
    else:
        return [], [f"不支持的文件类型：{path.suffix}（仅 .csv/.json）"]

    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for i, r in enumerate(raw, start=2 if path.suffix.lower() == ".csv" else 1):
        cat = (r.get("category") or "").strip()
        txt = (r.get("text") or "").strip()
        src = (r.get("source") or "").strip()
        if cat not in VALID_CATS:
            errs.append(f"L{i}: category 不在 A.5 四子类内：{cat!r}")
            continue
        if not txt:
            errs.append(f"L{i}: text 为空")
            continue
        if src not in ALLOWED_SOURCES:
            errs.append(f"L{i}: source={src!r} 不在白名单 {sorted(ALLOWED_SOURCES)}"
                        "（ai_generated 为 dev-seed 专用，导入通道拒收）")
            continue
        key = (cat, txt)
        if key in seen:
            errs.append(f"L{i}: 批次内重复（category+text）")
            continue
        seen.add(key)
        tags_raw = (r.get("tags") or "").strip()
        rows.append({
            "category": cat, "text": txt, "source": src,
            "split": (r.get("split") or "REFUSE").strip() or "REFUSE",
            "expected_behavior": (r.get("expected_behavior") or "REFUSE").strip() or "REFUSE",
            "language": (r.get("language") or "zh-CN").strip() or "zh-CN",
            "tags": [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else [],
            "note": (r.get("note") or "").strip(),
        })
    return rows, errs


def _bank_id(conn) -> int | None:
    row = conn.execute(sa_text(
        "SELECT id FROM question_bank WHERE code = :c AND deleted_at IS NULL"
    ), {"c": BANK_CODE}).fetchone()
    return row[0] if row else None


def _coverage(conn, bank_id: int) -> dict[str, dict[str, int]]:
    rows = conn.execute(sa_text(
        "SELECT category, source, count(*) FROM question"
        " WHERE bank_id = :b AND deleted_at IS NULL GROUP BY category, source"
    ), {"b": bank_id}).fetchall()
    cov = {c: {"visible": 0, "real": 0, "dev": 0} for c in sorted(VALID_CATS)}
    for cat, src, n in rows:
        if cat not in cov:
            continue
        cov[cat]["visible"] += n
        if src == "ai_generated":
            cov[cat]["dev"] += n
        else:
            cov[cat]["real"] += n
    return cov


def _print_coverage(cov: dict, gaps_ok_flag: list) -> None:
    print("覆盖复核（可见题=真实+dev-seed）：")
    for cat, v in cov.items():
        flag = "OK " if v["visible"] >= EXPECTED_PER_CAT else "缺口"
        if v["visible"] < EXPECTED_PER_CAT:
            gaps_ok_flag.append(False)
        print(f"  [{flag}] {cat}: visible={v['visible']}"
              f"（real={v['real']}, dev-seed={v['dev']}，阈值 {EXPECTED_PER_CAT}）")


def _recount(conn, bank_id: int) -> int:
    n = conn.execute(sa_text(
        "SELECT count(*) FROM question WHERE bank_id = :b AND deleted_at IS NULL"
    ), {"b": bank_id}).scalar()
    conn.execute(sa_text(
        "UPDATE question_bank SET question_count = :n, updated_at = NOW() WHERE id = :b"
    ), {"n": n, "b": bank_id})
    return int(n)


def do_import(args) -> int:
    path = Path(args.infile)
    if not path.exists():
        return _fail(f"输入文件不存在：{path}", 2)
    try:
        rows, errs = load_rows(path)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _fail(f"输入文件解析失败：{exc}", 2)
    if errs:
        for e in errs:
            print(f"  {e}")
        return _fail(f"输入校验不通过（{len(errs)} 处），整批未写入")
    if not rows:
        return _fail("输入文件无有效题目行")
    if not args.batch_id:
        return _fail("--apply 导入必须提供 --batch-id（留痕与回滚键）", 2)

    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    print(f"[计划] 批次 {args.batch_id}：导入 {len(rows)} 题 → "
          + "，".join(f"{c}={n}" for c, n in sorted(by_cat.items())))

    eng = create_engine(settings.DATABASE_URL, connect_args={"connect_timeout": 5})
    rc = 0
    with eng.begin() as conn:
        bank_id = _bank_id(conn)
        if bank_id is None:
            return _fail(f"题库不存在：{BANK_CODE}（先跑 seed_gbt45654_a5_dev.py --apply）", 2)
        # 与现存可见题撞键检查（uq_question_dedup 口径：bank 内 category+md5(btrim(text))）
        exist = {(c, t.strip()) for c, t in conn.execute(sa_text(
            "SELECT category, text FROM question WHERE bank_id = :b AND deleted_at IS NULL"
        ), {"b": bank_id}).fetchall()}
        dup = [r for r in rows if (r["category"], r["text"]) in exist]
        if dup:
            for d in dup[:5]:
                print(f"  撞键：{d['category']} / {d['text'][:30]}…")
            return _fail(f"与库中现存题重复 {len(dup)} 条，整批未写入")
        max_seq = int(conn.execute(sa_text(
            "SELECT COALESCE(MAX(seq), 0) FROM question WHERE bank_id = :b"
        ), {"b": bank_id}).scalar())
        if not args.apply:
            print("[dry-run] 未落库；--apply 执行写入")
        else:
            seq = max_seq
            for r in rows:
                seq += 1
                meta = {"stage": "real-import", "import_batch": args.batch_id}
                if r["note"]:
                    meta["note"] = r["note"]
                conn.execute(sa_text(
                    "INSERT INTO question (tenant_id, bank_id, seq, category,"
                    " sub_category, attack_vector, split, expected_behavior,"
                    " expected_answer, language, source, sensitivity, tags, meta, text,"
                    " created_at, updated_at)"
                    " VALUES (:t, :b, :s, :cat, NULL, 'direct', :split, :eb,"
                    " NULL, :lang, :src, 'internal', CAST(:tags AS jsonb),"
                    " CAST(:meta AS jsonb), :txt, NOW(), NOW())"
                ), {
                    "t": TENANT_ID, "b": bank_id, "s": seq, "cat": r["category"],
                    "split": r["split"], "eb": r["expected_behavior"],
                    "lang": r["language"], "src": r["source"],
                    "tags": json.dumps(r["tags"], ensure_ascii=False),
                    "meta": json.dumps(meta, ensure_ascii=False), "txt": r["text"],
                })
            n = _recount(conn, bank_id)
            print(f"[OK] 批次 {args.batch_id} 已导入 {len(rows)} 题，题库现存量 {n}")

        if args.replace_dev:
            dev = conn.execute(sa_text(
                "SELECT count(*) FROM question WHERE bank_id = :b AND deleted_at IS NULL"
                " AND meta->>'stage' = 'dev-seed'"
            ), {"b": bank_id}).scalar()
            if args.apply and dev:
                conn.execute(sa_text(
                    "UPDATE question SET deleted_at = NOW(), updated_at = NOW()"
                    " WHERE bank_id = :b AND deleted_at IS NULL"
                    " AND meta->>'stage' = 'dev-seed'"
                ), {"b": bank_id})
                _recount(conn, bank_id)
            print(f"[计划] dev-seed 下线 {dev} 题"
                  + ("（--apply 生效）" if args.apply else "（dry-run 未执行）"))

        cov = _coverage(conn, bank_id)
        bad: list = []
        _print_coverage(cov, bad)
        if args.apply and bad:
            rc = _fail("替换后覆盖不达标（缺口见上）")
    eng.dispose()
    return rc


def do_check(_args) -> int:
    eng = create_engine(settings.DATABASE_URL, connect_args={"connect_timeout": 5})
    rc = 0
    with eng.begin() as conn:
        bank_id = _bank_id(conn)
        if bank_id is None:
            return _fail(f"题库不存在：{BANK_CODE}", 2)
        bad: list = []
        _print_coverage(_coverage(conn, bank_id), bad)
        if bad:
            rc = _fail("覆盖不达标")
        else:
            print("[OK] 四子类覆盖达标")
    eng.dispose()
    return rc


def do_undo_or_restore(args) -> int:
    eng = create_engine(settings.DATABASE_URL, connect_args={"connect_timeout": 5})
    with eng.begin() as conn:
        bank_id = _bank_id(conn)
        if bank_id is None:
            return _fail(f"题库不存在：{BANK_CODE}", 2)
        if args.undo_import:
            cond = ("meta->>'stage' = 'real-import'"
                    " AND meta->>'import_batch' = :bid")
            n = conn.execute(sa_text(
                f"SELECT count(*) FROM question WHERE bank_id = :b"
                f" AND deleted_at IS NULL AND {cond}"
            ), {"b": bank_id, "bid": args.undo_import}).scalar()
            print(f"[计划] 撤销批次 {args.undo_import}：软删可见导入题 {n} 条")
            if args.apply and n:
                conn.execute(sa_text(
                    f"UPDATE question SET deleted_at = NOW(), updated_at = NOW()"
                    f" WHERE bank_id = :b AND deleted_at IS NULL AND {cond}"
                ), {"b": bank_id, "bid": args.undo_import})
                _recount(conn, bank_id)
                print(f"[OK] 已撤销 {n} 条")
        if args.restore_dev:
            n = conn.execute(sa_text(
                "SELECT count(*) FROM question WHERE bank_id = :b"
                " AND deleted_at IS NOT NULL AND meta->>'stage' = 'dev-seed'"
            ), {"b": bank_id}).scalar()
            print(f"[计划] 恢复 dev-seed：已下线 {n} 题")
            if args.apply and n:
                conn.execute(sa_text(
                    "UPDATE question SET deleted_at = NULL, updated_at = NOW()"
                    " WHERE bank_id = :b AND deleted_at IS NOT NULL"
                    " AND meta->>'stage' = 'dev-seed'"
                ), {"b": bank_id})
                _recount(conn, bank_id)
                print(f"[OK] 已恢复 {n} 题")
        if not args.apply:
            print("[dry-run] 未落库；--apply 执行写入")
        bad: list = []
        _print_coverage(_coverage(conn, bank_id), bad)
    eng.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A.5 真实语料替换一键工具（优化12 §7.4）")
    ap.add_argument("--in", dest="infile", help="真实语料文件（.csv/.json）")
    ap.add_argument("--batch-id", help="导入批次号（留痕+回滚键，--apply 必填）")
    ap.add_argument("--replace-dev", action="store_true",
                    help="导入同场将 dev-seed 题软下线（替换语义）")
    ap.add_argument("--check", action="store_true", help="仅复核覆盖")
    ap.add_argument("--undo-import", metavar="BATCH_ID", help="软删指定批次的导入题")
    ap.add_argument("--restore-dev", action="store_true", help="恢复被下线的 dev-seed 题")
    ap.add_argument("--apply", action="store_true", help="真正落库（默认 dry-run）")
    args = ap.parse_args(argv)

    if args.check:
        return do_check(args)
    if args.undo_import or args.restore_dev:
        return do_undo_or_restore(args)
    if args.infile:
        return do_import(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
