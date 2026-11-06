"""Recycle-bin deletion with a Windows stdlib fallback."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path


def send_to_recycle_bin(value: str | Path) -> None:
    path = Path(value).resolve(strict=False)
    if not path.exists():
        raise FileNotFoundError(str(path))
    try:
        from send2trash import send2trash

        send2trash(str(path))
        return
    except ImportError:
        pass

    if os.name != "nt":
        raise RuntimeError("Send2Trash es requerido fuera de Windows")

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.WORD),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    operation = SHFILEOPSTRUCTW()
    operation.wFunc = 3  # FO_DELETE
    operation.pFrom = str(path) + "\0\0"
    operation.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400  # ALLOWUNDO, NOCONFIRMATION, SILENT, NOERRORUI
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0 or operation.fAnyOperationsAborted:
        raise OSError(result, "Windows no pudo mover el elemento a la papelera")


__all__ = ["send_to_recycle_bin"]
