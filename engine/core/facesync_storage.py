"""Transactional, account-scoped persistence for FaceSync.

This module replaces loose embedding-cache files and the global identity JSON
with SQLite storage. It deliberately contains no recognition decisions: the
motor still produces the same embeddings and the existing reference pre-audit
still decides which identity owns a repeated code.

Sensitive payloads (face embeddings, names and source paths) remain protected
with Windows DPAPI before they are written to SQLite. The database keeps only
the minimum plaintext indexes required to locate compatible cache and identity
rows efficiently.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from core.identity_registry import IdentityRegistry, normalize_reference_code
from core.path_policy import safe_account_id
from core.private_store import protect_text, unprotect_text


SQLITE_STORAGE_SCHEMA = 2
CACHE_FLUSH_BATCH = 128


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized_account(value: Any) -> str:
    text = str(value or "default").strip() or "default"
    return safe_account_id(text).casefold()


def account_storage_key(account_id: Any) -> str:
    """Return a stable opaque directory key without exposing the email."""
    normalized = _normalized_account(account_id)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _text_hash(value: Any) -> str:
    return hashlib.sha256(_norm_text(value).encode("utf-8")).hexdigest()


def _cache_digest(cache_key: tuple) -> str:
    encoded = json.dumps(
        list(cache_key), ensure_ascii=False, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class _AccountCatalog:
    """Non-biometric catalog and one-time legacy-data ownership lock."""

    def __init__(
        self,
        path: Path,
        *,
        protector: Callable[[str], str],
    ) -> None:
        self.path = Path(path)
        self._protect = protector
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    account_key TEXT PRIMARY KEY,
                    protected_account TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS migration_claims (
                    claim_name TEXT PRIMARY KEY,
                    account_key TEXT NOT NULL,
                    claimed_at TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def touch(self, account_key: str, account_id: str) -> None:
        now = _utc_now()
        protected = self._protect(str(account_id))
        with closing(self._connect()) as db:
            db.execute(
                """
                INSERT INTO accounts(account_key, protected_account, created_at, last_seen_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_key) DO UPDATE SET
                    protected_account=excluded.protected_account,
                    last_seen_at=excluded.last_seen_at
                """,
                (account_key, protected, now, now),
            )
            db.commit()

    def claim(self, claim_name: str, account_key: str) -> bool:
        """Atomically claim legacy global data for exactly one account."""
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT account_key FROM migration_claims WHERE claim_name=?",
                (str(claim_name),),
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO migration_claims(claim_name, account_key, claimed_at) VALUES (?, ?, ?)",
                    (str(claim_name), account_key, _utc_now()),
                )
                db.commit()
                return True
            db.commit()
            return str(row[0]) == str(account_key)


class SQLiteFaceSyncStore:
    """One encrypted SQLite cache/identity store for one FaceSync account."""

    backend = "sqlite_encrypted"

    def __init__(
        self,
        app_data_root: Path,
        account_id: str = "default",
        *,
        protector: Callable[[str], str] = protect_text,
        unprotector: Callable[[str], str] = unprotect_text,
        legacy_identity_path: Optional[Path] = None,
        legacy_cache_dir: Optional[Path] = None,
    ) -> None:
        self.app_data_root = Path(app_data_root)
        self.account_id = _normalized_account(account_id)
        self.account_key = account_storage_key(self.account_id)
        self._protect = protector
        self._unprotect = unprotector
        self._lock = threading.RLock()
        self._pending_cache: Dict[str, tuple] = {}
        self.last_error = ""
        self.read_only = False
        self.legacy_cache_allowed = False

        self.account_root = (
            self.app_data_root / "context" / "accounts" / self.account_key
        )
        self.db_path = self.account_root / "facesync.db"
        self.cache_root = (
            self.app_data_root / "cache" / "accounts" / self.account_key
        )
        self.cr2_cache_dir = self.cache_root / "cr2"
        self.cr2_preview_cache_dir = self.cache_root / "cr2_preview"
        self.cr3_preview_cache_dir = self.cache_root / "cr3_preview"
        self.legacy_identity_path = (
            Path(legacy_identity_path) if legacy_identity_path else None
        )
        self.legacy_cache_dir = Path(legacy_cache_dir) if legacy_cache_dir else None

        self.account_root.mkdir(parents=True, exist_ok=True)
        self.cr2_cache_dir.mkdir(parents=True, exist_ok=True)
        self.cr2_preview_cache_dir.mkdir(parents=True, exist_ok=True)
        self.cr3_preview_cache_dir.mkdir(parents=True, exist_ok=True)

        self._db: Optional[sqlite3.Connection] = None
        try:
            self._db = sqlite3.connect(
                str(self.db_path),
                timeout=30,
                check_same_thread=False,
                isolation_level=None,
            )
            self._db.row_factory = sqlite3.Row
            self._configure()
            self._migrate_schema()
            catalog = _AccountCatalog(
                self.app_data_root / "context" / "accounts.db",
                protector=self._protect,
            )
            catalog.touch(self.account_key, self.account_id)
            # Never let an unauthenticated/default context claim biometric data
            # that belongs to a real saved account.
            if self.account_id != "default":
                self.legacy_cache_allowed = catalog.claim(
                    "legacy_global_facesync_v1", self.account_key
                )
            self._migrate_legacy_identity()
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.read_only = True
            if self._db is not None:
                try:
                    self._db.close()
                except Exception:
                    pass
                self._db = None

    def _configure(self) -> None:
        assert self._db is not None
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=30000")

    @property
    def closed(self) -> bool:
        return self._db is None

    def reopen(self) -> bool:
        """Reopen a clean store when one capability instance runs again."""
        with self._lock:
            if self._db is not None:
                return True
            if self.read_only:
                return False
            try:
                self._db = sqlite3.connect(
                    str(self.db_path),
                    timeout=30,
                    check_same_thread=False,
                    isolation_level=None,
                )
                self._db.row_factory = sqlite3.Row
                self._configure()
                self._migrate_schema()
                return True
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.read_only = True
                if self._db is not None:
                    try:
                        self._db.close()
                    except Exception:
                        pass
                    self._db = None
                return False

    def _migrate_schema(self) -> None:
        assert self._db is not None
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    cache_key_hash TEXT PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    embedding_schema INTEGER NOT NULL,
                    protected_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_embedding_cache_model
                    ON embedding_cache(model_name, embedding_schema);
                CREATE TABLE IF NOT EXISTS identity_records (
                    identity_id TEXT PRIMARY KEY,
                    code TEXT NOT NULL,
                    student_hash TEXT NOT NULL,
                    salon_hash TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    embedding_schema INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    protected_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    superseded_at TEXT NOT NULL DEFAULT '',
                    superseded_by_run_id TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_identity_lookup
                    ON identity_records(code, model_name, embedding_schema, status);
                CREATE INDEX IF NOT EXISTS idx_identity_scope
                    ON identity_records(student_hash, salon_hash, code, status);
                CREATE TABLE IF NOT EXISTS identity_route_records (
                    identity_id TEXT PRIMARY KEY,
                    code TEXT NOT NULL,
                    student_hash TEXT NOT NULL,
                    salon_hash TEXT NOT NULL,
                    format_family TEXT NOT NULL,
                    representation TEXT NOT NULL,
                    processing_version TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    embedding_schema INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    protected_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    superseded_at TEXT NOT NULL DEFAULT '',
                    superseded_by_run_id TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_identity_route_lookup
                    ON identity_route_records(
                        code, model_name, embedding_schema, format_family,
                        representation, processing_version, status
                    );
                CREATE INDEX IF NOT EXISTS idx_identity_route_scope
                    ON identity_route_records(
                        student_hash, salon_hash, code, format_family,
                        representation, processing_version, status
                    );
                CREATE TABLE IF NOT EXISTS classification_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    embedding_schema INTEGER NOT NULL,
                    protected_context TEXT NOT NULL,
                    protected_summary TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT ''
                );
                """
            )
            self._db.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema', ?)",
                (str(SQLITE_STORAGE_SCHEMA),),
            )
            self._db.execute(f"PRAGMA user_version={SQLITE_STORAGE_SCHEMA}")

    def _meta(self, key: str) -> str:
        if self._db is None:
            return ""
        row = self._db.execute(
            "SELECT value FROM meta WHERE key=?", (str(key),)
        ).fetchone()
        return str(row[0]) if row else ""

    def _set_meta(self, key: str, value: Any) -> None:
        if self._db is None:
            return
        self._db.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            (str(key), str(value)),
        )

    def _migrate_legacy_identity(self) -> None:
        if (
            self._db is None
            or self.read_only
            or not self.legacy_cache_allowed
            or self._meta("legacy_identity_migration")
        ):
            return
        if self.legacy_identity_path is None or not self.legacy_identity_path.is_file():
            self._set_meta("legacy_identity_migration", "no_data")
            return
        registry = IdentityRegistry(
            self.legacy_identity_path,
            protector=self._protect,
            unprotector=self._unprotect,
        )
        payload = registry.load()
        if registry.read_only:
            self._set_meta(
                "legacy_identity_migration_error",
                registry.last_error or "registro legacy ilegible",
            )
            return
        imported = self._import_identity_rows(payload.get("records") or [])
        self._set_meta("legacy_identity_migration", f"imported:{imported}")
        self._set_meta("legacy_identity_source", str(self.legacy_identity_path))

    def _import_identity_rows(self, records: Iterable[Dict[str, Any]]) -> int:
        if self._db is None or self.read_only:
            return 0
        count = 0
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for source in records:
                    if not isinstance(source, dict):
                        continue
                    record = dict(source)
                    embeddings = record.get("embeddings")
                    if not IdentityRegistry._valid_embeddings(embeddings):
                        continue
                    identity_id = str(record.get("identity_id") or uuid.uuid4())
                    status = str(record.get("status") or "active")
                    created_at = str(record.get("created_at") or _utc_now())
                    record["identity_id"] = identity_id
                    record["code"] = normalize_reference_code(record.get("code"))
                    record["status"] = status
                    record["created_at"] = created_at
                    protected = self._protect(
                        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                    )
                    self._db.execute(
                        """
                        INSERT OR IGNORE INTO identity_records(
                            identity_id, code, student_hash, salon_hash,
                            model_name, embedding_schema, status, run_id,
                            protected_payload, created_at, superseded_at,
                            superseded_by_run_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            identity_id,
                            record["code"],
                            _text_hash(record.get("student")),
                            _text_hash(record.get("salon")),
                            str(record.get("model_name", "")),
                            int(record.get("embedding_schema", 0) or 0),
                            status,
                            str(record.get("run_id", "legacy")),
                            protected,
                            created_at,
                            str(record.get("superseded_at", "")),
                            str(record.get("superseded_by_run_id", "")),
                        ),
                    )
                    if self._db.execute("SELECT changes()").fetchone()[0]:
                        count += 1
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return count

    # ------------------------------ embedding cache ---------------------
    def load_cached_faces(self, cache_key: tuple) -> Optional[List[Dict[str, Any]]]:
        digest = _cache_digest(cache_key)
        with self._lock:
            pending = self._pending_cache.get(digest)
            if pending is not None:
                return pending[1]
            if self._db is None or self.read_only:
                return None
            row = self._db.execute(
                "SELECT protected_payload FROM embedding_cache WHERE cache_key_hash=?",
                (digest,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(self._unprotect(str(row[0])))
            if payload.get("key") != list(cache_key):
                return None
            faces = payload.get("faces")
            return faces if isinstance(faces, list) else None
        except Exception:
            return None

    def save_cached_faces(self, cache_key: tuple, faces: list) -> None:
        if self._db is None or self.read_only:
            return
        digest = _cache_digest(cache_key)
        with self._lock:
            self._pending_cache[digest] = (tuple(cache_key), list(faces or []))
            should_flush = len(self._pending_cache) >= CACHE_FLUSH_BATCH
        if should_flush:
            self.flush_cache()

    def flush_cache(self) -> int:
        if self._db is None or self.read_only:
            return 0
        with self._lock:
            if not self._pending_cache:
                return 0
            pending = self._pending_cache
            self._pending_cache = {}
            now = _utc_now()
            rows = []
            try:
                for digest, (cache_key, faces) in pending.items():
                    payload = self._protect(json.dumps(
                        {"key": list(cache_key), "faces": faces},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ))
                    model_name = str(cache_key[-2]) if len(cache_key) >= 2 else ""
                    schema = int(cache_key[-1]) if cache_key else 0
                    rows.append((digest, model_name, schema, payload, now, now, now))
                self._db.execute("BEGIN IMMEDIATE")
                self._db.executemany(
                    """
                    INSERT INTO embedding_cache(
                        cache_key_hash, model_name, embedding_schema,
                        protected_payload, created_at, updated_at, last_accessed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cache_key_hash) DO UPDATE SET
                        protected_payload=excluded.protected_payload,
                        updated_at=excluded.updated_at,
                        last_accessed_at=excluded.last_accessed_at
                    """,
                    rows,
                )
                self._db.commit()
                return len(rows)
            except Exception as exc:
                self._db.rollback()
                self._pending_cache.update(pending)
                self.last_error = f"{type(exc).__name__}: {exc}"
                return 0

    def cache_count(self) -> int:
        if self._db is None:
            return 0
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()
            return int(row[0] or 0) + len(self._pending_cache)

    def clear_embedding_cache(self) -> int:
        """Delete disposable embeddings without touching identity history."""
        if self._db is None or self.read_only:
            return 0
        with self._lock:
            pending = len(self._pending_cache)
            self._pending_cache = {}
            self._db.execute("BEGIN IMMEDIATE")
            try:
                existing = int(
                    self._db.execute(
                        "SELECT COUNT(*) FROM embedding_cache"
                    ).fetchone()[0]
                    or 0
                )
                self._db.execute("DELETE FROM embedding_cache")
                self._db.commit()
                return pending + existing
            except Exception as exc:
                self._db.rollback()
                self.last_error = f"{type(exc).__name__}: {exc}"
                return 0

    # ------------------------------ identity registry -------------------
    def _identity_from_row(self, row: sqlite3.Row) -> Optional[Dict[str, Any]]:
        try:
            record = json.loads(self._unprotect(str(row["protected_payload"])))
            if not isinstance(record, dict):
                return None
            row_keys = set(row.keys())
            record.update({
                "identity_id": str(row["identity_id"]),
                "code": str(row["code"]),
                "model_name": str(row["model_name"]),
                "embedding_schema": int(row["embedding_schema"]),
                "status": str(row["status"]),
                "run_id": str(row["run_id"]),
                "created_at": str(row["created_at"]),
                "superseded_at": str(row["superseded_at"]),
                "superseded_by_run_id": str(row["superseded_by_run_id"]),
            })
            if "format_family" in row_keys:
                record.update({
                    "format_family": str(row["format_family"]),
                    "representation": str(row["representation"]),
                    "processing_version": str(row["processing_version"]),
                })
            return record
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def active_identity_records(self) -> List[Dict[str, Any]]:
        if self._db is None:
            return []
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM identity_records WHERE status='active' ORDER BY created_at, identity_id"
            ).fetchall()
            route_rows = self._db.execute(
                "SELECT * FROM identity_route_records WHERE status='active' ORDER BY created_at, identity_id"
            ).fetchall()
            rows = [*rows, *route_rows]
        return [record for row in rows if (record := self._identity_from_row(row))]

    def find_historical_identities(
        self,
        code: Any,
        *,
        current_student: str,
        current_salon: str,
        model_name: str,
        embedding_schema: int,
    ) -> List[Dict[str, Any]]:
        if self._db is None:
            return []
        normalized_code = normalize_reference_code(code)
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM identity_records
                WHERE code=? AND model_name=? AND embedding_schema=? AND status='active'
                ORDER BY created_at, identity_id
                """,
                (normalized_code, str(model_name), int(embedding_schema)),
            ).fetchall()
            route_rows = self._db.execute(
                """
                SELECT * FROM identity_route_records
                WHERE code=? AND model_name=? AND embedding_schema=? AND status='active'
                ORDER BY created_at, identity_id
                """,
                (normalized_code, str(model_name), int(embedding_schema)),
            ).fetchall()
            rows = [*rows, *route_rows]
        current_name = _norm_text(current_student)
        current_room = _norm_text(current_salon)
        matches = []
        for row in rows:
            record = self._identity_from_row(row)
            if not record:
                continue
            if (
                _norm_text(record.get("student")) == current_name
                and _norm_text(record.get("salon")) == current_room
            ):
                continue
            if not IdentityRegistry._valid_embeddings(record.get("embeddings")):
                continue
            matches.append(record)
        return matches

    def register_identities(
        self,
        records: Iterable[Dict[str, Any]],
        *,
        run_id: str,
    ) -> Dict[str, Any]:
        if self._db is None or self.read_only:
            return {
                "success": False,
                "registered": 0,
                "superseded": 0,
                "error": self.last_error or "SQLite en modo solo lectura",
            }
        prepared = []
        for source in records:
            embeddings = source.get("embeddings")
            if not IdentityRegistry._valid_embeddings(embeddings):
                continue
            record = dict(source)
            record["identity_id"] = str(record.get("identity_id") or uuid.uuid4())
            record["code"] = normalize_reference_code(record.get("code"))
            record["run_id"] = str(run_id)
            record["created_at"] = str(record.get("created_at") or _utc_now())
            record["status"] = "active"
            prepared.append(record)
        if not prepared:
            return {"success": True, "registered": 0, "superseded": 0}

        superseded = 0
        superseded_at = _utc_now()
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for record in prepared:
                    student_hash = _text_hash(record.get("student"))
                    salon_hash = _text_hash(record.get("salon"))
                    is_route_record = (
                        str(record.get("format_family", "")).casefold() == "cr3"
                        and str(record.get("representation", ""))
                        and str(record.get("processing_version", ""))
                    )
                    protected = self._protect(json.dumps(
                        record, ensure_ascii=False, separators=(",", ":")
                    ))
                    if is_route_record:
                        route_values = (
                            str(record.get("format_family", "")).casefold(),
                            str(record.get("representation", "")).casefold(),
                            str(record.get("processing_version", "")),
                        )
                        cursor = self._db.execute(
                            """
                            UPDATE identity_route_records
                            SET status='superseded', superseded_at=?, superseded_by_run_id=?
                            WHERE status='active' AND student_hash=? AND salon_hash=?
                              AND code=? AND model_name=? AND embedding_schema=?
                              AND format_family=? AND representation=?
                              AND processing_version=?
                            """,
                            (
                                superseded_at,
                                str(run_id),
                                student_hash,
                                salon_hash,
                                record["code"],
                                str(record.get("model_name", "")),
                                int(record.get("embedding_schema", 0) or 0),
                                *route_values,
                            ),
                        )
                        superseded += int(cursor.rowcount or 0)
                        self._db.execute(
                            """
                            INSERT INTO identity_route_records(
                                identity_id, code, student_hash, salon_hash,
                                format_family, representation, processing_version,
                                model_name, embedding_schema, status, run_id,
                                protected_payload, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                            """,
                            (
                                record["identity_id"],
                                record["code"],
                                student_hash,
                                salon_hash,
                                *route_values,
                                str(record.get("model_name", "")),
                                int(record.get("embedding_schema", 0) or 0),
                                str(run_id),
                                protected,
                                record["created_at"],
                            ),
                        )
                    else:
                        cursor = self._db.execute(
                            """
                            UPDATE identity_records
                            SET status='superseded', superseded_at=?, superseded_by_run_id=?
                            WHERE status='active' AND student_hash=? AND salon_hash=?
                              AND code=? AND model_name=? AND embedding_schema=?
                            """,
                            (
                                superseded_at,
                                str(run_id),
                                student_hash,
                                salon_hash,
                                record["code"],
                                str(record.get("model_name", "")),
                                int(record.get("embedding_schema", 0) or 0),
                            ),
                        )
                        superseded += int(cursor.rowcount or 0)
                        self._db.execute(
                            """
                            INSERT INTO identity_records(
                                identity_id, code, student_hash, salon_hash,
                                model_name, embedding_schema, status, run_id,
                                protected_payload, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                            """,
                            (
                                record["identity_id"],
                                record["code"],
                                student_hash,
                                salon_hash,
                                str(record.get("model_name", "")),
                                int(record.get("embedding_schema", 0) or 0),
                                str(run_id),
                                protected,
                                record["created_at"],
                            ),
                        )
                revision = int(self._meta("identity_revision") or 0) + 1
                self._set_meta("identity_revision", revision)
                self._db.commit()
            except Exception as exc:
                self._db.rollback()
                self.last_error = f"{type(exc).__name__}: {exc}"
                return {
                    "success": False,
                    "registered": 0,
                    "superseded": 0,
                    "error": self.last_error,
                }
        return {
            "success": True,
            "registered": len(prepared),
            "superseded": superseded,
            "revision": revision,
            "records": [IdentityRegistry.public_record(record) for record in prepared],
        }

    # ------------------------------ run ledger --------------------------
    def start_run(
        self,
        run_id: str,
        *,
        model_name: str,
        embedding_schema: int,
        context: Dict[str, Any],
    ) -> None:
        if self._db is None or self.read_only:
            return
        protected = self._protect(json.dumps(
            context or {}, ensure_ascii=False, separators=(",", ":")
        ))
        with self._lock:
            self._db.execute(
                """
                INSERT OR REPLACE INTO classification_runs(
                    run_id, status, model_name, embedding_schema,
                    protected_context, protected_summary, started_at, finished_at
                ) VALUES (?, 'running', ?, ?, ?, '', ?, '')
                """,
                (
                    str(run_id),
                    str(model_name),
                    int(embedding_schema),
                    protected,
                    _utc_now(),
                ),
            )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        summary: Dict[str, Any],
    ) -> None:
        if self._db is None or self.read_only:
            return
        protected = self._protect(json.dumps(
            summary or {}, ensure_ascii=False, separators=(",", ":"), default=str
        ))
        with self._lock:
            self._db.execute(
                """
                UPDATE classification_runs
                SET status=?, protected_summary=?, finished_at=?
                WHERE run_id=?
                """,
                (str(status), protected, _utc_now(), str(run_id)),
            )

    def close(self) -> None:
        self.flush_cache()
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None


class SQLiteIdentityRegistry:
    """Compatibility adapter used by the unchanged reference pre-audit."""

    def __init__(self, store: SQLiteFaceSyncStore) -> None:
        self.store = store

    @property
    def read_only(self) -> bool:
        return self.store.read_only

    @property
    def last_error(self) -> str:
        return self.store.last_error

    def active_records(self) -> List[Dict[str, Any]]:
        return self.store.active_identity_records()

    def find_historical(self, code: Any, **kwargs) -> List[Dict[str, Any]]:
        return self.store.find_historical_identities(code, **kwargs)

    def register_many(
        self, records: Iterable[Dict[str, Any]], *, run_id: str
    ) -> Dict[str, Any]:
        return self.store.register_identities(records, run_id=run_id)

    @staticmethod
    def public_record(record: Dict[str, Any]) -> Dict[str, Any]:
        return IdentityRegistry.public_record(record)


__all__ = [
    "SQLITE_STORAGE_SCHEMA",
    "SQLiteFaceSyncStore",
    "SQLiteIdentityRegistry",
    "account_storage_key",
]
