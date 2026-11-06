"""
======================================================================
MÓDULO: RESPONSE PARSER — Parser y Validador de Salidas del Modelo IA
Archivo: ai/response_parser.py
======================================================================
Responsabilidad:
- Analizar y estructurar las respuestas brutas del modelo Gemini.
- Detectar y extraer llamadas a herramientas (Function/Tool Calling).
- Extraer bloques JSON de markdown con alta tolerancia a errores.
- Sanitizar y formatear el Markdown final para la interfaz del usuario.
======================================================================
"""

import json
import re
import logging
from typing import Dict, List, Optional, Any, Union

logger = logging.getLogger("FaceSync.ResponseParser")


class ResponseParser:
    """
    Parser robusto para procesar, limpiar y estructurar respuestas de modelos IA.
    Asegura que el flujo de datos entre Gemini y Python sea íntegro.
    """

    @staticmethod
    def parse_gemini_response(response: Any) -> Dict[str, Any]:
        """
        Analiza un objeto GenerateContentResponse de Gemini y extrae su texto
        y sus intenciones de llamadas a herramientas (Tool Calls) de forma estructurada.

        Args:
            response: Respuesta del cliente de Gemini (SDK types.GenerateContentResponse).

        Returns:
            Dict[str, Any]: Estructura limpia conteniendo:
                - "text": str (Respuesta conversacional)
                - "tool_calls": List[Dict] (Lista de llamadas a herramientas, con nombre y kwargs)
                - "has_tool_calls": bool
        """
        parsed = {
            "text": "",
            "tool_calls": [],
            "has_tool_calls": False
        }

        try:
            # 1. Extraer el texto conversacional
            if hasattr(response, "text") and response.text:
                parsed["text"] = response.text
            elif hasattr(response, "candidates") and response.candidates:
                # Extraer texto de partes del primer candidato
                parts = response.candidates[0].content.parts
                text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
                parsed["text"] = "\n".join(text_parts)

            # 2. Extraer llamadas a herramientas (Tool Calls)
            if hasattr(response, "function_calls") and response.function_calls:
                parsed["has_tool_calls"] = True
                for call in response.function_calls:
                    parsed["tool_calls"].append({
                        "name": getattr(call, "name"),
                        "args": getattr(call, "args", {})
                    })
            elif hasattr(response, "candidates") and response.candidates:
                # Buscar en las partes de contenido directamente
                parts = response.candidates[0].content.parts
                for part in parts:
                    if hasattr(part, "function_call") and part.function_call:
                        call = part.function_call
                        parsed["has_tool_calls"] = True
                        
                        # Extraer argumentos de forma tolerante
                        args = {}
                        if hasattr(call, "args") and call.args:
                            # Convertir estructura de protobuf / dict seguro
                            try:
                                args = dict(call.args)
                            except:
                                args = call.args

                        parsed["tool_calls"].append({
                            "name": getattr(call, "name"),
                            "args": args
                        })

        except Exception as e:
            logger.error(f"Error parseando respuesta de Gemini: {e}")
            parsed["text"] = "❌ No se pudo analizar la respuesta de la IA debido a un formato no compatible."

        return parsed

    @staticmethod
    def extract_json(text: str) -> Optional[Dict[str, Any]]:
        """
        Extrae y deserializa de forma robusta bloques JSON contenidos dentro
        de textos conversacionales o bloques de código markdown (```json ... ```).

        Args:
            text (str): Texto que contiene el JSON.

        Returns:
            Optional[Dict]: Diccionario parseado o None si falla.
        """
        if not text:
            return None

        # Expresión regular para capturar bloques de código markdown con JSON
        json_block_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
        match = re.search(json_block_pattern, text, re.DOTALL | re.IGNORECASE)

        if match:
            json_str = match.group(1)
        else:
            # Si no hay bloques, buscar el primer '{' y el último '}'
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = text[start:end+1]
            else:
                json_str = text

        try:
            # Sanitizar saltos de línea inusuales y deserializar
            json_str = re.sub(r'[\r\n]+', '\n', json_str)
            return json.loads(json_str)
        except json.JSONDecodeError as jde:
            logger.warning(f"Fallo al decodificar JSON extraído: {jde}. Texto capturado: {json_str[:200]}")
            return None

    @staticmethod
    def format_markdown_response(text: str) -> str:
        """
        Sanitiza y embellece la respuesta en Markdown antes de enviarla a la interfaz de usuario.
        Asegura alineaciones, viñetas consistentes e introduce llamadas visuales si es necesario.

        Args:
            text (str): Respuesta bruta.

        Returns:
            str: Respuesta formateada para la UI.
        """
        if not text:
            return "Inactivo."

        formatted = text.strip()
        
        # Asegurar espaciado uniforme alrededor de títulos
        formatted = re.sub(r'\n*(###? .*?)\n*', r'\n\n\1\n', formatted)
        
        # Eliminar saltos de línea excesivos de más de tres líneas seguidas
        formatted = re.sub(r'\n{3,}', '\n\n', formatted)

        return formatted
