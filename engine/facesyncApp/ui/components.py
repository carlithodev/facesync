"""
FaceSync AI — Componentes visuales base (Fase 1).

Widgets reutilizables y puramente visuales: chips, tarjetas premium, tarjetas
'esqueleto' y la vista placeholder usada por las secciones que se construyen en
fases posteriores. Sin lógica de negocio ni acceso a datos.
"""

import tkinter as tk

import customtkinter as ctk

from facesyncApp.ui import theme

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    Image = ImageDraw = ImageFilter = None


class Chip(ctk.CTkLabel):
    """Etiqueta tipo 'pill' para estados, sugerencias o badges."""

    def __init__(self, parent, text="", color=theme.ACCENT_SOFT,
                 text_color=theme.TEXT, **kw):
        super().__init__(
            parent,
            text=f"  {text}  ",
            font=theme.FONT_SMALL,
            text_color=text_color,
            fg_color=color,
            corner_radius=theme.RADIUS_XL,
            height=24,
            **kw,
        )


class PremiumCard(ctk.CTkFrame):
    """Tarjeta con esquinas redondeadas, borde sutil y realce opcional al hover.

    Si hover=True, el borde se ilumina al pasar el cursor (efecto premium).
    """

    def __init__(self, parent, *, hover=False, fg_color=theme.CARD,
                 border_color=theme.BORDER, corner_radius=theme.RADIUS_LG, **kw):
        super().__init__(
            parent,
            fg_color=fg_color,
            border_width=1,
            border_color=border_color,
            corner_radius=corner_radius,
            **kw,
        )
        self._border_idle = border_color
        if hover:
            self.bind("<Enter>", lambda e: self.configure(border_color=theme.ACCENT))
            self.bind("<Leave>", lambda e: self.configure(border_color=self._border_idle))


# ======================================================================
# Helpers de imagen (PIL) para banners y motivos premium
# ======================================================================
def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def make_gradient_image(w, h, color_a, color_b, horizontal=True):
    """Degradado lineal (PIL Image RGB) de color_a a color_b.
    Eficiente: construye una franja 1-D y la escala al tamaño pedido."""
    if Image is None:
        return None
    w = max(1, int(w))
    h = max(1, int(h))
    ca, cb = _hex_to_rgb(color_a), _hex_to_rgb(color_b)
    n = w if horizontal else h
    strip = Image.new("RGB", (n, 1))
    px = strip.load()
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0.0
        px[i, 0] = (
            int(ca[0] + (cb[0] - ca[0]) * t),
            int(ca[1] + (cb[1] - ca[1]) * t),
            int(ca[2] + (cb[2] - ca[2]) * t),
        )
    if not horizontal:
        strip = strip.rotate(90, expand=True)
    return strip.resize((w, h))


class BarChart(ctk.CTkFrame):
    """Gráfica de barras ligera sobre tk.Canvas (sin matplotlib)."""

    def __init__(self, parent, labels, bg=theme.CARD, color=theme.ACCENT, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        self._labels = list(labels)
        self._values = [0] * len(self._labels)
        self._color = color
        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)
        # OJO: _render (pintar la gráfica), NO _draw (interno de CTkFrame) —
        # con _draw la gráfica nunca se redibujaba al redimensionar la ventana.
        self._canvas.bind("<Configure>", lambda e: self._render())

    def set_values(self, values):
        self._values = list(values)
        self._render()

    def _render(self):
        c = self._canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 12 or h < 12:
            return
        n = len(self._values) or 1
        mx = max(self._values) if any(self._values) else 0
        pad_t, pad_b, gap = 18, 22, 10
        bw = max(2, (w - gap * (n + 1)) / n)
        if mx <= 0:
            c.create_text(w / 2, h / 2, text="Sin actividad esta semana",
                          fill=theme.TEXT_MUTE, font=(theme.FONT_FAMILY, 9))
        for i, v in enumerate(self._values):
            x0 = gap + i * (bw + gap)
            x1 = x0 + bw
            bh = (h - pad_b - pad_t) * (v / mx) if mx else 0
            y1 = h - pad_b
            y0 = y1 - bh
            if bh > 0:
                c.create_rectangle(x0, y0, x1, y1, fill=self._color, outline="")
                c.create_text((x0 + x1) / 2, y0 - 8, text=str(v),
                              fill=theme.TEXT_SUB, font=(theme.FONT_FAMILY, 8))
            if i < len(self._labels):
                c.create_text((x0 + x1) / 2, h - 10, text=self._labels[i],
                              fill=theme.TEXT_MUTE, font=(theme.FONT_FAMILY, 8))


class DonutChart(ctk.CTkFrame):
    """Donut ligero sobre tk.Canvas. data = [(label, value, color), ...]."""

    def __init__(self, parent, bg=theme.CARD, **kw):
        super().__init__(parent, fg_color="transparent", **kw)
        self._bg = bg
        self._data = []
        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)
        # _render, NO _draw (ver BarChart): redibuja el donut al redimensionar.
        self._canvas.bind("<Configure>", lambda e: self._render())

    def set_data(self, data):
        self._data = list(data or [])
        self._render()

    def _render(self):
        c = self._canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 12 or h < 12:
            return
        total = sum(v for _, v, _ in self._data) if self._data else 0
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 8
        ri = r * 0.6
        if total <= 0:
            c.create_oval(cx - r, cy - r, cx + r, cy + r,
                          outline=theme.ELEVATED, width=3)
            c.create_text(cx, cy, text="Sin datos", fill=theme.TEXT_MUTE,
                          font=(theme.FONT_FAMILY, 9))
            return
        start = 90.0
        for _label, v, color in self._data:
            if v <= 0:
                continue
            ext = -360.0 * (v / total)
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=ext,
                         fill=color, outline=self._bg, width=1, style="pieslice")
            start += ext
        c.create_oval(cx - ri, cy - ri, cx + ri, cy + ri, fill=self._bg, outline="")
        c.create_text(cx, cy, text=f"{total:,}", fill=theme.TEXT,
                      font=(theme.FONT_FAMILY, 14, "bold"))


def make_face_scan_image(size=200, color="#22D3EE", seed=7):
    """'Rostro digital' tipo nube de puntos con glow suave (PIL Image RGBA).
    Evoca el reconocimiento facial de las imágenes de referencia. Si PIL no
    está disponible devuelve None y la vista usa un fallback de emoji."""
    if Image is None:
        return None
    import random
    rnd = random.Random(seed)
    S = int(size)
    rgb = _hex_to_rgb(color)

    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Glow radial suave
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = S * 0.5, S * 0.52
    gd.ellipse([cx - S * 0.34, cy - S * 0.40, cx + S * 0.34, cy + S * 0.40],
               fill=rgb + (70,))
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.07))
    img = Image.alpha_composite(img, glow)

    d = ImageDraw.Draw(img)
    rx, ry = S * 0.26, S * 0.34

    def inside(px, py):
        return ((px - cx) / rx) ** 2 + ((py - cy) / ry) ** 2 <= 1.0

    pts = []
    tries = 0
    while len(pts) < 130 and tries < 2000:
        tries += 1
        px = rnd.uniform(cx - rx, cx + rx)
        py = rnd.uniform(cy - ry, cy + ry)
        if inside(px, py):
            pts.append((px, py))

    # Malla: líneas entre puntos cercanos
    for i, (x1, y1) in enumerate(pts):
        for (x2, y2) in pts[i + 1:i + 4]:
            if (x1 - x2) ** 2 + (y1 - y2) ** 2 < (S * 0.11) ** 2:
                d.line([x1, y1, x2, y2], fill=rgb + (40,), width=1)

    # Puntos (más brillantes cerca del centro)
    for (px, py) in pts:
        dist = (((px - cx) / rx) ** 2 + ((py - cy) / ry) ** 2) ** 0.5
        a = int(230 - 120 * dist)
        r = 2 if a > 170 else 1
        d.ellipse([px - r, py - r, px + r, py + r], fill=rgb + (max(60, a),))

    # Marco de escaneo (corchetes en las esquinas)
    m, ln = int(S * 0.08), int(S * 0.12)
    bracket = rgb + (200,)
    for (ax, ay, dx, dy) in [
        (m, m, 1, 1), (S - m, m, -1, 1), (m, S - m, 1, -1), (S - m, S - m, -1, -1),
    ]:
        d.line([ax, ay, ax + dx * ln, ay], fill=bracket, width=2)
        d.line([ax, ay, ax, ay + dy * ln], fill=bracket, width=2)

    return img
