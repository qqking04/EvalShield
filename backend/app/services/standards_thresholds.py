# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""优化12 §6.1（T2 / M1b）：TC260/GBT45654 监管阈值核定写入服务。

把 CLI 的 ``patch_block()`` 与入参校验迁为纯函数（不做 IO、不读环境变量——
可测、可被 CLI 与 API 共用）；写盘统一走本模块 ``_atomic_write``：

- 同目录临时文件写全文 → flush + fsync → os.replace 原子重命名（禁止截断写）；
- 任何一步异常 → 清理 tmp 后原样抛出，原文件保持不动（失败回滚 = 从未触碰原文件）；
- 文件锁（``config_lock``）保护"读-改-写"全程，原子写保护"写"这一瞬。

块式行级改写约束（§6.1 v2.1）：``validate_and_patch`` 只做行级改写，不做键
插入；目标块缺 ``min_questions`` / ``pass_threshold`` 行 → 抛"块结构不符"。
唯一例外是 ``validate_and_patch_refusal``：顶层 ``refusal_thresholds:`` 块缺失
时允许追加规范模板块（v2.2，解决 Q19 之一），块存在但缺键仍拒绝。

留痕注释格式与旧 CLI 完全一致（§6.2）：在类别行之后插入
``# 人工核定 {日期}：核定人 {reviewer}；依据 {basis}``，块内已存在则原位替换。

环境隔离：核定目标 = 显式 target > 环境变量 ``STANDARDS_CONFIG`` > 仓库
deploy/standards/tc260.yaml（§6.3/§14 灰度说明）。自测一律指向临时副本，
**禁止写生产 yaml**。
"""

from __future__ import annotations

import os
import re
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, BinaryIO, Iterator

import yaml

# 仓库根 deploy/standards/tc260.yaml（backend/app/services/ 上溯三级到仓库根）
DEFAULT_YAML = Path(__file__).resolve().parents[3] / "deploy" / "standards" / "tc260.yaml"

_ENV_KEY = "STANDARDS_CONFIG"

# 块定位正则（支持两级：旧单层 category_code / 新两级 sub_code，§6.1）
CAT_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)(?:-[ \t]+)?(?:category_code|sub_code):[ \t]*(?P<code>\S+)"
)

_TRACE_RE = re.compile(r"(?m)^[ \t]*# 人工核定 .*$\r?\n?")
_BASIS_RE = re.compile(r"GB/T|TC260")
_TRAIL_RE = re.compile(r"[ \t]*(?:#[^\r\n]*)?(\r?\n)$")


def resolve_target(override: str | os.PathLike[str] | None = None) -> Path:
    """核定写入目标路径：显式 target > STANDARDS_CONFIG > 仓库默认（环境隔离）。"""
    if override:
        return Path(override)
    env = (os.environ.get(_ENV_KEY) or "").strip()
    if env:
        return Path(env)
    return DEFAULT_YAML


# ------------------------------------------------------------------ 入参校验


def _check_common(reviewer: str, basis: str) -> None:
    if not (reviewer or "").strip():
        raise ValueError("校验失败：reviewer 不能为空（核定人必填）")
    if not _BASIS_RE.search(basis or ""):
        raise ValueError(
            "校验失败：basis 必须引用 GB/T 45654 或 TC260-003 正式标准条款"
            "（防 AI 口径冒充监管口径）"
        )


# ------------------------------------------------------------------ 块改写原语


def _field_indent(block: str) -> str:
    """块内字段行（min_questions 等）的缩进；缺失回退类别缩进 +4。"""
    m = re.search(r"(?m)^(?P<i>[ \t]*)(?:min_questions|pass_threshold):", block)
    if m:
        return m.group("i")
    first = block.splitlines()[0] if block else ""
    lead = re.match(r"[ \t]*", first).group(0)
    return lead + ("  - " if "- " in first[: len(lead) + 2] else "    ")


def _upsert_trace_line(block: str, reviewer: str, basis: str) -> str:
    """在块首行（类别行）之后插入/替换核定留痕注释（格式与旧 CLI 一致，幂等）。"""
    line = (f"{_field_indent(block)}# 人工核定 {date.today().isoformat()}："
            f"核定人 {reviewer}；依据 {basis}\n")
    m = _TRACE_RE.search(block)
    if m:  # 幂等：已有留痕行则原位替换，不叠加
        return block[: m.start()] + line + block[m.end():]
    head, sep, rest = block.partition("\n")
    if sep == "":
        return head + "\n" + line
    if rest.startswith("\r\n"):
        head, rest = head + "\r", rest[2:]
        sep = "\n"
    return head + sep + line + rest


def _rewrite_value(line: str, key: str, value: Any) -> str:
    """改写块内单行 ``key: <value>`` 的值 token，保留行尾注释。"""
    return re.sub(rf"(?m)^([ \t]*{key}:)[ \t]*\S+", rf"\1 {value}", line, count=1)


def _find_block(text: str, code: str) -> tuple[int, int]:
    """定位 code 块（旧单层 category_code 或新两级 sub_code），返回 (起, 止)。

    块边界：缩进 ≤ 目标块缩进的下一个列表项/顶层键行，或文件尾。
    """
    for m in CAT_RE.finditer(text):
        if m.group("code") != code:
            continue
        indent = len(m.group("indent"))
        nxt = re.compile(rf"(?m)^[ \t]{{0,{indent}}}(?:- |\S)").search(text, m.end())
        return m.start(), (nxt.start() if nxt else len(text))
    raise ValueError(f"校验失败：类别 {code} 不存在于对照集")


# ------------------------------------------------------------------ 纯函数核定


def validate_and_patch(
    text: str,
    *,
    code: str,
    min_questions: Any,
    pass_threshold: Any,
    reviewer: str,
    basis: str,
) -> str:
    """校验入参 → 定位 code 块 → 改写 min_questions/pass_threshold → 留痕 → 新文本。

    校验：reviewer 非空；basis 含 GB/T 或 TC260 条款号；min_questions ≥ 1 整数；
    0 < pass_threshold ≤ 1。块缺两键行 → "块结构不符"（禁止键插入/静默跳过）。
    """
    _check_common(reviewer, basis)
    if not isinstance(min_questions, int) or isinstance(min_questions, bool) \
            or min_questions < 1:
        raise ValueError("校验失败：min_questions 须为 ≥1 的整数")
    if isinstance(pass_threshold, bool) or not isinstance(
        pass_threshold, (int, float)
    ) or not (0 < float(pass_threshold) <= 1):
        raise ValueError("校验失败：pass_threshold 须落在 (0, 1] 区间")

    start, end = _find_block(text, code)
    block = text[start:end]
    if re.search(r"(?m)^[ \t]*min_questions:", block) is None \
            or re.search(r"(?m)^[ \t]*pass_threshold:", block) is None:
        raise ValueError(
            f"块结构不符：{code} 缺 min_questions/pass_threshold 行，"
            "请先按 §5.1 块式补全（核定服务只做行级改写，不做键插入）"
        )

    block = re.sub(r"(?m)^([ \t]*min_questions:)[ \t]*\S+",
                   rf"\1 {min_questions}", block, count=1)
    block = re.sub(r"(?m)^([ \t]*pass_threshold:)[ \t]*\S+",
                   rf"\1 {pass_threshold}", block, count=1)
    block = _upsert_trace_line(block, reviewer, basis)
    return text[:start] + block + text[end:]


REFUSAL_TEMPLATE = """
# ES9-P-11：拒答/误拒阈值（人工核定后生效）
refusal_thresholds:
  refuse_pass_rate_min: null
  false_refuse_rate_max: null
  reviewed_by: null
  basis: null
"""


def validate_and_patch_refusal(
    text: str,
    *,
    refuse_pass_rate_min: Any,
    false_refuse_rate_max: Any,
    reviewer: str,
    basis: str,
) -> str:
    """写顶层 refusal_thresholds 块（§5.1/§6.1 v2.2）。

    唯一允许的结构插入：文件顶层无 ``refusal_thresholds:`` 块时，在文件尾前
    （mapping 块之后）追加规范模板块，随后走同一块内行级改写路径。块存在但
    缺两键行 → 仍抛"块结构不符"。
    """
    _check_common(reviewer, basis)
    for name, v in (
        ("refuse_pass_rate_min", refuse_pass_rate_min),
        ("false_refuse_rate_max", false_refuse_rate_max),
    ):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (
            0 <= float(v) <= 1
        ):
            raise ValueError(f"校验失败：{name} 须落在 [0, 1] 区间")

    m_head = re.search(r"(?m)^refusal_thresholds:", text)
    if m_head is None:
        if text and not text.endswith(("\n", "\r")):
            text += "\n"
        text += REFUSAL_TEMPLATE
        m_head = re.search(r"(?m)^refusal_thresholds:", text)
        assert m_head is not None
    # 块尾 = 其后第一个顶层键行（含缩进行为非顶层；注释/空行归入块内）
    nxt = re.search(r"(?m)^\S", text[m_head.end():])
    end = m_head.end() + nxt.start() if nxt else len(text)
    block = text[m_head.start():end]

    if re.search(r"(?m)^[ \t]+refuse_pass_rate_min:", block) is None \
            or re.search(r"(?m)^[ \t]+false_refuse_rate_max:", block) is None:
        raise ValueError(
            "块结构不符：refusal_thresholds 块缺 refuse_pass_rate_min/"
            "false_refuse_rate_max 行（除缺失块初始化外禁止键插入）"
        )

    block = _rewrite_value(block, "refuse_pass_rate_min", refuse_pass_rate_min)
    block = _rewrite_value(block, "false_refuse_rate_max", false_refuse_rate_max)
    block = re.sub(r"(?m)^([ \t]+reviewed_by:)[ \t]*[^#\r\n]*(?:#[^\r\n]*)?",
                   rf'\1 "{reviewer}"', block, count=1)
    block = re.sub(r"(?m)^([ \t]+basis:)[ \t]*[^#\r\n]*(?:#[^\r\n]*)?",
                   rf"\1 {basis}", block, count=1)
    return text[: m_head.start()] + block + text[end:]


# ------------------------------------------------------------------ 原子写


def _atomic_write(path: Path | str, text: str) -> None:
    """同目录 tmp + fsync + os.replace（§6.1 v2.2）；异常时清理 tmp、原文件不动。"""
    path = Path(path)
    tmp = path.with_name(path.name + f".tmp-{uuid.uuid4()}")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------ 文件锁


class ThresholdLockBusy(RuntimeError):
    """核定文件锁被占用（API 映射 409）。"""


def _lock_file(fh: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(fh: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextmanager
def config_lock(target: Path | str) -> Iterator[None]:
    """跨进程独占锁（保护读-改-写全程）。冲突抛 ThresholdLockBusy。"""
    lock_path = Path(target).with_name(Path(target).name + ".lock")
    fh: BinaryIO | None = None
    try:
        fh = open(lock_path, "a+b")
    except OSError as exc:  # 目录不可写等
        raise ThresholdLockBusy(f"无法打开核定锁文件：{exc}") from exc
    try:
        try:
            _lock_file(fh)
        except OSError as exc:
            raise ThresholdLockBusy("核定配置正被另一进程写入，请稍后重试") from exc
        yield
    finally:
        if fh is not None:
            _unlock_file(fh)
            fh.close()


# ------------------------------------------------------------------ 读写编排


def calibrate(
    payload: dict[str, Any],
    *,
    target: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """核定写入（API 与 CLI 共用）：锁 → 读 → 纯函数改写 → yaml 自检 → 原子写 → 刷新缓存。

    payload 形状（§6.3）::

        {target: "threshold"|"refusal", sub_code?, min_questions?,
         pass_threshold?, refuse_pass_rate_min?, false_refuse_rate_max?,
         reviewer, basis}

    校验不通过抛 ValueError（调用方映射 422）；锁冲突抛 ThresholdLockBusy（409）。
    返回 {target_path, changed, code, yaml_valid}。
    """
    path = resolve_target(target)
    kind = payload.get("target") or "threshold"
    reviewer = str(payload.get("reviewer") or "")
    basis = str(payload.get("basis") or "")
    if not path.exists():
        raise ValueError(f"校验失败：核定目标不存在 {path}")

    with config_lock(path):
        text = path.read_text(encoding="utf-8")
        if kind == "refusal":
            code = "REFUSAL"
            new = validate_and_patch_refusal(
                text,
                refuse_pass_rate_min=payload.get("refuse_pass_rate_min"),
                false_refuse_rate_max=payload.get("false_refuse_rate_max"),
                reviewer=reviewer,
                basis=basis,
            )
        elif kind == "threshold":
            code = str(payload.get("sub_code") or "")
            if not code:
                raise ValueError("校验失败：sub_code 不能为空")
            new = validate_and_patch(
                text,
                code=code,
                min_questions=payload.get("min_questions"),
                pass_threshold=payload.get("pass_threshold"),
                reviewer=reviewer,
                basis=basis,
            )
        else:
            raise ValueError(f"校验失败：target 仅支持 threshold/refusal，收到 {kind!r}")

        try:  # 写前自检：改写结果必须是合法 YAML
            yaml.safe_load(new)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"校验失败：改写后 YAML 非法（未写盘）：{exc}") from exc

        changed = new != text
        if changed:
            _atomic_write(path, new)

    # 写后自检（刷新缓存；standards 不可用不影响已完成的写入）
    try:  # pragma: no cover —— CLI 独立运行时 app 包可能不可导入
        from . import standards

        standards.load_standards(force=True)
    except Exception:  # noqa: BLE001
        pass
    return {"target_path": str(path), "changed": changed, "code": code}
