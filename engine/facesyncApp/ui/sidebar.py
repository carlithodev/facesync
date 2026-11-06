"""
FaceSync AI — Sidebar de navegación (Fase 1).

Navegación lateral premium entre las 5 vistas. Es una capa visual: delega la
navegación al callback ``on_navigate(key)`` que le pasa el dashboard. No
contiene lógica de negocio, motor ni acceso a datos.

Ítems (Fase 1): Inicio · Workspace · Resumen semanal · Reportes · Exportaciones.
(No incluye "Revisión" ni "Configuración" por decisión de producto.)
"""

import os
import queue
import shutil
import threading

import customtkinter as ctk

from facesyncApp import BASE_DIR
from facesyncApp.ui import theme, icons

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None


class Sidebar(ctk.CTkFrame):

    # (key interno, etiqueta visible) — navegación minimalista, solo texto.
    NAV = [
        ("inicio",        "Inicio"),
        ("workspace",     "Workspace"),
        ("resumen",       "Resumen semanal"),
        ("reportes",      "Reportes"),
        ("exportaciones", "Exportaciones"),
    ]

    def __init__(self, parent, *, on_navigate, email="", username="", on_logout=None):
        super().__init__(
            parent, width=theme.SIDEBAR_WIDTH, fg_color=theme.BG_SIDEBAR,
            corner_radius=0, border_width=1, border_color=theme.BORDER,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)
        self._on_navigate = on_navigate
        self._on_logout = on_logout
        self._email = email or ""
        self._username = username or (email.split("@")[0] if email else "Usuario")
        self._items = {}
        self._active = None
        self._img_refs = []  # mantiene referencias para evitar GC de imágenes

        self._build_user()      # perfil ARRIBA (con margen)
        self._build_storage()   # barra de espacio del workspace (ABAJO)
        self._build_nav()       # nombres centrados al medio

    # ------------------------------------------------------------------
    # Navegación (solo texto, centrada)
    # ------------------------------------------------------------------
    def _build_nav(self):
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=10)
        # Bloque centrado verticalmente en el medio de la sidebar.
        nav = ctk.CTkFrame(outer, fg_color="transparent")
        nav.place(relx=0.5, rely=0.42, anchor="center", relwidth=1.0)
        for key, label in self.NAV:
            self._build_item(nav, key, label)

    def _build_item(self, parent, key, label):
        row = ctk.CTkFrame(parent, fg_color="transparent", height=44,
                           corner_radius=theme.RADIUS_MD)
        row.pack(fill="x", pady=4)
        row.pack_propagate(False)

        text_lbl = ctk.CTkLabel(row, text=label, font=theme.FONT_NAV,
                                text_color=theme.TEXT_SUB, anchor="center")
        text_lbl.pack(fill="both", expand=True)

        self._items[key] = {"row": row, "label": text_lbl}

        for w in (row, text_lbl):
            w.bind("<Button-1>", lambda e, k=key: self._on_navigate(k))
            w.bind("<Enter>", lambda e, k=key: self._on_hover(k, True))
            w.bind("<Leave>", lambda e, k=key: self._on_hover(k, False))
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

    def _on_hover(self, key, entering):
        if key == self._active:
            return
        it = self._items.get(key)
        if not it:
            return
        it["row"].configure(fg_color=theme.NAV_HOVER_BG if entering else "transparent")

    def set_active(self, key):
        """Marca visualmente el ítem activo (fondo y color; tipografía en bold)."""
        for k, it in self._items.items():
            active = (k == key)
            it["row"].configure(fg_color=theme.NAV_ACTIVE_BG if active else "transparent")
            it["label"].configure(
                text_color=theme.ACCENT_HOVER if active else theme.TEXT_SUB,
                font=(theme.FONT_FAMILY, 14, "bold") if active else theme.FONT_NAV)
        self._active = key

    # ------------------------------------------------------------------
    # Tarjeta de usuario (ARRIBA, con margen)
    # ------------------------------------------------------------------
    def _build_user(self):
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(side="top", fill="x", padx=14, pady=(18, 10))

        card = ctk.CTkFrame(wrap, fg_color=theme.CARD, corner_radius=theme.RADIUS_LG,
                            border_width=1, border_color=theme.BORDER, height=64)
        card.pack(fill="x")
        card.pack_propagate(False)

        avatar = self._load_avatar(40)
        if avatar is not None:
            lbl = ctk.CTkLabel(card, image=avatar, text="")
        else:
            lbl = ctk.CTkLabel(card, text="👤", font=(theme.FONT_FAMILY, 22))
        lbl.pack(side="left", padx=(10, 8), pady=12)

        # Botón de cerrar sesión (anclado a la derecha de la tarjeta)
        if self._on_logout is not None:
            png = icons.icon("salir", 16)
            btn = ctk.CTkButton(card, text="" if png is not None else "⏻",
                                image=png, width=30, height=30,
                                corner_radius=theme.RADIUS_SM, fg_color="transparent",
                                hover_color=theme.ELEVATED, text_color=theme.TEXT_SUB,
                                font=(theme.FONT_FAMILY, 16), command=self._on_logout)
            btn.pack(side="right", padx=(0, 10))

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, pady=10)
        # Nombres largos: elipsis para que no se corten contra el botón de salir
        nombre = self._username or ""
        if len(nombre) > 13:
            nombre = nombre[:12].rstrip() + "…"
        ctk.CTkLabel(info, text=nombre, font=(theme.FONT_FAMILY, 14, "bold"),
                     text_color=theme.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(info, text="Cuenta Pro", font=theme.FONT_SMALL,
                     text_color=theme.ACCENT, anchor="w").pack(anchor="w")

    # ------------------------------------------------------------------
    # Almacenamiento del workspace (abajo) — SOLO LECTURA, en worker
    # ------------------------------------------------------------------
    def _build_storage(self):
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(side="bottom", fill="x", padx=14, pady=(6, 16))
        card = ctk.CTkFrame(wrap, fg_color=theme.CARD, corner_radius=theme.RADIUS_LG,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x")

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 2))
        png = icons.icon("almacenamiento", 16)
        if png is not None:
            ctk.CTkLabel(top, image=png, text="").pack(side="left")
        ctk.CTkLabel(top, text=" Almacenamiento", font=(theme.FONT_FAMILY, 11, "bold"),
                     text_color=theme.TEXT_SUB).pack(side="left")

        self._st_bar = ctk.CTkProgressBar(card, height=6, corner_radius=3,
                                          progress_color=theme.ACCENT)
        self._st_bar.set(0)
        self._st_bar.pack(fill="x", padx=12, pady=(6, 4))
        self._st_lbl = ctk.CTkLabel(card, text="Calculando…", font=theme.FONT_TINY,
                                    text_color=theme.TEXT_MUTE, anchor="w")
        self._st_lbl.pack(fill="x", padx=12, pady=(0, 10))

        self._st_q = queue.Queue()
        threading.Thread(target=self._calc_storage_worker, daemon=True).start()
        self.after(200, self._poll_storage)

    def _calc_storage_worker(self):
        """Suma el tamaño de las carpetas del workspace (solo lectura)."""
        try:
            from facesyncApp.ui import report_data as rd
            roots = rd.workspace_roots(self._email)
            total = 0
            for root in roots:
                for cur, _dirs, files in os.walk(root):
                    for f in files:
                        try:
                            total += os.stat(os.path.join(cur, f)).st_size
                        except OSError:
                            pass
            disk = None
            if roots:
                try:
                    disk = shutil.disk_usage(roots[0])
                except OSError:
                    disk = None
            self._st_q.put((roots, total, disk))
        except Exception:
            self._st_q.put(([], 0, None))

    def _poll_storage(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            roots, total, disk = self._st_q.get_nowait()
        except queue.Empty:
            self.after(250, self._poll_storage)
            return
        try:
            if not roots:
                self._st_lbl.configure(text="Sin carpetas en el workspace")
                return
            gb = total / (1024 ** 3)
            txt = f"{gb:.1f} GB" if gb >= 0.1 else f"{total / (1024 ** 2):.0f} MB"
            if disk is not None:
                frac = min(1.0, total / max(1, disk.total))
                self._st_bar.set(max(0.04, frac))
                self._st_lbl.configure(
                    text=f"{txt} usados · disco de {disk.total / (1024 ** 3):.0f} GB")
            else:
                self._st_bar.set(0.04)
                self._st_lbl.configure(text=f"{txt} usados")
        except Exception:
            pass

    def _load_avatar(self, size):
        if not PILImage:
            return None
        try:
            from core.app_paths import default_app_data_root
            pic = str(default_app_data_root() / "usuarios" / self._email / "perfil.png")
            if os.path.exists(pic):
                pil = PILImage.open(pic)
            else:
                from facesyncApp.utils import generate_fallback_avatar
                pil = generate_fallback_avatar(self._username or self._email or "U", size=size)
            img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(size, size))
            self._img_refs.append(img)
            return img
        except Exception:
            return None
