import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.cr3_evaluator import (
    evaluate_report_assignments,
    load_manifest,
    measure_cr3_manifest,
)


class FakeMotor:
    CR3_FULLRAW_CACHE_VARIANT = "cr3_fullraw_v1"

    def __init__(self, preview: Path, fullraw: Path, route_vectors=None):
        self.preview = preview
        self.fullraw = fullraw
        self.route_vectors = route_vectors or {}

    def _cr2_to_jpeg(self, _path):
        return self.preview, "converted"

    def _cr3_fullraw_to_jpeg(self, _path):
        return self.fullraw, "converted"

    def _get_all_face_embeddings(self, image_path, **kwargs):
        route = "fullraw" if kwargs.get("cache_variant") else "preview"
        vector = self.route_vectors.get(route, {}).get(image_path.name)
        if vector is None:
            vector = [1.0, 0.0] if image_path.name == "A.cr3" else [0.0, 1.0]
        return [{
            "embedding": vector,
            "face_confidence": 0.99,
            "facial_area": {"x": 10, "y": 20, "w": 40, "h": 50},
        }]

    @staticmethod
    def _cosine_distance(left, right):
        dot = sum(a * b for a, b in zip(left, right))
        norm_left = math.sqrt(sum(value * value for value in left))
        norm_right = math.sqrt(sum(value * value for value in right))
        return 1.0 - dot / (norm_left * norm_right)


class Cr3EvaluatorTests(unittest.TestCase):
    def test_manifest_rejects_contradictory_no_target(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "identities": [{"id": "A"}],
                "photos": [{
                    "file": "A.cr3",
                    "target_identities": ["A"],
                    "companion_identities": [],
                    "no_target": True,
                }],
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manifest(path)

    def test_report_evaluation_lists_false_negatives_and_ignores_control_copy(self):
        manifest = {
            "identities": [{"id": "A"}],
            "photos": [
                {"file": "A.cr3", "target_identities": ["A"]},
                {"file": "B.cr3", "target_identities": ["A"]},
                {"file": "N.cr3", "target_identities": []},
            ],
        }
        report = {"fotos_por_persona": {"A": ["X/A.cr3", "X/_CONTROL.cr3"]}}
        result = evaluate_report_assignments(manifest, report, "run")
        overall = result["metrics"]["overall"]
        self.assertEqual(overall["correct_photos"], 1)
        self.assertEqual(overall["target_photos"], 2)
        self.assertEqual(overall["recall"], 0.5)
        self.assertEqual(result["metrics"]["errors"][0]["file"], "B.cr3")
        self.assertEqual(result["unknown_deliveries"][0]["file"], "_CONTROL.cr3")

    def test_measurement_keeps_embeddings_out_of_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            photos = []
            for name, targets in (("A.cr3", ["A"]), ("N.cr3", [])):
                path = root / name
                path.write_bytes(name.encode("ascii"))
                photos.append({
                    "file": name,
                    "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                    "target_identities": targets,
                    "companion_identities": [],
                    "no_target": not bool(targets),
                })
            preview = root / "preview.jpg"
            fullraw = root / "fullraw.jpg"
            Image.new("RGB", (100, 200), "white").save(preview)
            Image.new("RGB", (100, 200), "gray").save(fullraw)
            manifest = {
                "schema_version": 1,
                "model_name": "ArcFace",
                "detector_backend": "retinaface",
                "identities": [{
                    "id": "A",
                    "natural_reference": "A.cr3",
                    "control_reference": None,
                }],
                "photos": photos,
            }
            result = measure_cr3_manifest(FakeMotor(preview, fullraw), manifest, root, object())
            serialized = json.dumps(result)
            self.assertNotIn('"embedding"', serialized)
            self.assertEqual(result["summaries"]["preview"]["decoded"], 2)
            face = result["photos"][0]["routes"]["preview"]["faces"][0]
            self.assertEqual(face["min_side_pixels"], 40.0)
            self.assertEqual(face["normalized_area"]["w"], 0.4)
            self.assertNotIn("representation_analysis", result)

    def test_representation_analysis_builds_separate_true_false_and_cross_matrices(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            definitions = (
                ("A1.cr3", ["A"], "A_SERIES"),
                ("A2.cr3", ["A"], "A_SERIES"),
                ("B.cr3", ["B"], "B_SERIES"),
                ("N.cr3", [], "CONTROL"),
            )
            photos = []
            for name, targets, sequence in definitions:
                path = root / name
                path.write_bytes(name.encode("ascii"))
                photos.append({
                    "file": name,
                    "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                    "target_identities": targets,
                    "companion_identities": [],
                    "no_target": not bool(targets),
                    "scene": "retrato_individual",
                    "sequence": sequence,
                })
            preview = root / "preview.jpg"
            fullraw = root / "fullraw.jpg"
            Image.new("RGB", (120, 200), "white").save(preview)
            Image.new("RGB", (120, 200), "gray").save(fullraw)
            vectors = {
                "preview": {
                    "A1.cr3": [1.0, 0.0, 0.0],
                    "A2.cr3": [0.99, 0.1, 0.0],
                    "B.cr3": [0.0, 1.0, 0.0],
                    "N.cr3": [0.0, 0.0, 1.0],
                },
                "fullraw": {
                    "A1.cr3": [1.0, 0.0, 0.0],
                    "A2.cr3": [0.98, 0.2, 0.0],
                    "B.cr3": [0.0, 1.0, 0.0],
                    "N.cr3": [0.0, 0.0, 1.0],
                },
            }
            manifest = {
                "schema_version": 1,
                "model_name": "ArcFace",
                "detector_backend": "retinaface",
                "identities": [
                    {"id": "A", "natural_reference": "A1.cr3", "control_reference": None},
                    {"id": "B", "natural_reference": "B.cr3", "control_reference": None},
                ],
                "photos": photos,
            }
            result = measure_cr3_manifest(
                FakeMotor(preview, fullraw, vectors),
                manifest,
                root,
                object(),
                include_representation_analysis=True,
            )
            serialized = json.dumps(result)
            self.assertNotIn('"embedding"', serialized)
            analysis = result["representation_analysis"]
            preview_data = analysis["within_route"]["preview"]
            self.assertEqual(len(preview_data["distance_matrix"]), 4)
            self.assertEqual(preview_data["summary"]["distributions"]["same_identity"]["count"], 1)
            self.assertEqual(preview_data["summary"]["distributions"]["different_identity"]["count"], 2)
            self.assertEqual(preview_data["summary"]["distributions"]["no_target_control"]["count"], 3)
            self.assertEqual(len(analysis["cross_route"]["distance_matrix"]), 4)
            self.assertEqual(len(analysis["cross_route"]["corresponding_photos"]), 4)
            sequence = next(
                item for item in analysis["sequence_comparison"]
                if item["sequence"] == "A_SERIES"
            )
            self.assertEqual(sequence["preview"]["count"], 1)
            self.assertEqual(sequence["fullraw"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
