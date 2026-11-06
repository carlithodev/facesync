"""
FaceSync - Utilidades compartidas
Funciones auxiliares reutilizables entre módulos (avatar, imágenes, etc.)
"""

import os
import tkinter as tk
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from facesyncApp import BASE_DIR


def set_windows_app_id():
    """Agrupa la app en Windows con identidad propia, no como Python."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "FaceSync.App"
        )
    except Exception:
        pass


def set_window_app_icon(window, default=False):
    """Usa assets/images/iconapp.png como icono de ventana/app."""
    try:
        path = os.path.join(BASE_DIR, "assets", "images", "iconapp.png")
        icon = tk.PhotoImage(file=path)
        window._facesync_icon_ref = icon
        window.iconphoto(default, icon)
    except Exception:
        pass


def clear_window_identity(window):
    """Deja la barra de una ventana sin titulo ni icono visible."""
    try:
        window.title("")
    except Exception:
        pass
    try:
        empty = tk.PhotoImage(width=16, height=16)
        window._facesync_empty_icon_ref = empty
        window.iconphoto(False, empty)
    except Exception:
        pass


def set_windows_title_bar_light(window):
    """Pinta la barra nativa de Windows en blanco cuando existe."""
    if os.name != "nt":
        return

    def apply_style():
        try:
            import ctypes

            hwnd = window.winfo_id()
            parent_hwnd = ctypes.windll.user32.GetParent(hwnd)
            targets = [h for h in (parent_hwnd, hwnd) if h]
            seen = set()
            for target in targets:
                if target in seen:
                    continue
                seen.add(target)
                handle = ctypes.c_void_p(target)
                for attr in (20, 19):
                    use_light = ctypes.c_int(0)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        handle, attr, ctypes.byref(use_light), ctypes.sizeof(use_light)
                    )
                for attr, color in (
                    (34, 0x00FFFFFF),  # borde
                    (35, 0x00FFFFFF),  # barra
                    (36, 0x00000000),  # texto
                ):
                    value = ctypes.c_int(color)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        handle, attr, ctypes.byref(value), ctypes.sizeof(value)
                    )
        except Exception:
            pass

    try:
        window.after(50, apply_style)
        window.after(300, apply_style)
    except Exception:
        apply_style()


def generate_fallback_avatar(name_or_email, size=128):
    """Genera un avatar circular con la inicial del nombre/email."""
    letter = "G"
    if name_or_email:
        letter = name_or_email.strip()[0].upper()
        
    colors = [
        "#137333",  # Verde Google
        "#7030A0",  # Morado
        "#0F8A9D",  # Azul/Teal
        "#D9480F",  # Naranja
        "#C2255C",  # Rosa oscuro
        "#1971C2",  # Azul
    ]
    hash_idx = sum(ord(c) for c in name_or_email) % len(colors)
    bg_color = colors[hash_idx]
    
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Dibujar círculo
    draw.ellipse((0, 0, size, size), fill=bg_color)
    
    # Dibujar letra centrada
    from PIL import ImageFont
    font = None
    try:
        font = ImageFont.truetype("arial.ttf", int(size * 0.5))
    except Exception:
        try:
            font = ImageFont.load_default()
        except Exception:
            pass
            
    if font:
        try:
            bbox = draw.textbbox((0, 0), letter, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
        except AttributeError:
            w, h = draw.textsize(letter, font=font)
        x = (size - w) / 2
        y = (size - h) / 2 - (h * 0.15)
        draw.text((x, y), letter, fill="white", font=font)
    else:
        draw.text((size/3, size/3), letter, fill="white")
        
    return img


def download_and_crop_avatar(picture_url, email_safe, size=128):
    """Descarga la foto de perfil de Google y la recorta en un círculo."""
    try:
        import urllib.request
        from io import BytesIO
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(picture_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            img_data = response.read()
            
        img = Image.open(BytesIO(img_data)).convert("RGBA")
        img = ImageOps.fit(img, (size, size), Image.Resampling.LANCZOS)
        
        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size, size), fill=255)
        
        output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        output.paste(img, (0, 0), mask=mask)
        
        from oauth_service import _account_id, _users_dir
        users_dir = os.path.join(_users_dir(), _account_id(email_safe))
        os.makedirs(users_dir, exist_ok=True)
        pic_path = os.path.join(users_dir, "perfil.png")
        output.save(pic_path, "PNG")
        return pic_path
    except Exception as e:
        print(f"Error downloading/cropping avatar: {e}")
        return None
