"""
motor_ia_fast.py  —  Despachador del motor de reconocimiento FACESYNC.

Reemplazo directo (drop-in) de facesyncApp.motor_ia.MotorFaceSync: misma clase
y mismo metodo iniciar_reconocimiento_en_hilo(...).

Elige el motor mas rapido disponible y SIEMPRE cae al anterior si algo falla:

    GPU (v3, ONNX/DirectML)  ->  CPU acelerado (v2)  ->  ORIGINAL (motor_ia)

Los tres dan los MISMOS resultados (v3 reutiliza el pre/post-proceso de DeepFace
y solo corre el forward en GPU; v2 es el mismo modelo cacheado). Si la laptop no
tiene GPU, usa v2. Si v2 fallara, usa el motor original probado.

Variable de entorno FACESYNC_MOTOR para forzar:
    auto (def) = GPU si hay, si no v2     |  gpu = forzar v3
    cpu / v2   = forzar v2                |  original = forzar el motor viejo
"""

import os
import tempfile
import threading
import traceback
import time
from datetime import datetime


def _log_resultado(texto):
    """Registra en %LOCALAPPDATA%\\FaceSync\\logs\\clasificacion.log qué motor se usó
    y cuánto tardó, para poder verificar que la GPU se activó."""
    try:
        from core.app_paths import ensure_app_data_root
        logdir = ensure_app_data_root() / "logs"
    except Exception:
        from pathlib import Path
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
        logdir = Path(base) / "FaceSync" / "logs"
    try:
        logdir.mkdir(parents=True, exist_ok=True)
        with open(logdir / "clasificacion.log", "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    except Exception:
        pass


def _run_v3(rcf, rx, cd, cn, cr):
    from facesyncApp.motor_ia_v3 import MotorFaceSyncV3
    MotorFaceSyncV3._ejecutar_reconocimiento(rcf, rx, cd, columna_nombre=cn, columna_referencia=cr)


def _run_v2(rcf, rx, cd, cn, cr):
    from facesyncApp.motor_ia_v2 import MotorFaceSyncV2
    MotorFaceSyncV2._ejecutar_reconocimiento(rcf, rx, cd, columna_nombre=cn, columna_referencia=cr)


def _run_original(rcf, rx, cd, cn, cr):
    from facesyncApp.motor_ia import MotorFaceSync as MotorOriginal
    MotorOriginal._ejecutar_reconocimiento(rcf, rx, cd, columna_nombre=cn, columna_referencia=cr)


def _cadena_motores():
    """Devuelve la lista ordenada de (nombre, funcion) a intentar segun FACESYNC_MOTOR."""
    modo = os.environ.get("FACESYNC_MOTOR", "auto").strip().lower()

    if modo == "original":
        return [("original", _run_original)]
    if modo in ("cpu", "v2"):
        return [("v2 (CPU acelerado)", _run_v2), ("original", _run_original)]
    if modo in ("gpu", "v3"):
        return [("v3 (GPU)", _run_v3), ("v2 (CPU acelerado)", _run_v2), ("original", _run_original)]

    # auto
    cadena = []
    try:
        from facesyncApp.motor_ia_v3 import gpu_disponible
        if gpu_disponible():
            cadena.append(("v3 (GPU)", _run_v3))
    except Exception:
        pass
    cadena.append(("v2 (CPU acelerado)", _run_v2))
    cadena.append(("original", _run_original))
    return cadena


class MotorFaceSync:
    @staticmethod
    def iniciar_reconocimiento_en_hilo(
        ruta_carpeta_fotos,
        ruta_excel,
        carpeta_destino,
        callback_resultado,
        columna_nombre="Nombre del Alumno",
        columna_referencia="Foto"
    ):
        def proceso():
            args = (ruta_carpeta_fotos, ruta_excel, carpeta_destino, columna_nombre, columna_referencia)
            cadena = _cadena_motores()
            ultimo_error = None

            for nombre, fn in cadena:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                try:
                    print(f"\n[FaceSync] Intentando motor: {nombre}")
                    t0 = time.time()
                    fn(*args)
                    mins = (time.time() - t0) / 60
                    _log_resultado(f"{ts} | OK | motor={nombre} | tiempo={mins:.1f} min | destino={carpeta_destino}")
                    if callback_resultado:
                        callback_resultado(
                            True,
                            f"✅ Clasificación facial completada con éxito.\n\n"
                            f"Motor usado: {nombre}\nTiempo: {mins:.1f} min"
                        )
                    return
                except Exception as e:
                    ultimo_error = e
                    _log_resultado(f"{ts} | FALLO | motor={nombre} | {e}")
                    print(f"[FaceSync] El motor '{nombre}' fallo, probando el siguiente...")
                    traceback.print_exc()

            if callback_resultado:
                callback_resultado(False, f"❌ Error en IA: {ultimo_error}")

        hilo = threading.Thread(target=proceso, daemon=True)
        hilo.start()
