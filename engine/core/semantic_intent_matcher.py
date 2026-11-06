"""
Optional semantic intent matching for FaceSync local actions.

This module never executes tools. It only compares a user message against
local intent examples and returns the most similar intent when the optional
sentence-transformers dependency is available.
"""

from __future__ import annotations

from math import sqrt
from typing import Any, Dict, Iterable, List, Optional

from core.text_normalizer import TextNormalizer


DEFAULT_SEMANTIC_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


SEMANTIC_THRESHOLDS: Dict[str, float] = {
    "create_folder": 0.54,
    "create_multiple_folders": 0.56,
    "create_file": 0.56,
    "create_multiple_files": 0.58,
    "read_document": 0.58,
    "create_folders_from_excel": 0.59,
    "create_folders_from_table": 0.59,
    "excel_to_facesync_pipeline": 0.56,
    "prepare_facesync_pipeline": 0.56,
    "run_facesync": 0.60,
    "run_reference_face_matching": 0.58,
    "classify_photos_by_reference": 0.58,
    "move_item": 0.58,
    "rename_item": 0.58,
    "delete_item": 0.68,
    "search_files": 0.56,
    "scan_workspace": 0.56,
    "analyze_or_explain": 0.65,
}


SEMANTIC_INTENT_EXAMPLES: Dict[str, List[str]] = {
    "create_folder": [
        "crear una carpeta nueva",
        "hacer un folder para guardar cosas",
        "preparar una carpeta para una persona",
        "quiero una carpeta con este nombre",
        "crear un espacio para organizar archivos",
        "necesito una carpeta para alguien",
        "ponme una carpeta para guardar documentos",
        "hazme un lugar donde meter archivos",
        "crea un directorio nuevo",
        "generar una carpeta individual",
        "quiero guardar cosas de una persona en una carpeta",
        "haz una carpeta con el nombre indicado",
        "crea una carpeta dentro de otra carpeta",
        "prepara una carpeta en la ubicacion actual",
        "hazme un espacio para guardar lo de alguien",
        "quiero un lugar para meter archivos",
        "necesito una carpeta para un alumno",
        "prepara un folder para una persona",
        "creame algo para guardar lo de una persona",
        "crea una carpeta llamada",
        "hazme una carpeta",
        "prepara un folder",
        "crea un espacio para guardar",
        "crea una carpeta aqui",
        "crea una carpeta en la carpeta principal",
    ],
    "create_multiple_folders": [
        "crear varias carpetas con el mismo nombre base",
        "hacer cinco carpetas numeradas",
        "generar multiples folders dentro de una carpeta",
        "crear varias carpetas para evidencias",
        "crear carpetas numeradas",
        "necesito muchas carpetas con nombres parecidos",
        "haz varias carpetas para organizar grupos",
        "genera carpetas del uno al cinco",
        "crea diez carpetas dentro de una ubicacion",
        "hacer varias carpetas consecutivas",
        "crear multiples directorios",
        "preparar varias carpetas para pruebas",
        "genera varias carpetas numeradas",
        "haz muchas carpetas de evidencia",
        "crea carpetas consecutivas",
        "prepara varias carpetas dentro de otra",
    ],
    "create_file": [
        "crear un archivo nuevo",
        "hacer un documento de texto",
        "guardar una nota en un archivo",
        "generar un txt con contenido",
        "crear un archivo con texto",
        "hacer un archivo vacio",
        "crear un documento dentro de una carpeta",
        "necesito un archivo para notas",
        "guardar este texto en un archivo",
        "crear un archivo llamado reporte",
        "generar documento simple",
    ],
    "create_multiple_files": [
        "crear varios archivos",
        "hacer muchos documentos de texto",
        "generar archivos numerados",
        "crear cinco txt",
        "preparar varios archivos para evidencias",
        "hacer multiples documentos",
        "crear varios archivos con el mismo nombre base",
    ],
    "read_document": [
        "leer un archivo",
        "abrir un documento",
        "revisar un excel",
        "mostrar el contenido de un pdf",
        "dame las columnas del excel",
        "cuantas filas tiene el excel",
        "abre esta lista",
        "revisa este documento",
        "lee este archivo de texto",
        "muestrame lo que dice el documento",
        "extrae informacion del archivo",
        "revisar datos de una tabla",
        "abrir hoja de calculo",
        "ver contenido del pdf",
        "leer lista de alumnos",
        "revisar archivo xlsx",
    ],
    "create_folders_from_excel": [
        "leer una lista de alumnos y crear carpetas",
        "crear una carpeta por cada alumno del excel",
        "sacar carpetas desde la lista",
        "preparar carpetas del salon usando excel",
        "crear carpetas con los nombres de alumnos",
        "hacer carpetas para todos los estudiantes",
        "crear carpetas desde un archivo de alumnos",
        "usar el excel para generar carpetas",
        "crear una carpeta para cada persona de la lista",
        "preparar las carpetas del grupo",
        "leer lista y crear carpetas individuales",
        "crear carpetas con la columna nombre del alumno",
        "sacar los nombres del excel y convertirlos en carpetas",
        "crear estructura de carpetas desde la lista",
        "saca los nombres del excel y haz carpetas",
        "usa la lista para preparar carpetas",
        "haz carpetas del salon",
        "genera carpetas con los alumnos",
        "crear carpetas desde una tabla",
        "crear carpetas por cada persona de un csv",
    ],
    "create_folders_from_table": [
        "crear carpetas desde una tabla",
        "crear una carpeta por cada nombre del csv",
        "generar carpetas usando una columna de nombres",
        "leer un archivo tabular y crear carpetas por persona",
        "crea las carpetas con los nombres del excel",
        "haz una carpeta por cada registro",
        "crea carpetas por alumno",
        "crea carpetas por persona",
        "genera las carpetas usando la columna nombre",
        "usa la lista para crear las carpetas",
        "crea carpetas conforme a la tabla",
        "arma las carpetas desde el csv",
    ],
    "excel_to_facesync_pipeline": [
        "clasificar fotos por alumno usando excel",
        "leer la lista y meter cada foto en su carpeta",
        "usar la referencia del excel para identificar alumnos",
        "hacer el proceso completo del salon",
        "acomodar las fotos donde van segun la lista",
        "separar imagenes por alumno",
        "reconocer rostros y guardar fotos en carpetas",
        "usar el numero de foto como referencia",
        "lee el archivo de alumnos y mete sus fotos",
        "guarda la foto correspondiente de cada alumno",
        "identifica mediante la referencia a cada alumno",
        "crea carpetas y mete las fotos segun la referencia",
        "organiza las fotos por alumno usando el excel",
        "clasifica las fotos con la lista",
        "usa la lista 501 y separa las fotos por alumno",
        "agarra el excel y acomoda las fotos",
        "con la lista de alumnos acomoda sus fotos",
        "usa la referencia de la foto para guardar cada imagen",
        "separa las fotos de cada alumno usando la lista",
        "ejecuta todo el proceso del grupo",
        "mete las imagenes en la carpeta del alumno correspondiente",
        "reconoce estas imagenes y metelas a la carpeta de alumnos",
        "usa el excel y las fotos para organizar todo",
        "quiero que cada alumno tenga sus fotos",
        "acomoda las fotografias donde corresponden",
        "clasifica imagenes escolares por alumno",
        "organizar fotos escolares automaticamente",
        "detectar la foto de referencia y copiar coincidencias",
        "acomoda las fotos donde van",
        "mete las fotos en el alumno correcto",
        "haz todo el proceso del salon",
        "separa las fotos usando la lista",
        "clasifica imagenes por alumno",
        "usa la referencia para reconocer alumnos",
        "pon cada fotografia en su carpeta",
        "organiza las fotos escolares automaticamente",
        "basate en la columna foto para reconocer cada persona",
        "usa la foto de referencia y copia todas las coincidencias",
        "con el csv separa imagenes por personaje",
        "con la carpeta maestra busca todas las fotos de cada alumno",
    ],
    "prepare_facesync_pipeline": [
        "preparar el flujo de facesync con tabla fotos y destino",
        "usar lista carpeta maestra y carpeta destino para clasificar",
        "crear carpetas y preparar reconocimiento por referencia",
    ],
    "run_facesync": [
        "ejecutar reconocimiento facial",
        "correr FaceSync",
        "clasificar fotos por rostro",
        "reconocer imagenes de alumnos",
        "separar fotos con el motor facial",
        "correr el motor de IA de fotos",
        "iniciar clasificacion facial",
        "usar DeepFace para reconocer fotos",
        "ejecutar el motor de reconocimiento",
        "identificar rostros en la carpeta de fotos",
        "buscar coincidencias de rostro",
        "iniciar proceso de fotos por alumno",
        "corre el motor facial",
        "inicia el reconocimiento",
        "busca rostros similares",
        "ejecuta la clasificacion facial",
    ],
    "run_reference_face_matching": [
        "usar la columna foto como referencia facial",
        "comparar cada referencia contra todas las fotos",
        "buscar coincidencias por foto base",
        "clasificar fotos por referencia facial",
        "clasifica las fotos usando la referencia",
        "acomoda las imagenes con la columna foto",
        "mete cada foto en su carpeta correspondiente",
        "busca todas las coincidencias de cada persona",
        "usa la foto de referencia para reconocer a cada persona",
        "con la lista y las fotos organizalas por persona",
        "toma la carpeta maestra y separa las fotos",
        "usa el excel para saber de quien es cada foto",
        "reconoce las fotos y guardalas donde van",
        "basate en el codigo de foto y acomoda todo",
        "separa las fotos segun la referencia facial",
        "ordena las imagenes por alumno",
        "ordena las imagenes por cliente",
        "ordena las imagenes por persona",
        "clasifica por rostro usando la referencia del archivo",
    ],
    "classify_photos_by_reference": [
        "clasificar fotos usando referencias de una tabla",
        "acomodar fotos segun foto de referencia",
        "copiar coincidencias a la carpeta correspondiente",
        "reconocer personas con su imagen de referencia",
        "clasifica las fotos usando la referencia",
        "acomoda las imagenes con la columna foto",
        "mete cada foto en su carpeta correspondiente",
        "busca todas las coincidencias de cada persona",
        "usa la foto de referencia para reconocer a cada persona",
        "con la lista y las fotos organizalas por persona",
        "toma la carpeta maestra y separa las fotos",
        "usa el excel para saber de quien es cada foto",
        "reconoce las fotos y guardalas donde van",
        "basate en el codigo de foto y acomoda todo",
        "separa las fotos segun la referencia facial",
        "ordena las imagenes por alumno",
        "ordena las imagenes por cliente",
        "ordena las imagenes por persona",
        "clasifica por rostro usando la referencia del archivo",
    ],
    "move_item": [
        "mover un archivo a otra carpeta",
        "meter esto dentro de esa carpeta",
        "trasladar fotos o documentos",
        "guardar este archivo en otra ubicacion",
        "mueve eso ahi",
        "pasa el archivo a esa carpeta",
        "coloca el documento en la carpeta",
        "mueve la carpeta completa",
        "manda las fotos a otra ruta",
        "transfiere estos archivos",
        "cambia esto de ubicacion",
    ],
    "rename_item": [
        "cambiar el nombre de una carpeta",
        "renombrar un archivo",
        "ponerle otro nombre a esto",
        "renombralo",
        "renombrala",
        "cambia el nombre del documento",
        "modifica el nombre de la carpeta",
        "llamalo de otra forma",
        "ponle este nombre",
        "cambia ese archivo a otro nombre",
    ],
    "delete_item": [
        "borrar una carpeta",
        "eliminar un archivo",
        "quitar este elemento",
        "borrar esto con todo",
        "elimina esa carpeta",
        "borra el documento",
        "quitar archivo del workspace",
        "eliminar carpeta completa",
        "borrar archivos seleccionados",
        "eliminar lo ultimo",
    ],
    "search_files": [
        "buscar un archivo",
        "encontrar un documento",
        "localizar una foto",
        "donde esta este excel",
        "busca la lista",
        "encuentra el pdf",
        "localiza las fotos",
        "buscar por nombre",
        "buscar archivos xlsx",
        "encontrar imagenes",
        "donde quedo ese archivo",
        "encuentra la lista",
        "donde quedo el excel",
        "localiza las fotos",
        "busca el archivo del grupo",
    ],
    "scan_workspace": [
        "mostrar mis archivos",
        "escanear el workspace",
        "ver estructura de carpetas",
        "listar lo que hay",
        "muestrame el arbol",
        "que hay en esta carpeta",
        "revisa el contenido del workspace",
        "ensename la estructura",
        "lista las carpetas",
        "muestra todo lo que tengo",
        "ensename que hay",
        "muestra la estructura",
        "que carpetas tengo",
        "lista todo",
    ],
    "analyze_or_explain": [
        "analiza mi workspace",
        "sugiere como organizarlo",
        "dime que conviene",
        "revisa y recomienda",
        "interpreta este documento",
        "compara opciones",
        "dame una estrategia",
        "que estructura me recomiendas",
        "revisa esto y dime que hacer",
        "explicame como deberia organizarlo",
        "dame una recomendacion profesional",
        "analiza este excel y dime que ves",
    ],
}


class SemanticIntentMatcher:
    _model_cache: Dict[str, Any] = {}
    _embeddings_cache: Dict[str, Dict[str, List[tuple[str, List[float]]]]] = {}
    _errors: Dict[str, str] = {}

    def __init__(self, model_name: str = DEFAULT_SEMANTIC_MODEL, enabled: bool = True):
        self.model_name = model_name or DEFAULT_SEMANTIC_MODEL
        self.enabled = bool(enabled)
        self._available = False
        self._error = ""
        if not self.enabled:
            self._error = "disabled"
            print("[SEMANTIC] deshabilitado o no disponible")
            return
        self._ensure_loaded()

    def is_available(self) -> bool:
        return bool(self._available)

    def match(self, text: str, candidate_intents: Optional[list[str]] = None) -> dict:
        if not self.is_available():
            return self._failure(self._error or "semantic matcher not available")

        try:
            query = TextNormalizer.normalize_for_matching(text)
            query_vector = self._encode([query])[0]
            allowed = set(candidate_intents or SEMANTIC_INTENT_EXAMPLES.keys())
            best_intent = "unknown"
            best_score = 0.0
            best_example = ""

            for intent, examples in self._embeddings_cache.get(self.model_name, {}).items():
                if intent not in allowed:
                    continue
                for example, vector in examples:
                    score = self._cosine(query_vector, vector)
                    if score > best_score:
                        best_intent = intent
                        best_score = score
                        best_example = example

            print(f"[SEMANTIC] intent={best_intent} score={best_score:.2f} example=\"{best_example}\"")
            return {
                "intent": best_intent,
                "confidence": round(best_score, 4),
                "matched_example": best_example,
                "source": "semantic",
                "available": True,
            }
        except Exception as exc:
            self._available = False
            self._error = str(exc)
            return self._failure(str(exc))

    def _ensure_loaded(self):
        if self.model_name in self._model_cache and self.model_name in self._embeddings_cache:
            self._available = True
            return

        if self.model_name in self._errors:
            self._error = self._errors[self.model_name]
            print("[SEMANTIC] deshabilitado o no disponible")
            return

        try:
            from sentence_transformers import SentenceTransformer

            try:
                model = SentenceTransformer(self.model_name, local_files_only=True)
            except TypeError:
                model = SentenceTransformer(self.model_name)

            self._model_cache[self.model_name] = model
            self._precompute_embeddings()
            self._available = True
            total_examples = sum(len(items) for items in self._embeddings_cache[self.model_name].values())
            print(f"[SEMANTIC] Modelo cargado: {self.model_name}")
            print(f"[SEMANTIC] Ejemplos precalculados: {total_examples}")
        except Exception as exc:
            self._available = False
            self._error = str(exc)
            self._errors[self.model_name] = self._error
            print("[SEMANTIC] deshabilitado o no disponible")

    def _precompute_embeddings(self):
        cache: Dict[str, List[tuple[str, List[float]]]] = {}
        for intent, examples in SEMANTIC_INTENT_EXAMPLES.items():
            normalized_examples = [TextNormalizer.normalize_for_matching(example) for example in examples]
            vectors = self._encode(normalized_examples)
            cache[intent] = list(zip(examples, vectors))
        self._embeddings_cache[self.model_name] = cache

    def _encode(self, texts: Iterable[str]) -> List[List[float]]:
        model = self._model_cache[self.model_name]
        encoded = model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        if hasattr(encoded, "tolist"):
            encoded = encoded.tolist()
        return [self._as_vector(vector) for vector in encoded]

    @staticmethod
    def _as_vector(vector: Any) -> List[float]:
        if hasattr(vector, "tolist"):
            vector = vector.tolist()
        return [float(value) for value in vector]

    @staticmethod
    def _cosine(left: List[float], right: List[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = sqrt(sum(a * a for a in left))
        right_norm = sqrt(sum(b * b for b in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def _failure(error: str) -> dict:
        return {
            "intent": "unknown",
            "confidence": 0.0,
            "matched_example": "",
            "source": "semantic",
            "available": False,
            "error": error,
        }
