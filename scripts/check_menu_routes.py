#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ES8-BUG-012: menus/permissions 种子 path 与前端路由表 / 导航项双向对账。

对账规则（任一失败 exit 1）：
  R1 正向（DB -> 前端）：inti.sql 中 menus 种子 INSERT 的全部 path 字面量
     （去豁免）必须能在 App.jsx 路由表中命中；
     permissions 种子 INSERT 语句不得出现 '/xxx' 形态 path 字面量
     （permissions 表无 path 列，出现即说明种子写歪）。
  R2 导航（MainLayout -> 前端）：MainLayout.jsx MENUS 数组全部 key
     （去豁免目录节点）必须能在 App.jsx 路由表中命中。
  R3 反向（前端 -> 台账）：App.jsx 主布局（path="/"）下「单段静态」子路由
     必须至少出现在 menus 种子或 MENUS 导航之一；结构性路由豁免：
     Navigate 重定向路由、作为某个种子/导航 path 前缀的父段路由。

已知豁免（目录节点 / 历史遗留页，台账与前端刻意不一致）：
  /dashboard  /cases  /environments  /admin(dir)  /lab(dir)

用法：python scripts/check_menu_routes.py   （仓库根或任意目录均可）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTI_SQL = os.path.join(ROOT, "database", "inti.sql")
APP_JSX = os.path.join(ROOT, "frontend", "src", "App.jsx")
MAIN_LAYOUT = os.path.join(ROOT, "frontend", "src", "layout", "MainLayout.jsx")

EXEMPT = {"/dashboard", "/cases", "/environments", "/admin", "/lab"}

PATH_LITERAL = re.compile(r"'(/[^']*)'")
INSERT_MENUS = re.compile(r"INSERT\s+INTO\s+menus\b", re.IGNORECASE)
INSERT_PERMS = re.compile(r"INSERT\s+INTO\s+permissions\b", re.IGNORECASE)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def strip_sql_comments(sql):
    """去掉行内 -- 注释，保留字符串字面量原样。"""
    out_lines = []
    for line in sql.splitlines():
        in_str = False
        cut = len(line)
        i = 0
        while i < len(line) - 1:
            c = line[i]
            if c == "'":
                in_str = not in_str
            elif c == "-" and not in_str and line[i + 1] == "-":
                cut = i
                break
            i += 1
        out_lines.append(line[:cut])
    return "\n".join(out_lines)


def extract_statements(sql, insert_re):
    """从 SQL 文本抽出每个 INSERT 语句体（到最近的顶层 ';'）。"""
    stmts = []
    for m in insert_re.finditer(sql):
        end = sql.find(";", m.end())
        if end == -1:
            continue
        stmts.append(sql[m.start():end])
    return stmts


def parse_seed_paths(sql):
    """R1a：menus 种子 INSERT 中的 path 字面量集合。"""
    paths = set()
    for stmt in extract_statements(sql, INSERT_MENUS):
        paths.update(PATH_LITERAL.findall(stmt))
    return paths


def parse_permissions_drift(sql):
    """R1b：permissions 种子 INSERT 中不应出现 '/xxx' 字面量。"""
    bad = set()
    for stmt in extract_statements(sql, INSERT_PERMS):
        bad.update(PATH_LITERAL.findall(stmt))
    return bad


def _tag_end(text, start):
    """从 '<Route' 起扫描到开标签结束，返回 (结束位置含'>', 是否自闭合)。"""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == '"':
            j = text.find('"', i + 1)
            i = j if j != -1 else i
        elif depth == 0 and c == ">":
            return i + 1, text[i - 1] == "/"
        i += 1
    raise ValueError("unterminated <Route tag")


def parse_app_routes(src):
    """解析 App.jsx：返回 (主布局绝对路由集合, Navigate 重定向路由集合)。

    栈式遍历 <Route / </Route> 令牌，嵌套相对 path 拼接父级绝对路径。
    仅收录 "/" 主布局（登录后受保护面）下的路由——顶层免登录页
    （/login、/pricing 等）与通配兜底不参与菜单对账。
    """
    tokens = []
    for m in re.finditer(r"<Route(?![A-Za-z])", src):
        end, self_closing = _tag_end(src, m.start())
        pm = re.search(r'path="([^"]*)"', src[m.start():end])
        tokens.append((m.start(), pm.group(1) if pm else "", self_closing))
    for m in re.finditer(r"</Route\s*>", src):
        tokens.append((m.start(), None, False))
    tokens.sort(key=lambda t: t[0])

    routes, redirects = set(), set()
    stack = []  # 打开中（未自闭合）路由的绝对路径栈
    for _, path, self_closing in tokens:
        if path is None:  # </Route>
            if stack:
                stack.pop()
            continue
        parent = stack[-1] if stack else None
        if path.startswith("/"):
            abspath = path
        elif path == "index" or path == "":
            abspath = parent or "/"
        else:
            abspath = (parent.rstrip("/") if parent else "") + "/" + path
        in_layout = "/" in stack or abspath == "/"
        if in_layout:
            routes.add(abspath)
        if not self_closing:
            # 非自闭合：可能是容器（"/" 布局）或 element 内含组件包裹
            stack.append(abspath)
    # 重定向路由：element={<Navigate .../>} 的 Route 单独收集
    for m in re.finditer(r'<Route(?![A-Za-z])[\s\S]{0,400}?/>', src):
        seg = m.group(0)
        pm = re.search(r'path="([^"]*)"', seg)
        if pm and "<Navigate" in seg:
            parent_hint = pm.group(1)
            abs_p = parent_hint if parent_hint.startswith("/") else "/" + parent_hint
            redirects.add(abs_p)
    return routes, redirects


def parse_nav_keys(src):
    """解析 MainLayout.jsx MENUS 数组的全部 key。"""
    m = re.search(r"const MENUS = \[([\s\S]*?)\n\]", src)
    if not m:
        raise RuntimeError("MENUS array not found in MainLayout.jsx")
    return set(re.findall(r"key:\s*'([^']+)'", m.group(1)))


def main():
    sql = strip_sql_comments(read(INTI_SQL))
    app_src = read(APP_JSX)
    layout_src = read(MAIN_LAYOUT)

    seed = parse_seed_paths(sql)
    perms_drift = parse_permissions_drift(sql)
    routes, redirects = parse_app_routes(app_src)
    nav = parse_nav_keys(layout_src)

    print("seed menu paths : %d" % len(seed))
    print("app routes      : %d" % len(routes))
    print("nav keys        : %d" % len(nav))

    errors = []

    # R1a 正向：种子 path（去豁免）必须在路由表
    for p in sorted(seed - EXEMPT):
        if p not in routes:
            errors.append("R1 seed path not in App.jsx routes: %s" % p)

    # R1b：permissions 种子不得含 path 字面量
    for p in sorted(perms_drift):
        errors.append("R1 permissions seed contains path literal (no path column): %s" % p)

    # R2：导航 key（去豁免目录节点）必须在路由表
    for p in sorted(nav - EXEMPT):
        if p not in routes:
            errors.append("R2 nav key not in App.jsx routes: %s" % p)

    # R3 反向：主布局下单段静态子路由必须有台账（种子或导航）
    ledger = seed | nav
    known_prefixes = {q for q in ledger} | {q for q in routes}
    for p in sorted(routes):
        if not p.startswith("/") or p == "/" or p == "*":
            continue
        seg = p[1:]
        if not seg or "/" in seg or ":" in seg or "*" in seg:
            continue  # 仅对账单段静态子路由
        if p in ledger:
            continue
        if p in redirects:
            continue  # Navigate 重定向为结构性路由
        if any(q != p and q.startswith(p + "/") for q in known_prefixes):
            continue  # 父段路由：其子路径已登记
        errors.append("R3 App route not in menus seed nor nav: %s" % p)

    if errors:
        for e in errors:
            print("FAIL " + e)
        sys.exit(1)
    print("OK menu/routes cross-check passed (%d seed, %d nav, %d routes)"
          % (len(seed), len(nav), len(routes)))
    sys.exit(0)


if __name__ == "__main__":
    main()
