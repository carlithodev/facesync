from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from core.security import SecurityManager
from tools.facesync_tools import FaceSyncCapabilities


def face(value: float, box=(100, 100, 120, 120), confidence: float = 0.99):
    x, y, width, height = box
    return {
        "embedding": [value],
        "face_confidence": confidence,
        "facial_area": {"x": x, "y": y, "w": width, "h": height},
    }


def distance(left, right) -> float:
    return abs(float(left[0]) - float(right[0]))


class CR3ReferenceIntegrationTests(unittest.TestCase):
    def _motor(self, root: Path) -> FaceSyncCapabilities:
        security = SecurityManager(
            str(root), app_data_root=str(root / "AppData")
        )
        return FaceSyncCapabilities(str(root), security_manager=security)

    def test_cr2_and_jpg_never_enter_cr3_reference_selector(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_ref_guard_") as tmp:
            root = Path(tmp)
            cr2 = root / "IMG_100.CR2"
            jpg = root / "IMG_101.JPG"
            cr2.write_bytes(b"cr2")
            jpg.write_bytes(b"jpg")
            motor = self._motor(root)
            references = [{
                "path": cr2,
                "person": {"display_name": "CR2"},
                "candidate_faces": [face(0.0)],
            }]

            with (
                patch.object(motor, "_cr2_to_jpeg") as preview_decode,
                patch.object(motor, "_cr3_fullraw_to_jpeg") as fullraw_decode,
                patch.object(motor, "_get_all_face_embeddings") as represent,
            ):
                details, stats = motor._strengthen_cr3_references(
                    refs_with_embeddings=references,
                    photo_faces_by_path={cr2: [face(0.0)], jpg: [face(0.1)]},
                    image_paths=[cr2, jpg],
                    model_name="ArcFace",
                    detector_backend="retinaface",
                    DeepFace=object(),
                )

            preview_decode.assert_not_called()
            fullraw_decode.assert_not_called()
            represent.assert_not_called()
            self.assertEqual(details, [])
            self.assertFalse(stats["enabled"])
            self.assertNotIn("cr3_reference_promoted", references[0])

    def test_cr2_and_jpg_never_enter_cr3_gallery_bootstrap(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_gallery_guard_") as tmp:
            root = Path(tmp)
            cr2 = root / "IMG_100.CR2"
            jpg = root / "IMG_101.JPG"
            motor = self._motor(root)
            references = [{
                "path": cr2,
                "embedding": [0.0],
                "person": {"display_name": "CR2", "folder_name": "CR2"},
            }]
            gallery = {"CR2": {
                "embeddings": [[0.0]],
                "paths": [cr2],
                "reference_trusted": True,
            }}
            matches = {}

            details, stats = motor._bootstrap_cr3_gallery_route(
                route="preview",
                refs_with_embeddings=references,
                photo_faces={cr2: [face(0.0)], jpg: [face(0.1)]},
                gallery_data=gallery,
                match_map=matches,
            )

            self.assertEqual(details, [])
            self.assertFalse(stats["enabled"])
            self.assertEqual(gallery["CR2"]["embeddings"], [[0.0]])
            self.assertEqual(matches, {})

    def test_cr3_integration_promotes_one_anchor_and_preserves_root_path(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_ref_integration_") as tmp:
            root = Path(tmp)
            root_photo = root / "IMG_100.CR3"
            first = root / "IMG_101.CR3"
            second = root / "IMG_102.CR3"
            for path in (root_photo, first, second):
                path.write_bytes(b"cr3")
            preview_jpeg = root / "preview.jpg"
            fullraw_jpeg = root / "fullraw.jpg"
            Image.new("RGB", (1000, 1000), "gray").save(preview_jpeg)
            Image.new("RGB", (1000, 1000), "gray").save(fullraw_jpeg)

            motor = self._motor(root)
            person = {
                "display_name": "ALUMNA CR3",
                "folder_name": "ALUMNA CR3",
                "reference_value": "100",
            }
            reference = {
                "path": root_photo,
                "person": person,
                "candidate_faces": [face(0.0)],
            }
            preview_faces = {
                root_photo: [face(0.0)],
                first: [face(0.55)],
                second: [face(0.56)],
            }
            fullraw_by_path = {
                root_photo: [face(0.0)],
                first: [face(0.35)],
                second: [face(0.36)],
            }

            with (
                patch.object(
                    motor, "_cr2_to_jpeg", return_value=(preview_jpeg, "cache_hit")
                ),
                patch.object(
                    motor,
                    "_cr3_fullraw_to_jpeg",
                    return_value=(fullraw_jpeg, "cache_hit"),
                ),
                patch.object(
                    motor,
                    "_get_all_face_embeddings",
                    side_effect=lambda path, **_kwargs: fullraw_by_path[Path(path)],
                ),
                patch.object(motor, "_cosine_distance", side_effect=distance),
            ):
                details, stats = motor._strengthen_cr3_references(
                    refs_with_embeddings=[reference],
                    photo_faces_by_path=preview_faces,
                    image_paths=[root_photo, first, second],
                    model_name="ArcFace",
                    detector_backend="retinaface",
                    DeepFace=object(),
                )

            self.assertEqual(reference["path"], root_photo)
            self.assertTrue(reference["cr3_reference_promoted"])
            self.assertEqual(reference["cr3_reference_selected_route"], "fullraw")
            self.assertEqual(reference["candidate_faces"][0]["embedding"], [0.55])
            self.assertEqual(
                reference["cr3_fullraw_reference_face"]["embedding"], [0.35]
            )
            self.assertEqual(stats["promoted_references"], 1)
            self.assertEqual(details[0]["codigo_raiz_conservado"], True)
            self.assertEqual(details[0]["soporte_fotos"], 2)
            self.assertNotIn("embedding", str(details[0]).lower())

    def test_fullraw_reference_search_is_bounded_for_large_cr3_batch(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_ref_bound_") as tmp:
            root = Path(tmp)
            root_photo = root / "ROOT.CR3"
            photos = [root / f"PHOTO_{index:04d}.CR3" for index in range(100)]
            jpeg = root / "route.jpg"
            Image.new("RGB", (1000, 1000), "gray").save(jpeg)
            motor = self._motor(root)
            reference = {
                "path": root_photo,
                "person": {"display_name": "BOUND", "folder_name": "BOUND"},
                "candidate_faces": [face(0.0)],
            }
            preview_faces = {root_photo: [face(0.0)]}
            preview_faces.update({
                path: [face(0.41 + (index * 0.001))]
                for index, path in enumerate(photos)
            })

            with (
                patch.object(
                    motor, "_cr2_to_jpeg", return_value=(jpeg, "cache_hit")
                ),
                patch.object(
                    motor, "_cr3_fullraw_to_jpeg", return_value=(jpeg, "cache_hit")
                ) as fullraw_decode,
                patch.object(
                    motor,
                    "_get_all_face_embeddings",
                    side_effect=lambda path, **_kwargs: preview_faces[Path(path)],
                ),
                patch.object(motor, "_cosine_distance", side_effect=distance),
            ):
                _details, stats = motor._strengthen_cr3_references(
                    refs_with_embeddings=[reference],
                    photo_faces_by_path=preview_faces,
                    image_paths=[root_photo, *photos],
                    model_name="ArcFace",
                    detector_backend="retinaface",
                    DeepFace=object(),
                )

            self.assertEqual(stats["cr3_photos"], 101)
            self.assertEqual(stats["candidate_photos"], 31)
            self.assertEqual(stats["fullraw_processed"], 31)
            self.assertEqual(fullraw_decode.call_count, 31)


if __name__ == "__main__":
    unittest.main()
