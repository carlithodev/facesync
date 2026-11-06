"""
======================================================================
MÓDULO: GEMINI CLIENT — Capa de Comunicación Resiliente con Gemini
Archivo: ai/gemini_client.py
======================================================================
Responsabilidad:
- Encapsular la conexión HTTP y gRPC con la API de Google Gemini.
- Implementar política de reintentos exponencial y control de Rate Limits (429).
- Administrar sesiones de chat contextuales de larga duración.
- Facilitar el soporte nativo de Tool Calling (Function Calling).
======================================================================
"""

import time
import logging
from typing import Dict, List, Optional, Union, Any, Callable
from google import genai
from google.genai import types
from google.genai.errors import APIError

logger = logging.getLogger("FaceSync.GeminiClient")


class GeminiClient:
    """
    Cliente robusto para la API de Google Gemini (SDK de google-genai v2).
    Asegura estabilidad operacional mediante manejo de rate-limits y timeouts.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash"):
        """
        Inicializa el cliente de Gemini.

        Args:
            api_key (Optional[str]): Clave de API de Gemini. Si es None, el SDK la busca en la variable GEMINI_API_KEY.
            model (str): Identificador del modelo (default: gemini-2.5-flash).
        """
        self.model = model
        
        # Inicializar el cliente nativo de Google GenAI
        if api_key:
            self.client = genai.Client(api_key=api_key)
        else:
            self.client = genai.Client()

        self.chat_session = None
        self.system_instruction = None
        self.tools = None

    def crear_sesion(self, instrucciones: str, herramientas: Optional[List[Callable]] = None) -> None:
        """
        Crea una sesión de chat contextual persistente configurada con system instructions y herramientas.

        Args:
            instrucciones (str): System prompt principal (System Instruction).
            herramientas (Optional[List[Callable]]): Lista de funciones Python registradas para Tool Calling.
        """
        self.system_instruction = instrucciones
        self.tools = herramientas

        config = types.GenerateContentConfig(
            system_instruction=self.system_instruction,
            temperature=0.2,  # Temperatura baja para mayor precisión en herramientas
        )

        if self.tools:
            config.tools = self.tools

        try:
            logger.info(f"Creando nueva sesión de chat de Gemini con modelo '{self.model}'")
            self.chat_session = self.client.chats.create(
                model=self.model,
                config=config
            )
        except Exception as e:
            logger.error(f"Error fatal inicializando chat de Gemini: {e}")
            raise

    def enviar_mensaje(self, texto: str, max_retries: int = 4) -> types.GenerateContentResponse:
        """
        Envía un mensaje a la sesión activa e implementa lógica exponencial de reintentos
        ante caídas de red, timeouts o Rate Limits (código HTTP 429).

        Args:
            texto (str): Mensaje del usuario o contexto dinámico.
            max_retries (int): Reintentos máximos (default: 4).

        Returns:
            types.GenerateContentResponse: Respuesta devuelta por la API.
        """
        if not self.chat_session:
            raise RuntimeError("Error: La sesión de chat no está activa. Ejecute primero 'crear_sesion()'.")

        delay = 2.0  # Delay inicial en segundos para reintento

        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(f"Enviando mensaje a Gemini (Intento {attempt}/{max_retries})")
                response = self.chat_session.send_message(texto)
                return response
            
            except APIError as api_err:
                logger.warning(f"Error de API de Gemini en intento {attempt}: Código {api_err.code} - {str(api_err)}")
                
                # Códigos típicos de Rate Limit / Servidor saturado (429, 503, 500)
                if api_err.code in [429, 503, 500] and attempt < max_retries:
                    logger.warning(f"Rate Limit o error temporal detectado. Reintentando en {delay}s...")
                    time.sleep(delay)
                    delay *= 2.0  # Backoff exponencial
                else:
                    raise api_err
                    
            except Exception as e:
                logger.error(f"Error inesperado en comunicación con Gemini: {e}")
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2.0
                else:
                    raise

        raise RuntimeError("Se excedieron todos los reintentos de comunicación con la API de Gemini.")

    def reset_sesion(self) -> None:
        """
        Reinicia la conversación actual de forma segura liberando la memoria acumulada del chat.
        """
        if self.system_instruction:
            logger.info("Reiniciando sesión de chat de Gemini...")
            self.crear_sesion(
                instrucciones=self.system_instruction,
                herramientas=self.tools
            )
