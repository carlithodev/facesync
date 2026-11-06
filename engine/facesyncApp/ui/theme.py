"""
FaceSync AI — Sistema de tema premium (Fase 1).

Capa puramente visual: constantes de diseño (paleta navy premium, tipografía,
radios, espaciado) inspiradas en las imágenes de referencia. No contiene
lógica de negocio. Estas constantes las consumen la sidebar, los componentes
y las vistas nuevas; el motor/backend no depende de este módulo.
"""

# ======================================================================
# SUPERFICIES / FONDOS  (LIGHT premium: blanco/perla, gris muy claro)
# ======================================================================
BG_APP      = "#F4F6FB"   # fondo de la ventana raíz (gris perla)
BG_SIDEBAR  = "#FFFFFF"   # fondo de la sidebar de navegación
BG_CONTENT  = "#F4F6FB"   # fondo del área de contenido / vistas
PANEL       = "#FFFFFF"   # paneles grandes (blanco)
CARD        = "#FFFFFF"   # tarjetas (blanco)
CARD_HOVER  = "#F7F9FC"   # tarjeta en hover
ELEVATED    = "#EEF2F8"   # superficies elevadas / badges / hover sutil

# ======================================================================
# BORDES / LÍNEAS
# ======================================================================
BORDER      = "#E3E8F0"   # borde estándar (gris claro)
BORDER_SOFT = "#EDF1F7"   # borde tenue
BORDER_GLOW = "#2563EB"   # borde resaltado (foco / activo)

# ======================================================================
# ACENTOS
# ======================================================================
ACCENT       = "#2563EB"  # azul principal
ACCENT_HOVER = "#1D4ED8"  # azul hover
ACCENT_SOFT  = "#E7EEFF"  # azul muy claro (chips / fondos suaves)
CYAN         = "#0EA5C4"  # cian (más profundo para contraste en claro)
CYAN_SOFT    = "#D7F4FB"

# ======================================================================
# TEXTO  (oscuro sobre fondos claros)
# ======================================================================
TEXT          = "#1E293B"  # texto principal (slate oscuro)
TEXT_SUB      = "#64748B"  # texto secundario
TEXT_MUTE     = "#9AA7BD"  # texto atenuado
TEXT_ON_ACCENT = "#FFFFFF"  # texto sobre botones azules

# ======================================================================
# ESTADOS  (tonos legibles sobre blanco)
# ======================================================================
SUCCESS = "#16A34A"
WARNING = "#D97706"
DANGER  = "#DC2626"
INFO    = "#2563EB"

# ======================================================================
# NAVEGACIÓN (sidebar)
# ======================================================================
NAV_ACTIVE_BG  = "#E9F0FF"  # fondo del ítem activo (azul muy claro)
NAV_ACTIVE_BAR = "#2563EB"  # barra de acento del ítem activo
NAV_HOVER_BG   = "#F1F5F9"  # fondo del ítem en hover

# ======================================================================
# BOTONES (minimalistas, sin color sólido — excepto acciones rápidas)
# ======================================================================
# Primario: azul muy suave con borde y texto azul (elegante, no chillón).
BTN_PRIMARY = {
    "fg_color": ACCENT_SOFT,
    "hover_color": "#D9E6FF",
    "text_color": ACCENT_HOVER,
    "border_width": 1,
    "border_color": "#C9DAFB",
}
# Fantasma: transparente con borde gris; para acciones secundarias.
BTN_GHOST = {
    "fg_color": "transparent",
    "hover_color": ELEVATED,
    "text_color": TEXT,
    "border_width": 1,
    "border_color": BORDER,
}

# ======================================================================
# TIPOGRAFÍA
# ======================================================================
FONT_FAMILY = "Segoe UI"


def font(size=13, weight="normal"):
    """Helper para crear tuplas de fuente consistentes."""
    return (FONT_FAMILY, size, weight)


FONT_DISPLAY = (FONT_FAMILY, 30, "bold")  # números grandes / héroes
FONT_H1      = (FONT_FAMILY, 24, "bold")  # título de vista
FONT_H2      = (FONT_FAMILY, 18, "bold")  # título de sección
FONT_H3      = (FONT_FAMILY, 15, "bold")  # subtítulo / tarjeta
FONT_NAV     = (FONT_FAMILY, 14)          # ítems de navegación
FONT_BODY    = (FONT_FAMILY, 13)
FONT_SUB     = (FONT_FAMILY, 12)
FONT_SMALL   = (FONT_FAMILY, 11)
FONT_TINY    = (FONT_FAMILY, 10)

# ======================================================================
# GEOMETRÍA
# ======================================================================
RADIUS_SM = 8
RADIUS_MD = 12
RADIUS_LG = 16
RADIUS_XL = 20

PAD_XS = 4
PAD_SM = 8
PAD_MD = 12
PAD_LG = 16
PAD_XL = 24

SIDEBAR_WIDTH = 230
