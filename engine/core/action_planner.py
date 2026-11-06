"""
Action planning for FaceSync AI.

The structured planner converts a validated FaceSyncDecision into an ActionPlan
from core.decision_schema. It never executes tools. A small legacy wrapper is
kept for existing LocalCommandRouter code that still expects Spanish tool ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.decision_schema import (
    ActionPlan as StructuredActionPlan,
    ActionStep as StructuredActionStep,
    AllowedIntent,
    FaceSyncDecision,
)


ACTION_ARG_KEYS = {
    "table_path",
    "excel_name",
    "name_column",
    "column_name",
    "reference_column",
    "source_folder",
    "destination_folder",
    "folder_name",
    "file_name",
    "target",
    "new_name",
    "quantity",
    "base_name",
    "content",
}

MASSIVE_OR_SENSITIVE_INTENTS = {
    "create_folders_from_table",
    "create_folders_from_excel",
    "run_reference_face_matching",
    "classify_photos_by_reference",
    "delete_item",
}


@dataclass
class ActionStep:
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)

    @property
    def tool_name(self) -> str:
        return self.tool

    @property
    def action(self) -> str:
        return self.tool


@dataclass
class ActionPlan:
    intent: str
    confidence: float
    steps: List[ActionStep] = field(default_factory=list)
    needs_clarification: bool = False
    question: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def as_list(self) -> List[Dict[str, Any]]:
        return [{"tool": step.tool, "args": step.args} for step in self.steps]


class ActionPlanner:
    @classmethod
    def plan(cls, decision: FaceSyncDecision | Dict[str, Any]) -> StructuredActionPlan:
        return cls.from_decision(decision)

    @classmethod
    def build_structured(cls, decision: FaceSyncDecision | Dict[str, Any]) -> StructuredActionPlan:
        return cls.from_decision(decision)

    @classmethod
    def from_decision(cls, decision: FaceSyncDecision | Dict[str, Any]) -> StructuredActionPlan:
        try:
            parsed = cls._coerce_decision(decision)
        except Exception as exc:
            return StructuredActionPlan.model_validate(
                {
                    "intent": "unknown",
                    "steps": [],
                    "preview_required": False,
                    "safe_to_execute": False,
                    "requires_confirmation": False,
                    "reason_summary": f"Decision invalida: {exc}",
                    "risk_flags": ["invalid_decision", "unknown_intent"],
                }
            )

        intent = cls._intent_value(parsed.intent)
        args = parsed.args.model_dump() if hasattr(parsed.args, "model_dump") else dict(parsed.args or {})
        risk_flags = list(parsed.risk_flags or [])

        if parsed.requires_clarification or intent == "ask_missing_data":
            return cls._empty_structured_plan(
                intent="ask_missing_data",
                reason_summary=parsed.reason_summary or "Faltan datos",
                risk_flags=cls._dedupe(risk_flags + ["clarification_required"]),
            )

        builder = getattr(cls, f"_structured_{intent}", None)
        if not builder:
            return cls._empty_structured_plan(
                intent="unknown",
                reason_summary=parsed.reason_summary or "Intent desconocido",
                risk_flags=cls._dedupe(risk_flags + ["unknown_intent"]),
            )

        plan = builder(parsed, args, risk_flags)
        return StructuredActionPlan.model_validate(plan)

    @classmethod
    def build(cls, interpretation: Dict[str, Any] | FaceSyncDecision, context: Any = None):
        if isinstance(interpretation, FaceSyncDecision):
            return cls.from_decision(interpretation)
        if isinstance(interpretation, dict) and (
            "requires_clarification" in interpretation or "clarification" in interpretation
        ):
            return cls.from_decision(interpretation)
        return cls._build_legacy(interpretation or {}, context)

    @classmethod
    def _structured_create_folder(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        folder_name = cls._text(args.get("folder_name"))
        destination = cls._text(args.get("destination_folder"))
        missing = []
        if not folder_name:
            missing.append("missing_folder_name")
        risk_flags = cls._missing_risks(risk_flags, missing)
        steps = [] if missing else [
            cls._step(
                1,
                "file_tools",
                "create_folder",
                {"folder_name": folder_name, "destination_folder": destination},
                f"Crear carpeta {folder_name}",
            )
        ]
        return cls._plan_dict(decision, steps, risk_flags=risk_flags, safe_to_execute=bool(decision.safe_to_execute) and not missing)

    @classmethod
    def _structured_create_multiple_folders(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        quantity = args.get("quantity")
        base_name = cls._text(args.get("base_name"))
        destination = cls._text(args.get("destination_folder"))
        missing = []
        if not quantity:
            missing.append("missing_quantity")
        if not base_name:
            missing.append("missing_base_name")
        risk_flags = cls._missing_risks(risk_flags, missing)
        steps = [] if missing else [
            cls._step(
                1,
                "file_tools",
                "create_multiple_folders",
                {"quantity": int(quantity), "base_name": base_name, "destination_folder": destination},
                f"Crear {int(quantity)} carpetas",
            )
        ]
        return cls._plan_dict(decision, steps, risk_flags=risk_flags, safe_to_execute=bool(decision.safe_to_execute) and not missing)

    @classmethod
    def _structured_create_file(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        file_name = cls._text(args.get("file_name"))
        destination = cls._text(args.get("destination_folder"))
        missing = [] if file_name else ["missing_file_name"]
        risk_flags = cls._missing_risks(risk_flags, missing)
        steps = [] if missing else [
            cls._step(
                1,
                "file_tools",
                "create_file",
                {"file_name": file_name, "destination_folder": destination, "content": args.get("content") or ""},
                f"Crear archivo {file_name}",
            )
        ]
        return cls._plan_dict(decision, steps, risk_flags=risk_flags, safe_to_execute=bool(decision.safe_to_execute) and not missing)

    @classmethod
    def _structured_read_document(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        path = cls._table_path(args) or cls._text(args.get("file_name")) or cls._text(args.get("target"))
        missing = [] if path else ["missing_document_path"]
        risk_flags = cls._missing_risks(risk_flags, missing)
        steps = [] if missing else [
            cls._step(1, "document_tools", "read_document", {"path": path}, f"Leer documento {path}")
        ]
        return cls._plan_dict(decision, steps, risk_flags=risk_flags, safe_to_execute=bool(decision.safe_to_execute) and not missing)

    @classmethod
    def _structured_create_folders_from_table(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        return cls._table_folder_plan(decision, args, risk_flags)

    _structured_create_folders_from_excel = _structured_create_folders_from_table

    @classmethod
    def _table_folder_plan(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        table_path = cls._table_path(args)
        name_column = cls._text(args.get("name_column") or args.get("column_name"))
        destination = cls._text(args.get("destination_folder"))
        missing = []
        if not table_path:
            missing.append("missing_table_path")
        if not name_column:
            missing.append("missing_name_column")
        risk_flags = cls._missing_risks(risk_flags, missing)
        steps = [] if missing else [
            cls._step(1, "document_tools", "validate_table", {"table_path": table_path}, "Validar tabla"),
            cls._step(
                2,
                "document_tools",
                "validate_column",
                {"table_path": table_path, "column_name": name_column},
                "Validar columna de nombres",
            ),
            cls._step(3, "file_tools", "ensure_folder", {"destination_folder": destination}, "Validar carpeta destino"),
            cls._step(
                4,
                "document_tools",
                "create_folders_from_table",
                {"table_path": table_path, "name_column": name_column, "destination_folder": destination},
                "Crear carpetas desde tabla",
                requires_confirmation=True,
            ),
        ]
        preview = cls._preview_create_folders(table_path, name_column, destination)
        return cls._plan_dict(
            decision,
            steps,
            preview_required=True,
            requires_confirmation=True,
            preview_text=preview,
            risk_flags=risk_flags,
            safe_to_execute=bool(decision.safe_to_execute) and not missing,
        )

    @classmethod
    def _structured_run_reference_face_matching(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        return cls._facesync_plan(decision, args, risk_flags)

    _structured_classify_photos_by_reference = _structured_run_reference_face_matching
    _structured_prepare_facesync_pipeline = _structured_run_reference_face_matching
    _structured_excel_to_facesync_pipeline = _structured_run_reference_face_matching

    @classmethod
    def _facesync_plan(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        table_path = cls._table_path(args)
        name_column = cls._text(args.get("name_column") or args.get("column_name"))
        reference_column = cls._text(args.get("reference_column"))
        source_folder = cls._text(args.get("source_folder"))
        source_folders = [cls._text(s) for s in (args.get("source_folders") or []) if cls._text(s)]
        destination = cls._text(args.get("destination_folder"))
        missing = []
        if not table_path:
            missing.append("missing_table_path")
        if not name_column:
            missing.append("missing_name_column")
        if not reference_column:
            missing.append("missing_reference_column")
        if not source_folder:
            missing.append("missing_source_folder")
        if not destination:
            missing.append("missing_destination_folder")
        risk_flags = cls._missing_risks(risk_flags, missing)
        action_name = "run_reference_face_matching"
        steps = [] if missing else [
            cls._step(1, "document_tools", "validate_table", {"table_path": table_path}, "Validar tabla"),
            cls._step(
                2,
                "document_tools",
                "validate_name_column",
                {"table_path": table_path, "column_name": name_column},
                "Validar columna de nombres",
            ),
            cls._step(
                3,
                "document_tools",
                "validate_reference_column",
                {"table_path": table_path, "column_name": reference_column},
                "Validar columna de referencia",
            ),
            cls._step(4, "file_tools", "validate_source_folder", {"source_folder": source_folder}, "Validar carpeta origen"),
            cls._step(
                5,
                "file_tools",
                "validate_destination_folder",
                {"destination_folder": destination},
                "Validar carpeta destino",
            ),
            cls._step(
                6,
                "facesync_tools",
                action_name,
                {
                    "table_path": table_path,
                    "name_column": name_column,
                    "reference_column": reference_column,
                    "source_folder": source_folder,
                    "source_folders": source_folders,
                    "destination_folder": destination,
                },
                "Clasificar fotos por referencia facial",
                requires_confirmation=True,
            ),
        ]
        preview = cls._preview_facesync(table_path, name_column, reference_column, source_folder, destination, source_folders)
        return cls._plan_dict(
            decision,
            steps,
            preview_required=True,
            requires_confirmation=True,
            preview_text=preview,
            risk_flags=risk_flags,
            safe_to_execute=bool(decision.safe_to_execute) and not missing,
        )

    @classmethod
    def _structured_move_item(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        target = cls._text(args.get("target"))
        destination = cls._text(args.get("destination_folder"))
        missing = []
        if not target:
            missing.append("missing_target")
        if not destination:
            missing.append("missing_destination_folder")
        risk_flags = cls._missing_risks(risk_flags, missing)
        steps = [] if missing else [
            cls._step(1, "file_tools", "move_item", {"target": target, "destination_folder": destination}, "Mover elemento")
        ]
        return cls._plan_dict(decision, steps, risk_flags=risk_flags, safe_to_execute=bool(decision.safe_to_execute) and not missing)

    @classmethod
    def _structured_copy_item(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        target = cls._text(args.get("target"))
        destination = cls._text(args.get("destination_folder"))
        missing = []
        if not target:
            missing.append("missing_target")
        if not destination:
            missing.append("missing_destination_folder")
        risk_flags = cls._missing_risks(risk_flags, missing)
        steps = [] if missing else [
            cls._step(1, "file_tools", "copy_item", {"target": target, "destination_folder": destination}, "Copiar elemento")
        ]
        return cls._plan_dict(decision, steps, risk_flags=risk_flags, safe_to_execute=bool(decision.safe_to_execute) and not missing)

    @classmethod
    def _structured_rename_item(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        target = cls._text(args.get("target"))
        new_name = cls._text(args.get("new_name"))
        missing = []
        if not target:
            missing.append("missing_target")
        if not new_name:
            missing.append("missing_new_name")
        risk_flags = cls._missing_risks(risk_flags, missing)
        steps = [] if missing else [
            cls._step(1, "file_tools", "rename_item", {"target": target, "new_name": new_name}, "Renombrar elemento")
        ]
        return cls._plan_dict(decision, steps, risk_flags=risk_flags, safe_to_execute=bool(decision.safe_to_execute) and not missing)

    @classmethod
    def _structured_delete_item(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        target = cls._text(args.get("target"))
        missing = [] if target else ["missing_target"]
        risk_flags = cls._missing_risks(risk_flags + ["destructive_action"], missing)
        steps = [] if missing else [
            cls._step(
                1,
                "file_tools",
                "delete_item",
                {"target": target},
                "Eliminar elemento",
                requires_confirmation=True,
            )
        ]
        return cls._plan_dict(
            decision,
            steps,
            preview_required=True,
            requires_confirmation=True,
            preview_text=f"Accion: borrar elemento\nObjetivo: {target}",
            risk_flags=risk_flags,
            safe_to_execute=False,
        )

    @classmethod
    def _structured_search_files(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        query = cls._text(args.get("target") or args.get("file_name") or args.get("content") or "*")
        steps = [cls._step(1, "file_tools", "search_files", {"query": query}, "Buscar archivos")]
        return cls._plan_dict(decision, steps, risk_flags=risk_flags, safe_to_execute=bool(decision.safe_to_execute))

    @classmethod
    def _structured_scan_workspace(
        cls,
        decision: FaceSyncDecision,
        args: Dict[str, Any],
        risk_flags: List[str],
    ) -> Dict[str, Any]:
        del args
        steps = [cls._step(1, "workspace_tools", "scan_workspace", {}, "Escanear workspace")]
        return cls._plan_dict(decision, steps, risk_flags=risk_flags, safe_to_execute=bool(decision.safe_to_execute))

    @classmethod
    def _structured_greeting(cls, decision: FaceSyncDecision, args: Dict[str, Any], risk_flags: List[str]) -> Dict[str, Any]:
        del args
        return cls._empty_structured_plan(cls._intent_value(decision.intent), decision.reason_summary or "Mensaje conversacional", risk_flags)

    _structured_thanks = _structured_greeting
    _structured_farewell = _structured_greeting
    _structured_unknown = _structured_greeting

    @classmethod
    def _plan_dict(
        cls,
        decision: FaceSyncDecision,
        steps: List[Dict[str, Any]],
        *,
        preview_required: bool = False,
        preview_text: str = "",
        safe_to_execute: bool = False,
        requires_confirmation: bool = False,
        risk_flags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        intent = cls._intent_value(decision.intent)
        requires_confirmation = bool(requires_confirmation or decision.requires_confirmation or intent in MASSIVE_OR_SENSITIVE_INTENTS)
        preview_required = bool(preview_required or requires_confirmation)
        return {
            "intent": intent,
            "steps": steps,
            "preview_required": preview_required,
            "preview_text": preview_text,
            "safe_to_execute": bool(safe_to_execute),
            "requires_confirmation": requires_confirmation,
            "reason_summary": decision.reason_summary or "",
            "risk_flags": cls._dedupe(risk_flags or []),
        }

    @classmethod
    def _empty_structured_plan(cls, intent: str, reason_summary: str, risk_flags: List[str]) -> StructuredActionPlan:
        return StructuredActionPlan.model_validate(
            {
                "intent": intent if intent in {item.value for item in AllowedIntent} else "unknown",
                "steps": [],
                "preview_required": False,
                "preview_text": "",
                "safe_to_execute": False,
                "requires_confirmation": False,
                "reason_summary": reason_summary,
                "risk_flags": cls._dedupe(risk_flags),
            }
        )

    @staticmethod
    def _step(
        step_id: int,
        tool_name: str,
        action: str,
        args: Dict[str, Any],
        description: str,
        *,
        requires_confirmation: bool = False,
    ) -> Dict[str, Any]:
        return StructuredActionStep.model_validate(
            {
                "step_id": step_id,
                "tool_name": tool_name,
                "action": action,
                "args": args,
                "description": description,
                "requires_confirmation": requires_confirmation,
            }
        ).model_dump()

    @staticmethod
    def _preview_create_folders(table_path: str, name_column: str, destination: str) -> str:
        return "\n".join(
            [
                f"Archivo: {table_path}",
                f"Columna de nombres: {name_column}",
                f"Destino: {destination}",
                "Accion: crear carpetas desde tabla",
            ]
        )

    @staticmethod
    def _preview_facesync(
        table_path: str,
        name_column: str,
        reference_column: str,
        source_folder: str,
        destination: str,
        source_folders: list | None = None,
    ) -> str:
        source_folders = source_folders or []
        if len(source_folders) >= 2:
            origen_line = "Carpetas origen: " + ", ".join(source_folders)
        else:
            origen_line = f"Carpeta origen: {source_folder}"
        return "\n".join(
            [
                f"Archivo: {table_path}",
                f"Columna de nombres: {name_column}",
                f"Columna referencia: {reference_column}",
                origen_line,
                f"Destino: {destination}",
                "Accion: clasificar fotos",
            ]
        )

    @classmethod
    def _coerce_decision(cls, decision: FaceSyncDecision | Dict[str, Any]) -> FaceSyncDecision:
        if isinstance(decision, FaceSyncDecision):
            return decision
        data = dict(decision or {})
        if data.get("capability"):
            data = cls._decision_payload_from_capability(data)
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
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        data["args"] = {key: value for key, value in args.items() if key in ACTION_ARG_KEYS}
        return FaceSyncDecision.model_validate(data)

    @classmethod
    def _decision_payload_from_capability(cls, route: Dict[str, Any]) -> Dict[str, Any]:
        capability = str(route.get("capability") or "").strip()
        operation = str(route.get("operation") or "").strip()
        mode = str(route.get("mode") or "").strip()
        items = route.get("items") if isinstance(route.get("items"), list) else []
        first = items[0] if items and isinstance(items[0], dict) else {}
        route_args = dict(route.get("args") or {})
        args: Dict[str, Any] = {}
        intent = str(route.get("intent") or "unknown")
        requires_confirmation = bool(route.get("requires_confirmation") or route.get("preview_required"))
        safe_to_execute = capability not in {"clarification", ""} and not requires_confirmation

        if capability == "file_actions":
            if operation == "create" and mode == "single":
                intent = "create_folder" if intent == "unknown" else intent
                if intent not in {"create_folder", "create_file"}:
                    intent = "create_folder"
                name_key = "file_name" if intent == "create_file" else "folder_name"
                args[name_key] = route_args.get(name_key) or first.get("name") or route.get(name_key)
                args["destination_folder"] = route_args.get("destination_folder") or route.get("destination_folder") or ""
            elif operation == "create" and mode == "batch":
                intent = "create_multiple_folders"
                args["base_name"] = route_args.get("base_name") or first.get("name")
                args["quantity"] = route_args.get("quantity") or first.get("quantity")
                args["destination_folder"] = route_args.get("destination_folder") or route.get("destination_folder") or ""
            elif operation == "create" and mode == "from_document":
                intent = "create_folders_from_table"
                args["table_path"] = route_args.get("table_path") or route.get("table_path")
                args["name_column"] = route_args.get("name_column") or route.get("name_column")
                args["destination_folder"] = route_args.get("destination_folder") or route.get("destination_folder") or ""
                requires_confirmation = True
                safe_to_execute = False
            elif operation in {"move", "copy"}:
                intent = "move_item" if operation == "move" else "copy_item"
                args["target"] = route_args.get("target") or first.get("source") or first.get("target")
                args["destination_folder"] = route_args.get("destination_folder") or route.get("destination_folder") or ""
            elif operation == "rename":
                intent = "rename_item"
                args["target"] = route_args.get("target") or first.get("source") or first.get("target")
                args["new_name"] = route_args.get("new_name") or first.get("new_name")
            elif operation == "delete":
                intent = "delete_item"
                args["target"] = route_args.get("target") or first.get("target") or first.get("source")
                requires_confirmation = True
                safe_to_execute = False

        elif capability == "document_understanding":
            intent = "read_document"
            args["table_path"] = route_args.get("table_path") or route.get("table_path") or route.get("path")

        elif capability == "face_recognition":
            intent = intent if intent in {"run_reference_face_matching", "classify_photos_by_reference"} else "run_reference_face_matching"
            args["table_path"] = route_args.get("table_path") or route.get("table_path")
            args["name_column"] = route_args.get("name_column") or route.get("name_column")
            args["reference_column"] = route_args.get("reference_column") or route.get("reference_column")
            args["source_folder"] = route_args.get("source_folder") or route.get("source_folder")
            args["destination_folder"] = route_args.get("destination_folder") or route.get("destination_folder")
            requires_confirmation = True
            safe_to_execute = False

        elif capability == "search_workspace":
            intent = intent if intent in {"search_files", "scan_workspace"} else "search_files"
            args = route_args

        return {
            "intent": intent,
            "confidence": float(route.get("confidence") or 0.0),
            "args": {key: value for key, value in args.items() if key in ACTION_ARG_KEYS},
            "requires_clarification": False,
            "safe_to_execute": bool(route.get("safe_to_execute", safe_to_execute)),
            "requires_confirmation": requires_confirmation,
            "reason_summary": route.get("reason_summary") or route.get("reason") or "Capacidad normalizada para planear.",
            "risk_flags": route.get("risk_flags") or [],
        }

    @staticmethod
    def _intent_value(intent: Any) -> str:
        return intent.value if hasattr(intent, "value") else str(intent or "unknown")

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @classmethod
    def _table_path(cls, args: Dict[str, Any]) -> str:
        return cls._text(args.get("table_path") or args.get("excel_name"))

    @classmethod
    def _missing_risks(cls, risk_flags: List[str], missing: List[str]) -> List[str]:
        if missing:
            risk_flags = list(risk_flags) + ["missing_required_args"] + missing
        return cls._dedupe(risk_flags)

    @staticmethod
    def _dedupe(values: List[str]) -> List[str]:
        result: List[str] = []
        seen = set()
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                result.append(text)
                seen.add(text)
        return result

    # ------------------------------------------------------------------
    # Legacy LocalCommandRouter planning. This keeps existing runtime code
    # working until the structured execution pipeline is wired in later.
    # ------------------------------------------------------------------

    @classmethod
    def _build_legacy(cls, interpretation: Dict[str, Any], context: Any = None) -> ActionPlan:
        intent = interpretation.get("intent", "unknown")
        confidence = float(interpretation.get("confidence", 0.0) or 0.0)
        args = dict(interpretation.get("args") or {})
        plan = ActionPlan(intent=intent, confidence=confidence, args=args, reason=interpretation.get("reason", ""))

        if interpretation.get("needs_clarification"):
            plan.needs_clarification = True
            plan.question = interpretation.get("question", "")
            return plan

        builder = getattr(cls, f"_legacy_{intent}", None)
        if not builder:
            plan.needs_clarification = True
            plan.question = "No tengo claro que accion local quieres hacer."
            return plan
        return builder(plan, args, context)

    @classmethod
    def _context_get(cls, context: Any, key: str):
        if not context:
            return None
        getter = getattr(context, "get_context", None)
        if callable(getter):
            return getter(key)
        if isinstance(context, dict):
            return context.get(key)
        return None

    @classmethod
    def _relative_to_project(cls, value: str, context: Any) -> str:
        value = str(value or "").strip()
        if not value:
            return ""
        project_root = cls._context_get(context, "project_root") or cls._context_get(context, "workspace_actual")
        if not project_root:
            return value
        try:
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                cleaned = value.replace("\\", "/").strip("/\\")
                return "" if cleaned in ("", ".") else cleaned
            rel = candidate.resolve(strict=False).relative_to(Path(project_root).resolve(strict=False))
            rel_text = str(rel).replace("\\", "/")
            return "" if rel_text in ("", ".") else rel_text
        except Exception:
            return value.replace("\\", "/")

    @classmethod
    def _active_destination(cls, context: Any) -> str:
        active = cls._context_get(context, "active_path") or ""
        workspace = cls._context_get(context, "workspace_actual") or cls._context_get(context, "project_root") or ""
        if active and workspace and str(active).rstrip("/\\").lower() == str(workspace).rstrip("/\\").lower():
            return ""
        return cls._relative_to_project(active, context) if active else ""

    @classmethod
    def _default_creation_destination(cls, context: Any) -> str:
        resolver = getattr(context, "resolve_default_destination", None)
        if callable(resolver):
            resolved = resolver()
            if resolved:
                return cls._relative_to_project(resolved, context)
        destination = (
            cls._context_get(context, "default_output_folder")
            or cls._context_get(context, "facesync_workspace")
            or cls._context_get(context, "ultima_carpeta_destino")
        )
        return cls._relative_to_project(destination, context) if destination else ""

    @classmethod
    def _creation_destination(cls, args: Dict[str, Any], context: Any, *, key: str = "destination_folder") -> str:
        destination = args.get(key) or args.get("destination") or ""
        return cls._relative_to_project(destination, context) if destination else cls._default_creation_destination(context)

    @classmethod
    def _destination_label(cls, destination: str, context: Any) -> str:
        destination = str(destination or "").strip().replace("\\", "/")
        if not destination:
            return "carpeta principal"
        active = cls._active_destination(context)
        default = cls._default_creation_destination(context)
        if active and destination.rstrip("/") == active.rstrip("/"):
            return "aqui"
        if default and destination.rstrip("/") == default.rstrip("/"):
            return Path(destination).name or destination
        return destination

    @staticmethod
    def _join_path(destination: str, name: str) -> str:
        destination = str(destination or "").strip().strip("/\\")
        name = str(name or "").strip().strip("/\\")
        if destination and name:
            return str(Path(destination) / name).replace("\\", "/")
        return name or destination

    @classmethod
    def _legacy_missing(cls, plan: ActionPlan, question: str) -> ActionPlan:
        plan.needs_clarification = True
        plan.question = question
        return plan

    @classmethod
    def _legacy_create_folder(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        name = args.get("folder_name") or ""
        if not name:
            return cls._legacy_missing(plan, "Que nombre quieres para la carpeta?")
        destination = cls._creation_destination(args, context, key="destination_folder")
        plan.steps.append(
            ActionStep(
                "crear_carpeta",
                {
                    "path": cls._join_path(destination, name),
                    "folder_name": name,
                    "destination": destination,
                    "destination_label": cls._destination_label(destination, context),
                },
            )
        )
        return plan

    @classmethod
    def _legacy_create_multiple_folders(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        quantity = args.get("quantity")
        base_name = args.get("base_name") or ""
        if not quantity:
            return cls._legacy_missing(plan, "Cuantas carpetas quieres crear?")
        if not base_name:
            return cls._legacy_missing(plan, "Con que nombre base quieres que las cree? Por ejemplo: fotos_01, fotos_02...")
        destination = cls._creation_destination(args, context, key="destination")
        plan.steps.append(
            ActionStep(
                "crear_multiples_carpetas",
                {
                    "quantity": int(quantity),
                    "base_name": base_name,
                    "destination": destination,
                    "destination_label": cls._destination_label(destination, context),
                },
            )
        )
        return plan

    @classmethod
    def _legacy_create_file(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        name = args.get("file_name") or ""
        if not name:
            return cls._legacy_missing(plan, "Que nombre quieres para el archivo?")
        destination = cls._creation_destination(args, context, key="destination_folder")
        plan.steps.append(
            ActionStep(
                "crear_archivo",
                {
                    "path": cls._join_path(destination, name),
                    "file_name": name,
                    "destination": destination,
                    "destination_label": cls._destination_label(destination, context),
                    "content": args.get("content") or "",
                },
            )
        )
        return plan

    @classmethod
    def _legacy_read_document(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        del context
        document_name = args.get("document_name") or args.get("table_path") or args.get("excel_name") or args.get("file_name") or ""
        if not document_name:
            return cls._legacy_missing(plan, "Que archivo quieres que lea?")
        plan.steps.append(ActionStep("leer_documento", {"path": document_name, "document_type": args.get("document_type") or ""}))
        return plan

    @classmethod
    def _legacy_create_folders_from_excel(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        destination = cls._creation_destination(args, context, key="destination_folder")
        plan.steps.extend(
            [
                ActionStep("resolver_excel", {"hint": args.get("table_path") or args.get("excel_name") or args.get("excel_path") or ""}),
                ActionStep("leer_excel", {}),
                ActionStep("detectar_columnas", {"name_column": args.get("column_name") or args.get("name_column") or "", "reference_column": ""}),
                ActionStep("crear_carpetas_desde_excel", {"destination": destination, "column": args.get("column_name") or args.get("name_column") or ""}),
            ]
        )
        return plan

    _legacy_create_folders_from_table = _legacy_create_folders_from_excel

    @classmethod
    def _legacy_excel_to_facesync_pipeline(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        destination = args.get("destination_folder") or cls._active_destination(context)
        plan.steps.extend(
            [
                ActionStep("resolver_excel", {"hint": args.get("table_path") or args.get("excel_name") or args.get("excel_path") or ""}),
                ActionStep("leer_excel", {}),
                ActionStep(
                    "detectar_columnas",
                    {
                        "name_column": args.get("name_column") or "",
                        "reference_column": args.get("reference_column") or "",
                        "require_reference": True,
                    },
                ),
                ActionStep("resolver_carpeta_fotos", {"hint": args.get("source_folder") or ""}),
                ActionStep("crear_carpetas_desde_excel", {"destination": destination, "column": args.get("name_column") or ""}),
                ActionStep("ejecutar_facesync", {"destination": destination}),
            ]
        )
        return plan

    _legacy_prepare_facesync_pipeline = _legacy_excel_to_facesync_pipeline

    @classmethod
    def _legacy_run_facesync(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        destination = args.get("destination_folder") or cls._active_destination(context)
        plan.steps.extend(
            [
                ActionStep("resolver_excel", {"hint": args.get("table_path") or args.get("excel_name") or args.get("excel_path") or ""}),
                ActionStep("leer_excel", {}),
                ActionStep(
                    "detectar_columnas",
                    {
                        "name_column": args.get("name_column") or "",
                        "reference_column": args.get("reference_column") or "",
                        "require_reference": True,
                    },
                ),
                ActionStep("resolver_carpeta_fotos", {"hint": args.get("source_folder") or ""}),
                ActionStep("ejecutar_facesync", {"destination": destination}),
            ]
        )
        return plan

    _legacy_run_reference_face_matching = _legacy_run_facesync
    _legacy_classify_photos_by_reference = _legacy_run_facesync

    @classmethod
    def _legacy_move_item(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        del context
        source = args.get("source") or args.get("target") or ""
        destination = args.get("destination") or args.get("destination_folder") or ""
        if not source:
            return cls._legacy_missing(plan, "Que archivo o carpeta quieres mover?")
        if not destination:
            return cls._legacy_missing(plan, "A que carpeta quieres moverlo?")
        plan.steps.append(ActionStep("mover", {"source": source, "destination": destination}))
        return plan

    @classmethod
    def _legacy_copy_item(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        del context
        source = args.get("source") or args.get("target") or ""
        destination = args.get("destination") or args.get("destination_folder") or ""
        if not source:
            return cls._legacy_missing(plan, "Que archivo o carpeta quieres copiar?")
        if not destination:
            return cls._legacy_missing(plan, "A que carpeta quieres copiarlo?")
        plan.steps.append(ActionStep("copiar", {"source": source, "destination": destination}))
        return plan

    @classmethod
    def _legacy_rename_item(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        del context
        target = args.get("target") or ""
        new_name = args.get("new_name") or ""
        if not target:
            return cls._legacy_missing(plan, "No tengo claro que elemento quieres renombrar.")
        if not new_name:
            return cls._legacy_missing(plan, "Que nombre nuevo quieres usar?")
        plan.steps.append(ActionStep("renombrar", {"target": target, "new_name": new_name}))
        return plan

    @classmethod
    def _legacy_delete_item(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        del context
        target = args.get("target") or ""
        if not target:
            return cls._legacy_missing(plan, "Que archivo o carpeta quieres borrar?")
        if args.get("ambiguous") or plan.confidence < 0.90:
            return cls._legacy_missing(plan, f"Quiero confirmar antes de borrar: quieres eliminar '{target}'?")
        plan.steps.append(ActionStep("borrar", {"target": target, "recursive": bool(args.get("recursive"))}))
        return plan

    @classmethod
    def _legacy_search_files(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        del context
        query = args.get("query") or args.get("target") or "*"
        plan.steps.append(ActionStep("buscar_archivos", {"query": query, "extension": args.get("extension") or ""}))
        return plan

    @classmethod
    def _legacy_scan_workspace(cls, plan: ActionPlan, args: Dict[str, Any], context: Any) -> ActionPlan:
        del args, context
        plan.steps.append(ActionStep("escanear_workspace", {}))
        return plan

    @staticmethod
    def _as_item_list(value: Any) -> List[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split(",") if item.strip()]


__all__ = [
    "ActionPlan",
    "ActionPlanner",
    "ActionStep",
    "StructuredActionPlan",
    "StructuredActionStep",
]
