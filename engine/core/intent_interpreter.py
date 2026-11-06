"""
Local intent scoring for FaceSync AI.

The interpreter is deliberately heuristic and transparent: it scores groups of
signals instead of depending on exact full-sentence commands.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Tuple

from core.semantic_intent_matcher import (
    DEFAULT_SEMANTIC_MODEL,
    SEMANTIC_THRESHOLDS,
    SemanticIntentMatcher,
)
from core.slot_extractor import SlotExtractor
from core.text_normalizer import NormalizedText, TextNormalizer


class IntentInterpreter:
    NORMAL_ACTION_THRESHOLD = 0.65
    HIGH_RULE_CONFIDENCE = 0.75
    _semantic_matcher: SemanticIntentMatcher | None = None

    CREATE_WORDS = {
        "crea",
        "crear",
        "creame",
        "haz",
        "genera",
        "generar",
        "preparar",
        "poner",
        "necesitar",
        "quiero",
        "nuevo",
        "nueva",
        "extraer",
    }
    FILE_WORDS = {"archivo", "txt", "documento"}
    FOLDER_WORDS = {"carpeta", "carpetas", "directorio", "espacio"}
    READ_WORDS = {"lee", "leer", "abre", "abrir", "muestra", "muestrame", "revisa", "dice", "dame"}
    DELETE_WORDS = {"elimina", "eliminar", "borra", "borrar", "quitar", "remueve", "remover", "deshazte",
                    "eliminalo", "eliminala", "borralo", "borrala",
                    "quita", "quitalo", "quitala"}
    MOVE_WORDS = {"mueve", "mover", "meter", "traslada", "poner", "guardar",
                  "muevelo", "muevela", "trasladar", "pasalo", "pasala",
                  "pasa", "pasar", "manda", "mandar", "lleva", "llevar",
                  "llevalo", "llevala", "acomoda", "acomodar"}
    COPY_WORDS = {"copia", "copiar", "copialo", "copiala", "copialos", "copialas",
                  "duplica", "duplicar", "duplicalo", "duplicala", "repite"}
    RENAME_WORDS = {"renombra", "renombrar", "renombralo", "renombrala",
                    "renombrame", "llamala", "llamalo"}
    SEARCH_WORDS = {"busca", "buscar", "encuentra", "localiza"}
    ANALYZE_WORDS = {"analiza", "analizar", "resume", "resumir", "interpreta", "sugiere", "recomienda", "explica"}

    PIPELINE_A = {
        "excel",
        "csv",
        "tabla",
        "archivo",
        "lista",
        "alumno",
        "alumnos",
        "persona",
        "personas",
        "cliente",
        "clientes",
        "participante",
        "participantes",
        "graduado",
        "graduados",
        "personaje",
        "personajes",
        "salon",
        "grupo",
    }
    PIPELINE_B = {"foto", "fotos", "imagen", "imagenes", "rostro", "rostros"}
    PIPELINE_C = {"referencia", "numero", "codigo", "id", "identifica", "identificar", "reconoce", "reconocer", "basate", "base", "coincidencia", "coincidencias"}
    PIPELINE_D = {"carpeta", "carpetas", "guardar", "meter", "clasificar", "organizar", "separar", "acomodar", "poner", "copiar", "copia", "buscar", "busca"}
    NUMBER_WORDS = {
        "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho",
        "nueve", "diez", "veinte", "varias", "varios", "multiples",
        "muchas", "muchos",
    }

    @classmethod
    def interpret(
        cls,
        original_text: str,
        normalized: NormalizedText | str,
        context: Any = None,
    ) -> Dict[str, Any]:
        if isinstance(normalized, str):
            normalized = TextNormalizer.normalize(normalized)

        scores: Dict[str, Tuple[float, str]] = {}
        tokens = set(normalized.tokens)
        text = normalized.normalized

        def add(intent: str, score: float, reason: str):
            previous = scores.get(intent)
            if previous is None or score > previous[0]:
                scores[intent] = (min(score, 0.99), reason)

        # FaceSync full pipeline has priority over folder-only Excel flows.
        a = cls._has_any(tokens, cls.PIPELINE_A) or "lista" in text
        b = cls._has_any(tokens, cls.PIPELINE_B)
        c = cls._has_any(tokens, cls.PIPELINE_C)
        d = cls._has_any(tokens, cls.PIPELINE_D)
        if a and b and d:
            add("excel_to_facesync_pipeline", 0.82 + (0.12 if c else 0.0), "Detecte Excel/lista, fotos y organizacion por carpetas")
        if a and b and c and d:
            add("excel_to_facesync_pipeline", 0.96, "Detecte lista, fotos, referencia e intencion de clasificar")
        if b and d and ("donde van" in text or ("cada" in tokens and "carpeta" in tokens)):
            add("excel_to_facesync_pipeline", 0.88, "Detecte fotos que deben ir a su carpeta")
        if a and c:
            add("excel_to_facesync_pipeline", 0.72, "Detecte referencia desde Excel")
        if b and c and d:
            add("excel_to_facesync_pipeline", 0.88, "Detecte fotos con referencia e intencion de clasificar")
        if b and c and any(word in tokens for word in ("referencia", "numero")):
            add("excel_to_facesync_pipeline", 0.76, "Detecte foto usada como referencia")
        if (
            ("proceso" in tokens or "todo" in tokens)
            and ("salon" in tokens or "grupo" in tokens or "persona" in tokens or "personas" in tokens or cls._context_has_excel(context))
            and (cls._has_any(tokens, cls.CREATE_WORDS) or "hacer" in tokens or "preparar" in tokens)
        ):
            add("excel_to_facesync_pipeline", 0.76, "Detecte proceso completo del grupo")
        if "proceso completo" in text and ("salon" in tokens or "grupo" in tokens or "persona" in tokens or "personas" in tokens or cls._context_has_excel(context)):
            add("excel_to_facesync_pipeline", 0.76, "Detecte el proceso completo del grupo")
        if "donde van" in text and b and ("excel" in tokens or cls._context_has_excel(context)):
            add("excel_to_facesync_pipeline", 0.82, "Detecte fotos con destino inferido desde Excel")
        if c and d and any(word in tokens for word in ("referencia", "numero")):
            add("excel_to_facesync_pipeline", 0.73, "Detecte clasificacion usando referencia")

        # Run FaceSync without the Excel+folder creation setup.
        if (
            "facesync" in text
            or "reconocimiento facial" in text
            or ("clasificar" in tokens and b)
            or ("identifica" in tokens and b)
        ):
            if "excel_to_facesync_pipeline" not in scores:
                add("run_facesync", 0.74, "Detecte ejecucion del motor FaceSync")

        # Excel -> folders only. Loses priority when photos/reference are present.
        has_quantity = cls._has_quantity(normalized)
        excel_signal = "excel" in tokens or "csv" in tokens or "tabla" in tokens or "salon" in tokens or "grupo" in tokens
        list_or_excel_signal = "excel" in tokens or "lista" in text or cls._has_document_signal(tokens, text)
        folder_batch_signal = (
            "carpetas" in text
            or ("carpeta" in tokens and "cada" in tokens)
            or ("carpeta" in tokens and "por" in tokens and ("alumno" in tokens or "alumnos" in tokens or "persona" in tokens or "personas" in tokens))
        )
        create_batch_signal = cls._has_any(tokens, cls.CREATE_WORDS) or "preparar" in tokens or "extraer" in tokens or "saca" in text
        student_batch_signal = "cada" in tokens and ("alumno" in tokens or "alumnos" in tokens or "persona" in tokens or "personas" in tokens or "nombre" in tokens)
        if (excel_signal or student_batch_signal) and folder_batch_signal and create_batch_signal and not b and (not has_quantity or list_or_excel_signal):
            add("create_folders_from_excel", 0.88, "Detecte creacion de carpetas desde lista/Excel")
        elif "excel" in tokens and "carpeta" in tokens and not b:
            add("create_folders_from_excel", 0.72, "Detecte Excel con carpetas")
        if cls._has_document_signal(tokens, text) and folder_batch_signal and create_batch_signal and not b:
            add("create_folders_from_excel", 0.90, "Detecte Excel especifico para crear carpetas")
        if cls._has_any(tokens, cls.CREATE_WORDS) and "carpetas" in text and "columna" in tokens and not b:
            add("create_folders_from_excel", 0.84, "Detecte carpetas desde columna del Excel")
        if cls._has_any(tokens, cls.CREATE_WORDS) and "carpetas" in text and ("alumnos" in tokens or "personas" in tokens or "grupo" in tokens) and not b:
            add("create_folders_from_excel", 0.80, "Detecte carpetas para alumnos del grupo")

        # Direct local actions.
        if has_quantity and cls._has_any(tokens, cls.CREATE_WORDS) and ("carpetas" in tokens or "carpeta" in tokens):
            add("create_multiple_folders", 0.84, "Detecte creacion de multiples carpetas")
        if has_quantity and cls._has_any(tokens, cls.CREATE_WORDS) and ("archivos" in tokens or "archivo" in tokens):
            add("create_multiple_files", 0.84, "Detecte creacion de multiples archivos")

        if cls._has_any(tokens, cls.CREATE_WORDS) and cls._has_any(tokens, cls.FILE_WORDS):
            add("create_file", 0.83, "Detecte creacion de archivo")
        if cls._looks_like_explicit_file_creation(normalized):
            add("create_file", 0.86, "Detecte nombre de archivo con intencion de crear")

        if cls._has_any(tokens, cls.CREATE_WORDS) and cls._has_any(tokens, cls.FOLDER_WORDS):
            add("create_folder", 0.82, "Detecte creacion de carpeta")
        create_folder_context = cls._has_any(tokens, cls.CREATE_WORDS) and cls._has_any(tokens, cls.FOLDER_WORDS)
        if create_folder_context and any(
            phrase in normalized.ascii_text
            for phrase in (
                " llama ",
                " llamada ",
                " llamado ",
                " que se llame ",
                " que se nombre ",
                " con nombre ",
                " con el nombre ",
            )
        ):
            add("create_folder", 0.90, "Detecte nombre de carpeta solicitado")
        if "guardar cosas de" in text and "carpeta" in tokens:
            add("create_folder", 0.78, "Detecte necesidad de una carpeta para guardar cosas")
        if "donde meter" in text:
            add("create_folder", 0.88, "Detecte solicitud de crear un espacio/carpeta")
        if cls._has_any(tokens, cls.CREATE_WORDS) and "algo" in tokens and any(word in tokens for word in ("guardar", "meter")):
            add("create_folder", 0.88, "Detecte solicitud de un espacio para guardar algo")

        if cls._has_any(tokens, cls.READ_WORDS) and (
            cls._has_document_signal(tokens, text) or "archivo" in tokens or "documento" in tokens
        ):
            add("read_document", 0.80, "Detecte lectura de documento local")
        if "columnas" in tokens or "filas" in tokens or "que dice" in text:
            add("read_document", 0.84, "Detecte consulta de contenido de documento")
        if cls._has_any(tokens, cls.READ_WORDS) and "hoja" in tokens and "calculo" in tokens:
            add("read_document", 0.80, "Detecte hoja de calculo")

        if cls._has_any(tokens, cls.SEARCH_WORDS) or "donde esta" in text:
            add("search_files", 0.82, "Detecte busqueda local")

        if (
            "workspace" in tokens
            or "estructura" in tokens
            or "arbol" in tokens
            or "mis archivos" in text
            or "que hay" in text
        ):
            if any(word in tokens for word in ("escanea", "muestra", "lista", "verifica", "metricas")) or "que hay" in text or "mis archivos" in text or "estructura" in tokens:
                add("scan_workspace", 0.82, "Detecte escaneo del workspace")

        if cls._has_any(tokens, cls.MOVE_WORDS) and "donde meter" not in text:
            add("move_item", 0.90, "Detecte movimiento de archivo/carpeta")

        if cls._has_any(tokens, cls.COPY_WORDS):
            # Prioridad sobre create_folder en frases contextuales como
            # "duplica la carpeta que acabas de crear".
            add("copy_item", 0.92, "Detecte copia de archivo/carpeta")

        explicit_rename = cls._has_any(tokens, cls.RENAME_WORDS)
        rename_signal = (
            explicit_rename
            or ("cambia" in tokens and "nombre" in tokens)
            or ("cambiar" in tokens and "nombre" in tokens)
            or ("cambiale" in tokens and "nombre" in tokens)
            or ("poner" in tokens and "nombre" in tokens)
            or ("ponle" in tokens and "nombre" in tokens)
            # "llama a esa carpeta X" / "llama al archivo X" -> renombrar.
            # El normalizador convierte "llama" -> "llamada"; se distingue de
            # "carpeta llamada X" (crear) porque aqui va "llamada a esa/ese/al ...".
            or any(p in text for p in (
                "llamada a esa", "llamada a ese", "llamada a esta",
                "llamada a este", "llamada al", "llamada a la"))
        )
        if rename_signal and (explicit_rename or not create_folder_context):
            add("rename_item", 0.84, "Detecte renombrado")

        if cls._has_any(tokens, cls.DELETE_WORDS) and ("carpeta" in tokens or "carpetas" in tokens) and list_or_excel_signal:
            add("delete_folders_from_excel", 0.93, "Detecte borrado de carpetas generadas desde Excel")

        if cls._has_any(tokens, cls.DELETE_WORDS):
            add("delete_item", 0.90, "Detecte eliminacion local")

        if cls._has_any(tokens, cls.ANALYZE_WORDS):
            add("analyze_or_explain", 0.70, "Detecte analisis o explicacion")

        intent, confidence, reason = cls._pick(scores)
        if confidence < 0.40:
            intent = "unknown"
            confidence = 0.20
            reason = "No encontre suficientes senales locales"

        source = "rules"
        semantic_match = {}
        if confidence < cls.HIGH_RULE_CONFIDENCE:
            intent, confidence, reason, source, semantic_match = cls._combine_with_semantic(
                intent=intent,
                confidence=confidence,
                reason=reason,
                text=normalized.normalized,
                tokens=tokens,
            )

        args = SlotExtractor.extract(intent, original_text, normalized, context)
        needs_clarification, question = cls._clarification_for(intent, args)

        return {
            "intent": intent,
            "confidence": round(confidence, 2),
            "args": args,
            "needs_clarification": needs_clarification,
            "question": question,
            "reason": reason,
            "source": source,
            "semantic": semantic_match,
            "normalized_text": normalized.normalized,
            "corrections": normalized.corrections,
        }

    @classmethod
    def _pick(cls, scores: Dict[str, Tuple[float, str]]) -> tuple[str, float, str]:
        if not scores:
            return "unknown", 0.20, "Sin senales"

        priority = {
            "excel_to_facesync_pipeline": 100,
            "run_facesync": 90,
            "create_folders_from_excel": 80,
            "delete_folders_from_excel": 78,
            "delete_item": 70,
            "rename_item": 65,
            "move_item": 60,
            "copy_item": 58,
            "create_file": 55,
            "create_multiple_folders": 54,
            "create_multiple_files": 54,
            "create_folder": 50,
            "read_document": 45,
            "search_files": 40,
            "scan_workspace": 35,
            "analyze_or_explain": 10,
        }

        intent = max(scores, key=lambda key: (scores[key][0], priority.get(key, 0)))
        score, reason = scores[intent]
        return intent, score, reason

    @staticmethod
    def _has_any(tokens: set[str], words: Iterable[str]) -> bool:
        return any(word in tokens for word in words)

    @staticmethod
    def _has_document_signal(tokens: set[str], text: str) -> bool:
        if tokens.intersection({"excel", "pdf", "csv", "txt", "json", "docx", "tabla"}):
            return True
        return any(ext in text for ext in (".xlsx", ".xls", ".csv", ".pdf", ".txt", ".docx", ".json"))

    @staticmethod
    def _context_has_excel(context: Any) -> bool:
        if not context:
            return False
        getter = getattr(context, "get_context", None)
        if callable(getter):
            return bool(getter("ultimo_excel_leido") or getter("last_excel"))
        if isinstance(context, dict):
            return bool(context.get("ultimo_excel_leido") or context.get("last_excel"))
        return False

    @classmethod
    def _looks_like_explicit_file_creation(cls, normalized: NormalizedText) -> bool:
        if not cls._has_any(set(normalized.tokens), cls.CREATE_WORDS):
            return False
        return any("." in item.clean and len(item.clean.rsplit(".", 1)[-1]) <= 5 for item in normalized.token_items)

    @classmethod
    def _has_quantity(cls, normalized: NormalizedText) -> bool:
        return any(token.isdigit() or token in cls.NUMBER_WORDS for token in normalized.tokens)

    @classmethod
    def _combine_with_semantic(
        cls,
        *,
        intent: str,
        confidence: float,
        reason: str,
        text: str,
        tokens: set[str],
    ) -> tuple[str, float, str, str, dict]:
        matcher = cls._get_semantic_matcher()
        if not matcher or not matcher.is_available():
            return intent, confidence, reason, "rules", {}

        semantic = matcher.match(text)
        if not semantic.get("available"):
            return intent, confidence, reason, "rules", semantic

        semantic_intent = semantic.get("intent") or "unknown"
        semantic_confidence = float(semantic.get("confidence") or 0.0)
        threshold = cls._semantic_threshold_for(semantic_intent)
        if semantic_confidence < threshold:
            return intent, confidence, reason, "rules", semantic

        if semantic_intent == "analyze_or_explain" and not cls._looks_like_analysis_request(tokens, text):
            return intent, confidence, reason, "rules", semantic

        if semantic_intent == intent:
            merged_confidence = min(0.99, max(confidence, semantic_confidence) + 0.08)
            return (
                intent,
                merged_confidence,
                f"{reason}; semantic coincidio con el intent",
                "rules+semantic",
                semantic,
            )

        facesync_semantic_intents = {
            "excel_to_facesync_pipeline",
            "prepare_facesync_pipeline",
            "run_facesync",
            "run_reference_face_matching",
            "classify_photos_by_reference",
        }
        if semantic_intent in facesync_semantic_intents and cls._mentions_facesync_pipeline(tokens, text):
            return (
                "excel_to_facesync_pipeline" if semantic_intent in {"run_reference_face_matching", "classify_photos_by_reference"} else semantic_intent,
                semantic_confidence,
                "SemanticIntentMatcher detecto pipeline FaceSync",
                "semantic",
                semantic,
            )

        if semantic_intent in {"move_item", "create_folder", "create_file"} and cls._mentions_facesync_pipeline(tokens, text):
            return intent, confidence, reason, "rules", semantic

        return (
            semantic_intent,
            semantic_confidence,
            f"SemanticIntentMatcher sugirio {semantic_intent}",
            "semantic",
            semantic,
        )

    @classmethod
    def _get_semantic_matcher(cls) -> SemanticIntentMatcher | None:
        if not cls._semantic_enabled():
            if cls._semantic_matcher is None:
                cls._semantic_matcher = SemanticIntentMatcher(enabled=False)
            return cls._semantic_matcher

        if cls._semantic_matcher is None:
            model_name = (os.getenv("SEMANTIC_MODEL") or DEFAULT_SEMANTIC_MODEL).strip()
            cls._semantic_matcher = SemanticIntentMatcher(model_name=model_name, enabled=True)
        return cls._semantic_matcher

    @staticmethod
    def _semantic_enabled() -> bool:
        value = (os.getenv("USE_SEMANTIC_ROUTER") or "true").strip().lower()
        return value not in {"0", "false", "no", "off", "disabled"}

    @staticmethod
    def _semantic_threshold_for(intent: str) -> float:
        fallback = os.getenv("SEMANTIC_THRESHOLD_DEFAULT") or "0.58"
        try:
            default = float(fallback)
        except ValueError:
            default = 0.58
        return SEMANTIC_THRESHOLDS.get(intent, default)

    @classmethod
    def _looks_like_analysis_request(cls, tokens: set[str], text: str) -> bool:
        return cls._has_any(tokens, cls.ANALYZE_WORDS) or any(
            phrase in text
            for phrase in (
                "que conviene",
                "como deberia",
                "dame una estrategia",
                "que estructura me recomiendas",
                "revisa y recomienda",
            )
        )

    @classmethod
    def _mentions_facesync_pipeline(cls, tokens: set[str], text: str) -> bool:
        signal_words = cls.PIPELINE_A | cls.PIPELINE_B | cls.PIPELINE_C | cls.PIPELINE_D
        return cls._has_any(tokens, signal_words) or any(
            phrase in text
            for phrase in (
                "donde van",
                "proceso del salon",
                "proceso completo",
                "todo el salon",
                "cada foto",
            )
        )

    @staticmethod
    def _clarification_for(intent: str, args: Dict[str, Any]) -> tuple[bool, str]:
        if intent == "create_multiple_folders":
            if not args.get("quantity"):
                return True, "Cuantas carpetas quieres crear?"
            if not args.get("base_name"):
                return True, "Con que nombre base quieres que las cree? Por ejemplo: fotos_01, fotos_02..."
            return False, ""

        if intent == "create_multiple_files":
            if not args.get("quantity"):
                return True, "Cuantos archivos quieres crear?"
            if not args.get("base_name"):
                return True, "Con que nombre base quieres que los cree? Por ejemplo: archivo_01, archivo_02..."
            return False, ""

        required = {
            "create_folder": ("folder_name", "Que nombre quieres para la carpeta?"),
            "create_file": ("file_name", "Que nombre quieres para el archivo?"),
            "read_document": ("document_name", "Que archivo quieres que lea?"),
            "move_item": ("source", "Que archivo o carpeta quieres mover?"),
            "rename_item": ("new_name", "Que nombre nuevo quieres usar?"),
            "delete_item": ("target", "Que archivo o carpeta quieres borrar?"),
            "search_files": ("query", "Que archivo quieres buscar?"),
        }
        if intent not in required:
            return False, ""

        key, question = required[intent]
        if not args.get(key):
            return True, question
        return False, ""
