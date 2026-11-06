
"""
======================================================================
MÓDULO: DOCUMENT CAPABILITIES — FaceSync AI Tools
Archivo: tools/document_tools.py
======================================================================

Responsabilidad:
- Lectura inteligente de documentos multiformato.
- Extracción de contenido estructurado.
- Automatización basada en documentos.
- Compatibilidad extensible para IA y agentes.

Capacidades:
✔ Leer Excel / CSV
✔ Leer PDF
✔ Leer TXT / JSON / DOCX
✔ Extraer metadata
✔ Crear carpetas automáticamente desde documentos
✔ Validación de seguridad sandbox
✔ Arquitectura preparada para Gemini / ChatGPT / Claude

NOTA:
Este módulo NO reemplaza tus scripts viejos.
Es una capa profesional orientada a agentes IA.

======================================================================
"""

from __future__ import annotations

import os
import json
import re
import logging
import shutil
import unicodedata
import csv
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Union, Dict, List, Any
from tools.tool_result import tool_error, tool_result

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except Exception:
    pd = None
    PANDAS_AVAILABLE = False

from core.security import SecurityManager

# ============================================================
# IMPORTS OPCIONALES
# ============================================================

try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    import docx
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger("FaceSync.DocumentTools")


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class DocumentCapabilities:
    """
    Sistema avanzado de lectura y procesamiento documental.

    Diseñado para:
    - Agentes IA
    - Automatización empresarial
    - Procesamiento de archivos heterogéneos
    - Integración con FaceSync

    Soporta:
    - Excel
    - CSV
    - PDF
    - TXT
    - JSON
    - DOCX
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        workspace_path: str,
        security_manager: Optional[SecurityManager] = None
    ):
        """
        Inicializa el sistema documental.

        Args:
            workspace_path (str):
                Ruta base segura del workspace.

            security_manager (Optional[SecurityManager]):
                Motor de seguridad compartido.
        """

        self.workspace_path = Path(workspace_path).resolve()

        self.security = security_manager or SecurityManager(workspace_path=str(self.workspace_path))
        if Path(getattr(self.security, "workspace_path", self.workspace_path)).resolve() != self.workspace_path:
            self.security = SecurityManager(
                workspace_path=str(self.workspace_path),
                app_data_root=getattr(self.security, "app_data_path", None),
            )

    def set_project_root(self, project_root: str):
        self.workspace_path = Path(project_root).resolve()
        if hasattr(self.security, "set_project_root"):
            self.security.set_project_root(str(self.workspace_path))
        else:
            self.security = SecurityManager(workspace_path=str(self.workspace_path))

    def set_workspace(self, workspace_path: str):
        self.set_project_root(workspace_path)

    # ========================================================
    # SEGURIDAD INTERNA
    # ========================================================

    def _resolve_secure_path(
        self,
        path: str
    ) -> Path:
        """
        Valida y resuelve una ruta segura.

        Raises:
            PermissionError
        """

        path_str = str(path)

        secure_path = self.security.secure_path(path_str)

        if not secure_path:
            raise PermissionError(
                f"Ruta insegura detectada: {path_str}"
            )

        return Path(secure_path)

    # ========================================================
    # DETECCIÓN DE TIPO
    # ========================================================

    def detect_document_type(
        self,
        path: str
    ) -> str:
        """
        Detecta automáticamente el tipo documental.

        Returns:
            str
        """

        extension = Path(path).suffix.lower()

        mapping = {
            ".xlsx": "excel",
            ".xls": "excel",
            ".csv": "csv",
            ".pdf": "pdf",
            ".txt": "text",
            ".json": "json",
            ".docx": "docx"
        }

        return mapping.get(extension, "unknown")

    # ========================================================
    # LECTURA UNIVERSAL
    # ========================================================

    def read_document(
        self,
        path: str
    ) -> Dict[str, Any]:
        """
        Lee automáticamente cualquier documento soportado.

        Returns:
            Dict estructurado.
        """

        try:
            secure_path = self._resolve_secure_path(path)

            if not secure_path.exists():
                return {
                    "success": False,
                    "error": "El documento no existe."
                }

            doc_type = self.detect_document_type(secure_path)

            if doc_type == "excel":
                return self.read_excel(secure_path, sheet_name=0)

            elif doc_type == "csv":
                return self.read_csv(secure_path)

            elif doc_type == "pdf":
                return self.read_pdf(secure_path)

            elif doc_type == "text":
                return self.read_text(secure_path)

            elif doc_type == "json":
                return self.read_json(secure_path)

            elif doc_type == "docx":
                return self.read_docx(secure_path)

            return {
                "success": False,
                "error": f"Formato no soportado: {doc_type}"
            }

        except Exception as e:
            logger.exception("Error leyendo documento")
            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # EXCEL
    # ========================================================

    def read_excel(
        self,
        path: str,
        sheet_name: Optional[Union[str, int]] = 0
    ) -> Dict[str, Any]:
        """
        Lee archivos Excel.

        Returns:
            Dict estructurado.
        """

        try:
            if not PANDAS_AVAILABLE:
                secure_path = self._resolve_secure_path(path)
                if secure_path.suffix.lower() == ".xlsx":
                    rows = self._read_xlsx_rows(secure_path)
                    columns = list(rows[0].keys()) if rows else []
                    return {
                        "success": True,
                        "type": "excel",
                        "rows": len(rows),
                        "columns": columns,
                        "preview": rows[:100],
                        "data": rows[:100]
                    }
                return {
                    "success": False,
                    "error": "pandas/xlrd no esta instalado para leer archivos .xls."
                }

            secure_path = self._resolve_secure_path(path)

            df = pd.read_excel(
                secure_path,
                sheet_name=sheet_name
            )

            if isinstance(df, dict):
                sheets = {
                    name: sheet.head(50).to_dict(orient="records")
                    for name, sheet in df.items()
                }

                return {
                    "success": True,
                    "type": "excel",
                    "multiple_sheets": True,
                    "sheets": list(df.keys()),
                    "data": sheets
                }

            preview = df.head(100).to_dict(orient="records")
            return {
                "success": True,
                "type": "excel",
                "rows": len(df),
                "columns": list(df.columns),
                "preview": preview,
                "data": preview
            }

        except Exception as e:
            logger.exception("Error leyendo Excel")

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # CSV
    # ========================================================

    def read_csv(
        self,
        path: str
    ) -> Dict[str, Any]:
        """
        Lee archivos CSV.
        """

        try:
            secure_path = self._resolve_secure_path(path)

            if not PANDAS_AVAILABLE:
                rows = self._read_csv_rows(secure_path)
                columns = list(rows[0].keys()) if rows else []
                return {
                    "success": True,
                    "type": "csv",
                    "rows": len(rows),
                    "columns": columns,
                    "preview": rows[:100],
                    "data": rows[:100]
                }

            df = pd.read_csv(secure_path)

            preview = df.head(100).to_dict(orient="records")
            return {
                "success": True,
                "type": "csv",
                "rows": len(df),
                "columns": list(df.columns),
                "preview": preview,
                "data": preview
            }

        except Exception as e:
            logger.exception("Error leyendo CSV")

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # PDF
    # ========================================================

    def read_pdf(
        self,
        path: str
    ) -> Dict[str, Any]:
        """
        Extrae texto de PDF.
        """

        try:
            if not PDF_AVAILABLE:
                return {
                    "success": False,
                    "error": "PyPDF2 no instalado."
                }

            secure_path = self._resolve_secure_path(path)

            text_content = []

            with open(secure_path, "rb") as file:
                reader = PyPDF2.PdfReader(file)

                total_pages = len(reader.pages)

                for page in reader.pages:
                    text_content.append(
                        page.extract_text() or ""
                    )

            return {
                "success": True,
                "type": "pdf",
                "pages": total_pages,
                "content": "\n".join(text_content)
            }

        except Exception as e:
            logger.exception("Error leyendo PDF")

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # TXT
    # ========================================================

    def read_text(
        self,
        path: str
    ) -> Dict[str, Any]:
        """
        Lee archivos TXT.
        """

        try:
            secure_path = self._resolve_secure_path(path)

            content = secure_path.read_text(
                encoding="utf-8",
                errors="replace"
            )

            return {
                "success": True,
                "type": "text",
                "content": content
            }

        except Exception as e:
            logger.exception("Error leyendo TXT")

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # JSON
    # ========================================================

    def read_json(
        self,
        path: str
    ) -> Dict[str, Any]:
        """
        Lee archivos JSON.
        """

        try:
            secure_path = self._resolve_secure_path(path)

            with open(
                secure_path,
                "r",
                encoding="utf-8"
            ) as file:

                data = json.load(file)

            return {
                "success": True,
                "type": "json",
                "data": data
            }

        except Exception as e:
            logger.exception("Error leyendo JSON")

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # DOCX
    # ========================================================

    def read_docx(
        self,
        path: str
    ) -> Dict[str, Any]:
        """
        Lee documentos Word.
        """

        try:
            if not DOCX_AVAILABLE:
                return {
                    "success": False,
                    "error": "python-docx no instalado."
                }

            secure_path = self._resolve_secure_path(path)

            document = docx.Document(secure_path)

            text = []

            for paragraph in document.paragraphs:
                text.append(paragraph.text)

            return {
                "success": True,
                "type": "docx",
                "content": "\n".join(text)
            }

        except Exception as e:
            logger.exception("Error leyendo DOCX")

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # METADATA
    # ========================================================

    def extract_metadata(
        self,
        path: str
    ) -> Dict[str, Any]:
        """
        Extrae metadata básica del archivo.
        """

        try:
            secure_path = self._resolve_secure_path(path)

            stats = secure_path.stat()

            return {
                "success": True,
                "name": secure_path.name,
                "extension": secure_path.suffix,
                "size_bytes": stats.st_size,
                "created": stats.st_ctime,
                "modified": stats.st_mtime,
                "absolute_path": str(secure_path)
            }

        except Exception as e:
            logger.exception("Error extrayendo metadata")

            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # EXCEL -> CARPETAS
    # ========================================================

    def _normalize_column_name(self, value: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _sanitize_folder_value(self, value: Any) -> str:
        name = re.sub(r"\s+", " ", str(value or "").strip())
        name = re.sub(r'[<>:"|?*]+', "", name)
        name = re.sub(r"[/\\]+", " - ", name)
        name = re.sub(r"\s*-\s*", " - ", name)
        name = re.sub(r"\s+", " ", name).strip().strip(".")
        if len(name) > 120:
            name = name[:120].rstrip()
        return name

    def _detect_student_column(self, columns: List[Any]) -> Optional[str]:
        candidates = [
            "alumno",
            "alumnos",
            "nombre",
            "nombres",
            "nombre completo",
            "estudiante",
            "estudiante nombre",
            "nombre del alumno",
        ]
        normalized_candidates = {self._normalize_column_name(item) for item in candidates}

        normalized_columns = {
            self._normalize_column_name(column): column
            for column in columns
        }

        for candidate in normalized_candidates:
            if candidate in normalized_columns:
                return normalized_columns[candidate]

        for normalized, original in normalized_columns.items():
            if "alumno" in normalized or "estudiante" in normalized:
                return original
            if normalized in ("nombre completo", "nombre"):
                return original

        return None

    def _detect_reference_column(self, columns: List[Any]) -> Optional[str]:
        candidates = [
            "foto",
            "referencia",
            "no foto",
            "no. foto",
            "numero foto",
            "numero de referencia",
            "imagen",
            "archivo",
            "foto referencia",
        ]
        normalized_candidates = {self._normalize_column_name(item) for item in candidates}
        normalized_columns = {
            self._normalize_column_name(column): column
            for column in columns
        }

        for candidate in normalized_candidates:
            if candidate in normalized_columns:
                return normalized_columns[candidate]

        for normalized, original in normalized_columns.items():
            if "referencia" in normalized:
                return original
            if "foto" in normalized or "imagen" in normalized:
                return original
            if normalized in ("archivo", "numero"):
                return original

        return None

    def _read_csv_rows(self, path: Path) -> List[Dict[str, Any]]:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")
        reader = csv.DictReader(text.splitlines())
        return [dict(row) for row in reader]

    def _read_xlsx_rows(self, path: Path) -> List[Dict[str, Any]]:
        with zipfile.ZipFile(path) as archive:
            shared_strings = self._read_xlsx_shared_strings(archive)
            sheet_path = self._first_xlsx_sheet_path(archive)
            with archive.open(sheet_path) as sheet_file:
                root = ET.parse(sheet_file).getroot()

        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        matrix: List[List[str]] = []
        for row in root.findall(".//x:sheetData/x:row", ns):
            values: List[str] = []
            for cell in row.findall("x:c", ns):
                column_index = self._xlsx_column_index(cell.attrib.get("r", ""))
                while len(values) <= column_index:
                    values.append("")
                values[column_index] = self._xlsx_cell_value(cell, shared_strings)
            matrix.append(values)

        matrix = [row for row in matrix if any(str(value).strip() for value in row)]
        if not matrix:
            return []

        headers = [str(value).strip() or f"Column {index + 1}" for index, value in enumerate(matrix[0])]
        rows: List[Dict[str, Any]] = []
        for raw_row in matrix[1:]:
            item = {}
            for index, header in enumerate(headers):
                item[header] = raw_row[index] if index < len(raw_row) else ""
            if any(str(value).strip() for value in item.values()):
                rows.append(item)
        return rows

    def _read_xlsx_shared_strings(self, archive: zipfile.ZipFile) -> List[str]:
        try:
            with archive.open("xl/sharedStrings.xml") as file:
                root = ET.parse(file).getroot()
        except KeyError:
            return []

        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        strings: List[str] = []
        for item in root.findall("x:si", ns):
            strings.append("".join(node.text or "" for node in item.findall(".//x:t", ns)))
        return strings

    def _first_xlsx_sheet_path(self, archive: zipfile.ZipFile) -> str:
        try:
            with archive.open("xl/workbook.xml") as workbook_file:
                workbook_root = ET.parse(workbook_file).getroot()
            with archive.open("xl/_rels/workbook.xml.rels") as rels_file:
                rels_root = ET.parse(rels_file).getroot()
        except KeyError:
            return "xl/worksheets/sheet1.xml"

        workbook_ns = {
            "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        }
        rels_ns = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
        first_sheet = workbook_root.find(".//x:sheets/x:sheet", workbook_ns)
        if first_sheet is None:
            return "xl/worksheets/sheet1.xml"

        relation_id = first_sheet.attrib.get(f"{{{workbook_ns['r']}}}id")
        for relation in rels_root.findall("rel:Relationship", rels_ns):
            if relation.attrib.get("Id") == relation_id:
                target = relation.attrib.get("Target", "worksheets/sheet1.xml")
                return "xl/" + target.lstrip("/")
        return "xl/worksheets/sheet1.xml"

    def _xlsx_cell_value(self, cell: ET.Element, shared_strings: List[str]) -> str:
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            return "".join(node.text or "" for node in cell.findall(".//x:t", ns)).strip()

        value_node = cell.find("x:v", ns)
        value = value_node.text if value_node is not None else ""
        if cell_type == "s":
            try:
                return shared_strings[int(value)].strip()
            except Exception:
                return ""
        if cell_type == "b":
            return "TRUE" if value == "1" else "FALSE"
        return str(value or "").strip()

    def _xlsx_column_index(self, cell_ref: str) -> int:
        letters = re.match(r"([A-Za-z]+)", str(cell_ref or ""))
        if not letters:
            return 0
        index = 0
        for char in letters.group(1).upper():
            index = index * 26 + (ord(char) - ord("A") + 1)
        return max(0, index - 1)

    def _create_folders_from_rows(
        self,
        rows: List[Dict[str, Any]],
        columns: List[Any],
        column: str,
        destination: str,
        secure_doc: Path,
    ) -> Dict[str, Any]:
        column_used = column if column and column in columns else self._detect_student_column(columns)
        if not column_used:
            result = tool_error("create_folders_from_table", "No se pudo detectar una columna clara para crear carpetas.")
            result.update({"requires_clarification": True, "columns": columns, "preview": rows[:5]})
            return result

        from tools.file_tools import FileCapabilities

        file_cap = FileCapabilities(str(self.workspace_path), self.security)
        destination = destination.strip().strip("/\\")
        if destination:
            base_result = file_cap.create_directory(destination)
            if not base_result.get("success"):
                return tool_error("create_folders_from_table", base_result.get("message", "No se pudo preparar el destino."))

        seen = {}
        created, reused, skipped, errors = [], [], [], []
        duplicates_resolved = 0

        for row in rows:
            value = row.get(column_used)
            if value in (None, ""):
                skipped.append("")
                continue

            base_name = self._sanitize_folder_value(value)
            if not base_name:
                skipped.append(str(value))
                continue

            final_name = base_name
            if base_name in seen:
                seen[base_name] += 1
                final_name = f"{base_name} ({seen[base_name]})"
                duplicates_resolved += 1
            else:
                seen[base_name] = 1

            folder_path = f"{destination}/{final_name}" if destination else final_name
            result = file_cap.create_directory(folder_path)
            if not result.get("success"):
                errors.extend(result.get("errors") or [result.get("message", "Error")])
                continue
            created.extend(result.get("created", []))
            reused.extend(result.get("reused", []))

        result = tool_result(
            success=not errors,
            action="create_folders_from_table",
            message="Carpetas desde tabla procesadas.",
            created=created,
            reused=reused,
            skipped=skipped,
            errors=errors,
            metadata={
                "created_count": len(created),
                "reused_count": len(reused),
                "skipped_count": len(skipped),
                "column_used": str(column_used),
                "table_path": secure_doc.name,
                "destination_folder": destination or ".",
                "duplicates_resolved": duplicates_resolved,
                "total_rows": len(rows),
            },
        )
        result.update({
            "total_rows": len(rows),
            "folders_created": len(created),
            "folders": created + reused,
            "column_used": str(column_used),
            "destination": destination or ".",
            "source": str(secure_doc),
            "ignored": len(skipped),
        })
        return result

    def detect_facesync_columns(
        self,
        excel_path: str,
        sheet_name: Optional[Union[str, int]] = 0
    ) -> Dict[str, Any]:
        """
        Detecta columnas probables para el flujo Excel -> carpetas -> FaceSync.
        """

        try:
            secure_doc = self._resolve_secure_path(excel_path)
            if not secure_doc.exists():
                return {"success": False, "error": "El Excel no existe."}

            doc_type = self.detect_document_type(secure_doc)
            if doc_type == "csv" and not PANDAS_AVAILABLE:
                rows = self._read_csv_rows(secure_doc)
                columns = list(rows[0].keys()) if rows else []
                return {
                    "success": True,
                    "rows": len(rows),
                    "columns": columns,
                    "name_column": self._detect_student_column(columns),
                    "reference_column": self._detect_reference_column(columns),
                    "preview": rows[:5],
                }
            if doc_type == "csv":
                df = pd.read_csv(secure_doc)
            elif doc_type == "excel":
                if not PANDAS_AVAILABLE:
                    if secure_doc.suffix.lower() == ".xlsx":
                        rows = self._read_xlsx_rows(secure_doc)
                        columns = list(rows[0].keys()) if rows else []
                        return {
                            "success": True,
                            "rows": len(rows),
                            "columns": columns,
                            "name_column": self._detect_student_column(columns),
                            "reference_column": self._detect_reference_column(columns),
                            "preview": rows[:5],
                        }
                    return {"success": False, "error": "pandas/xlrd no esta instalado para leer archivos .xls."}
                df = pd.read_excel(secure_doc, sheet_name=sheet_name)
            else:
                return {"success": False, "error": "El documento no es Excel/CSV."}

            if isinstance(df, dict):
                first_sheet = next(iter(df))
                df = df[first_sheet]

            columns = list(df.columns)
            return {
                "success": True,
                "rows": len(df),
                "columns": columns,
                "name_column": self._detect_student_column(columns),
                "reference_column": self._detect_reference_column(columns),
                "preview": df.head(5).to_dict(orient="records"),
            }

        except Exception as e:
            logger.exception("Error detectando columnas FaceSync")
            return {"success": False, "error": str(e)}

    def create_folders_from_excel(
        self,
        excel_path: str,
        column: str = "",
        destination: str = "",
        sheet_name: Optional[Union[str, int]] = 0
    ) -> Dict[str, Any]:
        """
        Crea una carpeta por fila de un Excel/CSV usando una columna detectada o indicada.
        """

        try:
            secure_doc = self._resolve_secure_path(excel_path)
            if not secure_doc.exists():
                return tool_error("create_folders_from_table", "El Excel no existe.")

            doc_type = self.detect_document_type(secure_doc)
            if doc_type not in ("excel", "csv"):
                return tool_error("create_folders_from_table", "El documento no es Excel/CSV.")

            if doc_type == "csv" and not PANDAS_AVAILABLE:
                rows = self._read_csv_rows(secure_doc)
                columns = list(rows[0].keys()) if rows else []
                return self._create_folders_from_rows(rows, columns, column, destination, secure_doc)

            if doc_type == "csv":
                df = pd.read_csv(secure_doc)
            else:
                if not PANDAS_AVAILABLE:
                    if secure_doc.suffix.lower() == ".xlsx":
                        rows = self._read_xlsx_rows(secure_doc)
                        columns = list(rows[0].keys()) if rows else []
                        return self._create_folders_from_rows(rows, columns, column, destination, secure_doc)
                    return tool_error("create_folders_from_table", "pandas/xlrd no esta instalado para leer archivos .xls.")
                df = pd.read_excel(secure_doc, sheet_name=sheet_name)

            if isinstance(df, dict):
                first_sheet = next(iter(df))
                df = df[first_sheet]

            columns = list(df.columns)
            rows = df.to_dict(orient="records")
            return self._create_folders_from_rows(rows, columns, column, destination, secure_doc)

        except Exception as e:
            logger.exception("Error creando carpetas desde Excel")
            return tool_error("create_folders_from_table", str(e))

    def create_folders_from_table(
        self,
        table_path: str,
        column: str = "",
        destination: str = "",
        sheet_name: Optional[Union[str, int]] = 0
    ) -> Dict[str, Any]:
        """
        Alias generico para CSV/Excel; conserva el motor seguro de create_folders_from_excel.
        """
        return self.create_folders_from_excel(
            excel_path=table_path,
            column=column,
            destination=destination,
            sheet_name=sheet_name,
        )

    def delete_folders_from_excel(
        self,
        excel_path: str,
        column: str = "",
        destination: str = "",
        sheet_name: Optional[Union[str, int]] = 0
    ) -> Dict[str, Any]:
        """
        Elimina carpetas generadas desde una columna de Excel/CSV, siempre dentro
        del workspace y con la misma normalizacion usada al crearlas.
        """

        try:
            secure_doc = self._resolve_secure_path(excel_path)
            if not secure_doc.exists():
                return {"success": False, "error": "El Excel no existe."}

            doc_type = self.detect_document_type(secure_doc)
            if doc_type not in ("excel", "csv"):
                return {"success": False, "error": "El documento no es Excel/CSV."}

            if doc_type == "csv":
                df = pd.read_csv(secure_doc)
            else:
                df = pd.read_excel(secure_doc, sheet_name=sheet_name)

            if isinstance(df, dict):
                first_sheet = next(iter(df))
                df = df[first_sheet]

            columns = list(df.columns)
            column_used = column if column and column in columns else self._detect_student_column(columns)
            if not column_used:
                return {
                    "success": False,
                    "requires_clarification": True,
                    "columns": columns,
                    "preview": df.head(5).to_dict(orient="records"),
                    "message": "No se pudo detectar una columna clara para borrar carpetas."
                }

            destination = destination.strip().strip("/\\")
            secure_destination = self._resolve_secure_path(destination or ".")

            deleted = []
            missing = []
            ignored = 0
            seen = {}

            for value in df[column_used].tolist():
                if pd.isna(value):
                    ignored += 1
                    continue

                base_name = self._sanitize_folder_value(value)
                if not base_name:
                    ignored += 1
                    continue

                final_name = base_name
                if base_name in seen:
                    seen[base_name] += 1
                    final_name = f"{base_name} ({seen[base_name]})"
                else:
                    seen[base_name] = 1

                target = secure_destination / final_name
                target_rel = f"{destination}/{final_name}" if destination else final_name
                secure_target = self.security.secure_path(str(target))
                if not secure_target:
                    ignored += 1
                    continue

                is_safe, reason = self.security.validate_delete(secure_target)
                if not is_safe:
                    ignored += 1
                    logger.warning("Borrado omitido por seguridad: %s", reason)
                    continue

                target_path = Path(secure_target)
                if not target_path.exists():
                    missing.append(target_rel)
                    continue
                if not target_path.is_dir():
                    ignored += 1
                    continue

                shutil.rmtree(target_path)
                deleted.append(target_rel)

            return {
                "success": True,
                "total_rows": len(df),
                "deleted": len(deleted),
                "folders_deleted": deleted,
                "missing": missing,
                "ignored": ignored,
                "column_used": str(column_used),
                "destination": destination or ".",
                "source": str(secure_doc),
            }

        except Exception as e:
            logger.exception("Error borrando carpetas desde Excel")
            return {
                "success": False,
                "error": str(e)
            }

    # ========================================================
    # CREAR CARPETAS DESDE DOCUMENTO
    # ========================================================

    def create_folders_from_document(
        self,
        document_path: str,
        output_dir: str = "",
        column_name: Optional[str] = None,
        destination_path: Optional[str] = None,
        mode: str = "auto"
    ) -> Dict[str, Any]:
        """
        Genera carpetas automáticamente desde datos documentales.

        Compatible con:
        - Excel
        - CSV
        - TXT

        Ideal para:
        - alumnos
        - clientes
        - eventos
        - FaceSync
        """

        try:
            if destination_path is not None:
                output_dir = destination_path

            secure_doc = self._resolve_secure_path(document_path)
            secure_output = self._resolve_secure_path(output_dir or ".")

            secure_output.mkdir(
                parents=True,
                exist_ok=True
            )

            doc_type = self.detect_document_type(secure_doc)

            created = []

            # ====================================================
            # EXCEL / CSV
            # ====================================================

            if doc_type in ["excel", "csv"]:
                report = self.create_folders_from_excel(
                    excel_path=str(secure_doc),
                    column=column_name or "",
                    destination=output_dir or "",
                )
                return report

            # ====================================================
            # TXT
            # ====================================================

            elif doc_type == "text":

                lines = secure_doc.read_text(
                    encoding="utf-8"
                ).splitlines()

                for line in lines:

                    line = line.strip()

                    if not line:
                        continue

                    folder_name = (
                        self.security.sanitize_filename(line)
                    )

                    folder = secure_output / folder_name

                    folder.mkdir(
                        parents=True,
                        exist_ok=True
                    )

                    created.append(folder_name)

            else:
                return {
                    "success": False,
                    "error": "Formato incompatible."
                }

            return {
                "success": True,
                "folders_created": len(created),
                "folders": created
            }

        except Exception as e:
            logger.exception(
                "Error creando carpetas desde documento"
            )

            return {
                "success": False,
                "error": str(e)
            }

