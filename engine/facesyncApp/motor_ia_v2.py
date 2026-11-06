"""
motor_ia_v2.py  —  Motor de reconocimiento FACESYNC acelerado (FASE 1, solo CPU).

OBJETIVO: bajar el tiempo de clasificacion SIN cambiar los resultados.

Como lo logra (mismo modelo, mismos resultados, mas rapido):
  - El motor original llama DeepFace.verify(img1, img2) por cada comparacion.
    Eso vuelve a DETECTAR y a re-procesar la foto de referencia decenas de
    veces (retinaface, que es lo mas lento). Aqui cada foto se procesa UNA
    sola vez: se calcula su "huella" (embedding) y se guarda en cache.
  - La comparacion se hace con la PROPIA funcion find_distance de DeepFace,
    asi la distancia sale BIT A BIT IGUAL que con DeepFace.verify ->
    misma clasificacion, mismo umbral (0.68), mismo reporte.
  - Las huellas se calculan en PARALELO (varios hilos) para aprovechar todos
    los nucleos del CPU. El calculo es determinista: el paralelismo solo
    cambia la velocidad, NUNCA el resultado.

Si algo fallara aqui, el despachador (motor_ia_fast.py) regresa
automaticamente al motor original probado. Nada se rompe.
"""

import os

# IMPORTANTE: DeepFace usa Keras 2 (tf_keras) para que retinaface/ArcFace
# funcionen con TensorFlow >= 2.16. Esto DEBE quedar puesto antes de que se
# importe TensorFlow. DeepFace.py lo hace en su top-level; como aqui usamos los
# submodulos de deepface, lo fijamos nosotros tambien (defensivo).
os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

import importlib.util

DEEPFACE_AVAILABLE = importlib.util.find_spec("deepface") is not None

# =====================================================
# OCULTAR WARNINGS TENSORFLOW
# =====================================================
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'


class MotorFaceSyncV2:

    @staticmethod
    def _ejecutar_reconocimiento(
        ruta_carpeta_fotos,
        ruta_excel,
        carpeta_destino,
        columna_nombre="Nombre del Alumno",
        columna_referencia="Foto"
    ):
        if not PANDAS_AVAILABLE:
            raise RuntimeError("La libreria 'pandas' no esta instalada. Ejecuta: pip install pandas")
        if not DEEPFACE_AVAILABLE:
            raise RuntimeError("La libreria 'deepface' no esta instalada. Ejecuta: pip install deepface")

        # Importamos PRIMERO el modulo top-level de DeepFace: su import fija
        # TF_USE_LEGACY_KERAS=1 antes de cargar TensorFlow, igual que hace el
        # motor original (sin esto, construir retinaface truena con Keras 3).
        from deepface import DeepFace as _DeepFace  # noqa: F401  (solo por su efecto de inicializacion)

        # Piezas internas que usa verify() por dentro.
        # Usar EXACTAMENTE estas funciones es lo que garantiza resultados identicos.
        from deepface.modules import detection, representation
        from deepface.modules.verification import find_distance

        # =====================================================
        # CONFIGURACION ORIGINAL DEL SCRIPT (sin cambios)
        # =====================================================
        MAX_OFFSET = 15
        MODELO = "ArcFace"
        DETECTOR = "retinaface"
        UMBRAL = 0.68
        EXTENSIONES = [".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"]

        # Nucleos a usar para calcular huellas en paralelo.
        # Configurable con la variable de entorno FACESYNC_WORKERS.
        try:
            workers = int(os.environ.get("FACESYNC_WORKERS", "0"))
        except ValueError:
            workers = 0
        if workers <= 0:
            workers = min(4, (os.cpu_count() or 1))

        # =====================================================
        # LEER TODAS LAS FOTOS
        # =====================================================
        imagenes = []
        print(f"\nBuscando imagenes en {ruta_carpeta_fotos}...\n")

        for root, dirs, files in os.walk(ruta_carpeta_fotos):
            for file in files:
                ext = os.path.splitext(file)[1]
                if ext not in EXTENSIONES:
                    continue
                nombre = os.path.splitext(file)[0]
                numeros = re.findall(r'\d+', nombre)
                if not numeros:
                    continue
                numero = int(numeros[-1])
                ruta = os.path.join(root, file)
                imagenes.append({
                    "numero": numero,
                    "ruta": ruta
                })

        imagenes.sort(key=lambda x: x["numero"])
        print(f"Fotos encontradas: {len(imagenes)}")

        # =====================================================
        # MAPA DE INDICES
        # =====================================================
        mapa_indices = {}
        for i, img in enumerate(imagenes):
            mapa_indices[img["numero"]] = i

        # =====================================================
        # LEER EXCEL
        # =====================================================
        print("\nLeyendo Excel...\n")
        df = pd.read_excel(ruta_excel)
        COLUMNA_NOMBRE = columna_nombre or "Nombre del Alumno"
        COLUMNA_REFERENCIA = columna_referencia or "Foto"
        faltantes = [col for col in (COLUMNA_NOMBRE, COLUMNA_REFERENCIA) if col not in df.columns]
        if faltantes:
            raise RuntimeError(
                "Columnas no encontradas en el Excel: "
                + ", ".join(map(str, faltantes))
                + ". Columnas disponibles: "
                + ", ".join(map(str, df.columns))
            )

        # =====================================================
        # CACHE DE HUELLAS (embeddings)
        # =====================================================
        # Por cada foto guardamos la lista de embeddings (uno por cara detectada),
        # tal cual los calcula verify() internamente. Asi cada foto se procesa
        # una sola vez y la comparacion es matematica pura (instantanea).
        cache_embeddings = {}

        def _calcular_embeddings(ruta_img):
            """Replica EXACTAMENTE lo que verify() hace por dentro para una imagen."""
            try:
                caras = detection.extract_faces(
                    img_path=ruta_img,
                    detector_backend=DETECTOR,
                    grayscale=False,
                    enforce_detection=False,
                    align=True,
                    expand_percentage=0,
                    anti_spoofing=False,
                )
                embs = []
                for cara in caras:
                    obj = representation.represent(
                        img_path=cara["face"][:, :, ::-1],  # mismo paso que verify (RGB->BGR)
                        model_name=MODELO,
                        enforce_detection=False,
                        detector_backend="skip",
                        align=True,
                        normalization="base",
                    )
                    embs.append(obj[0]["embedding"])
                return embs
            except Exception as e:
                print("\nERROR CALCULANDO HUELLA:")
                print(ruta_img)
                print(e)
                return []  # sin huella -> se tratara como "diferente" (igual que el motor original devolvia 999)

        def obtener_embeddings(ruta_img):
            if ruta_img not in cache_embeddings:
                cache_embeddings[ruta_img] = _calcular_embeddings(ruta_img)
            return cache_embeddings[ruta_img]

        def comparar(img1, img2):
            """Distancia minima entre todas las caras de img1 y img2.
            Identica a DeepFace.verify(...)['distance']."""
            embs1 = obtener_embeddings(img1)
            embs2 = obtener_embeddings(img2)
            if not embs1 or not embs2:
                return 999
            min_d = float("inf")
            for e1 in embs1:
                for e2 in embs2:
                    d = float(find_distance(e1, e2, "cosine"))
                    if d < min_d:
                        min_d = d
            return min_d

        # =====================================================
        # PRE-CALCULO DE HUELLAS EN PARALELO
        # =====================================================
        # Solo precalculamos las fotos que el algoritmo podria tocar: la
        # referencia de cada alumno y sus vecinos (+-MAX_OFFSET). Es el mismo
        # conjunto de trabajo del motor original, pero cada foto UNA vez y en
        # paralelo. El conteo final de copias lo decide el algoritmo de abajo
        # (con su corte temprano), asi que los resultados no cambian.
        indices_a_precalcular = set()
        for _, row in df.iterrows():
            try:
                referencia = int(row[COLUMNA_REFERENCIA])
            except Exception:
                continue
            if referencia not in mapa_indices:
                continue
            idx_ref = mapa_indices[referencia]
            ini = max(0, idx_ref - MAX_OFFSET)
            fin = min(len(imagenes), idx_ref + MAX_OFFSET + 1)
            for idx in range(ini, fin):
                indices_a_precalcular.add(idx)

        rutas_precalculo = [imagenes[i]["ruta"] for i in sorted(indices_a_precalcular)]
        total_pre = len(rutas_precalculo)
        print(f"\nPre-calculando huellas faciales: {total_pre} fotos ({workers} nucleos)...\n")

        if rutas_precalculo:
            # Calentamos los modelos UNA vez (build) antes de lanzar los hilos,
            # para que todos compartan el mismo modelo ya cargado.
            cache_embeddings[rutas_precalculo[0]] = _calcular_embeddings(rutas_precalculo[0])

            pendientes = rutas_precalculo[1:]
            if pendientes:
                hecho = 1

                def _trabajo(ruta):
                    return ruta, _calcular_embeddings(ruta)

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for ruta, embs in pool.map(_trabajo, pendientes):
                        cache_embeddings[ruta] = embs
                        hecho += 1
                        if hecho % 200 == 0 or hecho == total_pre:
                            print(f"  Huellas calculadas: {hecho}/{total_pre}")

        # =====================================================
        # CONTROL DE FOTOS UNICAS (identico al original)
        # =====================================================
        mapa_fotos = {}
        reporte = []

        def mover_foto_unica(ruta_foto, alumno):
            nombre_archivo = os.path.basename(ruta_foto)
            carpeta_alumno = os.path.join(carpeta_destino, alumno)
            os.makedirs(carpeta_alumno, exist_ok=True)
            nueva_ruta = os.path.join(carpeta_alumno, nombre_archivo)

            if ruta_foto in mapa_fotos:
                alumno_anterior = mapa_fotos[ruta_foto]
                if alumno_anterior != alumno:
                    ruta_anterior = os.path.join(carpeta_destino, alumno_anterior, nombre_archivo)
                    if os.path.exists(ruta_anterior):
                        os.remove(ruta_anterior)
                        print(f"ELIMINADA DE: {alumno_anterior}")

            if not os.path.exists(nueva_ruta):
                shutil.copy2(ruta_foto, nueva_ruta)
            mapa_fotos[ruta_foto] = alumno
            return True

        # =====================================================
        # PROCESAR ALUMNOS (algoritmo IDENTICO al original)
        # =====================================================
        for _, row in df.iterrows():
            alumno = ""
            referencia = ""
            fotos_copiadas = 0
            try:
                alumno = str(row[COLUMNA_NOMBRE]).strip()
                referencia = int(row[COLUMNA_REFERENCIA])
            except Exception as e:
                reporte.append({
                    "Alumno": alumno,
                    "Referencia": referencia,
                    "Fotos copiadas": fotos_copiadas,
                    "Estado": "Ignorado",
                    "Mensaje": f"Fila incompleta o referencia invalida: {e}"
                })
                continue

            print("\n===================================")
            print(f"Alumno: {alumno}")
            print(f"Referencia: {referencia}")

            if referencia not in mapa_indices:
                print("Referencia no encontrada")
                reporte.append({
                    "Alumno": alumno,
                    "Referencia": referencia,
                    "Fotos copiadas": fotos_copiadas,
                    "Estado": "Sin referencia",
                    "Mensaje": "La foto de referencia no se encontro en la carpeta origen."
                })
                continue

            idx_ref = mapa_indices[referencia]
            ruta_ref = imagenes[idx_ref]["ruta"]
            print(f"Foto referencia:\n{ruta_ref}")

            if mover_foto_unica(ruta_ref, alumno):
                fotos_copiadas += 1

            print("\nBuscando derecha...\n")
            for offset in range(1, MAX_OFFSET + 1):
                idx = idx_ref + offset
                if idx >= len(imagenes):
                    break
                actual = imagenes[idx]
                print(f"Comparando:\n{actual['ruta']}")
                distancia = comparar(ruta_ref, actual["ruta"])
                print(f"Distancia: {distancia:.3f}")
                if distancia <= UMBRAL:
                    print("MISMA PERSONA")
                    if mover_foto_unica(actual["ruta"], alumno):
                        fotos_copiadas += 1
                else:
                    print("DIFERENTE")
                    break

            print("\nBuscando izquierda...\n")
            for offset in range(1, MAX_OFFSET + 1):
                idx = idx_ref - offset
                if idx < 0:
                    break
                actual = imagenes[idx]
                print(f"Comparando:\n{actual['ruta']}")
                distancia = comparar(ruta_ref, actual["ruta"])
                print(f"Distancia: {distancia:.3f}")
                if distancia <= UMBRAL:
                    print("MISMA PERSONA")
                    if mover_foto_unica(actual["ruta"], alumno):
                        fotos_copiadas += 1
                else:
                    print("DIFERENTE")
                    break

            reporte.append({
                "Alumno": alumno,
                "Referencia": referencia,
                "Fotos copiadas": fotos_copiadas,
                "Estado": "Procesado",
                "Mensaje": ""
            })

        print("\n===================================")
        print("PROCESO TERMINADO (motor v2 acelerado)")
        print("===================================")

        try:
            os.makedirs(carpeta_destino, exist_ok=True)
            reporte_path = os.path.join(
                carpeta_destino,
                f"FaceSync_Reporte_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            )
            pd.DataFrame(reporte).to_excel(reporte_path, index=False)
            print(f"Reporte generado: {reporte_path}")
        except Exception as e:
            print(f"No se pudo generar reporte: {e}")
