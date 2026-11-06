from customtkinter import filedialog
import customtkinter as ctk
from tkinter import messagebox
import os
import errno
import shutil
import json
from datetime import datetime
from pathlib import Path
from facesyncApp.utils import set_windows_title_bar_light

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    HttpError = None

try:
    import pandas as pd
    import openpyxl
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

PANEL_COLOR = "#081122"
CARD_COLOR  = "#0B1526"
ACCENT      = "#2563EB"
SUBTEXT     = "#94A3B8"
BORDER      = "#122033"

EXTENSIONES_PERMITIDAS = (
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.cr2', '.cr3',
    '.xlsx', '.xls', '.pdf', '.txt', '.docx', '.pptx',
    '.mp4', '.mp3', '.avi', '.mov', '.wmv', '.flv', '.mkv',
    '.py', '.json', '.csv', '.zip', '.rar',
)


# ======================================================================
# Helpers de exportación a Drive (Fase 6 — robustez de subida)
# Extraídos a nivel de módulo para poder testearlos de forma aislada.
# ======================================================================

# Estados HTTP transitorios reales de la API de Google que justifican backoff.
_DRIVE_RATE_LIMIT_STATUS = {429, 500, 502, 503}
# Razones de un 403 que SÍ corresponden a límite de cuota (transitorio).
_DRIVE_RATE_LIMIT_REASONS = (
    "ratelimitexceeded", "userratelimitexceeded", "quotaexceeded",
    "backenderror", "internalerror", "rate limit",
)


def _clasificar_error_drive(exc) -> str:
    """Clasifica un error de subida en: 'missing' | 'rate_limit' | 'fatal'.

    - 'missing'    -> el archivo no existe / ruta inválida. Falla rápido, sin reintentar.
    - 'rate_limit' -> error transitorio real de la API. Reintentar con backoff.
    - 'fatal'      -> error permanente. No reintentar.

    Clave del fix: NO se hace substring del código contra el str() del error
    (eso confundía 'IMG_6429.JPG' con un 429). Se usa el tipo de excepción y,
    para errores de API, el status HTTP real.
    """
    if isinstance(exc, FileNotFoundError):
        return "missing"
    if isinstance(exc, IsADirectoryError):
        return "fatal"
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ENOENT:
        return "missing"

    if HttpError is not None and isinstance(exc, HttpError):
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "resp", None), "status", None)
        try:
            status = int(status) if status is not None else None
        except (TypeError, ValueError):
            status = None
        if status in _DRIVE_RATE_LIMIT_STATUS:
            return "rate_limit"
        if status == 403:
            # Un 403 puede ser cuota (transitorio) o permisos (permanente).
            # El motivo viaja en el cuerpo de la respuesta (exc.content), no
            # siempre en str(exc); revisamos ambos para acertar.
            motivo = str(exc).lower()
            raw = getattr(exc, "content", b"") or b""
            if isinstance(raw, (bytes, bytearray)):
                motivo += " " + bytes(raw).decode("utf-8", errors="replace").lower()
            else:
                motivo += " " + str(raw).lower()
            return "rate_limit" if any(r in motivo for r in _DRIVE_RATE_LIMIT_REASONS) else "fatal"
        return "fatal"

    return "fatal"


def _ruta_drive_segura(path) -> str:
    """Devuelve una ruta apta para abrir archivos con rutas largas.

    En Windows aplica el prefijo de ruta extendida para superar el límite
    MAX_PATH (260 chars), causa de FileNotFoundError en estructuras profundas
    tipo 'ALUMNOS 501 VESP/MEZA MARTINEZ.../IMG_xxxx.JPG'.
    """
    p = os.path.abspath(str(path))
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        if p.startswith("\\\\"):
            p = "\\\\?\\UNC\\" + p[2:]
        else:
            p = "\\\\?\\" + p
    return p


class DashboardBackend:
    def __init__(self, vista):
        self.vista = vista

    def manejar_boton_agregar(self):
        self._mostrar_popup_eleccion()

    def _mostrar_popup_eleccion(self):
        popup = ctk.CTkToplevel(self.vista)
        popup.title("¿Qué deseas agregar?")
        set_windows_title_bar_light(popup)
        popup.geometry("340x180")
        popup.resizable(False, False)
        popup.configure(fg_color=PANEL_COLOR)
        popup.grab_set()
        popup.focus_force()
        self.vista.update_idletasks()
        x = self.vista.winfo_x() + (self.vista.winfo_width() // 2) - 170
        y = self.vista.winfo_y() + (self.vista.winfo_height() // 2) - 90
        popup.geometry(f"+{x}+{y}")

        ctk.CTkLabel(popup, text="Selecciona el tipo de contenido a agregar",
                     font=("Segoe UI", 13), text_color=SUBTEXT).pack(pady=(20, 15))
        bf = ctk.CTkFrame(popup, fg_color="transparent")
        bf.pack(fill="x", padx=25)
        ctk.CTkButton(bf, text="📄  Archivos", height=42, corner_radius=10,
                      fg_color=ACCENT, hover_color="#1D4ED8", font=("Segoe UI", 14, "bold"),
                      command=lambda: [popup.destroy(), self._seleccionar_archivos()]
                      ).pack(side="left", expand=True, fill="x", padx=(0, 8))
        ctk.CTkButton(bf, text="📁  Carpeta", height=42, corner_radius=10,
                      fg_color=CARD_COLOR, hover_color="#1E3A5F",
                      border_width=1, border_color=BORDER, font=("Segoe UI", 14, "bold"),
                      command=lambda: [popup.destroy(), self._seleccionar_carpeta()]
                      ).pack(side="left", expand=True, fill="x")

    def _seleccionar_archivos(self, target_dir=None):
        print(f"DEBUG: _seleccionar_archivos llamado con target_dir={target_dir}")
        kwargs = {
            "title": "Selecciona archivos",
            "filetypes": [("Todos los archivos", "*.*")]
        }
        if target_dir and os.path.isdir(target_dir):
            kwargs["initialdir"] = target_dir
            print(f"DEBUG: initialdir set to {target_dir}")
        archivos = filedialog.askopenfilenames(**kwargs)
        print(f"DEBUG: archivos seleccionados: {archivos}")
        if not archivos:
            print("DEBUG: no archivos seleccionados")
            return

        archivos = [os.path.abspath(a).replace("\\", "/") for a in archivos]
        if target_dir and os.path.isdir(target_dir):
            target_dir = os.path.abspath(target_dir)
            archivos_destino = []
            for origen in archivos:
                if os.path.dirname(origen) == target_dir:
                    archivos_destino.append(origen)
                    continue
                destino = os.path.join(target_dir, os.path.basename(origen))
                destino = os.path.abspath(destino).replace("\\", "/")
                try:
                    if not os.path.exists(destino):
                        shutil.copy2(origen, destino)
                        print(f"DEBUG: copiado {origen} a {destino}")
                    archivos_destino.append(destino)
                except Exception as e:
                    print(f"DEBUG: error copiando {origen}: {e}")
                    archivos_destino.append(origen)
            self._finalizar(archivos_destino, target_dir=target_dir)
        else:
            self._finalizar(archivos)

    def _seleccionar_carpeta(self):
        carpeta = filedialog.askdirectory(title="Selecciona una carpeta")
        if not carpeta:
            return
        self.vista._add_folder_root(carpeta)
        self.vista._rerender_explorador()
        self.vista.guardar_espacio_trabajo()

    def _finalizar(self, archivos_encontrados, target_dir=None):
        if not archivos_encontrados:
            return
        archivos = [os.path.abspath(a).replace("\\", "/") for a in archivos_encontrados]
        self.vista._archivos_actuales = sorted(set(self.vista._archivos_actuales + archivos))
        if target_dir and os.path.isdir(target_dir):
            self.vista._refresh_after_fs_change(target_dir)
        else:
            self.vista._repair_legacy_tree()
            self.vista._rerender_explorador()
        self.vista.guardar_espacio_trabajo()

    # ==================== ACCIONES RÁPIDAS ====================
    
    def iniciar_analisis(self):
        """🚀 Iniciar Análisis: Reconocimiento facial en segundo plano."""
        # Verificar si hay carpeta de fotos en el explorador
        if not self.vista._folder_roots:
            messagebox.showerror("❌ Error", "Agrega al menos una carpeta con fotos al explorador primero.")
            return
            
        ruta_carpeta_fotos = self.vista._folder_roots[0]

        # Abrir filedialog para seleccionar Excel
        ruta_excel = filedialog.askopenfilename(
            title="Selecciona el Excel de referencia",
            filetypes=[("Excel files", "*.xlsx")]
        )

        if not ruta_excel:
            return

        # Definir ruta de salida: usuarios/{current_user_email}/ALUMNOS/
        email_usuario = self.vista.email_usuario
        usuarios_dir = Path(__file__).parent.parent / "usuarios"
        ruta_salida = usuarios_dir / email_usuario / "ALUMNOS"
        os.makedirs(ruta_salida, exist_ok=True)

        # Buscar la tarjeta de acción en la vista para modificar la UI
        card_info = next((c for c in self.vista.action_cards if "Análisis" in c["name"]), None)
        if card_info:
            card = card_info["card"]
            # Desvincular clicks
            card.unbind("<Button-1>")
            card_info["title"].unbind("<Button-1>")
            card_info["desc"].unbind("<Button-1>")
            
            # Cambiar estilo a procesando
            card.configure(border_color="#F59E0B")
            card_info["desc"].configure(text="Procesando rostros... Por favor espera.", text_color="#F59E0B")
            
            # Crear e iniciar barra de progreso
            if not hasattr(self.vista, 'pb_analisis'):
                self.vista.pb_analisis = ctk.CTkProgressBar(card, mode="indeterminate", height=6, progress_color="#F59E0B")
            self.vista.pb_analisis.pack(fill="x", padx=15, pady=(5, 0))
            self.vista.pb_analisis.start()

        # Importar y ejecutar el motor de IA
        # motor_ia_fast = motor acelerado (mismos resultados) con fallback
        # automatico al motor original (facesyncApp.motor_ia) si algo fallara.
        from facesyncApp.motor_ia_fast import MotorFaceSync

        def restaurar_ui():
            if card_info:
                card = card_info["card"]
                # Restaurar progress bar
                if hasattr(self.vista, 'pb_analisis'):
                    self.vista.pb_analisis.stop()
                    self.vista.pb_analisis.pack_forget()
                
                # Restaurar estilo
                card.configure(border_color=BORDER)
                card_info["desc"].configure(text="Ejecutar reconocimiento facial", text_color=SUBTEXT)
                
                # Revincular clicks
                def make_click_handler(command):
                    def on_click(event):
                        command()
                    return on_click
                
                handler = make_click_handler(card_info["cmd"])
                card.bind("<Button-1>", handler)
                card_info["title"].bind("<Button-1>", handler)
                card_info["desc"].bind("<Button-1>", handler)

        def callback_fin(exito, mensaje):
            self.vista.after(0, restaurar_ui)
            if exito:
                self.vista.after(0, lambda: messagebox.showinfo("✅ Análisis Terminado", mensaje))
                self.vista.after(0, lambda: self.vista._refresh_after_fs_change(str(ruta_salida)))
                self.vista.after(0, self.vista.guardar_espacio_trabajo)
            else:
                self.vista.after(0, lambda: messagebox.showerror("❌ Error en Análisis", mensaje))

        MotorFaceSync.iniciar_reconocimiento_en_hilo(
            ruta_carpeta_fotos=ruta_carpeta_fotos,
            ruta_excel=ruta_excel,
            carpeta_destino=str(ruta_salida),
            callback_resultado=callback_fin
        )
    
    def exportar_a_drive(self):
        """☁️ Exportar a Drive: Abre ventana modal para seleccionar carpeta y subirla a Google Drive."""
        # ── Validaciones previas ──
        email_usuario = self.vista.email_usuario
        from oauth_service import token_path_for_account
        token_path = token_path_for_account(email_usuario)

        if not os.path.exists(token_path):
            print(f"ERROR: No se encontró token.json para {email_usuario}")
            messagebox.showerror(
                "❌ Error",
                f"No hay credenciales de Google Drive para {email_usuario}.\nPor favor, configura tu cuenta primero."
            )
            return

        if not GOOGLE_API_AVAILABLE:
            print("ERROR: Dependencias de Google API no instaladas")
            messagebox.showerror(
                "❌ Dependencias Faltantes",
                "Instala las dependencias:\npip install google-auth-oauthlib google-auth-httplib2 google-api-python-client"
            )
            return

        # ── Recopilar subcarpetas disponibles del explorador ──
        subcarpetas = []  # lista de (nombre_display, ruta_absoluta)

        for root_path in self.vista._folder_roots:
            root_path = os.path.abspath(root_path).replace("\\", "/")
            # Agregar la carpeta raíz misma
            subcarpetas.append((os.path.basename(root_path) or root_path, root_path))
            # Agregar subcarpetas directas
            try:
                for entry in os.scandir(root_path):
                    if entry.is_dir(follow_symlinks=False):
                        subcarpetas.append((f"  └─ {entry.name}", entry.path.replace("\\", "/")))
            except OSError:
                pass

        if not subcarpetas:
            messagebox.showerror(
                "❌ Error",
                "No hay carpetas en el explorador.\nAgrega al menos una carpeta primero."
            )
            return

        # ── Crear ventana modal ──
        modal = ctk.CTkToplevel(self.vista)
        modal.title("Seleccionar Carpeta a Exportar")
        set_windows_title_bar_light(modal)
        modal.geometry("480x320")
        modal.resizable(False, False)
        modal.configure(fg_color="#0D0D0D")
        modal.grab_set()
        modal.focus_force()

        # Centrar en pantalla
        self.vista.update_idletasks()
        x = self.vista.winfo_x() + (self.vista.winfo_width() // 2) - 240
        y = self.vista.winfo_y() + (self.vista.winfo_height() // 2) - 160
        modal.geometry(f"+{x}+{y}")

        # ── Contenido de la modal ──
        # Icono y título
        ctk.CTkLabel(
            modal, text="☁️", font=("Segoe UI", 40)
        ).pack(pady=(25, 5))
        ctk.CTkLabel(
            modal, text="Exportar a Google Drive",
            font=("Segoe UI", 18, "bold"), text_color="#FFFFFF"
        ).pack(pady=(0, 5))
        ctk.CTkLabel(
            modal, text="Selecciona la carpeta que deseas respaldar en la nube",
            font=("Segoe UI", 12), text_color="#94A3B8"
        ).pack(pady=(0, 20))

        # Mapa nombre_display → ruta real
        nombres_display = [nombre for nombre, _ in subcarpetas]
        mapa_rutas = {nombre: ruta for nombre, ruta in subcarpetas}

        # ComboBox de selección
        combo_var = ctk.StringVar(value=nombres_display[0])
        combo = ctk.CTkComboBox(
            modal,
            values=nombres_display,
            variable=combo_var,
            width=400,
            height=42,
            corner_radius=12,
            fg_color="#1A1A1A",
            border_color="#2C2C2C",
            button_color="#2563EB",
            button_hover_color="#1D4ED8",
            dropdown_fg_color="#1A1A1A",
            dropdown_hover_color="#272727",
            font=("Segoe UI", 13),
            dropdown_font=("Segoe UI", 13),
            state="readonly"
        )
        combo.pack(pady=(0, 25))

        # Botón de exportar
        btn_exportar = ctk.CTkButton(
            modal,
            text="📤  Exportar a Drive",
            width=400,
            height=48,
            corner_radius=12,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            font=("Segoe UI", 15, "bold"),
            command=lambda: self._ejecutar_subida_drive(
                modal, btn_exportar, combo_var.get(), mapa_rutas, token_path
            )
        )
        btn_exportar.pack()

    def _ejecutar_subida_drive(self, modal, btn_exportar, seleccion, mapa_rutas, token_path):
        """Captura la selección, cierra la modal y lanza la subida en un hilo."""
        ruta_carpeta = mapa_rutas.get(seleccion)
        if not ruta_carpeta or not os.path.isdir(ruta_carpeta):
            messagebox.showerror("❌ Error", "La carpeta seleccionada no existe o es inválida.")
            return

        nombre_carpeta = os.path.basename(ruta_carpeta)
        modal.destroy()

        # ── Modificar tarjeta de acción para indicar estado "Subiendo..." ──
        card_info = next((c for c in self.vista.action_cards if "Drive" in c["name"]), None)
        if card_info:
            card = card_info["card"]
            card.unbind("<Button-1>")
            card_info["title"].unbind("<Button-1>")
            card_info["desc"].unbind("<Button-1>")
            card.configure(border_color="#F59E0B")
            card_info["desc"].configure(text=f"Subiendo '{nombre_carpeta}'...", text_color="#F59E0B")

            # Barra de progreso DETERMINADA (no indeterminada)
            if not hasattr(self.vista, 'pb_drive'):
                self.vista.pb_drive = ctk.CTkProgressBar(
                    card, mode="determinate", height=6, progress_color="#2563EB"
                )
            else:
                self.vista.pb_drive.configure(mode="determinate")
            self.vista.pb_drive.set(0)
            self.vista.pb_drive.pack(fill="x", padx=15, pady=(5, 0))

            # Label de conteo: "0 / ??? archivos"
            if not hasattr(self.vista, 'lbl_drive_count'):
                self.vista.lbl_drive_count = ctk.CTkLabel(
                    card, text="Escaneando archivos...",
                    font=("Segoe UI", 10), text_color="#F59E0B"
                )
            else:
                self.vista.lbl_drive_count.configure(text="Escaneando archivos...")
            self.vista.lbl_drive_count.pack(fill="x", padx=15, pady=(2, 5))

        # ── Función para restaurar la UI al finalizar ──
        def restaurar_ui():
            if card_info:
                card = card_info["card"]
                if hasattr(self.vista, 'pb_drive'):
                    self.vista.pb_drive.pack_forget()
                if hasattr(self.vista, 'lbl_drive_count'):
                    self.vista.lbl_drive_count.pack_forget()
                card.configure(border_color=BORDER)
                card_info["desc"].configure(text="Respaldar resultados en la nube", text_color=SUBTEXT)

                def make_click_handler(command):
                    def on_click(event):
                        command()
                    return on_click

                handler = make_click_handler(card_info["cmd"])
                card.bind("<Button-1>", handler)
                card_info["title"].bind("<Button-1>", handler)
                card_info["desc"].bind("<Button-1>", handler)

        # ══════════════════════════════════════════════════════════════════
        # HILO PRINCIPAL DE SUBIDA — Contiene ThreadPoolExecutor internamente
        # ══════════════════════════════════════════════════════════════════
        def tarea_subida_paralela():
            import threading as _threading
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import time
            import random

            t_start = time.time()

            MAX_WORKERS = 15
            MAX_RETRIES = 5
            BACKOFF_BASE = 1.0  # segundos

            # ── Contadores thread-safe ──
            lock = _threading.Lock()
            archivos_subidos_counter = [0]
            archivos_fallidos_counter = [0]
            archivos_missing_counter = [0]
            reintentos_counter = [0]
            procesados_counter = [0]
            total_archivos = [0]

            # ── Refresco seguro de la UI. La barra avanza por PROCESADOS,
            #    así llega a 100% aunque haya fallidos/omitidos. ──
            def _refrescar_ui():
                with lock:
                    proc = procesados_counter[0]
                    subidos = archivos_subidos_counter[0]
                total = total_archivos[0] or 1
                pct = min(1.0, proc / total)
                self.vista.after(0, lambda: self.vista.pb_drive.set(pct)
                                 if hasattr(self.vista, 'pb_drive') else None)
                self.vista.after(0, lambda s=subidos, t=total_archivos[0]:
                                 self.vista.lbl_drive_count.configure(
                                     text=f"📄 {s} / {t} subidos")
                                 if hasattr(self.vista, 'lbl_drive_count') else None)

            try:
                # ── Autenticación ──
                creds = Credentials.from_authorized_user_file(token_path, scopes=[
                    'https://www.googleapis.com/auth/drive.file'
                ])
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    with open(token_path, 'w') as token_file:
                        token_file.write(creds.to_json())

                # ── Servicio por hilo (thread-local) ──
                _thread_local = _threading.local()

                def get_drive_service():
                    """Retorna un objeto service exclusivo para este hilo."""
                    if not hasattr(_thread_local, 'service'):
                        _thread_local.service = build('drive', 'v3', credentials=creds)
                    return _thread_local.service

                # ── Escanear estructura de carpetas y contar archivos ──
                def escanear_estructura(ruta_local):
                    """Retorna lista de (ruta_archivo, ruta_relativa_carpeta)."""
                    resultados = []
                    for root, dirs, files in os.walk(ruta_local):
                        rel = os.path.relpath(root, ruta_local).replace("\\", "/")
                        if rel == ".":
                            rel = ""
                        for f in files:
                            resultados.append((
                                os.path.join(root, f).replace("\\", "/"),
                                rel
                            ))
                    return resultados

                print(f"[Drive] Escaneando estructura de '{nombre_carpeta}'...")
                archivos_a_subir = escanear_estructura(ruta_carpeta)
                total_archivos[0] = len(archivos_a_subir)
                print(f"[Drive] Total archivos encontrados: {total_archivos[0]}")

                # Actualizar UI con el total
                self.vista.after(0, lambda: self.vista.lbl_drive_count.configure(
                    text=f"📄 0 / {total_archivos[0]} archivos"
                ) if hasattr(self.vista, 'lbl_drive_count') else None)

                # ── Crear carpeta principal en Drive ──
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                drive_folder_name = f'FaceSync_{nombre_carpeta}_{timestamp}'

                service_main = get_drive_service()
                main_folder = service_main.files().create(
                    body={'name': drive_folder_name, 'mimeType': 'application/vnd.google-apps.folder'},
                    fields='id'
                ).execute()
                main_folder_id = main_folder.get('id')
                print(f"[Drive] Carpeta raíz creada: {drive_folder_name} (ID: {main_folder_id})")

                # ── Crear estructura de carpetas en Drive (secuencial, son pocas) ──
                carpetas_remotas = {"": main_folder_id}
                rutas_carpeta_unicas = sorted({rel for _, rel in archivos_a_subir if rel})

                for rel_path in rutas_carpeta_unicas:
                    partes = rel_path.split("/")
                    for i in range(len(partes)):
                        sub_path = "/".join(partes[:i + 1])
                        if sub_path in carpetas_remotas:
                            continue
                        parent_path = "/".join(partes[:i]) if i > 0 else ""
                        parent_drive_id = carpetas_remotas[parent_path]
                        folder_meta = {
                            'name': partes[i],
                            'parents': [parent_drive_id],
                            'mimeType': 'application/vnd.google-apps.folder'
                        }
                        folder = service_main.files().create(
                            body=folder_meta, fields='id'
                        ).execute()
                        carpetas_remotas[sub_path] = folder.get('id')
                        print(f"[Drive]   📁 Carpeta creada: {sub_path}")

                # ── Subir un solo archivo: backoff SOLO para errores reales de API ──
                def subir_archivo_con_reintentos(file_path, rel_folder):
                    """Valida existencia, maneja rutas largas y reintenta solo ante
                    errores transitorios reales de la API (nunca un FileNotFound)."""
                    parent_id = carpetas_remotas.get(rel_folder, main_folder_id)
                    file_name = os.path.basename(file_path)
                    safe_path = _ruta_drive_segura(file_path)

                    # Validar existencia ANTES de subir (rutas largas / movidos).
                    if not os.path.isfile(safe_path):
                        print(f"[Drive] ⏭ Omitido (no existe): '{file_name}'")
                        with lock:
                            archivos_missing_counter[0] += 1
                            procesados_counter[0] += 1
                        _refrescar_ui()
                        return False

                    for intento in range(MAX_RETRIES):
                        try:
                            svc = get_drive_service()
                            media = MediaFileUpload(safe_path, resumable=True)
                            file_metadata = {
                                'name': file_name,
                                'parents': [parent_id]
                            }
                            svc.files().create(
                                body=file_metadata, media_body=media, fields='id'
                            ).execute()

                            with lock:
                                archivos_subidos_counter[0] += 1
                                procesados_counter[0] += 1
                                subidos = archivos_subidos_counter[0]
                            _refrescar_ui()

                            if subidos % 50 == 0 or subidos == total_archivos[0]:
                                print(f"[Drive] ✓ Progreso: {subidos}/{total_archivos[0]}")
                            return True

                        except Exception as e:
                            categoria = _clasificar_error_drive(e)

                            if categoria == "missing":
                                print(f"[Drive] ⏭ Omitido (no existe): '{file_name}'")
                                with lock:
                                    archivos_missing_counter[0] += 1
                                    procesados_counter[0] += 1
                                _refrescar_ui()
                                return False

                            if categoria == "rate_limit" and intento < MAX_RETRIES - 1:
                                with lock:
                                    reintentos_counter[0] += 1
                                wait = BACKOFF_BASE * (2 ** intento) + random.uniform(0, 1)
                                print(f"[Drive] ⚠ Rate limit en '{file_name}' "
                                      f"(intento {intento + 1}/{MAX_RETRIES}). "
                                      f"Esperando {wait:.1f}s...")
                                time.sleep(wait)
                                continue

                            # fatal, o rate_limit que agotó reintentos
                            print(f"[Drive] ❌ Fallo definitivo '{file_name}': "
                                  f"{type(e).__name__}: {str(e)[:100]}")
                            with lock:
                                archivos_fallidos_counter[0] += 1
                                procesados_counter[0] += 1
                            _refrescar_ui()
                            return False

                    return False

                # ── Subida paralela con ThreadPoolExecutor ──
                print(f"[Drive] 🚀 Iniciando subida paralela con {MAX_WORKERS} workers...")

                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    futures = {
                        executor.submit(subir_archivo_con_reintentos, fp, rf): (fp, rf)
                        for fp, rf in archivos_a_subir
                    }

                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as exc:
                            fp, _ = futures[future]
                            print(f"[Drive] ❌ Excepción no capturada para {fp}: {exc}")
                            with lock:
                                archivos_fallidos_counter[0] += 1

                # ── Notificar resultado en el hilo principal ──
                total_ok = archivos_subidos_counter[0]
                total_fail = archivos_fallidos_counter[0]
                total_missing = archivos_missing_counter[0]
                total_reintentos = reintentos_counter[0]
                total = total_archivos[0]
                elapsed = time.time() - t_start

                print(f"[Drive] ════════════════════════════════")
                print(f"[Drive] ✅ Subidos:    {total_ok} / {total}")
                print(f"[Drive] ⏭ Omitidos:   {total_missing} (no existían / ruta inválida)")
                print(f"[Drive] ❌ Fallidos:   {total_fail} (API)")
                print(f"[Drive] 🔁 Reintentos: {total_reintentos}")
                print(f"[Drive] ⏱ Tiempo:     {elapsed:.1f}s")
                print(f"[Drive] ════════════════════════════════")

                self.vista.after(0, restaurar_ui)

                if total_fail == 0 and total_missing == 0:
                    self.vista.after(0, lambda: messagebox.showinfo(
                        "✅ Exportación Exitosa",
                        f"La carpeta '{nombre_carpeta}' se subió correctamente a Google Drive.\n\n"
                        f"📁 Carpeta en Drive: {drive_folder_name}\n"
                        f"📄 Archivos subidos: {total_ok} / {total}\n"
                        f"⏱ Tiempo: {elapsed:.1f}s"
                    ))
                else:
                    self.vista.after(0, lambda: messagebox.showwarning(
                        "⚠️ Exportación Parcial",
                        f"📁 Carpeta en Drive: {drive_folder_name}\n\n"
                        f"✅ Subidos: {total_ok} / {total}\n"
                        f"⏭ Omitidos (no existían): {total_missing}\n"
                        f"❌ Fallidos (API): {total_fail}\n"
                        f"🔁 Reintentos: {total_reintentos}\n"
                        f"⏱ Tiempo: {elapsed:.1f}s\n\n"
                        f"Revisa la consola para detalles."
                    ))

            except Exception as e:
                error_str = str(e)
                print(f"ERROR FATAL al exportar a Drive: {type(e).__name__}: {error_str}")
                self.vista.after(0, restaurar_ui)

                if "403" in error_str:
                    self.vista.after(0, lambda: messagebox.showerror(
                        "❌ Acceso Bloqueado",
                        "Google bloqueó el acceso. Intenta de nuevo en unos minutos."
                    ))
                elif "access_denied" in error_str or "401" in error_str or "Unauthorized" in error_str:
                    self.vista.after(0, lambda: messagebox.showerror(
                        "❌ Token Expirado/Denegado",
                        "Tu sesión expiró o denegó el acceso.\nInicia sesión de nuevo."
                    ))
                else:
                    self.vista.after(0, lambda: messagebox.showerror(
                        "❌ Error al Exportar",
                        f"Fallo al subir a Drive:\n{error_str[:200]}"
                    ))

        import threading
        threading.Thread(target=tarea_subida_paralela, daemon=True).start()
