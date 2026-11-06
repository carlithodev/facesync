from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn


def compact(value: str, limit: int = 240) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=10_000)
    args = parser.parse_args()

    doc = Document(args.docx)
    paragraph_positions = {id(p._p): i for i, p in enumerate(doc.paragraphs)}
    table_positions = {id(t._tbl): i for i, t in enumerate(doc.tables)}

    for body_index, child in enumerate(doc.element.body.iterchildren()):
        if not (args.start <= body_index < args.end):
            continue
        if child.tag == qn("w:p"):
            p_index = paragraph_positions.get(id(child), -1)
            paragraph = next((p for p in doc.paragraphs if p._p is child), None)
            if paragraph is None:
                continue
            drawings = len(child.xpath(".//w:drawing"))
            page_breaks = len(child.xpath(".//w:br[@w:type='page']"))
            style = paragraph.style.name if paragraph.style else ""
            print(
                f"B{body_index:03d} P{p_index:03d} {style:20} "
                f"img={drawings} pb={page_breaks} | {compact(paragraph.text)}"
            )
        elif child.tag == qn("w:tbl"):
            table = next((t for t in doc.tables if t._tbl is child), None)
            if table is None:
                continue
            t_index = table_positions.get(id(child), -1)
            first_row = " | ".join(compact(cell.text, 80) for cell in table.rows[0].cells)
            print(
                f"B{body_index:03d} T{t_index:03d} rows={len(table.rows)} "
                f"cols={len(table.columns)} | {first_row}"
            )
        else:
            print(f"B{body_index:03d} {child.tag}")


if __name__ == "__main__":
    main()
