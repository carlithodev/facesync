"""
Structured result shared by local tools, the UI agent and Gemini orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class OrchestrationResult:
    handled: bool
    message: str = ""
    action: str = ""
    refresh: bool = False
    used_gemini: bool = False
    requires_clarification: bool = False
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def not_handled(cls) -> "OrchestrationResult":
        return cls(handled=False)

    @classmethod
    def ok(
        cls,
        message: str,
        action: str = "",
        refresh: bool = False,
        data: Dict[str, Any] | None = None,
    ) -> "OrchestrationResult":
        return cls(
            handled=True,
            message=message,
            action=action,
            refresh=refresh,
            data=data or {},
        )
