from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(r"C:\Users\ianca\Desktop\FaceSyncV2")
OUT = ROOT / "outputs" / "manual" / "Manual_de_Usuario_FaceSync_v1.0.docx"
LOGO = ROOT / "frontend" / "src-tauri" / "icons" / "facesync-source.png"

# compact_reference_guide preset + named FaceSync_brand override.
PURPLE = "7C3AED"
PURPLE_DARK = "5B21B6"
MAGENTA = "D946EF"
INK = "1F2937"
MUTED = "64748B"
PALE = "F3E8FF"
PALE_2 = "FAF5FF"
GREEN = "047857"
GREEN_PALE = "ECFDF5"
AMBER = "92400E"
AMBER_PALE = "FFFBEB"
RED = "B91C1C"
RED_PALE = "FEF2F2"
BORDER = "DDD6FE"
GRAY_BORDER = "D9DEE8"
WHITE = "FFFFFF"

PAGE_WIDTH_DXA = 9360
TABLE_INDENT_DXA = 120
CELL_TOP_BOTTOM = 80
CELL_START_END = 120


def rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value)


def set_font(run, name="Calibri", size=11, color=INK, bold=None, italic=None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    run.font.size = Pt(size)
    run.font.color.rgb = rgb(color)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def set_repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def prevent_row_split(row):
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    tr_pr.append(cant_split)


def set_cell_margins(cell, top=CELL_TOP_BOTTOM, start=CELL_START_END,
                     bottom=CELL_TOP_BOTTOM, end=CELL_START_END):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for tag, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{tag}"))
        if node is None:
            node = OxmlElement(f"w:{tag}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def shade_cell(cell, fill: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_border(cell, color=GRAY_BORDER, size=4, left=None):
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "start", "bottom", "end", "insideH", "insideV"):
        tag = qn(f"w:{edge}")
        node = borders.find(tag)
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), str(size))
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), color)
    if left:
        node = borders.find(qn("w:start"))
        node.set(qn("w:sz"), str(left[1]))
        node.set(qn("w:color"), left[0])


def set_table_geometry(table, widths_dxa: Sequence[int], indent_dxa=TABLE_INDENT_DXA):
    assert sum(widths_dxa) == PAGE_WIDTH_DXA, (widths_dxa, sum(widths_dxa))
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.first_child_found_in("w:tblW")
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(PAGE_WIDTH_DXA))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_ind = tbl_pr.first_child_found_in("w:tblInd")
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), str(indent_dxa))
    tbl_ind.set(qn("w:type"), "dxa")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths_dxa:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row in table.rows:
        prevent_row_split(row)
        for idx, cell in enumerate(row.cells):
            width = widths_dxa[idx]
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.first_child_found_in("w:tcW")
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(width))
            tc_w.set(qn("w:type"), "dxa")
            cell.width = Inches(width / 1440)
            set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def set_paragraph_border(paragraph, color=PURPLE, size=12, side="bottom"):
    p_pr = paragraph._p.get_or_add_pPr()
    borders = p_pr.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        p_pr.append(borders)
    edge = OxmlElement(f"w:{side}")
    edge.set(qn("w:val"), "single")
    edge.set(qn("w:sz"), str(size))
    edge.set(qn("w:space"), "3")
    edge.set(qn("w:color"), color)
    borders.append(edge)


def add_field(paragraph, field_code: str, display=""):
    run_begin = OxmlElement("w:r")
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    run_begin.append(begin)
    run_instr = OxmlElement("w:r")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = field_code
    run_instr.append(instr)
    run_sep = OxmlElement("w:r")
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    run_sep.append(separate)
    run_text = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = display
    run_text.append(text)
    run_end = OxmlElement("w:r")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run_end.append(end)
    paragraph._p.extend([run_begin, run_instr, run_sep, run_text, run_end])


def add_numbering_definition(doc: Document, kind: str, abstract_id: int, num_id: int):
    numbering = doc.part.numbering_part.element
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    multi = OxmlElement("w:multiLevelType")
    multi.set(qn("w:val"), "singleLevel")
    abstract.append(multi)
    lvl = OxmlElement("w:lvl")
    lvl.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:start")
    start.set(qn("w:val"), "1")
    fmt = OxmlElement("w:numFmt")
    fmt.set(qn("w:val"), "bullet" if kind == "bullet" else "decimal")
    lvl_text = OxmlElement("w:lvlText")
    lvl_text.set(qn("w:val"), "•" if kind == "bullet" else "%1.")
    suff = OxmlElement("w:suff")
    suff.set(qn("w:val"), "tab")
    lvl_jc = OxmlElement("w:lvlJc")
    lvl_jc.set(qn("w:val"), "left")
    p_pr = OxmlElement("w:pPr")
    tabs = OxmlElement("w:tabs")
    tab = OxmlElement("w:tab")
    tab.set(qn("w:val"), "num")
    tab.set(qn("w:pos"), "540")
    tabs.append(tab)
    ind = OxmlElement("w:ind")
    ind.set(qn("w:left"), "540")
    ind.set(qn("w:hanging"), "270")
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:after"), "80")
    spacing.set(qn("w:line"), "300")
    spacing.set(qn("w:lineRule"), "auto")
    p_pr.extend([tabs, ind, spacing])
    lvl.extend([start, fmt, lvl_text, suff, lvl_jc, p_pr])
    if kind == "bullet":
        r_pr = OxmlElement("w:rPr")
        fonts = OxmlElement("w:rFonts")
        fonts.set(qn("w:ascii"), "Calibri")
        fonts.set(qn("w:hAnsi"), "Calibri")
        color = OxmlElement("w:color")
        color.set(qn("w:val"), PURPLE)
        r_pr.extend([fonts, color])
        lvl.append(r_pr)
    abstract.append(lvl)
    numbering.append(abstract)
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abs_id = OxmlElement("w:abstractNumId")
    abs_id.set(qn("w:val"), str(abstract_id))
    num.append(abs_id)
    numbering.append(num)


def apply_num(paragraph, num_id: int):
    p_pr = paragraph._p.get_or_add_pPr()
    num_pr = p_pr.find(qn("w:numPr"))
    if num_pr is None:
        num_pr = OxmlElement("w:numPr")
        p_pr.append(num_pr)
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    num = OxmlElement("w:numId")
    num.set(qn("w:val"), str(num_id))
    num_pr.extend([ilvl, num])


def configure_document(doc: Document):
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)
    section.different_first_page_header_footer = True

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Calibri"
    normal._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
    normal.font.size = Pt(11)
    normal.font.color.rgb = rgb(INK)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25

    for name, size, color, before, after in (
        ("Heading 1", 16, PURPLE, 18, 10),
        ("Heading 2", 13, PURPLE, 14, 7),
        ("Heading 3", 12, PURPLE_DARK, 10, 5),
    ):
        style = styles[name]
        style.font.name = "Calibri"
        style._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
        style._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = rgb(color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.line_spacing = 1.0
        style.paragraph_format.keep_with_next = True

    add_numbering_definition(doc, "bullet", 90, 90)
    add_numbering_definition(doc, "decimal", 91, 91)

    header = section.header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    hp.paragraph_format.space_after = Pt(3)
    r = hp.add_run("FaceSync")
    set_font(r, size=9, color=PURPLE, bold=True)
    r = hp.add_run("   |   Manual de usuario")
    set_font(r, size=9, color=MUTED)
    set_paragraph_border(hp, color=BORDER, size=4)

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = fp.add_run("FaceSync 1.0.0   •   Página ")
    set_font(r, size=8.5, color=MUTED)
    add_field(fp, " PAGE ", "1")
    r = fp.add_run(" de ")
    set_font(r, size=8.5, color=MUTED)
    add_field(fp, " NUMPAGES ", "1")


def paragraph(doc, text="", *, bold_prefix=None, italic=False, align=None, after=None,
              keep=False, color=INK, size=11):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    if after is not None:
        p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.keep_together = keep
    if bold_prefix and text.startswith(bold_prefix):
        r = p.add_run(bold_prefix)
        set_font(r, size=size, color=color, bold=True)
        r = p.add_run(text[len(bold_prefix):])
        set_font(r, size=size, color=color, italic=italic)
    else:
        r = p.add_run(text)
        set_font(r, size=size, color=color, italic=italic)
    return p


def heading(doc, text, level=1):
    p = doc.add_paragraph(style=f"Heading {level}")
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    return p


def section_page(doc, title: str, number: int | None = None, subtitle: str | None = None):
    doc.add_page_break()
    text = f"{number}. {title}" if number is not None else title
    p = heading(doc, text, 1)
    if subtitle:
        q = paragraph(doc, subtitle, size=10.5, color=MUTED, after=12)
        q.paragraph_format.keep_with_next = True
    return p


def bullet(doc, text, bold_prefix=None):
    p = doc.add_paragraph()
    apply_num(p, 90)
    if bold_prefix and text.startswith(bold_prefix):
        r = p.add_run(bold_prefix)
        set_font(r, bold=True)
        r = p.add_run(text[len(bold_prefix):])
        set_font(r)
    else:
        set_font(p.add_run(text))
    return p


def numbered(doc, text, bold_prefix=None, num_id=91):
    p = doc.add_paragraph()
    apply_num(p, num_id)
    if bold_prefix and text.startswith(bold_prefix):
        set_font(p.add_run(bold_prefix), bold=True, color=PURPLE_DARK)
        set_font(p.add_run(text[len(bold_prefix):]))
    else:
        set_font(p.add_run(text))
    return p


def new_numbered_list(doc, items: Iterable[tuple[str, str] | str], seed: int):
    abstract_id = 100 + seed
    num_id = 100 + seed
    add_numbering_definition(doc, "decimal", abstract_id, num_id)
    for item in items:
        if isinstance(item, tuple):
            title, body = item
            numbered(doc, f"{title}. {body}", bold_prefix=f"{title}. ", num_id=num_id)
        else:
            numbered(doc, item, num_id=num_id)


def callout(doc, label: str, text: str, *, tone="purple"):
    palette = {
        "purple": (PALE_2, PURPLE, PURPLE_DARK),
        "green": (GREEN_PALE, GREEN, GREEN),
        "amber": (AMBER_PALE, AMBER, AMBER),
        "red": (RED_PALE, RED, RED),
    }
    fill, accent, label_color = palette[tone]
    table = doc.add_table(rows=1, cols=1)
    set_table_geometry(table, [PAGE_WIDTH_DXA])
    cell = table.cell(0, 0)
    shade_cell(cell, fill)
    set_cell_border(cell, color=fill, size=0, left=(accent, 16))
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(label.upper())
    set_font(r, size=9, color=label_color, bold=True)
    p = cell.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.18
    set_font(p.add_run(text), size=10.5, color=INK)
    paragraph(doc, "", after=2)
    return table


def add_table(doc, headers: Sequence[str], rows: Sequence[Sequence[str]], widths: Sequence[int],
              *, header_fill=PALE, font_size=10):
    table = doc.add_table(rows=1, cols=len(headers))
    for idx, value in enumerate(headers):
        cell = table.rows[0].cells[idx]
        shade_cell(cell, header_fill)
        set_cell_border(cell, color=BORDER, size=5)
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        set_font(p.add_run(str(value)), size=font_size, color=PURPLE_DARK, bold=True)
    set_repeat_table_header(table.rows[0])
    for row_idx, values in enumerate(rows):
        cells = table.add_row().cells
        for idx, value in enumerate(values):
            cell = cells[idx]
            if row_idx % 2:
                shade_cell(cell, "FBFAFF")
            set_cell_border(cell, color=GRAY_BORDER, size=4)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.10
            set_font(p.add_run(str(value)), size=font_size, color=INK)
    set_table_geometry(table, widths)
    paragraph(doc, "", after=1)
    return table


def code_block(doc, text: str):
    table = doc.add_table(rows=1, cols=1)
    set_table_geometry(table, [PAGE_WIDTH_DXA])
    cell = table.cell(0, 0)
    shade_cell(cell, "F8FAFC")
    set_cell_border(cell, color=GRAY_BORDER, size=4)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    r = p.add_run(text)
    set_font(r, name="Consolas", size=9, color="334155")
    paragraph(doc, "", after=1)


def cover(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(45)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(LOGO), width=Inches(2.15))

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(20)
    p.paragraph_format.space_after = Pt(8)
    set_font(p.add_run("MANUAL DE USUARIO"), size=11, color=PURPLE, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    set_font(p.add_run("FaceSync"), size=34, color=PURPLE_DARK, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(34)
    p.paragraph_format.line_spacing = 1.12
    set_font(p.add_run("Clasificación inteligente de fotografías\npara agencias de graduaciones"), size=16, color=MUTED)

    callout(doc, "Propósito", "Guía completa para instalar, preparar, clasificar, revisar y entregar fotografías con FaceSync.", tone="purple")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(68)
    p.paragraph_format.space_after = Pt(3)
    set_font(p.add_run("Versión de la aplicación 1.0.0"), size=10.5, color=INK, bold=True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(3)
    set_font(p.add_run("Edición del manual: agosto de 2026"), size=10, color=MUTED)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("Ian Carlo | Desarrollador de FaceSync | Hermosillo, Sonora"), size=9.5, color=MUTED)


def add_contents(doc):
    section_page(doc, "Contenido")
    add_table(doc, ["Sección", "Tema"], [
        ["1", "Inicio rápido"],
        ["2", "Instalación, inicio de sesión y cuenta"],
        ["3", "Conocer la interfaz"],
        ["4", "Preparar el Excel"],
        ["5", "Preparar fotografías y workspace"],
        ["6", "Crear carpetas de alumnos"],
        ["7", "Clasificar fotografías"],
        ["8", "Supervisar, cancelar y reanudar"],
        ["9", "Resultados y reportes"],
        ["10", "Códigos repetidos e historial de identidad"],
        ["11", "Exportar a Google Drive"],
        ["12", "Asistente IA"],
        ["13", "Administrar archivos y carpetas"],
        ["14", "Buenas prácticas de producción"],
        ["15", "Solución de problemas"],
        ["16", "Preguntas frecuentes"],
        ["17", "Listas de control"],
        ["18", "Soporte y cierre"],
    ], [1500, 7860], font_size=9.6)
    callout(doc, "Consejo", "Si está consultando la versión PDF, utilice el panel de miniaturas o la búsqueda del lector para saltar rápidamente a un tema.", tone="purple")


def build_manual():
    doc = Document()
    configure_document(doc)
    cover(doc)

    section_page(doc, "Acerca de este manual")
    paragraph(doc, "Este documento explica el uso operativo de FaceSync desde la instalación hasta la entrega y revisión de resultados. Está dirigido a personal de producción, edición, coordinación y soporte de una agencia de graduaciones.")
    add_table(doc, ["Dato", "Información"], [
        ["Producto", "FaceSync"],
        ["Versión", "1.0.0 para Windows de 64 bits"],
        ["Alcance", "Clasificación local de fotografías por alumno, gestión del workspace, reportes y exportación opcional a Google Drive"],
        ["Formatos principales", "JPG, JPEG y CR2. El motor también admite PNG, WEBP y BMP."],
        ["Responsable", "Ian Carlo, desarrollador de FaceSync"],
    ], [2200, 7160])
    heading(doc, "Qué hace FaceSync", 2)
    paragraph(doc, "FaceSync utiliza reconocimiento facial para localizar a cada alumno a partir de una fotografía de referencia y copiar sus imágenes a una carpeta individual. Puede trabajar con retratos, fotografías grupales, varias carpetas de origen y lotes que mezclen JPG y CR2.")
    heading(doc, "Qué no sustituye", 2)
    paragraph(doc, "FaceSync reduce drásticamente la clasificación manual, pero no sustituye la revisión de control de calidad. El operador debe validar el Excel, revisar el resumen final y atender las advertencias de los reportes antes de entregar al cliente final.")
    callout(doc, "Privacidad operativa", "El reconocimiento facial se ejecuta localmente en la computadora. Las fotografías solo se suben a Google Drive cuando el usuario inicia expresamente una exportación. El inicio de sesión, el asistente y Drive requieren conexión a internet.", tone="green")

    add_contents(doc)

    section_page(doc, "Inicio rápido", 1, "El flujo completo en ocho decisiones.")
    new_numbered_list(doc, [
        ("Prepare el lote", "Reúna las fotografías del salón y confirme que no estén dañadas."),
        ("Abra FaceSync", "Inicie sesión con la cuenta operativa de la agencia."),
        ("Agregue el workspace", "Incorpore las carpetas de origen, el Excel y el destino."),
        ("Valide el Excel", "Debe existir una fila por alumno y una sola referencia numérica por fila."),
        ("Cree las carpetas", "Opcionalmente genere una carpeta por alumno desde el Excel."),
        ("Inicie la clasificación", "Elija Excel, columnas, una o varias carpetas de origen y un destino vacío."),
        ("Espere la finalización", "No cierre la aplicación, no desconecte el disco y no mueva los archivos mientras procesa."),
        ("Revise y entregue", "Compruebe carpetas, efectividad, alumnos con pocas fotos y los reportes JSON, TXT y XLSX."),
    ], 1)
    callout(doc, "Regla de oro", "La calidad del resultado comienza en el Excel. Una referencia correcta, visible y única por alumno es más importante que cualquier ajuste posterior.", tone="amber")
    heading(doc, "Antes de comenzar", 2)
    for item in [
        "Conecte la laptop a la corriente y desactive temporalmente la suspensión automática.",
        "Asegure espacio libre suficiente en el destino. Las fotos grupales pueden copiarse a varias carpetas y aumentar el tamaño final.",
        "Use una conexión estable si iniciará sesión, utilizará el asistente o exportará a Drive.",
        "Trabaje con una carpeta de destino distinta de las carpetas de origen.",
        "Para lotes críticos, conserve una copia de seguridad del material original.",
    ]:
        bullet(doc, item)

    section_page(doc, "Instalación, inicio de sesión y cuenta", 2)
    heading(doc, "Requisitos operativos", 2)
    add_table(doc, ["Elemento", "Recomendación"], [
        ["Sistema", "Windows 10 u 11, 64 bits"],
        ["Almacenamiento", "SSD interno o disco externo estable. Reserve como referencia 1.5 a 2 veces el tamaño del lote; si hay muchas grupales puede requerirse más."],
        ["Procesamiento", "GPU compatible recomendada para lotes grandes y CR2; FaceSync puede utilizar una ruta de CPU cuando sea necesario."],
        ["Internet", "Necesario para Google, el asistente y Drive; no para el cálculo facial local ya preparado."],
        ["Aplicación de hojas", "Microsoft Excel o una aplicación compatible para editar la plantilla .xlsx."],
    ], [2300, 7060])
    heading(doc, "Instalar FaceSync", 2)
    new_numbered_list(doc, [
        ("Ejecute el instalador", "Abra FaceSync_1.0.0_x64-setup.exe desde el canal oficial de entrega."),
        ("Confirme la instalación", "Siga el asistente de Windows y conserve la ubicación recomendada."),
        ("Abra FaceSync", "Utilice el acceso directo del escritorio o el menú Inicio."),
        ("Espere el primer arranque", "La primera apertura puede tardar más porque el motor prepara sus componentes."),
    ], 2)
    callout(doc, "Aviso de Windows", "Si Windows muestra una advertencia de protección, continúe únicamente cuando el instalador haya sido recibido directamente por el canal oficial de FaceSync. En ese caso puede elegir “Más información” y “Ejecutar de todas formas”.", tone="amber")
    heading(doc, "Iniciar y conservar la sesión", 2)
    paragraph(doc, "Seleccione “Continuar con Google”, autorice la cuenta y regrese a FaceSync. La cuenta queda guardada localmente y la aplicación intentará abrir directamente la sesión en los siguientes arranques.")
    for item in [
        "Para utilizar otra cuenta, elija “Cerrar sesión” en la barra lateral y agregue o seleccione la cuenta correspondiente.",
        "En la pantalla de acceso puede eliminar una cuenta guardada con el botón de cierre y su confirmación.",
        "La memoria del workspace, el chat y el historial de identidades se organizan por cuenta. Use la misma cuenta para una misma operación de producción.",
    ]:
        bullet(doc, item)

    section_page(doc, "Conocer la interfaz", 3)
    paragraph(doc, "La pantalla principal está dividida en tres áreas. Los separadores entre paneles se pueden arrastrar para dar más espacio a la zona que esté utilizando.")
    add_table(doc, ["Zona", "Función", "Uso principal"], [
        ["Explorador (izquierda)", "Muestra las raíces, carpetas y archivos del workspace.", "Abrir, refrescar, agregar, renombrar, quitar o eliminar elementos."],
        ["Área central", "Incluye visor de imágenes, acciones rápidas y estado del proceso.", "Crear Excel, crear carpetas, clasificar y revisar una imagen."],
        ["Asistente IA (derecha)", "Interpreta solicitudes en lenguaje natural y conserva conversación por cuenta.", "Organizar carpetas, leer Excel y ejecutar acciones guiadas."],
    ], [1900, 3300, 4160])
    heading(doc, "Navegación principal", 2)
    for label, text in [
        ("Workspace: ", "preparación, exploración y clasificación del material."),
        ("Reportes: ", "consulta de clasificaciones, métricas y archivos de auditoría."),
        ("Exportaciones: ", "subida de resultados a Google Drive e historial de entregas."),
        ("Ajustes: ", "estado del motor y uso de almacenamiento del workspace."),
        ("Cerrar sesión: ", "sale de la cuenta actual sin borrar sus archivos de trabajo."),
    ]:
        bullet(doc, label + text, bold_prefix=label)
    heading(doc, "Visor de imágenes", 2)
    paragraph(doc, "Seleccione una imagen en el árbol para verla en el panel central. Puede acercar, alejar, mover y rotar 90 grados. En CR2, FaceSync utiliza la vista previa integrada; si un archivo no contiene una vista utilizable, puede mostrar “Sin previsualización” aunque el motor todavía intente procesarlo mediante su ruta de respaldo.")

    section_page(doc, "Preparar el Excel", 4, "Una fila por alumno y una referencia facial clara.")
    heading(doc, "Crear la plantilla desde FaceSync", 2)
    new_numbered_list(doc, [
        ("Abra “Crear Excel”", "La acción se encuentra en el área central del Workspace."),
        ("Escriba el nombre", "FaceSync agrega automáticamente la extensión .xlsx."),
        ("Elija dónde guardarlo", "Seleccione una carpeta que ya forme parte del workspace."),
        ("Pulse “Crear Excel”", "La aplicación confirma el nombre y la ruta del archivo."),
        ("Abra la plantilla", "Use “Abrir Excel” para capturar la información o “Listo” para cerrar."),
    ], 3)
    heading(doc, "Estructura recomendada", 2)
    add_table(doc, ["Nombre del alumno", "Código de foto"], [
        ["AGUIRRE FIGUEROA", "2411"],
        ["ARMENTA CHICO", "2405"],
        ["ARRIOVIVEZ OTHON", "2462"],
    ], [6100, 3260])
    callout(doc, "Regla crítica: un solo código", "Escriba una sola referencia por alumno. No use listas, rangos ni varios números en la misma celda. Ejemplos no admitidos: “2411, 2412”, “2411-2415” o “2411 / 2412”.", tone="red")
    heading(doc, "Cómo se relaciona el código con el archivo", 2)
    paragraph(doc, "FaceSync busca el último bloque numérico del nombre de archivo. Por ello, la referencia 2411 puede localizar IMG_2411.JPG o IMG_2411.CR2. Evite agregar otro número después del código de la foto.")
    add_table(doc, ["Nombre de archivo", "Código interpretado", "Resultado"], [
        ["IMG_2411.JPG", "2411", "Correcto"],
        ["Sesion_02_IMG_2411.CR2", "2411", "Correcto"],
        ["IMG_2411_copia_2.JPG", "2", "No recomendado: el último número cambió"],
        ["IMG_sin_codigo.JPG", "Sin código", "No puede usarse como referencia numérica"],
    ], [4000, 1900, 3460])
    heading(doc, "Lista de validación del Excel", 2)
    for item in [
        "Cada alumno aparece una sola vez con su nombre final de carpeta.",
        "No hay filas vacías intercaladas ni referencias en blanco.",
        "La referencia corresponde a una foto donde el rostro del alumno es visible.",
        "El código existe realmente en alguna de las carpetas de origen.",
        "No se agregaron notas, comas, rangos o códigos alternos en la celda de referencia.",
        "El archivo se guardó y cerró antes de iniciar la clasificación.",
    ]:
        bullet(doc, item)

    section_page(doc, "Preparar fotografías y workspace", 5)
    heading(doc, "Formatos y calidad", 2)
    paragraph(doc, "El flujo principal está validado para JPG/JPEG y CR2. También se admiten PNG, WEBP y BMP. Para obtener mejores resultados, el rostro debe ser visible, con tamaño suficiente y sin desenfoque severo.")
    for item in [
        "La iluminación, el contraste o la edición pueden variar; una cara clara suele conservar la identidad facial.",
        "Evite usar como referencia una foto donde otra persona tape al alumno o donde el rostro sea demasiado pequeño.",
        "Las fotos grupales son válidas: un mismo archivo puede copiarse a las carpetas de varias personas reconocidas.",
        "Los originales no se modifican. FaceSync analiza y copia archivos hacia el destino.",
    ]:
        bullet(doc, item)
    heading(doc, "Pares JPG + CR2", 2)
    paragraph(doc, "Cuando una fotografía existe en JPG y CR2 con el mismo nombre base dentro de la misma carpeta, FaceSync puede analizar la versión JPG y entregar ambos archivos juntos. Un CR2 sin JPG gemelo también puede procesarse de forma independiente.")
    callout(doc, "Importante", "No cambie únicamente la extensión. Un par válido conserva el mismo nombre base, por ejemplo IMG_2411.JPG e IMG_2411.CR2.", tone="amber")
    heading(doc, "Agregar carpetas al workspace", 2)
    new_numbered_list(doc, [
        ("Pulse “Nueva carpeta / archivo”", "Agregue una carpeta raíz o un archivo al espacio de trabajo."),
        ("Seleccione las ubicaciones", "Incluya el Excel, las carpetas de fotos y una carpeta de destino."),
        ("Expanda el árbol", "Use la flecha de cada carpeta para revisar el contenido."),
        ("Refresque cuando sea necesario", "Si cambió algo desde el Explorador de Windows, pulse “Refrescar”."),
    ], 4)
    heading(doc, "Estructura de trabajo recomendada", 2)
    code_block(doc, "PRODUCCION_2026\\\n  501M\\\n    Excel\\501M.xlsx\n    Fotos_origen\\\n    Resultado\\\n  502M\\\n    Excel\\502M.xlsx\n    Fotos_origen\\\n    Resultado\\")
    callout(doc, "Evite ciclos", "No coloque la carpeta de destino dentro de una carpeta de origen que vaya a escanear. Use un destino vacío y separado para cada ejecución.", tone="red")

    section_page(doc, "Crear carpetas de alumnos", 6, "Paso opcional antes de clasificar.")
    paragraph(doc, "FaceSync puede crear automáticamente una carpeta por registro del Excel. Si omite este paso, el motor de clasificación también puede crear las carpetas necesarias en el destino.")
    new_numbered_list(doc, [
        ("Abra “Crear carpetas”", "Seleccione la acción rápida del Workspace."),
        ("Elija el Excel", "FaceSync muestra los Excel y CSV detectados en las raíces activas."),
        ("Seleccione la columna de nombres", "Use “Nombre del alumno” o la columna equivalente."),
        ("Seleccione el destino", "Elija la carpeta en la que se crearán las subcarpetas."),
        ("Revise la vista previa", "Confirme el número y los nombres de carpetas."),
        ("Pulse “Crear carpetas”", "Espere el resumen de creadas y total."),
    ], 5)
    callout(doc, "Nombres repetidos", "Si el Excel contiene nombres idénticos, FaceSync puede numerar las carpetas para evitar que una sobrescriba a otra. Aun así, conviene diferenciar los nombres en el Excel con grupo, matrícula o segundo apellido.", tone="purple")

    section_page(doc, "Clasificar fotografías", 7, "Selección del Excel, referencias, orígenes y destino.")
    heading(doc, "Configurar la clasificación", 2)
    new_numbered_list(doc, [
        ("Abra “Clasificar fotos”", "Se mostrará el formulario de reconocimiento facial por lotes."),
        ("Seleccione el Excel de referencia", "Verifique que sea el archivo del salón que va a procesar."),
        ("Seleccione la columna de nombres", "Normalmente “Nombre del alumno”."),
        ("Seleccione la columna de referencia", "Normalmente “Código de foto”."),
        ("Marque una o varias carpetas de origen", "Puede combinar varias sesiones o fotógrafos dentro del mismo lote."),
        ("Elija la carpeta destino", "Use una carpeta vacía, separada de los orígenes."),
        ("Confirme “Listo para clasificar”", "El botón se habilita cuando todos los datos requeridos están completos."),
        ("Pulse “Iniciar clasificación”", "Mantenga la aplicación abierta hasta ver el resumen final."),
    ], 6)
    heading(doc, "Qué hace FaceSync durante el proceso", 2)
    add_table(doc, ["Fase visible", "Qué sucede"], [
        ["Leyendo el Excel", "Carga alumnos, nombres de carpeta y códigos de referencia."],
        ["Escaneando las fotos", "Localiza archivos compatibles en todas las carpetas seleccionadas."],
        ["Buscando referencias", "Reúne los candidatos cuyo código coincide con el Excel y valida las caras."],
        ["Índice rápido de CR2", "Prepara vistas de trabajo para acelerar lotes RAW grandes."],
        ["Analizando rostros", "Detecta uno o varios rostros y calcula sus representaciones faciales."],
        ["Comparando identidades", "Compara las caras con las referencias y las galerías confirmadas."],
        ["Entregando fotos", "Copia JPG, CR2 y fotografías grupales a las carpetas correspondientes."],
        ["Generando reportes", "Escribe los reportes JSON, TXT y XLSX y finaliza el historial."],
    ], [2800, 6560])
    callout(doc, "El porcentaje puede avanzar por etapas", "Una fase compleja puede permanecer varios minutos en el mismo porcentaje mientras realiza auditorías internas. Esto no significa necesariamente que la aplicación esté congelada. Espere si la fase sigue activa, hay actividad de disco o el mensaje cambia.", tone="amber")

    section_page(doc, "Supervisar, cancelar y reanudar", 8)
    heading(doc, "Durante la clasificación", 2)
    for item in [
        "No cierre FaceSync ni apague el equipo.",
        "No renombre, mueva o elimine el Excel, los orígenes o el destino.",
        "No desconecte discos externos y evite que Windows suspenda la computadora.",
        "No inicie una segunda clasificación al mismo tiempo.",
        "Puede seguir la fase, el porcentaje, los nombres y las vistas de fotos en el modal.",
    ]:
        bullet(doc, item)
    heading(doc, "Cuando aparece “Entregando fotos”", 2)
    paragraph(doc, "El reconocimiento ya terminó y FaceSync está copiando los archivos físicos. En lotes CR2, discos externos o muchas fotos grupales, esta etapa puede ser extensa porque mueve más gigabytes y puede generar varias copias lógicas de una misma foto.")
    heading(doc, "Cancelar", 2)
    paragraph(doc, "Pulse “Cancelar” y espere a que el motor confirme la detención. La cancelación es cooperativa y puede tardar mientras termina una operación en curso. Los archivos ya copiados permanecen en el destino.")
    callout(doc, "Reintento seguro", "Después de cancelar o de un apagado, revise el destino. Para una repetición limpia, utilice una nueva carpeta vacía o elimine de forma controlada la salida incompleta después de conservar cualquier evidencia necesaria.", tone="red")
    heading(doc, "Lotes grandes", 2)
    paragraph(doc, "El tiempo depende del número de fotos únicas, resolución, proporción de CR2, velocidad del disco, GPU, cantidad de rostros por imagen, caché disponible y volumen de copia. No use una estimación fija como garantía; mida el equipo real con un lote representativo.")

    section_page(doc, "Resultados y reportes", 9)
    heading(doc, "Ventana final", 2)
    paragraph(doc, "Al terminar, FaceSync muestra las carpetas clasificadas, los archivos entregados y la efectividad operativa. También presenta una muestra visual y permite abrir la carpeta de destino.")
    callout(doc, "Cómo leer “Efectividad”", "Es un indicador de entrega operativa, no una probabilidad biométrica ni una garantía absoluta de exactitud. Siempre debe complementarse con la revisión de carpetas, conteos y advertencias del reporte.", tone="purple")
    heading(doc, "Por qué puede haber más entregas que fotos de origen", 2)
    paragraph(doc, "Una fotografía grupal reconocida para cinco alumnos se copia a cinco carpetas. Además, un JPG clasificado puede entregar también su CR2 gemelo. Por ello, el número de archivos entregados y el tamaño del destino pueden superar al lote original.")
    heading(doc, "Archivos generados", 2)
    add_table(doc, ["Reporte", "Uso recomendado"], [
        ["_reporte_facesync.xlsx", "Revisión operativa en Excel, filtros, conteos por alumno y seguimiento de incidencias."],
        ["_reporte_facesync.txt", "Lectura rápida del resultado, métricas principales y advertencias."],
        ["_reporte_facesync.json", "Auditoría técnica completa y trazabilidad detallada de decisiones."],
    ], [3000, 6360])
    heading(doc, "Sección “Reportes”", 2)
    paragraph(doc, "La sección permite filtrar por fecha, tipo y carpeta. Seleccione un reporte para ver origen, destino, analizadas, clasificadas y pendientes; use “Ver” para abrirlo o “Descargar” para guardar una copia.")
    heading(doc, "Control de calidad recomendado", 2)
    for item in [
        "Revise alumnos sin fotos, con una sola foto o con una cantidad anormalmente alta.",
        "Abra varias carpetas al azar y confirme identidad en retratos y grupales.",
        "Compare el total del Excel con las carpetas creadas.",
        "Lea las advertencias, referencias inválidas y errores de imagen.",
        "Conserve los tres reportes junto con la entrega final.",
    ]:
        bullet(doc, item)

    section_page(doc, "Códigos repetidos e historial de identidad", 10)
    paragraph(doc, "FaceSync incluye auditorías para resolver códigos que se repiten dentro de un lote o entre salones distintos. La aplicación compara todos los candidatos del código y utiliza un historial visual protegido por cuenta para evitar reutilizar por error la identidad de un salón anterior.")
    heading(doc, "Flujo recomendado entre salones", 2)
    new_numbered_list(doc, [
        ("Procese un primer salón limpio", "Use referencias correctas y compruebe el resultado antes de continuar."),
        ("Mantenga la misma cuenta", "El historial se separa por cuenta de FaceSync."),
        ("No borre los datos locales de FaceSync", "El registro de identidades es necesario para reconocer colisiones históricas."),
        ("Procese los siguientes salones", "Si reaparece un código, FaceSync compara la cara conocida con los nuevos candidatos."),
        ("Revise el reporte", "Confirme códigos repetidos históricos, referencias resueltas y cualquier advertencia."),
    ], 7)
    callout(doc, "La primera clasificación es la base", "Si el primer salón queda mal clasificado y se acepta sin revisión, el historial puede aprender una identidad incorrecta. La protección histórica es más confiable cuando la primera ejecución fue limpia y validada.", tone="red")
    heading(doc, "Qué puede romper la continuidad", 2)
    for item in [
        "Cambiar a otra cuenta de FaceSync para los salones de la misma producción.",
        "Borrar la carpeta de datos local, el caché completo o la base de identidad.",
        "Reinstalar o migrar de equipo sin trasladar los datos operativos acordados con soporte.",
        "Cambiar de forma masiva los nombres y códigos sin conservar una referencia clara.",
    ]:
        bullet(doc, item)

    section_page(doc, "Exportar a Google Drive", 11)
    paragraph(doc, "La exportación crea un respaldo de una carpeta del workspace en Google Drive. Solo está disponible cuando la cuenta autorizó el permiso correspondiente.")
    new_numbered_list(doc, [
        ("Abra “Exportaciones”", "Revise que la cuenta y la conexión estén activas."),
        ("Pulse “Nueva exportación”", "Se abrirá el selector de carpetas del workspace."),
        ("Navegue hasta el resultado", "Entre a la carpeta exacta que desea respaldar."),
        ("Pulse “Exportar a Drive”", "FaceSync mostrará progreso, subidos y total."),
        ("Espere el resumen", "Compruebe la carpeta creada en Drive y el historial de la aplicación."),
    ], 8)
    heading(doc, "Cancelar una exportación", 2)
    paragraph(doc, "Pulse “Cancelar” en la tarjeta de progreso. Los archivos que ya se subieron permanecen en Drive y el historial mostrará que la operación fue cancelada o parcial.")
    callout(doc, "Antes de reintentar", "Revise la carpeta parcial en Drive para evitar duplicados. Si es necesario, elimínela manualmente o elija una estrategia de reanudación acordada con soporte.", tone="amber")
    heading(doc, "Estados del historial", 2)
    paragraph(doc, "La vista muestra exportaciones completadas, archivos exportados y operaciones a Drive. Seleccione un registro para consultar origen, subidos, total, fecha, estado y tipo.")

    section_page(doc, "Asistente IA", 12)
    paragraph(doc, "El asistente entiende variantes de lenguaje natural, conserva memoria por cuenta y trabaja únicamente dentro de las raíces autorizadas del workspace. Puede ayudar a leer Excel, crear, copiar, mover, renombrar o eliminar elementos y guiar una clasificación.")
    heading(doc, "Pedir acciones con precisión", 2)
    add_table(doc, ["Necesidad", "Ejemplo recomendado"], [
        ["Crear", "Crea una carpeta llamada Entrega final dentro de 502M."],
        ["Mover", "Mueve la carpeta Frank de 502M a 501M."],
        ["Copiar", "Copia Selección de 501M dentro de Respaldos."],
        ["Eliminar", "Elimina la carpeta Frank que está dentro de 502M."],
        ["Leer Excel", "Lee 502M.xlsx y dime qué columnas y cuántos alumnos tiene."],
    ], [2200, 7160])
    callout(doc, "Si hay nombres repetidos", "Indique la carpeta padre o la ruta completa. Antes de confirmar una acción destructiva, lea la ruta exacta que muestra el asistente. Si no es la correcta, responda “no” y vuelva a especificarla.", tone="amber")
    heading(doc, "Controles del chat", 2)
    for item in [
        "Enter envía; Mayús + Enter crea una nueva línea.",
        "El botón “+” inicia una conversación nueva para la misma cuenta.",
        "Durante una respuesta, el botón de enviar cambia a un cuadrado para detenerla.",
        "Las acciones destructivas requieren confirmación.",
        "El asistente puede cometer errores; verifique siempre rutas y resultados.",
    ]:
        bullet(doc, item)

    section_page(doc, "Administrar archivos y carpetas", 13)
    heading(doc, "Menú contextual", 2)
    paragraph(doc, "Haga clic derecho sobre una carpeta o archivo para abrir las acciones disponibles.")
    add_table(doc, ["Acción", "Comportamiento"], [
        ["Nueva carpeta", "Crea una subcarpeta dentro de la ubicación seleccionada."],
        ["Agregar archivos", "Copia archivos elegidos hacia la carpeta."],
        ["Renombrar", "Cambia el nombre del elemento dentro del workspace."],
        ["Abrir en explorador", "Abre la ubicación en el Explorador de Windows."],
        ["Refrescar", "Vuelve a leer el contenido sin expandir carpetas cerradas."],
        ["Quitar del workspace", "Retira una raíz de FaceSync sin borrar sus archivos."],
        ["Eliminar", "Envía el elemento a la Papelera de reciclaje cuando está disponible."],
    ], [2500, 6860])
    callout(doc, "No confunda quitar con eliminar", "“Quitar del workspace” solo deja de mostrar la raíz. “Eliminar” actúa sobre el archivo o carpeta real. Lea la confirmación antes de continuar.", tone="red")
    heading(doc, "Arrastrar y soltar", 2)
    paragraph(doc, "Puede arrastrar archivos o carpetas a FaceSync para incorporar sus ubicaciones al workspace. Si la vista no cambia de inmediato, use “Refrescar”.")

    section_page(doc, "Buenas prácticas de producción", 14)
    heading(doc, "Organización", 2)
    for item in [
        "Use una carpeta independiente por escuela, salón y ejecución.",
        "Nombre el Excel igual que el salón y conserve una sola versión oficial.",
        "Mantenga separados origen, resultado y entrega aprobada.",
        "No mezcle en el mismo origen fotos de salones que no aparecen en el Excel, salvo que el flujo haya sido planeado para ello.",
        "Conserve reportes y una bitácora de fecha, operador, cuenta y equipo.",
    ]:
        bullet(doc, item)
    heading(doc, "Rendimiento", 2)
    for item in [
        "Use SSD y un puerto rápido para discos externos.",
        "Cierre editores pesados y procesos que consuman GPU, CPU o disco.",
        "No copie otros archivos grandes mientras FaceSync está entregando CR2.",
        "La primera ejecución calcula más información; las siguientes pueden reutilizar caché cuando los archivos no cambiaron.",
        "Si se edita, renombra o reemplaza una foto, FaceSync puede recalcularla porque cambió su identidad de archivo.",
    ]:
        bullet(doc, item)
    heading(doc, "Control de cambios", 2)
    paragraph(doc, "Antes de una temporada, pruebe la versión instalada con un salón representativo. Después de cualquier actualización, repita la prueba y compare el reporte con un resultado previamente aprobado.")

    section_page(doc, "Solución de problemas", 15)
    add_table(doc, ["Situación", "Qué revisar y qué hacer"], [
        ["El botón de clasificación está deshabilitado", "Complete Excel, columna de nombres, columna de referencia, al menos un origen y un destino."],
        ["El Excel o una carpeta no aparece", "Agregue su carpeta raíz al workspace y pulse Refrescar. Cierre el Excel antes de procesarlo."],
        ["Un alumno queda sin fotos", "Revise referencia en blanco, código inexistente, último número del archivo, rostro pequeño o referencia de otra persona."],
        ["Un alumno recibe demasiadas fotos", "Revise si la referencia es incorrecta, si existe un código repetido o si varias grupales lo incluyen. Consulte el XLSX y JSON."],
        ["El avance parece detenido cerca de 72%", "La app puede estar comparando y auditando identidades. Espere si hay actividad; no la cierre por el porcentaje solamente."],
        ["“Entregando fotos” tarda mucho", "La copia depende de gigabytes, CR2, disco externo y duplicación de grupales. Verifique espacio y conexión del disco."],
        ["Un CR2 no muestra vista previa", "El archivo puede carecer de JPEG integrado. Revise que no esté dañado; el motor intentará su ruta de respaldo."],
        ["Efectividad menor de 100%", "Abra el reporte y revise pendientes reales, errores, referencias inválidas y alumnos sin fotos. El porcentaje por sí solo no indica la causa."],
        ["No aparecen reportes", "Espere a que finalice, entre a Reportes y pulse Refrescar. También revise la carpeta de destino."],
        ["Drive queda parcial", "Compruebe internet, permiso de Drive, cuota y archivos ya subidos antes de reintentar."],
        ["El asistente elige una carpeta incorrecta", "Cancele, indique carpeta padre o ruta completa y confirme la ruta mostrada."],
        ["Se perdió la protección de códigos históricos", "Use la misma cuenta y verifique que no se borraron los datos locales de FaceSync. Si cambió de equipo, contacte soporte."],
    ], [3150, 6210], font_size=9.4)
    heading(doc, "Cuándo detener una entrega", 2)
    paragraph(doc, "No entregue el lote si faltan referencias, hay alumnos vacíos inesperados, un alumno concentra un volumen atípico, el reporte contiene errores de imagen o el destino se quedó sin espacio. Corrija la causa y vuelva a ejecutar en una carpeta limpia.")

    section_page(doc, "Preguntas frecuentes", 16)
    faqs = [
        ("¿Puede clasificar un lote compuesto solo por CR2?", "Sí. El motor convierte internamente una representación de trabajo sin modificar el RAW original."),
        ("¿Puedo mezclar JPG y CR2?", "Sí. Cuando comparten nombre base, FaceSync procura entregar ambos juntos."),
        ("¿Puedo seleccionar varias carpetas de origen?", "Sí. El modal permite marcar una o varias carpetas para tratarlas como un mismo lote."),
        ("¿Las fotos grupales llegan a más de un alumno?", "Sí. Una misma fotografía puede copiarse a cada carpeta donde se reconoció a una persona del Excel."),
        ("¿FaceSync modifica los originales?", "No durante la clasificación: analiza y copia. Las herramientas de administración sí pueden mover, renombrar o eliminar cuando el usuario lo solicita y confirma."),
        ("¿Puedo poner varios códigos en una celda?", "No. Use una sola referencia por alumno."),
        ("¿Puedo cerrar la aplicación durante el proceso?", "No. Espere el resumen final o utilice Cancelar y espere su confirmación."),
        ("¿La clasificación necesita internet?", "El cálculo facial es local. Google, el asistente y Drive requieren conexión."),
        ("¿Por qué el destino pesa más que el origen?", "Por copias de fotografías grupales en varias carpetas y por la entrega conjunta de pares JPG + CR2."),
        ("¿Los códigos repetidos están contemplados?", "Sí, mediante auditorías visuales e historial por cuenta. La primera ejecución limpia debe revisarse y conservarse."),
        ("¿La sesión queda iniciada?", "Sí. FaceSync recuerda la última cuenta; para cambiarla use Cerrar sesión."),
    ]
    for question, answer in faqs:
        heading(doc, question, 3)
        paragraph(doc, answer, after=7)

    section_page(doc, "Listas de control", 17)
    heading(doc, "Antes de clasificar", 2)
    for item in [
        "Excel correcto, guardado y cerrado.",
        "Una fila y una referencia por alumno.",
        "Código coincide con el último bloque numérico del archivo.",
        "Rostros de referencia visibles.",
        "Orígenes y destino agregados al workspace.",
        "Destino vacío y separado del origen.",
        "Espacio libre, corriente y discos externos estables.",
        "Misma cuenta usada para la producción y su historial.",
    ]:
        bullet(doc, item)
    heading(doc, "Antes de entregar", 2)
    for item in [
        "La aplicación mostró clasificación completada.",
        "El número de carpetas coincide con los alumnos esperados.",
        "Se revisaron alumnos vacíos, con pocas fotos o con demasiadas.",
        "Se verificaron muestras de retratos y grupales.",
        "Se revisaron advertencias, referencias y errores del reporte.",
        "Se conservaron JSON, TXT y XLSX.",
        "Se comprobó el respaldo o exportación a Drive, si aplica.",
        "La carpeta aprobada quedó separada de cualquier salida incompleta.",
    ]:
        bullet(doc, item)
    callout(doc, "Criterio de cierre", "Una clasificación termina cuando el resultado fue revisado y documentado, no únicamente cuando la barra llega al 100%.", tone="green")

    section_page(doc, "Soporte y cierre", 18)
    paragraph(doc, "Si una incidencia no se resuelve con este manual, conserve el Excel utilizado, la ruta de las carpetas de origen y destino, los tres reportes, una captura del mensaje y la hora aproximada del evento. No renombre ni elimine estos elementos hasta que soporte termine el diagnóstico.")
    heading(doc, "Información que debe enviar", 2)
    for item in [
        "Nombre de la agencia, salón y operador.",
        "Versión de FaceSync y versión de Windows.",
        "Cantidad y formatos aproximados del lote.",
        "Fase o porcentaje donde ocurrió el problema.",
        "Mensaje exacto mostrado por la aplicación.",
        "Reportes JSON, TXT y XLSX de la ejecución.",
        "Indique si el disco es interno o externo y cuánto espacio libre conserva.",
    ]:
        bullet(doc, item)
    callout(doc, "Contacto", "Ian Carlo — Desarrollador de FaceSync — Hermosillo, Sonora. Utilice el canal de soporte acordado durante la entrega de la licencia.", tone="purple")
    paragraph(doc, "FaceSync fue diseñado para convertir semanas de clasificación manual en un flujo controlado de preparación, procesamiento, auditoría y entrega. La disciplina del operador y la calidad de las referencias completan la tecnología.", italic=True, color=MUTED, align=WD_ALIGN_PARAGRAPH.CENTER, after=6)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("© 2026 FaceSync. Todos los derechos reservados."), size=9, color=MUTED)

    doc.core_properties.title = "Manual de Usuario FaceSync"
    doc.core_properties.subject = "Guía operativa completa de FaceSync 1.0.0"
    doc.core_properties.author = "Ian Carlo — FaceSync"
    doc.core_properties.keywords = "FaceSync, manual, clasificación, fotografías, CR2, JPG"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build_manual()
