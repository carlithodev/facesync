"""
chat_service.py — Cerebro del asistente IA, versión HEADLESS para el sidecar.

Replica fielmente la lógica de facesyncApp.agente_ia.AsistenteFaceSync SIN los
widgets de CustomTkinter: en vez de escribir en un textbox y marshalar con
`.after(...)` del loop de Tk, llama a un callback `emit(role, text)` que el
bridge convierte en eventos de progreso hacia React.

Pipeline (igual que el original):
  1. local_router.try_handle(texto)  -> si handled, responde sin LLM.
  2. OpenAI fallback (SmartOrchestrator) -> interpretación estructurada.
  3. Gemini (chat con tools del workspace) -> con rotación de modelo y retry
     ante saturación (503) / rate limit (429).

Reusa EXACTAMENTE los mismos componentes que el original: ContextManager,
LocalCommandRouter, SmartOrchestrator, AgentToolRegistry, construir_prompt,
SecurityManager y google.genai.
"""

import os
import re
import traceback
import json
import threading

from dotenv import load_dotenv

from core.context_manager import ContextManager
from core.app_paths import private_env_path
from core.local_command_router import LocalCommandRouter
from core.text_normalizer import TextNormalizer

load_dotenv(private_env_path())
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

GEMINI_MODELS = ["gemini-2.0-flash", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
DEFAULT_GEMINI_MODEL = GEMINI_MODELS[0]
ENV_GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()


def _es_rate_limit_error(error):
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    if code == 429:
        return True
    s = str(error).upper()
    return "RESOURCE_EXHAUSTED" in s or re.search(r"\b429\b", s) is not None


def _es_error_saturacion_modelo(error):
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    if code == 503:
        return True
    s = str(error).upper()
    return ("UNAVAILABLE" in s or "HIGH DEMAND" in s
            or "TEMPORARILY UNAVAILABLE" in s or re.search(r"\b503\b", s) is not None)


class ChatService:
    """Asistente headless. `emit(role, text)` recibe cada mensaje (Tú/Sistema/Asistente).
    `on_progress(data)` recibe el progreso del motor cuando se clasifica desde el chat."""

    def __init__(self, roots=None, emit=None, on_progress=None, account_id="default"):
        self.emit = emit or (lambda role, text: None)
        self.on_progress = on_progress or (lambda data: None)
        self.account_id = str(account_id or "default").strip() or "default"
        self.ruta_workspace = self._norm(roots[0]) if roots else None
        self.client = None
        self.registry = None
        self.chat_session = None
        self.modelo_gemini = ENV_GEMINI_MODEL if ENV_GEMINI_MODEL in GEMINI_MODELS else DEFAULT_GEMINI_MODEL
        self._gemini_config_kwargs = None
        self._cancel_event = threading.Event()
        self.context_manager = ContextManager()
        self.context_manager.set_user_key(self.account_id)
        try:
            from ai.smart_orchestrator import SmartOrchestrator
            self.openai_orchestrator = SmartOrchestrator.from_env()
        except Exception:
            self.openai_orchestrator = None
        if self.ruta_workspace:
            self.context_manager.set_workspace(self.ruta_workspace)
            self.context_manager.restore_from_vault()
        self.local_router = LocalCommandRouter(
            workspace_path=self.ruta_workspace,
            context_manager=self.context_manager,
            async_callback=self._on_facesync_async_result,
            account_id=self.account_id,
        )
        if roots:
            self.set_workspace_roots(roots, reiniciar=False)
        self._inicializar_ia()

    # ------------------------------------------------------------------
    @staticmethod
    def _norm(ruta):
        if not ruta:
            return None
        try:
            from pathlib import Path
            p = Path(ruta).expanduser().resolve()
            return str(p) if p.is_dir() else None
        except Exception:
            return None

    def set_workspace_roots(self, roots, reiniciar=True):
        cleaned, seen = [], set()
        for r in (roots or []):
            n = self._norm(r)
            if n and n not in seen:
                seen.add(n)
                cleaned.append(n)
        if not cleaned:
            return
        self.ruta_workspace = cleaned[0]
        self.context_manager.set_project_root(cleaned[0])
        self.local_router.set_project_root(cleaned[0])
        if hasattr(self.context_manager, "set_workspace_roots"):
            self.context_manager.set_workspace_roots(cleaned)
        if hasattr(self.local_router, "set_workspace_roots"):
            self.local_router.set_workspace_roots(cleaned)
        if reiniciar:
            self._inicializar_ia(saludo=False)

    # ------------------------------------------------------------------
    def _crear_chat_session(self):
        from google.genai import types
        self.chat_session = self.client.chats.create(
            model=self.modelo_gemini,
            config=types.GenerateContentConfig(**self._gemini_config_kwargs),
        )
        return self.chat_session

    def _cambiar_al_siguiente_modelo(self):
        try:
            idx = GEMINI_MODELS.index(self.modelo_gemini)
        except ValueError:
            idx = -1
        if idx + 1 >= len(GEMINI_MODELS):
            return False
        self.modelo_gemini = GEMINI_MODELS[idx + 1]
        self._crear_chat_session()
        return True

    def _inicializar_ia(self, saludo=True):
        self.registry = None
        self.chat_session = None
        try:
            if not API_KEY:
                self.emit("Sistema", "IA avanzada no disponible (falta GEMINI_API_KEY). "
                                     "Las acciones locales siguen funcionando.")
                return
            from google import genai
            from ai.tool_registry import AgentToolRegistry
            from ai.prompts import construir_prompt
            from core.security import SecurityManager

            self.client = genai.Client(api_key=API_KEY)
            tools = []
            mapa = ("No hay workspace activo. Si el usuario pide acciones sobre archivos, "
                    "pídele que seleccione una carpeta primero.")
            if self.ruta_workspace:
                security = SecurityManager(
                    workspace_path=self.ruta_workspace,
                    app_data_root=self.context_manager.get_app_data_root(),
                )
                workspace_roots = self.context_manager.get_workspace_roots()
                if workspace_roots and hasattr(security, "set_workspace_roots"):
                    security.set_workspace_roots(workspace_roots)
                self.registry = AgentToolRegistry()
                self.registry.auto_register_default_tools(
                    workspace_path=self.ruta_workspace,
                    security_manager=security,
                    account_id=self.account_id,
                )
                tools = self.registry.get_tool_callables()
                mapa = f"\nTu workspace actual es: {self.ruta_workspace}\n"

            instrucciones = construir_prompt(
                modo="base", workspace_tree=mapa,
                memory_context=self.context_manager.get_context_summary(),
                last_action_details="Ninguna")
            self._gemini_config_kwargs = {"system_instruction": instrucciones, "temperature": 0.4}
            if tools:
                self._gemini_config_kwargs["tools"] = tools
            self._crear_chat_session()
            if saludo:
                self.emit("Asistente", "Hola, soy tu asistente FaceSync. Puedo leer tu Excel, "
                                       "crear carpetas, clasificar fotos y organizar tu workspace.")
        except Exception as e:
            traceback.print_exc()
            self.emit("Sistema", "La IA conversacional no pudo inicializarse. Las acciones locales siguen disponibles.")

    # ------------------------------------------------------------------
    def _on_facesync_async_result(self, success, message, data):
        data = data or {}
        if data.get("event") == "progress":
            self.on_progress(data)
            return
        if success:
            resp = ("Listo, el reconocimiento terminó. Copié las fotos encontradas "
                    "en sus carpetas correspondientes.")
            data["phase"] = "done"
        else:
            resp = f"No pude completar el reconocimiento facial: {message}"
            data["phase"] = "error"
        self.on_progress(data)
        self.context_manager.add_message(role="assistant", content=resp)
        self.emit("Asistente", resp)

    def _guardar_uso_openai_en_vault(self, interpretation):
        usage = (interpretation or {}).get("usage") or {}
        if not usage or not hasattr(self.context_manager, "ensure_context_vault"):
            return
        vault = self.context_manager.ensure_context_vault()
        sid = getattr(self.context_manager, "context_session_id", None)
        if not vault or not sid:
            return
        try:
            vault.save_openai_usage(
                sid, usage.get("model") or (interpretation or {}).get("model_used") or "",
                usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                usage.get("estimated_cost_usd", 0.0), (interpretation or {}).get("intent", ""),
                float((interpretation or {}).get("confidence", 0.0) or 0.0),
                escalated=bool(usage.get("escalated")),
                escalation_reason=usage.get("escalation_reason") or (interpretation or {}).get("escalation_reason", ""))
        except Exception:
            return

    def _intentar_openai_fallback(self, texto):
        if not self.openai_orchestrator or not self.openai_orchestrator.is_available():
            return None
        try:
            normalized = TextNormalizer.normalize(texto)
            local_guess = self.local_router.interpreter.interpret(texto, normalized, self.context_manager)
        except Exception:
            local_guess = None
        if isinstance(local_guess, dict) and local_guess.get("intent") == "analyze_or_explain":
            return None
        if hasattr(self.context_manager, "build_system_state"):
            system_state = self.context_manager.build_system_state(texto)
        else:
            system_state = self.context_manager.current_context
        interpretation = self.openai_orchestrator.interpret(
            user_text=texto, context=system_state, local_guess=local_guess)
        self._guardar_uso_openai_en_vault(interpretation)
        # OpenAI interpreta acciones. Si no encontro una tool aplicable, la
        # consulta debe continuar al interlocutor conversacional (Gemini), no
        # convertirse en un plan vacio bloqueado por ToolExecutionGate.
        if not isinstance(interpretation, dict) or interpretation.get("intent") in {
            "unknown",
            "analyze_or_explain",
        }:
            return None
        source = "local" if interpretation.get("model_used") == "local" else "openai"
        result = self.local_router.handle_structured_interpretation(texto, interpretation, source=source)
        if result and result.action == "retry_smart":
            retry = self.openai_orchestrator.retry_with_smart(
                texto,
                self.context_manager.build_system_state(texto) if hasattr(self.context_manager, "build_system_state") else self.context_manager.current_context,
                local_guess=local_guess,
                previous_result=(result.data or {}).get("interpretation") or interpretation)
            self._guardar_uso_openai_en_vault(retry)
            return self.local_router.handle_structured_interpretation(texto, retry, source="openai")
        return result

    # ------------------------------------------------------------------
    def request_cancel(self):
        self._cancel_event.set()
        try:
            self.local_router.request_cancel()
        except Exception:
            pass

    def get_history(self):
        """Historial visible de la sesion activa, aislado por cuenta."""
        history = []
        for item in self.context_manager.get_messages():
            role = str(item.get("role") or "")
            if role == "user":
                ui_role = "Tú"
            elif role == "assistant":
                ui_role = "Asistente"
            else:
                ui_role = "Sistema"
            content = str(item.get("content") or "").strip()
            if content:
                history.append({
                    "role": ui_role,
                    "text": content,
                    "timestamp": item.get("timestamp") or "",
                })
        return history

    def start_new_conversation(self):
        self.request_cancel()
        self.context_manager.start_new_conversation()
        self._inicializar_ia(saludo=False)
        return self.get_history()

    def close(self):
        """Limpia la sesion RAM sin borrar su memoria persistente."""
        self.request_cancel()
        self.chat_session = None
        self.registry = None
        try:
            closer = getattr(self.client, "close", None)
            if callable(closer):
                closer()
        except Exception:
            pass
        self.client = None
        self.context_manager.detach_runtime()

    def send(self, texto):
        """Procesa un mensaje del usuario (síncrono; el bridge lo corre en su hilo)."""
        texto = (texto or "").strip()
        if not texto:
            return
        self._cancel_event.clear()
        self.context_manager.add_message(role="user", content=texto)

        # 1. Local primero.
        try:
            local = self.local_router.try_handle(texto)
            if local and local.handled:
                self.context_manager.add_message(role="assistant", content=local.message)
                self.emit("Asistente", local.message)
                return
        except Exception as exc:
            traceback.print_exc()
            self.emit("Sistema", "No pude completar la acción local. Revisa los datos e inténtalo de nuevo.")
            return

        # 2. OpenAI fallback.
        try:
            r = self._intentar_openai_fallback(texto)
            if r and r.handled:
                self.context_manager.add_message(role="assistant", content=r.message)
                self.emit("Asistente", r.message)
                return
        except Exception as e:
            print(f"[OPENAI_ORCH] error en fallback: {type(e).__name__}: {e}")

        # 3. Gemini.
        if not self.chat_session:
            self.emit("Asistente", "La IA avanzada no está inicializada. Verifica GEMINI_API_KEY "
                                   "y selecciona un workspace válido. (Las acciones locales siguen disponibles.)")
            return
        self._gemini(texto)

    def _gemini_turn_payload(self, texto):
        """Inyecta el contexto canonico actualizado en cada turno de Gemini."""
        try:
            state = self.context_manager.build_system_state(texto)
        except Exception:
            state = dict(self.context_manager.current_context or {})

        raw_run = state.get("last_facesync_run")
        if isinstance(raw_run, dict):
            last_run = {
                key: raw_run.get(key)
                for key in (
                    "table_path",
                    "name_column",
                    "reference_column",
                    "source_folder",
                    "destination_folder",
                    "report_path",
                    "success",
                )
                if raw_run.get(key) not in (None, "", [], {})
            }
            for key in ("copied", "reused", "skipped", "errors"):
                value = raw_run.get(key)
                if isinstance(value, list):
                    last_run[f"{key}_count"] = len(value)
        else:
            last_run = raw_run

        context = {
            "project_root": state.get("project_root"),
            "workspace_roots": (state.get("workspace_roots") or [])[:8],
            "active_path": state.get("active_path"),
            "last_table_path": state.get("last_table_path"),
            "last_table_columns": (state.get("last_table_columns") or [])[:40],
            "last_name_column": state.get("last_name_column"),
            "last_reference_column": state.get("last_reference_column"),
            "last_source_folder": state.get("last_source_folder"),
            "last_destination_folder": state.get("last_destination_folder"),
            "last_facesync_run": last_run,
            "pending_action": state.get("pending_action") or state.get("active_pending_action"),
            "conversation_summary": state.get("conversation_summary"),
            "recent_user_messages": (state.get("recent_user_messages") or [])[-8:],
            "recent_assistant_messages": (state.get("recent_assistant_messages") or [])[-8:],
            "available_files": (state.get("available_files") or [])[:40],
            "available_folders": (state.get("available_folders") or [])[:40],
        }
        compact = {
            key: value for key, value in context.items()
            if value not in (None, "", [], {})
        }
        return (
            "<contexto_operativo_actualizado>\n"
            + json.dumps(compact, ensure_ascii=False, default=str)
            + "\n</contexto_operativo_actualizado>\n\n"
            + "Solicitud actual del usuario:\n"
            + str(texto or "")
        )

    def _gemini(self, texto):
        payload = self._gemini_turn_payload(texto)
        for intento in range(3):
            if self._cancel_event.is_set():
                self.emit("Sistema", "Solicitud cancelada.")
                return
            try:
                response = self.chat_session.send_message(payload)
                if self._cancel_event.is_set():
                    self.emit("Sistema", "Solicitud cancelada.")
                    return
                try:
                    resp = response.text or "✅ Operación ejecutada."
                except ValueError:
                    resp = "✅ Operación completada (sin respuesta de texto)."
                except Exception:
                    resp = "✅ Operación procesada."
                self.context_manager.add_message(role="assistant", content=resp)
                self.emit("Asistente", resp)
                return
            except Exception as e:
                err = str(e)
                if _es_error_saturacion_modelo(e):
                    try:
                        if self._cambiar_al_siguiente_modelo():
                            self.emit("Sistema", f"Gemini saturado. Cambiando a {self.modelo_gemini}…")
                            continue
                    except Exception:
                        traceback.print_exc()
                        self.emit("Asistente", "La IA está saturada y no pude activar el modelo de respaldo.")
                        return
                    self.emit("Asistente", "Gemini está ocupado temporalmente. Puedo seguir con acciones "
                                           "locales (crear/mover/buscar/leer).")
                    return
                if _es_rate_limit_error(e):
                    if intento >= 2:
                        self.emit("Asistente", "La IA avanzada alcanzó su límite temporal, pero las "
                                               "acciones locales siguen disponibles.")
                        return
                    espera = 30
                    m = re.search(r"retry in (\d+(?:\.\d+)?)s", err, re.IGNORECASE)
                    if m:
                        espera = int(float(m.group(1))) + 2
                    self.emit("Sistema", f"⏳ Rate limit. Reintentando en {espera}s (intento {intento + 1}/3)…")
                    if self._cancel_event.wait(espera):
                        self.emit("Sistema", "Solicitud cancelada.")
                        return
                    continue
                traceback.print_exc()
                self.emit("Asistente", "No pude procesar esa solicitud en este momento. Inténtalo nuevamente.")
                return
