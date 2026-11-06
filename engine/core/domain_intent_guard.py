"""
Domain guard for FaceSync local actions.

If a message belongs to the local FaceSync domain, it should not fall through
directly to Gemini. The app should execute locally or ask a local clarification.
"""

from __future__ import annotations

from typing import Any

from core.text_normalizer import NormalizedText, TextNormalizer


class DomainIntentGuard:
    FILE_TERMS = {
        "archivo", "archivos", "documento", "documentos", "txt", "pdf",
        "excel", "csv", "json", "xlsx", "xls", "lista", "tabla",
    }
    FOLDER_TERMS = {
        "carpeta", "carpetas", "folder", "directorio", "directorios",
        "crear", "crea", "haz", "genera", "nueva", "nuevo", "guardar",
        "dentro", "adentro", "donde", "espacio",
    }
    ACTION_TERMS = {
        "crea", "crear", "creame", "haz", "hazme", "genera", "mueve",
        "mover", "meter", "guarda", "guardar", "copia", "copiar",
        "borra", "elimina", "quitar", "renombra", "renombralo", "renombrala", "busca", "encuentra", "lee",
        "abre", "escanea", "lista", "clasificar", "organizar", "separar",
        "identifica", "reconoce", "reconocer", "poner", "muestra", "estructura", "arbol",
    }
    FACESYNC_TERMS = {
        "foto", "fotos", "imagen", "imagenes", "alumno", "alumnos",
        "persona", "personas", "cliente", "clientes", "participante",
        "participantes", "graduado", "graduados", "salon", "grupo",
        "referencia", "reconocimiento", "rostro",
        "rostros", "identifica", "clasificar", "organizar", "separar",
        "facesync", "coincidencia", "coincidencias",
    }
    CONTEXT_TERMS = {
        "ahi", "alli", "esa", "ese", "esas", "esos", "ultimo", "ultima", "donde",
    }
    ANALYSIS_TERMS = {
        "analiza", "analizar", "sugiere", "recomienda", "conviene",
        "estrategia", "interpreta", "resume", "revisa", "compara",
        "evalua", "evaluar", "criterio",
    }
    QUANTITY_TERMS = {
        "varias", "varios", "multiples", "muchas", "muchos",
        "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho",
        "nueve", "diez", "veinte",
    }

    @classmethod
    def is_analysis_request(cls, text: str | NormalizedText) -> bool:
        normalized = cls._normalized(text)
        tokens = set(normalized.tokens)
        norm_text = normalized.normalized
        return bool(tokens & cls.ANALYSIS_TERMS) or any(
            phrase in norm_text
            for phrase in (
                "que conviene",
                "como deberia",
                "dame una estrategia",
                "que estructura",
            )
        )

    @classmethod
    def is_local_domain(cls, text: str | NormalizedText) -> bool:
        normalized = cls._normalized(text)
        tokens = set(normalized.tokens)
        norm_text = normalized.normalized

        file_score = len(tokens & cls.FILE_TERMS)
        folder_score = len(tokens & cls.FOLDER_TERMS)
        action_score = len(tokens & cls.ACTION_TERMS)
        facesync_score = len(tokens & cls.FACESYNC_TERMS)
        context_score = len(tokens & cls.CONTEXT_TERMS)
        quantity_score = len(tokens & cls.QUANTITY_TERMS) + len([token for token in tokens if token.isdigit()])

        if facesync_score >= 1 and (action_score >= 1 or file_score >= 1 or folder_score >= 1):
            return True
        if action_score >= 1 and (file_score >= 1 or folder_score >= 1 or context_score >= 1):
            return True
        if quantity_score >= 1 and (folder_score >= 1 or file_score >= 1):
            return True
        if "cambia nombre" in norm_text or "donde estoy" in norm_text:
            return True
        if "estructura" in tokens or "arbol" in tokens:
            return True
        if "proceso completo" in norm_text and ("salon" in tokens or "grupo" in tokens):
            return True
        if "donde van" in norm_text and ("foto" in tokens or "fotos" in tokens or "imagen" in tokens or "imagenes" in tokens):
            return True

        return False

    @classmethod
    def clarification(cls, text: str | NormalizedText, context: Any = None) -> str:
        normalized = cls._normalized(text)
        tokens = set(normalized.tokens)
        norm_text = normalized.normalized

        has_quantity = bool(tokens & cls.QUANTITY_TERMS) or any(token.isdigit() for token in tokens)
        has_folder = "carpeta" in tokens or "carpetas" in tokens
        has_file = "archivo" in tokens or "archivos" in tokens
        has_photo = bool(tokens & {"foto", "fotos", "imagen", "imagenes", "rostro", "rostros"})
        has_student = bool(tokens & {"alumno", "alumnos", "persona", "personas", "cliente", "clientes", "salon", "grupo"})
        has_excel = "excel" in tokens or "csv" in tokens or "tabla" in tokens or "lista" in tokens

        if "crea" in tokens and "algo" in tokens and has_student:
            return "Quieres que cree una carpeta para alumnos o que cree carpetas por cada alumno desde un Excel?"

        if has_quantity and has_folder:
            if not cls._has_numeric_quantity(tokens):
                return "Cuantas carpetas quieres crear?"
            return "Con que nombre base quieres que las cree? Por ejemplo: fotos_01, fotos_02..."

        if has_quantity and has_file:
            if not cls._has_numeric_quantity(tokens):
                return "Cuantos archivos quieres crear?"
            return "Con que nombre base quieres que los cree? Por ejemplo: archivo_01, archivo_02..."

        if has_photo or has_student or "facesync" in tokens or "referencia" in tokens or "donde van" in norm_text:
            missing_excel = not (has_excel or cls._context_value(context, "ultimo_excel_leido") or cls._context_value(context, "last_excel"))
            missing_photos = not cls._context_value(context, "ultima_carpeta_fotos")
            missing_destination = not cls._context_value(context, "ultima_carpeta_destino")
            if missing_excel and missing_photos and missing_destination:
                return "Te entendi: quieres clasificar fotos por persona. Me falta saber que Excel o CSV usar, que carpeta contiene las fotos y donde guardar el resultado."
            if missing_excel and missing_photos:
                return "Te entendi: quieres clasificar fotos por persona. Me falta saber que Excel o CSV usar y que carpeta contiene las fotos originales."
            if missing_excel:
                return "Que Excel o CSV quieres usar?"
            if missing_photos:
                return "Que carpeta contiene las fotos originales?"
            if missing_destination:
                return "Donde quieres guardar las fotos clasificadas?"
            return "Te entendi como una accion de FaceSync. Que parte quieres ejecutar: crear carpetas, clasificar fotos o revisar el Excel?"

        if bool(tokens & {"lee", "abre"}) or has_excel or bool(tokens & {"pdf", "txt", "csv", "json"}):
            return "Que archivo quieres que lea?"

        if bool(tokens & {"mueve", "mover", "meter"}):
            if bool(tokens & {"ahi", "alli"}):
                return "Que elemento quieres mover y a que carpeta?"
            return "A que carpeta quieres moverlo?"

        if bool(tokens & {"borra", "elimina"}):
            return "Que elemento quieres eliminar exactamente?"

        if bool(tokens & {"crea", "crear", "creame", "haz", "genera", "nueva", "nuevo"}):
            if has_folder:
                return "Que nombre quieres ponerle a la carpeta?"
            if has_file:
                return "Que nombre quieres para el archivo?"
            return "Que quieres crear: una carpeta, un archivo o carpetas desde un Excel?"

        return "Te entendi como una accion local de FaceSync. Me falta un dato: que quieres hacer exactamente?"

    @staticmethod
    def _context_value(context: Any, key: str):
        if not context:
            return None
        getter = getattr(context, "get_context", None)
        if callable(getter):
            return getter(key)
        if isinstance(context, dict):
            return context.get(key)
        return None

    @classmethod
    def _has_numeric_quantity(cls, tokens: set[str]) -> bool:
        if any(token.isdigit() for token in tokens):
            return True
        return bool(tokens & {"dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "veinte"})

    @staticmethod
    def _normalized(text: str | NormalizedText) -> NormalizedText:
        if isinstance(text, NormalizedText):
            return text
        return TextNormalizer.normalize(str(text or ""))
