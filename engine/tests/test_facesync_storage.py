from __future__ import annotations

import sqlite3
import json
import shutil
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from core.facesync_storage import (
    SQLITE_STORAGE_SCHEMA,
    SQLiteFaceSyncStore,
    SQLiteIdentityRegistry,
    account_storage_key,
)
from core.identity_registry import IdentityRegistry


def _protect(value: str) -> str:
    return "TESTSQL1:" + value


def _unprotect(value: str) -> str:
    if not value.startswith("TESTSQL1:"):
        raise ValueError("payload sin cifrado de prueba")
    return value[len("TESTSQL1:"):]


def _record(*, student="ANA", salon="501M", code="2411", vector=None):
    vector = vector or [1.0, 0.0, 0.0]
    return {
        "student": student,
        "salon": salon,
        "code": code,
        "table_path": f"{salon}.xlsx",
        "reference_path": f"IMG_{code}.JPG",
        "embeddings": [vector, [vector[0], vector[1] + 0.01, vector[2]]],
        "model_name": "ArcFace",
        "embedding_schema": 2,
        "support_count": 5,
    }


def _cr3_record(
    *,
    student="ANA",
    salon="501M",
    code="2411",
    vector=None,
    representation="preview",
):
    record = _record(
        student=student,
        salon=salon,
        code=code,
        vector=vector,
    )
    record.update({
        "reference_path": f"IMG_{code}.CR3",
        "format_family": "cr3",
        "representation": representation,
        "processing_version": (
            "cr3_fullraw_v1" if representation == "fullraw" else "cr3_preview_v1"
        ),
    })
    return record


class FaceSyncSQLiteStorageTests(unittest.TestCase):
    def _store(self, root: Path, account: str, **kwargs):
        return SQLiteFaceSyncStore(
            root,
            account,
            protector=_protect,
            unprotector=_unprotect,
            **kwargs,
        )

    def test_cache_and_identities_are_isolated_per_account(self):
        with tempfile.TemporaryDirectory(prefix="facesync_sqlite_isolation_") as tmp:
            root = Path(tmp)
            store_a = self._store(root, "a@example.com")
            store_b = self._store(root, "b@example.com")
            key = ("C:/Fotos/IMG_1.JPG", 123, 456.0, "ArcFace", 2)
            faces = [{"embedding": [1.0, 0.0], "face_confidence": 0.99}]

            store_a.save_cached_faces(key, faces)
            store_a.flush_cache()
            result = store_a.register_identities([_record()], run_id="run-a")

            self.assertTrue(result["success"])
            self.assertEqual(store_a.load_cached_faces(key), faces)
            self.assertIsNone(store_b.load_cached_faces(key))
            self.assertEqual(len(store_a.active_identity_records()), 1)
            self.assertEqual(store_b.active_identity_records(), [])
            self.assertNotEqual(store_a.db_path, store_b.db_path)
            self.assertNotIn("a@example.com", str(store_a.db_path))
            with closing(sqlite3.connect(root / "context" / "accounts.db")) as db:
                accounts = db.execute(
                    "SELECT protected_account FROM accounts ORDER BY account_key"
                ).fetchall()
            self.assertEqual(len(accounts), 2)
            self.assertTrue(all(row[0].startswith("TESTSQL1:") for row in accounts))
            store_a.close()
            store_b.close()

    def test_cache_survives_reopen_and_payload_is_not_plaintext(self):
        with tempfile.TemporaryDirectory(prefix="facesync_sqlite_cache_") as tmp:
            root = Path(tmp)
            key = ("C:/Fotos/IMG_2.CR2", 999, 100.25, "ArcFace", 2)
            faces = [{"embedding": [0.1, 0.2, 0.3], "face_confidence": 0.95}]
            store = self._store(root, "cache@example.com")
            db_path = store.db_path
            store.save_cached_faces(key, faces)
            store.close()

            with closing(sqlite3.connect(db_path)) as db:
                protected = db.execute(
                    "SELECT protected_payload FROM embedding_cache"
                ).fetchone()[0]
            self.assertTrue(protected.startswith("TESTSQL1:"))
            self.assertNotIn("0.1", protected[:20])

            reopened = self._store(root, "cache@example.com")
            self.assertEqual(reopened.load_cached_faces(key), faces)
            reopened.close()

    def test_registry_adapter_preserves_historical_and_supersession_flow(self):
        with tempfile.TemporaryDirectory(prefix="facesync_sqlite_registry_") as tmp:
            root = Path(tmp)
            store = self._store(root, "owner@example.com")
            registry = SQLiteIdentityRegistry(store)
            registry.register_many([_record()], run_id="run-501")

            history = registry.find_historical(
                "2411",
                current_student="ROMAN",
                current_salon="502M",
                model_name="ArcFace",
                embedding_schema=2,
            )
            same_scope = registry.find_historical(
                "2411",
                current_student="ANA",
                current_salon="501M",
                model_name="ArcFace",
                embedding_schema=2,
            )
            rerun = registry.register_many(
                [_record(vector=[0.99, 0.01, 0.0])],
                run_id="run-501-rerun",
            )

            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["student"], "ANA")
            self.assertEqual(same_scope, [])
            self.assertEqual(rerun["superseded"], 1)
            self.assertEqual(len(registry.active_records()), 1)

            registry.register_many(
                [_record(student="BEA", salon="502M", vector=[0.0, 1.0, 0.0])],
                run_id="run-502",
            )
            third_room_history = registry.find_historical(
                "2411",
                current_student="CARLA",
                current_salon="503M",
                model_name="ArcFace",
                embedding_schema=2,
            )
            self.assertEqual(
                {item["salon"] for item in third_room_history},
                {"501M", "502M"},
            )
            store.close()

    def test_legacy_registry_is_claimed_and_imported_only_once(self):
        with tempfile.TemporaryDirectory(prefix="facesync_sqlite_migration_") as tmp:
            root = Path(tmp)
            legacy_path = root / "context" / "identity_registry.json"
            legacy_path.parent.mkdir(parents=True)
            legacy = IdentityRegistry(
                legacy_path,
                protector=_protect,
                unprotector=_unprotect,
            )
            legacy.register_many([_record()], run_id="legacy-run")

            first = self._store(
                root,
                "first@example.com",
                legacy_identity_path=legacy_path,
            )
            second = self._store(
                root,
                "second@example.com",
                legacy_identity_path=legacy_path,
            )

            self.assertTrue(first.legacy_cache_allowed)
            self.assertFalse(second.legacy_cache_allowed)
            self.assertEqual(len(first.active_identity_records()), 1)
            self.assertEqual(second.active_identity_records(), [])
            self.assertTrue(legacy_path.is_file())
            first.close()
            second.close()

    def test_run_ledger_marks_completed_and_failed_without_plain_context(self):
        with tempfile.TemporaryDirectory(prefix="facesync_sqlite_runs_") as tmp:
            root = Path(tmp)
            store = self._store(root, "runs@example.com")
            store.start_run(
                "run-1",
                model_name="ArcFace",
                embedding_schema=2,
                context={"table_path": "C:/privado/501M.xlsx"},
            )
            store.finish_run(
                "run-1",
                status="completed",
                summary={"classified": 100},
            )
            row = store._db.execute(
                "SELECT status, protected_context, protected_summary FROM classification_runs"
            ).fetchone()

            self.assertEqual(row["status"], "completed")
            self.assertTrue(row["protected_context"].startswith("TESTSQL1:"))
            self.assertTrue(row["protected_summary"].startswith("TESTSQL1:"))
            self.assertNotIn("privado", row["protected_context"][:20])
            store.close()

    def test_schema_v1_expands_to_v2_without_rewriting_existing_identity(self):
        with tempfile.TemporaryDirectory(prefix="facesync_sqlite_v2_migration_") as tmp:
            root = Path(tmp)
            account = "migration@example.com"
            db_path = (
                root / "context" / "accounts" / account_storage_key(account)
                / "facesync.db"
            )
            db_path.parent.mkdir(parents=True)
            legacy = _record()
            with closing(sqlite3.connect(db_path)) as db:
                db.executescript(
                    """
                    CREATE TABLE identity_records (
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
                    PRAGMA user_version=1;
                    """
                )
                db.execute(
                    """
                    INSERT INTO identity_records VALUES (
                        'legacy-1', '2411', 'student-hash', 'salon-hash',
                        'ArcFace', 2, 'active', 'legacy-run', ?,
                        '2026-01-01T00:00:00+00:00', '', ''
                    )
                    """,
                    (_protect(json.dumps(legacy)),),
                )
                db.commit()

            store = self._store(root, account)
            self.assertEqual(
                store._db.execute("PRAGMA user_version").fetchone()[0],
                SQLITE_STORAGE_SCHEMA,
            )
            self.assertEqual(store.active_identity_records()[0]["student"], "ANA")
            route_table = store._db.execute(
                "SELECT name FROM sqlite_master WHERE name='identity_route_records'"
            ).fetchone()
            self.assertIsNotNone(route_table)
            store.close()

            # Reopening proves the additive migration is idempotent.
            reopened = self._store(root, account)
            self.assertEqual(len(reopened.active_identity_records()), 1)
            reopened.close()

    def test_cr3_routes_coexist_and_only_same_route_is_superseded(self):
        with tempfile.TemporaryDirectory(prefix="facesync_sqlite_routes_") as tmp:
            store = self._store(Path(tmp), "routes@example.com")
            registry = SQLiteIdentityRegistry(store)
            first = registry.register_many(
                [_cr3_record(), _cr3_record(representation="fullraw")],
                run_id="run-1",
            )
            rerun = registry.register_many(
                [_cr3_record(vector=[0.99, 0.01, 0.0])],
                run_id="run-2",
            )

            active = registry.active_records()
            self.assertEqual(first["registered"], 2)
            self.assertEqual(rerun["superseded"], 1)
            self.assertEqual(len(active), 2)
            self.assertEqual(
                {record["representation"] for record in active},
                {"preview", "fullraw"},
            )
            self.assertEqual(
                store._db.execute(
                    "SELECT COUNT(*) FROM identity_records"
                ).fetchone()[0],
                0,
            )
            store.close()

    def test_cr3_same_code_is_available_in_second_and_third_room_by_route(self):
        with tempfile.TemporaryDirectory(prefix="facesync_sqlite_three_rooms_") as tmp:
            store = self._store(Path(tmp), "owner@example.com")
            registry = SQLiteIdentityRegistry(store)
            registry.register_many(
                [
                    _cr3_record(student="ANA", salon="501M"),
                    _cr3_record(
                        student="ANA", salon="501M", representation="fullraw"
                    ),
                ],
                run_id="run-501",
            )
            second_history = registry.find_historical(
                "2411",
                current_student="BEA",
                current_salon="502M",
                model_name="ArcFace",
                embedding_schema=2,
            )
            registry.register_many(
                [
                    _cr3_record(
                        student="BEA", salon="502M", vector=[0.0, 1.0, 0.0]
                    ),
                    _cr3_record(
                        student="BEA",
                        salon="502M",
                        vector=[0.0, 1.0, 0.0],
                        representation="fullraw",
                    ),
                ],
                run_id="run-502",
            )
            third_history = registry.find_historical(
                "2411",
                current_student="CARLA",
                current_salon="503M",
                model_name="ArcFace",
                embedding_schema=2,
            )

            self.assertEqual(len(second_history), 2)
            self.assertEqual(len(third_history), 4)
            self.assertEqual(
                {(item["student"], item["representation"]) for item in third_history},
                {
                    ("ANA", "preview"),
                    ("ANA", "fullraw"),
                    ("BEA", "preview"),
                    ("BEA", "fullraw"),
                },
            )
            store.close()

    def test_cache_cleanup_preserves_route_history_and_reopen_session(self):
        with tempfile.TemporaryDirectory(prefix="facesync_sqlite_cache_cleanup_") as tmp:
            root = Path(tmp)
            account = "session@example.com"
            store = self._store(root, account)
            key = ("C:/Fotos/IMG_1.CR3", 123, 456.0, "ArcFace:cr3_preview_v1", 2)
            store.save_cached_faces(
                key,
                [{"embedding": [1.0, 0.0], "face_confidence": 0.99}],
            )
            SQLiteIdentityRegistry(store).register_many(
                [_cr3_record()], run_id="run-501"
            )
            conversion_marker = store.cr3_preview_cache_dir / "preview.jpg"
            conversion_marker.write_bytes(b"cache")

            self.assertGreater(store.cache_count(), 0)
            self.assertGreater(store.clear_embedding_cache(), 0)
            self.assertEqual(store.cache_count(), 0)
            shutil.rmtree(store.cache_root)
            self.assertFalse(conversion_marker.exists())
            self.assertEqual(len(store.active_identity_records()), 1)
            store.close()

            reopened = self._store(root, account)
            other = self._store(root, "other@example.com")
            self.assertEqual(len(reopened.active_identity_records()), 1)
            self.assertEqual(other.active_identity_records(), [])
            reopened.close()
            other.close()


if __name__ == "__main__":
    unittest.main()
