
"""
======================================================================
CORE PACKAGE — FaceSync AI Agent
======================================================================

Núcleo principal del sistema de agentes de FaceSync.

Este paquete contiene:
- Controlador central del agente
- Gestión de contexto conversacional
- Gestión de memoria operativa
- Seguridad y sandboxing
- Gestión del workspace
- Parsing de intención

Arquitectura:
    Usuario
        ↓
    AgentController
        ↓
    IntentParser
        ↓
    ContextManager
        ↓
    WorkspaceManager
        ↓
    Tools
        ↓
    Respuesta

Objetivo:
Construir un agente modular, seguro y escalable capaz de:
- Comprender intención
- Gestionar archivos
- Operar dentro de un workspace seguro
- Automatizar tareas complejas
- Integrarse con IA generativa
- Ejecutar FaceSync dinámicamente

======================================================================
"""

# ======================================================================
# IMPORTACIONES PRINCIPALES
# ======================================================================

try:
    from .agent_controller import AgentController
except ImportError:
    AgentController = None
from .context_manager import ContextManager
from .intent_parser import IntentParser
from .memory_manager import MemoryManager
from .security import SecurityManager
from .workspace_manager import WorkspaceManager

# ======================================================================
# METADATA DEL PAQUETE
# ======================================================================

__version__ = "3.0.0"
__author__ = "FaceSync AI"
__license__ = "Private"
__status__ = "Development"

# ======================================================================
# EXPORTS PÚBLICOS
# ======================================================================

__all__ = [
    "AgentController",
    "ContextManager",
    "IntentParser",
    "MemoryManager",
    "SecurityManager",
    "WorkspaceManager",
]

# ======================================================================
# CONFIGURACIÓN GLOBAL DEL CORE
# ======================================================================

CORE_NAME = "FaceSync Core"

SUPPORTED_DOCUMENTS = [
    ".txt",
    ".pdf",
    ".docx",
    ".xlsx",
    ".xls",
    ".csv",
    ".json",
]

SUPPORTED_IMAGES = [
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
]

SUPPORTED_ACTIONS = [
    "crear",
    "leer",
    "mover",
    "renombrar",
    "eliminar",
    "buscar",
    "organizar",
    "analizar",
    "procesar",
]

# ======================================================================
# FUNCIONES AUXILIARES
# ======================================================================

def get_core_info() -> dict:
    """
    Devuelve información general del núcleo del sistema.
    """

    return {
        "name": CORE_NAME,
        "version": __version__,
        "supported_documents": SUPPORTED_DOCUMENTS,
        "supported_images": SUPPORTED_IMAGES,
        "supported_actions": SUPPORTED_ACTIONS,
    }


def startup_banner() -> str:
    """
    Banner de inicio del núcleo FaceSync.
    """

    return f"""
======================================================================
🚀 FaceSync AI Core v{__version__}
======================================================================

Sistema modular de agentes inteligentes.

Capacidades:
✅ Gestión segura de archivos
✅ Contexto conversacional
✅ Parsing de intención
✅ Workspace aislado
✅ Integración con IA
✅ Automatización inteligente
✅ Reconocimiento facial FaceSync

Estado:
🟢 CORE INICIALIZADO

======================================================================
"""


# ======================================================================
# VALIDACIÓN DE ENTORNO
# ======================================================================

def validate_environment():
    """
    Verifica dependencias mínimas del núcleo.
    """

    import os

    carpetas_requeridas = [
        "core",
        "tools",
        "ai",
        "logs",
        "cache",
    ]

    faltantes = []

    for carpeta in carpetas_requeridas:
        if not os.path.exists(carpeta):
            faltantes.append(carpeta)

    if faltantes:
        raise RuntimeError(
            f"Faltan carpetas requeridas del sistema: {faltantes}"
        )

    return True
