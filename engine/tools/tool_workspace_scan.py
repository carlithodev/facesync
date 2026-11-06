"""
======================================================================
HERRAMIENTA: WORKSPACE SCAN - Escaneo del Workspace
======================================================================
"""
from tools.workspace_tools import WorkspaceCapabilities


def ejecutar(workspace: str) -> str:
    """
    Escanea y devuelve el arbol del workspace.
    """
    if not workspace:
        return "Error al escanear workspace: no hay workspace configurado."

    cap = WorkspaceCapabilities(workspace_path=workspace)
    resultado = cap.get_workspace_tree()

    if isinstance(resultado, str):
        return f"Workspace Tree:\n{resultado}"

    if isinstance(resultado, dict) and resultado.get("success"):
        return f"Workspace Tree:\n{resultado.get('tree', '')}"

    if isinstance(resultado, dict):
        return f"Error al escanear workspace: {resultado.get('error', 'Desconocido')}"

    return f"Error al escanear workspace: respuesta inesperada ({type(resultado).__name__})"
