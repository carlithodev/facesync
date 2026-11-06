"""
Argument extraction for the local conversational layer.

The extractor uses normalized tokens for structure and original tokens for
names, so it can understand typo-tolerant Spanish without corrupting filenames.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from core.text_normalizer import NormalizedText, NormalizedToken, TextNormalizer


class SlotExtractor:
    DETERMINERS = {
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "mi",
        "mis",
        "su",
        "sus",
        "ese",
        "esa",
        "este",
        "esta",
        "estos",
        "estas",
    }

    FILLER = {
        "por",
        "favor",
        "please",
        "pls",
        "quiero",
        "necesito",
        "necesitar",
        "ocupo",
        "crea",
        "crear",
        "creame",
        "haz",
        "genera",
        "generar",
        "preparar",
        "poner",
        "renombra",
        "renombrar",
        "renombralo",
        "renombrala",
        "mueve",
        "mover",
        "meter",
        "guardar",
        "borra",
        "elimina",
        "quitar",
        "nuevo",
        "nueva",
        "cosas",
        "cosa",
        "lo",
        "de",
        "a",
        "en",
        "del",
    }

    OBJECT_WORDS = {
        "carpeta",
        "carpetas",
        "archivo",
        "archivos",
        "documento",
        "documentos",
        "excel",
        "pdf",
        "txt",
        "directorio",
        "directorios",
        "espacio",
    }

    STOP_SEQUENCES = [
        ("dentro", "de"),
        ("adentro", "de"),
        ("en", "la", "carpeta"),
        ("con", "el", "texto"),
        ("con", "texto"),
        ("que", "diga"),
        ("para",),
        ("por", "favor"),
        ("y",),
    ]

    CREATE_FOLDER_NAME_SEQUENCES = [
        ("que", "se", "llame"),
        ("que", "se", "llama"),
        ("que", "se", "llamen"),
        ("que", "se", "nombre"),
        ("que", "se", "nombren"),
        ("con", "el", "nombre"),
        ("con", "nombre"),
        ("se", "llama"),
        ("llama",),
        ("llamada",),
        ("llamado",),
        ("nombre",),
    ]

    CREATE_FOLDER_DESTINATION_SEQUENCES = [
        ("dentro", "de", "la", "carpeta"),
        ("adentro", "de", "la", "carpeta"),
        ("en", "la", "carpeta"),
        ("dentro", "de"),
        ("adentro", "de"),
        ("en",),
    ]

    CREATE_FOLDER_DESTINATION_CUTOFF_SEQUENCES = [
        ("que", "se", "llame"),
        ("que", "se", "llamen"),
        ("que", "se", "nombre"),
        ("que", "se", "nombren"),
        ("con", "el", "nombre"),
        ("con", "nombre"),
    ]

    CREATE_FOLDER_DESTINATION_CUTOFF_WORDS = {
        "quiero",
        "necesito",
        "necesitar",
        "ocupo",
        "crea",
        "crear",
        "creame",
        "haz",
        "genera",
        "poner",
        "nueva",
        "nuevo",
        "otra",
        "otro",
        "llamada",
        "llamado",
        "para",
    }

    DESTINATION_JUNK_SEQUENCES = [
        ("adentro", "de", "la", "carpeta"),
        ("dentro", "de", "la", "carpeta"),
        ("en", "la", "carpeta"),
        ("adentro", "de"),
        ("dentro", "de"),
        ("que", "se", "llame"),
        ("que", "se", "llamen"),
        ("que", "se", "nombre"),
        ("que", "se", "nombren"),
    ]

    DESTINATION_JUNK_WORDS = {
        "carpeta",
        "carpetas",
        "llamada",
        "llamado",
    }

    OBJECT_LOCATION_SEQUENCES = [
        ("dentro", "de", "la", "carpeta"),
        ("adentro", "de", "la", "carpeta"),
        ("que", "esta", "dentro", "de"),
        ("que", "esta", "en"),
        ("ubicado", "dentro", "de"),
        ("ubicada", "dentro", "de"),
        ("ubicado", "en"),
        ("ubicada", "en"),
        ("dentro", "de"),
        ("adentro", "de"),
        ("en", "la", "carpeta"),
        ("en",),
    ]

    DESTINATION_CUTOFF_SEQUENCES = [
        ("usando",),
        ("usa",),
        ("usar",),
        ("con", "la", "columna"),
        ("con", "columna"),
        ("con",),
        ("basandote",),
        ("basado", "en"),
        ("tomando",),
        ("segun",),
        ("conforme", "a"),
        ("de", "acuerdo", "a"),
        ("como", "referencia"),
        ("como", "referencia", "facial"),
        ("para", "reconocer"),
        ("para", "clasificar"),
        ("y", "usa"),
        ("y", "usando"),
        ("donde",),
        ("cuando",),
        ("desde",),
    ]

    SOURCE_CUTOFF_SEQUENCES = DESTINATION_CUTOFF_SEQUENCES + [
        ("y",),
        ("en",),
        ("dentro", "de"),
        ("adentro", "de"),
        ("guardar",),
        ("mandar",),
        ("meter",),
        ("poner",),
        ("resultado", "en"),
        ("destino", "en"),
        ("para",),
    ]

    FILE_EXTENSIONS = {
        ".txt",
        ".pdf",
        ".docx",
        ".xlsx",
        ".xls",
        ".csv",
        ".json",
        ".xml",
        ".py",
        ".md",
        ".jpg",
        ".jpeg",
        ".png",
    }

    NAME_COLUMN_HINTS = [
        "nombre del alumno",
        "nombre completo",
        "nombre de la persona",
        "nombre del cliente",
        "nombre del participante",
        "nombre del graduado",
        "alumno",
        "nombre",
        "estudiante",
        "persona",
        "cliente",
        "participante",
        "graduado",
    ]

    REFERENCE_COLUMN_HINTS = [
        "foto referencia",
        "foto de referencia",
        "Foto referencia",
        "Foto de referencia",
        "ID Foto",
        "Codigo de foto",
        "código de foto",
        "numero de foto",
        "número de foto",
        "No Foto",
        "Numero de referencia",
        "Referencia",
        "Foto",
        "Imagen",
        "Archivo",
    ]

    NUMBER_WORDS = {
        "un": 1,
        "uno": 1,
        "una": 1,
        "dos": 2,
        "tres": 3,
        "cuatro": 4,
        "cinco": 5,
        "seis": 6,
        "siete": 7,
        "ocho": 8,
        "nueve": 9,
        "diez": 10,
        "once": 11,
        "doce": 12,
        "trece": 13,
        "catorce": 14,
        "quince": 15,
        "dieciseis": 16,
        "diecisiete": 17,
        "dieciocho": 18,
        "diecinueve": 19,
        "veinte": 20,
    }

    VAGUE_QUANTITY_WORDS = {"varias", "varios", "multiples", "muchas", "muchos"}

    @classmethod
    def extract(
        cls,
        intent: str,
        original: str,
        normalized: NormalizedText,
        context: Any = None,
    ) -> Dict[str, Any]:
        handlers = {
            "create_folder": cls._extract_create_folder,
            "create_multiple_folders": cls._extract_create_multiple_folders,
            "create_file": cls._extract_create_file,
            "create_multiple_files": cls._extract_create_multiple_files,
            "read_document": cls._extract_read_document,
            "create_folders_from_excel": cls._extract_create_folders_from_excel,
            "create_folders_from_table": cls._extract_create_folders_from_excel,
            "delete_folders_from_excel": cls._extract_create_folders_from_excel,
            "excel_to_facesync_pipeline": cls._extract_facesync_pipeline,
            "prepare_facesync_pipeline": cls._extract_facesync_pipeline,
            "run_facesync": cls._extract_run_facesync,
            "run_reference_face_matching": cls._extract_facesync_pipeline,
            "classify_photos_by_reference": cls._extract_facesync_pipeline,
            "move_item": cls._extract_move,
            "copy_item": cls._extract_move,
            "rename_item": cls._extract_rename,
            "delete_item": cls._extract_delete,
            "search_files": cls._extract_search,
            "scan_workspace": lambda *_: {},
            "analyze_or_explain": cls._extract_read_document,
        }
        handler = handlers.get(intent)
        if not handler:
            return {}
        return handler(original, normalized, context)

    # ------------------------------------------------------------------
    # General helpers
    # ------------------------------------------------------------------

    @classmethod
    def _norms(cls, normalized: NormalizedText) -> List[str]:
        return [item.norm for item in normalized.token_items]

    @classmethod
    def _find_sequence(cls, norms: Sequence[str], sequence: Sequence[str], start: int = 0) -> int:
        if not sequence:
            return -1
        limit = len(norms) - len(sequence) + 1
        for index in range(max(start, 0), max(limit, 0)):
            if tuple(norms[index : index + len(sequence)]) == tuple(sequence):
                return index
        return -1

    @classmethod
    def _find_any_sequence(
        cls,
        norms: Sequence[str],
        sequences: Iterable[Sequence[str]],
        start: int = 0,
    ) -> tuple[int, Sequence[str]]:
        best_index = -1
        best_sequence: Sequence[str] = ()
        for sequence in sequences:
            index = cls._find_sequence(norms, sequence, start=start)
            if index >= 0 and (best_index < 0 or index < best_index):
                best_index = index
                best_sequence = sequence
        return best_index, best_sequence

    @classmethod
    def _sequence_at(cls, norms: Sequence[str], index: int, sequences: Iterable[Sequence[str]]) -> bool:
        for sequence in sequences:
            if tuple(norms[index : index + len(sequence)]) == tuple(sequence):
                return True
        return False

    @classmethod
    def _collect(
        cls,
        items: Sequence[NormalizedToken],
        start: int,
        stop_sequences: Optional[Iterable[Sequence[str]]] = None,
        stop_words: Optional[set[str]] = None,
    ) -> List[NormalizedToken]:
        stop_sequences = list(stop_sequences or cls.STOP_SEQUENCES)
        stop_words = stop_words or set()
        norms = [item.norm for item in items]
        collected: List[NormalizedToken] = []
        index = max(start, 0)
        while index < len(items):
            if cls._sequence_at(norms, index, stop_sequences):
                break
            if norms[index] in stop_words:
                break
            collected.append(items[index])
            index += 1
        return collected

    @classmethod
    def _tokens_to_text(cls, items: Sequence[NormalizedToken]) -> str:
        raw = " ".join(item.clean for item in items if item.clean)
        raw = re.sub(r"\s+", " ", raw).strip()
        return raw.strip(" \t\r\n\"'`.,;:")

    @classmethod
    def _clean_candidate(cls, items: Sequence[NormalizedToken], *, allow_file: bool = False) -> str:
        selected = list(items)
        while selected and selected[0].norm in (cls.DETERMINERS | cls.FILLER | cls.OBJECT_WORDS):
            selected.pop(0)
        while selected and selected[-1].norm in (cls.DETERMINERS | cls.FILLER | cls.OBJECT_WORDS):
            selected.pop()

        if not allow_file:
            norms = [item.norm for item in selected]
            if "cada" in norms:
                return ""

        return cls._tokens_to_text(selected)

    @classmethod
    def _context_value(cls, context: Any, key: str):
        if not context:
            return None
        getter = getattr(context, "get_context", None)
        if callable(getter):
            return getter(key)
        if isinstance(context, dict):
            return context.get(key)
        return None

    @classmethod
    def _context_list(cls, context: Any, key: str) -> List[str]:
        value = cls._context_value(context, key)
        if not value:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return [str(value)]

    @classmethod
    def _resolve_available_folder(cls, value: str, context: Any) -> str:
        value = cls._strip_destination_text(value)
        if not value:
            return ""
        available = cls._context_list(context, "available_folders")
        if not available:
            return value

        value_norm = TextNormalizer.normalize_for_matching(value).strip("/\\")
        exact_matches = []
        basename_matches = []
        prefix_matches = []
        for folder in available:
            folder_text = str(folder).strip().strip("/\\")
            folder_norm = TextNormalizer.normalize_for_matching(folder_text).strip("/\\")
            folder_base = Path(folder_text).name
            base_norm = TextNormalizer.normalize_for_matching(folder_base)
            if folder_norm == value_norm or base_norm == value_norm:
                exact_matches.append(folder_text)
            elif folder_norm.startswith(value_norm + " ") or base_norm.startswith(value_norm + " "):
                prefix_matches.append(folder_text)
            elif value_norm and value_norm in {part for part in folder_norm.split("/") if part}:
                basename_matches.append(folder_text)

        matches = cls._dedupe_texts(exact_matches or basename_matches or prefix_matches)
        if not matches:
            return value
        # Nunca convertir un nombre duplicado a la primera ruta disponible.
        # WorkspaceLocationResolver debe mostrar todas las coincidencias.
        if len(matches) > 1:
            return value
        best = sorted(matches, key=lambda item: (len(Path(item).name), len(item)))[0]
        # If the match differs only in casing, preserve the user's original text
        # so that "ian" is not silently converted to "Ian".
        best_norm = TextNormalizer.normalize_for_matching(Path(best).name)
        if best_norm == value_norm:
            return value
        return best

    @staticmethod
    def _dedupe_texts(values: Iterable[str]) -> List[str]:
        result: List[str] = []
        seen = set()
        for value in values:
            text = str(value or "").strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                result.append(text)
        return result

    @classmethod
    def _resolve_reference(cls, value: str, context: Any):
        if not value or not context:
            return value
        resolver = getattr(context, "resolve_reference", None)
        if callable(resolver):
            resolved = resolver(value)
            if resolved:
                return resolved
            if cls._is_contextual(value):
                return ""
        return value

    @classmethod
    def _is_contextual(cls, value: str) -> bool:
        norm = TextNormalizer.normalize_for_matching(value)
        return any(
            phrase in norm
            for phrase in (
                "ahi",
                "alli",
                "eso",
                "esto",
                "ese",
                "esa",
                "esos",
                "esas",
                "donde estoy",
                "esa carpeta",
                "ese archivo",
                "ese documento",
                "ese excel",
                "ese pdf",
                "lo ultimo",
                "la anterior",
                "la de antes",
                "que acabas de crear",
                "que acabo de crear",
                "que acabamos de crear",
                "recien creada",
                "recien creado",
                "renombralo",
                "renombrala",
                "muevelo",
                "muevela",
                "copialo",
                "copiala",
            )
        )

    @classmethod
    def _extract_destination(cls, normalized: NormalizedText, context: Any = None) -> str:
        norms = cls._norms(normalized)
        items = normalized.token_items

        for phrase in ("workspace interno", "datos internos", "carpeta interna", "app data"):
            if phrase in normalized.normalized:
                return cls._resolve_reference(phrase, context) or cls._context_value(context, "app_data_root") or ""

        for phrase in ("carpeta principal", "project root", "raiz del proyecto", "en workspace", "en facesync", "carpeta de trabajo", "carpeta principal de facesync"):
            if phrase in normalized.normalized:
                return cls._context_value(context, "project_root") or cls._context_value(context, "workspace_actual") or ""

        for phrase in ("donde estoy", "en esta carpeta", "carpeta seleccionada", "aqui", "aca", "ahi", "alli"):
            if phrase in normalized.normalized:
                return cls._resolve_reference(phrase, context) or cls._context_value(context, "active_path") or ""

        destination_sequences = [
            ("clasificar", "en"),
            ("clasificar", "dentro", "de"),
            ("organizar", "en"),
            ("organizar", "dentro", "de"),
            ("carpeta", "correspondiente", "en"),
            ("carpetas", "correspondientes", "en"),
            ("correspondiente", "en"),
            ("guardar", "en"),
            ("guardar", "a"),
            ("mandar", "a"),
            ("mandar", "en"),
            ("meter", "en"),
            ("meter", "a"),
            ("poner", "en"),
            ("poner", "a"),
            ("hacia",),
            ("resultado", "en"),
            ("destino", "en"),
            ("guardar", "resultado", "en"),
        ]
        index, sequence = cls._find_any_sequence(norms, destination_sequences)
        if index >= 0:
            collected = cls._collect(
                items,
                index + len(sequence),
                stop_sequences=[("por", "favor"), ("y",)] + cls.DESTINATION_CUTOFF_SEQUENCES,
            )
            value = cls._clean_destination_name(collected)
            if cls._is_contextual(value):
                return cls._resolve_reference(value, context) or ""
            if value:
                return cls._resolve_available_folder(value, context)

        for sequence in (("dentro", "de", "la", "carpeta"), ("adentro", "de", "la", "carpeta"), ("dentro", "de"), ("adentro", "de"), ("en", "la", "carpeta"), ("en",)):
            index = cls._find_sequence(norms, sequence)
            if index >= 0:
                # Skip generic ("en",) when it introduces a column reference or
                # follows a method word (basandote en, basado en, tomando ...).
                if sequence == ("en",):
                    after = norms[index + 1] if index + 1 < len(norms) else ""
                    before = norms[index - 1] if index > 0 else ""
                    if after == "columna" or (index + 2 < len(norms) and norms[index + 1] == "la" and norms[index + 2] == "columna"):
                        continue
                    if before in {"basandote", "basado", "tomando", "segun"}:
                        continue
                collected = cls._collect(
                    items,
                    index + len(sequence),
                    stop_sequences=[("por", "favor"), ("y",)] + cls.DESTINATION_CUTOFF_SEQUENCES,
                )
                value = cls._clean_candidate(collected)
                value = cls._clean_destination_name(normalized.token_items[index + len(sequence): index + len(sequence) + len(collected)]) or value
                if cls._is_contextual(value):
                    return cls._resolve_reference(value, context) or ""
                return cls._resolve_available_folder(value, context)

        return ""

    @classmethod
    def _extract_file_like(cls, normalized: NormalizedText, extensions: Optional[set[str]] = None) -> str:
        extensions = extensions or cls.FILE_EXTENSIONS
        for item in normalized.token_items:
            clean = item.clean.strip(".,;:")
            suffix = Path(clean).suffix.lower()
            if suffix in extensions:
                return clean
        return ""

    @classmethod
    def _extract_after_keyword(
        cls,
        normalized: NormalizedText,
        keywords: Iterable[str],
        stop_sequences: Optional[Iterable[Sequence[str]]] = None,
    ) -> str:
        norms = cls._norms(normalized)
        for keyword in keywords:
            try:
                index = norms.index(keyword)
            except ValueError:
                continue
            collected = cls._collect(
                normalized.token_items,
                index + 1,
                stop_sequences=stop_sequences or cls.STOP_SEQUENCES,
            )
            value = cls._clean_candidate(collected, allow_file=True)
            if value:
                return value
        return ""

    # ------------------------------------------------------------------
    # Intent-specific extraction
    # ------------------------------------------------------------------

    @classmethod
    def _extract_create_folder(cls, original: str, normalized: NormalizedText, context: Any) -> Dict[str, Any]:
        folder_name = cls._extract_folder_name(normalized)
        destination = cls._extract_create_folder_destination(normalized, context)
        return {
            "folder_name": folder_name,
            "destination_folder": destination,
        }

    @classmethod
    def _extract_create_multiple_folders(cls, original: str, normalized: NormalizedText, context: Any) -> Dict[str, Any]:
        quantity, quantity_text = cls._extract_quantity(normalized)
        return {
            "quantity": quantity,
            "quantity_text": quantity_text,
            "entity_type": "folder",
            "base_name": cls._extract_folder_name(normalized),
            "destination": cls._extract_create_folder_destination(normalized, context),
        }

    @classmethod
    def _extract_create_multiple_files(cls, original: str, normalized: NormalizedText, context: Any) -> Dict[str, Any]:
        quantity, quantity_text = cls._extract_quantity(normalized)
        return {
            "quantity": quantity,
            "quantity_text": quantity_text,
            "entity_type": "file",
            "base_name": cls._extract_file_name(normalized) or cls._extract_folder_name(normalized),
            "destination": cls._extract_destination(normalized, context),
        }

    @classmethod
    def _extract_quantity(cls, normalized: NormalizedText) -> tuple[Optional[int], str]:
        for item in normalized.token_items:
            token = item.norm
            if token.isdigit():
                value = int(token)
                if value > 0:
                    return value, item.clean
            if token in cls.NUMBER_WORDS:
                return cls.NUMBER_WORDS[token], item.clean
            if token in cls.VAGUE_QUANTITY_WORDS:
                return None, item.clean
        return None, ""

    @classmethod
    def _extract_folder_name(cls, normalized: NormalizedText) -> str:
        norms = cls._norms(normalized)
        items = normalized.token_items

        index, sequence = cls._find_any_sequence(norms, cls.CREATE_FOLDER_NAME_SEQUENCES)
        if index >= 0:
            value = cls._clean_folder_name(cls._collect(items, index + len(sequence)))
            if value:
                return value

        for keyword in ("para", "de"):
            start = 0
            while True:
                try:
                    index = norms.index(keyword, start)
                except ValueError:
                    break
                previous = norms[index - 1] if index > 0 else ""
                if keyword == "de" and previous in {"dentro", "adentro"}:
                    start = index + 1
                    continue
                collected = cls._collect(items, index + 1)
                value = cls._clean_folder_name(collected)
                if value:
                    return value
                start = index + 1

        for object_word in ("carpeta", "espacio"):
            if object_word in norms:
                index = norms.index(object_word)
                collected = cls._collect(items, index + 1)
                value = cls._clean_folder_name(collected)
                if value:
                    return value

        for action in ("creame", "crea", "haz", "genera", "preparar", "poner"):
            if action in norms:
                index = norms.index(action)
                collected = cls._collect(items, index + 1)
                value = cls._clean_folder_name(collected)
                if value:
                    return value

        return ""

    @classmethod
    def _extract_create_folder_destination(cls, normalized: NormalizedText, context: Any) -> str:
        norms = cls._norms(normalized)
        items = normalized.token_items

        for phrase in ("workspace interno", "datos internos", "carpeta interna", "app data"):
            if phrase in normalized.normalized:
                return cls._resolve_reference(phrase, context) or cls._context_value(context, "app_data_root") or ""

        for phrase in ("carpeta principal", "project root", "raiz del proyecto", "en workspace", "en facesync", "carpeta de trabajo", "carpeta principal de facesync"):
            if phrase in normalized.normalized:
                return cls._context_value(context, "project_root") or cls._context_value(context, "workspace_actual") or ""

        for phrase in ("donde estoy", "en esta carpeta", "carpeta seleccionada", "aqui", "aca", "ahi", "alli"):
            if phrase in normalized.normalized:
                return cls._resolve_reference(phrase, context) or cls._context_value(context, "active_path") or ""

        index, sequence = cls._find_any_sequence(norms, cls.CREATE_FOLDER_DESTINATION_SEQUENCES)
        if index < 0:
            return ""

        collected: List[NormalizedToken] = []
        cursor = index + len(sequence)
        while cursor < len(items):
            if collected and cls._sequence_at(norms, cursor, cls.CREATE_FOLDER_DESTINATION_CUTOFF_SEQUENCES):
                break
            if collected and cls._sequence_at(norms, cursor, cls.DESTINATION_CUTOFF_SEQUENCES):
                break
            if collected and norms[cursor] in cls.CREATE_FOLDER_DESTINATION_CUTOFF_WORDS:
                break
            if cls._sequence_at(norms, cursor, [("por", "favor"), ("y",)]):
                break
            collected.append(items[cursor])
            cursor += 1

        value = cls._clean_destination_name(collected)
        if cls._is_contextual(value):
            return cls._resolve_reference(value, context) or ""
        return cls._resolve_available_folder(value, context)

    @classmethod
    def _clean_folder_name(cls, items: Sequence[NormalizedToken]) -> str:
        selected = list(items)

        while selected and cls._sequence_at([item.norm for item in selected], 0, cls.CREATE_FOLDER_NAME_SEQUENCES):
            matched = next(
                sequence
                for sequence in cls.CREATE_FOLDER_NAME_SEQUENCES
                if tuple([item.norm for item in selected[: len(sequence)]]) == tuple(sequence)
            )
            selected = selected[len(matched):]

        value = cls._clean_candidate(selected)
        return cls._strip_folder_name_text(value)

    @classmethod
    def _clean_destination_name(cls, items: Sequence[NormalizedToken]) -> str:
        selected = list(items)
        while selected:
            norms = [item.norm for item in selected]
            index, sequence = cls._find_any_sequence(norms, cls.DESTINATION_JUNK_SEQUENCES)
            if index == 0:
                selected = selected[len(sequence):]
                continue
            if selected[0].norm in (cls.DETERMINERS | cls.DESTINATION_JUNK_WORDS):
                selected.pop(0)
                continue
            break

        while selected and selected[-1].norm in (cls.DETERMINERS | cls.DESTINATION_JUNK_WORDS):
            selected.pop()
        return cls._strip_destination_text(cls._tokens_to_text(selected))

    @staticmethod
    def _strip_destination_text(value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        junk_patterns = [
            r"^(?:adentro|dentro)\s+de\s+",
            r"^en\s+la\s+carpeta\s+",
            r"^(?:la\s+)?carpeta\s+",
            r"^(?:que\s+se\s+llame|que\s+se\s+llama|que\s+se\s+llamen|que\s+se\s+nombre|que\s+se\s+nombren)\s+",
            r"^(?:se\s+llama|llama|llamada|llamado)\s+",
            r"\s+(?:que\s+se\s+llame|que\s+se\s+llama|que\s+se\s+llamen|que\s+se\s+nombre|que\s+se\s+nombren)$",
            r"\s+(?:se\s+llama|llama|llamada|llamado)$",
            r"\s+(?:la\s+)?carpeta$",
        ]
        changed = True
        while changed:
            before = text
            for pattern in junk_patterns:
                text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
            changed = text != before
        return text.strip(" \t\r\n\"'`.,;:")

    @staticmethod
    def _strip_folder_name_text(value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        junk_patterns = [
            r"^(?:una\s+)?carpeta\s+",
            r"^(?:nueva|nuevo)\s+",
            r"^(?:guardar\s+)?lo\s+de\s+",
            r"^(?:meter\s+)?lo\s+de\s+",
            r"^(?:guardar\s+)?cosas\s+de\s+",
            r"^donde\s+meter\s+lo\s+de\s+",
            r"^(?:el\s+|la\s+)?(?:alumno|alumna|persona|estudiante)\s+",
            r"^(?:que\s+se\s+llame|que\s+se\s+llama|que\s+se\s+nombre)\s+",
            r"^(?:se\s+llama|llama|llamada|llamado)\s+",
            r"^(?:con\s+nombre|con\s+el\s+nombre)\s+",
            r"^(?:adentro|dentro)\s+(?:de\s+)?",
            r"^en\s+la\s+carpeta\s+",
            r"\s+por\s+favor$",
            r"\s+(?:adentro|dentro)\s+de\s+.+$",
            r"\s+en\s+la\s+carpeta\s+.+$",
        ]
        changed = True
        while changed:
            before = text
            for pattern in junk_patterns:
                text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
            changed = text != before
        return text.strip(" \t\r\n\"'`.,;:")

    @classmethod
    def _extract_create_file(cls, original: str, normalized: NormalizedText, context: Any) -> Dict[str, Any]:
        destination = cls._extract_destination(normalized, context)
        content = cls._extract_content(normalized)
        file_name = cls._extract_file_name(normalized)

        if file_name and "." not in Path(file_name).name and ("txt" in normalized.tokens or "texto" in normalized.tokens):
            file_name = f"{file_name}.txt"

        return {
            "file_name": file_name,
            "content": content,
            "destination_folder": destination,
        }

    @classmethod
    def _extract_content(cls, normalized: NormalizedText) -> str:
        norms = cls._norms(normalized)
        items = normalized.token_items
        for sequence in (("con", "el", "texto"), ("con", "texto"), ("que", "diga"), ("contenido",)):
            index = cls._find_sequence(norms, sequence)
            if index >= 0:
                collected = cls._collect(items, index + len(sequence), stop_sequences=[("por", "favor")])
                return cls._tokens_to_text(collected)
        return ""

    @classmethod
    def _extract_file_name(cls, normalized: NormalizedText) -> str:
        file_like = cls._extract_file_like(normalized)
        if file_like:
            return file_like

        norms = cls._norms(normalized)
        items = normalized.token_items
        connector_sequences = [
            ("llamado",),
            ("llamada",),
            ("con", "el", "nombre"),
            ("con", "nombre"),
            ("para",),
        ]
        index, sequence = cls._find_any_sequence(norms, connector_sequences)
        if index >= 0:
            value = cls._clean_candidate(cls._collect(items, index + len(sequence)), allow_file=True)
            if value:
                return value

        for object_word in ("archivo", "txt"):
            if object_word in norms:
                index = norms.index(object_word)
                value = cls._clean_candidate(cls._collect(items, index + 1), allow_file=True)
                if value:
                    return value
        return ""

    @classmethod
    def _extract_read_document(cls, original: str, normalized: NormalizedText, context: Any) -> Dict[str, Any]:
        document_name = cls._extract_file_like(normalized)
        document_type = ""
        for doc_type in ("excel", "pdf", "txt", "csv", "json", "docx"):
            if doc_type in normalized.tokens:
                document_type = doc_type
                break

        if not document_name:
            if "ese excel" in normalized.normalized:
                document_name = cls._resolve_reference("ese excel", context) or ""
            elif "ese pdf" in normalized.normalized:
                document_name = cls._resolve_reference("ese pdf", context) or ""
            elif "ese documento" in normalized.normalized or "ese archivo" in normalized.normalized:
                document_name = cls._resolve_reference("ese documento", context) or ""

        if not document_name:
            for keyword in ("de", "dice", "lee", "abre", "muestra", "revisa", "tiene"):
                document_name = cls._extract_after_keyword(normalized, [keyword])
                if document_name:
                    break

        document_norm = TextNormalizer.normalize_for_matching(document_name)
        if document_norm in {
            "contenido",
            "contenido del txt",
            "contenido txt",
            "txt",
            "hoja de calculo",
            "hoja calculo",
            "calculo",
            "excel",
            "pdf",
        }:
            document_name = ""

        return {
            "document_name": document_name,
            "document_type": document_type,
        }

    @classmethod
    def _extract_create_folders_from_excel(cls, original: str, normalized: NormalizedText, context: Any) -> Dict[str, Any]:
        excel_name = cls._extract_excel_hint(normalized, context)
        name_column = cls._extract_column_hint(normalized, cls.NAME_COLUMN_HINTS)
        name_column = cls._resolve_available_column(name_column, context, role="name", normalized=normalized)
        return {
            "excel_name": excel_name,
            "table_path": excel_name,
            "destination_folder": cls._extract_destination(normalized, context),
            "column_name": name_column,
            "name_column": name_column,
        }

    @classmethod
    def _extract_source_folders(cls, original: str, context: Any) -> List[str]:
        """Detecta 2+ carpetas origen en frases como
        'usando FOTOS, FOTOS 2 y FOTOS 3'. Devuelve [] si no hay al menos 2
        claras, de modo que el caso de una sola carpeta no cambia."""
        text = str(original or "")
        low = TextNormalizer.strip_accents(text).lower()
        # Triggers ESTRICTOS: solo frases que claramente enumeran carpetas origen.
        # (Se quitaron " con ", "carpetas ", "origen " por ser demasiado genericos
        #  y romper la comprension de comandos normales de una sola carpeta.)
        triggers = ("con las carpetas ", "con la carpeta ", "usando ", "usa ",
                    "las fotos de ", "fotos de ")
        start = -1
        for trg in triggers:
            i = low.find(trg)
            if i >= 0:
                start = i + len(trg)
                break
        if start < 0:
            return []
        segment = text[start:]
        seg_low = TextNormalizer.strip_accents(segment).lower()
        for cut in (" en ", " hacia ", " destino", " guardar", " resultado",
                    " mandar", " mete", " como destino", " a la carpeta "):
            ci = seg_low.find(cut)
            if ci >= 0:
                segment = segment[:ci]
                seg_low = seg_low[:ci]
        parts = re.split(r",|\sy\s|\se\s", segment, flags=re.IGNORECASE)
        folders: List[str] = []
        for piece in parts:
            name = cls._clean_source_folder_piece(piece)
            if name:
                folders.append(name)
        seen: set = set()
        uniq: List[str] = []
        for f in folders:
            key = f.lower()
            if key not in seen:
                seen.add(key)
                uniq.append(f)
        if len(uniq) >= 2:
            return uniq
        # Caso "usa las tres carpetas ARTURO FRANK RUBEN": nombres separados por
        # ESPACIOS (sin comas/'y'). Solo cuando hay palabra de cantidad + "carpetas"
        # (señal explícita de varias) y los tokens NO llevan dígitos (evita partir
        # nombres con número como "FOTOS 2").
        seg_norm = TextNormalizer.strip_accents(segment).lower()
        has_count = ("carpeta" in seg_norm) and any(
            f" {cw} " in f" {seg_norm} " for cw in ("dos", "tres", "cuatro", "cinco", "seis", "varias"))
        if has_count:
            base = cls._clean_source_folder_piece(segment)
            toks = base.split()
            if len(toks) >= 2 and not any(any(ch.isdigit() for ch in t) for t in toks):
                cand, seen2 = [], set()
                _stop = {"tres", "dos", "cuatro", "cinco", "seis", "varias",
                         "carpetas", "carpeta", "las", "los", "todas", "todos"}
                for t in toks:
                    nm = cls._clean_source_folder_piece(t)
                    if nm and nm.lower() not in seen2 and nm.lower() not in _stop:
                        seen2.add(nm.lower())
                        cand.append(nm)
                if len(cand) >= 2:
                    return cand
        return []

    @staticmethod
    def _clean_source_folder_piece(piece: str) -> str:
        s = str(piece or "").strip().strip(".,;:¿?¡!").strip()
        low = TextNormalizer.strip_accents(s).lower()
        prefixes = ("las carpetas ", "la carpeta ", "carpetas ", "carpeta ",
                    "las fotos de ", "fotos de ", "los ", "las ", "la ", "el ")
        changed = True
        while changed:
            changed = False
            for f in prefixes:
                if low.startswith(f):
                    s = s[len(f):].strip()
                    low = TextNormalizer.strip_accents(s).lower()
                    changed = True
        for f in (" como origen", " de origen", " como fuente", " origen"):
            if low.endswith(f):
                s = s[: -len(f)].strip()
                low = TextNormalizer.strip_accents(s).lower()
        s = s.strip().strip(".,;:").strip()
        low = TextNormalizer.strip_accents(s).lower()
        # Descartar conectores/comandos vacios — NUNCA un nombre real de
        # carpeta (p.ej. "FOTOS" es una carpeta valida, no relleno).
        if low in ("", "y", "e", "con", "clasifica", "clasificar", "identifica"):
            return ""
        # No son carpetas: archivos de tabla o fragmentos de oracion.
        if low.endswith((".xlsx", ".xls", ".csv")):
            return ""
        words = set(low.split())
        if words & {"estan", "dentro", "donde", "para", "guardar", "guarda",
                    "resultado", "destino", "mete", "mandar"}:
            return ""
        return s

    @classmethod
    def _extract_facesync_pipeline(cls, original: str, normalized: NormalizedText, context: Any) -> Dict[str, Any]:
        destination = cls._extract_destination(normalized, context)
        excel_name = cls._extract_excel_hint(normalized, context)
        name_column = cls._extract_column_hint(normalized, cls.NAME_COLUMN_HINTS)
        reference_column = cls._extract_reference_column_hint(normalized)
        name_column, reference_column = cls._disambiguate_pipeline_columns(name_column, reference_column)
        name_column = cls._resolve_available_column(name_column, context, role="name", normalized=normalized)
        reference_column = cls._resolve_available_column(reference_column, context, role="reference", normalized=normalized)

        source_folders = cls._extract_source_folders(original, context)
        single_source = cls._extract_photo_folder_hint(normalized, context)
        return {
            "excel_name": excel_name,
            "table_path": excel_name,
            "source_folder": source_folders[0] if source_folders else single_source,
            "source_folders": source_folders,
            "destination_folder": destination,
            "name_column": name_column,
            "reference_column": reference_column,
        }

    @classmethod
    def _extract_run_facesync(cls, original: str, normalized: NormalizedText, context: Any) -> Dict[str, Any]:
        excel_name = cls._extract_excel_hint(normalized, context)
        name_column = cls._extract_column_hint(normalized, cls.NAME_COLUMN_HINTS)
        reference_column = cls._extract_reference_column_hint(normalized)
        name_column, reference_column = cls._disambiguate_pipeline_columns(name_column, reference_column)
        name_column = cls._resolve_available_column(name_column, context, role="name", normalized=normalized)
        reference_column = cls._resolve_available_column(reference_column, context, role="reference", normalized=normalized)
        # Multi-origen: igual que el pipeline, detecta varias carpetas origen
        # ("usando A, B y C") para que el chat no se quede solo con la primera.
        source_folders = cls._extract_source_folders(original, context)
        single_source = cls._extract_photo_folder_hint(normalized, context)
        return {
            "excel_name": excel_name,
            "table_path": excel_name,
            "source_folder": source_folders[0] if source_folders else single_source,
            "source_folders": source_folders,
            "destination_folder": cls._extract_destination(normalized, context),
            "name_column": name_column,
            "reference_column": reference_column,
        }

    @staticmethod
    def _disambiguate_pipeline_columns(name_column: str, reference_column: str) -> tuple[str, str]:
        if not name_column or not reference_column:
            return name_column, reference_column
        name_norm = TextNormalizer.normalize_for_matching(name_column)
        ref_norm = TextNormalizer.normalize_for_matching(reference_column)
        if name_norm != ref_norm:
            return name_column, reference_column
        if any(token in ref_norm for token in ("foto", "referencia", "imagen", "archivo", "codigo", "numero", "id")):
            return "", reference_column
        if any(token in ref_norm for token in ("nombre", "alumno", "persona", "cliente", "participante", "graduado")):
            return name_column, ""
        return name_column, reference_column

    @classmethod
    def _resolve_available_column(
        cls,
        value: str,
        context: Any,
        *,
        role: str,
        normalized: NormalizedText,
    ) -> str:
        columns = cls._context_list(context, "available_columns")
        if not columns:
            return value

        matched = cls._match_column_value(value, columns)
        if matched:
            return matched

        role_tokens = {
            "name": {"nombre", "alumno", "estudiante", "persona", "cliente", "participante", "graduado"},
            "reference": {"foto", "referencia", "imagen", "archivo", "codigo", "numero", "id", "base"},
        }.get(role, set())
        text_tokens = set(normalized.tokens)
        text_norm = normalized.normalized
        scored: List[tuple[int, str]] = []
        for column in columns:
            column_norm = TextNormalizer.normalize_for_matching(column)
            column_tokens = set(column_norm.split())
            overlap = column_tokens & text_tokens
            role_overlap = column_tokens & role_tokens
            score = 0
            if column_norm and column_norm in text_norm:
                score += 80
            if overlap:
                score += len(overlap) * 20
            if role_overlap and overlap:
                score += 35
            if score:
                scored.append((score, column))
        if not scored:
            return value
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return value
        return scored[0][1]

    @classmethod
    def _match_column_value(cls, value: str, columns: List[str]) -> str:
        raw = re.sub(r"\s+", " ", str(value or "")).strip().strip(" \t\r\n\"'`.,;:!?")
        if not raw:
            return ""
        raw_norm = TextNormalizer.normalize_for_matching(raw)
        raw_tokens = set(raw_norm.split())
        scored: List[tuple[int, str]] = []
        for column in columns:
            column_norm = TextNormalizer.normalize_for_matching(column)
            column_tokens = set(column_norm.split())
            score = 0
            if raw_norm == column_norm:
                score += 100
            elif raw_norm and raw_norm in column_norm:
                score += 80
            elif column_norm and column_norm in raw_norm:
                score += 70
            overlap = raw_tokens & column_tokens
            if overlap:
                score += len(overlap) * 25
            if raw_tokens and raw_tokens.issubset(column_tokens):
                score += 35
            if score:
                scored.append((score, column))
        if not scored:
            return ""
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return ""
        return scored[0][1]

    @classmethod
    def _extract_excel_hint(cls, normalized: NormalizedText, context: Any) -> str:
        file_like = cls._extract_file_like(normalized, {".xlsx", ".xls", ".csv"})
        if file_like:
            return file_like

        if "ese excel" in normalized.normalized:
            return cls._resolve_reference("ese excel", context) or ""

        norms = cls._norms(normalized)
        items = normalized.token_items
        for keyword in ("excel", "csv", "lista", "tabla"):
            try:
                index = norms.index(keyword)
            except ValueError:
                continue
            collected = cls._collect(
                items,
                index + 1,
                stop_sequences=[
                    ("usa",),
                    ("usar",),
                    ("toma",),
                    ("tomar",),
                    ("acomoda",),
                    ("acomodar",),
                    ("organizar",),
                    ("clasificar",),
                    ("separar",),
                    ("crea",),
                    ("crear",),
                    ("y",),
                    ("para",),
                ],
            )
            value = cls._clean_candidate(collected, allow_file=True)
            value_norm = TextNormalizer.normalize_for_matching(value)
            if value_norm and value_norm not in {
                "de alumno",
                "de alumnos",
                "alumno",
                "alumnos",
                "del salon",
                "salon",
                "de personas",
                "personas",
                "de clientes",
                "clientes",
                "de super heroes",
                "super heroes",
            }:
                return value

        return cls._context_value(context, "ultimo_excel_leido") or cls._context_value(context, "last_excel") or ""

    @classmethod
    def _extract_column_hint(cls, normalized: NormalizedText, hints: Sequence[str]) -> str:
        norms = cls._norms(normalized)
        if "columna" in norms:
            index = norms.index("columna")
            value = cls._clean_candidate(
                cls._collect(
                    normalized.token_items,
                    index + 1,
                    stop_sequences=[
                        ("dentro", "de"),
                        ("adentro", "de"),
                        ("en", "la", "carpeta"),
                        ("en",),
                        ("usando",),
                        ("usa",),
                        ("usar",),
                        ("para",),
                        ("y",),
                        ("con",),
                        ("como",),
                    ],
                ),
                allow_file=True,
            )
            if value:
                return value

        norm_text = normalized.normalized
        for hint in hints:
            if TextNormalizer.normalize_for_matching(hint) in norm_text:
                return hint
        return ""

    @classmethod
    def _extract_reference_column_hint(cls, normalized: NormalizedText) -> str:
        norms = cls._norms(normalized)
        items = normalized.token_items
        reference_sequences = [
            ("usando", "la", "columna"),
            ("usar", "la", "columna"),
            ("usa", "la", "columna"),
            ("con", "la", "columna"),
            ("con", "columna"),
            ("segun", "la", "columna"),
            ("segun", "columna"),
            ("basandote", "en", "la", "columna"),
            ("basandote", "en"),
            ("basado", "en", "la", "columna"),
            ("basado", "en"),
            ("tomando", "la", "columna"),
            ("tomando",),
            ("conforme", "a", "la", "columna"),
            ("de", "acuerdo", "a", "la", "columna"),
        ]
        stop_sequences = [
            ("como", "referencia"),
            ("como", "referencia", "facial"),
            ("para",),
            ("y",),
            ("en",),
            ("dentro", "de"),
            ("adentro", "de"),
            ("desde",),
            ("con",),
            ("usando",),
        ]
        for sequence in reference_sequences:
            index = cls._find_sequence(norms, sequence)
            if index < 0:
                continue
            value = cls._clean_candidate(
                cls._collect(items, index + len(sequence), stop_sequences=stop_sequences),
                allow_file=True,
            )
            value = cls._strip_reference_column_text(value)
            if value and Path(value).suffix.lower() in {".xlsx", ".xls", ".csv"}:
                continue
            if TextNormalizer.normalize_for_matching(value).startswith(("lista ", "excel ", "csv ")):
                continue
            if value:
                return cls._canonical_reference_hint(value)

        norm_text = normalized.normalized
        if "referencia del archivo" in norm_text or "referencia archivo" in norm_text:
            return "Archivo"
        for pattern in (
            r"usando\s+(.+?)\s+como\s+referencia",
            r"usa\s+(.+?)\s+como\s+referencia",
            r"con\s+(.+?)\s+como\s+referencia",
        ):
            match = re.search(pattern, norm_text)
            if match:
                value = cls._strip_reference_column_text(match.group(1))
                if value:
                    return cls._canonical_reference_hint(value)

        fallback = cls._extract_column_hint(normalized, cls.REFERENCE_COLUMN_HINTS)
        return cls._canonical_reference_hint(fallback) if fallback else ""

    @classmethod
    def _canonical_reference_hint(cls, value: str) -> str:
        value = cls._strip_reference_column_text(value)
        value_norm = TextNormalizer.normalize_for_matching(value)
        preferred = {
            "foto referencia": "Foto referencia",
            "foto de referencia": "Foto de referencia",
            "id foto": "ID Foto",
            "codigo de foto": "Codigo de foto",
            "numero de foto": "Numero de foto",
            "no foto": "No Foto",
            "numero de referencia": "Numero de referencia",
            "referencia": "Referencia",
            "foto": "Foto",
            "imagen": "Imagen",
            "archivo": "Archivo",
        }
        if value_norm in preferred:
            return preferred[value_norm]
        for hint in cls.REFERENCE_COLUMN_HINTS:
            if TextNormalizer.normalize_for_matching(hint) == value_norm:
                return hint
        return value

    @staticmethod
    def _strip_reference_column_text(value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n\"'`.,;:")
        text = re.sub(r"^(?:la\s+)?columna\s+", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s+como\s+referencia(?:\s+facial)?$", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s+de\s+referencia$", " referencia", text, flags=re.IGNORECASE).strip()
        return text

    @classmethod
    def _extract_photo_folder_hint(cls, normalized: NormalizedText, context: Any) -> str:
        if "esa carpeta" in normalized.normalized and any(token in normalized.tokens for token in ("foto", "fotos", "imagen", "imagenes")):
            return cls._resolve_reference("esa carpeta", context) or ""

        norms = cls._norms(normalized)
        priority_source_sequences = [
            ("fotos", "de"),
            ("imagenes", "de"),
            ("tomar", "fotos", "de"),
            ("tomar", "las", "fotos", "de"),
            ("toma", "fotos", "de"),
            ("toma", "las", "fotos", "de"),
            ("usar", "fotos", "de"),
            ("usa", "fotos", "de"),
            ("carpeta", "maestra"),
            ("carpeta", "origen"),
            ("origen",),
            ("desde",),
            ("carpeta",),
        ]
        for sequence in priority_source_sequences:
            index = cls._find_sequence(norms, sequence)
            if index < 0:
                continue
            collected = cls._collect(
                normalized.token_items,
                index + len(sequence),
                stop_sequences=cls.SOURCE_CUTOFF_SEQUENCES,
            )
            value = cls._clean_photo_folder_candidate(collected)
            if value:
                return cls._resolve_available_folder(value, context)
        source_sequences = [
            ("fotos", "estan", "en"),
            ("fotos", "estan", "dentro", "de"),
            ("fotos", "de"),
            ("imagenes", "de"),
            ("imagenes", "estan", "en"),
            ("imagenes", "estan", "dentro", "de"),
            ("tomar", "fotos", "de"),
            ("tomar", "las", "fotos", "de"),
            ("toma", "fotos", "de"),
            ("toma", "las", "fotos", "de"),
            ("usar", "fotos", "de"),
            ("usa", "fotos", "de"),
            ("carpeta", "de", "fotos"),
            ("carpeta", "fotos"),
            ("carpeta", "maestra"),
            ("carpeta", "origen"),
            ("origen",),
            ("desde",),
            ("carpeta",),
        ]
        for sequence in source_sequences:
            index = cls._find_sequence(norms, sequence)
            if index >= 0:
                collected = cls._collect(
                    normalized.token_items,
                    index + len(sequence),
                    stop_sequences=[("y",), ("guardar",), ("mandar",), ("meter",), ("resultado", "en"), ("destino", "en"), ("usando",), ("con",), ("segun",), ("según",)],
                )
                value = cls._clean_photo_folder_candidate(collected)
                if value:
                    return value

        if any(token in normalized.tokens for token in ("foto", "fotos", "imagen", "imagenes")):
            return cls._context_value(context, "ultima_carpeta_fotos") or cls._context_value(context, "source_folder") or ""
        return cls._context_value(context, "ultima_carpeta_fotos") or cls._context_value(context, "source_folder") or ""

    @classmethod
    def _clean_photo_folder_candidate(cls, items: Sequence[NormalizedToken]) -> str:
        value = cls._clean_candidate(items, allow_file=True)
        value_norm = TextNormalizer.normalize_for_matching(value)
        if value_norm in {
            "",
            "alumnos",
            "alumno",
            "sus fotos",
            "las fotos",
            "la carpeta maestra",
            "carpeta maestra",
        }:
            return ""
        return value

    @classmethod
    def _extract_move(cls, original: str, normalized: NormalizedText, context: Any) -> Dict[str, Any]:
        norms = cls._norms(normalized)
        items = normalized.token_items
        verb_index = cls._find_any_sequence(
            norms,
            [
                ("mueve",), ("mover",), ("meter",), ("poner",),
                ("traslada",), ("trasladar",), ("pasa",), ("pasar",),
                ("manda",), ("mandar",), ("lleva",), ("llevar",),
                ("acomoda",), ("acomodar",),
                ("guardar",), ("copia",), ("copiar",), ("duplica",),
                ("duplicar",), ("repite",),
            ],
        )[0]
        source = ""
        destination = ""

        if verb_index >= 0:
            # "de X a Y" y "que esta en X hacia Y": primero separa el
            # destino explicito; los conectores internos quedan en el origen.
            dest_index, dest_sequence = cls._find_any_sequence(
                norms,
                [("hacia",), ("hasta",), ("a",), ("para",)],
                start=verb_index + 1,
            )
            if dest_index < 0:
                dest_index, dest_sequence = cls._find_any_sequence(
                    norms,
                    [("dentro", "de"), ("adentro", "de"), ("en",), ("ahi",), ("alli",)],
                    start=verb_index + 1,
                )
            if dest_index >= 0:
                source_items = items[verb_index + 1 : dest_index]
                raw_source = cls._tokens_to_text(source_items)
                source = cls._qualified_object(source_items, context, allow_de=True)
                if cls._is_contextual(raw_source):
                    source = cls._resolve_reference(raw_source, context) or source
                if dest_sequence in (("ahi",), ("alli",)):
                    destination = cls._resolve_reference("ahi", context) or ""
                else:
                    destination = cls._clean_candidate(cls._collect(items, dest_index + len(dest_sequence)), allow_file=True)
            else:
                source_items = cls._collect(items, verb_index + 1)
                raw_source = cls._tokens_to_text(source_items)
                source = cls._qualified_object(source_items, context, allow_de=True)
                if cls._is_contextual(raw_source):
                    source = cls._resolve_reference(raw_source, context) or source

        if cls._is_contextual(source):
            source = cls._resolve_reference(source, context) or ""
        if cls._is_contextual(destination):
            destination = cls._resolve_reference(destination, context) or ""

        return {"source": source, "destination": destination}

    @classmethod
    def _qualified_object(
        cls,
        items: Sequence[NormalizedToken],
        context: Any,
        *,
        allow_de: bool = False,
    ) -> str:
        """Convierte "Frank dentro de 502m" en "502m/Frank".

        Conserva por separado el nombre y su carpeta padre, evitando que el
        resolvedor pierda el calificador que distingue nombres duplicados.
        """
        selected = list(items)
        while selected and selected[0].norm in (cls.DETERMINERS | cls.FILLER | cls.OBJECT_WORDS):
            selected.pop(0)
        norms = [item.norm for item in selected]
        sequences = list(cls.OBJECT_LOCATION_SEQUENCES)
        if allow_de:
            sequences.append(("de",))
        index, sequence = cls._find_any_sequence(norms, sequences)
        if index >= 0:
            child_items = selected[:index]
            parent_items = cls._collect(
                selected,
                index + len(sequence),
                stop_sequences=[("por", "favor"), ("y",)],
            )
            child = cls._clean_candidate(child_items, allow_file=True)
            parent = cls._clean_candidate(parent_items, allow_file=True)
            if child and parent:
                return cls._join_reference(parent, child)

        raw = cls._tokens_to_text(selected)
        if cls._is_contextual(raw):
            resolved = cls._resolve_reference(raw, context)
            if resolved:
                return resolved
        return cls._clean_candidate(selected, allow_file=True)

    @staticmethod
    def _join_reference(parent: str, child: str) -> str:
        parent = str(parent or "").strip().rstrip("/\\")
        child = str(child or "").strip().strip("/\\")
        return f"{parent}/{child}" if parent and child else child or parent

    @classmethod
    def _extract_rename(cls, original: str, normalized: NormalizedText, context: Any) -> Dict[str, Any]:
        norms = cls._norms(normalized)
        items = normalized.token_items
        new_name = ""
        target = ""

        a_index = cls._find_sequence(norms, ("a",))
        rename_index, _ = cls._find_any_sequence(
            norms,
            [("renombra",), ("renombrar",), ("renombralo",), ("renombrala",)],
        )
        if rename_index >= 0 and a_index > rename_index:
            target_items = items[rename_index + 1 : a_index]
            raw_target = cls._tokens_to_text(target_items)
            target = cls._qualified_object(target_items, context, allow_de=True)
            if cls._is_contextual(raw_target):
                target = cls._resolve_reference(raw_target, context) or target
            new_name = cls._clean_candidate(cls._collect(items, a_index + 1), allow_file=True)
        elif a_index >= 0:
            before_norms = norms[:a_index]
            after_value = cls._clean_candidate(cls._collect(items, a_index + 1), allow_file=True)
            if "nombre" in before_norms and any(word in before_norms for word in ("otro", "otra")):
                target = after_value
                new_name = ""
            else:
                new_name = after_value
                de_index = cls._find_sequence(before_norms, ("de",))
                if "nombre" in before_norms and de_index >= 0:
                    before = cls._clean_candidate(items[de_index + 1 : a_index], allow_file=True)
                else:
                    before = cls._clean_candidate(items[:a_index], allow_file=True)
                target = before

        if any(token in normalized.tokens for token in ("renombralo", "renombrala")) or not target:
            target = cls._resolve_reference(normalized.normalized, context) or target

        if any(token in normalized.tokens for token in ("renombralo", "renombrala", "eso", "esa", "ese", "ultimo", "ultima")):
            active_path = cls._context_value(context, "active_path")
            workspace = cls._context_value(context, "workspace_actual")
            if target and (str(target) == str(active_path) or str(target) == str(workspace)):
                target = ""
            if TextNormalizer.normalize_for_matching(target) in {"ultimo", "ultima", "lo ultimo"}:
                target = ""

        for action in ("renombra", "renombrar", "renombralo", "renombrala", "cambia", "poner"):
            if target.startswith(action):
                target = target.replace(action, "", 1).strip()

        if cls._is_contextual(target):
            target = cls._resolve_reference(target, context) or ""

        return {"target": target, "new_name": new_name}

    @classmethod
    def _extract_delete(cls, original: str, normalized: NormalizedText, context: Any) -> Dict[str, Any]:
        norms = cls._norms(normalized)
        items = normalized.token_items
        verb_index, _ = cls._find_any_sequence(
            norms,
            [
                ("elimina",), ("eliminar",), ("borra",), ("borrar",),
                ("quita",), ("quitar",), ("remueve",), ("remover",),
                ("deshazte",),
            ],
        )
        target_items = list(items[verb_index + 1 :]) if verb_index >= 0 else []
        while target_items and target_items[-1].norm in {"todo", "recursivo", "forzar"}:
            target_items.pop()
        if len(target_items) >= 2 and [item.norm for item in target_items[-2:]] == ["con", "todo"]:
            target_items = target_items[:-2]
        target = cls._qualified_object(target_items, context, allow_de=True)
        target_expression = target
        target = re.sub(r"\s+con\s+todo$", "", target, flags=re.IGNORECASE).strip()
        if cls._is_contextual(target):
            target = cls._resolve_reference(target, context) or ""
        recursive = any(token in normalized.tokens for token in ("recursivo", "forzar", "todo")) or "con todo" in normalized.normalized
        ambiguous = cls._is_contextual(target_expression) or any(
            token in normalized.tokens for token in ("eso", "esto", "esos", "esas", "ultimo", "ultima")
        )
        return {"target": target, "recursive": recursive, "ambiguous": ambiguous, "target_expression": target_expression}

    @classmethod
    def _extract_search(cls, original: str, normalized: NormalizedText, context: Any) -> Dict[str, Any]:
        query = cls._extract_after_keyword(normalized, ["busca", "encuentra", "localiza", "esta"])
        if not query and "donde esta" in normalized.normalized:
            query = cls._extract_after_keyword(normalized, ["esta"])
        extension = ""
        query_norm = TextNormalizer.normalize_for_matching(query)
        if query_norm in {"pdf", "excel", "xlsx", "xls", "txt", "csv", "docx"}:
            extension = ".xlsx" if query_norm in {"excel", "xlsx"} else f".{query_norm}"
            query = "*"
        return {"query": query or "*", "extension": extension}
