"""
FaceSync AI — Iconos PNG de la app (assets/images).

Capa puramente visual: carga perezosa + caché de CTkImage para usar los iconos
descargados en lugar de emojis. Si un icono no existe o PIL falla, devuelve
None y el llamador conserva su fallback (emoji/texto). No contiene lógica de
negocio.
"""

import os
import tkinter as tk

import customtkinter as ctk

from facesyncApp import BASE_DIR

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

_DIR = os.path.join(BASE_DIR, "assets", "images")
_cache = {}
_cache_root = None  # root de Tk al que pertenecen las imágenes cacheadas

# nombre lógico -> archivo en assets/images
FILES = {
    "logo": "sync.png",                 # logo transparente (tema claro)
    "logo_dark": "logo.png",            # variante con fondo oscuro
    "carpeta": "carpeta.png",
    "agregar_carpeta": "agregar carpeta.png",
    "agregar_archivo": "agregar archivo.png",
    "agregar_exportacion": "agregar exportacion.png",
    "clasificar": "clasificar fotos.png",
    "drive": "drive.png",
    "excel": "excel.png",
    "exportar": "exportar.png",
    "google": "GOOGLE.png",
    "imagen": "imagen.png",
    "refrescar": "refrescar.png",
    "reporte": "reporte.png",
    "salir": "salir.png",
    "trash": "trash.png",
    "trash_hover": "trash_hover.png",
    "almacenamiento": "almacenamineto.png",  # (nombre del archivo trae el typo)
}


def _norm(s):
    return " ".join(str(s).lower().replace(".png", "").split())


def _resolve(fname):
    """Ruta real del icono, tolerante a espacios extra en el nombre del archivo
    (p. ej. 'agregar archivo .png'). Escanea el directorio una sola vez."""
    path = os.path.join(_DIR, fname)
    if os.path.exists(path):
        return path
    global _dir_index
    try:
        _dir_index
    except NameError:
        _dir_index = {}
        try:
            for f in os.listdir(_DIR):
                if f.lower().endswith(".png"):
                    _dir_index[_norm(f)] = os.path.join(_DIR, f)
        except OSError:
            pass
    return _dir_index.get(_norm(fname))


def icon(name, size=18):
    """CTkImage del icono `name` a `size` px (cuadrado), o None si no se puede.

    El caché se INVALIDA cuando cambia el root de Tk (p. ej. cerrar sesión y
    volver a entrar crea otra ventana raíz): una CTkImage del root anterior no
    sirve en el nuevo ("image pyimageN doesn't exist")."""
    global _cache, _cache_root
    root = getattr(tk, "_default_root", None)
    if root is not _cache_root:
        _cache = {}
        _cache_root = root
    key = (name, int(size))
    if key in _cache:
        return _cache[key]
    img = None
    fname = FILES.get(name)
    if PILImage is not None and fname:
        try:
            path = _resolve(fname)
            if path:
                pil = PILImage.open(path).convert("RGBA")
                img = ctk.CTkImage(light_image=pil, dark_image=pil,
                                   size=(int(size), int(size)))
        except Exception:
            img = None
    _cache[key] = img
    return img
