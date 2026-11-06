"""
FaceSync AI — Vista Inicio (Fase 2).

Reproduce la imagen de referencia de Inicio:
  - Banner "Bienvenido a FaceSync AI" + slogan + rostro digital (glow).
  - 3 tarjetas: Fotos analizadas · Carpetas clasificadas · Exportaciones.
  - Actividad reciente.

Datos: se cargan en un worker (diferido) vía `home_data` (solo lectura) y se
cachean en la instancia, de modo que navegar Inicio<->Workspace NO recalcula
nada. Si un dato no existe, se muestra un estado vacío elegante (sin inventar
datos). No toca backend, motor, Drive, CR2 ni seguridad.
"""

import queue
import threading

import customtkinter as ctk

from facesyncApp.ui import theme, icons
from facesyncApp.ui.components import PremiumCard, Chip
from facesyncApp.ui.home_data import gather_home_summary, format_ts


class InicioView(ctk.CTkFrame):

    # (key, etiqueta, icono, color, caption_con_dato, caption_vacío)
    CARDS = [
        ("fotos_analizadas", "Fotos analizadas", "🖼️", theme.ACCENT,
         "fotos en caché de análisis", "Sin análisis todavía"),
        ("carpetas_clasificadas", "Carpetas clasificadas", "📁", theme.SUCCESS,
         "carpetas en tu salida ALUMNOS", "Sin clasificaciones todavía"),
        ("exportaciones", "Exportaciones", "☁️", theme.CYAN,
         "exportaciones registradas", "Sin registro de exportaciones"),
    ]

    def __init__(self, parent, *, email=""):
        super().__init__(parent, fg_color=theme.BG_CONTENT, corner_radius=0)
        self._email = email or ""
        self._loaded = False
        self._loading = False
        self._img_refs = []
        self._stat_value = {}
        self._stat_caption = {}
        self._result_q = queue.Queue()

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True, padx=4, pady=0)

        self._build_banner(self._scroll)
        self._build_cards(self._scroll)
        self._build_activity(self._scroll)

        # Carga diferida: la vista aparece al instante, los datos llegan luego.
        self.after(60, self._load_async)

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------
    def _build_banner(self, parent):
        banner = ctk.CTkFrame(parent, height=178, fg_color="transparent",
                              corner_radius=0)
        banner.pack(fill="x", padx=28, pady=(24, 8))
        banner.pack_propagate(False)
        self._banner = banner

        # Fondo degradado (se regenera al cambiar el ancho)

        # Rostro digital (derecha)
        face_pil = None
        if face_pil is not None:
            face_img = ctk.CTkImage(light_image=face_pil, dark_image=face_pil,
                                    size=(170, 170))
            self._img_refs.append(face_img)
            ctk.CTkLabel(banner, image=face_img, text="").place(
                relx=0.975, rely=0.5, anchor="e")
        elif False:
            ctk.CTkLabel(banner, text="🧠", font=(theme.FONT_FAMILY, 64),
                         text_color=theme.CYAN).place(relx=0.95, rely=0.5, anchor="e")

        # Texto (izquierda) sobre el degradado
        txt = ctk.CTkFrame(banner, fg_color=theme.CARD, corner_radius=14,
                           border_width=1, border_color=theme.BORDER)
        txt.place(x=0, rely=0.5, anchor="w", relwidth=0.62, relheight=0.9)
        inner = ctk.CTkFrame(txt, fg_color="transparent")
        inner.place(x=34, rely=0.5, anchor="w", relwidth=0.9)
        # Saludo personalizado con el nombre de la sesión (mismo formato que la
        # tarjeta de perfil: puntos/guiones bajos -> espacios, Título).
        user = (self._email.split("@")[0] if self._email else "") or "Usuario"
        user = user.replace(".", " ").replace("_", " ").strip().title() or "Usuario"
        title = ctk.CTkFrame(inner, fg_color="transparent")
        title.pack(fill="x", anchor="w")
        title.grid_columnconfigure(1, weight=1)
        name_size = 30 if len(user) <= 18 else 26 if len(user) <= 28 else 22
        ctk.CTkLabel(title, text="Bienvenido ", font=(theme.FONT_FAMILY, 30, "bold"),
                     text_color=theme.TEXT).grid(row=0, column=0, sticky="nw")
        user_label = ctk.CTkLabel(title, text=user, font=(theme.FONT_FAMILY, name_size, "bold"),
                                  text_color=theme.ACCENT, anchor="w", justify="left",
                                  wraplength=520)
        user_label.grid(row=0, column=1, sticky="new")
        title.bind(
            "<Configure>",
            lambda e, lbl=user_label: lbl.configure(wraplength=max(180, e.width - 210))
        )
        ctk.CTkLabel(inner, text="Organiza, clasifica y exporta tus fotos con inteligencia.",
                     font=theme.FONT_BODY, text_color=theme.TEXT_SUB).pack(
            anchor="w", pady=(6, 12))

        chips = ctk.CTkFrame(inner, fg_color="transparent")
        chips.pack(anchor="w")
        Chip(chips, text="● Motor: FaceSync Brain", color=theme.ELEVATED,
             text_color=theme.TEXT).pack(side="left", padx=(0, 8))
        Chip(chips, text="● Estado: Online", color=theme.ELEVATED,
             text_color=theme.SUCCESS).pack(side="left")

    # ------------------------------------------------------------------
    # Tarjetas de métricas
    # ------------------------------------------------------------------
    def _build_cards(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=28, pady=(12, 8))
        for i in range(3):
            row.grid_columnconfigure(i, weight=1, uniform="cards")
        for i, spec in enumerate(self.CARDS):
            self._build_stat_card(row, i, spec)

    def _build_stat_card(self, parent, col, spec):
        key, label, icon, color, _cap_ok, _cap_empty = spec
        card = PremiumCard(parent, hover=True, height=172)
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 16, 0))
        card.grid_propagate(False)
        card.pack_propagate(False)

        pad = ctk.CTkFrame(card, fg_color="transparent")
        pad.pack(fill="both", expand=True, padx=18, pady=16)

        top = ctk.CTkFrame(pad, fg_color="transparent")
        top.pack(fill="x")
        _png = icons.icon({"fotos_analizadas": "imagen",
                           "carpetas_clasificadas": "carpeta",
                           "exportaciones": "exportar"}.get(key), 26)
        if _png is not None:
            ctk.CTkLabel(top, image=_png, text="", fg_color="transparent",
                         width=34, height=34).pack(side="left")
        else:
            ctk.CTkLabel(top, text=icon, font=(theme.FONT_FAMILY, 18),
                         fg_color="transparent", width=34, height=34,
                         text_color=color).pack(side="left")
        ctk.CTkLabel(top, text=label, font=theme.FONT_H3,
                     text_color=theme.TEXT_SUB).pack(side="left", padx=(12, 0))

        value = ctk.CTkLabel(pad, text="…", font=theme.FONT_DISPLAY, text_color=theme.TEXT)
        value.pack(anchor="w", pady=(10, 0))
        self._stat_value[key] = value

        track = ctk.CTkFrame(pad, fg_color=theme.ELEVATED, height=4, corner_radius=2)
        track.pack(fill="x", pady=(8, 6))
        seg = ctk.CTkFrame(track, fg_color=color, height=4, width=70, corner_radius=2)
        seg.place(x=0, y=0)

        caption = ctk.CTkLabel(pad, text="Cargando…", font=theme.FONT_SMALL,
                               text_color=theme.TEXT_MUTE)
        caption.pack(anchor="w")
        self._stat_caption[key] = caption

    # ------------------------------------------------------------------
    # Actividad reciente
    # ------------------------------------------------------------------
    def _build_activity(self, parent):
        panel = PremiumCard(parent, fg_color=theme.CARD)
        panel.pack(fill="both", expand=True, padx=28, pady=(8, 24))
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(head, text="Actividad reciente", font=theme.FONT_H2,
                     text_color=theme.TEXT).pack(side="left")

        self._activity_body = ctk.CTkFrame(panel, fg_color="transparent")
        self._activity_body.pack(fill="both", expand=True, padx=20, pady=(4, 16))
        ctk.CTkLabel(self._activity_body, text="Cargando actividad…",
                     font=theme.FONT_SUB, text_color=theme.TEXT_MUTE).pack(
            anchor="w", pady=8)

    # ------------------------------------------------------------------
    # Carga diferida (worker) + aplicación de datos
    # ------------------------------------------------------------------
    def _load_async(self):
        if self._loaded or self._loading:
            return
        self._loading = True
        email = self._email

        def worker():
            try:
                data = gather_home_summary(email)
            except Exception:
                data = None
            self._result_q.put(data)   # thread-safe; el main thread lo recoge

        threading.Thread(target=worker, daemon=True).start()
        self._poll_result()

    def _poll_result(self):
        """Sondea el resultado del worker desde el hilo de UI (after es fiable
        en el main thread; llamar after() desde el worker no lo es)."""
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            data = self._result_q.get_nowait()
        except queue.Empty:
            self.after(80, self._poll_result)
            return
        self._apply(data)

    def _apply(self, data):
        self._loading = False
        self._loaded = True
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        data = data or {}
        self._apply_cards(data)
        self._apply_activity(data.get("actividad") or [])

    def _apply_cards(self, data):
        for key, label, icon, color, cap_ok, cap_empty in self.CARDS:
            vlabel = self._stat_value.get(key)
            clabel = self._stat_caption.get(key)
            if vlabel is None:
                continue
            val = data.get(key)
            if val is None:
                vlabel.configure(text="—", text_color=theme.TEXT_MUTE)
                if clabel:
                    clabel.configure(text=cap_empty, text_color=theme.TEXT_MUTE)
            else:
                vlabel.configure(text=f"{val:,}", text_color=theme.TEXT)
                if clabel:
                    clabel.configure(text=cap_ok, text_color=theme.TEXT_SUB)

    def _apply_activity(self, acts):
        for w in self._activity_body.winfo_children():
            w.destroy()

        if not acts:
            empty = ctk.CTkFrame(self._activity_body, fg_color="transparent")
            empty.pack(fill="both", expand=True, pady=18)
            ctk.CTkLabel(empty, text="🗂️", font=(theme.FONT_FAMILY, 30),
                         text_color=theme.TEXT_MUTE).pack()
            ctk.CTkLabel(empty, text="Aún no hay actividad reciente.",
                         font=theme.FONT_BODY, text_color=theme.TEXT_SUB).pack(pady=(8, 2))
            ctk.CTkLabel(empty, text="Empieza leyendo un Excel o clasificando en Workspace.",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE).pack()
            return

        dot_colors = [theme.SUCCESS, theme.ACCENT, theme.CYAN, theme.WARNING, theme.INFO]
        for i, a in enumerate(acts):
            self._activity_row(self._activity_body, a, dot_colors[i % len(dot_colors)])

    def _activity_row(self, parent, a, dot):
        row = ctk.CTkFrame(parent, fg_color="transparent", height=46)
        row.pack(fill="x", pady=3)
        row.pack_propagate(False)

        ctk.CTkLabel(row, text="●", text_color=dot, font=(theme.FONT_FAMILY, 12),
                     width=16).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(row, text=a.get("icon", "•"), font=(theme.FONT_FAMILY, 16),
                     fg_color="transparent",
                     width=30, height=36).pack(side="left", padx=(0, 12))

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(info, text=a.get("title", ""), font=theme.FONT_H3,
                     text_color=theme.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(info, text=a.get("subtitle", ""), font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB, anchor="w").pack(anchor="w")

        ts = format_ts(a.get("ts")) if a.get("ts") else ""
        ctk.CTkLabel(row, text=ts, font=theme.FONT_SMALL,
                     text_color=theme.TEXT_MUTE).pack(side="right", padx=(8, 4))
