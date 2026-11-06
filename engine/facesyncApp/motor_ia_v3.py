"""
motor_ia_v3.py  —  Motor FACESYNC con GPU (FASE 2), resultados IDENTICOS.

Idea: TensorFlow no usa GPU en Windows. Pero los modelos de DeepFace
(retinaface + ArcFace) se exportaron a ONNX y su *forward* coincide con el de
Keras (diferencia < 5e-6, verificado). onnxruntime + DirectML corre ese forward
en CUALQUIER GPU de Windows (NVIDIA/AMD/Intel) sin instalar CUDA.

Como mantiene resultados identicos:
  - Reutiliza TODO el pre/post-procesamiento de DeepFace (deteccion, anclas,
    NMS, alineacion, recorte, normalizacion). Lo UNICO que cambia es que el
    *forward* de las dos redes se ejecuta en GPU (ONNX) en vez de CPU (TF).
  - Inyecta detector/recognizer "falsos" en el cache de DeepFace que llaman a
    onnxruntime, y luego ejecuta el MISMO algoritmo del motor v2.
  - Las distancias se redondean a 6 decimales (como verify): la diferencia de
    punto flotante (<1e-5) es imperceptible -> misma clasificacion.

Seguridad: al terminar (o si algo falla) restaura el cache de DeepFace, de modo
que el fallback al motor original/v2 funcione intacto.
"""

import os

os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

import json
import importlib.util

import numpy as np

from facesyncApp import BASE_DIR

MODELOS_DIR = os.path.join(BASE_DIR, "models_onnx")
RETINA_ONNX = os.path.join(MODELOS_DIR, "retinaface.onnx")
ARC_ONNX = os.path.join(MODELOS_DIR, "arcface.onnx")
RETINA_META = os.path.join(MODELOS_DIR, "retinaface_meta.json")
ARC_META = os.path.join(MODELOS_DIR, "arcface_meta.json")

ONNX_AVAILABLE = importlib.util.find_spec("onnxruntime") is not None


def gpu_disponible():
    """True si se puede correr el motor GPU: onnxruntime + DirectML + modelos."""
    if not ONNX_AVAILABLE:
        return False
    for f in (RETINA_ONNX, ARC_ONNX, RETINA_META, ARC_META):
        if not os.path.exists(f):
            return False
    try:
        import onnxruntime as ort
        return "DmlExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


def _crear_sesion(ruta):
    import onnxruntime as ort
    so = ort.SessionOptions()
    # Explicitly keep ONNX Runtime's full graph optimizations enabled. This is
    # normally the default, but pinning it prevents packaging/config changes
    # from silently disabling safe operator fusion.
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # Requisitos de estabilidad del proveedor DirectML:
    so.enable_mem_pattern = False
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    provs = [p for p in ("DmlExecutionProvider", "CPUExecutionProvider")
             if p in ort.get_available_providers()]
    return ort.InferenceSession(ruta, sess_options=so, providers=provs)


class _Salida:
    """Envuelve un array para imitar la API .numpy() que espera el paquete retinaface."""
    __slots__ = ("_a",)

    def __init__(self, a):
        self._a = a

    def numpy(self):
        return self._a


class _RetinaOnnx:
    """Reemplaza el modelo Keras de retinaface: corre el forward en GPU (ONNX)
    y devuelve las 9 salidas en el ORDEN que espera el postproceso del paquete."""

    def __init__(self, sess, in_name, out_names, perm):
        self.sess = sess
        self.in_name = in_name
        self.out_names = out_names
        self.perm = perm

    def __call__(self, im_tensor):
        x = np.asarray(im_tensor, dtype=np.float32)
        raw = self.sess.run(self.out_names, {self.in_name: x})
        return [_Salida(raw[self.perm[i]]) for i in range(len(self.perm))]


class InstalledGpuBackend:
    """Handle idempotente para restaurar los modelos DeepFace originales."""

    def __init__(self, modeling, previous_detector, previous_recognizer,
                 retina_session, arc_session):
        self._modeling = modeling
        self._previous_detector = previous_detector
        self._previous_recognizer = previous_recognizer
        self._retina_session = retina_session
        self._arc_session = arc_session
        self.provider = retina_session.get_providers()[0]
        self.active = True

    def restore(self):
        if not self.active:
            return
        self._modeling.cached_models["face_detector"]["retinaface"] = self._previous_detector
        self._modeling.cached_models["facial_recognition"]["ArcFace"] = self._previous_recognizer
        self.active = False


def install_gpu_backend():
    """Instala ONNX/DirectML en el cache de DeepFace sin cambiar su API.

    Debe usarse con un solo consumidor de inferencia. DirectML no es estable
    cuando varios hilos ejecutan simultaneamente la misma sesion.
    """
    if not gpu_disponible():
        raise RuntimeError(
            "Motor GPU no disponible (falta onnxruntime/DirectML o los modelos ONNX)."
        )

    from deepface import DeepFace as _DeepFace  # noqa: F401
    from deepface.modules import modeling
    from deepface.models.face_detection.RetinaFace import RetinaFaceClient
    from deepface.models.FacialRecognition import FacialRecognition

    with open(RETINA_META, encoding="utf-8") as file:
        rmeta = json.load(file)
    with open(ARC_META, encoding="utf-8") as file:
        ameta = json.load(file)

    retina_sess = _crear_sesion(RETINA_ONNX)
    arc_sess = _crear_sesion(ARC_ONNX)
    arc_in = ameta["input"]
    wrapper = _RetinaOnnx(
        retina_sess, rmeta["input"], rmeta["outputs"], rmeta["perm"]
    )

    class _DetectorGPU(RetinaFaceClient):
        def __init__(self):
            self.model = wrapper

    class _RecognizerGPU(FacialRecognition):
        def __init__(self):
            self.model = None
            self.model_name = "ArcFace"
            self.input_shape = (112, 112)
            self.output_shape = 512

        def forward(self, img):
            array = np.asarray(img, dtype=np.float32)
            if array.ndim == 3:
                array = np.expand_dims(array, axis=0)
            embedding = arc_sess.run(None, {arc_in: array})[0]
            if embedding.shape[0] == 1:
                return embedding[0].tolist()
            return embedding.tolist()

    if getattr(modeling, "cached_models", None) is None:
        modeling.cached_models = {kind: {} for kind in modeling.AVAILABLE_MODELS.keys()}

    previous_detector = modeling.cached_models["face_detector"].get("retinaface")
    previous_recognizer = modeling.cached_models["facial_recognition"].get("ArcFace")
    modeling.cached_models["face_detector"]["retinaface"] = _DetectorGPU()
    modeling.cached_models["facial_recognition"]["ArcFace"] = _RecognizerGPU()
    return InstalledGpuBackend(
        modeling, previous_detector, previous_recognizer, retina_sess, arc_sess
    )


class MotorFaceSyncV3:

    @staticmethod
    def _ejecutar_reconocimiento(
        ruta_carpeta_fotos,
        ruta_excel,
        carpeta_destino,
        columna_nombre="Nombre del Alumno",
        columna_referencia="Foto"
    ):
        backend = install_gpu_backend()
        print("\n[FaceSync] Motor GPU (ONNX/DirectML) activo. Proveedor:", backend.provider)
        try:
            # Ejecuta EXACTAMENTE el mismo algoritmo del motor v2 (cache de huellas +
            # paralelo). Por la inyeccion, el forward corre en GPU.
            from facesyncApp.motor_ia_v2 import MotorFaceSyncV2
            MotorFaceSyncV2._ejecutar_reconocimiento(
                ruta_carpeta_fotos,
                ruta_excel,
                carpeta_destino,
                columna_nombre=columna_nombre,
                columna_referencia=columna_referencia
            )
        finally:
            backend.restore()
