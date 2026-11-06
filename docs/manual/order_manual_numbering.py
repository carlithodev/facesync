from __future__ import annotations

import argparse
import re
from pathlib import Path

from docx import Document


def first_text_run(paragraph):
    for run in paragraph.runs:
        if run.text:
            return run
    raise RuntimeError(f"El párrafo no contiene texto: {paragraph.text!r}")


def prefix_paragraph(paragraph, prefix: str) -> None:
    run = first_text_run(paragraph)
    if not paragraph.text.lstrip().startswith(prefix):
        run.text = prefix + run.text


def replace_fragment(paragraph, old: str, new: str) -> None:
    for run in paragraph.runs:
        if old in run.text:
            run.text = run.text.replace(old, new, 1)
            return
    raise RuntimeError(f"No se encontró {old!r} en {paragraph.text!r}")


def renumber_heading(paragraph, expected: int, new_number: int) -> None:
    text = paragraph.text.strip()
    if not re.match(rf"^{expected}\.\s+", text):
        raise RuntimeError(
            f"Se esperaba una sección que comenzara con {expected}. y se encontró {text!r}"
        )
    run = first_text_run(paragraph)
    run.text = re.sub(rf"^(\s*){expected}\.", rf"\g<1>{new_number}.", run.text, count=1)


def set_cell_text(cell, text: str) -> None:
    paragraph = cell.paragraphs[0]
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)
    for extra in cell.paragraphs[1:]:
        for run in extra.runs:
            run.text = ""


def find_contents_table(doc: Document):
    for table in doc.tables:
        if not table.rows or len(table.rows[0].cells) < 2:
            continue
        first = table.rows[0].cells[0].text.strip().casefold()
        second = table.rows[0].cells[1].text.strip().casefold()
        if first == "sección" and second == "tema":
            return table
    raise RuntimeError("No se encontró la tabla de contenido.")


def update_contents(doc: Document) -> None:
    entries = [
        ("1", "Inicio rápido"),
        ("2", "Instalación, inicio de sesión y cuenta"),
        ("3", "Conocer la interfaz"),
        ("4", "Preparar el Excel"),
        ("5", "Preparar fotografías y workspace"),
        ("6", "Supervisar, cancelar y reanudar"),
        ("7", "Resultados y reportes"),
        ("8", "Códigos repetidos e historial de identidad"),
        ("9", "Exportar a Google Drive"),
        ("10", "Asistente IA"),
        ("11", "Administrar archivos y carpetas"),
        ("12", "Buenas prácticas de producción"),
        ("13", "Preguntas frecuentes"),
        ("14", "Listas de control"),
    ]
    table = find_contents_table(doc)
    if len(table.rows) - 1 < len(entries):
        raise RuntimeError("La tabla de contenido no tiene suficientes filas.")
    for row, (number, title) in zip(table.rows[1:], entries):
        set_cell_text(row.cells[0], number)
        set_cell_text(row.cells[1], title)
    while len(table.rows) - 1 > len(entries):
        table._tbl.remove(table.rows[-1]._tr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    doc = Document(args.source)
    original_paragraphs = len(doc.paragraphs)
    original_tables = len(doc.tables)
    original_drawings = len(doc.element.xpath(".//w:drawing"))
    original_body_tags = [element.tag for element in doc.element.body.iterchildren()]

    # Pasos del inicio rápido: únicamente se añaden o corrigen sus números.
    replace_fragment(doc.paragraphs[22], "ocho", "siete")
    for index, prefix in [
        (23, "1. "),
        (24, "2. "),
        (31, "3. "),
        (40, "4. "),
        (49, "5. "),
        (50, "5.1 "),
        (56, "5.2 "),
        (76, "6. "),
        (103, "7. "),
    ]:
        prefix_paragraph(doc.paragraphs[index], prefix)
    replace_fragment(doc.paragraphs[179], "22.1", "3.1")

    # Los cinco primeros capítulos ya estaban correctos; se cierran los saltos restantes.
    for paragraph_index, old_number, new_number in [
        (245, 8, 6),
        (260, 9, 7),
        (263, 10, 8),
        (278, 11, 9),
        (291, 12, 10),
        (303, 13, 11),
        (311, 14, 12),
        (325, 16, 13),
        (343, 17, 14),
    ]:
        renumber_heading(doc.paragraphs[paragraph_index], old_number, new_number)

    update_contents(doc)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.output)

    final = Document(args.output)
    assert len(final.paragraphs) == original_paragraphs
    assert len(final.tables) == original_tables
    assert len(final.element.xpath(".//w:drawing")) == original_drawings
    assert [element.tag for element in final.element.body.iterchildren()] == original_body_tags
    print(f"Documento ordenado: {args.output}")
    print(f"Párrafos conservados: {len(final.paragraphs)}")
    print(f"Tablas conservadas: {len(final.tables)}")
    print(f"Imágenes conservadas: {original_drawings}")


if __name__ == "__main__":
    main()
