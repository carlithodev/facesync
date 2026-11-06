"""
Local conversational router for FaceSync AI.

Clear file/document/FaceSync actions are interpreted and executed locally with
safe Python tools. Gemini remains a fallback for unknown or reasoning-heavy
requests, never a requirement for normal workspace operations.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from ai.openai_orchestrator import ALLOWED_OPENAI_INTENTS
from core.action_fallback_manager import ActionFallbackManager, FallbackResult
from core.action_planner import ActionPlan, ActionPlanner
from core.app_paths import filter_internal_names
from core.capability_router import CapabilityRouter
from core.column_resolver import ColumnResolver
from core.context_manager import ContextManager
from core.decision_schema import ActionPlan as StructuredActionPlan
from core.decision_schema import FaceSyncDecision, FallbackResult as StructuredFallbackResult
from core.dialogue_manager import DialogueManager
from core.domain_intent_guard import DomainIntentGuard
from core.learning_queue import LearningQueue
from core.intent_interpreter import IntentInterpreter
from core.orchestration_result import OrchestrationResult
from core.plan_guard import PlanGuard
from core.post_action_fallback_manager import PostActionFallbackManager
from core.pre_action_fallback_manager import PreActionFallbackManager
from core.response_formatter import ResponseFormatter
from core.security import SecurityManager
from core.slot_extractor import SlotExtractor
from core.text_normalizer import TextNormalizer
from core.tool_execution_gate import ToolExecutionGate
from core.workspace_location_resolver import WorkspaceLocationResolver
from tools.document_tools import DocumentCapabilities
from tools.facesync_tools import FaceSyncCapabilities
from tools.file_tools import FileCapabilities
from tools.search_tools import SearchCapabilities
from tools.workspace_tools import WorkspaceCapabilities


class LocalCommandRouter:
    NORMAL_THRESHOLD = 0.65
    PIPELINE_THRESHOLD = 0.70
    DESTRUCTIVE_THRESHOLD = 0.90
    INVALID_OPENAI_MESSAGE = "No pude interpretar la acción con seguridad. ¿Puedes indicarme el Excel, la carpeta de fotos y el destino?"
    CONFIRM_WORDS = {"si", "sí", "confirmo", "adelante", "borralo", "bórralo", "eliminalo", "elimínalo", "borralas", "bórralas", "elimina todo", "ejecutalo", "ejecútalo"}
    CANCEL_WORDS = {"no", "cancela", "cancelar", "mejor no", "detente", "para", "no lo hagas"}
    DESTRUCTIVE_INTENTS = {"delete_item", "delete_multiple_items", "delete_folders_from_excel"}
    PREVIEW_CONFIRMATION_INTENTS = {
        "create_folders_from_table",
        "create_folders_from_excel",
        "excel_to_facesync_pipeline",
        "prepare_facesync_pipeline",
        "run_facesync",
        "run_reference_face_matching",
        "classify_photos_by_reference",
        "move_multiple_items",
        "copy_multiple_items",
        "delete_item",
        "delete_multiple_items",
        "delete_folders_from_excel",
    }
    FACESYNC_INTENTS = {
        "excel_to_facesync_pipeline",
        "prepare_facesync_pipeline",
        "run_facesync",
        "run_reference_face_matching",
        "classify_photos_by_reference",
    }
    PENDING_INTENTS = {
        "create_folder",
        "create_multiple_folders",
        "create_file",
        "create_multiple_files",
        "read_document",
        "create_folders_from_excel",
        "create_folders_from_table",
        "delete_folders_from_excel",
        "run_facesync",
        "excel_to_facesync_pipeline",
        "prepare_facesync_pipeline",
        "run_reference_face_matching",
        "classify_photos_by_reference",
        "move_item",
        "move_multiple_items",
        "copy_item",
        "copy_multiple_items",
        "rename_item",
        "delete_item",
        "delete_multiple_items",
        "search_files",
    }
    STRUCTURED_LOCAL_INTENTS = {
        "create_folder",
        "create_multiple_folders",
        "create_file",
        "read_document",
        "create_folders_from_excel",
        "create_folders_from_table",
        "run_reference_face_matching",
        "classify_photos_by_reference",
        "move_item",
        "copy_item",
        "rename_item",
        "delete_item",
    }
    CONSUMED_PENDING_STATUSES = {"executing", "consumed", "completed"}
    PATH_ARG_KEYS = {"table_path", "excel_path", "excel_name", "source_folder", "destination_folder", "target", "source", "destination"}
    PATH_LIST_ARG_KEYS = {"sources", "targets"}

    def __init__(
        self,
        workspace_path: Optional[str] = None,
        context_manager: Optional[ContextManager] = None,
        async_callback: Optional[Callable[[bool, str, Dict[str, Any]], None]] = None,
        account_id: str = "default",
    ):
        self.workspace_path = str(Path(workspace_path).expanduser().resolve(strict=False)) if workspace_path else None
        self.account_id = str(account_id or "default").strip() or "default"
        self.context = context_manager or ContextManager()
        self.interpreter = IntentInterpreter()
        self.capability_router = CapabilityRouter()
        self.column_resolver = ColumnResolver()
        self.location_resolver = WorkspaceLocationResolver()
        self.planner = ActionPlanner()
        self.action_fallback = ActionFallbackManager()
        self.pre_action_fallback = PreActionFallbackManager()
        self.post_action_fallback = PostActionFallbackManager()
        self.plan_guard = PlanGuard()
        self.formatter = ResponseFormatter()
        self.domain_guard = DomainIntentGuard()
        self.dialogue = DialogueManager(self.context)
        self.async_callback = async_callback
        self._facesync_cancel_event = threading.Event()
        if self.workspace_path:
            self.context.set_project_root(self.workspace_path)

    def set_workspace(self, workspace_path: Optional[str]):
        self.workspace_path = str(Path(workspace_path).expanduser().resolve(strict=False)) if workspace_path else None
        if workspace_path:
            self.context.set_project_root(self.workspace_path)

    def set_workspace_roots(self, roots) -> None:
        """Workspace compuesto: registra varias carpetas raiz para que el
        asistente busque en todas. La primera es la primaria (compatibilidad)."""
        cleaned = [str(Path(r).expanduser().resolve(strict=False)) for r in (roots or []) if r]
        if not cleaned:
            return
        self.workspace_path = cleaned[0]
        if self.context and hasattr(self.context, "set_workspace_roots"):
            self.context.set_workspace_roots(cleaned)
        elif self.context:
            self.context.set_project_root(cleaned[0])

    def set_project_root(self, project_root: Optional[str]):
        self.set_workspace(project_root)

    def set_account_id(self, account_id: str):
        self.account_id = str(account_id or "default").strip() or "default"

    def _workspace_root(self) -> Optional[str]:
        root = self.context.get_project_root() if self.context else None
        return root or self.workspace_path

    def _app_data_root(self) -> Optional[str]:
        getter = getattr(self.context, "get_app_data_root", None)
        if callable(getter):
            return getter()
        return self.context.get_context("app_data_root") if self.context else None

    def try_handle(self, text: str) -> Optional[OrchestrationResult]:
        text = (text or "").strip()
        if not text:
            return None

        normalized = TextNormalizer.normalize(text)
        if self.context.is_pending_expired():
            self.context.clear_pending_action()

        dialogue = self.dialogue.classify_message(text, self.context.current_context)
        dialogue_result = self._handle_dialogue_result(dialogue, text=text, normalized=normalized)
        if dialogue_result:
            return dialogue_result
        if dialogue.get("clear_pending"):
            self.context.clear_pending_action()

        interpretation = self.interpreter.interpret(text, normalized, self.context)
        interpretation = self.capability_router.apply_to_interpretation(
            text,
            interpretation,
            system_state=self._fallback_state(text),
            context=self.context,
        )
        intent = interpretation.get("intent", "unknown")
        confidence = float(interpretation.get("confidence", 0.0) or 0.0)
        source = interpretation.get("source", "rules")

        if intent == "create_folder":
            args = interpretation.get("args") or {}
            print(f"[INTENT] source={source} intent=create_folder confidence={confidence:.2f}")
            print(
                "[SLOTS] "
                f"folder_name={args.get('folder_name', '')} "
                f"destination_folder={args.get('destination_folder', '')}"
            )

        elif intent in ("create_multiple_folders", "create_multiple_files"):
            args = interpretation.get("args") or {}
            print(f"[INTENT] source={source} intent={intent} confidence={confidence:.2f}")
            print(
                "[SLOTS] "
                f"quantity={args.get('quantity', '')} "
                f"base_name={args.get('base_name', '')} "
                f"destination={args.get('destination', '')}"
            )
        else:
            print(f"[INTENT] source={source} intent={intent} confidence={confidence:.2f}")

        if intent == "analyze_or_explain":
            return None

        if intent == "unknown":
            # La capa local no adivina. El orquestador con contexto amplio puede
            # recuperar faltas de ortografia y referencias humanas; la accion
            # resultante seguira pasando por PlanGuard/SecurityManager/ToolGate.
            self._log_unhandled_intent(text, normalized, interpretation, action_taken="allowed_orchestrator")
            return None

        threshold = self._threshold_for(intent)
        if confidence < threshold:
            self._log_unhandled_intent(text, normalized, interpretation, action_taken="allowed_orchestrator")
            return None

        missing_workspace = self._require_workspace()
        if missing_workspace:
            return missing_workspace

        if intent in self.STRUCTURED_LOCAL_INTENTS:
            decision = self._decision_from_local_interpretation(interpretation)
            if decision is not None:
                return self._run_structured_pipeline(text, decision, source=source)

        repaired_interpretation, fallback_response, fallback = self._apply_action_fallback(
            text,
            interpretation,
            source=source,
            used_openai=False,
        )
        if fallback_response:
            if fallback.status == "retry_smart":
                return None
            return fallback_response
        interpretation = repaired_interpretation or interpretation
        intent = interpretation.get("intent", "unknown")
        args = interpretation.get("args") or {}

        facesync_clarification = self._facesync_missing_clarification(
            intent,
            args,
            source=source,
            used_openai=False,
        )
        if facesync_clarification:
            return facesync_clarification

        if interpretation.get("needs_clarification"):
            self._store_pending_action_if_relevant(
                intent,
                args,
                source=source,
                question=interpretation.get("question") or "",
            )
            return OrchestrationResult(
                handled=True,
                message=self.formatter.clarification(interpretation.get("question") or "Me falta un dato para continuar."),
                action=intent,
                requires_clarification=True,
                data={"interpretation": interpretation},
            )

        plan = self.planner.build(interpretation, self.context)
        if intent == "create_folder":
            for step in plan.steps:
                if step.tool == "crear_carpeta":
                    print(f"[PLAN] crear_carpeta path={step.args.get('path', '')}")
        if intent in ("create_multiple_folders", "create_multiple_files"):
            for step in plan.steps:
                print(f"[PLAN] {step.tool} args={step.args}")
        self.context.remember_action(
            "plan",
            plan=plan.as_list(),
            intent=intent,
        )

        if plan.needs_clarification:
            if not plan.question:
                guarded = self._local_domain_clarification(normalized, interpretation)
                if guarded:
                    return guarded
                return None
            self._store_pending_action_if_relevant(
                intent,
                args,
                source=source,
                question=plan.question,
                plan=plan,
            )
            return OrchestrationResult(
                handled=True,
                message=self.formatter.clarification(plan.question),
                action=intent,
                requires_clarification=True,
                data={"interpretation": interpretation, "plan": plan.as_list()},
            )

        if intent in self.DESTRUCTIVE_INTENTS:
            return self._ask_destructive_confirmation(intent, args, source=source, plan=plan)

        preview = self._maybe_ask_action_preview(intent, args, source=source, plan=plan, used_openai=False)
        if preview:
            return preview

        execution = self.execute_plan(plan)
        message = self.formatter.format(execution)
        if not execution.get("success"):
            self.context.update_context("last_failed_action", intent)
            self.context.update_context("last_error_type", execution.get("error") or "execution")

        if execution.get("requires_clarification"):
            self._store_pending_action_if_relevant(
                intent,
                self._merge_args_with_execution_data(args, execution.get("data") or {}),
                source=source,
                question=execution.get("question") or "",
                plan=plan,
                missing_slot=execution.get("missing_slot") or "",
            )
            return OrchestrationResult(
                handled=True,
                message=message,
                action=intent,
                refresh=False,
                requires_clarification=True,
                data={
                    "interpretation": interpretation,
                    "plan": plan.as_list(),
                    "execution": execution,
                },
            )

        self._remember_execution(execution, plan)
        self.context.clear_pending_action()
        return OrchestrationResult.ok(
            message,
            action=intent,
            refresh=bool(execution.get("refresh")),
            data={
                "interpretation": interpretation,
                "plan": plan.as_list(),
                "execution": execution,
            },
        )

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def _threshold_for(self, intent: str) -> float:
        if intent in self.DESTRUCTIVE_INTENTS:
            return self.DESTRUCTIVE_THRESHOLD
        if intent in self.FACESYNC_INTENTS:
            return self.PIPELINE_THRESHOLD
        return self.NORMAL_THRESHOLD

    def _fallback_state(self, user_text: str) -> Dict[str, Any]:
        state = dict(getattr(self.context, "current_context", {}) or {})
        state["_user_text"] = user_text
        if "recent_user_messages" not in state:
            messages = getattr(self.context, "messages", [])
            state["recent_user_messages"] = [
                item.get("content", "")
                for item in list(messages)[-10:]
                if item.get("role") == "user"
            ]
        return state

    def _apply_action_fallback(
        self,
        user_text: str,
        interpretation: Dict[str, Any],
        *,
        source: str,
        used_openai: bool,
        allow_destructive: bool = False,
    ) -> tuple[Optional[Dict[str, Any]], Optional[OrchestrationResult], FallbackResult]:
        decision = dict(interpretation or {})
        decision["user_text"] = user_text
        if allow_destructive:
            decision["_allow_destructive"] = True

        fallback = self.action_fallback.analyze_plan(decision, self._fallback_state(user_text))
        repaired = fallback.repaired_decision or decision
        intent = repaired.get("intent", "unknown")
        args = repaired.get("args") or {}

        if fallback.status == "ready":
            return repaired, None, fallback

        self.context.update_context(
            "last_interpretation_error",
            {"type": "fallback", "status": fallback.status, "reason": fallback.reason, "risk_flags": fallback.risk_flags},
        )

        if fallback.status == "retry_smart":
            return None, OrchestrationResult(
                handled=True,
                message="Necesito revisar ese plan con el modelo smart antes de ejecutar.",
                action="retry_smart",
                requires_clarification=True,
                data={
                    "interpretation": repaired,
                    "fallback_status": fallback.status,
                    "fallback_reason": fallback.reason,
                    "risk_flags": fallback.risk_flags,
                    "used_openai": used_openai,
                },
            ), fallback

        if "destructive_requires_confirmation" in fallback.risk_flags:
            return None, self._ask_destructive_confirmation(
                intent,
                args,
                source=source,
                plan=None,
                used_openai=used_openai,
            ), fallback

        if fallback.status == "clarification_needed":
            question = fallback.question or self.action_fallback.build_clarification(fallback.missing_fields, self.context.current_context)
            self._store_pending_action_if_relevant(
                intent,
                args,
                source=source,
                question=question,
                missing_slot=(fallback.missing_fields or [""])[0],
            )
            return None, OrchestrationResult(
                handled=True,
                message=self.formatter.clarification(question),
                action=intent,
                requires_clarification=True,
                data={
                    "interpretation": repaired,
                    "fallback_status": fallback.status,
                    "fallback_reason": fallback.reason,
                    "risk_flags": fallback.risk_flags,
                    "used_openai": used_openai,
                },
            ), fallback

        message = fallback.question or "No puedo ejecutar ese plan con seguridad."
        return None, OrchestrationResult(
            handled=True,
            message=message,
            action=intent,
            requires_clarification=True,
            data={
                "interpretation": repaired,
                "fallback_status": fallback.status,
                "fallback_reason": fallback.reason,
                "risk_flags": fallback.risk_flags,
                "used_openai": used_openai,
            },
        ), fallback

    def _local_domain_clarification(
        self,
        normalized,
        interpretation: Optional[Dict[str, Any]] = None,
    ) -> Optional[OrchestrationResult]:
        if self.domain_guard.is_analysis_request(normalized):
            return None
        if not self.domain_guard.is_local_domain(normalized):
            return None

        missing_workspace = self._require_workspace()
        if missing_workspace:
            return missing_workspace

        question = self.domain_guard.clarification(normalized, self.context)
        self._log_unhandled_intent(
            normalized.original,
            normalized,
            interpretation or {},
            action_taken="asked_clarification",
        )
        return OrchestrationResult(
            handled=True,
            message=self.formatter.clarification(question),
            action=(interpretation or {}).get("intent", "local_domain_clarification"),
            requires_clarification=True,
            data={"interpretation": interpretation or {}, "local_domain_guard": True},
        )

    def _handle_dialogue_result(self, dialogue: Dict[str, Any], *, text: str = "", normalized=None) -> Optional[OrchestrationResult]:
        message_type = dialogue.get("message_type")
        if dialogue.get("clear_pending") and message_type in {"cancellation", "command"}:
            pending_before_clear = getattr(self.context, "get_pending_action", lambda: None)()
            if (
                isinstance(pending_before_clear, dict)
                and pending_before_clear.get("pending_id")
                and hasattr(self.context, "update_pending_action_status_in_vault")
            ):
                self.context.update_pending_action_status_in_vault(pending_before_clear.get("pending_id"), "canceled")
                pending_before_clear["pending_status_finalized"] = True
                self.context.current_context["pending_action"] = pending_before_clear
            self.context.clear_pending_action()

        if message_type == "ambiguous" and self._ambiguous_can_use_facesync_context(normalized):
            return None

        if message_type in {"greeting", "farewell", "thanks", "ambiguous"}:
            return OrchestrationResult(
                handled=True,
                message=dialogue.get("response") or "",
                action=message_type,
                requires_clarification=(message_type == "ambiguous"),
                data={"dialogue": dialogue},
            )

        if message_type == "cancellation":
            return OrchestrationResult(
                handled=True,
                message=dialogue.get("response") or "No hay ninguna acción pendiente.",
                action="cancellation",
                data={"dialogue": dialogue},
            )

        if message_type == "confirmation":
            pending = dialogue.get("pending_action")
            if not pending:
                consumed = self.context.get_context("last_consumed_pending_action") if self.context else None
                if isinstance(consumed, dict):
                    return self._already_executed_pending_response(consumed)
                return OrchestrationResult(
                    handled=True,
                    message=dialogue.get("response") or "¿Qué acción quieres que confirme?",
                    action="confirmation",
                    requires_clarification=True,
                    data={"dialogue": dialogue},
                )
            return self._execute_pending_action(pending, confirmed=True)

        if message_type == "pending_answer":
            completed = dialogue.get("completed_action")
            if completed:
                if (
                    completed.get("location_selection_resolved")
                    and completed.get("pending_id")
                    and hasattr(self.context, "update_pending_action_status_in_vault")
                ):
                    self.context.update_pending_action_status_in_vault(completed.get("pending_id"), "resolved")
                    completed["pending_status_finalized"] = True
                preview_update = self._update_pending_preview_from_text(completed, text, normalized)
                if preview_update:
                    return preview_update
                return self._execute_pending_action(completed, confirmed=False)
            return OrchestrationResult(
                handled=True,
                message=dialogue.get("response") or "Me falta un dato para continuar.",
                action="pending_answer",
                requires_clarification=True,
                data={"dialogue": dialogue},
            )

        return None

    def _ambiguous_can_use_facesync_context(self, normalized) -> bool:
        tokens = set(getattr(normalized, "tokens", []) or [])
        text = getattr(normalized, "normalized", "") or ""
        if "identifica" not in tokens or "ahora" not in tokens:
            return False
        required = ("last_table_path", "last_name_column", "last_reference_column", "last_source_folder", "last_destination_folder")
        return any(self.context.get_context(key) for key in required)

    def _update_pending_preview_from_text(self, pending: Dict[str, Any], text: str, normalized) -> Optional[OrchestrationResult]:
        if not pending or not pending.get("requires_confirmation") or pending.get("destructive"):
            return None
        if not text or self._is_confirm(TextNormalizer.normalize_for_matching(text)):
            return None
        intent = pending.get("intent") or "unknown"
        if intent not in self.PREVIEW_CONFIRMATION_INTENTS:
            return None
        # Multi-origen: este atajo conserva el plan previo (sin source_folders).
        # Si la respuesta aporta varias carpetas, NO usar el atajo: dejar que el
        # pipeline estructurado reconstruya el plan con TODAS las carpetas.
        if len([s for s in (pending.get("args") or {}).get("source_folders") or [] if s]) >= 2:
            return None
        if normalized is None:
            normalized = TextNormalizer.normalize(text)

        args = dict(pending.get("args") or {})
        extracted = SlotExtractor.extract(intent, text, normalized, self.context)
        meaningful = {
            key: value
            for key, value in (extracted or {}).items()
            if key in {
                "table_path",
                "excel_path",
                "excel_name",
                "name_column",
                "column_name",
                "reference_column",
                "source_folder",
                "destination_folder",
                "destination",
                "source",
                "sources",
                "targets",
            }
            and value not in (None, "", [])
        }
        pending_slot = str(pending.get("missing_slot") or "").strip()
        pending_fields = [str(item).strip() for item in (pending.get("missing_fields") or []) if str(item).strip()]
        if not pending_slot and len(pending_fields) == 1:
            pending_slot = pending_fields[0]
        if pending_slot:
            aliases = {
                "source_folder": {"source_folder", "source"},
                "destination_folder": {"destination_folder", "destination"},
                "table_path": {"table_path", "excel_path", "excel_name"},
                "name_column": {"name_column", "column_name"},
                "reference_column": {"reference_column"},
                "folder_name": {"folder_name"},
                "target": {"target", "source"},
            }.get(pending_slot, {pending_slot})
            meaningful = {key: value for key, value in meaningful.items() if key in aliases}
            if pending_slot == "source_folder" and not meaningful:
                meaningful = {"source_folder": text.strip()}
        if not meaningful:
            return None

        updated_args = self._merge_args_with_execution_data(args, meaningful)
        if updated_args == args:
            return None

        question = self._preview_question(intent, updated_args)
        pending = dict(pending)
        pending["args"] = updated_args
        pending["question"] = question
        pending["created_at"] = datetime.now(timezone.utc).isoformat()
        self.context.set_pending_action(pending)
        return OrchestrationResult(
            handled=True,
            message=question,
            action=intent,
            requires_clarification=True,
            data={"pending_action": pending, "preview_required": True, "preview_updated": True},
        )

    def _pending_already_consumed(self, pending: Dict[str, Any]) -> bool:
        status = str((pending or {}).get("pending_status") or (pending or {}).get("status") or "").lower()
        return status in self.CONSUMED_PENDING_STATUSES

    def _mark_pending_executing(self, pending: Dict[str, Any]) -> Dict[str, Any]:
        pending = dict(pending or {})
        pending["pending_status"] = "executing"
        pending["consumed_at"] = datetime.now(timezone.utc).isoformat()
        pending_id = pending.get("pending_id")
        if pending_id and hasattr(self.context, "update_pending_action_status_in_vault"):
            self.context.update_pending_action_status_in_vault(pending_id, "executing")
        self.context.set_pending_action(pending)
        self.context.update_context(
            "last_consumed_pending_action",
            {
                "pending_id": pending_id,
                "intent": pending.get("intent"),
                "args": pending.get("args") or {},
                "consumed_at": pending.get("consumed_at"),
            },
        )
        return pending

    @staticmethod
    def _already_executed_pending_response(pending: Dict[str, Any]) -> OrchestrationResult:
        intent = (pending or {}).get("intent") or "pending_action"
        return OrchestrationResult(
            handled=True,
            message="Esa accion ya fue confirmada o ejecutada. No la repetire.",
            action=intent,
            requires_clarification=False,
            data={"pending_action": pending, "already_consumed": True},
        )

    def _execute_pending_action(self, pending: Dict[str, Any], *, confirmed: bool) -> OrchestrationResult:
        if confirmed and self._pending_already_consumed(pending):
            return self._already_executed_pending_response(pending)

        if pending.get("pipeline") == "structured" or pending.get("structured_plan"):
            return self._execute_structured_pending_action(pending, confirmed=confirmed)

        intent = pending.get("intent") or "unknown"
        args = dict(pending.get("args") or {})
        requires_confirmation = bool(pending.get("requires_confirmation") or pending.get("destructive"))
        missing_slot = self._infer_missing_slot(intent, args)

        if missing_slot:
            pending = dict(pending)
            pending["args"] = args
            pending["missing_slot"] = missing_slot
            pending["question"] = self._question_for_missing_slot(intent, missing_slot)
            self.context.set_pending_action(pending)
            return OrchestrationResult(
                handled=True,
                message=pending["question"],
                action=intent,
                requires_clarification=True,
                data={"pending_action": pending},
            )

        if requires_confirmation and not confirmed:
            self.context.set_pending_action(pending)
            return OrchestrationResult(
                handled=True,
                message=self._confirmation_question(intent, args),
                action=intent,
                requires_clarification=True,
                data={"pending_action": pending},
            )

        interpretation = {
            "intent": intent,
            "confidence": max(float(pending.get("confidence") or 0.95), 0.95),
            "needs_clarification": False,
            "question": "",
            "args": args,
            "reason": "Accion completada desde una respuesta pendiente.",
            "safe_to_execute": True,
        }
        if requires_confirmation and confirmed:
            pending = self._mark_pending_executing(pending)
        return self._execute_interpreted_action(
            interpretation,
            source=pending.get("source") or pending.get("origin") or "local",
            used_openai=pending.get("source") == "openai",
            allow_destructive=bool(requires_confirmation and confirmed),
        )

    def _facesync_missing_clarification(
        self,
        intent: str,
        args: Dict[str, Any],
        *,
        source: str,
        used_openai: bool = False,
    ) -> Optional[OrchestrationResult]:
        if intent not in self.FACESYNC_INTENTS:
            return None
        missing = self._facesync_missing_slots(args)
        if not missing:
            return None
        question = self._facesync_question(missing)
        pending = self._store_pending_action_if_relevant(
            intent,
            args,
            source=source,
            question=question,
            missing_slot=missing[0],
        )
        return OrchestrationResult(
            handled=True,
            message=self.formatter.clarification(question),
            action=intent,
            requires_clarification=True,
            data={"pending_action": pending, "used_openai": used_openai},
        )

    def _facesync_missing_slots(self, args: Dict[str, Any]) -> List[str]:
        missing: List[str] = []
        if not self._slot_value(args, "excel_path", use_context=True):
            missing.append("excel_path")
        if not self._slot_value(args, "source_folder", use_context=True):
            missing.append("source_folder")
        if not self._slot_value(args, "destination_folder", use_context=True):
            missing.append("destination_folder")
        return missing

    @staticmethod
    def _facesync_question(missing_slots: List[str]) -> str:
        missing = set(missing_slots or [])
        if {"excel_path", "source_folder", "destination_folder"}.issubset(missing):
            return (
                "Te entendi: quieres clasificar fotos por referencia. Me falta saber que Excel o CSV usar, "
                "que carpeta contiene las fotos y donde guardar el resultado."
            )
        if missing == {"excel_path"}:
            return "Que Excel o CSV quieres usar?"
        if missing == {"source_folder"}:
            return "Que carpeta contiene las fotos originales?"
        if missing == {"destination_folder"}:
            return "Donde quieres guardar las fotos clasificadas?"
        parts = []
        if "excel_path" in missing:
            parts.append("que Excel o CSV usar")
        if "source_folder" in missing:
            parts.append("que carpeta contiene las fotos")
        if "destination_folder" in missing:
            parts.append("donde guardar el resultado")
        if "name_column" in missing:
            parts.append("que columna contiene los nombres")
        if "reference_column" in missing:
            parts.append("que columna contiene la foto o codigo de referencia")
        return "Te entendi: quieres clasificar fotos por referencia. Me falta saber " + ", ".join(parts) + "."

    def _infer_missing_slot(self, intent: str, args: Dict[str, Any]) -> str:
        for slot in self._required_slots_for(intent):
            if not self._slot_value(args, slot, use_context=False):
                return slot
        return ""

    @classmethod
    def _required_slots_for(cls, intent: str) -> List[str]:
        required = {
            "create_folder": ["folder_name"],
            "create_multiple_folders": ["quantity", "base_name"],
            "create_file": ["file_name"],
            "create_multiple_files": ["quantity", "base_name"],
            "read_document": ["document_name"],
            "rename_item": ["target", "new_name"],
            "move_item": ["source", "destination"],
            "move_multiple_items": ["sources", "destination"],
            "copy_item": ["source", "destination"],
            "copy_multiple_items": ["sources", "destination"],
            "delete_item": ["target"],
            "delete_multiple_items": ["targets"],
            "create_folders_from_excel": ["excel_path"],
            "create_folders_from_table": ["excel_path"],
            "delete_folders_from_excel": ["excel_path", "destination_folder"],
            "run_facesync": ["excel_path", "source_folder", "destination_folder"],
            "excel_to_facesync_pipeline": ["excel_path", "source_folder", "destination_folder"],
            "prepare_facesync_pipeline": ["excel_path", "source_folder", "destination_folder"],
            "run_reference_face_matching": ["excel_path", "source_folder", "destination_folder"],
            "classify_photos_by_reference": ["excel_path", "source_folder", "destination_folder"],
            "search_files": ["query"],
        }
        return list(required.get(intent, []))

    def _slot_value(self, args: Dict[str, Any], slot: str, *, use_context: bool) -> Any:
        args = args or {}
        aliases = {
            "excel_path": ("excel_path", "table_path", "excel_name", "document_name"),
            "table_path": ("table_path", "excel_path", "excel_name", "document_name"),
            "source_folder": ("source_folder",),
            "destination_folder": ("destination_folder", "destination"),
            "name_column": ("name_column", "column_name"),
            "reference_column": ("reference_column",),
            "folder_name": ("folder_name",),
            "file_name": ("file_name",),
            "quantity": ("quantity",),
            "base_name": ("base_name",),
            "document_name": ("document_name", "excel_name", "excel_path"),
            "target": ("target", "source"),
            "source": ("source", "target"),
            "sources": ("sources", "targets"),
            "targets": ("targets", "sources"),
            "destination": ("destination", "destination_folder"),
            "new_name": ("new_name",),
            "query": ("query",),
        }
        for key in aliases.get(slot, (slot,)):
            value = args.get(key)
            if value not in (None, "", []):
                return value

        if not use_context:
            return None

        context_aliases = {
            "excel_path": ("ultimo_excel_leido", "last_excel"),
            "table_path": ("ultimo_excel_leido", "last_excel"),
            "source_folder": ("ultima_carpeta_fotos",),
            "destination_folder": ("ultima_carpeta_destino",),
            "document_name": ("ultimo_documento_leido", "last_document"),
        }
        for key in context_aliases.get(slot, ()):
            value = self.context.get_context(key)
            if value not in (None, "", []):
                return value
        return None

    def _question_for_missing_slot(self, intent: str, missing_slot: str) -> str:
        if intent in self.FACESYNC_INTENTS:
            return self._facesync_question([missing_slot])
        questions = {
            "folder_name": "Que nombre quieres para la carpeta?",
            "file_name": "Que nombre quieres para el archivo?",
            "quantity": "Cuantos elementos quieres crear?",
            "base_name": "Con que nombre base quieres que los cree?",
            "document_name": "Que archivo quieres que lea?",
            "target": "Que archivo o carpeta quieres usar?",
            "targets": "Que archivos o carpetas quieres usar?",
            "source": "Que archivo o carpeta quieres mover?",
            "sources": "Que archivos o carpetas quieres mover o copiar?",
            "destination": "A que carpeta quieres moverlo?",
            "new_name": "Que nombre nuevo quieres usar?",
            "excel_path": "Que Excel o CSV quieres usar?",
            "table_path": "Que Excel o CSV quieres usar?",
            "column_name": "Que columna quieres usar?",
            "name_column": "Que columna contiene los nombres para crear las carpetas?",
            "reference_column": "Que columna contiene la foto o codigo de referencia?",
            "destination_folder": "Donde quieres guardar el resultado?",
            "source_folder": "Que carpeta contiene las fotos originales?",
            "query": "Que archivo quieres buscar?",
        }
        return questions.get(missing_slot, "Me falta un dato para continuar.")

    def _confirmation_question(self, intent: str, args: Dict[str, Any]) -> str:
        target = args.get("target") or args.get("destination_folder") or args.get("excel_path") or "los elementos indicados"
        if intent == "delete_folders_from_excel":
            return "Voy a eliminar las carpetas creadas desde el Excel indicado. Confirmas?"
        if intent == "delete_multiple_items":
            return "Voy a eliminar los elementos indicados. Confirmas?"
        if intent == "delete_item":
            return f"Voy a eliminar '{target}'. Confirmas?"
        return "Confirmas que quieres ejecutar esta accion?"

    def handle_structured_interpretation(
        self,
        user_text: str,
        interpretation: Dict[str, Any],
        *,
        source: str = "openai",
    ) -> Optional[OrchestrationResult]:
        if isinstance(interpretation, FaceSyncDecision):
            return self._run_structured_pipeline(user_text, interpretation, source=source)

        raw_intent = self._intent_value((interpretation or {}).get("intent") or "unknown") if isinstance(interpretation, dict) else "unknown"
        if raw_intent not in ALLOWED_OPENAI_INTENTS:
            error = f"intent_not_allowed:{raw_intent}"
            print(f"[OPENAI_ORCH] invalid_response={error}")
            self._save_validation_failure(user_text, interpretation, error)
            return OrchestrationResult(
                handled=True,
                message=self.INVALID_OPENAI_MESSAGE,
                action="openai_invalid",
                requires_clarification=True,
                data={"used_openai": source == "openai", "error": error},
            )

        interpretation = self.capability_router.apply_to_interpretation(
            user_text,
            dict(interpretation or {}),
            system_state=self._fallback_state(user_text),
            context=self.context,
        )
        validated, error = self._validate_external_interpretation(interpretation)
        if error:
            print(f"[OPENAI_ORCH] invalid_response={error}")
            self._save_validation_failure(user_text, interpretation, error)
            message = (
                "No puedo ejecutar ese plan porque una ruta sale del workspace."
                if str(error).startswith("path_outside_workspace")
                else self.INVALID_OPENAI_MESSAGE
            )
            return OrchestrationResult(
                handled=True,
                message=message,
                action="openai_invalid",
                requires_clarification=True,
                data={"used_openai": source == "openai", "error": error},
            )

        if validated.get("intent") == "analyze_or_explain":
            return None
        if validated.get("intent") == "ask_missing_data":
            return OrchestrationResult(
                handled=True,
                message=self.formatter.clarification(validated.get("question") or self.INVALID_OPENAI_MESSAGE),
                action="ask_missing_data",
                requires_clarification=True,
                data={"interpretation": validated, "used_openai": source == "openai"},
            )

        structured_decision = self._decision_from_interpretation(validated)
        if structured_decision is not None:
            return self._run_structured_pipeline(user_text, structured_decision, source=source)

        return self._execute_interpreted_action(validated, source=source, used_openai=(source == "openai"), user_text=user_text)

    # ------------------------------------------------------------------
    # Structured pipeline: FaceSyncDecision -> ActionPlan -> guarded tools
    # ------------------------------------------------------------------

    def _run_structured_pipeline(
        self,
        user_text: str,
        decision: FaceSyncDecision,
        *,
        source: str,
        confirmed: bool = False,
        skip_prefallback: bool = False,
        stored_plan: Optional[StructuredActionPlan] = None,
    ) -> OrchestrationResult:
        missing_workspace = self._require_workspace()
        if missing_workspace:
            return missing_workspace

        system_state = self._structured_system_state(user_text)
        decision = FaceSyncDecision.model_validate(decision.model_dump())
        # Multi-origen: recordar las carpetas ya resueltas (p.ej. desde un pending
        # "FOTOS, FOTOS 2 y FOTOS 3") para no perderlas al re-rutear el texto pelado.
        original_sources = [s for s in (getattr(decision.args, "source_folders", []) or []) if s]
        # Multi-origen: si la decision del modelo solo trajo UNA carpeta pero el
        # texto del usuario enumera varias ("usando A, B y C"), recuperarlas del
        # texto para no quedarnos con la primera. Solo se expande cuando la carpeta
        # unica del modelo esta entre las enumeradas, para no confundir columnas u
        # otras frases con "usando" como si fueran carpetas origen.
        if len(original_sources) < 2:
            try:
                text_sources = [s for s in SlotExtractor._extract_source_folders(user_text, self.context) if s]
            except Exception:
                text_sources = []
            if len(text_sources) >= 2:
                single = (getattr(decision.args, "source_folder", "") or "").strip()
                single_base = os.path.basename(single.rstrip("/\\")).lower()
                if single_base and any(
                    single_base == os.path.basename(str(t).rstrip("/\\")).lower()
                    for t in text_sources
                ):
                    original_sources = text_sources
        if not (confirmed and stored_plan is not None):
            route = self.capability_router.route(
                user_text,
                self._decision_to_legacy_interpretation(decision),
                system_state=system_state,
                context=self.context,
            )

            self.context.update_context("last_capability_route", route.model_dump())
            decision = self.capability_router.to_decision(route, fallback=decision)
            # Si la re-ruta no conservo la lista multi-origen, reinyectarla.
            if original_sources and not [s for s in (getattr(decision.args, "source_folders", []) or []) if s]:
                _args = decision.args.model_copy(update={
                    "source_folders": original_sources,
                    "source_folder": original_sources[0],
                })
                decision = decision.model_copy(update={"args": _args})
            decision, location_result = self._resolve_decision_locations(decision, system_state)
            if location_result is not None:
                location_field = str(getattr(location_result, "location_field", "") or "target")
                message = location_result.message or "Necesito confirmar la ubicacion."
                pending_args = decision.args.model_dump()
                pending_args["_location_candidates"] = list(getattr(location_result, "candidates", []) or [])
                pending_args["_location_field"] = location_field
                pending_args["_location_query"] = str(getattr(location_result, "query", "") or "")
                pending = self._store_structured_pending(
                    self._intent_value(decision.intent),
                    pending_args,
                    source=source,
                    question=message,
                    plan=None,
                    missing_fields=[location_field],
                    requires_confirmation=False,
                )
                pending["location_candidates"] = list(getattr(location_result, "candidates", []) or [])
                pending["location_field"] = location_field
                pending["location_query"] = str(getattr(location_result, "query", "") or "")
                self.context.set_pending_action(pending)
                if hasattr(self.context, "save_context_snapshot_to_vault"):
                    self.context.save_context_snapshot_to_vault(self.context.current_context)
                return OrchestrationResult(
                    handled=True,
                    message=self.formatter.clarification(message),
                    action=self._intent_value(decision.intent),
                    requires_clarification=True,
                    data={"location_resolution": location_result.model_dump(), "pending_action": pending},
                )
            system_state = self._enrich_system_state_with_table_columns(decision, system_state)
            decision, column_result = self._resolve_decision_columns(decision, system_state)
            if column_result is not None:
                return OrchestrationResult(
                    handled=True,
                    message=self.formatter.clarification(column_result.message or "Necesito confirmar la columna."),
                    action=self._intent_value(decision.intent),
                    requires_clarification=True,
                    data={"column_resolution": column_result.model_dump()},
                )

        if not skip_prefallback:
            pre = self.pre_action_fallback.analyze(decision, system_state, retry_count=int(decision.retry_count or 0))
            pre_result = self._handle_pre_fallback_result(user_text, decision, pre, source=source)
            if pre_result is not None:
                return pre_result
            if pre.repaired_decision is not None:
                decision = pre.repaired_decision

        plan = stored_plan or ActionPlanner.plan(decision)
        plan = self._recover_empty_structured_plan(user_text, decision, plan, system_state)

        return self._execute_guarded_structured_plan(
            user_text,
            decision,
            plan,
            source=source,
            confirmed=confirmed,
            system_state=system_state,
        )

    def _recover_empty_structured_plan(
        self,
        user_text: str,
        decision: FaceSyncDecision,
        plan: StructuredActionPlan,
        system_state: Dict[str, Any],
    ) -> StructuredActionPlan:
        if plan.steps:
            return plan
        intent = self._intent_value(decision.intent)
        if intent in {"ask_missing_data", "unknown"}:
            return plan

        route_data = self.context.get_context("last_capability_route") if self.context else None
        if isinstance(route_data, dict) and route_data.get("capability"):
            recovered = ActionPlanner.plan(route_data)
            if recovered.steps:
                return recovered

        route = self.capability_router.route(
            user_text,
            self._decision_to_legacy_interpretation(decision),
            system_state=system_state,
            context=self.context,
        )
        recovered = ActionPlanner.plan(route.model_dump())
        if recovered.steps:
            self.context.update_context("last_capability_route", route.model_dump())
            return recovered

        return plan

    def _execute_guarded_structured_plan(
        self,
        user_text: str,
        decision: FaceSyncDecision,
        plan: StructuredActionPlan,
        *,
        source: str,
        confirmed: bool,
        system_state: Dict[str, Any],
        pending_id: Any = None,
    ) -> OrchestrationResult:
        guard = self.plan_guard.validate(plan, system_state=system_state)
        if guard.repaired_plan is not None:
            plan = guard.repaired_plan
        if guard.status != "ready":
            return self._handle_guard_failure(user_text, decision, guard, source=source)

        route_error = self._validate_structured_plan_security(plan)
        if route_error:
            failed_id = self._save_structured_failure(
                user_text,
                decision,
                system_state,
                route_error,
                "Ruta bloqueada por SecurityManager antes de ejecutar tools.",
            )
            return OrchestrationResult(
                handled=True,
                message="No puedo ejecutar ese plan porque una ruta sale del workspace.",
                action=self._intent_value(decision.intent),
                requires_clarification=True,
                data={"security_error": route_error, "failed_interpretation_id": failed_id},
            )

        gate_error = self._validate_tool_execution_gate(plan)
        if gate_error:
            missing_result = self._empty_plan_clarification(decision, plan, source=source)
            if missing_result is not None:
                return missing_result
            failed_id = self._save_structured_failure(user_text, decision, system_state, "tool_gate_blocked", gate_error)
            return OrchestrationResult(
                handled=True,
                message=f"No ejecuto esa accion porque los datos no son seguros: {gate_error}",
                action=self._intent_value(decision.intent),
                requires_clarification=True,
                data={"gate_error": gate_error, "failed_interpretation_id": failed_id},
            )

        if (plan.preview_required or plan.requires_confirmation) and not confirmed:
            message = self._preview_message(plan)
            pending = self._store_structured_pending(
                self._intent_value(decision.intent),
                decision.args.model_dump(),
                source=source,
                question=message,
                plan=plan,
                missing_fields=[],
                requires_confirmation=True,
            )
            return OrchestrationResult(
                handled=True,
                message=message,
                action=self._intent_value(decision.intent),
                requires_clarification=True,
                data={"pending_action": pending, "preview_required": True, "structured_plan": plan.model_dump()},
            )

        execution = self.execute_structured_plan(plan)
        if not execution.get("success"):
            return self._handle_structured_execution_failure(
                user_text,
                decision,
                plan,
                execution,
                system_state,
                source=source,
            )

        self._persist_structured_success(decision, plan, execution)
        if pending_id and hasattr(self.context, "update_pending_action_status_in_vault"):
            self.context.update_pending_action_status_in_vault(pending_id, "completed")
            current_pending = self.context.get_pending_action() if hasattr(self.context, "get_pending_action") else None
            if isinstance(current_pending, dict) and current_pending.get("pending_id") == pending_id:
                current_pending["pending_status_finalized"] = True
                self.context.current_context["pending_action"] = current_pending
        self.context.clear_pending_action()
        message = self.formatter.format(execution)
        return OrchestrationResult.ok(
            message,
            action=self._intent_value(decision.intent),
            refresh=bool(execution.get("refresh")),
            data={
                "decision": decision.model_dump(),
                "interpretation": self._decision_to_legacy_interpretation(decision),
                "plan": plan.model_dump(),
                "execution": execution,
            },
        )

    def _empty_plan_clarification(
        self,
        decision: FaceSyncDecision,
        plan: StructuredActionPlan,
        *,
        source: str,
    ) -> Optional[OrchestrationResult]:
        if plan.steps:
            return None
        intent = self._intent_value(decision.intent)
        questions = {
            "create_folder": (["folder_name"], "Claro, que nombre quieres para la carpeta?"),
            "create_file": (["file_name"], "Claro, que nombre quieres para el archivo?"),
            "read_document": (["table_path"], "Claro, que archivo quieres que lea?"),
            "move_item": (["target", "destination_folder"], "Claro, que carpeta quieres mover y a donde?"),
            "copy_item": (["target", "destination_folder"], "Claro, que carpeta quieres copiar y a donde?"),
            "rename_item": (["target", "new_name"], "Claro, que carpeta quieres renombrar y que nuevo nombre tendra?"),
            "delete_item": (["target"], "Claro, que archivo o carpeta quieres borrar?"),
        }
        if intent not in questions:
            return None
        missing_fields, question = questions[intent]
        pending = self._store_structured_pending(
            intent,
            decision.args.model_dump(),
            source=source,
            question=question,
            plan=None,
            missing_fields=missing_fields,
            requires_confirmation=intent in self.DESTRUCTIVE_INTENTS,
        )
        return OrchestrationResult(
            handled=True,
            message=self.formatter.clarification(question),
            action=intent,
            requires_clarification=True,
            data={"pending_action": pending, "fallback_status": "clarification_needed"},
        )

    def _handle_pre_fallback_result(
        self,
        user_text: str,
        decision: FaceSyncDecision,
        fallback: StructuredFallbackResult,
        *,
        source: str,
    ) -> Optional[OrchestrationResult]:
        intent = self._intent_value(decision.intent)
        repaired = fallback.repaired_decision or decision
        args = repaired.args.model_dump()

        if fallback.status == "ready":
            return None

        if fallback.status == "retry_smart":
            return OrchestrationResult(
                handled=True,
                message="Necesito revisar ese plan con el modelo smart antes de ejecutar.",
                action="retry_smart",
                requires_clarification=True,
                data={
                    "interpretation": self._decision_to_legacy_interpretation(repaired),
                    "fallback_status": fallback.status,
                    "fallback_reason": fallback.reason,
                    "risk_flags": fallback.risk_flags,
                },
            )

        if fallback.status == "clarification_needed":
            question = fallback.question or "Me falta un dato para continuar."
            confirmation_required = bool(
                repaired.requires_confirmation
                or "destructive_requires_confirmation" in (fallback.risk_flags or [])
            )
            pending_plan = ActionPlanner.plan(repaired) if confirmation_required else fallback.repaired_plan
            pending = self._store_structured_pending(
                intent,
                args,
                source=source,
                question=question,
                plan=pending_plan,
                missing_fields=fallback.missing_fields,
                requires_confirmation=confirmation_required,
            )
            return OrchestrationResult(
                handled=True,
                message=self.formatter.clarification(question),
                action=intent,
                requires_clarification=True,
                data={"pending_action": pending, "fallback_status": fallback.status, "risk_flags": fallback.risk_flags},
            )

        failed_id = self._save_structured_failure(user_text, repaired, self._structured_system_state(user_text), "pre_action_blocked", fallback.reason)
        return OrchestrationResult(
            handled=True,
            message=fallback.question or "No puedo ejecutar ese plan con seguridad.",
            action=intent,
            requires_clarification=True,
            data={"fallback_status": fallback.status, "risk_flags": fallback.risk_flags, "failed_interpretation_id": failed_id},
        )

    def _resolve_decision_locations(
        self,
        decision: FaceSyncDecision,
        system_state: Dict[str, Any],
    ) -> tuple[FaceSyncDecision, Optional[Any]]:
        intent = self._intent_value(decision.intent)
        args = decision.args.model_dump()
        resolved_args, issue = self.location_resolver.resolve_args(intent, args, system_state)
        if issue is not None:
            return decision, issue
        data = decision.model_dump()
        data["args"] = {key: value for key, value in resolved_args.items() if key in self._structured_arg_keys()}
        return FaceSyncDecision.model_validate(data), None

    def _resolve_decision_columns(
        self,
        decision: FaceSyncDecision,
        system_state: Dict[str, Any],
    ) -> tuple[FaceSyncDecision, Optional[Any]]:
        intent = self._intent_value(decision.intent)
        if intent not in {
            "create_folders_from_table",
            "create_folders_from_excel",
            "run_reference_face_matching",
            "classify_photos_by_reference",
        }:
            return decision, None

        columns = (
            system_state.get("available_columns")
            or system_state.get("last_table_columns")
            or (system_state.get("context_summary") or {}).get("last_table_columns")
            or []
        )
        if not columns:
            return decision, None

        args = decision.args.model_dump()
        if intent in {"run_reference_face_matching", "classify_photos_by_reference"}:
            name, reference, issue = self.column_resolver.resolve_pair(
                args.get("name_column"),
                args.get("reference_column"),
                columns,
            )
            if issue is not None:
                return decision, issue
            args["name_column"] = name
            args["reference_column"] = reference
        else:
            raw = args.get("name_column") or args.get("column_name")
            if raw:
                result = self.column_resolver.resolve(raw, columns, role="name")
                if not result.success:
                    return decision, result
                args["name_column"] = result.resolved_column

        data = decision.model_dump()
        data["args"] = {key: value for key, value in args.items() if key in self._structured_arg_keys()}
        return FaceSyncDecision.model_validate(data), None

    def _enrich_system_state_with_table_columns(
        self,
        decision: FaceSyncDecision,
        system_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        intent = self._intent_value(decision.intent)
        if intent not in {
            "create_folders_from_table",
            "create_folders_from_excel",
            "run_reference_face_matching",
            "classify_photos_by_reference",
        }:
            return system_state
        if system_state.get("available_columns") or system_state.get("last_table_columns"):
            return system_state
        table_path = decision.args.table_path or decision.args.excel_name or ""
        if not table_path:
            return system_state
        path = self._find_file(table_path, extensions={".xlsx", ".xls", ".csv"})
        if not path:
            return system_state
        try:
            result = self._docs().read_document(path)
        except Exception:
            return system_state
        columns = list(result.get("columns") or []) if isinstance(result, dict) else []
        if not columns:
            return system_state
        rows = result.get("rows") if isinstance(result, dict) else None
        enriched = dict(system_state)
        enriched["available_columns"] = columns
        enriched["last_table_columns"] = columns
        enriched["last_table_path"] = path
        if rows is not None:
            enriched["last_table_rows"] = rows
        self.context.update_context("available_columns", columns)
        self.context.update_context("last_table_columns", columns)
        self.context.update_context("last_table_path", path)
        if rows is not None:
            self.context.update_context("last_table_rows", rows)
        if hasattr(self.context, "save_detected_table_to_vault"):
            self.context.save_detected_table_to_vault(path, columns, row_count=rows)
        return enriched

    @staticmethod
    def _structured_arg_keys() -> set[str]:
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

    def _handle_guard_failure(
        self,
        user_text: str,
        decision: FaceSyncDecision,
        guard: StructuredFallbackResult,
        *,
        source: str,
    ) -> OrchestrationResult:
        intent = self._intent_value(decision.intent)
        if guard.status == "clarification_needed":
            pending = self._store_structured_pending(
                intent,
                decision.args.model_dump(),
                source=source,
                question=guard.question or "Necesito aclarar datos antes de ejecutar.",
                plan=guard.repaired_plan,
                missing_fields=guard.missing_fields,
                requires_confirmation=False,
            )
            return OrchestrationResult(
                handled=True,
                message=self.formatter.clarification(guard.question or "Necesito aclarar datos antes de ejecutar."),
                action=intent,
                requires_clarification=True,
                data={"pending_action": pending, "guard_status": guard.status, "risk_flags": guard.risk_flags},
            )

        failed_id = self._save_structured_failure(user_text, decision, self._structured_system_state(user_text), "plan_guard_blocked", guard.reason)
        return OrchestrationResult(
            handled=True,
            message=guard.question or "PlanGuard bloqueo el plan por incoherencia semantica.",
            action=intent,
            requires_clarification=True,
            data={"guard_status": guard.status, "risk_flags": guard.risk_flags, "failed_interpretation_id": failed_id},
        )

    def _execute_structured_pending_action(self, pending: Dict[str, Any], *, confirmed: bool) -> OrchestrationResult:
        intent = pending.get("intent") or "unknown"
        args = dict(pending.get("args") or {})
        source = pending.get("source") or pending.get("origin") or "local"
        user_text = self._last_user_text()

        decision = self._decision_from_interpretation(
            {
                "intent": intent,
                "confidence": max(float(pending.get("confidence") or 0.95), 0.95),
                "needs_clarification": False,
                "question": "",
                "args": args,
                "reason": "Accion pendiente estructurada.",
                "safe_to_execute": True,
                "requires_confirmation": bool(pending.get("requires_confirmation")),
            }
        )
        if decision is None:
            return OrchestrationResult(
                handled=True,
                message="No pude recuperar la accion pendiente con seguridad.",
                action=intent,
                requires_clarification=True,
            )

        if confirmed and pending.get("structured_plan"):
            pending = self._mark_pending_executing(pending)
            try:
                plan = StructuredActionPlan.model_validate(pending.get("structured_plan"))
            except Exception:
                plan = ActionPlanner.plan(decision)
            return self._execute_guarded_structured_plan(
                user_text,
                decision,
                plan,
                source=source,
                confirmed=True,
                system_state=self._structured_system_state(user_text),
                pending_id=pending.get("pending_id"),
            )

        return self._run_structured_pipeline(user_text, decision, source=source, confirmed=confirmed)

    def _store_structured_pending(
        self,
        intent: str,
        args: Dict[str, Any],
        *,
        source: str,
        question: str,
        plan: Optional[StructuredActionPlan],
        missing_fields: List[str],
        requires_confirmation: bool,
    ) -> Dict[str, Any]:
        args = {key: value for key, value in dict(args or {}).items() if value not in (None, "")}
        missing_fields = [str(item) for item in (missing_fields or []) if str(item)]
        pending = {
            "pipeline": "structured",
            "intent": intent,
            "args": args,
            "source": source,
            "origin": source,
            "question": question,
            "missing_slot": missing_fields[0] if missing_fields else "",
            "missing_fields": missing_fields,
            "requires_confirmation": bool(requires_confirmation),
            "destructive": intent in self.DESTRUCTIVE_INTENTS,
            "preview_text": getattr(plan, "preview_text", "") if plan else "",
            "structured_plan": plan.model_dump() if plan else None,
            "last_prompt_type": "confirmation" if requires_confirmation else "clarification",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if hasattr(self.context, "save_pending_action_to_vault"):
            pending_id = self.context.save_pending_action_to_vault(
                intent,
                args,
                missing_fields,
                preview_text=pending.get("preview_text") or question,
            )
            if pending_id:
                pending["pending_id"] = pending_id
        self.context.set_pending_action(pending)
        if intent in self.FACESYNC_INTENTS:
            self.context.update_context("ultimo_facesync_plan", pending)
        return pending

    def _decision_from_interpretation(self, interpretation: Any) -> Optional[FaceSyncDecision]:
        try:
            if isinstance(interpretation, FaceSyncDecision):
                return interpretation
            if hasattr(interpretation, "model_dump"):
                return FaceSyncDecision.model_validate(interpretation.model_dump())
            data = dict(interpretation or {})
            args = dict(data.get("args") or {})
            if args.get("excel_path") and not args.get("table_path"):
                args["table_path"] = args.get("excel_path")
            if args.get("document_name") and not args.get("table_path"):
                args["table_path"] = args.get("document_name")
            if args.get("source") and not args.get("target"):
                args["target"] = args.get("source")
            if args.get("destination") and not args.get("destination_folder"):
                args["destination_folder"] = args.get("destination")
            allowed_arg_keys = {
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
            clarification = data.get("clarification") or {}
            needs_clarification = bool(data.get("requires_clarification") or data.get("needs_clarification"))
            if needs_clarification and not clarification:
                clarification = {
                    "required": True,
                    "missing_fields": data.get("missing_fields") or [],
                    "question": data.get("question") or "",
                }
            return FaceSyncDecision.model_validate(
                {
                    "intent": data.get("intent") or "unknown",
                    "confidence": float(data.get("confidence") or 0.0),
                    "args": {key: value for key, value in args.items() if key in allowed_arg_keys},
                    "requires_clarification": needs_clarification,
                    "clarification": clarification,
                    "safe_to_execute": bool(data.get("safe_to_execute")) and not needs_clarification,
                    "requires_confirmation": bool(data.get("requires_confirmation")),
                    "reason_summary": data.get("reason_summary") or data.get("reason") or "",
                    "risk_flags": data.get("risk_flags") or [],
                    "model_used": data.get("model_used") or "",
                    "escalation_reason": data.get("escalation_reason") or "",
                    "retry_count": int(data.get("retry_count") or data.get("fallback_retry_count") or 0),
                }
            )
        except Exception:
            return None

    def _decision_from_local_interpretation(self, interpretation: Dict[str, Any]) -> Optional[FaceSyncDecision]:
        data = dict(interpretation or {})
        intent = self._intent_value(data.get("intent") or "unknown")
        data["safe_to_execute"] = intent not in self.DESTRUCTIVE_INTENTS
        data["requires_confirmation"] = intent in self.DESTRUCTIVE_INTENTS or intent in self.PREVIEW_CONFIRMATION_INTENTS
        data["reason_summary"] = data.get("reason_summary") or data.get("reason") or "Interpretacion local enviada al pipeline estructurado."
        return self._decision_from_interpretation(data)

    @staticmethod
    def _decision_to_legacy_interpretation(decision: FaceSyncDecision) -> Dict[str, Any]:
        data = decision.model_dump()
        clarification = data.get("clarification") or {}
        return {
            "intent": data.get("intent"),
            "confidence": data.get("confidence", 0.0),
            "needs_clarification": bool(data.get("requires_clarification")),
            "requires_clarification": bool(data.get("requires_clarification")),
            "question": clarification.get("question") or "",
            "args": data.get("args") or {},
            "reason": data.get("reason_summary") or "",
            "safe_to_execute": bool(data.get("safe_to_execute")),
            "requires_confirmation": bool(data.get("requires_confirmation")),
            "risk_flags": data.get("risk_flags") or [],
            "model_used": data.get("model_used") or "",
        }

    def _execute_interpreted_action(
        self,
        interpretation: Dict[str, Any],
        *,
        source: str,
        used_openai: bool = False,
        allow_destructive: bool = False,
        user_text: str = "",
    ) -> OrchestrationResult:
        intent = interpretation.get("intent", "unknown")
        args = interpretation.get("args") or {}

        missing_workspace = self._require_workspace()
        if missing_workspace:
            return missing_workspace

        repaired_interpretation, fallback_response, _fallback = self._apply_action_fallback(
            user_text,
            interpretation,
            source=source,
            used_openai=used_openai,
            allow_destructive=allow_destructive,
        )
        if fallback_response:
            return fallback_response
        interpretation = repaired_interpretation or interpretation
        intent = interpretation.get("intent", "unknown")
        args = interpretation.get("args") or {}

        facesync_clarification = self._facesync_missing_clarification(
            intent,
            args,
            source=source,
            used_openai=used_openai,
        )
        if facesync_clarification:
            return facesync_clarification

        if interpretation.get("needs_clarification"):
            question = interpretation.get("question") or self._default_question_for(intent)
            self._store_pending_action_if_relevant(intent, args, source=source, question=question)
            return OrchestrationResult(
                handled=True,
                message=self.formatter.clarification(question),
                action=intent,
                requires_clarification=True,
                data={"interpretation": interpretation, "used_openai": used_openai},
            )

        if intent in self.DESTRUCTIVE_INTENTS and not allow_destructive:
            return self._ask_destructive_confirmation(intent, args, source=source, plan=None, used_openai=used_openai)

        if not bool(interpretation.get("safe_to_execute", True)):
            question = interpretation.get("question") or self.INVALID_OPENAI_MESSAGE
            self._store_pending_action_if_relevant(intent, args, source=source, question=question)
            return OrchestrationResult(
                handled=True,
                message=self.formatter.clarification(question),
                action=intent,
                requires_clarification=True,
                data={"interpretation": interpretation, "used_openai": used_openai},
            )

        plan = self.planner.build(interpretation, self.context)
        self.context.remember_action("plan", plan=plan.as_list(), intent=intent)

        if plan.needs_clarification:
            question = plan.question or self._default_question_for(intent)
            self._store_pending_action_if_relevant(intent, args, source=source, question=question, plan=plan)
            return OrchestrationResult(
                handled=True,
                message=self.formatter.clarification(question),
                action=intent,
                requires_clarification=True,
                data={"interpretation": interpretation, "plan": plan.as_list(), "used_openai": used_openai},
            )

        if not allow_destructive:
            preview = self._maybe_ask_action_preview(intent, args, source=source, plan=plan, used_openai=used_openai)
            if preview:
                return preview

        execution = self.execute_plan(plan)
        message = self.formatter.format(execution)
        if not execution.get("success"):
            self.context.update_context("last_failed_action", intent)
            self.context.update_context("last_error_type", execution.get("error") or "execution")

        if execution.get("requires_clarification"):
            merged_args = self._merge_args_with_execution_data(args, execution.get("data") or {})
            self._store_pending_action_if_relevant(
                intent,
                merged_args,
                source=source,
                question=execution.get("question") or "",
                plan=plan,
                missing_slot=execution.get("missing_slot") or "",
            )
            return OrchestrationResult(
                handled=True,
                message=message,
                action=intent,
                refresh=False,
                requires_clarification=True,
                data={
                    "interpretation": interpretation,
                    "plan": plan.as_list(),
                    "execution": execution,
                    "used_openai": used_openai,
                },
            )

        self._remember_execution(execution, plan)
        self.context.clear_pending_action()
        return OrchestrationResult.ok(
            message,
            action=intent,
            refresh=bool(execution.get("refresh")),
            data={
                "interpretation": interpretation,
                "plan": plan.as_list(),
                "execution": execution,
                "used_openai": used_openai,
            },
        )

    def _validate_external_interpretation(self, interpretation: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
        if not isinstance(interpretation, dict):
            return {}, "response_not_dict"

        intent = self._intent_value(interpretation.get("intent") or "unknown")
        if intent not in ALLOWED_OPENAI_INTENTS:
            return {}, f"intent_not_allowed:{intent}"

        confidence = interpretation.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            return {}, "confidence_not_number"
        confidence = float(confidence)
        if confidence < 0 or confidence > 1:
            return {}, "confidence_out_of_range"

        needs_clarification = interpretation.get("needs_clarification")
        if not isinstance(needs_clarification, bool):
            return {}, "needs_clarification_not_bool"

        safe_to_execute = interpretation.get("safe_to_execute")
        if not isinstance(safe_to_execute, bool):
            return {}, "safe_to_execute_not_bool"

        args = interpretation.get("args")
        if not isinstance(args, dict):
            return {}, "args_not_dict"

        normalized_args = self._canonicalize_external_args(intent, args)
        route_error = self._validate_workspace_routes(normalized_args)
        if route_error:
            return {}, route_error

        return {
            "intent": intent,
            "confidence": confidence,
            "needs_clarification": needs_clarification,
            "question": str(interpretation.get("question") or ""),
            "args": normalized_args,
            "reason": str(interpretation.get("reason") or ""),
            "safe_to_execute": safe_to_execute,
            "source": "openai",
            "fallback_retry_count": int(interpretation.get("fallback_retry_count") or 0),
            "model_used": str(interpretation.get("model_used") or ""),
        }, ""

    def _canonicalize_external_args(self, intent: str, args: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(args or {})
        if normalized.get("table_path") and not normalized.get("excel_path"):
            normalized["excel_path"] = normalized.get("table_path")
        if normalized.get("excel_path") and not normalized.get("excel_name"):
            normalized["excel_name"] = normalized.get("excel_path")
        if normalized.get("excel_path") and not normalized.get("table_path"):
            normalized["table_path"] = normalized.get("excel_path")
        if intent in {"move_item", "copy_item"}:
            if not normalized.get("source") and normalized.get("target"):
                normalized["source"] = normalized.get("target")
            if not normalized.get("destination") and normalized.get("destination_folder"):
                normalized["destination"] = normalized.get("destination_folder")
        if intent in {"move_multiple_items", "copy_multiple_items"}:
            if not normalized.get("sources") and normalized.get("target"):
                normalized["sources"] = self._split_external_items(normalized.get("target"))
            if not normalized.get("destination") and normalized.get("destination_folder"):
                normalized["destination"] = normalized.get("destination_folder")
        if intent == "delete_multiple_items" and not normalized.get("targets") and normalized.get("target"):
            normalized["targets"] = self._split_external_items(normalized.get("target"))
        if intent in ("create_multiple_folders", "create_multiple_files"):
            quantity = normalized.get("quantity")
            if isinstance(quantity, str) and quantity.strip().isdigit():
                normalized["quantity"] = int(quantity.strip())
        return normalized

    def _validate_workspace_routes(self, args: Dict[str, Any]) -> str:
        if not self._workspace_root():
            return ""
        security = self._security()
        for key in self.PATH_ARG_KEYS:
            value = args.get(key)
            if value is None or value == "":
                continue
            if not isinstance(value, str):
                return f"path_not_string:{key}"
            if not security.secure_path(value):
                return f"path_outside_workspace:{key}"
        for key in self.PATH_LIST_ARG_KEYS:
            value = args.get(key)
            if value in (None, ""):
                continue
            if not isinstance(value, list):
                return f"path_list_not_list:{key}"
            for item in value:
                if not isinstance(item, str):
                    return f"path_not_string:{key}"
                if item and not security.secure_path(item):
                    return f"path_outside_workspace:{key}"
        return ""

    @staticmethod
    def _split_external_items(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value or "").split(",") if item.strip()]

    def _handle_pending_followup(self, text: str, normalized) -> Optional[OrchestrationResult]:
        getter = getattr(self.context, "get_pending_action", None)
        pending = getter() if callable(getter) else self.context.get_context("pending_action")
        if not pending:
            return None

        normalized_text = TextNormalizer.normalize_for_matching(text)
        if self._is_cancel(normalized_text):
            self.context.clear_pending_action()
            message = "No eliminé nada." if pending.get("destructive") else "De acuerdo, no ejecuté nada."
            return OrchestrationResult(
                handled=True,
                message=message,
                action=pending.get("intent", "pending_action"),
                requires_clarification=False,
            )

        intent = pending.get("intent") or "unknown"
        args = dict(pending.get("args") or {})

        if intent in self.FACESYNC_INTENTS:
            extracted = SlotExtractor.extract(intent, text, normalized, self.context)
            meaningful_extracted = {key: value for key, value in (extracted or {}).items() if value not in (None, "", [])}
            args = self._merge_args_with_execution_data(args, meaningful_extracted)
            pending["args"] = args
            self.context.set_pending_action(pending)
            if self._is_confirm(normalized_text) or meaningful_extracted:
                interpretation = {
                    "intent": intent,
                    "confidence": max(float(pending.get("confidence") or 0.95), 0.95),
                    "needs_clarification": False,
                    "question": "",
                    "args": args,
                    "reason": "Continuacion de accion pendiente.",
                    "safe_to_execute": True,
                }
                return self._execute_interpreted_action(
                    interpretation,
                    source=pending.get("source") or "local",
                    used_openai=pending.get("source") == "openai",
                    allow_destructive=False,
                )
            return None

        if intent in self.DESTRUCTIVE_INTENTS:
            if not self._is_confirm(normalized_text):
                return None
            interpretation = {
                "intent": intent,
                "confidence": max(float(pending.get("confidence") or 0.95), 0.95),
                "needs_clarification": False,
                "question": "",
                "args": args,
                "reason": "Confirmacion del usuario.",
                "safe_to_execute": True,
            }
            return self._execute_interpreted_action(
                interpretation,
                source=pending.get("source") or "local",
                used_openai=pending.get("source") == "openai",
                allow_destructive=True,
            )

        return None

    def _ask_destructive_confirmation(
        self,
        intent: str,
        args: Dict[str, Any],
        *,
        source: str,
        plan: Optional[ActionPlan] = None,
        used_openai: bool = False,
    ) -> OrchestrationResult:
        pending = self._store_pending_action_if_relevant(
            intent,
            args,
            source=source,
            question=self._confirmation_question(intent, args),
            plan=plan,
            destructive=True,
        )
        target = args.get("target") or args.get("destination_folder") or args.get("excel_path") or "los elementos indicados"
        if intent == "delete_folders_from_excel":
            message = "Voy a eliminar las carpetas creadas desde el Excel indicado. ¿Confirmas?"
        else:
            message = f"Voy a eliminar '{target}'. ¿Confirmas?"
        return OrchestrationResult(
            handled=True,
            message=message,
            action=intent,
            requires_clarification=True,
            data={"pending_action": pending, "used_openai": used_openai},
        )

    def _maybe_ask_action_preview(
        self,
        intent: str,
        args: Dict[str, Any],
        *,
        source: str,
        plan: Optional[ActionPlan],
        used_openai: bool,
    ) -> Optional[OrchestrationResult]:
        if intent not in self.PREVIEW_CONFIRMATION_INTENTS:
            return None
        if intent in self.DESTRUCTIVE_INTENTS:
            return None

        question = self._preview_question(intent, args)
        pending = self._store_pending_action_if_relevant(
            intent,
            args,
            source=source,
            question=question,
            plan=plan,
            destructive=False,
            requires_confirmation=True,
        )
        return OrchestrationResult(
            handled=True,
            message=question,
            action=intent,
            requires_clarification=True,
            data={"pending_action": pending, "used_openai": used_openai, "preview_required": True},
        )

    def _preview_question(self, intent: str, args: Dict[str, Any]) -> str:
        action_labels = {
            "create_folders_from_excel": "crear carpetas desde tabla",
            "create_folders_from_table": "crear carpetas desde tabla",
            "run_reference_face_matching": "clasificar fotos por referencia facial",
            "classify_photos_by_reference": "clasificar fotos por referencia facial",
            "move_multiple_items": "mover varios elementos",
            "copy_multiple_items": "copiar varios elementos",
            "delete_item": "eliminar",
            "delete_multiple_items": "eliminar varios elementos",
            "delete_folders_from_excel": "eliminar carpetas desde tabla",
        }
        table = args.get("table_path") or args.get("excel_path") or args.get("excel_name") or ""
        name_column = args.get("name_column") or args.get("column_name") or ""
        reference_column = args.get("reference_column") or ""
        source = args.get("source_folder") or args.get("source") or ""
        source_folders = [s for s in (args.get("source_folders") or []) if s]
        destination = args.get("destination_folder") or args.get("destination") or ""
        targets = args.get("targets") or args.get("sources") or args.get("target") or ""

        lines = ["Voy a usar:"]
        if table:
            lines.append(f"Archivo: {table}")
        if name_column:
            lines.append(f"Columna de nombres: {name_column}")
        if reference_column:
            lines.append(f"Columna referencia: {reference_column}")
        if len(source_folders) >= 2:
            lines.append("Carpetas origen: " + ", ".join(source_folders))
        elif source:
            lines.append(f"Carpeta origen: {source}")
        if destination:
            lines.append(f"Destino: {destination}")
        if targets:
            if isinstance(targets, list):
                lines.append(f"Elementos: {', '.join(map(str, targets[:8]))}")
            else:
                lines.append(f"Elementos: {targets}")
        lines.append(f"Accion: {action_labels.get(intent, intent)}")
        lines.append("")
        lines.append("Confirmas?")
        return "\n".join(lines)

    def _store_pending_action_if_relevant(
        self,
        intent: str,
        args: Dict[str, Any],
        *,
        source: str,
        question: str = "",
        plan: Optional[ActionPlan] = None,
        destructive: Optional[bool] = None,
        missing_slot: str = "",
        requires_confirmation: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        if intent not in self.PENDING_INTENTS:
            return None
        args = dict(args or {})
        inferred_missing = missing_slot or self._infer_missing_slot(intent, args)
        is_destructive = intent in self.DESTRUCTIVE_INTENTS if destructive is None else bool(destructive)
        requires_confirmation_value = is_destructive if requires_confirmation is None else bool(requires_confirmation)
        # Extract available_columns from args so it's at the top level of pending
        available_columns = args.pop("available_columns", None) or []
        pending = {
            "intent": intent,
            "args": args,
            "source": source,
            "origin": source,
            "question": question or (self._question_for_missing_slot(intent, inferred_missing) if inferred_missing else ""),
            "missing_slot": inferred_missing,
            "requires_confirmation": requires_confirmation_value,
            "destructive": is_destructive,
            "plan": plan.as_list() if plan else [],
            "confidence": getattr(plan, "confidence", None) if plan else None,
            "last_prompt_type": "confirmation" if requires_confirmation_value else "clarification",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if available_columns:
            pending["available_columns"] = available_columns
        self.context.set_pending_action(pending)
        if intent in self.FACESYNC_INTENTS:
            self.context.update_context("ultimo_facesync_plan", pending)
        return pending

    @staticmethod
    def _merge_args_with_execution_data(args: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(args or {})
        for key, value in (data or {}).items():
            if value in (None, ""):
                continue
            if key == "excel_path":
                merged["excel_path"] = value
                merged["excel_name"] = value
                merged["table_path"] = value
            elif key == "table_path":
                merged["table_path"] = value
                merged["excel_path"] = value
                merged["excel_name"] = value
            elif key in {"excel_name", "source_folder", "destination_folder", "destination", "name_column", "reference_column", "mode"}:
                if key == "destination":
                    merged.setdefault("destination_folder", value)
                merged[key] = value
            elif key in {"folder_name", "file_name", "target", "source", "sources", "targets", "new_name", "quantity", "base_name", "content", "column_name"}:
                merged[key] = value
            elif key in {"columns", "available_columns"}:
                if isinstance(value, list) and value:
                    merged["available_columns"] = value
        return merged

    def _structured_system_state(self, user_text: str = "") -> Dict[str, Any]:
        builder = getattr(self.context, "build_system_state", None)
        if callable(builder):
            state = builder(user_text)
        else:
            state = dict(getattr(self.context, "current_context", {}) or {})
        state["_user_text"] = user_text or state.get("_user_text") or self._last_user_text()
        state["last_user_text"] = state.get("_user_text") or self._last_user_text()
        if getattr(self.context, "context_session_id", None):
            state["session_id"] = self.context.context_session_id
        if getattr(self.context, "context_project_id", None):
            state["project_id"] = self.context.context_project_id
        return state

    def _validate_structured_plan_security(self, plan: StructuredActionPlan) -> str:
        if not self._workspace_root():
            return ""
        security = self._security()
        path_keys = {"table_path", "source_folder", "destination_folder", "target", "file_name"}
        for step in plan.steps:
            args = dict(step.args or {})
            for key in path_keys:
                value = args.get(key)
                if value in (None, ""):
                    continue
                if not isinstance(value, str):
                    return f"path_not_string:{key}"
                if not security.secure_path(value):
                    return f"path_outside_workspace:{key}"
            if step.action == "create_folder":
                folder_path = self._join_path(args.get("destination_folder") or "", args.get("folder_name") or "")
                if folder_path and not security.secure_path(folder_path):
                    return "path_outside_workspace:folder_name"
            if step.action == "create_file":
                file_path = self._join_path(args.get("destination_folder") or "", args.get("file_name") or "")
                if file_path and not security.secure_path(file_path):
                    return "path_outside_workspace:file_name"
        return ""

    @staticmethod
    def _validate_tool_execution_gate(plan: StructuredActionPlan) -> str:
        if not plan.steps:
            risks = set(plan.risk_flags or [])
            if not plan.safe_to_execute or risks:
                return "plan sin pasos ejecutables o con argumentos incompletos"
        for step in plan.steps:
            ok, reason = ToolExecutionGate.validate_action(LocalCommandRouter._intent_value(step.action or ""), dict(step.args or {}))
            if not ok:
                return f"{step.action}:{reason}"
        return ""

    def _persist_structured_success(self, decision: FaceSyncDecision, plan: StructuredActionPlan, execution: Dict[str, Any]):
        intent = self._intent_value(plan.intent)
        data = execution.get("data") or {}
        args = decision.args.model_dump()

        if hasattr(self.context, "save_action_to_vault"):
            self.context.save_action_to_vault(intent, args, result=execution, success=True)

        if intent == "read_document":
            path = data.get("path") or data.get("table_path")
            document = data.get("document") or {}
            doc_type = document.get("type")
            self.context.remember_action(
                intent,
                document=path,
                excel=path if doc_type in {"excel", "csv"} else None,
                file=path,
            )
            if doc_type in {"excel", "csv"}:
                columns = list(document.get("columns") or [])
                rows = document.get("rows", 0)
                self.context.update_context("available_columns", columns)
                self.context.update_context("last_table_columns", columns)
                self.context.update_context("last_table_path", path)
                self.context.update_context("last_table_rows", rows)
                detected_name = self._detect_name_column(columns)
                detected_ref = self._detect_reference_column(columns)
                if detected_name:
                    self.context.update_context("last_name_column", detected_name)
                # La columna de referencia almacenada debe existir en la tabla
                # actual; si no, se limpia para no heredarla de un Excel anterior
                # al encadenar lecturas (evita clasificar con columnas inexistentes).
                if detected_ref:
                    self.context.update_context("last_reference_column", detected_ref)
                elif self.context.get_context("last_reference_column") not in columns:
                    self.context.update_context("last_reference_column", None)
                if hasattr(self.context, "save_detected_table_to_vault"):
                    self.context.save_detected_table_to_vault(path, columns, row_count=rows)

        elif intent in {"create_folders_from_table", "create_folders_from_excel"}:
            destination = data.get("destination_folder") or args.get("destination_folder")
            name_column = data.get("name_column") or args.get("name_column") or args.get("column_name")
            table_path = data.get("table_path") or args.get("table_path")
            self.context.remember_action(
                intent,
                excel=table_path,
                folder=destination,
                destination=destination,
                column=name_column,
                modified=destination,
            )
            self.context.update_context("last_name_column", name_column)
            self.context.update_context("last_destination_folder", destination)
            created_items = data.get("created_items") or []
            if created_items:
                self.context.update_context("last_created_items", created_items[-20:])
            reused_items = data.get("reused_items") or []
            if reused_items:
                self.context.update_context("last_reused_items", reused_items[-20:])

        elif intent in self.FACESYNC_INTENTS:
            table_path = data.get("table_path") or args.get("table_path")
            source_folder = data.get("source_folder") or args.get("source_folder")
            destination = data.get("destination_folder") or args.get("destination_folder")
            name_column = data.get("name_column") or args.get("name_column")
            reference_column = data.get("reference_column") or args.get("reference_column")
            self.context.remember_action(
                intent,
                excel=table_path,
                folder=destination,
                destination=destination,
                source_folder=source_folder,
                column=name_column,
                reference_column=reference_column,
                modified=destination,
            )
            self.context.update_context("last_facesync_run", {
                "table_path": table_path,
                "name_column": name_column,
                "reference_column": reference_column,
                "source_folder": source_folder,
                "destination_folder": destination,
                "report_path": data.get("report_path", ""),
                "copied": data.get("copied", []),
                "reused": data.get("reused", []),
                "skipped": data.get("skipped", []),
                "errors": data.get("errors", []),
                "success": True,
            })
            self.context.update_context("last_copied_items", data.get("copied", []))
            self.context.update_context("last_reused_items", data.get("reused", []))
            if hasattr(self.context, "save_facesync_run_to_vault"):
                self.context.save_facesync_run_to_vault(
                    table_path,
                    name_column,
                    reference_column,
                    source_folder,
                    destination,
                    report_path=data.get("report_path", ""),
                    success=True,
                )
        elif intent == "create_folder":
            path = data.get("path") or self._join_path(args.get("destination_folder") or "", args.get("folder_name") or "")
            self.context.remember_action(intent, folder=path, path=path, modified=path)
        elif intent == "create_file":
            path = data.get("path") or self._join_path(args.get("destination_folder") or "", args.get("file_name") or "")
            self.context.remember_action(intent, file=path, path=path, modified=path)
        elif intent == "move_item":
            path = data.get("path") or data.get("target") or args.get("target")
            self.context.remember_action(
                intent,
                path=path,
                folder=path,
                destination=data.get("destination") or args.get("destination_folder"),
                modified=path,
            )
        elif intent == "copy_item":
            path = data.get("path") or data.get("target") or args.get("target")
            self.context.remember_action(
                intent,
                path=path,
                folder=path,
                destination=data.get("destination") or args.get("destination_folder"),
                modified=path,
            )
            copied = self.context.get_context("last_copied_items")
            if isinstance(copied, list) and path:
                copied.append(path)
                del copied[:-20]
        elif intent == "rename_item":
            path = data.get("path") or args.get("target")
            self.context.remember_action(intent, path=path, folder=path, file=path, modified=path)
        elif intent == "delete_item":
            target = data.get("target") or args.get("target")
            self.context.remember_action(intent, path=target, modified=target)
        else:
            self.context.remember_action(intent, args=args)

        if hasattr(self.context, "save_context_snapshot_to_vault"):
            self.context.save_context_snapshot_to_vault(self.context.current_context)

    def _handle_structured_execution_failure(
        self,
        user_text: str,
        decision: FaceSyncDecision,
        plan: StructuredActionPlan,
        execution: Dict[str, Any],
        system_state: Dict[str, Any],
        *,
        source: str,
    ) -> OrchestrationResult:
        intent = self._intent_value(decision.intent)
        error = {
            "error_type": execution.get("error_type") or "unknown_tool_error",
            "error_message": execution.get("error") or execution.get("question") or "",
        }
        if execution.get("data", {}).get("available_columns"):
            system_state["available_columns"] = execution["data"]["available_columns"]
            system_state["last_table_columns"] = execution["data"]["available_columns"]

        vault = getattr(self.context, "context_vault", None)
        post = self.post_action_fallback.handle_tool_error(error, decision, system_state, context_vault=vault)
        failed_id = self._save_structured_failure(user_text, decision, system_state, error["error_type"], error["error_message"])

        if post.status in {"clarification_needed", "repaired"}:
            repaired = post.repaired_decision or decision
            question = post.question or "Encontré una posible corrección. ¿Confirmas los datos?"
            pending = self._store_structured_pending(
                self._intent_value(repaired.intent),
                repaired.args.model_dump(),
                source=source,
                question=question,
                plan=None,
                missing_fields=post.missing_fields,
                requires_confirmation=False,
            )
            return OrchestrationResult(
                handled=True,
                message=self.formatter.clarification(question),
                action=intent,
                requires_clarification=True,
                data={
                    "execution": execution,
                    "post_fallback": post.model_dump(),
                    "pending_action": pending,
                    "failed_interpretation_id": failed_id,
                },
            )

        if post.status == "retry_smart":
            return OrchestrationResult(
                handled=True,
                message="La herramienta fallo por una posible mala interpretacion. Necesito revisarlo con el modelo smart.",
                action="retry_smart",
                requires_clarification=True,
                data={
                    "interpretation": self._decision_to_legacy_interpretation(decision),
                    "execution": execution,
                    "post_fallback": post.model_dump(),
                    "failed_interpretation_id": failed_id,
                },
            )

        return OrchestrationResult(
            handled=True,
            message=post.question or self.formatter.error(execution),
            action=intent,
            requires_clarification=True,
            data={"execution": execution, "post_fallback": post.model_dump(), "failed_interpretation_id": failed_id},
        )

    def _save_structured_failure(
        self,
        user_text: str,
        decision: FaceSyncDecision,
        system_state: Dict[str, Any],
        error_type: str,
        error_message: str,
    ):
        intent = self._intent_value(decision.intent)
        args = decision.args.model_dump()
        if hasattr(self.context, "save_action_to_vault"):
            self.context.save_action_to_vault(intent, args, result={}, success=False, error_type=error_type, error_message=error_message)
        failed_id = None
        if hasattr(self.context, "save_failed_interpretation_to_vault"):
            failed_id = self.context.save_failed_interpretation_to_vault(user_text, system_state, intent, args, error_type, assistant_response=error_message)
        self._run_learning_queue(failed_id)
        self.context.update_context("last_failed_action", intent)
        self.context.update_context("last_error_type", error_type)
        self.context.update_context("last_interpretation_error", {"type": error_type, "message": error_message})
        return failed_id

    def _save_validation_failure(self, user_text: str, interpretation: Any, error: str):
        decision = self._decision_from_interpretation(interpretation) or FaceSyncDecision.model_validate(
            {"intent": "unknown", "confidence": 0.0, "safe_to_execute": False, "reason_summary": error}
        )
        self._save_structured_failure(user_text, decision, self._structured_system_state(user_text), error, "Interpretacion externa invalida.")

    def _run_learning_queue(self, failed_id: Any):
        if not failed_id:
            return []
        vault = getattr(self.context, "context_vault", None)
        if not vault:
            return []
        try:
            return LearningQueue(vault).analyze_failed_interpretation(int(failed_id))
        except Exception:
            return []

    @staticmethod
    def _preview_message(plan: StructuredActionPlan) -> str:
        text = (plan.preview_text or "Se requiere confirmacion antes de ejecutar esta accion.").strip()
        if "confirmas" not in text.lower():
            text = f"{text}\n\nConfirmas?"
        return text

    @staticmethod
    def _intent_value(intent: Any) -> str:
        return intent.value if hasattr(intent, "value") else str(intent or "unknown")

    def _last_user_text(self) -> str:
        recent = self.context.get_context("recent_user_messages") if self.context else []
        if isinstance(recent, list) and recent:
            return str(recent[-1])
        return ""

    @staticmethod
    def _detect_name_column(columns: List[Any]) -> str:
        for column in columns:
            text = TextNormalizer.strip_accents(str(column)).lower()
            if "nombre" in text or "persona" in text or "cliente" in text or "participante" in text:
                return str(column)
        return str(columns[0]) if columns else ""

    @staticmethod
    def _detect_reference_column(columns: List[Any]) -> str:
        for column in columns:
            text = TextNormalizer.strip_accents(str(column)).lower()
            if "foto" in text or "referencia" in text or "imagen" in text:
                return str(column)
        return ""

    @staticmethod
    def _default_question_for(intent: str) -> str:
        if intent in {
            "excel_to_facesync_pipeline",
            "prepare_facesync_pipeline",
            "run_facesync",
            "run_reference_face_matching",
            "classify_photos_by_reference",
        }:
            return "¿Puedes indicarme el Excel o CSV, la carpeta de fotos y el destino?"
        if intent == "delete_folders_from_excel":
            return "¿Qué Excel y destino quieres usar para identificar las carpetas a eliminar?"
        return "Me falta un dato para continuar."

    def _is_confirm(self, normalized_text: str) -> bool:
        text = normalized_text.strip()
        tokens = set(text.split())
        return text in self.CONFIRM_WORDS or any(
            (phrase in tokens if " " not in phrase else phrase in text)
            for phrase in self.CONFIRM_WORDS
        )

    def _is_cancel(self, normalized_text: str) -> bool:
        text = normalized_text.strip()
        tokens = set(text.split())
        return text in self.CANCEL_WORDS or any(
            (phrase in tokens if " " not in phrase else phrase in text)
            for phrase in self.CANCEL_WORDS
        )

    def _log_unhandled_intent(
        self,
        text: str,
        normalized,
        interpretation: Dict[str, Any],
        *,
        action_taken: str,
    ):
        try:
            secure_log = self._security().secure_internal_path("logs/unhandled_intents.jsonl")
            if not secure_log:
                return
            log_path = Path(secure_log)
            logs_dir = log_path.parent
            logs_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "text": str(text or "")[:500],
                "normalized": getattr(normalized, "normalized", "")[:500],
                "best_intent": interpretation.get("intent", "unknown"),
                "confidence": interpretation.get("confidence", 0.0),
                "reason": interpretation.get("reason", ""),
                "source": interpretation.get("source", "rules"),
                "action_taken": action_taken,
            }
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            print(f"[INTENT_LOG] No pude registrar frase no entendida: {exc}")

    def _require_workspace(self) -> Optional[OrchestrationResult]:
        if not self._workspace_root():
            return OrchestrationResult.ok("Selecciona primero un workspace.", action="workspace_missing")
        return None

    def _security(self) -> SecurityManager:
        security = SecurityManager(self._workspace_root(), app_data_root=self._app_data_root())
        # Propagar las raices del workspace compuesto para validar contra todas.
        roots = self.context.get_context("workspace_roots") if self.context else None
        if roots and hasattr(security, "set_workspace_roots"):
            security.set_workspace_roots(roots)
        return security

    def _files(self) -> FileCapabilities:
        return FileCapabilities(self._workspace_root(), self._security())

    def _docs(self) -> DocumentCapabilities:
        return DocumentCapabilities(self._workspace_root(), self._security())

    def _facesync(self) -> FaceSyncCapabilities:
        return FaceSyncCapabilities(
            self._workspace_root(),
            self._security(),
            account_id=self.account_id,
        )

    def _search(self) -> SearchCapabilities:
        return SearchCapabilities(self._workspace_root(), self._security())

    def _workspace(self) -> WorkspaceCapabilities:
        return WorkspaceCapabilities(self._workspace_root(), self._security())

    # ------------------------------------------------------------------
    # Plan execution
    # ------------------------------------------------------------------

    def execute_structured_plan(self, plan: StructuredActionPlan) -> Dict[str, Any]:
        intent = self._intent_value(plan.intent)
        state: Dict[str, Any] = {
            "success": True,
            "intent": intent,
            "action": intent,
            "data": {},
            "steps": [],
            "refresh": False,
        }

        for step in plan.steps:
            action = step.action
            args = dict(step.args or {})
            result = self._execute_structured_step(action, args, state)
            state["steps"].append(
                {
                    "tool_name": step.tool_name,
                    "action": action,
                    "args": args,
                    "result": result,
                }
            )

            if result.get("requires_clarification"):
                return {
                    "success": False,
                    "requires_clarification": True,
                    "question": result.get("question", "Me falta un dato para continuar."),
                    "missing_slot": result.get("missing_slot", ""),
                    "error_type": result.get("error_type") or "missing_context",
                    "action": intent,
                    "intent": intent,
                    "data": {**state.get("data", {}), **(result.get("data") or {})},
                    "steps": state["steps"],
                }

            if not result.get("success", False):
                return {
                    "success": False,
                    "action": intent,
                    "intent": intent,
                    "error": result.get("error", "Error desconocido"),
                    "error_type": result.get("error_type") or "unknown_tool_error",
                    "data": {**state.get("data", {}), **(result.get("data") or {})},
                    "steps": state["steps"],
                    "refresh": state.get("refresh", False),
                }

            if result.get("refresh"):
                state["refresh"] = True
            if result.get("data"):
                state["data"].update(result["data"])

        if state.get("refresh"):
            refresher = getattr(self.context, "refresh_available_entries", None)
            if callable(refresher):
                refresher()

        return state

    def _execute_structured_step(self, action: str, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        if action == "read_document":
            return self._structured_read_document(args)
        if action == "validate_table":
            return self._structured_validate_table(args, state)
        if action in {"validate_column", "validate_name_column", "validate_reference_column"}:
            return self._structured_validate_column(args, state, action)
        if action == "ensure_folder":
            return self._structured_ensure_folder(args)
        if action in {"validate_source_folder", "validate_destination_folder"}:
            return self._structured_validate_folder(args, action)
        if action == "create_folders_from_table":
            return self._structured_create_folders_from_table(args)
        if action == "run_reference_face_matching":
            return self._structured_run_reference_face_matching(args)
        if action == "create_folder":
            path = self._join_path(args.get("destination_folder") or "", args.get("folder_name") or "")
            raw = self._files().create_directory(path)
            if self._raw_failed(raw):
                return {"success": False, "error": raw, "error_type": "folder_create_failed"}
            return {"success": True, "refresh": True, "data": {"path": path, "tool_result": raw, **args}}
        if action == "create_multiple_folders":
            quantity = int(args.get("quantity") or 0)
            base_name = str(args.get("base_name") or "").strip()
            destination = str(args.get("destination_folder") or "").strip()
            raw = self._files().create_multiple_folders(quantity, base_name, destination)
            if self._raw_failed(raw):
                return {"success": False, "error": raw, "error_type": "folder_create_failed", "data": {"paths": raw.get("created", []) + raw.get("reused", [])}}
            paths = raw.get("created", []) + raw.get("reused", [])
            meta = raw.get("metadata", {})
            return {"success": True, "refresh": True, "data": {"paths": paths, "created_count": meta.get("created_count", 0), "reused_count": meta.get("reused_count", 0), "destination": destination, "tool_result": raw, **args}}
        if action == "create_file":
            path = self._join_path(args.get("destination_folder") or "", args.get("file_name") or "")
            raw = self._files().create_file(path, content=args.get("content") or "")
            if self._raw_failed(raw):
                return {"success": False, "error": raw, "error_type": "file_create_failed"}
            return {"success": True, "refresh": True, "data": {"path": path, **args}}
        if action == "move_item":
            raw = self._files().move_path(args.get("target") or "", args.get("destination_folder") or "")
            if self._raw_failed(raw):
                return {"success": False, "error": raw, "error_type": "move_failed"}
            moved = list(raw.get("moved") or raw.get("reused") or []) if isinstance(raw, dict) else []
            return {
                "success": True,
                "refresh": True,
                "data": {**args, "source": args.get("target"), "destination": args.get("destination_folder"), "path": moved[-1] if moved else "", "tool_result": raw},
            }
        if action == "copy_item":
            raw = self._files().copy_path(args.get("target") or "", args.get("destination_folder") or "")
            if self._raw_failed(raw):
                return {"success": False, "error": raw, "error_type": "copy_failed"}
            copied = list(raw.get("copied") or raw.get("reused") or []) if isinstance(raw, dict) else []
            return {
                "success": True,
                "refresh": True,
                "data": {**args, "source": args.get("target"), "destination": args.get("destination_folder"), "path": copied[-1] if copied else "", "tool_result": raw},
            }
        if action == "rename_item":
            raw = self._files().rename_path(args.get("target") or "", args.get("new_name") or "")
            if self._raw_failed(raw):
                return {"success": False, "error": raw, "error_type": "rename_failed"}
            moved = list(raw.get("moved") or raw.get("reused") or []) if isinstance(raw, dict) else []
            return {"success": True, "refresh": True, "data": {**args, "path": moved[-1] if moved else "", "tool_result": raw}}
        if action == "delete_item":
            raw = self._files().delete_path(args.get("target") or "", recursive=True)
            if self._raw_failed(raw):
                return {"success": False, "error": raw, "error_type": "delete_failed"}
            return {"success": True, "refresh": True, "data": {**args, "tool_result": raw}}
        if action == "search_files":
            result = self._search().search_by_name(args.get("query") or "*")
            if not result.get("success"):
                return {"success": False, "error": result.get("error", "Error buscando archivos."), "error_type": "search_failed"}
            return {"success": True, "data": {"results": result.get("results", []), "query": args.get("query") or "*"}}
        if action == "scan_workspace":
            return {"success": True, "data": {"tree": self._workspace().get_workspace_tree()}}
        return {"success": False, "error": f"Accion local no registrada: {action}", "error_type": "unknown_tool_error"}

    def _structured_read_document(self, args: Dict[str, Any]) -> Dict[str, Any]:
        path = self._find_file(args.get("path") or args.get("table_path") or "", extensions=None)
        if not path:
            return {"success": False, "error": "No encontre el documento.", "error_type": "file_not_found"}
        result = self._docs().read_document(path)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "No pude leer el documento."), "error_type": "file_not_found"}
        return {"success": True, "data": {"path": path, "table_path": path, "document": result}}

    def _structured_validate_table(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        table_path = args.get("table_path") or state["data"].get("table_path") or ""
        if not table_path:
            return {"success": False, "error": "Falta el archivo de tabla.", "error_type": "missing_table_path"}
        result = self._docs().read_document(table_path)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "No pude leer la tabla."), "error_type": "file_not_found"}
        if result.get("type") not in {"excel", "csv"}:
            return {"success": False, "error": "El documento no es Excel/CSV.", "error_type": "invalid_table"}
        columns = result.get("columns") or []
        rows = result.get("rows") or 0
        return {"success": True, "data": {"table_path": table_path, "excel_path": table_path, "document": result, "columns": columns, "rows": rows}}

    def _structured_validate_column(self, args: Dict[str, Any], state: Dict[str, Any], action: str) -> Dict[str, Any]:
        table_path = args.get("table_path") or state["data"].get("table_path") or ""
        column = args.get("column_name") or args.get("name_column") or args.get("reference_column") or ""
        columns = list(state["data"].get("columns") or [])
        if not columns and table_path:
            read = self._docs().read_document(table_path)
            if read.get("success"):
                columns = list(read.get("columns") or [])
        if not column:
            return {"success": False, "requires_clarification": True, "missing_slot": "column_name", "question": "Que columna debo usar?", "error_type": "missing_column"}
        if column not in columns:
            return {
                "success": False,
                "error": f"No encontre la columna '{column}'.",
                "error_type": "column_not_found",
                "column": column,
                "data": {"available_columns": columns, "columns": columns, "table_path": table_path},
            }
        data_key = "reference_column" if action == "validate_reference_column" else "name_column"
        return {"success": True, "data": {data_key: column, "columns": columns, "available_columns": columns}}

    def _structured_ensure_folder(self, args: Dict[str, Any]) -> Dict[str, Any]:
        destination = str(args.get("destination_folder") or "").strip()
        if not destination:
            return {"success": True, "data": {"destination_folder": ""}}
        raw = self._files().create_directory(destination)
        if self._raw_failed(raw):
            return {"success": False, "error": raw, "error_type": "folder_not_found", "folder": destination}
        return {"success": True, "refresh": True, "data": {"destination_folder": destination, "destination": destination}}

    def _structured_validate_folder(self, args: Dict[str, Any], action: str) -> Dict[str, Any]:
        key = "source_folder" if action == "validate_source_folder" else "destination_folder"
        folder = str(args.get(key) or "").strip()
        if not folder:
            return {"success": False, "requires_clarification": True, "missing_slot": key, "question": self._question_for_missing_slot("run_reference_face_matching", key)}
        secure = self._security().secure_path(folder)
        if not secure:
            return {"success": False, "error": "La ruta sale del workspace.", "error_type": "path_outside_workspace", "folder": folder}
        path = Path(secure)
        if action == "validate_source_folder" and not path.is_dir():
            return {"success": False, "error": f"No encontre la carpeta '{folder}'.", "error_type": "folder_not_found", "folder": folder}
        if action == "validate_destination_folder" and not path.exists():
            raw = self._files().create_directory(folder)
            if self._raw_failed(raw):
                return {"success": False, "error": raw, "error_type": "folder_not_found", "folder": folder}
        return {"success": True, "data": {key: folder}}

    def _structured_create_folders_from_table(self, args: Dict[str, Any]) -> Dict[str, Any]:
        table_path = args.get("table_path") or ""
        column = args.get("name_column") or args.get("column_name") or ""
        destination = args.get("destination_folder") or ""
        report = self._docs().create_folders_from_table(table_path, column=column, destination=destination)
        if report.get("requires_clarification"):
            return {
                "success": False,
                "requires_clarification": True,
                "missing_slot": "name_column",
                "question": "Que columna contiene los nombres?",
                "error_type": "missing_column",
                "data": {"available_columns": report.get("columns", [])},
            }
        if not report.get("success"):
            return {"success": False, "error": report.get("error", "No pude crear carpetas desde la tabla."), "error_type": "column_not_found" if "columna" in str(report.get("error", "")).lower() else "unknown_tool_error"}
        return {
            "success": True,
            "refresh": True,
            "data": {
                "folder_report": report,
                "folders_created": len(report.get("created", [])) if isinstance(report.get("created"), list) else report.get("created", report.get("folders_created", 0)),
                "destination_folder": report.get("destination", destination or "."),
                "destination": report.get("destination", destination or "."),
                "name_column": report.get("column_used", column),
                "table_path": table_path,
                "excel_path": table_path,
                "rows": report.get("total_rows", 0),
                "created_items": report.get("created", []) if isinstance(report.get("created"), list) else report.get("folders", []),
                "reused_items": report.get("reused", []),
            },
        }

    @staticmethod
    def _norm_folder_name(text: str) -> str:
        """Normaliza un nombre de carpeta para comparar: sin acentos, sin
        mayusculas, sin espacios/slashes sobrantes. (p.ej. 'Rubén' -> 'ruben')."""
        import unicodedata
        s = unicodedata.normalize("NFKD", str(text or ""))
        s = "".join(c for c in s if not unicodedata.combining(c))
        return s.strip().strip("\\/").strip().lower()

    def _resolve_source_folder_path(self, name: str, state: Dict[str, Any]) -> str:
        """Resuelve UN nombre de carpeta origen a su ruta real, robusto.

        Arregla el caso donde el resolver devolvia '.' (p.ej. 'Rubén' con acento
        cuando la carpeta real es 'RUBEN') y por eso el motor no leia esa carpeta.
        Orden: (0) si ya es ruta real, usarla; (1) resolver normal, pero RECHAZAR
        '.'/vacio; (2) buscar la carpeta por nombre (sin acentos/mayusculas) entre
        las raices del workspace y sus subcarpetas; (3) ultimo recurso, el nombre.
        NO toca el motor ni la comprension: solo asegura que cada carpeta escrita
        llegue al motor como ruta real."""
        raw = str(name or "").strip().strip('"').strip("'")
        if not raw:
            return name
        try:
            if os.path.isdir(raw):
                return raw
        except Exception:
            pass
        try:
            _r = self.location_resolver.resolve(raw, state, kind="folder")
            rel = _r.relative_path if (_r and _r.success and _r.relative_path) else ""
        except Exception:
            rel = ""
        if rel and rel.strip().strip("\\/").strip() not in ("", "."):
            return rel
        target = self._norm_folder_name(raw)
        roots: List[str] = []
        try:
            ctx_roots = self.context.get_context("workspace_roots") if self.context else None
            if ctx_roots:
                roots.extend([str(r) for r in ctx_roots if r])
        except Exception:
            pass
        wr = self._workspace_root()
        if wr and wr not in roots:
            roots.append(wr)
        for root in roots:
            try:
                if os.path.isdir(root) and self._norm_folder_name(os.path.basename(os.path.normpath(root))) == target:
                    return root
                for child in os.listdir(root):
                    full = os.path.join(root, child)
                    if os.path.isdir(full) and self._norm_folder_name(child) == target:
                        return full
            except Exception:
                continue
        return raw

    def _structured_run_reference_face_matching(self, args: Dict[str, Any]) -> Dict[str, Any]:
        table_path = args.get("table_path") or ""
        source_folder = args.get("source_folder") or ""
        source_folders = [s for s in (args.get("source_folders") or []) if s]
        if len(source_folders) >= 2:
            # Resolver CADA carpeta (incluye nombres de RAICES del explorador,
            # p.ej. FRANK/RUBEN/ARTURO) a su ruta real, para que el motor combine
            # y SUME las fotos de todas, no solo de la primera.
            try:
                _state = self.context.build_system_state("") if self.context else {}
            except Exception:
                _state = getattr(self.context, "current_context", {}) if self.context else {}
            resolved_sources = []
            for _sf in source_folders:
                resolved_sources.append(self._resolve_source_folder_path(_sf, _state))
            source_arg = resolved_sources
        else:
            source_arg = source_folder
        destination = args.get("destination_folder") or ""
        name_column = args.get("name_column") or args.get("column_name") or ""
        reference_column = args.get("reference_column") or ""
        facesync = self._facesync()
        self._facesync_cancel_event.clear()

        def progress_callback(payload: Dict[str, Any]):
            if self.async_callback:
                self.async_callback(True, payload.get("message", "Procesando FaceSync..."), payload)

        if hasattr(facesync, "run_reference_face_matching"):
            result = facesync.run_reference_face_matching(
                table_path=table_path,
                source_folder=source_arg,
                destination_folder=destination,
                name_column=name_column,
                reference_column=reference_column,
                progress_callback=progress_callback,
                cancel_event=self._facesync_cancel_event,
            )
        else:
            result = facesync.run_face_sync(
                excel_path=table_path,
                source_folder=source_folder,
                dest_folder=destination,
                name_column=name_column,
                reference_column=reference_column,
            )
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "No pude ejecutar FaceSync."), "error_type": result.get("error_type") or "deepface_error"}
        return {
            "success": True,
            "refresh": True,
            "data": {
                "table_path": table_path,
                "excel_path": table_path,
                "source_folder": source_folder,
                "source_folders": source_folders,
                "destination_folder": destination,
                "name_column": name_column,
                "reference_column": reference_column,
                "facesync": result,
                "rows": result.get("total_personas", 0),
                "report_path": result.get("report_path", ""),
                "copied": result.get("copied", []),
                "reused": result.get("reused", []),
                "skipped": result.get("skipped", []),
                "errors": result.get("errors", []),
            },
        }

    def request_cancel(self) -> Dict[str, Any]:
        self._facesync_cancel_event.set()
        return {"success": True, "message": "Cancelacion solicitada."}

    def execute_plan(self, plan: ActionPlan) -> Dict[str, Any]:
        state: Dict[str, Any] = {
            "success": True,
            "intent": plan.intent,
            "action": plan.intent,
            "data": {},
            "steps": [],
            "refresh": False,
        }

        for step in plan.steps:
            tool = step.tool
            args = dict(step.args or {})
            handler = getattr(self, f"_step_{tool}", None)
            if not handler:
                return self._execution_error(plan.intent, f"Tool local no registrada: {tool}", state)

            result = handler(args, state)
            state["steps"].append({"tool": tool, "args": args, "result": result})

            if result.get("requires_clarification"):
                return {
                    "success": False,
                    "requires_clarification": True,
                    "question": result.get("question", "Me falta un dato para continuar."),
                    "missing_slot": result.get("missing_slot", ""),
                    "action": plan.intent,
                    "intent": plan.intent,
                    "data": {**state.get("data", {}), **(result.get("data") or {})},
                    "steps": state["steps"],
                }

            if not result.get("success", False):
                return self._execution_error(plan.intent, result.get("error", "Error desconocido"), state)

            if result.get("refresh"):
                state["refresh"] = True
            if result.get("data"):
                state["data"].update(result["data"])

        if state.get("refresh"):
            refresher = getattr(self.context, "refresh_available_entries", None)
            if callable(refresher):
                refresher()

        return state

    @staticmethod
    def _execution_error(intent: str, error: str, state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": False,
            "action": intent,
            "intent": intent,
            "error": error,
            "data": state.get("data", {}),
            "steps": state.get("steps", []),
            "refresh": state.get("refresh", False),
        }

    @staticmethod
    def _raw_failed(raw: Any) -> bool:
        if isinstance(raw, dict):
            return not bool(raw.get("success"))
        raw_lower = str(raw or "").strip().lower()
        return (
            raw_lower.startswith("error")
            or raw_lower.startswith("operacion cancelada")
            or raw_lower.startswith("operación cancelada")
            or raw_lower.startswith("no pude")
            or raw_lower.startswith("el archivo ya existe")
            or raw_lower.startswith("el destino")
            or raw_lower.startswith("el origen")
            or raw_lower.startswith("el elemento")
            or raw_lower.startswith("la carpeta")
        )

    @staticmethod
    def _join_path(destination: str, name: str) -> str:
        destination = str(destination or "").strip().strip("/\\")
        name = str(name or "").strip().strip("/\\")
        if destination and name:
            return str(Path(destination) / name).replace("\\", "/")
        return name or destination

    @staticmethod
    def _indexed_name(base_name: str, index: int, total: int, default_suffix: str = "") -> str:
        base = str(base_name or "").strip().strip("/\\")
        width = max(2, len(str(total)))
        path = Path(base)
        suffix = path.suffix or default_suffix
        stem = path.stem if suffix else base
        return f"{stem}_{index:0{width}d}{suffix}"

    # ------------------------------------------------------------------
    # Direct steps
    # ------------------------------------------------------------------

    def _step_crear_carpeta(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        path = args.get("path") or ""
        raw = self._files().create_directory(path)
        if self._raw_failed(raw):
            return {"success": False, "error": raw}
        return {
            "success": True,
            "refresh": True,
            "data": {
                "path": path,
                "folder_name": args.get("folder_name") or Path(path).name,
                "destination": args.get("destination") or "",
                "destination_label": args.get("destination_label") or args.get("destination") or "",
            },
        }

    def _step_crear_archivo(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        path = args.get("path") or ""
        raw = self._files().create_file(path, content=args.get("content") or "")
        if self._raw_failed(raw):
            return {"success": False, "error": raw}
        return {
            "success": True,
            "refresh": True,
            "data": {
                "path": path,
                "file_name": args.get("file_name") or Path(path).name,
                "destination": args.get("destination") or "",
                "destination_label": args.get("destination_label") or args.get("destination") or "",
            },
        }

    def _step_crear_multiples_carpetas(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        quantity = int(args.get("quantity") or 0)
        base_name = str(args.get("base_name") or "").strip()
        destination = str(args.get("destination") or "").strip()
        if quantity <= 0:
            return {"success": False, "requires_clarification": True, "question": "Cuantas carpetas quieres crear?"}
        if quantity > 200:
            return {"success": False, "error": "Por seguridad, puedo crear hasta 200 carpetas por solicitud."}
        if not base_name:
            return {
                "success": False,
                "requires_clarification": True,
                "question": "Con que nombre base quieres que las cree? Por ejemplo: fotos_01, fotos_02...",
            }

        paths = []
        for index in range(1, quantity + 1):
            name = self._indexed_name(base_name, index, quantity)
            path = self._join_path(destination, name)
            raw = self._files().create_directory(path)
            if self._raw_failed(raw):
                return {"success": False, "error": raw, "data": {"paths": paths}}
            paths.append(path)

        return {
            "success": True,
            "refresh": True,
            "data": {
                "paths": paths,
                "created_count": len(paths),
                "base_name": base_name,
                "destination": destination,
                "destination_label": args.get("destination_label") or destination,
            },
        }

    def _step_crear_multiples_archivos(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        quantity = int(args.get("quantity") or 0)
        base_name = str(args.get("base_name") or "").strip()
        destination = str(args.get("destination") or "").strip()
        if quantity <= 0:
            return {"success": False, "requires_clarification": True, "question": "Cuantos archivos quieres crear?"}
        if quantity > 200:
            return {"success": False, "error": "Por seguridad, puedo crear hasta 200 archivos por solicitud."}
        if not base_name:
            return {
                "success": False,
                "requires_clarification": True,
                "question": "Con que nombre base quieres que los cree? Por ejemplo: archivo_01, archivo_02...",
            }

        paths = []
        for index in range(1, quantity + 1):
            name = self._indexed_name(base_name, index, quantity, default_suffix=".txt")
            path = self._join_path(destination, name)
            raw = self._files().create_file(path, content="")
            if self._raw_failed(raw):
                return {"success": False, "error": raw, "data": {"paths": paths}}
            paths.append(path)

        return {
            "success": True,
            "refresh": True,
            "data": {
                "paths": paths,
                "created_count": len(paths),
                "base_name": base_name,
                "destination": destination,
                "destination_label": args.get("destination_label") or destination,
            },
        }

    def _step_leer_documento(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        path = self._find_file(args.get("path") or "", extensions=self._extensions_for_doc_type(args.get("document_type") or ""))
        if not path:
            return {"success": False, "error": "No encontre el documento que quieres leer."}

        result = self._docs().read_document(path)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "No pude leer el documento.")}

        return {
            "success": True,
            "data": {
                "path": path,
                "document": result,
            },
        }

    def _step_mover(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        source = args.get("source") or ""
        destination = args.get("destination") or ""
        raw = self._files().move_path(source, destination)
        if self._raw_failed(raw):
            return {"success": False, "error": raw}
        final_path = str(Path(destination) / Path(source).name).replace("\\", "/")
        return {"success": True, "refresh": True, "data": {"source": source, "destination": destination, "path": final_path}}

    def _step_copiar(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        source = args.get("source") or ""
        destination = args.get("destination") or ""
        raw = self._files().copy_path(source, destination)
        if self._raw_failed(raw):
            return {"success": False, "error": raw}
        final_path = str(Path(destination) / Path(source).name).replace("\\", "/")
        return {"success": True, "refresh": True, "data": {"source": source, "destination": destination, "path": final_path}}

    def _step_renombrar(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        target = args.get("target") or ""
        new_name = args.get("new_name") or ""
        raw = self._files().rename_path(target, new_name)
        if self._raw_failed(raw):
            return {"success": False, "error": raw}
        new_path = str(Path(target).parent / new_name) if str(Path(target).parent) != "." else new_name
        return {"success": True, "refresh": True, "data": {"target": target, "new_name": new_name, "path": new_path}}

    def _step_borrar(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        target = args.get("target") or ""
        raw = self._files().delete_path(target, recursive=bool(args.get("recursive")))
        if self._raw_failed(raw):
            return {"success": False, "error": raw}
        return {"success": True, "refresh": True, "data": {"target": target}}

    def _step_buscar_archivos(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        extension = args.get("extension") or ""
        query = args.get("query") or "*"
        if extension:
            result = self._search().search_by_extension(extension)
        else:
            result = self._search().search_by_name(query)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "Error buscando archivos.")}
        return {"success": True, "data": {"results": result.get("results", []), "query": query}}

    def _step_escanear_workspace(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        tree = self._workspace().get_workspace_tree()
        return {"success": True, "data": {"tree": tree}}

    # ------------------------------------------------------------------
    # Excel / FaceSync steps
    # ------------------------------------------------------------------

    def _step_resolver_excel(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        hint = args.get("hint") or ""
        resolved = self._resolve_excel(hint)
        if resolved.get("requires_clarification"):
            return resolved
        if not resolved.get("success"):
            return {"success": False, "error": resolved.get("error", "No pude resolver el Excel.")}
        return {"success": True, "data": {"excel_path": resolved["path"], "table_path": resolved["path"]}}

    def _step_leer_excel(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        excel_path = args.get("path") or state["data"].get("excel_path")
        if not excel_path:
            return {"success": False, "error": "No tengo claro que Excel debo leer."}
        result = self._docs().read_document(excel_path)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "No pude leer el Excel.")}
        if result.get("type") not in ("excel", "csv"):
            return {"success": False, "error": "El documento encontrado no es Excel/CSV."}
        columns = result.get("columns", [])
        rows = result.get("rows", 0)
        self.context.update_context("available_columns", columns)
        self.context.update_context("last_table_columns", columns)
        self.context.update_context("last_table_path", excel_path)
        self.context.update_context("last_table_rows", rows)
        return {"success": True, "data": {"excel_path": excel_path, "table_path": excel_path, "excel_document": result, "rows": rows, "columns": columns}}

    def _step_detectar_columnas(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        excel_path = state["data"].get("excel_path")
        columns = list(state["data"].get("columns") or [])
        require_reference = bool(args.get("require_reference"))
        requested_name = args.get("name_column") or ""
        requested_reference = args.get("reference_column") or ""

        name_column = self._choose_column(columns, requested_name, self._name_column_candidates())
        reference_column = self._choose_column(columns, requested_reference, self._reference_column_candidates())

        if not name_column:
            column_list = ", ".join(map(str, columns))
            return {
                "success": False,
                "requires_clarification": True,
                "missing_slot": "name_column",
                "question": f"Encontre estas columnas: {column_list}. Que columna contiene los nombres para crear las carpetas?",
                "data": {"excel_path": excel_path, "columns": columns, "available_columns": columns},
            }

        if require_reference and not reference_column:
            column_list = ", ".join(map(str, columns))
            return {
                "success": False,
                "requires_clarification": True,
                "missing_slot": "reference_column",
                "question": f"Encontre estas columnas: {column_list}. Que columna contiene la foto o codigo de referencia?",
                "data": {"excel_path": excel_path, "columns": columns, "available_columns": columns, "name_column": name_column},
            }

        self.context.update_context("available_columns", columns)
        self.context.update_context("last_name_column", name_column)
        if reference_column:
            self.context.update_context("last_reference_column", reference_column)

        return {
            "success": True,
            "data": {
                "excel_path": excel_path,
                "name_column": name_column,
                "reference_column": reference_column,
            },
        }

    def _step_crear_carpetas_desde_excel(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        excel_path = state["data"].get("excel_path")
        column = args.get("column") or state["data"].get("name_column") or ""
        destination = args.get("destination") or ""
        if not excel_path:
            return {"success": False, "error": "No tengo claro que Excel debo usar."}

        report = self._docs().create_folders_from_excel(excel_path, column=column, destination=destination)
        if report.get("requires_clarification"):
            columns = ", ".join(map(str, report.get("columns", [])))
            return {
                "success": False,
                "requires_clarification": True,
                "missing_slot": "name_column",
                "question": f"Encontre estas columnas: {columns}. Que columna contiene los nombres para crear las carpetas?",
            }
        if not report.get("success"):
            return {"success": False, "error": report.get("error", "No pude crear carpetas desde el Excel.")}

        return {
            "success": True,
            "refresh": True,
            "data": {
                "folder_report": report,
                "folders_created": len(report.get("created", [])) if isinstance(report.get("created"), list) else report.get("created", report.get("folders_created", 0)),
                "destination_folder": report.get("destination", destination or "."),
                "destination": report.get("destination", destination or "."),
                "name_column": report.get("column_used", column),
            },
        }

    def _step_borrar_carpetas_desde_excel(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        excel_path = state["data"].get("excel_path")
        column = args.get("column") or state["data"].get("name_column") or ""
        destination = args.get("destination") or ""
        if not excel_path:
            return {"success": False, "error": "No tengo claro que Excel debo usar."}

        report = self._docs().delete_folders_from_excel(excel_path, column=column, destination=destination)
        if report.get("requires_clarification"):
            columns = ", ".join(map(str, report.get("columns", [])))
            return {
                "success": False,
                "requires_clarification": True,
                "question": f"Encontre estas columnas: {columns}. Cual columna identifica las carpetas que quieres borrar?",
            }
        if not report.get("success"):
            return {"success": False, "error": report.get("error", "No pude borrar carpetas desde el Excel.")}

        return {
            "success": True,
            "refresh": True,
            "data": {
                "delete_report": report,
                "deleted_count": report.get("deleted", 0),
                "destination_folder": report.get("destination", destination or "."),
                "destination": report.get("destination", destination or "."),
                "name_column": report.get("column_used", column),
            },
        }

    def _step_resolver_carpeta_fotos(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        hint = args.get("hint") or ""
        resolved = self._resolve_photo_folder(hint)
        if resolved.get("requires_clarification"):
            return resolved
        if not resolved.get("success"):
            return {"success": False, "error": resolved.get("error", "No pude resolver la carpeta de fotos.")}
        return {"success": True, "data": {"source_folder": resolved["path"]}}

    def _step_ejecutar_facesync(self, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        excel_path = state["data"].get("excel_path")
        source_folder = state["data"].get("source_folder")
        destination = args.get("destination") or state["data"].get("destination_folder") or state["data"].get("destination") or ""
        name_column = state["data"].get("name_column") or ""
        reference_column = state["data"].get("reference_column") or ""

        if not excel_path:
            return {"success": False, "error": "Falta el Excel para ejecutar FaceSync."}
        if not source_folder:
            return {
                "success": False,
                "requires_clarification": True,
                "missing_slot": "source_folder",
                "question": "Que carpeta contiene las fotos originales?",
            }
        if not destination:
            return {
                "success": False,
                "requires_clarification": True,
                "missing_slot": "destination_folder",
                "question": "¿Dónde quieres guardar las fotos clasificadas?",
            }
        if not name_column:
            return {
                "success": False,
                "requires_clarification": True,
                "missing_slot": "name_column",
                "question": "Que columna contiene los nombres para crear las carpetas?",
            }
        if not reference_column:
            return {
                "success": False,
                "requires_clarification": True,
                "missing_slot": "reference_column",
                "question": "Que columna contiene la foto o codigo de referencia?",
            }

        def final_callback(success: bool, message: str):
            if self.async_callback:
                self.async_callback(
                    success,
                    message,
                    {
                        "excel_path": excel_path,
                        "table_path": excel_path,
                        "source_folder": source_folder,
                        "destination_folder": destination,
                        "name_column": name_column,
                        "reference_column": reference_column,
                    },
                )

        result = self._facesync().run_face_sync(
            excel_path=excel_path,
            source_folder=source_folder,
            dest_folder=destination,
            name_column=name_column,
            reference_column=reference_column,
            callback=final_callback,
        )
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "No pude iniciar FaceSync.")}

        return {
            "success": True,
            "refresh": True,
            "data": {
                "excel_path": excel_path,
                "table_path": excel_path,
                "source_folder": source_folder,
                "destination_folder": destination,
                "name_column": name_column,
                "reference_column": reference_column,
                "mode": "reference_face_matching",
                "facesync": result,
            },
        }

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def _extensions_for_doc_type(self, doc_type: str) -> Optional[set[str]]:
        mapping = {
            "excel": {".xlsx", ".xls", ".csv"},
            "pdf": {".pdf"},
            "txt": {".txt"},
            "csv": {".csv"},
            "json": {".json"},
            "docx": {".docx"},
        }
        return mapping.get(str(doc_type or "").lower())

    def _find_file(self, query: str, extensions: Optional[set[str]] = None) -> Optional[str]:
        query = str(query or "").strip()
        if not query:
            return None

        secure = self._security().secure_path(query)
        if secure and Path(secure).is_file():
            return self._relative_to_workspace(Path(secure))

        candidates = self._iter_workspace_files(extensions=extensions)
        scored = self._score_candidates(query, candidates)
        if not scored:
            return query
        return self._relative_to_workspace(scored[0][1])

    def _resolve_excel(self, hint: str) -> Dict[str, Any]:
        hint = str(hint or "").strip()

        if hint:
            path = self._find_file(hint, extensions={".xlsx", ".xls", ".csv"})
            if path and self._secure_exists(path, is_file=True):
                return {"success": True, "path": path}

        for context_key in ("ultimo_excel_leido", "last_excel"):
            value = self.context.get_context(context_key)
            if value and self._secure_exists(value, is_file=True):
                return {"success": True, "path": self._relative_or_original(value)}

        excel_files = self._iter_workspace_files(extensions={".xlsx", ".xls", ".csv"})
        if len(excel_files) == 1:
            return {"success": True, "path": self._relative_to_workspace(excel_files[0])}

        if hint:
            scored = self._score_candidates(hint, excel_files)
            if scored:
                return {"success": True, "path": self._relative_to_workspace(scored[0][1])}

        if excel_files:
            options = ", ".join(self._relative_to_workspace(path) for path in excel_files[:8])
            return {
                "success": False,
                "requires_clarification": True,
                "question": f"Encontre varios Excel/CSV: {options}. Cual quieres usar?",
            }

        return {
            "success": False,
            "requires_clarification": True,
            "question": "Te entendi, pero me falta saber que Excel o CSV debo usar.",
        }

    def _resolve_photo_folder(self, hint: str) -> Dict[str, Any]:
        hint = str(hint or "").strip()

        for value in (hint, self.context.get_context("ultima_carpeta_fotos"), self.context.get_context("source_folder")):
            if value and self._secure_exists(value, is_dir=True):
                return {"success": True, "path": self._relative_or_original(value)}

        directories = self._iter_workspace_dirs()
        probable_names = {"fotos", "imagenes", "imágenes", "originales", "carpeta maestra", "maestra"}

        if hint:
            scored = self._score_candidates(hint, directories)
            if scored and scored[0][0] >= 20:
                return {"success": True, "path": self._relative_to_workspace(scored[0][1])}

        probable = []
        for directory in directories:
            norm = self._norm_name(directory.name)
            if norm in probable_names or any(token in norm.split() for token in ("foto", "fotos", "imagen", "imagenes", "originales")):
                probable.append(directory)

        if len(probable) == 1:
            return {"success": True, "path": self._relative_to_workspace(probable[0])}

        if probable:
            options = ", ".join(self._relative_to_workspace(path) for path in probable[:8])
            return {
                "success": False,
                "requires_clarification": True,
                "question": f"Te entendi: quieres clasificar las fotos por alumno usando el Excel. Encontre estas carpetas posibles: {options}. Cual contiene las fotos originales?",
            }

        return {
            "success": False,
            "requires_clarification": True,
            "question": "Te entendi: quieres clasificar fotos por alumno usando el Excel, pero me falta saber que carpeta contiene las fotos originales.",
        }

    def _iter_workspace_files(self, extensions: Optional[set[str]] = None) -> List[Path]:
        root = Path(self._workspace_root()).resolve()
        extensions = {ext.lower() for ext in extensions} if extensions else None
        files: List[Path] = []
        for current_root, dirs, filenames in os.walk(root):
            dirs[:] = filter_internal_names([name for name in dirs if name not in {".git", "__pycache__", "env", "venv", "env_ia", "node_modules"}])
            for filename in filenames:
                path = Path(current_root) / filename
                if extensions is None or path.suffix.lower() in extensions:
                    files.append(path)
        return files

    def _iter_workspace_dirs(self) -> List[Path]:
        root = Path(self._workspace_root()).resolve()
        dirs: List[Path] = []
        for current_root, dirnames, _ in os.walk(root):
            dirnames[:] = filter_internal_names([name for name in dirnames if name not in {".git", "__pycache__", "env", "venv", "env_ia", "node_modules"}])
            for dirname in dirnames:
                dirs.append(Path(current_root) / dirname)
        return dirs

    @staticmethod
    def _skip_path(path: Path) -> bool:
        blocked = {".git", "__pycache__", "env", "venv", "env_ia", "node_modules"}
        return any(part in blocked for part in path.parts)

    def _score_candidates(self, query: str, candidates: Iterable[Path]) -> List[tuple[int, Path]]:
        query_norm = self._norm_name(query)
        query_tokens = [token for token in query_norm.split() if token]
        scored: List[tuple[int, Path]] = []
        for path in candidates:
            name_norm = self._norm_name(path.stem)
            full_norm = self._norm_name(path.name)
            rel_norm = self._norm_name(self._relative_to_workspace(path))
            score = 0
            if query_norm and query_norm in (name_norm, full_norm):
                score += 100
            if query_norm and (query_norm in full_norm or query_norm in rel_norm):
                score += 50
            for token in query_tokens:
                if token in full_norm:
                    score += 15
                elif token in rel_norm:
                    score += 8
            if score > 0:
                scored.append((score, path))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored

    @staticmethod
    def _norm_name(value: str) -> str:
        text = TextNormalizer.strip_accents(str(value or "")).lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _relative_to_workspace(self, path: Path) -> str:
        try:
            return str(path.resolve(strict=False).relative_to(Path(self._workspace_root()).resolve())).replace("\\", "/")
        except Exception:
            return str(path).replace("\\", "/")

    def _relative_or_original(self, value: str) -> str:
        secure = self._security().secure_path(value)
        if secure:
            return self._relative_to_workspace(Path(secure))
        return value

    def _secure_exists(self, value: str, *, is_file: bool = False, is_dir: bool = False) -> bool:
        secure = self._security().secure_path(value)
        if not secure:
            return False
        path = Path(secure)
        if is_file:
            return path.is_file()
        if is_dir:
            return path.is_dir()
        return path.exists()

    @staticmethod
    def _name_column_candidates() -> List[str]:
        return [
            "Nombre del Alumno",
            "Nombre completo",
            "Alumno",
            "Nombre",
            "Estudiante",
            "Persona",
            "Cliente",
            "Participante",
            "Graduado",
        ]

    @staticmethod
    def _reference_column_candidates() -> List[str]:
        return [
            "Foto",
            "Referencia",
            "Foto referencia",
            "Foto de referencia",
            "ID Foto",
            "Código de foto",
            "Codigo de foto",
            "Numero de foto",
            "Número de foto",
            "No. Foto",
            "No Foto",
            "Numero",
            "Imagen",
            "Archivo",
        ]

    def _choose_column(self, columns: List[Any], requested: str, candidates: List[str]) -> str:
        if not columns:
            return ""

        normalized_columns = {self._norm_name(column): str(column) for column in columns}

        if requested:
            requested_norm = self._norm_name(requested)
            if requested_norm in normalized_columns:
                return normalized_columns[requested_norm]
            requested_tokens = set(requested_norm.split())
            for norm, original in normalized_columns.items():
                if requested_tokens and requested_tokens.issubset(set(norm.split())):
                    return original

        for candidate in candidates:
            candidate_norm = self._norm_name(candidate)
            if candidate_norm in normalized_columns:
                return normalized_columns[candidate_norm]

        for norm, original in normalized_columns.items():
            if any(self._norm_name(candidate) in norm for candidate in candidates):
                return original
            if "alumno" in norm and any("alumno" in self._norm_name(candidate) for candidate in candidates):
                return original
            if "foto" in norm and any("foto" in self._norm_name(candidate) for candidate in candidates):
                return original
            if "referencia" in norm and any("referencia" in self._norm_name(candidate) for candidate in candidates):
                return original

        return ""

    # ------------------------------------------------------------------
    # Context updates
    # ------------------------------------------------------------------

    def _remember_execution(self, execution: Dict[str, Any], plan: ActionPlan):
        if not execution.get("success"):
            return

        data = execution.get("data") or {}
        action = plan.intent

        if action == "create_folder":
            self.context.remember_action(action, folder=data.get("path"), path=data.get("path"), modified=data.get("path"))
        elif action == "create_multiple_folders":
            paths = data.get("paths") or []
            last_path = paths[-1] if paths else None
            self.context.remember_action(
                action,
                folder=data.get("destination") or last_path,
                path=last_path,
                destination=data.get("destination"),
                modified=last_path,
            )
        elif action == "create_file":
            self.context.remember_action(action, file=data.get("path"), path=data.get("path"), modified=data.get("path"))
        elif action == "create_multiple_files":
            paths = data.get("paths") or []
            last_path = paths[-1] if paths else None
            self.context.remember_action(
                action,
                file=last_path,
                path=last_path,
                destination=data.get("destination"),
                modified=last_path,
            )
        elif action == "read_document":
            path = data.get("path")
            doc_type = (data.get("document") or {}).get("type")
            self.context.remember_action(
                action,
                document=path,
                excel=path if doc_type in ("excel", "csv") else None,
                pdf=path if doc_type == "pdf" else None,
                file=path,
            )
        elif action == "create_folders_from_excel":
            self.context.remember_action(
                action,
                excel=data.get("excel_path"),
                folder=data.get("destination_folder"),
                destination=data.get("destination_folder"),
                column=data.get("name_column"),
                modified=data.get("destination_folder"),
            )
        elif action in self.FACESYNC_INTENTS:
            self.context.remember_action(
                action,
                excel=data.get("excel_path"),
                folder=data.get("destination_folder"),
                destination=data.get("destination_folder"),
                source_folder=data.get("source_folder"),
                column=data.get("name_column"),
                reference_column=data.get("reference_column"),
                modified=data.get("destination_folder"),
            )
        elif action == "move_item":
            self.context.remember_action(action, path=data.get("path"), file=data.get("path"), destination=data.get("destination"), modified=data.get("path"))
        elif action in {"move_multiple_items", "copy_multiple_items"}:
            self.context.remember_action(action, path=data.get("path"), destination=data.get("destination"), modified=data.get("path"))
            if action == "copy_multiple_items":
                copied = self.context.get_context("last_copied_items")
                if not isinstance(copied, list):
                    copied = []
                    self.context.update_context("last_copied_items", copied)
                if data.get("path"):
                    copied.append(data.get("path"))
                    del copied[:-20]
        elif action == "copy_item":
            self.context.remember_action(action, path=data.get("path"), file=data.get("path"), destination=data.get("destination"), modified=data.get("path"))
            copied = self.context.get_context("last_copied_items")
            if not isinstance(copied, list):
                copied = []
                self.context.update_context("last_copied_items", copied)
            if data.get("path"):
                copied.append(data.get("path"))
                del copied[:-20]
        elif action == "rename_item":
            self.context.remember_action(action, path=data.get("path"), file=data.get("path"), folder=data.get("path"), modified=data.get("path"))
        elif action == "delete_item":
            self.context.remember_action(action, path=data.get("target"), modified=data.get("target"))
        elif action == "delete_multiple_items":
            self.context.remember_action(action, path=data.get("target"), modified=data.get("target"))
        elif action == "delete_folders_from_excel":
            report = data.get("delete_report") or {}
            self.context.remember_action(
                action,
                excel=report.get("source") or data.get("excel_path"),
                folder=data.get("destination_folder"),
                destination=data.get("destination_folder"),
                modified=data.get("destination_folder"),
            )
        elif action == "search_files":
            self.context.remember_action(action, search=data.get("query"), search_results=data.get("results"))
        elif action == "scan_workspace":
            self.context.remember_action(action)
