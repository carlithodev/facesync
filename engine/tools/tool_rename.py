"""
======================================================================
HERRAMIENTA: RENAME — Renombrar Archivos o Carpetas
======================================================================
"""
from tools.file_tools import FileCapabilities

def ejecutar(ruta_actual: str, nombre_nuevo: str, workspace: str) -> str:
    """
    Renombra un archivo o carpeta.
    """
    if not workspace:
        return "Error renombrando: no hay workspace configurado."
    cap = FileCapabilities(workspace_path=workspace)
    return cap.rename_path(path=ruta_actual, new_name=nombre_nuevo)
