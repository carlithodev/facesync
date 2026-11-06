"""
Learning candidate queue for FaceSync AI.

LearningQueue reviews failed interpretations stored by ContextVault and creates
human-reviewable improvement candidates. It never modifies source code.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from typing import Any, Dict, List, Optional


VALID_CANDIDATE_STATUSES = {"pending", "reviewed", "approved", "rejected", "implemented"}

FACESYNC_INTENTS = {
    "prepare_facesync_pipeline",
    "excel_to_facesync_pipeline",
    "run_reference_face_matching",
    "classify_photos_by_reference",
}

MISSING_CONTEXT_ERRORS = {
    "missing_context",
    "missing_source_folder",
    "missing_table_path",
    "missing_source",
    "missing_table",
    "source_folder_missing",
    "table_path_missing",
}

DESTINATION_CONTAMINATION_TERMS = ("columna", "usando", "referencia", "como referencia")


def _json_loads(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _normalize(text: Any) -> str:
    raw = str(text or "")
    normalized = unicodedata.normalize("NFKD", raw)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(normalized.lower().split())


def _compact(text: Any, limit: int = 1800) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"


class LearningQueue:
    def __init__(self, context_vault: Any, logger: Optional[logging.Logger] = None):
        self.context_vault = context_vault
        self.logger = logger or logging.getLogger(__name__)
        self.last_warning = ""

    def analyze_failed_interpretation(self, failed_id: int) -> List[Dict[str, Any]]:
        if not self._ensure_vault():
            return []
        try:
            failed = self._get_failed_interpretation(failed_id)
            if not failed:
                return []
            specs = self._build_candidate_specs(failed)
            created: List[Dict[str, Any]] = []
            for spec in specs:
                candidate = self.create_candidate_if_new(
                    failed_interpretation_id=int(failed["id"]),
                    pattern_detected=spec["pattern_detected"],
                    suggested_rule=spec["suggested_rule"],
                    suggested_test=spec["suggested_test"],
                    affected_module=spec["affected_module"],
                    risk_level=spec.get("risk_level", "medium"),
                )
                if candidate:
                    created.append(candidate)
            return created
        except Exception as exc:
            self._warn(f"No se pudo analizar failed_interpretation {failed_id}: {exc}")
            return []

    def analyze_pending_failures(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self._ensure_vault():
            return []
        try:
            candidates: List[Dict[str, Any]] = []
            for failed in self._list_failed_interpretations(limit=limit):
                candidates.extend(self.analyze_failed_interpretation(int(failed["id"])))
            return candidates
        except Exception as exc:
            self._warn(f"No se pudieron analizar errores pendientes: {exc}")
            return []

    def create_candidate_if_new(
        self,
        failed_interpretation_id: int,
        pattern_detected: str,
        suggested_rule: str,
        suggested_test: str,
        affected_module: str,
        risk_level: str = "medium",
    ) -> Optional[Dict[str, Any]]:
        if not self._ensure_vault():
            return None
        pattern = _compact(pattern_detected)
        try:
            existing = self._find_candidate(failed_interpretation_id, pattern)
            if existing:
                return None
            candidate_id = self.context_vault.create_learning_candidate(
                failed_interpretation_id,
                pattern,
                _compact(suggested_rule),
                _compact(suggested_test),
                _compact(affected_module, 300),
                _compact(risk_level, 40) or "medium",
            )
            candidate = self._get_candidate(candidate_id)
            return self._candidate_dict(candidate) if candidate else {
                "id": candidate_id,
                "failed_interpretation_id": failed_interpretation_id,
                "pattern": pattern,
                "pattern_detected": pattern,
                "suggested_rule": _compact(suggested_rule),
                "suggested_test": _compact(suggested_test),
                "affected_module": _compact(affected_module, 300),
                "risk_level": _compact(risk_level, 40) or "medium",
                "status": "pending",
            }
        except Exception as exc:
            self._warn(f"No se pudo crear learning_candidate: {exc}")
            return None

    def list_candidates(self, status: str = "pending") -> List[Dict[str, Any]]:
        if not self._ensure_vault():
            return []
        try:
            return [self._candidate_dict(row) for row in self.context_vault.list_learning_candidates(status)]
        except Exception as exc:
            self._warn(f"No se pudieron listar learning_candidates: {exc}")
            return []

    def update_candidate_status(self, candidate_id: int, status: str) -> bool:
        if status not in VALID_CANDIDATE_STATUSES:
            raise ValueError(f"status no permitido: {status}")
        if not self._ensure_vault():
            return False
        try:
            return bool(self.context_vault.update_learning_candidate_status(candidate_id, status))
        except Exception as exc:
            self._warn(f"No se pudo actualizar learning_candidate {candidate_id}: {exc}")
            return False

    def _build_candidate_specs(self, failed: Dict[str, Any]) -> List[Dict[str, str]]:
        user_text = failed.get("user_text") or ""
        system_state = failed.get("system_state") or {}
        bad_intent = _normalize(failed.get("bad_intent"))
        bad_args = failed.get("bad_args") or {}
        error_type = _normalize(failed.get("error_type"))
        specs: List[Dict[str, str]] = []

        folder_name = _normalize(bad_args.get("folder_name"))
        available_columns = system_state.get("available_columns") or system_state.get("last_table_columns") or []
        if bad_intent == "create_folder" and self._mentions_first_column(folder_name) and available_columns:
            specs.append(
                {
                    "pattern_detected": "Usuario menciono primera columna con columnas disponibles, pero se interpreto como carpeta literal.",
                    "suggested_rule": "Si available_columns existe y user_text menciona primera columna, mapear a available_columns[0] y usar create_folders_from_table.",
                    "suggested_test": "Agregar test: 'creame las carpetas de la primera columna adentro de heroes' -> create_folders_from_table.",
                    "affected_module": "PreActionFallbackManager",
                    "risk_level": "low",
                }
            )

        destination = _normalize(bad_args.get("destination_folder"))
        if destination and any(term in destination for term in DESTINATION_CONTAMINATION_TERMS):
            specs.append(
                {
                    "pattern_detected": "destination_folder contiene lenguaje de columna, uso o referencia y parece contaminado por instrucciones.",
                    "suggested_rule": "PlanGuard y PreActionFallbackManager deben rechazar destination_folder que contenga 'columna', 'usando', 'referencia' o 'como referencia', y pedir aclaracion.",
                    "suggested_test": "Agregar test: destination_folder='columna Foto usando referencia' debe bloquearse o pedir aclaracion antes de ejecutar.",
                    "affected_module": "PlanGuard/PreActionFallbackManager",
                    "risk_level": "medium",
                }
            )

        name_column = _normalize(bad_args.get("name_column"))
        reference_column = _normalize(bad_args.get("reference_column"))
        if bad_intent in FACESYNC_INTENTS and name_column and reference_column and name_column == reference_column:
            specs.append(
                {
                    "pattern_detected": "name_column y reference_column quedaron iguales en un flujo FaceSync.",
                    "suggested_rule": "Validar coherencia: name_column y reference_column no deben ser iguales en flujos FaceSync; reparar con contexto o pedir aclaracion.",
                    "suggested_test": "Agregar test: name_column='Foto' y reference_column='Foto' en classify_photos_by_reference debe bloquearse o repararse.",
                    "affected_module": "PlanGuard/PreActionFallbackManager",
                    "risk_level": "medium",
                }
            )

        if "ahora identifica" in _normalize(user_text) and self._is_missing_context_error(error_type):
            specs.append(
                {
                    "pattern_detected": "Usuario dijo ahora identifica, pero faltaba contexto suficiente para ejecutar FaceSync.",
                    "suggested_rule": "ContextVault/context_summary debe exponer last_table_path, columnas y carpetas recientes; si falta source_folder, preguntar solo por esa carpeta.",
                    "suggested_test": "Agregar test: 'Ahora identifica las fotos' con tabla previa pero sin source_folder debe preguntar por la carpeta de fotos originales.",
                    "affected_module": "ContextVault/context_summary",
                    "risk_level": "medium",
                }
            )

        correction = _compact(failed.get("user_correction"))
        if correction:
            correct_intent = _compact(failed.get("correct_intent"))
            correct_args = failed.get("correct_args") or {}
            specs.append(
                {
                    "pattern_detected": "El usuario corrigio una interpretacion fallida; usar la correccion como senal supervisada.",
                    "suggested_rule": self._correction_rule(correction, correct_intent, correct_args),
                    "suggested_test": self._correction_test(user_text, correct_intent),
                    "affected_module": "SmartOrchestrator/PreActionFallbackManager",
                    "risk_level": "medium",
                }
            )

        return specs

    def _ensure_vault(self) -> bool:
        if self.context_vault is None:
            self._warn("LearningQueue no tiene ContextVault disponible.")
            return False
        try:
            if not getattr(self.context_vault, "initialized", False):
                self.context_vault.initialize()
            return True
        except Exception as exc:
            self._warn(f"ContextVault no disponible para LearningQueue: {exc}")
            return False

    def _get_failed_interpretation(self, failed_id: int) -> Optional[Dict[str, Any]]:
        if getattr(self.context_vault, "using_memory", False):
            row = self.context_vault._memory_get("failed_interpretations", int(failed_id))
            return self._failed_dict(row) if row else None
        conn = getattr(self.context_vault, "connection", None)
        if conn is None:
            return None
        row = conn.execute("SELECT * FROM failed_interpretations WHERE id = ?", (int(failed_id),)).fetchone()
        return self._failed_dict(dict(row)) if row else None

    def _list_failed_interpretations(self, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 50), 200))
        if getattr(self.context_vault, "using_memory", False):
            rows = list(self.context_vault._memory_table("failed_interpretations"))
            rows = sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)[:limit]
            return [self._failed_dict(row) for row in rows]
        conn = getattr(self.context_vault, "connection", None)
        if conn is None:
            return []
        rows = conn.execute("SELECT * FROM failed_interpretations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._failed_dict(dict(row)) for row in rows]

    def _find_candidate(self, failed_interpretation_id: int, pattern: str) -> Optional[Dict[str, Any]]:
        if getattr(self.context_vault, "using_memory", False):
            for row in self.context_vault._memory_table("learning_candidates"):
                if int(row.get("failed_interpretation_id", 0)) == int(failed_interpretation_id) and row.get("pattern") == pattern:
                    return dict(row)
            return None
        conn = getattr(self.context_vault, "connection", None)
        if conn is None:
            return None
        row = conn.execute(
            "SELECT * FROM learning_candidates WHERE failed_interpretation_id = ? AND pattern = ? ORDER BY id DESC LIMIT 1",
            (int(failed_interpretation_id), pattern),
        ).fetchone()
        return dict(row) if row else None

    def _get_candidate(self, candidate_id: int) -> Optional[Dict[str, Any]]:
        if getattr(self.context_vault, "using_memory", False):
            row = self.context_vault._memory_get("learning_candidates", int(candidate_id))
            return dict(row) if row else None
        conn = getattr(self.context_vault, "connection", None)
        if conn is None:
            return None
        row = conn.execute("SELECT * FROM learning_candidates WHERE id = ?", (int(candidate_id),)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _failed_dict(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row.get("id"),
            "session_id": row.get("session_id"),
            "user_text": row.get("user_text") or "",
            "system_state": _json_loads(row.get("system_state_json"), {}) or {},
            "bad_intent": row.get("bad_intent") or "",
            "bad_args": _json_loads(row.get("bad_args_json"), {}) or {},
            "error_type": row.get("error_type") or "",
            "assistant_response": row.get("assistant_response") or "",
            "user_correction": row.get("user_correction") or "",
            "correct_intent": row.get("correct_intent") or "",
            "correct_args": _json_loads(row.get("correct_args_json"), {}) or {},
            "status": row.get("status") or "",
            "created_at": row.get("created_at") or "",
            "updated_at": row.get("updated_at") or "",
        }

    @staticmethod
    def _candidate_dict(row: Dict[str, Any]) -> Dict[str, Any]:
        candidate = dict(row or {})
        candidate["pattern_detected"] = candidate.get("pattern") or candidate.get("pattern_detected") or ""
        return candidate

    @staticmethod
    def _mentions_first_column(text: str) -> bool:
        return any(phrase in text for phrase in ("primera columna", "primer columna", "1era columna", "1a columna"))

    @staticmethod
    def _is_missing_context_error(error_type: str) -> bool:
        if error_type in MISSING_CONTEXT_ERRORS:
            return True
        return error_type.startswith("missing_") and ("source" in error_type or "table" in error_type or "context" in error_type)

    @staticmethod
    def _correction_rule(correction: str, correct_intent: str, correct_args: Dict[str, Any]) -> str:
        pieces = [f"Usar correccion del usuario como referencia: {correction}"]
        if correct_intent:
            pieces.append(f"Intent correcto sugerido: {correct_intent}.")
        if correct_args:
            pieces.append(f"Args correctos sugeridos: {json.dumps(correct_args, ensure_ascii=False, default=str)}.")
        return _compact(" ".join(pieces))

    @staticmethod
    def _correction_test(user_text: str, correct_intent: str) -> str:
        text = _compact(user_text, 300) or "mensaje corregido por el usuario"
        expected = correct_intent or "intent corregido"
        return f"Agregar test basado en correccion: '{text}' -> {expected}."

    def _warn(self, message: str):
        self.last_warning = message
        try:
            self.logger.warning(message)
        except Exception:
            pass


__all__ = ["LearningQueue", "VALID_CANDIDATE_STATUSES"]

