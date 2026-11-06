"""
FaceSync - Login (Autenticación con Google OAuth)
Clase FaceSyncLogin: ventana de inicio de sesión con selección de cuentas.

Rediseño claro (boceto del cliente): mitad izquierda con el logo, divisor
vertical negro, mitad derecha con "Welcome" (sin cuentas) o "Select an Account"
(con cuentas). Al elegir una cuenta se muestra una ventana redondeada
"Logging in..." y el dashboard se pre-importa en segundo plano para que no
haya espacios en blanco. La LÓGICA de autenticación no cambia.
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import customtkinter as ctk
import tkinter as tk
from PIL import Image
import os
import json
import threading
import shutil
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from facesyncApp import BASE_DIR
from oauth_service import (
    _account_id,
    _users_dir as oauth_users_dir,
    _write_private_text,
    client_secret_path,
    delete_account as delete_saved_account,
)
from facesyncApp.utils import (
    clear_window_identity,
    generate_fallback_avatar,
    download_and_crop_avatar,
    set_windows_title_bar_light,
)

# ==========================================
# CONFIGURACIÓN
# ==========================================
SCOPES = [
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/drive.file',  # Para acceder a Google Drive
    'openid'
]


class FaceSyncLogin(ctk.CTk):
    """
    Ventana de Login con Google OAuth.
    Muestra cuentas guardadas y permite agregar nuevas.
    Al autenticarse exitosamente, abre DashboardWindow.
    """

    def __init__(self):
        super().__init__()
        try:
            tk._default_root = self
        except Exception:
            pass
        ctk.set_appearance_mode("light")

        # Centrar la ventana en la pantalla
        window_width, window_height, x, y = self._center_geometry(1000, 650)
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")

        clear_window_identity(self)
        set_windows_title_bar_light(self)
        self.resizable(False, False)

        # PALETA CLARA (boceto)
        self.BG = "#FFFFFF"
        self.TEXT = "#1F2937"      # texto principal oscuro
        self.SUBTEXT = "#111827"   # subtítulo (negro suave)
        self.MUTED = "#6B7280"     # gris (emails/estados)
        self.HOVER = "#F3F4F6"     # hover suave
        self.DIVIDER = "#D1D5DB"   # línea vertical gris suave (notable, no dura)

        self.configure(fg_color=self.BG)

        # Email del usuario autenticado (se establece al hacer login)
        self._email_autenticado = None
        self._img_refs = []        # evita GC de imágenes
        self._login_dialog = None
        self._login_dialog_status = None
        self._login_dialog_name_label = None
        self._login_dialog_email_label = None
        self._login_dialog_avatar_label = None
        self._main_status = None

        self._setup_ui()

    def _center_geometry(self, width, height, margin=80):
        """Devuelve geometria centrada y ajustada al tamano de pantalla."""
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        max_width = max(320, screen_width - margin)
        max_height = max(300, screen_height - margin)
        width = min(width, max_width)
        height = min(height, max_height)
        x = max(0, int((screen_width - width) / 2))
        y = max(0, int((screen_height - height) / 2))
        return width, height, x, y

    def _center_window(self, window, width, height, margin=80):
        """Centra una ventana de login en la pantalla actual."""
        width, height, x, y = self._center_geometry(width, height, margin=margin)
        window.geometry(f"{width}x{height}+{x}+{y}")
        return width, height

    # ==========================================
    # HELPERS DE ASSETS
    # ==========================================
    def _asset(self, fname, width=None, height=None):
        """CTkImage de assets/images escalada (None si no se puede)."""
        try:
            path = os.path.join(BASE_DIR, 'assets', 'images', fname)
            pil = Image.open(path).convert("RGBA")
            w, h = pil.size
            if width and not height:
                height = max(1, int(h * (width / w)))
            elif height and not width:
                width = max(1, int(w * (height / h)))
            elif not width and not height:
                width, height = w, h
            img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(width, height))
            self._img_refs.append(img)
            return img
        except Exception:
            return None

    # ==========================================
    # CONSTRUCCIÓN DE LA INTERFAZ (boceto claro)
    # ==========================================
    def _setup_ui(self):
        """Mitad izquierda: logo. Divisor negro. Mitad derecha: cuentas."""
        self.main_frame = ctk.CTkFrame(self, fg_color=self.BG, corner_radius=0)
        self.main_frame.pack(fill="both", expand=True)

        # LOGO (izquierda, centrado)
        logo = self._asset('logologin.png', width=200)
        if logo is not None:
            ctk.CTkLabel(self.main_frame, image=logo, text="").place(
                relx=0.25, rely=0.5, anchor="center")
        else:
            fb = ctk.CTkFrame(self.main_frame, fg_color="transparent")
            fb.place(relx=0.25, rely=0.5, anchor="center")
            ctk.CTkLabel(fb, text="Face", font=("Segoe UI", 34, "bold"),
                         text_color=self.TEXT).pack(side="left")
            ctk.CTkLabel(fb, text="Sync", font=("Segoe UI", 34, "bold"),
                         text_color="#3B82F6").pack(side="left")

        # DIVISOR vertical negro: muy delgado pero SIEMPRE visible.
        # tk.Frame plano (no CTkFrame): 2 px nítidos sin que el escalado/AA
        # de CTk se "coma" la línea.
        tk.Frame(self.main_frame, bg=self.DIVIDER, width=2,
                 bd=0, highlightthickness=0).place(relx=0.5, rely=0.5,
                                                   anchor="center",
                                                   relheight=0.86)

        # Contenedor derecho (las dos variantes viven aquí)
        self.card = ctk.CTkFrame(self.main_frame, width=420, height=560,
                                 fg_color="transparent", corner_radius=0)
        self.card.place(relx=0.75, rely=0.5, anchor="center")
        self.card.pack_propagate(False)

        # Icono de Google (para el botón)
        self.google_icon_ctk = self._asset('GOOGLE.png', width=20)

        self._load_accounts_ui()

    # ==========================================
    # UI DE CUENTAS GUARDADAS
    # ==========================================
    def _load_accounts_ui(self):
        """Carga la lista de cuentas guardadas o muestra el login inicial."""
        # Limpiar elementos previos en la tarjeta
        for widget in self.card.winfo_children():
            widget.destroy()

        users_dir = oauth_users_dir()
        os.makedirs(users_dir, exist_ok=True)
        # Obtener carpetas de usuarios que contengan token.json
        accounts = []
        for d in os.listdir(users_dir):
            if os.path.isdir(os.path.join(users_dir, d)) and os.path.exists(os.path.join(users_dir, d, 'token.json')):
                accounts.append(d)

        if not accounts:
            # BOCETO 1: cliente nuevo
            ctk.CTkLabel(self.card, text="Welcome", font=("Segoe UI", 30, "bold"),
                         text_color=self.TEXT).place(relx=0.5, rely=0.30, anchor="center")
            ctk.CTkLabel(self.card, text="Login to continue to FaceSync",
                         font=("Segoe UI", 13), text_color=self.SUBTEXT
                         ).place(relx=0.5, rely=0.43, anchor="center")
            self._add_google_btn(self.card, "  Add another account", rely=0.58)

            self.status_label = ctk.CTkLabel(self.card, text="", font=("Segoe UI", 11),
                                             text_color=self.MUTED)
            self.status_label.place(relx=0.5, rely=0.72, anchor="center")
        else:
            # BOCETO 2: selección de cuenta. TODO el bloque (título + cuentas +
            # botón) vive en un frame CENTRADO verticalmente: crece hacia arriba
            # y hacia abajo desde el medio, no desde arriba.
            block = ctk.CTkFrame(self.card, fg_color="transparent")
            block.place(relx=0.5, rely=0.5, anchor="center")

            title = ctk.CTkFrame(block, fg_color="transparent")
            title.pack(pady=(0, 22))
            ctk.CTkLabel(title, text="Select an Account ", font=("Segoe UI", 26),
                         text_color=self.TEXT).pack(side="left")
            usuarios_icon = self._asset('usuarioslogin.png', width=30)
            if usuarios_icon is not None:
                ctk.CTkLabel(title, image=usuarios_icon, text="").pack(side="left", padx=(6, 0))

            x_icon = self._asset('xlogin.png', width=14)

            for email_safe in accounts:
                user_path = os.path.join(users_dir, email_safe)
                config_path = os.path.join(user_path, 'config.json')
                pic_path = os.path.join(user_path, 'perfil.png')

                # Cargar config o fallback
                name = ""
                email = email_safe
                if os.path.exists(config_path):
                    try:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                            name = config_data.get('name', '')
                            email = config_data.get('email', email_safe)
                    except Exception:
                        pass

                if not name:
                    name = email_safe.split('@')[0]
                    name = " ".join(part.capitalize() for part in name.replace('.', ' ').replace('_', ' ').split())

                # Asegurar que el avatar de imagen exista
                if not os.path.exists(pic_path):
                    fallback_img = generate_fallback_avatar(name, size=128)
                    fallback_img.save(pic_path, "PNG")

                # Fila de la cuenta (apilada dentro del bloque centrado)
                row_frame = ctk.CTkFrame(block, width=360, height=56,
                                         fg_color="transparent", corner_radius=10)
                row_frame.pack(pady=4)
                row_frame.pack_propagate(False)

                # Avatar circular
                try:
                    img_pil = Image.open(pic_path)
                    img_ctk = ctk.CTkImage(light_image=img_pil, dark_image=img_pil, size=(36, 36))
                    self._img_refs.append(img_ctk)
                    img_label = ctk.CTkLabel(row_frame, image=img_ctk, text="")
                except Exception:
                    img_label = ctk.CTkLabel(row_frame, text="•", text_color=self.TEXT,
                                             font=("Segoe UI", 24))
                img_label.place(x=14, rely=0.5, anchor="w")

                # Nombre y email
                name_label = ctk.CTkLabel(row_frame, text=name, font=("Segoe UI", 13, "bold"),
                                          text_color=self.TEXT, anchor="w")
                name_label.place(x=62, y=16, anchor="w")
                email_label = ctk.CTkLabel(row_frame, text=email, font=("Segoe UI", 11),
                                           text_color=self.MUTED, anchor="w")
                email_label.place(x=62, y=37, anchor="w")

                # Botón eliminar (✕ del boceto)
                delete_btn = ctk.CTkButton(
                    row_frame, text="" if x_icon is not None else "✕", image=x_icon,
                    width=26, height=26, fg_color="transparent", hover_color=self.HOVER,
                    text_color=self.MUTED, font=("Segoe UI", 13, "bold"), border_width=0,
                    command=lambda em=email_safe: self.eliminar_usuario(em)
                )
                delete_btn.place(x=336, rely=0.5, anchor="center")

                # Hover + click en toda la fila
                on_enter = lambda e, f=row_frame: f.configure(fg_color=self.HOVER)
                on_leave = lambda e, f=row_frame: f.configure(fg_color="transparent")
                on_click = lambda e, em=email_safe, nm=name, eml=email, pp=pic_path: \
                    self._login_with_saved_account(em, nm, eml, pp)

                for w in [row_frame, img_label, name_label, email_label]:
                    w.configure(cursor="hand2")
                    w.bind("<Enter>", on_enter)
                    w.bind("<Leave>", on_leave)
                    w.bind("<Button-1>", on_click)

            self._add_google_btn(block, "  Add another account", packed=True)

            self.status_label = ctk.CTkLabel(block, text="", font=("Segoe UI", 11),
                                             text_color=self.MUTED)
            self.status_label.pack(pady=(10, 0))
        self._main_status = self.status_label
        if self._login_dialog_status is not None:
            try:
                if self._login_dialog_status.winfo_exists():
                    self.status_label = self._login_dialog_status
            except Exception:
                pass

    def _add_google_btn(self, parent, text, rely=None, y=None, packed=False):
        """Botón de Google del boceto: G + texto, sin caja (hover suave)."""
        btn = ctk.CTkButton(
            parent, text=text, image=self.google_icon_ctk, compound="left",
            width=240, height=44, corner_radius=10,
            fg_color="transparent", hover_color=self.HOVER, border_width=0,
            text_color=self.TEXT, font=("Segoe UI", 14, "bold"),
            command=self._start_auth_thread
        )
        if packed:
            btn.pack(pady=(26, 0))
        elif rely is not None:
            btn.place(relx=0.5, rely=rely, anchor="center")
        elif y is not None:
            btn.place(relx=0.5, y=y, anchor="center")

    # ==========================================
    # VENTANA "Logging in..." (boceto 3, esquinas redondeadas)
    # ==========================================
    def _mostrar_logging_dialog(self, name, email, pic_path=None, status_text="Logging in..."):
        """Ventanita redondeada con logo + cuenta + 'Logging in...'. La ventana
        principal se oculta; el estado del login se muestra aquí."""
        self._dlg_background = False  # cada diálogo nuevo empieza al frente
        try:
            dlg = self._login_dialog
            if dlg is not None and dlg.winfo_exists():
                self._actualizar_logging_dialog(name, email, pic_path, status_text)
                self._bring_login_dialog_front()
                return
        except Exception:
            self._login_dialog = None
            self._login_dialog_status = None
        try:
            dlg = ctk.CTkToplevel(self)
            dlg.withdraw()
            dlg.overrideredirect(True)
            try:
                dlg.transient(self)
            except Exception:
                pass
            self._center_window(dlg, 340, 450, margin=40)
            # Marco-sombra + panel blanco redondeado (estable, sin transparencias)
            dlg.configure(fg_color="#C7D0E0")
            body = ctk.CTkFrame(dlg, fg_color="#FFFFFF", corner_radius=18,
                                border_width=1, border_color="#E5E7EB")
            body.pack(fill="both", expand=True, padx=6, pady=6)

            # Contenido CENTRADO vertical y horizontalmente
            cont = ctk.CTkFrame(body, fg_color="transparent")
            cont.pack(expand=True)

            logo = self._asset('logologin.png', width=170)
            if logo is not None:
                ctk.CTkLabel(cont, image=logo, text="").pack(pady=(0, 6))
            else:
                ctk.CTkLabel(cont, text="FaceSync", font=("Segoe UI", 24, "bold"),
                             text_color=self.TEXT).pack(pady=(0, 6))

            # Avatar CENTRADO con anillo giratorio (solo diseño: la lógica y los
            # tiempos del login no cambian; el anillo muere con el diálogo).
            # OJO: tk.Canvas NO escala con el DPI de CTk -> dibujar en px físicos.
            import tkinter as _tk
            try:
                esc = float(self._get_window_scaling())
            except Exception:
                esc = 1.0
            lado = int(96 * esc)
            pad = int(6 * esc)
            grosor = max(2, int(3 * esc))
            ring = _tk.Canvas(cont, width=lado, height=lado, bg="#FFFFFF",
                              highlightthickness=0)
            ring.pack(pady=(10, 2))
            ring.create_oval(pad, pad, lado - pad, lado - pad,
                             outline="#E8EEF9", width=grosor)
            arc = ring.create_arc(pad, pad, lado - pad, lado - pad, start=90,
                                  extent=110, style="arc", outline="#2563EB",
                                  width=grosor)
            avatar_initial = (name or email or "G").strip()[:1].upper() or "G"
            avatar_label = ctk.CTkLabel(
                ring, text=avatar_initial, width=44, height=44,
                fg_color="#E8F1FF", text_color="#0B57D0",
                corner_radius=22, font=("Segoe UI", 18, "bold")
            )
            ring.create_window(lado // 2, lado // 2, window=avatar_label)
            self._login_dialog_avatar_label = avatar_label
            try:
                pil = Image.open(pic_path)
                av = ctk.CTkImage(light_image=pil, dark_image=pil, size=(44, 44))
                self._img_refs.append(av)
                avatar_label.configure(image=av, text="", fg_color="transparent")
            except Exception:
                pass

            def _girar(ang=[90]):
                try:
                    if not ring.winfo_exists():
                        return
                    ang[0] = (ang[0] - 9) % 360
                    ring.itemconfigure(arc, start=ang[0])
                    ring.after(40, _girar)
                except Exception:
                    pass
            ring.after(40, _girar)

            # Nombre + correo CENTRADOS bajo el avatar
            name_label = ctk.CTkLabel(cont, text=name, font=("Segoe UI", 15, "bold"),
                                      text_color=self.TEXT)
            name_label.pack(pady=(8, 0))
            email_label = ctk.CTkLabel(cont, text=email, font=("Segoe UI", 11),
                                       text_color=self.MUTED)
            email_label.pack()
            self._login_dialog_name_label = name_label
            self._login_dialog_email_label = email_label

            status = ctk.CTkLabel(cont, text=status_text, font=("Segoe UI", 13),
                                  text_color=self.MUTED)
            status.pack(pady=(18, 0))

            # Barra de actividad continua (indeterminada) — sensación de avance real
            try:
                act = ctk.CTkProgressBar(cont, width=170, height=5, corner_radius=3,
                                         progress_color="#2563EB", fg_color="#E8EEF9",
                                         mode="indeterminate", indeterminate_speed=0.9)
                act.pack(pady=(14, 0))
                act.start()
            except Exception:
                pass

            dlg.lift()
            self._login_dialog = dlg
            self._login_dialog_status = status
            import time as _t
            self._dlg_shown_ts = _t.time()
            # El estado del login (lo escribe la lógica existente) se ve aquí.
            self.status_label = status
            self.withdraw()
            dlg.deiconify()
            self._bring_login_dialog_front()
            dlg.update()
            self.after(400, self._vigilar_login_dialog)
        except Exception:
            self._login_dialog = None
            self._login_dialog_status = None

    def _bring_login_dialog_front(self):
        """Mantiene visible la ventanita de entrada mientras carga el inicio."""
        if getattr(self, "_dlg_background", False):
            return  # fase navegador: no taparlo (el usuario escribe su correo)
        dlg = self._login_dialog
        try:
            if dlg is not None and dlg.winfo_exists():
                dlg.lift()
                try:
                    dlg.attributes("-topmost", True)
                except Exception:
                    pass
                try:
                    dlg.focus_force()
                except Exception:
                    pass
        except Exception:
            pass

    def _set_login_dialog_background(self, flag):
        """SOLO UX de la ventanita: mientras el usuario autoriza en el
        navegador (escribe su correo en Google), la ventanita se va al fondo
        para no estorbar; al volver el control a la app, regresa al frente.
        No cambia tiempos ni lógica del OAuth."""
        self._dlg_background = bool(flag)
        dlg = self._login_dialog
        try:
            if dlg is None or not dlg.winfo_exists():
                return
            if flag:
                try:
                    dlg.attributes("-topmost", False)
                except Exception:
                    pass
                dlg.lower()
            else:
                self._bring_login_dialog_front()
        except Exception:
            pass

    def _actualizar_logging_dialog(self, name=None, email=None, pic_path=None,
                                   status_text=None, bring_front=True):
        """Actualiza los datos visibles sin cerrar ni recrear el dialogo."""
        try:
            if name and self._login_dialog_name_label is not None:
                self._login_dialog_name_label.configure(text=name)
            if email and self._login_dialog_email_label is not None:
                self._login_dialog_email_label.configure(text=email)
            if status_text and self._login_dialog_status is not None:
                self._login_dialog_status.configure(text=status_text, text_color=self.MUTED)
            if pic_path and self._login_dialog_avatar_label is not None:
                try:
                    pil = Image.open(pic_path)
                    av = ctk.CTkImage(light_image=pil, dark_image=pil, size=(44, 44))
                    self._img_refs.append(av)
                    self._login_dialog_avatar_label.configure(
                        image=av, text="", fg_color="transparent")
                except Exception:
                    pass
            elif self._login_dialog_avatar_label is not None and (name or email):
                initial = (name or email).strip()[:1].upper() or "G"
                self._login_dialog_avatar_label.configure(text=initial)
            if bring_front:
                self._bring_login_dialog_front()
        except Exception:
            pass

    def _vigilar_login_dialog(self):
        """Si la lógica reporta un error en el diálogo, vuelve a la ventana
        principal para que el usuario reintente (solo visual)."""
        dlg = self._login_dialog
        if dlg is None:
            return
        try:
            if not dlg.winfo_exists():
                self._login_dialog = None
                return
            label = self._login_dialog_status or self.status_label
            txt = str(label.cget("text"))
            if any(k in txt.lower() for k in ("error", "expir", "bloque")):
                self._cerrar_logging_dialog(mensaje=txt)
                return
            self.after(400, self._vigilar_login_dialog)
        except Exception:
            pass

    def _cerrar_logging_dialog(self, mensaje=""):
        """Cierra el diálogo y restaura la ventana principal (p. ej. tras error)."""
        dlg = self._login_dialog
        self._dlg_background = False
        self._login_dialog = None
        self._login_dialog_status = None
        self._login_dialog_name_label = None
        self._login_dialog_email_label = None
        self._login_dialog_avatar_label = None
        try:
            if dlg is not None and dlg.winfo_exists():
                dlg.destroy()
        except Exception:
            pass
        try:
            self._center_window(self, 1000, 650)
            self.deiconify()
            self.lift()
            if self._main_status is not None and self._main_status.winfo_exists():
                self.status_label = self._main_status
                if mensaje:
                    self.status_label.configure(text=mensaje, text_color="#DC2626")
        except Exception:
            pass

    @staticmethod
    def _precargar_dashboard():
        """Pre-importa el dashboard en segundo plano (mientras se valida el
        token) para que al abrirlo no haya espacios en blanco."""
        try:
            import facesyncApp.dashboard  # noqa: F401
        except Exception:
            pass

    # ==========================================
    # LÓGICA DE AUTENTICACIÓN
    # ==========================================
    def _start_auth_thread(self):
        """Inicia la autenticación OAuth en un hilo separado."""
        # Ventanita visible TAMBIÉN al agregar cuenta nueva: acompaña la
        # pantalla de consentimiento de Google y se queda hasta entrar.
        self._mostrar_logging_dialog("Conectando con Google",
                                     "Autoriza el acceso en tu navegador…",
                                     status_text="Logging in...")
        # Mientras el usuario escribe su correo en el NAVEGADOR, la ventanita
        # no debe flotar encima; vuelve al frente cuando Google nos regresa.
        self._set_login_dialog_background(True)
        threading.Thread(target=self._precargar_dashboard, daemon=True).start()
        threading.Thread(target=self._login_logic, daemon=True).start()

    def _login_with_saved_account(self, email, name=None, email_display=None, pic_path=None):
        """Inicia sesión con una cuenta previamente guardada."""
        # Ventana "Logging in..." (boceto 3) + pre-carga del dashboard.
        self._mostrar_logging_dialog(name or email, email_display or email,
                                     pic_path or os.path.join(oauth_users_dir(), email, 'perfil.png'))
        threading.Thread(target=self._precargar_dashboard, daemon=True).start()
        self.status_label.configure(text="Logging in...", text_color=self.MUTED)
        threading.Thread(target=self._login_saved_logic, args=(email,), daemon=True).start()

    def _login_saved_logic(self, email):
        """Lógica para restaurar sesión desde token guardado."""
        users_dir = oauth_users_dir()
        ruta_token = os.path.join(users_dir, email, 'token.json')
        try:
            creds = Credentials.from_authorized_user_file(ruta_token)
            if creds and creds.valid:
                self._email_autenticado = email
                self.status_label.configure(text="Logging in...", text_color=self.MUTED)
                self.after(400, self._abrir_dashboard)
            elif creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(ruta_token, 'w') as token:
                    token.write(creds.to_json())
                self._email_autenticado = email
                self.status_label.configure(text="Logging in...", text_color=self.MUTED)
                self.after(400, self._abrir_dashboard)
            else:
                self.status_label.configure(text="La sesión expiró. Inicia sesión de nuevo.", text_color="#EF4444")
        except Exception as e:
            print(f"ERROR en _login_saved_logic: {type(e).__name__}: {e}")
            self.status_label.configure(text=f"Error al cargar sesión: {str(e)[:50]}", text_color="#EF4444")

    def _login_logic(self):
        """Lógica completa de OAuth: abre navegador, obtiene credenciales, guarda perfil."""
        # Se obtiene el directorio raíz (FaceSync) subiendo un nivel desde facesyncApp
        ruta_json = client_secret_path()
        users_dir = oauth_users_dir()
        os.makedirs(users_dir, exist_ok=True)

        if not os.path.exists(ruta_json):
            def show_error():
                try:
                    from CTkMessagebox import CTkMessagebox
                    CTkMessagebox(title="Error de Archivo", message="No se encontró el archivo 'client_secret.json'.\nPor favor, asegúrese de que el archivo exista en la ruta correcta.", icon="cancel")
                except ImportError:
                    import tkinter.messagebox
                    tkinter.messagebox.showerror("Error", "No se encontró el archivo 'client_secret.json'.")
                self.status_label.configure(text="Error: falta client_secret.json", text_color="#EF4444")
            self.after(0, show_error)
            return

        try:
            self.status_label.configure(text="Abriendo el navegador...", text_color="#3B82F6")
            # Si el usuario NO marca el permiso de Drive en la pantalla de
            # Google, el token vuelve con menos scopes y oauthlib lo trata como
            # error fatal ("Scope has changed"). Relajamos esa validación para
            # aceptar los permisos concedidos y avisar si faltó Drive.
            os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
            flow = InstalledAppFlow.from_client_secrets_file(ruta_json, SCOPES)
            creds = flow.run_local_server(port=0, prompt='select_account')
            # Google ya devolvió el control: la ventanita regresa al frente
            # para acompañar el resto del inicio de sesión (solo UX).
            self.after(0, self._set_login_dialog_background, False)

            if creds:
                self.after(0, lambda: self._mostrar_logging_dialog(
                    "Google", "Validando cuenta...", None, "Logging in..."))
                # Obtener email, nombre y foto de Google
                import urllib.request
                req = urllib.request.Request('https://www.googleapis.com/oauth2/v2/userinfo')
                req.add_header('Authorization', f'Bearer {creds.token}')

                name = ""
                picture_url = ""
                email = "unknown"
                try:
                    with urllib.request.urlopen(req) as response:
                        user_info = json.loads(response.read())
                        email = user_info.get('email', 'unknown')
                        name = user_info.get('name', '')
                        picture_url = user_info.get('picture', '')
                except Exception:
                    pass

                email_safe = _account_id("".join(c for c in email if c.isalnum() or c in "@.+-_"))
                ruta_usuario = os.path.join(users_dir, email_safe)
                os.makedirs(ruta_usuario, exist_ok=True)

                ruta_token = os.path.join(ruta_usuario, 'token.json')
                _write_private_text(Path(ruta_token), creds.to_json())

                # Generar archivo config.json básico
                config_data = {
                    "name": name,
                    "email": email,
                    "picture_url": picture_url,
                    "theme": "dark"
                }
                config_path = os.path.join(ruta_usuario, 'config.json')
                _write_private_text(Path(config_path), json.dumps(config_data, ensure_ascii=False, indent=4))

                # Descargar e inicializar avatar circular
                pic_path = None
                if picture_url:
                    pic_path = download_and_crop_avatar(picture_url, email_safe, size=128)

                if not pic_path:
                    fallback_img = generate_fallback_avatar(name if name else email, size=128)
                    pic_path = os.path.join(ruta_usuario, "perfil.png")
                    fallback_img.save(pic_path, "PNG")

                self.after(0, lambda n=(name or email), e=email, p=pic_path:
                           self._actualizar_logging_dialog(n, e, p, "Logging in..."))
                self._email_autenticado = email_safe
                # ¿Se concedió el permiso de Drive? (si no, la app funciona
                # igual; solo "Exportar a Drive" pedirá re-autorizar).
                scopes_ok = "drive.file" in " ".join(getattr(creds, "scopes", None) or [])
                if scopes_ok:
                    self.status_label.configure(text=f"✅ ¡Sesión de {email_safe} Exitosa!", text_color="#10B981")
                else:
                    self.status_label.configure(
                        text="✅ Sesión iniciada (sin permiso de Drive: marca esa casilla al reautorizar).",
                        text_color="#F59E0B")

                # Actualizamos la UI y abrimos dashboard
                self.after(500, self._load_accounts_ui)
                self.after(1000, self._abrir_dashboard)

        except Exception as e:
            error_str = str(e)
            print(f"ERROR en _login_logic: {type(e).__name__}: {error_str}")
            import traceback
            traceback.print_exc()

            # Si es un error de Google/OAuth, mostrar opción para continuar sin Drive
            if "403" in error_str or "access_denied" in error_str or "Forbidden" in error_str:
                self.status_label.configure(
                    text="⚠️ Google bloqueó el acceso. Usa la app en modo limitado.",
                    text_color="#F59E0B"
                )
                print("\n⚠️ SOLUCIÓN: Intenta de nuevo en unos minutos, o usa la app sin Google Drive por ahora")
            else:
                self.status_label.configure(text=f"Error: {error_str[:60]}", text_color="#EF4444")

    # ==========================================
    # TRANSICIÓN AL DASHBOARD
    # ==========================================
    def eliminar_usuario(self, email):
        """Elimina un usuario y todos sus datos locales."""
        # Crear ventana de confirmación
        confirm_window = ctk.CTkToplevel(self)
        confirm_window.title("Confirmar eliminación")
        set_windows_title_bar_light(confirm_window)
        self._center_window(confirm_window, 400, 210)
        confirm_window.resizable(False, False)
        confirm_window.configure(fg_color="#FFFFFF")
        confirm_window.grab_set()


        # Título
        ctk.CTkLabel(
            confirm_window,
            text="Eliminar cuenta",
            font=("Segoe UI", 18, "bold"),
            text_color="#DC2626"
        ).pack(pady=(20, 8))

        # Mensaje
        ctk.CTkLabel(
            confirm_window,
            text=f"¿Seguro que deseas eliminar esta cuenta\ny todos sus datos locales?\n\n{email}",
            font=("Segoe UI", 12),
            text_color=self.MUTED,
            justify="center"
        ).pack(pady=4)

        # Frame de botones
        btn_frame = ctk.CTkFrame(confirm_window, fg_color="transparent")
        btn_frame.pack(pady=18)

        # Botón Cancelar
        ctk.CTkButton(
            btn_frame, text="Cancelar", width=150, height=40, corner_radius=10,
            fg_color="transparent", hover_color=self.HOVER, border_width=1,
            border_color="#E5E7EB", text_color=self.TEXT, font=("Segoe UI", 12, "bold"),
            command=confirm_window.destroy
        ).pack(side="left", padx=10)

        # Botón Eliminar
        def confirmar_eliminacion():
            try:
                delete_saved_account(email)
                print(f"✓ Usuario {email} eliminado exitosamente")

                confirm_window.destroy()
                # Recargar la UI de cuentas
                self._load_accounts_ui()
            except Exception as e:
                print(f"❌ Error al eliminar usuario: {e}")
                confirm_window.destroy()
                self._load_accounts_ui()

        ctk.CTkButton(
            btn_frame, text="Eliminar", width=150, height=40, corner_radius=10,
            fg_color="#DC2626", hover_color="#991B1B",
            text_color="#FFFFFF", font=("Segoe UI", 12, "bold"),
            command=confirmar_eliminacion
        ).pack(side="left", padx=10)

    def _abrir_dashboard(self):
        """Destruye el login y abre el DashboardWindow con el email del usuario."""
        email = self._email_autenticado

        # Validación
        if not email:
            print("ERROR: email_autenticado es None")
            self.status_label.configure(text="Error: Email no disponible. Intenta de nuevo.", text_color="#EF4444")
            return

        try:
            print(f"DEBUG: Abriendo dashboard para {email}")
            try:
                self._actualizar_logging_dialog(status_text="Cargando inicio...")
            except Exception:
                pass
            # Importación diferida para evitar dependencia circular
            from facesyncApp.dashboard import DashboardWindow
            print(f"DEBUG: DashboardWindow importado correctamente")
            self.destroy()
            app = DashboardWindow(email_usuario=email)
            print(f"DEBUG: DashboardWindow instanciado correctamente para {email}")
            try:
                app.update_idletasks()
                app.lift()
                app.focus_force()
            except Exception:
                pass
            app.mainloop()
        except Exception as e:
            print(f"ERROR al abrir dashboard: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            try:
                if self.winfo_exists():
                    self._cerrar_logging_dialog(mensaje=f"Error al abrir inicio: {str(e)[:45]}")
                    return
            except Exception:
                pass
            # Recrear la ventana de login si algo falla
            from facesyncApp.login import FaceSyncLogin
            login_app = FaceSyncLogin()
            login_app.mainloop()
