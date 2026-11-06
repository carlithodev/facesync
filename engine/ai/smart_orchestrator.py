"""
Hybrid OpenAI semantic orchestrator for FaceSync AI.

This layer is intentionally narrow: OpenAI only interprets natural language
into the FaceSync JSON contract. Local Python still validates and executes
safe tools.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ai.openai_orchestrator import (
    ALLOWED_OPENAI_INTENTS,
    DEFAULT_ARGS,
    ENV_PATH,
    OPENAI_ORCHESTRATOR_PROMPT,
    OpenAIOrchestrator,
    load_dotenv,
)
from core.app_paths import ensure_app_data_root
from core.decision_schema import FaceSyncDecision
from core.dialogue_manager import DialogueManager
from core.text_normalizer import TextNormalizer


try:  # instructor is optional.
    import instructor as _INSTRUCTOR_MODULE

    _INSTRUCTOR_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - depends on optional dependency.
    _INSTRUCTOR_MODULE = None
    _INSTRUCTOR_IMPORT_ERROR = exc


SMART_ORCHESTRATOR_PROMPT = """
Eres el orquestador semantico de FaceSync.
Tu trabajo NO es ejecutar.
Tu trabajo es convertir lenguaje natural del usuario en JSON seguro.

Debes interpretar mensajes mal escritos, incompletos o naturales.

Debes usar el contexto:
- project_root_name
- active_path_name
- available_files
- available_folders
- available_columns
- pending_action
- last_created_items
- last_moved_items
- last_table_path
- last_source_folder
- last_destination_folder
- last_name_column
- last_reference_column
- last_question

Debes resolver referencias como:
- eso
- esa
- esas
- ahi
- lo anterior
- la carpeta que hice
- la lista que abri
- el Excel anterior
- las fotos de ahorita
- donde iban
- como la otra vez

Pero solo si el contexto es claro.
Si no es claro, pregunta.

No inventes rutas.
No inventes columnas.
No inventes archivos.
No inventes carpetas fuente.
Si puedes usar carpetas destino nuevas si el usuario claramente las nombra.

Para Excel/CSV adaptable:
- Nunca asumas que las columnas se llaman Nombre y Foto.
- Usa solo los nombres de available_columns.
- Si el usuario dice "la primera", "columna 1", "la de alumno",
  "foto base", "referencia", "codigo" o frases similares, mapea a la
  columna real del contexto cuando haya coincidencia clara.
- Si hay ambiguedad, devuelve needs_clarification=true y pregunta por la
  columna concreta.
- Nunca pidas el Excel completo ni inventes columnas.

Para FaceSync reference_face_matching se requieren:
- table_path
- name_column
- reference_column
- source_folder
- destination_folder

La columna de referencia NO significa copiar solo esa foto. Se usa como rostro
base o codigo de referencia para buscar coincidencias en source_folder.

Devuelve solo JSON valido con este formato exacto:
{
  "intent": "",
  "confidence": 0.0,
  "needs_clarification": false,
  "question": "",
  "args": {
    "table_path": "",
    "excel_name": "",
    "name_column": "",
    "column_name": "",
    "reference_column": "",
    "source_folder": "",
    "destination_folder": "",
    "folder_name": "",
    "file_name": "",
    "target": "",
    "new_name": "",
    "quantity": null,
    "base_name": "",
    "content": ""
  },
  "reason": "",
  "safe_to_execute": false,
  "model_used": "",
  "escalation_reason": ""
}
""".strip()


STRUCTURED_ORCHESTRATOR_PROMPT = """
Eres el orquestador estructurado de FaceSync AI.
No ejecutas nada.
Solo devuelves FaceSyncDecision.
Usa SystemState.
No inventes archivos, rutas ni columnas.
Si falta informacion, requires_clarification=true.
Si la accion es destructiva, requires_confirmation=true y safe_to_execute=false.
Si el usuario dice "primera columna", usa available_columns[0] si existe.
Si el usuario dice "segunda columna", usa available_columns[1] si existe.
Si el usuario dice "ahora identifica", usa context_summary.
No devuelvas texto libre.
Python valida, planea, protege y ejecuta despues; tu salida no ejecuta tools.
No pidas ni uses fotos, Excel completo, CSV completo, API keys ni secretos.
""".strip()


class SmartOrchestrator(OpenAIOrchestrator):
    CONTEXT_REFERENCE_PHRASES = (
        "eso",
        "esa",
        "esas",
        "ahi",
        "alli",
        "lo de antes",
        "lo anterior",
        "la carpeta que hice",
        "la carpeta anterior",
        "la lista que abri",
        "el excel anterior",
        "las fotos de ahorita",
        "donde iba",
        "donde iban",
        "como la otra vez",
        "mejor",
        "no mejor",
        "cambialo",
        "hazlo con esa",
    )
    PHOTO_FOLDER_HINTS = ("foto", "fotos", "imagen", "imagenes", "original", "originales", "maestra")
    DESTINATION_HINTS = ("resultado", "destino", "final", "entrega", "clasificado", "clasificados")
    TABLE_EXTENSIONS = {".xlsx", ".xls", ".csv"}
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    VERB_TOKENS = {
        "acomoda",
        "organiza",
        "clasifica",
        "mueve",
        "crea",
        "crear",
        "lee",
        "usa",
        "toma",
        "mete",
        "guarda",
        "borra",
        "renombra",
        "cancela",
    }
    INTENT_ALIASES = {
        "run_facesync": "classify_photos_by_reference",
        "create_multiple_files": "create_file",
        "analyze_or_explain": "unknown",
    }

    def __init__(
        self,
        api_key: str = "",
        model_fast: str = "",
        model_smart: str = "",
        response_provider: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ):
        load_dotenv(ENV_PATH)
        configured_fast = model_fast or os.getenv("OPENAI_MODEL_FAST") or os.getenv("OPENAI_MODEL") or "gpt-5.4-mini"
        super().__init__(api_key=api_key or os.getenv("OPENAI_API_KEY", ""), model=configured_fast)

        self.model_fast = configured_fast.strip()
        self.smart_fallback = self._env_bool("OPENAI_SMART_FALLBACK", default=True)
        configured_smart = model_smart or os.getenv("OPENAI_MODEL_SMART") or ("gpt-5.5" if self.smart_fallback else self.model_fast)
        self.model_smart = configured_smart.strip()
        self.fast_min_confidence = self._env_float("OPENAI_FAST_MIN_CONFIDENCE", 0.78)
        self.smart_min_confidence = self._env_float("OPENAI_SMART_MIN_CONFIDENCE", 0.70)
        self.escalate_on_ambiguous = self._env_bool("OPENAI_ESCALATE_ON_AMBIGUOUS", default=True)
        self.escalate_on_context_refs = self._env_bool("OPENAI_ESCALATE_ON_CONTEXT_REFERENCES", default=True)
        self.escalate_on_mini_clarification = self._env_bool("OPENAI_ESCALATE_ON_MINI_CLARIFICATION", default=True)
        self.max_input_chars = self._env_int("OPENAI_MAX_INPUT_CHARS", 12000)
        self.max_context_files = self._env_int("OPENAI_MAX_CONTEXT_FILES", 80)
        self.max_context_folders = self._env_int("OPENAI_MAX_CONTEXT_FOLDERS", 120)
        self.monthly_soft_limit_usd = self._env_float("OPENAI_MONTHLY_SOFT_LIMIT_USD", 5.0)
        self.log_usage_enabled = self._env_bool("OPENAI_LOG_USAGE", default=True)
        self.response_provider = response_provider
        self.last_usage: Dict[str, Any] = {}
        self.use_instructor = self._env_bool("USE_INSTRUCTOR", default=False)
        self.instructor_max_retries = self._env_int("INSTRUCTOR_MAX_RETRIES", 2)
        self.instructor_strict_mode = self._env_bool("INSTRUCTOR_STRICT_MODE", default=True)
        self._instructor_client = None
        self._instructor_warning_logged = False
        self.logger = logging.getLogger(__name__)

    @classmethod
    def from_env(cls) -> "SmartOrchestrator":
        load_dotenv(ENV_PATH)
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model_fast=os.getenv("OPENAI_MODEL_FAST") or os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
            model_smart=os.getenv("OPENAI_MODEL_SMART", ""),
        )

    def interpret(
        self,
        user_text: str,
        context: dict,
        local_guess: dict | None = None,
    ) -> dict:
        text = str(user_text or "").strip()
        context_dict = self._context_dict(context)
        local_result = self._local_bypass(text, context_dict, local_guess)
        if local_result:
            return local_result

        if not self.is_available():
            return self._unknown("SmartOrchestrator deshabilitado o sin API key.")

        current_spend = self._current_monthly_usage(context_dict)
        if self.monthly_soft_limit_usd > 0 and current_spend >= self.monthly_soft_limit_usd:
            result = self._unknown("OpenAI monthly soft limit reached.")
            result["question"] = "Alcance el limite mensual configurado para OpenAI. Puedes resolverlo localmente o subir el limite."
            return result

        try:
            client = self._get_client()
        except Exception as exc:
            return self._unknown(str(exc))

        compact_context = self._compact_context(context_dict)
        payload = self._build_payload(text, compact_context, local_guess, stage="fast")

        print(f"[SMART_ORCH] called model={self.model_fast}")
        try:
            if self.use_instructor and self._instructor_is_available():
                decision = self._call_openai_with_instructor(
                    self.model_fast,
                    self._build_instructor_messages(payload),
                    compact_context,
                )
                fast_usage = {}
                fast_result = self._parse_instructor_decision(
                    decision,
                    model=self.model_fast,
                    context=compact_context,
                    user_text=text,
                    escalation_reason="",
                )
            else:
                fast_raw = self._call_model(client, self.model_fast, payload)
                fast_usage = fast_raw.get("usage") or {}
                fast_result = self._parse_model_response(
                    fast_raw.get("text") or "",
                    model=self.model_fast,
                    context=compact_context,
                    user_text=text,
                    escalation_reason="",
                )
            self._log_usage(context_dict, self.model_fast, fast_usage, fast_result, escalated=False, escalation_reason="")
        except Exception as exc:
            print(f"[SMART_ORCH] fast_error={type(exc).__name__}: {exc}")
            if self.use_instructor and str(type(exc).__name__).lower().find("validation") >= 0:
                fast_result = self._unknown(f"instructor_validation_error:{exc}")
            elif self.use_instructor and self.response_provider:
                fast_result = self._unknown(f"instructor_error:{exc}")
            else:
                fast_result = self._unknown(f"fast_model_error:{exc}")
            fast_result["model_used"] = self.model_fast

        escalation_reason = self._should_escalate(text, compact_context, local_guess, fast_result)
        if escalation_reason and self.smart_fallback and self.model_smart:
            if self.monthly_soft_limit_usd > 0 and self._current_monthly_usage(context_dict) >= self.monthly_soft_limit_usd:
                fast_result["escalation_reason"] = "soft_limit_prevented_smart"
                return fast_result

            smart_payload = self._build_payload(
                text,
                compact_context,
                local_guess,
                stage="smart",
                fast_result=fast_result,
                escalation_reason=escalation_reason,
            )
            print(f"[SMART_ORCH] escalated model={self.model_smart} reason={escalation_reason}")
            try:
                if self.use_instructor and self._instructor_is_available():
                    decision = self._call_openai_with_instructor(
                        self.model_smart,
                        self._build_instructor_messages(smart_payload),
                        compact_context,
                    )
                    smart_usage = {}
                    smart_result = self._parse_instructor_decision(
                        decision,
                        model=self.model_smart,
                        context=compact_context,
                        user_text=text,
                        escalation_reason=escalation_reason,
                    )
                else:
                    smart_raw = self._call_model(client, self.model_smart, smart_payload)
                    smart_usage = smart_raw.get("usage") or {}
                    smart_result = self._parse_model_response(
                        smart_raw.get("text") or "",
                        model=self.model_smart,
                        context=compact_context,
                        user_text=text,
                        escalation_reason=escalation_reason,
                    )
                self._log_usage(
                    context_dict,
                    self.model_smart,
                    smart_usage,
                    smart_result,
                    escalated=True,
                    escalation_reason=escalation_reason,
                )
                return smart_result
            except Exception as exc:
                print(f"[SMART_ORCH] smart_error={type(exc).__name__}: {exc}")
                fast_result["escalation_reason"] = f"{escalation_reason};smart_error"
                fast_result["needs_clarification"] = True
                fast_result["safe_to_execute"] = False
                fast_result["question"] = fast_result.get("question") or "No pude interpretar eso con suficiente seguridad. Puedes decirme el Excel, la carpeta de fotos y el destino?"
                return fast_result

        return fast_result

    def retry_with_smart(
        self,
        user_text: str,
        context: dict,
        *,
        local_guess: dict | None = None,
        previous_result: dict | None = None,
        escalation_reason: str = "action_fallback_incoherent_plan",
    ) -> dict:
        text = str(user_text or "").strip()
        context_dict = self._context_dict(context)
        if not self.smart_fallback or not self.model_smart or not self.is_available():
            result = previous_result or self._unknown("smart_retry_unavailable")
            result["fallback_retry_count"] = 1
            result["needs_clarification"] = True
            result["safe_to_execute"] = False
            result["question"] = result.get("question") or "No pude reparar ese plan con suficiente seguridad. Puedes confirmarme los datos?"
            return result

        if self.monthly_soft_limit_usd > 0 and self._current_monthly_usage(context_dict) >= self.monthly_soft_limit_usd:
            result = previous_result or self._unknown("soft_limit_prevented_smart_retry")
            result["fallback_retry_count"] = 1
            result["needs_clarification"] = True
            result["safe_to_execute"] = False
            result["question"] = result.get("question") or "Alcance el limite mensual configurado para OpenAI."
            return result

        try:
            client = self._get_client()
            compact_context = self._compact_context(context_dict)
            payload = self._build_payload(
                text,
                compact_context,
                local_guess,
                stage="smart",
                fast_result=previous_result,
                escalation_reason=escalation_reason,
            )
            print(f"[SMART_ORCH] fallback_retry model={self.model_smart} reason={escalation_reason}")
            if self.use_instructor and self._instructor_is_available():
                decision = self._call_openai_with_instructor(
                    self.model_smart,
                    self._build_instructor_messages(payload),
                    compact_context,
                )
                smart_usage = {}
                smart_result = self._parse_instructor_decision(
                    decision,
                    model=self.model_smart,
                    context=compact_context,
                    user_text=text,
                    escalation_reason=escalation_reason,
                )
            else:
                smart_raw = self._call_model(client, self.model_smart, payload)
                smart_usage = smart_raw.get("usage") or {}
                smart_result = self._parse_model_response(
                    smart_raw.get("text") or "",
                    model=self.model_smart,
                    context=compact_context,
                    user_text=text,
                    escalation_reason=escalation_reason,
                )
            smart_result["fallback_retry_count"] = 1
            self._log_usage(
                context_dict,
                self.model_smart,
                smart_usage,
                smart_result,
                escalated=True,
                escalation_reason=escalation_reason,
            )
            return smart_result
        except Exception as exc:
            print(f"[SMART_ORCH] fallback_retry_error={type(exc).__name__}: {exc}")
            result = previous_result or self._unknown(f"smart_retry_error:{exc}")
            result["fallback_retry_count"] = 1
            result["needs_clarification"] = True
            result["safe_to_execute"] = False
            result["question"] = result.get("question") or "No pude reparar ese plan con suficiente seguridad. Puedes confirmarme los datos?"
            return result

    def _build_payload(
        self,
        user_text: str,
        compact_context: Dict[str, Any],
        local_guess: Optional[Dict[str, Any]],
        *,
        stage: str,
        fast_result: Optional[Dict[str, Any]] = None,
        escalation_reason: str = "",
    ) -> Dict[str, Any]:
        payload = {
            "mensaje_usuario": user_text[: self.max_input_chars],
            "contexto_resumido": compact_context,
            "local_guess": self._compact_local_guess(local_guess),
            "intents_permitidos": sorted(ALLOWED_OPENAI_INTENTS),
            "stage": stage,
            "formato_json_obligatorio": {
                "intent": "classify_photos_by_reference",
                "confidence": 0.92,
                "needs_clarification": False,
                "question": "",
                "args": {key: DEFAULT_ARGS.get(key) for key in DEFAULT_ARGS},
                "reason": "",
                "safe_to_execute": True,
                "model_used": self.model_fast if stage == "fast" else self.model_smart,
                "escalation_reason": escalation_reason,
            },
            "reglas": {
                "openai_no_ejecuta": True,
                "python_valida_y_ejecuta": True,
                "no_enviar_excel_completo": True,
                "no_enviar_fotos": True,
                "delete_requiere_confirmacion": True,
            },
        }
        if fast_result:
            payload["fast_result"] = self._compact_model_result(fast_result)
            payload["escalation_reason"] = escalation_reason
        return payload

    def _call_model(self, client: Any, model: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.response_provider:
            provided = self.response_provider(model, payload)
            if isinstance(provided, dict) and ("text" in provided or "usage" in provided):
                return {
                    "text": provided.get("text") or json.dumps(provided.get("json") or {}, ensure_ascii=False),
                    "usage": provided.get("usage") or {},
                }
            return {"text": json.dumps(provided or {}, ensure_ascii=False), "usage": {}}

        system_prompt = SMART_ORCHESTRATOR_PROMPT if model == self.model_smart else OPENAI_ORCHESTRATOR_PROMPT
        return self._call_openai(client, payload, model=model, system_prompt=system_prompt)

    def _build_instructor_messages(self, payload: Dict[str, Any]) -> list[dict[str, str]]:
        safe_payload = {
            "mensaje_usuario": payload.get("mensaje_usuario", ""),
            "system_state": payload.get("contexto_resumido") or {},
            "local_guess": payload.get("local_guess") or {},
            "intents_permitidos": payload.get("intents_permitidos") or [],
            "stage": payload.get("stage") or "",
            "fast_result": payload.get("fast_result") or {},
            "escalation_reason": payload.get("escalation_reason") or "",
            "reglas": payload.get("reglas") or {},
        }
        return [
            {"role": "system", "content": STRUCTURED_ORCHESTRATOR_PROMPT},
            {"role": "user", "content": json.dumps(safe_payload, ensure_ascii=False)},
        ]

    def _call_openai_with_instructor(
        self,
        model: str,
        messages: list[dict[str, str]],
        system_state: Dict[str, Any],
    ) -> FaceSyncDecision:
        module = self._instructor_module()
        if module is None:
            raise RuntimeError("instructor no instalado")

        if self.response_provider:
            payload = {
                "messages": messages,
                "system_state": system_state,
                "response_model": "FaceSyncDecision",
                "use_instructor": True,
                "strict": self.instructor_strict_mode,
            }
            provided = self.response_provider(model, payload)
            return self._validate_instructor_decision(provided, model=model, escalation_reason="")

        client = self._get_client()
        if client == "raw_http":
            raise RuntimeError("instructor requiere OpenAI SDK disponible")
        patched_client = self._get_instructor_client(client, module)
        response = patched_client.chat.completions.create(
            model=model,
            messages=messages,
            response_model=FaceSyncDecision,
            max_retries=max(0, int(self.instructor_max_retries)),
        )
        return self._validate_instructor_decision(response, model=model, escalation_reason="")

    def _parse_instructor_decision(
        self,
        decision: FaceSyncDecision,
        *,
        model: str,
        context: Dict[str, Any],
        user_text: str,
        escalation_reason: str,
    ) -> Dict[str, Any]:
        shaped = self._decision_to_legacy_dict(decision, model=model, escalation_reason=escalation_reason)
        shaped = self._normalize_paths_from_context(shaped, context)
        shaped = self._coerce_allowed_intent(shaped)
        shaped = self._postprocess_columns(shaped, context, user_text)
        if model == self.model_smart and shaped.get("confidence", 0) < self.smart_min_confidence:
            shaped["needs_clarification"] = True
            shaped["safe_to_execute"] = False
            shaped["question"] = shaped.get("question") or "Necesito un dato mas para hacerlo con seguridad."
        return shaped

    def _validate_instructor_decision(self, value: Any, *, model: str, escalation_reason: str) -> FaceSyncDecision:
        if isinstance(value, FaceSyncDecision):
            decision = value
        elif hasattr(value, "model_dump"):
            decision = FaceSyncDecision.model_validate(value.model_dump())
        elif isinstance(value, dict) and "json" in value:
            decision = FaceSyncDecision.model_validate(value.get("json") or {})
        else:
            decision = FaceSyncDecision.model_validate(value)

        data = decision.model_dump()
        data["model_used"] = data.get("model_used") or model
        if escalation_reason and not data.get("escalation_reason"):
            data["escalation_reason"] = escalation_reason
        if data.get("confidence") in (None, ""):
            data["confidence"] = 0.0
        if not data.get("reason_summary"):
            data["reason_summary"] = "Decision estructurada validada por FaceSyncDecision."
        return FaceSyncDecision.model_validate(data)

    def _decision_to_legacy_dict(self, decision: FaceSyncDecision, *, model: str, escalation_reason: str) -> Dict[str, Any]:
        dumped = decision.model_dump()
        args_data = dumped.get("args") or {}
        args = dict(DEFAULT_ARGS)
        for key, value in args_data.items():
            if key in args and value is not None:
                args[key] = value
        if args.get("table_path") and not args.get("excel_path"):
            args["excel_path"] = args["table_path"]
        if args.get("table_path") and not args.get("excel_name"):
            args["excel_name"] = args["table_path"]

        clarification = dumped.get("clarification") or {}
        needs_clarification = bool(dumped.get("requires_clarification") or clarification.get("required"))
        question = str(clarification.get("question") or "")
        intent = dumped.get("intent") or "unknown"
        return {
            "intent": intent.value if hasattr(intent, "value") else str(intent),
            "confidence": float(dumped.get("confidence") or 0.0),
            "needs_clarification": needs_clarification,
            "requires_clarification": needs_clarification,
            "question": question,
            "clarification": clarification,
            "args": args,
            "reason": dumped.get("reason_summary") or "",
            "reason_summary": dumped.get("reason_summary") or "",
            "risk_flags": dumped.get("risk_flags") or [],
            "safe_to_execute": bool(dumped.get("safe_to_execute")) and not needs_clarification,
            "requires_confirmation": bool(dumped.get("requires_confirmation")),
            "model_used": dumped.get("model_used") or model,
            "escalation_reason": dumped.get("escalation_reason") or escalation_reason,
            "retry_count": dumped.get("retry_count") or 0,
            "used_instructor": True,
            "used_openai": True,
        }

    def _instructor_is_available(self) -> bool:
        if self._instructor_module() is not None:
            return True
        if not self._instructor_warning_logged:
            warning = f"instructor no instalado; usando fallback manual actual. {_INSTRUCTOR_IMPORT_ERROR or ''}".strip()
            print(f"[SMART_ORCH] {warning}")
            try:
                self.logger.warning(warning)
            except Exception:
                pass
            self._instructor_warning_logged = True
        return False

    @staticmethod
    def _instructor_module():
        return _INSTRUCTOR_MODULE

    def _get_instructor_client(self, client: Any, module: Any):
        if self._instructor_client is not None:
            return self._instructor_client
        if hasattr(module, "from_openai"):
            self._instructor_client = module.from_openai(client)
        elif hasattr(module, "patch"):
            self._instructor_client = module.patch(client)
        else:
            raise RuntimeError("instructor instalado pero sin from_openai/patch compatible")
        return self._instructor_client

    def _parse_model_response(
        self,
        text: str,
        *,
        model: str,
        context: Dict[str, Any],
        user_text: str,
        escalation_reason: str,
    ) -> Dict[str, Any]:
        parsed = self._parse_json(text)
        shaped = self._with_default_shape(parsed)
        shaped = self._normalize_paths_from_context(shaped, context)
        shaped = self._coerce_allowed_intent(shaped)
        shaped = self._postprocess_columns(shaped, context, user_text)
        shaped["model_used"] = model
        shaped["escalation_reason"] = escalation_reason
        if model == self.model_smart and shaped.get("confidence", 0) < self.smart_min_confidence:
            shaped["needs_clarification"] = True
            shaped["safe_to_execute"] = False
            shaped["question"] = shaped.get("question") or "Necesito un dato mas para hacerlo con seguridad."
        return shaped

    def _local_bypass(
        self,
        text: str,
        context: Dict[str, Any],
        local_guess: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        normalized = TextNormalizer.normalize(text)
        norm = normalized.normalized
        pending = context.get("pending_action")

        if not text:
            return self._local_result("unknown", 0.0, True, "Necesito que me indiques que quieres hacer.")

        if self._matches(norm, DialogueManager.GREETING_PHRASES):
            return self._local_result("greeting", 0.99, False, "", reason="saludo local")
        if self._matches(norm, DialogueManager.THANKS_PHRASES):
            return self._local_result("thanks", 0.99, False, "", reason="agradecimiento local")
        if self._matches(norm, DialogueManager.FAREWELL_PHRASES):
            return self._local_result("farewell", 0.99, False, "", reason="despedida local")
        if norm in {"si", "no"} and not pending:
            return self._local_result("unknown", 0.99, True, "No hay una accion pendiente que confirmar.")

        pending_result = self._complete_pending_column_answer(text, pending)
        if pending_result:
            return pending_result

        tokens = [token for token in normalized.tokens if token]
        if len(tokens) <= 3 and not (set(tokens) & self.VERB_TOKENS) and not pending:
            return self._local_result(
                "unknown",
                0.99,
                True,
                f"Necesito mas contexto. Que deseas hacer con '{text}'?",
                reason="texto corto ambiguo local",
            )

        if local_guess:
            confidence = float(local_guess.get("confidence") or 0.0)
            intent = self.INTENT_ALIASES.get(str(local_guess.get("intent") or ""), local_guess.get("intent") or "unknown")
            if confidence >= 0.85 and intent in ALLOWED_OPENAI_INTENTS:
                return self._local_result(
                    intent,
                    confidence,
                    bool(local_guess.get("needs_clarification")),
                    str(local_guess.get("question") or ""),
                    args=local_guess.get("args") or {},
                    reason=local_guess.get("reason") or "local confidence high",
                    safe_to_execute=not bool(local_guess.get("needs_clarification")),
                )
        return None

    def _complete_pending_column_answer(self, text: str, pending: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(pending, dict):
            return None
        missing_slot = pending.get("missing_slot") or ""
        if missing_slot not in {"name_column", "column_name", "reference_column"}:
            return None
        columns = pending.get("available_columns") or (pending.get("args") or {}).get("available_columns") or []
        matched = DialogueManager._match_available_column(text, [str(col) for col in columns])
        if not matched:
            return None
        args = dict(pending.get("args") or {})
        if missing_slot in {"name_column", "column_name"}:
            args["name_column"] = matched
            args["column_name"] = matched
        else:
            args["reference_column"] = matched
        return self._local_result(
            self.INTENT_ALIASES.get(str(pending.get("intent") or ""), pending.get("intent") or "unknown"),
            0.99,
            False,
            "",
            args=args,
            reason="respuesta local a columna pendiente",
            safe_to_execute=True,
        )

    def _should_escalate(
        self,
        text: str,
        context: Dict[str, Any],
        local_guess: Optional[Dict[str, Any]],
        fast_result: Dict[str, Any],
    ) -> str:
        confidence = float(fast_result.get("confidence") or 0.0)
        if confidence < self.fast_min_confidence:
            return "fast_low_confidence"

        if self.escalate_on_ambiguous and fast_result.get("intent") in {"unknown", "ask_missing_data"}:
            return "ambiguous_fast_result"

        if self.escalate_on_context_refs and self._has_context_references(text):
            return "context_reference"

        if self._has_bad_writing(text):
            return "strong_typo_noise"

        if self._has_chained_actions(text):
            return "chained_actions"

        if self._has_intent_conflict(text, local_guess, fast_result):
            return "intent_conflict"

        suspicious = self._suspicious_slots(text, context, fast_result)
        if suspicious:
            return suspicious

        if (
            self.escalate_on_mini_clarification
            and fast_result.get("needs_clarification")
            and self._context_has_sufficient_data(context, fast_result)
        ):
            return "mini_clarification_with_sufficient_context"

        if self._last_interpretation_failed(context):
            return "previous_interpretation_error"

        return ""

    def _suspicious_slots(self, text: str, context: Dict[str, Any], result: Dict[str, Any]) -> str:
        args = result.get("args") or {}
        destination = self._norm(args.get("destination_folder"))
        table_path = self._norm(args.get("table_path") or args.get("excel_path") or args.get("excel_name"))
        source_folder = args.get("source_folder") or ""
        reference_column = args.get("reference_column") or ""
        norm_text = self._norm(text)

        if destination and any(phrase in destination for phrase in ("columna", "usando", "como referencia")):
            return "suspicious_destination_slot"
        if table_path and any(verb in table_path.split() for verb in self.VERB_TOKENS):
            return "suspicious_table_slot"
        if not reference_column and re.search(r"\bcolumna\s+\S+", norm_text):
            return "missing_reference_column"
        if not source_folder and self._probable_photo_folder(context):
            return "missing_source_folder_with_context"
        return ""

    def _context_has_sufficient_data(self, context: Dict[str, Any], result: Dict[str, Any]) -> bool:
        args = result.get("args") or {}
        has_table = bool(
            args.get("table_path")
            or args.get("excel_path")
            or context.get("last_table_path")
            or self._probable_table_file(context)
        )
        has_source = bool(args.get("source_folder") or context.get("last_source_folder") or self._probable_photo_folder(context))
        has_destination = bool(
            args.get("destination_folder")
            or context.get("last_destination_folder")
            or self._probable_destination_folder(context)
        )
        pending = context.get("pending_action")
        return bool((has_table and has_source and has_destination) or pending)

    def _postprocess_columns(self, result: Dict[str, Any], context: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        if not isinstance(result.get("args"), dict):
            return result
        args = dict(result["args"])
        summary = context.get("context_summary") if isinstance(context.get("context_summary"), dict) else {}
        columns = [
            str(col)
            for col in (
                context.get("available_columns")
                or context.get("last_table_columns")
                or summary.get("last_table_columns")
                or []
            )
            if col
        ]
        if not columns:
            result["args"] = args
            return result

        name_value = args.get("name_column") or args.get("column_name") or ""
        reference_value = args.get("reference_column") or ""
        name_match = self._resolve_column_alias(name_value, columns)
        reference_match = self._resolve_column_alias(reference_value, columns)

        inferred_name, inferred_reference = self._infer_columns_from_text(user_text, columns)
        name_match = name_match or inferred_name
        reference_match = reference_match or inferred_reference

        if name_match:
            args["name_column"] = name_match
            args["column_name"] = name_match
        if reference_match:
            args["reference_column"] = reference_match
        result["args"] = args
        return result

    def _infer_columns_from_text(self, text: str, columns: list[str]) -> tuple[str, str]:
        norm_text = self._norm(text)
        name_match = ""
        reference_match = ""
        if columns and any(phrase in norm_text for phrase in ("primera columna", "primer columna", "columna 1", "1era columna", "1a columna")):
            name_match = columns[0]
        if len(columns) > 1 and any(phrase in norm_text for phrase in ("segunda columna", "columna 2", "2da columna", "2a columna")):
            reference_match = columns[1]
        for column in columns:
            norm_col = self._norm(column)
            tokens = set(norm_col.split())
            if not tokens:
                continue
            if norm_col in norm_text or any(token in norm_text.split() for token in tokens):
                if not name_match and tokens & {"nombre", "alumno", "estudiante", "persona", "cliente", "participante"}:
                    name_match = column
                if not reference_match and tokens & {"foto", "referencia", "imagen", "archivo", "codigo", "numero", "base"}:
                    reference_match = column
        return name_match, reference_match

    def _resolve_column_alias(self, value: Any, columns: list[str]) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        raw_norm = self._norm(raw)
        if any(phrase in raw_norm for phrase in ("primera columna", "primer columna", "columna 1", "1era columna", "1a columna")):
            return columns[0] if columns else ""
        if any(phrase in raw_norm for phrase in ("segunda columna", "columna 2", "2da columna", "2a columna")):
            return columns[1] if len(columns) > 1 else ""
        direct = DialogueManager._match_available_column(raw, columns)
        if direct:
            return direct
        raw_tokens = set(raw_norm.split())
        scored: list[tuple[int, str]] = []
        for column in columns:
            col_norm = self._norm(column)
            col_tokens = set(col_norm.split())
            score = 0
            if raw_norm == col_norm:
                score += 100
            elif raw_norm and raw_norm in col_norm:
                score += 80
            overlap = raw_tokens & col_tokens
            score += len(overlap) * 25
            if raw_tokens and raw_tokens.issubset(col_tokens):
                score += 30
            if score:
                scored.append((score, column))
        if not scored:
            return ""
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return ""
        return scored[0][1]

    def _log_usage(
        self,
        context: Dict[str, Any],
        model: str,
        usage: Dict[str, Any],
        result: Dict[str, Any],
        *,
        escalated: bool,
        escalation_reason: str,
    ):
        tokens_input = int(usage.get("tokens_input") or usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        tokens_output = int(usage.get("tokens_output") or usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        estimated_cost = self._estimate_cost(model, tokens_input, tokens_output)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "input_tokens": tokens_input,
            "output_tokens": tokens_output,
            "estimated_cost_usd": estimated_cost,
            "intent": result.get("intent", ""),
            "confidence": result.get("confidence", 0),
            "escalated": bool(escalated),
            "escalation_reason": escalation_reason,
        }
        self.last_usage = record
        result["usage"] = record
        if not self.log_usage_enabled:
            return
        try:
            log_path = self._usage_log_path(context)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            print(f"[SMART_ORCH] usage log error={exc}")

    def _current_monthly_usage(self, context: Dict[str, Any]) -> float:
        if not self.log_usage_enabled:
            return 0.0
        try:
            log_path = self._usage_log_path(context)
            if not log_path.exists():
                return 0.0
            prefix = datetime.now(timezone.utc).strftime("%Y-%m")
            total = 0.0
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if str(record.get("timestamp", "")).startswith(prefix):
                        total += float(record.get("estimated_cost_usd") or 0.0)
            return total
        except Exception:
            return 0.0

    def _usage_log_path(self, context: Dict[str, Any]) -> Path:
        app_data = context.get("app_data_root")
        root = ensure_app_data_root(app_data) if app_data else ensure_app_data_root()
        return root / "logs" / "openai_usage.jsonl"

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        if model == self.model_smart:
            input_rate = self._env_float("OPENAI_SMART_INPUT_COST_PER_1K", 0.005)
            output_rate = self._env_float("OPENAI_SMART_OUTPUT_COST_PER_1K", 0.015)
        else:
            input_rate = self._env_float("OPENAI_FAST_INPUT_COST_PER_1K", 0.00025)
            output_rate = self._env_float("OPENAI_FAST_OUTPUT_COST_PER_1K", 0.001)
        return round((input_tokens / 1000.0 * input_rate) + (output_tokens / 1000.0 * output_rate), 8)

    @classmethod
    def _compact_context(cls, context: Any) -> Dict[str, Any]:
        source = cls._context_dict(context)
        project_root = source.get("project_root") or source.get("workspace_actual") or source.get("workspace")
        active_path = source.get("active_path")
        compact: Dict[str, Any] = {}
        if project_root:
            compact["project_root_name"] = Path(str(project_root)).name or str(project_root)
        if active_path:
            compact["active_path_name"] = Path(str(active_path)).name or str(active_path)
        workspace_roots = source.get("workspace_roots") or []
        if isinstance(workspace_roots, list):
            compact["workspace_root_names"] = [
                Path(str(item)).name or str(item)
                for item in workspace_roots[:12]
                if item
            ]

        max_files = cls._env_int_static("OPENAI_MAX_CONTEXT_FILES", 80)
        max_folders = cls._env_int_static("OPENAI_MAX_CONTEXT_FOLDERS", 120)
        available_files = cls._filter_context_files(source.get("available_files") or [])[:max_files]
        available_folders = [str(item) for item in (source.get("available_folders") or []) if item][:max_folders]
        compact["available_files"] = available_files
        compact["available_folders"] = available_folders
        compact["available_columns"] = [str(item) for item in (source.get("available_columns") or []) if item]
        compact["table_row_count"] = source.get("table_row_count") or source.get("last_table_rows") or 0

        aliases = {
            "pending_action": source.get("pending_action"),
            "context_summary": source.get("context_summary"),
            "last_created_items": source.get("last_created_items") or source.get("ultima_carpeta_creada") or source.get("ultimo_archivo_creado"),
            "last_moved_items": source.get("last_moved_items"),
            "last_table_path": source.get("last_table_path") or source.get("ultimo_excel_leido") or source.get("last_excel"),
            "last_table_columns": source.get("last_table_columns"),
            "last_source_folder": source.get("last_source_folder") or source.get("ultima_carpeta_fotos"),
            "last_destination_folder": source.get("last_destination_folder") or source.get("ultima_carpeta_destino"),
            "last_name_column": source.get("last_name_column") or source.get("ultima_columna_detectada"),
            "last_reference_column": source.get("last_reference_column") or source.get("ultima_columna_referencia"),
            "last_facesync_run": source.get("last_facesync_run"),
            "recent_user_messages": source.get("recent_user_messages"),
            "recent_assistant_messages": source.get("recent_assistant_messages"),
            "recent_intents": source.get("recent_intents"),
            "recent_errors": source.get("recent_errors"),
            "learning_hints": source.get("learning_hints"),
            "last_question": source.get("last_question"),
            "last_interpretation_error": source.get("last_interpretation_error"),
        }
        for key, value in aliases.items():
            if isinstance(value, dict):
                compact[key] = {k: value.get(k) for k in list(value.keys())[:12]}
            elif isinstance(value, list):
                compact[key] = value[:10]
            elif value:
                compact[key] = value

        history = source.get("historial_acciones_recientes")
        if isinstance(history, list) and history:
            compact["recent_actions"] = history[-5:]
        return compact

    @staticmethod
    def _filter_context_files(files: Any) -> list[str]:
        result = []
        for item in files if isinstance(files, list) else []:
            text = str(item)
            suffix = Path(text).suffix.lower()
            if suffix in SmartOrchestrator.IMAGE_EXTENSIONS:
                continue
            result.append(text)
        return result

    @staticmethod
    def _compact_model_result(result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "intent": result.get("intent"),
            "confidence": result.get("confidence"),
            "needs_clarification": result.get("needs_clarification"),
            "question": result.get("question"),
            "args": result.get("args"),
            "reason": result.get("reason"),
            "safe_to_execute": result.get("safe_to_execute"),
            "model_used": result.get("model_used"),
        }

    @classmethod
    def _coerce_allowed_intent(cls, result: Dict[str, Any]) -> Dict[str, Any]:
        intent = str(result.get("intent") or "unknown")
        intent = cls.INTENT_ALIASES.get(intent, intent)
        if intent not in ALLOWED_OPENAI_INTENTS:
            intent = "unknown"
            result["needs_clarification"] = True
            result["safe_to_execute"] = False
        result["intent"] = intent
        return result

    @staticmethod
    def _matches(norm_text: str, phrases: set[str]) -> bool:
        return norm_text in {TextNormalizer.normalize_for_matching(item) for item in phrases}

    @staticmethod
    def _local_result(
        intent: str,
        confidence: float,
        needs_clarification: bool,
        question: str,
        *,
        args: Optional[Dict[str, Any]] = None,
        reason: str = "",
        safe_to_execute: bool = False,
    ) -> Dict[str, Any]:
        shaped_args = dict(DEFAULT_ARGS)
        if args:
            shaped_args.update(args)
        return {
            "intent": intent if intent in ALLOWED_OPENAI_INTENTS else "unknown",
            "confidence": float(confidence),
            "needs_clarification": bool(needs_clarification),
            "question": question,
            "args": shaped_args,
            "reason": reason,
            "safe_to_execute": bool(safe_to_execute),
            "model_used": "local",
            "escalation_reason": "",
            "used_openai": False,
        }

    @classmethod
    def _context_dict(cls, context: Any) -> Dict[str, Any]:
        if not context:
            return {}
        if hasattr(context, "current_context"):
            return getattr(context, "current_context") or {}
        if isinstance(context, dict):
            return context
        return {}

    @classmethod
    def _probable_table_file(cls, context: Dict[str, Any]) -> str:
        for value in context.get("available_files") or []:
            if Path(str(value)).suffix.lower() in cls.TABLE_EXTENSIONS:
                return str(value)
        return ""

    @classmethod
    def _probable_photo_folder(cls, context: Dict[str, Any]) -> str:
        for value in context.get("available_folders") or []:
            norm = cls._norm(value)
            if any(hint in norm for hint in cls.PHOTO_FOLDER_HINTS):
                return str(value)
        return ""

    @classmethod
    def _probable_destination_folder(cls, context: Dict[str, Any]) -> str:
        for value in context.get("available_folders") or []:
            norm = cls._norm(value)
            if any(hint in norm for hint in cls.DESTINATION_HINTS):
                return str(value)
        return ""

    @classmethod
    def _has_context_references(cls, text: str) -> bool:
        norm = cls._norm(text)
        return any(phrase in norm for phrase in cls.CONTEXT_REFERENCE_PHRASES)

    @staticmethod
    def _has_bad_writing(text: str) -> bool:
        normalized = TextNormalizer.normalize(text)
        noisy_patterns = ("caerpt", "fots", "ban", "als ", "imaj", "exel", "ecxel")
        raw = TextNormalizer.strip_accents(text).lower()
        return len(normalized.corrections) >= 2 or any(pattern in raw for pattern in noisy_patterns)

    @classmethod
    def _has_chained_actions(cls, text: str) -> bool:
        norm = cls._norm(text)
        tokens = set(norm.split())
        action_hits = len(tokens & cls.VERB_TOKENS)
        return action_hits >= 2 and any(connector in norm for connector in (" y ", " luego ", " despues ", " en vez de "))

    @classmethod
    def _has_intent_conflict(
        cls,
        text: str,
        local_guess: Optional[Dict[str, Any]],
        result: Dict[str, Any],
    ) -> bool:
        norm = cls._norm(text)
        conflict_pairs = (
            ("mueve", "clasifica"),
            ("mover", "clasificar"),
            ("crear", "clasificar"),
            ("renombra", "crear"),
            ("borra", "mueve"),
        )
        if any(left in norm and right in norm for left, right in conflict_pairs):
            return True
        if local_guess and local_guess.get("intent") not in {None, "", "unknown", result.get("intent")}:
            local_confidence = float(local_guess.get("confidence") or 0.0)
            model_confidence = float(result.get("confidence") or 0.0)
            return local_confidence >= 0.55 and abs(local_confidence - model_confidence) <= 0.18
        return False

    @staticmethod
    def _last_interpretation_failed(context: Dict[str, Any]) -> bool:
        value = context.get("last_interpretation_error")
        if isinstance(value, dict):
            return str(value.get("type") or value.get("reason") or "").lower() in {"interpretation", "intent", "slot"}
        return bool(value)

    @staticmethod
    def _norm(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.lower()
        text = re.sub(r"[^a-z0-9./\\-]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _env_float(key: str, default: float) -> float:
        try:
            return float(os.getenv(key, str(default)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _env_int(key: str, default: int) -> int:
        try:
            return int(os.getenv(key, str(default)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _env_int_static(key: str, default: int) -> int:
        try:
            return int(os.getenv(key, str(default)))
        except (TypeError, ValueError):
            return default
