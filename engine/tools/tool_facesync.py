"""
======================================================================
HERRAMIENTA: FACESYNC — Reconocimiento Facial
======================================================================
Ejecuta el motor de reconocimiento facial FaceSync.

Relación con el sistema existente:
- Actúa como wrapper de facesyncApp/motor_ia.py (MotorFaceSync)
- La función ejecutar_motor_facesync() en agente_ia.py es el
  antecedente directo de esta herramienta

Flujo:
1. Recibe ruta_excel, carpeta_maestra, carpeta_destino
2. Valida rutas via core.security
3. Invoca MotorFaceSync.iniciar_reconocimiento_en_hilo()
4. Retorna estado de la operación
======================================================================
"""
from typing import Callable, Optional
from tools.facesync_tools import FaceSyncCapabilities
from core.tool_execution_gate import ToolExecutionGate

def ejecutar(
    ruta_excel: str,
    carpeta_maestra: str,
    carpeta_destino: str,
    workspace: str,
    columna_nombre: str = "Nombre del Alumno",
    columna_referencia: str = "Foto",
    callback: Optional[Callable] = None
) -> str:
    """
    Ejecuta el reconocimiento facial de forma segura.
    """
    ok, reason = ToolExecutionGate.validate_action("run_reference_face_matching", {
        "table_path": ruta_excel,
        "name_column": columna_nombre,
        "reference_column": columna_referencia,
        "source_folder": carpeta_maestra,
        "destination_folder": carpeta_destino,
    })
    if not ok:
        return f"Error: {reason}"
    cap = FaceSyncCapabilities(workspace_path=workspace)
    resultado = cap.run_face_sync(
        excel_path=ruta_excel,
        source_folder=carpeta_maestra,
        dest_folder=carpeta_destino,
        name_column=columna_nombre,
        reference_column=columna_referencia,
        callback=callback
    )
    if resultado.get("success"):
        return resultado.get("message", "Motor FaceSync iniciado con éxito.")
    else:
        return f"Error: {resultado.get('error', 'Desconocido')}"


def run_reference_face_matching(
    table_path: str,
    name_column: str,
    reference_column: str,
    source_folder: str,
    destination_folder: str,
    workspace: str,
    mock_face_matches: Optional[dict] = None,
) -> dict:
    """
    Ejecuta el flujo general de referencia facial:
    tabla + nombres + referencia + carpeta maestra + destino.
    """
    ok, reason = ToolExecutionGate.validate_action("run_reference_face_matching", {
        "table_path": table_path,
        "name_column": name_column,
        "reference_column": reference_column,
        "source_folder": source_folder,
        "destination_folder": destination_folder,
    })
    if not ok:
        return {"success": False, "action": "run_reference_face_matching", "message": reason, "errors": [reason], "metadata": {}}
    cap = FaceSyncCapabilities(workspace_path=workspace)
    return cap.run_reference_face_matching(
        table_path=table_path,
        name_column=name_column,
        reference_column=reference_column,
        source_folder=source_folder,
        destination_folder=destination_folder,
        mock_face_matches=mock_face_matches,
    )
