"""
Conversational guard layer for FaceSync AI.

DialogueManager classifies social messages, confirmations, cancellations,
short ambiguous text, and answers to pending questions before the local router
or OpenAI fallback sees the message.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from core.slot_extractor import SlotExtractor
from core.text_normalizer import NormalizedText, TextNormalizer


class DialogueManager:
    GREETING_PHRASES = {
        "hola",
        "holaa",
        "buenas",
        "buenos dias",
        "buen dia",
        "buenas tardes",
        "buenas noches",
        "que onda",
        "hey",
        "hello",
    }
    THANKS_PHRASES = {
        "gracias",
        "ok gracias",
        "perfecto gracias",
        "muchas gracias",
        "mil gracias",
    }
    FAREWELL_PHRASES = {
        "adios",
        "bye",
        "nos vemos",
        "hasta luego",
        "hasta pronto",
    }
    CONFIRMATION_PHRASES = {
        "si",
        "sí",
        "confirmo",
        "adelante",
        "hazlo",
        "ejecutalo",
        "ejecútalo",
        "borralo",
        "bórralo",
        "eliminalo",
        "elimínalo",
        "borralas",
        "bórralas",
        "dale",
        "ok hazlo",
        "ok dale",
        "procede",
        "correcto",
        "de acuerdo",
        "esta bien",
        "está bien",
        "asi es",
        "así es",
        "hazlo ya",
        "confirmado",
    }
    CANCELLATION_PHRASES = {
        "no",
        "cancela",
        "cancelar",
        "olvidalo",
        "olvídalo",
        "ya no",
        "mejor no",
        "detener",
        "detente",
        "para",
        "no hagas nada",
        "dejalo",
        "déjalo",
        "dejalo asi",
        "déjalo así",
        "asi no",
        "así no",
    }
    COMMAND_WORDS = {
        "crea",
        "crear",
        "creame",
        "haz",
        "lee",
        "leer",
        "abre",
        "mueve",
        "mover",
        "pasa",
        "pasar",
        "traslada",
        "trasladar",
        "copia",
        "copiar",
        "duplica",
        "duplicar",
        "repite",
        "renombra",
        "renombrar",
        "borra",
        "borrar",
        "elimina",
        "eliminar",
        "quita",
        "quitar",
        "remueve",
        "remover",
        "deshazte",
        "busca",
        "buscar",
        "escanea",
        "escanear",
        "acomoda",
        "acomodar",
        "organiza",
        "organizar",
        "clasifica",
        "clasificar",
        "ejecuta",
        "ejecutar",
        "reconoce",
        "reconocer",
        "usa",
        "usar",
        "toma",
        "tomar",
        "manda",
        "mandar",
        "guarda",
        "guardar",
        "mete",
        "meter",
        "pon",
        "poner",
        "preparar",
        "extraer",
    }
    SHORT_AMBIGUOUS_MAX_TOKENS = 3

    def __init__(self, context_manager):
        self.context_manager = context_manager

    def classify_message(self, text: str, context: dict | None = None) -> dict:
        text = (text or "").strip()
        normalized = TextNormalizer.normalize(text)
        norm_text = normalized.normalized
        context = context or self._context_dict()
        pending_action = context.get("pending_action")

        if not text:
            return self._result("unknown", False, "")

        if self.is_greeting(text):
            return self._result("greeting", False, "Hola, ¿en qué te ayudo?")

        if self.is_thanks(text):
            return self._result("thanks", False, "De nada. ¿Necesitas algo más?")

        if self.is_farewell(text):
            return self._result(
                "farewell",
                False,
                "Perfecto, aquí estaré si necesitas organizar más archivos o fotos.",
            )

        if self.is_cancellation(text):
            if pending_action:
                return self._result(
                    "cancellation",
                    False,
                    "Perfecto, cancelé la acción pendiente. No hice cambios.",
                    clear_pending=True,
                )
            return self._result("cancellation", False, "No hay ninguna acción pendiente.")

        if self.is_confirmation(text):
            if pending_action:
                location_confirmation = self._confirm_single_location_candidate(pending_action)
                if location_confirmation is not None:
                    return self._result("pending_answer", False, "", completed_action=location_confirmation)
                return self._result("confirmation", False, "", pending_action=pending_action)
            return self._result("confirmation", False, "¿Qué acción quieres que confirme?")

        if pending_action:
            pending_answer = self.handle_pending_answer(text, pending_action, context)
            if pending_answer.get("completed_action") and self._should_use_pending_answer(
                normalized,
                pending_answer["completed_action"],
            ):
                return pending_answer
            if self._is_new_command(normalized):
                return self._result("command", True, "", clear_pending=True)
            if pending_answer.get("completed_action"):
                return pending_answer
            if pending_answer.get("response"):
                return pending_answer

        if self._is_short_ambiguous(normalized):
            return self._result(
                "ambiguous",
                False,
                f"Necesito más contexto. ¿Qué deseas hacer con '{self._clean_value(text)}'?",
            )

        return self._result("command", True, "")

    def handle_pending_answer(self, text: str, pending_action: dict, context: dict) -> dict:
        intent = pending_action.get("intent") or "unknown"
        args = dict(pending_action.get("args") or {})
        missing_slot = pending_action.get("missing_slot") or self._infer_missing_slot(intent, args)
        if not missing_slot:
            return self._result("pending_answer", False, "", completed_action=pending_action)

        location_candidates = list(
            pending_action.get("location_candidates")
            or args.get("_location_candidates")
            or []
        )
        location_field = str(
            pending_action.get("location_field")
            or args.get("_location_field")
            or missing_slot
        )
        if location_candidates and missing_slot == location_field:
            selected = self._select_location_candidate(text, location_candidates, context)
            if not selected:
                return self._result(
                    "pending_answer",
                    False,
                    pending_action.get("question")
                    or pending_action.get("preview_text")
                    or self._location_choices_question(location_candidates),
                )
            args[location_field] = selected
            for key in ("_location_candidates", "_location_field", "_location_query"):
                args.pop(key, None)
            completed = dict(pending_action)
            completed["args"] = args
            completed["answered_slot"] = location_field
            completed["missing_fields"] = [
                item for item in (completed.get("missing_fields") or []) if item != location_field
            ]
            completed["missing_slot"] = self._infer_missing_slot(intent, args)
            completed["location_candidates"] = []
            completed["location_selection_resolved"] = True
            return self._result("pending_answer", False, "", completed_action=completed)

        normalized = TextNormalizer.normalize(text)
        extracted = SlotExtractor.extract(intent, text, normalized, self.context_manager)

        # Multi-origen en pending: si se pide la carpeta origen y el usuario da
        # varias ("FOTOS, FOTOS 2 y FOTOS 3") o "las 2"/"todas", guardar la lista
        # en source_folders en vez de forzar una sola.
        if missing_slot in ("source_folder", "source", "source_folders"):
            multi = self._multi_source_answer(text, pending_action, context)
            if len(multi) >= 2:
                args["source_folder"] = multi[0]
                args["source_folders"] = multi
                completed = dict(pending_action)
                completed["args"] = args
                completed["answered_slot"] = "source_folder"
                completed["missing_slot"] = self._infer_missing_slot(intent, args)
                return self._result("pending_answer", False, "", completed_action=completed)

        value = self._value_for_missing_slot(text, normalized, missing_slot, intent, extracted, pending_action=pending_action)
        if value in (None, ""):
            return self._result("pending_answer", False, pending_action.get("question") or "Me falta ese dato para continuar.")

        args[missing_slot] = value
        if missing_slot == "excel_path":
            args["excel_name"] = value
            args["table_path"] = value
        elif missing_slot == "table_path":
            args["excel_path"] = value
            args["excel_name"] = value
        elif missing_slot == "destination":
            args["destination_folder"] = value
        elif missing_slot == "source":
            args["target"] = value
        elif missing_slot in ("name_column", "column_name"):
            args["name_column"] = value
            args["column_name"] = value
        elif missing_slot == "reference_column":
            args["reference_column"] = value

        completed = dict(pending_action)
        completed["args"] = args
        completed["answered_slot"] = missing_slot
        completed["missing_slot"] = self._infer_missing_slot(intent, args)
        return self._result("pending_answer", False, "", completed_action=completed)

    @classmethod
    def _select_location_candidate(cls, text: str, candidates: list[str], context: dict) -> str:
        choices = [str(item).strip() for item in candidates if str(item).strip()]
        if not choices:
            return ""
        norm = cls._normalize_location_answer(text)

        number = re.search(r"(?:^|\b)(\d+)(?:\b|$)", norm)
        if number:
            index = int(number.group(1)) - 1
            if 0 <= index < len(choices):
                return choices[index]

        ordinals = {
            "primera": 0, "primero": 0,
            "segunda": 1, "segundo": 1,
            "tercera": 2, "tercero": 2,
            "cuarta": 3, "cuarto": 3,
        }
        for word, index in ordinals.items():
            if word in norm.split() and index < len(choices):
                return choices[index]

        # Referencias conversacionales respaldadas por una ruta exacta.
        if any(phrase in norm for phrase in (
            "que acabas de crear", "que acabo de crear", "que acabamos de crear",
            "recien creada", "recien creado", "la anterior", "la de antes",
        )):
            created = context.get("last_created_items") if isinstance(context, dict) else None
            last = str(created[-1]) if isinstance(created, list) and created else str(
                (context or {}).get("ultima_carpeta_creada") or (context or {}).get("last_resource") or ""
            )
            matched = cls._match_candidate_reference(last, choices)
            if matched:
                return matched

        normalized_choices = [(choice, cls._normalize_location_answer(choice)) for choice in choices]
        exact = [choice for choice, candidate_norm in normalized_choices if norm == candidate_norm]
        if len(exact) == 1:
            return exact[0]

        ignored = {
            "la", "el", "de", "del", "una", "un", "carpeta", "archivo",
            "ruta", "opcion", "que", "esta", "en", "dentro", "quiero",
            "esa", "ese", "usa", "usar", "selecciona",
        }
        hints = [token for token in norm.split() if token not in ignored and len(token) > 1]
        if not hints:
            return ""
        scored = []
        for choice, candidate_norm in normalized_choices:
            score = sum(1 for token in hints if token in candidate_norm.split() or token in candidate_norm)
            if score:
                scored.append((score, choice))
        if not scored:
            return ""
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return ""
        return scored[0][1]

    @classmethod
    def _match_candidate_reference(cls, value: str, candidates: list[str]) -> str:
        wanted = cls._normalize_location_answer(value)
        if not wanted:
            return ""
        matches = []
        for candidate in candidates:
            candidate_norm = cls._normalize_location_answer(candidate)
            if candidate_norm == wanted or candidate_norm.endswith("/" + wanted) or wanted.endswith("/" + candidate_norm):
                matches.append(candidate)
        return matches[0] if len(matches) == 1 else ""

    @staticmethod
    def _normalize_location_answer(value: str) -> str:
        text = TextNormalizer.strip_accents(str(value or "")).lower().replace("\\", "/")
        text = re.sub(r"[^a-z0-9_./\-\s]+", " ", text)
        return re.sub(r"\s+", " ", text).strip(" /\t\r\n.,;:")

    @staticmethod
    def _location_choices_question(candidates: list[str]) -> str:
        lines = ["Encontre varias ubicaciones:"]
        lines.extend(f"{index}. {candidate}" for index, candidate in enumerate(candidates, start=1))
        lines.append("Cual quieres usar?")
        return "\n".join(lines)

    @staticmethod
    def _confirm_single_location_candidate(pending_action: dict) -> dict | None:
        args = dict((pending_action or {}).get("args") or {})
        candidates = list(
            (pending_action or {}).get("location_candidates")
            or args.get("_location_candidates")
            or []
        )
        if len(candidates) != 1:
            return None
        location_field = str(
            (pending_action or {}).get("location_field")
            or args.get("_location_field")
            or (pending_action or {}).get("missing_slot")
            or "target"
        )
        args[location_field] = str(candidates[0])
        for key in ("_location_candidates", "_location_field", "_location_query"):
            args.pop(key, None)
        completed = dict(pending_action or {})
        completed["args"] = args
        completed["answered_slot"] = location_field
        completed["missing_fields"] = [
            item for item in (completed.get("missing_fields") or []) if item != location_field
        ]
        completed["missing_slot"] = ""
        completed["location_candidates"] = []
        completed["location_selection_resolved"] = True
        return completed

    def _multi_source_answer(self, text: str, pending_action: dict, context: dict) -> list:
        """Devuelve >=2 carpetas si el usuario respondio varias, o [] si no."""
        # 1) Frase con trigger ("usando FOTOS, FOTOS 2 y FOTOS 3").
        folders = SlotExtractor._extract_source_folders(text, self.context_manager)
        if len(folders) >= 2:
            return folders
        # 2) Respuesta directa sin trigger ("FOTOS, FOTOS 2 y FOTOS 3").
        bare = self._parse_bare_folder_list(text)
        if len(bare) >= 2:
            return bare
        # 3) "las 2" / "las tres" / "todas".
        return self._select_multi_from_options(text, pending_action, context)

    @staticmethod
    def _parse_bare_folder_list(text: str) -> list:
        """Separa una respuesta pelada por comas / 'y' / 'e' en nombres de carpeta."""
        s = str(text or "").strip()
        if not s:
            return []
        parts = re.split(r",|\sy\s|\se\s", s, flags=re.IGNORECASE)
        folders = []
        seen = set()
        for piece in parts:
            name = SlotExtractor._clean_source_folder_piece(piece)
            if name and name.lower() not in seen:
                seen.add(name.lower())
                folders.append(name)
        return folders

    def _select_multi_from_options(self, text: str, pending_action: dict, context: dict) -> list:
        """Resuelve "las 2"/"las tres"/"todas" contra las opciones ofrecidas
        (pending_action['source_options']) o las carpetas tipo foto del workspace."""
        norm = TextNormalizer.strip_accents(str(text or "")).lower()
        norm = re.sub(r"[^a-z0-9\s]+", " ", norm)
        norm = re.sub(r"\s+", " ", norm).strip()
        triggers = ("todas", "todas esas", "todas las", "ambas", "las dos", "las 2",
                    "las tres", "las 3", "las cuatro", "las 4")
        if not any(t == norm or t in norm for t in triggers):
            return []
        state = context if isinstance(context, dict) else {}
        pool = [str(o) for o in (pending_action.get("source_options") or []) if o]
        if not pool:
            folders = [f for f in (state.get("available_folders") or [])
                       if f and "/" not in str(f) and "\\" not in str(f)]
            photo = [f for f in folders if "foto" in TextNormalizer.strip_accents(str(f)).lower()]
            pool = photo or folders
        pool = sorted(dict.fromkeys(pool), key=lambda s: TextNormalizer.strip_accents(str(s)).lower())
        if len(pool) < 2:
            return []
        if "todas" in norm or "ambas" in norm:
            return pool
        match = re.search(r"\b(dos|tres|cuatro|2|3|4)\b", norm)
        if match:
            n = {"dos": 2, "2": 2, "tres": 3, "3": 3, "cuatro": 4, "4": 4}[match.group(1)]
            return pool[:n]
        return []

    def is_greeting(self, text: str) -> bool:
        return self._matches_social_phrase(text, self.GREETING_PHRASES)

    def is_confirmation(self, text: str) -> bool:
        return self._matches_social_phrase(text, self.CONFIRMATION_PHRASES, allow_extra=True)

    def is_cancellation(self, text: str) -> bool:
        return self._matches_social_phrase(text, self.CANCELLATION_PHRASES, allow_extra=True)

    def is_thanks(self, text: str) -> bool:
        return self._matches_social_phrase(text, self.THANKS_PHRASES)

    def is_farewell(self, text: str) -> bool:
        return self._matches_social_phrase(text, self.FAREWELL_PHRASES)

    @classmethod
    def _matches_social_phrase(cls, text: str, phrases: set[str], allow_extra: bool = False) -> bool:
        norm_text = TextNormalizer.strip_accents(str(text or "")).lower()
        norm_text = re.sub(r"[^a-z0-9\s]+", " ", norm_text, flags=re.IGNORECASE)
        norm_text = re.sub(r"\s+", " ", norm_text).strip()
        if not norm_text:
            return False
        if norm_text in phrases:
            return True
        if allow_extra:
            tokens = norm_text.split()
            if not tokens:
                return False
            if tokens[0] in phrases and len(tokens) <= 4:
                return True
            return any((" " in phrase and phrase in norm_text) for phrase in phrases)
        return False

    def _is_new_command(self, normalized: NormalizedText) -> bool:
        tokens = set(normalized.tokens)
        return bool(tokens & self.COMMAND_WORDS)

    def _should_use_pending_answer(self, normalized: NormalizedText, completed_action: Dict[str, Any]) -> bool:
        if not self._is_new_command(normalized):
            return True
        answered_slot = completed_action.get("answered_slot") or completed_action.get("missing_slot") or ""
        return self._looks_like_slot_answer(answered_slot, normalized)

    @staticmethod
    def _looks_like_slot_answer(slot: str, normalized: NormalizedText) -> bool:
        tokens = set(normalized.tokens)
        text = normalized.normalized
        if slot in {"destination_folder", "destination"}:
            return bool(tokens & {"guardar", "mandar", "meter", "poner", "destino"}) or "resultado en" in text
        if slot in {"source_folder", "source"}:
            return bool(tokens & {"foto", "fotos", "imagen", "imagenes", "origen", "desde", "tomar"})
        if slot in {"excel_path", "table_path", "document_name"}:
            return bool(tokens & {"excel", "csv", "tabla", "archivo", "lista", "documento"}) or any(
                "." in item.clean for item in normalized.token_items
            )
        if slot in {"target", "new_name", "column_name", "name_column", "reference_column"}:
            return bool(tokens & {"archivo", "carpeta", "nombre", "columna"})
        return False

    def _is_short_ambiguous(self, normalized: NormalizedText) -> bool:
        tokens = [token for token in normalized.tokens if token]
        if not tokens or len(tokens) > self.SHORT_AMBIGUOUS_MAX_TOKENS:
            return False
        if set(tokens) & self.COMMAND_WORDS:
            return False
        if any("." in item.clean for item in normalized.token_items):
            return False
        return True

    def _value_for_missing_slot(
        self,
        text: str,
        normalized: NormalizedText,
        missing_slot: str,
        intent: str,
        extracted: Dict[str, Any],
        pending_action: dict | None = None,
    ):
        if missing_slot == "quantity":
            return self._extract_quantity(normalized)

        # For column-type slots, try matching against available_columns first
        if missing_slot in ("name_column", "column_name", "reference_column"):
            available_columns = self._get_available_columns(pending_action)
            if available_columns:
                matched = self._match_available_column(text, available_columns)
                if matched:
                    return matched

        slot_aliases = {
            "folder_name": ["folder_name"],
            "file_name": ["file_name"],
            "content": ["content"],
            "target": ["target", "source", "document_name"],
            "new_name": ["new_name"],
            "source": ["source", "target"],
            "destination": ["destination", "destination_folder"],
            "document_name": ["document_name", "excel_name"],
            "excel_path": ["excel_path", "table_path", "excel_name", "document_name"],
            "table_path": ["table_path", "excel_path", "excel_name", "document_name"],
            "column_name": ["column_name", "name_column"],
            "name_column": ["name_column", "column_name"],
            "reference_column": ["reference_column", "column_name"],
            "destination_folder": ["destination_folder", "destination"],
            "source_folder": ["source_folder"],
            "base_name": ["base_name", "folder_name", "file_name"],
        }
        for key in slot_aliases.get(missing_slot, [missing_slot]):
            value = extracted.get(key)
            if value not in (None, ""):
                return value

        return self._clean_value(text)

    @staticmethod
    def _extract_quantity(normalized: NormalizedText):
        numbers = {
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
            "veinte": 20,
        }
        for token in normalized.tokens:
            if token.isdigit():
                return int(token)
            if token in numbers:
                return numbers[token]
        return None

    @classmethod
    def _infer_missing_slot(cls, intent: str, args: Dict[str, Any]) -> str:
        order = {
            "create_folder": ["folder_name"],
            "create_multiple_folders": ["quantity", "base_name", "destination_folder"],
            "create_file": ["file_name"],
            "create_multiple_files": ["quantity", "base_name", "destination_folder"],
            "read_document": ["document_name"],
            "rename_item": ["target", "new_name"],
            "move_item": ["source", "destination"],
            "delete_item": ["target"],
            "create_folders_from_excel": ["excel_path", "column_name", "destination_folder"],
            "create_folders_from_table": ["excel_path", "column_name", "destination_folder"],
            "run_facesync": ["excel_path", "source_folder", "destination_folder"],
            "excel_to_facesync_pipeline": ["excel_path", "source_folder", "destination_folder"],
            "prepare_facesync_pipeline": ["excel_path", "source_folder", "destination_folder"],
            "run_reference_face_matching": ["excel_path", "source_folder", "destination_folder"],
            "classify_photos_by_reference": ["excel_path", "source_folder", "destination_folder"],
            "delete_folders_from_excel": ["excel_path", "destination_folder"],
        }
        for slot in order.get(intent, []):
            if not cls._has_slot(args, slot):
                return slot
        return ""

    @staticmethod
    def _has_slot(args: Dict[str, Any], slot: str) -> bool:
        if slot == "excel_path":
            return bool(args.get("excel_path") or args.get("table_path") or args.get("excel_name"))
        if slot == "destination":
            return bool(args.get("destination") or args.get("destination_folder"))
        if slot == "source":
            return bool(args.get("source") or args.get("target"))
        if slot == "column_name":
            return bool(args.get("column_name") or args.get("name_column"))
        if slot == "name_column":
            return bool(args.get("name_column") or args.get("column_name"))
        return bool(args.get(slot))

    @staticmethod
    def _clean_value(text: str) -> str:
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        value = re.sub(r"^(?:mejor\s+)?(?:se\s+llama|llamado|llamada|nombre)\s+", "", value, flags=re.IGNORECASE)
        return value.strip(" \t\r\n\"'`.,;:!?")

    # ------------------------------------------------------------------
    # Column matching helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_available_columns(pending_action: dict | None) -> list[str]:
        """Extract available_columns from pending_action or its args."""
        if not pending_action:
            return []
        columns = pending_action.get("available_columns")
        if columns:
            return [str(c) for c in columns]
        args = pending_action.get("args") or {}
        columns = args.get("available_columns") or args.get("columns")
        if columns and isinstance(columns, list):
            return [str(c) for c in columns]
        return []

    @classmethod
    def _match_available_column(cls, text: str, available_columns: list[str]) -> str:
        """
        Match user response against available column names.

        Supports:
        - Exact match
        - Case-insensitive match
        - Partial / substring match
        - Ordinal references ("la primera", "columna 1", "la segunda", etc.)
        - Keyword references ("la de nombre", "la de foto")
        """
        if not available_columns or not text:
            return ""

        clean_text = re.sub(r"\s+", " ", str(text or "")).strip().strip(" \t\r\n\"'`.,;:!?")
        if not clean_text:
            return ""

        # 1. Exact match
        for col in available_columns:
            if clean_text == col:
                return col

        # 2. Case-insensitive match
        lower_text = clean_text.lower().strip()
        for col in available_columns:
            if lower_text == col.lower().strip():
                return col

        # 3. Ordinal references
        ordinal = cls._parse_ordinal(lower_text)
        if ordinal is not None and 0 <= ordinal < len(available_columns):
            return available_columns[ordinal]

        # 4. Partial / substring match (user text is contained in column name, or vice versa)
        norm_text = cls._normalize_for_column_match(clean_text)
        best_match = ""
        best_score = 0
        for col in available_columns:
            norm_col = cls._normalize_for_column_match(col)
            # User text is a substring of a column name
            if norm_text in norm_col:
                score = len(norm_text)
                if score > best_score:
                    best_score = score
                    best_match = col
            # Column name is a substring of user text
            elif norm_col in norm_text:
                score = len(norm_col)
                if score > best_score:
                    best_score = score
                    best_match = col

        if best_match:
            return best_match

        # 5. Keyword references ("la de nombre", "la de foto")
        keyword_text = re.sub(
            r"^(?:la|el|las|los|una?|ese|esa)\s+(?:de\s+|del\s+|que\s+dice?\s+)?",
            "",
            lower_text,
            flags=re.IGNORECASE,
        ).strip()
        if keyword_text and keyword_text != lower_text:
            norm_kw = cls._normalize_for_column_match(keyword_text)
            for col in available_columns:
                norm_col = cls._normalize_for_column_match(col)
                if norm_kw in norm_col:
                    return col

        return ""

    @staticmethod
    def _parse_ordinal(text: str) -> int | None:
        """Parse ordinal references like 'la primera', 'columna 2', etc. Returns 0-based index or None."""
        text = text.strip().lower()
        ordinal_map = {
            "primera": 0, "la primera": 0, "primer": 0, "el primero": 0, "el primer": 0,
            "1": 0, "columna 1": 0, "la 1": 0, "la columna 1": 0,
            "segunda": 1, "la segunda": 1, "segundo": 1, "el segundo": 1,
            "2": 1, "columna 2": 1, "la 2": 1, "la columna 2": 1,
            "tercera": 2, "la tercera": 2, "tercero": 2, "el tercero": 2,
            "3": 2, "columna 3": 2, "la 3": 2, "la columna 3": 2,
            "cuarta": 3, "la cuarta": 3, "cuarto": 3, "el cuarto": 3,
            "4": 3, "columna 4": 3, "la 4": 3, "la columna 4": 3,
            "quinta": 4, "la quinta": 4, "quinto": 4, "el quinto": 4,
            "5": 4, "columna 5": 4, "la 5": 4, "la columna 5": 4,
        }
        # Check full text first
        if text in ordinal_map:
            return ordinal_map[text]
        # Check for "primera columna", "segunda columna"
        match = re.match(r"^(?:la\s+)?(primera|segunda|tercera|cuarta|quinta)\s+columna$", text)
        if match:
            word = match.group(1)
            word_map = {"primera": 0, "segunda": 1, "tercera": 2, "cuarta": 3, "quinta": 4}
            return word_map.get(word)
        return None

    @staticmethod
    def _normalize_for_column_match(text: str) -> str:
        """Normalize text for column matching: strip accents, lowercase, collapse whitespace."""
        from core.text_normalizer import TextNormalizer
        stripped = TextNormalizer.strip_accents(str(text or "")).lower()
        return re.sub(r"\s+", " ", stripped).strip()

    def _context_dict(self) -> dict:
        return getattr(self.context_manager, "current_context", {}) or {}

    @staticmethod
    def _result(message_type: str, should_continue: bool, response: str, **extra) -> dict:
        result = {
            "message_type": message_type,
            "should_continue_to_router": should_continue,
            "response": response,
            "clear_pending": bool(extra.pop("clear_pending", False)),
        }
        result.update(extra)
        return result
