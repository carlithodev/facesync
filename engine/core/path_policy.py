"""Pure path validation helpers shared by the desktop bridge.

This module deliberately performs no filesystem writes.  It is the final
defence between renderer-provided values and file operations.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Optional


_ACCOUNT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9@._+\-]{0,253}\Z")


def safe_account_id(value: object) -> str:
    text = str(value or "").strip()
    if text in {"", ".", ".."} or not _ACCOUNT_ID_RE.fullmatch(text):
        raise ValueError("identificador de cuenta invalido")
    return text


def safe_component(value: object) -> str:
    """Return one filesystem name, never an absolute or traversing path."""
    text = str(value or "").strip()
    if not text or text in {".", ".."}:
        raise ValueError("nombre vacio o reservado")
    if os.path.isabs(text) or "/" in text or "\\" in text:
        raise ValueError("el nombre no puede contener una ruta")
    if Path(text).name != text:
        raise ValueError("nombre de archivo invalido")
    return text


class WorkspacePathPolicy:
    def __init__(self, roots: Iterable[object]):
        resolved: list[Path] = []
        for raw in roots or []:
            if raw in (None, ""):
                continue
            path = Path(str(raw)).expanduser().resolve(strict=False)
            if path not in resolved:
                resolved.append(path)
        self.roots = tuple(resolved)

    def resolve(
        self,
        value: object,
        *,
        must_exist: Optional[bool] = None,
        allow_root: bool = True,
    ) -> Path:
        if value in (None, "") or not self.roots:
            raise PermissionError("no hay una ruta de workspace valida")
        candidate = Path(str(value)).expanduser().resolve(strict=False)
        matched_root = None
        for root in self.roots:
            try:
                candidate.relative_to(root)
                matched_root = root
                break
            except ValueError:
                continue
        if matched_root is None:
            raise PermissionError("la ruta sale del workspace autorizado")
        if not allow_root and candidate == matched_root:
            raise PermissionError("no se permite operar sobre la raiz del workspace")
        if must_exist is True and not candidate.exists():
            raise FileNotFoundError(str(candidate))
        if must_exist is False and candidate.exists():
            raise FileExistsError(str(candidate))
        return candidate

    def contains(self, value: object, *, allow_root: bool = True) -> bool:
        try:
            self.resolve(value, allow_root=allow_root)
            return True
        except (OSError, ValueError):
            return False


__all__ = ["WorkspacePathPolicy", "safe_account_id", "safe_component"]
