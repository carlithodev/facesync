"""
Persistent context vault for FaceSync AI.

ContextVault stores compact conversational and operational state in a local
SQLite database under app-data. If SQLite cannot be opened, it switches to a RAM
fallback and keeps the same public API so the application can continue.
"""

from __future__ import annotations

import copy
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.app_paths import ensure_app_data_root


DB_FILE_NAME = "facesync_context.db"
MAX_TEXT_CHARS = 2000
MAX_LIST_ITEMS = 80
MAX_DICT_KEYS = 120
SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "credential",
    "credentials",
    "password",
    "refresh_token",
    "secret",
    "token",
}
MASSIVE_KEYS = {
    "csv",
    "csv_content",
    "dataframe",
    "excel",
    "excel_content",
    "file_bytes",
    "image",
    "image_bytes",
    "photo",
    "photo_bytes",
    "photos",
    "raw_csv",
    "raw_excel",
    "rows",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _json_loads(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return copy.deepcopy(default)
    try:
        return json.loads(value)
    except Exception:
        return copy.deepcopy(default)


def _compact_text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _clean_list(values: Any, limit: int = MAX_LIST_ITEMS) -> List[str]:
    if not values:
        return []
    if isinstance(values, str):
        raw_values = [values]
    else:
        raw_values = list(values)
    cleaned: List[str] = []
    seen = set()
    for value in raw_values[:limit]:
        text = _compact_text(value, 300)
        if text and text not in seen:
            cleaned.append(text)
            seen.add(text)
    return cleaned


def _storage_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        path = Path(text).expanduser()
        if path.is_absolute():
            return str(path.resolve(strict=False)).replace("\\", "/")
    except Exception:
        pass
    return text.replace("\\", "/").strip()


def _sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return str(value).replace("\\", "/")
    if isinstance(value, str):
        return _compact_text(value)
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        compact = [_sanitize(item, depth + 1) for item in items[:MAX_LIST_ITEMS]]
        if len(items) > MAX_LIST_ITEMS:
            compact.append({"truncated_count": len(items) - MAX_LIST_ITEMS})
        return compact
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for index, (key, nested) in enumerate(value.items()):
            if index >= MAX_DICT_KEYS:
                result["truncated_keys"] = len(value) - MAX_DICT_KEYS
                break
            key_text = str(key).strip()
            lower_key = key_text.lower()
            if lower_key in SECRET_KEYS or lower_key.endswith("_secret"):
                result[key_text] = "[redacted]"
                continue
            if lower_key in MASSIVE_KEYS or lower_key.endswith("_bytes") or lower_key.endswith("_content"):
                result[key_text] = "[omitted]"
                continue
            result[key_text] = _sanitize(nested, depth + 1)
        return result
    return _compact_text(value)


class ContextVault:
    def __init__(
        self,
        user_app_data_root: Optional[str | Path] = None,
        app_data_root: Optional[str | Path] = None,
        db_path: Optional[str | Path] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.user_app_data_root = Path(user_app_data_root).expanduser() if user_app_data_root else None
        self.app_data_root = Path(app_data_root).expanduser() if app_data_root else None
        self.db_path = Path(db_path).expanduser() if db_path else None
        self.logger = logger or logging.getLogger(__name__)
        self.connection: Optional[sqlite3.Connection] = None
        self.initialized = False
        self.using_memory = False
        self.last_warning = ""
        self._memory: Dict[str, List[Dict[str, Any]]] = {}
        self._ids: Dict[str, int] = {}

    def initialize(self):
        if self.initialized:
            return self

        candidates = self._db_candidates()
        last_error: Optional[Exception] = None
        for candidate in candidates:
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(candidate), timeout=10)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("PRAGMA journal_mode = WAL")
                self.connection = conn
                self.db_path = candidate
                self._create_schema()
                self.initialized = True
                self.using_memory = False
                return self
            except Exception as exc:
                last_error = exc
                try:
                    if self.connection:
                        self.connection.close()
                except Exception:
                    pass
                self.connection = None

        self._activate_memory(last_error)
        return self

    def close(self):
        if self.connection is not None:
            try:
                self.connection.close()
            finally:
                self.connection = None
                if not self.using_memory:
                    self.initialized = False
        return True

    def __enter__(self):
        return self.initialize()

    def __exit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback
        self.close()
        return False

    def get_or_create_user(self, user_key: str, email: Optional[str] = None, display_name: Optional[str] = None) -> int:
        self._ensure_ready()
        user_key = _compact_text(user_key, 300)
        email = _compact_text(email, 300) if email else ""
        display_name = _compact_text(display_name, 300) if display_name else ""
        if self.using_memory:
            existing = self._memory_find("users", user_key=user_key)
            if existing:
                if email:
                    existing["email"] = email
                if display_name:
                    existing["display_name"] = display_name
                existing["updated_at"] = _now()
                return int(existing["id"])
            return self._memory_insert(
                "users",
                {
                    "user_key": user_key,
                    "email": email,
                    "display_name": display_name,
                    "created_at": _now(),
                    "updated_at": _now(),
                },
            )

        row = self._fetchone("SELECT id FROM users WHERE user_key = ?", (user_key,))
        if row:
            self._execute(
                "UPDATE users SET email = COALESCE(NULLIF(?, ''), email), display_name = COALESCE(NULLIF(?, ''), display_name), updated_at = ? WHERE id = ?",
                (email, display_name, _now(), row["id"]),
            )
            return int(row["id"])
        return self._execute(
            "INSERT INTO users (user_key, email, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (user_key, email, display_name, _now(), _now()),
        )

    def get_or_create_project(self, user_id: int, project_root: str | Path) -> int:
        self._ensure_ready()
        root = _storage_path(project_root)
        project_name = Path(root).name if root else ""
        if self.using_memory:
            existing = self._memory_find("projects", user_id=int(user_id), project_root=root)
            if existing:
                existing["updated_at"] = _now()
                return int(existing["id"])
            return self._memory_insert(
                "projects",
                {
                    "user_id": int(user_id),
                    "project_root": root,
                    "project_name": project_name,
                    "created_at": _now(),
                    "updated_at": _now(),
                },
            )

        row = self._fetchone(
            "SELECT id FROM projects WHERE user_id = ? AND project_root = ?",
            (int(user_id), root),
        )
        if row:
            self._execute("UPDATE projects SET updated_at = ? WHERE id = ?", (_now(), row["id"]))
            return int(row["id"])
        return self._execute(
            "INSERT INTO projects (user_id, project_root, project_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (int(user_id), root, project_name, _now(), _now()),
        )

    def start_session(self, user_id: int, project_id: int) -> int:
        self._ensure_ready()
        data = {"user_id": int(user_id), "project_id": int(project_id), "started_at": _now(), "ended_at": "", "status": "active"}
        if self.using_memory:
            return self._memory_insert("sessions", data)
        return self._execute(
            "INSERT INTO sessions (user_id, project_id, started_at, ended_at, status) VALUES (?, ?, ?, ?, ?)",
            (data["user_id"], data["project_id"], data["started_at"], data["ended_at"], data["status"]),
        )

    def get_or_start_session(self, user_id: int, project_id: int) -> int:
        """Resume la conversacion activa de una cuenta/proyecto o crea una.

        Una sesion activa funciona como el hilo principal persistente del chat.
        Cerrar la aplicacion no la termina; "Nueva conversacion" si lo hace.
        """
        self._ensure_ready()
        user_id = int(user_id)
        project_id = int(project_id)
        if self.using_memory:
            rows = [
                row for row in self._memory_table("sessions")
                if int(row.get("user_id", 0)) == user_id
                and int(row.get("project_id", 0)) == project_id
                and row.get("status") == "active"
            ]
            if rows:
                return int(sorted(rows, key=lambda item: int(item.get("id", 0)), reverse=True)[0]["id"])
            return self.start_session(user_id, project_id)

        row = self._fetchone(
            """
            SELECT id FROM sessions
            WHERE user_id = ? AND project_id = ? AND status = 'active'
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, project_id),
        )
        return int(row["id"]) if row else self.start_session(user_id, project_id)

    def get_session_messages(self, session_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Devuelve el historial reciente en orden conversacional."""
        self._ensure_ready()
        limit = max(1, min(int(limit or 50), 200))
        if self.using_memory:
            rows = [
                row for row in self._memory_table("conversation_messages")
                if int(row.get("session_id", 0)) == int(session_id)
            ]
            rows = sorted(rows, key=lambda item: int(item.get("id", 0)), reverse=True)[:limit]
            rows.reverse()
        else:
            fetched = self._fetchall(
                """
                SELECT role, message, intent, confidence, model_used, created_at
                FROM conversation_messages
                WHERE session_id = ? ORDER BY id DESC LIMIT ?
                """,
                (int(session_id), limit),
            )
            rows = [dict(row) for row in reversed(fetched)]

        return [
            {
                "role": str(row.get("role") or ""),
                "content": str(row.get("message") or ""),
                "timestamp": str(row.get("created_at") or ""),
                "intent": str(row.get("intent") or ""),
                "confidence": row.get("confidence"),
                "model_used": str(row.get("model_used") or ""),
            }
            for row in rows
        ]

    def end_session(self, session_id: int):
        self._ensure_ready()
        if self.using_memory:
            row = self._memory_get("sessions", session_id)
            if row:
                row["ended_at"] = _now()
                row["status"] = "ended"
            return True
        self._execute("UPDATE sessions SET ended_at = ?, status = ? WHERE id = ?", (_now(), "ended", int(session_id)))
        return True

    def save_message(
        self,
        session_id: int,
        role: str,
        message: str,
        intent: str = "",
        confidence: Optional[float] = None,
        model_used: str = "",
    ) -> int:
        self._ensure_ready()
        data = {
            "session_id": int(session_id),
            "role": _compact_text(role, 40),
            "message": _compact_text(message),
            "intent": _compact_text(intent, 120),
            "confidence": confidence,
            "model_used": _compact_text(model_used, 120),
            "created_at": _now(),
        }
        if self.using_memory:
            return self._memory_insert("conversation_messages", data)
        return self._execute(
            """
            INSERT INTO conversation_messages
            (session_id, role, message, intent, confidence, model_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(data.values()),
        )

    def save_context_snapshot(self, session_id: int, snapshot_dict: Dict[str, Any]) -> int:
        self._ensure_ready()
        data = {"session_id": int(session_id), "snapshot_json": _sanitize(snapshot_dict or {}), "created_at": _now()}
        if self.using_memory:
            return self._memory_insert("context_snapshots", data)
        return self._execute(
            "INSERT INTO context_snapshots (session_id, snapshot_json, created_at) VALUES (?, ?, ?)",
            (data["session_id"], _json_dumps(data["snapshot_json"]), data["created_at"]),
        )

    def save_detected_table(self, project_id: int, file_path: str | Path, columns: List[str], row_count: Optional[int] = None) -> int:
        self._ensure_ready()
        stored_path = _storage_path(file_path)
        cols = _clean_list(columns, 300)
        file_name = Path(stored_path).name if stored_path else ""
        data = {
            "project_id": int(project_id),
            "file_path": stored_path,
            "file_name": file_name,
            "columns_json": cols,
            "row_count": int(row_count) if row_count is not None else None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        if self.using_memory:
            existing = self._memory_find("detected_tables", project_id=int(project_id), file_path=stored_path)
            if existing:
                existing.update(data)
                table_id = int(existing["id"])
                self._memory["detected_columns"] = [
                    row for row in self._memory_table("detected_columns") if int(row.get("table_id", 0)) != table_id
                ]
            else:
                table_id = self._memory_insert("detected_tables", data)
            self._save_columns_memory(table_id, int(project_id), stored_path, cols)
            return table_id

        row = self._fetchone(
            "SELECT id FROM detected_tables WHERE project_id = ? AND file_path = ?",
            (int(project_id), stored_path),
        )
        if row:
            table_id = int(row["id"])
            self._execute(
                "UPDATE detected_tables SET file_name = ?, columns_json = ?, row_count = ?, updated_at = ? WHERE id = ?",
                (file_name, _json_dumps(cols), data["row_count"], _now(), table_id),
            )
            self._execute("DELETE FROM detected_columns WHERE table_id = ?", (table_id,))
        else:
            table_id = self._execute(
                """
                INSERT INTO detected_tables
                (project_id, file_path, file_name, columns_json, row_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (int(project_id), stored_path, file_name, _json_dumps(cols), data["row_count"], _now(), _now()),
            )
        for index, column in enumerate(cols):
            self._execute(
                "INSERT INTO detected_columns (table_id, project_id, file_path, column_name, ordinal, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (table_id, int(project_id), stored_path, column, index, _now()),
            )
        return table_id

    def get_last_detected_table(self, project_id: int) -> Optional[Dict[str, Any]]:
        self._ensure_ready()
        if self.using_memory:
            rows = [row for row in self._memory_table("detected_tables") if int(row.get("project_id", 0)) == int(project_id)]
            if not rows:
                return None
            row = sorted(rows, key=lambda item: (item.get("updated_at", ""), int(item.get("id", 0))), reverse=True)[0]
            return self._table_dict(row)
        row = self._fetchone(
            "SELECT * FROM detected_tables WHERE project_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (int(project_id),),
        )
        return self._table_dict(dict(row)) if row else None

    def get_table_columns(self, project_id: int, file_path: str | Path) -> List[str]:
        self._ensure_ready()
        stored_path = _storage_path(file_path)
        if self.using_memory:
            table = self._memory_find("detected_tables", project_id=int(project_id), file_path=stored_path)
            return list(table.get("columns_json", [])) if table else []
        rows = self._fetchall(
            "SELECT column_name FROM detected_columns WHERE project_id = ? AND file_path = ? ORDER BY ordinal ASC, id ASC",
            (int(project_id), stored_path),
        )
        return [str(row["column_name"]) for row in rows]

    def save_action(
        self,
        session_id: int,
        intent: str,
        args: Dict[str, Any],
        result: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error_type: str = "",
        error_message: str = "",
    ) -> int:
        self._ensure_ready()
        data = {
            "session_id": int(session_id),
            "intent": _compact_text(intent, 120),
            "args_json": _sanitize(args or {}),
            "result_json": _sanitize(result or {}),
            "success": bool(success),
            "error_type": _compact_text(error_type, 120),
            "error_message": _compact_text(error_message),
            "created_at": _now(),
        }
        if self.using_memory:
            return self._memory_insert("action_history", data)
        return self._execute(
            """
            INSERT INTO action_history
            (session_id, intent, args_json, result_json, success, error_type, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["session_id"],
                data["intent"],
                _json_dumps(data["args_json"]),
                _json_dumps(data["result_json"]),
                int(data["success"]),
                data["error_type"],
                data["error_message"],
                data["created_at"],
            ),
        )

    def get_recent_actions(self, session_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        self._ensure_ready()
        limit = max(1, min(int(limit), 50))
        if self.using_memory:
            rows = [row for row in self._memory_table("action_history") if int(row.get("session_id", 0)) == int(session_id)]
            rows = sorted(rows, key=lambda item: int(item.get("id", 0)), reverse=True)[:limit]
            return [self._action_dict(row) for row in rows]
        rows = self._fetchall(
            "SELECT * FROM action_history WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (int(session_id), limit),
        )
        return [self._action_dict(dict(row)) for row in rows]

    def save_pending_action(
        self,
        session_id: int,
        intent: str,
        args: Dict[str, Any],
        missing_fields: List[str],
        preview_text: str = "",
    ) -> int:
        self._ensure_ready()
        data = {
            "session_id": int(session_id),
            "intent": _compact_text(intent, 120),
            "args_json": _sanitize(args or {}),
            "missing_fields_json": _clean_list(missing_fields),
            "preview_text": _compact_text(preview_text),
            "status": "active",
            "created_at": _now(),
            "updated_at": _now(),
        }
        if self.using_memory:
            return self._memory_insert("pending_actions", data)
        return self._execute(
            """
            INSERT INTO pending_actions
            (session_id, intent, args_json, missing_fields_json, preview_text, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["session_id"],
                data["intent"],
                _json_dumps(data["args_json"]),
                _json_dumps(data["missing_fields_json"]),
                data["preview_text"],
                data["status"],
                data["created_at"],
                data["updated_at"],
            ),
        )

    def get_active_pending_action(self, session_id: int) -> Optional[Dict[str, Any]]:
        self._ensure_ready()
        if self.using_memory:
            rows = [
                row
                for row in self._memory_table("pending_actions")
                if int(row.get("session_id", 0)) == int(session_id) and row.get("status") == "active"
            ]
            if not rows:
                return None
            return self._pending_dict(sorted(rows, key=lambda item: int(item.get("id", 0)), reverse=True)[0])
        row = self._fetchone(
            "SELECT * FROM pending_actions WHERE session_id = ? AND status = ? ORDER BY id DESC LIMIT 1",
            (int(session_id), "active"),
        )
        return self._pending_dict(dict(row)) if row else None

    def update_pending_action_status(self, pending_id: int, status: str):
        self._ensure_ready()
        status = _compact_text(status, 40)
        if self.using_memory:
            row = self._memory_get("pending_actions", pending_id)
            if row:
                row["status"] = status
                row["updated_at"] = _now()
            return True
        self._execute("UPDATE pending_actions SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), int(pending_id)))
        return True

    def save_facesync_run(
        self,
        session_id: int,
        table_path: str,
        name_column: str,
        reference_column: str,
        source_folder: str,
        destination_folder: str,
        report_path: str = "",
        success: bool = True,
    ) -> int:
        self._ensure_ready()
        data = {
            "session_id": int(session_id),
            "table_path": _storage_path(table_path),
            "name_column": _compact_text(name_column, 300),
            "reference_column": _compact_text(reference_column, 300),
            "source_folder": _storage_path(source_folder),
            "destination_folder": _storage_path(destination_folder),
            "report_path": _storage_path(report_path),
            "success": bool(success),
            "created_at": _now(),
        }
        if self.using_memory:
            return self._memory_insert("facesync_runs", data)
        return self._execute(
            """
            INSERT INTO facesync_runs
            (session_id, table_path, name_column, reference_column, source_folder, destination_folder, report_path, success, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["session_id"],
                data["table_path"],
                data["name_column"],
                data["reference_column"],
                data["source_folder"],
                data["destination_folder"],
                data["report_path"],
                int(data["success"]),
                data["created_at"],
            ),
        )

    def get_last_facesync_run(self, session_id: int) -> Optional[Dict[str, Any]]:
        self._ensure_ready()
        if self.using_memory:
            rows = [row for row in self._memory_table("facesync_runs") if int(row.get("session_id", 0)) == int(session_id)]
            if not rows:
                return None
            return self._facesync_run_dict(sorted(rows, key=lambda item: int(item.get("id", 0)), reverse=True)[0])
        row = self._fetchone(
            "SELECT * FROM facesync_runs WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (int(session_id),),
        )
        return self._facesync_run_dict(dict(row)) if row else None

    def save_failed_interpretation(
        self,
        session_id: int,
        user_text: str,
        system_state: Dict[str, Any],
        bad_intent: str,
        bad_args: Dict[str, Any],
        error_type: str,
        assistant_response: str = "",
    ) -> int:
        self._ensure_ready()
        data = {
            "session_id": int(session_id),
            "user_text": _compact_text(user_text),
            "system_state_json": _sanitize(system_state or {}),
            "bad_intent": _compact_text(bad_intent, 120),
            "bad_args_json": _sanitize(bad_args or {}),
            "error_type": _compact_text(error_type, 120),
            "assistant_response": _compact_text(assistant_response),
            "user_correction": "",
            "correct_intent": "",
            "correct_args_json": {},
            "status": "open",
            "created_at": _now(),
            "updated_at": _now(),
        }
        if self.using_memory:
            return self._memory_insert("failed_interpretations", data)
        return self._execute(
            """
            INSERT INTO failed_interpretations
            (session_id, user_text, system_state_json, bad_intent, bad_args_json, error_type, assistant_response,
             user_correction, correct_intent, correct_args_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["session_id"],
                data["user_text"],
                _json_dumps(data["system_state_json"]),
                data["bad_intent"],
                _json_dumps(data["bad_args_json"]),
                data["error_type"],
                data["assistant_response"],
                data["user_correction"],
                data["correct_intent"],
                _json_dumps(data["correct_args_json"]),
                data["status"],
                data["created_at"],
                data["updated_at"],
            ),
        )

    def attach_user_correction(
        self,
        failed_id: int,
        correction_text: str,
        correct_intent: str = "",
        correct_args: Optional[Dict[str, Any]] = None,
    ):
        self._ensure_ready()
        data = {
            "user_correction": _compact_text(correction_text),
            "correct_intent": _compact_text(correct_intent, 120),
            "correct_args_json": _sanitize(correct_args or {}),
            "status": "corrected",
            "updated_at": _now(),
        }
        if self.using_memory:
            row = self._memory_get("failed_interpretations", failed_id)
            if row:
                row.update(data)
            return True
        self._execute(
            """
            UPDATE failed_interpretations
            SET user_correction = ?, correct_intent = ?, correct_args_json = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                data["user_correction"],
                data["correct_intent"],
                _json_dumps(data["correct_args_json"]),
                data["status"],
                data["updated_at"],
                int(failed_id),
            ),
        )
        return True

    def create_learning_candidate(
        self,
        failed_interpretation_id: int,
        pattern: str,
        suggested_rule: str,
        suggested_test: str,
        affected_module: str,
        risk_level: str = "medium",
    ) -> int:
        self._ensure_ready()
        data = {
            "failed_interpretation_id": int(failed_interpretation_id),
            "pattern": _compact_text(pattern),
            "suggested_rule": _compact_text(suggested_rule),
            "suggested_test": _compact_text(suggested_test),
            "affected_module": _compact_text(affected_module, 200),
            "risk_level": _compact_text(risk_level, 40) or "medium",
            "status": "pending",
            "created_at": _now(),
            "updated_at": _now(),
        }
        if self.using_memory:
            return self._memory_insert("learning_candidates", data)
        return self._execute(
            """
            INSERT INTO learning_candidates
            (failed_interpretation_id, pattern, suggested_rule, suggested_test, affected_module, risk_level, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(data.values()),
        )

    def list_learning_candidates(self, status: str = "pending") -> List[Dict[str, Any]]:
        self._ensure_ready()
        status = _compact_text(status, 40)
        if self.using_memory:
            rows = self._memory_table("learning_candidates")
            if status:
                rows = [row for row in rows if row.get("status") == status]
            return [dict(row) for row in sorted(rows, key=lambda item: int(item.get("id", 0)), reverse=True)]
        if status:
            rows = self._fetchall("SELECT * FROM learning_candidates WHERE status = ? ORDER BY id DESC", (status,))
        else:
            rows = self._fetchall("SELECT * FROM learning_candidates ORDER BY id DESC", ())
        return [dict(row) for row in rows]

    def update_learning_candidate_status(self, candidate_id: int, status: str):
        self._ensure_ready()
        status = _compact_text(status, 40)
        if self.using_memory:
            row = self._memory_get("learning_candidates", candidate_id)
            if row:
                row["status"] = status
                row["updated_at"] = _now()
            return True
        self._execute("UPDATE learning_candidates SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), int(candidate_id)))
        return True

    def save_openai_usage(
        self,
        session_id: int,
        model: str,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_usd: float,
        intent: str,
        confidence: float,
        escalated: bool = False,
        escalation_reason: str = "",
    ) -> int:
        self._ensure_ready()
        data = {
            "session_id": int(session_id),
            "model": _compact_text(model, 120),
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "total_tokens": int(input_tokens or 0) + int(output_tokens or 0),
            "estimated_cost_usd": float(estimated_cost_usd or 0.0),
            "intent": _compact_text(intent, 120),
            "confidence": float(confidence or 0.0),
            "escalated": bool(escalated),
            "escalation_reason": _compact_text(escalation_reason),
            "created_at": _now(),
        }
        if self.using_memory:
            return self._memory_insert("openai_usage", data)
        return self._execute(
            """
            INSERT INTO openai_usage
            (session_id, model, input_tokens, output_tokens, total_tokens, estimated_cost_usd, intent, confidence, escalated, escalation_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["session_id"],
                data["model"],
                data["input_tokens"],
                data["output_tokens"],
                data["total_tokens"],
                data["estimated_cost_usd"],
                data["intent"],
                data["confidence"],
                int(data["escalated"]),
                data["escalation_reason"],
                data["created_at"],
            ),
        )

    def get_context_summary(self, session_id: int, project_id: int) -> Dict[str, Any]:
        self._ensure_ready()
        latest_snapshot = self._get_latest_snapshot(session_id)
        last_table = self.get_last_detected_table(project_id)
        last_run = self.get_last_facesync_run(session_id)
        recent_actions = self.get_recent_actions(session_id, limit=10)
        active_pending = self.get_active_pending_action(session_id)
        recent_user_messages = self._recent_messages(session_id, "user", 5)
        recent_assistant_messages = self._recent_messages(session_id, "assistant", 5)
        recent_errors = self._recent_errors(session_id, 5)
        learning_hints = [
            {
                "id": item.get("id"),
                "pattern": item.get("pattern"),
                "suggested_rule": item.get("suggested_rule"),
                "affected_module": item.get("affected_module"),
                "risk_level": item.get("risk_level"),
            }
            for item in self.list_learning_candidates("pending")[:5]
        ]

        action_args = self._latest_action_args(recent_actions)
        snapshot = latest_snapshot or {}
        table_path = self._first_present(
            last_table.get("file_path") if last_table else None,
            last_run.get("table_path") if last_run else None,
            snapshot.get("last_table_path"),
        )
        table_columns = (
            (last_table or {}).get("columns")
            or (self.get_table_columns(project_id, table_path) if table_path else [])
            or snapshot.get("last_table_columns")
            or snapshot.get("available_columns")
            or []
        )

        recent_intents = _clean_list(
            [action.get("intent") for action in recent_actions if action.get("intent")]
            + self._recent_message_intents(session_id, 10),
            10,
        )

        summary = {
            "conversation_summary": _compact_text(snapshot.get("conversation_summary"), 6000),
            "last_table_path": table_path or "",
            "last_table_columns": _clean_list(table_columns, 60),
            "last_name_column": self._first_present(
                last_run.get("name_column") if last_run else None,
                action_args.get("name_column"),
                action_args.get("column_name"),
                snapshot.get("last_name_column"),
            ),
            "last_reference_column": self._first_present(
                last_run.get("reference_column") if last_run else None,
                action_args.get("reference_column"),
                snapshot.get("last_reference_column"),
            ),
            "last_source_folder": self._first_present(
                last_run.get("source_folder") if last_run else None,
                action_args.get("source_folder"),
                snapshot.get("last_source_folder"),
            ),
            "last_destination_folder": self._first_present(
                last_run.get("destination_folder") if last_run else None,
                action_args.get("destination_folder"),
                snapshot.get("last_destination_folder"),
            ),
            "last_facesync_run": last_run,
            "recent_intents": recent_intents,
            "recent_user_messages": recent_user_messages,
            "recent_assistant_messages": recent_assistant_messages,
            "active_pending_action": active_pending,
            "recent_errors": recent_errors,
            "learning_hints": learning_hints,
        }
        return _sanitize(summary)

    def _db_candidates(self) -> List[Path]:
        if self.db_path:
            return [self.db_path]
        roots: List[Path] = []
        if self.user_app_data_root:
            roots.append(self.user_app_data_root)
        if self.app_data_root:
            roots.append(self.app_data_root)
        if not roots:
            roots.append(ensure_app_data_root())
        return [root.expanduser().resolve(strict=False) / "context" / DB_FILE_NAME for root in roots]

    def _activate_memory(self, exc: Optional[Exception]):
        self.initialized = True
        self.using_memory = True
        self.connection = None
        self._memory = {table: [] for table in self._table_names()}
        self._ids = {table: 0 for table in self._table_names()}
        self.last_warning = f"ContextVault SQLite no disponible; usando memoria RAM. {exc or ''}".strip()
        self.logger.warning(self.last_warning)

    def _ensure_ready(self):
        if not self.initialized:
            self.initialize()

    def _create_schema(self):
        assert self.connection is not None
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_key TEXT NOT NULL UNIQUE,
                email TEXT,
                display_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                project_root TEXT NOT NULL,
                project_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, project_root)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                intent TEXT,
                confidence REAL,
                model_used TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS context_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS detected_tables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                file_name TEXT,
                columns_json TEXT NOT NULL,
                row_count INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, file_path)
            );

            CREATE TABLE IF NOT EXISTS detected_columns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                column_name TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS action_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                intent TEXT NOT NULL,
                args_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                success INTEGER NOT NULL,
                error_type TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                intent TEXT NOT NULL,
                args_json TEXT NOT NULL,
                missing_fields_json TEXT NOT NULL,
                preview_text TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS facesync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                table_path TEXT NOT NULL,
                name_column TEXT NOT NULL,
                reference_column TEXT NOT NULL,
                source_folder TEXT NOT NULL,
                destination_folder TEXT NOT NULL,
                report_path TEXT,
                success INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS failed_interpretations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                user_text TEXT NOT NULL,
                system_state_json TEXT NOT NULL,
                bad_intent TEXT NOT NULL,
                bad_args_json TEXT NOT NULL,
                error_type TEXT NOT NULL,
                assistant_response TEXT,
                user_correction TEXT,
                correct_intent TEXT,
                correct_args_json TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS learning_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                failed_interpretation_id INTEGER NOT NULL,
                pattern TEXT NOT NULL,
                suggested_rule TEXT NOT NULL,
                suggested_test TEXT NOT NULL,
                affected_module TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS openai_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                estimated_cost_usd REAL NOT NULL,
                intent TEXT,
                confidence REAL,
                escalated INTEGER NOT NULL,
                escalation_reason TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def _execute(self, sql: str, params: tuple[Any, ...]) -> int:
        assert self.connection is not None
        cursor = self.connection.execute(sql, params)
        self.connection.commit()
        return int(cursor.lastrowid or 0)

    def _fetchone(self, sql: str, params: tuple[Any, ...]) -> Optional[sqlite3.Row]:
        assert self.connection is not None
        return self.connection.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple[Any, ...]) -> List[sqlite3.Row]:
        assert self.connection is not None
        return list(self.connection.execute(sql, params).fetchall())

    @staticmethod
    def _table_names() -> List[str]:
        return [
            "users",
            "projects",
            "sessions",
            "conversation_messages",
            "context_snapshots",
            "detected_tables",
            "detected_columns",
            "action_history",
            "pending_actions",
            "facesync_runs",
            "failed_interpretations",
            "learning_candidates",
            "openai_usage",
        ]

    def _memory_table(self, table: str) -> List[Dict[str, Any]]:
        if table not in self._memory:
            self._memory[table] = []
            self._ids[table] = 0
        return self._memory[table]

    def _memory_insert(self, table: str, data: Dict[str, Any]) -> int:
        self._ids[table] = self._ids.get(table, 0) + 1
        row = {"id": self._ids[table], **copy.deepcopy(data)}
        self._memory_table(table).append(row)
        return int(row["id"])

    def _memory_find(self, table: str, **criteria: Any) -> Optional[Dict[str, Any]]:
        for row in self._memory_table(table):
            if all(row.get(key) == value for key, value in criteria.items()):
                return row
        return None

    def _memory_get(self, table: str, row_id: int) -> Optional[Dict[str, Any]]:
        for row in self._memory_table(table):
            if int(row.get("id", 0)) == int(row_id):
                return row
        return None

    def _save_columns_memory(self, table_id: int, project_id: int, file_path: str, columns: List[str]):
        for index, column in enumerate(columns):
            self._memory_insert(
                "detected_columns",
                {
                    "table_id": int(table_id),
                    "project_id": int(project_id),
                    "file_path": file_path,
                    "column_name": column,
                    "ordinal": index,
                    "created_at": _now(),
                },
            )

    @staticmethod
    def _table_dict(row: Dict[str, Any]) -> Dict[str, Any]:
        columns = row.get("columns_json")
        if isinstance(columns, str):
            columns = _json_loads(columns, [])
        return {
            "id": row.get("id"),
            "project_id": row.get("project_id"),
            "file_path": row.get("file_path"),
            "file_name": row.get("file_name"),
            "columns": list(columns or []),
            "row_count": row.get("row_count"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    @staticmethod
    def _action_dict(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row.get("id"),
            "session_id": row.get("session_id"),
            "intent": row.get("intent"),
            "args": _json_loads(row.get("args_json"), {}) if isinstance(row.get("args_json"), str) else row.get("args_json", {}),
            "result": _json_loads(row.get("result_json"), {}) if isinstance(row.get("result_json"), str) else row.get("result_json", {}),
            "success": bool(row.get("success")),
            "error_type": row.get("error_type") or "",
            "error_message": row.get("error_message") or "",
            "created_at": row.get("created_at"),
        }

    @staticmethod
    def _pending_dict(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row.get("id"),
            "session_id": row.get("session_id"),
            "intent": row.get("intent"),
            "args": _json_loads(row.get("args_json"), {}) if isinstance(row.get("args_json"), str) else row.get("args_json", {}),
            "missing_fields": (
                _json_loads(row.get("missing_fields_json"), [])
                if isinstance(row.get("missing_fields_json"), str)
                else row.get("missing_fields_json", [])
            ),
            "preview_text": row.get("preview_text") or "",
            "status": row.get("status"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    @staticmethod
    def _facesync_run_dict(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row.get("id"),
            "session_id": row.get("session_id"),
            "table_path": row.get("table_path"),
            "name_column": row.get("name_column"),
            "reference_column": row.get("reference_column"),
            "source_folder": row.get("source_folder"),
            "destination_folder": row.get("destination_folder"),
            "report_path": row.get("report_path") or "",
            "success": bool(row.get("success")),
            "created_at": row.get("created_at"),
        }

    def _get_latest_snapshot(self, session_id: int) -> Dict[str, Any]:
        if self.using_memory:
            rows = [row for row in self._memory_table("context_snapshots") if int(row.get("session_id", 0)) == int(session_id)]
            if not rows:
                return {}
            row = sorted(rows, key=lambda item: int(item.get("id", 0)), reverse=True)[0]
            return dict(row.get("snapshot_json") or {})
        row = self._fetchone(
            "SELECT snapshot_json FROM context_snapshots WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (int(session_id),),
        )
        return _json_loads(row["snapshot_json"], {}) if row else {}

    def _recent_messages(self, session_id: int, role: str, limit: int) -> List[str]:
        if self.using_memory:
            rows = [
                row
                for row in self._memory_table("conversation_messages")
                if int(row.get("session_id", 0)) == int(session_id) and row.get("role") == role
            ]
            rows = sorted(rows, key=lambda item: int(item.get("id", 0)), reverse=True)[:limit]
            return [_compact_text(row.get("message"), 500) for row in reversed(rows)]
        rows = self._fetchall(
            "SELECT message FROM conversation_messages WHERE session_id = ? AND role = ? ORDER BY id DESC LIMIT ?",
            (int(session_id), role, int(limit)),
        )
        return [_compact_text(row["message"], 500) for row in reversed(rows)]

    def _recent_message_intents(self, session_id: int, limit: int) -> List[str]:
        if self.using_memory:
            rows = [
                row
                for row in self._memory_table("conversation_messages")
                if int(row.get("session_id", 0)) == int(session_id) and row.get("intent")
            ]
            rows = sorted(rows, key=lambda item: int(item.get("id", 0)), reverse=True)[:limit]
            return [str(row.get("intent")) for row in rows]
        rows = self._fetchall(
            "SELECT intent FROM conversation_messages WHERE session_id = ? AND intent != '' ORDER BY id DESC LIMIT ?",
            (int(session_id), int(limit)),
        )
        return [str(row["intent"]) for row in rows if row["intent"]]

    def _recent_errors(self, session_id: int, limit: int) -> List[Dict[str, Any]]:
        errors: List[Dict[str, Any]] = []
        if self.using_memory:
            action_rows = [
                row
                for row in self._memory_table("action_history")
                if int(row.get("session_id", 0)) == int(session_id) and not bool(row.get("success"))
            ]
            failed_rows = [
                row
                for row in self._memory_table("failed_interpretations")
                if int(row.get("session_id", 0)) == int(session_id)
            ]
        else:
            action_rows = [dict(row) for row in self._fetchall(
                "SELECT * FROM action_history WHERE session_id = ? AND success = 0 ORDER BY id DESC LIMIT ?",
                (int(session_id), int(limit)),
            )]
            failed_rows = [dict(row) for row in self._fetchall(
                "SELECT * FROM failed_interpretations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (int(session_id), int(limit)),
            )]
        for row in action_rows[:limit]:
            errors.append(
                {
                    "source": "action_history",
                    "intent": row.get("intent"),
                    "error_type": row.get("error_type") or "",
                    "error_message": row.get("error_message") or "",
                    "created_at": row.get("created_at"),
                }
            )
        for row in failed_rows[:limit]:
            errors.append(
                {
                    "source": "failed_interpretations",
                    "intent": row.get("bad_intent"),
                    "error_type": row.get("error_type") or "",
                    "user_text": row.get("user_text") or "",
                    "created_at": row.get("created_at"),
                }
            )
        return errors[:limit]

    @staticmethod
    def _latest_action_args(recent_actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        for action in recent_actions:
            args = action.get("args")
            if isinstance(args, dict) and args:
                return args
        return {}

    @staticmethod
    def _first_present(*values: Any) -> str:
        for value in values:
            if value not in (None, "", [], {}):
                return str(value)
        return ""


__all__ = ["ContextVault", "DB_FILE_NAME"]
