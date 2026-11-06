import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import customtkinter as ctk
import tkinter as tk
import os
import json
import queue
import shutil
import threading
from core.app_paths import ensure_app_data_root, filter_internal_names
from facesyncApp.dashboardback import DashboardBackend
from facesyncApp.agente_ia import AsistenteFaceSync
from facesyncApp.utils import set_window_app_icon, set_windows_title_bar_light
from facesyncApp.ui import theme, icons
from facesyncApp.ui.sidebar import Sidebar
from facesyncApp.ui.views.inicio_view import InicioView
from facesyncApp.ui.views.resumen_view import ResumenView
from facesyncApp.ui.views.reportes_view import ReportesView
from facesyncApp.ui.views.exportaciones_view import ExportacionesView

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

try:
    import windnd
except ImportError:
    windnd = None

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# Paleta del Workspace remapeada al tema premium navy (Fase 3).
# Se cambian SOLO los valores; los nombres se conservan para no tocar la
# lógica de render del explorador/visor que ya los usa.
BG     = theme.BG_CONTENT     # fondo del área central
PANEL  = theme.PANEL          # paneles (explorador, visor, chat)
CARD   = theme.CARD           # tarjetas
ACCENT = theme.ACCENT         # azul principal
TEXT   = theme.TEXT           # texto principal
SUB    = theme.TEXT_SUB       # texto secundario
BORDER = theme.BORDER         # bordes
HOVER  = theme.NAV_HOVER_BG   # hover de filas del árbol
SELECT = theme.NAV_ACTIVE_BG  # fila/archivo seleccionado
IMG_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
RAW_EXT = {'.cr2', '.cr3'}  # RAW: se detecta y etiqueta, NO se previsualiza pesado
_FILE_CAP = 120
_FILE_BATCH = 400
_DIR_BATCH = 60
_DIR_CAP = 120


class DashboardWindow(ctk.CTk):

    _ICON = {
        ".jpg": "🖼️", ".jpeg": "🖼️", ".png": "🖼️", ".gif": "🖼️",
        ".bmp": "🖼️", ".webp": "🖼️", ".cr2": "🎞️", ".cr3": "🎞️",
        ".xlsx": "📗", ".xls": "📗", ".pdf": "📕",
        ".docx": "📘", ".doc": "📘", ".pptx": "📙", ".ppt": "📙",
        ".mp4": "🎬", ".avi": "🎬", ".mov": "🎬", ".mkv": "🎬",
        ".mp3": "🎵", ".wav": "🎵", ".txt": "📝", ".py": "🐍",
        ".json": "{ }", ".csv": "📊", ".zip": "📦", ".rar": "📦",
    }

    def __init__(self, email_usuario="usuario_demo@gmail.com"):
        super().__init__()
        self.withdraw()
        try:
            tk._default_root = self
        except Exception:
            pass
        self.email_usuario = email_usuario
        self._configurar_tamano_normal()
        self.title("FaceSync")
        set_window_app_icon(self, default=True)
        set_windows_title_bar_light(self)
        self.configure(fg_color=theme.BG_APP)

        # Pantalla de carga INMEDIATA (sin espacios en blanco tras el login):
        # se pinta antes de construir la app y se retira sola al terminar.
        self._boot_overlay = None
        try:
            ov = ctk.CTkFrame(self, fg_color="#FFFFFF", corner_radius=0)
            ov.place(relx=0, rely=0, relwidth=1, relheight=1)
            inner = ctk.CTkFrame(ov, fg_color="transparent")
            inner.place(relx=0.5, rely=0.45, anchor="center")
            try:
                from PIL import Image as _PI
                _lp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "assets", "images", "logologin.png")
                _pil = _PI.open(_lp).convert("RGBA")
                _w = 240
                _h = max(1, int(_pil.height * (_w / _pil.width)))
                _img = ctk.CTkImage(light_image=_pil, dark_image=_pil, size=(_w, _h))
                self._boot_logo_ref = _img
                ctk.CTkLabel(inner, image=_img, text="").pack()
            except Exception:
                ctk.CTkLabel(inner, text="FaceSync", font=("Segoe UI", 30, "bold"),
                             text_color=theme.TEXT).pack()
            ctk.CTkLabel(inner, text="Cargando tu espacio…", font=("Segoe UI", 13),
                         text_color=theme.TEXT_SUB).pack(pady=(16, 0))
            self._boot_overlay = ov
            self.update()  # pintar YA, antes del init pesado
        except Exception:
            self._boot_overlay = None

        # Layout raíz (Fase 1): [ sidebar fija | área de contenido ].
        # El antiguo grid de 3 columnas (explorador/visor/chat) ahora vive
        # dentro de la vista Workspace, no directamente sobre la raíz.
        self.grid_columnconfigure(0, weight=0)   # sidebar (ancho fijo)
        self.grid_columnconfigure(1, weight=1)   # contenido (las vistas)
        self.grid_rowconfigure(0, weight=1)

        self.backend = DashboardBackend(self)

        self._folder_roots = []
        self._active_project_root = None
        self._root_paths = {}
        self._archivos_actuales = []
        self._dir_cache = {}
        self._nodes = {}
        self._carpetas_expandidas = {}
        self._selected_path = None
        self._selected_widget = None
        self._render_gen = 0
        self._viewer_img_ref = None
        self._viewer_img_path = None
        self._viewer_orig_image = None
        self._viewer_zoom = 1.0
        self._ctx_target = None

        # --- Mejor coincidencia + lote activo (Fase 7.5) ---

        # --- Shell visual / navegación entre las 5 vistas (Fase 1) ---
        self._vistas = {}          # key -> frame ya construido
        self._vista_builders = {}  # key -> callable(parent) -> frame (lazy)
        self._vista_actual = None
        self._nav_after = None
        self._nav_pending_key = None

        self._crear_sidebar()
        self._crear_area_contenido()
        self._registrar_vistas()

        # Workspace se construye de inmediato para preservar el __init__
        # original (explorador, visor, action_cards, asistente y la carga del
        # espacio de trabajo). Queda oculto hasta que se navega a él.
        self._construir_vista_workspace()

        # Vista por defecto: Inicio (placeholder premium en esta fase).
        self._mostrar_vista("inicio")

        if windnd:
            try:
                windnd.hook_dropfiles(self, func=self._on_drop)
            except Exception:
                pass
        self._mostrar_dashboard_listo()

    def _configurar_tamano_normal(self):
        """Define el tamano al restaurar y evita que quede mini."""
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            w = min(1600, max(1100, sw - 120))
            h = min(900, max(700, sh - 120))
            x = max(0, int((sw - w) / 2))
            y = max(0, int((sh - h) / 2))
            self.geometry(f"{w}x{h}+{x}+{y}")
            self.minsize(min(w, 1100), min(h, 700))
            self.resizable(True, True)
        except Exception:
            self.geometry("1400x850")
            self.minsize(1100, 700)

    def _maximizar_inicio(self):
        """Abre el dashboard ocupando toda la pantalla disponible."""
        try:
            self._configurar_tamano_normal()
        except Exception:
            pass
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                try:
                    w = self.winfo_screenwidth()
                    h = self.winfo_screenheight()
                    self.geometry(f"{w}x{h}+0+0")
                except Exception:
                    pass

    def _mostrar_dashboard_listo(self):
        """Muestra la ventana ya construida y maximizada."""
        try:
            self.update_idletasks()
        except Exception:
            pass
        self._maximizar_inicio()
        try:
            self._quitar_boot_overlay()
        except Exception:
            pass
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    # ==========================================================
    # SHELL VISUAL / NAVEGACIÓN ENTRE VISTAS (Fase 1)
    # ==========================================================
    def _crear_sidebar(self):
        username = self.email_usuario.split("@")[0]
        username = " ".join(
            p.capitalize()
            for p in username.replace(".", " ").replace("_", " ").split()
        )
        self._sidebar = Sidebar(
            self,
            on_navigate=self._solicitar_vista,
            email=self.email_usuario,
            username=username,
            on_logout=self.cerrar_sesion,
        )
        self._sidebar.grid(row=0, column=0, sticky="nsw")

    def _crear_area_contenido(self):
        self._content = ctk.CTkFrame(self, fg_color=theme.BG_CONTENT, corner_radius=0)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_rowconfigure(0, weight=1)
        self._content.grid_columnconfigure(0, weight=1)

    def _registrar_vistas(self):
        """Registra los constructores diferidos de las vistas placeholder.
        Workspace NO va aquí: se construye eager en _construir_vista_workspace."""
        self._vista_builders = {
            "inicio": lambda p: InicioView(p, email=self.email_usuario),
            "resumen": lambda p: ResumenView(p, email=self.email_usuario),
            "reportes": lambda p: ReportesView(
                p, email=self.email_usuario, on_export=self._accion_exportar_drive),
            "exportaciones": lambda p: ExportacionesView(
                p, email=self.email_usuario, on_export=self._accion_exportar_drive),
        }

    def _construir_vista_workspace(self):
        """Construye la vista Workspace reutilizando los 3 paneles originales,
        ahora montados dentro de un frame de vista (no en la raíz). Mantiene
        intactos explorador, visor, action_cards y asistente, y conserva el
        orden y el manejo de errores del __init__ original."""
        ws = ctk.CTkFrame(self._content, fg_color=theme.BG_CONTENT, corner_radius=0)
        ws.grid_columnconfigure(1, weight=1)
        ws.grid_columnconfigure(2, minsize=420)
        ws.grid_rowconfigure(0, weight=1)
        self._vistas["workspace"] = ws

        self._crear_panel_izquierdo(ws)
        try:
            self._crear_panel_central(ws)
        except Exception as e:
            print(f"ERROR en _crear_panel_central: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
        try:
            self.cargar_espacio_trabajo()
        except Exception as e:
            print(f"ERROR en cargar_espacio_trabajo: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
        try:
            self._crear_panel_derecho(ws)
        except Exception as e:
            print(f"ERROR en _crear_panel_derecho: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
        # Conecta el progreso de clasificación a la barra "lote activo" (Fase 7.5).
        try:
            self._instalar_lote_hook()
        except Exception as e:
            print(f"Advertencia: no se pudo instalar el hook de lote activo: {e}")
        # Pre-construcción de vistas en IDLE: una por tick para no trabar el
        # arranque; al hacer clic ya están construidas -> navegación instantánea.
        self.after(1000, self._prewarm_vistas)
        # Retirar la pantalla de carga: la app ya está lista (sin huecos).
        try:
            if self._boot_overlay is not None:
                self._boot_overlay.lift()
                self.after(120, self._quitar_boot_overlay)
        except Exception:
            pass

    def _quitar_boot_overlay(self):
        ov = getattr(self, "_boot_overlay", None)
        self._boot_overlay = None
        try:
            if ov is not None and ov.winfo_exists():
                ov.destroy()
        except Exception:
            pass

    def _prewarm_vistas(self):
        try:
            for key, builder in self._vista_builders.items():
                if key not in self._vistas:
                    v = builder(self._content)
                    v.grid(row=0, column=0, sticky="nsew")
                    v.grid_remove()  # construida y oculta, lista para mostrarse
                    self._vistas[key] = v
                    self.after(300, self._prewarm_vistas)  # siguiente en otro tick
                    return
        except Exception:
            pass

    def _solicitar_vista(self, key):
        """Agrupa clics rapidos para pintar solo la ultima vista pedida."""
        self._nav_pending_key = key
        if self._nav_after is not None:
            try:
                self.after_cancel(self._nav_after)
            except Exception:
                pass
        self._nav_after = self.after(35, self._aplicar_vista_pendiente)

    def _aplicar_vista_pendiente(self):
        self._nav_after = None
        key = self._nav_pending_key
        self._nav_pending_key = None
        if key:
            self._mostrar_vista(key)

    def _mostrar_vista(self, key):
        """Muestra la vista 'key', construyéndola de forma diferida si es un
        placeholder. El cambio es instantáneo: solo se oculta/des-oculta el
        frame (no se reconstruye), preservando la fluidez al navegar."""
        if key == self._vista_actual and key in self._vistas:
            return
        if key not in self._vistas:
            builder = self._vista_builders.get(key)
            if builder is None:
                return
            self._vistas[key] = builder(self._content)
        nueva = self._vistas.get(key)
        if nueva is None:
            return
        nueva.grid(row=0, column=0, sticky="nsew")
        nueva.tkraise()
        for vista_key, vista in list(self._vistas.items()):
            if vista_key != key:
                try:
                    vista.grid_remove()
                except Exception:
                    pass
        self._vista_actual = key
        if hasattr(self, "_sidebar"):
            self._sidebar.set_active(key)
        try:
            self._content.update_idletasks()
        except Exception:
            pass

    def _crear_panel_izquierdo(self, parent):
        # Panel del explorador ("Mi espacio"). Fase 3: se quitó el logo y la
        # tarjeta de usuario duplicados (viven en la sidebar global). Se conserva
        # toda la lógica del explorador (multi-root, lazy, paginación, CR2).
        lp = ctk.CTkFrame(parent, width=300, fg_color=PANEL,
                          corner_radius=0, border_width=1, border_color=BORDER)
        lp.grid(row=0, column=0, sticky="nsw")
        lp.grid_propagate(False)

        head = ctk.CTkFrame(lp, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(18, 8))
        ctk.CTkLabel(head, text="Mi espacio", font=theme.FONT_H2,
                     text_color=TEXT).pack(anchor="w")

        ctk.CTkButton(lp, text="Nueva carpeta / archivo", height=44,
                      image=icons.icon("agregar_carpeta", 18), compound="left",
                      corner_radius=theme.RADIUS_MD, font=("Segoe UI", 13, "bold"),
                      command=self.backend.manejar_boton_agregar,
                      **theme.BTN_PRIMARY
                      ).pack(fill="x", padx=20, pady=(0, 12))

        hdr = ctk.CTkFrame(lp, fg_color="transparent", height=28)
        hdr.pack(fill="x", padx=20, pady=(4, 3))
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="EXPLORADOR", font=("Segoe UI", 12, "bold"),
                     text_color=theme.CYAN).pack(side="left")

        tb = {"width": 26, "height": 26, "corner_radius": 6,
              "fg_color": "transparent", "hover_color": HOVER,
              "font": ("Segoe UI", 14), "text_color": SUB}
        for t, ic, c, tip in [
            ("🔄", "refrescar", self._refrescar_desde_raiz, "Refrescar"),
            ("➕", "agregar_archivo", self._agregar_archivos, "Agregar archivos"),
            ("📁", "agregar_carpeta", self._crear_nueva_carpeta, "Nueva carpeta"),
        ]:
            png = icons.icon(ic, 15)
            btn = ctk.CTkButton(hdr, text="" if png is not None else t,
                                image=png, command=c, **tb)
            btn.pack(side="right", padx=1)
            self._tooltip(btn, tip)

        self.tree_frame = ctk.CTkScrollableFrame(lp, fg_color="transparent")
        self.tree_frame.pack(fill="both", expand=True, padx=10, pady=(2, 14))
        ctk.CTkLabel(self.tree_frame,
                     text="Clic en '+ Nueva carpeta / archivo' para comenzar",
                     font=("Segoe UI", 12), text_color=SUB, wraplength=170,
                     justify="center").pack(pady=30)

        self._ctx = tk.Menu(self, tearoff=0, bg=PANEL, fg=TEXT,
                            activebackground=ACCENT, activeforeground="#FFFFFF",
                            font=("Segoe UI", 10), relief="flat", bd=0)
        self._ctx.add_command(label="  📁  Nueva carpeta", command=self._crear_nueva_carpeta)
        self._ctx.add_command(label="  📄  Agregar archivos", command=self._agregar_archivos)
        self._ctx.add_separator()
        self._ctx.add_command(label="  ✏️  Renombrar", command=self._renombrar_seleccion)
        self._ctx.add_command(label="  🗑️  Eliminar", command=self._eliminar_seleccion)
        self._ctx.add_separator()
        self._ctx.add_command(label="  🔄  Refrescar", command=self._refrescar_desde_raiz)

        for w in [self.tree_frame, self.tree_frame._parent_frame]:
            w.bind("<Button-3>", self._mostrar_ctx)
        try:
            self.tree_frame._parent_canvas.bind("<Button-3>", self._mostrar_ctx)
        except Exception:
            pass

    def _icono(self, nombre):
        return self._ICON.get(os.path.splitext(nombre)[1].lower(), "📄")

    def _root_label(self, path):
        path = path.replace("\\", "/")
        name = os.path.basename(path) or path
        if path in set(self._root_paths.values()):
            return next(k for k, v in self._root_paths.items() if v == path)
        label = name
        n = 2
        while label in self._root_paths:
            label = f"{name} ({n})"
            n += 1
        self._root_paths[label] = path
        return label

    def _normalize_folder_roots(self):
        roots = sorted({os.path.abspath(r).replace("\\", "/") for r in self._folder_roots}, key=len)
        top = []
        for r in roots:
            if not os.path.isdir(r):
                continue
            if any(r != t and r.startswith(t + "/") for t in top):
                continue
            top = [t for t in top if not (t != r and t.startswith(r + "/"))]
            top.append(r)
        self._folder_roots = top
        return top

    def _ensure_app_data_root(self):
        try:
            return str(ensure_app_data_root()).replace("\\", "/")
        except Exception as e:
            print(f"Advertencia: no se pudo preparar app_data_root: {e}")
            return None

    def _add_folder_root(self, path):
        path = os.path.abspath(path).replace("\\", "/")
        self._ensure_app_data_root()
        self._active_project_root = path
        self._selected_path = path
        if path not in self._folder_roots:
            self._folder_roots.append(path)
        self._normalize_folder_roots()
        self._archivos_actuales = [
            f for f in self._archivos_actuales
            if not self._under_folder_root(os.path.abspath(f).replace("\\", "/"))
        ]
        self._dir_cache.clear()

        # Sincronizar workspace del agente IA
        if hasattr(self, 'controlador_ia') and self.controlador_ia:
            # Workspace compuesto: registrar TODAS las raices, no solo la ultima.
            if hasattr(self.controlador_ia, "set_workspace_roots"):
                self.controlador_ia.set_workspace_roots(self._folder_roots)
            else:
                self.controlador_ia.set_workspace(path)
            self.controlador_ia.context_manager.set_active_path(path)

    def _repair_legacy_tree(self):
        if self._folder_roots or not self._archivos_actuales:
            return
        paths = [os.path.abspath(f).replace("\\", "/") for f in self._archivos_actuales]
        try:
            common = os.path.commonpath(paths).replace("\\", "/")
        except ValueError:
            return
        if os.path.isfile(common):
            common = os.path.dirname(common)
        if os.path.isdir(common):
            self._add_folder_root(common)

    def _invalidate_dir(self, path):
        p = os.path.abspath(path).replace("\\", "/")
        if os.path.isfile(p):
            p = os.path.dirname(p)
        while p and p not in ("", "/"):
            self._dir_cache.pop(p, None)
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent.replace("\\", "/")

    def _refresh_after_fs_change(self, path=None):
        if path:
            self._invalidate_dir(path)
        else:
            self._dir_cache.clear()
        self._rerender_explorador()

    def _under_folder_root(self, fpath):
        fpath = fpath.replace("\\", "/")
        for root in self._folder_roots:
            r = root.replace("\\", "/")
            if fpath == r or fpath.startswith(r + "/"):
                return True
        return False

    def _list_dir(self, path):
        path = os.path.abspath(path).replace("\\", "/")
        if path in self._dir_cache:
            return self._dir_cache[path]
        dirs, files = [], []
        try:
            with os.scandir(path) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        dirs.append(e.name)
                    elif e.is_file(follow_symlinks=False):
                        files.append(e.name)
        except OSError:
            pass
        dirs = filter_internal_names(dirs)
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        self._dir_cache[path] = (dirs, files)
        return dirs, files

    def _loose_groups(self):
        groups = {}
        for f in self._archivos_actuales:
            f = os.path.abspath(f).replace("\\", "/")
            if self._under_folder_root(f):
                continue
            parent = os.path.dirname(f)
            if self._under_folder_root(parent):
                continue
            groups.setdefault(parent, set()).add(os.path.basename(f))
        return {k: sorted(v, key=str.casefold) for k, v in groups.items()}

    def actualizar_explorador(self, archivos=None):
        if archivos is not None:
            self._archivos_actuales = archivos
        self._repair_legacy_tree()
        self._rerender_explorador()

    def _rerender_explorador(self):
        self._repair_legacy_tree()
        self._render_gen += 1
        self._do_render()

    def _do_render(self):
        self._nodes.clear()
        for w in self.tree_frame.winfo_children():
            w.destroy()
        if not self._folder_roots and not self._archivos_actuales:
            ctk.CTkLabel(self.tree_frame, text="Clic en '+ Agregar' para comenzar",
                         font=("Segoe UI", 12), text_color=SUB).pack(pady=30)
            return

        gen = self._render_gen
        self._root_paths = {}
        for root in self._normalize_folder_roots():
            label = self._root_label(root)
            self._render_dir(self.tree_frame, label, root, 0, gen, is_root=True)

        for parent, files in self._loose_groups().items():
            label = self._root_label(parent)
            self._render_loose(self.tree_frame, label, parent, files, gen)

    def _render_dir(self, parent, name, folder_abs, depth, gen, is_root=False, before=None):
        folder_abs = folder_abs.replace("\\", "/")
        indent = depth * 16
        cid = folder_abs

        if cid not in self._carpetas_expandidas:
            self._carpetas_expandidas[cid] = is_root
        exp = self._carpetas_expandidas[cid]
        # Escaneo/conteo diferido: solo se escanea la carpeta si esta expandida.
        # Para las colapsadas el conteo "(N)" se calcula luego en idle, evitando
        # un scandir sincrono por cada carpeta al expandir un arbol enorme.
        if exp:
            dirs, files = self._list_dir(folder_abs)
        else:
            dirs, files = None, None
        extra = ""

        node_frame = ctk.CTkFrame(parent, fg_color="transparent")
        if before is not None:
            node_frame.pack(fill="x", before=before)
        else:
            node_frame.pack(fill="x")

        row = ctk.CTkFrame(node_frame, fg_color="transparent", height=26)
        row.pack(fill="x", pady=0)
        row.pack_propagate(False)
        lbl = ctk.CTkLabel(row, text=f"{'▼' if exp else '▶'}  📁 {name}{extra}", anchor="w",
                           font=("Segoe UI", 12), text_color=TEXT, cursor="hand2")
        lbl.pack(fill="x", padx=(indent + 4, 4))
        self._bind_hover(row, lbl)
        lbl.bind("<Button-1>", lambda e, c=cid, p=folder_abs: self._toggle(c, p))
        row.bind("<Button-1>", lambda e, c=cid, p=folder_abs: self._toggle(c, p))
        lbl.bind("<Button-3>", lambda e, p=folder_abs: self._ctx_on(e, p))
        row.bind("<Button-3>", lambda e, p=folder_abs: self._ctx_on(e, p))

        content = ctk.CTkFrame(node_frame, fg_color="transparent")
        self._nodes[cid] = {"row": row, "lbl": lbl, "content": content,
                            "node_frame": node_frame, "folder_abs": folder_abs,
                            "depth": depth, "name": name, "dirs": dirs, "files": files}

        if exp:
            content.pack(fill="x")
            self._fill_dir(content, folder_abs, depth, gen, dirs, files)
        else:
            # Conteo diferido: no bloquea el render del arbol al expandir.
            self.after_idle(lambda c=cid, fa=folder_abs, g=gen: self._update_dir_count(c, fa, g))

    def _update_dir_count(self, cid, folder_abs, gen):
        """Calcula '(N)' de una carpeta colapsada en idle (sin congelar)."""
        if self._render_gen != gen:
            return
        node = self._nodes.get(cid)
        if not node or self._carpetas_expandidas.get(cid):
            return
        try:
            _, files = self._list_dir(folder_abs)
        except Exception:
            return
        node["files"] = files
        if files:
            try:
                node["lbl"].configure(text=f"▶  📁 {node.get('name', '')}  ({len(files)})")
            except Exception:
                pass

    def _fill_dir(self, content, folder_abs, depth, gen, dirs=None, files=None):
        if dirs is None or files is None:
            dirs, files = self._list_dir(folder_abs)
        # Subcarpetas por lotes (after_idle) para no congelar al expandir una
        # carpeta con miles de subcarpetas. Los archivos se renderizan al
        # terminar las carpetas, preservando el orden carpetas -> archivos.
        self._batch_dirs(content, dirs, 0, depth, gen, folder_abs, files)

    def _batch_dirs(self, content, dirs, idx, depth, gen, folder_abs, files, batch=_DIR_BATCH, cap=_DIR_CAP):
        if self._render_gen != gen:
            return
        # Solo se renderizan hasta 'cap' carpetas; el resto queda tras el boton
        # "Cargar mas carpetas" para no crear miles de widgets de golpe.
        limit = min(cap, len(dirs)) if cap else len(dirs)
        end = min(idx + batch, limit)
        for i in range(idx, end):
            self._render_dir(content, dirs[i], f"{folder_abs}/{dirs[i]}", depth + 1, gen)
        if end < limit:
            self.after_idle(lambda: self._batch_dirs(content, dirs, end, depth, gen,
                                                     folder_abs, files, batch, cap))
            return
        # Carpetas (cap) listas -> archivos, y luego el boton ANTES de los
        # archivos para conservar el orden carpetas -> [Cargar mas] -> archivos.
        files_frame = None
        if files:
            files_frame = ctk.CTkFrame(content, fg_color="transparent")
            files_frame.pack(fill="x")
            self._render_files(files_frame, files, depth + 1, (depth + 1) * 16, gen, folder_abs)
        if cap and len(dirs) > cap:
            indent = (depth + 1) * 16
            btn = ctk.CTkButton(
                content, text=f"⏬ Mostrando {cap} de {len(dirs)} carpetas. Cargar más…",
                height=24, fg_color="transparent", hover_color=HOVER,
                font=("Segoe UI", 11), text_color=ACCENT,
                command=lambda: self._load_more_dirs(content, dirs, cap, depth, gen, folder_abs, btn, files_frame),
            )
            if files_frame is not None:
                btn.pack(fill="x", padx=(indent + 4, 4), before=files_frame)
            else:
                btn.pack(fill="x", padx=(indent + 4, 4))

    def _load_more_dirs(self, content, dirs, start, depth, gen, folder_abs, btn, files_frame):
        if self._render_gen != gen:
            return
        try:
            btn.destroy()
        except Exception:
            pass
        self._batch_more_dirs(content, dirs, start, depth, gen, folder_abs, files_frame)

    def _batch_more_dirs(self, content, dirs, idx, depth, gen, folder_abs, files_frame, batch=_DIR_BATCH):
        if self._render_gen != gen:
            return
        end = min(idx + batch, len(dirs))
        for i in range(idx, end):
            self._render_dir(content, dirs[i], f"{folder_abs}/{dirs[i]}", depth + 1, gen,
                             before=files_frame)
        if end < len(dirs):
            self.after_idle(lambda: self._batch_more_dirs(content, dirs, end, depth, gen,
                                                          folder_abs, files_frame, batch))

    def _render_files(self, parent, files, depth, indent, gen, abs_path, offset=0):
        end = len(files) if offset else min(_FILE_CAP, len(files))
        chunk = files[offset:end]
        if chunk:
            self._batch_files(parent, chunk, 0, depth, indent, gen, abs_path, _FILE_BATCH)
        if not offset and len(files) > _FILE_CAP:
            btn = ctk.CTkButton(parent, text=f"⏬ Mostrando {_FILE_CAP} de {len(files)}. Cargar más…", height=24,
                                fg_color="transparent", hover_color=HOVER,
                                font=("Segoe UI", 11), text_color=ACCENT,
                                command=lambda p=parent, f=files, d=depth, i=indent,
                                g=gen, a=abs_path: self._load_more_files(p, f, d, i, g, a))
            btn.pack(fill="x", padx=(indent + 4, 4))

    def _load_more_files(self, parent, files, depth, indent, gen, abs_path):
        for w in parent.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.destroy()
                break
        self._batch_files(parent, files[_FILE_CAP:], 0, depth, indent, gen, abs_path, _FILE_BATCH)

    def _render_loose(self, parent, label, dir_path, files, gen):
        dir_path = dir_path.replace("\\", "/")
        cid = f"loose:{dir_path}"
        if cid not in self._carpetas_expandidas:
            self._carpetas_expandidas[cid] = True
        exp = self._carpetas_expandidas[cid]

        node_frame = ctk.CTkFrame(parent, fg_color="transparent")
        node_frame.pack(fill="x")

        row = ctk.CTkFrame(node_frame, fg_color="transparent", height=26)
        row.pack(fill="x", pady=0)
        row.pack_propagate(False)
        lbl = ctk.CTkLabel(row, text=f"{'▼' if exp else '▶'}  📁 {label}", anchor="w",
                           font=("Segoe UI", 12), text_color=TEXT, cursor="hand2")
        lbl.pack(fill="x", padx=(4, 4))
        self._bind_hover(row, lbl)
        lbl.bind("<Button-1>", lambda e, c=cid: self._toggle_loose(c))
        row.bind("<Button-1>", lambda e, c=cid: self._toggle_loose(c))

        content = ctk.CTkFrame(node_frame, fg_color="transparent")
        self._nodes[cid] = {"row": row, "lbl": lbl, "content": content,
                            "node_frame": node_frame, "files": files,
                            "dir_path": dir_path, "label": label}

        if exp:
            content.pack(fill="x")
            self._render_files(content, files, 1, 16, gen, dir_path)

    def _batch_files(self, parent, files, idx, depth, indent, gen, abs_path, batch=_FILE_BATCH):
        if self._render_gen != gen:
            return
        end = min(idx + batch, len(files))
        for i in range(idx, end):
            self._render_file(parent, files[i], indent, abs_path)
        if end < len(files):
            self.after_idle(lambda p=parent, f=files, e=end, d=depth, ind=indent, g=gen, a=abs_path, b=batch:
                            self._batch_files(p, f, e, d, ind, g, a, b))

    def _render_file(self, parent, archivo, indent, abs_path):
        file_abs = os.path.join(abs_path, archivo).replace("\\", "/")
        lbl = tk.Label(parent, text=f"    {self._icono(archivo)}  {archivo}", anchor="w",
                       bg=PANEL, fg=TEXT, font=("Segoe UI", 11), cursor="hand2",
                       padx=indent + 4, pady=1)
        lbl.pack(fill="x")
        self._bind_hover_file(lbl)
        lbl.bind("<Button-1>", lambda e, p=file_abs, w=lbl: self._select(p, w))
        lbl.bind("<Button-3>", lambda e, p=file_abs: self._ctx_on(e, p))

    def _tooltip(self, widget, text):
        tip = [None]
        def show(_):
            if tip[0]:
                return
            tw = tk.Toplevel(widget)
            tw.wm_overrideredirect(True)
            tw.configure(bg="#1E293B")
            tw.wm_geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 4}")
            tk.Label(tw, text=text, bg="#1E293B", fg="#E2E8F0",
                     font=("Segoe UI", 10), padx=8, pady=4).pack()
            tip[0] = tw
        def hide(_):
            if tip[0]:
                tip[0].destroy()
                tip[0] = None
        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    def _bind_hover_file(self, lbl):
        lbl.bind("<Enter>", lambda e, w=lbl: w.configure(bg=HOVER))
        lbl.bind("<Leave>", lambda e, w=lbl: w.configure(
            bg=SELECT if w == self._selected_widget else PANEL))

    def _bind_hover(self, row, lbl):
        enter = lambda e, r=row: r.configure(fg_color=HOVER)
        leave = lambda e, r=row: r.configure(
            fg_color=SELECT if r == self._selected_widget else "transparent")
        for w in (row, lbl):
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def _toggle(self, cid, folder_abs=None):
        exp = not self._carpetas_expandidas.get(cid, False)
        self._carpetas_expandidas[cid] = exp
        if folder_abs:
            self._selected_path = folder_abs
        node = self._nodes.get(cid)
        if not node:
            self._rerender()
            return

        _, files = self._list_dir(node["folder_abs"])
        extra = f"  ({len(files)})" if not exp and files else ""
        node["lbl"].configure(text=f"{'▼' if exp else '▶'}  📁 {node['name']}{extra}")

        if exp:
            dirs, files = self._list_dir(node["folder_abs"])
            node["dirs"], node["files"] = dirs, files
            for w in node["content"].winfo_children():
                w.destroy()
            node["content"].pack(fill="x")
            self._fill_dir(node["content"], node["folder_abs"], node["depth"],
                           self._render_gen, dirs, files)
        else:
            node["content"].pack_forget()
            for w in node["content"].winfo_children():
                w.destroy()
        
        self.guardar_espacio_trabajo()

    def _toggle_loose(self, cid):
        exp = not self._carpetas_expandidas.get(cid, False)
        self._carpetas_expandidas[cid] = exp
        node = self._nodes.get(cid)
        if not node:
            self._rerender()
            return
        node["lbl"].configure(text=f"{'▼' if exp else '▶'}  📁 {node['label']}")
        if exp:
            for w in node["content"].winfo_children():
                w.destroy()
            node["content"].pack(fill="x")
            self._render_files(node["content"], node["files"], 1, 16,
                               self._render_gen, node["dir_path"])
        else:
            node["content"].pack_forget()
            for w in node["content"].winfo_children():
                w.destroy()
        
        self.guardar_espacio_trabajo()

    def _select(self, path, widget):
        if self._selected_widget:
            try:
                if isinstance(self._selected_widget, tk.Label):
                    self._selected_widget.configure(bg=PANEL)
                else:
                    self._selected_widget.configure(fg_color="transparent")
            except Exception:
                pass
        self._selected_path = path
        self._selected_widget = widget
        try:
            if hasattr(self, "controlador_ia") and self.controlador_ia and path:
                active = path if os.path.isdir(path) else os.path.dirname(path)
                self.controlador_ia.context_manager.set_active_path(active)
        except Exception:
            pass
        if isinstance(widget, tk.Label):
            widget.configure(bg=SELECT)
        else:
            widget.configure(fg_color=SELECT)
        if path:
            self._mostrar_imagen(path)

    def _rerender(self):
        self._repair_legacy_tree()
        self._render_gen += 1
        self._do_render()

    def _mostrar_ctx(self, event):
        self._ctx_target = self._folder_roots[-1] if self._folder_roots else None
        try:
            self._ctx.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx.grab_release()

    def _ctx_on(self, event, path):
        self._ctx_target = path or (self._folder_roots[-1] if self._folder_roots else None)
        try:
            self._ctx.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx.grab_release()

    def _target_dir(self):
        t = self._ctx_target
        self._ctx_target = None
        if not t:
            t = self._selected_path or (self._folder_roots[-1] if self._folder_roots else None)
        if not t:
            return None
        t = t.replace("\\", "/")
        return t if os.path.isdir(t) else os.path.dirname(t)

    def _crear_nueva_carpeta(self):
        print("DEBUG: boton _crear_nueva_carpeta presionado")
        d = self._target_dir()
        print(f"DEBUG: target_dir = {d}")
        
        if not d:
            if self._folder_roots:
                d = self._folder_roots[-1]
                print(f"DEBUG: usando última carpeta raíz: {d}")
            else:
                print("DEBUG: sin carpeta, no se puede crear")
                return
        
        nombre = ctk.CTkInputDialog(text="Nombre de la carpeta:", title="Nueva Carpeta").get_input()
        print(f"DEBUG: nombre ingresado = {nombre}")
        if nombre and nombre.strip():
            try:
                ruta_nueva = os.path.join(d, nombre.strip())
                print(f"DEBUG: creando carpeta en {ruta_nueva}")
                os.makedirs(ruta_nueva, exist_ok=True)
                self._refresh_after_fs_change(d)
                self.guardar_espacio_trabajo()
                print(f"DEBUG: carpeta creada exitosamente")
            except Exception as e:
                print(f"❌ Error creando carpeta: {e}")

    def _agregar_archivos(self):
        print("DEBUG: boton _agregar_archivos presionado")
        d = self._target_dir()
        print(f"DEBUG: target_dir = {d}")
        if d:
            print(f"DEBUG: llamando _seleccionar_archivos con target_dir={d}")
            self.backend._seleccionar_archivos(target_dir=d)
        else:
            print("DEBUG: llamando _seleccionar_archivos sin target_dir")
            self.backend._seleccionar_archivos()

    def _renombrar_seleccion(self):
        path = self._ctx_target or self._selected_path
        self._ctx_target = None
        if not path or not os.path.exists(path):
            return
        viejo = os.path.basename(path)
        nuevo = ctk.CTkInputDialog(text=f"Renombrar '{viejo}' a:", title="Renombrar").get_input()
        if nuevo and nuevo.strip():
            try:
                os.rename(path, os.path.join(os.path.dirname(path), nuevo.strip()))
                self._refresh_after_fs_change(path)
                self.guardar_espacio_trabajo()
            except Exception as e:
                print(f"❌ {e}")

    def _eliminar_seleccion(self):
        path = self._ctx_target or self._selected_path
        self._ctx_target = None
        if not path or not os.path.exists(path):
            return
        nombre = os.path.basename(path)
        confirm = ctk.CTkInputDialog(
            text=f"Escribe 'si' para eliminar:\n{nombre}",
            title="Confirmar eliminación"
        ).get_input()
        if confirm and confirm.strip().lower() in ("si", "sí", "yes"):
            self._delete_path_async(path)

    def _delete_path_async(self, path):
        """Elimina en un hilo para no congelar la UI con carpetas grandes.
        El refresco del árbol vuelve al hilo de UI vía after(). Devuelve el
        Thread (útil para tests)."""
        path = os.path.abspath(path).replace("\\", "/")
        try:
            self._viewer_title.configure(text=f"Eliminando '{os.path.basename(path)}'…")
        except Exception:
            pass

        def _worker():
            error = None
            try:
                from core.safe_delete import send_to_recycle_bin
                send_to_recycle_bin(path)
            except Exception as e:
                error = e
            self.after(0, lambda: self._after_fs_delete(path, error))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return t

    def _after_fs_delete(self, path, error):
        try:
            self._viewer_title.configure(text="Selecciona un archivo")
        except Exception:
            pass
        if error:
            print(f"❌ Error eliminando '{path}': {error}")
        if self._selected_path and (
            self._selected_path == path or self._selected_path.startswith(path + "/")
        ):
            self._selected_path = None
            self._selected_widget = None
        self._refresh_after_fs_change(path)
        self.guardar_espacio_trabajo()

    def _refrescar_desde_raiz(self):
        if not self._folder_roots and not self._archivos_actuales:
            return
        self._dir_cache.clear()
        self._repair_legacy_tree()
        self._rerender_explorador()

    def _abrir_en_explorador(self):
        t = self._ctx_target or self._selected_path or (self._folder_roots[-1] if self._folder_roots else None)
        self._ctx_target = None
        if not t:
            return
        if os.path.isfile(t):
            t = os.path.dirname(t)
        try:
            os.startfile(t)
        except Exception:
            pass

    def _on_drop(self, paths):
        changed = False
        for p in paths:
            path = p.decode("utf-8") if isinstance(p, bytes) else str(p)
            path = path.strip()
            if os.path.isdir(path):
                self._add_folder_root(path)
                changed = True
            elif os.path.isfile(path):
                self._archivos_actuales.append(os.path.abspath(path).replace("\\", "/"))
                changed = True
        if changed:
            self._archivos_actuales = sorted(set(self._archivos_actuales))
            self._dir_cache.clear()
            self._rerender_explorador()
            self.guardar_espacio_trabajo()

    def _crear_panel_central(self, parent):
        # Estado del visor para zoom/paneo (capa visual, no toca el motor).
        self._pan_mode = False
        self._pan_off = [0, 0]
        self._pan_start = None

        cp = ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)
        cp.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        cp.grid_columnconfigure(0, weight=1)
        cp.grid_rowconfigure(1, weight=1)

        # --- Topbar: nombre del archivo seleccionado ---
        topbar = ctk.CTkFrame(cp, height=42, fg_color="transparent")
        topbar.grid(row=0, column=0, sticky="ew")
        self._viewer_title = ctk.CTkLabel(topbar, text="Selecciona un archivo",
                                          font=theme.FONT_H3, text_color=TEXT)
        self._viewer_title.pack(side="left", padx=6)

        # --- Fila central: visor a TODO el ancho (se retiró "Mejor coincidencia") ---
        midrow = ctk.CTkFrame(cp, fg_color="transparent")
        midrow.grid(row=1, column=0, sticky="nsew", pady=(8, 14))
        midrow.grid_columnconfigure(0, weight=1)
        midrow.grid_rowconfigure(0, weight=1)

        self._viewer_frame = ctk.CTkFrame(midrow, fg_color=PANEL,
                                          corner_radius=theme.RADIUS_XL,
                                          border_width=1, border_color=BORDER)
        self._viewer_frame.grid(row=0, column=0, sticky="nsew")
        self._viewer_frame.grid_columnconfigure(0, weight=1)
        self._viewer_frame.grid_rowconfigure(0, weight=1)

        # Área de imagen: el label se posiciona con place para permitir paneo.
        self._viewer_img_area = ctk.CTkFrame(self._viewer_frame, fg_color="transparent")
        self._viewer_img_area.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        self._viewer_label = ctk.CTkLabel(
            self._viewer_img_area,
            text="VISOR DE IMÁGENES\n\nSelecciona una imagen del explorador",
            font=("Segoe UI", 20, "bold"), text_color=SUB)
        self._viewer_label.place(relx=0.5, rely=0.5, anchor="center")

        for w in (self._viewer_label,):
            w.bind("<ButtonPress-1>", self._on_pan_press)
            w.bind("<B1-Motion>", self._on_pan_move)
            w.bind("<ButtonRelease-1>", self._on_pan_release)
            w.bind("<MouseWheel>", self._zoom_wheel)
        try:
            inner = self._viewer_label._label
            inner.bind("<ButtonPress-1>", self._on_pan_press)
            inner.bind("<B1-Motion>", self._on_pan_move)
            inner.bind("<ButtonRelease-1>", self._on_pan_release)
            inner.bind("<MouseWheel>", self._zoom_wheel)
        except Exception:
            pass
        self._viewer_img_area.bind("<MouseWheel>", self._zoom_wheel)

        # Toolbar del visor: zoom +, zoom -, mano (paneo)
        controls = ctk.CTkFrame(self._viewer_frame, fg_color="transparent", height=50)
        controls.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        tbtn = {"width": 42, "height": 38, "corner_radius": theme.RADIUS_MD,
                "fg_color": CARD, "hover_color": ACCENT, "font": ("Segoe UI", 15)}
        ctk.CTkButton(controls, text="🔍+", command=self._zoom_in, **tbtn).pack(side="left", padx=5)
        ctk.CTkButton(controls, text="🔍-", command=self._zoom_out, **tbtn).pack(side="left", padx=5)
        self._btn_pan = ctk.CTkButton(controls, text="✋", command=self._toggle_pan, **tbtn)
        self._btn_pan.pack(side="left", padx=5)
        self._tooltip(self._btn_pan, "Mover imagen (paneo)")
        btn_rot = ctk.CTkButton(controls, text="⟳", command=self._rotar_imagen, **tbtn)
        btn_rot.pack(side="left", padx=5)
        self._tooltip(btn_rot, "Rotar 90° (solo vista)")

        # --- Acciones rápidas ---
        ctk.CTkLabel(cp, text="Acciones rápidas", font=theme.FONT_H2,
                     text_color=theme.CYAN).grid(row=2, column=0, sticky="w", pady=(2, 10))
        af = ctk.CTkFrame(cp, fg_color="transparent")
        af.grid(row=3, column=0, sticky="ew")
        af.grid_columnconfigure((0, 1, 2), weight=1, uniform="qa")

        actions = [
            ("📗", "Leer Excel", "Carga y valida tu Excel de referencia",
             self._accion_leer_excel, "Leer Excel"),
            ("📁", "Crear carpetas", "Crea la estructura de carpetas",
             self._accion_crear_carpetas, "Crear carpetas"),
            ("🚀", "Clasificar fotos", "Clasifica las fotos según coincidencias",
             self._accion_clasificar, "Clasificar fotos"),
        ]
        self.action_cards = []
        for i, spec in enumerate(actions):
            self._crear_action_card(af, i, *spec)

        # --- Barra de progreso (lote activo) ---
        self._crear_progreso_lote(cp)

    def _crear_action_card(self, parent, col, icon, title, desc, cmd, name):
        """Tarjeta de acción rápida. Estructura compatible con DashboardBackend
        (claves card/title/desc/cmd/name + layout por pack para que el backend
        pueda empaquetar su barra de progreso en la tarjeta de clasificación)."""
        card = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=theme.RADIUS_LG,
                            border_width=1, border_color=BORDER, height=132)
        card.grid(row=0, column=col, padx=(0 if col == 0 else 12, 0), sticky="nsew")
        card.grid_propagate(False)
        card.pack_propagate(False)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(14, 4))
        _card_png = {"Leer Excel": "excel", "Crear carpetas": "carpeta",
                     "Clasificar fotos": "clasificar"}.get(name)
        png = icons.icon(_card_png, 24) if _card_png else None
        if png is not None:
            ctk.CTkLabel(top, image=png, text="", fg_color="transparent",
                         width=30, height=34).pack(side="left")
        else:
            ctk.CTkLabel(top, text=icon, font=("Segoe UI", 18),
                         fg_color="transparent", width=30, height=34,
                         text_color=theme.CYAN).pack(side="left")
        lbl_title = ctk.CTkLabel(top, text=title, font=("Segoe UI", 15, "bold"),
                                 text_color=TEXT, cursor="hand2")
        lbl_title.pack(side="left", padx=(10, 0))

        lbl_desc = ctk.CTkLabel(card, text=desc, font=("Segoe UI", 11), text_color=SUB,
                                wraplength=210, justify="left", anchor="w", cursor="hand2")
        lbl_desc.pack(anchor="w", padx=14, pady=(0, 8))

        self.action_cards.append({"card": card, "title": lbl_title,
                                  "desc": lbl_desc, "cmd": cmd, "name": name})

        # Responsive: en pantallas chicas (1366x768) la tarjeta se estrecha y
        # el título/descripción se cortaban. Se adaptan al ancho real.
        def _responsive(e, t=lbl_title, d=lbl_desc):
            try:
                w = e.width
                size = 15 if w >= 210 else (13 if w >= 175 else 12)
                t.configure(font=("Segoe UI", size, "bold"))
                d.configure(wraplength=max(90, w - 30))
            except Exception:
                pass
        card.bind("<Configure>", _responsive, add="+")

        def handler(event, command=cmd):
            command()
        for w in (card, lbl_title, lbl_desc):
            w.bind("<Button-1>", handler)
        card.bind("<Enter>", lambda e, c=card: c.configure(border_color=ACCENT))
        card.bind("<Leave>", lambda e, c=card: c.configure(border_color=BORDER))

    def _crear_progreso_lote(self, parent):
        """Barra de proceso bajo las acciones. Estado inactivo por defecto; el
        progreso de clasificación activo se muestra en la tarjeta (mecanismo
        existente del backend, intacto)."""
        strip = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=theme.RADIUS_LG,
                             border_width=1, border_color=BORDER, height=58)
        strip.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        strip.grid_propagate(False)
        strip.grid_columnconfigure(1, weight=1)

        self._lote_dot = ctk.CTkLabel(strip, text="●", text_color=theme.TEXT_MUTE,
                                      font=("Segoe UI", 12))
        self._lote_dot.grid(row=0, column=0, padx=(16, 8), pady=18)
        self._lote_label = ctk.CTkLabel(strip, text="Sin proceso activo",
                                        font=theme.FONT_SUB, text_color=SUB, anchor="w")
        self._lote_label.grid(row=0, column=1, sticky="w")
        self._lote_bar = ctk.CTkProgressBar(strip, width=220, height=6, corner_radius=3,
                                            progress_color=ACCENT)
        self._lote_bar.set(0)
        self._lote_bar.grid(row=0, column=2, padx=16)

    # ---- Acciones rápidas: placeholders premium (modales en Fase 7) ----
    def _accion_leer_excel(self):
        if not self._folder_roots:
            self._toast("Agrega una carpeta al workspace primero.")
            return
        if not getattr(self, "controlador_ia", None):
            self._toast("El asistente no está disponible todavía.")
            return
        from facesyncApp.ui.modals import LeerExcelModal
        LeerExcelModal(self, roots=list(self._folder_roots),
                       on_read=self._leer_excel_adapter)

    def _leer_excel_adapter(self, path):
        """Adaptador delgado al flujo de lectura YA existente (el mismo del chat):
        local_router.try_handle('lee <archivo>') detecta columnas y actualiza el
        contexto. Devuelve un resumen leído del contexto. NO toca motor/backend."""
        nombre = os.path.basename(path)
        res = self.controlador_ia.local_router.try_handle(f"lee {nombre}")
        cm = self.controlador_ia.context_manager
        cols = (cm.get_context("available_columns")
                or cm.get_context("last_table_columns") or [])
        ok = (getattr(res, "action", None) == "read_document") and bool(cols)
        return {
            "ok": ok,
            "columns": list(cols),
            "name_col": cm.get_context("last_name_column"),
            "ref_col": cm.get_context("last_reference_column"),
            "rows": cm.get_context("last_table_rows"),
            "message": "" if ok else (getattr(res, "message", "") or
                                      "No se reconoció como tabla legible."),
        }

    def _accion_crear_carpetas(self):
        if not self._folder_roots:
            self._toast("Agrega una carpeta al workspace primero.")
            return
        if not getattr(self, "controlador_ia", None):
            self._toast("El asistente no está disponible todavía.")
            return
        cm = self.controlador_ia.context_manager
        prefill = None
        ltp = cm.get_context("last_table_path")
        cols = cm.get_context("available_columns") or cm.get_context("last_table_columns")
        if ltp and cols:
            prefill = {"path": ltp, "columns": list(cols),
                       "name_col": cm.get_context("last_name_column")}
        from facesyncApp.ui.modals import CrearCarpetasModal
        CrearCarpetasModal(self, roots=list(self._folder_roots), prefill=prefill,
                           on_columns=self._leer_excel_adapter,
                           on_preview=self._crear_carpetas_preview,
                           on_create=self._crear_carpetas_adapter)

    def _crear_carpetas_preview(self, path, column):
        """Vista previa SOLO LECTURA: una carpeta por registro (los nombres
        repetidos se numeran como hace el backend). No crea nada. Corre en worker
        (solo lee el archivo con pandas)."""
        try:
            import pandas as pd
        except Exception:
            return []
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in (".xlsx", ".xls"):
                df = pd.read_excel(path)
            elif ext == ".csv":
                df = pd.read_csv(path)
            else:
                return []
        except Exception:
            return []
        if column not in df.columns:
            return []
        seen, out = {}, []
        for v in df[column].tolist():
            s = str(v).strip()
            if not s or s.lower() == "nan":
                continue
            if s in seen:
                seen[s] += 1
                out.append(f"{s} ({seen[s]})")
            else:
                seen[s] = 1
                out.append(s)
        return out[:2000]

    def _crear_carpetas_adapter(self, table_path, name_column, destination):
        """Adaptador delgado al ejecutor existente del router (mismo backend que
        usa el chat). Corre en hilo UI (toca contexto/seguridad). NO toca motor."""
        res = self.controlador_ia.local_router._structured_create_folders_from_table({
            "table_path": table_path,
            "name_column": name_column,
            "destination_folder": destination,
        })
        if not res or not res.get("success"):
            msg = ((res or {}).get("error") or (res or {}).get("question")
                   or "No se pudieron crear las carpetas.")
            return {"ok": False, "message": msg}
        d = res.get("data", {})
        if res.get("refresh"):
            try:
                self._refresh_after_fs_change(destination)
            except Exception:
                pass
        return {
            "ok": True,
            "created": d.get("folders_created", 0),
            "reused": len(d.get("reused_items", []) or []),
            "destination": d.get("destination", destination),
            "items": d.get("created_items", []) or [],
        }

    def _accion_clasificar(self):
        if not self._folder_roots:
            self._toast("Agrega una carpeta al workspace primero.")
            return
        if not getattr(self, "controlador_ia", None):
            self._toast("El asistente no está disponible todavía.")
            return
        if getattr(self.controlador_ia, "_worker_activo", False):
            self._toast("Ya hay una tarea en curso. Espera o cancélala.")
            return
        cm = self.controlador_ia.context_manager
        prefill = None
        ltp = cm.get_context("last_table_path")
        cols = cm.get_context("available_columns") or cm.get_context("last_table_columns")
        if ltp and cols:
            prefill = {"path": ltp, "columns": list(cols),
                       "name_col": cm.get_context("last_name_column"),
                       "ref_col": cm.get_context("last_reference_column")}
        from facesyncApp.ui.modals import ClasificarFotosModal
        ClasificarFotosModal(self, roots=list(self._folder_roots), prefill=prefill,
                             on_columns=self._leer_excel_adapter,
                             on_classify=self._clasificar_adapter)

    def _clasificar_adapter(self, args):
        """Lanza la clasificación con el flujo EXISTENTE (sin duplicar motor):
        corre el ejecutor estructurado del router en un worker. El progreso usa la
        ventana de progreso del asistente (async_callback ya conectado) y la
        cancelación usa request_cancel() (botón Cancelar de esa ventana). NO llama
        al motor directamente ni salta worker/progreso/cancelación."""
        ia = self.controlador_ia
        if getattr(ia, "_worker_activo", False):
            return False
        ia._worker_activo = True
        self._clasificar_q = queue.Queue()

        def worker():
            try:
                res = ia.local_router._structured_run_reference_face_matching(args)
                ok = bool(res and res.get("success"))
                msg = "" if ok else (res or {}).get("error", "Error en la clasificación.")
            except Exception as e:
                ok, msg = False, f"{type(e).__name__}: {e}"
            self._clasificar_q.put((ok, msg))

        threading.Thread(target=worker, daemon=True).start()
        self._clasificar_poll()
        return True

    def _clasificar_poll(self):
        """Sondea el fin del worker desde el hilo de UI (fiable; a diferencia de
        after() llamado desde el worker). El progreso/cancelación siguen usando
        la ventana de progreso del asistente vía su async_callback existente."""
        try:
            ok, msg = self._clasificar_q.get_nowait()
        except queue.Empty:
            self.after(150, self._clasificar_poll)
            return
        self._clasificar_finalizado(ok, msg)

    def _clasificar_finalizado(self, ok, msg):
        ia = self.controlador_ia
        ia._worker_activo = False
        try:
            self._chat_typing_remove()
        except Exception:
            pass
        # Restaurar el botón de envío del chat por si quedó deshabilitado al cancelar.
        try:
            ia.boton_enviar.configure(state="normal", text="➜", command=ia.procesar_mensaje)
        except Exception:
            pass
        # Si falló (y no fue cancelación), asegurar que la ventana de progreso lo muestre.
        if not ok and msg and "cancel" not in str(msg).lower():
            try:
                ia._on_facesync_async_result(False, msg, {})
            except Exception:
                pass
        try:
            self._refresh_after_fs_change(None)
        except Exception:
            pass

    # ==========================================================
    # EXPORTAR A DRIVE (Fase 7.4) — modal premium + backend existente
    # ==========================================================
    def _drive_token_path(self):
        from oauth_service import token_path_for_account
        return token_path_for_account(self.email_usuario)

    def _accion_exportar_drive(self):
        if not self._folder_roots:
            self._toast("Agrega una carpeta al workspace primero.")
            return
        try:
            from facesyncApp.dashboardback import GOOGLE_API_AVAILABLE
        except Exception:
            GOOGLE_API_AVAILABLE = False
        token_path = self._drive_token_path()
        token_ok = bool(GOOGLE_API_AVAILABLE) and os.path.exists(token_path)
        if not GOOGLE_API_AVAILABLE:
            reason = ("Faltan dependencias de Google API. Instala "
                      "google-auth-oauthlib y google-api-python-client.")
        elif not os.path.exists(token_path):
            reason = (f"No hay credenciales de Google Drive para {self.email_usuario}. "
                      "Inicia sesión / configura tu cuenta primero.")
        else:
            reason = ""
        from facesyncApp.ui.modals import ExportarDriveModal
        ExportarDriveModal(self, roots=list(self._folder_roots), token_ok=token_ok,
                           token_reason=reason, on_export=self._exportar_drive_adapter)

    def _exportar_drive_adapter(self, picker_modal, folder_path):
        """Lanza la exportación con el backend EXISTENTE y muestra una ventana
        glass de progreso/finalización. NO reescribe subida/auth/reintentos:
        - apunta pb_drive/lbl_drive_count a la barra/contador de la ventana (el
          backend los actualiza vía _refrescar_ui, con guardas hasattr);
        - redirige el messagebox final del backend a la ventana (sin tocar el
          código del backend) para mostrar el resumen elegante, no un alert."""
        if getattr(self, "_drive_exporting", False):
            self._toast("Ya hay una exportación a Drive en curso.")
            return
        token_path = self._drive_token_path()
        import facesyncApp.dashboardback as dbk
        from facesyncApp.ui.modals import DriveProgressModal
        real_mb = dbk.messagebox
        state = {"restored": False, "finished": False}

        def _restore():
            # Idempotente: restaura el messagebox y libera el flag de exportación.
            if not state["restored"]:
                state["restored"] = True
                try:
                    dbk.messagebox = real_mb
                except Exception:
                    pass
            self._drive_exporting = False

        # Ventana de progreso NO bloqueante; al ocultarse restaura el messagebox.
        prog = DriveProgressModal(self, folder_name=os.path.basename(folder_path),
                                  folder_path=folder_path, on_close=_restore)
        self._drive_exporting = True
        self.pb_drive = prog.bar       # proxies (no widgets reales)
        self.lbl_drive_count = prog.count
        try:
            if hasattr(self, "_lote_label"):
                self._lote_label.configure(text="Exportando a Drive…", text_color=SUB)
                self._lote_dot.configure(text_color=theme.ACCENT)
        except Exception:
            pass

        def _done(kind, message):
            if state["finished"]:
                return
            state["finished"] = True
            _restore()
            try:
                prog.finish(kind, message)
            except Exception:
                pass
            # Historial de exportaciones (alimenta Inicio/Reportes/Exportaciones).
            try:
                import re as _re
                from facesyncApp.ui import report_data as _rd
                m = _re.search(r"(\d+)\s*/\s*(\d+)", str(message or ""))
                _rd.append_export(self.email_usuario, {
                    "nombre": os.path.basename(folder_path) or folder_path,
                    "tipo": "Drive",
                    "estado": {"ok": "Completado", "warn": "Parcial"}.get(kind, "Error"),
                    "subidos": int(m.group(1)) if m else None,
                    "total": int(m.group(2)) if m else None,
                    "origen": folder_path,
                    "destino": "Google Drive",
                })
            except Exception:
                pass
            try:
                if hasattr(self, "_lote_label"):
                    self._lote_label.configure(text="Sin proceso activo", text_color=SUB)
                    self._lote_dot.configure(text_color=theme.TEXT_MUTE)
            except Exception:
                pass

        class _FakeMB:
            def showinfo(self_, title=None, message=None, **k):
                _done("ok", message)

            def showwarning(self_, title=None, message=None, **k):
                _done("warn", message)

            def showerror(self_, title=None, message=None, **k):
                _done("error", message)

        try:
            dbk.messagebox = _FakeMB()
        except Exception:
            pass

        display = os.path.basename(folder_path) or folder_path
        mapa_rutas = {display: folder_path}
        try:
            self.backend._ejecutar_subida_drive(picker_modal, None, display, mapa_rutas, token_path)
        except Exception as e:
            _done("error", f"{type(e).__name__}: {e}")

    # ==========================================================
    # MEJOR COINCIDENCIA (Fase 7.5) — SOLO lee resultados ya generados
    # ==========================================================
    def _instalar_lote_hook(self):
        """Envuelve el async_callback del router para reflejar el progreso de
        clasificación TAMBIÉN en la barra 'lote activo', sin cambiar el backend ni
        romper la FaceSyncProgressWindow existente. (Drive ya alimenta esta barra
        vía el shim pb_drive/lbl_drive_count de la Fase 7.4.)"""
        ia = getattr(self, "controlador_ia", None)
        router = getattr(ia, "local_router", None) if ia else None
        if not router or getattr(router, "_lote_hooked", False):
            return
        orig = router.async_callback

        def wrapper(success, message, data):
            if orig:
                try:
                    orig(success, message, data)
                except Exception:
                    pass
            try:
                self.after(0, self._lote_update, dict(data or {}))
            except Exception:
                pass

        router.async_callback = wrapper
        router._lote_hooked = True

        # La ventana premium de RESULTADOS reemplaza el estado final de la
        # ventanita de progreso: si los resultados ya están visibles, el panel
        # viejo no debe re-crearse para mostrar "Finalizado" (wrapper en
        # runtime; agente_ia NO se edita y progreso/cancelación siguen igual).
        orig_panel = ia._actualizar_panel_progreso

        def _pw_viva():
            pw = getattr(ia, "_progress_window", None)
            try:
                return pw if (pw is not None and pw.winfo_exists()) else None
            except Exception:
                return None

        def _ventanitas_progreso():
            # TODAS las ventanas de progreso vivas (incluye huérfanas que la
            # referencia ia._progress_window ya no apunta).
            try:
                from facesyncApp.agente_ia import FaceSyncProgressWindow
            except Exception:
                return []
            vivas = []
            try:
                for w in self.winfo_children():
                    try:
                        if isinstance(w, FaceSyncProgressWindow) and w.winfo_exists():
                            vivas.append(w)
                    except Exception:
                        pass
            except Exception:
                pass
            return vivas

        def _habilitar_cerrar():
            # La ventana clásica deja "Cerrar" DESHABILITADO tras cancelar
            # (cancel_action lo deshabilita y update_progress no lo re-habilita).
            # Las huérfanas se vuelven SIEMPRE cerrables.
            actual = _pw_viva()
            for w in _ventanitas_progreso():
                try:
                    if w is actual:
                        w.btn_cancel.configure(state="normal")
                    else:
                        w.btn_cancel.configure(text="Cerrar", state="normal",
                                               command=w.destroy)
                except Exception:
                    pass

        def _cerrar_ventanitas():
            for w in _ventanitas_progreso():
                try:
                    w.destroy()
                except Exception:
                    pass

        self._cerrar_ventanitas_progreso = _cerrar_ventanitas

        def panel_wrapper(data):
            ph = (data or {}).get("phase") or (data or {}).get("stage")
            if ph in ("done", "completed", "finalizado") and self._resultados_visibles():
                _cerrar_ventanitas()
                return
            if ph in ("canceled", "cancelado") and _pw_viva() is None:
                # El usuario ya cerró la ventana: no resucitarla solo para
                # confirmar la cancelación; pero deja cerrables las huérfanas.
                _habilitar_cerrar()
                return
            # Guarda anti-reentrada: crear la CTkToplevel procesa eventos
            # pendientes y puede RE-ENTRAR aquí con el siguiente payload ANTES
            # de que ia._progress_window quede asignada -> se creaban DOS
            # ventanitas (una huérfana imposible de cerrar). Si hay una creación
            # en curso, este payload se reagenda y actualiza la ventana única.
            if getattr(self, "_panel_progreso_creando", False):
                try:
                    self.after(60, panel_wrapper, data)
                except Exception:
                    pass
                return
            creando = _pw_viva() is None
            if creando:
                self._panel_progreso_creando = True
            try:
                orig_panel(data)
            finally:
                if creando:
                    self._panel_progreso_creando = False
            if ph in ("done", "completed", "finalizado", "canceled", "cancelado", "error"):
                _habilitar_cerrar()

        ia._actualizar_panel_progreso = panel_wrapper

        # Al pulsar Cancelar, re-habilitar "Cerrar" de inmediato (la confirmación
        # real del motor puede tardar si va a mitad de una foto; mientras tanto la
        # ventana debe poderse cerrar).
        orig_cancel = ia.cancelar_tarea_actual

        def cancel_wrapper():
            orig_cancel()
            try:
                self.after(80, _habilitar_cerrar)
            except Exception:
                pass

        ia.cancelar_tarea_actual = cancel_wrapper

    def _lote_update(self, data):
        if not hasattr(self, "_lote_label"):
            return
        percent = data.get("percent")
        current = data.get("current")
        total = data.get("total")
        message = data.get("message")
        phase = data.get("phase") or data.get("stage")
        if percent is None and current is not None and total:
            try:
                percent = (current / total) * 100
            except Exception:
                percent = None
        if percent is not None:
            try:
                self._lote_bar.set(min(1.0, max(0.0, percent / 100.0)))
            except Exception:
                pass
        if phase in ("done", "completed", "finalizado"):
            # Ventana premium de resultados: solo con el payload final REAL del
            # motor (trae porcentaje_clasificado), una vez por lote.
            if "porcentaje_clasificado" in data:
                try:
                    self._mostrar_resultados_clasificacion(data)
                except Exception:
                    pass
            txt, dot = "Proceso finalizado", theme.SUCCESS
            extra = []
            if data.get("copied_count") is not None:
                extra.append(f"{data.get('copied_count')} copiadas")
            if data.get("error_count"):
                extra.append(f"{data.get('error_count')} errores")
            if extra:
                txt += " · " + " · ".join(str(e) for e in extra)
        elif phase in ("canceled", "cancelado"):
            txt, dot = "Proceso cancelado", theme.WARNING
        elif phase == "error":
            txt, dot = (str(message) or "Error en el proceso")[:90], theme.DANGER
        else:
            base = str(message) if message else "Clasificando fotos…"
            if current is not None and total is not None and " / " not in base:
                base += f"  {current} / {total}"
            txt, dot = base, theme.ACCENT
        try:
            self._lote_label.configure(text=txt, text_color=SUB)
            self._lote_dot.configure(text_color=dot)
        except Exception:
            pass

    def _lote_reset(self):
        try:
            self._lote_bar.set(0)
            self._lote_label.configure(text="Sin proceso activo", text_color=SUB)
            self._lote_dot.configure(text_color=theme.TEXT_MUTE)
        except Exception:
            pass

    # ==========================================================
    # RESULTADOS DE CLASIFICACIÓN — ventana premium (solo UI)
    # ==========================================================
    def _resultados_visibles(self):
        m = getattr(self, "_resultados_modal", None)
        try:
            return bool(m is not None and m.winfo_exists())
        except Exception:
            return False

    def _resolver_carpeta_workspace(self, ruta):
        """El motor reporta rutas RELATIVAS al workspace; aquí se resuelven a
        ruta absoluta real probando contra cada raíz del explorador."""
        ruta = str(ruta or "").strip()
        if not ruta:
            return ""
        candidatos = []
        if os.path.isabs(ruta):
            candidatos.append(ruta)
        else:
            for r in (self._folder_roots or []):
                candidatos.append(r if ruta == "." else os.path.join(r, ruta))
        for c in candidatos:
            try:
                if os.path.isdir(c):
                    return os.path.abspath(c)
            except Exception:
                pass
        return ""

    def _mostrar_resultados_clasificacion(self, data):
        """Abre la ventana premium de resultados al terminar la clasificación
        (reemplaza el estado final de la ventanita de progreso). Solo presenta
        el payload que el motor ya emite; no llama al motor."""
        if self._resultados_visibles():
            return
        ia = getattr(self, "controlador_ia", None)
        try:
            cerrar = getattr(self, "_cerrar_ventanitas_progreso", None)
            if cerrar:
                cerrar()  # cierra TODAS las ventanitas (incluye huérfanas)
            else:
                pw = getattr(ia, "_progress_window", None) if ia else None
                if pw is not None and pw.winfo_exists():
                    pw.destroy()
        except Exception:
            pass
        # Resolver el destino a ruta ABSOLUTA (el motor lo emite relativo al
        # workspace) para que "Ver carpetas" abra el Explorador de Windows.
        data = dict(data or {})
        abs_dest = self._resolver_carpeta_workspace(data.get("destination_folder"))
        if abs_dest:
            data["destination_folder"] = abs_dest
        from facesyncApp.ui.modals import ClasificacionResultadosModal
        self._resultados_modal = ClasificacionResultadosModal(
            self, datos=data, on_ver=self._ver_carpetas_clasificadas)

    def _ver_carpetas_clasificadas(self, dest):
        """Botón "Ver carpetas": lleva al explorador del Workspace (refrescado)
        y abre la carpeta destino con las carpetas clasificadas."""
        try:
            self._mostrar_vista("workspace")
        except Exception:
            pass
        try:
            self._refresh_after_fs_change(None)
        except Exception:
            pass
        if dest and not os.path.isdir(dest):
            dest = self._resolver_carpeta_workspace(dest)
        if dest and os.path.isdir(dest):
            def w():
                try:
                    os.startfile(dest)  # noqa
                except Exception:
                    pass
            threading.Thread(target=w, daemon=True).start()

    def _toast(self, msg, ms=3400):
        """Aviso flotante no bloqueante (premium)."""
        try:
            old = getattr(self, "_toast_win", None)
            if old is not None and old.winfo_exists():
                old.destroy()
        except Exception:
            pass
        t = ctk.CTkFrame(self, fg_color=theme.ELEVATED, corner_radius=theme.RADIUS_MD,
                         border_width=1, border_color=ACCENT)
        ctk.CTkLabel(t, text=msg, font=theme.FONT_SUB, text_color=TEXT,
                     wraplength=440, justify="left").pack(padx=14, pady=10)
        t.place(relx=0.5, rely=0.96, anchor="s")
        self._toast_win = t
        self.after(ms, lambda: t.destroy() if t.winfo_exists() else None)

    # ---- Paneo del visor (capa visual; no altera el render ni el zoom) ----
    def _toggle_pan(self):
        self._pan_mode = not getattr(self, "_pan_mode", False)
        if self._pan_mode:
            self._btn_pan.configure(fg_color=ACCENT)
            cursor = "fleur"
        else:
            self._btn_pan.configure(fg_color=CARD)
            cursor = "arrow"
            self._pan_off = [0, 0]
            self._place_viewer()
        for w in (self._viewer_img_area, self._viewer_label):
            try:
                w.configure(cursor=cursor)
            except Exception:
                pass
        try:
            self._viewer_label._label.configure(cursor=cursor)
        except Exception:
            pass

    def _place_viewer(self):
        try:
            self._viewer_label.place_configure(relx=0.5, rely=0.5, anchor="center",
                                               x=self._pan_off[0], y=self._pan_off[1])
        except Exception:
            pass

    def _on_pan_press(self, event):
        if not getattr(self, "_pan_mode", False):
            return
        self._pan_start = (event.x_root, event.y_root, self._pan_off[0], self._pan_off[1])

    def _on_pan_move(self, event):
        if not getattr(self, "_pan_mode", False) or not getattr(self, "_pan_start", None):
            return
        sx, sy, ox, oy = self._pan_start
        self._pan_off = [ox + (event.x_root - sx), oy + (event.y_root - sy)]
        self._place_viewer()

    def _on_pan_release(self, event):
        self._pan_start = None

    def _clear_viewer_image(self):
        self._viewer_img_ref = None
        try:
            self._viewer_label._label.configure(image="")
        except Exception:
            pass

    def _set_viewer_text(self, text):
        self._viewer_img_path = None
        self._viewer_orig_image = None
        self._viewer_zoom = 1.0
        self._clear_viewer_image()
        self._viewer_label.configure(text=text)

    def _build_viewer_proxies(self):
        """Proxies pre-escalados de la imagen actual (se construyen UNA vez):
        el zoom redimensiona desde el proxy, no desde los 24MP originales ->
        cada paso de zoom es liviano y el visor se siente fluido."""
        img = self._viewer_orig_image
        self._viewer_proxy_big = None
        self._viewer_proxy_fast = None
        if img is None:
            return
        try:
            big = img
            if max(img.size) > 2600:
                k = 2600 / max(img.size)
                big = img.resize((max(1, int(img.width * k)),
                                  max(1, int(img.height * k))), PILImage.BILINEAR)
            fast = big
            if max(big.size) > 1600:
                k = 1600 / max(big.size)
                fast = big.resize((max(1, int(big.width * k)),
                                   max(1, int(big.height * k))), PILImage.BILINEAR)
            self._viewer_proxy_big, self._viewer_proxy_fast = big, fast
        except Exception:
            self._viewer_proxy_big = self._viewer_proxy_fast = None

    def _render_viewer_image(self):
        """Render FLUIDO: la imagen encaja en el visor (zoom 1 = encaja) y el
        zoom multiplica ese encaje. Redimensiona desde un proxy pre-escalado
        (no desde la foto completa) con tope ~4000px."""
        if not self._viewer_orig_image:
            return

        self._viewer_frame.update_idletasks()
        mw = max(self._viewer_frame.winfo_width() - 60, 200)
        mh = max(self._viewer_frame.winfo_height() - 120, 200)

        W, H = self._viewer_orig_image.width, self._viewer_orig_image.height
        base = min(mw / max(1, W), mh / max(1, H), 1.0)   # encaje al visor
        scale = base * self._viewer_zoom
        target_w = max(1, int(W * scale))
        target_h = max(1, int(H * scale))
        cap = 2600  # con paneo no hace falta más; mantiene el zoom fluido
        if max(target_w, target_h) > cap:
            k = cap / max(target_w, target_h)
            target_w, target_h = max(1, int(target_w * k)), max(1, int(target_h * k))

        # Caché: mismo tamaño -> no re-renderizar (clic repetido instantáneo).
        key = (id(self._viewer_orig_image), target_w, target_h)
        if getattr(self, "_viewer_render_key", None) == key and self._viewer_img_ref:
            return
        try:
            fast = getattr(self, "_viewer_proxy_fast", None)
            big = getattr(self, "_viewer_proxy_big", None)
            if fast is not None and max(target_w, target_h) <= max(fast.size):
                src = fast
            elif big is not None:
                src = big
            else:
                src = self._viewer_orig_image
            if (target_w, target_h) == src.size:
                img = src  # ya está al tamaño exacto (p. ej. zoom al tope)
            else:
                filt = PILImage.LANCZOS if max(target_w, target_h) <= 1200 else PILImage.BILINEAR
                img = src.resize((target_w, target_h), filt)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(target_w, target_h))
            self._clear_viewer_image()
            self._viewer_img_ref = ctk_img
            self._viewer_render_key = key
            self._viewer_label.configure(image=ctk_img, text="")
        except Exception as e:
            self._set_viewer_text(f"Error al renderizar imagen:\n{e}")

    def _zoom_in(self):
        if not self._viewer_orig_image:
            return
        self._viewer_zoom = min(self._viewer_zoom * 1.15, 4.0)
        self._render_viewer_image()

    def _zoom_out(self):
        if not self._viewer_orig_image:
            return
        self._viewer_zoom = max(self._viewer_zoom * 0.85, 0.3)
        self._render_viewer_image()

    def _zoom_wheel(self, event):
        """Zoom con la rueda del mouse sobre el visor (fluido)."""
        if not self._viewer_orig_image:
            return
        if getattr(event, "delta", 0) > 0:
            self._zoom_in()
        else:
            self._zoom_out()

    def _rotar_imagen(self):
        """Rota la vista 90° (solo visual; el archivo NO se modifica). Los
        proxies se rotan con transpose (barato), no se reconstruyen."""
        if not self._viewer_orig_image:
            return
        try:
            self._viewer_orig_image = self._viewer_orig_image.transpose(
                PILImage.ROTATE_270)  # 90° en sentido horario
            for attr in ("_viewer_proxy_big", "_viewer_proxy_fast"):
                p = getattr(self, attr, None)
                if p is not None:
                    setattr(self, attr, p.transpose(PILImage.ROTATE_270))
            self._pan_off = [0, 0]
            self._place_viewer()
            self._render_viewer_image()
        except Exception:
            pass

    def _mostrar_imagen(self, path):
        name = os.path.basename(path)
        self._viewer_title.configure(text=name)
        ext = os.path.splitext(name)[1].lower()

        if ext in RAW_EXT:
            self._mostrar_cr2(path, name)
            return

        if ext not in IMG_EXT:
            ic = self._ICON.get(ext, "📄")
            self._set_viewer_text(f"\n\n{ic}\n\n{name}\n\nArchivo no previsualizable")
            return

        if not PILImage:
            self._set_viewer_text("Instala Pillow:\npip install Pillow")
            return

        try:
            img = PILImage.open(path)
            self._viewer_orig_image = img.copy()
            self._build_viewer_proxies()
            self._viewer_img_path = path
            self._viewer_zoom = 1.0
            self._render_viewer_image()
        except Exception as e:
            self._viewer_orig_image = None
            self._viewer_img_path = None
            self._set_viewer_text(f"Error:\n{e}")

    def _mostrar_cr2(self, path, name):
        """Vista previa de RAW .CR2 en el visor (solo UI, no toca el motor):
        extrae el JPEG embebido con rawpy en un worker (rápido) y, si no hay,
        revela el RAW a media resolución. queue+after para no congelar la UI."""
        self._set_viewer_text(f"\n\n🎞️\n\n{name}\n\nCargando vista previa RAW…")
        self._cr2_token = path  # descarta resultados viejos si cambian de foto
        q = queue.Queue()

        def worker():
            try:
                import io as _io
                import rawpy
                with rawpy.imread(path) as raw:
                    try:
                        th = raw.extract_thumb()
                        if th.format == rawpy.ThumbFormat.JPEG:
                            img = PILImage.open(_io.BytesIO(th.data)).convert("RGB")
                        else:  # bitmap
                            img = PILImage.fromarray(th.data)
                    except Exception:
                        rgb = raw.postprocess(half_size=True, use_camera_wb=True)
                        img = PILImage.fromarray(rgb)
                img.thumbnail((1600, 1600), PILImage.LANCZOS)
                q.put(("ok", img))
            except Exception as e:
                q.put(("err", f"{type(e).__name__}: {e}"))

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if getattr(self, "_cr2_token", None) != path:
                return  # el usuario ya seleccionó otra foto
            try:
                status, payload = q.get_nowait()
            except queue.Empty:
                self.after(100, poll)
                return
            if status == "ok":
                self._viewer_orig_image = payload
                self._build_viewer_proxies()
                self._viewer_img_path = path
                self._viewer_zoom = 1.0
                self._render_viewer_image()
            else:
                self._set_viewer_text(
                    f"\n\n🎞️\n\n{name}\n\nNo se pudo previsualizar el RAW:\n{payload}")

        self.after(80, poll)

    def _crear_panel_derecho(self, parent):
        rp = ctk.CTkFrame(parent, width=420, fg_color=PANEL,
                          corner_radius=0, border_width=1, border_color=BORDER)
        rp.grid(row=0, column=2, sticky="nsew")
        rp.grid_propagate(False)

        head = ctk.CTkFrame(rp, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(22, 8))
        ctk.CTkLabel(head, text="Asistente IA", font=theme.FONT_H2,
                     text_color=TEXT).pack(side="left")
        ctk.CTkLabel(head, text="● Activo", font=theme.FONT_SMALL,
                     text_color=theme.SUCCESS).pack(side="right", pady=6)

        self.chat_history = ctk.CTkScrollableFrame(rp, fg_color=BG,
                                                   corner_radius=theme.RADIUS_LG)
        self.chat_history.pack(fill="both", expand=True, padx=15, pady=(6, 12))

        inp = ctk.CTkFrame(rp, fg_color="transparent", height=70)
        inp.pack(fill="x", padx=15, pady=(0, 6))
        self.entry_chat = ctk.CTkEntry(inp, placeholder_text="Pregúntame algo…", height=46,
                     corner_radius=theme.RADIUS_MD, fg_color=CARD, border_color=BORDER
                     )
        self.entry_chat.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.boton_enviar = ctk.CTkButton(inp, text="➜", width=50, height=46,
                      corner_radius=theme.RADIUS_MD,
                      font=(theme.FONT_FAMILY, 16, "bold"), **theme.BTN_PRIMARY
                      )
        self.boton_enviar.pack(side="right")
        ctk.CTkLabel(rp, text="IA puede cometer errores. Verifica resultados.",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTE
                     ).pack(anchor="w", padx=20, pady=(0, 14))

        # Integrar Agente de IA (PRO: con workspace y callback de refresco)
        workspace_inicial = self._active_project_root or (self._folder_roots[0] if self._folder_roots else None)
        self.controlador_ia = AsistenteFaceSync(
            entry_chat=self.entry_chat,
            boton_enviar=self.boton_enviar,
            textbox_historial=self.chat_history,
            ruta_workspace=workspace_inicial,
            callback_refrescar=self._refresh_after_fs_change
        )
        # Propagar TODAS las carpetas raiz ya cargadas (workspace guardado) para
        # que el asistente las reconozca al iniciar, no solo al agregar nuevas.
        if self._folder_roots and hasattr(self.controlador_ia, "set_workspace_roots"):
            try:
                self.controlador_ia.set_workspace_roots(self._folder_roots)
            except Exception as e:
                print(f"Advertencia: no se pudieron registrar las raices del workspace: {e}")
        # Experiencia premium del chat (solo visual; la lógica no se toca).
        try:
            self._instalar_chat_premium()
        except Exception as e:
            print(f"Advertencia: chat premium no instalado: {e}")

    # ==========================================================
    # CHAT PREMIUM (indicador de "agente trabajando" — SOLO VISUAL)
    # ==========================================================
    def _instalar_chat_premium(self):
        """Burbuja de estado animada tipo agente: aparece al enviar un mensaje
        ("Pensando…", "Trabajando en ello…") y se retira sola cuando llega la
        respuesta. Implementada con ENVOLTORIOS en runtime sobre el asistente —
        agente_ia.py NO se modifica y su lógica no cambia."""
        ia = self.controlador_ia
        self._typing_lbl = None
        self._typing_phase = 0
        self._typing_after = None
        _states = ("Pensando", "Analizando tu workspace", "Trabajando en ello",
                   "Preparando la respuesta")

        def _animate():
            lbl = self._typing_lbl
            if lbl is None:
                return
            try:
                if not lbl.winfo_exists():
                    self._typing_lbl = None
                    return
                self._typing_phase += 1
                base = _states[(self._typing_phase // 5) % len(_states)]
                dots = "·" * (self._typing_phase % 4)
                lbl.configure(text=f"{base}{dots}")
                self._typing_after = self.after(320, _animate)
            except Exception:
                self._typing_lbl = None

        def _show_typing():
            self._chat_typing_remove()
            hist = ia.textbox_historial
            try:
                # Texto simple DENTRO del chat, debajo del último mensaje
                # (sin burbuja, sin icono, alineado a la izquierda).
                lbl = ctk.CTkLabel(hist, text="Pensando", font=theme.FONT_SMALL,
                                   text_color=theme.TEXT_SUB, fg_color="transparent",
                                   anchor="w")
                lbl.pack(fill="x", padx=16, pady=(0, 4))
                self._typing_lbl, self._typing_phase = lbl, 0
                try:
                    hist._parent_canvas.yview_moveto(1.0)
                except Exception:
                    pass
                # Pintar YA: aunque después haya trabajo en el hilo de UI, el
                # usuario ve el estado (no parece congelado).
                self.update_idletasks()
                _animate()
            except Exception:
                self._typing_lbl = None

        orig_mostrar = ia._mostrar_en_chat

        def mostrar_wrapped(remitente, texto):
            if remitente != "Tú":
                self._chat_typing_remove()
            res = orig_mostrar(remitente, texto)
            if remitente == "Tú":
                _show_typing()
            return res

        ia._mostrar_en_chat = mostrar_wrapped

    def _chat_typing_remove(self):
        try:
            if self._typing_after is not None:
                self.after_cancel(self._typing_after)
        except Exception:
            pass
        self._typing_after = None
        lbl = getattr(self, "_typing_lbl", None)
        self._typing_lbl = None
        try:
            if lbl is not None and lbl.winfo_exists():
                lbl.destroy()
        except Exception:
            pass

    def _get_config_path(self):
        """Obtiene la ruta del archivo config.json para el usuario actual."""
        base_dir = os.path.join(str(ensure_app_data_root()), "context", "usuarios")
        user_dir = os.path.join(base_dir, self.email_usuario)
        os.makedirs(user_dir, exist_ok=True)
        return os.path.join(user_dir, "config.json")

    def cerrar_sesion(self):
        """Cierra la sesión del usuario actual y vuelve a la pantalla de login."""
        print(f"Cerrando sesión de {self.email_usuario}...")
        self.destroy()
        # Importación diferida para evitar dependencia circular
        from facesyncApp.login import FaceSyncLogin
        login_window = FaceSyncLogin()
        login_window.mainloop()

    def guardar_espacio_trabajo(self):
        """Guarda el estado del espacio de trabajo (árbol de archivos) en config.json."""
        try:
            config_path = self._get_config_path()
            workspace_state = {
                "archivos_actuales": self._archivos_actuales,
                "folder_roots": self._folder_roots,
                "active_project_root": self._active_project_root,
                "carpetas_expandidas": self._carpetas_expandidas
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(workspace_state, f, indent=2, ensure_ascii=False)
            print(f"✓ Espacio de trabajo guardado en {config_path}")
        except Exception as e:
            print(f"❌ Error guardando espacio de trabajo: {e}")

    def cargar_espacio_trabajo(self):
        """Carga el estado del espacio de trabajo desde config.json y reconstruye el árbol."""
        try:
            config_path = self._get_config_path()
            if not os.path.exists(config_path):
                print(f"ℹ No se encontró config.json para {self.email_usuario}, usando estado vacío")
                return
            
            with open(config_path, "r", encoding="utf-8") as f:
                workspace_state = json.load(f)
            
            # Restaurar variables de estado
            self._archivos_actuales = workspace_state.get("archivos_actuales", [])
            self._folder_roots = workspace_state.get("folder_roots", [])
            self._active_project_root = workspace_state.get("active_project_root")
            self._carpetas_expandidas = workspace_state.get("carpetas_expandidas", {})
            
            # Filtrar archivos y carpetas que ya no existen
            self._archivos_actuales = [f for f in self._archivos_actuales if os.path.exists(f)]
            self._folder_roots = [r for r in self._folder_roots if os.path.isdir(r)]
            if not self._active_project_root or not os.path.isdir(self._active_project_root):
                self._active_project_root = self._folder_roots[0] if self._folder_roots else None
            self._ensure_app_data_root()
            
            # Reconstruir el árbol visualmente
            self._repair_legacy_tree()
            self._rerender_explorador()

            # Sincronizar workspace con el agente IA
            if hasattr(self, 'controlador_ia') and self.controlador_ia and self._active_project_root:
                self.controlador_ia.set_workspace(self._active_project_root)
                self.controlador_ia.context_manager.set_active_path(self._active_project_root)
                print(f"Workspace del agente IA: {self._active_project_root}")

            print(f"✓ Espacio de trabajo restaurado para {self.email_usuario}")
        except Exception as e:
            print(f"❌ Error cargando espacio de trabajo: {e}")


if __name__ == "__main__":
    app = DashboardWindow()
    app.mainloop()
