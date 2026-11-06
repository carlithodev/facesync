"""
bridge.py — Sidecar FaceSyncV2 (engine).

Capa FINA entre React/Tauri y el motor IA Python. NO toca el motor: solo lo
invoca. Protocolo JSON-lines por stdin/stdout.

  Petición  (stdin, 1 JSON por línea):
      {"id": "<str>", "cmd": "<str>", "args": {...}}

  Respuestas (stdout, 1 JSON por línea):
      {"id": "<str>", "type": "progress", "data": {...}}
      {"id": "<str>", "type": "result",   "ok": true,  "data": {...}}
      {"id": "<str>", "type": "error",     "ok": false, "error": "<msg>"}

CRÍTICO: el motor (DeepFace/ONNX) escribe muchísimo con print() a stdout. Eso
corrompería el canal de protocolo. Solución: al arrancar redirigimos
sys.stdout -> stderr, y el protocolo se escribe SOLO por el handle real de
stdout, guardado aparte. Todo log de librerías va a stderr (lo lee Tauri como
diagnóstico, no como protocolo).
"""

import sys
import os
import io
import json
import threading
import traceback

# DeepFace y RetinaFace todavía construyen sus modelos con la API Keras 2.
# Este indicador debe existir ANTES de que cualquier import indirecto cargue
# TensorFlow; configurarlo después deja RetinaFace bajo Keras 3 y todas las
# referencias fallan al crear su embedding con un error de KerasTensor.
os.environ["TF_USE_LEGACY_KERAS"] = "1"

from core.path_policy import WorkspacePathPolicy, safe_account_id, safe_component

# --- Separación de canales (debe ocurrir ANTES de importar el motor) --------
_REAL_STDOUT = sys.stdout
try:  # asegurar UTF-8 en ambos canales
    _REAL_STDOUT.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
# Cualquier print() de librerías -> stderr, nunca al protocolo.
sys.stdout = sys.stderr

# BASE_DIR del engine = carpeta de este archivo (= raíz del paquete facesyncApp).
ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

# En el paquete congelado: registra explícitamente los directorios de DLLs
# nativas. TensorFlow carga DLLs anidadas (tensorflow/lite/python/…) cuyas
# dependencias (runtime VC++ que Win10 no trae en System32) viven en la raíz del
# bundle. Al lanzarse desde la app (spawn) la búsqueda por defecto NO siempre las
# encuentra aunque estén bundleadas; add_dll_directory lo hace determinista.
if getattr(sys, "frozen", False):
    _dll_base = getattr(sys, "_MEIPASS", ENGINE_DIR)
    for _sub in ("", "tensorflow", os.path.join("tensorflow", "python"),
                 os.path.join("tensorflow", "lite", "python")):
        _d = os.path.join(_dll_base, _sub) if _sub else _dll_base
        try:
            if os.path.isdir(_d):
                os.add_dll_directory(_d)
        except Exception:
            pass


def _writable_app_root():
    """Raíz de datos escribible (LocalAppData/FaceSync). Sin crear el árbol."""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "FaceSync")
    return os.path.join(os.path.expanduser("~"), ".facesync")


def _bundled_dir(name):
    """Carpeta de datos bundleada (`name`), tanto en dev como congelado por
    PyInstaller. En frozen, los datas viven en sys._MEIPASS; en dev, junto a
    este archivo (ENGINE_DIR). Devuelve la primera que exista."""
    for base in (getattr(sys, "_MEIPASS", None), ENGINE_DIR):
        if base:
            cand = os.path.join(base, name)
            if os.path.isdir(cand):
                return cand
    return os.path.join(ENGINE_DIR, name)


def _setup_deepface_home():
    """Blindaje de empaque: DEEPFACE_HOME -> carpeta escribible + siembra los
    pesos .h5 bundleados (engine/weights) para que DeepFace y RetinaFace NUNCA
    descarguen ~255MB de internet en el primer uso. Best-effort: si algo falla,
    DeepFace cae a su descarga normal (no rompe el flujo). DEBE correr ANTES de
    importar el motor (que importa deepface)."""
    try:
        import shutil
        home = os.path.join(_writable_app_root(), "deepface")
        weights_dir = os.path.join(home, ".deepface", "weights")
        os.makedirs(weights_dir, exist_ok=True)
        os.environ.setdefault("DEEPFACE_HOME", home)
        bundled = _bundled_dir("weights")
        for fn in ("arcface_weights.h5", "retinaface.h5"):
            src = os.path.join(bundled, fn)
            dst = os.path.join(weights_dir, fn)
            try:
                if os.path.isfile(src) and (
                    not os.path.isfile(dst)
                    or os.path.getsize(dst) != os.path.getsize(src)
                ):
                    shutil.copyfile(src, dst)
            except OSError:
                pass
    except Exception:
        pass


def _seed_private_config():
    """Si se bundlearon credenciales (engine/config: client_secret.json / .env),
    las copia al config privado escribible la 1ª vez -> login Google + chat
    quedan listos sin que el usuario coloque archivos a mano. Opt-in y
    best-effort: sin estos archivos la app degrada (clasificación NO se afecta)."""
    try:
        import shutil
        src_dir = _bundled_dir("config")
        if not os.path.isdir(src_dir):
            return
        dst_dir = os.path.join(_writable_app_root(), "config")
        os.makedirs(dst_dir, exist_ok=True)
        for fn in ("client_secret.json", ".env"):
            src = os.path.join(src_dir, fn)
            dst = os.path.join(dst_dir, fn)
            try:
                if os.path.isfile(src) and not os.path.isfile(dst):
                    shutil.copyfile(src, dst)
            except OSError:
                pass
    except Exception:
        pass


_setup_deepface_home()
_seed_private_config()

# PASADA UNICA CR2: con la conversion rapida activa (FACESYNC_CR2_FAST, default
# ON), cada CR2 se analiza UNA sola vez a calidad completa (preview embebido a
# resolucion half_size). La doble pasada del indice rapido (preview + completa)
# se vuelve redundante -> se apaga por defecto. setdefault respeta un override
# explicito del usuario; FACESYNC_CR2_FAST=0 restaura el comportamiento previo.
if os.environ.get("FACESYNC_CR2_FAST", "1").strip().lower() not in ("0", "off", "false"):
    os.environ.setdefault("FACESYNC_FAST_INDEX", "off")

_OUT_LOCK = threading.Lock()


def _emit(obj):
    """Escribe un mensaje de protocolo (JSON-line) por el stdout real, atómico."""
    line = json.dumps(obj, ensure_ascii=False)
    with _OUT_LOCK:
        _REAL_STDOUT.write(line + "\n")
        _REAL_STDOUT.flush()


def emit_progress(req_id, data):
    _emit({"id": req_id, "type": "progress", "data": data})


def emit_result(req_id, data=None):
    _emit({"id": req_id, "type": "result", "ok": True, "data": data if data is not None else {}})


def emit_error(req_id, msg):
    _emit({"id": req_id, "type": "error", "ok": False, "error": str(msg)})


_LOGFILE = None


def _logfile_path():
    global _LOGFILE
    if _LOGFILE is not None:
        return _LOGFILE
    try:
        d = os.path.join(_writable_app_root(), "logs")
        os.makedirs(d, exist_ok=True)
        _LOGFILE = os.path.join(d, "sidecar.log")
    except Exception:
        _LOGFILE = ""
    return _LOGFILE


def log(*a):
    """Diagnóstico a stderr (no es protocolo) + a un archivo persistente para
    poder depurar fallos que solo ocurren al lanzar desde la app."""
    msg = "[bridge] " + " ".join(str(x) for x in a)
    print(msg, file=sys.stderr, flush=True)
    p = _logfile_path()
    if p:
        try:
            # Rota si crece demasiado (>1MB) para no acumular sin límite.
            if os.path.isfile(p) and os.path.getsize(p) > 1_000_000:
                os.replace(p, p + ".old")
            with open(p, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass


# ============================================================================
# Estado de trabajos en curso (para cancelar)
# ============================================================================
_JOBS = {}          # req_id -> {"cancel": bool}
_JOBS_LOCK = threading.Lock()
_WORKER_SLOTS = threading.BoundedSemaphore(8)
# Se activa cuando TensorFlow/DeepFace ya están cargados en MAIN. El login y el
# resto de la UI NO esperan esto; solo clasificar lo necesita.
_HEAVY_READY = threading.Event()
# Clasificaciones que llegan ANTES de que el motor pesado esté caliente se
# ESTACIONAN aquí y se despachan al terminar el warm. NUNCA se bloquea un hilo
# esperando (un hilo bloqueado en un wait mientras MAIN carga las DLLs de
# TensorFlow deadlockea el import en Windows — loader lock; reproducido).
_PARK_LOCK = threading.Lock()
_PARKED = []


def _job_new(req_id):
    cancel_event = threading.Event()
    with _JOBS_LOCK:
        _JOBS[req_id] = {"cancel": False, "event": cancel_event}
    return cancel_event


def _job_cancelled(req_id):
    with _JOBS_LOCK:
        j = _JOBS.get(req_id)
        return bool(j and j["cancel"])


def _job_cancel(req_id):
    with _JOBS_LOCK:
        j = _JOBS.get(req_id)
        if j:
            j["cancel"] = True
            event = j.get("event")
            if event is not None:
                event.set()
            return True
    return False


def _job_done(req_id):
    with _JOBS_LOCK:
        _JOBS.pop(req_id, None)


# ============================================================================
# COMANDOS
# ============================================================================

def cmd_ping(req_id, args):
    emit_result(req_id, {"pong": True})


def cmd_gpu_info(req_id, args):
    """Providers ONNX + si la GPU (DirectML) está disponible para el motor v3."""
    info = {}
    try:
        import onnxruntime as ort
        info["onnxruntime"] = ort.__version__
        info["providers"] = list(ort.get_available_providers())
    except Exception as e:
        info["onnxruntime_error"] = f"{type(e).__name__}: {e}"
    try:
        from facesyncApp.motor_ia_v3 import gpu_disponible
        info["gpu_disponible"] = bool(gpu_disponible())
    except Exception as e:
        info["gpu_error"] = f"{type(e).__name__}: {e}"
    info["motor_forzado"] = os.environ.get("FACESYNC_MOTOR", "auto")
    emit_result(req_id, info)


def cmd_diag_cr2_ab(req_id, args):
    """Validador A/B de la ruta RAW. Para cada CR2/CR3 de una carpeta:
    genera el JPG por la ruta VIEJA (decode RAW half_size) y por la NUEVA
    (preview embebido escalado a half_size), corre DeepFace.represent en ambos
    y compara: nº de rostros y distancia coseno entre embeddings emparejados.
    Distancias ~0 (<0.05) = rutas equivalentes -> la meta queda firmada.
    args: {"folder": str, "max_photos"?: int}"""
    folder = args.get("folder")
    if not (folder and os.path.isdir(folder)):
        emit_error(req_id, f"carpeta inválida: {folder}")
        return
    max_photos = int(args.get("max_photos") or 25)
    try:
        import io
        import tempfile
        import numpy as np
        import rawpy
        from PIL import Image, ImageOps
        from deepface import DeepFace

        def faces_of(path):
            r = DeepFace.represent(img_path=str(path), model_name="ArcFace",
                                   detector_backend="retinaface", enforce_detection=False)
            return [x["embedding"] for x in (r or []) if isinstance(x, dict) and x.get("embedding")]

        def cos_dist(a, b):
            a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
            return float(1.0 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))

        results, done = [], 0
        for fn in sorted(os.listdir(folder)):
            extension = os.path.splitext(fn)[1].lower()
            if extension not in {".cr2", ".cr3"} or done >= max_photos:
                continue
            src = os.path.join(folder, fn)
            row = {"foto": fn, "formato": extension.lstrip(".").upper()}
            try:
                with rawpy.imread(src) as raw:
                    half_w = max(1, int(raw.sizes.width) // 2)
                    half_h = max(1, int(raw.sizes.height) // 2)
                    rgb = raw.postprocess(half_size=True)
                    old_im = Image.fromarray(rgb)
                    try:
                        thumb = raw.extract_thumb()
                    except Exception:
                        thumb = None
                new_im = None
                if thumb is not None and thumb.format == rawpy.ThumbFormat.JPEG:
                    im = Image.open(io.BytesIO(thumb.data)); im.load()
                    im = ImageOps.exif_transpose(im) or im
                    w, h = im.size
                    if (w >= half_w and h >= half_h) or (w >= half_h and h >= half_w):
                        tw, th = (half_w, half_h) if (w >= half_w and h >= half_h) else (half_h, half_w)
                        new_im = im.convert("RGB").resize((tw, th), Image.LANCZOS)
                row["preview_valido"] = new_im is not None
                if new_im is None:
                    row["veredicto"] = "fallback (usaria ruta vieja: sin riesgo)"
                    results.append(row); done += 1
                    continue
                with tempfile.TemporaryDirectory() as td:
                    p_old, p_new = os.path.join(td, "old.jpg"), os.path.join(td, "new.jpg")
                    old_im.save(p_old, "JPEG", quality=90)
                    new_im.save(p_new, "JPEG", quality=90)
                    f_old, f_new = faces_of(p_old), faces_of(p_new)
                row["rostros_viejo"], row["rostros_nuevo"] = len(f_old), len(f_new)
                if f_old and f_new:
                    dists = []
                    for e_old in f_old:
                        dists.append(min(cos_dist(e_old, e_new) for e_new in f_new))
                    row["dist_max"] = round(max(dists), 4)
                    row["veredicto"] = ("EQUIVALENTE" if max(dists) < 0.05 and len(f_old) == len(f_new)
                                        else "REVISAR")
                else:
                    row["veredicto"] = "EQUIVALENTE (sin rostros en ambas)" if not f_old and not f_new else "REVISAR"
                results.append(row); done += 1
            except Exception as e:
                row["error"] = f"{type(e).__name__}: {e}"
                results.append(row); done += 1
        ok = sum(1 for r in results if str(r.get("veredicto", "")).startswith("EQUIVALENTE"))
        fb = sum(1 for r in results if "fallback" in str(r.get("veredicto", "")))
        emit_result(req_id, {"total": len(results), "equivalentes": ok,
                             "fallbacks_seguros": fb,
                             "revisar": len(results) - ok - fb,
                             "detalle": results})
    except Exception:
        emit_result(req_id, {"ok": False, "traceback": traceback.format_exc()})


def cmd_diag_represent(req_id, args):
    """Diagnóstico: corre DeepFace.represent con los MISMOS parámetros que usa
    el motor sobre una foto, y devuelve el resultado o el traceback COMPLETO.
    El motor traga estas excepciones (referencia 'inválida' sin causa visible);
    este comando las expone. No toca el motor."""
    path = args.get("path")
    if not (path and os.path.isfile(path)):
        emit_error(req_id, f"foto inválida: {path}")
        return
    info = {"TF_USE_LEGACY_KERAS": os.environ.get("TF_USE_LEGACY_KERAS")}
    try:
        import tensorflow as tf
        info["tf_keras_resuelto"] = repr(tf.keras)  # KerasLazyLoader dice cuál keras usa
    except Exception as e:
        info["tf_keras_resuelto"] = f"error: {e}"
    try:
        from deepface import DeepFace
        results = DeepFace.represent(
            img_path=str(path),
            model_name=args.get("model_name") or "ArcFace",
            detector_backend=args.get("detector_backend") or "retinaface",
            enforce_detection=False,
        )
        faces = [
            {"confidence": float(r.get("face_confidence", 0.0)),
             "embedding_len": len(r.get("embedding") or [])}
            for r in (results or []) if isinstance(r, dict)
        ]
        emit_result(req_id, {"ok": True, "rostros": len(faces), "detalle": faces, **info})
    except Exception:
        emit_result(req_id, {"ok": False, "traceback": traceback.format_exc(), **info})


def cmd_diag_cr3_measurements(req_id, args):
    """Genera mediciones CR3 de los Módulos 1/2 sin cambiar reglas.

    args: {"manifest": str, "source_folder": str, "output": str,
           "include_representation_analysis"?: bool, "email"?: str}
    Los embeddings permanecen en memoria; el JSON contiene únicamente cajas,
    confianza, distancias y métricas explicables.
    """
    if not _HEAVY_READY.wait(timeout=180):
        emit_error(req_id, "El motor facial no terminó de inicializarse.")
        return
    try:
        manifest_path = _workspace_path(args.get("manifest"), must_exist=True)
        source_folder = _workspace_path(args.get("source_folder"), must_exist=True)
        output_path = _workspace_path(args.get("output"))
    except (OSError, ValueError) as exc:
        emit_error(req_id, f"ruta fuera del workspace: {exc}")
        return
    if not os.path.isfile(manifest_path):
        emit_error(req_id, "manifiesto CR3 inválido")
        return
    if not os.path.isdir(source_folder):
        emit_error(req_id, "carpeta CR3 inválida")
        return
    if not output_path:
        emit_error(req_id, "ruta de salida requerida")
        return
    try:
        from pathlib import Path
        from core.security import SecurityManager
        from deepface import DeepFace
        from tools.cr3_evaluator import load_manifest, measure_cr3_manifest
        from tools.facesync_tools import FaceSyncCapabilities

        roots = [str(path) for path in _path_policy().roots]
        security = SecurityManager(workspace_path=roots[0])
        security.set_workspace_roots(roots)
        motor = FaceSyncCapabilities(
            workspace_path=roots[0],
            security_manager=security,
            account_id=_email(args) or "module1-cr3-evaluator",
        )
        manifest = load_manifest(Path(manifest_path))

        def progress(payload):
            data = dict(payload or {})
            data.update({"estado": "running", "frac": float(data.get("percent", 0)) / 100.0})
            emit_progress(req_id, data)

        result = measure_cr3_manifest(
            motor,
            manifest,
            Path(source_folder),
            DeepFace,
            progress_callback=progress,
            include_representation_analysis=bool(
                args.get("include_representation_analysis", False)
            ),
        )
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(destination)
        emit_result(req_id, {
            "ok": True,
            "output": str(destination),
            "photo_count": result.get("photo_count"),
            "summaries": result.get("summaries"),
            "representation_analysis": bool(result.get("representation_analysis")),
        })
    except Exception:
        emit_result(req_id, {"ok": False, "traceback": traceback.format_exc()})


# Cada fase del motor reporta 0-100% de SÍ misma. Para una barra global y
# monótona, mapeamos cada fase a un tramo del total (pesos por tiempo típico).
# Esto NO toca el motor: solo reinterpreta el porcentaje que ve la UI.
_CLASSIFY_STAGE_SPAN = {
    "started": (0.00, 0.01),
    "listed_images": (0.01, 0.03),
    "extracting_references": (0.03, 0.08),
    "indexing_faces": (0.08, 0.25),
    "extracting_faces": (0.25, 0.65),
    "comparing": (0.65, 0.72),
    "copying": (0.72, 0.95),
    "reporting": (0.95, 0.98),
    "finalizing": (0.98, 0.995),
    "done": (1.00, 1.00),
}


def cmd_classify_start(req_id, args):
    """Clasifica todas las fotos contra las referencias del Excel/CSV.

    args: {
      "carpeta_fotos": str,   "excel": str,   "destino": str,
      "columna_nombre"?: str, "columna_referencia"?: str
    }

    Usa el flujo moderno del FaceSync original. Este flujo escanea todas las
    fotos compatibles, admite varios rostros por imagen, resuelve referencias
    numéricas repetidas y genera reportes JSON/TXT/XLSX.
    """
    # Multi-origen: se envía como un solo lote, igual que en FaceSync original.
    raw_sources = args.get("sources") or ([args.get("carpeta_fotos")] if args.get("carpeta_fotos") else [])
    try:
        sources = [_workspace_path(s, must_exist=True) for s in raw_sources if s]
        sources = [s for s in sources if os.path.isdir(s)]
        excel = _workspace_path(args.get("excel") or args.get("table_path"), must_exist=True)
        destino = _workspace_path(args.get("destino") or args.get("destination_folder"))
    except (OSError, ValueError) as e:
        emit_error(req_id, f"ruta fuera del workspace: {e}")
        return
    if not sources:
        emit_error(req_id, "carpeta(s) origen inválida(s)")
        return
    if not (excel and os.path.isfile(excel)):
        emit_error(req_id, f"excel inválido: {excel}")
        return
    if not destino:
        emit_error(req_id, "destino requerido")
        return

    col_nombre = args.get("columna_nombre") or args.get("name_column") or "Nombre del Alumno"
    col_ref = args.get("columna_referencia") or args.get("reference_column") or "Foto"

    cancel_event = _job_new(req_id)
    # Cuando este handler corre, el motor pesado YA está caliente: dispatch()
    # estaciona las clasificaciones tempranas y las re-despacha tras el warm.
    # PROHIBIDO bloquear aquí esperando el warm (deadlock del loader-lock).
    try:
        from core.security import SecurityManager
        from tools.facesync_tools import FaceSyncCapabilities

        roots = [str(path) for path in _path_policy().roots]
        if not roots:
            emit_error(req_id, "No hay carpetas registradas en el workspace.")
            return

        security = SecurityManager(workspace_path=roots[0])
        security.set_workspace_roots(roots)
        motor = FaceSyncCapabilities(
            workspace_path=roots[0],
            security_manager=security,
            account_id=_email(args) or "default",
        )

        _last_frac = [0.0]

        def progress_callback(payload):
            data = dict(payload or {})
            stage = data.get("stage") or ""
            percent = max(0, min(100, int(data.get("percent") or 0)))
            span = _CLASSIFY_STAGE_SPAN.get(stage)
            if span:
                lo, hi = span
                frac = lo + (hi - lo) * (percent / 100.0)
            else:
                frac = _last_frac[0]  # fase no mapeada: no retroceder
            if frac < _last_frac[0]:
                frac = _last_frac[0]
            _last_frac[0] = frac
            data.update({
                "estado": "running",
                "mensaje": data.get("message") or "Procesando FaceSync...",
                "frac": frac,
            })
            emit_progress(req_id, data)

        result = motor.run_reference_face_matching(
            table_path=excel,
            name_column=col_nombre,
            reference_column=col_ref,
            source_folder=sources,
            destination_folder=destino,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

        if result.get("canceled") or _job_cancelled(req_id):
            emit_result(req_id, {
                "estado": "cancelado",
                "exito": False,
                "mensaje": result.get("message") or "Cancelado por el usuario.",
                "reporte": result.get("report_path", ""),
            })
            return
        if not result.get("success"):
            emit_error(req_id, result.get("error") or result.get("message") or "Falló la clasificación facial.")
            return

        diagnostico = result.get("diagnostico") or {}
        entregadas = result.get("archivos_entregados_totales", result.get("total_fotos_copiadas", 0))
        analizadas = result.get("total_fotos_analizadas", 0)
        # Historial acumulado: recuerda este destino para que la sección
        # Reportes muestre TODAS las clasificaciones, no solo la última.
        try:
            from facesyncApp.ui import report_data as rd
            rd.append_classify_dest(_email(args), destino)
        except Exception:
            pass
        emit_result(req_id, {
            "estado": "ok",
            "exito": True,
            "destino": destino,
            "mensaje": f"Clasificación completada: {entregadas} archivo(s) entregado(s) de {analizadas} analizado(s).",
            "total_fotos_analizadas": analizadas,
            "total_fotos_copiadas": result.get("total_fotos_copiadas", 0),
            "archivos_entregados_totales": entregadas,
            "referencias_encontradas": result.get("referencias_encontradas", 0),
            "referencias_ambiguas": len(result.get("referencias_ambiguas") or []),
            "fotos_ignoradas_no_asignadas": len(result.get("fotos_ignoradas_no_asignadas") or []),
            "diagnostico": diagnostico,
            "metadata": result.get("metadata") or {},
            "reporte": result.get("report_path", ""),
            "report_files": result.get("report_files") or {},
        })
    except Exception as e:
        traceback.print_exc()
        emit_error(req_id, f"{type(e).__name__}: {e}")
    finally:
        _job_done(req_id)


def cmd_cancel(req_id, args):
    """Cancela un trabajo en curso por su id. args: {"target_id": str}"""
    target = args.get("target_id")
    ok = _job_cancel(target) if target else False
    emit_result(req_id, {"cancelled": ok, "target_id": target})


# ============================================================================
# Estado de workspace (lo fija la UI al cargar/añadir carpetas raíz)
# ============================================================================
_WS = {"roots": [], "email": None}


def _email(args):
    value = args.get("email") or _WS.get("email") or ""
    return safe_account_id(value) if value else ""


def _path_policy(roots=None):
    return WorkspacePathPolicy(roots if roots is not None else _WS.get("roots") or [])


def _workspace_path(value, *, must_exist=None, allow_root=True):
    return str(_path_policy().resolve(value, must_exist=must_exist, allow_root=allow_root))


def _ws_config_path(email):
    """config.json del usuario en app_data (mismo que lee report_data.workspace_roots)."""
    from facesyncApp.ui import report_data as rd
    account = safe_account_id(email) if email else "default"
    return os.path.join(rd._app_data_root(), "context", "usuarios", account, "config.json")


def _is_internal_dir(path):
    """True si la ruta cae dentro de directorios PROPIOS de la app: los datos
    (%LOCALAPPDATA%/FaceSync) o la instalación/engine (que contiene _internal).
    Esas carpetas NUNCA deben aparecer como raíz del workspace."""
    try:
        p = os.path.abspath(str(path)).replace("\\", "/").lower().rstrip("/")
    except Exception:
        return False
    bases = []
    try:
        from core.app_paths import default_app_data_root
        bases.append(str(default_app_data_root()))
    except Exception:
        pass
    # ENGINE_DIR (frozen = <install>/resources/engine/_internal) y sus ancestros
    # hasta la raíz de instalación.
    d = ENGINE_DIR
    for _ in range(4):
        bases.append(d)
        parent = os.path.dirname(d)
        if not parent or parent == d:
            break
        d = parent
    for base in bases:
        try:
            b = os.path.abspath(base).replace("\\", "/").lower().rstrip("/")
        except Exception:
            continue
        if b and (p == b or p.startswith(b + "/")):
            return True
    return False


def _clean_roots(roots):
    """Roots válidos: existen y NO son directorios internos de la app."""
    out = []
    for r in roots or []:
        if r and os.path.isdir(r) and not _is_internal_dir(r) and r not in out:
            out.append(r)
    return out


def _ws_save_roots(email, roots):
    """Persiste folder_roots para que la sesión sobreviva reinicios (y reportes
    encuentren los reportes del workspace)."""
    try:
        path = _ws_config_path(email)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        data["folder_roots"] = list(roots)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"ws_save_roots FALLO: {e}")


def cmd_set_workspace(req_id, args):
    roots = _clean_roots(args.get("roots") or [])
    roots = [str(p) for p in _path_policy(roots).roots]
    _WS["roots"] = roots
    if args.get("email"):
        _WS["email"] = safe_account_id(args["email"])
    _ws_save_roots(_WS["email"], roots)
    emit_result(req_id, {"roots": roots, "email": _WS["email"]})


def cmd_ws_load(req_id, args):
    """Restaura la sesión del usuario (folder_roots persistidos)."""
    email = _email(args)
    roots = []
    try:
        path = _ws_config_path(email)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                roots = (json.load(f) or {}).get("folder_roots") or []
        roots = _clean_roots(roots)  # descarta dirs internos de la app (p.ej. _internal)
    except Exception as e:
        log(f"ws_load FALLO: {e}")
    _WS["roots"] = roots
    _WS["email"] = email
    emit_result(req_id, {"roots": roots, "email": email})


# ============================================================================
# Explorador de archivos (directo con os, igual que el dashboard original)
# ============================================================================
def cmd_fs_list_dir(req_id, args):
    try:
        path = _workspace_path(args.get("path"), must_exist=True)
    except (OSError, ValueError) as e:
        emit_error(req_id, str(e))
        return
    if not (path and os.path.isdir(path)):
        emit_error(req_id, f"no es carpeta: {path}")
        return
    try:
        from core.app_paths import filter_internal_names
    except Exception:
        def filter_internal_names(x):
            return x
    dirs, files = [], []
    with os.scandir(path) as it:
        for e in it:
            try:
                if e.is_dir(follow_symlinks=False):
                    dirs.append(e.name)
                elif e.is_file(follow_symlinks=False):
                    files.append(e.name)
            except OSError:
                pass
    dirs = sorted(filter_internal_names(dirs), key=str.casefold)
    files = sorted(files, key=str.casefold)
    emit_result(req_id, {"path": path, "dirs": dirs, "files": files})


def cmd_fs_new_folder(req_id, args):
    try:
        parent = _workspace_path(args.get("parent"), must_exist=True)
        name = safe_component(args.get("name"))
    except (OSError, ValueError) as e:
        emit_error(req_id, str(e))
        return
    if not (parent and os.path.isdir(parent)):
        emit_error(req_id, "parent inválido")
        return
    try:
        ruta = os.path.join(parent, name)
        _workspace_path(ruta)
        os.makedirs(ruta, exist_ok=True)
        emit_result(req_id, {"created": ruta.replace("\\", "/")})
    except Exception as e:
        emit_error(req_id, str(e))


def cmd_fs_rename(req_id, args):
    try:
        path = _workspace_path(args.get("path"), must_exist=True, allow_root=False)
        new_name = safe_component(args.get("new_name"))
    except (OSError, ValueError) as e:
        emit_error(req_id, str(e))
        return
    if not (path and os.path.exists(path) and new_name):
        emit_error(req_id, "args inválidos")
        return
    try:
        dest = os.path.join(os.path.dirname(path), new_name)
        _workspace_path(dest)
        os.rename(path, dest)
        emit_result(req_id, {"renamed": dest.replace("\\", "/")})
    except Exception as e:
        emit_error(req_id, str(e))


def cmd_fs_delete(req_id, args):
    try:
        path = _workspace_path(args.get("path"), must_exist=True, allow_root=False)
    except (OSError, ValueError) as e:
        emit_error(req_id, str(e))
        return
    if not (path and os.path.exists(path)):
        emit_error(req_id, "no existe")
        return
    try:
        from core.safe_delete import send_to_recycle_bin
        send_to_recycle_bin(path)
        emit_result(req_id, {"deleted": path.replace("\\", "/")})
    except Exception as e:
        emit_error(req_id, str(e))


def cmd_scan_assets(req_id, args):
    """Escanea las raíces (+1 nivel) buscando Excel/CSV y listando carpetas.
    Alimenta los dropdowns de los modales Crear carpetas / Clasificar."""
    requested = args.get("roots") or _WS["roots"]
    roots = []
    for raw in requested:
        try:
            resolved = _workspace_path(raw, must_exist=True)
            if os.path.isdir(resolved) and resolved not in roots:
                roots.append(resolved)
        except (OSError, ValueError):
            continue
    EXT = (".xlsx", ".xls", ".csv")
    excels, folders, sf, sd = [], [], set(), set()
    for root in roots:
        rp = root.replace("\\", "/")
        if rp not in sd:
            sd.add(rp); folders.append(rp)
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        subs = []
        for e in entries:
            try:
                if e.is_file(follow_symlinks=False) and e.name.lower().endswith(EXT):
                    p = e.path.replace("\\", "/")
                    if p not in sf:
                        sf.add(p); excels.append(p)
                elif e.is_dir(follow_symlinks=False):
                    subs.append(e.path)
            except OSError:
                continue
        for s in subs[:120]:
            dp = s.replace("\\", "/")
            if dp not in sd:
                sd.add(dp); folders.append(dp)
            try:
                with os.scandir(s) as it2:
                    for f in it2:
                        if f.is_file(follow_symlinks=False) and f.name.lower().endswith(EXT):
                            p = f.path.replace("\\", "/")
                            if p not in sf:
                                sf.add(p); excels.append(p)
            except OSError:
                continue
    excels.sort(key=lambda p: os.path.basename(p).lower())
    emit_result(req_id, {"excels": excels, "folders": folders})


def cmd_workspace_folders(req_id, args):
    """Lista carpetas de cualquier profundidad para elegir un destino."""
    requested = args.get("roots") or _WS["roots"]
    roots = []
    for raw in requested:
        try:
            resolved = _workspace_path(raw, must_exist=True)
            if os.path.isdir(resolved) and resolved not in roots:
                roots.append(resolved)
        except (OSError, ValueError):
            continue

    try:
        from core.app_paths import filter_internal_names
    except Exception:
        def filter_internal_names(names):
            return names

    folders, seen = [], set()
    limit = 10000
    truncated = False
    for root in roots:
        for current, dirs, _ in os.walk(root, topdown=True, followlinks=False):
            dirs[:] = sorted(
                [
                    name for name in filter_internal_names(dirs)
                    if not os.path.islink(os.path.join(current, name))
                ],
                key=str.casefold,
            )
            normalized = current.replace("\\", "/")
            if normalized not in seen:
                seen.add(normalized)
                folders.append(normalized)
            if len(folders) >= limit:
                truncated = True
                break
        if truncated:
            break

    emit_result(req_id, {"folders": folders, "truncated": truncated})


def cmd_dirs_for_paths(req_id, args):
    """Para drag&drop: por cada ruta soltada devuelve su carpeta (la misma si es
    dir, o el padre si es archivo). Solo dirs existentes, deduplicado."""
    out = []
    for p in (args.get("paths") or []):
        try:
            d = p if os.path.isdir(p) else os.path.dirname(p)
            d = d.replace("\\", "/")
            if d and os.path.isdir(d) and d not in out:
                out.append(d)
        except Exception:
            pass
    emit_result(req_id, {"dirs": out})


def cmd_open_path(req_id, args):
    """Abre un archivo/carpeta con la app por defecto del SO (Ver reporte, etc.)."""
    try:
        path = _workspace_path(args.get("path"), must_exist=True)
    except (OSError, ValueError) as e:
        emit_error(req_id, str(e))
        return
    if not (path and os.path.exists(path)):
        emit_error(req_id, f"no existe: {path}")
        return
    try:
        os.startfile(path)  # noqa: Windows
        emit_result(req_id, {"opened": path})
    except Exception as e:
        emit_error(req_id, str(e))


def cmd_file_copy(req_id, args):
    """Copia un archivo a dest (Descargar reporte: guardar copia donde elija)."""
    try:
        src = _workspace_path(args.get("src"), must_exist=True)
    except (OSError, ValueError) as e:
        emit_error(req_id, str(e))
        return
    dest = args.get("dest")
    if not (src and dest and os.path.isfile(src)):
        emit_error(req_id, "args inválidos (src/dest)")
        return
    try:
        import shutil
        shutil.copy2(src, dest)
        emit_result(req_id, {"copied": dest})
    except Exception as e:
        emit_error(req_id, str(e))


def cmd_fs_copy_files(req_id, args):
    """Copia archivos a target_dir (Tauri elige los archivos; el bridge copia)."""
    try:
        target = _workspace_path(args.get("target_dir"), must_exist=True)
    except (OSError, ValueError) as e:
        emit_error(req_id, str(e))
        return
    files = args.get("files") or []
    if not (target and os.path.isdir(target)):
        emit_error(req_id, "target inválido")
        return
    import shutil
    copied = []
    for f in files:
        try:
            if os.path.isfile(f):
                dest = os.path.join(target, os.path.basename(f))
                if os.path.abspath(f) == os.path.abspath(dest) or os.path.exists(dest):
                    continue
                shutil.copy2(f, dest)
                copied.append(dest.replace("\\", "/"))
        except Exception as e:
            log(f"fs_copy_files omitio '{f}': {e}")
    emit_result(req_id, {"copied": copied})


# ============================================================================
# Excel + creación de carpetas
# ============================================================================
def cmd_read_excel(req_id, args):
    """Lee Excel/CSV de referencia: columnas + filas + preview (para 'Leer Excel')."""
    try:
        path = _workspace_path(args.get("path"), must_exist=True)
    except (OSError, ValueError) as e:
        emit_error(req_id, str(e))
        return
    if not (path and os.path.isfile(path)):
        emit_error(req_id, f"excel inválido: {path}")
        return
    try:
        import pandas as pd
        ext = os.path.splitext(path)[1].lower()
        df = pd.read_csv(path) if ext == ".csv" else pd.read_excel(path)
        emit_result(req_id, {
            "columns": [str(c) for c in df.columns],
            "rows": int(len(df)),
            "preview": df.head(50).fillna("").astype(str).to_dict(orient="records"),
        })
    except Exception as e:
        emit_error(req_id, str(e))


def cmd_excel_template_summary(req_id, args):
    """Resume la plantilla creada por la acción rápida, sin ejecutar FaceSync."""
    try:
        path = _workspace_path(args.get("path"), must_exist=True)
    except (OSError, ValueError) as e:
        emit_error(req_id, str(e))
        return
    if not (path and os.path.isfile(path) and path.lower().endswith(".xlsx")):
        emit_error(req_id, f"excel inválido: {path}")
        return

    try:
        import unicodedata
        from collections import Counter
        import pandas as pd

        df = pd.read_excel(path, dtype=str, keep_default_na=False)
        columns = [str(column).strip() for column in df.columns]

        def header_key(value):
            normalized = unicodedata.normalize("NFKD", str(value))
            return " ".join(
                "".join(char for char in normalized if not unicodedata.combining(char))
                .casefold()
                .split()
            )

        by_key = {header_key(column): column for column in columns}
        name_column = by_key.get("nombre del alumno")
        code_column = by_key.get("codigo de foto")
        missing_columns = []
        if not name_column:
            missing_columns.append("Nombre del alumno")
        if not code_column:
            missing_columns.append("Código de foto")

        fallback_name = name_column or (columns[0] if columns else None)
        fallback_code = code_column or (columns[1] if len(columns) > 1 else None)
        records = []
        for _, row in df.iterrows():
            name = str(row.get(fallback_name, "")).strip() if fallback_name else ""
            code = str(row.get(fallback_code, "")).strip() if fallback_code else ""
            if name or code:
                records.append({"name": name, "code": code})

        names_count = sum(bool(record["name"]) for record in records)
        codes_count = sum(bool(record["code"]) for record in records)
        complete_count = sum(bool(record["name"] and record["code"]) for record in records)
        incomplete_count = len(records) - complete_count
        code_counts = Counter(record["code"] for record in records if record["code"])
        duplicates = [
            {"code": code, "count": count}
            for code, count in sorted(code_counts.items(), key=lambda item: item[0].casefold())
            if count > 1
        ]

        emit_result(req_id, {
            "path": path.replace("\\", "/"),
            "filename": os.path.basename(path),
            "columns": columns,
            "rows": len(records),
            "names_count": names_count,
            "codes_count": codes_count,
            "complete_count": complete_count,
            "incomplete_count": incomplete_count,
            "duplicate_codes": duplicates,
            "missing_columns": missing_columns,
            "template_valid": not missing_columns,
            "ready": bool(records) and not missing_columns and incomplete_count == 0 and not duplicates,
            "preview": records[:100],
            "preview_truncated": len(records) > 100,
            "modified_ms": int(os.path.getmtime(path) * 1000),
        })
    except Exception as e:
        emit_error(req_id, str(e))


def _folder_names_from_column(path, column):
    """Una carpeta por registro; nombres repetidos numerados (igual que el backend)."""
    import pandas as pd
    ext = os.path.splitext(path)[1].lower()
    df = pd.read_csv(path) if ext == ".csv" else pd.read_excel(path)
    if column not in df.columns:
        return []
    seen, out = {}, []
    for v in df[column].tolist():
        name = str(v).strip()
        if not name or name.lower() == "nan":
            continue
        name = "".join(c for c in name if c not in '<>:"/\\|?*').strip()
        if not name:
            continue
        if name in seen:
            seen[name] += 1
            out.append(f"{name} ({seen[name]})")
        else:
            seen[name] = 1
            out.append(name)
    return out


def cmd_folders_preview(req_id, args):
    try:
        path = _workspace_path(args.get("path"), must_exist=True)
    except (OSError, ValueError) as e:
        emit_error(req_id, str(e))
        return
    column = args.get("column")
    if not (path and os.path.isfile(path) and column):
        emit_error(req_id, "args inválidos (path/column)")
        return
    try:
        names = _folder_names_from_column(path, column)
        emit_result(req_id, {"count": len(names), "names": names[:1000]})
    except Exception as e:
        emit_error(req_id, str(e))


def cmd_folders_create(req_id, args):
    try:
        destino = _workspace_path(args.get("destino"))
    except (OSError, ValueError) as e:
        emit_error(req_id, str(e))
        return
    names = args.get("names")
    path, column = args.get("path"), args.get("column")
    if not destino:
        emit_error(req_id, "destino requerido")
        return
    try:
        if not names and path and column:
            names = _folder_names_from_column(path, column)
        names = [safe_component(n) for n in (names or [])]
        os.makedirs(destino, exist_ok=True)
        created = 0
        for n in names:
            try:
                os.makedirs(os.path.join(destino, n), exist_ok=True)
                created += 1
            except Exception:
                pass
        emit_result(req_id, {"created": created, "total": len(names), "destino": destino})
    except Exception as e:
        emit_error(req_id, str(e))


# ============================================================================
# Reportes / Exportaciones / Almacenamiento (report_data, SOLO LECTURA)
# ============================================================================
def cmd_reports_list(req_id, args):
    try:
        from facesyncApp.ui import report_data as rd
        em = _email(args)
        emit_result(req_id, {"reports": rd.list_reports(em),
                             "classified": rd.count_classified(em)})
    except Exception as e:
        emit_error(req_id, str(e))


def cmd_report_detail(req_id, args):
    try:
        from facesyncApp.ui import report_data as rd
        emit_result(req_id, rd.report_detail(_workspace_path(args.get("path"), must_exist=True)))
    except Exception as e:
        emit_error(req_id, str(e))


def cmd_exports_list(req_id, args):
    try:
        from facesyncApp.ui import report_data as rd
        emit_result(req_id, {"exports": rd.list_exports(_email(args))})
    except Exception as e:
        emit_error(req_id, str(e))


def cmd_storage_usage(req_id, args):
    try:
        from facesyncApp.ui import report_data as rd
        import shutil
        requested = args.get("roots") or rd.workspace_roots(_email(args)) or _WS["roots"]
        roots = []
        for raw in requested:
            try:
                root = _workspace_path(raw, must_exist=True)
                if os.path.isdir(root) and root not in roots:
                    roots.append(root)
            except (OSError, ValueError):
                continue
        total = 0
        for root in roots:
            for cur, _d, files in os.walk(root):
                for f in files:
                    try:
                        total += os.stat(os.path.join(cur, f)).st_size
                    except OSError:
                        pass
        disk = None
        if roots:
            try:
                du = shutil.disk_usage(roots[0])
                disk = {"total": du.total, "free": du.free}
            except OSError:
                pass
        emit_result(req_id, {"total_bytes": total, "disk": disk, "roots": list(roots)})
    except Exception as e:
        emit_error(req_id, str(e))


# ============================================================================
# Chat IA (asistente headless: local-first -> OpenAI -> Gemini)
# ============================================================================
_CHAT = {"accounts": {}}
_CHAT_LOCK = threading.Lock()
_CHAT_STATE_LOCK = threading.RLock()


def _chat_service(roots, account_id):
    account_id = safe_account_id(account_id) if account_id else ""
    if not account_id:
        raise ValueError("cuenta requerida para iniciar el chat")
    requested = roots or _WS["roots"]
    roots = []
    for raw in requested:
        try:
            root = _workspace_path(raw, must_exist=True)
            if os.path.isdir(root) and root not in roots:
                roots.append(root)
        except (OSError, ValueError):
            continue
    entry = _CHAT["accounts"].get(account_id)
    if entry is None or (roots and list(roots) != entry.get("roots")):
        if entry is not None:
            try:
                entry["svc"].close()
            except Exception:
                pass
        from chat_service import ChatService
        entry = {
            "svc": ChatService(roots=roots, account_id=account_id),
            "roots": list(roots or []),
        }
        _CHAT["accounts"][account_id] = entry
    return entry["svc"]


def cmd_chat_bootstrap(req_id, args):
    """Abre el hilo persistente de la cuenta y restaura su historial."""
    account_id = _email(args)
    if not account_id:
        emit_error(req_id, "email requerido")
        return
    try:
        with _CHAT_STATE_LOCK:
            svc = _chat_service(args.get("roots"), account_id)
        emit_result(req_id, {
            "account_id": account_id,
            "history": svc.get_history(),
            "workspace": svc.ruta_workspace or "",
        })
    except Exception as exc:
        emit_error(req_id, f"no se pudo restaurar el chat: {type(exc).__name__}: {exc}")


def cmd_chat_new(req_id, args):
    account_id = _email(args)
    if not account_id:
        emit_error(req_id, "email requerido")
        return
    try:
        with _CHAT_STATE_LOCK:
            svc = _chat_service(args.get("roots"), account_id)
        emit_result(req_id, {"history": svc.start_new_conversation()})
    except Exception as exc:
        emit_error(req_id, f"no se pudo crear la conversacion: {type(exc).__name__}: {exc}")


def cmd_chat_logout(req_id, args):
    """Descarta exclusivamente la RAM del chat de la cuenta indicada."""
    account_id = _email(args)
    with _CHAT_STATE_LOCK:
        entry = _CHAT["accounts"].pop(account_id, None) if account_id else None
    if entry:
        try:
            if _CHAT_LOCK.locked():
                entry["svc"].request_cancel()
            else:
                entry["svc"].close()
        except Exception:
            pass
    emit_result(req_id, {"closed": bool(entry), "account_id": account_id})


def cmd_chat_send(req_id, args):
    """Mensaje de chat. Stream: cada mensaje (Sistema/Asistente) va como
    progress {kind:'msg',role,text}; el progreso del motor (si se clasifica
    desde el chat) como {kind:'motor',data}. El result final marca fin de turno."""
    text = args.get("text")
    if not text:
        emit_error(req_id, "text requerido")
        return
    if not _CHAT_LOCK.acquire(blocking=False):
        emit_error(req_id, "el asistente ya esta procesando otra solicitud")
        return
    try:
        account_id = _email(args)
        if not account_id:
            raise ValueError("email requerido")
        with _CHAT_STATE_LOCK:
            svc = _chat_service(args.get("roots"), account_id)
    except Exception as e:
        traceback.print_exc()
        emit_error(req_id, f"no se pudo iniciar el chat: {type(e).__name__}: {e}")
        _CHAT_LOCK.release()
        return
    svc.emit = lambda role, t: emit_progress(req_id, {"kind": "msg", "role": role, "text": t})
    svc.on_progress = lambda data: emit_progress(req_id, {"kind": "motor", "data": data})
    try:
        svc.send(text)
        emit_result(req_id, {"done": True})
    except Exception as e:
        traceback.print_exc()
        emit_error(req_id, f"{type(e).__name__}: {e}")
    finally:
        _CHAT_LOCK.release()


def cmd_chat_cancel(req_id, args):
    account_id = _email(args)
    with _CHAT_STATE_LOCK:
        entry = _CHAT["accounts"].get(account_id) if account_id else None
    if entry:
        entry["svc"].request_cancel()
    emit_result(req_id, {"cancelled": bool(entry), "account_id": account_id})


# ============================================================================
# Exportar a Google Drive (subida paralela, drive_service)
# ============================================================================
def cmd_drive_export_start(req_id, args):
    carpeta = args.get("carpeta")
    em = _email(args)
    if not (carpeta and os.path.isdir(carpeta)):
        emit_error(req_id, f"carpeta inválida: {carpeta}")
        return
    from oauth_service import token_path_for_account
    token_path = token_path_for_account(em)
    if not os.path.isfile(token_path):
        emit_error(req_id, f"sin credenciales de Drive para '{em}'. Inicia sesión primero.")
        return
    cancel_event = _job_new(req_id)  # job cancelable (botón Cancelar de la UI)
    emit_progress(req_id, {"estado": "running", "mensaje": "Escaneando archivos…"})
    try:
        from drive_service import upload_folder
        summary = upload_folder(
            token_path, carpeta,
            on_progress=lambda d: emit_progress(req_id, {"estado": "running", **d}),
            cancel_check=lambda: cancel_event.is_set() or _job_cancelled(req_id))
        if not summary.get("canceled"):
            try:
                from facesyncApp.ui import report_data as rd
                rd.append_export(em, {
                    "nombre": summary["drive_folder"], "tipo": "Drive",
                    "estado": "Completado" if summary["ok"] else "Parcial",
                    "origen": carpeta, "subidos": summary["subidos"], "total": summary["total"],
                    "drive_folder_id": summary.get("drive_folder_id"),
                })
            except Exception:
                pass
        emit_result(req_id, summary)
    except Exception as e:
        traceback.print_exc()
        emit_error(req_id, f"{type(e).__name__}: {e}")
    finally:
        _job_done(req_id)


# ============================================================================
# Login Google OAuth (oauth_service)
# ============================================================================
def cmd_list_accounts(req_id, args):
    try:
        from oauth_service import list_accounts
        emit_result(req_id, {"accounts": list_accounts()})
    except Exception as e:
        emit_error(req_id, str(e))


def cmd_oauth_login(req_id, args):
    """Abre el navegador para autorizar; BLOQUEA hasta que el usuario concede."""
    try:
        from oauth_service import login
        emit_progress(req_id, {"estado": "browser", "mensaje": "Abre tu navegador y autoriza el acceso…"})
        acc = login()
        _WS["email"] = acc.get("email_safe") or _WS.get("email")
        emit_result(req_id, acc)
    except Exception as e:
        traceback.print_exc()
        emit_error(req_id, str(e))


def cmd_oauth_saved(req_id, args):
    try:
        from oauth_service import login_saved
        acc = login_saved(args.get("email"))
        _WS["email"] = acc.get("email_safe") or _WS.get("email")
        emit_result(req_id, acc)
    except Exception as e:
        emit_error(req_id, str(e))


def cmd_delete_account(req_id, args):
    try:
        from oauth_service import delete_account
        emit_result(req_id, delete_account(args.get("email")))
    except Exception as e:
        emit_error(req_id, str(e))


# RAW soportados via rawpy (extrae el JPEG embebido, rapido).
_RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".rw2", ".orf", ".srw"}


def cmd_read_thumb(req_id, args):
    """Miniatura/preview rapida de una imagen para la UI. JPG/PNG/etc. se reducen;
    CR2/RAW extraen el JPEG embebido (sin demosaicar el RAW). Aditivo: NO toca el
    motor ni los comandos existentes. args: {path, size?}."""
    try:
        path = _workspace_path(args.get("path"), must_exist=True, allow_root=False)
    except (OSError, ValueError) as e:
        emit_error(req_id, f"ruta fuera del workspace: {e}")
        return
    try:
        size = max(32, min(2400, int(args.get("size") or 256)))
    except (TypeError, ValueError):
        size = 256
    try:
        import io
        import base64
        from PIL import Image, ImageOps

        ext = os.path.splitext(path)[1].lower()
        if ext in _RAW_EXTS:
            import rawpy

            with rawpy.imread(path) as raw:
                thumb = None
                try:
                    thumb = raw.extract_thumb()
                except Exception:
                    thumb = None
                if thumb is not None and thumb.format == rawpy.ThumbFormat.JPEG:
                    im = Image.open(io.BytesIO(thumb.data))
                elif thumb is not None:
                    im = Image.fromarray(thumb.data)
                else:
                    im = Image.fromarray(raw.postprocess(half_size=True))
        else:
            im = Image.open(path)

        # Aplica la orientación EXIF: el JPEG embebido del CR2 (y los JPG
        # verticales) traen su orientación; sin esto los verticales salen
        # rotados 90 grados. Igual que hace el motor original (exif_transpose).
        im = ImageOps.exif_transpose(im) or im
        im = im.convert("RGB")
        im.thumbnail((size, size))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        emit_result(req_id, {"data": base64.b64encode(buf.getvalue()).decode("ascii"), "mime": "jpeg"})
    except Exception as e:
        emit_error(req_id, f"{type(e).__name__}: {e}")


# --- (todo el contrato del CHECKLIST queda cableado) ---
def _not_implemented(req_id, args):
    emit_error(req_id, "not_implemented")


# Mapa de comandos. Los implementados ya corren; los stub devuelven not_implemented
# pero dejan el contrato visible (se cablean en fases siguientes con su API real).
HANDLERS = {
    "ping": cmd_ping,
    "gpu_info": cmd_gpu_info,
    "diag_represent": cmd_diag_represent,
    "diag_cr2_ab": cmd_diag_cr2_ab,
    "diag_raw_ab": cmd_diag_cr2_ab,
    "diag_cr3_measurements": cmd_diag_cr3_measurements,
    "classify_start": cmd_classify_start,
    "cancel": cmd_cancel,
    # workspace + explorador
    "set_workspace": cmd_set_workspace,
    "ws_load": cmd_ws_load,
    "fs_list_dir": cmd_fs_list_dir,
    "fs_new_folder": cmd_fs_new_folder,
    "fs_rename": cmd_fs_rename,
    "fs_delete": cmd_fs_delete,
    "fs_copy_files": cmd_fs_copy_files,
    "open_path": cmd_open_path,
    "read_thumb": cmd_read_thumb,
    "file_copy": cmd_file_copy,
    "dirs_for_paths": cmd_dirs_for_paths,
    "scan_assets": cmd_scan_assets,
    "workspace_folders": cmd_workspace_folders,
    # excel + carpetas
    "read_excel": cmd_read_excel,
    "excel_template_summary": cmd_excel_template_summary,
    "folders_preview": cmd_folders_preview,
    "folders_create": cmd_folders_create,
    # reportes / exportaciones / almacenamiento
    "reports_list": cmd_reports_list,
    "report_detail": cmd_report_detail,
    "exports_list": cmd_exports_list,
    "storage_usage": cmd_storage_usage,
    # chat IA
    "chat_bootstrap": cmd_chat_bootstrap,
    "chat_new": cmd_chat_new,
    "chat_logout": cmd_chat_logout,
    "chat_send": cmd_chat_send,
    "chat_cancel": cmd_chat_cancel,
    # exportar a Drive
    "drive_export_start": cmd_drive_export_start,
    # login Google OAuth
    "list_accounts": cmd_list_accounts,
    "oauth_login": cmd_oauth_login,
    "oauth_saved": cmd_oauth_saved,
    "delete_account": cmd_delete_account,
}


def _warm(mods):
    import time as _t
    for m in mods:
        t0 = _t.time()
        try:
            __import__(m)
            log(f"warm {m} {(_t.time()-t0):.1f}s")
        except Exception as e:
            log(f"warm {m} FALLO: {type(e).__name__}: {e}")


def _warm_light():
    """Stack LIGERO + dependencias de handlers, en MAIN. Rápido (~1-2s). Tras
    esto la UI ya puede login/explorar/miniaturas SIN esperar TensorFlow.

    Loader-lock: todos los C-extensions que puedan tocar los handlers ligeros
    (numpy/cv2/PIL/rawpy/onnxruntime…) se cargan aquí en MAIN, así ningún worker
    dispara un LoadLibrary mientras MAIN calienta el stack pesado después.
    """
    _warm(["numpy", "onnxruntime", "cv2", "pandas", "PIL", "PIL.Image", "rawpy"])
    _warm(["ctypes", "core.app_paths", "core.security",
           "tools.file_tools", "tools.document_tools",
           "facesyncApp.ui.report_data",
           "google.genai", "chat_service", "drive_service", "oauth_service"])


def _warm_heavy():
    """Stack PESADO (TensorFlow/tf_keras/DeepFace/RetinaFace + motor) en MAIN,
    DESPUÉS de emitir 'ready'. ~6s. El hilo lector solo está en un syscall
    (os.read) mientras tanto -> no hay LoadLibrary en un hilo secundario -> sin
    deadlock. Clasificar espera a _HEAVY_READY (ver cmd_classify_start).
    """
    # OJO: "deepface" solo carga un __init__ casi vacío; la importación REAL que
    # usa clasificar es deepface.DeepFace (y arrastra todos sus módulos). Se
    # calienta explícita para que cualquier módulo faltante en el paquete
    # reviente AQUÍ (y quede en sidecar.log), no a mitad de una clasificación.
    _warm(["tensorflow", "tf_keras", "deepface", "deepface.DeepFace",
           "retinaface", "retinaface.RetinaFace",
           "facesyncApp.motor_ia_v3", "facesyncApp.motor_ia_v2", "facesyncApp.motor_ia"])
    with _PARK_LOCK:
        _HEAVY_READY.set()
        parked, _PARKED[:] = list(_PARKED), []
    for req in parked:
        log(f"despachando clasificacion estacionada id={req.get('id')}")
        dispatch(req)


def dispatch(req):
    req_id = req.get("id", "?")
    cmd = req.get("cmd")
    args = req.get("args") or {}
    handler = HANDLERS.get(cmd)
    if handler is None:
        emit_error(req_id, f"comando desconocido: {cmd}")
        return
    # Clasificar requiere el stack pesado (TF/DeepFace). Si aún calienta, se
    # ESTACIONA y se despacha al terminar el warm (ver _warm_heavy). El lock
    # hace atómico el check+append frente al set+drain del warm.
    if handler is cmd_classify_start:
        with _PARK_LOCK:
            if not _HEAVY_READY.is_set():
                _PARKED.append(req)
                emit_progress(req_id, {"estado": "running", "stage": "started",
                                       "frac": 0.01, "mensaje": "Preparando el motor…"})
                return
    # Los comandos largos usan un pool acotado para evitar crear hilos sin
    # limite. Cancelar se atiende en el lector para que nunca quede en cola.
    if handler in {cmd_cancel, cmd_chat_cancel, cmd_chat_logout}:
        _safe_run(handler, req_id, args)
    elif not _WORKER_SLOTS.acquire(blocking=False):
        emit_error(req_id, "el motor esta ocupado; intenta de nuevo en unos segundos")
    else:
        threading.Thread(
            target=_bounded_run,
            args=(handler, req_id, args),
            daemon=True,
            name=f"facesync-{cmd}",
        ).start()


def _bounded_run(handler, req_id, args):
    try:
        _safe_run(handler, req_id, args)
    finally:
        _WORKER_SLOTS.release()


def _safe_run(handler, req_id, args):
    try:
        handler(req_id, args)
    except Exception as e:
        traceback.print_exc()
        try:
            emit_error(req_id, f"{type(e).__name__}: {e}")
        except Exception:
            pass


def _read_loop():
    """Lee stdin (JSON-lines) y despacha. Corre en un hilo secundario para que
    MAIN pueda calentar el stack pesado en paralelo sin bloquear la UI.

    os.read(0) en vez de sys.stdin: en Windows el wrapper de archivo no entrega
    líneas hasta llenar buffer/EOF y retiene el GIL; os.read lo libera y entrega
    los bytes apenas llegan. Partimos en líneas a mano.
    """
    buf = b""
    while True:
        try:
            chunk = os.read(0, 65536)
        except Exception:
            break
        if not chunk:  # EOF
            break
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            raw = raw.strip()
            if not raw:
                continue
            try:
                req = json.loads(raw.decode("utf-8"))
            except Exception as e:
                log(f"JSON inválido: {e} | {raw[:120]!r}")
                continue
            if req.get("cmd") == "shutdown":
                log("shutdown solicitado")
                return
            dispatch(req)


def main():
    log(f"sidecar arrancando. engine={ENGINE_DIR} python={sys.version.split()[0]}")
    _emit({"type": "starting", "engine": ENGINE_DIR})
    modo = os.environ.get("FACESYNC_WARM", "full").strip().lower()

    # TODO el warm ocurre en MAIN, ANTES de leer stdin. NO mover: un hilo
    # bloqueado leyendo stdin mientras MAIN importa TensorFlow deadlockea la
    # carga de sus DLLs en Windows (reproducido: el import quedaba congelado
    # hasta el EOF del pipe). Es la arquitectura original probada; el costo es
    # que "ready" tarda el warm completo (~10-20s la primera vez).
    _warm_light()
    if modo == "light":
        _HEAVY_READY.set()
    else:
        _warm_heavy()
        log("sidecar motor caliente")

    _emit({"type": "ready", "engine": ENGINE_DIR})
    log("sidecar listo")

    # Lectura de stdin en MAIN (hilo único, como el original).
    _read_loop()


if __name__ == "__main__":
    main()
