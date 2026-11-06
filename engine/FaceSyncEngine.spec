from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


engine_dir = Path(SPECPATH)
# weights: pesos keras .h5 (ruta CPU, máquinas sin DirectML) -> se siembran en
# runtime (bridge._setup_deepface_home): NUNCA se descargan de internet.
# models_onnx: motor GPU/DirectML (velocidad de producción). AMBOS van en el
# paquete; para caber bajo el límite (~1.92GB) de NSIS se recorta equipaje
# muerto abajo (scipy/sklearn/keras3/ffmpeg/catálogos de Google sin uso).
datas = []
if (engine_dir / "weights").is_dir():
    datas.append((str(engine_dir / "weights"), "weights"))
if (engine_dir / "models_onnx").is_dir():
    datas.append((str(engine_dir / "models_onnx"), "models_onnx"))
# config/: opcional. Si el usuario deja client_secret.json y/o .env aquí antes de
# compilar, se bundlean y se siembran en el config privado (login + chat listos).
if (engine_dir / "config").is_dir():
    datas.append((str(engine_dir / "config"), "config"))
binaries = []
# VC++ runtime DLLs que Windows 11 trae pero Windows 10 NO (vcruntime140_threads,
# msvcp140_2, concrt140). Sin ellas, pywrap_tflite_common.dll no carga y
# `import tensorflow` truena con "DLL load failed" -> deepface no arranca. Se
# bundlean en la raíz del paquete para que el loader las encuentre en cualquier
# Windows. (Confirmado por análisis de dependencias del pyd de tflite.)
_vcredist = engine_dir / "vcredist"
if _vcredist.is_dir():
    # Se colocan en la raíz Y junto a las DLLs de TensorFlow que las cargan: el
    # DIRECTORIO PROPIO de una DLL siempre se busca primero al resolver sus
    # dependencias, sin importar cómo se lanzó el proceso -> a prueba de balas.
    _vc_targets = [".", "tensorflow", "tensorflow/python", "tensorflow/lite/python"]
    for _dll in _vcredist.glob("*.dll"):
        for _t in _vc_targets:
            binaries.append((str(_dll), _t))
hiddenimports = []

for package in (
    "deepface",
    "retinaface",
    "google.genai",
    "googleapiclient",
    "onnxruntime",
    "openpyxl",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# tf_keras COMPLETO: el KerasLazyLoader de TensorFlow (TF_USE_LEGACY_KERAS=1)
# importa `tf_keras.api._v2.keras` en runtime; ese subárbol no es alcanzable
# estáticamente y PyInstaller lo omitía -> el loader caía en silencio a Keras 3
# y TODAS las referencias fallaban con el error de KerasTensor (reproducido).
hiddenimports += collect_submodules("tf_keras")

# Peso muerto: el matcher semántico (sentence-transformers/torch) ya degrada con
# try/except y además usa local_files_only sin modelo bundleado -> NUNCA carga en
# el paquete. Excluirlo quita ~450MB y mantiene el instalador bajo el límite de
# NSIS (~2GB). La clasificación (DeepFace/tf-keras/onnx) NO usa torch.
# NO excluir "sympy": la cadena de import de deepface.DeepFace lo requiere
# (ModuleNotFoundError: No module named 'sympy' al clasificar si falta).
# Recortes verificados para que quepan los models_onnx bajo el límite de NSIS:
# - scipy/sklearn: NADIE los importa (ni código propio, ni deepface, ni
#   retinaface; solo imports opcionales de keras/tf) -> ~83MB.
# - keras (3): jamás se usa en runtime; TF_USE_LEGACY_KERAS=1 enruta tf.keras a
#   tf_keras (bundleado completo). "keras" NO toca "tf_keras" (paquete distinto).
_DEAD_WEIGHT = [
    "torch", "torchvision", "torchaudio", "torchgen", "functorch",
    "transformers", "sentence_transformers", "tokenizers", "safetensors",
    "huggingface_hub", "accelerate",
    "scipy", "sklearn", "keras",
]

a = Analysis(
    [str(engine_dir / "bridge.py")],
    pathex=[str(engine_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter.test", "test", "tests"] + _DEAD_WEIGHT,
    noarchive=False,
)

# Más equipaje muerto (datas/binaries ya colectados):
# - googleapiclient discovery_cache: catálogos JSON de TODAS las APIs de Google
#   (~93MB); solo usamos Drive -> conservar únicamente drive*.json.
# - opencv_videoio_ffmpeg*.dll (~26MB): decodifica VIDEO; clasificamos fotos.
def _keep_data(entry):
    src = str(entry[0]).replace("\\", "/").lower()
    if "discovery_cache/documents/" in src:
        return os.path.basename(src).startswith("drive.")
    return True

import os
a.datas = [d for d in a.datas if _keep_data(d)]
a.binaries = [b for b in a.binaries
              if "opencv_videoio_ffmpeg" not in str(b[0]).lower()]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FaceSyncEngine",
    # Tauri exchanges newline-delimited JSON with the engine over stdin/stdout.
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    # UPX DESACTIVADO: comprime las DLL/pyd nativas y es causa clásica de
    # "carga en la PC de compilación pero falla en otra" (TensorFlow/tflite
    # especialmente). Sin UPX el binario es un poco más grande pero carga en
    # cualquier Windows. Fiabilidad > tamaño.
    upx=False,
    name="FaceSyncEngine",
)
