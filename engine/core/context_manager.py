
"""
======================================================================
CONTEXT MANAGER — FaceSync AI Core
======================================================================

Gestor de contexto conversacional y operativo del agente.

Responsabilidades:
- Mantener historial conversacional
- Gestionar contexto temporal
- Recordar referencias recientes
- Mantener estado operativo
- Resolver referencias implícitas
- Administrar contexto del workspace

Ejemplos:
    "muévelo a la otra carpeta"
    "usa el mismo excel"
    "borra el último archivo"
    "ponlo donde estaban las fotos"

======================================================================
"""

# ======================================================================
# IMPORTS
# ======================================================================

from datetime import datetime, timedelta
from collections import deque
from pathlib import Path
import unicodedata
import os
import logging

from core.app_paths import ensure_app_data_root, filter_internal_names


# ======================================================================
# CONTEXT MANAGER
# ======================================================================

class ContextManager:
    """
    Administrador de contexto del agente.
    """

    # ==================================================================
    # INIT
    # ==================================================================

    def __init__(self, max_messages: int = 50):

        # ==============================================================
        # HISTORIAL CONVERSACIONAL
        # ==============================================================

        self.messages = deque(maxlen=max_messages)

        # ==============================================================
        # CONTEXTO OPERATIVO
        # ==============================================================

        self.current_context = {

            # Último archivo usado
            "last_file": None,

            # Última carpeta usada
            "last_folder": None,

            # Último documento leído
            "last_document": None,

            # Último excel utilizado
            "last_excel": None,

            # Última imagen usada
            "last_image": None,

            # Último PDF
            "last_pdf": None,

            # Último output generado
            "last_output": None,

            # Última búsqueda
            "last_search": None,

            # Última acción
            "last_action": None,

            # Último recurso afectado
            "last_resource": None,

            "project_root": None,
            "workspace_roots": [],
            "app_data_root": None,
            "facesync_workspace": None,
            "default_output_folder": None,
            "workspace_actual": None,
            "active_path": None,
            "available_files": [],
            "available_folders": [],
            "available_columns": [],
            "last_table_path": None,
            "last_table_columns": [],
            "last_table_rows": None,
            "last_source_folder": None,
            "last_destination_folder": None,
            "last_name_column": None,
            "last_reference_column": None,
            "last_created_items": [],
            "last_moved_items": [],
            "last_copied_items": [],
            "last_facesync_run": None,
            "active_pending_action": None,
            "recent_intents": [],
            "recent_errors": [],
            "conversation_summary": "",
            "learning_hints": [],
            "context_summary": {},
            "context_vault_db_path": None,
            "recent_user_messages": [],
            "recent_assistant_messages": [],
            "last_successful_action": None,
            "last_failed_action": None,
            "last_error_type": None,
            "last_interpretation_error": None,
            "ultima_accion": None,
            "ultima_ruta_usada": None,
            "ultima_carpeta_creada": None,
            "ultimo_archivo_creado": None,
            "ultimo_documento_leido": None,
            "ultimo_excel_leido": None,
            "ultimo_pdf_leido": None,
            "ultima_columna_detectada": None,
            "ultima_columna_referencia": None,
            "ultima_carpeta_destino": None,
            "ultima_carpeta_fotos": None,
            "ultimo_elemento_modificado": None,
            "ultima_busqueda": None,
            "ultimos_resultados_busqueda": [],
            "ultimo_plan": None,
            "ultimo_facesync_plan": None,
            "pending_action": None,
            "pending_intent": None,
            "missing_slot": None,
            "last_question": None,
            "last_prompt_type": None,
            "last_intent": None,
            "last_args": {},
            "ultimo_intent": None,
            "ultimo_plan_gemini": None,
            "ultima_accion_ejecutada": None,
            "historial_acciones_recientes": [],
        }

        # ==============================================================
        # ENTIDADES DETECTADAS
        # ==============================================================

        self.entities = {
            "people": [],
            "folders": [],
            "documents": [],
            "images": [],
            "projects": [],
        }

        # ==============================================================
        # ESTADO DE SESIÓN
        # ==============================================================

        self.session_data = {
            "session_started": datetime.now(),
            "total_messages": 0,
            "last_activity": None,
        }

        self.context_vault = None
        self.context_user_key = "local_user"
        self.context_user_id = None
        self.context_project_id = None
        self.context_session_id = None
        self._context_vault_warning_logged = False

    # ==================================================================
    # MENSAJES
    # ==================================================================

    def add_message(self, role: str, content: str):
        """
        Agrega mensaje al historial.
        """

        if self.messages.maxlen and len(self.messages) >= self.messages.maxlen:
            oldest = self.messages[0]
            previous = str(self.current_context.get("conversation_summary") or "")
            line = f"{oldest.get('role', 'message')}: {str(oldest.get('content') or '')[:600]}"
            self.current_context["conversation_summary"] = (previous + "\n" + line).strip()[-6000:]

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }

        self.messages.append(message)

        if role == "user":
            recent = self.current_context.get("recent_user_messages")
            if not isinstance(recent, list):
                recent = []
                self.current_context["recent_user_messages"] = recent
            recent.append(content)
            del recent[:-10]
        elif role == "assistant":
            recent = self.current_context.get("recent_assistant_messages")
            if not isinstance(recent, list):
                recent = []
                self.current_context["recent_assistant_messages"] = recent
            recent.append(content)
            del recent[:-10]

        self.session_data["total_messages"] += 1
        self.session_data["last_activity"] = datetime.now()
        self.save_message_to_vault(role, content)
        if role == "assistant":
            self.save_context_snapshot_to_vault(self.current_context)

    # ==================================================================
    # OBTENER HISTORIAL
    # ==================================================================

    def get_messages(self):
        """
        Devuelve historial completo.
        """

        return list(self.messages)

    # ==================================================================
    # ÚLTIMO MENSAJE
    # ==================================================================

    def get_last_message(self):
        """
        Obtiene último mensaje.
        """

        if not self.messages:
            return None

        return self.messages[-1]

    # ==================================================================
    # RESUMEN CONTEXTO
    # ==================================================================

    def get_context_summary(self) -> str:
        """
        Genera resumen contextual para IA.
        """

        summary = []

        summary.append("=== CONTEXTO ACTUAL ===")

        for key, value in self.current_context.items():

            if value:
                summary.append(f"{key}: {value}")

        summary.append("\n=== HISTORIAL RECIENTE ===")

        recent = list(self.messages)[-5:]

        for msg in recent:

            role = msg["role"]

            content = msg["content"]

            summary.append(f"{role}: {content}")

        return "\n".join(summary)

    def build_system_state(self, user_text: str = "") -> dict:
        """
        Devuelve el SystemState compacto que consume el orquestador.

        Mantiene la memoria RAM actual y, si ContextVault esta disponible,
        incorpora su resumen persistente sin incluir contenido masivo.
        """

        self.refresh_available_entries()
        state = dict(self.current_context)
        project_root = state.get("project_root") or state.get("workspace_actual")
        active_path = state.get("active_path")
        if project_root:
            state["project_root_name"] = Path(str(project_root)).name
        if active_path:
            state["active_path_name"] = Path(str(active_path)).name
        if user_text:
            state["_user_text"] = user_text
            state["last_user_text"] = user_text

        vault_summary = self.get_vault_context_summary()
        if vault_summary:
            state["context_summary"] = vault_summary
            for key, value in vault_summary.items():
                if value not in (None, "", []):
                    state.setdefault(key, value)
                    if not state.get(key):
                        state[key] = value
        state["active_pending_action"] = state.get("pending_action") or state.get("active_pending_action")
        return self._compact_state(state)

    def set_user_key(self, user_key: str):
        """Fija la identidad propietaria del contexto conversacional.

        Cambiar de cuenta invalida todos los ids y memoria RAM de la cuenta
        anterior. La informacion persistente permanece en SQLite y se recupera
        cuando esa cuenta vuelva a iniciar sesion.
        """
        normalized = str(user_key or "local_user").strip() or "local_user"
        if normalized == self.context_user_key:
            return normalized
        self._close_vault_if_file(self.context_vault)
        self.context_user_key = normalized
        self.context_user_id = None
        self.context_project_id = None
        self.context_session_id = None
        self.clear_messages()
        self.current_context["recent_user_messages"] = []
        self.current_context["recent_assistant_messages"] = []
        self.current_context["active_pending_action"] = None
        self.current_context["pending_action"] = None
        self.current_context["pending_intent"] = None
        return normalized

    def ensure_context_vault(self, user_key: str | None = None):
        """
        Inicializa ContextVault sin hacer fallar la app si SQLite no esta disponible.
        """

        try:
            from core.context_vault import ContextVault

            requested_user = str(user_key or self.context_user_key or "local_user").strip() or "local_user"
            if requested_user != self.context_user_key:
                self.set_user_key(requested_user)

            app_data_root = self.get_app_data_root()
            if self.context_vault is None:
                self.context_vault = ContextVault(
                    user_app_data_root=app_data_root,
                    app_data_root=app_data_root,
                    logger=logging.getLogger(__name__),
                ).initialize()
                self.current_context["context_vault_db_path"] = str(getattr(self.context_vault, "db_path", "") or "")

            if self.context_user_id is None:
                self.context_user_id = self.context_vault.get_or_create_user(self.context_user_key)

            project_root = self.get_project_root()
            if project_root and self.context_project_id is None:
                self.context_project_id = self.context_vault.get_or_create_project(self.context_user_id, project_root)

            if self.context_project_id is not None and self.context_session_id is None:
                starter = getattr(self.context_vault, "get_or_start_session", None)
                if callable(starter):
                    self.context_session_id = starter(self.context_user_id, self.context_project_id)
                else:
                    self.context_session_id = self.context_vault.start_session(self.context_user_id, self.context_project_id)

            return self.context_vault
        except Exception as exc:
            if not self._context_vault_warning_logged:
                print(f"[ContextVault] warning: {type(exc).__name__}: {exc}")
                self._context_vault_warning_logged = True
            return None

    def restore_from_vault(self, limit: int = 50) -> list[dict]:
        """Restaura historial y contexto operativo de la sesion activa."""
        vault = self.ensure_context_vault()
        if not vault or not self.context_session_id or not self.context_project_id:
            return []
        try:
            loader = getattr(vault, "get_session_messages", None)
            history = loader(self.context_session_id, limit=limit) if callable(loader) else []
            self.messages.clear()
            recent_user = []
            recent_assistant = []
            for item in history:
                role = str(item.get("role") or "")
                content = str(item.get("content") or "")
                self.messages.append({
                    "role": role,
                    "content": content,
                    "timestamp": item.get("timestamp") or datetime.now().isoformat(),
                })
                if role == "user":
                    recent_user.append(content)
                elif role == "assistant":
                    recent_assistant.append(content)
            self.current_context["recent_user_messages"] = recent_user[-10:]
            self.current_context["recent_assistant_messages"] = recent_assistant[-10:]

            summary = vault.get_context_summary(self.context_session_id, self.context_project_id)
            if isinstance(summary, dict):
                self.current_context["context_summary"] = summary
                for key, value in summary.items():
                    if value not in (None, "", []):
                        self.current_context[key] = value
                pending = summary.get("active_pending_action")
                if isinstance(pending, dict):
                    self.set_pending_action(self._hydrate_pending_action(pending))
            return list(self.messages)
        except Exception as exc:
            if not self._context_vault_warning_logged:
                print(f"[ContextVault] restore warning: {type(exc).__name__}: {exc}")
                self._context_vault_warning_logged = True
            return []
        finally:
            self._close_vault_if_file(vault)

    def start_new_conversation(self) -> list[dict]:
        """Cierra el hilo activo y crea uno vacio para la misma cuenta/proyecto."""
        vault = self.ensure_context_vault()
        if not vault or not self.context_user_id or not self.context_project_id:
            self.clear_messages()
            return []
        try:
            if self.context_session_id:
                vault.end_session(self.context_session_id)
            self.context_session_id = vault.start_session(self.context_user_id, self.context_project_id)
            self.clear_messages()
            for key in (
                "recent_user_messages",
                "recent_assistant_messages",
                "recent_intents",
                "recent_errors",
                "historial_acciones_recientes",
            ):
                self.current_context[key] = []
            for key in (
                "active_pending_action",
                "pending_action",
                "pending_intent",
                "missing_slot",
                "last_question",
                "last_prompt_type",
            ):
                self.current_context[key] = None
            self.current_context["conversation_summary"] = ""
            return []
        finally:
            self._close_vault_if_file(vault)

    def detach_runtime(self):
        """Descarta datos RAM al cerrar sesion sin borrar su memoria SQLite."""
        self._close_vault_if_file(self.context_vault)
        self.clear_messages()
        self.context_user_id = None
        self.context_project_id = None
        self.context_session_id = None

    def get_vault_context_summary(self) -> dict:
        vault = self.ensure_context_vault()
        if not vault or not self.context_session_id or not self.context_project_id:
            return {}
        try:
            summary = vault.get_context_summary(self.context_session_id, self.context_project_id)
            if isinstance(summary, dict):
                self.current_context["context_summary"] = summary
                for key in (
                    "last_table_path",
                    "last_table_columns",
                    "last_name_column",
                    "last_reference_column",
                    "last_source_folder",
                    "last_destination_folder",
                    "last_facesync_run",
                    "recent_intents",
                    "recent_errors",
                    "learning_hints",
                    "active_pending_action",
                ):
                    if summary.get(key) not in (None, "", []):
                        self.current_context[key] = summary.get(key)
                pending = summary.get("active_pending_action")
                if isinstance(pending, dict):
                    self.set_pending_action(self._hydrate_pending_action(pending))
                return summary
        except Exception as exc:
            if not self._context_vault_warning_logged:
                print(f"[ContextVault] summary warning: {type(exc).__name__}: {exc}")
                self._context_vault_warning_logged = True
        finally:
            self._close_vault_if_file(vault)
        return {}

    def save_message_to_vault(self, role: str, message: str, intent: str = "", confidence=None, model_used: str = ""):
        vault = self.ensure_context_vault()
        if not vault or not self.context_session_id:
            return None
        try:
            return vault.save_message(self.context_session_id, role, message, intent=intent, confidence=confidence, model_used=model_used)
        except Exception:
            return None
        finally:
            self._close_vault_if_file(vault)

    def save_context_snapshot_to_vault(self, snapshot: dict | None = None):
        vault = self.ensure_context_vault()
        if not vault or not self.context_session_id:
            return None
        try:
            return vault.save_context_snapshot(self.context_session_id, snapshot or self._compact_state(self.current_context))
        except Exception:
            return None
        finally:
            self._close_vault_if_file(vault)

    def save_detected_table_to_vault(self, file_path: str, columns: list, row_count=None):
        vault = self.ensure_context_vault()
        if not vault or not self.context_project_id:
            return None
        try:
            return vault.save_detected_table(self.context_project_id, file_path, columns, row_count=row_count)
        except Exception:
            return None
        finally:
            self._close_vault_if_file(vault)

    def save_action_to_vault(self, intent: str, args: dict, result: dict | None = None, success: bool = True, error_type: str = "", error_message: str = ""):
        vault = self.ensure_context_vault()
        if not vault or not self.context_session_id:
            return None
        try:
            return vault.save_action(
                self.context_session_id,
                intent,
                args or {},
                result=result or {},
                success=success,
                error_type=error_type,
                error_message=error_message,
            )
        except Exception:
            return None
        finally:
            self._close_vault_if_file(vault)

    def save_pending_action_to_vault(self, intent: str, args: dict, missing_fields: list | None = None, preview_text: str = ""):
        vault = self.ensure_context_vault()
        if not vault or not self.context_session_id:
            return None
        try:
            return vault.save_pending_action(self.context_session_id, intent, args or {}, missing_fields or [], preview_text=preview_text)
        except Exception:
            return None
        finally:
            self._close_vault_if_file(vault)

    def update_pending_action_status_in_vault(self, pending_id, status: str):
        vault = self.ensure_context_vault()
        if not vault or not pending_id:
            return False
        try:
            return bool(vault.update_pending_action_status(int(pending_id), status))
        except Exception:
            return False
        finally:
            self._close_vault_if_file(vault)

    def save_facesync_run_to_vault(
        self,
        table_path: str,
        name_column: str,
        reference_column: str,
        source_folder: str,
        destination_folder: str,
        report_path: str = "",
        success: bool = True,
    ):
        vault = self.ensure_context_vault()
        if not vault or not self.context_session_id:
            return None
        try:
            return vault.save_facesync_run(
                self.context_session_id,
                table_path,
                name_column,
                reference_column,
                source_folder,
                destination_folder,
                report_path=report_path,
                success=success,
            )
        except Exception:
            return None
        finally:
            self._close_vault_if_file(vault)

    def save_failed_interpretation_to_vault(
        self,
        user_text: str,
        system_state: dict,
        bad_intent: str,
        bad_args: dict,
        error_type: str,
        assistant_response: str = "",
    ):
        vault = self.ensure_context_vault()
        if not vault or not self.context_session_id:
            return None
        try:
            return vault.save_failed_interpretation(
                self.context_session_id,
                user_text,
                system_state or {},
                bad_intent,
                bad_args or {},
                error_type,
                assistant_response=assistant_response,
            )
        except Exception:
            return None
        finally:
            self._close_vault_if_file(vault)

    @staticmethod
    def _compact_state(state: dict) -> dict:
        compact = {}
        for key, value in (state or {}).items():
            if key.startswith("_"):
                compact[key] = value
                continue
            if value in (None, ""):
                continue
            if isinstance(value, list):
                compact[key] = value[:80]
            elif isinstance(value, dict):
                compact[key] = {k: value[k] for k in list(value.keys())[:40]}
            else:
                compact[key] = value
        return compact

    @staticmethod
    def _close_vault_if_file(vault):
        if vault and not getattr(vault, "using_memory", False):
            try:
                vault.close()
            except Exception:
                pass

    # ==================================================================
    # ACTUALIZAR CONTEXTO
    # ==================================================================

    def update_context(self, key: str, value):
        """
        Actualiza variable contextual.
        """

        self.current_context[key] = value

    def set_workspace(self, workspace_path: str):
        self.set_project_root(workspace_path)

    def set_app_data_root(self, path: str | None = None):
        app_data_root = str(ensure_app_data_root(path))
        self.current_context["app_data_root"] = app_data_root
        self.current_context["facesync_workspace"] = app_data_root
        return app_data_root

    def get_app_data_root(self):
        return self.current_context.get("app_data_root") or self.set_app_data_root()

    def ensure_app_data_root(self):
        return self.set_app_data_root(self.current_context.get("app_data_root"))

    def set_project_root(self, path: str):
        if not path:
            return
        project_root = str(Path(path).expanduser().resolve(strict=False))
        app_data_root = self.ensure_app_data_root()
        self.current_context["project_root"] = project_root
        self.current_context["workspace_actual"] = project_root
        self.current_context["facesync_workspace"] = app_data_root
        self.current_context["default_output_folder"] = project_root
        active_path = self.current_context.get("active_path")
        if not active_path or not self._is_inside(project_root, active_path):
            self.current_context["active_path"] = project_root
        self.refresh_available_entries()

    def set_workspace_roots(self, roots):
        """Workspace compuesto: varias carpetas raiz. La primera es la primaria.
        El asistente busca en todas; con una sola se comporta como antes."""
        resolved = []
        for r in roots or []:
            if r:
                rp = str(Path(r).expanduser().resolve(strict=False))
                if rp not in resolved:
                    resolved.append(rp)
        self.current_context["workspace_roots"] = resolved
        if resolved:
            self.set_project_root(resolved[0])

    def get_workspace_roots(self):
        roots = self.current_context.get("workspace_roots") or []
        if roots:
            return list(roots)
        primary = self.get_project_root()
        return [primary] if primary else []

    def get_project_root(self):
        return self.current_context.get("project_root") or self.current_context.get("workspace_actual")

    def get_facesync_workspace(self):
        return self.get_app_data_root()

    def ensure_facesync_workspace(self):
        return self.ensure_app_data_root()

    def set_active_path(self, active_path: str):
        if active_path:
            resolved = str(Path(active_path).expanduser().resolve(strict=False))
            roots = self.get_workspace_roots()
            if roots and not any(self._is_inside(r, resolved) for r in roots):
                return
            self.current_context["active_path"] = resolved

    def get_active_path(self):
        return self.current_context.get("active_path")

    def resolve_default_destination(self):
        return (
            self.current_context.get("default_output_folder")
            or self.current_context.get("project_root")
            or self.current_context.get("workspace_actual")
        )

    def refresh_available_entries(self, max_items: int = 500):
        project_root = self.get_project_root()
        if not project_root:
            self.current_context["available_files"] = []
            self.current_context["available_folders"] = []
            return

        primary = Path(project_root).resolve(strict=False)
        roots = [Path(item).resolve(strict=False) for item in self.get_workspace_roots() if item]
        if primary not in roots:
            roots.insert(0, primary)
        files = []
        folders = []
        seen_files = set()
        seen_folders = set()
        blocked = {".git", "__pycache__", "env", "venv", "env_ia", "node_modules"}
        for root in roots:
            try:
                for current_root, dirnames, filenames in os.walk(root):
                    dirnames[:] = filter_internal_names([name for name in dirnames if name not in blocked])
                    current = Path(current_root)
                    for dirname in dirnames:
                        if len(folders) >= max_items:
                            break
                        path = (current / dirname).resolve(strict=False)
                        key = str(path).lower()
                        if key in seen_folders:
                            continue
                        seen_folders.add(key)
                        label = str(path.relative_to(primary)).replace("\\", "/") if self._is_inside(str(primary), str(path)) else str(path)
                        folders.append(label)
                    for filename in filenames:
                        if len(files) >= max_items:
                            break
                        path = (current / filename).resolve(strict=False)
                        key = str(path).lower()
                        if key in seen_files:
                            continue
                        seen_files.add(key)
                        label = str(path.relative_to(primary)).replace("\\", "/") if self._is_inside(str(primary), str(path)) else str(path)
                        files.append(label)
                    if len(files) >= max_items and len(folders) >= max_items:
                        break
            except Exception:
                continue
            if len(files) >= max_items and len(folders) >= max_items:
                break
        self.current_context["available_files"] = files
        self.current_context["available_folders"] = folders

    @staticmethod
    def _is_inside(root: str, value: str) -> bool:
        try:
            Path(value).expanduser().resolve(strict=False).relative_to(
                Path(root).expanduser().resolve(strict=False)
            )
            return True
        except Exception:
            return False

    def resolve_user_destination(self, text: str = "", slots: dict | None = None):
        slots = slots or {}
        destination = slots.get("destination_folder") or slots.get("destination")
        if destination:
            return destination
        norm = self._normalize_text(text)
        if any(phrase in norm for phrase in ("aqui", "aca", "en esta carpeta", "donde estoy", "carpeta seleccionada")):
            return self.get_active_path()
        if any(phrase in norm for phrase in ("workspace interno", "datos internos", "carpeta interna", "app data")):
            return self.get_app_data_root()
        if any(phrase in norm for phrase in ("carpeta principal", "project root", "raiz del proyecto", "workspace", "carpeta de trabajo")):
            return self.get_project_root()
        return self.resolve_default_destination()

    def remember_action(self, action_name: str, **kwargs):
        """
        Guarda datos operativos recientes para resolver referencias como "ahi" o "ese archivo".
        """

        self.current_context["last_action"] = action_name
        self.current_context["ultima_accion"] = action_name
        self.current_context["ultimo_intent"] = action_name
        self.current_context["last_intent"] = action_name
        self.current_context["ultima_accion_ejecutada"] = action_name

        aliases = {
            "path": ["ultima_ruta_usada", "last_resource"],
            "folder": ["last_folder", "ultima_carpeta_creada", "ultima_carpeta_destino", "last_resource", "last_destination_folder"],
            "destination": ["ultima_carpeta_destino", "last_folder", "last_destination_folder"],
            "source_folder": ["ultima_carpeta_fotos", "last_source_folder"],
            "photo_folder": ["ultima_carpeta_fotos"],
            "file": ["last_file", "ultimo_archivo_creado", "last_resource"],
            "document": ["last_document", "ultimo_documento_leido", "last_resource"],
            "excel": ["last_excel", "ultimo_excel_leido", "last_document", "ultimo_documento_leido", "last_resource", "last_table_path"],
            "pdf": ["last_pdf", "ultimo_pdf_leido", "last_document", "ultimo_documento_leido", "last_resource"],
            "modified": ["ultimo_elemento_modificado", "last_resource"],
            "search": ["last_search", "ultima_busqueda"],
            "search_results": ["ultimos_resultados_busqueda"],
            "column": ["ultima_columna_detectada", "last_name_column"],
            "table_columns": ["last_table_columns", "available_columns"],
            "reference_column": ["ultima_columna_referencia", "last_reference_column"],
            "plan": ["ultimo_plan", "ultimo_plan_gemini"],
            "facesync_plan": ["ultimo_facesync_plan"],
            "pending_action": ["pending_action"],
            "pending_intent": ["pending_intent"],
            "missing_slot": ["missing_slot"],
            "question": ["last_question"],
            "prompt_type": ["last_prompt_type"],
            "args": ["last_args"],
            "intent": ["ultimo_intent"],
        }

        for key, value in kwargs.items():
            if value is None:
                continue
            for context_key in aliases.get(key, [key]):
                self.current_context[context_key] = value

        created_items = self.current_context.get("last_created_items")
        if not isinstance(created_items, list):
            created_items = []
            self.current_context["last_created_items"] = created_items
        moved_items = self.current_context.get("last_moved_items")
        if not isinstance(moved_items, list):
            moved_items = []
            self.current_context["last_moved_items"] = moved_items
        item_value = kwargs.get("path") or kwargs.get("folder") or kwargs.get("file") or kwargs.get("modified")
        if item_value and action_name in {"create_folder", "create_multiple_folders", "create_file", "create_multiple_files", "create_folders_from_excel"}:
            if isinstance(item_value, list):
                created_items.extend(item_value)
            else:
                created_items.append(item_value)
            del created_items[:-20]
        if item_value and action_name in {"move_item", "move_multiple_items"}:
            moved_items.append(item_value)
            del moved_items[:-20]

        history = self.current_context.get("historial_acciones_recientes")
        if not isinstance(history, list):
            history = []
            self.current_context["historial_acciones_recientes"] = history
        history.append({
            "action": action_name,
            "timestamp": datetime.now().isoformat(),
            "data": kwargs,
        })
        del history[:-20]

        if action_name != "plan":
            self.current_context["last_successful_action"] = action_name
            self.current_context["last_error_type"] = None

    def set_pending_action(self, action: dict):
        self.current_context["pending_action"] = action
        self.current_context["active_pending_action"] = action
        self.current_context["pending_intent"] = (action or {}).get("intent")
        self.current_context["missing_slot"] = (action or {}).get("missing_slot")
        self.current_context["last_question"] = (action or {}).get("question")
        self.current_context["last_prompt_type"] = (action or {}).get("last_prompt_type") or "clarification"
        self.current_context["last_args"] = (action or {}).get("args") or {}

    @staticmethod
    def _hydrate_pending_action(action: dict) -> dict:
        """Reconstruye metadatos conversacionales guardados en SQLite."""
        pending = dict(action or {})
        args = dict(pending.get("args") or {})
        missing = [str(item) for item in (pending.get("missing_fields") or []) if str(item)]
        pending.setdefault("pipeline", "structured")
        pending.setdefault("pending_id", pending.get("id"))
        pending.setdefault("missing_slot", missing[0] if missing else "")
        pending.setdefault("question", pending.get("preview_text") or "")
        pending.setdefault("last_prompt_type", "clarification" if missing else "confirmation")
        candidates = args.get("_location_candidates") or []
        if candidates:
            pending.setdefault("location_candidates", list(candidates))
            pending.setdefault("location_field", args.get("_location_field") or pending.get("missing_slot") or "target")
            pending.setdefault("location_query", args.get("_location_query") or "")
            pending["requires_confirmation"] = False
        return pending

    def get_pending_action(self):
        return self.current_context.get("pending_action")

    def clear_pending_action(self):
        pending = self.current_context.get("pending_action")
        if isinstance(pending, dict) and pending.get("pending_id") and not pending.get("pending_status_finalized"):
            self.update_pending_action_status_in_vault(pending.get("pending_id"), "cleared")
        self.current_context["pending_action"] = None
        self.current_context["active_pending_action"] = None
        self.current_context["pending_intent"] = None
        self.current_context["missing_slot"] = None
        self.current_context["last_question"] = None
        self.current_context["last_prompt_type"] = None
        self.current_context["last_args"] = {}

    def has_pending_action(self) -> bool:
        return bool(self.current_context.get("pending_action"))

    def is_pending_expired(self, max_age_minutes: int = 30) -> bool:
        pending = self.current_context.get("pending_action")
        if not pending:
            return False
        created_at = pending.get("created_at")
        if not created_at:
            return False
        try:
            created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            now = datetime.now(created.tzinfo) if created.tzinfo else datetime.now()
            return now - created > timedelta(minutes=max_age_minutes)
        except Exception:
            return False

    # ==================================================================
    # OBTENER CONTEXTO
    # ==================================================================

    def get_context(self, key: str):
        """
        Obtiene valor contextual.
        """

        return self.current_context.get(key)

    # ==================================================================
    # LIMPIAR CONTEXTO
    # ==================================================================

    def clear_context(self):
        """
        Limpia contexto temporal.
        """

        for key in self.current_context:
            self.current_context[key] = None

    # ==================================================================
    # REGISTRAR ARCHIVO
    # ==================================================================

    def register_file(self, file_path: str):
        """
        Registra archivo usado recientemente.
        """

        self.current_context["last_file"] = file_path
        self.current_context["last_resource"] = file_path

    # ==================================================================
    # REGISTRAR CARPETA
    # ==================================================================

    def register_folder(self, folder_path: str):
        """
        Registra carpeta usada recientemente.
        """

        self.current_context["last_folder"] = folder_path
        self.current_context["last_resource"] = folder_path

    # ==================================================================
    # REGISTRAR DOCUMENTO
    # ==================================================================

    def register_document(self, document_path: str):
        """
        Registra documento reciente.
        """

        self.current_context["last_document"] = document_path
        self.current_context["last_resource"] = document_path

        # ==============================================================
        # DETECTAR TIPO
        # ==============================================================

        lower = document_path.lower()

        if lower.endswith(".xlsx") or lower.endswith(".xls"):
            self.current_context["last_excel"] = document_path

        elif lower.endswith(".pdf"):
            self.current_context["last_pdf"] = document_path

    # ==================================================================
    # REGISTRAR IMAGEN
    # ==================================================================

    def register_image(self, image_path: str):
        """
        Registra imagen reciente.
        """

        self.current_context["last_image"] = image_path
        self.current_context["last_resource"] = image_path

    # ==================================================================
    # REGISTRAR OUTPUT
    # ==================================================================

    def register_output(self, output_path: str):
        """
        Registra salida generada.
        """

        self.current_context["last_output"] = output_path

    # ==================================================================
    # REGISTRAR ACCIÓN
    # ==================================================================

    def register_action(self, action_name: str):
        """
        Registra última acción ejecutada.
        """

        self.current_context["last_action"] = action_name

    # ==================================================================
    # RESOLVER REFERENCIAS
    # ==================================================================

    def resolve_reference(self, text: str):
        """
        Resuelve referencias implícitas.

        Ejemplos:
            "ese archivo"
            "la carpeta anterior"
            "el excel"
            "la última imagen"
        """

        raw_text = str(text or "")
        normalized_text = unicodedata.normalize("NFKD", raw_text)
        normalized_text = "".join(ch for ch in normalized_text if not unicodedata.combining(ch)).lower()

        if any(phrase in normalized_text for phrase in ["workspace interno", "datos internos", "carpeta interna", "app data"]):
            return (
                self.current_context.get("app_data_root")
                or self.current_context.get("facesync_workspace")
            )

        if any(phrase in normalized_text for phrase in ["carpeta principal", "project root", "raiz del proyecto", "en workspace", "en facesync", "carpeta de trabajo", "carpeta principal de facesync"]):
            return self.current_context.get("project_root") or self.current_context.get("workspace_actual")

        if any(word in normalized_text for word in [
            "esa carpeta",
            "carpeta anterior",
            "la carpeta anterior",
            "la de antes",
            "que acabas de crear",
            "que acabo de crear",
            "que acabamos de crear",
            "recien creada",
            "recien creado",
        ]):
            return (
                self._last_created_item()
                or self.current_context.get("ultima_carpeta_destino")
                or self.current_context.get("last_folder")
                or self.current_context.get("ultima_carpeta_creada")
                or self.current_context.get("active_path")
            )

        if any(word in normalized_text for word in ["donde estoy", "aqui", "aca", "ahi", "alli", "esta carpeta", "carpeta seleccionada"]):
            return (
                self.current_context.get("active_path")
                or self.current_context.get("ultima_carpeta_destino")
                or self.current_context.get("last_folder")
                or self.current_context.get("ultima_carpeta_creada")
                or self.current_context.get("workspace_actual")
            )

        if any(word in normalized_text for word in ["lo ultimo", "ultimo", "el ultimo", "la ultima"]):
            return (
                self.current_context.get("ultimo_elemento_modificado")
                or self.current_context.get("last_resource")
                or self.current_context.get("ultima_ruta_usada")
            )

        if "archivo" in normalized_text or "renombralo" in normalized_text or "muevelo" in normalized_text:
            return self.current_context.get("last_file") or self.current_context.get("ultimo_archivo_creado")

        if "excel" in normalized_text:
            return self.current_context.get("last_excel") or self.current_context.get("ultimo_excel_leido")

        if "pdf" in normalized_text:
            return self.current_context.get("last_pdf") or self.current_context.get("ultimo_pdf_leido")

        if "imagen" in normalized_text or "foto" in normalized_text:
            return self.current_context.get("ultima_carpeta_fotos") or self.current_context.get("last_image")

        if "carpeta" in normalized_text or "renombrala" in normalized_text:
            return (
                self.current_context.get("last_folder")
                or self.current_context.get("ultima_carpeta_creada")
                or self.current_context.get("ultima_carpeta_destino")
                or self.current_context.get("active_path")
            )

        if "documento" in normalized_text:
            return self.current_context.get("last_document") or self.current_context.get("ultimo_documento_leido")

        text = raw_text.lower()

        if any(word in text for word in ["ahi", "ahí", "alli", "allí", "esa carpeta", "carpeta anterior"]):
            return (
                self.current_context.get("ultima_carpeta_destino")
                or self.current_context.get("last_folder")
                or self.current_context.get("ultima_carpeta_creada")
            )

        if any(word in text for word in ["lo ultimo", "lo último", "ultimo", "último"]):
            return (
                self.current_context.get("ultimo_elemento_modificado")
                or self.current_context.get("last_resource")
                or self.current_context.get("ultima_ruta_usada")
            )

        # ==============================================================
        # ARCHIVO
        # ==============================================================

        if "archivo" in text or "renombralo" in text or "renómbralo" in text or "muevelo" in text or "muévelo" in text:
            return self.current_context.get("last_file") or self.current_context.get("ultimo_archivo_creado")

        # ==============================================================
        # EXCEL
        # ==============================================================

        if "excel" in text:
            return self.current_context.get("last_excel") or self.current_context.get("ultimo_excel_leido")

        # ==============================================================
        # PDF
        # ==============================================================

        if "pdf" in text:
            return self.current_context.get("last_pdf") or self.current_context.get("ultimo_pdf_leido")

        # ==============================================================
        # IMAGEN
        # ==============================================================

        if "imagen" in text or "foto" in text:
            return self.current_context.get("last_image")

        # ==============================================================
        # CARPETA
        # ==============================================================

        if "carpeta" in text or "renombrala" in text or "renómbrala" in text:
            return (
                self.current_context.get("last_folder")
                or self.current_context.get("ultima_carpeta_creada")
                or self.current_context.get("ultima_carpeta_destino")
            )

        # ==============================================================
        # RECURSO GENERAL
        # ==============================================================

        return self.current_context.get("last_resource")

    def _last_created_item(self):
        items = self.current_context.get("last_created_items")
        if isinstance(items, list) and items:
            return items[-1]
        return self.current_context.get("ultima_carpeta_creada") or self.current_context.get("ultimo_archivo_creado")

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(text or ""))
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()
        return " ".join(normalized.split())

    # ==================================================================
    # ENTIDADES
    # ==================================================================

    def add_entity(self, entity_type: str, value):
        """
        Agrega entidad detectada.
        """

        if entity_type not in self.entities:
            self.entities[entity_type] = []

        if value not in self.entities[entity_type]:
            self.entities[entity_type].append(value)

    # ==================================================================
    # OBTENER ENTIDADES
    # ==================================================================

    def get_entities(self, entity_type: str):
        """
        Obtiene entidades registradas.
        """

        return self.entities.get(entity_type, [])

    # ==================================================================
    # LIMPIAR HISTORIAL
    # ==================================================================

    def clear_messages(self):
        """
        Limpia conversación.
        """

        self.messages.clear()

    # ==================================================================
    # RESET COMPLETO
    # ==================================================================

    def reset(self):
        """
        Reinicia completamente el contexto.
        """

        self.clear_messages()
        self.clear_context()

        self.entities = {
            "people": [],
            "folders": [],
            "documents": [],
            "images": [],
            "projects": [],
        }

    # ==================================================================
    # INFO SESIÓN
    # ==================================================================

    def get_session_info(self):
        """
        Información de sesión.
        """

        return {
            "started": str(self.session_data["session_started"]),
            "messages": self.session_data["total_messages"],
            "last_activity": str(self.session_data["last_activity"]),
        }

    # ==================================================================
    # DEBUG
    # ==================================================================

    def debug_dump(self):
        """
        Devuelve dump completo del contexto.
        """

        return {
            "context": self.current_context,
            "entities": self.entities,
            "messages": list(self.messages),
            "session": self.session_data
        }
