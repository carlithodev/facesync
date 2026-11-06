"""
FaceSync AI — Datos de la vista Reportes (Fase 5). SOLO LECTURA.

Lista los reportes que el motor ya genera (FaceSync_Reporte_*.xlsx y otros
.xlsx/.json/.txt/.csv en usuarios/<email>/ALUMNOS) y, de forma diferida, lee el
detalle del reporte seleccionado (openpyxl, read-only). No toca backend/motor.
Si no hay reportes, devuelve lista vacía -> la vista muestra estado vacío.
"""

import os
from datetime import datetime

from facesyncApp import BASE_DIR

_TIPOS = {".xlsx": "Excel", ".xls": "Excel", ".json": "JSON",
          ".txt": "TXT", ".csv": "CSV"}


def _alumnos_dir(email):
    return os.path.join(_app_data_root(), "usuarios", email or "", "ALUMNOS")


def _fmt(ts):
    try:
        return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""


def _app_data_root():
    """Raíz de datos de la app SIN crear nada."""
    try:
        from core.app_paths import default_app_data_root
        return str(default_app_data_root())
    except Exception:
        local = os.environ.get("LOCALAPPDATA")
        return os.path.join(local, "FaceSync") if local else os.path.join(
            os.path.expanduser("~"), ".facesync")


def workspace_roots(email):
    """Carpetas raíz del workspace del usuario (config.json, SOLO LECTURA)."""
    cfg = os.path.join(_app_data_root(), "context", "usuarios", email or "", "config.json")
    try:
        import json
        with open(cfg, "r", encoding="utf-8") as f:
            roots = (json.load(f) or {}).get("folder_roots") or []
        return [r for r in roots if r and os.path.isdir(r)]
    except Exception:
        return []


_SKIP_WALK = {".git", "__pycache__", "env", "venv", "env_ia", "node_modules",
              ".facesync_cache", "pendientes", "_pendientes_revision"}
_REPORT_NAMES = ("_reporte_facesync.json", "_reporte_facesync.txt",
                 "_reporte_facesync.xlsx")


def _walk_reports(root, max_depth=4):
    """Encuentra archivos de reporte del motor bajo `root` (profundidad acotada)."""
    root = os.path.abspath(root)
    base_depth = root.replace("\\", "/").count("/")
    found = []
    for cur, dirs, files in os.walk(root):
        if cur.replace("\\", "/").count("/") - base_depth >= max_depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d.lower() not in _SKIP_WALK]
        for fn in files:
            low = fn.lower()
            if low in _REPORT_NAMES or (low.startswith("facesync_reporte") and low.endswith(".xlsx")):
                found.append(os.path.join(cur, fn))
    return found


def list_reports(email):
    """Reportes del usuario: los del motor en las carpetas del WORKSPACE
    (\\_reporte_facesync.*, aparecen solos al terminar una clasificación) +
    los del directorio legado usuarios/<email>/ALUMNOS. SOLO LECTURA."""
    seen = set()
    out = []

    def add(path):
        p = path.replace("\\", "/")
        if p in seen:
            return
        ext = os.path.splitext(p)[1].lower()
        if ext not in _TIPOS:
            return
        seen.add(p)
        try:
            ts = os.stat(path).st_mtime
        except OSError:
            ts = 0
        out.append({
            "path": p, "nombre": os.path.basename(p),
            "tipo": _TIPOS[ext], "ext": ext, "ts": ts, "fecha": _fmt(ts),
            "carpeta": os.path.basename(os.path.dirname(p)) or p,
            "estado": "Completado",
        })

    # Raíces del workspace actual + TODOS los destinos donde se ha clasificado
    # alguna vez (historial acumulado) -> los reportes de clasificaciones
    # pasadas no desaparecen aunque cambies de carpeta destino.
    roots = list(workspace_roots(email))
    for d in classify_dests(email):
        if d not in roots:
            roots.append(d)
    for root in roots:
        try:
            for p in _walk_reports(root):
                add(p)
        except OSError:
            continue

    base = _alumnos_dir(email)
    if os.path.isdir(base):
        try:
            with os.scandir(base) as it:
                for e in it:
                    if e.is_file(follow_symlinks=False):
                        add(e.path)
        except OSError:
            pass

    out.sort(key=lambda r: r["ts"], reverse=True)
    return out 


def latest_report_summaries(email, cap=12):
    """Resumen pequeño del JSON más reciente por carpeta destino (en worker)."""
    import json
    newest = {}
    for r in list_reports(email):
        if r["ext"] != ".json" or not r["nombre"].startswith("_reporte"):
            continue
        key = os.path.dirname(r["path"])
        if key not in newest or r["ts"] > newest[key]["ts"]:
            newest[key] = r
    res = []
    for r in sorted(newest.values(), key=lambda x: x["ts"], reverse=True)[:cap]:
        try:
            with open(r["path"], "r", encoding="utf-8") as f:
                d = json.load(f) or {}
            diag = d.get("diagnostico") or {}
            res.append({
                "carpeta": r["carpeta"], "path": r["path"], "ts": r["ts"],
                "total_personas": d.get("total_personas"),
                "clasificadas": d.get("total_fotos_copiadas"),
                "entregadas": d.get("archivos_entregados_totales"),
                "analizadas": d.get("total_fotos_analizadas"),
                "pendientes": diag.get("total_pendientes_reales"),
                "porcentaje": diag.get("porcentaje_clasificado"),
                "fotos_por_persona": {k: len(v) for k, v in
                                      (d.get("fotos_por_persona") or {}).items()},
            })
        except Exception:
            continue
    return res


def classified_folder_ranking(email, top=5):
    """Ranking de carpetas de alumnos por nº de fotos (del último reporte por
    destino; suma si hay varios destinos). Fallback: ALUMNOS legado."""
    counts = {}
    for s in latest_report_summaries(email):
        for name, n in (s.get("fotos_por_persona") or {}).items():
            counts[name] = counts.get(name, 0) + int(n or 0)
    res = [{"nombre": k, "count": v} for k, v in counts.items()]
    res.sort(key=lambda x: x["count"], reverse=True)
    if res:
        return res[:top]
    # Fallback legado
    base = _alumnos_dir(email)
    legacy = []
    if os.path.isdir(base):
        try:
            with os.scandir(base) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        try:
                            n = sum(1 for f in os.scandir(e.path)
                                    if f.is_file(follow_symlinks=False))
                        except OSError:
                            n = 0
                        legacy.append({"nombre": e.name, "count": n})
        except OSError:
            pass
    legacy.sort(key=lambda x: x["count"], reverse=True)
    return legacy[:top]


# ----------------------------------------------------------------------
# Historial de destinos de clasificación (lo escribe el motor al terminar).
# Permite que la sección Reportes acumule TODAS las clasificaciones, no solo
# las de las carpetas raíz del workspace actual.
# ----------------------------------------------------------------------
def _classify_dests_path(email):
    return os.path.join(_app_data_root(), "context", "usuarios",
                        email or "", "classify_dests.json")


def classify_dests(email):
    """Destinos donde se ha clasificado (existentes), más reciente 1º."""
    import json
    try:
        with open(_classify_dests_path(email), "r", encoding="utf-8") as f:
            data = json.load(f) or []
        return [d for d in data if d and os.path.isdir(d)]
    except Exception:
        return []


def append_classify_dest(email, destino):
    """Registra un destino de clasificación (best-effort, sin duplicados)."""
    import json
    if not destino:
        return False
    try:
        path = _classify_dests_path(email)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        dest = os.path.abspath(destino).replace("\\", "/")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or []
        except Exception:
            data = []
        data = [d for d in data if d != dest]
        data.insert(0, dest)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data[:200], f, ensure_ascii=False, indent=1)
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------
# Historial de exportaciones (lo escribe la UI al terminar un export a Drive)
# ----------------------------------------------------------------------
def _exports_path(email):
    return os.path.join(_app_data_root(), "context", "usuarios",
                        email or "", "export_history.json")


def list_exports(email):
    """Historial de exportaciones persistido por la UI (lista, más reciente 1º)."""
    import json
    try:
        with open(_exports_path(email), "r", encoding="utf-8") as f:
            data = json.load(f) or []
        data.sort(key=lambda r: r.get("ts", 0), reverse=True)
        return data
    except Exception:
        return []


def append_export(email, record):
    """Agrega un registro al historial (best-effort; nunca rompe el flujo)."""
    import json
    import time
    try:
        path = _exports_path(email)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = list_exports(email)
        record = dict(record or {})
        record.setdefault("ts", time.time())
        record.setdefault("fecha", _fmt(record["ts"]))
        data.insert(0, record)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data[:200], f, ensure_ascii=False, indent=1)
        return True
    except Exception:
        return False


def count_classified(email):
    """Fotos clasificadas: suma de los últimos reportes del workspace; si no
    hay reportes, cuenta el ALUMNOS legado."""
    try:
        sums = latest_report_summaries(email)
        total = sum(int(s.get("clasificadas") or 0) for s in sums)
        if total:
            return total
    except Exception:
        pass
    base = _alumnos_dir(email)
    if not os.path.isdir(base):
        return None
    total, any_dir = 0, False
    try:
        with os.scandir(base) as it:
            for e in it:
                if not e.is_dir(follow_symlinks=False):
                    continue
                any_dir = True
                try:
                    with os.scandir(e.path) as it2:
                        for f in it2:
                            if f.is_file(follow_symlinks=False):
                                total += 1
                except OSError:
                    pass
    except OSError:
        return None
    return total if any_dir else None


def build_match_index(email, extra_dests=None, cap=60000):
    """Índice SOLO LECTURA basename(lower) -> [(persona, carpeta, archivo), ...]
    a partir de las carpetas de SALIDA de clasificación (subcarpetas-persona con
    fotos ya copiadas). Permite saber a qué persona se clasificó una imagen sin
    llamar al motor. Pensado para correr en un worker; resultado cacheable.

    Fuentes: usuarios/<email>/ALUMNOS + destinos extra (los usados al clasificar).
    """
    dests = [_alumnos_dir(email)]
    for d in (extra_dests or []):
        if d and d not in dests:
            dests.append(d)
    index = {}
    n = 0
    for base in dests:
        if not base or not os.path.isdir(base):
            continue
        try:
            with os.scandir(base) as it:
                persons = [(e.name, e.path) for e in it if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for person, ppath in persons:
            try:
                with os.scandir(ppath) as it2:
                    for f in it2:
                        if not f.is_file(follow_symlinks=False):
                            continue
                        entry = (person, ppath.replace("\\", "/"), f.path.replace("\\", "/"))
                        lst = index.setdefault(f.name.lower(), [])
                        if entry not in lst:
                            lst.append(entry)
                        n += 1
                        if n >= cap:
                            return index
            except OSError:
                continue
    return index


def report_detail(path):
    """Detalle del reporte seleccionado (lazy). JSON del motor directo; xlsx
    con openpyxl."""
    d = {"nombre": os.path.basename(path), "estado": "Completado",
         "origen": "—", "destino": "—",
         "analizadas": None, "clasificadas": None, "pendientes": None}
    try:
        d["destino"] = os.path.basename(os.path.dirname(path))
    except Exception:
        pass
    low = os.path.basename(path).lower()
    if low.endswith(".json") and low.startswith("_reporte"):
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                rep = json.load(f) or {}
            srcs = rep.get("source_folders") or [rep.get("source_folder") or "—"]
            d["origen"] = ", ".join(str(s) for s in srcs[:3]) + ("…" if len(srcs) > 3 else "")
            d["destino"] = rep.get("destination_folder") or d["destino"]
            d["analizadas"] = rep.get("total_fotos_analizadas")
            d["clasificadas"] = rep.get("total_fotos_copiadas")
            diag = rep.get("diagnostico") or {}
            d["pendientes"] = diag.get("total_pendientes_reales")
        except Exception:
            pass
        return d
    if os.path.splitext(path)[1].lower() not in (".xlsx", ".xls"):
        return d
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        headers = next(rows, None) or ()
        headers = [str(h).strip().lower() if h is not None else "" for h in headers]
        est_idx = next((i for i, h in enumerate(headers) if "estado" in h), None)
        ori_idx = next((i for i, h in enumerate(headers)
                        if "origen" in h or "ruta" in h or "archivo" in h), None)
        n, clf, origen = 0, 0, None
        for r in rows:
            if r is None or all(c is None for c in r):
                continue
            n += 1
            if est_idx is not None and est_idx < len(r):
                v = str(r[est_idx] or "").lower()
                if any(k in v for k in ("proces", "clasif", "ok", "copiad", "match")):
                    clf += 1
            if origen is None and ori_idx is not None and ori_idx < len(r) and r[ori_idx]:
                try:
                    origen = os.path.basename(os.path.dirname(str(r[ori_idx]))) or str(r[ori_idx])
                except Exception:
                    origen = str(r[ori_idx])
        wb.close()
        d["analizadas"] = n
        if est_idx is not None:
            d["clasificadas"], d["pendientes"] = clf, max(0, n - clf)
        else:
            d["clasificadas"], d["pendientes"] = n, 0
        if origen:
            d["origen"] = origen
    except Exception:
        pass
    return d
