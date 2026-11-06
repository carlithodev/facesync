
"""
======================================================================
MÓDULO: TOOL CREATE FILE — Compatibilidad Legacy
Archivo: tools/tool_create_file.py
======================================================================

OBJETIVO:
Mantener compatibilidad con sistemas antiguos (legacy) mientras
la nueva arquitectura basada en capacidades utiliza FileCapabilities.

Este módulo funciona como WRAPPER ligero sobre:
    tools.file_tools.FileCapabilities

IMPORTANTE:
- NO contiene lógica pesada.
- Toda la seguridad real vive en:
      core/security.py
- Toda la lógica moderna vive en:
      tools/file_tools.py

Este archivo existe únicamente para:
✔ Compatibilidad retroactiva
✔ Scripts antiguos
✔ Integraciones heredadas
✔ Tool Calling simple

======================================================================
"""

from pathlib import Path
from typing import Optional

from tools.file_tools import FileCapabilities
from core.security import SecurityManager
from core.tool_execution_gate import ToolExecutionGate


# ======================================================================
# FUNCIÓN LEGACY PRINCIPAL
# ======================================================================

def create_file(
    workspace_path: str,
    file_path: str,
    content: str = "",
    overwrite: bool = False
) -> str:
    """
    Wrapper legacy para crear archivos de forma segura.

    Args:
        workspace_path (str):
            Ruta raíz del workspace/sandbox.

        file_path (str):
            Ruta relativa del archivo a crear.

        content (str):
            Contenido inicial.

        overwrite (bool):
            Sobrescribir si existe.

    Returns:
        str:
            Resultado descriptivo.
    """

    ok, reason = ToolExecutionGate.validate_tool_args("create_file", file_name=file_path)
    if not ok:
        return {"success": False, "action": "create_file", "message": reason, "errors": [reason], "metadata": {}}
    security = SecurityManager(workspace_path)
    capabilities = FileCapabilities(
        workspace_path=workspace_path,
        security_manager=security
    )

    return capabilities.create_file(
        path=file_path,
        content=content,
        overwrite=overwrite
    )


def ejecutar(ruta_archivo: str, contenido: str = "", workspace: str = "", sobrescribir: bool = False) -> str:
    """
    Entrada simple para agentes legacy.
    """
    if not workspace:
        return "Error creando archivo: no hay workspace configurado."
    return create_file(
        workspace_path=workspace,
        file_path=ruta_archivo,
        content=contenido,
        overwrite=sobrescribir
    )


# ======================================================================
# WRAPPER AVANZADO
# ======================================================================

class ToolCreateFile:
    """
    Clase wrapper legacy compatible con arquitecturas antiguas.

    Esta clase NO implementa lógica.
    Delegará SIEMPRE hacia FileCapabilities.
    """

    def __init__(self, workspace_path: str):
        """
        Inicializa la herramienta.

        Args:
            workspace_path (str):
                Ruta raíz del workspace.
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
        file_path: str,
        content: str = "",
        overwrite: bool = False
    ) -> str:
        """
        Ejecuta creación de archivo.

        Args:
            file_path (str):
                Ruta relativa destino.

            content (str):
                Contenido inicial.

            overwrite (bool):
                Sobrescribir.

        Returns:
            str:
                Resultado.
        """

        return self.capabilities.create_file(
            path=file_path,
            content=content,
            overwrite=overwrite
        )

    # ==================================================================
    # MÉTODO ALTERNATIVO
    # ==================================================================

    def run(
        self,
        file_path: str,
        content: str = "",
        overwrite: bool = False
    ) -> str:
        """
        Alias de execute() para compatibilidad.
        """

        return self.execute(
            file_path=file_path,
            content=content,
            overwrite=overwrite
        )


# ======================================================================
# FACTORY
# ======================================================================

def build_tool(workspace_path: str) -> ToolCreateFile:
    """
    Factory helper para crear la herramienta.

    Args:
        workspace_path (str):
            Ruta sandbox.

    Returns:
        ToolCreateFile
    """

    return ToolCreateFile(workspace_path)


# ======================================================================
# TEST LOCAL
# ======================================================================

if __name__ == "__main__":

    WORKSPACE = "./workspace_test"

    tool = ToolCreateFile(WORKSPACE)

    result = tool.execute(
        file_path="ejemplo/test.txt",
        content="Hola desde FaceSync AI 🚀",
        overwrite=True
    )

    print(result)
