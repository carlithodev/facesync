from __future__ import annotations

import unittest
from pathlib import Path

from tools.cr3_reference_selector import (
    match_faces_by_geometry,
    select_cr3_reference_evidence,
)


def face(value: float, box=(100, 100, 120, 120), confidence: float = 0.99):
    x, y, width, height = box
    return {
        "embedding": [value],
        "face_confidence": confidence,
        "facial_area": {"x": x, "y": y, "w": width, "h": height},
    }


def distance(left, right) -> float:
    return abs(float(left[0]) - float(right[0]))


class CR3ReferenceSelectorTests(unittest.TestCase):
    def _select(
        self,
        references,
        preview_faces,
        fullraw_faces,
        preview_sizes=None,
        fullraw_sizes=None,
    ):
        paths = set(preview_faces) | set(fullraw_faces)
        preview_sizes = preview_sizes or {path: (1000, 1000) for path in paths}
        fullraw_sizes = fullraw_sizes or {path: (1000, 1000) for path in paths}
        return select_cr3_reference_evidence(
            references,
            preview_faces,
            fullraw_faces,
            preview_sizes,
            fullraw_sizes,
            cosine_distance=distance,
            recurrence_threshold=0.40,
            peer_distance=0.40,
            identity_margin=0.05,
            geometry_min_iou=0.25,
            geometry_min_margin=0.03,
            min_support=2,
            min_face_side_pixels=56.0,
        )

    def test_geometry_relates_group_faces_across_rotation(self):
        preview = [
            face(0.0, (100, 120, 200, 120)),
            face(1.0, (650, 120, 180, 120)),
        ]
        # Inverse of rot90 for the two normalized preview boxes.
        fullraw = [
            face(0.0, (120, 700, 120, 200)),
            face(1.0, (120, 170, 120, 180)),
        ]
        result = match_faces_by_geometry(
            preview,
            (1000, 600),
            fullraw,
            (600, 1000),
            min_iou=0.25,
            min_margin=0.03,
        )

        self.assertEqual(result["transform"], "rot90")
        accepted = {
            (item["preview_index"], item["fullraw_index"])
            for item in result["pairs"] if item["accepted"]
        }
        self.assertEqual(accepted, {(0, 0), (1, 1)})

    def test_lateral_reference_promotes_coherent_fullraw_group(self):
        root = Path("ATLETA_ROOT.cr3")
        other_root = Path("OTRO_ROOT.cr3")
        photos = [Path(f"ATLETA_{index}.cr3") for index in range(3)]
        references = [
            {"path": root, "person": {"display_name": "ATLETA", "reference_value": "9874"}},
            {"path": other_root, "person": {"display_name": "OTRO", "reference_value": "6176"}},
        ]
        preview_faces = {
            root: [face(0.0)],
            other_root: [face(0.95)],
            photos[0]: [face(0.55)],
            photos[1]: [face(0.56)],
            photos[2]: [face(0.57)],
        }
        fullraw_faces = {
            root: [face(0.0)],
            other_root: [face(0.95)],
            photos[0]: [face(0.35)],
            photos[1]: [face(0.36)],
            photos[2]: [face(0.37)],
        }

        selections, diagnostics = self._select(
            references, preview_faces, fullraw_faces
        )

        self.assertTrue(selections[0]["promoted"])
        self.assertEqual(selections[0]["selected_route"], "fullraw")
        self.assertIn(
            selections[0]["anchor_path"],
            [path.resolve(strict=False) for path in photos],
        )
        self.assertEqual(selections[0]["preview_face"]["embedding"], [0.56])
        self.assertEqual(selections[0]["fullraw_face"]["embedding"], [0.36])
        self.assertEqual(diagnostics[0]["soporte_fotos"], 3)
        self.assertGreater(diagnostics[0]["margen_otras_identidades"], 0.05)

    def test_small_preview_reference_prefers_supported_fullraw_route(self):
        root = Path("SMALL_ROOT.cr3")
        photos = [Path("SMALL_1.cr3"), Path("SMALL_2.cr3")]
        references = [{
            "path": root,
            "person": {"display_name": "SMALL", "reference_value": "100"},
        }]
        preview_faces = {
            root: [face(0.0, (20, 20, 20, 20))],
            photos[0]: [face(0.10)],
            photos[1]: [face(0.11)],
        }
        fullraw_faces = {
            root: [face(0.0, (100, 100, 120, 120))],
            photos[0]: [face(0.10)],
            photos[1]: [face(0.11)],
        }

        selections, diagnostics = self._select(
            references, preview_faces, fullraw_faces
        )

        self.assertTrue(selections[0]["promoted"])
        self.assertEqual(selections[0]["selected_route"], "fullraw")
        self.assertLess(
            diagnostics[0]["raiz_preview"]["lado_minimo_px"],
            diagnostics[0]["raiz_fullraw"]["lado_minimo_px"],
        )

    def test_group_reference_selects_only_the_recurring_student_face(self):
        root = Path("GROUP_ROOT.cr3")
        first = Path("GROUP_1.cr3")
        second = Path("GROUP_2.cr3")
        references = [{
            "path": root,
            "person": {"display_name": "ALUMNA", "reference_value": "200"},
        }]
        root_faces = [
            face(0.0, (100, 100, 180, 180)),
            face(0.8, (650, 100, 180, 180)),
        ]
        preview_faces = {
            root: root_faces,
            first: [face(0.10, (100, 100, 180, 180)), face(0.82, (650, 100, 180, 180))],
            second: [face(0.12, (100, 100, 180, 180)), face(0.40, (650, 100, 180, 180))],
        }
        fullraw_faces = {
            root: [dict(item) for item in root_faces],
            first: [face(0.10, (100, 100, 180, 180)), face(0.82, (650, 100, 180, 180))],
            second: [face(0.12, (100, 100, 180, 180)), face(0.40, (650, 100, 180, 180))],
        }

        selections, diagnostics = self._select(
            references, preview_faces, fullraw_faces
        )

        self.assertTrue(selections[0]["promoted"])
        self.assertLess(selections[0]["preview_face"]["embedding"][0], 0.2)
        self.assertEqual(diagnostics[0]["soporte_fotos"], 2)
        self.assertFalse(diagnostics[0]["geometria"]["ambigua"])

    def test_reference_without_connected_group_is_not_promoted(self):
        root = Path("ISOLATED_ROOT.cr3")
        first = Path("STRANGER_1.cr3")
        second = Path("STRANGER_2.cr3")
        references = [{
            "path": root,
            "person": {"display_name": "AISLADA", "reference_value": "300"},
        }]
        preview_faces = {root: [face(0.0)], first: [face(0.7)], second: [face(0.71)]}
        fullraw_faces = {root: [face(0.0)], first: [face(0.7)], second: [face(0.71)]}

        selections, diagnostics = self._select(
            references, preview_faces, fullraw_faces
        )

        self.assertFalse(selections[0]["promoted"])
        self.assertEqual(selections[0]["anchor_path"], root.resolve(strict=False))
        self.assertEqual(diagnostics[0]["estado"], "referencia_raiz_conservada")
        self.assertNotIn("embedding", str(diagnostics[0]).lower())

    def test_weak_root_can_select_only_a_clearly_separated_nearest_group(self):
        root = Path("WEAK_ROOT.cr3")
        correct = [Path("CORRECT_1.cr3"), Path("CORRECT_2.cr3")]
        other = [Path("OTHER_1.cr3"), Path("OTHER_2.cr3")]
        references = [{
            "path": root,
            "person": {"display_name": "WEAK", "reference_value": "350"},
        }]
        values = {
            root: 0.0,
            correct[0]: 0.46,
            correct[1]: 0.47,
            other[0]: -0.65,
            other[1]: -0.66,
        }
        preview_faces = {path: [face(value)] for path, value in values.items()}
        fullraw_faces = {path: [face(value)] for path, value in values.items()}

        selections, diagnostics = self._select(
            references, preview_faces, fullraw_faces
        )

        self.assertTrue(selections[0]["promoted"])
        self.assertIn(
            selections[0]["anchor_path"],
            [path.resolve(strict=False) for path in correct],
        )
        self.assertEqual(
            diagnostics[0]["motivo"],
            "grupo_mas_cercano_coherente_y_separado",
        )

    def test_weak_root_does_not_guess_between_two_near_groups(self):
        root = Path("WEAK_TIE_ROOT.cr3")
        paths = [Path(f"TIE_{index}.cr3") for index in range(4)]
        references = [{
            "path": root,
            "person": {"display_name": "WEAK TIE", "reference_value": "360"},
        }]
        values = {
            root: 0.0,
            paths[0]: 0.46,
            paths[1]: 0.47,
            paths[2]: -0.48,
            paths[3]: -0.49,
        }
        preview_faces = {path: [face(value)] for path, value in values.items()}
        fullraw_faces = {path: [face(value)] for path, value in values.items()}

        selections, _diagnostics = self._select(
            references, preview_faces, fullraw_faces
        )

        self.assertFalse(selections[0]["promoted"])

    def test_fallback_face_cannot_be_used_as_cross_route_anchor(self):
        root = Path("FALLBACK_ROOT.cr3")
        first = Path("FALLBACK_1.cr3")
        second = Path("FALLBACK_2.cr3")
        references = [{
            "path": root,
            "person": {"display_name": "REAL", "reference_value": "400"},
        }]
        preview_faces = {
            root: [face(0.0)],
            first: [face(0.1, confidence=0.0)],
            second: [face(0.11, confidence=0.0)],
        }
        fullraw_faces = {
            root: [face(0.0)],
            first: [face(0.1)],
            second: [face(0.11)],
        }

        selections, _diagnostics = self._select(
            references, preview_faces, fullraw_faces
        )

        self.assertFalse(selections[0]["promoted"])


if __name__ == "__main__":
    unittest.main()
