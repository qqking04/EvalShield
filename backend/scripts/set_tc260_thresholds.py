# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# SPDX-License-Identifier: BUSL-1.1
"""ES11 修复 / 优化12 §6.2（T2）：监管阈值人工核定工具（交付人专用瘦 CLI）。

合规约束（设计方案 §4.3.1 / AGENTS.md）：min_questions / pass_threshold 的
数值**只能由交付人依据 GB/T 45654 / TC260-003 正式原文核定**，AI 与脚本
不得推断填值。本 CLI 只做参数解析与转调：

- 校验、块式行级改写、留痕注释、文件锁、原子写、写后自检统一在
  ``app.services.standards_thresholds``（与 PUT /api/standards/thresholds
  同一实现，保证 CLI 与 API 产出同一文本）；
- ``--category`` 同时接受旧单层 ``TC260-*`` 与新两级子类码（A1a~A5*/Xt1/Xq1/Xq2）；
- ``--target refusal`` 走 refuse_pass_rate_min / false_refuse_rate_max 通道；
- 既有参数、退出码（校验失败 REJECT→2）、留痕注释格式全部不变。

用法（backend 目录）：
    python scripts/set_tc260_thresholds.py --category TC260-A1.1 \
        --min-questions 100 --pass-threshold 0.95 \
        --reviewer "张三(合规)" --basis "GB/T 45654-2025 §8.2 表3" [--dry-run]
    python scripts/set_tc260_thresholds.py --target refusal \
        --refuse-pass-rate-min 0.95 --false-refuse-rate-max 0.05 \
        --reviewer "张三(合规)" --basis "GB/T 45654-2025 §附录" [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许从任意 cwd 直接运行本脚本：把 backend/ 挂进 sys.path 以便导入 app 包
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import standards_thresholds as svc  # noqa: E402

# 仓库根 deploy/standards/tc260.yaml（保持旧常量名，兼容既有引用）
DEFAULT_YAML = svc.DEFAULT_YAML

CAT_RE = svc.CAT_RE  # 兼容旧模块级引用（实际匹配逻辑在服务层）


def patch_block(text: str, category: str, min_q: int, threshold: float,
                reviewer: str, basis: str) -> str:
    """按类别块替换 min_questions / pass_threshold 并写入核定留痕注释。

    瘦转调：签名与语义保持旧 CLI 纯函数形态（可单测），实现统一走
    services 层 validate_and_patch（校验 + 行级改写 + 留痕）。
    """
    return svc.validate_and_patch(
        text, code=category, min_questions=min_q, pass_threshold=threshold,
        reviewer=reviewer, basis=basis,
    )


def _preview(new_text: str, anchor: str) -> None:
    print(f"[DRY] {anchor} 核定预览（相关行）：")
    show = 0
    for ln in new_text.splitlines():
        if anchor in ln:
            show = 8
        if show > 0:
            print("  |", ln)
            show -= 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="监管阈值人工核定（交付人专用）")
    ap.add_argument("--file", default=None,
                    help="目标 yaml；缺省 = STANDARDS_CONFIG 环境变量 → 仓库默认")
    ap.add_argument("--target", choices=["threshold", "refusal"], default="threshold",
                    help="threshold=类别阈值块（默认）；refusal=拒答/误拒阈值块")
    ap.add_argument("--category",
                    help="子类码：旧单层 TC260-* 或新两级 A1a~A5*/Xt1/Xq1/Xq2")
    ap.add_argument("--min-questions", type=int)
    ap.add_argument("--pass-threshold", type=float)
    ap.add_argument("--refuse-pass-rate-min", type=float,
                    help="target=refusal：拒答正确率下限 [0,1]")
    ap.add_argument("--false-refuse-rate-max", type=float,
                    help="target=refusal：误拒率上限 [0,1]")
    ap.add_argument("--reviewer", required=True,
                    help="核定人姓名（职责：交付/合规负责人），写入留痕注释")
    ap.add_argument("--basis", required=True,
                    help="标准原文条款依据，如 'GB/T 45654-2025 §8.2'；禁止填写 AI 推断口径")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    target = Path(a.file) if a.file else svc.resolve_target()

    try:
        text = target.read_text(encoding="utf-8")
        if a.target == "refusal":
            new = svc.validate_and_patch_refusal(
                text,
                refuse_pass_rate_min=a.refuse_pass_rate_min,
                false_refuse_rate_max=a.false_refuse_rate_max,
                reviewer=a.reviewer, basis=a.basis,
            )
            anchor = "refusal_thresholds"
        else:
            if not a.category or a.min_questions is None or a.pass_threshold is None:
                raise ValueError(
                    "校验失败：target=threshold 需要 --category/--min-questions/--pass-threshold")
            new = patch_block(text, a.category, a.min_questions, a.pass_threshold,
                              a.reviewer, a.basis)
            anchor = a.category
    except ValueError as exc:
        print(f"REJECT：{exc}")
        return 2

    if a.dry_run:
        _preview(new, anchor)
        return 0

    try:
        res = svc.calibrate(
            {
                "target": a.target,
                "sub_code": a.category,
                "min_questions": a.min_questions,
                "pass_threshold": a.pass_threshold,
                "refuse_pass_rate_min": a.refuse_pass_rate_min,
                "false_refuse_rate_max": a.false_refuse_rate_max,
                "reviewer": a.reviewer,
                "basis": a.basis,
            },
            target=target,
        )
    except ValueError as exc:
        print(f"REJECT：{exc}")
        return 2
    except svc.ThresholdLockBusy as exc:
        print(f"REJECT：{exc}")
        return 2
    print(f"OK：{anchor} 已写入（核定人 {a.reviewer}，依据 {a.basis}）"
          f"{'，内容未变化' if not res['changed'] else ''}")

    # 写后自检：刷新缓存并列出剩余未核定子类（按 regulatory 口径）
    try:
        from app.services import standards

        standards.load_standards(force=True)
        missing = standards.missing_threshold_items()
        print("剩余未核定子类：" + (", ".join(missing) if missing else "无（可出交付件）"))
    except Exception as exc:  # noqa: BLE001
        print(f"自检跳过（服务层不可用）：{exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
