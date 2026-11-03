# SPDX-License-Identifier: BUSL-1.1
"""ES9 UAT 报告渲染（md/html/pdf/word）。零业务逻辑：输入 payload dict，输出 bytes/str。

渲染规则（设计方案 §4.1）：
- 签核栏：未签=横线空位；已签=姓名+时间；
- CONDITIONAL：§8 顶部显示 note（md 引用块 / html 引用样式随 md 转换）；
- DRAFT 导出强制水印「草稿 DRAFT」：PDF 对角水印 / Word 页眉 / HTML body class / MD 首行声明。
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

from .export_helpers import (
    docx_east_asia,
    docx_table_from_md,
    fmt_dt,
    md_to_html,
    now_cn,
    pdf_text,
)

_SECTION_TITLES = {
    "s1_overview": "§1 项目概况",
    "s2_scope": "§2 验收范围与依据",
    "s3_environment": "§3 验收环境指纹",
    "s4_results": "§4 执行结果汇总",
    "s5_gate": "§5 质量门禁结论",
    "s6_perf_security": "§6 性能与安全专项",
    "s7_defects": "§7 遗留缺陷与处置意见",
    "s8_conclusion": "§8 验收结论与签核",
}

_VERDICT_CN = {"PASSED": "通过", "CONDITIONAL": "有条件通过",
               "REJECTED": "不通过", "FAILED": "未达标"}
_WATERMARK = "草稿 DRAFT —— 未经双方签核，不作验收依据"
_RISK_CN = {"CRITICAL": "严重", "HIGH": "高", "MEDIUM": "中", "LOW": "低", "NONE": "无"}


def _sign_line(sig: dict | None) -> str:
    """签字栏渲染：None→横线；已签→姓名 + 时间。"""
    if not sig or not sig.get("name"):
        return "＿＿＿＿＿＿　　日期：＿＿＿＿＿＿"
    return f"{sig['name']}　　日期：{fmt_dt(sig.get('signed_at') or '')}"


def _pct(v: Any) -> str:
    try:
        return f"{float(v) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-" if v is None else str(v)


# ---------------------------------------------------------------------------
# Markdown（四格式共用的中间表示）
# ---------------------------------------------------------------------------
def render_uat_md(payload: dict, acceptance: dict, watermark: bool) -> str:
    """Markdown：8 节顺序渲染 + 尾注（哈希尾 8 位 + 版本链号）。"""
    lines: list[str] = []
    if watermark:
        lines += [f"> ⚠️ **{_WATERMARK}**", ""]
    s = payload["sections"]
    o = s["s1_overview"]
    lines += [f"# UAT 验收报告 {o.get('report_no', '')}",
              f"- 项目：{o.get('project_name', '-')}　生成时间：{fmt_dt(now_cn().isoformat())}　"
              f"版本：v{payload.get('uat_version') or 1}", ""]
    for key in _SECTION_TITLES:
        lines.append(f"## {_SECTION_TITLES[key]}")
        lines.append(_section_md(key, s.get(key, {}), acceptance))
        lines.append("")
    # 附录：审计轨迹摘要（操作计数等，只读留痕）
    aud = payload.get("audit_summary") or {}
    if aud:
        lines.append("## 附录 审计轨迹摘要")
        lines.append(_kv_block(aud))
        lines.append("")
    h = (payload.get("report_hash") or "").replace("sha256:", "")
    lines += ["---", f"报告哈希：sha256:{h[:8]}…（完整哈希见系统审计链）",
              "本报告经双方签核后进入不可变更状态，任何修订以新版本报告为准。"]
    return "\n".join(lines)


def _kv_block(data: Any) -> str:
    """dict → 「- **k**：v」列表行（嵌套值压平为字符串）。"""
    if not isinstance(data, dict):
        return str(data)
    out = []
    for k, v in data.items():
        if v in (None, "", [], {}):
            continue
        out.append(f"- **{k}**：{_flat(v)}")
    return "\n".join(out) if out else "无"


def _flat(v: Any) -> str:
    if isinstance(v, (dict, list)):
        return "；".join(str(x) for x in v) if v else "-"
    return str(v)


def _table(cols: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _section_md(key: str, data: Any, acc: dict) -> str:
    """各节 → Markdown 片段（字段以 §3.2 payload 为准）。"""
    if key == "s1_overview":
        return _kv_block({
            "报告编号": data.get("report_no"),
            "项目名称": data.get("project_name"),
            "纳入任务": "、".join(data.get("task_nos") or []) or "-",
        })
    if key == "s2_scope":
        rows = [[t.get("task_no"), t.get("title"), str(t.get("cases")),
                 _pct(t.get("pass_rate")), _VERDICT_CN.get(str(t.get("verdict")), "-")]
                for t in data.get("tasks") or []]
        crit = [[c.get("metric"), c.get("op"), str(c.get("threshold"))]
                for c in data.get("criteria") or []]
        parts = [f"- 合同编号：{data.get('contract_no') or '-'}",
                 f"- 标准来源：{'人工覆写' if data.get('criteria_source') == 'override' else '任务门禁规则合并'}",
                 "", "纳入任务：", _table(["任务编号", "任务名称", "用例数", "通过率", "门禁"], rows),
                 "", "验收标准：", _table(["指标", "操作符", "阈值"], crit)]
        return "\n".join(parts)
    if key == "s3_environment":
        return _kv_block({k: v for k, v in (data or {}).items() if k != "distinct_env_count"}) + \
            f"\n- **环境来源报告数**：{data.get('distinct_env_count', '-')}"
    if key == "s4_results":
        rows = [[t.get("task_no"), str(t.get("cases")), _pct(t.get("pass_rate")),
                 fmt_dt(t.get("started_at")), fmt_dt(t.get("finished_at"))]
                for t in data.get("per_task") or []]
        return _table(["任务编号", "用例数", "通过率", "开始", "结束"], rows) + \
            f"\n\n- **用例总数**：{data.get('total_cases', 0)}　**加权通过率**：{_pct(data.get('agg_pass_rate'))}"
    if key == "s5_gate":
        rows = ["| 指标 | 操作符 | 阈值 | 实际值 | 判定 |", "|---|---|---|---|---|"]
        for c in data.get("checks", []):
            rows.append(f"| {c['metric']} | {c['op']} | {c['threshold']} "
                        f"| {c.get('actual')} | {'✅ PASS' if c['passed'] else '❌ FAIL'} |")
        rows.append(f"\n**门禁总结论：{_VERDICT_CN.get(data.get('verdict'), data.get('verdict'))}**")
        return "\n".join(rows)
    if key == "s6_perf_security":
        perf = data.get("performance") or {}
        sec = data.get("security") or {}
        p_lines = ["| 指标 | 合并值（按用例数加权） |", "|---|---|"]
        for k in ("rt_p50", "rt_p95", "rt_p99", "tps", "error_rate"):
            p_lines.append(f"| {k} | {perf.get(k) if perf.get(k) is not None else '-'} |")
        lvl = sec.get("risk_level")
        s_lines = [f"- **风险等级**：{_RISK_CN.get(str(lvl).upper(), lvl or '-')}"]
        if sec.get("risk_basis"):
            s_lines.append("- **风险依据**：" + "；".join(str(b) for b in sec["risk_basis"]))
        return "\n".join(p_lines) + "\n\n" + "\n".join(s_lines)
    if key == "s7_defects":
        if not data:
            return "无遗留缺陷。"
        rows = [[d.get("defect_no"), (d.get("title") or "")[:60], d.get("severity"),
                 d.get("status"), (d.get("disposal") or {}).get("deadline", "-")
                 if isinstance(d.get("disposal"), dict) else (d.get("disposal") or "待处置")]
                for d in data]
        return _table(["缺陷编号", "标题", "严重度", "状态", "处置意见"], rows)
    if key == "s8_conclusion":
        v = acc.get("verdict") or (data or {}).get("verdict")
        out = [f"**验收结论：{_VERDICT_CN.get(str(v), v or '（待签核）')}**"]
        if acc.get("note"):
            out.append(f"> 豁免/附加说明：{acc['note']}")
        out.append(f"- 供应商代表：{_sign_line(acc.get('signer_vendor'))}")
        out.append(f"- 客户代表：{_sign_line(acc.get('signer_customer'))}")
        return "\n".join(out)
    return _kv_block(data)


# ---------------------------------------------------------------------------
# HTML（md 结果套企业级模板；样式 token 与前端 §5.3 一致）
# ---------------------------------------------------------------------------
def render_uat_html(payload: dict, acceptance: dict, watermark: bool) -> str:
    md = render_uat_md(payload, acceptance, watermark)
    body = md_to_html(md)
    verdict = acceptance.get("verdict") or ""
    color = {"PASSED": "#00B42A", "CONDITIONAL": "#FF7D00", "REJECTED": "#F53F3F"}.get(verdict, "#86909C")
    wm_css = ("body::before{content:'草稿 DRAFT';position:fixed;top:40%;left:20%;font-size:96px;"
              "color:rgba(245,63,63,.12);transform:rotate(-30deg);pointer-events:none}") if watermark else ""
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>UAT 验收报告</title><style>
body{{font-family:'Noto Serif SC','Songti SC',serif;max-width:820px;margin:0 auto;padding:48px 32px;color:#1D2129;line-height:1.7;font-size:14px}}
h1{{font-size:20px;text-align:center}}h2{{font-size:16px;border-left:4px solid #165DFF;padding-left:8px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #DCDFE6;padding:6px 8px;font-size:13px}}
blockquote{{color:#86909C;border-left:3px solid #FF7D00;margin:8px 0;padding:4px 12px;background:#FFF7E8}}
.verdict{{display:inline-block;padding:2px 12px;border-radius:4px;color:#fff;background:{color}}}
{wm_css}</style></head><body>{body}</body></html>"""


# ---------------------------------------------------------------------------
# PDF（Canvas 直绘：MD 行流 + DRAFT 对角水印）
# ---------------------------------------------------------------------------
def render_uat_pdf(payload: dict, acceptance: dict, watermark: bool) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as pdf_canvas

    from .export_helpers import detect_cjk_font

    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    font = detect_cjk_font()
    w, h = A4
    if watermark:
        c.saveState()
        c.setFillColorRGB(0.96, 0.25, 0.25, alpha=0.12)
        c.setFont(font, 64)
        c.translate(w * 0.12, h * 0.42)
        c.rotate(30)
        c.drawString(0, 0, "草稿 DRAFT")
        c.restoreState()
    y = h - 60
    for line in render_uat_md(payload, acceptance, watermark).splitlines():
        if y < 60:
            if watermark:  # showPage 后水印不自动延续——逐页重绘
                c.saveState()
                c.setFillColorRGB(0.96, 0.25, 0.25, alpha=0.12)
                c.setFont(font, 64)
                c.translate(w * 0.12, h * 0.42)
                c.rotate(30)
                c.drawString(0, 0, "草稿 DRAFT")
                c.restoreState()
                c.setFont(font, 10)
            y = h - 60
        y = pdf_text(c, font, line, y, w)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Word（python-docx：标题层级 + 管道表聚合；DRAFT 页眉水印）
# ---------------------------------------------------------------------------
def render_uat_word(payload: dict, acceptance: dict, watermark: bool) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()
    docx_east_asia(doc)
    if watermark:
        sec = doc.sections[0]
        hp = sec.header.paragraphs[0]
        hp.text = _WATERMARK
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER

    md_lines = render_uat_md(payload, acceptance, watermark).splitlines()
    i = 0
    while i < len(md_lines):
        line = md_lines[i]
        stripped = line.strip()
        if stripped.startswith("|"):
            block: list[str] = []
            while i < len(md_lines) and md_lines[i].strip().startswith("|"):
                block.append(md_lines[i])
                i += 1
            docx_table_from_md(doc, block)  # 连续管道行聚合为表
            continue
        if stripped.startswith("# "):
            doc.add_heading(stripped[2:], level=0)
        elif stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=1)
        elif stripped.startswith("> "):
            p = doc.add_paragraph(stripped[2:])
            p.style = doc.styles["Intense Quote"] if "Intense Quote" in [
                s.name for s in doc.styles] else p.style
        elif stripped.startswith("- "):
            doc.add_paragraph(stripped[2:], style="List Bullet")
        elif stripped == "---":
            doc.add_paragraph("─" * 40)
        elif stripped:
            doc.add_paragraph(stripped.replace("**", ""))
        i += 1
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()
