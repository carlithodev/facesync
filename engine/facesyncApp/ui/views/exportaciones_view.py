"""
FaceSync AI — Vista Exportaciones (Fase 6).

Header + filtros + 3 cards + Paquetes recientes + Historial de exportaciones +
panel de detalle. IMPORTANTE: el backend de Drive NO persiste un historial de
exportaciones, así que (honestamente) la lista llega vacía y se muestra estado
vacío elegante, sin inventar números. La acción real "Nueva exportación" /
"Exportar a Drive" abre el modal de Drive existente (backend, no se toca).

Estructura lista para datos reales: carga en worker + queue + after, lista
cacheada, tabla paginada y detalle diferido (cuando exista un origen persistido).
"""

import queue
import threading

import customtkinter as ctk

from facesyncApp.ui import theme, icons
from facesyncApp.ui.components import PremiumCard
from facesyncApp.ui import report_data as rd


def _gather(email):
    """Exportaciones persistidas por la UI al terminar cada export a Drive
    (report_data.list_exports, SOLO LECTURA)."""
    return {"list": rd.list_exports(email)}


class ExportacionesView(ctk.CTkFrame):

    PAGE = 8

    def __init__(self, parent, *, email="", on_export=None):
        super().__init__(parent, fg_color=theme.BG_CONTENT, corner_radius=0)
        self._email = email or ""
        self._on_export = on_export
        self._loaded = self._loading = False
        self._all = []
        self._filtered = []
        self._page = 0
        self._sel = None
        self._q = queue.Queue()
        self._cards = {}
        self._f_tipo = "Todos"
        self._f_fecha = "Todas las fechas"

        s = ctk.CTkScrollableFrame(self, fg_color="transparent")
        s.pack(fill="both", expand=True, padx=4)
        self._build_header(s)
        self._build_filters(s)
        self._build_cards(s)
        self._build_main(s)
        self.after(60, self._load)

    # ---------------- build ----------------
    def _build_header(self, p):
        h = ctk.CTkFrame(p, fg_color="transparent")
        h.pack(fill="x", padx=28, pady=(26, 2))
        ctk.CTkLabel(h, text="Exportaciones", font=theme.FONT_H1,
                     text_color=theme.TEXT).pack(anchor="w")
        ctk.CTkLabel(h, text="Gestiona y realiza el seguimiento de todas tus exportaciones.",
                     font=theme.FONT_SUB, text_color=theme.TEXT_SUB).pack(anchor="w", pady=(4, 0))

    def _build_filters(self, p):
        f = ctk.CTkFrame(p, fg_color="transparent")
        f.pack(fill="x", padx=28, pady=(14, 4))
        self._om_fecha = ctk.CTkOptionMenu(
            f, values=["Todas las fechas", "Hoy", "Últimos 7 días", "Últimos 30 días"],
            width=170, height=36, corner_radius=theme.RADIUS_MD, fg_color=theme.CARD,
            button_color=theme.ELEVATED, button_hover_color=theme.ACCENT,
            command=lambda v: (setattr(self, "_f_fecha", v), self._apply_filters()))
        self._om_fecha.pack(side="left", padx=(0, 8))
        self._om_tipo = ctk.CTkOptionMenu(f, values=["Todos", "Drive", "Local"],
                                          width=130, height=36, corner_radius=theme.RADIUS_MD,
                                          fg_color=theme.CARD, button_color=theme.ELEVATED,
                                          button_hover_color=theme.ACCENT,
                                          command=lambda v: setattr(self, "_f_tipo", v))
        self._om_tipo.pack(side="left", padx=8)
        self._search = ctk.CTkEntry(f, placeholder_text="Buscar paquete o carpeta…",
                                    width=220, height=36, corner_radius=theme.RADIUS_MD,
                                    fg_color=theme.CARD, border_color=theme.BORDER)
        self._search.pack(side="left", padx=8)
        ctk.CTkButton(f, text="Filtrar", height=36, width=90, corner_radius=theme.RADIUS_MD,
                      **theme.BTN_GHOST,
                      command=self._apply_filters).pack(side="left", padx=8)
        ctk.CTkButton(f, text=" Nueva exportación", height=36, corner_radius=theme.RADIUS_MD,
                      image=icons.icon("agregar_exportacion", 16), compound="left",
                      font=(theme.FONT_FAMILY, 13, "bold"), **theme.BTN_PRIMARY,
                      command=self._exportar).pack(side="right")

    def _build_cards(self, p):
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=28, pady=(8, 4))
        specs = [("done", "Exportaciones completadas", theme.SUCCESS),
                 ("files", "Archivos exportados", theme.ACCENT),
                 ("drive", "Exportaciones a Drive", theme.CYAN)]
        for i in range(3):
            row.grid_columnconfigure(i, weight=1, uniform="ec")
        for i, (k, label, color) in enumerate(specs):
            c = PremiumCard(row, hover=True, height=104)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 14, 0))
            c.grid_propagate(False)
            c.pack_propagate(False)
            pad = ctk.CTkFrame(c, fg_color="transparent")
            pad.pack(fill="both", expand=True, padx=16, pady=14)
            ctk.CTkLabel(pad, text=label, font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SUB).pack(anchor="w")
            v = ctk.CTkLabel(pad, text="…", font=theme.FONT_H1, text_color=color)
            v.pack(anchor="w", pady=(6, 0))
            self._cards[k] = v

    def _build_main(self, p):
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=28, pady=(8, 24))
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, minsize=320)
        row.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))

        paq = PremiumCard(left, fg_color=theme.CARD)
        paq.pack(fill="both", expand=True)
        ctk.CTkLabel(paq, text="Paquetes recientes", font=theme.FONT_H3,
                     text_color=theme.TEXT).pack(anchor="w", padx=18, pady=(16, 6))
        self._tbody = ctk.CTkFrame(paq, fg_color="transparent")
        self._tbody.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self._pag = ctk.CTkFrame(paq, fg_color="transparent")
        self._pag.pack(fill="x", padx=18, pady=(0, 14))

        hist = PremiumCard(left, fg_color=theme.CARD)
        hist.pack(fill="x", pady=(14, 0))
        ctk.CTkLabel(hist, text="Historial de exportaciones", font=theme.FONT_H3,
                     text_color=theme.TEXT).pack(anchor="w", padx=18, pady=(16, 6))
        self._hist = ctk.CTkFrame(hist, fg_color="transparent")
        self._hist.pack(fill="x", padx=18, pady=(0, 16))

        det = PremiumCard(row, fg_color=theme.CARD)
        det.grid(row=0, column=1, sticky="nsew")
        det.grid_propagate(False)
        ctk.CTkLabel(det, text="Detalle de exportación", font=theme.FONT_H3,
                     text_color=theme.TEXT).pack(anchor="w", padx=18, pady=(16, 6))
        self._det = ctk.CTkFrame(det, fg_color="transparent")
        self._det.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self._show_detail_empty()

    # ---------------- data ----------------
    def _load(self):
        if self._loaded or self._loading:
            return
        self._loading = True
        email = self._email

        def worker():
            try:
                data = _gather(email)
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
        self._all = data.get("list") or []
        self._filtered = list(self._all)
        done = sum(1 for r in self._all if r.get("estado") == "Completado")
        files = sum(int(r.get("subidos") or 0) for r in self._all)
        drive = sum(1 for r in self._all if r.get("tipo") == "Drive")
        for k, n, color in (("done", done, theme.SUCCESS),
                            ("files", files, theme.ACCENT),
                            ("drive", drive, theme.CYAN)):
            self._cards[k].configure(text=(f"{n:,}" if n else "—"),
                                     text_color=color if n else theme.TEXT_MUTE)
        self._render_table()
        self._render_hist()

    def _apply_filters(self):
        q = (self._search.get() or "").strip().lower()
        cutoff = self._date_cutoff()
        self._filtered = [r for r in self._all
                          if (self._f_tipo == "Todos" or r.get("tipo") == self._f_tipo)
                          and (not q or q in r.get("nombre", "").lower())
                          and (r.get("ts", 0) >= cutoff)]
        self._page = 0
        self._render_table()

    def _date_cutoff(self):
        """Epoch mínimo según el filtro de fechas (0 = sin filtro). Hoy no hay
        historial persistido de exportaciones; el filtro queda listo para cuando
        lo haya y, mientras tanto, la lista permanece vacía (estado honesto)."""
        import time
        from datetime import datetime
        f = self._f_fecha
        if f == "Hoy":
            return datetime.now().replace(hour=0, minute=0, second=0,
                                          microsecond=0).timestamp()
        if f == "Últimos 7 días":
            return time.time() - 7 * 86400
        if f == "Últimos 30 días":
            return time.time() - 30 * 86400
        return 0.0

    # ---------------- render ----------------
    def _empty(self, parent, icon, title, sub):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.pack(expand=True, fill="both", pady=24)
        ctk.CTkLabel(box, text=icon, font=(theme.FONT_FAMILY, 34),
                     text_color=theme.TEXT_MUTE).pack()
        ctk.CTkLabel(box, text=title, font=theme.FONT_BODY,
                     text_color=theme.TEXT_SUB).pack(pady=(8, 2))
        ctk.CTkLabel(box, text=sub, font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE,
                     wraplength=360, justify="center").pack()

    def _render_table(self):
        for w in self._tbody.winfo_children():
            w.destroy()
        for w in self._pag.winfo_children():
            w.destroy()
        if not self._filtered:
            self._empty(self._tbody, "📦", "Aún no hay paquetes de exportación.",
                        "Crea uno con “Nueva exportación”. El historial aparecerá aquí.")
            return
        start = self._page * self.PAGE
        for r in self._filtered[start:start + self.PAGE]:
            self._row(r)
        total = len(self._filtered)
        n_pages = (total - 1) // self.PAGE + 1
        ctk.CTkLabel(self._pag, text=f"Mostrando {start + 1}-{min(start + self.PAGE, total)} de {total}",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE).pack(side="left")
        nav = {"width": 30, "height": 28, "corner_radius": theme.RADIUS_SM,
               "fg_color": theme.ELEVATED, "hover_color": theme.ACCENT}
        ctk.CTkButton(self._pag, text="›", command=self._next, **nav).pack(side="right", padx=(4, 0))
        ctk.CTkLabel(self._pag, text=f"{self._page + 1}/{n_pages}", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB).pack(side="right", padx=6)
        ctk.CTkButton(self._pag, text="‹", command=self._prev, **nav).pack(side="right")

    def _render_hist(self):
        for w in self._hist.winfo_children():
            w.destroy()
        if not self._all:
            self._empty(self._hist, "🕓", "Sin exportaciones recientes.",
                        "Tus últimas exportaciones se mostrarán aquí.")
            return
        for r in self._all[:5]:
            f = ctk.CTkFrame(self._hist, fg_color="transparent")
            f.pack(fill="x", pady=2)
            ok = r.get("estado") == "Completado"
            ctk.CTkLabel(f, text=("●" if ok else "▲"), font=theme.FONT_SMALL,
                         text_color=theme.SUCCESS if ok else theme.WARNING).pack(side="left")
            ctk.CTkLabel(f, text=f" {r.get('nombre', '—')} · {r.get('fecha', '')}",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_SUB).pack(side="left")
            subs = r.get("subidos")
            if subs:
                ctk.CTkLabel(f, text=f"{subs:,} archivos", font=theme.FONT_SMALL,
                             text_color=theme.TEXT_MUTE).pack(side="right")

    def _row(self, r):
        row = ctk.CTkFrame(self._tbody, fg_color="transparent",
                           corner_radius=theme.RADIUS_SM, height=44)
        row.pack(fill="x", pady=2)
        row.pack_propagate(False)
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=10)
        ctk.CTkLabel(info, text=r.get("nombre", "—"), font=(theme.FONT_FAMILY, 12, "bold"),
                     text_color=theme.TEXT, anchor="w").pack(anchor="w", pady=(4, 0))
        ctk.CTkLabel(info, text=f"{r.get('tipo', '—')} · {r.get('fecha', '')}",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE,
                     anchor="w").pack(anchor="w")
        ok = r.get("estado") == "Completado"
        ctk.CTkLabel(row, text=("● " + r.get("estado", "—")), font=theme.FONT_SMALL,
                     text_color=theme.SUCCESS if ok else theme.WARNING
                     ).pack(side="left", padx=10)
        ctk.CTkLabel(row, text="Ver  ›", font=theme.FONT_SMALL,
                     text_color=theme.ACCENT).pack(side="right", padx=12)

        def _bind(w):
            w.bind("<Button-1>", lambda e, rr=r: self._select(rr))
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
            for c in w.winfo_children():
                _bind(c)

        _bind(row)

    def _next(self):
        if (self._page + 1) * self.PAGE < len(self._filtered):
            self._page += 1
            self._render_table()

    def _prev(self):
        if self._page > 0:
            self._page -= 1
            self._render_table()

    # ---------------- detalle ----------------
    def _select(self, r):
        self._sel = r
        self._show_detail(r)

    def _show_detail_empty(self):
        for w in self._det.winfo_children():
            w.destroy()
        box = ctk.CTkFrame(self._det, fg_color="transparent")
        box.pack(expand=True, fill="both", pady=20)
        ctk.CTkLabel(box, text="📤", font=(theme.FONT_FAMILY, 34),
                     text_color=theme.TEXT_MUTE).pack()
        ctk.CTkLabel(box, text="Selecciona un paquete", font=theme.FONT_BODY,
                     text_color=theme.TEXT_SUB).pack(pady=(8, 2))
        ctk.CTkLabel(box, text="Verás aquí su detalle.", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_MUTE).pack()
        acts = ctk.CTkFrame(self._det, fg_color="transparent")
        acts.pack(fill="x", side="bottom")
        ctk.CTkButton(acts, text=" Exportar a Drive", height=40, corner_radius=theme.RADIUS_MD,
                      image=icons.icon("drive", 16), compound="left",
                      font=(theme.FONT_FAMILY, 13, "bold"), **theme.BTN_PRIMARY,
                      command=self._exportar).pack(fill="x")

    def _show_detail(self, r):
        for w in self._det.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._det, text=r.get("nombre", "—"), font=theme.FONT_H3,
                     text_color=theme.TEXT, wraplength=280, justify="left").pack(anchor="w")

        def field(label, value):
            f = ctk.CTkFrame(self._det, fg_color="transparent")
            f.pack(fill="x", pady=3)
            ctk.CTkLabel(f, text=label, font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTE).pack(side="left")
            ctk.CTkLabel(f, text=str(value), font=theme.FONT_SMALL,
                         text_color=theme.TEXT).pack(side="right")

        field("Carpeta origen", r.get("origen", "—"))
        field("Carpeta destino", r.get("destino", "—"))
        field("Total de archivos", r.get("total", "—"))
        field("Fecha", r.get("fecha", "—"))
        field("Estado", r.get("estado", "—"))
        field("Tipo de exportación", r.get("tipo", "—"))

        acts = ctk.CTkFrame(self._det, fg_color="transparent")
        acts.pack(fill="x", pady=(16, 0))
        ctk.CTkButton(acts, text=" Exportar a Drive", height=40, corner_radius=theme.RADIUS_MD,
                      image=icons.icon("drive", 16), compound="left",
                      font=(theme.FONT_FAMILY, 13, "bold"), **theme.BTN_PRIMARY,
                      command=self._exportar).pack(fill="x", pady=(0, 8))
        ctk.CTkButton(acts, text=" Abrir carpeta local", height=40, corner_radius=theme.RADIUS_MD,
                      image=icons.icon("carpeta", 16), compound="left", **theme.BTN_GHOST,
                      command=lambda rr=r: self._abrir_origen(rr)).pack(fill="x")

    def _abrir_origen(self, r):
        import os as _os
        path = (r or {}).get("origen") or ""
        if path and _os.path.isdir(path):
            try:
                _os.startfile(path)  # noqa
                return
            except Exception:
                pass
        self._toast("No hay carpeta local asociada a este paquete.")

    # ---------------- acciones ----------------
    def _exportar(self):
        if callable(self._on_export):
            try:
                self._on_export()
                return
            except Exception:
                pass
        self._toast("Exportar a Drive no está disponible ahora mismo.")

    def _toast(self, msg, ms=3200):
        try:
            old = getattr(self, "_tw", None)
            if old is not None and old.winfo_exists():
                old.destroy()
        except Exception:
            pass
        t = ctk.CTkFrame(self, fg_color=theme.ELEVATED, corner_radius=theme.RADIUS_MD,
                         border_width=1, border_color=theme.ACCENT)
        ctk.CTkLabel(t, text=msg, font=theme.FONT_SUB, text_color=theme.TEXT,
                     wraplength=440, justify="left").pack(padx=14, pady=10)
        t.place(relx=0.5, rely=0.96, anchor="s")
        self._tw = t
        self.after(ms, lambda: t.destroy() if t.winfo_exists() else None)
