
"""
======================================================================
MÓDULO: TOOL CREATE STRUCTURE FROM DOCUMENT
Archivo: tools/tool_create_folders_from_excel.py
======================================================================

⚠️ IMPORTANTE:
Aunque el nombre legacy del archivo conserva "excel" por compatibilidad,
el sistema YA NO depende únicamente de Excel.

Este módulo soporta:

✔ Excel (.xlsx, .xls)
✔ CSV
✔ TXT
✔ JSON
✔ PDF (texto extraíble)
✔ DOCX
✔ Listas de texto plano
✔ Datos estructurados dinámicos

======================================================================

OBJETIVO:
Crear estructuras masivas de carpetas desde documentos de entrada.

Ejemplos reales:
- Crear carpetas de alumnos
- Crear carpetas de clientes
- Crear carpetas por IDs
- Crear estructuras empresariales
- Crear datasets IA
- Crear árboles dinámicos

======================================================================
"""

from pathlib import Path
from typing import Optional, List

from tools.document_tools import DocumentCapabilities
from core.security import SecurityManager


# ======================================================================
# FUNCIÓN LEGACY
# ======================================================================

def create_structure_from_document(
    workspace_path: str,
    document_path: str,
    destination_path: str,
    mode: str = "auto"
) -> str:
    """
    Genera carpetas automáticamente desde documentos estructurados.

    Args:
        workspace_path (str):
            Ruta raíz segura.

        document_path (str):
            Documento fuente.

        destination_path (str):
            Carpeta base donde crear estructura.

        mode (str):
            Modo de lectura:
                - auto
                - excel
                - csv
                - txt
                - json
                - pdf
                - docx

    Returns:
        str:
            Resultado descriptivo.
    """

    security = SecurityManager(workspace_path)

    capabilities = DocumentCapabilities(
        workspace_path=workspace_path,
        security_manager=security
    )

    return capabilities.create_folders_from_document(
        document_path=document_path,
        destination_path=destination_path,
        mode=mode
    )


# ======================================================================
# WRAPPER LEGACY
# ======================================================================

class ToolCreateStructureFromDocument:
    """
    Wrapper universal para generación de estructuras dinámicas.

    Compatible con:
    - IA Agents
    - Gemini Tool Calling
    - LangChain
    - Sistemas legacy
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

        self.capabilities = DocumentCapabilities(
            workspace_path=workspace_path,
            security_manager=self.security
        )

    def set_project_root(self, project_root: str):
        self.workspace_path = project_root
        self.security.set_project_root(project_root)
        self.capabilities.set_project_root(project_root)

    def set_workspace(self, workspace_path: str):
        self.set_project_root(workspace_path)

    # ==================================================================
    # MÉTODO PRINCIPAL
    # ==================================================================

    def execute(
        self,
        document_path: str,
        destination_path: str,
        mode: str = "auto"
    ) -> str:
        """
        Ejecuta creación masiva.

        Args:
            document_path (str):
                Documento entrada.

            destination_path (str):
                Destino raíz.

            mode (str):
                Tipo de documento.

        Returns:
            str:
                Resultado.
        """

        return self.capabilities.create_folders_from_document(
            document_path=document_path,
            destination_path=destination_path,
            mode=mode
        )

    # ==================================================================
    # ALIAS
    # ==================================================================

    def run(
        self,
        document_path: str,
        destination_path: str,
        mode: str = "auto"
    ) -> str:
        """
        Alias compatible.
        """

        return self.execute(
            document_path=document_path,
            destination_path=destination_path,
            mode=mode
        )


# ======================================================================
# FACTORY
# ======================================================================

def build_tool(workspace_path: str) -> ToolCreateStructureFromDocument:
    """
    Factory helper.

    Args:
        workspace_path (str):
            Workspace raíz.

    Returns:
        ToolCreateStructureFromDocument
    """

    return ToolCreateStructureFromDocument(workspace_path)


# ======================================================================
# TEST LOCAL
# ======================================================================

if __name__ == "__main__":

    WORKSPACE = "./workspace_test"

    tool = ToolCreateStructureFromDocument(WORKSPACE)

    result = tool.execute(
        document_path="datos/alumnos.xlsx",
        destination_path="ALUMNOS",
        mode="auto"
    )

    print(result)
