# SPDX-License-Identifier: BUSL-1.1
"""导出渲染原语（OSS 服务层）——自 commercial/routers/quality_export.py 提升，
供 quality_export（商业）与 uat_render（共享）共用，逻辑零改动。

约束：本文件不得 import 任何 app.commercial 模块（OSS → commercial 禁止反向依赖）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..routers._business_common import (  # re-export：PDF 表格底座留原处，避免双份实现
    _PDF_AVAIL_MM,
    _make_pdf_table,
    _md_to_html,
)

#: PDF 正文可用宽度（mm）对外别名
PDF_AVAIL_MM = _PDF_AVAIL_MM
#: Markdown → HTML 轻量转换对外别名
md_to_html = _md_to_html

FMT_EXT = {"pdf": "pdf", "word": "docx", "md": "md", "html": "html"}


def now_cn() -> datetime:
    """UTC+8 当前时间（导出文件名的日期口径）。"""
    return datetime.now(timezone(timedelta(hours=8)))


def fmt_dt(iso: str | None) -> str:
    """ISO8601 → YYYY-MM-DD HH:MM（+08:00 展示口径，视图/导出一致）。"""
    if not iso:
        return "-"
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(
            timezone(timedelta(hours=8))
        )
        return d.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(iso)


def detect_cjk_font():
    """reportlab 字体探测链（容器 wqy → 宿主机 simhei → DejaVu → STSong），返回字体名。"""
    import os

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for fp in (
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            if not os.path.exists(fp):
                continue
            if fp.lower().endswith(".ttc"):
                pdfmetrics.registerFont(TTFont("WQY", fp, subfontIndex=0))
                return "WQY"
            pdfmetrics.registerFont(TTFont("SimHei", fp))
            return "SimHei"
        except Exception:  # noqa: BLE001
            continue
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


# ---------------------------------------------------------------------------
# MD 行流式 PDF 绘制原语（Canvas 直绘，供 uat_render 使用；
# quality_export 的 Platypus 表格路径继续走 _make_pdf_table，两条管道互不影响）
# ---------------------------------------------------------------------------
def pdf_text(c, font: str, line: str, y: int, page_w: int) -> int:
    """单行 MD 文本 → Canvas 绘制，返回下一行 y 坐标。"""
    if not line.strip():
        return y - 6
    size, indent = 10, 40
    if line.startswith("# "):
        size, indent = 18, 40
        line = line[2:]
    elif line.startswith("## "):
        size, indent = 14, 40
        line = line[3:]
    elif line.startswith("### "):
        size, indent = 12, 40
        line = line[4:]
    elif line.startswith("> "):
        indent = 60
        line = line[2:]
    elif line.startswith("---"):
        c.setLineWidth(0.5)
        c.line(indent, y + 3, page_w - 40, y + 3)
        return y - 10
    text = line.lstrip("-— ").replace("**", "")
    # 简单按列宽截断换行（中文按 1 字符宽估算，避免溢出页边）
    max_chars = int((page_w - indent - 40) / (size * 0.62)) or 40
    c.setFont(font, size)
    for i in range(0, len(text), max_chars):
        c.drawString(indent, y, text[i : i + max_chars])
        y -= size + 4
    return y


# ---------------------------------------------------------------------------
# Word 原语（python-docx）
# ---------------------------------------------------------------------------
def docx_east_asia(doc) -> None:
    """正文样式显式声明 eastAsia 中文字体（缺省会被 Word 回退为宋体乱版式）。"""
    from docx.oxml.ns import qn

    style = doc.styles["Normal"]
    style.font.name = "微软雅黑"
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")


def docx_table(doc, rows: list[list[str]], bold_head: bool = True) -> None:
    """管道表行集合 → docx 表格（首行加粗表头）。"""
    if not rows:
        return
    width = max(len(r) for r in rows)
    tbl = doc.add_table(rows=0, cols=width)
    for ri, row in enumerate(rows):
        cells = tbl.add_row().cells
        for ci in range(width):
            cells[ci].text = (row[ci] if ci < len(row) else "").replace("**", "")
        if ri == 0 and bold_head:
            for ci in range(width):
                for para_ in cells[ci].paragraphs:
                    for run_ in para_.runs:
                        run_.bold = True


def docx_table_from_md(doc, pipe_lines: list[str]) -> None:
    """连续 `|` 行聚合 → 管道表解析（跳过分隔行）→ docx_table。"""
    rows: list[list[str]] = []
    for ln in pipe_lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):  # |---|---| 分隔行
            continue
        rows.append(cells)
    docx_table(doc, rows)


__all__ = [
    "FMT_EXT", "PDF_AVAIL_MM", "md_to_html", "now_cn", "fmt_dt",
    "detect_cjk_font", "pdf_text", "docx_east_asia", "docx_table",
    "docx_table_from_md", "_make_pdf_table",
]
