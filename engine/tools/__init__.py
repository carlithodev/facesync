
"""
======================================================================
PAQUETE: tools
Archivo: tools/__init__.py
======================================================================

FaceSync AI Tools Package
-------------------------

Este paquete contiene TODAS las capacidades operativas del agente IA.

Arquitectura:
- Capability-Based Agent System
- Sandbox Security
- Tool Registry
- Dynamic Tool Discovery
- AI Function Calling Ready

Objetivos:
- Centralizar herramientas del agente
- Permitir registro dinámico
- Facilitar integración con Gemini/OpenAI/Claude
- Separar capacidades por dominios funcionales
- Mantener escalabilidad enterprise

======================================================================
"""

# ======================================================================
# IMPORTS BASE
# ======================================================================

from typing import Dict, Any, List, Type

# ======================================================================
# FILE CAPABILITIES
# ======================================================================

from .file_tools import FileCapabilities

# ======================================================================
# DOCUMENT CAPABILITIES
# ======================================================================

from .document_tools import DocumentCapabilities

# ======================================================================
# FACESYNC CAPABILITIES
# ======================================================================

from .facesync_tools import FaceSyncCapabilities

# ======================================================================
# WORKSPACE CAPABILITIES
# ======================================================================

from .workspace_tools import WorkspaceCapabilities

# ======================================================================
# SEARCH CAPABILITIES
# ======================================================================

from .search_tools import SearchCapabilities

# ======================================================================
# SYSTEM CAPABILITIES
# ======================================================================

from .system_tools import SystemCapabilities

# ======================================================================
# EXPORTACIONES PRINCIPALES
# ======================================================================

__all__ = [
    "FileCapabilities",
    "DocumentCapabilities",
    "FaceSyncCapabilities",
    "WorkspaceCapabilities",
    "SearchCapabilities",
    "SystemCapabilities",
    "AgentToolRegistry"
]

# ======================================================================
# REGISTRO CENTRAL DE HERRAMIENTAS
# ======================================================================

class AgentToolRegistry:
    """
    Registro centralizado de capacidades del agente IA.

    Responsabilidades:
    - Registrar tools automáticamente
    - Exponer capacidades al motor IA
    - Permitir introspección dinámica
    - Facilitar integración con LLM Function Calling
    - Centralizar acceso a herramientas

    Compatible con:
    - Google Gemini
    - OpenAI Tool Calling
    - Claude Tools
    - LangChain
    - AutoGen
    """

    def __init__(self):
        """
        Inicializa el registro vacío de herramientas.
        """
        self._tools: Dict[str, Any] = {}

    # ==================================================================
    # REGISTRO DE CAPACIDADES
    # ==================================================================

    def register_tool(self, name: str, tool_instance: Any) -> None:
        """
        Registra una capability/tool en el sistema.

        Args:
            name (str):
                Nombre lógico de la herramienta.

            tool_instance (Any):
                Instancia de la capability.
        """
        self._tools[name] = tool_instance

    def unregister_tool(self, name: str) -> None:
        """
        Elimina una herramienta registrada.

        Args:
            name (str):
                Nombre de la herramienta.
        """
        if name in self._tools:
            del self._tools[name]

    # ==================================================================
    # OBTENCIÓN DE TOOLS
    # ==================================================================

    def get_tool(self, name: str) -> Any:
        """
        Obtiene una herramienta registrada.

        Args:
            name (str):
                Nombre de la herramienta.

        Returns:
            Any:
                Instancia registrada o None.
        """
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """
        Lista todas las herramientas registradas.

        Returns:
            List[str]:
                Nombres de tools disponibles.
        """
        return list(self._tools.keys())

    def has_tool(self, name: str) -> bool:
        """
        Verifica si una herramienta existe.

        Args:
            name (str)

        Returns:
            bool
        """
        return name in self._tools

    # ==================================================================
    # EXPORTACIÓN PARA LLMs
    # ==================================================================

    def export_schema(self) -> Dict[str, Any]:
        """
        Exporta metadata de tools para integración
        con motores de IA.

        Esto permite:
        - Tool Calling
        - Function Calling
        - Introspección automática
        - Agentes dinámicos

        Returns:
            Dict[str, Any]
        """
        schema = {}

        for tool_name, tool_instance in self._tools.items():

            methods = []

            for attr_name in dir(tool_instance):

                # Ignorar privados
                if attr_name.startswith("_"):
                    continue

                attr = getattr(tool_instance, attr_name)

                if callable(attr):
                    methods.append({
                        "name": attr_name,
                        "doc": attr.__doc__
                    })

            schema[tool_name] = {
                "class": tool_instance.__class__.__name__,
                "methods": methods
            }

        return schema

    # ==================================================================
    # REGISTRO AUTOMÁTICO
    # ==================================================================

    def auto_register_default_tools(
        self,
        workspace_path: str,
        security_manager=None
    ) -> None:
        """
        Registra automáticamente todas las capabilities
        principales del sistema.

        Args:
            workspace_path (str):
                Ruta base del workspace.

            security_manager:
                Instancia compartida de seguridad.
        """

        # --------------------------------------------------------------
        # FILE TOOLS
        # --------------------------------------------------------------

        self.register_tool(
            "file",
            FileCapabilities(
                workspace_path=workspace_path,
                security_manager=security_manager
            )
        )

        # --------------------------------------------------------------
        # DOCUMENT TOOLS
        # --------------------------------------------------------------

        self.register_tool(
            "document",
            DocumentCapabilities(
                workspace_path=workspace_path,
                security_manager=security_manager
            )
        )

        # --------------------------------------------------------------
        # FACESYNC TOOLS
        # --------------------------------------------------------------

        self.register_tool(
            "facesync",
            FaceSyncCapabilities(
                workspace_path=workspace_path,
                security_manager=security_manager
            )
        )

        # --------------------------------------------------------------
        # WORKSPACE TOOLS
        # --------------------------------------------------------------

        self.register_tool(
            "workspace",
            WorkspaceCapabilities(
                workspace_path=workspace_path,
                security_manager=security_manager
            )
        )

        # --------------------------------------------------------------
        # SEARCH TOOLS
        # --------------------------------------------------------------

        self.register_tool(
            "search",
            SearchCapabilities(
                workspace_path=workspace_path,
                security_manager=security_manager
            )
        )

        # --------------------------------------------------------------
        # SYSTEM TOOLS
        # --------------------------------------------------------------

        self.register_tool(
            "system",
            SystemCapabilities(
                workspace_path=workspace_path,
                security_manager=security_manager
            )
        )

    # ==================================================================
    # DEBUG / INSPECCIÓN
    # ==================================================================

    def debug_summary(self) -> str:
        """
        Genera resumen textual del estado del registry.

        Returns:
            str
        """

        lines = []

        lines.append("=" * 60)
        lines.append("FaceSync Agent Tool Registry")
        lines.append("=" * 60)

        for tool_name, tool_instance in self._tools.items():

            lines.append(
                f"[{tool_name}] -> "
                f"{tool_instance.__class__.__name__}"
            )

        lines.append("=" * 60)

        return "\n".join(lines)


# La implementacion activa del registry vive en ai.tool_registry.
# Este alias mantiene compatibilidad con imports legacy: from tools import AgentToolRegistry.
try:
    from ai.tool_registry import AgentToolRegistry as AgentToolRegistry
except Exception:
    pass
