import sys
import tempfile
import unittest
from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from tools.cr3_route_arbiter import arbitrate_cr3_routes


def person(name):
    return {"folder_name": name, "display_name": name}


def face(x, y, w=100, h=100, confidence=1.0):
    return {
        "embedding": [float(x + y + 1)],
        "face_confidence": confidence,
        "facial_area": {"x": x, "y": y, "w": w, "h": h},
    }


def match(who, distance, face_index=0, **extra):
    return {
        "person": who,
        "distance": distance,
        "face_index": face_index,
        **extra,
    }


class Cr3RouteArbiterTests(unittest.TestCase):
    def run_arbiter(self, path, **overrides):
        alice = person("ALICE")
        preview_faces = {path: [face(100, 100)]}
        fullraw_faces = {path: [face(200, 200)]}
        values = {
            "image_paths": [path],
            "preview_matches": {},
            "preview_faces": preview_faces,
            "preview_sizes": {path: (1000, 1000)},
            "preview_confirmed": {},
            "preview_conflicts": [],
            "preview_rescues": [],
            "fullraw_matches": {path: [match(alice, 0.20)]},
            "fullraw_faces": fullraw_faces,
            "fullraw_sizes": {path: (2000, 2000)},
            "fullraw_confirmed": {path: [alice]},
            "fullraw_conflicts": [],
            "fullraw_rescues": [],
            "secure_threshold": 0.28,
            "review_threshold": 0.40,
            "identity_margin": 0.04,
            "geometry_min_iou": 0.25,
            "geometry_min_margin": 0.05,
            "min_gallery_support": 2,
        }
        values.update(overrides)
        return arbitrate_cr3_routes(**values)

    def test_fullraw_only_secure_face_is_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.cr3"
            accepted, details, stats = self.run_arbiter(path)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["reason"], "rescate_solo_fullraw")
        self.assertEqual(details[0]["estado"], "rescatada")
        self.assertEqual(stats["rescues_accepted"], 1)

    def test_preview_secure_assignment_is_immutable_on_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.cr3"
            alice, bob = person("ALICE"), person("BOB")
            accepted, details, stats = self.run_arbiter(
                path,
                preview_matches={path: [match(bob, 0.18)]},
                preview_confirmed={path: [bob]},
                fullraw_matches={path: [match(alice, 0.17)]},
                fullraw_confirmed={path: [alice]},
            )
        self.assertEqual(accepted, [])
        self.assertEqual(details[0]["motivo"], "asignacion_preview_segura_inmutable")
        self.assertEqual(stats["preview_assignments_preserved"], 1)

    def test_same_secure_identity_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.cr3"
            alice = person("ALICE")
            accepted, details, stats = self.run_arbiter(
                path,
                preview_matches={path: [match(alice, 0.19)]},
                preview_confirmed={path: [alice]},
            )
        self.assertEqual(accepted, [])
        self.assertEqual(details[0]["motivo"], "coincidencia_entre_rutas")
        self.assertEqual(stats["agreements"], 1)

    def test_unlocated_preview_owner_is_preserved_without_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.cr3"
            alice = person("ALICE")
            accepted, details, stats = self.run_arbiter(
                path,
                preview_confirmed={path: [alice]},
            )
        self.assertEqual(accepted, [])
        self.assertEqual(
            details[0]["motivo"],
            "coincidencia_con_propietario_preview_no_localizado",
        )
        self.assertEqual(stats["preview_assignments_preserved"], 1)

    def test_matching_review_and_fullraw_form_consensus(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.cr3"
            alice = person("ALICE")
            accepted, _details, stats = self.run_arbiter(
                path,
                preview_matches={path: [match(alice, 0.35)]},
            )
        self.assertEqual(accepted[0]["reason"], "consenso_preview_fullraw")
        self.assertEqual(stats["rescues_by_consensus"], 1)

    def test_clear_review_disagreement_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.cr3"
            bob = person("BOB")
            accepted, details, stats = self.run_arbiter(
                path,
                preview_matches={path: [match(bob, 0.34)]},
            )
        self.assertEqual(accepted, [])
        self.assertEqual(details[0]["motivo"], "rutas_proponen_identidades_distintas")
        self.assertEqual(stats["blocked_contradictions"], 1)

    def test_ambiguous_preview_does_not_override_clear_fullraw(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.cr3"
            bob, carol = person("BOB"), person("CAROL")
            accepted, _details, _stats = self.run_arbiter(
                path,
                preview_matches={path: [match(bob, 0.34), match(carol, 0.36)]},
            )
        self.assertEqual(accepted[0]["reason"], "fullraw_supera_preview_ambiguo")

    def test_insufficient_fullraw_identity_margin_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.cr3"
            alice, bob = person("ALICE"), person("BOB")
            accepted, details, stats = self.run_arbiter(
                path,
                fullraw_matches={path: [match(alice, 0.20), match(bob, 0.22)]},
                fullraw_confirmed={path: [alice]},
            )
        self.assertEqual(accepted, [])
        self.assertEqual(details[0]["motivo"], "margen_fullraw_insuficiente")
        self.assertEqual(stats["blocked_margin"], 1)

    def test_gallery_consensus_can_resolve_weak_reference_margin(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.cr3"
            alice, bob = person("ALICE"), person("BOB")
            accepted, _details, _stats = self.run_arbiter(
                path,
                fullraw_matches={path: [match(alice, 0.33), match(bob, 0.35)]},
                fullraw_confirmed={path: [alice]},
                fullraw_rescues=[{
                    "image_path": path,
                    "person_display_name": "ALICE",
                    "supporter_count": 3,
                }],
            )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["gallery_supporters"], 3)

    def test_group_face_without_safe_geometry_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "group.cr3"
            accepted, details, stats = self.run_arbiter(
                path,
                preview_faces={path: [face(20, 20), face(700, 700)]},
                fullraw_faces={path: [face(900, 100), face(100, 900)]},
            )
        self.assertEqual(accepted, [])
        self.assertEqual(details[0]["motivo"], "sin_correspondencia_geometrica_segura")
        self.assertEqual(stats["blocked_geometry"], 1)

    def test_group_routes_are_decided_per_face(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "group.cr3"
            alice, bob = person("ALICE"), person("BOB")
            accepted, _details, _stats = self.run_arbiter(
                path,
                preview_faces={path: [face(100, 100), face(600, 100)]},
                fullraw_faces={path: [face(200, 200), face(1200, 200)]},
                preview_matches={path: [match(alice, 0.18, 0)]},
                preview_confirmed={path: [alice]},
                fullraw_matches={path: [match(alice, 0.17, 0), match(bob, 0.19, 1)]},
                fullraw_confirmed={path: [alice, bob]},
            )
        self.assertEqual([item["person"]["folder_name"] for item in accepted], ["BOB"])
        self.assertEqual(accepted[0]["fullraw_face_index"], 1)

    def test_confidence_zero_preview_allows_unique_fullraw_only_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.cr3"
            accepted, _details, _stats = self.run_arbiter(
                path,
                preview_faces={path: [face(0, 0, confidence=0.0)]},
            )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["reason"], "rescate_solo_fullraw")

    def test_non_cr3_input_is_exact_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.cr2"
            accepted, details, stats = self.run_arbiter(path)
        self.assertEqual(accepted, [])
        self.assertEqual(details, [])
        self.assertFalse(stats["enabled"])


if __name__ == "__main__":
    unittest.main()
