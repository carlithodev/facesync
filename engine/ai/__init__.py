"""
======================================================================
MÓDULO: AI — Capa de Inteligencia Artificial (FaceSync AI)
======================================================================
Centraliza la comunicación, traducción, seguridad y registro de herramientas
para los modelos de Lenguaje de Gran Escala (específicamente Google Gemini).

Componentes Expuestos:
- GeminiClient: Cliente robusto y tolerante con políticas de backoff exponencial.
- AgentToolRegistry: Registro dinámico de herramientas mediante introspección.
- ResponseParser: Extracción de intenciones, JSON y formateo en Markdown.
- SafetyLayer: Filtro anti-jailbreak y verificación en sandbox de tool calling.
- prompts: Módulo central de prompts maestros y constructores dinámicos.

======================================================================
"""

try:
    from .gemini_client import GeminiClient
except Exception:
    GeminiClient = None
from .tool_registry import AgentToolRegistry
from .response_parser import ResponseParser
from .safety_layer import SafetyLayer
from .prompts import construir_prompt, SYSTEM_PROMPT_BASE, SAFETY_GUARDRAILS
from .openai_orchestrator import OpenAIOrchestrator
from .smart_orchestrator import SmartOrchestrator

__all__ = [
    "GeminiClient",
    "AgentToolRegistry",
    "ResponseParser",
    "SafetyLayer",
    "construir_prompt",
    "SYSTEM_PROMPT_BASE",
    "SAFETY_GUARDRAILS",
    "OpenAIOrchestrator",
    "SmartOrchestrator",
]
