"""
FaceSync AI — Vista Reportes (Fase 5).

Header + filtros + 3 cards + lista de reportes recientes (paginada) + panel de
detalle del reporte seleccionado + formatos disponibles. Datos reales vía
`report_data` (SOLO LECTURA): la lista se carga en un worker y se cachea; el
detalle se lee de forma diferida solo del reporte seleccionado. Si no hay
reportes, estado vacío elegante. No toca backend/motor/Drive/seguridad.
"""

import os
import queue
import shutil
import threading
from tkinter import filedialog

import customtkinter as ctk

from facesyncApp.ui import theme, icons
from facesyncApp.ui.components import PremiumCard, Chip
from facesyncApp.ui import report_data as rd


class ReportesView(ctk.CTkFrame):

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
        self._dq = queue.Queue()
        self._cards = {}
        self._f_tipo = "Todos"
        self._f_carpeta = "Todos"
        self._f_fecha = "Todas las fechas"

        s = ctk.CTkScrollableFrame(self, fg_color="transparent")
        s.pack(fill="both", expand=True, padx=4)
        self._build_header(s)
        self._build_filters(s)
        self._build_cards(s)
        self._build_main(s)
        self._build_formats(s)
        self.after(60, self._load)

    # ---------------- build ----------------
    def _build_header(self, p):
        h = ctk.CTkFrame(p, fg_color="transparent")
        h.pack(fill="x", padx=28, pady=(26, 2))
        ctk.CTkLabel(h, text="Reportes", font=theme.FONT_H1,
                     text_color=theme.TEXT).pack(anchor="w")
        ctk.CTkLabel(h, text="Consulta, filtra y exporta los resultados generados por FaceSync AI.",
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
        self._om_tipo = ctk.CTkOptionMenu(f, values=["Todos", "Excel", "JSON", "TXT"],
                                          width=130, height=36, corner_radius=theme.RADIUS_MD,
                                          fg_color=theme.CARD, button_color=theme.ELEVATED,
                                          button_hover_color=theme.ACCENT,
                                          command=lambda v: self._set("_f_tipo", v))
        self._om_tipo.pack(side="left", padx=8)
        self._om_carp = ctk.CTkOptionMenu(f, values=["Todos"], width=160, height=36,
                                          corner_radius=theme.RADIUS_MD, fg_color=theme.CARD,
                                          button_color=theme.ELEVATED, button_hover_color=theme.ACCENT,
                                          command=lambda v: self._set("_f_carpeta", v))
        self._om_carp.pack(side="left", padx=8)
        ctk.CTkButton(f, text="Filtrar", height=36, width=90, corner_radius=theme.RADIUS_MD,
                      **theme.BTN_GHOST,
                      command=self._apply_filters).pack(side="left", padx=8)
        # ("Generar reporte" se retiró: los reportes aparecen SOLOS al terminar
        #  cada clasificación; esta vista solo los lista/abre/descarga.)

    def _build_cards(self, p):
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=28, pady=(8, 4))
        specs = [("gen", "Reportes generados", theme.ACCENT),
                 ("exp", "Exportaciones completas", theme.CYAN),
                 ("clf", "Fotos clasificadas", theme.SUCCESS)]
        for i in range(3):
            row.grid_columnconfigure(i, weight=1, uniform="rc")
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
        row.pack(fill="both", expand=True, padx=28, pady=(8, 6))
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, minsize=320)
        row.grid_rowconfigure(0, weight=1)

        # tabla
        tbl = PremiumCard(row, fg_color=theme.CARD)
        tbl.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        ctk.CTkLabel(tbl, text="Reportes recientes", font=theme.FONT_H3,
                     text_color=theme.TEXT).pack(anchor="w", padx=18, pady=(16, 6))
        self._tbody = ctk.CTkFrame(tbl, fg_color="transparent")
        self._tbody.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self._pag = ctk.CTkFrame(tbl, fg_color="transparent")
        self._pag.pack(fill="x", padx=18, pady=(0, 14))

        # detalle
        det = PremiumCard(row, fg_color=theme.CARD)
        det.grid(row=0, column=1, sticky="nsew")
        det.grid_propagate(False)
        self._det = ctk.CTkFrame(det, fg_color="transparent")
        self._det.pack(fill="both", expand=True, padx=18, pady=16)
        self._show_detail_empty()

    def _build_formats(self, p):
        f = ctk.CTkFrame(p, fg_color="transparent")
        f.pack(fill="x", padx=28, pady=(4, 24))
        ctk.CTkLabel(f, text="Formatos disponibles", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB).pack(side="left", padx=(0, 12))
        for txt, color in [("📗 Excel (.xlsx)", theme.SUCCESS),
                           ("{ } JSON (.json)", theme.WARNING),
                           ("📄 TXT (.txt)", theme.CYAN)]:
            Chip(f, text=txt, color=theme.ELEVATED, text_color=color).pack(side="left", padx=4)

    # ---------------- data ----------------
    def _load(self):
        if self._loaded or self._loading:
            return
        self._loading = True
        email = self._email

        def worker():
            try:
                data = {"list": rd.list_reports(email), "clf": rd.count_classified(email),
                        "exp": len(rd.list_exports(email))}
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
        clf = data.get("clf")
        self._cards["gen"].configure(text=f"{len(self._all):,}",
                                     text_color=theme.ACCENT if self._all else theme.TEXT_MUTE)
        exp = data.get("exp")
        self._cards["exp"].configure(text=(f"{exp:,}" if exp else "—"),
                                     text_color=theme.CYAN if exp else theme.TEXT_MUTE)
        self._cards["clf"].configure(text=(f"{clf:,}" if clf is not None else "—"),
                                     text_color=theme.SUCCESS if clf else theme.TEXT_MUTE)
        carps = sorted({r["carpeta"] for r in self._all})
        try:
            self._om_carp.configure(values=["Todos"] + carps)
        except Exception:
            pass
        self._render_table()

    def _apply_filters(self):
        cutoff = self._date_cutoff()
        self._filtered = [r for r in self._all
                          if (self._f_tipo == "Todos" or r["tipo"] == self._f_tipo)
                          and (self._f_carpeta == "Todos" or r["carpeta"] == self._f_carpeta)
                          and (r.get("ts", 0) >= cutoff)]
        self._page = 0
        self._render_table()

    def _date_cutoff(self):
        """Epoch mínimo según el filtro de fechas (0 = sin filtro)."""
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

    def _set(self, attr, v):
        setattr(self, attr, v)

    # ---------------- table ----------------
    def _render_table(self):
        for w in self._tbody.winfo_children():
            w.destroy()
        for w in self._pag.winfo_children():
            w.destroy()
        if not self._filtered:
            box = ctk.CTkFrame(self._tbody, fg_color="transparent")
            box.pack(expand=True, fill="both", pady=30)
            ctk.CTkLabel(box, text="📄", font=(theme.FONT_FAMILY, 34),
                         text_color=theme.TEXT_MUTE).pack()
            ctk.CTkLabel(box, text="Aún no hay reportes.", font=theme.FONT_BODY,
                         text_color=theme.TEXT_SUB).pack(pady=(8, 2))
            ctk.CTkLabel(box, text="Se generan al clasificar fotos con el motor.",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE).pack()
            return
        start = self._page * self.PAGE
        page = self._filtered[start:start + self.PAGE]
        for r in page:
            self._row(r)
        # paginación
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

    def _row(self, r):
        sel = (self._sel and self._sel["path"] == r["path"])
        row = ctk.CTkFrame(self._tbody, fg_color=(theme.NAV_ACTIVE_BG if sel else "transparent"),
                           corner_radius=theme.RADIUS_SM, height=46)
        row.pack(fill="x", pady=2)
        row.pack_propagate(False)
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=10)
        ctk.CTkLabel(info, text=r["nombre"], font=(theme.FONT_FAMILY, 12, "bold"),
                     text_color=theme.TEXT, anchor="w").pack(anchor="w", pady=(5, 0))
        ctk.CTkLabel(info, text=f"{r['tipo']} · {r['carpeta']} · {r['fecha']}",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE, anchor="w").pack(anchor="w")
        ctk.CTkLabel(row, text="● Completado", font=theme.FONT_SMALL,
                     text_color=theme.SUCCESS).pack(side="left", padx=10)

        def _hover(on):
            if self._sel and self._sel.get("path") == r["path"]:
                return
            try:
                row.configure(fg_color=theme.NAV_HOVER_BG if on else "transparent")
            except Exception:
                pass

        def _bind(w):
            w.bind("<Button-1>", lambda e, rr=r: self._select(rr))
            w.bind("<Enter>", lambda e: _hover(True))
            w.bind("<Leave>", lambda e: _hover(False))
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
            for c in w.winfo_children():
                _bind(c)

        _bind(row)

        # Acciones por fila (se crean DESPUÉS de _bind para que su clic no
        # dispare la selección de la fila): Ver = abrir; Descargar = guardar copia.
        mini = {"height": 26, "corner_radius": theme.RADIUS_SM,
                "font": theme.FONT_SMALL, **theme.BTN_GHOST}
        ctk.CTkButton(row, text="Descargar", width=78,
                      command=lambda rr=r: self._descargar(rr), **mini
                      ).pack(side="right", padx=(4, 12), pady=9)
        ctk.CTkButton(row, text="Ver", width=48,
                      command=lambda rr=r: (self._select(rr), self._abrir(rr)), **mini
                      ).pack(side="right", padx=2, pady=9)

    def _descargar(self, r):
        """Guarda una copia del reporte donde el usuario elija."""
        if not r:
            return
        try:
            dest = filedialog.asksaveasfilename(
                title="Guardar reporte como…",
                initialfile=r["nombre"],
                defaultextension=r.get("ext", ""),
                filetypes=[(r.get("tipo", "Archivo"), f"*{r.get('ext', '.*')}"),
                           ("Todos", "*.*")])
            if not dest:
                return
            shutil.copy2(r["path"], dest)
            self._toast(f"Reporte guardado en: {dest}")
        except Exception as e:
            self._toast(f"No se pudo guardar: {e}")

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
        self._render_table()
        for w in self._det.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._det, text="Cargando detalle…", font=theme.FONT_SUB,
                     text_color=theme.TEXT_MUTE).pack(anchor="w")
        path = r["path"]

        def worker():
            try:
                d = rd.report_detail(path)
            except Exception:
                d = None
            self._dq.put(d)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_detail()

    def _poll_detail(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            d = self._dq.get_nowait()
        except queue.Empty:
            self.after(80, self._poll_detail)
            return
        self._show_detail(d)

    def _show_detail_empty(self):
        for w in self._det.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._det, text="📄", font=(theme.FONT_FAMILY, 34),
                     text_color=theme.TEXT_MUTE).pack(pady=(20, 8))
        ctk.CTkLabel(self._det, text="Selecciona un reporte", font=theme.FONT_BODY,
                     text_color=theme.TEXT_SUB).pack()
        ctk.CTkLabel(self._det, text="Verás aquí su detalle.", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_MUTE).pack(pady=(2, 0))

    def _show_detail(self, d):
        for w in self._det.winfo_children():
            w.destroy()
        if not d:
            self._show_detail_empty()
            return
        ctk.CTkLabel(self._det, text=d["nombre"], font=theme.FONT_H3, text_color=theme.TEXT,
                     wraplength=280, justify="left").pack(anchor="w")
        ctk.CTkLabel(self._det, text="● " + d.get("estado", "—"), font=theme.FONT_SMALL,
                     text_color=theme.SUCCESS).pack(anchor="w", pady=(2, 10))

        def field(label, value):
            r = ctk.CTkFrame(self._det, fg_color="transparent")
            r.pack(fill="x", pady=3)
            ctk.CTkLabel(r, text=label, font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTE).pack(side="left")
            ctk.CTkLabel(r, text=str(value), font=theme.FONT_SMALL,
                         text_color=theme.TEXT).pack(side="right")

        def num(v):
            return f"{v:,}" if isinstance(v, int) else "—"

        field("Carpeta origen", d.get("origen", "—"))
        field("Carpeta destino", d.get("destino", "—"))
        field("Total analizadas", num(d.get("analizadas")))
        field("Total clasificadas", num(d.get("clasificadas")))
        field("Pendientes", num(d.get("pendientes")))

        acts = ctk.CTkFrame(self._det, fg_color="transparent")
        acts.pack(fill="x", pady=(16, 0))
        ctk.CTkButton(acts, text=" Abrir", height=40, corner_radius=theme.RADIUS_MD,
                      image=icons.icon("carpeta", 16), compound="left", **theme.BTN_GHOST,
                      command=lambda: self._abrir(self._sel)).pack(fill="x", pady=(0, 8))
        ctk.CTkButton(acts, text=" Descargar", height=40, corner_radius=theme.RADIUS_MD,
                      image=icons.icon("reporte", 16), compound="left", **theme.BTN_GHOST,
                      command=lambda: self._descargar(self._sel)).pack(fill="x", pady=(0, 8))
        ctk.CTkButton(acts, text=" Exportar a Drive", height=40, corner_radius=theme.RADIUS_MD,
                      image=icons.icon("drive", 16), compound="left",
                      font=(theme.FONT_FAMILY, 13, "bold"), **theme.BTN_PRIMARY,
                      command=self._exportar).pack(fill="x")

    def _abrir(self, r):
        if not r:
            return
        path = r["path"]

        def w():
            try:
                os.startfile(path)  # noqa: abre el archivo con la app por defecto
            except Exception as e:
                self.after(0, lambda: self._toast(f"No se pudo abrir: {e}"))

        threading.Thread(target=w, daemon=True).start()

    def _exportar(self):
        if callable(self._on_export):
            try:
                self._on_export()
                return
            except Exception:
                pass
        self._toast("Exportar a Drive no está disponible ahora mismo.")

    # ---------------- toast ----------------
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
