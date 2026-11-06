"""
Final safety and repair layer before local action planning.

This module never executes tools. It only repairs a structured decision when
context makes the missing value unambiguous, asks for the smallest missing
piece, or stops risky/incoherent plans before ActionPlanner sees them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple
import copy
import re
import unicodedata


@dataclass
class FallbackResult:
    status: str
    repaired_decision: Dict[str, Any] = field(default_factory=dict)
    question: str = ""
    missing_fields: List[str] = field(default_factory=list)
    reason: str = ""
    risk_flags: List[str] = field(default_factory=list)

    def with_decision(self, decision: Dict[str, Any]) -> "FallbackResult":
        self.repaired_decision = decision
        return self


class ActionFallbackManager:
    FACESYNC_INTENTS = {
        "excel_to_facesync_pipeline",
        "prepare_facesync_pipeline",
        "run_facesync",
        "run_reference_face_matching",
        "classify_photos_by_reference",
    }
    TABLE_INTENTS = {
        "create_folders_from_excel",
        "create_folders_from_table",
        "delete_folders_from_excel",
        *FACESYNC_INTENTS,
    }
    NAME_COLUMN_INTENTS = {
        "create_folders_from_excel",
        "create_folders_from_table",
        "delete_folders_from_excel",
        *FACESYNC_INTENTS,
    }
    REFERENCE_COLUMN_INTENTS = FACESYNC_INTENTS
    SOURCE_FOLDER_INTENTS = FACESYNC_INTENTS
    DESTINATION_FOLDER_INTENTS = {
        "create_folders_from_excel",
        "create_folders_from_table",
        "delete_folders_from_excel",
        *FACESYNC_INTENTS,
    }
    DESTRUCTIVE_INTENTS = {"delete_item", "delete_multiple_items", "delete_folders_from_excel"}
    TABLE_EXTENSIONS = {".xlsx", ".xls", ".csv"}

    BAD_CREATE_FOLDER_VALUES = {
        "primera columna",
        "segunda columna",
        "columna foto",
        "valores",
        "registros",
        "nombres del archivo",
        "nombres de archivo",
    }
    BAD_DESTINATION_PARTS = ("columna", "usando", "referencia", "como referencia", "primera columna")
    VERB_TOKENS = {
        "acomoda",
        "acomodar",
        "organiza",
        "organizar",
        "clasifica",
        "clasificar",
        "mete",
        "meter",
        "crear",
        "crea",
        "haz",
        "hacer",
    }
    NAME_HINTS = {"nombre", "nombres", "alumno", "alumnos", "cliente", "clientes", "persona", "personas"}
    NAME_COLUMN_TOKENS = {
        "nombre",
        "alumno",
        "estudiante",
        "persona",
        "cliente",
        "participante",
        "graduado",
    }
    REFERENCE_HINTS = {"foto", "fotos", "referencia", "codigo", "imagen", "archivo", "base"}
    REFERENCE_COLUMN_TOKENS = {
        "foto",
        "referencia",
        "imagen",
        "archivo",
        "codigo",
        "numero",
        "num",
        "id",
        "base",
    }
    PHOTO_FOLDER_TOKENS = {
        "foto",
        "fotos",
        "imagen",
        "imagenes",
        "maestra",
        "original",
        "originales",
        "master",
        "galeria",
    }
    CONTEXT_DESTINATION_PHRASES = (
        "ahi",
        "alli",
        "donde iban",
        "donde iba",
        "la carpeta anterior",
        "la que hice",
        "donde estaban",
    )

    def analyze_plan(self, decision: Any, system_state: Any, last_error: Any = None) -> FallbackResult:
        return self.repair_plan(decision, system_state, last_error=last_error)

    def repair_plan(self, decision: Any, system_state: Any, last_error: Any = None) -> FallbackResult:
        repaired = self._decision_dict(decision)
        state = self._state_dict(system_state)
        args = dict(repaired.get("args") or {})
        repaired["args"] = args
        intent = str(repaired.get("intent") or "unknown")
        user_text = self._user_text(repaired, state)
        retry_count = self._retry_count(repaired, state)
        risk_flags: List[str] = []

        self._canonicalize_table_args(args)
        self._clean_path_slots(args)

        path_risks = self._path_risk_flags(args, state)
        if path_risks:
            return FallbackResult(
                status="blocked",
                repaired_decision=repaired,
                reason="Una ruta quedaria fuera del project_root.",
                risk_flags=path_risks,
            )

        early_flags = self._detect_incoherence(intent, args, state, user_text)
        if early_flags and self.should_retry_with_smart(repaired, state, early_flags):
            return FallbackResult(
                status="retry_smart",
                repaired_decision=repaired,
                reason="Plan incoherente antes de ActionPlanner.",
                risk_flags=early_flags,
            )

        if early_flags:
            question = self._clarification_for_risk(intent, early_flags)
            return FallbackResult(
                status="clarification_needed",
                repaired_decision=repaired,
                question=question,
                reason="Plan sigue incoherente tras el reintento permitido.",
                risk_flags=early_flags,
            )

        missing_result = self._repair_required_fields(intent, args, state, user_text)
        if missing_result:
            return missing_result.with_decision(repaired)

        risk_flags.extend(self._detect_incoherence(intent, args, state, user_text))
        if risk_flags:
            if self.should_retry_with_smart(repaired, state, risk_flags):
                return FallbackResult(
                    status="retry_smart",
                    repaired_decision=repaired,
                    reason="Plan incoherente despues de reparaciones locales.",
                    risk_flags=risk_flags,
                )
            return FallbackResult(
                status="clarification_needed",
                repaired_decision=repaired,
                question=self._clarification_for_risk(intent, risk_flags),
                reason="Plan inseguro despues del reintento permitido.",
                risk_flags=risk_flags,
            )

        if intent in self.DESTRUCTIVE_INTENTS and not bool(repaired.get("_allow_destructive")):
            repaired["safe_to_execute"] = False
            repaired["requires_confirmation"] = True
            return FallbackResult(
                status="clarification_needed",
                repaired_decision=repaired,
                question=self._confirmation_question(intent, args),
                reason="Accion destructiva requiere confirmacion.",
                risk_flags=["destructive_requires_confirmation"],
            )

        repaired["safe_to_execute"] = True
        return FallbackResult(status="ready", repaired_decision=repaired, reason="Plan listo.", risk_flags=[])

    def resolve_missing_path(self, name: str, available_files: Any, available_folders: Any) -> str:
        status, value, _matches = self._resolve_path(name, available_files, available_folders)
        return value if status == "unique" else ""

    def resolve_column(self, column_hint: str, available_columns: Any, expected_role: str = "") -> str:
        status, value, _matches = self._resolve_column(column_hint, available_columns, expected_role)
        return value if status == "unique" else ""

    def should_retry_with_smart(self, decision: Any, system_state: Any, risk_flags: List[str]) -> bool:
        if not risk_flags:
            return False
        if "path_outside_workspace" in risk_flags:
            return False
        return self._retry_count(self._decision_dict(decision), self._state_dict(system_state)) < 1

    def build_clarification(self, missing_fields: List[str], context: Any) -> str:
        if not missing_fields:
            return "Necesito un dato mas para hacerlo con seguridad."
        field = missing_fields[0]
        questions = {
            "table_path": "Que Excel o CSV quieres usar?",
            "excel_path": "Que Excel o CSV quieres usar?",
            "name_column": "Que columna contiene los nombres para crear las carpetas?",
            "column_name": "Que columna contiene los nombres para crear las carpetas?",
            "reference_column": "Que columna contiene la foto o referencia facial?",
            "source_folder": "Que carpeta contiene las fotos originales?",
            "destination_folder": "Donde quieres guardar el resultado?",
            "target": "Que archivo o carpeta quieres borrar?",
            "targets": "Que archivos o carpetas quieres borrar?",
        }
        return questions.get(field, "Me falta un dato para continuar.")

    # ------------------------------------------------------------------
    # Repair helpers
    # ------------------------------------------------------------------

    def _repair_required_fields(
        self,
        intent: str,
        args: Dict[str, Any],
        state: Dict[str, Any],
        user_text: str,
    ) -> FallbackResult | None:
        if intent == "delete_item" and not args.get("target"):
            if self._norm(user_text) in {"eso", "esa", "ese", "borra eso", "borra esa", "borra ese"} and state.get("last_resource"):
                args["target"] = state["last_resource"]
            else:
                return self._clarify(["target"], "Que archivo o carpeta quieres borrar?")

        if intent == "delete_multiple_items" and not args.get("targets"):
            return self._clarify(["targets"], "Que archivos o carpetas quieres borrar?")

        if intent in self.FACESYNC_INTENTS:
            missing_major = self._facesync_missing_after_context(args, state, user_text)
            if len(missing_major) > 1:
                return self._clarify(missing_major, self._facesync_question(missing_major))

        if intent in self.TABLE_INTENTS:
            table = self._slot(args, "table_path", "excel_path", "excel_name")
            if table:
                table_result = self._repair_table_hint(args, state, table)
                if table_result:
                    return table_result
            else:
                table_result = self._fill_missing_table(args, state)
                if table_result:
                    return table_result

        if intent in self.NAME_COLUMN_INTENTS:
            name_result = self._fill_or_repair_name_column(args, state, user_text, intent)
            if name_result:
                return name_result

        if intent in self.REFERENCE_COLUMN_INTENTS:
            ref_result = self._fill_or_repair_reference_column(args, state, user_text)
            if ref_result:
                return ref_result

        if intent in self.SOURCE_FOLDER_INTENTS:
            source_result = self._fill_or_repair_source_folder(args, state)
            if source_result:
                return source_result

        if intent in self.DESTINATION_FOLDER_INTENTS:
            destination_result = self._fill_or_repair_destination_folder(args, state, user_text, intent)
            if destination_result:
                return destination_result

        return None

    def _facesync_missing_after_context(self, args: Dict[str, Any], state: Dict[str, Any], user_text: str) -> List[str]:
        missing: List[str] = []
        if not self._has_table_candidate(args, state):
            missing.append("table_path")
        if not self._has_source_candidate(args, state):
            missing.append("source_folder")
        if not self._has_destination_candidate(args, state, user_text):
            missing.append("destination_folder")
        return missing

    def _has_table_candidate(self, args: Dict[str, Any], state: Dict[str, Any]) -> bool:
        if self._slot(args, "table_path", "excel_path", "excel_name"):
            return True
        if state.get("last_table_path") or state.get("ultimo_excel_leido") or state.get("last_excel"):
            return True
        table_files = [
            str(value)
            for value in self._list(state, "available_files")
            if Path(str(value)).suffix.lower() in self.TABLE_EXTENSIONS
        ]
        return len(table_files) == 1

    def _has_source_candidate(self, args: Dict[str, Any], state: Dict[str, Any]) -> bool:
        if args.get("source_folder"):
            return True
        if state.get("last_source_folder") or state.get("ultima_carpeta_fotos") or state.get("source_folder"):
            return True
        return len(self._probable_photo_folders(self._list(state, "available_folders"))) == 1

    def _has_destination_candidate(self, args: Dict[str, Any], state: Dict[str, Any], user_text: str) -> bool:
        if self._slot(args, "destination_folder", "destination"):
            return True
        if state.get("last_destination_folder") or state.get("ultima_carpeta_destino"):
            return True
        return self._has_context_destination_phrase(user_text)

    @staticmethod
    def _facesync_question(missing_fields: List[str]) -> str:
        missing = set(missing_fields or [])
        if {"table_path", "source_folder", "destination_folder"}.issubset(missing):
            return (
                "Te entendi: quieres clasificar fotos por referencia. Me falta saber que Excel o CSV usar, "
                "que carpeta contiene las fotos y donde guardar el resultado."
            )
        parts = []
        if "table_path" in missing:
            parts.append("que Excel o CSV usar")
        if "source_folder" in missing:
            parts.append("que carpeta contiene las fotos")
        if "destination_folder" in missing:
            parts.append("donde guardar el resultado")
        return "Te entendi: quieres clasificar fotos por referencia. Me falta saber " + ", ".join(parts) + "."

    def _repair_table_hint(self, args: Dict[str, Any], state: Dict[str, Any], table: str) -> FallbackResult | None:
        files = self._list(state, "available_files")
        if not files:
            self._set_table(args, table)
            return None
        status, value, matches = self._resolve_path(table, files, [])
        if status == "unique":
            self._set_table(args, value)
            return None
        if status == "ambiguous":
            return self._clarify(["table_path"], f"Encontre varios Excel/CSV parecidos: {', '.join(matches[:8])}. Cual quieres usar?")
        suffix = Path(str(table)).suffix.lower()
        if suffix and suffix not in self.TABLE_EXTENSIONS:
            return self._clarify(["table_path"], "Que Excel o CSV quieres usar?")
        self._set_table(args, table)
        return None

    def _fill_missing_table(self, args: Dict[str, Any], state: Dict[str, Any]) -> FallbackResult | None:
        for key in ("last_table_path", "ultimo_excel_leido", "last_excel"):
            value = state.get(key)
            if value:
                self._set_table(args, value)
                return None

        table_files = [
            str(value)
            for value in self._list(state, "available_files")
            if Path(str(value)).suffix.lower() in self.TABLE_EXTENSIONS
        ]
        if len(table_files) == 1:
            self._set_table(args, table_files[0])
            return None
        if len(table_files) > 1:
            return self._clarify(["table_path"], "Que Excel o CSV quieres usar?")
        return self._clarify(["table_path"], "Que Excel o CSV quieres usar?")

    def _fill_or_repair_name_column(
        self,
        args: Dict[str, Any],
        state: Dict[str, Any],
        user_text: str,
        intent: str,
    ) -> FallbackResult | None:
        columns = self._available_columns(state)
        raw = self._slot(args, "name_column", "column_name")
        if not columns:
            if state.get("last_name_column") and intent in self.FACESYNC_INTENTS:
                self._set_name_column(args, state["last_name_column"])
            return None
        if raw:
            status, value, matches = self._resolve_column(raw, columns, "name")
            if status == "unique":
                self._set_name_column(args, value)
                return None
            if status == "ambiguous":
                return self._clarify(["name_column"], f"Encontre varias columnas parecidas: {', '.join(matches)}. Cual contiene los nombres?")
            if columns:
                return self._clarify(["name_column"], "Que columna contiene los nombres para crear las carpetas?")
            return None

        explicit = self._ordinal_column_from_text(user_text, columns, preferred=("primera", "primer", "1"))
        if explicit:
            self._set_name_column(args, explicit)
            return None

        hint = self._column_hint_from_text(user_text, self.NAME_HINTS)
        if hint:
            status, value, matches = self._resolve_column(hint, columns, "name")
            if status == "unique":
                self._set_name_column(args, value)
                return None
            if status == "ambiguous":
                return self._clarify(["name_column"], f"Encontre varias columnas parecidas: {', '.join(matches)}. Cual contiene los nombres?")

        if state.get("last_name_column") and intent in self.FACESYNC_INTENTS:
            self._set_name_column(args, state["last_name_column"])
            return None

        clear = self._unique_role_column(columns, "name")
        if clear:
            self._set_name_column(args, clear)
            return None

        return self._clarify(["name_column"], "Que columna contiene los nombres para crear las carpetas?")

    def _fill_or_repair_reference_column(
        self,
        args: Dict[str, Any],
        state: Dict[str, Any],
        user_text: str,
    ) -> FallbackResult | None:
        columns = self._available_columns(state)
        raw = str(args.get("reference_column") or "").strip()
        if not columns:
            if state.get("last_reference_column"):
                args["reference_column"] = state["last_reference_column"]
            return None
        if raw:
            status, value, matches = self._resolve_column(raw, columns, "reference")
            if status == "unique":
                args["reference_column"] = value
                return None
            if status == "ambiguous":
                return self._clarify(["reference_column"], f"Encontre varias columnas parecidas: {', '.join(matches)}. Cual contiene la referencia facial?")
            if columns:
                return self._clarify(["reference_column"], "Que columna contiene la foto o referencia facial?")
            return None

        explicit = self._ordinal_column_from_text(user_text, columns, preferred=("segunda", "segundo", "2"))
        if explicit:
            args["reference_column"] = explicit
            return None

        hint = self._column_hint_from_text(user_text, self.REFERENCE_HINTS)
        if hint:
            status, value, matches = self._resolve_column(hint, columns, "reference")
            if status == "unique":
                args["reference_column"] = value
                return None
            if status == "ambiguous":
                return self._clarify(["reference_column"], f"Encontre varias columnas parecidas: {', '.join(matches)}. Cual contiene la referencia facial?")

        if state.get("last_reference_column"):
            args["reference_column"] = state["last_reference_column"]
            return None

        clear = self._unique_role_column(columns, "reference")
        if clear:
            args["reference_column"] = clear
            return None

        return self._clarify(["reference_column"], "Que columna contiene la foto o referencia facial?")

    def _fill_or_repair_source_folder(self, args: Dict[str, Any], state: Dict[str, Any]) -> FallbackResult | None:
        raw = str(args.get("source_folder") or "").strip()
        folders = self._list(state, "available_folders")
        if raw:
            status, value, matches = self._resolve_path(raw, [], folders)
            if status == "unique":
                args["source_folder"] = value
                return None
            if status == "ambiguous":
                return self._clarify(["source_folder"], f"Encontre varias carpetas parecidas: {', '.join(matches[:8])}. Cual contiene las fotos originales?")
            return self._clarify(["source_folder"], "Que carpeta contiene las fotos originales?")

        for key in ("last_source_folder", "ultima_carpeta_fotos", "source_folder"):
            value = state.get(key)
            if value:
                args["source_folder"] = value
                return None

        probable = self._probable_photo_folders(folders)
        if len(probable) == 1:
            args["source_folder"] = probable[0]
            return None
        if len(probable) > 1:
            return self._clarify(["source_folder"], f"Encontre estas carpetas posibles: {', '.join(probable[:8])}. Cual contiene las fotos originales?")
        return self._clarify(["source_folder"], "Que carpeta contiene las fotos originales?")

    def _fill_or_repair_destination_folder(
        self,
        args: Dict[str, Any],
        state: Dict[str, Any],
        user_text: str,
        intent: str,
    ) -> FallbackResult | None:
        raw = self._slot(args, "destination_folder", "destination")
        folders = self._list(state, "available_folders")
        if raw:
            cleaned = self._clean_folder_phrase(raw)
            status, value, matches = self._resolve_path(cleaned, [], folders)
            if status == "unique":
                self._set_destination(args, value)
                return None
            if status == "ambiguous":
                return self._clarify(["destination_folder"], f"Encontre varias carpetas parecidas: {', '.join(matches[:8])}. Cual quieres usar?")
            if cleaned != raw:
                self._set_destination(args, cleaned)
                return None
            return self._clarify(["destination_folder"], f"No encontre la carpeta '{cleaned}'. Quieres crearla?")

        last_destination = state.get("last_destination_folder") or state.get("ultima_carpeta_destino")
        if last_destination and (intent in self.FACESYNC_INTENTS or self._has_context_destination_phrase(user_text)):
            self._set_destination(args, last_destination)
            return None
        return self._clarify(["destination_folder"], "Donde quieres guardar el resultado?")

    # ------------------------------------------------------------------
    # Risk detection
    # ------------------------------------------------------------------

    def _detect_incoherence(
        self,
        intent: str,
        args: Dict[str, Any],
        state: Dict[str, Any],
        user_text: str,
    ) -> List[str]:
        flags: List[str] = []
        columns = self._available_columns(state)

        if intent == "create_folder" and columns:
            folder_name = self._norm(args.get("folder_name"))
            if folder_name in self.BAD_CREATE_FOLDER_VALUES or re.match(r"^(primera|segunda|tercera)\s+columna$", folder_name):
                flags.append("create_folder_from_column_phrase")

        destination = self._norm(self._slot(args, "destination_folder", "destination"))
        if destination and any(part in destination for part in self.BAD_DESTINATION_PARTS):
            flags.append("suspicious_destination_folder")

        table_path = self._norm(self._slot(args, "table_path", "excel_path", "excel_name"))
        if table_path and any(verb in table_path.split() for verb in self.VERB_TOKENS):
            flags.append("suspicious_table_path")

        source_folder = self._norm(args.get("source_folder"))
        if source_folder and len(source_folder.split()) >= 5 and any(verb in source_folder.split() for verb in self.VERB_TOKENS):
            flags.append("suspicious_source_folder")

        return flags

    def _path_risk_flags(self, args: Dict[str, Any], state: Dict[str, Any]) -> List[str]:
        project_root = state.get("project_root") or state.get("workspace_actual")
        if not project_root:
            return []
        risky = []
        for key in ("table_path", "excel_path", "excel_name", "source_folder", "destination_folder", "destination", "target", "source"):
            value = args.get(key)
            if value in (None, "", []):
                continue
            if isinstance(value, list):
                values = value
            else:
                values = [value]
            for item in values:
                if self._is_absolute_outside(item, project_root):
                    risky.append("path_outside_workspace")
                    break
        return risky

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, name: str, available_files: Any, available_folders: Any) -> Tuple[str, str, List[str]]:
        raw = str(name or "").strip().strip(" \t\r\n\"'`.,;:")
        if not raw:
            return "missing", "", []

        candidates = [str(item) for item in (available_files or []) if item] + [
            str(item) for item in (available_folders or []) if item
        ]
        if not candidates:
            return "missing", "", []

        raw_norm = self._norm_path(raw)
        scored: List[Tuple[int, str]] = []
        for candidate in candidates:
            score = self._path_score(raw_norm, candidate)
            if score > 0:
                scored.append((score, candidate))
        if not scored:
            return "missing", "", []
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score = scored[0][0]
        best = [candidate for score, candidate in scored if score == best_score]
        if len(best) == 1:
            return "unique", best[0], best
        return "ambiguous", "", best

    def _resolve_column(self, hint: str, available_columns: Any, expected_role: str) -> Tuple[str, str, List[str]]:
        raw = str(hint or "").strip().strip(" \t\r\n\"'`.,;:!?")
        columns = [str(item) for item in (available_columns or []) if item]
        if not raw or not columns:
            return "missing", "", []

        ordinal = self._ordinal_index(raw)
        if ordinal is not None:
            if 0 <= ordinal < len(columns):
                return "unique", columns[ordinal], [columns[ordinal]]
            return "missing", "", []

        raw_norm = self._norm_column(raw)
        scored: List[Tuple[int, str]] = []
        for column in columns:
            col_norm = self._norm_column(column)
            score = self._column_score(raw_norm, col_norm, expected_role)
            if score > 0:
                scored.append((score, column))
        if not scored:
            return "missing", "", []
        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[0][0]
        best = [column for score, column in scored if score == top]
        if len(best) == 1 and top >= 35:
            return "unique", best[0], best
        return "ambiguous", "", best

    def _unique_role_column(self, columns: List[str], role: str) -> str:
        role_tokens = self.NAME_COLUMN_TOKENS if role == "name" else self.REFERENCE_COLUMN_TOKENS
        matches = []
        for column in columns:
            tokens = set(self._norm_column(column).split())
            if tokens & role_tokens:
                matches.append(column)
        return matches[0] if len(matches) == 1 else ""

    def _ordinal_column_from_text(self, user_text: str, columns: List[str], preferred: Tuple[str, ...]) -> str:
        if not columns:
            return ""
        text = self._norm(user_text)
        first_patterns = ("primera columna", "columna 1", "la primera", "la columna 1")
        second_patterns = ("segunda columna", "columna 2", "la segunda", "la columna 2")
        if any(pattern in text for pattern in first_patterns) and any(token in preferred for token in ("primera", "primer", "1")):
            return columns[0]
        if any(pattern in text for pattern in second_patterns) and any(token in preferred for token in ("segunda", "segundo", "2")) and len(columns) > 1:
            return columns[1]
        return ""

    def _column_hint_from_text(self, user_text: str, hints: set[str]) -> str:
        text = self._norm(user_text)
        for hint in sorted(hints, key=len, reverse=True):
            if hint in text.split() or hint in text:
                return hint
        return ""

    def _probable_photo_folders(self, folders: List[str]) -> List[str]:
        matches = []
        for folder in folders:
            tokens = set(self._norm_path(folder).split())
            if tokens & self.PHOTO_FOLDER_TOKENS:
                matches.append(folder)
        return matches

    # ------------------------------------------------------------------
    # Small utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _decision_dict(decision: Any) -> Dict[str, Any]:
        if isinstance(decision, dict):
            return copy.deepcopy(decision)
        if hasattr(decision, "model_dump"):
            return copy.deepcopy(decision.model_dump())
        if hasattr(decision, "__dict__"):
            return copy.deepcopy(vars(decision))
        return {}

    @staticmethod
    def _state_dict(system_state: Any) -> Dict[str, Any]:
        if isinstance(system_state, dict):
            return dict(system_state)
        if hasattr(system_state, "current_context"):
            return dict(getattr(system_state, "current_context") or {})
        return {}

    @staticmethod
    def _list(state: Dict[str, Any], key: str) -> List[str]:
        value = state.get(key) or []
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return []

    def _available_columns(self, state: Dict[str, Any]) -> List[str]:
        columns = self._list(state, "available_columns") or self._list(state, "last_table_columns")
        return [str(column) for column in columns if column]

    @staticmethod
    def _user_text(decision: Dict[str, Any], state: Dict[str, Any]) -> str:
        for key in ("user_text", "_user_text", "normalized_text"):
            if decision.get(key):
                return str(decision[key])
        recent = state.get("recent_user_messages") or []
        if isinstance(recent, list) and recent:
            return str(recent[-1])
        return ""

    @staticmethod
    def _retry_count(decision: Dict[str, Any], state: Dict[str, Any]) -> int:
        for value in (
            decision.get("fallback_retry_count"),
            decision.get("retry_count"),
            state.get("action_fallback_retry_count"),
            state.get("fallback_retry_count"),
        ):
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                continue
        return 0

    @staticmethod
    def _slot(args: Dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = args.get(key)
            if value not in (None, "", []):
                return str(value).strip()
        return ""

    @staticmethod
    def _set_table(args: Dict[str, Any], value: Any):
        text = str(value or "").strip()
        args["table_path"] = text
        args["excel_path"] = text
        args["excel_name"] = text

    @staticmethod
    def _set_name_column(args: Dict[str, Any], value: Any):
        text = str(value or "").strip()
        args["name_column"] = text
        args["column_name"] = text

    @staticmethod
    def _set_destination(args: Dict[str, Any], value: Any):
        text = str(value or "").strip()
        args["destination_folder"] = text
        args["destination"] = text

    def _canonicalize_table_args(self, args: Dict[str, Any]):
        value = self._slot(args, "table_path", "excel_path", "excel_name")
        if value:
            self._set_table(args, value)

    def _clean_path_slots(self, args: Dict[str, Any]):
        for key in ("destination_folder", "destination", "source_folder"):
            if args.get(key):
                args[key] = self._clean_folder_phrase(args[key])

    @staticmethod
    def _clean_folder_phrase(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip().strip(" \t\r\n\"'`.,;:")
        text = re.sub(r"^(?:adentro|dentro)\s+de\s+(?:la\s+)?carpeta\s+de\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^(?:adentro|dentro)\s+de\s+(?:la\s+)?carpeta\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^(?:adentro|dentro)\s+de\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^(?:en\s+)?(?:la\s+)?carpeta\s+de\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^(?:en\s+)?(?:la\s+)?carpeta\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^de\s+", "", text, flags=re.IGNORECASE)
        text = re.split(
            r"\s+(?:usando|usa|usar|con\s+la\s+columna|con\s+columna|como\s+referencia|para\s+reconocer)\b",
            text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        return text.strip(" \t\r\n\"'`.,;:")

    @staticmethod
    def _norm(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.lower()
        text = re.sub(r"[^a-z0-9./\\\s-]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _norm_path(self, value: Any) -> str:
        text = self._norm(value).replace("\\", "/")
        text = re.sub(r"[/_-]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _norm_column(self, value: Any) -> str:
        text = self._norm(value)
        text = re.sub(r"\bnum\b", "numero", text)
        text = re.sub(r"\bno\b", "numero", text)
        return re.sub(r"[^a-z0-9]+", " ", text).strip()

    def _path_score(self, raw_norm: str, candidate: str) -> int:
        candidate_norm = self._norm_path(candidate)
        candidate_name_norm = self._norm_path(Path(str(candidate)).name)
        score = 0
        if raw_norm == candidate_norm or raw_norm == candidate_name_norm:
            score += 100
        elif raw_norm and (raw_norm in candidate_norm or raw_norm in candidate_name_norm):
            score += 70
        raw_tokens = set(raw_norm.split())
        candidate_tokens = set(candidate_norm.split())
        overlap = raw_tokens & candidate_tokens
        score += len(overlap) * 20
        if raw_tokens and raw_tokens.issubset(candidate_tokens):
            score += 25
        return score

    def _column_score(self, raw_norm: str, col_norm: str, expected_role: str) -> int:
        score = 0
        if raw_norm == col_norm:
            score += 100
        elif raw_norm and raw_norm in col_norm:
            score += 80
        elif col_norm and col_norm in raw_norm:
            score += 70
        raw_tokens = set(raw_norm.split())
        col_tokens = set(col_norm.split())
        overlap = raw_tokens & col_tokens
        score += len(overlap) * 25
        if raw_tokens and raw_tokens.issubset(col_tokens):
            score += 35
        role_tokens = self.NAME_COLUMN_TOKENS if expected_role == "name" else self.REFERENCE_COLUMN_TOKENS
        if col_tokens & role_tokens and (not raw_tokens or raw_tokens & role_tokens or overlap):
            score += 20
        return score

    def _ordinal_index(self, text: str) -> int | None:
        norm = self._norm(text)
        mapping = {
            "primera": 0,
            "primer": 0,
            "la primera": 0,
            "columna 1": 0,
            "la columna 1": 0,
            "1": 0,
            "segunda": 1,
            "segundo": 1,
            "la segunda": 1,
            "columna 2": 1,
            "la columna 2": 1,
            "2": 1,
        }
        if norm in mapping:
            return mapping[norm]
        match = re.match(r"^(?:la\s+)?(primera|segunda)\s+columna$", norm)
        if match:
            return 0 if match.group(1) == "primera" else 1
        return None

    @staticmethod
    def _is_absolute_outside(value: Any, project_root: Any) -> bool:
        try:
            text = str(value or "").strip()
            if not text:
                return False
            path = Path(text).expanduser()
            if not path.is_absolute():
                return False
            path.resolve(strict=False).relative_to(Path(str(project_root)).expanduser().resolve(strict=False))
            return False
        except Exception:
            return True

    @staticmethod
    def _has_context_destination_phrase(user_text: str) -> bool:
        norm = ActionFallbackManager._norm(user_text)
        return any(phrase in norm for phrase in ActionFallbackManager.CONTEXT_DESTINATION_PHRASES)

    @staticmethod
    def _confirmation_question(intent: str, args: Dict[str, Any]) -> str:
        target = args.get("target") or args.get("destination_folder") or args.get("excel_path") or "los elementos indicados"
        if intent == "delete_folders_from_excel":
            return "Voy a eliminar las carpetas creadas desde el Excel indicado. Confirmas?"
        if intent == "delete_multiple_items":
            return "Voy a eliminar los elementos indicados. Confirmas?"
        return f"Voy a eliminar '{target}'. Confirmas?"

    def _clarification_for_risk(self, intent: str, risk_flags: List[str]) -> str:
        if "create_folder_from_column_phrase" in risk_flags:
            return "Quieres crear carpetas usando una columna del Excel/CSV o una carpeta literal llamada asi?"
        if "suspicious_destination_folder" in risk_flags:
            return "El destino parece contener texto de columna o referencia. Que carpeta destino quieres usar?"
        if "suspicious_table_path" in risk_flags:
            return "El archivo de tabla no parece una ruta valida. Que Excel o CSV quieres usar?"
        if "suspicious_source_folder" in risk_flags:
            return "La carpeta origen parece contener una frase completa. Que carpeta contiene las fotos originales?"
        return self.build_clarification([], {})

    def _clarify(self, fields: List[str], question: str) -> FallbackResult:
        return FallbackResult(
            status="clarification_needed",
            question=question,
            missing_fields=fields,
            reason="Falta un dato que no se puede inferir con seguridad.",
        )
