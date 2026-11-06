from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import _Cell
from docx.text.paragraph import Paragraph


def paragraph_from_element(element, doc: Document) -> Paragraph:
    return Paragraph(element, doc._body)


def set_plain_paragraph(paragraph: Paragraph, text: str) -> None:
    target = next(
        (
            run
            for run in paragraph.runs
            if run.text and not run._r.xpath(".//w:drawing")
        ),
        None,
    )
    if target is None:
        target = next(
            (run for run in paragraph.runs if not run._r.xpath(".//w:drawing")),
            None,
        )
    if target is None:
        target = paragraph.add_run()
    target.text = text
    for run in paragraph.runs:
        if run._r is not target._r and not run._r.xpath(".//w:drawing"):
            run.text = ""


def prefix_first_text_run(paragraph: Paragraph, prefix: str) -> None:
    for run in paragraph.runs:
        if run.text:
            run.text = prefix + run.text
            return
    paragraph.add_run(prefix)


def set_cell_text(cell: _Cell, text: str) -> None:
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


def move_after(anchor, elements) -> None:
    current = anchor
    for element in elements:
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
        current.addnext(element)
        current = element


def remove_elements(elements) -> None:
    for element in elements:
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)


def assert_paragraph(element, doc: Document, starts_with: str) -> None:
    paragraph = paragraph_from_element(element, doc)
    actual = " ".join(paragraph.text.split())
    if not actual.startswith(starts_with):
        raise RuntimeError(
            f"La estructura del manual cambió. Se esperaba '{starts_with}' y se encontró '{actual}'."
        )


def find_contents_table(doc: Document):
    for table in doc.tables:
        if not table.rows or len(table.rows[0].cells) < 2:
            continue
        first = " ".join(table.rows[0].cells[0].text.split()).casefold()
        second = " ".join(table.rows[0].cells[1].text.split()).casefold()
        if first == "sección" and second == "tema":
            return table
    raise RuntimeError("No se encontró la tabla de contenido.")


def update_contents(doc: Document) -> None:
    table = find_contents_table(doc)
    rows = [
        ("1", "Inicio rápido"),
        ("2", "Instalación y requisitos operativos"),
        ("3", "Conocer la interfaz"),
        ("4", "Preparar el Excel"),
        ("5", "Resultados y reportes"),
        ("6", "Códigos repetidos e historial de identidad"),
        ("7", "Asistente IA"),
        ("8", "Administrar archivos y carpetas"),
        ("9", "Buenas prácticas de producción"),
        ("10", "Preguntas frecuentes"),
        ("11", "Listas de control"),
    ]
    while len(table.rows) - 1 > len(rows):
        table._tbl.remove(table.rows[-1]._tr)
    if len(table.rows) - 1 != len(rows):
        raise RuntimeError("La tabla de contenido no tiene suficientes filas para actualizarse.")
    for row, (number, title) in zip(table.rows[1:], rows):
        set_cell_text(row.cells[0], number)
        set_cell_text(row.cells[1], title)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    doc = Document(args.source)
    original_drawings = len(doc.element.xpath(".//w:drawing"))
    body = doc.element.body
    blocks = list(body.iterchildren())
    if len(blocks) != 417:
        raise RuntimeError(f"Se esperaban 417 bloques y se encontraron {len(blocks)}.")

    # Anclas principales: estas comprobaciones evitan editar otro archivo por accidente.
    assert_paragraph(blocks[25], doc, "1. Inicio rápido")
    assert_paragraph(blocks[128], doc, "2. Instalación")
    assert_paragraph(blocks[196], doc, "4. Preparar el Excel")
    assert_paragraph(blocks[240], doc, "5. Preparar fotografías")
    assert_paragraph(blocks[259], doc, "6. Crear carpetas")
    assert_paragraph(blocks[271], doc, "7. Clasificar fotografías")
    assert_paragraph(blocks[288], doc, "8. Supervisar")
    assert_paragraph(blocks[324], doc, "11. Exportar a Google Drive")

    # Consolidación: se mueven, no se duplican, los detalles existentes hacia
    # los pasos visuales correspondientes.
    move_after(blocks[27], blocks[241:248])  # Formatos y calidad -> Preparar el lote.
    move_after(blocks[34], blocks[140:145])  # Sesión -> captura de inicio de sesión.
    move_after(blocks[43], blocks[248:257])  # Workspace -> captura del workspace.
    move_after(blocks[52], blocks[223:239])  # Validación del Excel -> captura del Excel.
    move_after(blocks[79], [*blocks[263:267], blocks[268]])  # Crear carpetas.
    move_after(blocks[89], blocks[275:281])  # Configurar clasificación.
    move_after(
        blocks[118],
        [*blocks[282:286], blocks[289], *blocks[293:303]],
    )  # Fases, supervisión, cancelación y lotes grandes.
    move_after(
        blocks[194],
        [blocks[324], blocks[325], *blocks[328:337]],
    )  # Exportación a Drive junto a sus capturas.

    # Eliminar únicamente encabezados, frases o separadores que ya quedaron
    # representados en la explicación visual.
    remove_elements(
        [
            blocks[125],  # Recomendación repetida sobre separar destino y origen.
            blocks[240],
            blocks[257],
            blocks[258],
            blocks[259],
            blocks[260],
            blocks[261],
            blocks[262],
            blocks[267],
            blocks[269],
            blocks[270],
            blocks[271],
            blocks[272],
            blocks[273],
            blocks[274],
            blocks[281],
            blocks[286],
            blocks[287],
            blocks[288],
            blocks[290],
            blocks[291],
            blocks[292],
            blocks[303],
            blocks[326],
            blocks[327],
            blocks[337],
        ]
    )

    # Numeración y correcciones editoriales sin añadir información nueva.
    set_plain_paragraph(paragraph_from_element(blocks[26], doc), "El flujo completo en siete decisiones.")
    prefix_first_text_run(paragraph_from_element(blocks[27], doc), "1. ")
    prefix_first_text_run(paragraph_from_element(blocks[28], doc), "2. ")
    prefix_first_text_run(paragraph_from_element(blocks[35], doc), "3. ")
    workspace_p = paragraph_from_element(blocks[35], doc)
    for run in workspace_p.runs:
        if "una carpeta para un salón en especial" in run.text:
            run.text = run.text.replace(
                "una carpeta para un salón en especial", "una carpeta de destino para el salón"
            )
    prefix_first_text_run(paragraph_from_element(blocks[44], doc), "4. ")
    prefix_first_text_run(paragraph_from_element(blocks[53], doc), "5. ")
    set_plain_paragraph(
        paragraph_from_element(blocks[54], doc),
        "5.1 Abra la acción rápida “Crear carpetas”.",
    )
    set_plain_paragraph(
        paragraph_from_element(blocks[60], doc),
        "5.2 Seleccione las opciones necesarias para crear las carpetas utilizando la columna de nombres del Excel elegido.",
    )
    set_plain_paragraph(
        paragraph_from_element(blocks[70], doc),
        "5.3 Pulse el botón “Crear” para generar las carpetas en el destino.",
    )
    classify_p = paragraph_from_element(blocks[80], doc)
    prefix_first_text_run(classify_p, "6. ")
    classify_p.runs[1].text = (
        "Elija el Excel, las columnas, una o varias carpetas de origen y la carpeta de destino "
    )
    classify_p.runs[2].text = "donde se crearon las carpetas desde el "
    classify_p.runs[3].text = "Excel"
    classify_p.runs[4].text = "."
    set_plain_paragraph(
        paragraph_from_element(blocks[90], doc),
        "6.1 Pulse “Iniciar clasificación”.",
    )
    prefix_first_text_run(paragraph_from_element(blocks[107], doc), "7. ")
    set_plain_paragraph(
        paragraph_from_element(blocks[187], doc),
        "3.1 Seleccione “Nueva exportación” y la carpeta que desee exportar.",
    )
    drive_heading = paragraph_from_element(blocks[324], doc)
    drive_heading.style = doc.styles["Heading 2"]
    set_plain_paragraph(drive_heading, "Exportar a Google Drive")

    # Correcciones ortográficas y de claridad sobre frases ya existentes.
    set_plain_paragraph(
        paragraph_from_element(blocks[244], doc),
        "Evite usar como referencia una fotografía donde otra persona u objeto cubra el rostro del alumno.",
    )
    set_plain_paragraph(
        paragraph_from_element(blocks[206], doc),
        "Seleccione el nombre del archivo y dónde quiere guardarlo. FaceSync agrega automáticamente la extensión .xlsx.",
    )
    set_plain_paragraph(
        paragraph_from_element(blocks[229], doc),
        "FaceSync busca el último bloque numérico del nombre de archivo. Por ello, la referencia 2411 puede localizar IMG_2411.JPG o IMG_2411.CR2. Evite agregar otro número después del código de la foto.",
    )
    set_plain_paragraph(
        paragraph_from_element(blocks[279], doc),
        "Elija la carpeta de destino. Use una carpeta vacía, separada de los orígenes.",
    )
    set_plain_paragraph(
        paragraph_from_element(blocks[372], doc),
        "No copie otros archivos grandes mientras FaceSync está entregando.",
    )
    set_plain_paragraph(
        paragraph_from_element(blocks[121], doc),
        "Recomendaciones al usar la aplicación (opcional)",
    )

    # Encabezados principales consecutivos.
    heading_updates = {
        128: "2. Instalación y requisitos operativos",
        304: "5. Resultados y reportes",
        308: "6. Códigos repetidos e historial de identidad",
        338: "7. Asistente IA",
        352: "8. Administrar archivos y carpetas",
        362: "9. Buenas prácticas de producción",
        376: "10. Preguntas frecuentes",
        394: "11. Listas de control",
    }
    for index, text in heading_updates.items():
        set_plain_paragraph(paragraph_from_element(blocks[index], doc), text)

    update_contents(doc)

    # Metadatos de accesibilidad; no alteran el contenido visible.
    for doc_pr in doc.element.xpath(".//wp:docPr"):
        if not doc_pr.get("descr"):
            doc_pr.set("descr", "Captura de pantalla de FaceSync")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.output)

    final = Document(args.output)
    final_drawings = len(final.element.xpath(".//w:drawing"))
    if original_drawings != final_drawings:
        raise RuntimeError(
            f"Cambió la cantidad de imágenes: {original_drawings} -> {final_drawings}."
        )
    print(f"Documento final: {args.output}")
    print(f"Bloques finales: {len(list(final.element.body.iterchildren()))}")
    print(f"Imágenes conservadas: {final_drawings}")
    print(f"Tablas conservadas: {len(final.tables)}")


if __name__ == "__main__":
    main()
