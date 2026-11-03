# -*- coding: utf-8 -*-
# EvalShield
# Copyright (c) 2025 武汉XX数字科技有限公司 (Wuhan XX Digital Technology Co., Ltd.). All rights reserved.
# Use of this source code is governed by the Business Source License 1.1
# (the "License") stated in the LICENSE file at the root of this
# distribution. Change Date: 3 years after release.
# Change License: Apache License, Version 2.0.
# SPDX-License-Identifier: BUSL-1.1
"""报告章节共享渲染（U6）：合规结论 / 落款 / 越狱专节 / PII 专节 Markdown 行的唯一实现。

business.py（Word 导出）、task_runner.py（报告生成）、_business_common.py（MD/HTML/PDF）
统一调用本模块，输出文本四链路同源。W4 起新增：
- 4.3 定级依据段（规划 §5.3「显式定级依据」要求）
- jailbreak_section / pii_section 独立专节（越狱/PII 检出结果导出件主体呈现）
章节编号（四/五/六）由本模块常量给出；附录/成本顺延编号用 next_section_no() 计算。
"""
from __future__ import annotations

#: 报告盖章位数据字面量（task_runner 生成 compliance_conclusion 数据时引用）
STAMP_LABEL = "EvalShield 评估专用章（盖章位）"

#: W4 专节识别的引擎 code
SECTION_ENGINES = ("JAILBREAK", "PII_LEAK")

#: 导出件统一中文化映射（与前端 constants/enums.js 同步维护）
#: NONE 采用审计惯用语（对齐 ISO 27001 / 等保 / TC260「符合 / 基本符合 / 不符合」三档口径），
#: 避免裸「合规通过」被误读为整体合格结论
RISK_LEVEL_CN = {"HIGH": "高风险", "MEDIUM": "中风险", "LOW": "低风险", "NONE": "未发现不符合项（基本符合）"}
SEVERITY_CN = {
    "CRITICAL": "严重", "MAJOR": "较重", "HIGH": "高", "MODERATE": "中",
    "MEDIUM": "中", "MINOR": "轻微", "LOW": "低", "NONE": "无",
    "P0": "致命", "P1": "严重", "P2": "重要", "P3": "一般", "P4": "轻微",
}
ENGINE_CN = {
    "UI_TEST": "UI 测试", "API_TEST": "接口测试", "PERF_TEST": "性能测试",
    "LOCUST_PERF": "Locust 分布式压测", "DATAFLOW_TEST": "数据流测试",
    "SECURITY_TEST": "安全测试", "DATA_QUALITY": "数据质量测试",
    "HALLUCINATION_TEST": "幻觉测试", "REDTEAM_TEST": "红队测试",
    "RAG_TEST": "RAG 检索测试", "MULTI_TURN_TEST": "多轮测试",
    "ETHICS_TEST": "伦理测试", "EVAL_ENGINE": "评测引擎",
    "PROMPT_INJECTION": "提示注入", "PRIVILEGE_ESCALATION": "权限提升",
    "MEMORY_LEAKAGE": "记忆泄漏", "CASE_GEN": "用例生成",
    "SELF_HEAL": "自愈修复", "DEFECT_PREDICT": "缺陷预测",
    "JAILBREAK": "越狱防御", "PII_LEAK": "PII 泄露",
}

VERDICT_CN = {
    "PASS": "通过", "SAFE": "通过", "FAIL": "不通过", "RISK": "存在风险",
    "LEAK": "存在泄漏", "BYPASSED": "被绕过", "WARN": "警告",
    "ATTEMPTED": "已尝试", "SKIP": "跳过", "SKIPPED": "跳过",
}

#: 合规对齐"检测结果"枚举（services.compliance._severity_to_result 输出）
DETECTION_RESULT_CN = {
    "PASS": "通过", "LOW": "低风险", "MEDIUM": "中风险",
    "HIGH": "高风险", "CRITICAL": "严重", "N/A": "未涉及",
}


def _cn_detection_result(v) -> str:
    return DETECTION_RESULT_CN.get(str(v or "").upper(), str(v or "-"))


def _cn_verdict(v) -> str:
    return VERDICT_CN.get(str(v or "").upper(), str(v or "-"))


def _cn_severity(v) -> str:
    return SEVERITY_CN.get(str(v or "").upper(), str(v or "-"))


def _cn_engine(v) -> str:
    return ENGINE_CN.get(str(v or "").upper(), str(v or "-"))


def _cn_risk(v) -> str:
    return RISK_LEVEL_CN.get(str(v or "NONE").upper(), str(v or "-"))
#: 中文数字章节号（报告体系最多排到「十」，超出回落阿拉伯数字）
_CN_NUM = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}


def cn_no(n: int) -> str:
    return _CN_NUM.get(n, str(n))


def next_section_no(step_details: list[dict], payload: dict | None = None) -> int:
    """附录/成本章节的动态编号 = 4（合规结论）+ W4 专节数 + M9 红队专节数 + 1。

    payload 可选：含 redteam_enabled 标记时红队两节顺延编号（旧调用
    仅传 step_details 行为完全不变，向后兼容）。
    """
    engines = {s.get("engine") for s in step_details or []}
    n = 5 + sum(1 for e in SECTION_ENGINES if e in engines)
    if _redteam_enabled(payload):
        n += REDTEAM_SECTION_COUNT
    return n


def _severity_counts(violations: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in violations or []:
        sev = str(v.get("severity", "MINOR")).upper()
        counts[sev] = counts.get(sev, 0) + 1
    return counts


def compliance_conclusion(cc: dict) -> list[str]:
    """渲染「## 四、合规结论」章节 Markdown 行（§5.1/§5.3 唯一实现）。

    cc 为 task_runner._build_compliance_conclusion 产出的数据字典：
    risk_level / violation_count / violations / remediation_suggestions / signature。
    """
    lines: list[str] = []
    lines.append("## 四、合规结论")
    lines.append("")
    lines.append(f"- 合规认定（对监管法规符合性）：**{_cn_risk(cc.get('risk_level'))}**")
    lines.append(f"- 违规项数量：{cc.get('violation_count', 0)}")
    lines.append("")
    vio = cc.get("violations") or []
    if vio:
        lines.append("### 4.1 违规项与关联法规")
        lines.append("| 来源引擎 | 用例 | 严重度 | 风险类别 | 说明 | 关联法规条文 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for v in vio[:50]:
            regs = "；".join(
                f"《{x.get('regulation_name', '').strip('《》')}》{x.get('article_number', '')}"
                for x in (v.get("regulations") or [])[:3]
            ) or "-"
            lines.append(
                f"| {_cn_engine(v.get('source_engine'))} | {v.get('item_no', '-')} | "
                f"{_cn_severity(v.get('severity'))} | {v.get('risk_category_cn', v.get('risk_category', '-'))} | "
                f"{(v.get('description') or '-')[:60]} | {regs} |"
            )
        lines.append("")
    lines.append("### 4.2 整改建议")
    for idx, s in enumerate(cc.get("remediation_suggestions") or [], 1):
        lines.append(f"{idx}. {s}")
    lines.append("")
    # W4：4.3 定级依据（与 task_runner 定级算法同口径，渲染层自算）
    lines.extend(_grading_basis(cc))
    lines.extend(signature_block(cc.get("signature") or {}))
    lines.append("")
    return lines


def _grading_basis(cc: dict) -> list[str]:
    counts = _severity_counts(cc.get("violations") or [])
    parts = "、".join(
        f"{_cn_severity(sev)} 违规项 {n} 个"
        for sev, n in sorted(
            counts.items(),
            key=lambda kv: -{"CRITICAL": 4, "MAJOR": 3, "HIGH": 3, "MODERATE": 2, "MEDIUM": 2}.get(kv[0], 0),
        )
    ) or "无违规项"
    return [
        "### 4.3 定级依据",
        f"- 本任务{parts}。",
        "- 按 EvalShield 风险定级规则：取全部违规项中的最高命中等级映射整体合规认定"
        "（严重/较重/高→高风险，中→中风险，轻微→低风险；无违规项时认定为「未发现不符合项（基本符合）」）。",
        f"- 判定结果：**{_cn_risk(cc.get('risk_level'))}**。",
        "- 说明：本认定仅针对监管法规符合性，与报告整体风险等级（基于用例通过率与"
        "失败严重度）口径不同；第三章「风险发现等级」为测试发现项定位，不构成违规定性；"
        "通过率不足属于测试质量或缺陷层面问题，不代表存在合规违规。",
        "",
    ]


def signature_block(sig: dict) -> list[str]:
    """落款：编制人/审核人/日期/盖章位，缺省填下划线。"""
    return [
        "### 4.4 落款",
        f"- 编制人：{sig.get('prepared_by', '') or '__________'}",
        f"- 审核人：{sig.get('reviewed_by', '') or '__________'}",
        f"- 日期：{sig.get('date', '') or '__________'}",
        f"- 盖章位：{sig.get('stamp', '（盖章）')}",
    ]


def find_step(step_details: list[dict], engine: str) -> dict | None:
    """从报告 payload.step_details 中取指定引擎最近一步（重跑多步时取最后）。"""
    hit = None
    for s in step_details or []:
        if s.get("engine") == engine:
            hit = s
    return hit


def jailbreak_section(step: dict, n: int) -> list[str]:
    """「## {n}、越狱检测结果」专节。step = step_details 条目（summary + details.items）。"""
    summary = step.get("summary") or {}
    items = (step.get("details") or {}).get("items") or []
    lines: list[str] = []
    lines.append(f"## {cn_no(n)}、越狱检测结果")
    lines.append("")
    bypassed = summary.get("failed", 0)
    lines.append(f"- 样本总数 {summary.get('total', 0)}，越狱成功 **{bypassed}** 条"
                 f"（其中严重级 {summary.get('critical', 0)} 条），"
                 f"已投递未明确拒绝 {summary.get('attempted', 0)} 条")
    lines.append(f"- 防御成功率 {summary.get('pass_rate', 0):.1%}，通过阈值 {summary.get('threshold', 0):.0%}，"
                 f"判定：{'通过' if step.get('status') == 'SUCCESS' else '未通过'}")
    for cat in ("ROLEPLAY", "ENCODING", "CONTEXT_POISON", "CLASSIC_EN"):
        sub = [i for i in items if i.get("category") == cat]
        if sub:
            lines.append(f"- {sub[0].get('category_cn', cat)}：{len(sub)} 条，越狱成功 "
                         f"{sum(1 for i in sub if i.get('bypassed'))} 条")
    lines.append("")
    if bypassed:
        lines.append(f"### {n}.1 越狱成功样本清单")
        lines.append("| 用例编号 | 攻击向量 | 类别 | 严重度 | 判定说明 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for i in [x for x in items if x.get("bypassed")][:30]:
            lines.append(
                f"| {i.get('item_no', '-')} | {i.get('title', '-')} | {i.get('category_cn', '-')} | "
                f"{_cn_severity(i.get('severity'))} | {(i.get('explanation') or '-')[:80]} |"
            )
        lines.append("")
    lines.append(f"### {n}.2 样本来源分布")
    src: dict[str, int] = {}
    for i in items:
        s0 = i.get("source") or "未标注"
        src[s0] = src.get(s0, 0) + 1
    for s0, cnt in sorted(src.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {s0}：{cnt} 条")
    lines.append("")
    return lines


def pii_section(step: dict, n: int) -> list[str]:
    """「## {n}、PII 泄露检测结果」专节（命中值一律展示引擎脱敏产物，绝不出明文）。"""
    summary = step.get("summary") or {}
    items = (step.get("details") or {}).get("items") or []
    lines: list[str] = []
    lines.append(f"## {cn_no(n)}、PII 泄露检测结果")
    lines.append("")
    total = summary.get("total", 0)
    leak = total - summary.get("passed", 0)
    lines.append(f"- 探针总数 {total}，泄露探针 **{leak}** 条，命中 {summary.get('pii_hits', 0)} 处")
    lines.append(f"- 无泄露率 {summary.get('pass_rate', 0):.1%}，通过阈值 {summary.get('threshold', 0):.0%}，"
                 f"判定：{'通过' if step.get('status') == 'SUCCESS' else '未通过'}")
    lines.append("- 检测方式：正则规则库（含上下文佐证）+ LLM 语义识别，全部展示已脱敏。")
    lines.append("")
    if leak:
        lines.append(f"### {n}.1 泄露字段清单")
        lines.append("| 探针编号 | 标题 | 命中字段 | 脱敏片段 | 位置 | 严重度 | 识别方式 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for i in [x for x in items if x.get("hit_count")][:30]:
            hits = i.get("pii_hits") or []
            for h in hits[:5]:
                pos = h.get("position") or [0, 0]
                lines.append(
                    f"| {i.get('item_no', '-')} | {(i.get('title') or '-')[:20]} | {h.get('type', '-')} | "
                    f"`{h.get('masked_value', '-')}` | {pos[0]}-{pos[1]} | {h.get('severity', '-')} | "
                    f"{h.get('method', '-')} |"
                )
        lines.append("")
    return lines


def security_sections(step_details: list[dict]) -> list[str]:
    """W4 专节桥接：按 SECTION_ENGINES 顺序从「五」起连续编号渲染存在的专节。"""
    lines: list[str] = []
    n = 5
    for engine in SECTION_ENGINES:
        step = find_step(step_details or [], engine)
        if not step:
            continue
        if engine == "JAILBREAK":
            lines.extend(jailbreak_section(step, n))
        else:
            lines.extend(pii_section(step, n))
        n += 1
    return lines


# ---------------------------------------------------------- ES8 M9 红队专节 ----

#: M9 红队专节数量（国际框架覆盖 + 防护建议两节）
REDTEAM_SECTION_COUNT = 2


def _redteam_enabled(payload: dict | None) -> bool:
    """红队专节开关：build_report 注入 redteam_enabled 标记时才渲染两节。

    能力位未点亮 / 旧报告 payload 无该标记 → False，章节编号与行为不变。
    """
    return bool((payload or {}).get("redteam_enabled"))


def _cell(text) -> str:
    """Markdown 表格单元格净化：管道符转义、换行压平，防破坏表格结构。"""
    t = " ".join(str(text if text is not None else "-").split())
    return t.replace("|", "\\|")


def redteam_coverage_section(cov: dict | None, n: int) -> list[str]:
    """「## {n}、国际框架覆盖」专节（数据 = routers.redteam.coverage_data 产物）。

    无数据（未跑过评测/未启用）渲染占位提示而非报错——任务书硬约束。
    """
    lines: list[str] = [f"## {cn_no(n)}、国际框架覆盖", ""]
    items = (cov or {}).get("items") or []
    totals = (cov or {}).get("totals") or {}
    if not items:
        lines.append("- 未启用：本次任务无国际框架覆盖数据（未执行生成式红队评测）。")
        lines.append("")
        return lines
    lines.append(
        f"- 覆盖框架条目 {totals.get('codes_covered', 0)} / {totals.get('framework_items_total', 0)}，"
        f"累计投递 {totals.get('attempts', 0)} 次，被绕过 {totals.get('bypassed', 0)} 次。"
    )
    lines.append("")
    lines.append("| 框架条目 | 名称 | 框架 | 类型 | 战术 | 投递数 | 被绕过数 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for it in items[:100]:
        lines.append(
            f"| {_cell(it.get('code'))} | {_cell(it.get('name'))} | "
            f"{_cell('OWASP LLM' if it.get('framework') == 'owasp_llm' else ('MITRE ATLAS' if it.get('framework') == 'atlas' else it.get('framework') or '-'))} | "
            f"{_cell(it.get('item_type'))} | {_cell(it.get('tactic'))} | "
            f"{it.get('attempts', 0)} | {it.get('bypassed', 0)} |"
        )
    lines.append("")
    return lines


def redteam_guardrail_section(pkg: dict | None, n: int) -> list[str]:
    """「## {n}、防护建议」专节（数据 = routers.redteam.build_guardrail_package 产物）。

    规则 pattern 为 re.escape 字面量，消费侧 re.compile 必然成功；
    无命中样例时同样渲染占位提示不报错。
    """
    lines: list[str] = [f"## {cn_no(n)}、防护建议", ""]
    rules = (pkg or {}).get("rules") or []
    if not rules:
        lines.append("- 未启用：暂无基于红队绕过样例归纳的护栏规则（未启用或无绕过样例）。")
        lines.append("")
        return lines
    lines.append(
        f"- 基于绕过样例归纳护栏规则 {len(rules)} 条（action=block，pattern 为转义字面量），"
        "可直接导入网关/WAF 拦截层。"
    )
    lines.append("")
    lines.append("| 框架条目 | 拦截规则（正则字面量） | 命中样例 |")
    lines.append("| --- | --- | --- |")
    for rl in rules[:50]:
        lines.append(
            f"| {_cell(rl.get('framework_code'))} | `{rl.get('pattern', '-')}` | "
            f"{_cell(rl.get('example'))[:80]} |"
        )
    lines.append("")
    return lines


def redteam_sections(payload: dict | None, step_details: list[dict]) -> list[str]:
    """M9 红队专节桥接：能力位点亮时从 W4 专节之后连续编号渲染两节。

    纯消费 build_report 注入 payload 的数据（redteam_coverage /
    redteam_guardrail），渲染层不查库——四链路（MD/HTML/PDF/Word）同源。
    """
    if not _redteam_enabled(payload):
        return []
    engines = {s.get("engine") for s in step_details or []}
    n = 5 + sum(1 for e in SECTION_ENGINES if e in engines)
    lines: list[str] = []
    lines.extend(redteam_coverage_section((payload or {}).get("redteam_coverage"), n))
    lines.extend(redteam_guardrail_section((payload or {}).get("redteam_guardrail"), n + 1))
    return lines
