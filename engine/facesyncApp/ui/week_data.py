"""
FaceSync AI — Datos de la vista Resumen semanal (Fase 4). SOLO LECTURA.

Reutiliza señales reales y baratas (sin tocar backend):
  - mtimes de los embeddings en caché (1 .json por imagen analizada) -> permite
    una gráfica real de "fotos analizadas por día" y comparar semanas.
  - carpetas de clasificación (usuarios/<email>/ALUMNOS) por nº de archivos.

Se escanea el disco UNA vez (en un worker); el cambio de semana solo re-agrupa
en memoria la lista de mtimes cacheada. Si no hay datos, los valores son None/[]
y la vista muestra estado vacío (no se inventan datos).
"""

import os
from datetime import datetime, timedelta

from facesyncApp import BASE_DIR

_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
          "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _app_data_root():
    try:
        from core.app_paths import default_app_data_root
        return str(default_app_data_root())
    except Exception:
        local = os.environ.get("LOCALAPPDATA")
        return os.path.join(local, "FaceSync") if local else os.path.join(
            os.path.expanduser("~"), ".facesync")


def _embeddings_dir():
    return os.path.join(_app_data_root(), "cache", "embeddings")


def _alumnos_dir(email):
    return os.path.join(_app_data_root(), "usuarios", email or "", "ALUMNOS")


def scan_mtimes():
    """mtimes de los embeddings (un solo listado de directorio)."""
    d = _embeddings_dir()
    out = []
    if not os.path.isdir(d):
        return out
    try:
        with os.scandir(d) as it:
            for e in it:
                if e.name.lower().endswith(".json"):
                    try:
                        out.append(e.stat().st_mtime)
                    except OSError:
                        pass
    except OSError:
        pass
    return out


def folder_ranking(email, top=5):
    """Carpetas/alumnos con más fotos clasificadas. Usa los reportes reales del
    workspace (report_data, solo lectura) con fallback al ALUMNOS legado."""
    try:
        from facesyncApp.ui import report_data as rd
        return rd.classified_folder_ranking(email, top=top)
    except Exception:
        return []


def week_bounds(offset=0):
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)
    start = datetime(monday.year, monday.month, monday.day).timestamp()
    return monday, sunday, start, start + 7 * 86400


def week_label(offset=0):
    monday, sunday, _, _ = week_bounds(offset)
    if monday.month == sunday.month:
        return f"Semana del {monday.day} al {sunday.day} de {_MESES[monday.month - 1]}"
    return (f"Semana del {monday.day} de {_MESES[monday.month - 1]} "
            f"al {sunday.day} de {_MESES[sunday.month - 1]}")


def bucket_week(mtimes, offset=0):
    """Cuenta por día (Lun..Dom) los mtimes dentro de la semana 'offset'."""
    _, _, start, end = week_bounds(offset)
    days = [0] * 7
    for m in mtimes:
        if start <= m < end:
            idx = int((m - start) // 86400)
            if 0 <= idx < 7:
                days[idx] += 1
    return days
