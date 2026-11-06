"""
FaceSync AI — Vista Resumen semanal (Fase 4).

Header + selector de semana + 5 KPIs + actividad semanal (gráfica por día) +
distribución (donut) + carpetas con más movimiento (ranking).

Datos reales y baratos vía `week_data` (SOLO LECTURA): se escanea el disco UNA
vez en un worker y se cachea; cambiar de semana solo re-agrupa en memoria. Lo
que no existe (exportaciones, pendientes) se muestra como estado vacío "—".
No toca backend, motor, Drive, CR2 ni seguridad.
"""

import queue
import threading

import customtkinter as ctk

from facesyncApp.ui import theme
from facesyncApp.ui import week_data as wd
from facesyncApp.ui.components import PremiumCard, BarChart, DonutChart


class ResumenView(ctk.CTkFrame):

    DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    _DONUT_COLORS = [theme.ACCENT, theme.SUCCESS, theme.CYAN,
                     theme.WARNING, theme.INFO, "#A855F7"]

    def __init__(self, parent, *, email=""):
        super().__init__(parent, fg_color=theme.BG_CONTENT, corner_radius=0)
        self._email = email or ""
        self._loaded = False
        self._loading = False
        self._mtimes = []
        self._ranking = []
        self._carpetas_total = None
        self._week_offset = 0
        self._q = queue.Queue()
        self._kpi = {}  # key -> (value_label, caption_label)

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True, padx=4)

        self._build_header(self._scroll)
        self._build_weekbar(self._scroll)
        self._build_kpis(self._scroll)
        self._build_charts(self._scroll)

        self.after(60, self._load_async)

    # ---------------- Construcción ----------------
    def _build_header(self, parent):
        h = ctk.CTkFrame(parent, fg_color="transparent")
        h.pack(fill="x", padx=28, pady=(26, 2))
        ctk.CTkLabel(h, text="Resumen semanal", font=theme.FONT_H1,
                     text_color=theme.TEXT).pack(anchor="w")
        ctk.CTkLabel(h, text="Organiza, clasifica y controla el avance de tu semana.",
                     font=theme.FONT_SUB, text_color=theme.TEXT_SUB).pack(anchor="w", pady=(4, 0))

    def _build_weekbar(self, parent):
        bar = PremiumCard(parent, fg_color=theme.CARD, height=58)
        bar.pack(fill="x", padx=28, pady=(16, 6))
        bar.pack_propagate(False)
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(expand=True)
        btn = {"width": 34, "height": 34, "corner_radius": theme.RADIUS_MD,
               "fg_color": theme.ELEVATED, "hover_color": theme.ACCENT,
               "font": (theme.FONT_FAMILY, 14)}
        ctk.CTkButton(inner, text="‹", command=lambda: self._change_week(-1), **btn).pack(side="left", padx=6)
        ctk.CTkLabel(inner, text="📅", font=(theme.FONT_FAMILY, 16)).pack(side="left", padx=(8, 6))
        self._week_lbl = ctk.CTkLabel(inner, text=wd.week_label(0),
                                      font=theme.FONT_H3, text_color=theme.TEXT)
        self._week_lbl.pack(side="left", padx=6)
        ctk.CTkButton(inner, text="›", command=lambda: self._change_week(1), **btn).pack(side="left", padx=6)

    def _build_kpis(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=28, pady=(8, 4))
        specs = [
            ("fotos", "Fotos analizadas", theme.ACCENT),
            ("carpetas", "Carpetas clasificadas", theme.SUCCESS),
            ("export", "Exportaciones", theme.CYAN),
            ("pend", "Pendientes de revisión", theme.WARNING),
            ("rend", "Rendimiento semanal", theme.INFO),
        ]
        for i in range(len(specs)):
            row.grid_columnconfigure(i, weight=1, uniform="kpi")
        for i, (key, label, color) in enumerate(specs):
            self._kpi_card(row, i, key, label, color)

    def _kpi_card(self, parent, col, key, label, color):
        card = PremiumCard(parent, hover=True, height=110)
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 12, 0))
        card.grid_propagate(False)
        card.pack_propagate(False)
        pad = ctk.CTkFrame(card, fg_color="transparent")
        pad.pack(fill="both", expand=True, padx=14, pady=12)
        ctk.CTkLabel(pad, text=label, font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                     anchor="w", wraplength=150, justify="left").pack(anchor="w")
        val = ctk.CTkLabel(pad, text="…", font=theme.FONT_H1, text_color=color)
        val.pack(anchor="w", pady=(6, 0))
        cap = ctk.CTkLabel(pad, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE)
        cap.pack(anchor="w")
        self._kpi[key] = (val, cap)

    def _build_charts(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=28, pady=(10, 24))
        row.grid_columnconfigure(0, weight=2, uniform="ch")
        row.grid_columnconfigure(1, weight=1, uniform="ch")
        row.grid_columnconfigure(2, weight=2, uniform="ch")
        row.grid_rowconfigure(0, weight=1)

        # Responsive: en pantallas chicas los títulos se cortaban; el texto se
        # envuelve según el ancho REAL de cada tarjeta.
        def _fit(lbl, card):
            card.bind("<Configure>",
                      lambda e, l=lbl: l.configure(wraplength=max(90, e.width - 36)),
                      add="+")

        # Actividad semanal
        act = PremiumCard(row, fg_color=theme.CARD)
        act.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        t1 = ctk.CTkLabel(act, text="Actividad semanal", font=theme.FONT_H3,
                          text_color=theme.TEXT, justify="left")
        t1.pack(anchor="w", padx=18, pady=(16, 2))
        _fit(t1, act)
        ctk.CTkLabel(act, text="Fotos analizadas por día", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB).pack(anchor="w", padx=18)
        self._bar = BarChart(act, self.DIAS, height=200)
        self._bar.pack(fill="both", expand=True, padx=14, pady=12)

        # Distribución (donut)
        dist = PremiumCard(row, fg_color=theme.CARD)
        dist.grid(row=0, column=1, sticky="nsew", padx=(0, 14))
        t2 = ctk.CTkLabel(dist, text="Distribución del trabajo", font=theme.FONT_H3,
                          text_color=theme.TEXT, justify="left")
        t2.pack(anchor="w", padx=18, pady=(16, 2))
        _fit(t2, dist)
        t2b = ctk.CTkLabel(dist, text="Por carpeta de clasificación", font=theme.FONT_SMALL,
                           text_color=theme.TEXT_SUB, justify="left")
        t2b.pack(anchor="w", padx=18)
        _fit(t2b, dist)
        self._donut = DonutChart(dist, height=200)
        self._donut.pack(fill="both", expand=True, padx=14, pady=12)

        # Carpetas con más movimiento
        rank = PremiumCard(row, fg_color=theme.CARD)
        rank.grid(row=0, column=2, sticky="nsew")
        t3 = ctk.CTkLabel(rank, text="Carpetas con más movimiento", font=theme.FONT_H3,
                          text_color=theme.TEXT, justify="left")
        t3.pack(anchor="w", padx=18, pady=(16, 2))
        _fit(t3, rank)
        ctk.CTkLabel(rank, text="Por cantidad de archivos", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB).pack(anchor="w", padx=18)
        self._rank_body = ctk.CTkFrame(rank, fg_color="transparent")
        self._rank_body.pack(fill="both", expand=True, padx=18, pady=(10, 14))
        ctk.CTkLabel(self._rank_body, text="Cargando…", font=theme.FONT_SUB,
                     text_color=theme.TEXT_MUTE).pack(anchor="w")

    # ---------------- Carga diferida ----------------
    def _load_async(self):
        if self._loaded or self._loading:
            return
        self._loading = True
        email = self._email

        def worker():
            try:
                data = {"mtimes": wd.scan_mtimes(),
                        "ranking": wd.folder_ranking(email, top=5)}
            except Exception:
                data = None
            self._q.put(data)

        threading.Thread(target=worker, daemon=True).start()
        self._poll()

    def _poll(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            data = self._q.get_nowait()
        except queue.Empty:
            self.after(80, self._poll)
            return
        self._apply(data or {})

    def _apply(self, data):
        self._loading = False
        self._loaded = True
        self._mtimes = data.get("mtimes") or []
        self._ranking = data.get("ranking") or []
        self._carpetas_total = len(self._ranking) if self._ranking else None
        self._apply_static()
        self._refresh_week()

    def _apply_static(self):
        # KPIs no dependientes de la semana
        self._set_kpi("carpetas",
                      self._carpetas_total if self._carpetas_total else None,
                      "carpetas en ALUMNOS", "Sin clasificaciones")
        self._set_kpi("export", None, "", "Sin registro")
        self._set_kpi("pend", None, "", "Sin datos de pendientes")

        # Donut por carpeta
        donut = [(r["nombre"], r["count"], self._DONUT_COLORS[i % len(self._DONUT_COLORS)])
                 for i, r in enumerate(self._ranking) if r["count"] > 0]
        self._donut.set_data(donut)

        # Ranking
        for w in self._rank_body.winfo_children():
            w.destroy()
        if not self._ranking:
            ctk.CTkLabel(self._rank_body, text="Sin carpetas de clasificación todavía.",
                         font=theme.FONT_SUB, text_color=theme.TEXT_MUTE,
                         wraplength=240, justify="left").pack(anchor="w", pady=6)
            return
        mx = max((r["count"] for r in self._ranking), default=1) or 1
        for i, r in enumerate(self._ranking):
            self._rank_row(i, r, mx)

    def _rank_row(self, i, r, mx):
        row = ctk.CTkFrame(self._rank_body, fg_color="transparent")
        row.pack(fill="x", pady=5)
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x")
        nombre = r["nombre"]
        if len(nombre) > 22:
            nombre = nombre[:21] + "…"
        ctk.CTkLabel(top, text=f"{i + 1}. {nombre}", font=theme.FONT_SMALL,
                     text_color=theme.TEXT, anchor="w").pack(side="left")
        ctk.CTkLabel(top, text=f"{r['count']:,}", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB).pack(side="right")
        bar = ctk.CTkProgressBar(row, height=6, corner_radius=3, progress_color=theme.ACCENT)
        bar.set(r["count"] / mx if mx else 0)
        bar.pack(fill="x", pady=(4, 0))

    # ---------------- Semana ----------------
    def _change_week(self, d):
        self._week_offset += d
        self._refresh_week()

    def _refresh_week(self):
        off = self._week_offset
        self._week_lbl.configure(text=wd.week_label(off))
        if not self._loaded:
            return
        days = wd.bucket_week(self._mtimes, off)
        self._bar.set_values(days)
        total = sum(days)
        self._set_kpi("fotos", total if total else 0, "esta semana", "esta semana")

        prev = sum(wd.bucket_week(self._mtimes, off - 1))
        if prev > 0:
            pct = round((total - prev) / prev * 100)
            self._set_kpi("rend", f"{pct:+d}%", "vs. semana anterior", "")
        elif total > 0:
            self._set_kpi("rend", "+100%", "vs. semana anterior", "")
        else:
            self._set_kpi("rend", None, "", "Sin datos suficientes")

    def _set_kpi(self, key, value, cap_ok, cap_empty):
        pair = self._kpi.get(key)
        if not pair:
            return
        val, cap = pair
        if value is None:
            val.configure(text="—", text_color=theme.TEXT_MUTE)
            cap.configure(text=cap_empty)
        else:
            txt = f"{value:,}" if isinstance(value, int) else str(value)
            val.configure(text=txt)
            cap.configure(text=cap_ok)
