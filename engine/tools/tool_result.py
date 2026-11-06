from __future__ import annotations

from typing import Any, Dict, List


STANDARD_KEYS = ("created", "reused", "skipped", "moved", "copied", "deleted", "errors")


def tool_result(
    *,
    success: bool,
    action: str,
    message: str = "",
    metadata: Dict[str, Any] | None = None,
    report_path: str = "",
    **items: Any,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "success": bool(success),
        "action": action,
        "message": message,
        "created": [],
        "reused": [],
        "skipped": [],
        "moved": [],
        "copied": [],
        "deleted": [],
        "errors": [],
        "report_path": report_path,
        "metadata": dict(metadata or {}),
    }
    for key in STANDARD_KEYS:
        value = items.get(key, [])
        if value is None:
            value = []
        result[key] = value if isinstance(value, list) else [value]
    for key, value in items.items():
        if key not in STANDARD_KEYS:
            result[key] = value
    if not success and message and not result["errors"]:
        result["errors"] = [message]
    if not success:
        result["error"] = result["errors"][0] if result["errors"] else message
    return result


def tool_error(action: str, message: str, **metadata: Any) -> Dict[str, Any]:
    result = tool_result(success=False, action=action, message=message, errors=[message], metadata=metadata)
    for key in ("error_type", "code"):
        if key in metadata:
            result[key] = metadata[key]
    return result
