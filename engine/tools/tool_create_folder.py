
"""
======================================================================
MÓDULO: TOOL CREATE FOLDER — Compatibilidad Legacy
Archivo: tools/tool_create_folder.py
======================================================================

OBJETIVO:
Wrapper legacy para creación segura de carpetas dentro del sandbox
FaceSync AI.

Este módulo mantiene compatibilidad con versiones anteriores
mientras delega toda la lógica moderna hacia:

    tools.file_tools.FileCapabilities

======================================================================
"""

from pathlib import Path
from typing import Optional

from tools.file_tools import FileCapabilities
from core.security import SecurityManager
from core.tool_execution_gate import ToolExecutionGate


# ======================================================================
# FUNCIÓN LEGACY
# ======================================================================

def create_folder(
    workspace_path: str,
    folder_path: str
) -> str:
    """
    Crea una carpeta segura dentro del workspace.

    Args:
        workspace_path (str):
            Ruta raíz del sandbox.

        folder_path (str):
            Ruta relativa de la carpeta.

    Returns:
        str:
            Resultado descriptivo.
    """

    ok, reason = ToolExecutionGate.validate_tool_args("create_folder", folder_name=folder_path)
    if not ok:
        return {"success": False, "action": "create_folder", "message": reason, "errors": [reason], "metadata": {}}
    security = SecurityManager(workspace_path)

    capabilities = FileCapabilities(
        workspace_path=workspace_path,
        security_manager=security
    )

    return capabilities.create_directory(folder_path)


def ejecutar(ruta_carpeta: str, workspace: str) -> str:
    """
    Entrada simple para agentes legacy.
    """
    if not workspace:
        return "Error creando carpeta: no hay workspace configurado."
    return create_folder(workspace_path=workspace, folder_path=ruta_carpeta)


# ======================================================================
# CLASE WRAPPER LEGACY
# ======================================================================

class ToolCreateFolder:
    """
    Wrapper orientado a compatibilidad retroactiva.

    Toda la lógica real se ejecuta en:
        FileCapabilities.create_directory()
    """

    def __init__(self, workspace_path: str):
        """
        Inicializa herramienta.

        Args:
            workspace_path (str):
                Ruta raíz segura.
        """

        self.workspace_path = workspace_path

        self.security = SecurityManager(workspace_path)

        self.capabilities = FileCapabilities(
            workspace_path=workspace_path,
            security_manager=self.security
        )

    # ==================================================================
    # MÉTODO PRINCIPAL
    # ==================================================================

    def execute(self, folder_path: str) -> str:
        """
        Ejecuta creación de carpeta.

        Args:
            folder_path (str):
                Ruta relativa destino.

        Returns:
            str:
                Resultado de operación.
        """

        return self.capabilities.create_directory(folder_path)

    # ==================================================================
    # ALIAS
    # ==================================================================

    def run(self, folder_path: str) -> str:
        """
        Alias compatible.
        """

        return self.execute(folder_path)


# ======================================================================
# FACTORY
# ======================================================================

def build_tool(workspace_path: str) -> ToolCreateFolder:
    """
    Factory helper.

    Args:
        workspace_path (str):
            Workspace sandbox.

    Returns:
        ToolCreateFolder
    """

    return ToolCreateFolder(workspace_path)


# ======================================================================
# TEST LOCAL
# ======================================================================

if __name__ == "__main__":

    WORKSPACE = "./workspace_test"

    tool = ToolCreateFolder(WORKSPACE)

    result = tool.execute(
        folder_path="clientes/escuela/grupo_a"
    )

    print(result)
