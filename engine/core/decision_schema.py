"""
Structured decision and planning schemas for FaceSync AI.

The module prefers real Pydantic v2 models. When Pydantic is not importable in
the active interpreter, a small compatible fallback keeps local manual tests and
offline execution from crashing while preserving the same public methods used by
the project: model_validate(), model_dump() and model_copy().
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, get_args, get_origin, get_type_hints
import copy
import sys
import types


try:  # pragma: no cover - exercised only when Pydantic is installed.
    from pydantic import BaseModel as _PydanticBaseModel
    from pydantic import ConfigDict, Field, ValidationError

    PYDANTIC_AVAILABLE = True
except Exception:  # pragma: no cover - the fallback is covered by manual tests.
    _PydanticBaseModel = object
    ConfigDict = dict
    ValidationError = ValueError
    PYDANTIC_AVAILABLE = False

    class _FallbackField:
        def __init__(self, default: Any = None, default_factory: Any = None):
            self.default = default
            self.default_factory = default_factory

        def build(self):
            if self.default_factory is not None:
                return self.default_factory()
            return copy.deepcopy(self.default)

    def Field(default: Any = None, *, default_factory: Any = None, **_: Any):
        return _FallbackField(default=default, default_factory=default_factory)


DANGEROUS_ARG_KEYS = {
    "cmd",
    "command",
    "eval",
    "exec",
    "execute_code",
    "python_code",
    "run_shell",
    "script",
    "shell",
    "subprocess",
}

ALLOWED_FALLBACK_STATUSES = {
    "ready",
    "repaired",
    "clarification_needed",
    "blocked",
    "retry_smart",
    "failed",
    "noop",
}


class AllowedIntent(str, Enum):
    GREETING = "greeting"
    THANKS = "thanks"
    FAREWELL = "farewell"
    CREATE_FOLDER = "create_folder"
    CREATE_MULTIPLE_FOLDERS = "create_multiple_folders"
    CREATE_FILE = "create_file"
    READ_DOCUMENT = "read_document"
    CREATE_FOLDERS_FROM_TABLE = "create_folders_from_table"
    CREATE_FOLDERS_FROM_EXCEL = "create_folders_from_excel"
    PREPARE_FACESYNC_PIPELINE = "prepare_facesync_pipeline"
    EXCEL_TO_FACESYNC_PIPELINE = "excel_to_facesync_pipeline"
    RUN_REFERENCE_FACE_MATCHING = "run_reference_face_matching"
    CLASSIFY_PHOTOS_BY_REFERENCE = "classify_photos_by_reference"
    MOVE_ITEM = "move_item"
    COPY_ITEM = "copy_item"
    RENAME_ITEM = "rename_item"
    DELETE_ITEM = "delete_item"
    SEARCH_FILES = "search_files"
    SCAN_WORKSPACE = "scan_workspace"
    ASK_MISSING_DATA = "ask_missing_data"
    UNKNOWN = "unknown"


def _intent_value(intent: Any) -> str:
    if isinstance(intent, AllowedIntent):
        return intent.value
    return str(intent or "").strip()


def _safe_text(value: Any, *, keep_empty: bool = False) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" and not keep_empty:
        return None
    return text


def _dedupe_texts(values: Any) -> List[str]:
    if not values:
        return []
    if isinstance(values, str):
        raw_values = [values]
    else:
        raw_values = list(values)
    result: List[str] = []
    seen = set()
    for value in raw_values:
        text = str(value).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _scan_dangerous_keys(value: Any, path: str = "args"):
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).strip().lower()
            if key_text in DANGEROUS_ARG_KEYS:
                raise ValueError(f"Campo peligroso no permitido en {path}: {key}")
            _scan_dangerous_keys(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _scan_dangerous_keys(nested, f"{path}[{index}]")


def _field_names(cls: type) -> set[str]:
    if PYDANTIC_AVAILABLE:
        return set(getattr(cls, "model_fields", {}).keys())
    return set(get_type_hints(cls).keys())


class _FallbackBaseModel:
    model_config: ClassVar[Any] = ConfigDict(extra="forbid")

    def __init__(self, **data: Any):
        hints = get_type_hints(self.__class__)
        field_names = set(hints.keys())
        extra = set(data.keys()) - field_names
        if extra:
            names = ", ".join(sorted(extra))
            raise ValueError(f"Campos no permitidos para {self.__class__.__name__}: {names}")
        for name, annotation in hints.items():
            if name in data:
                value = data[name]
            else:
                default = getattr(self.__class__, name, None)
                if isinstance(default, _FallbackField):
                    value = default.build()
                else:
                    value = copy.deepcopy(default)
            setattr(self, name, self._coerce_value(value, annotation, name))
        self._validate_model()

    @classmethod
    def model_validate(cls, value: Any):
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(**value)
        raise ValueError(f"No se puede validar {type(value).__name__} como {cls.__name__}")

    def model_dump(self, *args: Any, exclude_none: bool = False, **kwargs: Any) -> Dict[str, Any]:
        del args, kwargs
        data: Dict[str, Any] = {}
        for name in get_type_hints(self.__class__).keys():
            value = self._dump_value(getattr(self, name))
            if exclude_none and value is None:
                continue
            data[name] = value
        return data

    def model_copy(self, *, update: Optional[Dict[str, Any]] = None, deep: bool = False):
        data = self.model_dump()
        if deep:
            data = copy.deepcopy(data)
        if update:
            data.update(update)
        return self.__class__.model_validate(data)

    def dict(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self.model_dump(*args, **kwargs)

    def copy(self, *, update: Optional[Dict[str, Any]] = None, deep: bool = False):
        return self.model_copy(update=update, deep=deep)

    def _validate_model(self):
        return None

    @classmethod
    def _coerce_value(cls, value: Any, annotation: Any, field_name: str):
        origin = get_origin(annotation)
        args = get_args(annotation)
        if annotation is Any:
            return value
        if origin in (types.UnionType, getattr(types, "UnionType", object)):
            return cls._coerce_union(value, args, field_name)
        if origin is Optional:
            return cls._coerce_union(value, args, field_name)
        if origin is list or origin is List:
            if value is None:
                return []
            if not isinstance(value, list):
                raise ValueError(f"{field_name} debe ser una lista")
            item_type = args[0] if args else Any
            return [cls._coerce_value(item, item_type, field_name) for item in value]
        if origin is dict or origin is Dict:
            if value is None:
                return {}
            if not isinstance(value, dict):
                raise ValueError(f"{field_name} debe ser un diccionario")
            return value
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            try:
                return value if isinstance(value, annotation) else annotation(value)
            except Exception as exc:
                allowed = ", ".join(item.value for item in annotation)
                raise ValueError(f"{field_name} no permitido: {value}. Permitidos: {allowed}") from exc
        if isinstance(annotation, type) and issubclass(annotation, _FallbackBaseModel):
            if value is None:
                return None
            return annotation.model_validate(value)
        if annotation is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "si", "sí", "yes"}
            return bool(value)
        if annotation is int:
            if value is None:
                return 0
            return int(value)
        if annotation is float:
            if value is None:
                return 0.0
            return float(value)
        if annotation is str:
            if value is None:
                return ""
            return str(value)
        return value

    @classmethod
    def _coerce_union(cls, value: Any, args: Any, field_name: str):
        if value is None and type(None) in args:
            return None
        last_error: Optional[Exception] = None
        for option in args:
            if option is type(None):
                continue
            try:
                return cls._coerce_value(value, option, field_name)
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        return value

    @classmethod
    def _dump_value(cls, value: Any):
        if isinstance(value, Enum):
            return value.value
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, list):
            return [cls._dump_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): cls._dump_value(nested) for key, nested in value.items()}
        return value

    def __repr__(self) -> str:
        args = ", ".join(f"{key}={value!r}" for key, value in self.model_dump().items())
        return f"{self.__class__.__name__}({args})"


class _StrictModel(_PydanticBaseModel if PYDANTIC_AVAILABLE else _FallbackBaseModel):
    if PYDANTIC_AVAILABLE:  # pragma: no cover - depends on external package.
        model_config = ConfigDict(extra="forbid", validate_assignment=True)

        def model_post_init(self, __context: Any):
            del __context
            self._validate_model()

    def _validate_model(self):
        return None


class ActionArgs(_StrictModel):
    table_path: Optional[str] = None
    excel_name: Optional[str] = None
    name_column: Optional[str] = None
    column_name: Optional[str] = None
    reference_column: Optional[str] = None
    source_folder: Optional[str] = None
    source_folders: List[str] = Field(default_factory=list)
    destination_folder: Optional[str] = None
    folder_name: Optional[str] = None
    file_name: Optional[str] = None
    target: Optional[str] = None
    new_name: Optional[str] = None
    quantity: Optional[int] = None
    base_name: Optional[str] = None
    content: Optional[str] = None

    def _validate_model(self):
        for name in _field_names(ActionArgs):
            value = getattr(self, name)
            if name == "quantity":
                if value is not None and int(value) < 1:
                    raise ValueError("quantity debe ser mayor o igual a 1")
                continue
            if name == "source_folders":
                setattr(self, name, _dedupe_texts(value))
                continue
            keep_empty = name == "content"
            setattr(self, name, _safe_text(value, keep_empty=keep_empty))


class Clarification(_StrictModel):
    required: bool = False
    missing_fields: List[str] = Field(default_factory=list)
    question: str = ""

    def _validate_model(self):
        self.missing_fields = _dedupe_texts(self.missing_fields)
        self.question = _safe_text(self.question, keep_empty=True) or ""
        if self.required and not (self.missing_fields or self.question):
            raise ValueError("Una aclaracion requerida necesita pregunta o campos faltantes")


class FaceSyncDecision(_StrictModel):
    intent: AllowedIntent = AllowedIntent.UNKNOWN
    confidence: float = 0.0
    args: ActionArgs = Field(default_factory=ActionArgs)
    requires_clarification: bool = False
    clarification: Clarification = Field(default_factory=Clarification)
    safe_to_execute: bool = False
    requires_confirmation: bool = False
    reason_summary: str = ""
    risk_flags: List[str] = Field(default_factory=list)
    model_used: str = ""
    escalation_reason: str = ""
    retry_count: int = 0

    def _validate_model(self):
        intent = _intent_value(self.intent)
        if intent not in {item.value for item in AllowedIntent}:
            raise ValueError(f"Intent no permitido: {intent}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence debe estar entre 0 y 1")
        if int(self.retry_count) < 0:
            raise ValueError("retry_count no puede ser negativo")
        if isinstance(self.args, dict):
            self.args = ActionArgs.model_validate(self.args)
        if isinstance(self.clarification, dict):
            self.clarification = Clarification.model_validate(self.clarification)
        self.reason_summary = _safe_text(self.reason_summary, keep_empty=True) or ""
        self.model_used = _safe_text(self.model_used, keep_empty=True) or ""
        self.escalation_reason = _safe_text(self.escalation_reason, keep_empty=True) or ""
        self.risk_flags = _dedupe_texts(self.risk_flags)
        if intent == AllowedIntent.ASK_MISSING_DATA.value:
            self.requires_clarification = True
        if self.requires_clarification:
            self.clarification.required = True
            self.safe_to_execute = False


class ActionStep(_StrictModel):
    step_id: int = 1
    tool_name: str = ""
    action: str = ""
    args: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    requires_confirmation: bool = False

    def _validate_model(self):
        if int(self.step_id) < 1:
            raise ValueError("step_id debe ser mayor o igual a 1")
        self.tool_name = _safe_text(self.tool_name, keep_empty=True) or ""
        self.action = _safe_text(self.action, keep_empty=True) or ""
        self.description = _safe_text(self.description, keep_empty=True) or ""
        _scan_dangerous_keys(self.args)


class ActionPlan(_StrictModel):
    intent: AllowedIntent = AllowedIntent.UNKNOWN
    steps: List[ActionStep] = Field(default_factory=list)
    preview_required: bool = False
    preview_text: str = ""
    safe_to_execute: bool = False
    requires_confirmation: bool = False
    reason_summary: str = ""
    risk_flags: List[str] = Field(default_factory=list)

    def _validate_model(self):
        intent = _intent_value(self.intent)
        if intent not in {item.value for item in AllowedIntent}:
            raise ValueError(f"Intent no permitido: {intent}")
        self.preview_text = _safe_text(self.preview_text, keep_empty=True) or ""
        self.reason_summary = _safe_text(self.reason_summary, keep_empty=True) or ""
        self.risk_flags = _dedupe_texts(self.risk_flags)
        if self.requires_confirmation:
            self.preview_required = True
        if self.preview_required and not self.preview_text:
            self.preview_text = "Se requiere confirmacion antes de ejecutar esta accion."


class FallbackResult(_StrictModel):
    status: str
    repaired_decision: Optional[FaceSyncDecision] = None
    repaired_plan: Optional[ActionPlan] = None
    question: str = ""
    missing_fields: List[str] = Field(default_factory=list)
    reason: str = ""
    risk_flags: List[str] = Field(default_factory=list)

    def _validate_model(self):
        self.status = _safe_text(self.status, keep_empty=True) or ""
        if self.status not in ALLOWED_FALLBACK_STATUSES:
            allowed = ", ".join(sorted(ALLOWED_FALLBACK_STATUSES))
            raise ValueError(f"status no permitido: {self.status}. Permitidos: {allowed}")
        if isinstance(self.repaired_decision, dict):
            self.repaired_decision = FaceSyncDecision.model_validate(self.repaired_decision)
        if isinstance(self.repaired_plan, dict):
            self.repaired_plan = ActionPlan.model_validate(self.repaired_plan)
        self.question = _safe_text(self.question, keep_empty=True) or ""
        self.reason = _safe_text(self.reason, keep_empty=True) or ""
        self.missing_fields = _dedupe_texts(self.missing_fields)
        self.risk_flags = _dedupe_texts(self.risk_flags)
        if self.status == "clarification_needed" and not (self.question or self.missing_fields):
            raise ValueError("clarification_needed requiere question o missing_fields")


def ensure_decision(value: Any) -> FaceSyncDecision:
    return FaceSyncDecision.model_validate(value)


def ensure_action_plan(value: Any) -> ActionPlan:
    return ActionPlan.model_validate(value)


__all__ = [
    "ActionArgs",
    "ActionPlan",
    "ActionStep",
    "AllowedIntent",
    "Clarification",
    "FaceSyncDecision",
    "FallbackResult",
    "PYDANTIC_AVAILABLE",
    "ValidationError",
    "ensure_action_plan",
    "ensure_decision",
]

