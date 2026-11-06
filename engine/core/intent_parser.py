
"""
======================================================================
MÓDULO: INTENT PARSER — FaceSync AI
Archivo: core/intent_parser.py
======================================================================

Responsabilidad:
- Analizar mensajes naturales del usuario
- Detectar intención principal
- Detectar entidades y parámetros
- Extraer rutas, nombres, acciones y contexto
- Convertir lenguaje humano → acciones estructuradas

Ejemplos:
"créame una carpeta llamada ventas en usuarios"
→ {
    "intent": "create_folder",
    "entities": {
        "folder_name": "ventas",
        "target_path": "usuarios"
    }
}

"lee el excel alumnos.xlsx"
→ {
    "intent": "read_file",
    "entities": {
        "file": "alumnos.xlsx"
    }
}

NO ejecuta acciones.
SOLO interpreta lenguaje natural.

======================================================================
"""

import re
from typing import Dict, List, Optional


class IntentParser:
    """
    Parser inteligente de intenciones.

    Convierte lenguaje natural en acciones estructuradas.
    """

    # ==========================================================
    # PALABRAS CLAVE
    # ==========================================================

    CREATE_WORDS = [
        "crear",
        "créame",
        "crea",
        "haz",
        "genera",
        "agrega",
        "añade",
        "nueva carpeta",
        "nuevo archivo"
    ]

    DELETE_WORDS = [
        "elimina",
        "borra",
        "borrar",
        "quitar",
        "destruye",
        "remueve"
    ]

    MOVE_WORDS = [
        "mueve",
        "traslada",
        "manda",
        "cambia",
        "reubica"
    ]

    RENAME_WORDS = [
        "renombra",
        "cambia nombre",
        "ponle",
        "modifica nombre"
    ]

    READ_WORDS = [
        "lee",
        "abre",
        "analiza",
        "revisa",
        "muestra",
        "dime qué contiene"
    ]

    SEARCH_WORDS = [
        "busca",
        "encuentra",
        "localiza"
    ]

    FACESYNC_WORDS = [
        "reconoce",
        "clasifica",
        "organiza fotos",
        "facesync",
        "deepface",
        "reconocimiento facial"
    ]

    # ==========================================================
    # EXTENSIONES SOPORTADAS
    # ==========================================================

    FILE_EXTENSIONS = [
        ".txt",
        ".pdf",
        ".docx",
        ".xlsx",
        ".xls",
        ".csv",
        ".json",
        ".xml",
        ".py",
        ".jpg",
        ".png",
        ".jpeg"
    ]

    # ==========================================================
    # PARSER PRINCIPAL
    # ==========================================================

    @classmethod
    def parse(cls, user_message: str) -> Dict:
        """
        Analiza el mensaje y devuelve una intención estructurada.

        Returns:
            {
                "intent": str,
                "confidence": float,
                "entities": {},
                "raw_text": str
            }
        """

        text = user_message.lower().strip()

        # ======================================================
        # DETECTAR INTENCIÓN
        # ======================================================

        intent = cls._detect_intent(text)

        # ======================================================
        # EXTRAER ENTIDADES
        # ======================================================

        entities = cls._extract_entities(text, intent)

        # ======================================================
        # CONFIANZA
        # ======================================================

        confidence = cls._calculate_confidence(intent, entities)

        return {
            "intent": intent,
            "confidence": confidence,
            "entities": entities,
            "raw_text": user_message
        }

    # ==========================================================
    # DETECCIÓN DE INTENCIÓN
    # ==========================================================

    @classmethod
    def _detect_intent(cls, text: str) -> str:
        """
        Detecta qué quiere hacer el usuario.
        """

        # FaceSync
        if cls._contains_any(text, cls.FACESYNC_WORDS):
            return "facesync"

        # Crear
        if cls._contains_any(text, cls.CREATE_WORDS):
            if "archivo" in text:
                return "create_file"
            return "create_folder"

        # Eliminar
        if cls._contains_any(text, cls.DELETE_WORDS):
            return "delete"

        # Mover
        if cls._contains_any(text, cls.MOVE_WORDS):
            return "move"

        # Renombrar
        if cls._contains_any(text, cls.RENAME_WORDS):
            return "rename"

        # Leer archivo
        if cls._contains_any(text, cls.READ_WORDS):
            return "read_file"

        # Buscar
        if cls._contains_any(text, cls.SEARCH_WORDS):
            return "search"

        return "unknown"

    # ==========================================================
    # EXTRAER ENTIDADES
    # ==========================================================

    @classmethod
    def _extract_entities(cls, text: str, intent: str) -> Dict:
        """
        Extrae nombres, rutas, archivos y datos relevantes.
        """

        entities = {}

        # ======================================================
        # EXTRAER ARCHIVOS
        # ======================================================

        file_match = re.findall(
            r'[\w\-. ]+\.(txt|pdf|docx|xlsx|xls|csv|json|xml|py|jpg|png|jpeg)',
            text
        )

        if file_match:
            entities["files"] = file_match

        # ======================================================
        # EXTRAER CARPETAS
        # ======================================================

        folder_patterns = [
            r'carpeta llamada ([\w\-_ ]+)',
            r'carpeta ([\w\-_ ]+)',
            r'directorio ([\w\-_ ]+)'
        ]

        for pattern in folder_patterns:
            match = re.search(pattern, text)

            if match:
                entities["folder_name"] = match.group(1).strip()
                break

        # ======================================================
        # EXTRAER RUTAS
        # ======================================================

        path_patterns = [
            r'en ([\w\/\\\-_ ]+)',
            r'dentro de ([\w\/\\\-_ ]+)',
            r'a ([\w\/\\\-_ ]+)'
        ]

        for pattern in path_patterns:
            match = re.search(pattern, text)

            if match:
                ruta = match.group(1).strip()

                # limpiar texto basura
                ruta = ruta.replace("la carpeta", "")
                ruta = ruta.replace("el directorio", "")
                ruta = ruta.strip()

                entities["target_path"] = ruta
                break

        # ======================================================
        # EXTRAER NOMBRE NUEVO
        # ======================================================

        rename_patterns = [
            r'a ([\w\-_ ]+)',
            r'como ([\w\-_ ]+)'
        ]

        if intent == "rename":
            for pattern in rename_patterns:
                match = re.search(pattern, text)

                if match:
                    entities["new_name"] = match.group(1).strip()
                    break

        # ======================================================
        # EXTRAER NÚMEROS
        # ======================================================

        numbers = re.findall(r'\d+', text)

        if numbers:
            entities["numbers"] = numbers

        # ======================================================
        # DETECTAR TIPO DE ARCHIVO
        # ======================================================

        if "excel" in text:
            entities["file_type"] = "excel"

        elif "pdf" in text:
            entities["file_type"] = "pdf"

        elif "word" in text:
            entities["file_type"] = "word"

        elif "txt" in text or "texto" in text:
            entities["file_type"] = "text"

        elif "json" in text:
            entities["file_type"] = "json"

        # ======================================================
        # FACE SYNC
        # ======================================================

        if intent == "facesync":

            # detectar excel
            excel_match = re.search(r'([\w\-_ ]+\.xlsx?)', text)

            if excel_match:
                entities["excel"] = excel_match.group(1)

            # detectar carpetas
            carpetas = re.findall(r'carpeta[s]? ([\w\-_\/\\ ]+)', text)

            if carpetas:
                entities["folders"] = carpetas

        return entities

    # ==========================================================
    # UTILIDADES
    # ==========================================================

    @staticmethod
    def _contains_any(text: str, words: List[str]) -> bool:
        """
        Verifica si el texto contiene alguna palabra clave.
        """

        return any(word in text for word in words)

    @staticmethod
    def _calculate_confidence(intent: str, entities: Dict) -> float:
        """
        Calcula nivel de confianza.
        """

        if intent == "unknown":
            return 0.2

        score = 0.5

        if entities:
            score += 0.3

        if len(entities) >= 2:
            score += 0.1

        if len(entities) >= 4:
            score += 0.1

        return min(score, 1.0)

    # ==========================================================
    # DEBUG
    # ==========================================================

    @classmethod
    def debug_parse(cls, text: str):
        """
        Método útil para pruebas.
        """

        result = cls.parse(text)

        print("\n" + "=" * 50)
        print("DEBUG PARSER")
        print("=" * 50)

        print(f"\nTexto:")
        print(text)

        print(f"\nIntent:")
        print(result["intent"])

        print(f"\nConfidence:")
        print(result["confidence"])

        print(f"\nEntities:")
        for k, v in result["entities"].items():
            print(f"  {k}: {v}")

        print("=" * 50)


# ==============================================================
# TEST LOCAL
# ==============================================================

if __name__ == "__main__":

    pruebas = [
        "créame una carpeta llamada ventas dentro de usuarios",
        "borra la carpeta pruebas",
        "mueve alumnos.xlsx a reportes",
        "lee el pdf contrato.pdf",
        "organiza las fotos usando alumnos.xlsx",
        "renombra carpeta1 a carpeta_final",
        "búscame el archivo test.py"
    ]

    for prueba in pruebas:
        IntentParser.debug_parse(prueba)

