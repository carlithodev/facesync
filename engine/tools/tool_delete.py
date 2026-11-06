"""
======================================================================
MÓDULO: TOOL DELETE — Compatibilidad Legacy
Archivo: tools/tool_delete.py
======================================================================

OBJETIVO:
Wrapper seguro para eliminación de archivos y carpetas
dentro del sandbox FaceSync AI.

Este módulo mantiene compatibilidad con sistemas antiguos
delegando toda la lógica moderna hacia:

    tools.file_tools.FileCapabilities

======================================================================

CAPACIDADES:
✔ Eliminar archivos
✔ Eliminar carpetas
✔ Eliminación recursiva segura
✔ Protección del sandbox
✔ Prevención de borrado crítico
✔ Compatible con agentes IA

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

def delete(
    workspace_path: str,
    target_path: str,
    recursive: bool = False
) -> str:
    """
    Elimina un archivo o carpeta de forma segura.

    Args:
        workspace_path (str):
            Ruta raíz del workspace.

        target_path (str):
            Ruta relativa del elemento a eliminar.

        recursive (bool):
            Si True elimina carpetas completas.

    Returns:
        str:
            Resultado descriptivo.
    """

    ok, reason = ToolExecutionGate.validate_tool_args("delete_item", target=target_path)
    if not ok:
        return {"success": False, "action": "delete_item", "message": reason, "errors": [reason], "metadata": {}}
    security = SecurityManager(workspace_path)

    capabilities = FileCapabilities(
        workspace_path=workspace_path,
        security_manager=security
    )

    return capabilities.delete_path(
        path=target_path,
        recursive=recursive
    )


def ejecutar(ruta: str, workspace: str, recursivo: bool = True) -> str:
    """
    Entrada simple para agentes legacy.
    """
    if not workspace:
        return "Error eliminando: no hay workspace configurado."
    return delete(workspace_path=workspace, target_path=ruta, recursive=recursivo)


# ======================================================================
# WRAPPER LEGACY
# ======================================================================

class ToolDelete:
    """
    Wrapper orientado a compatibilidad retroactiva.

    Toda la lógica real vive en:
        FileCapabilities.delete_path()
    """

    def __init__(self, workspace_path: str):
        """
        Inicializa herramienta.

        Args:
            workspace_path (str):
                Sandbox raíz.
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

    def execute(
        self,
        target_path: str,
        recursive: bool = False
    ) -> str:
        """
        Ejecuta eliminación segura.

        Args:
            target_path (str):
                Ruta relativa objetivo.

            recursive (bool):
                Eliminar contenido interno.

        Returns:
            str:
                Resultado de operación.
        """

        return self.capabilities.delete_path(
            path=target_path,
            recursive=recursive
        )

    # ==================================================================
    # ALIAS
    # ==================================================================

    def run(
        self,
        target_path: str,
        recursive: bool = False
    ) -> str:
        """
        Alias compatible.
        """

        return self.execute(
            target_path=target_path,
            recursive=recursive
        )


# ======================================================================
# FACTORY
# ======================================================================

def build_tool(workspace_path: str) -> ToolDelete:
    """
    Factory helper.

    Args:
        workspace_path (str):
            Workspace raíz.

    Returns:
        ToolDelete
    """

    return ToolDelete(workspace_path)


# ======================================================================
# TEST LOCAL
# ======================================================================

if __name__ == "__main__":

    WORKSPACE = "./workspace_test"

    tool = ToolDelete(WORKSPACE)

    result = tool.execute(
        target_path="temp/test_folder",
        recursive=True
    )

    print(result)
