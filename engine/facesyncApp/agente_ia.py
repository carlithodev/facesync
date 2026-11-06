"""
======================================================================
MÓDULO: AGENTE IA (ASISTENTE FACESYNC) — v2.0 PRO
======================================================================
Sistema de gestión de archivos profesional con IA integrada.

Capacidades:
- 👁️ Ojos del Agente: escanea y mapea el workspace completo
- 🤲 Manos del Agente: CRUD de archivos y carpetas (crear, borrar,
  renombrar, mover) con seguridad de rutas
- 🔒 Seguridad: TODAS las operaciones están confinadas al workspace
- 🤖 Motor FaceSync: ejecuta reconocimiento facial desde el chat

Todas las rutas se validan contra la ruta_workspace obligatoria.
======================================================================
"""

import os
import shutil
import json
import threading
import re
from pathlib import Path
from typing import Optional
import customtkinter as ctk
from google import genai
from google.genai import types
from dotenv import load_dotenv
from core.app_paths import private_env_path
from core.app_paths import filter_internal_names
from core.context_manager import ContextManager
from core.local_command_router import LocalCommandRouter
from core.text_normalizer import TextNormalizer
from ai.smart_orchestrator import SmartOrchestrator
from facesyncApp.utils import set_windows_title_bar_light

# Importar el motor que ejecuta DeepFace de forma segura
try:
    from facesyncApp.motor_ia import MotorFaceSync
except ImportError:
    # Fallback por si ejecutan el script desde otra ubicación
    from motor_ia import MotorFaceSync

# ======================================================================
# CONFIGURACIÓN SEGURA DE VARIABLES DE ENTORNO
# ======================================================================
# Cargar variables de entorno desde el archivo .env
load_dotenv(private_env_path())
load_dotenv()

# Obtener API KEY sin exponerla en el código
API_KEY = os.getenv("GEMINI_API_KEY")

GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]
DEFAULT_GEMINI_MODEL = GEMINI_MODELS[0]
ENV_GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()

if not API_KEY:
    # Mostrar error elegante en consola sin crashear el programa
    print("\n" + "="*60)
    print("❌ ERROR DE CONFIGURACIÓN: GEMINI_API_KEY no encontrada.")
    print("="*60)
    print("Para que la IA funcione, debes configurar tu API KEY.")
    print("1. Crea un archivo llamado '.env' en la raíz del proyecto.")
    print("2. Agrega la siguiente línea dentro del archivo:")
    print("   GEMINI_API_KEY=tu_clave_secreta_aqui")
    print("="*60 + "\n")

# Referencia global para enviar mensajes a la UI desde herramientas locales
_agente_global = None

# ======================================================================
# SEGURIDAD DE RUTAS
# ======================================================================
def _ruta_segura(ruta_relativa, workspace):
    """
    Convierte una ruta relativa a absoluta DENTRO del workspace.
    Bloquea cualquier intento de escapar (../ o rutas absolutas externas).
    
    Returns:
        str: Ruta absoluta segura, o None si es inválida.
    """
    if not workspace:
        return None

    try:
        workspace_path = Path(workspace).resolve()
        user_path = Path(str(ruta_relativa).strip().replace('"', '').replace("'", ""))

        if user_path.is_absolute():
            ruta_abs = user_path.resolve(strict=False)
        else:
            ruta_abs = (workspace_path / user_path).resolve(strict=False)

        ruta_abs.relative_to(workspace_path)
    except Exception:
        return None

    return str(ruta_abs)


# ======================================================================
# 👁️ OJOS DEL AGENTE — HERRAMIENTA: OBTENER MAPA DE ARCHIVOS
# ======================================================================
def obtener_mapa_archivos() -> str:
    """
    Escanea y devuelve un mapa completo de TODOS los archivos y carpetas
    dentro del área de trabajo (workspace) del usuario. Usa esta herramienta
    para "ver" qué hay en el explorador antes de manipular archivos.
    Llámala siempre que el usuario pregunte qué archivos tiene, o antes
    de crear/mover/borrar algo para saber la estructura actual.
    
    Returns:
        str: Un mapa en texto con la estructura de carpetas y archivos.
    """
    if not _agente_global or not _agente_global.ruta_workspace:
        return "Error: No hay un área de trabajo configurada."

    workspace = _agente_global.ruta_workspace

    if _agente_global:
        _agente_global.agregar_mensaje_sistema("👁️ Escaneando archivos del workspace...")

    lineas = []
    lineas.append(f"📂 WORKSPACE: {os.path.basename(workspace)}")
    lineas.append(f"   Ruta: {workspace}")
    lineas.append("=" * 50)

    total_archivos = 0
    total_carpetas = 0

    for raiz, dirs, archivos in os.walk(workspace):
        # Saltar carpetas ocultas y de sistema
        dirs[:] = filter_internal_names([
            d for d in dirs
            if not d.startswith('.') and d not in ('__pycache__', 'env_ia', '.git', 'node_modules')
        ])

        nivel = raiz.replace(workspace, "").count(os.sep)
        indent = "│   " * nivel
        nombre_carpeta = os.path.basename(raiz) or os.path.basename(workspace)
        lineas.append(f"{indent}📁 {nombre_carpeta}/")
        total_carpetas += 1

        sub_indent = "│   " * (nivel + 1)
        for archivo in sorted(archivos):
            if archivo.startswith('.'):
                continue
            tamaño = ""
            try:
                size_bytes = os.path.getsize(os.path.join(raiz, archivo))
                if size_bytes < 1024:
                    tamaño = f" ({size_bytes} B)"
                elif size_bytes < 1024 * 1024:
                    tamaño = f" ({size_bytes / 1024:.1f} KB)"
                else:
                    tamaño = f" ({size_bytes / (1024*1024):.1f} MB)"
            except OSError:
                pass
            lineas.append(f"{sub_indent}📄 {archivo}{tamaño}")
            total_archivos += 1

        # Limitar profundidad y cantidad para no saturar los tokens de la API
        if total_archivos > 100:
            lineas.append("\n⚠️ Se alcanzó el límite de 100 archivos por seguridad de tokens. Mapa truncado.")
            break

    lineas.append("=" * 50)
    lineas.append(f"📊 Total: {total_carpetas} carpetas, {total_archivos} archivos")

    return "\n".join(lineas)


# ======================================================================
# 🤲 MANOS DEL AGENTE — HERRAMIENTA: MANIPULAR ARCHIVOS
# ======================================================================
def manipular_archivos(accion: str, nombre: str, ruta_destino: str = "", nombre_nuevo: str = "") -> str:
    """
    Herramienta maestra para crear, borrar, renombrar y mover archivos y carpetas
    dentro del workspace del usuario. TODAS las rutas deben ser relativas al workspace.
    
    Acciones disponibles:
    - "crear_carpeta": Crea una carpeta. Usa 'nombre' para el nombre y 'ruta_destino' 
      para la ubicación relativa dentro del workspace (dejar vacío para raíz).
    - "borrar": Elimina un archivo o carpeta. Usa 'nombre' con la ruta relativa al
      workspace del elemento a eliminar.
    - "renombrar": Renombra un archivo o carpeta. Usa 'nombre' con la ruta relativa
      actual y 'nombre_nuevo' con el nuevo nombre.
    - "mover": Mueve un archivo o carpeta. Usa 'nombre' con la ruta relativa actual
      del elemento y 'ruta_destino' con la ruta relativa de destino.
    
    Args:
        accion: Una de "crear_carpeta", "borrar", "renombrar", "mover"
        nombre: Nombre o ruta relativa del elemento
        ruta_destino: Ruta relativa destino (para crear_carpeta y mover)
        nombre_nuevo: Nuevo nombre (solo para renombrar)
    
    Returns:
        str: Mensaje con el resultado de la operación
    """
    if not _agente_global or not _agente_global.ruta_workspace:
        return "Error: No hay un área de trabajo configurada."

    workspace = _agente_global.ruta_workspace

    if _agente_global:
        _agente_global.agregar_mensaje_sistema(f"⚙️ Ejecutando: {accion} — {nombre}")

    try:
        # ─── CREAR CARPETA ───
        if accion == "crear_carpeta":
            if ruta_destino:
                base = _ruta_segura(ruta_destino, workspace)
            else:
                base = workspace

            if not base:
                return "❌ Error: La ruta de destino está fuera del workspace."

            ruta_nueva = os.path.join(base, nombre)
            ruta_nueva = _ruta_segura(ruta_nueva, workspace)
            if not ruta_nueva:
                return "❌ Error: La carpeta resultante estaría fuera del workspace."

            os.makedirs(ruta_nueva, exist_ok=True)

            # Notificar al dashboard para refrescar el explorador
            if _agente_global and _agente_global.callback_refrescar:
                _agente_global.textbox_historial.after(
                    0, _agente_global.callback_refrescar, os.path.dirname(ruta_nueva)
                )
            return f"✅ Carpeta creada: {os.path.relpath(ruta_nueva, workspace)}"

        # ─── BORRAR ───
        elif accion == "borrar":
            ruta = _ruta_segura(nombre, workspace)
            if not ruta:
                return "❌ Error: La ruta está fuera del workspace."
            if not os.path.exists(ruta):
                return f"❌ Error: No existe '{nombre}' en el workspace."

            padre = os.path.dirname(ruta)
            if os.path.isdir(ruta):
                shutil.rmtree(ruta)
                tipo = "Carpeta"
            else:
                os.remove(ruta)
                tipo = "Archivo"

            if _agente_global and _agente_global.callback_refrescar:
                _agente_global.textbox_historial.after(
                    0, _agente_global.callback_refrescar, padre
                )
            return f"✅ {tipo} eliminado: {os.path.relpath(ruta, workspace)}"

        # ─── RENOMBRAR ───
        elif accion == "renombrar":
            ruta_actual = _ruta_segura(nombre, workspace)
            if not ruta_actual:
                return "❌ Error: La ruta actual está fuera del workspace."
            if not os.path.exists(ruta_actual):
                return f"❌ Error: No existe '{nombre}' en el workspace."
            if not nombre_nuevo or not nombre_nuevo.strip():
                return "❌ Error: Debes proporcionar un nombre nuevo."

            ruta_nueva = os.path.join(os.path.dirname(ruta_actual), nombre_nuevo.strip())
            ruta_nueva = _ruta_segura(ruta_nueva, workspace)
            if not ruta_nueva:
                return "❌ Error: El nuevo nombre resultaría fuera del workspace."

            os.rename(ruta_actual, ruta_nueva)

            if _agente_global and _agente_global.callback_refrescar:
                _agente_global.textbox_historial.after(
                    0, _agente_global.callback_refrescar, os.path.dirname(ruta_nueva)
                )
            return f"✅ Renombrado: '{os.path.basename(ruta_actual)}' → '{nombre_nuevo.strip()}'"

        # ─── MOVER ───
        elif accion == "mover":
            ruta_origen = _ruta_segura(nombre, workspace)
            if not ruta_origen:
                return "❌ Error: La ruta de origen está fuera del workspace."
            if not os.path.exists(ruta_origen):
                return f"❌ Error: No existe '{nombre}' en el workspace."

            ruta_dest = _ruta_segura(ruta_destino, workspace)
            if not ruta_dest:
                return "❌ Error: La ruta de destino está fuera del workspace."

            # Si el destino es una carpeta, mover dentro de ella
            if os.path.isdir(ruta_dest):
                ruta_final = os.path.join(ruta_dest, os.path.basename(ruta_origen))
            else:
                os.makedirs(os.path.dirname(ruta_dest), exist_ok=True)
                ruta_final = ruta_dest

            ruta_final = _ruta_segura(ruta_final, workspace)
            if not ruta_final:
                return "❌ Error: El destino final estaría fuera del workspace."

            shutil.move(ruta_origen, ruta_final)

            if _agente_global and _agente_global.callback_refrescar:
                _agente_global.textbox_historial.after(
                    0, _agente_global.callback_refrescar, None
                )
            return f"✅ Movido: {os.path.relpath(ruta_origen, workspace)} → {os.path.relpath(ruta_final, workspace)}"

        else:
            return f"❌ Acción no reconocida: '{accion}'. Usa: crear_carpeta, borrar, renombrar, mover."

    except PermissionError:
        return "❌ Error: No tienes permisos para esta operación."
    except Exception as e:
        return f"❌ Error en la operación: {str(e)}"


# ======================================================================
# 🚀 HERRAMIENTA: MOTOR FACESYNC (RECONOCIMIENTO FACIAL)
# ======================================================================
def ejecutar_motor_facesync(ruta_excel: str, carpeta_maestra: str, carpeta_destino: str) -> str:
    """
    Ejecuta el motor de reconocimiento facial en segundo plano.
    Las rutas pueden ser relativas al workspace o absolutas (dentro del workspace).
    
    Args:
        ruta_excel: Ruta al archivo Excel con los datos.
        carpeta_maestra: Ruta a las fotos originales.
        carpeta_destino: Ruta donde se organizarán las fotos.
    """
    if not _agente_global or not _agente_global.ruta_workspace:
        return "Error: No hay un área de trabajo configurada."

    workspace = _agente_global.ruta_workspace

    # Validar y resolver rutas
    ruta_excel = _ruta_segura(ruta_excel, workspace)
    carpeta_maestra = _ruta_segura(carpeta_maestra, workspace)
    carpeta_destino = _ruta_segura(carpeta_destino, workspace)

    if not ruta_excel or not carpeta_maestra or not carpeta_destino:
        return "❌ Error: Una o más rutas están fuera del workspace."

    if _agente_global:
        _agente_global.agregar_mensaje_sistema(f"🚀 Iniciando DeepFace...\nExcel: {ruta_excel}")

    def callback_resultado(exito, mensaje):
        if _agente_global:
            estado = "✅" if exito else "❌"
            _agente_global.agregar_mensaje_sistema(f"{estado} [Motor IA] {mensaje}")

    try:
        MotorFaceSync.iniciar_reconocimiento_en_hilo(
            ruta_carpeta_fotos=carpeta_maestra,
            ruta_excel=ruta_excel,
            carpeta_destino=carpeta_destino,
            callback_resultado=callback_resultado
        )
        return "El motor FaceSync fue iniciado en segundo plano. Notificaré al usuario."
    except Exception:
        return "Error al iniciar Motor FaceSync."


# ======================================================================
# UI DE PROGRESO DE FACESYNC
# ======================================================================
class FaceSyncProgressWindow(ctk.CTkToplevel):
    def __init__(self, master, on_cancel_callback=None):
        super().__init__(master)
        self.title("FaceSync en progreso")
        set_windows_title_bar_light(self)
        self.geometry("420x220")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.on_cancel_callback = on_cancel_callback
        
        self.grid_columnconfigure(0, weight=1)
        
        self.lbl_title = ctk.CTkLabel(self, text="FaceSync en progreso", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_title.grid(row=0, column=0, pady=(15, 5), padx=20, sticky="w")
        
        self.frame_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_bar.grid(row=1, column=0, sticky="ew", padx=20, pady=5)
        self.frame_bar.grid_columnconfigure(0, weight=1)
        
        self.progressbar = ctk.CTkProgressBar(self.frame_bar)
        self.progressbar.grid(row=0, column=0, sticky="ew", pady=5)
        self.progressbar.set(0)
        
        self.lbl_percent = ctk.CTkLabel(self.frame_bar, text="0%", font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_percent.grid(row=0, column=1, padx=(10, 0))
        
        self.lbl_phase = ctk.CTkLabel(self, text="Inicializando FaceSync...", font=ctk.CTkFont(size=13))
        self.lbl_phase.grid(row=2, column=0, pady=(5, 5), padx=20, sticky="w")
        
        self.lbl_stats = ctk.CTkLabel(self, text="Copiadas: 0 | Pendientes: 0 | Errores: 0", font=ctk.CTkFont(size=12), text_color="gray")
        self.lbl_stats.grid(row=3, column=0, pady=(0, 15), padx=20, sticky="w")
        
        self.btn_cancel = ctk.CTkButton(self, text="Cancelar", command=self.cancel_action, fg_color="#E02424", hover_color="#9B1C1C")
        self.btn_cancel.grid(row=4, column=0, pady=(5, 15))

    def update_progress(self, data):
        percent = data.get("percent")
        current = data.get("current")
        total = data.get("total")
        message = data.get("message")
        phase = data.get("phase") or data.get("stage")
        copied = data.get("copied_count", 0)
        pending = data.get("pending_count", 0)
        errors = data.get("error_count", 0)

        if percent is None and current is not None and total and total > 0:
            percent = (current / total) * 100

        if percent is not None:
            self.progressbar.set(min(1.0, max(0.0, percent / 100.0)))
            self.lbl_percent.configure(text=f"{int(percent)}%")
        
        phase_text = ""
        if message:
            phase_text = str(message)
        elif phase:
            phase_text = str(phase).capitalize()
            
        if current is not None and total is not None and " / " not in phase_text:
            phase_text += f" {current} / {total}"
            
        if phase_text:
            self.lbl_phase.configure(text=phase_text)
            
        stats_text = f"Copiadas: {copied} | Pendientes: {pending} | Errores: {errors}"
        self.lbl_stats.configure(text=stats_text)

        if phase in ["done", "completed", "finalizado"]:
            self.lbl_title.configure(text="FaceSync Finalizado")
            self.btn_cancel.configure(text="Cerrar", command=self.destroy, fg_color="#059669", hover_color="#047857")
        elif phase in ["canceled", "cancelado"]:
            self.lbl_title.configure(text="FaceSync Cancelado")
            self.btn_cancel.configure(text="Cerrar", command=self.destroy, fg_color="gray", hover_color="#4B5563")
        elif phase in ["error"]:
            self.lbl_title.configure(text="Error en FaceSync")
            self.btn_cancel.configure(text="Cerrar", command=self.destroy)

    def cancel_action(self):
        self.btn_cancel.configure(state="disabled", text="Cancelando...")
        if self.on_cancel_callback:
            self.on_cancel_callback()

    def on_closing(self):
        if self.btn_cancel.cget("text") == "Cerrar":
            self.destroy()
        else:
            self.cancel_action()


# ======================================================================
# CLASE CONTROLADORA (BACKEND) — v2.0 PRO
# ======================================================================
class AsistenteFaceSync:
    """
    Controlador lógico (Backend) para el asistente IA.
    Gestiona la interfaz de chat, la interacción con Google Gemini,
    y la manipulación segura de archivos dentro del workspace.
    """
    def __init__(self, entry_chat, boton_enviar, textbox_historial,
                 ruta_workspace=None, callback_refrescar=None):
        self.entry_chat = entry_chat
        self.boton_enviar = boton_enviar
        self.textbox_historial = textbox_historial
        self.ruta_workspace = self._normalizar_workspace(ruta_workspace)
        self.callback_refrescar = callback_refrescar
        self.client = None
        self.registry = None
        self.chat_session = None
        self.modelo_gemini = self._modelo_inicial_gemini()
        self._gemini_config_kwargs = None
        self.context_manager = ContextManager()
        self.openai_orchestrator = SmartOrchestrator.from_env()
        self._worker_activo = False
        self._last_facesync_progress = {"time": 0.0, "percent": -1}
        if self.ruta_workspace:
            self.context_manager.set_workspace(self.ruta_workspace)
        self.local_router = LocalCommandRouter(
            workspace_path=self.ruta_workspace,
            context_manager=self.context_manager,
            async_callback=self._on_facesync_async_result
        )

        # Vincular eventos de la interfaz
        self.boton_enviar.configure(command=self.procesar_mensaje)
        self.entry_chat.bind("<Return>", lambda e: self.procesar_mensaje())

        # Configurar variable global para herramientas
        global _agente_global
        _agente_global = self

        # Iniciar modelo IA
        self._inicializar_ia()

    def _normalizar_workspace(self, ruta_workspace):
        if not ruta_workspace:
            return None

        try:
            ruta = Path(ruta_workspace).expanduser().resolve()
        except Exception:
            return None

        if not ruta.exists() or not ruta.is_dir():
            return None

        return str(ruta)

    def _modelo_inicial_gemini(self):
        modelo = ENV_GEMINI_MODEL or DEFAULT_GEMINI_MODEL
        if modelo not in GEMINI_MODELS:
            print(
                f"[Gemini] GEMINI_MODEL='{modelo}' no esta en la lista soportada. "
                f"Usando {DEFAULT_GEMINI_MODEL}."
            )
            return DEFAULT_GEMINI_MODEL

        return modelo

    def _crear_chat_session(self):
        if not self.client:
            raise RuntimeError("Cliente Gemini no inicializado.")
        if not self._gemini_config_kwargs:
            raise RuntimeError("Configuracion de Gemini no disponible.")

        print(f"[Gemini] Usando modelo: {self.modelo_gemini}")
        self.chat_session = self.client.chats.create(
            model=self.modelo_gemini,
            config=types.GenerateContentConfig(**self._gemini_config_kwargs)
        )
        return self.chat_session

    def _cambiar_al_siguiente_modelo(self):
        try:
            indice = GEMINI_MODELS.index(self.modelo_gemini)
        except ValueError:
            indice = -1

        siguiente_indice = indice + 1
        if siguiente_indice >= len(GEMINI_MODELS):
            return False

        modelo_anterior = self.modelo_gemini
        self.modelo_gemini = GEMINI_MODELS[siguiente_indice]
        print(
            f"[Gemini] Modelo saturado/no disponible: {modelo_anterior}. "
            f"Cambiando a: {self.modelo_gemini}"
        )
        self._crear_chat_session()
        return True

    def set_workspace(self, ruta_workspace, reiniciar_ia=True):
        """
        Actualiza el workspace activo y reconstruye las tools de Gemini.
        """
        nueva_ruta = self._normalizar_workspace(ruta_workspace)
        if not nueva_ruta:
            self.agregar_mensaje_sistema("No se pudo activar el workspace: la ruta no existe o no es una carpeta.")
            return False

        if self.ruta_workspace == nueva_ruta:
            self.context_manager.set_project_root(nueva_ruta)
            self.local_router.set_project_root(nueva_ruta)
            if self.registry and hasattr(self.registry, "set_project_root"):
                try:
                    from core.security import SecurityManager
                    self.registry.set_project_root(
                        nueva_ruta,
                        SecurityManager(nueva_ruta, app_data_root=self.context_manager.get_app_data_root()),
                    )
                except Exception:
                    pass
            return True

        self.ruta_workspace = nueva_ruta
        self.context_manager.set_project_root(nueva_ruta)
        self.local_router.set_project_root(nueva_ruta)
        if self.registry and hasattr(self.registry, "set_project_root"):
            try:
                from core.security import SecurityManager
                self.registry.set_project_root(
                    nueva_ruta,
                    SecurityManager(nueva_ruta, app_data_root=self.context_manager.get_app_data_root()),
                )
            except Exception:
                pass
        if reiniciar_ia:
            self._inicializar_ia(mostrar_saludo=False)
            self.agregar_mensaje_sistema(f"Workspace activo: {os.path.basename(nueva_ruta)}")

        return True

    def set_workspace_roots(self, roots, reiniciar_ia=False):
        """Workspace compuesto: registra varias carpetas raiz para que el
        asistente busque en TODAS (no solo la ultima). La primera es la primaria."""
        cleaned = [self._normalizar_workspace(r) for r in (roots or [])]
        seen = set()
        roots_norm = []
        for r in cleaned:
            if r and r not in seen:
                seen.add(r)
                roots_norm.append(r)
        if not roots_norm:
            return False
        # Activa la primaria (reconstruye tools/seguridad) y registra todas.
        self.set_workspace(roots_norm[0], reiniciar_ia=reiniciar_ia)
        if hasattr(self.context_manager, "set_workspace_roots"):
            self.context_manager.set_workspace_roots(roots_norm)
        if hasattr(self.local_router, "set_workspace_roots"):
            self.local_router.set_workspace_roots(roots_norm)
        return True

    def _inicializar_ia(self, mostrar_saludo=True):
        """Inicializa la sesion con Gemini y las tools del workspace activo."""
        from ai.tool_registry import AgentToolRegistry
        from core.security import SecurityManager
        from ai.prompts import construir_prompt
        import traceback

        self.registry = None
        self.chat_session = None

        try:
            if not API_KEY:
                if self.openai_orchestrator and self.openai_orchestrator.is_available():
                    self._mostrar_en_chat(
                        "Sistema",
                        "¡Bienvenido a FaceSync! 👋 Soy tu asistente. Puedo leer tu Excel, crear carpetas, clasificar fotos por rostro y exportar a Drive. Escríbeme qué necesitas."
                    )
                    return
                self._mostrar_en_chat(
                    "Sistema",
                    "IA avanzada no disponible: falta GEMINI_API_KEY y OpenAI está deshabilitado o sin API key. Las acciones locales siguen disponibles."
                )
                return

            self.client = genai.Client(api_key=API_KEY)

            tools = []
            mapa_workspace = (
                "No hay workspace activo. Si el usuario pide acciones sobre archivos, "
                "solicita que seleccione una carpeta primero."
            )

            if self.ruta_workspace:
                security = SecurityManager(
                    workspace_path=self.ruta_workspace,
                    app_data_root=self.context_manager.get_app_data_root(),
                )
                self.registry = AgentToolRegistry()
                self.registry.auto_register_default_tools(
                    workspace_path=self.ruta_workspace,
                    security_manager=security
                )
                tools = self.registry.get_tool_callables()
                mapa_workspace = f"\nTu workspace actual es: {self.ruta_workspace}\n"
                
            instrucciones = construir_prompt(
                modo="base",
                workspace_tree=mapa_workspace,
                memory_context=self.context_manager.get_context_summary(),
                last_action_details="Ninguna"
            )

            self._gemini_config_kwargs = {
                "system_instruction": instrucciones,
                "temperature": 0.4
            }
            if tools:
                self._gemini_config_kwargs["tools"] = tools

            self._crear_chat_session()

            if mostrar_saludo:
                ws_name = os.path.basename(self.ruta_workspace) if self.ruta_workspace else "pendiente"
                extra = (
                    "Puedo ver, crear, mover, renombrar y eliminar archivos."
                    if self.ruta_workspace
                    else "Selecciona una carpeta para activar las herramientas de archivos."
                )
                self._mostrar_en_chat(
                    "Asistente",
                    f"Hola, soy tu asistente FaceSync PRO.\n"
                    f"Workspace: {ws_name}\n"
                    f"{extra}"
                )

        except Exception as e:
            print(f"Error inicializando IA: {type(e).__name__}: {e}")
            traceback.print_exc()
            self._mostrar_en_chat(
                "Sistema",
                f"No se pudo inicializar Gemini: {type(e).__name__}: {e}"
            )

    # ==================================================================
    # MÉTODOS DE INTERFAZ Y COMUNICACIÓN
    # ==================================================================
    def agregar_mensaje_sistema(self, texto):
        """Permite que otros hilos (como las Tools) actualicen el chat de forma segura."""
        self.textbox_historial.after(0, self._mostrar_en_chat, "Sistema", texto)

    def _mostrar_en_chat(self, remitente, texto):
        """Añade texto al historial visual del chat."""
        # Soporte para CTkTextbox
        if hasattr(self.textbox_historial, "insert"):
            estado_previo = self.textbox_historial.cget("state")
            self.textbox_historial.configure(state="normal")
            self.textbox_historial.insert("end", f"\n[{remitente}]: {texto}\n")
            self.textbox_historial.configure(state=estado_previo)
            self.textbox_historial.see("end")
        # Soporte para Frame (CTkScrollableFrame)
        else:
            # Burbujas glass claras (SOLO apariencia; la lógica del chat no cambia).
            if remitente == "Tú":
                _bg, _brd, _lc = "#E7EEFF", "#CBD9FF", "#2563EB"   # usuario: azul muy suave
            elif remitente == "Sistema":
                _bg, _brd, _lc = "#EEF2F8", "#E3E8F0", "#64748B"   # sistema: neutro
            else:
                _bg, _brd, _lc = "#FFFFFF", "#E3E8F0", "#1E293B"   # asistente: perla/blanco
            marco = ctk.CTkFrame(self.textbox_historial, fg_color=_bg, corner_radius=12,
                                 border_width=1, border_color=_brd)
            marco.pack(fill="x", padx=10, pady=5)

            ctk.CTkLabel(
                marco, text=f"{remitente}", font=ctk.CTkFont(size=11, weight="bold"),
                text_color=_lc, anchor="w"
            ).pack(anchor="w", fill="x", padx=12, pady=(7, 0))

            # Calcular altura necesaria según el largo del texto
            chars_por_linea = 38  # aprox. caracteres por línea en el panel
            num_lineas = 0
            for linea in texto.split("\n"):
                if not linea:
                    num_lineas += 1
                else:
                    num_lineas += -(-len(linea) // chars_por_linea)  # ceil division
            
            # Permitir que el cuadro crezca lo necesario para que no se oculte el texto
            altura = max(num_lineas * 22 + 10, 40)

            txt_box = ctk.CTkTextbox(
                marco, fg_color="transparent", text_color="#1E293B",
                font=("Segoe UI", 13), wrap="word",
                height=altura, activate_scrollbars=False,
                border_width=0, corner_radius=0
            )
            txt_box.pack(fill="x", padx=10, pady=(2, 8))
            txt_box.insert("1.0", texto)
            txt_box.configure(state="disabled")

            self.textbox_historial.after(50, lambda: self.textbox_historial._parent_canvas.yview_moveto(1.0))

    def _limpiar_argumento_comando(self, valor: str, quitar_tipo=False) -> str:
        texto = (valor or "").strip()
        texto = texto.strip(" \t\r\n\"'`.,;:")
        texto = re.sub(r"\s+", " ", texto)
        texto = re.sub(r"\s+(?:por favor|please|pls)$", "", texto, flags=re.IGNORECASE).strip()

        if quitar_tipo:
            texto = re.sub(
                r"^(?:en\s+)?(?:la|el|una|un)?\s*(?:carpeta|archivo|directorio)\s+",
                "",
                texto,
                flags=re.IGNORECASE
            ).strip()

        return texto

    def _ruta_local(self, *partes: str) -> str:
        limpias = []
        for parte in partes:
            valor = self._limpiar_argumento_comando(parte, quitar_tipo=True)
            if valor:
                limpias.append(valor.strip("/\\"))
        return "/".join(limpias)

    def _refrescar_explorador_seguro(self):
        if not self.callback_refrescar:
            return

        try:
            self.callback_refrescar(None)
        except Exception as e:
            print(f"Error al refrescar UI: {e}")

    def _actualizar_panel_progreso(self, data):
        if not hasattr(self, '_progress_window') or self._progress_window is None or not self._progress_window.winfo_exists():
            root = self.textbox_historial.winfo_toplevel()
            self._progress_window = FaceSyncProgressWindow(root, on_cancel_callback=self.cancelar_tarea_actual)
            
        self._progress_window.update_progress(data)

    def _on_facesync_async_result(self, success: bool, message: str, data: dict):
        data = data or {}
        if data.get("event") == "progress":
            self.textbox_historial.after(0, self._actualizar_panel_progreso, data)
            return
            
        if success:
            respuesta = (
                "Listo, el reconocimiento terminó. Copié las fotos encontradas "
                "en sus carpetas correspondientes."
            )
            data["phase"] = "done"
            data["message"] = "Completado: fotos procesadas exitosamente."
        else:
            respuesta = f"No pude completar el reconocimiento facial: {message}"
            data["phase"] = "error"
            data["message"] = respuesta

        self.textbox_historial.after(0, self._actualizar_panel_progreso, data)
        self.context_manager.add_message(role="assistant", content=respuesta)
        self.textbox_historial.after(0, self._mostrar_en_chat, "Asistente", respuesta)
        if self.callback_refrescar:
            self.textbox_historial.after(0, self._refrescar_explorador_seguro)

    def _intentar_openai_fallback(self, texto: str):
        if not self.openai_orchestrator or not self.openai_orchestrator.is_available():
            return None

        try:
            normalized = TextNormalizer.normalize(texto)
            local_guess = self.local_router.interpreter.interpret(texto, normalized, self.context_manager)
        except Exception:
            local_guess = None

        if hasattr(self.context_manager, "build_system_state"):
            system_state = self.context_manager.build_system_state(texto)
        else:
            system_state = self.context_manager.current_context

        interpretation = self.openai_orchestrator.interpret(
            user_text=texto,
            context=system_state,
            local_guess=local_guess,
        )
        self._guardar_uso_openai_en_vault(interpretation)
        source = "local" if interpretation.get("model_used") == "local" else "openai"
        result = self.local_router.handle_structured_interpretation(
            texto,
            interpretation,
            source=source,
        )
        if result and result.action == "retry_smart":
            retry_interpretation = self.openai_orchestrator.retry_with_smart(
                texto,
                self.context_manager.build_system_state(texto) if hasattr(self.context_manager, "build_system_state") else self.context_manager.current_context,
                local_guess=local_guess,
                previous_result=(result.data or {}).get("interpretation") or interpretation,
            )
            self._guardar_uso_openai_en_vault(retry_interpretation)
            return self.local_router.handle_structured_interpretation(
                texto,
                retry_interpretation,
                source="openai",
            )
        return result

    def _guardar_uso_openai_en_vault(self, interpretation: dict):
        usage = (interpretation or {}).get("usage") or {}
        if not usage or not hasattr(self.context_manager, "ensure_context_vault"):
            return
        vault = self.context_manager.ensure_context_vault()
        session_id = getattr(self.context_manager, "context_session_id", None)
        if not vault or not session_id:
            return
        try:
            vault.save_openai_usage(
                session_id,
                usage.get("model") or (interpretation or {}).get("model_used") or "",
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                usage.get("estimated_cost_usd", 0.0),
                (interpretation or {}).get("intent", ""),
                float((interpretation or {}).get("confidence", 0.0) or 0.0),
                escalated=bool(usage.get("escalated")),
                escalation_reason=usage.get("escalation_reason") or (interpretation or {}).get("escalation_reason", ""),
            )
        except Exception:
            return

    def _intentar_comando_local(self, texto: str) -> Optional[str]:
        """
        Ejecuta comandos simples de archivos sin llamar a Gemini.
        """
        import re
        from core.security import SecurityManager
        from tools.file_tools import FileCapabilities
        from tools.search_tools import SearchCapabilities
        from tools.workspace_tools import WorkspaceCapabilities

        texto = (texto or "").strip()
        if not texto:
            return None

        if hasattr(self, "local_router") and self.local_router:
            result = self.local_router.try_handle(texto)
            if result and result.handled:
                return result.message

        flags = re.IGNORECASE
        modifica_fs = False

        def requiere_workspace():
            if not self.ruta_workspace:
                return "Selecciona primero un workspace."
            return None

        def file_cap():
            security = SecurityManager(self.ruta_workspace, app_data_root=self.context_manager.get_app_data_root())
            return FileCapabilities(self.ruta_workspace, security)

        def search_cap():
            security = SecurityManager(self.ruta_workspace, app_data_root=self.context_manager.get_app_data_root())
            return SearchCapabilities(self.ruta_workspace, security)

        def workspace_cap():
            security = SecurityManager(self.ruta_workspace, app_data_root=self.context_manager.get_app_data_root())
            return WorkspaceCapabilities(self.ruta_workspace, security)

        # Crear carpeta: "creame una carpeta llamada X dentro de Y"
        match = re.match(
            r"^(?:cr.?ame|crea|crear|haz|hazme)\s+"
            r"(?:una\s+)?carpeta(?:\s+llamada)?\s+"
            r"(?P<nombre>.+?)"
            r"(?:\s+(?:dentro|adentro)\s+de\s+(?P<destino>.+))?$",
            texto,
            flags
        )
        if match:
            sin_workspace = requiere_workspace()
            if sin_workspace:
                return sin_workspace
            nombre = self._limpiar_argumento_comando(match.group("nombre"), quitar_tipo=True)
            destino = self._limpiar_argumento_comando(match.group("destino") or "", quitar_tipo=True)
            if not nombre:
                return "Indica el nombre de la carpeta."
            ruta = self._ruta_local(destino, nombre) if destino else self._ruta_local(nombre)
            resultado = file_cap().create_directory(ruta)
            modifica_fs = True
            if modifica_fs:
                self._refrescar_explorador_seguro()
            return resultado

        # Crear archivo: "crea un archivo llamado X con el texto Y"
        match = re.match(
            r"^(?:cr.?ame|crea|crear|haz|hazme)\s+"
            r"(?:un\s+)?archivo(?:\s+llamado)?\s+"
            r"(?P<nombre>.+?)"
            r"(?:\s+con\s+(?:el\s+)?texto\s+(?P<contenido>.+))?$",
            texto,
            flags
        )
        if match:
            sin_workspace = requiere_workspace()
            if sin_workspace:
                return sin_workspace
            nombre = self._limpiar_argumento_comando(match.group("nombre"), quitar_tipo=True)
            contenido = match.group("contenido") or ""
            contenido = contenido.strip().strip("\"'")
            if not nombre:
                return "Indica el nombre del archivo."
            resultado = file_cap().create_file(nombre, content=contenido)
            self._refrescar_explorador_seguro()
            return resultado

        # Escanear workspace
        if re.match(r"^(?:escanea(?:r)?\s+(?:mi\s+)?workspace|muestra\s+mis\s+archivos|qu.?\s+hay\s+en\s+mi\s+workspace)\??$", texto, flags):
            sin_workspace = requiere_workspace()
            if sin_workspace:
                return sin_workspace
            return workspace_cap().get_workspace_tree()

        # Buscar archivos
        match = re.match(r"^busca(?:\s+el\s+archivo)?\s+(?P<patron>.+)$", texto, flags)
        if match:
            sin_workspace = requiere_workspace()
            if sin_workspace:
                return sin_workspace
            patron = self._limpiar_argumento_comando(match.group("patron"), quitar_tipo=True)
            if not patron:
                return "Indica que archivo quieres buscar."
            resultado = search_cap().search_by_name(pattern=patron)
            if not resultado.get("success"):
                return f"Error buscando archivos: {resultado.get('error', 'Desconocido')}"
            archivos = resultado.get("results", [])
            if not archivos:
                return "No se encontraron archivos."
            lineas = [
                item.get("relative_path") or item.get("path") or item.get("name", "")
                for item in archivos[:100]
            ]
            return f"Archivos encontrados ({len(archivos)}):\n" + "\n".join(lineas)

        # Renombrar
        match = re.match(
            r"^(?:renombra|cambia\s+el\s+nombre\s+de)\s+(?P<origen>.+?)\s+a\s+(?P<nuevo>.+)$",
            texto,
            flags
        )
        if match:
            sin_workspace = requiere_workspace()
            if sin_workspace:
                return sin_workspace
            origen = self._limpiar_argumento_comando(match.group("origen"), quitar_tipo=True)
            nuevo = self._limpiar_argumento_comando(match.group("nuevo"), quitar_tipo=True)
            if not origen or not nuevo:
                return "Indica la ruta actual y el nuevo nombre."
            resultado = file_cap().rename_path(origen, nuevo)
            self._refrescar_explorador_seguro()
            return resultado

        # Mover
        match = re.match(
            r"^mueve\s+(?P<origen>.+?)\s+(?:a|dentro\s+de)\s+(?P<destino>.+)$",
            texto,
            flags
        )
        if match:
            sin_workspace = requiere_workspace()
            if sin_workspace:
                return sin_workspace
            origen = self._limpiar_argumento_comando(match.group("origen"), quitar_tipo=True)
            destino = self._limpiar_argumento_comando(match.group("destino"), quitar_tipo=True)
            if not origen or not destino:
                return "Indica que quieres mover y hacia donde."
            resultado = file_cap().move_path(origen, destino)
            self._refrescar_explorador_seguro()
            return resultado

        # Eliminar
        match = re.match(r"^(?:elimina|borra)\s+(?P<ruta>.+)$", texto, flags)
        if match:
            sin_workspace = requiere_workspace()
            if sin_workspace:
                return sin_workspace
            ruta = self._limpiar_argumento_comando(match.group("ruta"), quitar_tipo=True)
            if not ruta:
                return "Indica que quieres eliminar."
            resultado = file_cap().delete_path(ruta, recursive=True)
            self._refrescar_explorador_seguro()
            return resultado

        return None

    def procesar_mensaje(self):
        """Lee el texto, bloquea controles y lanza el hilo de Gemini."""
        texto = self.entry_chat.get().strip()
        if not texto:
            return
        if self._worker_activo:
            self.cancelar_tarea_actual()
            return

        # 1. Mostrar mensaje del usuario
        self._mostrar_en_chat("Tú", texto)
        self.context_manager.add_message(role="user", content=texto)
        self.entry_chat.delete(0, "end")

        # 2. Bloquear UI
        self.entry_chat.configure(state="disabled")
        self._worker_activo = True
        self.boton_enviar.configure(text="Cancelar", state="normal", command=self.cancelar_tarea_actual)
        
        # 3. Lanzar hilo
        threading.Thread(target=self._hilo_local_primero, args=(texto,), daemon=True).start()

    def _hilo_local_primero(self, texto: str):
        try:
            resultado_local = self.local_router.try_handle(texto)
            if resultado_local and resultado_local.handled:
                self.textbox_historial.after(0, self._finalizar_resultado_local, resultado_local)
                return
        except Exception as exc:
            self.textbox_historial.after(0, self._restaurar_ui, f"Error procesando accion local: {type(exc).__name__}: {exc}")
            return

        self._hilo_gemini(texto)

    def _finalizar_resultado_local(self, resultado_local):
        self._mostrar_en_chat("Asistente", resultado_local.message)
        self.context_manager.add_message(role="assistant", content=resultado_local.message)
        self._restaurar_controles()
        if resultado_local.refresh:
            self._refrescar_explorador_seguro()

    def cancelar_tarea_actual(self):
        if not self._worker_activo:
            return
        try:
            self.local_router.request_cancel()
        except Exception:
            pass
        self.agregar_mensaje_sistema("Cancelacion solicitada. Se detendra al terminar la foto o lote actual.")
        self.boton_enviar.configure(state="disabled")
        if hasattr(self, '_progress_window') and self._progress_window and self._progress_window.winfo_exists():
            self._progress_window.update_progress({"phase": "canceled", "message": "Cancelando..."})

    def _es_rate_limit_error(self, error):
        import re

        code = getattr(error, "code", None) or getattr(error, "status_code", None)
        if code == 429:
            return True

        error_str = str(error).upper()
        return "RESOURCE_EXHAUSTED" in error_str or re.search(r"\b429\b", error_str) is not None

    def _es_error_saturacion_modelo(self, error):
        import re

        code = getattr(error, "code", None) or getattr(error, "status_code", None)
        if code == 503:
            return True

        error_str = str(error).upper()
        return (
            "UNAVAILABLE" in error_str
            or "HIGH DEMAND" in error_str
            or "TEMPORARILY UNAVAILABLE" in error_str
            or re.search(r"\b503\b", error_str) is not None
        )

    def _hilo_gemini(self, texto):
        """Hilo en segundo plano para procesar la petición con la IA."""
        import time
        import re
        import traceback

        try:
            resultado_openai = self._intentar_openai_fallback(texto)
            if resultado_openai and resultado_openai.handled:
                self.textbox_historial.after(0, self._restaurar_ui, resultado_openai.message)
                return
        except Exception as e:
            print(f"[OPENAI_ORCH] error en fallback: {type(e).__name__}: {e}")
        
        if not self.chat_session:
            mensaje_error = (
                "La IA avanzada no está inicializada. Verifica OPENAI_API_KEY/GEMINI_API_KEY y selecciona un workspace válido."
            )
            self.textbox_historial.after(0, self._restaurar_ui, mensaje_error)
            return

        max_reintentos = 3
        intento = 0
        
        while intento < max_reintentos:
            try:
                # Llama a Gemini. Las Tools se ejecutarán aquí mismo de ser necesario.
                response = self.chat_session.send_message(texto)
                
                # Obtener el texto de la respuesta de forma segura
                try:
                    respuesta_final = response.text
                    if not respuesta_final:
                        respuesta_final = "✅ Operación ejecutada."
                except ValueError:
                    # El SDK de google.genai puede lanzar ValueError si no hay texto
                    respuesta_final = "✅ Operación completada (sin respuesta de texto)."
                except Exception:
                    respuesta_final = "✅ Operación procesada."
                
                # Volver al hilo principal
                self.textbox_historial.after(0, self._restaurar_ui, respuesta_final)
                return  # Éxito, salir de la función
                
            except Exception as e:
                error_str = str(e)
                
                if self._es_error_saturacion_modelo(e):
                    print(f"[Gemini] Error de saturacion en {self.modelo_gemini}: {error_str}")
                    try:
                        cambio_ok = self._cambiar_al_siguiente_modelo()
                    except Exception as cambio_error:
                        print(f"[Gemini] No se pudo reconstruir chat_session: {type(cambio_error).__name__}: {cambio_error}")
                        traceback.print_exc()
                        mensaje_error = (
                            "Gemini devolvio saturacion y no se pudo cambiar de modelo:\n"
                            f"{type(cambio_error).__name__}: {cambio_error}"
                        )
                        self.textbox_historial.after(0, self._restaurar_ui, mensaje_error)
                        return

                    if cambio_ok:
                        self.textbox_historial.after(
                            0,
                            self.agregar_mensaje_sistema,
                            f"Gemini esta saturado. Cambiando a {self.modelo_gemini}..."
                        )
                        continue

                    mensaje_error = (
                        "Gemini esta ocupado temporalmente. Puedo seguir creando, moviendo, buscando, leyendo y organizando archivos localmente.\n"
                        f"Ultimo error: {error_str}"
                    )
                    self.textbox_historial.after(0, self._restaurar_ui, mensaje_error)
                    return

                # Detectar error 429 (Cuota o Rate Limit excedido)
                if self._es_rate_limit_error(e):
                    intento += 1
                    
                    if intento >= max_reintentos:
                        mensaje_error = "El modulo de IA avanzada alcanzo su limite temporal, pero las acciones locales siguen disponibles."
                        self.textbox_historial.after(0, self._restaurar_ui, mensaje_error)
                        return
                    
                    # Intentar extraer el tiempo de espera recomendado ("Retry in 50s")
                    espera = 30  # Default 30s
                    match = re.search(r"retry in (\d+(?:\.\d+)?)s", error_str, re.IGNORECASE)
                    if match:
                        espera = int(float(match.group(1))) + 2  # Añadir 2s de margen de seguridad
                    
                    mensaje_espera = f"⏳ Límite de IA alcanzado (Rate Limit). Pausando {espera}s antes de reintentar (Intento {intento}/{max_reintentos})..."
                    self.textbox_historial.after(0, self.agregar_mensaje_sistema, mensaje_espera)
                    
                    time.sleep(espera)
                    # El bucle repetirá la petición automáticamente sin pedirle al usuario que vuelva a enviar
                else:
                    print("\n❌ ERROR EN HILO GEMINI:")
                    traceback.print_exc()
                    
                    # Mostrar el error real en el chat para saber exactamente qué falló
                    mensaje_error = f"⚠️ Ocurrió un error al procesar la respuesta:\n{error_str}"
                    self.textbox_historial.after(0, self._restaurar_ui, mensaje_error)
                    return

    def _restaurar_ui(self, respuesta, refresh=True):
        """Restaura los controles de la interfaz y actualiza el árbol de archivos."""
        self._mostrar_en_chat("Asistente", respuesta)
        if hasattr(self, "context_manager") and self.context_manager:
            self.context_manager.add_message(role="assistant", content=respuesta)
        self._restaurar_controles()
        if refresh and self.callback_refrescar:
            try:
                self.callback_refrescar(None)
            except Exception as e:
                print(f"Error al refrescar explorador: {e}")

    def _restaurar_controles(self):
        self._worker_activo = False
        self.entry_chat.configure(state="normal")
        self.boton_enviar.configure(text="➜", state="normal", command=self.procesar_mensaje)
        self.entry_chat.focus()
        
        # Refrescar árbol de archivos automáticamente
