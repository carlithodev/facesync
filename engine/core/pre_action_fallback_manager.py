"""
Pre-execution repair and clarification layer for FaceSync AI.

This manager runs after a structured decision exists and before any local tool
is executed. It only repairs unambiguous slots, asks for the smallest missing
piece, or requests one smart retry for incoherent interpretations.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.action_planner import ActionPlanner
from core.decision_schema import ActionPlan, FallbackResult, FaceSyncDecision


class PreActionFallbackManager:
    FACESYNC_INTENTS = {
        "prepare_facesync_pipeline",
        "excel_to_facesync_pipeline",
        "run_reference_face_matching",
        "classify_photos_by_reference",
    }
    TABLE_INTENTS = {
        "create_folders_from_table",
        "create_folders_from_excel",
        *FACESYNC_INTENTS,
    }
    NAME_COLUMN_INTENTS = {
        "create_folders_from_table",
        "create_folders_from_excel",
        *FACESYNC_INTENTS,
    }
    REFERENCE_COLUMN_INTENTS = FACESYNC_INTENTS
    SOURCE_FOLDER_INTENTS = FACESYNC_INTENTS
    DESTINATION_FOLDER_INTENTS = {
        "create_folders_from_table",
        "create_folders_from_excel",
        *FACESYNC_INTENTS,
    }
    DESTRUCTIVE_INTENTS = {"delete_item", "delete_multiple_items", "delete_folders_from_excel"}
    TABLE_EXTENSIONS = {".xlsx", ".xls", ".csv"}
    PHOTO_FOLDER_TOKENS = {"foto", "fotos", "imagen", "imagenes", "original", "originales", "maestra", "master"}
    NAME_COLUMN_TOKENS = {"nombre", "nombres", "alumno", "estudiante", "persona", "cliente", "participante"}
    REFERENCE_COLUMN_TOKENS = {"foto", "referencia", "imagen", "archivo", "codigo", "numero", "id", "base"}
    BAD_DESTINATION_PARTS = ("columna", "usando", "referencia", "como referencia")
    VERB_TOKENS = {"acomoda", "organiza", "clasifica", "mete", "crear", "crea", "haz"}
    CONTEXT_DESTINATION_PHRASES = ("ahi", "alli", "donde iba", "donde iban", "carpeta anterior", "donde estaba")

    def analyze(self, decision_or_plan: Any, system_state: Any, retry_count: int = 0) -> FallbackResult:
        if isinstance(decision_or_plan, ActionPlan):
            return self._analyze_plan(decision_or_plan, system_state, retry_count)
        decision = self._coerce_decision(decision_or_plan)
        if decision is None:
            return FallbackResult(
                status="blocked",
                reason="Decision invalida antes de ejecutar.",
                risk_flags=["invalid_decision"],
            )

        state = self._state_dict(system_state)
        user_text = self._user_text(decision_or_plan, state)
        args = decision.args.model_dump()
        intent = self._intent_value(decision.intent)
        risk_flags: List[str] = []

        incoherent = self._detect_incoherence(intent, args, state, user_text)
        if incoherent:
            repaired = self._decision_with_args(decision, args, safe_to_execute=False, risk_flags=incoherent)
            if retry_count < 1:
                return FallbackResult(
                    status="retry_smart",
                    repaired_decision=repaired,
                    reason="Plan incoherente antes de ejecutar.",
                    risk_flags=incoherent,
                )
            return FallbackResult(
                status="clarification_needed",
                repaired_decision=repaired,
                question=self._question_for_risk(incoherent),
                missing_fields=self._missing_from_risks(incoherent),
                reason="Plan incoherente tras el reintento permitido.",
                risk_flags=incoherent,
            )

        clarification = self._repair_required_fields(intent, args, state, user_text)
        if clarification:
            repaired = self._decision_with_args(decision, args, safe_to_execute=False)
            return FallbackResult(
                status="clarification_needed",
                repaired_decision=repaired,
                question=clarification["question"],
                missing_fields=clarification["missing_fields"],
                reason=clarification["reason"],
                risk_flags=clarification.get("risk_flags", []),
            )

        post_flags = self._detect_incoherence(intent, args, state, user_text)
        if post_flags:
            repaired = self._decision_with_args(decision, args, safe_to_execute=False, risk_flags=post_flags)
            if retry_count < 1:
                return FallbackResult(
                    status="retry_smart",
                    repaired_decision=repaired,
                    reason="Plan incoherente despues de reparaciones locales.",
                    risk_flags=post_flags,
                )
            return FallbackResult(
                status="clarification_needed",
                repaired_decision=repaired,
                question=self._question_for_risk(post_flags),
                missing_fields=self._missing_from_risks(post_flags),
                reason="Plan inseguro despues del reintento permitido.",
                risk_flags=post_flags,
            )

        if intent in self.DESTRUCTIVE_INTENTS:
            repaired = self._decision_with_args(
                decision,
                args,
                safe_to_execute=False,
                requires_confirmation=True,
                risk_flags=["destructive_requires_confirmation"],
            )
            return FallbackResult(
                status="clarification_needed",
                repaired_decision=repaired,
                question=self._confirmation_question(intent, args),
                missing_fields=[],
                reason="Accion destructiva requiere confirmacion.",
                risk_flags=["destructive_requires_confirmation"],
            )

        repaired = self._decision_with_args(decision, args, safe_to_execute=bool(decision.safe_to_execute), risk_flags=risk_flags)
        return FallbackResult(status="ready", repaired_decision=repaired, reason="Decision lista.", risk_flags=risk_flags)

    def analyze_plan(self, decision_or_plan: Any, system_state: Any, retry_count: int = 0) -> FallbackResult:
        return self.analyze(decision_or_plan, system_state, retry_count=retry_count)

    def repair_plan(self, decision_or_plan: Any, system_state: Any, retry_count: int = 0) -> FallbackResult:
        return self.analyze(decision_or_plan, system_state, retry_count=retry_count)

    def _analyze_plan(self, plan: ActionPlan, system_state: Any, retry_count: int) -> FallbackResult:
        from core.plan_guard import PlanGuard

        guarded = PlanGuard().validate(plan, system_state=system_state, retry_count=retry_count)
        return guarded

    def _repair_required_fields(self, intent: str, args: Dict[str, Any], state: Dict[str, Any], user_text: str) -> Optional[Dict[str, Any]]:
        if intent == "create_folder":
            folder_name = self._clean_creation_name_phrase(args.get("folder_name"))
            if folder_name:
                args["folder_name"] = folder_name
            else:
                return self._clarify(["folder_name"], "Claro, que nombre quieres para la carpeta?")

        if intent == "create_multiple_folders":
            base_name = self._clean_creation_name_phrase(args.get("base_name"))
            if base_name:
                args["base_name"] = base_name
            if not args.get("quantity"):
                return self._clarify(["quantity"], "Cuantas carpetas quieres crear?")
            if not args.get("base_name"):
                return self._clarify(["base_name"], "Que nombre base quieres para las carpetas?")

        if intent in self.TABLE_INTENTS:
            table_result = self._repair_table(args, state)
            if table_result:
                return table_result

        if intent in self.NAME_COLUMN_INTENTS:
            name_result = self._repair_name_column(args, state, user_text)
            if name_result:
                return name_result

        if intent in self.REFERENCE_COLUMN_INTENTS:
            ref_result = self._repair_reference_column(args, state, user_text)
            if ref_result:
                return ref_result

        if intent in self.SOURCE_FOLDER_INTENTS:
            source_result = self._repair_source_folder(args, state, user_text)
            if source_result:
                return source_result

        if intent in self.DESTINATION_FOLDER_INTENTS:
            destination_result = self._repair_destination_folder(args, state, user_text, intent)
            if destination_result:
                return destination_result

        if intent in {"move_item", "copy_item", "rename_item", "delete_item"} and self._is_last_created_reference(args.get("target")):
            last_created = self._last_created_item(state)
            if last_created:
                args["target"] = last_created

        if intent in {"move_item", "copy_item", "rename_item", "delete_item"} and self._is_generic_placeholder(args.get("target")):
            args["target"] = None

        if intent == "delete_item" and not args.get("target"):
            return self._clarify(["target"], "Claro, que archivo o carpeta quieres borrar?")

        if intent == "read_document" and not self._text(args.get("table_path") or args.get("excel_name") or args.get("file_name") or args.get("target")):
            return self._clarify(["table_path"], "Claro, que archivo quieres que lea?")

        if intent == "move_item":
            target = self._text(args.get("target"))
            destination = self._text(args.get("destination_folder"))
            if not target and not destination:
                return self._clarify(["target", "destination_folder"], "Claro, que carpeta quieres mover y a donde?")
            if not target:
                return self._clarify(["target"], "Claro, que carpeta quieres mover?")
            if not destination:
                return self._clarify(["destination_folder"], "Claro, a donde quieres moverla?")

        if intent == "copy_item":
            target = self._text(args.get("target"))
            destination = self._text(args.get("destination_folder"))
            if not target and not destination:
                return self._clarify(["target", "destination_folder"], "Claro, que carpeta quieres copiar y a donde?")
            if not target:
                return self._clarify(["target"], "Claro, que carpeta quieres copiar?")
            if not destination:
                return self._clarify(["destination_folder"], "Claro, a donde quieres copiarla?")

        if intent == "rename_item":
            target = self._text(args.get("target"))
            new_name = self._text(args.get("new_name"))
            if not target and not new_name:
                return self._clarify(["target", "new_name"], "Claro, que carpeta quieres renombrar y que nuevo nombre tendra?")
            if not target:
                return self._clarify(["target"], "Claro, que carpeta quieres renombrar?")
            if not new_name:
                return self._clarify(["new_name"], "Claro, que nuevo nombre tendra?")

        return None

    def _repair_table(self, args: Dict[str, Any], state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        table = self._text(args.get("table_path") or args.get("excel_name"))
        if table:
            files = self._table_files(state)
            if files:
                status, value, matches = self._resolve_name(table, files)
                if status == "unique":
                    self._set_table(args, value)
                elif status == "ambiguous":
                    return self._clarify(["table_path"], f"Encontre varios Excel/CSV parecidos: {', '.join(matches)}. Cual quieres usar?")
                else:
                    self._set_table(args, table)
            else:
                self._set_table(args, table)
            return None

        for key in ("last_table_path", "ultimo_excel_leido", "last_excel"):
            if state.get(key):
                self._set_table(args, state[key])
                return None

        files = self._table_files(state)
        if len(files) == 1:
            self._set_table(args, files[0])
            return None
        if len(files) > 1:
            return self._clarify(["table_path"], "Que Excel o CSV quieres usar?")
        return self._clarify(["table_path"], "Que Excel o CSV quieres usar?")

    def _repair_name_column(self, args: Dict[str, Any], state: Dict[str, Any], user_text: str) -> Optional[Dict[str, Any]]:
        columns = self._columns(state)
        raw = self._text(args.get("name_column") or args.get("column_name"))
        if raw:
            status, value, matches = self._resolve_column(raw, columns, role="name")
            if status == "unique":
                self._set_name(args, value)
                return None
            if status == "ambiguous":
                return self._clarify(["name_column"], f"Encontre varias columnas parecidas: {', '.join(matches)}. Cual contiene los nombres?")
            return self._clarify(["name_column"], "Que columna contiene los nombres?")

        if state.get("last_name_column"):
            self._set_name(args, state["last_name_column"])
            return None

        ordinal = self._ordinal_from_text(user_text, columns, index=0)
        if ordinal:
            self._set_name(args, ordinal)
            return None

        probable = self._unique_role_column(columns, self.NAME_COLUMN_TOKENS)
        if probable:
            self._set_name(args, probable)
            return None

        return self._clarify(["name_column"], "Que columna contiene los nombres?")

    def _repair_reference_column(self, args: Dict[str, Any], state: Dict[str, Any], user_text: str) -> Optional[Dict[str, Any]]:
        columns = self._columns(state)
        raw = self._text(args.get("reference_column"))
        if raw:
            status, value, matches = self._resolve_column(raw, columns, role="reference")
            if status == "unique":
                args["reference_column"] = value
                return None
            if status == "ambiguous":
                return self._clarify(["reference_column"], f"Encontre varias columnas parecidas: {', '.join(matches)}. Cual contiene la referencia?")
            return self._clarify(["reference_column"], "Que columna contiene la foto o referencia?")

        if state.get("last_reference_column"):
            args["reference_column"] = state["last_reference_column"]
            return None

        ordinal = self._ordinal_from_text(user_text, columns, index=1)
        if ordinal:
            args["reference_column"] = ordinal
            return None

        probable = self._unique_role_column(columns, self.REFERENCE_COLUMN_TOKENS)
        if probable:
            args["reference_column"] = probable
            return None

        return self._clarify(["reference_column"], "Que columna contiene la foto o referencia?")

    def _repair_source_folder(self, args: Dict[str, Any], state: Dict[str, Any], user_text: str = "") -> Optional[Dict[str, Any]]:
        columns = {self._norm(column) for column in self._columns(state)}
        # Multi-origen ya provisto: con 2+ carpetas se aceptan tal cual (el motor
        # las resuelve y combina). No re-validar contra la lista de subcarpetas
        # de una sola raiz (eso causaba re-preguntar en loop).
        if len([s for s in (args.get("source_folders") or []) if s]) >= 2:
            return None
        raw = self._text(args.get("source_folder"))
        if raw:
            # Si ya es una carpeta real resuelta (ruta absoluta existente, incluida
            # una RAIZ del workspace), aceptarla sin re-validar.
            try:
                _p = Path(raw)
                if _p.is_absolute() and _p.is_dir():
                    return None
            except Exception:
                pass
            if self._norm(raw) in columns:
                return self._clarify(["source_folder"], "Que carpeta contiene las fotos originales?", ["source_folder_is_column"])
            status, value, matches = self._resolve_name(raw, self._folders(state))
            if status == "unique":
                args["source_folder"] = value
                return None
            if status == "ambiguous":
                return self._clarify(["source_folder"], f"Encontre varias carpetas parecidas: {', '.join(matches)}. Cual contiene las fotos originales?")
            return self._clarify(["source_folder"], "Que carpeta contiene las fotos originales?")

        for key in ("last_source_folder", "ultima_carpeta_fotos"):
            if state.get(key):
                args["source_folder"] = state[key]
                return None

        if "ahora identifica" in self._norm(user_text):
            return self._clarify(["source_folder"], "Que carpeta contiene las fotos originales?")

        probable = self._probable_photo_folders(self._folders(state))
        if len(probable) == 1:
            args["source_folder"] = probable[0]
            return None
        if len(probable) > 1:
            return self._clarify(["source_folder"], f"Encontre varias carpetas posibles: {', '.join(probable)}. Cual contiene las fotos originales?")
        return self._clarify(["source_folder"], "Que carpeta contiene las fotos originales?")

    def _repair_destination_folder(self, args: Dict[str, Any], state: Dict[str, Any], user_text: str, intent: str) -> Optional[Dict[str, Any]]:
        raw = self._text(args.get("destination_folder"))
        if raw:
            cleaned = self._clean_folder_phrase(raw)
            status, value, matches = self._resolve_name(cleaned, self._folders(state))
            if status == "unique":
                args["destination_folder"] = value
                return None
            if status == "ambiguous":
                return self._clarify(["destination_folder"], f"Encontre varias carpetas parecidas: {', '.join(matches)}. Cual quieres usar?")
            args["destination_folder"] = cleaned
            return None

        if self._has_context_destination_phrase(user_text) or intent in self.FACESYNC_INTENTS:
            for key in ("last_destination_folder", "ultima_carpeta_destino"):
                if state.get(key):
                    args["destination_folder"] = state[key]
                    return None
        return self._clarify(["destination_folder"], "Donde quieres guardar el resultado?")

    def _detect_incoherence(self, intent: str, args: Dict[str, Any], state: Dict[str, Any], user_text: str) -> List[str]:
        del user_text
        flags: List[str] = []
        columns = self._columns(state)
        normalized_columns = {self._norm(column) for column in columns}

        if intent == "create_folder" and columns:
            folder_name = self._norm(args.get("folder_name"))
            if folder_name in {"primera columna", "segunda columna", "columna foto", "valores", "registros"}:
                flags.append("create_folder_from_column_phrase")

        destination = self._norm(args.get("destination_folder"))
        if destination and any(part in destination for part in self.BAD_DESTINATION_PARTS):
            flags.append("suspicious_destination_folder")

        table_path = self._norm(args.get("table_path") or args.get("excel_name"))
        if table_path and any(verb in table_path.split() for verb in self.VERB_TOKENS):
            flags.append("suspicious_table_path")

        source_folder = self._norm(args.get("source_folder"))
        if source_folder and source_folder in normalized_columns:
            flags.append("source_folder_is_column")
        if source_folder and len(source_folder.split()) > 5:
            flags.append("suspicious_source_folder")

        if intent in self.FACESYNC_INTENTS:
            name = self._norm(args.get("name_column"))
            reference = self._norm(args.get("reference_column"))
            if name and reference and name == reference:
                last_name = state.get("last_name_column")
                if last_name and self._norm(last_name) != reference:
                    self._set_name(args, last_name)
                else:
                    flags.append("same_name_and_reference_column")

        return self._dedupe(flags)

    def _decision_with_args(
        self,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        *,
        safe_to_execute: bool,
        requires_confirmation: Optional[bool] = None,
        risk_flags: Optional[List[str]] = None,
    ) -> FaceSyncDecision:
        data = decision.model_dump()
        data["args"] = {key: value for key, value in args.items() if key in self._action_arg_keys()}
        data["safe_to_execute"] = bool(safe_to_execute)
        if requires_confirmation is not None:
            data["requires_confirmation"] = bool(requires_confirmation)
        if risk_flags:
            data["risk_flags"] = self._dedupe(list(data.get("risk_flags") or []) + list(risk_flags))
        return FaceSyncDecision.model_validate(data)

    @staticmethod
    def _coerce_decision(value: Any) -> Optional[FaceSyncDecision]:
        try:
            if isinstance(value, FaceSyncDecision):
                return value
            if hasattr(value, "model_dump"):
                return FaceSyncDecision.model_validate(value.model_dump())
            data = copy.deepcopy(value or {})
            if "needs_clarification" in data and "requires_clarification" not in data:
                data["requires_clarification"] = bool(data.get("needs_clarification"))
            if "question" in data and "clarification" not in data:
                data["clarification"] = {
                    "required": bool(data.get("requires_clarification")),
                    "missing_fields": data.get("missing_fields") or [],
                    "question": data.get("question") or "",
                }
            if "reason" in data and "reason_summary" not in data:
                data["reason_summary"] = data.get("reason") or ""
            return FaceSyncDecision.model_validate(data)
        except Exception:
            return None

    @classmethod
    def _state_dict(cls, state: Any) -> Dict[str, Any]:
        if isinstance(state, dict):
            result = dict(state)
        elif hasattr(state, "current_context"):
            result = dict(getattr(state, "current_context") or {})
        else:
            result = {}
        summary = result.get("context_summary")
        if isinstance(summary, dict):
            for key, value in summary.items():
                result.setdefault(key, value)
        return result

    @classmethod
    def _user_text(cls, decision_or_plan: Any, state: Dict[str, Any]) -> str:
        if isinstance(decision_or_plan, dict):
            for key in ("user_text", "_user_text", "normalized_text"):
                if decision_or_plan.get(key):
                    return str(decision_or_plan[key])
        recent = state.get("recent_user_messages") or []
        if isinstance(recent, list) and recent:
            return str(recent[-1])
        return ""

    @staticmethod
    def _intent_value(intent: Any) -> str:
        return intent.value if hasattr(intent, "value") else str(intent or "unknown")

    @staticmethod
    def _text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @classmethod
    def _is_generic_placeholder(cls, value: Any) -> bool:
        norm = cls._norm(value)
        return norm in {
            "",
            "ayudame",
            "ayuda",
            "una carpeta",
            "un archivo",
            "carpeta",
            "archivo",
            "la carpeta",
            "el archivo",
        }

    @classmethod
    def _is_last_created_reference(cls, value: Any) -> bool:
        norm = cls._norm(value)
        return norm in {"ultimo que creaste", "lo ultimo que creaste", "ultima carpeta", "la ultima carpeta"}

    @staticmethod
    def _last_created_item(state: Dict[str, Any]) -> str:
        value = state.get("last_created_item")
        if value:
            return str(value)
        items = state.get("last_created_items")
        if isinstance(items, list) and items:
            return str(items[-1])
        return ""

    @staticmethod
    def _action_arg_keys() -> set[str]:
        return {
            "table_path",
            "excel_name",
            "name_column",
            "column_name",
            "reference_column",
            "source_folder",
            "source_folders",
            "destination_folder",
            "folder_name",
            "file_name",
            "target",
            "new_name",
            "quantity",
            "base_name",
            "content",
        }

    def _table_files(self, state: Dict[str, Any]) -> List[str]:
        return [item for item in self._list(state, "available_files") if Path(item).suffix.lower() in self.TABLE_EXTENSIONS]

    def _folders(self, state: Dict[str, Any]) -> List[str]:
        return self._list(state, "available_folders")

    def _columns(self, state: Dict[str, Any]) -> List[str]:
        return self._list(state, "available_columns") or self._list(state, "last_table_columns")

    @staticmethod
    def _list(state: Dict[str, Any], key: str) -> List[str]:
        value = state.get(key) or []
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        return []

    @staticmethod
    def _set_table(args: Dict[str, Any], value: Any):
        args["table_path"] = str(value or "").strip()
        args["excel_name"] = str(value or "").strip()

    @staticmethod
    def _set_name(args: Dict[str, Any], value: Any):
        args["name_column"] = str(value or "").strip()
        args["column_name"] = str(value or "").strip()

    def _resolve_name(self, hint: str, candidates: List[str]) -> Tuple[str, str, List[str]]:
        raw = self._norm_path(hint)
        scored: List[Tuple[int, str]] = []
        for candidate in candidates:
            score = self._score(raw, self._norm_path(candidate))
            if score:
                scored.append((score, candidate))
        if not scored:
            return "missing", "", []
        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[0][0]
        matches = [value for score, value in scored if score == top]
        if len(matches) == 1:
            return "unique", matches[0], matches
        return "ambiguous", "", matches

    def _resolve_column(self, hint: str, columns: List[str], role: str) -> Tuple[str, str, List[str]]:
        if not columns:
            return "missing", "", []
        ordinal = self._ordinal_index(hint)
        if ordinal is not None and ordinal < len(columns):
            return "unique", columns[ordinal], [columns[ordinal]]
        raw = self._norm_column(hint)
        scored: List[Tuple[int, str]] = []
        role_tokens = self.NAME_COLUMN_TOKENS if role == "name" else self.REFERENCE_COLUMN_TOKENS
        for column in columns:
            col_norm = self._norm_column(column)
            score = self._score(raw, col_norm)
            if set(col_norm.split()) & role_tokens and (raw in col_norm or set(raw.split()) & role_tokens):
                score += 20
            if score:
                scored.append((score, column))
        if not scored:
            return "missing", "", []
        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[0][0]
        matches = [value for score, value in scored if score == top]
        if len(matches) == 1:
            return "unique", matches[0], matches
        return "ambiguous", "", matches

    def _unique_role_column(self, columns: List[str], tokens: set[str]) -> str:
        matches = [column for column in columns if set(self._norm_column(column).split()) & tokens]
        return matches[0] if len(matches) == 1 else ""

    def _ordinal_from_text(self, user_text: str, columns: List[str], index: int) -> str:
        if not columns or index >= len(columns):
            return ""
        text = self._norm(user_text)
        if index == 0 and any(pattern in text for pattern in ("primera columna", "columna 1", "la primera")):
            return columns[0]
        if index == 1 and any(pattern in text for pattern in ("segunda columna", "columna 2", "la segunda")):
            return columns[1]
        return ""

    def _probable_photo_folders(self, folders: List[str]) -> List[str]:
        matches = [folder for folder in folders if set(self._norm_path(folder).split()) & self.PHOTO_FOLDER_TOKENS]
        if len(matches) <= 1:
            return matches
        roots = []
        normalized = [(folder, self._norm_path(folder)) for folder in matches]
        for folder, norm in normalized:
            if any(other != folder and other_norm.startswith(norm + " ") for other, other_norm in normalized):
                roots.append(folder)
        if len(roots) == 1:
            return roots
        min_depth = min(str(folder).replace("\\", "/").count("/") for folder in matches)
        shallow = [folder for folder in matches if str(folder).replace("\\", "/").count("/") == min_depth]
        return shallow if len(shallow) == 1 else matches

    @staticmethod
    def _score(raw: str, candidate: str) -> int:
        if not raw or not candidate:
            return 0
        score = 0
        if raw == candidate:
            score += 100
        elif raw in candidate or candidate in raw:
            score += 70
        raw_tokens = set(raw.split())
        candidate_tokens = set(candidate.split())
        overlap = raw_tokens & candidate_tokens
        score += len(overlap) * 20
        if raw_tokens and raw_tokens.issubset(candidate_tokens):
            score += 30
        return score

    @staticmethod
    def _norm(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
        text = re.sub(r"[^a-z0-9./\\\s-]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _norm_path(self, value: Any) -> str:
        text = self._norm(value).replace("\\", "/")
        text = re.sub(r"[/_-]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _norm_column(self, value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", " ", self._norm(value)).strip()

    def _ordinal_index(self, value: Any) -> Optional[int]:
        text = self._norm(value)
        if text in {"primera", "primer", "primera columna", "columna 1", "la primera", "1"}:
            return 0
        if text in {"segunda", "segundo", "segunda columna", "columna 2", "la segunda", "2"}:
            return 1
        return None

    @staticmethod
    def _clean_folder_phrase(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip().strip(" \t\r\n\"'`.,;:")
        text = re.sub(r"^(?:adentro|dentro)\s+de\s+(?:la\s+)?carpeta\s+de\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^(?:adentro|dentro)\s+de\s+(?:la\s+)?carpeta\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^(?:en\s+)?(?:la\s+)?carpeta\s+de\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^(?:en\s+)?(?:la\s+)?carpeta\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^de\s+", "", text, flags=re.IGNORECASE)
        text = re.split(r"\s+(?:usando|con\s+la\s+columna|como\s+referencia)\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
        return text.strip(" \t\r\n\"'`.,;:")

    @staticmethod
    def _clean_creation_name_phrase(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip().strip(" \t\r\n\"'`.,;:")
        if not text:
            return ""
        patterns = [
            r"^(?:una?\s+)?carpeta\s+(?:se\s+llama|llama|llamada|llamado)\s+",
            r"^(?:una?\s+)?carpeta\s+que\s+se\s+(?:llame|llama)\s+",
            r"^(?:que\s+se\s+llame|que\s+se\s+llama|que\s+se\s+nombra|que\s+se\s+nombre)\s+",
            r"^(?:se\s+llama|llama|llamada|llamado)\s+",
            r"^(?:con\s+el\s+nombre|con\s+nombre)\s+",
        ]
        for pattern in patterns:
            text = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
        return text.strip(" \t\r\n\"'`.,;:")

    def _has_context_destination_phrase(self, user_text: str) -> bool:
        text = self._norm(user_text)
        return any(phrase in text for phrase in self.CONTEXT_DESTINATION_PHRASES)

    @staticmethod
    def _clarify(missing_fields: List[str], question: str, risk_flags: Optional[List[str]] = None) -> Dict[str, Any]:
        return {
            "missing_fields": missing_fields,
            "question": question,
            "reason": "Falta un dato que no se puede inferir con seguridad.",
            "risk_flags": risk_flags or [],
        }

    @staticmethod
    def _question_for_risk(flags: List[str]) -> str:
        if "create_folder_from_column_phrase" in flags:
            return "Quieres crear carpetas usando la columna del Excel/CSV o una carpeta literal con ese nombre?"
        if "suspicious_destination_folder" in flags:
            return "El destino parece mezclar una carpeta con texto de columna o referencia. Que carpeta destino quieres usar?"
        if "same_name_and_reference_column" in flags:
            return "La columna de nombres y la columna de referencia quedaron iguales. Cuales columnas debo usar?"
        if "source_folder_is_column" in flags:
            return "La carpeta origen parece ser una columna. Que carpeta contiene las fotos originales?"
        return "Necesito un dato mas para hacerlo con seguridad."

    @staticmethod
    def _missing_from_risks(flags: List[str]) -> List[str]:
        mapping = {
            "suspicious_destination_folder": "destination_folder",
            "same_name_and_reference_column": "reference_column",
            "source_folder_is_column": "source_folder",
            "suspicious_source_folder": "source_folder",
            "suspicious_table_path": "table_path",
        }
        return [mapping[flag] for flag in flags if flag in mapping]

    @staticmethod
    def _confirmation_question(intent: str, args: Dict[str, Any]) -> str:
        target = args.get("target") or "el elemento indicado"
        if intent == "delete_folders_from_excel":
            return "Voy a eliminar carpetas desde una tabla. Confirmas?"
        return f"Voy a eliminar '{target}'. Confirmas?"

    @staticmethod
    def _dedupe(values: List[str]) -> List[str]:
        result = []
        seen = set()
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                result.append(text)
                seen.add(text)
        return result


__all__ = ["PreActionFallbackManager"]
