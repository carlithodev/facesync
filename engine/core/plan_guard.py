"""
Semantic plan guard for FaceSync AI.

PlanGuard checks intent and slot coherence before SecurityManager validates
paths. It never executes tools and never relaxes filesystem security.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List

from core.action_planner import ActionPlanner
from core.decision_schema import ActionPlan, FallbackResult, FaceSyncDecision


class PlanGuard:
    ALLOWED_INTENTS = {
        "greeting",
        "thanks",
        "farewell",
        "create_folder",
        "create_multiple_folders",
        "create_file",
        "read_document",
        "create_folders_from_table",
        "create_folders_from_excel",
        "prepare_facesync_pipeline",
        "excel_to_facesync_pipeline",
        "run_reference_face_matching",
        "classify_photos_by_reference",
        "move_item",
        "copy_item",
        "rename_item",
        "delete_item",
        "search_files",
        "scan_workspace",
        "ask_missing_data",
        "unknown",
    }
    FACESYNC_INTENTS = {
        "prepare_facesync_pipeline",
        "excel_to_facesync_pipeline",
        "run_reference_face_matching",
        "classify_photos_by_reference",
    }
    MASSIVE_INTENTS = {
        "create_folders_from_table",
        "create_folders_from_excel",
        *FACESYNC_INTENTS,
    }
    DESTRUCTIVE_INTENTS = {"delete_item", "delete_multiple_items", "delete_folders_from_excel"}
    BAD_CREATE_FOLDER_VALUES = {"primera columna", "segunda columna", "columna foto", "valores", "registros"}
    BAD_DESTINATION_PARTS = ("columna", "usando", "referencia", "como referencia")
    VERB_TOKENS = {"acomoda", "organiza", "clasifica", "mete", "crear", "crea", "haz"}

    def validate(self, decision_or_plan: Any, system_state: Any = None, retry_count: int = 0) -> FallbackResult:
        del retry_count
        state = self._state_dict(system_state)
        plan = self._plan_from(decision_or_plan)
        if plan is None:
            return FallbackResult(status="blocked", reason="Plan invalido.", risk_flags=["invalid_plan"])

        flags = self._risk_flags(plan, state)
        if flags:
            repaired = self._guarded_plan(plan, flags)
            status = "clarification_needed" if any(flag.startswith("missing_") for flag in flags) else "blocked"
            return FallbackResult(
                status=status,
                repaired_plan=repaired,
                question=self._question(flags),
                missing_fields=self._missing_fields(flags),
                reason="PlanGuard encontro incoherencias semanticas.",
                risk_flags=flags,
            )

        intent = self._intent_value(plan.intent)
        if intent in self.MASSIVE_INTENTS or intent in self.DESTRUCTIVE_INTENTS:
            repaired = self._guarded_plan(plan, [])
            return FallbackResult(status="ready", repaired_plan=repaired, reason="Plan aprobado con preview/confirmacion.")
        return FallbackResult(status="ready", repaired_plan=plan, reason="Plan aprobado.")

    def validate_plan(self, decision_or_plan: Any, system_state: Any = None) -> FallbackResult:
        return self.validate(decision_or_plan, system_state=system_state)

    def _risk_flags(self, plan: ActionPlan, state: Dict[str, Any]) -> List[str]:
        flags: List[str] = []
        intent = self._intent_value(plan.intent)
        args = self._merged_args(plan)
        columns = state.get("available_columns") or state.get("last_table_columns") or []

        if intent not in self.ALLOWED_INTENTS:
            flags.append("intent_not_allowed")

        if intent == "create_folder" and columns:
            folder = self._norm(args.get("folder_name"))
            if folder in self.BAD_CREATE_FOLDER_VALUES or folder.startswith("columna "):
                flags.append("create_folder_conceptual_name")

        destination = self._norm(args.get("destination_folder"))
        if destination and any(part in destination for part in self.BAD_DESTINATION_PARTS):
            flags.append("suspicious_destination_folder")

        table = self._norm(args.get("table_path") or args.get("excel_name"))
        if table and any(verb in table.split() for verb in self.VERB_TOKENS):
            flags.append("suspicious_table_path")

        if intent in self.FACESYNC_INTENTS:
            name = self._norm(args.get("name_column"))
            reference = self._norm(args.get("reference_column"))
            if not args.get("table_path"):
                flags.append("missing_table_path")
            if not args.get("reference_column"):
                flags.append("missing_reference_column")
            if not args.get("source_folder"):
                flags.append("missing_source_folder")
            if not args.get("destination_folder"):
                flags.append("missing_destination_folder")
            if name and reference and name == reference:
                flags.append("same_name_and_reference_column")

        if intent in {"create_folders_from_table", "create_folders_from_excel"}:
            if not args.get("table_path"):
                flags.append("missing_table_path")
            if not args.get("name_column"):
                flags.append("missing_name_column")

        if intent == "delete_item" and not args.get("target"):
            flags.append("missing_target")

        return self._dedupe(flags)

    def _guarded_plan(self, plan: ActionPlan, flags: List[str]) -> ActionPlan:
        data = plan.model_dump()
        intent = self._intent_value(data.get("intent"))
        existing = data.get("risk_flags") or []
        data["risk_flags"] = self._dedupe(existing + flags)
        if intent in self.MASSIVE_INTENTS:
            data["preview_required"] = True
            data["requires_confirmation"] = True
            data["safe_to_execute"] = bool(data.get("safe_to_execute"))
        if intent in self.DESTRUCTIVE_INTENTS:
            data["preview_required"] = True
            data["requires_confirmation"] = True
            data["safe_to_execute"] = False
        if flags:
            data["safe_to_execute"] = False
        return ActionPlan.model_validate(data)

    @staticmethod
    def _intent_value(intent: Any) -> str:
        return intent.value if hasattr(intent, "value") else str(intent or "unknown")

    @classmethod
    def _plan_from(cls, value: Any) -> ActionPlan | None:
        try:
            if isinstance(value, ActionPlan):
                return value
            if isinstance(value, FaceSyncDecision):
                return ActionPlanner.plan(value)
            if hasattr(value, "model_dump"):
                data = value.model_dump()
                if "steps" in data:
                    return ActionPlan.model_validate(data)
                return ActionPlanner.plan(data)
            if isinstance(value, dict) and "steps" in value:
                return ActionPlan.model_validate(value)
            return ActionPlanner.plan(value)
        except Exception:
            return None

    @staticmethod
    def _merged_args(plan: ActionPlan) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for step in plan.steps:
            if isinstance(step.args, dict):
                merged.update(step.args)
        return merged

    @staticmethod
    def _state_dict(state: Any) -> Dict[str, Any]:
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

    @staticmethod
    def _norm(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
        text = re.sub(r"[^a-z0-9./\\\s-]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _question(flags: List[str]) -> str:
        if "suspicious_destination_folder" in flags:
            return "Que carpeta destino quieres usar?"
        if "same_name_and_reference_column" in flags:
            return "La columna de nombres y referencia son iguales. Cuales debo usar?"
        if "create_folder_conceptual_name" in flags:
            return "Quieres usar una columna de la tabla o crear una carpeta literal?"
        return "Necesito aclarar datos antes de ejecutar."

    @staticmethod
    def _missing_fields(flags: List[str]) -> List[str]:
        mapping = {
            "missing_table_path": "table_path",
            "missing_name_column": "name_column",
            "missing_reference_column": "reference_column",
            "missing_source_folder": "source_folder",
            "missing_destination_folder": "destination_folder",
            "missing_target": "target",
        }
        return [mapping[flag] for flag in flags if flag in mapping]

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


__all__ = ["PlanGuard"]
