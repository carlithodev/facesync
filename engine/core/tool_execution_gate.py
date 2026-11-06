from __future__ import annotations

import re
from typing import Any, Dict, Iterable


class ToolExecutionGate:
    NATURAL_TOKENS = {
        "crea", "crear", "creame", "mueve", "mover", "borra", "borrar",
        "elimina", "renombra", "adentro", "dentro", "mete", "pon",
        "columna", "usando", "referencia",
    }
    PATH_KEYS = {"path", "folder_name", "file_name", "target", "source", "src", "dest", "destination", "destination_folder", "source_folder", "table_path"}
    REQUIRED_BY_ACTION = {
        "create_folder": ("folder_name",),
        "create_file": ("file_name",),
        "move_item": ("target", "destination_folder"),
        "copy_item": ("target", "destination_folder"),
        "rename_item": ("target", "new_name"),
        "delete_item": ("target",),
        "run_reference_face_matching": ("table_path", "name_column", "reference_column", "source_folder", "destination_folder"),
        "create_folders_from_table": ("table_path", "name_column"),
        "create_folders_from_excel": ("table_path", "name_column"),
    }

    @classmethod
    def validate_action(cls, action: str, args: Dict[str, Any]) -> tuple[bool, str]:
        args = dict(args or {})
        for key in cls.REQUIRED_BY_ACTION.get(action, ()):
            ok, reason = cls._valid_value(key, args.get(key))
            if not ok:
                return False, reason
        for key, value in args.items():
            if value in (None, "") and key not in cls.REQUIRED_BY_ACTION.get(action, ()):
                continue
            if key in cls.PATH_KEYS or key.endswith("_column") or key == "new_name":
                ok, reason = cls._valid_value(key, value)
                if not ok:
                    return False, reason
        name = cls._norm(args.get("name_column"))
        ref = cls._norm(args.get("reference_column"))
        if action == "run_reference_face_matching" and name and ref and name == ref:
            return False, "name_column y reference_column no pueden ser iguales"
        dest = cls._norm(args.get("destination_folder"))
        if dest and any(token in dest for token in ("columna", "usando", "referencia")):
            return False, "destination_folder contaminado"
        return True, ""

    @classmethod
    def validate_tool_args(cls, action: str, **kwargs: Any) -> tuple[bool, str]:
        for key, value in kwargs.items():
            ok, reason = cls._valid_value(key, value)
            if not ok:
                return False, reason
        return cls.validate_action(action, kwargs)

    @classmethod
    def _valid_value(cls, key: str, value: Any) -> tuple[bool, str]:
        if value is None:
            return False, f"{key} no puede ser None"
        text = str(value).strip()
        if not text or text.lower() == "none":
            return False, f"{key} vacío o None"
        if key in {"folder_name", "file_name", "target", "source", "src", "dest", "destination", "destination_folder", "source_folder"}:
            norm = cls._norm(text)
            if cls._looks_like_instruction(norm):
                return False, f"{key} parece texto natural crudo"
        return True, ""

    @classmethod
    def _looks_like_instruction(cls, text: str) -> bool:
        tokens = set(text.split())
        return len(tokens) >= 4 and bool(tokens & cls.NATURAL_TOKENS)

    @staticmethod
    def _norm(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").lower()).strip()
