# -*- coding: utf-8 -*-
"""三方一致性只读校验器：ORM 实体类 ↔ 数据库 ↔ database/inti.sql。

优化12 §11.3 / T0 前置动作。定位：
- **只读**：本脚本不写库、不重写 inti.sql、不生成 DDL（inti.sql 是人工维护的幂等
  增量脚本，机器重写会破坏其变更记录留痕）。发现漂移只报告、以退出码表达。
- 三方对账：
  1. models（Base.registry.mappers 声明的表/列）
  2. 数据库（--db-url 或 backend/.env 的 PostgreSQL，information_schema）
  3. inti.sql（CREATE TABLE 语句解析出的表/列）
- 降级模式：无法建立数据库连接时，自动降级为 models vs inti.sql 两方对账，
  并在退出信息中显式声明降级（防止把"没连上库"误读为"三方一致"）。
- 豁免基线：backend/scripts/sync_inti_sql_baseline.json 记录存量已知差异，
  命中基线的差异不判失败（防首跑红灯）；新增差异（不在基线内）即失败。

用法（仓库根或 backend/ 下均可）：
    python backend/scripts/sync_inti_sql.py [--db-url URL] [--refresh-baseline]

退出码：0 = 一致（或差异全在豁免基线内）；1 = 存在基线外新差异；2 = 解析/环境错误。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

MODELS_PATH = BACKEND / "app" / "models.py"
INTI_SQL = REPO / "database" / "inti.sql"
DATA_SQL = REPO / "database" / "data.sql"  # 优化13 拆分：种子数据（2026-11-01 定稿）
BASELINE = Path(__file__).resolve().parent / "sync_inti_sql_baseline.json"

_CT_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:public\.)?\"?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\"?\s*\(",
    re.IGNORECASE,
)


def _split_top_level(body: str) -> list[str]:
    """按顶层逗号切分 CREATE TABLE 主体（括号/引号内不切）。"""
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    cur: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if quote:
            cur.append(ch)
            if ch == quote:
                # 处理 '' 转义
                if i + 1 < len(body) and body[i + 1] == quote:
                    cur.append(body[i + 1])
                    i += 1
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            cur.append(ch)
        elif ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


_CONSTRAINT_WORDS = {
    "constraint", "primary", "unique", "foreign", "check", "exclude", "like",
}


def _col_name(part: str) -> str | None:
    """从一个列定义片段提取列名；约束定义返回 None。"""
    s = part.strip()
    if not s:
        return None
    if s.startswith('"'):
        m = re.match(r'^"([^"]+)"', s)
        name = m.group(1) if m else ""
    else:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)", s)
        name = m.group(1) if m else ""
    if name.lower() in _CONSTRAINT_WORDS:
        return None
    return name or None


def parse_inti_sql(path: Path) -> dict[str, set[str]]:
    """解析 inti.sql → {表名: {列名}}（只取 CREATE TABLE 定义体）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    # 去行注释（简化：-- 到行尾；不处理字符串内 -- 的极端场景——inti.sql 惯例不出现）
    tables: dict[str, set[str]] = {}
    for m in _CT_RE.finditer(text):
        name = m.group("name").lower()
        start = m.end()
        # 找到匹配的右括号
        depth = 1
        i = start
        in_quote: str | None = None
        while i < len(text) and depth > 0:
            ch = text[i]
            if in_quote:
                if ch == in_quote:
                    in_quote = None
            elif ch in ("'", '"'):
                in_quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        body = text[start:i - 1]
        cols: set[str] = set()
        for part in _split_top_level(body):
            c = _col_name(part)
            if c:
                cols.add(c.lower())
        tables[name] = cols
    return tables


def model_tables() -> dict[str, set[str]]:
    """ORM 声明 → {表名: {列名}}。"""
    from sqlalchemy.orm import close_all_sessions  # noqa: F401 触发导入检查
    from app.database import Base
    import app.models  # noqa: F401,E402  —— 注册全部 mapper

    out: dict[str, set[str]] = {}
    for mapper in Base.registry.mappers:
        tbl = mapper.mapper.class_.__tablename__.lower()
        out[tbl] = {c.name.lower() for c in mapper.mapper.columns}
    return out


# ---------------------------------------------------------------- 种子解析
# 优化12 §7.3：lint_std_bank_align.py 与本校验器共用（单一解析实现，import 复用，
# 禁止两处各写一份 SQL 文本解析）。

_BANK_DICT_RE = re.compile(
    r"WHERE dict_code = 'bank_category_gbt45654'\)\s*,\s*'(?P<label>[^']*)',\s*'(?P<value>[^']*)',\s*\d+,\s*'\{(?P<ext>[^{}]*)\}'"
)
_FW_ITEM_RE = re.compile(
    r"^\s*\('GBT45654-2025',\s*'(?P<code>[^']*)',\s*'(?P<name>[^']*)'",
    re.MULTILINE,
)


def parse_bank_dict_items(path: Path) -> dict[str, str]:
    """inti.sql section 78 → {item_value: ext.sub_code}（题库类别字典项全集）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, str] = {}
    for m in _BANK_DICT_RE.finditer(text):
        ext = m.group("ext") or ""
        sub = re.search(r'"sub_code"\s*:\s*"([^"]*)"', ext)
        out[m.group("value")] = sub.group(1) if sub else ""
    return out


def parse_framework_gbt45654(path: Path) -> dict[str, str]:
    """inti.sql section 78 → {code: name}（framework=GBT45654-2025 子类种子行）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    return {m.group("code"): m.group("name") for m in _FW_ITEM_RE.finditer(text)}


def parse_bank_dict_items_split() -> dict[str, str]:
    """优化13 拆分后字典基准：种子语句自 inti.sql 原样迁移至 data.sql，
    两文件合并解析（inti 命中保留、data 覆盖，兼容拆分前后两代仓库）。"""
    out = parse_bank_dict_items(INTI_SQL)
    if DATA_SQL.exists():
        out.update(parse_bank_dict_items(DATA_SQL))
    return out


def parse_framework_gbt45654_split() -> dict[str, str]:
    """同上：framework_items(GBT45654-2025) 种子行 inti.sql + data.sql 合并解析。"""
    out = parse_framework_gbt45654(INTI_SQL)
    if DATA_SQL.exists():
        out.update(parse_framework_gbt45654(DATA_SQL))
    return out


def db_tables(db_url: str) -> dict[str, set[str]]:
    """数据库 information_schema → {表名: {列名}}（public schema BASE TABLE）。"""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    eng = create_engine(db_url, connect_args={"connect_timeout": 5})
    out: dict[str, set[str]] = {}
    with Session(eng) as s:
        rows = s.execute(text(
            """
            SELECT c.table_name, c.column_name
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = c.table_schema AND t.table_name = c.table_name
            WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
            """
        )).fetchall()
    eng.dispose()
    for t, c in rows:
        out.setdefault(str(t).lower(), set()).add(str(c).lower())
    return out


def resolve_db_url(cli_url: str | None) -> str | None:
    if cli_url:
        return cli_url
    try:
        from app.config import settings
        url = getattr(settings, "DATABASE_URL", None)
        if url:
            return str(url)
    except Exception:  # noqa: BLE001
        pass
    return None


def _diff_raw(exp: dict[str, set[str]], got: dict[str, set[str]],
              exp_name: str, got_name: str) -> list[dict[str, str]]:
    """exp 有而 got 缺 / got 多出的表列（不做基线过滤）。"""
    issues: list[dict[str, str]] = []
    for tbl in sorted(set(exp) | set(got)):
        e = exp.get(tbl)
        g = got.get(tbl)
        if e is not None and g is None:
            issues.append({"pair": f"{exp_name}->{got_name}", "table": tbl,
                           "kind": "missing_table",
                           "detail": f"{got_name} 缺表 {tbl}"})
            continue
        if g is not None and e is None:
            issues.append({"pair": f"{exp_name}->{got_name}", "table": tbl,
                           "kind": "extra_table",
                           "detail": f"{got_name} 多表 {tbl}（{exp_name} 未声明）"})
            continue
        for col in sorted(e - g):
            issues.append({"pair": f"{exp_name}->{got_name}", "table": tbl,
                           "kind": "missing_column", "column": col,
                           "detail": f"{got_name} 表 {tbl} 缺列 {col}"})
        for col in sorted(g - e):
            issues.append({"pair": f"{exp_name}->{got_name}", "table": tbl,
                           "kind": "extra_column", "column": col,
                           "detail": f"{got_name} 表 {tbl} 多列 {col}（{exp_name} 未声明）"})
    return issues


def _diff(exp: dict[str, set[str]], got: dict[str, set[str]],
          exp_name: str, got_name: str, baseline: dict[str, Any]) -> list[dict[str, str]]:
    """_diff_raw + 豁免基线过滤。"""
    exempt = baseline.get("exempt", {})
    return [i for i in _diff_raw(exp, got, exp_name, got_name)
            if not _exempted(exempt, i)]


def main() -> int:
    ap = argparse.ArgumentParser(description="实体类↔库↔inti.sql 三方只读一致性校验")
    ap.add_argument("--db-url", default=None, help="PostgreSQL URL（缺省读 backend/.env）")
    ap.add_argument("--refresh-baseline", action="store_true",
                    help="把当前全部差异写回豁免基线（仅在人工确认差异合法后使用）")
    args = ap.parse_args()

    if not INTI_SQL.exists():
        print(f"[错误] inti.sql 不存在：{INTI_SQL}", file=sys.stderr)
        return 2
    try:
        inti = parse_inti_sql(INTI_SQL)
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] inti.sql 解析失败：{exc}", file=sys.stderr)
        return 2
    try:
        mdl = model_tables()
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] ORM 模型加载失败：{exc}", file=sys.stderr)
        return 2

    mode = "three-way"
    dbt: dict[str, set[str]] | None = None
    url = resolve_db_url(args.db_url)
    if url:
        try:
            dbt = db_tables(url)
        except Exception as exc:  # noqa: BLE001
            mode = "two-way(models vs inti.sql) —— 数据库不可达，降级对账"
            print(f"[警告] 数据库连接失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
    else:
        mode = "two-way(models vs inti.sql) —— 未提供数据库连接，降级对账"

    baseline: dict[str, Any] = {"version": 1, "exempt": {}}
    if BASELINE.exists():
        try:
            baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[错误] 基线文件损坏：{BASELINE}（{exc}）", file=sys.stderr)
            return 2
    exempt = baseline.get("exempt", {})

    issues: list[dict[str, str]] = []
    issues += _diff(mdl, inti, "models", "inti.sql", baseline)
    if dbt is not None:
        issues += _diff(mdl, dbt, "models", "db", baseline)
        issues += _diff(inti, dbt, "inti.sql", "db", baseline)

    if args.refresh_baseline:
        # 重算未过滤差异（忽略现有基线）供人工复核后固化
        raw: list[dict[str, str]] = []
        raw += _diff_raw(mdl, inti, "models", "inti.sql")
        if dbt is not None:
            raw += _diff_raw(mdl, dbt, "models", "db")
            raw += _diff_raw(inti, dbt, "inti.sql", "db")
        new_exempt: dict[str, Any] = {}
        for it in raw:
            key = f"{it['pair']}|{it['table']}"
            if it["kind"] in ("missing_table", "extra_table"):
                new_exempt[key] = "*"
            else:
                v = new_exempt.setdefault(key, [])
                if it.get("column") and it["column"] not in v:
                    v.append(it["column"])
        baseline = {"version": 1, "note": "refresh-baseline 自动生成，须人工复核",
                    "exempt": new_exempt}
        BASELINE.write_text(json.dumps(baseline, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"[基线] 已写入 {len(raw)} 条差异豁免 → {BASELINE}")
        return 0

    report = {
        "mode": mode,
        "tables": {"models": len(mdl), "inti_sql": len(inti),
                   "db": len(dbt) if dbt is not None else None},
        "exempt_in_baseline": len(exempt),
        "issues_new": issues,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if issues:
        print(f"[失败] 基线外新差异 {len(issues)} 条（模式：{mode}）", file=sys.stderr)
        return 1
    print(f"[通过] 无基线外新差异（模式：{mode}"
          + ("，已降级两方对账，未核对数据库" if dbt is None else "，三方对账") + "）")
    return 0


def _exempted(exempt: dict[str, Any], it: dict[str, str]) -> bool:
    """基线豁免匹配：键 = "pair|table"，值 = ["col", ...] 或 "*"（整表）。"""
    key = f"{it['pair']}|{it['table']}"
    v = exempt.get(key)
    if v is None:
        return False
    if v == "*":
        return True
    if isinstance(v, list):
        col = it.get("column")
        if col is None:
            return False
        return col in v or "*" in v
    return False


if __name__ == "__main__":
    sys.exit(main())
