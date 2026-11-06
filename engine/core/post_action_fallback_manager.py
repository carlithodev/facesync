"""
Post-execution fallback manager for FaceSync AI.

This layer handles real tool errors after execution attempts. It records the
failure when ContextVault is available and returns a safe FallbackResult. It
does not execute replacement actions.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from core.decision_schema import FallbackResult, FaceSyncDecision
from core.pre_action_fallback_manager import PreActionFallbackManager


class PostActionFallbackManager:
    REPAIRABLE_COLUMN_ERRORS = {"column_not_found", "missing_column"}
    REPAIRABLE_FOLDER_ERRORS = {"folder_not_found", "file_not_found", "missing_folder"}
    SOFT_ERRORS = {"duplicate_exists"}
    IMAGE_ERRORS = {"deepface_error", "invalid_image"}

    def handle_tool_error(
        self,
        error: Any,
        decision_or_plan: Any,
        system_state: Any,
        context_vault: Any = None,
    ) -> FallbackResult:
        error_info = self._error_dict(error)
        decision = self._coerce_decision(decision_or_plan)
        state = PreActionFallbackManager._state_dict(system_state)
        self._save_error(context_vault, error_info, decision, state)

        error_type = error_info.get("error_type") or "unknown_tool_error"
        if error_type in self.SOFT_ERRORS:
            return FallbackResult(
                status="ready",
                repaired_decision=decision,
                reason="El elemento ya existia; se trata como resultado idempotente.",
                risk_flags=["idempotent_duplicate"],
            )

        if error_type in self.REPAIRABLE_COLUMN_ERRORS:
            self._save_failed_interpretation(context_vault, error_info, decision, state)
            return self._repair_column(error_info, decision, state)

        if error_type in self.REPAIRABLE_FOLDER_ERRORS:
            self._save_failed_interpretation(context_vault, error_info, decision, state)
            return self._repair_folder(error_info, decision, state)

        if error_type in {"destination_conflict", "conflict", "copy_conflict", "move_conflict"}:
            return FallbackResult(
                status="clarification_needed",
                repaired_decision=decision,
                question="El destino ya existe con contenido distinto. Quieres elegir otro destino o revisar el conflicto?",
                reason="Conflicto de destino seguro; no se sobrescribe.",
                risk_flags=[error_type, "destination_conflict"],
            )

        if error_type in self.IMAGE_ERRORS:
            return FallbackResult(
                status="clarification_needed",
                repaired_decision=decision,
                question="Hubo imagenes que no pude procesar. Las registro como pendientes o revisas esa carpeta?",
                reason="Error de imagen o DeepFace controlado.",
                risk_flags=[error_type, "partial_facesync_failure"],
            )

        if self._looks_like_bad_interpretation(error_info):
            self._save_failed_interpretation(context_vault, error_info, decision, state)
            return FallbackResult(
                status="retry_smart",
                repaired_decision=decision,
                reason="El error parece venir de una mala interpretacion.",
                risk_flags=["failed_interpretation_saved"],
            )

        return FallbackResult(
            status="failed",
            repaired_decision=decision,
            question="No pude completar la accion. Puedes revisar el archivo, carpeta o permisos?",
            reason=str(error_info.get("error_message") or "Error desconocido de tool."),
            risk_flags=[error_type],
        )

    def _repair_column(self, error: Dict[str, Any], decision: Optional[FaceSyncDecision], state: Dict[str, Any]) -> FallbackResult:
        if decision is None:
            return FallbackResult(status="failed", reason="No hay decision para reparar.", risk_flags=["missing_decision"])
        missing_value = error.get("column") or error.get("value") or error.get("missing_value") or ""
        columns = state.get("available_columns") or state.get("last_table_columns") or []
        status, value, matches = self._fuzzy(missing_value, columns)
        if status == "unique":
            data = decision.model_dump()
            args = data.get("args") or {}
            if args.get("reference_column") == missing_value:
                args["reference_column"] = value
            else:
                args["name_column"] = value
                args["column_name"] = value
            data["args"] = args
            return FallbackResult(
                status="repaired",
                repaired_decision=FaceSyncDecision.model_validate(data),
                reason="Columna reparada por coincidencia unica.",
                risk_flags=["column_repaired"],
            )
        if status == "ambiguous":
            return FallbackResult(
                status="clarification_needed",
                repaired_decision=decision,
                question=f"Encontre varias columnas parecidas: {', '.join(matches)}. Cual quieres usar?",
                missing_fields=["column_name"],
                risk_flags=["ambiguous_column_repair"],
            )
        return FallbackResult(
            status="clarification_needed",
            repaired_decision=decision,
            question="No encontre esa columna. Que columna quieres usar?",
            missing_fields=["column_name"],
            risk_flags=["column_not_found"],
        )

    def _repair_folder(self, error: Dict[str, Any], decision: Optional[FaceSyncDecision], state: Dict[str, Any]) -> FallbackResult:
        if decision is None:
            return FallbackResult(status="failed", reason="No hay decision para reparar.", risk_flags=["missing_decision"])
        missing_value = error.get("folder") or error.get("path") or error.get("value") or error.get("missing_value") or ""
        folders = state.get("available_folders") or []
        status, value, matches = self._fuzzy(missing_value, folders)
        if status == "unique":
            data = decision.model_dump()
            args = data.get("args") or {}
            if args.get("source_folder") == missing_value:
                args["source_folder"] = value
            elif args.get("destination_folder") == missing_value:
                args["destination_folder"] = value
            else:
                args["source_folder"] = value
            data["args"] = args
            return FallbackResult(
                status="repaired",
                repaired_decision=FaceSyncDecision.model_validate(data),
                reason="Carpeta reparada por coincidencia unica.",
                risk_flags=["folder_repaired"],
            )
        if status == "ambiguous":
            return FallbackResult(
                status="clarification_needed",
                repaired_decision=decision,
                question=f"Encontre varias carpetas parecidas: {', '.join(matches)}. Cual quieres usar?",
                missing_fields=["folder"],
                risk_flags=["ambiguous_folder_repair"],
            )
        return FallbackResult(
            status="clarification_needed",
            repaired_decision=decision,
            question="No encontre esa carpeta. Que carpeta quieres usar?",
            missing_fields=["folder"],
            risk_flags=["folder_not_found"],
        )

    def _save_error(self, vault: Any, error: Dict[str, Any], decision: Optional[FaceSyncDecision], state: Dict[str, Any]):
        if vault is None:
            return
        try:
            if not getattr(vault, "initialized", False):
                vault.initialize()
            session_id = int(state.get("session_id") or 0)
            if session_id:
                vault.save_action(
                    session_id,
                    self._intent(decision),
                    (decision.model_dump().get("args") if decision else {}),
                    result={},
                    success=False,
                    error_type=error.get("error_type") or "unknown_tool_error",
                    error_message=error.get("error_message") or "",
                )
        except Exception:
            return

    def _save_failed_interpretation(self, vault: Any, error: Dict[str, Any], decision: Optional[FaceSyncDecision], state: Dict[str, Any]):
        if vault is None:
            return
        try:
            session_id = int(state.get("session_id") or 0)
            if not session_id:
                return
            data = decision.model_dump() if decision else {}
            vault.save_failed_interpretation(
                session_id,
                str(state.get("last_user_text") or ""),
                state,
                self._intent(decision),
                data.get("args") or {},
                error.get("error_type") or "unknown_tool_error",
                assistant_response=error.get("error_message") or "",
            )
        except Exception:
            return

    @staticmethod
    def _error_dict(error: Any) -> Dict[str, Any]:
        if isinstance(error, dict):
            result = copy.deepcopy(error)
        else:
            result = {
                "error_type": getattr(error, "error_type", "") or type(error).__name__,
                "error_message": str(error),
            }
        result.setdefault("error_type", "unknown_tool_error")
        result.setdefault("error_message", result.get("error") or result.get("message") or "")
        return result

    @staticmethod
    def _coerce_decision(value: Any) -> Optional[FaceSyncDecision]:
        try:
            if isinstance(value, FaceSyncDecision):
                return value
            if hasattr(value, "model_dump") and "intent" in value.model_dump():
                data = value.model_dump()
                if "steps" in data:
                    return None
                return FaceSyncDecision.model_validate(data)
            if isinstance(value, dict) and "intent" in value and "steps" not in value:
                return FaceSyncDecision.model_validate(value)
        except Exception:
            return None
        return None

    @staticmethod
    def _intent(decision: Optional[FaceSyncDecision]) -> str:
        if decision is None:
            return "unknown"
        intent = decision.intent
        return intent.value if hasattr(intent, "value") else str(intent)

    @staticmethod
    def _looks_like_bad_interpretation(error: Dict[str, Any]) -> bool:
        text = f"{error.get('error_type', '')} {error.get('error_message', '')}".lower()
        return any(token in text for token in ("bad_intent", "interpretation", "slot", "incoherent"))

    @staticmethod
    def _fuzzy(value: Any, candidates: List[str]) -> Tuple[str, str, List[str]]:
        raw = str(value or "").strip().lower()
        if not raw or not candidates:
            return "missing", "", []
        scored = []
        raw_tokens = set(raw.replace("_", " ").split())
        for candidate in candidates:
            norm = str(candidate).lower()
            tokens = set(norm.replace("_", " ").split())
            score = 0
            if raw == norm:
                score += 100
            elif raw in norm or norm in raw:
                score += 70
            overlap = raw_tokens & tokens
            score += len(overlap) * 20
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


__all__ = ["PostActionFallbackManager"]
