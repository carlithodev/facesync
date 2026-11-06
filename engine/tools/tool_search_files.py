"""
======================================================================
HERRAMIENTA: SEARCH FILES - Busqueda de Archivos
======================================================================
"""
from tools.search_tools import SearchCapabilities


def ejecutar(patron: str = "", extension: str = "", recursivo: bool = True, workspace: str = "") -> str:
    """
    Busca archivos por patron o extension dentro del workspace.
    """
    if not workspace:
        return "Error en busqueda: no hay workspace configurado."

    cap = SearchCapabilities(workspace_path=workspace)

    if extension:
        resultados = cap.search_by_extension(extension=extension, recursive=recursivo)
    else:
        resultados = cap.search_by_name(pattern=patron or "*", recursive=recursivo)

    if not resultados.get("success"):
        return f"Error en busqueda: {resultados.get('error', 'Desconocido')}"

    archivos = resultados.get("results", [])
    if not archivos:
        return "No se encontraron archivos."

    lineas = [
        f.get("relative_path") or f.get("path") or f.get("name", "")
        for f in archivos
    ]
    return f"Archivos encontrados ({len(archivos)}):\n" + "\n".join(lineas)
