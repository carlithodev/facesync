"""
======================================================================
HERRAMIENTA: READ EXCEL - Leer Documentos Excel
======================================================================
"""
from typing import Optional
from tools.document_tools import DocumentCapabilities


def ejecutar(ruta_excel: str, hoja: Optional[str] = None, rango: Optional[str] = None, workspace: str = "") -> str:
    """
    Lee contenido de un archivo Excel.
    """
    if not workspace:
        return "Error leyendo Excel: no hay workspace configurado."

    cap = DocumentCapabilities(workspace_path=workspace)
    resultado = cap.read_excel(path=ruta_excel, sheet_name=hoja if hoja is not None else 0)

    if not resultado.get("success"):
        return f"Error leyendo Excel: {resultado.get('error', 'Desconocido')}"

    data = resultado.get("data", {})
    if resultado.get("multiple_sheets"):
        return f"Contenido de Excel (multiples hojas):\n{data}"

    return (
        "Contenido de Excel:\n"
        f"Filas: {resultado.get('rows', 0)}\n"
        f"Columnas: {resultado.get('columns', [])}\n"
        f"Datos: {data}"
    )
