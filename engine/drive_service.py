"""
drive_service.py — Subida paralela a Google Drive (headless).

Port FIEL de la lógica de facesyncApp.dashboardback._ejecutar_subida_drive, sin
los widgets de CustomTkinter. Mantiene: ThreadPoolExecutor (15 workers), backoff
exponencial SOLO ante errores transitorios reales (clasificador 429/500/502/503
y 403-cuota), espejo de estructura de carpetas, rutas largas de Windows.

upload_folder(token_path, ruta_carpeta, on_progress) -> dict resumen.
"""

import os
import errno
import time
import random
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

_DRIVE_RATE_LIMIT_STATUS = {429, 500, 502, 503}
_DRIVE_RATE_LIMIT_REASONS = (
    "ratelimitexceeded", "userratelimitexceeded", "quotaexceeded",
    "backenderror", "internalerror", "rate limit",
)


def _clasificar_error_drive(exc) -> str:
    """'missing' | 'rate_limit' | 'fatal'. NO hace substring del código contra
    str(exc) (eso confundía 'IMG_6429.JPG' con un 429): usa tipo + status HTTP."""
    if isinstance(exc, FileNotFoundError):
        return "missing"
    if isinstance(exc, IsADirectoryError):
        return "fatal"
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ENOENT:
        return "missing"
    if isinstance(exc, HttpError):
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "resp", None), "status", None)
        try:
            status = int(status) if status is not None else None
        except (TypeError, ValueError):
            status = None
        if status in _DRIVE_RATE_LIMIT_STATUS:
            return "rate_limit"
        if status == 403:
            motivo = str(exc).lower()
            raw = getattr(exc, "content", b"") or b""
            if isinstance(raw, (bytes, bytearray)):
                motivo += " " + bytes(raw).decode("utf-8", errors="replace").lower()
            else:
                motivo += " " + str(raw).lower()
            return "rate_limit" if any(r in motivo for r in _DRIVE_RATE_LIMIT_REASONS) else "fatal"
        return "fatal"
    return "fatal"


def _ruta_drive_segura(path) -> str:
    """Prefijo de ruta extendida en Windows para superar MAX_PATH (260)."""
    p = os.path.abspath(str(path))
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        if p.startswith("\\\\"):
            p = "\\\\?\\UNC\\" + p[2:]
        else:
            p = "\\\\?\\" + p
    return p


def upload_folder(token_path, ruta_carpeta, on_progress=None, cancel_check=None):
    """Sube `ruta_carpeta` (recursivo) a una carpeta nueva en Drive.
    on_progress(dict) recibe {procesados,total,subidos} periódicamente.
    cancel_check(): callable opcional -> True para detener la subida (lo ya
    subido se conserva; los pendientes se omiten).
    Devuelve resumen {ok, drive_folder, drive_folder_id, subidos, omitidos,
    fallidos, reintentos, total, tiempo, nombre, canceled}."""
    if not os.path.isdir(ruta_carpeta):
        raise NotADirectoryError(f"no es carpeta: {ruta_carpeta}")

    def _cancelled():
        try:
            return bool(cancel_check and cancel_check())
        except Exception:
            return False

    nombre_carpeta = os.path.basename(os.path.abspath(ruta_carpeta))

    MAX_WORKERS, MAX_RETRIES, BACKOFF_BASE = 15, 5, 1.0
    lock = threading.Lock()
    c_sub = [0]; c_fail = [0]; c_miss = [0]; c_retry = [0]; c_proc = [0]; total = [0]
    t_start = time.time()

    def _emit():
        if not on_progress:
            return
        with lock:
            on_progress({"procesados": c_proc[0], "total": total[0], "subidos": c_sub[0]})

    creds = Credentials.from_authorized_user_file(
        token_path, scopes=["https://www.googleapis.com/auth/drive.file"])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        from oauth_service import _write_private_text
        from pathlib import Path
        _write_private_text(Path(token_path), creds.to_json())

    _tl = threading.local()

    def service():
        if not hasattr(_tl, "svc"):
            _tl.svc = build("drive", "v3", credentials=creds)
        return _tl.svc

    def escanear(ruta_local):
        """Devuelve (archivos, carpetas). Incluye TODAS las subcarpetas, también
        las vacías, para espejarlas en Drive aunque no tengan archivos."""
        res, dirs = [], set()
        for root, _subdirs, files in os.walk(ruta_local):
            rel = os.path.relpath(root, ruta_local).replace("\\", "/")
            if rel == ".":
                rel = ""
            if rel:
                dirs.add(rel)
            for f in files:
                res.append((os.path.join(root, f).replace("\\", "/"), rel))
        # ordenar por profundidad para crear los padres antes que los hijos
        return res, sorted(dirs, key=lambda d: (d.count("/"), d))

    archivos, all_dirs = escanear(ruta_carpeta)
    total[0] = len(archivos)
    _emit()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    drive_folder_name = f"FaceSync_{nombre_carpeta}_{timestamp}"
    svc_main = service()
    main_folder = svc_main.files().create(
        body={"name": drive_folder_name, "mimeType": "application/vnd.google-apps.folder"},
        fields="id").execute()
    main_id = main_folder.get("id")

    # Estructura de carpetas (secuencial, son pocas). TODAS las carpetas, incl.
    # las vacías -> el árbol completo se replica en Drive.
    remotas = {"": main_id}
    for rel_path in all_dirs:
        partes = rel_path.split("/")
        for i in range(len(partes)):
            sub = "/".join(partes[:i + 1])
            if sub in remotas:
                continue
            parent = remotas["/".join(partes[:i]) if i > 0 else ""]
            folder = svc_main.files().create(
                body={"name": partes[i], "parents": [parent],
                      "mimeType": "application/vnd.google-apps.folder"},
                fields="id").execute()
            remotas[sub] = folder.get("id")

    def subir(file_path, rel_folder):
        # Cancelación: los archivos aún no subidos se omiten al instante.
        if _cancelled():
            with lock:
                c_miss[0] += 1; c_proc[0] += 1
            _emit(); return False
        parent_id = remotas.get(rel_folder, main_id)
        file_name = os.path.basename(file_path)
        safe = _ruta_drive_segura(file_path)
        if not os.path.isfile(safe):
            with lock:
                c_miss[0] += 1; c_proc[0] += 1
            _emit(); return False
        for intento in range(MAX_RETRIES):
            try:
                media = MediaFileUpload(safe, resumable=True)
                service().files().create(
                    body={"name": file_name, "parents": [parent_id]},
                    media_body=media, fields="id").execute()
                with lock:
                    c_sub[0] += 1; c_proc[0] += 1
                _emit(); return True
            except Exception as e:
                cat = _clasificar_error_drive(e)
                if cat == "missing":
                    with lock:
                        c_miss[0] += 1; c_proc[0] += 1
                    _emit(); return False
                if cat == "rate_limit" and intento < MAX_RETRIES - 1:
                    with lock:
                        c_retry[0] += 1
                    time.sleep(BACKOFF_BASE * (2 ** intento) + random.uniform(0, 1))
                    continue
                with lock:
                    c_fail[0] += 1; c_proc[0] += 1
                _emit(); return False
        return False

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(subir, fp, rf): fp for fp, rf in archivos}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception:
                with lock:
                    c_fail[0] += 1

    elapsed = time.time() - t_start
    canceled = _cancelled()
    return {
        "ok": (not canceled) and c_fail[0] == 0 and c_miss[0] == 0,
        "canceled": canceled,
        "drive_folder": drive_folder_name,
        "drive_folder_id": main_id,
        "nombre": nombre_carpeta,
        "subidos": c_sub[0], "omitidos": c_miss[0], "fallidos": c_fail[0],
        "reintentos": c_retry[0], "total": total[0], "tiempo": round(elapsed, 1),
    }
