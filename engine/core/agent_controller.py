
"""
======================================================================
AGENT CONTROLLER — FaceSync AI Core
======================================================================

Controlador central del agente inteligente.

Responsabilidades:
- Orquestar flujo completo del agente
- Gestionar contexto
- Interpretar intención
- Ejecutar herramientas
- Comunicarse con Gemini
- Proteger el workspace
- Mantener memoria operativa

Arquitectura:

Usuario
   ↓
AgentController
   ↓
IntentParser
   ↓
WorkspaceManager
   ↓
Tool Execution
   ↓
Respuesta

======================================================================
"""

# ======================================================================
# IMPORTS
# ======================================================================

import os
import json
import traceback
from datetime import datetime

from google import genai
from google.genai import types

from .intent_parser import IntentParser
from .context_manager import ContextManager
from .memory_manager import MemoryManager
from .workspace_manager import WorkspaceManager
from .security import SecurityManager


# ======================================================================
# AGENT CONTROLLER
# ======================================================================

class AgentController:
    """
    Núcleo principal del agente FaceSync.
    """

    # ==================================================================
    # INIT
    # ==================================================================

    def __init__(
        self,
        workspace_path: str,
        gemini_api_key: str,
        ui_callback=None,
        refresh_callback=None
    ):

        self.workspace_path = os.path.abspath(workspace_path)

        self.ui_callback = ui_callback
        self.refresh_callback = refresh_callback

        # ==============================================================
        # VALIDAR WORKSPACE
        # ==============================================================

        SecurityManager.validate_workspace(self.workspace_path)

        # ==============================================================
        # MANAGERS
        # ==============================================================

        self.context_manager = ContextManager()

        self.memory_manager = MemoryManager(
            memory_path=os.path.join(self.workspace_path, "cache", "memory")
        )

        self.workspace_manager = WorkspaceManager(
            workspace_path=self.workspace_path
        )

        self.intent_parser = IntentParser()

        # ==============================================================
        # GEMINI
        # ==============================================================

        self.client = genai.Client(
            api_key=gemini_api_key
        )

        self.chat_session = self.client.chats.create(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=self._build_system_prompt()
            )
        )

        # ==============================================================
        # ESTADO
        # ==============================================================

        self.running = True

        self.log("✅ AgentController inicializado correctamente.")

    # ==================================================================
    # SYSTEM PROMPT
    # ==================================================================

    def _build_system_prompt(self) -> str:
        """
        Construye prompt maestro del sistema.
        """

        return f"""
Eres FaceSync AI.

Eres un agente inteligente especializado en:
- gestión de archivos
- automatización
- organización de workspace
- reconocimiento facial
- análisis documental

REGLAS OBLIGATORIAS:

1. SOLO puedes trabajar dentro del workspace autorizado.

2. NUNCA inventes rutas.

3. SIEMPRE analiza el contexto antes de responder.

4. Tu trabajo es:
- interpretar intención
- planificar acciones
- responder claramente

5. NO ejecutes acciones peligrosas sin confirmación.

6. Tipos soportados:
- PDF
- TXT
- DOCX
- XLSX
- CSV
- imágenes
- JSON

Workspace actual:
{self.workspace_path}
"""

    # ==================================================================
    # LOG
    # ==================================================================

    def log(self, message: str):
        """
        Logger central.
        """

        timestamp = datetime.now().strftime("%H:%M:%S")

        final = f"[{timestamp}] {message}"

        print(final)

        if self.ui_callback:
            try:
                self.ui_callback("Sistema", final)
            except:
                pass

    # ==================================================================
    # MAIN ENTRYPOINT
    # ==================================================================

    def process_user_message(self, message: str) -> str:
        """
        Procesa mensaje del usuario.
        """

        try:

            self.log(f"🧠 Usuario: {message}")

            # ==========================================================
            # ACTUALIZAR CONTEXTO
            # ==========================================================

            self.context_manager.add_message(
                role="user",
                content=message
            )

            # ==========================================================
            # INDEXAR WORKSPACE
            # ==========================================================

            workspace_snapshot = self.workspace_manager.index_workspace()

            # ==========================================================
            # PARSEAR INTENCIÓN
            # ==============================================================

            intent_data = self.intent_parser.parse(
                user_message=message
            )

            self.log(f"🎯 Intent detectado: {intent_data}")

            # ==========================================================
            # EJECUTAR ACCIÓN
            # ==============================================================

            response = self._execute_intent(intent_data)

            # ==========================================================
            # GUARDAR RESPUESTA
            # ==============================================================

            self.context_manager.add_message(
                role="assistant",
                content=response
            )

            return response

        except Exception as e:

            traceback.print_exc()

            error = f"""
❌ Error interno del agente:

{str(e)}
"""

            self.log(error)

            return error

    # ==================================================================
    # EXECUTE INTENT
    # ==================================================================

    def _execute_intent(self, intent_data: dict) -> str:
        """
        Ejecuta intención detectada.
        """

        intent = intent_data.get("intent")

        # ==============================================================
        # CREAR CARPETA
        # ==============================================================

        if intent == "create_folder":

            folder_name = intent_data.get("folder_name")
            target_path = intent_data.get("target_path", "")

            return self.workspace_manager.create_folder(
                folder_name=folder_name,
                target_path=target_path
            )

        # ==============================================================
        # ELIMINAR
        # ==============================================================

        elif intent == "delete_resource":

            path = intent_data.get("path")

            return self.workspace_manager.delete_resource(
                path
            )

        # ==============================================================
        # MOVER
        # ==============================================================

        elif intent == "move_resource":

            source = intent_data.get("source")
            destination = intent_data.get("destination")

            return self.workspace_manager.move_resource(
                source,
                destination
            )

        # ==============================================================
        # LEER DOCUMENTO
        # ==============================================================

        elif intent == "read_document":

            path = intent_data.get("path")

            return self.workspace_manager.read_document(
                path
            )

        # ==============================================================
        # LISTAR ARCHIVOS
        # ==============================================================

        elif intent == "list_workspace":

            return self.workspace_manager.get_workspace_tree()

        # ==============================================================
        # FACESYNC
        # ==============================================================

        elif intent == "execute_facesync":

            return self._execute_facesync(
                intent_data
            )

        # ==============================================================
        # IA GENERAL
        # ==============================================================

        else:

            return self._ask_gemini(
                intent_data
            )

    # ==================================================================
    # GEMINI FALLBACK
    # ==================================================================

    def _ask_gemini(self, intent_data: dict) -> str:
        """
        Usa Gemini como razonador general.
        """

        prompt = f"""
Analiza esta intención del usuario:

{json.dumps(intent_data, indent=2, ensure_ascii=False)}

Contexto:
{self.context_manager.get_context_summary()}

Workspace:
{self.workspace_manager.get_workspace_summary()}

Responde de forma profesional.
"""

        response = self.chat_session.send_message(
            prompt
        )

        try:
            return response.text
        except:
            return "✅ Operación procesada."

    # ==================================================================
    # EXECUTE FACESYNC
    # ==================================================================

    def _execute_facesync(self, intent_data: dict) -> str:
        """
        Ejecuta motor FaceSync.
        """

        try:

            excel_path = intent_data.get("excel_path")
            photos_path = intent_data.get("photos_path")
            output_path = intent_data.get("output_path")

            # ==========================================================
            # VALIDAR
            # ==========================================================

            SecurityManager.validate_path(
                excel_path,
                self.workspace_path
            )

            SecurityManager.validate_path(
                photos_path,
                self.workspace_path
            )

            SecurityManager.validate_path(
                output_path,
                self.workspace_path
            )

            # ==========================================================
            # IMPORT DINÁMICO
            # ==========================================================

            from facesyncApp.motor_ia import MotorFaceSync

            # ==========================================================
            # CALLBACK
            # ==========================================================

            def callback(success, message):

                status = "✅" if success else "❌"

                self.log(
                    f"{status} FaceSync: {message}"
                )

            # ==========================================================
            # EJECUCIÓN
            # ==========================================================

            MotorFaceSync.iniciar_reconocimiento_en_hilo(
                ruta_carpeta_fotos=photos_path,
                ruta_excel=excel_path,
                carpeta_destino=output_path,
                callback_resultado=callback
            )

            return """
🚀 FaceSync iniciado correctamente.

El reconocimiento facial se está ejecutando
en segundo plano.
"""

        except Exception as e:

            traceback.print_exc()

            return f"""
❌ Error ejecutando FaceSync:

{str(e)}
"""

    # ==================================================================
    # SHUTDOWN
    # ==================================================================

    def shutdown(self):
        """
        Apaga el agente.
        """

        self.running = False

        self.log("🛑 AgentController apagado.")

    # ==================================================================
    # INFO
    # ==================================================================

    def get_status(self) -> dict:
        """
        Estado general del agente.
        """

        return {
            "running": self.running,
            "workspace": self.workspace_path,
            "context_messages": len(
                self.context_manager.messages
            ),
            "memory_entries": self.memory_manager.count(),
        }

