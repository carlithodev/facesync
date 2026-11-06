from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.identity_registry import IdentityRegistry, normalize_reference_code


def _protect(value: str) -> str:
    return "TEST1:" + value


def _unprotect(value: str) -> str:
    if not value.startswith("TEST1:"):
        raise ValueError("payload sin cifrado de prueba")
    return value[len("TEST1:"):]


class IdentityRegistryTests(unittest.TestCase):
    @staticmethod
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

    def test_registers_and_finds_only_other_identity_scopes(self):
        with tempfile.TemporaryDirectory(prefix="facesync_identity_registry_") as tmp:
            path = Path(tmp) / "identity_registry.json"
            registry = IdentityRegistry(path, protector=_protect, unprotector=_unprotect)
            result = registry.register_many([self._record()], run_id="run-1")

            self.assertTrue(result["success"])
            self.assertEqual(result["registered"], 1)
            self.assertTrue(path.read_text(encoding="utf-8").startswith("TEST1:"))

            other_room = registry.find_historical(
                "IMG_2411.JPG",
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
            wrong_model = registry.find_historical(
                "2411",
                current_student="ROMAN",
                current_salon="502M",
                model_name="OtherModel",
                embedding_schema=2,
            )

            self.assertEqual(len(other_room), 1)
            self.assertEqual(same_scope, [])
            self.assertEqual(wrong_model, [])

    def test_rerun_supersedes_instead_of_deleting_history(self):
        with tempfile.TemporaryDirectory(prefix="facesync_identity_supersede_") as tmp:
            path = Path(tmp) / "identity_registry.json"
            registry = IdentityRegistry(path, protector=_protect, unprotector=_unprotect)
            registry.register_many([self._record()], run_id="run-1")
            result = registry.register_many([self._record(vector=[0.99, 0.01, 0.0])], run_id="run-2")

            self.assertTrue(result["success"])
            self.assertEqual(result["superseded"], 1)
            self.assertEqual(len(registry.active_records()), 1)
            self.assertEqual(len(registry.load()["records"]), 2)
            self.assertEqual(registry.load()["records"][0]["status"], "superseded")

    def test_corrupt_registry_is_read_only_and_never_overwritten(self):
        with tempfile.TemporaryDirectory(prefix="facesync_identity_corrupt_") as tmp:
            path = Path(tmp) / "identity_registry.json"
            path.write_text("contenido corrupto", encoding="utf-8")
            registry = IdentityRegistry(path, protector=_protect, unprotector=_unprotect)

            self.assertEqual(registry.active_records(), [])
            result = registry.register_many([self._record()], run_id="run-1")

            self.assertFalse(result["success"])
            self.assertTrue(registry.read_only)
            self.assertEqual(path.read_text(encoding="utf-8"), "contenido corrupto")

    def test_normalizes_numeric_reference_to_final_code(self):
        self.assertEqual(normalize_reference_code("IMG_002411.JPG"), "2411")
        self.assertEqual(normalize_reference_code("2411.0"), "2411")

    def test_fallback_registry_keeps_cr3_preview_and_fullraw_active(self):
        with tempfile.TemporaryDirectory(prefix="facesync_identity_routes_") as tmp:
            registry = IdentityRegistry(
                Path(tmp) / "identity_registry.json",
                protector=_protect,
                unprotector=_unprotect,
            )
            preview = self._record()
            preview.update({
                "format_family": "cr3",
                "representation": "preview",
                "processing_version": "cr3_preview_v1",
            })
            fullraw = self._record()
            fullraw.update({
                "format_family": "cr3",
                "representation": "fullraw",
                "processing_version": "cr3_fullraw_v1",
            })

            result = registry.register_many([preview, fullraw], run_id="run-cr3")

            self.assertEqual(result["registered"], 2)
            self.assertEqual(result["superseded"], 0)
            self.assertEqual(len(registry.active_records()), 2)
            self.assertEqual(
                {item["representation"] for item in result["records"]},
                {"preview", "fullraw"},
            )


if __name__ == "__main__":
    unittest.main()
