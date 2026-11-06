"""Small Windows DPAPI wrapper for user-bound local cache values."""

from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes


PREFIX = "DPAPI1:"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    value = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return value, buffer


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise OSError("DPAPI solo esta disponible en Windows")
    source, keepalive = _blob(data)
    target = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    if decrypt:
        ok = function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        ok = function(ctypes.byref(source), "FaceSync local biometric cache", None, None, None, 1, ctypes.byref(target))
    _ = keepalive
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(target.pbData)


def protect_text(value: str) -> str:
    encrypted = _dpapi(str(value).encode("utf-8"), decrypt=False)
    return PREFIX + base64.b64encode(encrypted).decode("ascii")


def unprotect_text(value: str) -> str:
    text = str(value)
    if not text.startswith(PREFIX):
        return text
    encrypted = base64.b64decode(text[len(PREFIX):], validate=True)
    return _dpapi(encrypted, decrypt=True).decode("utf-8")


__all__ = ["protect_text", "unprotect_text"]
