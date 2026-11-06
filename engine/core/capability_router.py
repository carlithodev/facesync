"""
Capability routing for FaceSync AI.

This module normalizes user intent into reusable canonical capabilities. It does
not execute tools and does not bypass ActionPlanner, PlanGuard, SecurityManager
or ToolExecutionGate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.decision_schema import FaceSyncDecision
from core.intent_interpreter import IntentInterpreter
from core.text_normalizer import TextNormalizer


FILE_ACTION_INTENTS = {
    "create_folder",
    "create_multiple_folders",
    "create_file",
    "move_item",
    "copy_item",
    "rename_item",
    "delete_item",
    "create_folders_from_table",
    "create_folders_from_excel",
}
DOCUMENT_INTENTS = {"read_document"}
FACE_INTENTS = {
    "prepare_facesync_pipeline",
    "excel_to_facesync_pipeline",
    "run_reference_face_matching",
    "classify_photos_by_reference",
    "run_facesync",
}
SEARCH_INTENTS = {"search_files", "scan_workspace"}
CONFIRMATION_INTENTS = {"ask_missing_data", "unknown"}


@dataclass
class CapabilityItem:
    name: str = ""
    source: str = ""
    target: str = ""
    new_name: str = ""
    quantity: Optional[int] = None

    def model_dump(self) -> Dict[str, Any]:
        data = {
            "name": self.name,
            "source": self.source,
            "target": self.target,
            "new_name": self.new_name,
            "quantity": self.quantity,
        }
        return {key: value for key, value in data.items() if value not in (None, "", [])}


@dataclass
class CapabilityRoute:
    capability: str = "clarification"
    operation: str = "unknown"
    mode: str = "single"
    items: List[CapabilityItem] = field(default_factory=list)
    destination_folder: str = ""
    source_folder: str = ""
    table_path: str = ""
    path: str = ""
    document_type: str = "unknown"
    extraction_target: str = "unknown"
    name_column: str = ""
    reference_column: str = ""
    requires_confirmation: bool = False
    preview_required: bool = False
    intent: str = "unknown"
    confidence: float = 0.0
    reason: str = ""
    links: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    args: Dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> Dict[str, Any]:
        return {
            "capability": self.capability,
            "operation": self.operation,
            "mode": self.mode,
            "items": [item.model_dump() for item in self.items],
            "destination_folder": self.destination_folder,
            "source_folder": self.source_folder,
            "table_path": self.table_path,
            "path": self.path,
            "document_type": self.document_type,
            "extraction_target": self.extraction_target,
            "name_column": self.name_column,
            "reference_column": self.reference_column,
            "requires_confirmation": self.requires_confirmation,
            "preview_required": self.preview_required,
            "intent": self.intent,
            "confidence": self.confidence,
            "reason": self.reason,
            "links": list(self.links),
            "risk_flags": list(self.risk_flags),
            "args": dict(self.args),
        }


def _intent_str(val: Any) -> str:
    if val is None:
        return "unknown"
    return str(getattr(val, "value", val) or "unknown").strip()


class CapabilityRouter:
    """Maps text/decisions into canonical capabilities without executing."""

    @classmethod
    def route(
        cls,
        user_text: str,
        interpretation: Optional[Dict[str, Any]] = None,
        *,
        system_state: Optional[Dict[str, Any]] = None,
        context: Any = None,
    ) -> CapabilityRoute:
        state = dict(system_state or {})
        normalized = TextNormalizer.normalize(user_text or "")
        interp = dict(interpretation or {})
        if not interp:
            interp = cls._interpret(user_text, normalized, context or state)
        elif _intent_str(interp.get("intent")) == "unknown":
            inferred = cls._interpret(user_text, normalized, context or state)
            if _intent_str(inferred.get("intent")) != "unknown":
                interp = inferred

        intent = _intent_str(interp.get("intent"))
        args = dict(interp.get("args") or {})
        confidence = float(interp.get("confidence") or 0.0)
        reason = str(interp.get("reason") or interp.get("reason_summary") or "")

        column_route = cls._route_column_to_file_action(user_text, normalized, args, state, confidence, reason)
        if column_route:
            return column_route

        if intent in FILE_ACTION_INTENTS:
            return cls._route_file_action(intent, args, user_text, normalized, state, confidence, reason)
        if intent in DOCUMENT_INTENTS:
            return cls._route_document(intent, args, user_text, state, confidence, reason)
        if intent in FACE_INTENTS:
            return cls._route_face(intent, args, user_text, state, confidence, reason)
        if intent in SEARCH_INTENTS:
            return cls._route_search(intent, args, confidence, reason)
        if intent in CONFIRMATION_INTENTS:
            return CapabilityRoute(
                capability="clarification",
                operation="ask" if intent == "ask_missing_data" else "unknown",
                intent=intent,
                confidence=confidence,
                reason=reason or "Requiere aclaracion.",
                risk_flags=list(interp.get("risk_flags") or []),
                args=args,
            )

        return CapabilityRoute(
            capability="clarification",
            operation="unknown",
            intent="unknown",
            confidence=confidence,
            reason=reason or "No se pudo normalizar la capacidad.",
            risk_flags=["unknown_capability"],
            args=args,
        )

    @classmethod
    def apply_to_interpretation(
        cls,
        user_text: str,
        interpretation: Dict[str, Any],
        *,
        system_state: Optional[Dict[str, Any]] = None,
        context: Any = None,
    ) -> Dict[str, Any]:
        route = cls.route(user_text, interpretation, system_state=system_state, context=context)
        updated = dict(interpretation or {})
        updated["intent"] = route.intent or updated.get("intent") or "unknown"
        updated["confidence"] = max(float(updated.get("confidence") or 0.0), float(route.confidence or 0.0))
        updated["args"] = cls._route_args(route, dict(updated.get("args") or {}))
        updated["capability_route"] = route.model_dump()
        if route.requires_confirmation:
            updated["requires_confirmation"] = True
        if route.preview_required:
            updated["requires_confirmation"] = True
        if route.reason and not updated.get("reason"):
            updated["reason"] = route.reason
        return updated

    @classmethod
    def to_decision(cls, route: CapabilityRoute, fallback: Optional[FaceSyncDecision] = None) -> FaceSyncDecision:
        base = fallback.model_dump() if fallback is not None else {}
        base["intent"] = route.intent or base.get("intent") or "unknown"
        base["confidence"] = max(float(base.get("confidence") or 0.0), float(route.confidence or 0.0))
        base["args"] = cls._route_args(route, dict(base.get("args") or {}))
        base["safe_to_execute"] = bool(base.get("safe_to_execute")) and route.capability != "clarification"
        base["requires_confirmation"] = bool(base.get("requires_confirmation") or route.requires_confirmation or route.preview_required)
        base["reason_summary"] = base.get("reason_summary") or route.reason
        base["risk_flags"] = list(dict.fromkeys(list(base.get("risk_flags") or []) + list(route.risk_flags or [])))
        return FaceSyncDecision.model_validate(base)

    @classmethod
    def _interpret(cls, user_text: str, normalized: Any, context: Any) -> Dict[str, Any]:
        interp = IntentInterpreter.interpret(user_text or "", normalized, context)
        if interp.get("intent") != "unknown":
            return interp
        inferred = cls._infer_intent_from_rough_text(user_text)
        if inferred:
            interp["intent"] = inferred
            interp["confidence"] = 0.72
            interp["reason"] = "CapabilityRouter inferio capacidad por texto normalizado."
            interp["args"] = cls._extract_rough_args(inferred, user_text)
        return interp

    @classmethod
    def _route_file_action(
        cls,
        intent: str,
        args: Dict[str, Any],
        user_text: str,
        normalized: Any,
        state: Dict[str, Any],
        confidence: float,
        reason: str,
    ) -> CapabilityRoute:
        if intent in {"create_folders_from_table", "create_folders_from_excel"}:
            table_path = cls._clean_text(args.get("table_path") or args.get("excel_name") or state.get("last_table_path"))
            name_column = cls._clean_text(args.get("name_column") or args.get("column_name"))
            destination = cls._clean_destination(args.get("destination_folder") or args.get("destination"))
            return CapabilityRoute(
                capability="file_actions",
                operation="create",
                mode="from_document",
                destination_folder=destination,
                table_path=table_path,
                name_column=name_column,
                intent="create_folders_from_table",
                confidence=confidence,
                reason=reason or "Crear carpetas desde documento.",
                links=["document_understanding->file_actions"],
                requires_confirmation=True,
                preview_required=True,
                args={"table_path": table_path, "name_column": name_column, "destination_folder": destination},
            )

        operation = {
            "create_folder": "create",
            "create_multiple_folders": "create",
            "create_file": "create",
            "move_item": "move",
            "copy_item": "copy",
            "rename_item": "rename",
            "delete_item": "delete",
        }.get(intent, "unknown")
        mode = "single"
        route_args: Dict[str, Any] = {}
        items: List[CapabilityItem] = []
        destination = cls._clean_destination(args.get("destination_folder") or args.get("destination"))
        if intent in {"create_folder", "create_multiple_folders", "create_file"}:
            destination = cls._extract_destination_from_create_text(user_text) or destination
        if intent in {"move_item", "copy_item"}:
            _source_hint, dest_hint = cls._extract_pair_move(user_text)
            destination = dest_hint or destination

        if intent == "create_folder":
            name = cls._extract_create_name_after_action(user_text) or cls._clean_created_name(args.get("folder_name"), user_text)
            items = [CapabilityItem(name=name)]
            route_args = {"folder_name": name, "destination_folder": destination}
        elif intent == "create_multiple_folders":
            mode = "batch"
            base_name = cls._clean_created_name(args.get("base_name") or args.get("folder_name"), user_text)
            quantity = cls._safe_int(args.get("quantity"))
            items = [CapabilityItem(name=base_name, quantity=quantity)]
            route_args = {"base_name": base_name, "quantity": quantity, "destination_folder": destination}
        elif intent == "create_file":
            name = cls._clean_created_name(args.get("file_name"), user_text)
            items = [CapabilityItem(name=name)]
            route_args = {"file_name": name, "destination_folder": destination, "content": args.get("content") or ""}
        elif intent in {"move_item", "copy_item"}:
            source = cls._clean_text(args.get("target") or args.get("source"))
            items = [CapabilityItem(source=source)]
            route_args = {"target": source, "destination_folder": destination}
        elif intent == "rename_item":
            source = cls._clean_text(args.get("target") or args.get("source"))
            new_name = cls._clean_created_name(args.get("new_name"), user_text)
            items = [CapabilityItem(source=source, new_name=new_name)]
            route_args = {"target": source, "new_name": new_name}
            mode = "pair"
        elif intent == "delete_item":
            target = cls._clean_text(args.get("target") or args.get("source"))
            items = [CapabilityItem(target=target)]
            route_args = {"target": target}

        return CapabilityRoute(
            capability="file_actions",
            operation=operation,
            mode=mode,
            items=items,
            destination_folder=destination,
            requires_confirmation=operation == "delete",
            preview_required=operation == "delete",
            intent=intent,
            confidence=confidence,
            reason=reason or f"Accion de archivo: {operation}.",
            args=route_args,
        )

    @classmethod
    def _route_document(cls, intent: str, args: Dict[str, Any], user_text: str, state: Dict[str, Any], confidence: float, reason: str) -> CapabilityRoute:
        path = cls._clean_text(args.get("table_path") or args.get("excel_name") or args.get("file_name") or args.get("target"))
        if not path:
            path = cls._extract_file_like(user_text) or cls._extract_document_hint(user_text)
        if not path and len(state.get("available_files") or []) == 1:
            path = cls._clean_text((state.get("available_files") or [""])[0])
        return CapabilityRoute(
            capability="document_understanding",
            operation="read",
            mode="single",
            path=path,
            table_path=path,
            document_type=cls._document_type(path),
            extraction_target="columns",
            intent="read_document",
            confidence=confidence,
            reason=reason or "Leer documento.",
            args={"table_path": path},
        )

    @classmethod
    def _route_face(cls, intent: str, args: Dict[str, Any], user_text: str, state: Dict[str, Any], confidence: float, reason: str) -> CapabilityRoute:
        table_path = cls._clean_text(args.get("table_path") or state.get("last_table_path"))
        name_column = cls._clean_text(args.get("name_column") or state.get("last_name_column"))
        reference_column = cls._clean_text(args.get("reference_column") or state.get("last_reference_column"))
        explicit_source = cls._extract_explicit_source_folder(user_text, state)
        source_folder = cls._clean_destination(explicit_source or args.get("source_folder") or state.get("last_source_folder"))
        destination = cls._clean_destination(args.get("destination_folder") or state.get("last_destination_folder"))
        risk_flags = []
        if name_column and reference_column and TextNormalizer.normalize_for_matching(name_column) == TextNormalizer.normalize_for_matching(reference_column):
            risk_flags.append("name_reference_same")
        mapped_intent = intent
        if intent in {"run_facesync", "prepare_facesync_pipeline", "excel_to_facesync_pipeline"} and (
            table_path or source_folder or destination
        ):
            mapped_intent = "run_reference_face_matching"
        return CapabilityRoute(
            capability="face_recognition",
            operation="match_by_reference" if table_path or reference_column else "classify",
            mode="balanced",
            table_path=table_path,
            name_column=name_column,
            reference_column=reference_column,
            source_folder=source_folder,
            destination_folder=destination,
            intent=mapped_intent,
            confidence=confidence,
            reason=reason or "Reconocimiento facial por referencia.",
            links=["context->face_recognition"],
            requires_confirmation=True,
            preview_required=True,
            risk_flags=risk_flags,
            args={
                "table_path": table_path,
                "name_column": name_column,
                "reference_column": reference_column,
                "source_folder": source_folder,
                "destination_folder": destination,
            },
        )

    @classmethod
    def _route_search(cls, intent: str, args: Dict[str, Any], confidence: float, reason: str) -> CapabilityRoute:
        return CapabilityRoute(
            capability="search_workspace",
            operation="scan" if intent == "scan_workspace" else "search",
            mode="single",
            intent=intent,
            confidence=confidence,
            reason=reason or "Consulta de workspace.",
            args=dict(args or {}),
        )

    @classmethod
    def _route_column_to_file_action(
        cls,
        user_text: str,
        normalized: Any,
        args: Dict[str, Any],
        state: Dict[str, Any],
        confidence: float,
        reason: str,
    ) -> Optional[CapabilityRoute]:
        text = normalized.normalized if hasattr(normalized, "normalized") else TextNormalizer.normalize_for_matching(user_text)
        if "columna" not in text:
            return None
        if not any(word in text.split() for word in {"meter", "mueve", "mover", "poner", "crea", "crear", "creame"}):
            return None
        destination = cls._extract_destination_from_column_text(user_text) or cls._clean_destination(args.get("destination_folder") or args.get("destination"))
        column = cls._ordinal_column_hint(user_text, state) or cls._extract_column_hint(user_text) or cls._clean_text(args.get("name_column") or args.get("column_name"))
        table_path = cls._clean_text(args.get("table_path") or state.get("last_table_path"))
        return CapabilityRoute(
            capability="file_actions",
            operation="create",
            mode="from_document",
            destination_folder=destination,
            table_path=table_path,
            name_column=column,
            intent="create_folders_from_table",
            confidence=max(confidence, 0.74),
            reason=reason or "Columna de documento enlazada a creacion de carpetas.",
            links=["document_understanding->file_actions"],
            requires_confirmation=True,
            preview_required=True,
            args={"table_path": table_path, "name_column": column, "destination_folder": destination},
        )

    @staticmethod
    def _route_args(route: CapabilityRoute, existing: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(existing or {})
        for key, value in route.args.items():
            if value not in (None, ""):
                merged[key] = value
        return merged

    @staticmethod
    def _document_type(path: str) -> str:
        suffix = Path(path or "").suffix.lower()
        return {
            ".xlsx": "excel",
            ".xls": "excel",
            ".csv": "csv",
            ".pdf": "pdf",
            ".docx": "word",
            ".txt": "txt",
            ".jpg": "image",
            ".jpeg": "image",
            ".png": "image",
        }.get(suffix, "unknown")

    @classmethod
    def _infer_intent_from_rough_text(cls, user_text: str) -> str:
        text = cls._rough_text(user_text)
        words = set(text.split())
        if "columna" in words and words & {"meter", "mueve", "mover", "poner", "crea", "crear", "creame"}:
            return "create_folders_from_table"
        if words & {"identifica", "clasifica", "reconoce"} and words & {"foto", "fotos", "caras", "rostros"}:
            return "run_reference_face_matching"
        if "identifica" in words and "ahora" in words:
            return "run_reference_face_matching"
        if words & {"usa", "usar", "usando"} and ("origen" in words or ("misma" in words and "carpeta" in words)):
            return "run_reference_face_matching"
        if words & {"lee", "abre", "carga"} and words & {"excel", "csv", "pdf", "word", "txt", "archivo"}:
            return "read_document"
        if words & {"borra", "elimina", "quita"}:
            return "delete_item"
        if words & {"renombra"}:
            return "rename_item"
        if words & {"mueve", "mover", "meter", "pasa", "acomoda"}:
            return "move_item"
        if words & {"crea", "crear", "creame", "haz", "pon"} and words & {"carpeta", "folder"}:
            return "create_folder"
        return ""

    @classmethod
    def _extract_rough_args(cls, intent: str, user_text: str) -> Dict[str, Any]:
        text = re.sub(r"\s+", " ", str(user_text or "")).strip()
        if intent == "create_folder":
            return {
                "folder_name": cls._clean_created_name(cls._extract_after_name_connector(text), text),
                "destination_folder": cls._extract_destination_from_create_text(text),
            }
        if intent in {"move_item", "copy_item"}:
            source, dest = cls._extract_pair_move(cls._rough_text(text))
            return {"target": source, "destination_folder": dest}
        if intent == "delete_item":
            return {"target": cls._clean_text(re.sub(r"(?i)^(borra|elimina|quita)\s+", "", text))}
        if intent == "read_document":
            return {"table_path": cls._extract_file_like(text)}
        if intent == "run_reference_face_matching":
            return {"source_folder": cls._extract_between(text, "de", "en"), "destination_folder": cls._extract_after_last(text, " en ")}
        if intent == "create_folders_from_table":
            return {"name_column": cls._extract_column_hint(text), "destination_folder": cls._extract_destination_from_column_text(text)}
        return {}

    @classmethod
    def _rough_text(cls, value: str) -> str:
        text = TextNormalizer.strip_accents(str(value or "")).lower()
        replacements = {
            "kreame": "creame",
            "kream": "creame",
            "krpeta": "carpeta",
            "karpeta": "carpeta",
            "llamda": "llamada",
            "llanmada": "llamada",
            "llamdo": "llamado",
            "mube": "mueve",
            "clasifca": "clasifica",
            "fots": "fotos",
            "exel": "excel",
        }
        text = re.sub(r"[^\w.\-/\\]+", " ", text)
        parts = [replacements.get(part, TextNormalizer.COMMON_CORRECTIONS.get(part, part)) for part in text.split()]
        return " ".join(parts)

    @staticmethod
    def _clean_text(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if text.lower() == "none":
            return ""
        return text.strip(" \t\r\n\"'`.,;:")

    @classmethod
    def _clean_destination(cls, value: Any) -> str:
        text = cls._clean_text(value)
        patterns = [
            r"^(?:adentro|dentro)\s+de\s+",
            r"^en\s+",
            r"^(?:la\s+)?carpeta\s+de\s+",
            r"^(?:la\s+)?carpeta\s+",
            r"^de\s+",
        ]
        changed = True
        while changed:
            before = text
            for pattern in patterns:
                text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
            changed = text != before
        return text.strip(" \t\r\n\"'`.,;:")

    @classmethod
    def _clean_created_name(cls, value: Any, user_text: str = "") -> str:
        text = cls._clean_text(value)
        if not text and user_text:
            text = cls._extract_after_name_connector(user_text)
        patterns = [
            r"^(?:una\s+|un\s+)?(?:nueva\s+|nuevo\s+)?(?:carpeta|folder|directorio)\s+",
            r"^(?:que\s+se\s+llame|que\s+se\s+llama|que\s+se\s+nombre|con\s+el\s+nombre|con\s+nombre)\s+",
            r"^(?:se\s+llama|llama|llamada|llamado|llamda|llanmada|llamdo|llanmado)\s+",
            r"^(?:de\s+)?(?:la\s+)?carpeta\s+",
        ]
        changed = True
        while changed:
            before = text
            for pattern in patterns:
                text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
            changed = text != before
        text = re.sub(r"\s+(?:adentro|dentro)\s+de\s+.+$", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s+en\s+(?:la\s+)?carpeta\s+.+$", "", text, flags=re.IGNORECASE).strip()
        return cls._clean_text(text)

    @classmethod
    def _extract_after_name_connector(cls, text: str) -> str:
        for pattern in (
            r"(?i)(?:que\s+se\s+llame|que\s+se\s+llama|que\s+se\s+nombre|con\s+el\s+nombre|con\s+nombre|se\s+llama|llama|llamada|llamado|llamda|llanmada|llamdo)\s+(.+)$",
            r"(?i)(?:carpeta|folder|directorio)\s+(.+)$",
        ):
            match = re.search(pattern, str(text or ""))
            if match:
                return cls._clean_text(match.group(1))
        return ""

    @classmethod
    def _extract_destination_from_create_text(cls, text: str) -> str:
        match = re.search(r"(?i)(?:adentro|dentro)\s+de\s+(?:la\s+)?(?:carpeta\s+)?(.+?)\s+(?:crea|crear|creame|haz|pon|genera)\b", text or "")
        if match:
            return cls._clean_destination(match.group(1))
        match = re.search(r"(?i)^en\s+(?:la\s+)?(?:carpeta\s+)?(.+?)\s+(?:crea|crear|creame|haz|pon|genera)\b", text or "")
        if match:
            return cls._clean_destination(match.group(1))
        return ""

    @classmethod
    def _extract_create_name_after_action(cls, text: str) -> str:
        match = re.search(
            r"(?i)(?:adentro|dentro)\s+de\s+(?:la\s+)?(?:carpeta\s+)?(.+?)\s+"
            r"(?:crea|crear|creame|haz|genera|pon)\s+(.+)$",
            text or "",
        )
        if not match:
            return ""
        value = cls._clean_created_name(match.group(2), text)
        return "" if cls._rough_text(value) in {"", "una carpeta", "carpeta", "nueva carpeta"} else value

    @classmethod
    def _extract_destination_from_column_text(cls, text: str) -> str:
        match = re.search(r"(?i)^(?:en|dentro\s+de|adentro\s+de)\s+(?:la\s+)?(?:carpeta\s+)?(.+?)\s+(?:mete|meter|mueve|mover|pon|poner|crea|crear)\b", text or "")
        if match:
            return cls._clean_destination(match.group(1))
        match = re.search(r"(?i)(?:en|dentro\s+de|adentro\s+de)\s+(?:la\s+)?(?:carpeta\s+)?([^,.;]+)$", text or "")
        if match:
            return cls._clean_destination(match.group(1))
        return ""

    @classmethod
    def _extract_column_hint(cls, text: str) -> str:
        match = re.search(r"(?i)columna\s+(?:de\s+|del\s+|la\s+|el\s+)?(.+?)(?:\s+en\s+|\s+dentro\s+|\s+adentro\s+|$)", text or "")
        if match:
            return cls._clean_text(match.group(1))
        return ""

    @classmethod
    def _ordinal_column_hint(cls, text: str, state: Dict[str, Any]) -> str:
        norm = TextNormalizer.normalize_for_matching(text)
        columns = list(state.get("available_columns") or state.get("last_table_columns") or [])
        if ("primera columna" in norm or "columna 1" in norm or "la primera" in norm) and columns:
            return cls._clean_text(columns[0])
        if ("segunda columna" in norm or "columna 2" in norm or "la segunda" in norm) and len(columns) > 1:
            return cls._clean_text(columns[1])
        return ""

    @classmethod
    def _extract_pair_move(cls, text: str) -> tuple[str, str]:
        match = re.search(r"(?i)(?:mueve|mover|mete|meter|pasa|acomoda)\s+(.+?)\s+(?:a|en|dentro\s+de|adentro\s+de)\s+(.+)$", text or "")
        if match:
            return cls._clean_text(match.group(1)), cls._clean_destination(match.group(2))
        return cls._clean_text(text), ""

    @staticmethod
    def _extract_file_like(text: str) -> str:
        match = re.search(r"(?:^|\s)([^\s,;:]+?\.(?:xlsx|xls|csv|pdf|docx|txt|jpg|jpeg|png))", str(text or ""), flags=re.IGNORECASE)
        return match.group(1).strip() if match else ""

    @classmethod
    def _extract_document_hint(cls, text: str) -> str:
        raw = str(text or "")
        match = re.search(r"(?i)(?:excel|csv|pdf|word|txt|archivo|documento)\s+(?:de\s+)?(.+)$", raw)
        if match:
            return cls._clean_text(match.group(1))
        return ""

    @classmethod
    def _extract_between(cls, text: str, left: str, right: str) -> str:
        match = re.search(rf"(?i)\b{re.escape(left)}\b\s+(.+?)\s+\b{re.escape(right)}\b", text or "")
        return cls._clean_destination(match.group(1)) if match else ""

    @classmethod
    def _extract_after_last(cls, text: str, marker: str) -> str:
        parts = str(text or "").rsplit(marker, 1)
        return cls._clean_destination(parts[1]) if len(parts) == 2 else ""

    @classmethod
    def _extract_explicit_source_folder(cls, text: str, state: Dict[str, Any]) -> str:
        raw = str(text or "")
        norm = cls._rough_text(raw)
        if "misma carpeta" in norm or "la misma" in norm:
            return cls._clean_destination(state.get("last_source_folder") or state.get("ultima_carpeta_fotos") or "")

        patterns = [
            r"(?i)(?:fotos|imagenes)\s+de\s+(.+?)(?:\s+y\s+|\s+acomoda\b|\s+clasifica\b|\s+en\s+|\s+dentro\s+de\s+|\s+adentro\s+de\s+|\s+usando\s+|\s+con\s+|[,.;]|$)",
            r"(?i)\busando\s+(?!la\s+columna\b)(.+?)(?:\s+y\s+|\s+en\s+|\s+dentro\s+de\s+|\s+adentro\s+de\s+|\s+como\s+origen\b|\s+con\s+|[,.;]|$)",
            r"(?i)\busa\s+(?!la\s+columna\b)(.+?)\s+como\s+origen\b",
            r"(?i)\borigen\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw)
            if not match:
                continue
            candidate = cls._clean_destination(match.group(1))
            if cls._valid_source_candidate(candidate):
                return candidate
        return ""

    @classmethod
    def _valid_source_candidate(cls, value: str) -> bool:
        norm = cls._rough_text(value)
        if not norm or norm in {"la misma carpeta", "misma carpeta", "fotos", "las fotos"}:
            return False
        if norm.startswith("columna ") or " referencia" in norm or "como referencia" in norm:
            return False
        if re.search(r"\.(?:csv|xlsx|xls|pdf|docx|txt)\b", value, flags=re.IGNORECASE):
            return False
        return True

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            if value in (None, ""):
                return None
            return int(value)
        except Exception:
            return None


__all__ = ["CapabilityItem", "CapabilityRoute", "CapabilityRouter"]
