# -*- coding: utf-8 -*-
"""ES8-BUG-012(a)：inti.sql 幂等性对账门禁 —— Python 版（无 psql/pg_dump 环境用）

与 check_ddl_idempotent.sh 判据等价：向一次性临时库连跑两遍 database/inti.sql，
两遍各自的 schema 快照（information_schema + pg_catalog 导出，替代 pg_dump
--schema-only）diff 必须为空——第二次执行不得产生任何 schema 变化（DDL-06）。

用法：
    python scripts/check_ddl_idempotent.py [inti.sql 路径]
环境（默认值，可用环境变量覆盖）：
    IDEM_PG_HOST / IDEM_PG_PORT / IDEM_PG_USER / IDEM_PG_PASSWORD / IDEM_PG_MAINT_DB
    维护库需 CREATEDB 权限；本机需 psycopg2。

实现说明（与 bash 版差异）：
  * psycopg2 执行 CREATE DATABASE / 整库脚本均需 autocommit=True；
    整库一次性 execute()（simple query 协议），显式 BEGIN/COMMIT 由服务端处理。
  * 本仓库无 psql/pg_dump 客户端，快照用 SQL 查询 information_schema.columns、
    pg_indexes、pg_constraint、pg_class(视图/表) 拼文本替代 pg_dump。
  * inti.sql 当前不含 \\c 等 psql 元命令，也不含 CREATE ROLE/DATABASE；
    为稳健起见仍按行首正则跳过 psql 元命令行（\"\\\\+字母\"，字符串字面量
    不以反斜杠+字母出现在行首，无误伤），CREATE ROLE/CREATE DATABASE/ALTER ROLE
    等对临时库无效或已在维护连接执行的语句会被剔除并计数报告。
  * 结束（含异常）时 finally 强制 drop 临时库，等价 bash 版 trap EXIT cleanup。
"""
import os
import re
import sys
import difflib

import psycopg2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL_FILE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO_ROOT, "database", "inti.sql")
TMPDB = "evalshield_ddl_idem_test"

MAINT = dict(
    host=os.environ.get("IDEM_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("IDEM_PG_PORT", "5432")),
    user=os.environ.get("IDEM_PG_USER", "EvalShield"),
    password=os.environ.get("IDEM_PG_PASSWORD", "EvalShield"),
    dbname=os.environ.get("IDEM_PG_MAINT_DB", "EvalShield"),
    connect_timeout=10,
)

# psql 元命令（行首反斜杠+字母），以及对本临时库无效/应跳过的语句
META_RE = re.compile(r"^\s*\\[a-zA-Z]")
SKIP_STMT_RE = re.compile(
    r"^\s*(CREATE\s+ROLE|CREATE\s+USER|CREATE\s+DATABASE|ALTER\s+ROLE|ALTER\s+DATABASE|DROP\s+DATABASE|DROP\s+ROLE|CREATE\s+EXTENSION|ALTER\s+SYSTEM|GRANT\s+CREATE\s+ON\s+SCHEMA\s+public\s+TO\s+PUBLIC)\b",
    re.IGNORECASE,
)


def prep_sql(raw: str):
    """逐行剔除 psql 元命令；再按分号感知的粗粒度整块剥离 CREATE ROLE 等语句。
    inti.sql 实际不含这两类语句，此函数是防御性对齐 bash 版 psql -f 的容错。"""
    lines = []
    dropped_meta = 0
    for ln in raw.splitlines():
        if META_RE.match(ln):
            dropped_meta += 1
            continue
        lines.append(ln)
    text = "\n".join(lines) + "\n"
    dropped_other = 0
    if SKIP_STMT_RE.search(text):
        # 保守处理：含此类语句即报告并整体跳过该"行"（这些脚本语句均为单行形态）
        kept = []
        for ln in text.splitlines():
            if SKIP_STMT_RE.match(ln):
                dropped_other += 1
            else:
                kept.append(ln)
        text = "\n".join(kept) + "\n"
    return text, dropped_meta, dropped_other


SNAPSHOT_QUERIES = [
    ("tables", """
        SELECT c.relname, c.relkind
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','m')
        ORDER BY 1"""),
    ("columns", """
        SELECT table_name, column_name, data_type, udt_name, is_nullable,
               coalesce(column_default,'')
        FROM information_schema.columns
        WHERE table_schema='public'
        ORDER BY 1,2"""),
    ("indexes", """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes WHERE schemaname='public' ORDER BY 2,1"""),
    ("constraints", """
        SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)
        FROM pg_constraint WHERE connamespace='public'::regnamespace
        ORDER BY 2,1"""),
    ("views", """
        SELECT c.relname, pg_get_viewdef(c.oid, true)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind='v' ORDER BY 1"""),
    ("sequences", """
        SELECT relname FROM pg_class
        WHERE relkind='S' AND relnamespace='public'::regnamespace ORDER BY 1"""),
]


def export_snapshot(conn):
    parts = []
    with conn.cursor() as cur:
        for label, q in SNAPSHOT_QUERIES:
            cur.execute(q)
            parts.append(f"-- {label}")
            for row in cur.fetchall():
                parts.append("\t".join(str(x) for x in row))
    return "\n".join(parts) + "\n"


def run_script(cur, sql_text, tag):
    print(f"==> 第 {tag} 遍执行 {os.path.basename(SQL_FILE)}")
    cur.execute(sql_text)


def main():
    if not os.path.isfile(SQL_FILE):
        print(f"FATAL: inti.sql 不存在: {SQL_FILE}", file=sys.stderr)
        return 1
    with open(SQL_FILE, encoding="utf-8") as f:
        sql_text, dm, do = prep_sql(f.read())
    if dm or do:
        print(f"NOTE: 跳过 psql 元命令行 {dm} 行、临时库无效语句 {do} 行（inti.sql 预期均为 0）")

    maint = psycopg2.connect(**MAINT)
    maint.autocommit = True
    tmp_conn = None
    try:
        with maint.cursor() as cur:
            print(f"==> 建临时库 {TMPDB}")
            cur.execute(f"DROP DATABASE IF EXISTS {TMPDB}")
            cur.execute(f"CREATE DATABASE {TMPDB}")

        cfg = dict(MAINT, dbname=TMPDB)
        tmp_conn = psycopg2.connect(**cfg)
        tmp_conn.autocommit = True  # 脚本内含显式 BEGIN/COMMIT，必须 autocommit 直发
        with tmp_conn.cursor() as cur:
            run_script(cur, sql_text, 1)
        snap1 = export_snapshot(tmp_conn)

        with tmp_conn.cursor() as cur:
            run_script(cur, sql_text, 2)
        snap2 = export_snapshot(tmp_conn)

        print("==> 断言关键新表/扩列存在")
        with tmp_conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema='public' AND table_name IN
                ('question_bank','question','eval_run_items','delivery_packages','fact_sources','global_refusal_rules')""")
            have = {r[0] for r in cur.fetchall()}
            missing = {"question_bank", "question", "eval_run_items", "delivery_packages", "fact_sources", "global_refusal_rules"} - have
            cur.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='review_items'
                  AND column_name='judge_prompt_hash'""")
            if cur.fetchone() is None:
                missing.add("review_items.judge_prompt_hash")
        if missing:
            print(f"FAIL: 关键对象缺失: {sorted(missing)}", file=sys.stderr)
            return 1

        print("==> 比对两遍 schema 快照")
        if snap1 == snap2:
            print("PASS: inti.sql 幂等（两遍执行 schema 零漂移）")
            return 0
        print("FAIL: 第二遍执行产生 schema 漂移：", file=sys.stderr)
        diff = list(difflib.unified_diff(
            snap1.splitlines(), snap2.splitlines(), "snap1", "snap2", lineterm=""))
        for line in diff[:80]:
            print(line, file=sys.stderr)
        return 1
    finally:
        if tmp_conn is not None:
            try:
                tmp_conn.close()
            except Exception:
                pass
        try:
            with maint.cursor() as cur:
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                    (TMPDB,))
                cur.execute(f"DROP DATABASE IF EXISTS {TMPDB}")
                print(f"==> 已清理临时库 {TMPDB}")
        except Exception as e:
            print(f"WARN: 临时库清理失败，请手工 DROP DATABASE {TMPDB}: {e}", file=sys.stderr)
        maint.close()


if __name__ == "__main__":
    sys.exit(main())
