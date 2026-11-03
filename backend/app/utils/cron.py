# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""Cron 表达式解析（5 段：分 时 日 月 周）。

支持语法：* 、*/n 、a-b 、a-b/n 、逗号列表、单个数字；周字段 0-6（0/7 为周日，可写 SUN 等）。
用途：定时任务 worker 的命中判断与前端"下次执行时间"展示。
"""

from __future__ import annotations

from datetime import datetime, timedelta

_WEEKDAY_ALIAS = {
    "SUN": 0,
    "MON": 1,
    "TUE": 2,
    "WED": 3,
    "THU": 4,
    "FRI": 5,
    "SAT": 6,
}


def _expand_field(field: str, lo: int, hi: int) -> set[int]:
    """展开单个字段为数字集合（含 *、*/n、a-b、a-b/n、逗号列表）。"""
    if field in ("*", "?"):
        return set(range(lo, hi + 1))
    values: set[int] = set()
    for part in str(field).split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            part, _, step_str = part.partition("/")
            try:
                step = int(step_str)
            except ValueError:
                step = 1
            if step < 1:
                step = 1
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, _, b = part.partition("-")
            try:
                start, end = int(a), int(b)
            except ValueError:
                continue
            if end < start:
                end, start = start, end
        else:
            try:
                num = int(part)
            except ValueError:
                num = _WEEKDAY_ALIAS.get(part.upper(), -1)
                if num < 0:
                    continue
            start = end = num
        for v in range(start, end + 1, step):
            if lo <= v <= hi:
                values.add(v)
    return values


class CronExpr:
    """标准 5 段 cron 表达式。语义：各字段 AND 匹配（周字段与日期字段同时生效）。"""

    def __init__(self, expr: str) -> None:
        parts = str(expr).strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"cron 表达式必须为 5 段（分 时 日 月 周），收到: {expr!r}"
            )
        self.minutes = _expand_field(parts[0], 0, 59)
        self.hours = _expand_field(parts[1], 0, 23)
        self.days = _expand_field(parts[2], 1, 31)
        self.months = _expand_field(parts[3], 1, 12)
        self.weekdays = _expand_field(parts[4], 0, 7)  # 7 归一为周日
        if 7 in self.weekdays:
            self.weekdays.discard(7)
            self.weekdays.add(0)

    def matches(self, dt: datetime) -> bool:
        # Python weekday(): 0=周一…6=周日；cron 周字段：0/7=周日，1=周一…
        cron_wd = (dt.weekday() + 1) % 7
        return (
            dt.minute in self.minutes
            and dt.hour in self.hours
            and dt.day in self.days
            and dt.month in self.months
            and cron_wd in self.weekdays
        )

    def next_after(self, from_dt: datetime) -> datetime | None:
        """计算 from_dt 之后的第一个命中时刻（精确到分钟）。”"""
        cur = from_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        # 最多向前搜索 366 天，避免死循环
        limit = from_dt + timedelta(days=366)
        while cur <= limit:
            if self.matches(cur):
                return cur
            cur += timedelta(minutes=1)
        return None


def parse_cron(expr: str | None) -> CronExpr | None:
    if not expr or not str(expr).strip():
        return None
    try:
        return CronExpr(str(expr))
    except ValueError:
        return None


def next_fire(expr: str | None, after: datetime) -> datetime | None:
    """求 after 之后的首个命中时刻（ES8 M4：monitors.next_fire_at 推进用）。

    复用 CronExpr.matches 判定；逐分钟推进，命中前先做日级/时级跳跃避免空转，
    上限回扫 400 天（极端表达式不可能命中时返回 None）。表达式无效返回 None。
    """
    c = parse_cron(expr)
    if c is None:
        return None
    cur = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = after + timedelta(days=400)
    while cur <= limit:
        # 日级跳跃：月/日/周任一不命中则整日不可能命中，直接跳次日 00:00
        if (
            cur.month not in c.months
            or cur.day not in c.days
            or (cur.weekday() + 1) % 7 not in c.weekdays
        ):
            cur = (cur + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        # 时级跳跃：当前小时不可能命中则跳下一整点
        if cur.hour not in c.hours:
            cur = (cur + timedelta(hours=1)).replace(minute=0)
            continue
        if c.matches(cur):
            return cur
        cur += timedelta(minutes=1)
    return None


if __name__ == "__main__":
    # 自检
    c = parse_cron("*/5 * * * *")  # 每 5 分钟
    assert c and c.matches(datetime(2026, 1, 1, 10, 5))
    assert c and not c.matches(datetime(2026, 1, 1, 10, 6))
    c2 = parse_cron("0 9 * * 1")  # 每周一 09:00
    assert c2 and c2.matches(datetime(2026, 9, 14, 9, 0))  # 2026-09-14 是周一
    assert c2 and not c2.matches(datetime(2026, 9, 15, 9, 0))
    nxt = parse_cron("30 14 * * *").next_after(datetime(2026, 9, 15, 13, 59))  # type: ignore[union-attr]
    print("cron self-check OK", nxt)
