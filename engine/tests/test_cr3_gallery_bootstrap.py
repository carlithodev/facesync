from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.cr3_gallery_bootstrap import build_cr3_gallery_bootstrap


def face(value: float, confidence: float = 0.99, side: float | None = None):
    result = {"embedding": [value], "face_confidence": confidence}
    if side is not None:
        result["facial_area"] = {"x": 0, "y": 0, "w": side, "h": side}
    return result


def distance(left, right) -> float:
    return abs(float(left[0]) - float(right[0]))


class CR3GalleryBootstrapTests(unittest.TestCase):
    def _run(self, root: Path, values, *, second_gallery=None, extension=".CR3"):
        a_root = root / f"A_ROOT{extension}"
        b_root = root / f"B_ROOT{extension}"
        references = [
            {
                "path": a_root,
                "embedding": [0.0],
                "person": {"folder_name": "A", "display_name": "ALUMNA A"},
            },
            {
                "path": b_root,
                "embedding": [1.0],
                "person": {"folder_name": "B", "display_name": "ALUMNA B"},
            },
        ]
        faces = {
            root / f"PHOTO_{index}{extension}": [face(value, confidence)]
            for index, (value, confidence) in enumerate(values)
        }
        galleries = {
            "A": {
                "embeddings": [[0.0]],
                "paths": [a_root],
                "reference_trusted": True,
            },
            "B": second_gallery
            or {
                "embeddings": [[1.0], [0.90], [0.92]],
                "paths": [b_root, root / "B1.CR3", root / "B2.CR3"],
                "reference_trusted": True,
            },
        }
        return build_cr3_gallery_bootstrap(
            references,
            faces,
            galleries,
            route="fullraw",
            cosine_distance=distance,
            secure_threshold=0.28,
            review_threshold=0.40,
            identity_margin=0.05,
            min_support=2,
            max_anchors=15,
            duplicate_threshold=0.05,
            candidate_limit=30,
        )

    def test_coherent_separated_group_feeds_gallery_and_is_reevaluated(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_bootstrap_") as tmp:
            proposals, diagnostics, stats = self._run(
                Path(tmp), [(0.44, 0.99), (0.50, 0.99)]
            )

        self.assertIn("A", proposals)
        self.assertEqual(len(proposals["A"]["anchors"]), 2)
        self.assertEqual(len(proposals["A"]["decisions"]), 2)
        self.assertEqual(stats["accepted_identities"], 1)
        detail = next(item for item in diagnostics if item["persona"] == "ALUMNA A")
        self.assertEqual(detail["estado"], "aceptada")
        self.assertEqual(detail["soporte_fotos"], 2)
        self.assertNotIn("embedding", str(detail).lower())

    def test_isolated_candidate_cannot_teach_gallery(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_isolated_") as tmp:
            proposals, diagnostics, _stats = self._run(
                Path(tmp), [(0.44, 0.99)]
            )

        self.assertNotIn("A", proposals)
        detail = next(item for item in diagnostics if item["persona"] == "ALUMNA A")
        self.assertEqual(detail["estado"], "bloqueada")

    def test_confidence_zero_fallback_cannot_be_an_anchor(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_fallback_") as tmp:
            proposals, _diagnostics, stats = self._run(
                Path(tmp), [(0.44, 0.99), (0.50, 0.0)]
            )

        self.assertNotIn("A", proposals)
        self.assertEqual(stats["real_faces"], 1)

    def test_group_owned_by_other_identity_is_blocked(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_owned_") as tmp:
            root = Path(tmp)
            other_gallery = {
                "embeddings": [[1.0], [0.46], [0.50]],
                "paths": [root / "B_ROOT.CR3", root / "B1.CR3", root / "B2.CR3"],
                "reference_trusted": True,
            }
            proposals, _diagnostics, _stats = self._run(
                root,
                [(0.44, 0.99), (0.50, 0.99)],
                second_gallery=other_gallery,
            )

        self.assertNotIn("A", proposals)

    def test_weakly_connected_companion_group_is_blocked(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_companion_") as tmp:
            proposals, _diagnostics, _stats = self._run(
                Path(tmp), [(0.70, 0.99), (0.74, 0.99)]
            )

        self.assertNotIn("A", proposals)

    def test_scale_incompatible_lookalike_cannot_feed_or_rejoin(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_scale_guard_") as tmp:
            root = Path(tmp)
            a_root = root / "A_ROOT.CR3"
            b_root = root / "B_ROOT.CR3"
            references = [
                {
                    "path": a_root,
                    "embedding": [0.0],
                    "candidate_faces": [face(0.0, side=100)],
                    "person": {"folder_name": "A", "display_name": "ALUMNA A"},
                },
                {
                    "path": b_root,
                    "embedding": [1.0],
                    "candidate_faces": [face(1.0, side=100)],
                    "person": {"folder_name": "B", "display_name": "ALUMNA B"},
                },
            ]
            galleries = {
                "A": {"embeddings": [[0.0]], "paths": [a_root], "reference_trusted": True},
                "B": {
                    "embeddings": [[1.0], [0.90], [0.92]],
                    "paths": [b_root, root / "B1.CR3", root / "B2.CR3"],
                    "reference_trusted": True,
                },
            }
            proposals, _diagnostics, _stats = build_cr3_gallery_bootstrap(
                references,
                {
                    root / "A1.CR3": [face(0.44, side=100)],
                    root / "A2.CR3": [face(0.50, side=115)],
                    root / "OBJECT.CR3": [face(0.46, side=220)],
                },
                galleries,
                route="fullraw",
                cosine_distance=distance,
                secure_threshold=0.28,
                review_threshold=0.40,
                identity_margin=0.05,
                min_support=2,
                max_anchors=15,
                duplicate_threshold=0.05,
                candidate_limit=30,
            )

        self.assertIn("A", proposals)
        self.assertEqual(len(proposals["A"]["anchors"]), 2)
        decision_names = {item["path"].name for item in proposals["A"]["decisions"]}
        self.assertEqual(decision_names, {"A1.CR3", "A2.CR3"})

    def test_multiple_faces_from_one_photo_do_not_count_as_multiple_evidence(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_one_photo_") as tmp:
            root = Path(tmp)
            a_root = root / "A_ROOT.CR3"
            references = [{
                "path": a_root,
                "embedding": [0.0],
                "person": {"folder_name": "A", "display_name": "ALUMNA A"},
            }]
            proposals, _diagnostics, _stats = build_cr3_gallery_bootstrap(
                references,
                {root / "GROUP.CR3": [face(0.44), face(0.50)]},
                {"A": {
                    "embeddings": [[0.0]],
                    "paths": [a_root],
                    "reference_trusted": True,
                }},
                route="preview",
                cosine_distance=distance,
                secure_threshold=0.28,
                review_threshold=0.40,
                identity_margin=0.05,
                min_support=2,
                max_anchors=15,
                duplicate_threshold=0.05,
                candidate_limit=30,
            )

        self.assertEqual(proposals, {})

    def test_non_cr3_references_are_an_exact_noop(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_guard_") as tmp:
            proposals, diagnostics, stats = self._run(
                Path(tmp),
                [(0.44, 0.99), (0.50, 0.99)],
                extension=".CR2",
            )

        self.assertEqual(proposals, {})
        self.assertEqual(diagnostics, [])
        self.assertFalse(stats["enabled"])


if __name__ == "__main__":
    unittest.main()
