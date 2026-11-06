"""
FaceSync AI — Modales premium (Fase 7).

Capa visual + adaptadores delgados al flujo YA existente. Los modales NO
contienen lógica de negocio: reciben callbacks que invocan el backend/asistente
existente. El primero (LeerExcelModal) selecciona un Excel/CSV del workspace
multi-root y delega la lectura en el flujo del chat (que detecta columnas y
actualiza el contexto). No toca motor ni backend.
"""

import os
import queue
import threading
import tkinter as tk

import customtkinter as ctk

from facesyncApp.ui import theme, icons

_EXCEL_EXT = (".xlsx", ".xls", ".csv")

# Gris tenue del "margen-sombra" alrededor del panel perla (tarjeta flotante).
GLASS_SHADOW = "#C7D0E0"


class GlassModal(ctk.CTkToplevel):
    """Base 'glassmorphism' premium (aproximación estable, sin libs extra):
      - overlay oscuro semitransparente sobre la app -> sensación flotante.
      - leve translucidez de la propia ventana (-alpha) -> efecto vidrio/perla.
      - franja de acento superior premium.
      - cierre limpio (Esc / X / Cancelar) que elimina también el overlay.
    Las subclases solo cambian su clase base; conservan su contenido y lógica.
    """

    def __init__(self, parent, overlay=True):
        super().__init__(parent)
        self._glass_overlay = None
        self._glass_parent = parent
        # Overlay oscuro translúcido cubriendo la app (atenúa el fondo). Es
        # transient para mantenerse SOBRE la app (si no, queda detrás).
        # `overlay=False` (p. ej. ventana de progreso) deja la app visible y
        # USABLE detrás (no bloquea clics): no se atenúa ni se intercepta.
        # Usa tk.Toplevel PLANO (no CTkToplevel) -> crear/destruir mucho más
        # ligero (sin init de CTk) => abrir/cerrar más fluido.
        if overlay:
            try:
                ov = tk.Toplevel(parent)
                ov.overrideredirect(True)
                try:
                    ov.transient(parent)
                except Exception:
                    pass
                ov.configure(bg="#0A1020")
                ov.attributes("-alpha", 0.45)
                parent.update_idletasks()
                ov.geometry(f"{parent.winfo_width()}x{parent.winfo_height()}"
                            f"+{parent.winfo_rootx()}+{parent.winfo_rooty()}")
                ov.bind("<Button-1>", lambda e: self.destroy())
                self._glass_overlay = ov
            except Exception:
                self._glass_overlay = None
        # Ventana sin marco del SO -> panel flotante limpio (sin barra oscura).
        try:
            self.overrideredirect(True)
            self.transient(parent)
        except Exception:
            pass
        # Marco-sombra: la ventana es un gris tenue y dentro va un panel perla
        # REDONDEADO con borde => tarjeta flotante con sombra/borde simulados
        # (aproximación estable: sin blur ni transparencias frágiles). El contenido
        # de cada modal se construye dentro de `self.body`.
        try:
            self.configure(fg_color=GLASS_SHADOW)
            self.attributes("-transparentcolor", GLASS_SHADOW)
        except Exception:
            pass
        self.body = ctk.CTkFrame(self, fg_color=theme.BG_APP, corner_radius=theme.RADIUS_XL,
                                 border_width=1, border_color=theme.BORDER)
        self.body.pack(fill="both", expand=True, padx=7, pady=7)
        # Franja de acento (dentro del panel, inset para respetar las esquinas).
        try:
            ctk.CTkFrame(self.body, height=4, corner_radius=2, fg_color=theme.ACCENT
                         ).pack(fill="x", padx=20, pady=(10, 0))
        except Exception:
            pass
        # Botón de cierre (✕) propio.
        try:
            ctk.CTkButton(self.body, text="✕", width=30, height=28, corner_radius=theme.RADIUS_SM,
                          fg_color="transparent", hover_color=theme.ELEVATED,
                          text_color=theme.TEXT_SUB, command=self.destroy
                          ).place(relx=1.0, x=-14, y=12, anchor="ne")
        except Exception:
            pass
        # Translucidez muy sutil de la ventana (efecto vidrio, legible).
        try:
            self.attributes("-alpha", 0.985)
        except Exception:
            pass
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(20, self._raise_glass)

    def _raise_glass(self):
        try:
            if self._glass_overlay is not None and self._glass_overlay.winfo_exists():
                self._glass_overlay.lift()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _debounce(self, key, fn, ms=160):
        """Agenda fn() tras `ms`, cancelando el pendiente anterior. Evita
        re-renderizar la lista en CADA tecla (escritura fluida en los buscadores)."""
        d = getattr(self, "_debouncers", None)
        if d is None:
            d = {}
            self._debouncers = d
        old = d.get(key)
        if old is not None:
            try:
                self.after_cancel(old)
            except Exception:
                pass
        try:
            d[key] = self.after(ms, fn)
        except Exception:
            try:
                fn()
            except Exception:
                pass

    def destroy(self):
        # Cancela cualquier 'after' pendiente (debounce/poll) para no disparar
        # callbacks sobre la ventana ya destruida.
        try:
            d = getattr(self, "_debouncers", None)
            if d:
                for aid in list(d.values()):
                    try:
                        self.after_cancel(aid)
                    except Exception:
                        pass
                d.clear()
        except Exception:
            pass
        # Libera el grab ANTES de destruir (si no, el foco/teclado puede quedar
        # "colgado" y la app parece congelada).
        try:
            self.grab_release()
        except Exception:
            pass
        parent = getattr(self, "_glass_parent", None) or self.master
        # Oculta el modal y el overlay de INMEDIATO y devuelve foco/activación a
        # la app, repintando antes de la destrucción real de widgets. Así el
        # cierre se PERCIBE instantáneo aunque destruir muchas filas tarde algo,
        # y el teclado/chat queda usable al instante (no "se congela").
        try:
            self.withdraw()
        except Exception:
            pass
        try:
            ov = getattr(self, "_glass_overlay", None)
            if ov is not None and ov.winfo_exists():
                ov.destroy()
        except Exception:
            pass
        try:
            if parent is not None and parent.winfo_exists():
                parent.lift()
                parent.focus_force()
                parent.update_idletasks()
        except Exception:
            pass
        super().destroy()

    def _center(self, parent, w, h):
        """Centra el modal sobre la ventana principal y lo mantiene SIEMPRE dentro
        del área visible. CustomTkinter escala TODA la geometría (W, H, X e Y) por
        el factor DPI, así que medimos ese factor empíricamente y hacemos todo el
        cálculo en coordenadas lógicas; el modal se posiciona con la forma completa
        'WxH+X+Y'. Funciona en 1366x768 / 1600x900 / 1920x1080, con o sin escalado
        de Windows, y nunca queda cortado abajo ni fuera de pantalla."""
        w, h = int(w), int(h)
        # 1) Factor de escalado DPI de CTk. Primero la API de CTk; si no, medirlo
        #    empíricamente (con guarda, porque la ventana puede no estar realizada).
        scaling = None
        try:
            s = float(self._get_window_scaling())
            if 0.5 <= s <= 4.0:
                scaling = s
        except Exception:
            scaling = None
        if scaling is None:
            try:
                self.geometry(f"{w}x{h}")
                self.update()
                aw = self.winfo_width()
                if aw and aw > 50 and w:
                    s = aw / float(w)
                    if 0.5 <= s <= 4.0:
                        scaling = s
            except Exception:
                scaling = None
        if scaling is None or scaling <= 0:
            scaling = 1.0
        # 2) Pantalla y tamaño en unidades LÓGICAS (lo que espera geometry()).
        try:
            sw = self.winfo_screenwidth() / scaling
            sh = self.winfo_screenheight() / scaling
        except Exception:
            sw, sh = 1366.0, 768.0
        m = 24
        w = min(w, int(sw - 2 * m))
        h = min(h, int(sh - 2 * m))
        # 3) Centro de la ventana principal (lógico); fallback a centro de pantalla.
        try:
            parent.update_idletasks()
            pw = parent.winfo_width() / scaling
            ph = parent.winfo_height() / scaling
            if pw <= 1 or ph <= 1:
                raise ValueError
            cx = parent.winfo_rootx() / scaling + pw / 2
            cy = parent.winfo_rooty() / scaling + ph / 2
        except Exception:
            cx, cy = sw / 2, sh / 2
        # 4) Clampear dentro de la pantalla con margen.
        x = max(m, min(cx - w / 2, sw - w - m))
        y = max(m, min(cy - h / 2, sh - h - m))
        try:
            self.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        except Exception:
            pass


class LeerExcelModal(GlassModal):
    """Selecciona un Excel/CSV del workspace y lo lee con el flujo existente.

    Parámetros:
      - roots: lista de carpetas raíz del workspace (multi-root).
      - on_read: callable(path) -> dict {ok, columns, name_col, ref_col, rows,
        message}. El dashboard lo implementa como adaptador delgado al
        local_router (el mismo "lee ..." del chat).
    """

    def __init__(self, parent, *, roots, on_read):
        super().__init__(parent)
        self._on_read = on_read
        self._roots = [r for r in (roots or []) if r]
        self._files = []
        self._sel_path = None
        self._scan_q = queue.Queue()

        self.title("Leer Excel")
        # Fondo lo fija GlassModal: ventana=sombra, panel (self.body)=perla.
        try:
            self.transient(parent)
        except Exception:
            pass
        self._build()
        self._center(parent, 560, 580)
        try:
            self.grab_set()
            self.focus_force()
        except Exception:
            pass
        self.after(60, self._scan_async)

    # ---------------- build ----------------
    def _build(self):
        head = ctk.CTkFrame(self.body, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(20, 4))
        ctk.CTkLabel(head, text="  Leer Excel", image=icons.icon("excel", 24),
                     compound="left", font=theme.FONT_H2,
                     text_color=theme.TEXT).pack(anchor="w")
        ctk.CTkLabel(head, text="Selecciona el Excel/CSV de referencia de tu workspace.",
                     font=theme.FONT_SUB, text_color=theme.TEXT_SUB).pack(anchor="w", pady=(2, 0))

        self._search = ctk.CTkEntry(self.body, placeholder_text="Buscar archivo…", height=38,
                                    corner_radius=theme.RADIUS_MD, fg_color=theme.CARD,
                                    border_color=theme.BORDER)
        self._search.pack(fill="x", padx=22, pady=(10, 6))
        self._search.bind("<KeyRelease>", lambda e: self._debounce("list", self._render_list))

        # Footer FIJO al fondo (siempre visible) + estados, empaquetados ANTES
        # del área expandible para que el scroll nunca empuje los botones fuera.
        btns = ctk.CTkFrame(self.body, fg_color="transparent")
        btns.pack(side="bottom", fill="x", padx=22, pady=(8, 18))
        ctk.CTkButton(btns, text="Cancelar", height=42, corner_radius=theme.RADIUS_MD,
                      **theme.BTN_GHOST,
                      command=self.destroy).pack(side="left")
        self._btn = ctk.CTkButton(btns, text="Leer Excel", height=42, width=160,
                                  corner_radius=theme.RADIUS_MD, **theme.BTN_PRIMARY,
                                  font=(theme.FONT_FAMILY, 13, "bold"),
                                  command=self._do_read, state="disabled")
        self._btn.pack(side="right")

        self._result = ctk.CTkFrame(self.body, fg_color="transparent")
        self._result.pack(side="bottom", fill="x", padx=22, pady=(2, 2))

        self._status = ctk.CTkLabel(self.body, text="Escaneando workspace…",
                                    font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE)
        self._status.pack(side="bottom", anchor="w", padx=24, pady=(2, 0))

        self._list = ctk.CTkScrollableFrame(self.body, fg_color=theme.PANEL,
                                            corner_radius=theme.RADIUS_LG)
        self._list.pack(side="top", fill="both", expand=True, padx=22, pady=(4, 6))

    # ---------------- scan (worker) ----------------
    def _scan_async(self):
        roots = list(self._roots)
        if not roots:
            self._files = []
            self._render_list()
            return

        def worker():
            found, seen = [], set()
            for root in roots:
                try:
                    entries = list(os.scandir(root))
                except OSError:
                    continue
                subdirs = []
                for e in entries:
                    try:
                        if e.is_file(follow_symlinks=False) and e.name.lower().endswith(_EXCEL_EXT):
                            p = e.path.replace("\\", "/")
                            if p not in seen:
                                seen.add(p)
                                found.append(p)
                        elif e.is_dir(follow_symlinks=False):
                            subdirs.append(e.path)
                    except OSError:
                        continue
                for sd in subdirs[:60]:  # un nivel, acotado (no escanear el árbol completo)
                    try:
                        with os.scandir(sd) as it2:
                            for f in it2:
                                if f.is_file(follow_symlinks=False) and f.name.lower().endswith(_EXCEL_EXT):
                                    p = f.path.replace("\\", "/")
                                    if p not in seen:
                                        seen.add(p)
                                        found.append(p)
                    except OSError:
                        continue
            found.sort(key=lambda p: os.path.basename(p).lower())
            self._scan_q.put(found)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_scan()

    def _poll_scan(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            self._files = self._scan_q.get_nowait()
        except queue.Empty:
            self.after(80, self._poll_scan)
            return
        self._render_list()

    # ---------------- list ----------------
    def _render_list(self):
        for w in self._list.winfo_children():
            w.destroy()
        q = (self._search.get() or "").strip().lower()
        files = [p for p in self._files if not q or q in os.path.basename(p).lower()]
        self._status.configure(
            text=(f"{len(files)} archivo(s) Excel/CSV" if files
                  else "Sin archivos Excel/CSV en el workspace"))
        for p in files[:300]:
            self._file_row(p)

    def _file_row(self, path):
        name = os.path.basename(path)
        parent = os.path.basename(os.path.dirname(path))
        sel = (self._sel_path == path)
        row = ctk.CTkFrame(self._list, fg_color=(theme.NAV_ACTIVE_BG if sel else "transparent"),
                           corner_radius=theme.RADIUS_SM, height=42)
        row.pack(fill="x", pady=2)
        row.pack_propagate(False)
        icon = "📗" if name.lower().endswith((".xlsx", ".xls")) else "📄"
        ctk.CTkLabel(row, text=f"{icon}  {name}", font=(theme.FONT_FAMILY, 12, "bold"),
                     text_color=theme.TEXT).pack(side="left", padx=10)
        ctk.CTkLabel(row, text=parent, font=theme.FONT_SMALL,
                     text_color=theme.TEXT_MUTE).pack(side="right", padx=10)
        for w in [row] + list(row.winfo_children()):
            w.bind("<Button-1>", lambda e, pp=path: self._select(pp))
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

    def _select(self, path):
        self._sel_path = path
        self._btn.configure(state="normal")
        self._render_list()

    # ---------------- read (worker) ----------------
    def _do_read(self):
        if not self._sel_path:
            return
        # La lectura es rápida y el flujo del chat (contexto/vault SQLite) es
        # sensible al hilo, por eso se ejecuta en el hilo de UI tras pintar el
        # estado "Leyendo…". No es una operación larga como la clasificación.
        self._btn.configure(state="disabled", text="Leyendo…")
        try:
            self.update_idletasks()
        except Exception:
            pass
        try:
            data = self._on_read(self._sel_path)
        except Exception as e:
            data = {"ok": False, "message": str(e), "columns": []}
        self._show_result(data)

    def _show_result(self, data):
        for w in self._result.winfo_children():
            w.destroy()
        self._btn.configure(state="normal", text="Leer Excel")
        if not data or not data.get("ok"):
            msg = (data or {}).get("message", "") or "No se pudo leer el archivo."
            ctk.CTkLabel(self._result, text=f"⚠ {msg[:140]}", font=theme.FONT_SMALL,
                         text_color=theme.DANGER, wraplength=480, justify="left").pack(anchor="w")
            return
        cols = data.get("columns") or []
        card = ctk.CTkFrame(self._result, fg_color=theme.CARD, corner_radius=theme.RADIUS_MD,
                            border_width=1, border_color=theme.SUCCESS)
        card.pack(fill="x")
        ctk.CTkLabel(card, text=f"✓ Excel leído · {len(cols)} columnas",
                     font=(theme.FONT_FAMILY, 12, "bold"), text_color=theme.SUCCESS).pack(
            anchor="w", padx=12, pady=(8, 2))
        if cols:
            txt = ", ".join(map(str, cols[:12])) + ("…" if len(cols) > 12 else "")
            ctk.CTkLabel(card, text=f"Columnas: {txt}", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SUB, wraplength=480, justify="left").pack(
                anchor="w", padx=12)
        det = []
        if data.get("name_col"):
            det.append(f"Nombre → {data['name_col']}")
        if data.get("ref_col"):
            det.append(f"Foto/Ref → {data['ref_col']}")
        if det:
            ctk.CTkLabel(card, text=" · ".join(det), font=theme.FONT_SMALL,
                         text_color=theme.CYAN).pack(anchor="w", padx=12, pady=(2, 0))
        ctk.CTkLabel(card, text="Contexto actualizado (igual que el chat).",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE).pack(
            anchor="w", padx=12, pady=(2, 8))
        self._btn.configure(text="Listo ✓")


class CrearCarpetasModal(GlassModal):
    """Crea carpetas desde un Excel/CSV usando el flujo existente del router.

    Parámetros (todos callbacks/datos provistos por el dashboard como adaptadores
    delgados; el modal no contiene lógica de negocio):
      - roots: carpetas raíz del workspace (multi-root) para escanear.
      - prefill: {path, columns, name_col} del Excel ya leído (o None).
      - on_columns(path) -> {ok, columns, name_col}: lee columnas (flujo del chat).
      - on_preview(path, column) -> list[str]: nombres de carpeta (solo lectura).
      - on_create(path, column, destination) -> {ok, created, reused, destination,
        items, message}: ejecuta vía el router existente.
    """

    def __init__(self, parent, *, roots, prefill=None, on_columns, on_preview, on_create):
        super().__init__(parent)
        self._roots = [r for r in (roots or []) if r]
        self._prefill = prefill or {}
        self._on_columns = on_columns
        self._on_preview = on_preview
        self._on_create = on_create
        self._excel_map = {}   # display -> path
        self._dest_map = {}    # display -> path
        self._scan_q = queue.Queue()
        self._prev_q = queue.Queue()

        self.title("Crear carpetas")
        # Fondo lo fija GlassModal: ventana=sombra, panel (self.body)=perla.
        try:
            self.transient(parent)
        except Exception:
            pass
        self._build()
        self._center(parent, 600, 660)
        try:
            self.grab_set()
            self.focus_force()
        except Exception:
            pass
        self.after(60, self._scan_async)

    # ---------------- build ----------------
    def _build(self):
        head = ctk.CTkFrame(self.body, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(20, 4))
        ctk.CTkLabel(head, text="  Crear carpetas", image=icons.icon("agregar_carpeta", 24),
                     compound="left", font=theme.FONT_H2,
                     text_color=theme.TEXT).pack(anchor="w")
        ctk.CTkLabel(head, text="Crea una carpeta por registro del Excel/CSV de referencia.",
                     font=theme.FONT_SUB, text_color=theme.TEXT_SUB).pack(anchor="w", pady=(2, 0))

        form = ctk.CTkFrame(self.body, fg_color="transparent")
        form.pack(fill="x", padx=22, pady=(10, 4))
        om = {"height": 36, "corner_radius": theme.RADIUS_MD, "fg_color": theme.CARD,
              "button_color": theme.ELEVATED, "button_hover_color": theme.ACCENT}

        ctk.CTkLabel(form, text="Excel de referencia", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB).pack(anchor="w")
        self._om_excel = ctk.CTkOptionMenu(form, values=["Escaneando…"], state="disabled",
                                           command=self._on_excel_change, **om)
        self._om_excel.pack(fill="x", pady=(2, 10))

        ctk.CTkLabel(form, text="Columna de nombres", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB).pack(anchor="w")
        self._om_col = ctk.CTkOptionMenu(form, values=["—"], state="disabled",
                                         command=lambda v: self._refresh_preview(), **om)
        self._om_col.pack(fill="x", pady=(2, 10))

        ctk.CTkLabel(form, text="Carpeta destino", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB).pack(anchor="w")
        self._om_dest = ctk.CTkOptionMenu(form, values=["Escaneando…"], state="disabled", **om)
        self._om_dest.pack(fill="x", pady=(2, 4))

        prev_head = ctk.CTkFrame(self.body, fg_color="transparent")
        prev_head.pack(fill="x", padx=22, pady=(8, 2))
        ctk.CTkLabel(prev_head, text="Vista previa", font=theme.FONT_H3,
                     text_color=theme.TEXT).pack(side="left")
        self._prev_count = ctk.CTkLabel(prev_head, text="", font=theme.FONT_SMALL,
                                        text_color=theme.CYAN)
        self._prev_count.pack(side="right")

        # Footer FIJO al fondo (siempre visible), ANTES del área expandible.
        btns = ctk.CTkFrame(self.body, fg_color="transparent")
        btns.pack(side="bottom", fill="x", padx=22, pady=(8, 18))
        ctk.CTkButton(btns, text="Cancelar", height=42, corner_radius=theme.RADIUS_MD,
                      **theme.BTN_GHOST,
                      command=self.destroy).pack(side="left")
        self._btn = ctk.CTkButton(btns, text="Crear carpetas", height=42, width=170,
                                  corner_radius=theme.RADIUS_MD, **theme.BTN_PRIMARY,
                                  font=(theme.FONT_FAMILY, 13, "bold"),
                                  command=self._do_create, state="disabled")
        self._btn.pack(side="right")

        self._result = ctk.CTkFrame(self.body, fg_color="transparent")
        self._result.pack(side="bottom", fill="x", padx=22, pady=(0, 2))

        self._prev_list = ctk.CTkScrollableFrame(self.body, fg_color=theme.PANEL,
                                                 corner_radius=theme.RADIUS_LG, height=150)
        self._prev_list.pack(side="top", fill="both", expand=True, padx=22, pady=(2, 6))

    # ---------------- scan (worker) ----------------
    def _scan_async(self):
        roots = list(self._roots)

        def worker():
            excels, efolders, seen_f, seen_d = [], [], set(), set()
            for root in roots:
                rp = root.replace("\\", "/")
                if rp not in seen_d:
                    seen_d.add(rp)
                    efolders.append(rp)
                try:
                    entries = list(os.scandir(root))
                except OSError:
                    continue
                subdirs = []
                for e in entries:
                    try:
                        if e.is_file(follow_symlinks=False) and e.name.lower().endswith(_EXCEL_EXT):
                            p = e.path.replace("\\", "/")
                            if p not in seen_f:
                                seen_f.add(p)
                                excels.append(p)
                        elif e.is_dir(follow_symlinks=False):
                            subdirs.append(e.path)
                    except OSError:
                        continue
                for sd in subdirs[:80]:
                    dp = sd.replace("\\", "/")
                    if dp not in seen_d:
                        seen_d.add(dp)
                        efolders.append(dp)
                    try:
                        with os.scandir(sd) as it2:
                            for f in it2:
                                if f.is_file(follow_symlinks=False) and f.name.lower().endswith(_EXCEL_EXT):
                                    p = f.path.replace("\\", "/")
                                    if p not in seen_f:
                                        seen_f.add(p)
                                        excels.append(p)
                    except OSError:
                        continue
            excels.sort(key=lambda p: os.path.basename(p).lower())
            self._scan_q.put((excels, efolders))

        threading.Thread(target=worker, daemon=True).start()
        self._poll_scan()

    def _poll_scan(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            excels, folders = self._scan_q.get_nowait()
        except queue.Empty:
            self.after(80, self._poll_scan)
            return
        self._apply_scan(excels, folders)

    @staticmethod
    def _uniq_display(path, used):
        base = os.path.basename(path) or path
        disp = base
        i = 2
        while disp in used:
            disp = f"{base} · {os.path.basename(os.path.dirname(path))}" if i == 2 else f"{base} ({i})"
            i += 1
        used.add(disp)
        return disp

    def _apply_scan(self, excels, folders):
        used_e = set()
        self._excel_map = {}
        for p in excels:
            self._excel_map[self._uniq_display(p, used_e)] = p
        used_d = set()
        self._dest_map = {}
        for p in folders:
            self._dest_map[self._uniq_display(p, used_d)] = p

        # Excel OptionMenu
        if self._excel_map:
            vals = list(self._excel_map.keys())
            self._om_excel.configure(values=vals, state="normal")
            # preselección del Excel ya leído (por basename)
            pre = self._prefill.get("path")
            sel = vals[0]
            if pre:
                pb = os.path.basename(str(pre)).lower()
                for disp, p in self._excel_map.items():
                    if os.path.basename(p).lower() == pb:
                        sel = disp
                        break
            self._om_excel.set(sel)
        else:
            self._om_excel.configure(values=["(sin Excel/CSV en el workspace)"], state="disabled")

        # Destino OptionMenu
        if self._dest_map:
            self._om_dest.configure(values=list(self._dest_map.keys()), state="normal")
            self._om_dest.set(list(self._dest_map.keys())[0])

        # columnas: del prefill si coincide, si no, leer del seleccionado
        pre = self._prefill.get("path")
        cur = self._excel_map.get(self._om_excel.get())
        if pre and cur and os.path.basename(str(pre)).lower() == os.path.basename(cur).lower() \
                and self._prefill.get("columns"):
            self._set_columns(self._prefill.get("columns"), self._prefill.get("name_col"))
        elif cur:
            self._on_excel_change(self._om_excel.get())

    # ---------------- columnas ----------------
    def _on_excel_change(self, _disp):
        path = self._excel_map.get(self._om_excel.get())
        if not path:
            return
        self._om_col.configure(values=["Leyendo…"], state="disabled")
        try:
            self.update_idletasks()
        except Exception:
            pass
        try:
            data = self._on_columns(path)  # flujo del chat (hilo UI)
        except Exception as e:
            data = {"ok": False, "message": str(e)}
        if data and data.get("ok") and data.get("columns"):
            self._set_columns(data.get("columns"), data.get("name_col"))
        else:
            self._om_col.configure(values=["(sin columnas)"], state="disabled")
            self._refresh_preview()

    def _set_columns(self, columns, name_col):
        cols = [str(c) for c in (columns or [])]
        if not cols:
            self._om_col.configure(values=["(sin columnas)"], state="disabled")
            return
        self._om_col.configure(values=cols, state="normal")
        self._om_col.set(name_col if name_col in cols else cols[0])
        self._refresh_preview()

    # ---------------- preview (worker) ----------------
    def _refresh_preview(self):
        for w in self._prev_list.winfo_children():
            w.destroy()
        self._prev_count.configure(text="")
        path = self._excel_map.get(self._om_excel.get())
        col = self._om_col.get()
        if not path or col in ("—", "(sin columnas)", "Leyendo…"):
            self._btn.configure(state="disabled")
            return
        self._prev_count.configure(text="calculando…")

        def worker():
            try:
                names = self._on_preview(path, col)
            except Exception:
                names = []
            self._prev_q.put(names)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_preview()

    def _poll_preview(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            names = self._prev_q.get_nowait()
        except queue.Empty:
            self.after(80, self._poll_preview)
            return
        self._show_preview(names)

    def _show_preview(self, names):
        for w in self._prev_list.winfo_children():
            w.destroy()
        n = len(names or [])
        self._prev_count.configure(text=(f"{n} carpeta(s)" if n else "0 carpetas"))
        if not n:
            ctk.CTkLabel(self._prev_list, text="No hay nombres en esa columna.",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE).pack(anchor="w", pady=8)
            self._btn.configure(state="disabled")
            return
        for nm in names[:200]:
            ctk.CTkLabel(self._prev_list, text=f"📁  {nm}", font=theme.FONT_SMALL,
                         text_color=theme.TEXT, anchor="w").pack(anchor="w", padx=8, pady=1)
        if n > 200:
            ctk.CTkLabel(self._prev_list, text=f"… y {n - 200} más",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE).pack(anchor="w", padx=8, pady=2)
        self._btn.configure(state="normal")

    # ---------------- crear (hilo UI) ----------------
    def _do_create(self):
        path = self._excel_map.get(self._om_excel.get())
        col = self._om_col.get()
        dest = self._dest_map.get(self._om_dest.get())
        if not path or not dest or col in ("—", "(sin columnas)", "Leyendo…"):
            return
        self._btn.configure(state="disabled", text="Creando…")
        try:
            self.update_idletasks()
        except Exception:
            pass
        try:
            data = self._on_create(path, col, dest)
        except Exception as e:
            data = {"ok": False, "message": str(e)}
        self._show_result(data)

    def _show_result(self, data):
        for w in self._result.winfo_children():
            w.destroy()
        self._btn.configure(state="normal", text="Crear carpetas")
        if not data or not data.get("ok"):
            msg = (data or {}).get("message", "") or "No se pudieron crear las carpetas."
            ctk.CTkLabel(self._result, text=f"⚠ {msg[:140]}", font=theme.FONT_SMALL,
                         text_color=theme.DANGER, wraplength=520, justify="left").pack(anchor="w")
            return
        card = ctk.CTkFrame(self._result, fg_color=theme.CARD, corner_radius=theme.RADIUS_MD,
                            border_width=1, border_color=theme.SUCCESS)
        card.pack(fill="x")
        created = data.get("created", 0)
        reused = data.get("reused", 0)
        ctk.CTkLabel(card, text=f"✓ {created} carpeta(s) creada(s)" +
                     (f" · {reused} ya existían" if reused else ""),
                     font=(theme.FONT_FAMILY, 12, "bold"), text_color=theme.SUCCESS).pack(
            anchor="w", padx=12, pady=(8, 2))
        ctk.CTkLabel(card, text=f"Destino: {data.get('destination', '')}",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_SUB).pack(anchor="w", padx=12, pady=(0, 8))
        self._btn.configure(text="Listo ✓")


class ClasificarFotosModal(GlassModal):
    """Prepara y lanza la clasificación reutilizando el flujo existente.

    Callbacks (adaptadores delgados del dashboard; el modal no contiene lógica):
      - roots: carpetas raíz del workspace (para escanear excels y carpetas).
      - prefill: {path, columns, name_col, ref_col} del Excel ya leído (o None).
      - on_columns(path) -> {ok, columns, name_col, ref_col}.
      - on_classify(args) -> bool: lanza la clasificación (worker + progreso +
        cancelación existentes). Devuelve True si arrancó, False si está ocupado.
        args = {table_path, name_column, reference_column, source_folders, source_folder,
                destination_folder}.
    """

    def __init__(self, parent, *, roots, prefill=None, on_columns, on_classify):
        super().__init__(parent)
        self._roots = [r for r in (roots or []) if r]
        self._prefill = prefill or {}
        self._on_columns = on_columns
        self._on_classify = on_classify
        self._excel_map = {}
        self._dest_map = {}
        self._folders = []         # [(display, path)]
        self._sel_sources = set()  # paths seleccionados
        self._scan_q = queue.Queue()

        self.title("Clasificar fotos")
        # Fondo lo fija GlassModal: ventana=sombra, panel (self.body)=perla.
        try:
            self.transient(parent)
        except Exception:
            pass
        self._build()
        self._center(parent, 620, 760)
        try:
            self.grab_set()
            self.focus_force()
        except Exception:
            pass
        self.after(60, self._scan_async)

    # ---------------- build ----------------
    def _build(self):
        head = ctk.CTkFrame(self.body, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(18, 2))
        ctk.CTkLabel(head, text="  Clasificar fotos", image=icons.icon("clasificar", 24),
                     compound="left", font=theme.FONT_H2,
                     text_color=theme.TEXT).pack(anchor="w")
        ctk.CTkLabel(head, text="Reconocimiento facial por lotes usando tu Excel de referencia.",
                     font=theme.FONT_SUB, text_color=theme.TEXT_SUB).pack(anchor="w", pady=(2, 0))

        body = ctk.CTkScrollableFrame(self.body, fg_color="transparent")
        # (se empaqueta al final, tras el footer, para reservar el fondo fijo)
        om = {"height": 34, "corner_radius": theme.RADIUS_MD, "fg_color": theme.CARD,
              "button_color": theme.ELEVATED, "button_hover_color": theme.ACCENT}

        def lab(t):
            ctk.CTkLabel(body, text=t, font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SUB).pack(anchor="w", padx=4)

        lab("Excel de referencia")
        self._om_excel = ctk.CTkOptionMenu(body, values=["Escaneando…"], state="disabled",
                                           command=self._on_excel_change, **om)
        self._om_excel.pack(fill="x", padx=4, pady=(2, 8))

        cols = ctk.CTkFrame(body, fg_color="transparent")
        cols.pack(fill="x", pady=(0, 8))
        cols.grid_columnconfigure((0, 1), weight=1, uniform="c")
        cn = ctk.CTkFrame(cols, fg_color="transparent")
        cn.grid(row=0, column=0, sticky="ew", padx=(4, 6))
        ctk.CTkLabel(cn, text="Columna de nombres", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB).pack(anchor="w")
        self._om_name = ctk.CTkOptionMenu(cn, values=["—"], state="disabled",
                                          command=lambda v: self._update(), **om)
        self._om_name.pack(fill="x", pady=(2, 0))
        cr = ctk.CTkFrame(cols, fg_color="transparent")
        cr.grid(row=0, column=1, sticky="ew", padx=(6, 4))
        ctk.CTkLabel(cr, text="Columna de referencia / foto", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB).pack(anchor="w")
        self._om_ref = ctk.CTkOptionMenu(cr, values=["—"], state="disabled",
                                         command=lambda v: self._update(), **om)
        self._om_ref.pack(fill="x", pady=(2, 0))

        lab("Carpetas origen (una o varias)")
        self._src_search = ctk.CTkEntry(body, placeholder_text="Buscar carpeta…", height=32,
                                        corner_radius=theme.RADIUS_MD, fg_color=theme.CARD,
                                        border_color=theme.BORDER)
        self._src_search.pack(fill="x", padx=4, pady=(2, 4))
        self._src_search.bind("<KeyRelease>", lambda e: self._debounce("src", self._render_sources))
        self._src_list = ctk.CTkScrollableFrame(body, fg_color=theme.PANEL,
                                                corner_radius=theme.RADIUS_LG, height=150)
        self._src_list.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self._src_count = ctk.CTkLabel(body, text="0 carpeta(s) seleccionada(s)",
                                       font=theme.FONT_SMALL, text_color=theme.CYAN)
        self._src_count.pack(anchor="w", padx=6, pady=(0, 8))

        lab("Carpeta destino")
        self._om_dest = ctk.CTkOptionMenu(body, values=["Escaneando…"], state="disabled",
                                          command=lambda v: self._update(), **om)
        self._om_dest.pack(fill="x", padx=4, pady=(2, 8))

        ctk.CTkLabel(body, text="Resumen", font=theme.FONT_H3,
                     text_color=theme.TEXT).pack(anchor="w", padx=4, pady=(2, 2))
        self._preview = ctk.CTkLabel(body, text="—", font=theme.FONT_SMALL,
                                     text_color=theme.TEXT_SUB, justify="left", anchor="w")
        self._preview.pack(fill="x", padx=6, pady=(0, 4))

        # Footer FIJO + estado al fondo (siempre visibles); el área con scroll
        # (body) se empaqueta al final para llenar el espacio restante.
        btns = ctk.CTkFrame(self.body, fg_color="transparent")
        btns.pack(side="bottom", fill="x", padx=22, pady=(4, 16))
        ctk.CTkButton(btns, text="Cancelar", height=42, corner_radius=theme.RADIUS_MD,
                      **theme.BTN_GHOST,
                      command=self.destroy).pack(side="left")
        self._btn = ctk.CTkButton(btns, text="Iniciar clasificación", height=42, width=190,
                                  corner_radius=theme.RADIUS_MD, **theme.BTN_PRIMARY,
                                  font=(theme.FONT_FAMILY, 13, "bold"),
                                  command=self._start, state="disabled")
        self._btn.pack(side="right")

        self._status = ctk.CTkLabel(self.body, text="", font=theme.FONT_SMALL,
                                    text_color=theme.WARNING)
        self._status.pack(side="bottom", anchor="w", padx=24, pady=(0, 2))

        body.pack(side="top", fill="both", expand=True, padx=18, pady=(8, 4))

    # ---------------- scan ----------------
    def _scan_async(self):
        roots = list(self._roots)

        def worker():
            excels, folders, sf, sd = [], [], set(), set()
            for root in roots:
                rp = root.replace("\\", "/")
                if rp not in sd:
                    sd.add(rp)
                    folders.append(rp)
                try:
                    entries = list(os.scandir(root))
                except OSError:
                    continue
                subs = []
                for e in entries:
                    try:
                        if e.is_file(follow_symlinks=False) and e.name.lower().endswith(_EXCEL_EXT):
                            p = e.path.replace("\\", "/")
                            if p not in sf:
                                sf.add(p)
                                excels.append(p)
                        elif e.is_dir(follow_symlinks=False):
                            subs.append(e.path)
                    except OSError:
                        continue
                for s in subs[:120]:
                    dp = s.replace("\\", "/")
                    if dp not in sd:
                        sd.add(dp)
                        folders.append(dp)
                    try:
                        with os.scandir(s) as it2:
                            for f in it2:
                                if f.is_file(follow_symlinks=False) and f.name.lower().endswith(_EXCEL_EXT):
                                    p = f.path.replace("\\", "/")
                                    if p not in sf:
                                        sf.add(p)
                                        excels.append(p)
                    except OSError:
                        continue
            excels.sort(key=lambda p: os.path.basename(p).lower())
            self._scan_q.put((excels, folders))

        threading.Thread(target=worker, daemon=True).start()
        self._poll_scan()

    def _poll_scan(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            excels, folders = self._scan_q.get_nowait()
        except queue.Empty:
            self.after(80, self._poll_scan)
            return
        self._apply_scan(excels, folders)

    @staticmethod
    def _uniq(path, used):
        base = os.path.basename(path) or path
        disp, i = base, 2
        while disp in used:
            disp = f"{base} · {os.path.basename(os.path.dirname(path))}" if i == 2 else f"{base} ({i})"
            i += 1
        used.add(disp)
        return disp

    def _apply_scan(self, excels, folders):
        ue = set()
        self._excel_map = {self._uniq(p, ue): p for p in excels}
        ud = set()
        self._dest_map = {self._uniq(p, ud): p for p in folders}
        self._folders = [(d, p) for d, p in self._dest_map.items()]

        if self._excel_map:
            vals = list(self._excel_map.keys())
            self._om_excel.configure(values=vals, state="normal")
            sel = vals[0]
            pre = self._prefill.get("path")
            if pre:
                pb = os.path.basename(str(pre)).lower()
                for d, p in self._excel_map.items():
                    if os.path.basename(p).lower() == pb:
                        sel = d
                        break
            self._om_excel.set(sel)
        else:
            self._om_excel.configure(values=["(sin Excel/CSV)"], state="disabled")

        if self._dest_map:
            self._om_dest.configure(values=list(self._dest_map.keys()), state="normal")
            self._om_dest.set(list(self._dest_map.keys())[0])

        self._render_sources()

        cur = self._excel_map.get(self._om_excel.get())
        pre = self._prefill.get("path")
        if pre and cur and os.path.basename(str(pre)).lower() == os.path.basename(cur).lower() \
                and self._prefill.get("columns"):
            self._set_cols(self._prefill.get("columns"),
                           self._prefill.get("name_col"), self._prefill.get("ref_col"))
        elif cur:
            self._on_excel_change(self._om_excel.get())
        else:
            self._update()

    # ---------------- columnas ----------------
    def _on_excel_change(self, _disp):
        path = self._excel_map.get(self._om_excel.get())
        if not path:
            return
        for om in (self._om_name, self._om_ref):
            om.configure(values=["Leyendo…"], state="disabled")
        try:
            self.update_idletasks()
        except Exception:
            pass
        try:
            data = self._on_columns(path)
        except Exception:
            data = {"ok": False}
        if data and data.get("ok") and data.get("columns"):
            self._set_cols(data["columns"], data.get("name_col"), data.get("ref_col"))
        else:
            for om in (self._om_name, self._om_ref):
                om.configure(values=["(sin columnas)"], state="disabled")
            self._update()

    def _set_cols(self, columns, name_col, ref_col):
        cols = [str(c) for c in (columns or [])]
        if not cols:
            for om in (self._om_name, self._om_ref):
                om.configure(values=["(sin columnas)"], state="disabled")
            self._update()
            return
        self._om_name.configure(values=cols, state="normal")
        self._om_name.set(name_col if name_col in cols else cols[0])
        self._om_ref.configure(values=cols, state="normal")
        self._om_ref.set(ref_col if ref_col in cols else (cols[1] if len(cols) > 1 else cols[0]))
        self._update()

    # ---------------- carpetas origen ----------------
    def _render_sources(self):
        for w in self._src_list.winfo_children():
            w.destroy()
        q = (self._src_search.get() or "").strip().lower()
        shown = [(d, p) for d, p in self._folders if not q or q in d.lower()]
        if not shown:
            ctk.CTkLabel(self._src_list, text="Sin carpetas.", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTE).pack(anchor="w", pady=6)
        cap = 80  # acota widgets -> abrir/cerrar fluido (la selección vive en
        for d, p in shown[:cap]:   # self._sel_sources, no se pierde al acotar)
            var = ctk.StringVar(value="on" if p in self._sel_sources else "off")
            cb = ctk.CTkCheckBox(self._src_list, text=d, variable=var, onvalue="on", offvalue="off",
                                 font=theme.FONT_SMALL, checkbox_width=18, checkbox_height=18,
                                 command=lambda pp=p, v=var: self._toggle_source(pp, v))
            cb.pack(anchor="w", padx=8, pady=2)
        if len(shown) > cap:
            ctk.CTkLabel(self._src_list, text=f"… +{len(shown) - cap} más · escribe para filtrar",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE).pack(anchor="w", padx=8, pady=(4, 2))
        self._update()

    def _toggle_source(self, path, var):
        if var.get() == "on":
            self._sel_sources.add(path)
        else:
            self._sel_sources.discard(path)
        self._update()

    # ---------------- preview + validación ----------------
    def _current(self):
        return {
            "table_path": self._excel_map.get(self._om_excel.get()),
            "name_column": self._om_name.get(),
            "reference_column": self._om_ref.get(),
            "sources": sorted(self._sel_sources),
            "destination": self._dest_map.get(self._om_dest.get()),
        }

    def _update(self):
        c = self._current()
        bad = ("—", "(sin columnas)", "Leyendo…", "Escaneando…", "(sin Excel/CSV)")
        falta = []
        if not c["table_path"]:
            falta.append("Excel")
        if not c["name_column"] or c["name_column"] in bad:
            falta.append("columna de nombres")
        if not c["reference_column"] or c["reference_column"] in bad:
            falta.append("columna de referencia")
        if not c["sources"]:
            falta.append("carpeta origen")
        if not c["destination"]:
            falta.append("carpeta destino")

        n = len(c["sources"])
        self._src_count.configure(text=f"{n} carpeta(s) seleccionada(s)")
        srcs = ", ".join(os.path.basename(s) for s in c["sources"][:6]) + ("…" if n > 6 else "")
        self._preview.configure(text=(
            f"Excel: {os.path.basename(c['table_path']) if c['table_path'] else '—'}\n"
            f"Nombres: {c['name_column']}   ·   Referencia: {c['reference_column']}\n"
            f"Origen ({n}): {srcs or '—'}\n"
            f"Destino: {os.path.basename(c['destination']) if c['destination'] else '—'}"
        ))
        if falta:
            self._status.configure(text="Falta: " + ", ".join(falta), text_color=theme.WARNING)
            self._btn.configure(state="disabled")
        else:
            self._status.configure(text="Listo para clasificar.", text_color=theme.SUCCESS)
            self._btn.configure(state="normal")

    # ---------------- lanzar ----------------
    def _start(self):
        c = self._current()
        if not (c["table_path"] and c["sources"] and c["destination"]):
            return
        args = {
            "table_path": c["table_path"],
            "name_column": c["name_column"],
            "reference_column": c["reference_column"],
            "destination_folder": c["destination"],
            "source_folder": c["sources"][0],
            "source_folders": c["sources"],
        }
        self._btn.configure(state="disabled", text="Lanzando…")
        try:
            started = self._on_classify(args)
        except Exception as e:
            started = False
            self._status.configure(text=f"Error: {e}", text_color=theme.DANGER)
        if started:
            # El progreso/cancelación se muestran en la ventana de progreso existente.
            self.destroy()
        else:
            self._btn.configure(state="normal", text="Iniciar clasificación")
            self._status.configure(text="Ya hay una tarea en curso. Espera o cancélala.",
                                   text_color=theme.WARNING)


class ExportarDriveModal(GlassModal):
    """Selecciona una carpeta del workspace y la exporta con el backend de Drive
    EXISTENTE (no reescribe la subida). Si no hay token/credenciales, muestra un
    estado de error elegante y deshabilita la exportación.

    Callbacks/datos del dashboard:
      - roots: carpetas raíz del workspace (multi-root).
      - token_ok: bool; token_reason: motivo si no.
      - on_export(modal, folder_path): adaptador delgado que llama al backend
        (_ejecutar_subida_drive); cierra este modal y muestra el progreso en la
        barra/estado existente.
    """

    def __init__(self, parent, *, roots, token_ok=True, token_reason="", on_export):
        super().__init__(parent)
        self._roots = [r for r in (roots or []) if r]
        self._token_ok = token_ok
        self._on_export = on_export
        self._folder_map = {}     # display -> path
        self._sel = None
        self._scan_q = queue.Queue()
        self._cnt_q = queue.Queue()

        self.title("Exportar a Drive")
        # Fondo lo fija GlassModal: ventana=sombra, panel (self.body)=perla.
        try:
            self.transient(parent)
        except Exception:
            pass
        self._build(token_reason)
        self._center(parent, 560, 560)
        try:
            self.grab_set()
            self.focus_force()
        except Exception:
            pass
        self.after(60, self._scan_async)

    def _build(self, token_reason):
        head = ctk.CTkFrame(self.body, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(20, 4))
        ctk.CTkLabel(head, text="  Exportar a Drive", image=icons.icon("drive", 24),
                     compound="left", font=theme.FONT_H2,
                     text_color=theme.TEXT).pack(anchor="w")
        ctk.CTkLabel(head, text="Selecciona una carpeta del workspace para respaldarla en Google Drive.",
                     font=theme.FONT_SUB, text_color=theme.TEXT_SUB).pack(anchor="w", pady=(2, 0))

        if not self._token_ok:
            warn = ctk.CTkFrame(self.body, fg_color=theme.CARD, corner_radius=theme.RADIUS_MD,
                                border_width=1, border_color=theme.DANGER)
            warn.pack(fill="x", padx=22, pady=(10, 2))
            ctk.CTkLabel(warn, text="⚠  Google Drive no está disponible",
                         font=(theme.FONT_FAMILY, 12, "bold"), text_color=theme.DANGER).pack(
                anchor="w", padx=12, pady=(8, 2))
            ctk.CTkLabel(warn, text=token_reason or "Configura tu cuenta de Google Drive primero.",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                         wraplength=480, justify="left").pack(anchor="w", padx=12, pady=(0, 8))

        self._search = ctk.CTkEntry(self.body, placeholder_text="Buscar carpeta…", height=36,
                                    corner_radius=theme.RADIUS_MD, fg_color=theme.CARD,
                                    border_color=theme.BORDER)
        self._search.pack(fill="x", padx=22, pady=(10, 6))
        self._search.bind("<KeyRelease>", lambda e: self._debounce("list", self._render_list))

        # Footer FIJO + estado al fondo (siempre visibles), ANTES del área expandible.
        btns = ctk.CTkFrame(self.body, fg_color="transparent")
        btns.pack(side="bottom", fill="x", padx=22, pady=(4, 16))
        ctk.CTkButton(btns, text="Cancelar", height=42, corner_radius=theme.RADIUS_MD,
                      **theme.BTN_GHOST,
                      command=self.destroy).pack(side="left")
        self._btn = ctk.CTkButton(btns, text="☁️  Exportar a Drive", height=42, width=190,
                                  corner_radius=theme.RADIUS_MD, **theme.BTN_PRIMARY,
                                  font=(theme.FONT_FAMILY, 13, "bold"),
                                  command=self._do_export, state="disabled")
        self._btn.pack(side="right")

        self._status = ctk.CTkLabel(self.body, text="Escaneando workspace…",
                                    font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE,
                                    wraplength=500, justify="left")
        self._status.pack(side="bottom", anchor="w", padx=24, pady=(0, 4))

        self._list = ctk.CTkScrollableFrame(self.body, fg_color=theme.PANEL,
                                            corner_radius=theme.RADIUS_LG)
        self._list.pack(side="top", fill="both", expand=True, padx=22, pady=(2, 6))

    # ---------------- scan (worker, solo filesystem) ----------------
    def _scan_async(self):
        roots = list(self._roots)

        def worker():
            folders, seen = [], set()
            for root in roots:
                rp = root.replace("\\", "/")
                if rp not in seen:
                    seen.add(rp)
                    folders.append((os.path.basename(rp) or rp, rp))
                try:
                    with os.scandir(root) as it:
                        subs = [e.path for e in it if e.is_dir(follow_symlinks=False)]
                except OSError:
                    subs = []
                for s in sorted(subs)[:200]:
                    dp = s.replace("\\", "/")
                    if dp not in seen:
                        seen.add(dp)
                        folders.append((f"  └─ {os.path.basename(dp)}", dp))
            self._scan_q.put(folders)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_scan()

    def _poll_scan(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            folders = self._scan_q.get_nowait()
        except queue.Empty:
            self.after(80, self._poll_scan)
            return
        used = set()
        self._folder_map = {}
        for disp, p in folders:
            d = disp
            i = 2
            while d in used:
                d = f"{disp} ({i})"
                i += 1
            used.add(d)
            self._folder_map[d] = p
        self._render_list()

    def _render_list(self):
        for w in self._list.winfo_children():
            w.destroy()
        q = (self._search.get() or "").strip().lower()
        items = [(d, p) for d, p in self._folder_map.items() if not q or q in d.lower()]
        if not items:
            ctk.CTkLabel(self._list, text="Sin carpetas en el workspace.",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE).pack(anchor="w", pady=8)
        if "Escaneando" in str(self._status.cget("text")):
            self._status.configure(text="Selecciona una carpeta para exportar.")
        cap = 80  # acota widgets -> abrir/cerrar fluido (usa el buscador para más)
        for d, p in items[:cap]:
            sel = (self._sel == p)
            row = ctk.CTkFrame(self._list, fg_color=(theme.NAV_ACTIVE_BG if sel else "transparent"),
                               corner_radius=theme.RADIUS_SM, height=40)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)
            ctk.CTkLabel(row, text=f"📁  {d.strip()}", font=(theme.FONT_FAMILY, 12, "bold"),
                         text_color=theme.TEXT).pack(side="left", padx=10)
            for w in [row] + list(row.winfo_children()):
                w.bind("<Button-1>", lambda e, pp=p: self._select(pp))
                try:
                    w.configure(cursor="hand2")
                except Exception:
                    pass
        if len(items) > cap:
            ctk.CTkLabel(self._list, text=f"… +{len(items) - cap} más · escribe para filtrar",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE).pack(anchor="w", padx=10, pady=(4, 2))

    def _select(self, path):
        self._sel = path
        self._render_list()
        if self._token_ok:
            self._btn.configure(state="normal")
        self._status.configure(
            text=f"Carpeta: {os.path.basename(path)}   ·   Destino: Google Drive\nContando archivos…",
            text_color=theme.TEXT_SUB)
        self._count_async(path)

    # ---------------- conteo aproximado (worker, diferido) ----------------
    def _count_async(self, path):
        def worker():
            n, capped = 0, False
            try:
                for _root, _dirs, files in os.walk(path):
                    n += len(files)
                    if n >= 5000:
                        capped = True
                        break
            except Exception:
                n = -1
            self._cnt_q.put((path, n, capped))

        threading.Thread(target=worker, daemon=True).start()
        self._poll_count()

    def _poll_count(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        try:
            path, n, capped = self._cnt_q.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_count)
            return
        if path != self._sel:
            return
        if n < 0:
            txt = "—"
        elif capped:
            txt = "5000+ archivos (aprox.)"
        else:
            txt = f"~{n:,} archivos"
        self._status.configure(
            text=f"Carpeta: {os.path.basename(path)}   ·   {txt}   ·   Destino: Google Drive",
            text_color=theme.TEXT_SUB)

    # ---------------- exportar ----------------
    def _do_export(self):
        if not self._sel or not self._token_ok:
            return
        self._btn.configure(state="disabled", text="Preparando…")
        self._status.configure(text="Preparando exportación a Drive…", text_color=theme.CYAN)
        try:
            self.update_idletasks()
        except Exception:
            pass
        # El backend cierra este modal; el progreso/finalización se muestran en
        # la ventana DriveProgressModal que crea el adaptador.
        self._on_export(self, self._sel)


class _WidgetProxy:
    """Proxy ligero para pb_drive / lbl_drive_count. Reenvía set()/configure(text=)
    a la ventana de progreso y ABSORBE pack/pack_forget/grid/place (que el backend
    podría invocar) para no romper el layout de la ventana. Así reutilizamos el
    backend de Drive tal cual, sin tocarlo."""

    def __init__(self, on_set=None, on_text=None, real=None):
        self._on_set = on_set
        self._on_text = on_text
        self._real = real

    def set(self, v):
        if self._on_set:
            try:
                self._on_set(float(v))
            except Exception:
                pass

    def configure(self, *a, **k):
        if self._on_text is not None and "text" in k:
            try:
                self._on_text(k["text"])
            except Exception:
                pass

    config = configure

    def cget(self, key):
        try:
            return self._real.cget(key)
        except Exception:
            return ""

    def pack(self, *a, **k):
        pass

    def pack_forget(self, *a, **k):
        pass

    def grid(self, *a, **k):
        pass

    def grid_forget(self, *a, **k):
        pass

    def place(self, *a, **k):
        pass

    def place_forget(self, *a, **k):
        pass

    def winfo_exists(self):
        try:
            return bool(self._real.winfo_exists())
        except Exception:
            return False


class DriveProgressModal(GlassModal):
    """Ventana glass NO bloqueante de progreso/finalización de la exportación a
    Drive. Diseño:
      - SIN overlay ni grab -> la app sigue visible y USABLE detrás (no se congela).
      - topmost -> flota encima sin bloquear.
      - barra "viva" mientras autentica/escanea (cubre el hueco antes del 1er %).
      - se puede ocultar en cualquier momento (ocultar NO cancela la subida), pero
        NUNCA se cierra sola antes de terminar.
    No reescribe la subida: el backend actualiza pb_drive/lbl_drive_count a través
    de proxies (self.bar/self.count) que reenvían aquí; el adaptador redirige el
    messagebox final a finish()."""

    def __init__(self, parent, *, folder_name="", folder_path="", on_close=None):
        super().__init__(parent, overlay=False)
        self._folder_path = folder_path
        self._on_close = on_close
        self._done = False
        self._got_progress = False
        self._anim = 0.0
        self.title("Exportando a Drive")
        # Fondo lo fija GlassModal: ventana=sombra, panel (self.body)=perla.
        self._build(folder_name)
        self._center(parent, 500, 360)
        try:
            self.attributes("-topmost", True)
            self.lift()
            self.focus_force()
        except Exception:
            pass
        # Proxies que el adaptador asigna a vista.pb_drive / vista.lbl_drive_count.
        self.bar = _WidgetProxy(on_set=self._on_progress, real=self._barw)
        self.count = _WidgetProxy(on_text=self._on_count, real=self._countw)
        self.after(120, self._tick)

    def _build(self, folder_name):
        head = ctk.CTkFrame(self.body, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(22, 4))
        ctk.CTkLabel(head, text="  Exportar a Drive", image=icons.icon("drive", 24),
                     compound="left", font=theme.FONT_H2,
                     text_color=theme.TEXT).pack(anchor="w")
        ctk.CTkLabel(head, text=f"Carpeta: {folder_name}", font=theme.FONT_SUB,
                     text_color=theme.TEXT_SUB).pack(anchor="w", pady=(2, 0))

        card = ctk.CTkFrame(self.body, fg_color=theme.CARD, corner_radius=theme.RADIUS_LG,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="both", expand=True, padx=24, pady=(14, 8))
        self.status = ctk.CTkLabel(card, text="Conectando con Google Drive…",
                                   font=(theme.FONT_FAMILY, 13, "bold"), text_color=theme.ACCENT)
        self.status.pack(anchor="w", padx=18, pady=(18, 6))
        self._barw = ctk.CTkProgressBar(card, height=10, corner_radius=5,
                                        progress_color=theme.ACCENT)
        self._barw.set(0)
        self._barw.pack(fill="x", padx=18, pady=(2, 8))
        self._countw = ctk.CTkLabel(card, text="Preparando exportación…",
                                    font=theme.FONT_SMALL, text_color=theme.TEXT_SUB)
        self._countw.pack(anchor="w", padx=18)
        self._summary = ctk.CTkLabel(card, text="", font=theme.FONT_SMALL,
                                     text_color=theme.TEXT_SUB, wraplength=410, justify="left")
        self._summary.pack(anchor="w", padx=18, pady=(8, 14))

        self._btns = ctk.CTkFrame(self.body, fg_color="transparent")
        self._btns.pack(fill="x", padx=24, pady=(0, 18))
        # Cerrar/ocultar disponible siempre; ocultar NO cancela la subida.
        ctk.CTkButton(self._btns, text="Ocultar", height=40, width=120,
                      corner_radius=theme.RADIUS_MD, **theme.BTN_GHOST,
                      command=self.destroy).pack(side="right")

    # --- backend (vía proxy, siempre en hilo UI por el after() del backend) ---
    def _on_progress(self, pct):
        if self._done:
            return
        self._got_progress = True
        try:
            if self._barw.winfo_exists():
                self._barw.set(max(0.0, min(1.0, pct)))
            self.status.configure(text="Exportando a Drive…", text_color=theme.ACCENT)
        except Exception:
            pass

    def _on_count(self, text):
        if self._done:
            return
        try:
            if self._countw.winfo_exists():
                self._countw.configure(text=str(text))
            if not self._got_progress:
                self.status.configure(text="Exportando a Drive…", text_color=theme.ACCENT)
        except Exception:
            pass

    def _tick(self):
        # Vaivén "vivo" de la barra mientras aún no llega un % real (auth/escaneo).
        try:
            if not self.winfo_exists() or self._done or self._got_progress:
                return
            self._anim = (self._anim + 0.09) % 1.0
            v = self._anim if self._anim <= 0.5 else (1.0 - self._anim)
            self._barw.set(max(0.05, min(0.9, v * 1.8)))
            self.after(120, self._tick)
        except Exception:
            pass

    def finish(self, kind, message):
        """Estado final (kind: 'ok' | 'warn' | 'error') con el resumen real del
        backend (subidos/omitidos/fallidos/reintentos/tiempo)."""
        self._done = True
        try:
            for w in self._btns.winfo_children():
                w.destroy()
            if kind == "ok":
                self.status.configure(text="✅ Exportación completada", text_color=theme.SUCCESS)
                self._barw.set(1.0)
            elif kind == "warn":
                self.status.configure(text="⚠️ Exportación parcial", text_color=theme.WARNING)
                self._barw.set(1.0)
            else:
                self.status.configure(text="❌ Error en la exportación", text_color=theme.DANGER)
            self._summary.configure(text=str(message or "").strip())
            self._countw.configure(text="")
            if self._folder_path and os.path.isdir(self._folder_path):
                ctk.CTkButton(self._btns, text=" Abrir carpeta", height=40,
                              image=icons.icon("carpeta", 16), compound="left",
                              corner_radius=theme.RADIUS_MD, **theme.BTN_GHOST,
                              command=self._abrir).pack(side="left")
            ctk.CTkButton(self._btns, text="Cerrar", height=40, width=120,
                          corner_radius=theme.RADIUS_MD, **theme.BTN_PRIMARY,
                          font=(theme.FONT_FAMILY, 13, "bold"),
                          command=self.destroy).pack(side="right")
            self.lift()
        except Exception:
            pass

    def _abrir(self):
        def w():
            try:
                os.startfile(self._folder_path)  # noqa
            except Exception:
                pass
        threading.Thread(target=w, daemon=True).start()


class ClasificacionResultadosModal(GlassModal):
    """Ventana premium de RESULTADOS al terminar la clasificación. Reemplaza el
    estado final de la ventanita de progreso: grande, centrada, con todos los
    detalles del lote y botón "Ver carpetas" que lleva al explorador donde
    quedaron las carpetas clasificadas. SOLO presenta datos que el motor ya
    emite en su payload final (stage="done"); no llama al motor ni al backend.

    Parámetros:
      - datos: dict = payload final del motor (metadata del reporte).
      - on_ver: callable(destination_folder) -> el dashboard navega al
        explorador y abre la carpeta destino.
    """

    def __init__(self, parent, *, datos, on_ver=None):
        super().__init__(parent)
        self._datos = dict(datos or {})
        self._on_ver = on_ver
        self.title("Clasificación completada")
        self._build()
        self._center(parent, 680, 600)
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    @staticmethod
    def _num(v, default=0):
        try:
            return int(v)
        except Exception:
            return default

    def _build(self):
        d = self._datos
        dest = str(d.get("destination_folder") or "")

        # ---------- header ----------
        head = ctk.CTkFrame(self.body, fg_color="transparent")
        head.pack(fill="x", padx=28, pady=(24, 2))
        ctk.CTkLabel(head, text="  Clasificación completada",
                     image=icons.icon("clasificar", 30), compound="left",
                     font=theme.FONT_H1, text_color=theme.TEXT).pack(anchor="w")
        ctk.CTkLabel(head, text="✓  Tus fotos ya están organizadas en sus carpetas.",
                     font=(theme.FONT_FAMILY, 13, "bold"),
                     text_color=theme.SUCCESS).pack(anchor="w", pady=(4, 0))

        # ---------- footer PRIMERO (side=bottom) para que nunca quede fuera ----------
        foot = ctk.CTkFrame(self.body, fg_color="transparent")
        foot.pack(side="bottom", fill="x", padx=28, pady=(6, 20))
        if dest:
            ctk.CTkButton(foot, text="  Ver carpetas", height=44,
                          image=icons.icon("carpeta", 18), compound="left",
                          corner_radius=theme.RADIUS_MD, **theme.BTN_PRIMARY,
                          font=(theme.FONT_FAMILY, 14, "bold"),
                          command=self._ver).pack(side="left")
        ctk.CTkButton(foot, text="Cerrar", height=44, width=130,
                      corner_radius=theme.RADIUS_MD, **theme.BTN_GHOST,
                      command=self.destroy).pack(side="right")

        # ---------- hero: 3 métricas grandes ----------
        hero = ctk.CTkFrame(self.body, fg_color="transparent")
        hero.pack(fill="x", padx=28, pady=(16, 4))
        hero.grid_columnconfigure((0, 1, 2), weight=1, uniform="hero")
        entregadas = self._num(d.get("copied_count")) + self._num(d.get("reused_count"))
        pct = d.get("porcentaje_clasificado")
        heroes = [
            (f"{entregadas:,}", "Fotos entregadas", theme.ACCENT),
            (f"{pct}%" if pct is not None else "—", "Del lote clasificado", theme.SUCCESS),
            (f"{self._num(d.get('pending_count')):,}", "Pendientes de revisión", theme.WARNING),
        ]
        for i, (valor, etiqueta, color) in enumerate(heroes):
            card = ctk.CTkFrame(hero, fg_color=theme.CARD, corner_radius=theme.RADIUS_LG,
                                border_width=1, border_color=theme.BORDER)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            ctk.CTkLabel(card, text=valor, font=(theme.FONT_FAMILY, 26, "bold"),
                         text_color=color).pack(anchor="w", padx=16, pady=(14, 0))
            ctk.CTkLabel(card, text=etiqueta, font=theme.FONT_SUB,
                         text_color=theme.TEXT_SUB).pack(anchor="w", padx=16, pady=(0, 12))

        # ---------- detalles (scroll por si la pantalla es chica) ----------
        area = ctk.CTkScrollableFrame(self.body, fg_color="transparent")
        area.pack(fill="both", expand=True, padx=22, pady=(8, 0))

        det = ctk.CTkFrame(area, fg_color=theme.CARD, corner_radius=theme.RADIUS_LG,
                           border_width=1, border_color=theme.BORDER)
        det.pack(fill="x", padx=6, pady=(0, 10))
        ctk.CTkLabel(det, text="Detalles del lote", font=theme.FONT_H3,
                     text_color=theme.TEXT).pack(anchor="w", padx=18, pady=(14, 6))
        grid = ctk.CTkFrame(det, fg_color="transparent")
        grid.pack(fill="x", padx=18, pady=(0, 14))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="det")

        filas = []
        if d.get("total") is not None:
            filas.append(("Fotos analizadas", f"{self._num(d.get('total')):,}"))
        filas.append(("Conflictos de identidad", f"{self._num(d.get('identity_conflict_count')):,}"))
        filas.append(("Sin coincidencia (otros salones)", f"{self._num(d.get('ignored_unassigned_count')):,}"))
        filas.append(("Errores de imagen", f"{self._num(d.get('image_error_count')):,}"))
        if self._num(d.get("rescued_by_gallery_count")):
            filas.append(("Rescatadas por galería", f"{self._num(d.get('rescued_by_gallery_count')):,}"))
        if self._num(d.get("reused_count")):
            filas.append(("Ya estaban en su carpeta", f"{self._num(d.get('reused_count')):,}"))
        if d.get("promedio_fotos_por_alumno") is not None:
            filas.append(("Promedio de fotos por alumno", str(d.get("promedio_fotos_por_alumno"))))
        if d.get("invalid_reference_count"):
            filas.append(("Referencias inválidas", f"{self._num(d.get('invalid_reference_count')):,}"))

        for i, (k, v) in enumerate(filas):
            fila = ctk.CTkFrame(grid, fg_color="transparent")
            fila.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 14), pady=3)
            ctk.CTkLabel(fila, text=k, font=theme.FONT_SUB,
                         text_color=theme.TEXT_SUB).pack(side="left")
            ctk.CTkLabel(fila, text=v, font=(theme.FONT_FAMILY, 12, "bold"),
                         text_color=theme.TEXT).pack(side="right")

        # ---------- ubicaciones ----------
        ubi = ctk.CTkFrame(area, fg_color=theme.CARD, corner_radius=theme.RADIUS_LG,
                           border_width=1, border_color=theme.BORDER)
        ubi.pack(fill="x", padx=6, pady=(0, 10))
        ctk.CTkLabel(ubi, text="Ubicaciones", font=theme.FONT_H3,
                     text_color=theme.TEXT).pack(anchor="w", padx=18, pady=(14, 6))
        pares = []
        if d.get("table_path"):
            pares.append(("excel", "Excel", os.path.basename(str(d.get("table_path")))))
        if d.get("source_folder"):
            pares.append(("carpeta", "Origen", str(d.get("source_folder"))))
        if dest:
            pares.append(("carpeta", "Destino", dest))
        for icono, k, v in pares:
            fila = ctk.CTkFrame(ubi, fg_color="transparent")
            fila.pack(fill="x", padx=18, pady=2)
            ctk.CTkLabel(fila, text=f"  {k}:", image=icons.icon(icono, 15), compound="left",
                         font=theme.FONT_SUB, text_color=theme.TEXT_SUB).pack(side="left")
            ctk.CTkLabel(fila, text=v, font=theme.FONT_SUB, text_color=theme.TEXT,
                         wraplength=420, justify="left", anchor="w").pack(side="left", padx=(8, 0))
        ctk.CTkFrame(ubi, fg_color="transparent", height=10).pack()

    def _ver(self):
        cb, dest = self._on_ver, str(self._datos.get("destination_folder") or "")
        self.destroy()
        if cb:
            try:
                cb(dest)
            except Exception:
                pass

    def destroy(self):
        # Restaura el messagebox monkeypatcheado aunque se oculte antes de terminar.
        cb = getattr(self, "_on_close", None)
        if cb is not None:
            self._on_close = None
            try:
                cb()
            except Exception:
                pass
        super().destroy()
