"""
FaceSync AI — Proveedor de datos de la vista Inicio (Fase 2).

SOLO LECTURA. Reúne un resumen ligero a partir de artefactos que el motor ya
genera, sin importar ni modificar el backend, motor, Drive, seguridad ni el
contexto:

  - Fotos analizadas    -> nº de embeddings en caché (1 .json por imagen).
  - Carpetas clasificadas -> subcarpetas en usuarios/<email>/ALUMNOS.
  - Exportaciones       -> no se persiste registro -> None (estado vacío).
  - Actividad reciente  -> derivada de mtimes reales (reporte, workspace, ALUMNOS).

Todas las operaciones son listados de directorio / stat (baratas) y están
pensadas para ejecutarse en un worker. Si un dato no existe, su valor es None
o lista vacía, y la vista muestra un estado vacío elegante (no se inventan
datos). No hay efectos secundarios: nunca se crea ni modifica nada.
"""

import os
from datetime import datetime

from facesyncApp import BASE_DIR


# ----------------------------------------------------------------------
# Localización de artefactos (solo lectura, sin crear directorios)
# ----------------------------------------------------------------------
def _app_data_root():
    """Raíz de datos de la app SIN crear nada (a diferencia de ensure_*)."""
    try:
        from core.app_paths import default_app_data_root
        return str(default_app_data_root())
    except Exception:
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return os.path.join(local, "FaceSync")
        return os.path.join(os.path.expanduser("~"), ".facesync")


def _embeddings_dir():
    return os.path.join(_app_data_root(), "cache", "embeddings")


def _alumnos_dir(email):
    return os.path.join(_app_data_root(), "usuarios", email or "", "ALUMNOS")


def _user_config_path(email):
    return os.path.join(_app_data_root(), "context", "usuarios", email or "", "config.json")


# ----------------------------------------------------------------------
# Conteos baratos
# ----------------------------------------------------------------------
def _count_entries(path, want_dirs=False, suffix=None):
    """Cuenta archivos (o carpetas) en 'path'. Devuelve None si no existe."""
    if not path or not os.path.isdir(path):
        return None
    n = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if want_dirs:
                        if e.is_dir(follow_symlinks=False):
                            n += 1
                    elif e.is_file(follow_symlinks=False):
                        if suffix and not e.name.lower().endswith(suffix):
                            continue
                        n += 1
                except OSError:
                    continue
    except OSError:
        return None
    return n


def _newest_report(alumnos_dir):
    """(mtime, nombre) del FaceSync_Reporte_*.xlsx más reciente, o None."""
    if not os.path.isdir(alumnos_dir):
        return None
    best = None
    try:
        with os.scandir(alumnos_dir) as it:
            for e in it:
                name = e.name.lower()
                if name.startswith("facesync_reporte") and name.endswith(".xlsx"):
                    try:
                        m = e.stat().st_mtime
                    except OSError:
                        continue
                    if best is None or m > best[0]:
                        best = (m, e.name)
    except OSError:
        return None
    return best


def _gather_activity(email):
    """Construye una lista de actividad a partir de señales reales del sistema
    de archivos. Cada item: {icon, title, subtitle, ts}. Vacía si no hay nada."""
    acts = []
    alumnos = _alumnos_dir(email)

    rep = _newest_report(alumnos)
    if rep:
        acts.append({
            "icon": "🧠",
            "title": "Clasificación completada",
            "subtitle": f"Reporte generado · {rep[1]}",
            "ts": rep[0],
        })

    carpetas = _count_entries(alumnos, want_dirs=True)
    if carpetas:
        try:
            acts.append({
                "icon": "📁",
                "title": "Carpetas de clasificación",
                "subtitle": f"{carpetas:,} carpetas en ALUMNOS",
                "ts": os.path.getmtime(alumnos),
            })
        except OSError:
            pass

    cfg = _user_config_path(email)
    if os.path.isfile(cfg):
        try:
            acts.append({
                "icon": "🗂️",
                "title": "Espacio de trabajo actualizado",
                "subtitle": "Cambios guardados en tu workspace",
                "ts": os.path.getmtime(cfg),
            })
        except OSError:
            pass

    acts.sort(key=lambda a: a["ts"], reverse=True)
    return acts[:5]


# ----------------------------------------------------------------------
# API pública
# ----------------------------------------------------------------------
def gather_home_summary(email):
    """Resumen ligero para Inicio. Valores None = desconocido (estado vacío)."""
    summary = {
        "fotos_analizadas": None,
        "carpetas_clasificadas": None,
        "exportaciones": None,
        "actividad": [],
    }
    try:
        summary["fotos_analizadas"] = _count_entries(_embeddings_dir(), suffix=".json")
    except Exception:
        pass
    try:
        summary["carpetas_clasificadas"] = _count_entries(_alumnos_dir(email), want_dirs=True)
    except Exception:
        pass
    # Datos reales del workspace (reportes del motor + historial de exportaciones).
    try:
        from facesyncApp.ui import report_data as rd
        sums = rd.latest_report_summaries(email, cap=6)
        if sums:
            summary["carpetas_clasificadas"] = sum(
                int(s.get("total_personas") or 0) for s in sums) or summary["carpetas_clasificadas"]
            newest = sums[0]
            summary["actividad"] = ([{
                "icon": "🧠",
                "title": "Clasificación completada",
                "subtitle": f"{newest['carpeta']} · {newest.get('clasificadas') or 0:,} fotos",
                "ts": newest["ts"],
            }] + (summary["actividad"] or []))
        exps = rd.list_exports(email)
        if exps:
            summary["exportaciones"] = len(exps)
            summary["actividad"] = (summary["actividad"] or []) + [{
                "icon": "☁️",
                "title": "Exportación a Drive",
                "subtitle": exps[0].get("nombre", "—"),
                "ts": exps[0].get("ts", 0),
            }]
    except Exception:
        pass
    try:
        summary["actividad"] = (summary["actividad"] or []) + _gather_activity(email)
        summary["actividad"].sort(key=lambda a: a.get("ts", 0), reverse=True)
        summary["actividad"] = summary["actividad"][:5]
    except Exception:
        summary["actividad"] = summary["actividad"] or []
    return summary


def format_ts(epoch):
    """Formatea un timestamp epoch a texto relativo en español."""
    try:
        dt = datetime.fromtimestamp(epoch)
    except Exception:
        return ""
    now = datetime.now()
    hora = dt.strftime("%H:%M")
    delta_dias = (now.date() - dt.date()).days
    if delta_dias == 0:
        return f"Hoy, {hora}"
    if delta_dias == 1:
        return f"Ayer, {hora}"
    meses = ["ene", "feb", "mar", "abr", "may", "jun",
             "jul", "ago", "sep", "oct", "nov", "dic"]
    return f"{dt.day} {meses[dt.month - 1]}, {hora}"
