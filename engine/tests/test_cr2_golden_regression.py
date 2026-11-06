import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("run_cr2_golden_regression.py")
SPEC = importlib.util.spec_from_file_location("cr2_golden_regression", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class Cr2GoldenRegressionTests(unittest.TestCase):
    def test_assignment_snapshot_is_stable_and_ignores_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "ALUMNO").mkdir()
            (root / "ALUMNO" / "IMG_1.CR2").write_bytes(b"raw")
            (root / "_reporte_facesync.json").write_text("{}", encoding="utf-8")
            first = MODULE.assignment_snapshot(root)
            (root / "_reporte_facesync.txt").write_text("cambio", encoding="utf-8")
            second = MODULE.assignment_snapshot(root)
            self.assertEqual(first, second)
            self.assertEqual(first["assignment_count"], 1)
            self.assertEqual(first["by_extension"], {".CR2": 1})

    def test_report_snapshot_projects_only_golden_metrics(self):
        report = {
            "success": True,
            "total_personas": 1,
            "referencias_faltantes": [],
            "referencias_ambiguas": [],
            "fotos_ignoradas_no_asignadas": [],
            "conflictos_identidad": [],
            "errores_imagen": [],
            "cr2_metrics": {"cr2_detectadas": 2, "cr2_errores": 0, "cr3_detectadas": 0},
            "cr3_dual_decode": {"enabled": False, "fullraw_processed": 0},
            "performance_stats": {"backend": "onnx_directml"},
            "cache_metrics": {"cache_hit_percent": 0.0},
            "tiempo_total": 999,
        }
        snapshot = MODULE.report_snapshot(report)
        self.assertNotIn("tiempo_total", snapshot)
        self.assertEqual(snapshot["cr2_detectadas"], 2)
        self.assertFalse(snapshot["cr3_fullraw_enabled"])

    def test_compare_mapping_reports_exact_difference(self):
        failures = MODULE.compare_mapping("reporte", {"copiadas": 10}, {"copiadas": 9})
        self.assertEqual(len(failures), 1)
        self.assertIn("esperado=10", failures[0])


if __name__ == "__main__":
    unittest.main()
