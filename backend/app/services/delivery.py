# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""ES9-P-11：交付四件套生成链（设计方案 §4.3.2）。

POST /api/reports/{run_id}/delivery-package 一键产出：
1. 技术支撑报告.pdf —— 标准对照章节（类别→题库类别→用例数→实测结论→证据编号）
   + 三集指标表 + 裁判信息页脚 + 结论限定语区块；
2. 证据链包.zip —— items.csv 明细（csv_guard 防公式注入）+ manifest + 链签名；
3. 整改建议清单.csv —— FAIL 条目按类别聚合；
4. 复测点列表.md —— 按 category 复测清单模板。

每件计算 sha256 入 delivery_packages.items。
合规门禁：standards.assert_thresholds_configured()——阈值未配置（tc260.yaml
留 null）一律 422 阻断，防文档口径冒充监管口径；代码内 0 题量/百分比字面量。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import zipfile
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..errors import BizError
from ..models import DeliveryPackage, EvalRun, EvalRunItem
from . import standards

logger = logging.getLogger(__name__)

# 四件套逻辑名（§4.3.2 原文文件名）
KINDS: dict[str, str] = {
    "pdf": "技术支撑报告.pdf",
    "zip": "证据链包.zip",
    "csv": "整改建议清单.csv",
    "md": "复测点列表.md",
}

# CSV 公式注入防护（csv_guard）：单元格以这些字符开头时前缀单引号
_CSV_UNSAFE = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(v: Any) -> str:
    s = "" if v is None else str(v)
    if s and s[0] in _CSV_UNSAFE:
        s = "'" + s
    return s


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _package_dir(package_no: str) -> str:
    d = os.path.join(settings.REPORT_DIR, settings.DELIVERY_DIR_NAME, package_no)
    os.makedirs(d, exist_ok=True)
    return d


# ------------------------------------------------------------------ 数据聚合


def collect_run_data(db: Session, run: EvalRun) -> dict[str, Any]:
    """run + items + 标准对照行组装（PDF/ZIP/CSV/MD 共用底稿）。

    优化12 §9.1：聚合键扩展 by_dimension/by_sub（自 coverage 派生，不重算）；
    coverage 为唯一判定事实源（旧口径 run → None → 下游走现行 6 类别分支，
    双口径共存、历史包可复现——铁律 7）。auth 缺省（门禁语义）：coverage
    内部以 run.tenant_id 过滤引擎轨。
    """
    from . import dimension_coverage

    items = (
        db.query(EvalRunItem)
        .filter(EvalRunItem.run_id == run.id)
        .order_by(EvalRunItem.seq)
        .all()
    )
    by_cat: dict[str, dict[str, Any]] = {}
    for it in items:
        row = by_cat.setdefault(
            it.category or "未分类",
            {"total": 0, "pass": 0, "fail": 0, "evidence_ids": []},
        )
        row["total"] += 1
        if it.final_verdict == "PASS":
            row["pass"] += 1
        if it.final_verdict == "FAIL":
            row["fail"] += 1
            if len(row["evidence_ids"]) < 20:  # 证据编号列表截断，防报告爆炸
                row["evidence_ids"].append(int(it.id))
    coverage = dimension_coverage.coverage_matrix(db, run)
    by_dimension = dimension_coverage.summary_rows(coverage) if coverage else []
    by_sub = [
        dict(s, dimension_code=d["dimension_code"],
             dimension_name=d["dimension_name"])
        for d in (coverage or {}).get("dimensions") or []
        for s in d["subs"]
    ]
    return {
        "run": run,
        "items": items,
        "by_cat": by_cat,
        "by_dimension": by_dimension,
        "by_sub": by_sub,
        "coverage": coverage,
        "summary": dict(run.summary or {}),
        "snapshot": dict(run.run_snapshot or {}),
        "mapping": standards.mapping_rows(),
        "statement": standards.statement_of("delivery_qualifier"),
    }


# ------------------------------------------------------------- 1. 技术报告 PDF


def _pct(v: Any) -> str:
    try:
        return f"{float(v) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def _cov_pct(v: Any) -> str:
    """coverage 数字展示（表中数字一律由 coverage 提供，报告层不做二次计算，§9.2）。"""
    return _pct(v) if v is not None else "-"


def _status_label(v: Any) -> str:
    return {
        "PASS": "通过", "WARN": "警告", "BLOCK": "未达标",
        "NOT_CONFIGURED": "阈值未核定", "N/A": "不计符合性",
    }.get(str(v or ""), str(v or "-"))


def _build_standard_section(data: dict[str, Any], lines: list[str]) -> None:
    """§9.2：coverage 非空时的"一、标准对照（GBT45654-2025 五维度）"五小节。"""
    cov = data["coverage"]
    meta = standards.standard_meta()
    lines.append("## 一、标准对照（GBT45654-2025 五维度）")
    lines.append("")
    lines.append(f"对照标准：{meta.get('name') or '-'}"
                 f"（{meta.get('code') or '-'} {cov.get('standards_ver') or meta.get('version') or '-'}）")
    lines.append("")
    # 1.1 五维度得分总表
    lines.append("### 1.1 五维度得分总表")
    lines.append("")
    lines.append("| 维度 | 子类数 | 实测题量 | 加权合格率 | 阈值 | 结论 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for d in cov["dimensions"]:
        thr = "—" if not d["regulatory"] else "按子类核定"
        lines.append(
            f"| {d['dimension_code']} {d['dimension_name']} | {len(d['subs'])} | "
            f"{d['dimension_tested']} | {_cov_pct(d['dimension_rate'])} | {thr} | "
            f"{_status_label(d['dimension_status'])} |")
    lines.append("")
    # 1.2 子类明细表（证据编号：by_cat 按题库类别反查，明细事实仍是 items 链）
    lines.append("### 1.2 子类明细表")
    lines.append("")
    lines.append("| 子类 | 题库类别 | 服务类型 | 题量(实测/核定) | 合格率 | 阈值 | 结论 | 证据编号 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for d in cov["dimensions"]:
        for s in d["subs"]:
            agg = data["by_cat"].get(s["bank_category"])
            evid = ", ".join(f"E{str(i).zfill(6)}"
                             for i in (agg["evidence_ids"][:5] if agg else []))
            lines.append(
                f"| {s['sub_code']} | {s['bank_category']} | {s['service_type'] or '-'} | "
                f"{s['tested']}/{s['min_questions'] if s['min_questions'] is not None else '未核定'} | "
                f"{_cov_pct(s['rate'])} | {_cov_pct(s['pass_threshold'])} | "
                f"{_status_label(s['status'])} | {evid or '-'} |")
    lines.append("")
    # 1.3 引擎级覆盖（要求 vs 执行）——"要求"二字为表头硬约束（§9.1 末条）
    lines.append("### 1.3 引擎级覆盖（要求 vs 执行）")
    lines.append("")
    lines.append("| 子类 | 要求引擎 | 本活动执行状态 | 运行编号 | 结论 | fidelity |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for d in cov["dimensions"]:
        for s in d["subs"]:
            if not s["engines"]:
                continue
            for e in s["engines"]:
                lines.append(
                    f"| {s['sub_code']} | {e['code']} | {e['state']} | "
                    f"{e.get('run_no') or '-'} | "
                    f"{'已执行' if e['state'] == 'EXECUTED' else '本活动未执行'} | "
                    f"{e.get('fidelity') or '-'} |")
    lines.append("")
    lines.append(f"> 口径说明：{cov.get('disclaimer') or ''}")
    lines.append("")
    # 1.4 拒答双指标（§5.2d）——阈值 null 只展示不判定
    lines.append("### 1.4 拒答双指标")
    lines.append("")
    r = cov.get("refusal") or {}
    thr = r.get("thresholds") or {}
    lines.append("| 指标 | 数值 | 核定阈值 |")
    lines.append("| --- | --- | --- |")
    lines.append(f"| 拒答合格率（REFUSE） | {_cov_pct(r.get('refuse_pass_rate'))} | "
                 + (f"≥ {_cov_pct(thr.get('refuse_pass_rate_min'))}"
                    if thr.get("refuse_pass_rate_min") is not None
                    else "待核定（不判定符合性）") + " |")
    lines.append(f"| 误拒率（ANSWER） | {_cov_pct(r.get('answer_false_refuse_rate'))} | "
                 + (f"≤ {_cov_pct(thr.get('false_refuse_rate_max'))}"
                    if thr.get("false_refuse_rate_max") is not None
                    else "待核定（不判定符合性）") + " |")
    lines.append(f"| 攻击成功率 ASR（ATTACK） | {_cov_pct(r.get('attack_success_rate'))} | - |")
    lines.append("")
    # 1.5 扩展视角（不参与符合性表述）
    ext = [d for d in cov["dimensions"] if not d["regulatory"]]
    if ext:
        lines.append("### 1.5 扩展视角（对抗 / 质量，不参与符合性表述）")
        lines.append("")
        lines.append("| 维度 | 子类 | 实测题量 | 加权合格率 |")
        lines.append("| --- | --- | --- | --- |")
        for d in ext:
            lines.append(f"| {d['dimension_code']} {d['dimension_name']} | {len(d['subs'])} | "
                         f"{d['dimension_tested']} | {_cov_pct(d['dimension_rate'])} |")
        lines.append("")
    ov = cov.get("overall") or {}
    lines.append(f"官方五维度符合性初判：{'通过' if ov.get('official_pass') else '未通过（存在题量/合格率缺口）'}"
                 "（以门禁 G4 与复核结论为准）")
    lines.append("")


def build_report_md(data: dict[str, Any]) -> str:
    run: EvalRun = data["run"]
    s = data["summary"]
    snap = data["snapshot"]
    meta = standards.standard_meta()
    lines: list[str] = []
    lines.append(f"# EvalShield 技术支撑报告")
    lines.append("")
    lines.append(f"- 运行编号：{run.run_no}")
    lines.append(f"- 被测目标：{run.target_id}（{run.target_type}）")
    lines.append(f"- 题库：{s.get('bank_name') or '-'}（{s.get('bank_code') or '-'}）")
    lines.append(f"- 抽样：{s.get('sampled') or 0} 题 / 请求 {s.get('requested_sample_size') or 0}，seed={s.get('sample_seed')}")
    lines.append(f"- 生成时间：{datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    if data.get("coverage"):
        # 优化12 §9.2：新口径两级章节；coverage 空（旧口径 run）→ 现行单表不改
        _build_standard_section(data, lines)
    else:
        lines.append("## 一、标准对照")
        lines.append("")
        lines.append(f"对照标准：{meta.get('name') or '-'}（{meta.get('code') or '-'} {meta.get('version') or '-'}）")
        lines.append("")
        lines.append("| 类别 | 题库类别 | 用例数 | 实测结论 | 证据编号 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for row in data["mapping"]:
            cat = row["bank_category"]
            agg = data["by_cat"].get(cat)
            n = agg["total"] if agg else 0
            evid = ", ".join(f"E{str(i).zfill(6)}" for i in (agg["evidence_ids"][:5] if agg else []))
            if n == 0:
                verdict = "无样本"
            else:
                rate = agg["pass"] / n
                verdict = "通过" if rate >= row["pass_threshold"] else "未通过"
                verdict += f"（通过率 {_pct(rate)} / 阈值 {_pct(row['pass_threshold'])}）"
            lines.append(f"| {row['category_code']} | {cat} | {n} | {verdict} | {evid or '-'} |")
        lines.append("")
    lines.append("## 二、三集指标")
    lines.append("")
    lines.append("| 指标 | 数值 | 样本数 |")
    lines.append("| --- | --- | --- |")
    for label, key, rk in (
        ("拒答合格率（REFUSE 集）", "refuse_pass_rate", "qualified_rate"),
        ("非答误拒率（ANSWER 集）", "answer_false_refuse_rate", "false_refuse_rate"),
        ("攻击成功率 ASR（ATTACK 集）", "attack_success_rate", "asr"),
    ):
        m = s.get(key) or {}
        lines.append(f"| {label} | {_pct(m.get(rk))} | {m.get('total') or 0} |")
    lines.append(
        f"| 双轨一致率 | {_pct(s.get('judge_agreement_rate'))} | "
        f"{s.get('judge_agreement_sampled') or 0} |"
    )
    lines.append("")
    if s.get("needs_review"):
        lines.append(f"> 注意：一致率低于阈值（{s.get('agreement_threshold')}），"
                     "本报告全部判定条目已进入人工复核队列，结论以复核后为准。")
        lines.append("")
    lines.append("## 三、结论限定语")
    lines.append("")
    lines.append(data["statement"] or "（限定语文案未配置）")
    lines.append("")
    lines.append("---")
    lines.append(f"裁判模型：{snap.get('judge_model') or 'RULE-ONLY'}｜"
                 f"judge_prompt v{snap.get('judge_prompt_version')}｜"
                 f"hash {snap.get('judge_prompt_hash') or '-'}｜"
                 f"sample_seed {snap.get('sample_seed')}｜"
                 f"被测模式 {snap.get('target_mode') or '-'}")
    return "\n".join(lines)


def render_report_pdf(md_text: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as pdf_canvas

    from .export_helpers import detect_cjk_font, pdf_text

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    font = detect_cjk_font()
    w, h = A4
    y = h - 60
    for line in md_text.splitlines():
        if y < 60:
            c.showPage()
            y = h - 60
        y = pdf_text(c, font, line, y, w)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


# ------------------------------------------------------------- 2. 证据链包 ZIP


def build_evidence_zip(data: dict[str, Any], delivery_meta: dict[str, Any] | None = None) -> bytes:
    run: EvalRun = data["run"]
    cov = data.get("coverage")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # items.csv 明细（csv_guard 转义）
        # 优化12 §9.3：新口径 run 增 dimension_code/sub_code 两列（category 反查 yaml）；
        # 旧口径 run 保持原列结构（铁律 7：不改写历史）
        cat_map = standards.category_map() if cov else {}
        csv_buf = io.StringIO()
        wr = csv.writer(csv_buf)
        head = [
            "证据编号", "run_id", "question_id", "split", "category",
        ]
        if cov:
            head += ["dimension_code", "sub_code"]
        head += [
            "题面", "被测回答", "规则轨", "裁判轨", "终判", "判定理由", "延迟ms",
            "失败类别",
        ]
        wr.writerow(head)
        for it in data["items"]:
            row = [
                f"E{str(int(it.id)).zfill(6)}", int(run.id),
                it.question_id, it.split, it.category,
            ]
            if cov:
                m = cat_map.get(it.category or "") or {}
                row += [m.get("dimension_code") or "", m.get("category_code") or ""]
            row += [
                _csv_cell((it.prompt or "")[:500]),
                _csv_cell((it.response or "")[:2000]),
                it.rule_verdict, it.judge_verdict, it.final_verdict,
                _csv_cell(it.verdict_reason), it.latency_ms,
                (it.evidence_payload or {}).get("failure_class") or "",
            ]
            wr.writerow(row)
        zf.writestr("items.csv", csv_buf.getvalue().encode("utf-8-sig"))
        # 链签名
        payload = {
            "run_no": run.run_no,
            "run_id": int(run.id),
            "summary_sha256": _sha256(
                json.dumps(run.summary or {}, sort_keys=True, ensure_ascii=False).encode()
            ),
            "run_snapshot": run.run_snapshot or {},
            "item_count": len(data["items"]),
            "packaged_at": datetime.now(timezone.utc).isoformat(),
        }
        zf.writestr("chain_signature.json", json.dumps(payload, ensure_ascii=False, indent=2))
        manifest = {
            "manifest_version": "1.2" if cov else "1.1",
            "run_no": run.run_no,
            "files": [
                {"name": "items.csv", "desc": "逐题证据明细（证据编号=eval_run_items.id）"},
                {"name": "chain_signature.json", "desc": "链签名（summary hash + 快照）"},
            ],
        }
        # ES11 §3.6：正式包 manifest 扩展（缺陷验证/复核/Judge 健康/风险接受摘要）
        if delivery_meta:
            if cov:
                # 优化12 §9.3：总表行摘要 + 引擎级三态 + disclaimer（不含全量明细）
                delivery_meta = {
                    **delivery_meta,
                    "dimension_coverage": {
                        "standards_ver": cov.get("standards_ver"),
                        "disclaimer": cov.get("disclaimer"),
                        "summary_rows": data.get("by_dimension") or [],
                        "engine_states": [
                            {"sub_code": s["sub_code"], "code": e["code"], "state": e["state"]}
                            for d in cov["dimensions"] for s in d["subs"] for e in s["engines"]
                        ],
                    },
                    "refusal_metrics": cov.get("refusal"),
                }
            manifest["delivery_meta"] = delivery_meta
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    buf.seek(0)
    return buf.read()


# --------------------------------------------------------- 3. 整改建议清单 CSV


def build_remediation_csv(data: dict[str, Any]) -> bytes:
    buf = io.StringIO()
    wr = csv.writer(buf)
    cov = data.get("coverage")
    cat_map = standards.category_map()
    if cov:
        # 优化12 §9.3：新口径七列（维度/子类编码前置）
        wr.writerow(["维度编码", "子类编码", "题库类别", "未通过数",
                     "样本示例", "整改建议", "复测标准"])
    else:
        wr.writerow(["类别", "未通过数", "样本示例", "整改建议", "复测标准"])
    for cat, agg in sorted(data["by_cat"].items()):
        if not agg["fail"]:
            continue
        sample = next(
            (
                _csv_cell((it.prompt or "")[:120])
                for it in data["items"]
                if (it.category or "未分类") == cat and it.final_verdict == "FAIL"
            ),
            "",
        )
        row = cat_map.get(cat)
        advice = "针对该类别失败样本补充安全对齐/拒答策略后重跑同 seed 样本"
        if cov:
            dim_code = (row or {}).get("dimension_code") or ""
            sub_code = (row or {}).get("category_code") or ""
            if row and row.get("pass_threshold") is not None:
                # 核定留痕（§9.3）：通过率 ≥ X%（子类，核定 YYYY-MM-DD）
                traced = _threshold_trace(row)
                threshold_note = f"通过率 ≥ {_pct(row['pass_threshold'])}（{sub_code}{traced}）"
            else:
                threshold_note = "子类阈值未核定（不判定符合性）"
            wr.writerow([dim_code, sub_code, cat, agg["fail"], sample, advice, threshold_note])
            continue
        threshold_note = (
            f"{row['category_code']} 通过率阈值 {_pct(row['pass_threshold'])}"
            if row else "类别未配置标准阈值"
        )
        wr.writerow([cat, agg["fail"], sample, advice, threshold_note])
    return buf.getvalue().encode("utf-8-sig")


def _threshold_trace(row: dict[str, Any]) -> str:
    """核定留痕后缀（§9.3）：mapping 行若带核定日期则附 ", 核定 YYYY-MM-DD"。

    核定信息来自 yaml 阈值块 reviewed_by/basis（不内联日期字面量，无则省略）。
    """
    data = standards.load_standards()
    thr = data.get("thresholds_review") or data.get("review") or {}
    day = thr.get("reviewed_at") or thr.get("date")
    return f"，核定 {day}" if day else ""


# ----------------------------------------------------------- 4. 复测点列表 MD


def build_retest_md(data: dict[str, Any]) -> str:
    run: EvalRun = data["run"]
    cat_map = standards.category_map()
    cov = data.get("coverage")
    lines = [f"# 复测点列表（{run.run_no}）", ""]
    if cov:
        # 优化12 §9.3：新口径两级标题（## 维度 → ### 子类），判定标准行同 CSV 口径
        dim_by_code = {d["dimension_code"]: d["dimension_name"] for d in cov["dimensions"]}
        first_by_dim: dict[str, list[str]] = {}
        for cat, agg in sorted(data["by_cat"].items()):
            if not agg["fail"]:
                continue
            row = cat_map.get(cat) or {}
            dim_code = row.get("dimension_code") or "未归类"
            first_by_dim.setdefault(dim_code, []).append(cat)
        for dim_code in sorted(first_by_dim):
            lines.append(f"## {dim_by_code.get(dim_code) or dim_code}（{dim_code}）")
            lines.append("")
            for cat in first_by_dim[dim_code]:
                agg = data["by_cat"][cat]
                row = cat_map.get(cat) or {}
                lines.append(f"### {row.get('category_code') or '-'} {cat}")
                lines.append("")
                lines.append(f"- 未通过样本：{agg['fail']} / {agg['total']}")
                lines.append(f"- 证据编号：{', '.join(f'E{str(i).zfill(6)}' for i in agg['evidence_ids'][:10])} …")
                lines.append(f"- 复测要求：整改后以同一样题 seed（{data['snapshot'].get('sample_seed')}）"
                             f"重放执行链，对 `{run.target_id}` 复跑本子类全部样本")
                if row.get("pass_threshold") is not None:
                    traced = _threshold_trace(row)
                    lines.append(f"- 判定标准：通过率 ≥ {_pct(row['pass_threshold'])}"
                                 f"（{row.get('category_code')}{traced}）")
                else:
                    lines.append("- 判定标准：子类阈值未核定（不判定符合性）")
                lines.append("- [ ] 整改完成")
                lines.append("- [ ] 复测通过")
                lines.append("")
        if len(lines) == 3:
            lines.append("本次运行无未通过类别，暂无复测点。")
        return "\n".join(lines)
    for cat, agg in sorted(data["by_cat"].items()):
        if not agg["fail"]:
            continue
        row = cat_map.get(cat)
        lines.append(f"## {cat}")
        lines.append("")
        lines.append(f"- 未通过样本：{agg['fail']} / {agg['total']}")
        lines.append(f"- 证据编号：{', '.join(f'E{str(i).zfill(6)}' for i in agg['evidence_ids'][:10])} …")
        lines.append(f"- 复测要求：整改后以同一样题 seed（{data['snapshot'].get('sample_seed')}）"
                     f"重放执行链，对 `{run.target_id}` 复跑本类别全部样本")
        if row:
            lines.append(f"- 判定标准：通过率 ≥ {_pct(row['pass_threshold'])}（{row['category_code']}）")
        lines.append("- [ ] 整改完成" )
        lines.append("- [ ] 复测通过")
        lines.append("")
    if len(lines) == 2:
        lines.append("本次运行无未通过类别，暂无复测点。")
    return "\n".join(lines)


# ------------------------------------------------------------------ 生成主链


def generate_package(
    db: Session, run: EvalRun, created_by: int | None = None, *,
    deliverable: bool = True, delivery_meta: dict[str, Any] | None = None,
) -> DeliveryPackage:
    """四件套全量生成 → 落盘 + delivery_packages 台账。

    ES11 §3.6：G4 未通过（deliverable=False）只出带"草稿/未冻结"水印预览包
    （status=draft）；正式包 manifest 附 delivery_meta 扩展段。

    优化12 §9 开头：出包门禁感知 run——仅 STANDARD + 新口径 + strict=on 才硬阻断
    （ES-STD-003）；SCREENING / 旧口径 / strict=off 落入草稿分支并强制加注。
    """
    from . import dimension_coverage

    # 合规门禁（§9 改造）：阈值未配置直接 422（不产出任何交付件）——仅限
    # 新口径正式评估；SCREENING/旧口径/kill switch off 不抛，走草稿加注路径
    ver = dimension_coverage.resolve_effective_standards_ver(db, run)
    strict_on = settings.STANDARDS_STRICT_MODE != "off"
    new_caliber = dimension_coverage.is_new_caliber(ver)
    hard_block = (
        str(run.run_purpose or "STANDARD").upper() == "STANDARD"
        and new_caliber and strict_on
    )
    if hard_block:
        standards.assert_thresholds_configured()

    # 包号前缀与 _seq_no() 的 like 前缀是同一字面量（§9.5），改动必须两处同步
    package_no = f"ES9-DELIV-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{_seq_no(db, run)}"
    out_dir = _package_dir(package_no)
    data = collect_run_data(db, run)

    md_text = build_report_md(data)
    prefix = ""
    if not deliverable:
        prefix += (
            "> ⚠ 草稿/未冻结：本报告未通过交付门禁（G4），仅供预览，"
            "不得作为正式交付结论。\n\n"
        )
        if str(run.run_purpose or "").upper() == "SCREENING":
            # §8.6-3：SCREENING 恒草稿包，首页强制标注（硬编码文案，非开关）
            prefix += "> 抽样探查，不覆盖全部维度。\n\n"
    if not hard_block and new_caliber and standards.missing_threshold_items():
        # §8.5/§8.6：未核定但绕过硬阻断的（SCREENING/REGRESSION 旧基线/strict=off）强制加注
        prefix += "> 阈值未核定，本件仅供内部预览。\n\n"
    if prefix:
        md_text = prefix + md_text
    artifacts: dict[str, bytes] = {
        "pdf": render_report_pdf(md_text),
        "zip": build_evidence_zip(data, delivery_meta if deliverable else None),
        "csv": build_remediation_csv(data),
        "md": build_retest_md(data).encode("utf-8"),
    }
    items: list[dict[str, Any]] = []
    for kind, blob in artifacts.items():
        path = os.path.join(out_dir, KINDS[kind])
        with open(path, "wb") as f:
            f.write(blob)
        items.append(
            {"kind": kind, "file_path": path, "sha256": _sha256(blob), "size": len(blob)}
        )

    pkg = DeliveryPackage(
        tenant_id=run.tenant_id,
        run_id=int(run.id),
        package_no=package_no,
        items=items,
        standards_ver=standards.standards_version(),
        status="ready" if deliverable else "draft",
        created_by=created_by,
    )
    db.add(pkg)
    db.flush()
    return pkg


def _seq_no(db: Session, run: EvalRun) -> str:
    """当日包序号（001 起，按已存在台账计数；并发极端时可能重号由唯一索引兜底）。

    like 前缀与 generate_package 中 package_no 字面量同源（§9.5），改动必须两处同步。
    """
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    cnt = (
        db.query(DeliveryPackage)
        .filter(
            DeliveryPackage.tenant_id == (run.tenant_id or 0),
            DeliveryPackage.package_no.like(f"ES9-DELIV-{day}-%"),
        )
        .count()
    )
    return f"{cnt + 1:03d}"
