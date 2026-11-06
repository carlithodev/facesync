"""
======================================================================
HERRAMIENTA: MOVE — Mover Archivos o Carpetas
======================================================================
"""
from tools.file_tools import FileCapabilities
from core.tool_execution_gate import ToolExecutionGate

def ejecutar(ruta_origen: str, ruta_destino: str, workspace: str) -> str:
    """
    Mueve un archivo o carpeta.
    """
    if not workspace:
        return "Error moviendo: no hay workspace configurado."
    ok, reason = ToolExecutionGate.validate_tool_args("move_item", target=ruta_origen, destination_folder=ruta_destino)
    if not ok:
        return {"success": False, "action": "move_item", "message": reason, "errors": [reason], "metadata": {}}
    cap = FileCapabilities(workspace_path=workspace)
    return cap.move_path(src=ruta_origen, dest=ruta_destino)
