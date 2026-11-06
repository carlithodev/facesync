from __future__ import annotations

from html import escape
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(r"C:\Users\ianca\Desktop\FaceSyncV2")
DOCX = ROOT / "outputs" / "manual" / "Manual_de_Usuario_FaceSync_v1.0.docx"
PDF = ROOT / "outputs" / "manual" / "Manual_de_Usuario_FaceSync_v1.0.pdf"
LOGO = ROOT / "frontend" / "src-tauri" / "icons" / "facesync-source.png"

PURPLE = colors.HexColor("#7C3AED")
PURPLE_DARK = colors.HexColor("#5B21B6")
INK = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#64748B")
BORDER = colors.HexColor("#DDD6FE")
GRAY_BORDER = colors.HexColor("#D9DEE8")
PALE = colors.HexColor("#F3E8FF")
PALE_2 = colors.HexColor("#FAF5FF")


def paragraph_html(p: DocxParagraph) -> str:
    parts = []
    for run in p.runs:
        text = escape(run.text).replace("\n", "<br/>")
        if not text:
            continue
        if run.bold:
            text = f"<b>{text}</b>"
        if run.italic:
            text = f"<i>{text}</i>"
        parts.append(text)
    return "".join(parts) or escape(p.text).replace("\n", "<br/>")


def has_page_break(p: DocxParagraph) -> bool:
    return bool(p._p.xpath('.//w:br[@w:type="page"]'))


def has_drawing(p: DocxParagraph) -> bool:
    return bool(p._p.xpath(".//w:drawing"))


def num_id(p: DocxParagraph):
    num = p._p.find(".//" + qn("w:numId"))
    return int(num.get(qn("w:val"))) if num is not None else None


def iter_blocks(doc: Document):
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield DocxParagraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, doc)


class ManualPDF(BaseDocTemplate):
    def __init__(self, filename):
        super().__init__(
            filename,
            pagesize=LETTER,
            leftMargin=0.82 * inch,
            rightMargin=0.82 * inch,
            topMargin=0.78 * inch,
            bottomMargin=0.75 * inch,
            title="Manual de Usuario FaceSync",
            author="Ian Carlo — FaceSync",
        )
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="main",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates([
            PageTemplate(id="manual", frames=[frame], onPage=self._decorate),
        ])

    def _decorate(self, canvas, doc):
        if doc.page > 1:
            canvas.saveState()
            canvas.setFont("Helvetica-Bold", 8.5)
            canvas.setFillColor(PURPLE)
            canvas.drawString(self.leftMargin, LETTER[1] - 0.45 * inch, "FaceSync")
            canvas.setFont("Helvetica", 8.5)
            canvas.setFillColor(MUTED)
            canvas.drawString(self.leftMargin + 48, LETTER[1] - 0.45 * inch, "|  Manual de usuario")
            canvas.setStrokeColor(BORDER)
            canvas.setLineWidth(0.5)
            canvas.line(self.leftMargin, LETTER[1] - 0.51 * inch,
                        LETTER[0] - self.rightMargin, LETTER[1] - 0.51 * inch)
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(LETTER[0] - self.rightMargin, 0.42 * inch,
                                   f"FaceSync 1.0.0  •  Página {doc.page}")
            canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            level = getattr(flowable, "_heading_level", None)
            if level:
                key = f"h{self.page}_{abs(hash(flowable.getPlainText()))}"
                self.canv.bookmarkPage(key)
                outline_level = 0 if level == 1 else 1
                self.canv.addOutlineEntry(flowable.getPlainText(), key, level=outline_level, closed=False)


def build_styles():
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "FSBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=10.2,
        leading=12.8, textColor=INK, spaceAfter=5.5, allowWidows=0, allowOrphans=0,
    )
    h1 = ParagraphStyle(
        "FSH1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=15,
        leading=18, textColor=PURPLE, spaceBefore=6, spaceAfter=9, keepWithNext=1,
    )
    h2 = ParagraphStyle(
        "FSH2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12.3,
        leading=15, textColor=PURPLE, spaceBefore=10, spaceAfter=6, keepWithNext=1,
    )
    h3 = ParagraphStyle(
        "FSH3", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=10.8,
        leading=13, textColor=PURPLE_DARK, spaceBefore=7, spaceAfter=4, keepWithNext=1,
    )
    center = ParagraphStyle("FSCenter", parent=body, alignment=TA_CENTER)
    cover_kicker = ParagraphStyle(
        "CoverKicker", parent=center, fontName="Helvetica-Bold", fontSize=10.5,
        leading=13, textColor=PURPLE, spaceAfter=8,
    )
    cover_title = ParagraphStyle(
        "CoverTitle", parent=center, fontName="Helvetica-Bold", fontSize=32,
        leading=37, textColor=PURPLE_DARK, spaceAfter=8,
    )
    cover_sub = ParagraphStyle(
        "CoverSub", parent=center, fontName="Helvetica", fontSize=15,
        leading=18, textColor=MUTED, spaceAfter=24,
    )
    table = ParagraphStyle(
        "FSTable", parent=body, fontSize=8.9, leading=10.8, spaceAfter=0,
    )
    table_head = ParagraphStyle(
        "FSTableHead", parent=table, fontName="Helvetica-Bold", textColor=PURPLE_DARK,
    )
    note_label = ParagraphStyle(
        "FSNoteLabel", parent=body, fontName="Helvetica-Bold", fontSize=8,
        leading=9.5, textColor=PURPLE_DARK, spaceAfter=2,
    )
    note_body = ParagraphStyle(
        "FSNoteBody", parent=body, fontSize=9.4, leading=11.6, spaceAfter=0,
    )
    code = ParagraphStyle(
        "FSCode", parent=body, fontName="Courier", fontSize=8.2, leading=10,
        textColor=colors.HexColor("#334155"), spaceAfter=0,
    )
    return locals()


def table_widths(doc_table: DocxTable, available: float):
    grid = doc_table._tbl.tblGrid
    values = []
    for col in grid.gridCol_lst:
        raw = col.get(qn("w:w"))
        values.append(float(raw or 1))
    if not values:
        values = [1] * len(doc_table.columns)
    total = sum(values) or 1
    return [available * value / total for value in values]


def cell_fill(cell):
    shd = cell._tc.get_or_add_tcPr().find(qn("w:shd"))
    return shd.get(qn("w:fill")) if shd is not None else None


def convert_table(src: DocxTable, available, s):
    rows = []
    one_col = len(src.columns) == 1
    is_code = one_col and any(
        "Consolas" in str(run.font.name or "")
        for cell in src.rows[0].cells for p in cell.paragraphs for run in p.runs
    )
    for r_idx, row in enumerate(src.rows):
        values = []
        for cell in row.cells:
            paras = []
            for p_idx, p in enumerate(cell.paragraphs):
                style = s["code"] if is_code else (s["note_label"] if one_col and p_idx == 0 else s["note_body"] if one_col else s["table_head"] if r_idx == 0 else s["table"])
                text = paragraph_html(p).replace("\n", "<br/>")
                if text:
                    paras.append(Paragraph(text, style))
            values.append(paras or [Paragraph("", s["table"])])
        rows.append(values)

    widths = table_widths(src, available)
    if one_col:
        fill_hex = cell_fill(src.cell(0, 0)) or "FAF5FF"
        fill = colors.HexColor(f"#{fill_hex}")
        accent = PURPLE
        label = src.cell(0, 0).paragraphs[0].text.upper() if src.cell(0, 0).paragraphs else ""
        if "IMPORTANTE" in label or "CONSEJO" in label or "REGLA" in label:
            accent = colors.HexColor("#92400E") if "IMPORTANTE" in label else PURPLE
        if "AVISO" in label or "REINTENTO" in label or "NO CONFUNDA" in label or "PRIMERA" in label:
            accent = colors.HexColor("#B91C1C")
        if "PRIVACIDAD" in label or "CRITERIO" in label:
            accent = colors.HexColor("#047857")
        tbl = Table(rows, colWidths=widths, hAlign="LEFT")
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), fill),
            ("BOX", (0, 0), (-1, -1), 0.4, fill),
            ("LINEBEFORE", (0, 0), (0, -1), 4, accent),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return KeepTogether([tbl, Spacer(1, 5)])

    tbl = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("TEXTCOLOR", (0, 0), (-1, 0), PURPLE_DARK),
        ("GRID", (0, 0), (-1, -1), 0.4, GRAY_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for idx in range(2, len(rows), 2):
        style.append(("BACKGROUND", (0, idx), (-1, idx), PALE_2))
    tbl.setStyle(TableStyle(style))
    return [tbl, Spacer(1, 5)]


def build_pdf():
    src = Document(DOCX)
    s = build_styles()
    pdf = ManualPDF(str(PDF))
    story = []
    blocks = list(iter_blocks(src))
    i = 0
    cover_state = 0
    while i < len(blocks):
        block = blocks[i]
        if isinstance(block, DocxParagraph):
            if has_page_break(block):
                story.append(PageBreak())
                i += 1
                continue
            if has_drawing(block):
                story.extend([Spacer(1, 0.5 * inch), Image(str(LOGO), width=1.85 * inch, height=1.85 * inch, hAlign="CENTER"), Spacer(1, 14)])
                cover_state = 1
                i += 1
                continue
            text = paragraph_html(block)
            if not text:
                story.append(Spacer(1, 4))
                i += 1
                continue
            style_name = block.style.name if block.style else "Normal"
            if style_name == "Heading 1":
                flow = Paragraph(text, s["h1"])
                flow._heading_level = 1
                story.append(flow)
            elif style_name == "Heading 2":
                flow = Paragraph(text, s["h2"])
                flow._heading_level = 2
                story.append(flow)
            elif style_name == "Heading 3":
                flow = Paragraph(text, s["h3"])
                flow._heading_level = 3
                story.append(flow)
            elif num_id(block) is not None:
                list_items = []
                current_num = num_id(block)
                while i < len(blocks) and isinstance(blocks[i], DocxParagraph) and num_id(blocks[i]) == current_num:
                    list_items.append(ListItem(Paragraph(paragraph_html(blocks[i]), s["body"]), leftIndent=5))
                    i += 1
                list_options = {
                    "bulletType": "bullet" if current_num == 90 else "1",
                    "leftIndent": 19,
                    "bulletFontName": "Helvetica-Bold",
                    "bulletFontSize": 9,
                    "bulletColor": PURPLE,
                    "spaceAfter": 5,
                }
                if current_num != 90:
                    list_options["start"] = "1"
                story.append(ListFlowable(list_items, **list_options))
                continue
            elif cover_state == 1 and "MANUAL DE USUARIO" in block.text:
                story.append(Paragraph(text, s["cover_kicker"]))
                cover_state = 2
            elif cover_state == 2 and block.text.strip() == "FaceSync":
                story.append(Paragraph(text, s["cover_title"]))
                cover_state = 3
            elif cover_state == 3 and "Clasificación inteligente" in block.text:
                story.append(Paragraph(text, s["cover_sub"]))
                cover_state = 4
            else:
                style = s["center"] if block.alignment == WD_ALIGN_PARAGRAPH.CENTER else s["body"]
                story.append(Paragraph(text, style))
        else:
            rendered = convert_table(block, pdf.width, s)
            story.extend(rendered if isinstance(rendered, list) else [rendered])
        i += 1

    pdf.build(story)
    print(PDF)


if __name__ == "__main__":
    build_pdf()
