"""
======================================================================
HERRAMIENTA: READ PDF - Leer Documentos PDF
======================================================================
"""
from typing import List, Optional
from tools.document_tools import DocumentCapabilities


def ejecutar(
    ruta_pdf: str,
    paginas: Optional[List[int]] = None,
    extraer_imagenes: bool = False,
    workspace: str = ""
) -> str:
    """
    Lee contenido de un PDF.
    """
    if not workspace:
        return "Error leyendo PDF: no hay workspace configurado."

    cap = DocumentCapabilities(workspace_path=workspace)
    resultado = cap.read_pdf(path=ruta_pdf)

    if not resultado.get("success"):
        return f"Error leyendo PDF: {resultado.get('error', 'Desconocido')}"

    contenido = resultado.get("content", "")
    if paginas:
        return (
            "Contenido PDF:\n"
            f"(Filtro de paginas solicitado: {paginas}; el lector actual devuelve el texto extraido disponible.)\n"
            f"{contenido}"
        )

    return f"Contenido PDF:\n{contenido}"
