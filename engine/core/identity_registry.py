"""Encrypted, versioned registry of FaceSync identities confirmed by a run.

The regular embedding cache is intentionally image-oriented and unlabeled.  This
registry stores only the selected face of a trusted reference plus a small set
of confirmed gallery anchors.  It is used by the reference pre-audit; it never
changes the recognition model or its thresholds.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from core.private_store import protect_text, unprotect_text


REGISTRY_SCHEMA = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def normalize_reference_code(value: Any) -> str:
    """Return the final numeric reference code, or a normalized literal value."""
    text = str(value or "").strip()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    numbers = re.findall(r"\d+", text)
    if numbers:
        return numbers[-1].lstrip("0") or "0"
    return _norm_text(text)


def file_sha256(path: Optional[Path]) -> str:
    if path is None:
        return ""
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


class IdentityRegistry:
    """DPAPI-protected identity ledger with append-only supersession history."""

    def __init__(
        self,
        path: Path,
        *,
        protector: Callable[[str], str] = protect_text,
        unprotector: Callable[[str], str] = unprotect_text,
    ) -> None:
        self.path = Path(path)
        self._protect = protector
        self._unprotect = unprotector
        self._data: Optional[Dict[str, Any]] = None
        self.last_error = ""
        self.read_only = False

    @staticmethod
    def _empty() -> Dict[str, Any]:
        return {
            "schema": REGISTRY_SCHEMA,
            "created_at": _utc_now(),
            "updated_at": "",
            "revision": 0,
            "records": [],
        }

    def load(self, *, refresh: bool = False) -> Dict[str, Any]:
        if self._data is not None and not refresh:
            return self._data
        if not self.path.exists():
            self._data = self._empty()
            return self._data
        try:
            payload = json.loads(self._unprotect(self.path.read_text(encoding="utf-8")))
            if not isinstance(payload, dict):
                raise ValueError("Formato de registro invalido")
            if int(payload.get("schema", 0)) != REGISTRY_SCHEMA:
                raise ValueError("Version de registro no compatible")
            records = payload.get("records")
            if not isinstance(records, list):
                raise ValueError("Lista de identidades invalida")
            self._data = payload
            self.last_error = ""
            self.read_only = False
        except Exception as exc:
            # Never overwrite an unreadable biometric registry automatically.
            self._data = self._empty()
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.read_only = True
        return self._data

    def active_records(self) -> List[Dict[str, Any]]:
        return [
            record
            for record in self.load().get("records", [])
            if isinstance(record, dict) and record.get("status", "active") == "active"
        ]

    def find_historical(
        self,
        code: Any,
        *,
        current_student: str,
        current_salon: str,
        model_name: str,
        embedding_schema: int,
    ) -> List[Dict[str, Any]]:
        normalized_code = normalize_reference_code(code)
        current_name = _norm_text(current_student)
        current_room = _norm_text(current_salon)
        matches = []
        for record in self.active_records():
            if normalize_reference_code(record.get("code")) != normalized_code:
                continue
            if str(record.get("model_name", "")) != str(model_name):
                continue
            if int(record.get("embedding_schema", 0) or 0) != int(embedding_schema):
                continue
            same_identity_scope = (
                _norm_text(record.get("student")) == current_name
                and _norm_text(record.get("salon")) == current_room
            )
            if same_identity_scope:
                continue
            if not self._valid_embeddings(record.get("embeddings")):
                continue
            matches.append(record)
        return matches

    @staticmethod
    def _valid_embeddings(value: Any) -> bool:
        if not isinstance(value, list) or not value:
            return False
        return all(
            isinstance(embedding, list)
            and bool(embedding)
            and all(isinstance(number, (int, float)) for number in embedding)
            for embedding in value
        )

    @staticmethod
    def public_record(record: Dict[str, Any]) -> Dict[str, Any]:
        """Return report-safe metadata without biometric vectors."""
        public = {
            "identity_id": record.get("identity_id", ""),
            "code": record.get("code", ""),
            "student": record.get("student", ""),
            "salon": record.get("salon", ""),
            "table_path": record.get("table_path", ""),
            "reference_path": record.get("reference_path", ""),
            "model_name": record.get("model_name", ""),
            "embedding_schema": record.get("embedding_schema", 0),
            "anchor_count": len(record.get("embeddings") or []),
            "support_count": record.get("support_count", 0),
            "created_at": record.get("created_at", ""),
            "status": record.get("status", "active"),
        }
        if record.get("format_family"):
            public.update({
                "format_family": record.get("format_family", ""),
                "representation": record.get("representation", ""),
                "processing_version": record.get("processing_version", ""),
            })
        return public

    def register_many(self, records: Iterable[Dict[str, Any]], *, run_id: str) -> Dict[str, Any]:
        data = copy.deepcopy(self.load())
        if self.read_only:
            return {
                "success": False,
                "registered": 0,
                "superseded": 0,
                "error": self.last_error or "Registro en modo solo lectura",
            }

        prepared: List[Dict[str, Any]] = []
        for item in records:
            embeddings = item.get("embeddings")
            if not self._valid_embeddings(embeddings):
                continue
            record = dict(item)
            record["identity_id"] = str(record.get("identity_id") or uuid.uuid4())
            record["code"] = normalize_reference_code(record.get("code"))
            record["run_id"] = str(run_id)
            record["created_at"] = str(record.get("created_at") or _utc_now())
            record["status"] = "active"
            prepared.append(record)

        if not prepared:
            return {"success": True, "registered": 0, "superseded": 0}

        existing = data.setdefault("records", [])
        superseded = 0
        superseded_at = _utc_now()
        for new_record in prepared:
            new_key = self._identity_key(new_record)
            for old_record in existing:
                if (
                    isinstance(old_record, dict)
                    and old_record.get("status", "active") == "active"
                    and self._identity_key(old_record) == new_key
                ):
                    old_record["status"] = "superseded"
                    old_record["superseded_at"] = superseded_at
                    old_record["superseded_by_run_id"] = str(run_id)
                    superseded += 1
            existing.append(new_record)

        data["updated_at"] = _utc_now()
        data["revision"] = int(data.get("revision", 0) or 0) + 1
        try:
            self._write(data)
            return {
                "success": True,
                "registered": len(prepared),
                "superseded": superseded,
                "revision": data["revision"],
                "records": [self.public_record(record) for record in prepared],
            }
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {
                "success": False,
                "registered": 0,
                "superseded": 0,
                "error": self.last_error,
            }

    @staticmethod
    def _identity_key(record: Dict[str, Any]) -> tuple:
        return (
            _norm_text(record.get("student")),
            _norm_text(record.get("salon")),
            normalize_reference_code(record.get("code")),
            str(record.get("model_name", "")),
            int(record.get("embedding_schema", 0) or 0),
            str(record.get("format_family", "legacy")).casefold(),
            str(record.get("representation", "legacy")).casefold(),
            str(record.get("processing_version", "legacy")),
        )

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        protected = self._protect(serialized)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(protected, encoding="utf-8")
        os.replace(temporary, self.path)
        self._data = data


__all__ = [
    "IdentityRegistry",
    "REGISTRY_SCHEMA",
    "file_sha256",
    "normalize_reference_code",
]
