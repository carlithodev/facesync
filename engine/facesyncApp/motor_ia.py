import os
import re
import shutil
import threading
from datetime import datetime

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# DeepFace arrastra TensorFlow (~6s y ~1GB) — se carga LAZY al primer uso.
# find_spec solo comprueba que el paquete exista, sin importarlo.
import importlib.util

DEEPFACE_AVAILABLE = importlib.util.find_spec("deepface") is not None
DeepFace = None  # se resuelve en _ejecutar_reconocimiento

# =====================================================
# OCULTAR WARNINGS TENSORFLOW
# =====================================================
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

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
        """
        Ejecuta el reconocimiento facial en un hilo secundario para no congelar la UI.
        """
        def proceso():
            try:
                MotorFaceSync._ejecutar_reconocimiento(
                    ruta_carpeta_fotos,
                    ruta_excel,
                    carpeta_destino,
                    columna_nombre=columna_nombre,
                    columna_referencia=columna_referencia
                )
                if callback_resultado:
                    callback_resultado(True, "✅ Clasificación facial completada con éxito.")
            except Exception as e:
                import traceback
                traceback.print_exc()
                if callback_resultado:
                    callback_resultado(False, f"❌ Error en IA: {str(e)}")

        hilo = threading.Thread(target=proceso, daemon=True)
        hilo.start()

    @staticmethod
    def _ejecutar_reconocimiento(
        ruta_carpeta_fotos,
        ruta_excel,
        carpeta_destino,
        columna_nombre="Nombre del Alumno",
        columna_referencia="Foto"
    ):
        if not PANDAS_AVAILABLE:
            raise RuntimeError("La librería 'pandas' no está instalada. Ejecuta: pip install pandas")
        if not DEEPFACE_AVAILABLE:
            raise RuntimeError("La librería 'deepface' no está instalada. Ejecuta: pip install deepface")

        global DeepFace
        if DeepFace is None:
            from deepface import DeepFace as _DeepFace
            DeepFace = _DeepFace

        # =====================================================
        # CONFIGURACIÓN ORIGINAL DEL SCRIPT
        # =====================================================
        MAX_OFFSET = 15
        MODELO = "ArcFace"
        DETECTOR = "retinaface"
        UMBRAL = 0.68
        EXTENSIONES = [".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"]

        # =====================================================
        # LEER TODAS LAS FOTOS
        # =====================================================
        imagenes = []
        print(f"\nBuscando imágenes en {ruta_carpeta_fotos}...\n")

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
        # MAPA DE ÍNDICES
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
        # CACHE & CONTROL DE FOTOS ÚNICAS
        # =====================================================
        cache = {}
        mapa_fotos = {}
        reporte = []

        def comparar(img1, img2):
            import time
            time.sleep(0.001)
            clave = tuple(sorted([img1, img2]))
            if clave in cache:
                return cache[clave]
            try:
                resultado = DeepFace.verify(
                    img1_path=img1,
                    img2_path=img2,
                    model_name=MODELO,
                    detector_backend=DETECTOR,
                    enforce_detection=False
                )
                distancia = resultado["distance"]
                cache[clave] = distancia
                return distancia
            except Exception as e:
                print("\nERROR COMPARANDO:")
                print(e)
                return 999

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
        # PROCESAR ALUMNOS
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
        print("PROCESO TERMINADO")
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
