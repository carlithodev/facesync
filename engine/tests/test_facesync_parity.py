from __future__ import annotations

import tempfile
import unittest
import ast
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

from core.security import SecurityManager
from core.smart_reference_resolver import RefCandidate, RefContext, SmartReferenceResolver
from tools.facesync_tools import FaceSyncCapabilities


class FaceSyncParityTests(unittest.TestCase):
    @staticmethod
    def _write_image(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"mock image for deterministic FaceSync test")

    def test_cr3_is_scanned_and_uses_the_existing_raw_decode_path(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_route_") as tmp:
            root = Path(tmp)
            source = root / "fotos"
            cr3 = source / "IMG_2411.CR3"
            decoded = root / "AppData" / "decoded.jpg"
            self._write_image(cr3)
            self._write_image(decoded)
            (source / "ignorar.txt").write_text("no es foto", encoding="utf-8")

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            scanned = motor._iter_images(source)
            self.assertEqual(scanned, [cr3])
            self.assertIn(".cr3", motor.RAW_EXTENSIONS)

            class FakeDeepFace:
                received_path = ""

                @classmethod
                def represent(cls, **kwargs):
                    cls.received_path = kwargs["img_path"]
                    return [{
                        "embedding": [1.0, 0.0],
                        "face_confidence": 0.99,
                        "facial_area": {"x": 1, "y": 1, "w": 50, "h": 50},
                    }]

            metrics = {
                "cr2_detectadas": 0,
                "cr2_convertidas": 0,
                "cr2_cache_hits": 0,
                "cr2_errores": 0,
                "cr2_ignoradas_por_dependencia": 0,
            }
            with patch.object(motor, "_cr2_to_jpeg", return_value=(decoded, "converted")) as convert:
                faces = motor._get_all_face_embeddings(
                    cr3,
                    model_name="ArcFace",
                    detector_backend="retinaface",
                    DeepFace=FakeDeepFace,
                    cr2_metrics=metrics,
                )

            convert.assert_called_once_with(cr3)
            self.assertEqual(FakeDeepFace.received_path, str(decoded))
            self.assertEqual(len(faces), 1)
            self.assertEqual(metrics["cr2_convertidas"], 0)
            self.assertEqual(metrics["cr3_convertidas"], 1)
            self.assertEqual(metrics["raw_convertidas"], 1)

    def test_jpg_cr2_cr3_twins_use_one_inference_and_deliver_both_raws(self):
        with tempfile.TemporaryDirectory(prefix="facesync_raw_twins_") as tmp:
            root = Path(tmp)
            source = root / "fotos"
            destination = root / "resultado"
            jpg = source / "IMG_2411.JPG"
            cr2 = source / "IMG_2411.CR2"
            cr3 = source / "IMG_2411.CR3"
            lone_cr3 = source / "IMG_2412.CR3"
            for path in (jpg, cr2, cr3, lone_cr3):
                self._write_image(path)

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            paths = [jpg, cr2, cr3, lone_cr3]

            analyzed, raw_twins, omitted = motor._split_cr2_twins(paths)
            delivery_index = motor._build_cr2_delivery_index(paths)

            self.assertEqual(analyzed, [jpg, lone_cr3])
            self.assertEqual(omitted, 2)
            self.assertEqual(raw_twins[jpg.resolve(strict=False)], [cr2, cr3])

            copied = motor._copy_cr2_twin(
                jpg, destination, raw_twins, delivery_index
            )
            self.assertEqual(copied, 2)
            self.assertTrue((destination / cr2.name).is_file())
            self.assertTrue((destination / cr3.name).is_file())

    def test_raw_prefetch_includes_cr2_and_cr3(self):
        with tempfile.TemporaryDirectory(prefix="facesync_raw_prefetch_") as tmp:
            root = Path(tmp)
            cr2 = root / "IMG_1.CR2"
            cr3 = root / "IMG_2.CR3"
            jpg = root / "IMG_3.JPG"
            for path in (cr2, cr3, jpg):
                self._write_image(path)

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            with patch.object(
                motor, "_cr2_to_jpeg", return_value=(root / "decoded.jpg", "converted")
            ) as convert:
                motor._start_cr2_prefetch([cr2, cr3, jpg])
                motor._stop_cr2_prefetch(wait=True)

            converted_paths = {call.args[0] for call in convert.call_args_list}
            self.assertEqual(converted_paths, {cr2, cr3})
            self.assertEqual(motor._performance_stats["cr2_prefetch_count"], 2)

    def test_cr2_and_cr3_use_distinct_conversion_cache_keys(self):
        with tempfile.TemporaryDirectory(prefix="facesync_raw_cache_keys_") as tmp:
            root = Path(tmp)
            cr2 = root / "IMG_2411.CR2"
            cr3 = root / "IMG_2411.CR3"
            self._write_image(cr2)
            self._write_image(cr3)

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            self.assertNotEqual(
                motor._cr2_cache_path(cr2),
                motor._cr2_cache_path(cr3),
            )

    def test_cr3_fullraw_cache_is_separate_and_never_accepts_cr2(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_fullraw_cache_") as tmp:
            root = Path(tmp)
            cr2 = root / "IMG_2411.CR2"
            cr3 = root / "IMG_2411.CR3"
            self._write_image(cr2)
            self._write_image(cr3)
            security = SecurityManager(
                str(root), app_data_root=str(root / "AppData")
            )
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            fast_path = motor._cr2_cache_path(cr3)
            full_path = motor._cr3_fullraw_cache_path(cr3)

            self.assertIsNotNone(full_path)
            self.assertNotEqual(fast_path, full_path)
            self.assertIsNone(motor._cr3_fullraw_cache_path(cr2))
            self.assertEqual(
                motor._cr3_fullraw_to_jpeg(cr2), (None, "not_cr3")
            )

    def test_cr3_fullraw_conversion_reuses_only_its_own_cache(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_fullraw_hit_") as tmp:
            root = Path(tmp)
            cr3 = root / "IMG_2411.CR3"
            self._write_image(cr3)
            security = SecurityManager(
                str(root), app_data_root=str(root / "AppData")
            )
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            full_path = motor._cr3_fullraw_cache_path(cr3)
            self.assertIsNotNone(full_path)
            full_path.write_bytes(b"cached full CR3 decode")

            decoded, status = motor._cr3_fullraw_to_jpeg(cr3)

            self.assertEqual(decoded, full_path)
            self.assertEqual(status, "cache_hit")

    def test_cr3_fullraw_second_opinion_never_runs_for_cr2(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_only_guard_") as tmp:
            root = Path(tmp)
            cr2 = root / "IMG_2411.CR2"
            self._write_image(cr2)
            security = SecurityManager(
                str(root), app_data_root=str(root / "AppData")
            )
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            person = {
                "display_name": "ALUMNO CR2",
                "folder_name": "ALUMNO CR2",
                "folder_path": root / "ALUMNO CR2",
            }
            reference = {
                "path": cr2,
                "person": person,
                "embedding": [1.0, 0.0],
                "embeddings": [[1.0, 0.0]],
            }

            with patch.object(motor, "_cr3_fullraw_to_jpeg") as convert:
                additions, details, stats = motor._recover_cr3_fullraw_assignments(
                    image_paths=[cr2],
                    refs_with_embeddings=[reference],
                    base_match_map={},
                    base_photo_faces={},
                    base_confirmed={},
                    model_name="ArcFace",
                    detector_backend="retinaface",
                    ambiguity_margin=motor.IDENTITY_CONFLICT_MARGIN,
                )

            convert.assert_not_called()
            self.assertEqual(additions, {})
            self.assertEqual(details, [])
            self.assertFalse(stats["enabled"])
            self.assertEqual(stats["cr3_photos"], 0)

    def test_cr3_fullraw_second_opinion_recovers_an_unassigned_photo(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_recovery_") as tmp:
            root = Path(tmp)
            reference_path = root / "IMG_2411.CR3"
            target_path = root / "IMG_2412.CR3"
            support_path = root / "IMG_2413.CR3"
            for path in (reference_path, target_path, support_path):
                self._write_image(path)
            security = SecurityManager(
                str(root), app_data_root=str(root / "AppData")
            )
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            person = {
                "display_name": "ALUMNO CR3",
                "folder_name": "ALUMNO CR3",
                "folder_path": root / "ALUMNO CR3",
            }
            reference = {
                "path": reference_path,
                "person": person,
                "embedding": [1.0, 0.0],
                "embeddings": [[1.0, 0.0]],
                "reference_trusted": True,
            }
            face = {
                "embedding": [1.0, 0.0],
                "face_confidence": 0.99,
                "facial_area": {"x": 10, "y": 10, "w": 80, "h": 80},
            }
            base_ref_match = {
                "person": person,
                "distance": 0.0,
                "verified": True,
                "face_index": 0,
                "match_type": "secure",
            }

            class FakeDeepFace:
                pass

            def embeddings_for(path, **_kwargs):
                self.assertIn(
                    Path(path), {reference_path, target_path, support_path}
                )
                return [dict(face)]

            fake_module = types.SimpleNamespace(DeepFace=FakeDeepFace)
            with (
                patch.dict(sys.modules, {"deepface": fake_module}),
                patch.object(motor, "_enable_gpu_backend"),
                patch.object(motor, "_disable_gpu_backend"),
                patch.object(motor, "_is_cached", return_value=False),
                patch.object(
                    motor,
                    "_cr3_fullraw_to_jpeg",
                    side_effect=lambda path: (Path(path), "converted"),
                ),
                patch.object(
                    motor,
                    "_get_all_face_embeddings",
                    side_effect=embeddings_for,
                ),
            ):
                additions, details, stats = motor._recover_cr3_fullraw_assignments(
                    image_paths=[reference_path, target_path, support_path],
                    refs_with_embeddings=[reference],
                    base_match_map={reference_path: [base_ref_match]},
                    base_photo_faces={reference_path: [face]},
                    base_confirmed={reference_path: [person]},
                    model_name="ArcFace",
                    detector_backend="retinaface",
                    ambiguity_margin=motor.IDENTITY_CONFLICT_MARGIN,
                )

            self.assertIn(target_path, additions, msg=str(stats))
            self.assertEqual(additions[target_path], [person])
            self.assertEqual(len(details), 2)
            self.assertEqual(stats["recovered_photos"], 2)
            self.assertEqual(stats["recovered_assignments"], 2)

    def test_cr3_fullraw_second_opinion_cannot_replace_a_confirmed_face(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_no_replace_") as tmp:
            root = Path(tmp)
            ref_a_path = root / "IMG_1001.CR3"
            ref_b_path = root / "IMG_2001.CR3"
            target_path = root / "IMG_1002.CR3"
            support_path = root / "IMG_2002.CR3"
            for path in (ref_a_path, ref_b_path, target_path, support_path):
                self._write_image(path)
            security = SecurityManager(
                str(root), app_data_root=str(root / "AppData")
            )
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            person_a = {
                "display_name": "ALUMNO A",
                "folder_name": "ALUMNO A",
                "folder_path": root / "ALUMNO A",
            }
            person_b = {
                "display_name": "ALUMNO B",
                "folder_name": "ALUMNO B",
                "folder_path": root / "ALUMNO B",
            }
            ref_a = {
                "path": ref_a_path,
                "person": person_a,
                "embedding": [0.0, 1.0],
                "embeddings": [[0.0, 1.0]],
                "reference_trusted": True,
            }
            ref_b = {
                "path": ref_b_path,
                "person": person_b,
                "embedding": [1.0, 0.0],
                "embeddings": [[1.0, 0.0]],
                "reference_trusted": True,
            }
            area = {"x": 10, "y": 10, "w": 80, "h": 80}
            base_faces = {
                ref_a_path: [{"embedding": [0.0, 1.0], "facial_area": area}],
                ref_b_path: [{"embedding": [1.0, 0.0], "facial_area": area}],
                target_path: [{"embedding": [0.0, 1.0], "facial_area": area}],
                support_path: [{"embedding": [1.0, 0.0], "facial_area": area}],
            }
            base_matches = {
                ref_a_path: [{
                    "person": person_a, "distance": 0.0, "verified": True,
                    "face_index": 0, "match_type": "secure",
                }],
                ref_b_path: [{
                    "person": person_b, "distance": 0.0, "verified": True,
                    "face_index": 0, "match_type": "secure",
                }],
                target_path: [
                    {
                        "person": person_a, "distance": 0.20,
                        "verified": True, "face_index": 0,
                        "match_type": "secure",
                    },
                    {
                        "person": person_b, "distance": 0.35,
                        "verified": False, "face_index": 0,
                        "match_type": "review",
                    },
                ],
            }

            class FakeDeepFace:
                pass

            def full_embeddings(path, **_kwargs):
                path = Path(path)
                embedding = (
                    [0.0, 1.0] if path == ref_a_path else [1.0, 0.0]
                )
                return [{"embedding": embedding, "facial_area": dict(area)}]

            fake_module = types.SimpleNamespace(DeepFace=FakeDeepFace)
            with (
                patch.dict(sys.modules, {"deepface": fake_module}),
                patch.object(motor, "_enable_gpu_backend"),
                patch.object(motor, "_disable_gpu_backend"),
                patch.object(motor, "_is_cached", return_value=False),
                patch.object(
                    motor,
                    "_cr3_fullraw_to_jpeg",
                    side_effect=lambda path: (Path(path), "converted"),
                ),
                patch.object(
                    motor,
                    "_get_all_face_embeddings",
                    side_effect=full_embeddings,
                ),
            ):
                additions, details, stats = motor._recover_cr3_fullraw_assignments(
                    image_paths=[
                        ref_a_path, ref_b_path, target_path, support_path
                    ],
                    refs_with_embeddings=[ref_a, ref_b],
                    base_match_map=base_matches,
                    base_photo_faces=base_faces,
                    base_confirmed={
                        ref_a_path: [person_a],
                        ref_b_path: [person_b],
                        target_path: [person_a],
                    },
                    model_name="ArcFace",
                    detector_backend="retinaface",
                    ambiguity_margin=motor.IDENTITY_CONFLICT_MARGIN,
                )

            self.assertNotIn(target_path, additions)
            self.assertIn(support_path, additions)
            self.assertEqual(len(details), 1)
            self.assertEqual(
                stats["blocked_cross_route_conflicts"], 1, msg=str(stats)
            )

    def test_raw_metrics_separate_cr2_cr3_and_are_written_to_report(self):
        with tempfile.TemporaryDirectory(prefix="facesync_raw_report_") as tmp:
            root = Path(tmp)
            destination = root / "resultado"
            destination.mkdir()
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            metrics = {
                "raw_detectadas": 2,
                "cr2_detectadas": 1,
                "cr3_detectadas": 1,
            }

            motor._record_raw_status(metrics, root / "A.CR2", "converted")
            motor._record_raw_status(metrics, root / "B.CR3", "error")

            self.assertEqual(metrics["raw_convertidas"], 1)
            self.assertEqual(metrics["cr2_convertidas"], 1)
            self.assertEqual(metrics.get("cr3_convertidas", 0), 0)
            self.assertEqual(metrics["raw_errores"], 1)
            self.assertEqual(metrics["cr3_errores"], 1)
            self.assertEqual(metrics.get("cr2_errores", 0), 0)

            report = {
                "raw_metrics": metrics,
                "raw_gemelos_copiados": 1,
                "cr2_gemelos_copiados": 0,
                "cr3_gemelos_copiados": 1,
                "diagnostico": {},
                "fotos_por_persona": {},
            }
            files = motor._write_reports(report, destination)
            text_report = (destination / "_reporte_facesync.txt").read_text(
                encoding="utf-8"
            )

            self.assertIn("cr3_detectadas: 1", text_report)
            self.assertIn("cr3_gemelos_copiados: 1", text_report)
            self.assertIn("txt", files)

    def test_full_delivery_report_counts_jpg_cr2_and_cr3_without_dup_inference(self):
        with tempfile.TemporaryDirectory(prefix="facesync_full_raw_delivery_") as tmp:
            root = Path(tmp)
            source = root / "fotos"
            destination = root / "resultado"
            table = root / "personas.csv"
            table.write_text("Nombre,Foto\nANA,2411\n", encoding="utf-8")
            for extension in ("JPG", "CR2", "CR3"):
                self._write_image(source / f"IMG_2411.{extension}")

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            report = motor.run_reference_face_matching(
                table_path=str(table),
                name_column="Nombre",
                reference_column="Foto",
                source_folder=str(source),
                destination_folder=str(destination),
                mock_face_matches={"ANA": ["IMG_2411.JPG"]},
            )

            self.assertTrue(report["success"], report.get("error"))
            self.assertEqual(report["total_fotos_analizadas"], 3)
            self.assertEqual(report["fotos_analizadas_reales"], 1)
            self.assertEqual(report["raw_omitidos_por_jpg_gemelo"], 2)
            self.assertEqual(report["cr2_omitidos_por_jpg_gemelo"], 1)
            self.assertEqual(report["cr3_omitidos_por_jpg_gemelo"], 1)
            self.assertEqual(report["raw_gemelos_copiados"], 2)
            self.assertEqual(report["cr2_gemelos_copiados"], 1)
            self.assertEqual(report["cr3_gemelos_copiados"], 1)
            self.assertEqual(report["archivos_entregados_totales"], 3)
            self.assertTrue((destination / "ANA" / "IMG_2411.JPG").is_file())
            self.assertTrue((destination / "ANA" / "IMG_2411.CR2").is_file())
            self.assertTrue((destination / "ANA" / "IMG_2411.CR3").is_file())

    def test_scans_entire_batch_and_copies_group_photos_to_each_person(self):
        with tempfile.TemporaryDirectory(prefix="facesync_parity_") as tmp:
            root = Path(tmp)
            source_a = root / "Fotografo A"
            source_b = root / "Fotografo B"
            destination = root / "Resultado"
            app_data = root / "AppData"
            source_a.mkdir()
            source_b.mkdir()

            table = root / "personas.csv"
            table.write_text("Nombre,Foto\nANA,100\nLUIS,200\n", encoding="utf-8")

            for path in (
                source_a / "100.jpg",
                source_b / "200.jpg",
                source_b / "ana_sin_codigo_en_el_nombre.jpg",
                source_b / "foto_grupal.jpg",
                source_b / "sin_coincidencia.jpg",
            ):
                self._write_image(path)

            security = SecurityManager(str(root), app_data_root=str(app_data))
            motor = FaceSyncCapabilities(
                str(root),
                security_manager=security,
                account_id="parity@example.com",
            )
            report = motor.run_reference_face_matching(
                table_path=str(table),
                name_column="Nombre",
                reference_column="Foto",
                source_folder=[str(source_a), str(source_b)],
                destination_folder=str(destination),
                mock_face_matches={
                    "ANA": ["ana_sin_codigo_en_el_nombre.jpg", "foto_grupal.jpg"],
                    "LUIS": ["foto_grupal.jpg"],
                },
            )

            self.assertTrue(report.get("success"), report.get("error"))
            self.assertEqual(report.get("total_fotos_analizadas"), 5)
            self.assertTrue((destination / "ANA" / "100.jpg").is_file())
            self.assertTrue((destination / "ANA" / "ana_sin_codigo_en_el_nombre.jpg").is_file())
            self.assertTrue((destination / "ANA" / "foto_grupal.jpg").is_file())
            self.assertTrue((destination / "LUIS" / "200.jpg").is_file())
            self.assertTrue((destination / "LUIS" / "foto_grupal.jpg").is_file())
            self.assertTrue(any("sin_coincidencia.jpg" in item for item in report["fotos_ignoradas_no_asignadas"]))
            self.assertEqual(report["total_fotos_unicas_clasificadas"], 4)
            self.assertEqual(report["diagnostico"]["porcentaje_clasificado"], 80.0)
            self.assertEqual(report["identity_registry"]["storage"], "sqlite_encrypted")
            self.assertEqual(report["cache_metrics"]["storage"], "sqlite_encrypted")
            self.assertTrue(motor._storage.db_path.is_file())
            self.assertTrue(motor._storage.closed)

    def test_repeated_numeric_code_uses_context_and_real_ties_are_not_guessed(self):
        resolver = SmartReferenceResolver()
        candidates = [
            RefCandidate("Retratos/IMG_2159.JPG", "Retratos", ".jpg", faces=1),
            RefCandidate("Familia/IMG_2159.JPG", "Familia", ".jpg", faces=4),
        ]
        context = RefContext(
            number="2159",
            selected_sources=["Retratos", "Familia"],
            folder_numbers={"retratos": {"2158", "2160"}, "familia": set()},
            multi_source=True,
            folder_portrait_score={"retratos": 0.9, "familia": 0.1},
        )
        resolved = resolver.resolve(candidates, context)
        self.assertEqual(resolved.status, "resuelta_automaticamente")
        self.assertEqual(resolved.chosen, "Retratos/IMG_2159.JPG")

        tie_context = RefContext(
            number="2159",
            selected_sources=["A", "B"],
            folder_numbers={"a": {"2158", "2160"}, "b": {"2158", "2160"}},
            multi_source=True,
        )
        tied = resolver.resolve([
            RefCandidate("A/IMG_2159.JPG", "A", ".jpg"),
            RefCandidate("B/IMG_2159.JPG", "B", ".jpg"),
        ], tie_context)
        self.assertEqual(tied.status, "referencia_ambigua")
        self.assertIsNone(tied.chosen)

    def test_duplicate_excel_code_assigns_distinct_references_by_row_context(self):
        with tempfile.TemporaryDirectory(prefix="facesync_duplicate_excel_code_") as tmp:
            root = Path(tmp)
            folder_a = root / "sesion_a"
            folder_b = root / "sesion_b"
            paths = [
                folder_a / "100.jpg",
                folder_a / "500.jpg",
                folder_a / "101.jpg",
                folder_b / "200.jpg",
                folder_b / "500.jpg",
                folder_b / "201.jpg",
            ]
            for path in paths:
                self._write_image(path)
            people = [
                {"display_name": "A PREV", "folder_name": "A PREV", "reference_value": "100"},
                {"display_name": "DAVO", "folder_name": "DAVO", "reference_value": "500"},
                {"display_name": "A NEXT", "folder_name": "A NEXT", "reference_value": "101"},
                {"display_name": "B PREV", "folder_name": "B PREV", "reference_value": "200"},
                {"display_name": "COBRA", "folder_name": "COBRA", "reference_value": "500"},
                {"display_name": "B NEXT", "folder_name": "B NEXT", "reference_value": "201"},
            ]
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            report = {"referencias_faltantes": []}

            with patch.object(motor, "_face_context_for_ambiguous", return_value=({}, [])):
                hits = motor._resolve_references_smart(
                    people,
                    [root],
                    paths,
                    {path.name.lower(): path for path in paths},
                    report,
                )

            self.assertEqual(hits, len(people))
            self.assertEqual(people[1]["reference_path"], folder_a / "500.jpg")
            self.assertEqual(people[4]["reference_path"], folder_b / "500.jpg")
            self.assertNotEqual(people[1]["reference_path"], people[4]["reference_path"])
            self.assertEqual(
                report["smart_reference_summary"]["codigos_repetidos_excel"], ["500"]
            )

    def test_numeric_reference_keeps_distinct_same_folder_captures(self):
        with tempfile.TemporaryDirectory(prefix="facesync_numeric_candidates_") as tmp:
            root = Path(tmp)
            source = root / "FRANK"
            paths = [
                source / "2405.CR2",
                source / "IMG_2405.CR2",
                source / "IMG_2405.JPG",
            ]
            for path in paths:
                self._write_image(path)

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            ref_index = motor._build_reference_index(paths)
            candidates = motor._reference_candidates(
                "2405",
                source,
                paths,
                {path.name.lower(): path for path in paths},
                ref_index,
            )

            candidate_paths = {Path(candidate.path) for candidate in candidates}
            self.assertEqual(candidate_paths, {source / "2405.CR2", source / "IMG_2405.JPG"})
            self.assertNotIn(source / "IMG_2405.CR2", candidate_paths)

    def test_visual_preaudit_repairs_crossed_numeric_reference_chain(self):
        with tempfile.TemporaryDirectory(prefix="facesync_reference_preaudit_") as tmp:
            root = Path(tmp)
            source = root / "FRANK"
            agu_ref = source / "IMG_2411.JPG"
            arm_wrong = source / "2405.CR2"
            arm_ref = source / "IMG_2405.JPG"
            arr_wrong = source / "2462.CR2"
            arr_ref = source / "IMG_2462.JPG"
            support_a = [source / f"IMG_{number}.JPG" for number in range(2412, 2416)]
            support_b = [source / f"IMG_{number}.JPG" for number in range(2406, 2410)]
            support_c = [source / f"IMG_{number}.JPG" for number in range(2463, 2467)]
            image_paths = [
                agu_ref, arm_wrong, arm_ref, arr_wrong, arr_ref,
                *support_a, *support_b, *support_c,
            ]
            for path in image_paths:
                self._write_image(path)

            agu = {
                "display_name": "AGUIRRE FIGUEROA",
                "folder_name": "AGUIRRE FIGUEROA",
                "reference_value": "2411",
                "reference_path": agu_ref,
                "reference_candidate_paths": [agu_ref],
            }
            arm = {
                "display_name": "ARMENTA CHICO",
                "folder_name": "ARMENTA CHICO",
                "reference_value": "2405",
                # Deliberately wrong provisional choice: Aguirre's face.
                "reference_path": arm_wrong,
                "reference_candidate_paths": [arm_wrong, arm_ref],
            }
            arr = {
                "display_name": "ARRIOVIVEZ OTHON",
                "folder_name": "ARRIOVIVEZ OTHON",
                "reference_value": "2462",
                # Deliberately wrong provisional choice: Armenta's face.
                "reference_path": arr_wrong,
                "reference_candidate_paths": [arr_wrong, arr_ref],
            }
            vector_by_path = {
                agu_ref: [0.9, 0.435889894, 0.0],
                arm_wrong: [1.0, 0.0, 0.0],
                arm_ref: [0.0, 0.9, 0.435889894],
                arr_wrong: [0.0, 1.0, 0.0],
                arr_ref: [0.0, 0.0, 1.0],
            }
            for path in support_a:
                vector_by_path[path] = [1.0, 0.0, 0.0]
            for path in support_b:
                vector_by_path[path] = [0.0, 1.0, 0.0]
            for path in support_c:
                vector_by_path[path] = [0.0, 0.0, 1.0]

            def embeddings(path, **_kwargs):
                return [{
                    "embedding": vector_by_path[Path(path)],
                    "face_confidence": 0.99,
                    "facial_area": {"w": 120, "h": 120},
                }]

            fake_module = types.ModuleType("deepface")
            fake_module.DeepFace = object()
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            with (
                patch.dict(sys.modules, {"deepface": fake_module}),
                patch.object(motor, "_enable_gpu_backend", return_value={}),
                patch.object(motor, "_disable_gpu_backend"),
                patch.object(motor, "_get_all_face_embeddings", side_effect=embeddings),
                patch.object(
                    motor,
                    "_select_index_candidates",
                    return_value=(image_paths, {"enabled": False, "selected_photos": len(image_paths)}),
                ),
            ):
                matches, errors = motor._collect_deepface_matches(
                    [agu, arm, arr],
                    image_paths,
                    threshold=0.85,
                    model_name="ArcFace",
                    detector_backend="retinaface",
                )

            selected = {
                ref["person"]["folder_name"]: ref["path"]
                for ref in errors["refs_with_embeddings"]
            }
            self.assertEqual(selected["AGUIRRE FIGUEROA"], agu_ref)
            self.assertEqual(selected["ARMENTA CHICO"], arm_ref)
            self.assertEqual(selected["ARRIOVIVEZ OTHON"], arr_ref)
            self.assertEqual(arm["reference_path"], arm_ref)
            self.assertEqual(arr["reference_path"], arr_ref)

            selected_refs = {
                ref["person"]["folder_name"]: ref
                for ref in errors["refs_with_embeddings"]
            }
            self.assertTrue(selected_refs["AGUIRRE FIGUEROA"]["reference_trusted"])
            self.assertTrue(selected_refs["ARMENTA CHICO"]["reference_trusted"])

            audits = {item["persona"]: item for item in errors["preauditoria_referencias"]}
            self.assertEqual(
                audits["ARMENTA CHICO"]["metodo"],
                "descarte_por_propiedad_facial_global",
            )
            self.assertEqual(
                audits["ARRIOVIVEZ OTHON"]["metodo"],
                "descarte_por_propiedad_facial_global",
            )
            self.assertTrue(audits["ARMENTA CHICO"]["cambio_sobre_preseleccion"])
            self.assertTrue(audits["ARRIOVIVEZ OTHON"]["cambio_sobre_preseleccion"])
            self.assertTrue(
                audits["AGUIRRE FIGUEROA"]["cuarentena_revalidada_post_preauditoria"]
            )
            self.assertTrue(
                audits["ARMENTA CHICO"]["cuarentena_revalidada_post_preauditoria"]
            )
            self.assertTrue(any(
                match["person"]["folder_name"] == "AGUIRRE FIGUEROA"
                for match in matches[arm_wrong]
            ))
            self.assertFalse(any(
                match["person"]["folder_name"] == "ARMENTA CHICO"
                for match in matches[arm_wrong]
            ))
            self.assertTrue(any(
                match["person"]["folder_name"] == "ARMENTA CHICO"
                for match in matches[arr_wrong]
            ))
            self.assertFalse(any(
                match["person"]["folder_name"] == "ARRIOVIVEZ OTHON"
                for match in matches[arr_wrong]
            ))

    def test_historical_registry_discards_prior_owner_and_selects_new_root(self):
        with tempfile.TemporaryDirectory(prefix="facesync_historical_reference_") as tmp:
            root = Path(tmp)
            old_path = root / "501M" / "IMG_2411.JPG"
            new_path = root / "502M" / "IMG_2411.CR2"
            self._write_image(old_path)
            self._write_image(new_path)
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            history = {
                "identity_id": "agu-501",
                "student": "AGUIRRE",
                "salon": "501M",
                "code": "2411",
                "embeddings": [[1.0, 0.0, 0.0], [0.999, 0.02, 0.0]],
                "model_name": "ArcFace",
                "embedding_schema": 2,
                "status": "active",
            }
            person = {
                "display_name": "ROMAN",
                "folder_name": "ROMAN",
                "reference_value": "2411",
                "reference_path": old_path,
                "historical_identity_records": [history],
            }
            refs = [
                {
                    "person": person,
                    "path": old_path,
                    "embedding": [1.0, 0.0, 0.0],
                    "reference_preselected": True,
                    "reference_support_count": 10,
                    "reference_coherent_support": 10,
                    "reference_selection_score": 10.0,
                    "reference_trusted": True,
                },
                {
                    "person": person,
                    "path": new_path,
                    "embedding": [0.0, 1.0, 0.0],
                    "reference_preselected": False,
                    "reference_support_count": 4,
                    "reference_coherent_support": 4,
                    "reference_selection_score": 4.0,
                    "reference_trusted": True,
                },
            ]

            selected, audit = motor._select_reference_candidates_global(refs, [person])

            self.assertEqual([item["path"] for item in selected], [new_path])
            self.assertEqual(person["reference_path"], new_path)
            self.assertEqual(audit[0]["metodo"], "descarte_por_registro_historico")
            self.assertTrue(audit[0]["resuelta"])
            self.assertEqual(
                audit[0]["identidades_descartadas_por_historial"][0]["alumno"],
                "AGUIRRE",
            )
            old_candidate = next(
                item for item in audit[0]["candidatos"]
                if item["archivo"].endswith("IMG_2411.JPG")
            )
            self.assertTrue(old_candidate["descartado_por_historial"])

    def test_historical_registry_never_relabels_when_only_old_root_exists(self):
        with tempfile.TemporaryDirectory(prefix="facesync_historical_block_") as tmp:
            root = Path(tmp)
            old_path = root / "IMG_5410.JPG"
            self._write_image(old_path)
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            person = {
                "display_name": "MANRIQUEZ",
                "folder_name": "MANRIQUEZ",
                "reference_value": "5410",
                "reference_path": old_path,
                "historical_identity_records": [{
                    "identity_id": "abu-501",
                    "student": "ABURILLO",
                    "salon": "501M",
                    "code": "5410",
                    "embeddings": [[1.0, 0.0, 0.0], [0.999, 0.02, 0.0]],
                    "model_name": "ArcFace",
                    "embedding_schema": 2,
                    "status": "active",
                }],
            }
            refs = [{
                "person": person,
                "path": old_path,
                "embedding": [1.0, 0.0, 0.0],
                "reference_preselected": True,
                "reference_support_count": 5,
                "reference_coherent_support": 5,
                "reference_selection_score": 5.0,
                "reference_trusted": True,
            }]

            selected, audit = motor._select_reference_candidates_global(refs, [person])

            self.assertEqual(selected, [])
            self.assertIsNone(person["reference_path"])
            self.assertFalse(audit[0]["resuelta"])
            self.assertEqual(
                audit[0]["metodo"],
                "sin_candidato_nuevo_tras_descartar_historial",
            )

    def test_cr3_history_compares_only_the_same_representation_and_version(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_history_route_") as tmp:
            root = Path(tmp)
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            preview_record = {
                "identity_id": "ana-preview",
                "student": "ANA",
                "salon": "501M",
                "code": "2411",
                "embeddings": [[1.0, 0.0, 0.0], [0.99, 0.1, 0.0]],
                "format_family": "cr3",
                "representation": "preview",
                "processing_version": motor.CR3_PREVIEW_CACHE_VARIANT,
            }
            legacy_record = {
                "identity_id": "legacy-jpg",
                "student": "LEGACY",
                "salon": "500M",
                "code": "2411",
                "embeddings": [[1.0, 0.0, 0.0], [0.99, 0.1, 0.0]],
            }

            preview = motor._match_historical_identity(
                [1.0, 0.0, 0.0],
                [preview_record, legacy_record],
                format_family="cr3",
                representation="preview",
                processing_version=motor.CR3_PREVIEW_CACHE_VARIANT,
            )
            fullraw = motor._match_historical_identity(
                [1.0, 0.0, 0.0],
                [preview_record, legacy_record],
                format_family="cr3",
                representation="fullraw",
                processing_version=motor.CR3_FULLRAW_CACHE_VARIANT,
            )
            base = motor._match_historical_identity(
                [1.0, 0.0, 0.0],
                [preview_record, legacy_record],
                format_family="base",
            )

            self.assertEqual(preview["identity_id"], "ana-preview")
            self.assertIsNone(fullraw)
            self.assertEqual(base["identity_id"], "legacy-jpg")

    def test_cr3_third_room_discards_both_prior_owners_and_selects_new_face(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_third_room_") as tmp:
            root = Path(tmp)
            paths = [root / f"candidate_{index}_2411.CR3" for index in range(3)]
            for path in paths:
                path.write_bytes(b"raw-test")
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            histories = []
            for identity_id, student, salon, vector in (
                ("ana-preview", "ANA", "501M", [1.0, 0.0, 0.0]),
                ("bea-preview", "BEA", "502M", [0.0, 1.0, 0.0]),
            ):
                histories.append({
                    "identity_id": identity_id,
                    "student": student,
                    "salon": salon,
                    "code": "2411",
                    "embeddings": [vector, vector],
                    "format_family": "cr3",
                    "representation": "preview",
                    "processing_version": motor.CR3_PREVIEW_CACHE_VARIANT,
                })
            person = {
                "display_name": "CARLA",
                "folder_name": "CARLA",
                "reference_value": "2411",
                "reference_path": paths[0],
                "historical_identity_records": histories,
            }
            refs = []
            for index, vector in enumerate(
                ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])
            ):
                refs.append({
                    "person": person,
                    "path": paths[index],
                    "embedding": vector,
                    "reference_preselected": index == 0,
                    "reference_support_count": 5 - index,
                    "reference_coherent_support": 5 - index,
                    "reference_selection_score": float(5 - index),
                    "reference_trusted": True,
                })

            selected, audit = motor._select_reference_candidates_global(refs, [person])

            self.assertEqual([item["path"] for item in selected], [paths[2]])
            self.assertEqual(audit[0]["metodo"], "descarte_por_registro_historico")
            self.assertEqual(
                {
                    item["alumno"]
                    for item in audit[0]["identidades_descartadas_por_historial"]
                },
                {"ANA", "BEA"},
            )

    def test_cr3_fullraw_registry_requires_two_independent_support_photos(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_registry_record_") as tmp:
            root = Path(tmp)
            reference = root / "IMG_2411.CR3"
            support_a = root / "IMG_2412.CR3"
            support_b = root / "IMG_2413.CR3"
            for path in (reference, support_a, support_b):
                path.write_bytes(b"raw-test")
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            person = {
                "display_name": "ANA",
                "folder_name": "ANA",
                "reference_value": "2411",
            }
            ref = {
                "person": person,
                "path": reference,
                "embedding": [1.0, 0.0, 0.0],
                "reference_trusted": True,
            }
            context = {
                "salon": "501M",
                "table_path": str(root / "501M.xlsx"),
                "table_hash": "excel-hash",
                "source_folders": [str(root)],
            }
            incomplete = motor._build_confirmed_identity_records(
                [ref],
                {"ANA": {
                    "embeddings": [[1.0, 0.0, 0.0], [0.9, 0.4359, 0.0]],
                    "paths": [reference, support_a],
                }},
                identity_context=context,
                model_name="ArcFace",
                representation="fullraw",
                processing_version=motor.CR3_FULLRAW_CACHE_VARIANT,
                require_gallery_support=True,
            )
            complete = motor._build_confirmed_identity_records(
                [ref],
                {"ANA": {
                    "embeddings": [
                        [1.0, 0.0, 0.0],
                        [0.9, 0.4359, 0.0],
                        [0.6, 0.8, 0.0],
                    ],
                    "paths": [reference, support_a, support_b],
                }},
                identity_context=context,
                model_name="ArcFace",
                representation="fullraw",
                processing_version=motor.CR3_FULLRAW_CACHE_VARIANT,
                require_gallery_support=True,
            )

            self.assertEqual(incomplete, [])
            self.assertEqual(len(complete), 1)
            self.assertEqual(complete[0]["format_family"], "cr3")
            self.assertEqual(complete[0]["representation"], "fullraw")
            self.assertEqual(complete[0]["support_count"], 2)
            self.assertEqual(len(complete[0]["embeddings"]), 3)

    def test_cr3_preview_cache_is_versioned_without_changing_cr2_cache(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cr3_cache_version_") as tmp:
            root = Path(tmp)
            cr2 = root / "IMG_1.CR2"
            cr3 = root / "IMG_1.CR3"
            cr2.write_bytes(b"cr2")
            cr3.write_bytes(b"cr3")
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            cr2_path = motor._cr2_cache_path(cr2)
            cr3_path = motor._cr2_cache_path(cr3)
            cr2_preview = motor._cr2_preview_cache_path(cr2)
            cr3_preview = motor._cr2_preview_cache_path(cr3)

            self.assertEqual(cr2_path.parent.name, "cr2")
            self.assertEqual(cr2_preview.parent.name, "cr2_preview")
            self.assertEqual(cr3_path.parent.name, "cr3_preview")
            self.assertEqual(cr3_preview.parent.name, "cr3_preview")
            self.assertNotEqual(cr3_path.name, cr3_preview.name)

    def test_confirmed_identity_survives_embedding_cache_cleanup_and_is_found_next_salon(self):
        with tempfile.TemporaryDirectory(prefix="facesync_identity_cycle_") as tmp:
            root = Path(tmp)
            app_data = root / "AppData"
            source = root / "Fotos"
            reference = source / "IMG_2411.JPG"
            support = source / "IMG_2412.JPG"
            table_501 = root / "501M.csv"
            table_502 = root / "502M.csv"
            self._write_image(reference)
            self._write_image(support)
            table_501.write_text("Nombre,Foto\nAGUIRRE,2411\n", encoding="utf-8")
            table_502.write_text("Nombre,Foto\nROMAN,2411\n", encoding="utf-8")

            security = SecurityManager(str(root), app_data_root=str(app_data))
            motor = FaceSyncCapabilities(
                str(root),
                security_manager=security,
                account_id="owner@example.com",
            )
            person_501 = {
                "display_name": "AGUIRRE",
                "folder_name": "AGUIRRE",
                "reference_value": "2411",
            }
            selected_refs = [{
                "person": person_501,
                "path": reference,
                "embedding": [1.0, 0.0, 0.0],
                "selected_face_index": 0,
                "reference_trusted": True,
                "reference_coherent_support": 3,
                "reference_coherence_ratio": 1.0,
                "reference_selection_score": 3.0,
            }]
            gallery = {
                "AGUIRRE": {
                    "embeddings": [[1.0, 0.0, 0.0], [0.8, 0.6, 0.0]],
                }
            }
            registry, context_501 = motor._attach_identity_history(
                [person_501],
                table_path=table_501,
                source_folders=[source],
                model_name="ArcFace",
                run_id="run-501",
            )
            records = motor._build_confirmed_identity_records(
                selected_refs,
                gallery,
                identity_context=context_501,
                model_name="ArcFace",
            )

            self.assertEqual(len(records), 1)
            registry.register_many(records, run_id="run-501")
            self.assertNotIn("embeddings", str(motor._identity_registry_path))

            # The performance cache is disposable; the labeled identity
            # registry must remain available for later classrooms.
            if motor._cache_dir:
                for cached_file in motor._cache_dir.glob("*"):
                    if cached_file.is_file():
                        cached_file.unlink()

            person_502 = {
                "display_name": "ROMAN",
                "folder_name": "ROMAN",
                "reference_value": "2411",
            }
            _, context_502 = motor._attach_identity_history(
                [person_502],
                table_path=table_502,
                source_folders=[source],
                model_name="ArcFace",
                run_id="run-502",
            )

            self.assertEqual(
                context_502["summary"]["codigos_repetidos_historicos"],
                ["2411"],
            )
            self.assertEqual(
                person_502["historical_identity_records"][0]["student"],
                "AGUIRRE",
            )
            self.assertEqual(
                context_502["summary"]["storage"],
                "sqlite_encrypted",
            )
            motor._storage.close()

    def test_sqlite_embedding_cache_is_reused_only_by_the_same_account(self):
        with tempfile.TemporaryDirectory(prefix="facesync_account_cache_") as tmp:
            root = Path(tmp)
            image = root / "IMG_2411.JPG"
            self._write_image(image)
            security = SecurityManager(
                str(root), app_data_root=str(root / "AppData")
            )
            cache_key = FaceSyncCapabilities._make_cache_key(image, "ArcFace")
            faces = [{"embedding": [1.0, 0.0], "face_confidence": 0.99}]

            first = FaceSyncCapabilities(
                str(root), security_manager=security, account_id="a@example.com"
            )
            first._save_to_disk_cache(cache_key, faces)
            first._storage.close()

            same_account = FaceSyncCapabilities(
                str(root), security_manager=security, account_id="a@example.com"
            )
            other_account = FaceSyncCapabilities(
                str(root), security_manager=security, account_id="b@example.com"
            )
            self.assertEqual(same_account._load_from_disk_cache(cache_key), faces)
            self.assertIsNone(other_account._load_from_disk_cache(cache_key))
            self.assertFalse(any(same_account._cache_dir.glob("*.json")))
            same_account._storage.close()
            other_account._storage.close()

    def test_post_preaudit_revalidation_keeps_a_genuine_cross_identity_quarantine(self):
        with tempfile.TemporaryDirectory(prefix="facesync_reference_revalidation_") as tmp:
            root = Path(tmp)
            ana_ref = root / "ana.jpg"
            luis_ref = root / "luis.jpg"
            self._write_image(ana_ref)
            self._write_image(luis_ref)
            support_paths = [root / f"support_{index}.jpg" for index in range(4)]
            for path in support_paths:
                self._write_image(path)

            ana = {"display_name": "ANA", "folder_name": "ANA"}
            luis = {"display_name": "LUIS", "folder_name": "LUIS"}
            refs = [
                {
                    "person": ana,
                    "path": ana_ref,
                    "embedding": [0.8, 0.6],
                    "ref_faces_count": 1,
                    "reference_trusted": False,
                    "reference_quarantine_reasons": [
                        "soporte_reclamado_por_otras_identidades"
                    ],
                },
                {
                    "person": luis,
                    "path": luis_ref,
                    "embedding": [1.0, 0.0],
                    "ref_faces_count": 1,
                    "reference_trusted": True,
                    "reference_quarantine_reasons": [],
                },
            ]
            photo_faces = {
                path: [{"embedding": [1.0, 0.0]}] for path in support_paths
            }
            preaudit = [
                {"persona": "ANA", "confianza": "alta"},
                {"persona": "LUIS", "confianza": "alta"},
            ]
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            revalidated = motor._revalidate_reference_trust_after_preaudit(
                refs,
                preaudit,
                photo_faces,
            )

            self.assertFalse(refs[0]["reference_trusted"])
            self.assertEqual(
                refs[0]["reference_quarantine_reasons"],
                ["soporte_reclamado_por_otras_identidades"],
            )
            self.assertFalse(revalidated)

    def test_recurrence_selects_identity_from_reference_with_many_faces(self):
        self.assertEqual(FaceSyncCapabilities.THRESHOLD_SECURE, 0.28)
        self.assertEqual(FaceSyncCapabilities.THRESHOLD_REVIEW, 0.40)

        with tempfile.TemporaryDirectory(prefix="facesync_reference_faces_") as tmp:
            root = Path(tmp)
            reference = root / "100.jpg"
            candidate = root / "candidate.jpg"
            self._write_image(reference)
            self._write_image(candidate)

            class FakeDeepFace:
                @staticmethod
                def represent(*, img_path, **_kwargs):
                    if Path(img_path) == reference:
                        return [
                            {"embedding": [1.0, 0.0, 0.0, 0.0], "face_confidence": 0.99},
                            {"embedding": [0.0, 1.0, 0.0, 0.0], "face_confidence": 0.90},
                            {"embedding": [0.0, 0.0, 1.0, 0.0], "face_confidence": 0.98},
                            {"embedding": [0.0, 0.0, 0.0, 1.0], "face_confidence": 0.97},
                        ]
                    return [{"embedding": [0.0, 1.0, 0.0, 0.0], "face_confidence": 0.95}]

            fake_module = types.ModuleType("deepface")
            fake_module.DeepFace = FakeDeepFace
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            person = {
                "display_name": "ANA",
                "folder_name": "ANA",
                "reference_path": reference,
            }

            with patch.dict(sys.modules, {"deepface": fake_module}):
                matches, errors = motor._collect_deepface_matches(
                    [person],
                    [candidate],
                    threshold=FaceSyncCapabilities.THRESHOLD_REVIEW,
                    model_name="ArcFace",
                    detector_backend="retinaface",
                )

            self.assertFalse(errors["referencias_invalidas"])
            self.assertEqual(len(matches[candidate]), 1)
            self.assertEqual(matches[candidate][0]["distance"], 0.0)
            self.assertEqual(
                errors["seleccion_rostros_referencia"][0]["rostro_seleccionado"],
                2,
            )

    def test_equal_recurrence_is_reported_as_ambiguous_instead_of_guessed(self):
        with tempfile.TemporaryDirectory(prefix="facesync_reference_tie_") as tmp:
            root = Path(tmp)
            reference = root / "reference.jpg"
            first_photo = root / "first.jpg"
            second_photo = root / "second.jpg"
            for path in (reference, first_photo, second_photo):
                self._write_image(path)

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            person = {"display_name": "ANA", "folder_name": "ANA"}
            refs = [{
                "person": person,
                "path": reference,
                "candidate_faces": [
                    {"embedding": [1.0, 0.0], "face_confidence": 1.0},
                    {"embedding": [0.0, 1.0], "face_confidence": 1.0},
                ],
                "ref_faces_count": 2,
            }]
            photo_faces = {
                reference: refs[0]["candidate_faces"],
                first_photo: [{"embedding": [1.0, 0.0], "face_confidence": 1.0}],
                second_photo: [{"embedding": [0.0, 1.0], "face_confidence": 1.0}],
            }

            selected, details, ambiguous = motor._select_reference_faces_by_recurrence(
                refs, photo_faces,
            )

            self.assertFalse(selected)
            self.assertFalse(details)
            self.assertEqual(len(ambiguous), 1)
            self.assertIsNone(ambiguous[0]["rostro_seleccionado"])

    def test_fragmented_single_face_reference_is_quarantined(self):
        with tempfile.TemporaryDirectory(prefix="facesync_reference_quarantine_") as tmp:
            root = Path(tmp)
            reference = root / "reference.jpg"
            self._write_image(reference)
            support_vectors = [
                [0.7, 0.7141, 0.0],
                [0.7, -0.7141, 0.0],
                [0.7, 0.0, 0.7141],
                [0.7, 0.0, -0.7141],
            ]
            photo_faces = {}
            for index, vector in enumerate(support_vectors):
                photo = root / f"support_{index}.jpg"
                self._write_image(photo)
                photo_faces[photo] = [{"embedding": vector}]
            person = {"display_name": "ANA", "folder_name": "ANA"}
            refs = [{
                "person": person,
                "path": reference,
                "candidate_faces": [{
                    "embedding": [1.0, 0.0, 0.0],
                    "face_confidence": 0.99,
                    "facial_area": {"w": 50, "h": 50},
                }],
            }]
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            selected, details, ambiguous = motor._select_reference_faces_by_recurrence(
                refs, photo_faces,
            )

            self.assertFalse(ambiguous)
            self.assertEqual(len(selected), 1)
            self.assertFalse(selected[0]["reference_trusted"])
            self.assertIn("soporte_visual_fragmentado", selected[0]["reference_quarantine_reasons"])
            self.assertFalse(details[0]["referencia_confiable"])

    def test_quarantined_reference_cannot_directly_assign_a_stranger(self):
        with tempfile.TemporaryDirectory(prefix="facesync_quarantined_direct_") as tmp:
            root = Path(tmp)
            reference = root / "reference.jpg"
            stranger = root / "stranger.jpg"
            for path in (reference, stranger):
                self._write_image(path)
            person = {
                "display_name": "ANA", "folder_name": "ANA",
                "folder_path": root / "ANA",
            }
            gallery = {"ANA": {
                "person": person,
                "embeddings": [[1.0, 0.0]],
                "paths": [reference],
                "times": [0.0],
                "reference_path": reference.resolve(),
                "reference_trusted": False,
                "reference_recovered": False,
            }}
            match_map = {stranger: [{
                "person": person, "distance": 0.10,
                "face_index": 0, "match_type": "secure",
            }]}
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            confirmed, review, conflicts, rescues = motor._resolve_assignments(
                match_map,
                ambiguity_margin=0.03,
                gallery_data=gallery,
                photo_face_embeddings={stranger: [[1.0, 0.0]]},
            )

            self.assertNotIn(stranger, confirmed)
            self.assertEqual(len(review), 1)
            self.assertFalse(conflicts)
            self.assertFalse(rescues)

    def test_quarantined_reference_recovers_from_exclusive_visual_cluster(self):
        with tempfile.TemporaryDirectory(prefix="facesync_reference_recovery_") as tmp:
            root = Path(tmp)
            reference = root / "reference.jpg"
            self._write_image(reference)
            person = {"display_name": "ANA", "folder_name": "ANA"}
            refs = [{
                "person": person,
                "path": reference,
                "embedding": [0.4, 0.9165, 0.0],
                "embeddings": [[0.4, 0.9165, 0.0]],
                "reference_trusted": False,
                "reference_quarantine_reasons": ["soporte_visual_fragmentado"],
            }]
            vectors = [
                [1.0, 0.0, 0.0],
                [0.99, 0.02, 0.0],
                [0.98, -0.03, 0.01],
            ]
            match_map = {}
            photo_embeddings = {}
            for index, vector in enumerate(vectors):
                photo = root / f"candidate_{index}.jpg"
                self._write_image(photo)
                match_map[photo] = [{
                    "person": person, "distance": 0.60,
                    "face_index": 0, "match_type": "secure",
                }]
                photo_embeddings[photo] = [vector]
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            gallery, stats = motor._build_identity_gallery(
                refs, match_map, photo_embeddings,
            )

            self.assertTrue(gallery["ANA"]["reference_recovered"])
            self.assertFalse(gallery["ANA"]["reference_trusted"])
            self.assertEqual(gallery["ANA"]["cluster_size"], 3)
            self.assertEqual(stats["references_recovered_by_cluster"], 1)
            self.assertEqual(len(gallery["ANA"]["embeddings"]), 3)

    def test_two_quarantined_references_cannot_claim_same_recovery_cluster(self):
        with tempfile.TemporaryDirectory(prefix="facesync_symmetric_recovery_") as tmp:
            root = Path(tmp)
            refs = []
            people = []
            for name, embedding in (("ANA", [1.0, 0.0]), ("LUIS", [0.9, 0.1])):
                reference = root / f"{name}.jpg"
                self._write_image(reference)
                person = {"display_name": name, "folder_name": name}
                people.append(person)
                refs.append({
                    "person": person,
                    "path": reference,
                    "embedding": embedding,
                    "embeddings": [embedding],
                    "reference_trusted": False,
                    "reference_quarantine_reasons": ["rostro_referencia_demasiado_pequeno"],
                })
            match_map = {}
            photo_embeddings = {}
            for index, vector in enumerate(([0.0, 1.0], [0.02, 0.99], [-0.03, 0.98])):
                photo = root / f"shared_{index}.jpg"
                self._write_image(photo)
                photo_embeddings[photo] = [vector]
                match_map[photo] = [
                    {"person": person, "distance": 0.70, "face_index": 0, "match_type": "review"}
                    for person in people
                ]
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            gallery, stats = motor._build_identity_gallery(refs, match_map, photo_embeddings)

            self.assertFalse(gallery["ANA"]["reference_recovered"])
            self.assertFalse(gallery["LUIS"]["reference_recovered"])
            self.assertEqual(stats["references_recovered_by_cluster"], 0)

    def test_adaptive_gallery_cannot_rescue_without_one_hard_visual_anchor(self):
        with tempfile.TemporaryDirectory(prefix="facesync_gallery_hard_anchor_") as tmp:
            root = Path(tmp)
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            def fake_distance(left, right):
                if left == [0.0]:
                    return {1.0: 0.71, 2.0: 0.72, 3.0: 0.73}.get(right[0], 0.71)
                return 0.65

            with patch.object(motor, "_cosine_distance", side_effect=fake_distance):
                result = motor._try_gallery_rescue(
                    [0.0], [[1.0], [2.0], [3.0]],
                )

            self.assertGreater(result["best_gallery_distance"], motor.GALLERY_RESCUE_MAX_DISTANCE)
            self.assertFalse(result["rescued"])

    def test_consensus_rescue_adds_evidence_for_later_hard_faces(self):
        with tempfile.TemporaryDirectory(prefix="facesync_gallery_consensus_") as tmp:
            root = Path(tmp)
            first = root / "first.jpg"
            second = root / "second.jpg"
            person = {
                "display_name": "ANA",
                "folder_name": "ANA",
                "folder_path": root / "ANA",
            }
            match = lambda: {
                "person": person,
                "distance": 0.34,
                "face_index": 0,
                "match_type": "review",
            }
            match_map = {first: [match()], second: [match()]}
            photo_embeddings = {
                first: [[1.0, 0.0]],
                second: [[0.9, 0.1]],
            }
            gallery = {
                "ANA": {
                    "person": person,
                    "embeddings": [[0.0, 1.0], [-1.0, 0.0]],
                }
            }
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            def fake_rescue(_face, gallery_embeddings, **_kwargs):
                return {
                    "rescued": len(gallery_embeddings) >= 2,
                    "best_gallery_distance": 0.30,
                    "avg_top3": 0.34,
                    "supporter_avg": 0.34,
                    "supporter_count": len(gallery_embeddings),
                    "temporal_support": True,
                    "robust_score": 0.34,
                }

            with patch.object(motor, "_try_gallery_rescue", side_effect=fake_rescue):
                confirmed, review, conflicts, rescues = motor._resolve_assignments(
                    match_map,
                    ambiguity_margin=0.03,
                    gallery_data=gallery,
                    photo_face_embeddings=photo_embeddings,
                )

            self.assertIn(first, confirmed)
            self.assertIn(second, confirmed)
            self.assertFalse(review)
            self.assertFalse(conflicts)
            self.assertEqual(len(rescues), 2)
            self.assertEqual(rescues[1]["supporter_count"], 3)
            self.assertEqual(len(gallery["ANA"]["embeddings"]), 3)

    def test_reference_photo_cannot_refeed_accompanying_face_into_gallery(self):
        with tempfile.TemporaryDirectory(prefix="facesync_gallery_reference_") as tmp:
            root = Path(tmp)
            reference = root / "reference.jpg"
            self._write_image(reference)
            person = {"display_name": "ANA", "folder_name": "ANA"}
            refs = [{
                "person": person,
                "path": reference,
                "embedding": [1.0, 0.0],
            }]
            match_map = {
                reference: [{
                    "person": person,
                    "distance": 0.0,
                    "face_index": 0,
                }]
            }
            photo_embeddings = {reference: [[0.0, 1.0], [1.0, 0.0]]}
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            gallery, stats = motor._build_identity_gallery(
                refs, match_map, photo_embeddings,
            )

            self.assertEqual(gallery["ANA"]["embeddings"], [[1.0, 0.0]])
            self.assertEqual(stats["gallery_feeds"], 0)

    def test_recurrent_secure_faces_bootstrap_gallery_but_isolated_face_does_not(self):
        with tempfile.TemporaryDirectory(prefix="facesync_gallery_recurrence_") as tmp:
            root = Path(tmp)
            reference = root / "reference.jpg"
            first = root / "first.jpg"
            second = root / "second.jpg"
            isolated = root / "isolated.jpg"
            for path in (reference, first, second, isolated):
                self._write_image(path)

            person = {"display_name": "ANA", "folder_name": "ANA"}
            refs = [{"person": person, "path": reference, "embedding": [1.0, 0.0]}]
            match = lambda distance=0.26: {
                "person": person,
                "distance": distance,
                "face_index": 0,
                "match_type": "secure",
            }
            match_map = {
                first: [match()],
                second: [match(0.27)],
                isolated: [match(0.25)],
            }
            photo_embeddings = {
                first: [[0.80, 0.60]],
                second: [[0.78, 0.62]],
                isolated: [[-1.0, 0.0]],
            }
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            gallery, stats = motor._build_identity_gallery(
                refs, match_map, photo_embeddings,
            )

            self.assertEqual(len(gallery["ANA"]["embeddings"]), 2)
            self.assertNotIn([-1.0, 0.0], gallery["ANA"]["embeddings"])
            self.assertEqual(stats["gallery_bootstrap_feeds"], 1)

    def test_isolated_medium_direct_match_requires_gallery_consensus(self):
        with tempfile.TemporaryDirectory(prefix="facesync_isolated_direct_") as tmp:
            root = Path(tmp)
            photo = root / "photo.jpg"
            self._write_image(photo)
            person = {
                "display_name": "ANA",
                "folder_name": "ANA",
                "folder_path": root / "ANA",
            }
            match_map = {photo: [{
                "person": person,
                "distance": 0.34,
                "face_index": 0,
                "match_type": "review",
            }]}
            gallery = {"ANA": {
                "person": person,
                "embeddings": [[0.0, 1.0], [0.0, -1.0], [-1.0, 0.0]],
                "paths": [],
                "times": [],
            }}
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            confirmed, review, conflicts, rescues = motor._resolve_assignments(
                match_map,
                ambiguity_margin=0.03,
                gallery_data=gallery,
                photo_face_embeddings={photo: [[1.0, 0.0]]},
            )

            self.assertNotIn(photo, confirmed)
            self.assertEqual(len(review), 1)
            self.assertFalse(conflicts)
            self.assertFalse(rescues)

    def test_two_strong_visual_votes_rescue_without_temporal_veto(self):
        with tempfile.TemporaryDirectory(prefix="facesync_visual_votes_") as tmp:
            root = Path(tmp)
            photo = root / "photo.jpg"
            self._write_image(photo)
            person = {
                "display_name": "ANA",
                "folder_name": "ANA",
                "folder_path": root / "ANA",
            }
            match_map = {photo: [{
                "person": person,
                "distance": 0.34,
                "face_index": 0,
                "match_type": "review",
            }]}
            gallery = {"ANA": {
                "person": person,
                "embeddings": [[1.0, 0.03], [0.98, -0.04]],
                "paths": [],
                "times": [],
            }}
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            confirmed, review, conflicts, rescues = motor._resolve_assignments(
                match_map,
                ambiguity_margin=0.03,
                gallery_data=gallery,
                photo_face_embeddings={photo: [[1.0, 0.0]]},
            )

            self.assertEqual(confirmed[photo][0]["display_name"], "ANA")
            self.assertFalse(review)
            self.assertFalse(conflicts)
            self.assertEqual(len(rescues), 1)
            self.assertFalse(rescues[0]["temporal_support"])

    def test_secondary_cluster_needs_clear_surplus_from_dominant_gallery(self):
        with tempfile.TemporaryDirectory(prefix="facesync_secondary_cluster_") as tmp:
            root = Path(tmp)
            weak_photo = root / "weak.jpg"
            strong_photo = root / "strong.jpg"
            for path in (weak_photo, strong_photo):
                self._write_image(path)
            person = {
                "display_name": "ANA",
                "folder_name": "ANA",
                "folder_path": root / "ANA",
            }
            match = lambda: {
                "person": person,
                "distance": 0.34,
                "face_index": 0,
                "match_type": "review",
            }
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            weak_gallery = {"ANA": {
                "person": person,
                "embeddings": [[1.0, 0.02], [0.98, -0.03]],
                "paths": [],
                "times": [],
                "rejected_cluster_members": {(weak_photo.resolve(), 0)},
            }}
            weak_confirmed, weak_review, _, _ = motor._resolve_assignments(
                {weak_photo: [match()]},
                ambiguity_margin=0.03,
                gallery_data=weak_gallery,
                photo_face_embeddings={weak_photo: [[1.0, 0.0]]},
            )
            self.assertNotIn(weak_photo, weak_confirmed)
            self.assertEqual(len(weak_review), 1)

            strong_gallery = {"ANA": {
                "person": person,
                "embeddings": [
                    [1.0, 0.02], [0.98, -0.03], [0.99, 0.05],
                    [0.97, -0.02], [1.0, 0.04], [0.99, -0.05],
                ],
                "paths": [],
                "times": [],
                "rejected_cluster_members": {(strong_photo.resolve(), 0)},
            }}
            strong_confirmed, strong_review, _, _ = motor._resolve_assignments(
                {strong_photo: [match()]},
                ambiguity_margin=0.03,
                gallery_data=strong_gallery,
                photo_face_embeddings={strong_photo: [[1.0, 0.0]]},
            )
            self.assertEqual(strong_confirmed[strong_photo][0]["display_name"], "ANA")
            self.assertFalse(strong_review)

    def test_fast_delivery_uses_hardlink_without_changing_file_contents(self):
        with tempfile.TemporaryDirectory(prefix="facesync_hardlink_") as tmp:
            root = Path(tmp)
            source = root / "source.cr2"
            destination = root / "resultado"
            source.write_bytes(b"raw-photo-payload")
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            with patch.dict(os.environ, {"FACESYNC_DELIVERY_MODE": "auto"}):
                result = motor._copy_image_once(source, destination)

            self.assertEqual(result["status"], "copied")
            self.assertEqual(result["delivery_mode"], "hardlink")
            self.assertTrue(os.path.samefile(source, destination / source.name))
            self.assertEqual(motor._delivery_stats["hardlinks"], 1)

    def test_fast_delivery_falls_back_to_physical_copy(self):
        with tempfile.TemporaryDirectory(prefix="facesync_copy_fallback_") as tmp:
            root = Path(tmp)
            source = root / "source.cr2"
            destination = root / "resultado"
            source.write_bytes(b"raw-photo-payload")
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            with (
                patch.dict(os.environ, {"FACESYNC_DELIVERY_MODE": "auto"}),
                patch("tools.facesync_tools.os.link", side_effect=OSError("unsupported")),
            ):
                result = motor._copy_image_once(source, destination)

            self.assertEqual(result["delivery_mode"], "physical_copy")
            self.assertEqual((destination / source.name).read_bytes(), source.read_bytes())
            self.assertEqual(motor._delivery_stats["link_fallbacks"], 1)
            self.assertEqual(motor._delivery_stats["physical_copies"], 1)

    def test_weak_reference_reports_coherent_orphan_group_without_assigning(self):
        with tempfile.TemporaryDirectory(prefix="facesync_weak_reference_") as tmp:
            root = Path(tmp)
            source = root / "FRANK"
            corrected = source / "FOTOS CORREGIDAS"
            reference = source / "IMG_2411.CR2"
            orphan_a = corrected / "IMG_2412.JPG"
            orphan_b = corrected / "IMG_2413.JPG"
            orphan_c = corrected / "IMG_2414.JPG"
            far_photo = corrected / "IMG_2428.JPG"
            for path in (reference, orphan_a, orphan_b, orphan_c, far_photo):
                self._write_image(path)

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            person = {
                "display_name": "AGUIRRE FIGUEROA",
                "folder_name": "AGUIRRE FIGUEROA",
                "folder_path": root / "resultado" / "AGUIRRE FIGUEROA",
                "reference_value": "2411",
                "reference_path": reference,
            }
            report = {
                "seleccion_rostros_referencia": [{
                    "persona": "AGUIRRE FIGUEROA",
                    "foto": "FRANK/IMG_2411.CR2",
                    "soporte_fotos": 0,
                    "score": 0.35,
                }]
            }
            embeddings = {
                reference: [[0.0, 1.0]],
                orphan_a: [[1.0, 0.0]],
                orphan_b: [[0.99, 0.01]],
                orphan_c: [[0.98, 0.02]],
                far_photo: [[0.0, -1.0]],
            }

            weak_refs, groups = motor._detect_weak_reference_orphan_groups(
                [person],
                [reference, orphan_a, orphan_b, orphan_c, far_photo],
                {reference.resolve(strict=False)},
                embeddings,
                report,
            )

            self.assertEqual(len(weak_refs), 1)
            self.assertEqual(weak_refs[0]["persona"], "AGUIRRE FIGUEROA")
            self.assertEqual(weak_refs[0]["grupos_candidatos_detectados"], 1)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["persona_sugerida"], "AGUIRRE FIGUEROA")
            self.assertEqual(groups[0]["numeros"], [2412, 2413, 2414])
            self.assertEqual(groups[0]["cantidad_fotos_unicas"], 3)
            self.assertGreater(groups[0]["distancia_minima_a_referencia"], motor.THRESHOLD_REVIEW)
            self.assertIn("FRANK/FOTOS CORREGIDAS/IMG_2412.JPG", groups[0]["fotos"])

    def test_weak_reference_orphan_delivery_keeps_motor_result_traceable(self):
        with tempfile.TemporaryDirectory(prefix="facesync_weak_reference_delivery_") as tmp:
            root = Path(tmp)
            source = root / "FRANK"
            corrected = source / "FOTOS CORREGIDAS"
            destination = root / "resultado"
            corrected_jpg = corrected / "IMG_2412.JPG"
            raw_jpg = source / "IMG_2412.JPG"
            raw_cr2 = source / "IMG_2412.CR2"
            corrected_jpg.parent.mkdir(parents=True, exist_ok=True)
            raw_jpg.parent.mkdir(parents=True, exist_ok=True)
            corrected_jpg.write_bytes(b"corrected jpg")
            raw_jpg.write_bytes(b"original jpg")
            raw_cr2.write_bytes(b"raw payload")

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            person = {
                "display_name": "AGUIRRE FIGUEROA",
                "folder_name": "AGUIRRE FIGUEROA",
                "folder_path": destination / "AGUIRRE FIGUEROA",
            }
            image_paths = [corrected_jpg, raw_jpg, raw_cr2]
            analyzed, cr2_twin_of, _omitted = motor._split_cr2_twins(image_paths)
            cr2_delivery_index = motor._build_cr2_delivery_index(image_paths)
            copied_sources = set()
            assigned_sources = set()
            report = {
                "copied": [],
                "reused": [],
                "conflicts": [],
                "errors": [],
                "fotos_por_persona": {"AGUIRRE FIGUEROA": []},
                "fotos_no_identificadas": [
                    "FRANK/FOTOS CORREGIDAS/IMG_2412.JPG",
                    "FRANK/IMG_2412.JPG",
                ],
                "fotos_ignoradas_no_asignadas": [
                    "FRANK/FOTOS CORREGIDAS/IMG_2412.JPG",
                    "FRANK/IMG_2412.JPG",
                ],
                "fotos_rescatadas_referencia_debil": [],
                "total_fotos_copiadas": 0,
                "cr2_gemelos_copiados": 0,
            }
            group = {
                "persona_sugerida": "AGUIRRE FIGUEROA",
                "referencia": "2411",
                "rango_numerico": "2412-2412",
                "cantidad_archivos_relacionados": 2,
                "distancia_promedio_grupo": 0.1,
                "distancia_minima_a_referencia": 0.84,
                "fotos": [
                    "FRANK/FOTOS CORREGIDAS/IMG_2412.JPG",
                    "FRANK/IMG_2412.JPG",
                ],
            }

            motor._deliver_weak_reference_orphan_groups(
                [person],
                analyzed,
                [group],
                copied_sources,
                assigned_sources,
                report,
                cr2_twin_of,
                cr2_delivery_index,
            )

            person_dir = destination / "AGUIRRE FIGUEROA"
            self.assertEqual((person_dir / "IMG_2412.JPG").read_bytes(), b"corrected jpg")
            self.assertEqual((person_dir / "IMG_2412.CR2").read_bytes(), b"raw payload")
            self.assertEqual(report["total_fotos_copiadas"], 1)
            self.assertEqual(report["cr2_gemelos_copiados"], 1)
            self.assertEqual(len(report["fotos_rescatadas_referencia_debil"]), 1)
            self.assertTrue(group["entregado_postmotor"])
            self.assertEqual(report["fotos_ignoradas_no_asignadas"], [])
            self.assertEqual(report["fotos_no_identificadas"], [])

    def test_weak_reference_duplicate_group_uses_global_tiebreaker(self):
        with tempfile.TemporaryDirectory(prefix="facesync_weak_reference_tiebreak_") as tmp:
            root = Path(tmp)
            source = root / "FRANK"
            destination = root / "resultado"
            photo_a = source / "IMG_2405.JPG"
            photo_b = source / "IMG_2406.JPG"
            photo_a.parent.mkdir(parents=True, exist_ok=True)
            photo_a.write_bytes(b"photo 2405")
            photo_b.write_bytes(b"photo 2406")

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            people = [
                {
                    "display_name": "AGUIRRE FIGUEROA",
                    "folder_name": "AGUIRRE FIGUEROA",
                    "folder_path": destination / "AGUIRRE FIGUEROA",
                },
                {
                    "display_name": "ARMENTA CHICO",
                    "folder_name": "ARMENTA CHICO",
                    "folder_path": destination / "ARMENTA CHICO",
                },
            ]
            image_paths = [photo_a, photo_b]
            report = {
                "copied": [],
                "reused": [],
                "conflicts": [],
                "errors": [],
                "fotos_por_persona": {
                    "AGUIRRE FIGUEROA": [],
                    "ARMENTA CHICO": [],
                },
                "fotos_no_identificadas": ["FRANK/IMG_2405.JPG", "FRANK/IMG_2406.JPG"],
                "fotos_ignoradas_no_asignadas": ["FRANK/IMG_2405.JPG", "FRANK/IMG_2406.JPG"],
                "fotos_rescatadas_referencia_debil": [],
                "total_fotos_copiadas": 0,
                "cr2_gemelos_copiados": 0,
            }
            shared_fotos = ["FRANK/IMG_2405.JPG", "FRANK/IMG_2406.JPG"]
            aguirre_claim = {
                "persona_sugerida": "AGUIRRE FIGUEROA",
                "referencia": "2411",
                "numeros": [2405, 2406],
                "rango_numerico": "2405-2406",
                "cantidad_archivos_relacionados": 2,
                "distancia_promedio_grupo": 0.1,
                "distancia_minima_a_referencia": 0.84,
                "fotos": list(shared_fotos),
            }
            armenta_claim = {
                "persona_sugerida": "ARMENTA CHICO",
                "referencia": "2405",
                "numeros": [2405, 2406],
                "rango_numerico": "2405-2406",
                "cantidad_archivos_relacionados": 2,
                "distancia_promedio_grupo": 0.1,
                "distancia_minima_a_referencia": 0.84,
                "fotos": list(shared_fotos),
            }

            motor._deliver_weak_reference_orphan_groups(
                people,
                image_paths,
                [aguirre_claim, armenta_claim],
                set(),
                set(),
                report,
                {},
                {},
            )

            self.assertFalse((destination / "AGUIRRE FIGUEROA" / "IMG_2405.JPG").exists())
            self.assertEqual((destination / "ARMENTA CHICO" / "IMG_2405.JPG").read_bytes(), b"photo 2405")
            self.assertEqual((destination / "ARMENTA CHICO" / "IMG_2406.JPG").read_bytes(), b"photo 2406")
            self.assertEqual(report["total_fotos_copiadas"], 2)
            self.assertEqual(len(report["fotos_rescatadas_referencia_debil"]), 2)
            self.assertTrue(aguirre_claim["resuelto_por_otro_grupo"])
            self.assertEqual(aguirre_claim["grupo_ganador"], "ARMENTA CHICO")
            self.assertTrue(armenta_claim["entregado_postmotor"])
            self.assertEqual(report["fotos_ignoradas_no_asignadas"], [])
            self.assertEqual(report["fotos_no_identificadas"], [])

    def test_reference_collision_repair_reanchors_strong_crossed_reference(self):
        with tempfile.TemporaryDirectory(prefix="facesync_reference_collision_") as tmp:
            root = Path(tmp)
            source = root / "FRANK"
            source.mkdir(parents=True, exist_ok=True)
            owner_ref_path = source / "2405.CR2"
            target_ref_path = source / "2462.CR2"
            owner_a = source / "IMG_2405.JPG"
            owner_b = source / "IMG_2406.JPG"
            target_a = source / "IMG_2462.JPG"
            target_b = source / "IMG_2463.JPG"
            for path in (owner_ref_path, target_ref_path, owner_a, owner_b, target_a, target_b):
                self._write_image(path)

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            owner = {
                "display_name": "ARMENTA CHICO",
                "folder_name": "ARMENTA CHICO",
                "reference_value": "2405",
            }
            target = {
                "display_name": "ARRIOVIVEZ OTHON",
                "folder_name": "ARRIOVIVEZ OTHON",
                "reference_value": "2462",
            }
            refs = [
                {
                    "person": owner,
                    "path": owner_ref_path,
                    "embedding": [1.0, 0.0],
                    "candidate_faces": [{"embedding": [1.0, 0.0]}],
                },
                {
                    "person": target,
                    # Deliberately crossed: the 2462 reference contains the
                    # same face as Armenta, not the 2462 numeric cluster.
                    "path": target_ref_path,
                    "embedding": [0.999, 0.01],
                    "candidate_faces": [{"embedding": [0.999, 0.01]}],
                },
            ]
            photo_embeddings = {
                owner_ref_path: [[1.0, 0.0]],
                target_ref_path: [[0.999, 0.01]],
                owner_a: [[0.998, 0.02]],
                owner_b: [[0.995, 0.03]],
                target_a: [[0.0, 1.0]],
                target_b: [[0.01, 0.999]],
            }
            match_map = {
                owner_a: [{"person": owner, "distance": 0.02, "face_index": 0}],
                owner_b: [{"person": owner, "distance": 0.03, "face_index": 0}],
                target_ref_path: [{"person": target, "distance": 0.01, "face_index": 0}],
                target_a: [{"person": target, "distance": 0.01, "face_index": 0}],
                target_b: [{"person": target, "distance": 0.02, "face_index": 0}],
            }
            report = {
                "auditoria_referencias_cruzadas": [],
                "seleccion_rostros_referencia": [
                    {"persona": "ARRIOVIVEZ OTHON"}
                ],
            }

            motor._audit_reference_collisions(
                [owner, target], refs, photo_embeddings, match_map, report
            )

            self.assertEqual(len(report["auditoria_referencias_cruzadas"]), 1)
            audit = report["auditoria_referencias_cruzadas"][0]
            self.assertEqual(audit["persona"], "ARRIOVIVEZ OTHON")
            self.assertEqual(audit["cruzada_con"], "ARMENTA CHICO")
            self.assertEqual(audit["grupo_reparacion"], "2462-2463")
            self.assertTrue(refs[1]["reference_collision_repaired"])
            self.assertLess(motor._cosine_distance(refs[1]["embedding"], [0.0, 1.0]), 0.01)
            self.assertNotIn(owner_a, [key for key in match_map if any(
                m.get("person", {}).get("folder_name") == "ARRIOVIVEZ OTHON"
                for m in match_map.get(key, [])
            )])
            target_matches = [
                key for key, matches in match_map.items()
                if any(m.get("person", {}).get("folder_name") == "ARRIOVIVEZ OTHON"
                       for m in matches)
            ]
            self.assertEqual(set(target_matches), {target_a, target_b})
            self.assertTrue(any(
                m.get("person", {}).get("folder_name") == "ARMENTA CHICO"
                for m in match_map[target_ref_path]
            ))

    def test_reference_collision_global_evidence_repairs_far_numeric_session(self):
        """A crossed strong reference can be far from the owner's numbers.

        The post-motor audit must use the coherent assigned-face evidence, not
        only the +/- numeric window around the Excel code.
        """
        with tempfile.TemporaryDirectory(prefix="facesync_reference_collision_global_") as tmp:
            root = Path(tmp)
            source = root / "FRANK"
            source.mkdir(parents=True, exist_ok=True)
            owner_ref_path = source / "2405.CR2"
            target_ref_path = source / "2462.CR2"
            owner_paths = [source / f"IMG_{number}.JPG" for number in (3000, 3001, 3002)]
            target_paths = [source / f"IMG_{number}.JPG" for number in (2700, 2701, 2702)]
            for path in [owner_ref_path, target_ref_path, *owner_paths, *target_paths]:
                self._write_image(path)

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            owner = {
                "display_name": "ARMENTA CHICO",
                "folder_name": "ARMENTA CHICO",
                "reference_value": "2405",
            }
            target = {
                "display_name": "ARRIOVIVEZ OTHON",
                "folder_name": "ARRIOVIVEZ OTHON",
                "reference_value": "2462",
            }
            refs = [
                {
                    "person": owner,
                    "path": owner_ref_path,
                    "embedding": [1.0, 0.0],
                    "candidate_faces": [{"embedding": [1.0, 0.0]}],
                },
                {
                    "person": target,
                    "path": target_ref_path,
                    # The target reference is actually the owner's face.
                    "embedding": [0.999, 0.01],
                    "candidate_faces": [{"embedding": [0.999, 0.01]}],
                },
            ]
            photo_embeddings = {
                owner_ref_path: [[1.0, 0.0]],
                target_ref_path: [[0.999, 0.01]],
            }
            match_map = {
                target_ref_path: [{"person": target, "distance": 0.01, "face_index": 0}],
            }
            for index, path in enumerate(owner_paths):
                embedding = [1.0, 0.01 * (index + 1)]
                photo_embeddings[path] = [embedding]
                match_map[path] = [{"person": owner, "distance": 0.02, "face_index": 0}]
            for index, path in enumerate(target_paths):
                embedding = [0.01 * (index + 1), 1.0]
                photo_embeddings[path] = [embedding]
                match_map[path] = [{"person": target, "distance": 0.02, "face_index": 0}]

            report = {
                "auditoria_referencias_cruzadas": [],
                "seleccion_rostros_referencia": [{"persona": "ARRIOVIVEZ OTHON"}],
            }

            motor._audit_reference_collisions(
                [owner, target], refs, photo_embeddings, match_map, report
            )

            self.assertEqual(len(report["auditoria_referencias_cruzadas"]), 1)
            audit = report["auditoria_referencias_cruzadas"][0]
            self.assertEqual(audit["cruzada_con"], "ARMENTA CHICO")
            self.assertEqual(audit["fuente_grupo"], "asignaciones_seguras_postmotor")
            self.assertTrue(refs[1]["reference_collision_repaired"])
            self.assertLess(motor._cosine_distance(refs[1]["embedding"], [0.0, 1.0]), 0.01)
            self.assertTrue(any(
                m.get("person", {}).get("folder_name") == "ARMENTA CHICO"
                for m in match_map[target_ref_path]
            ))
            for path in target_paths:
                self.assertTrue(any(
                    m.get("person", {}).get("folder_name") == "ARRIOVIVEZ OTHON"
                    for m in match_map[path]
                ))
            gallery, _stats = motor._build_identity_gallery(
                refs, match_map, photo_embeddings
            )
            confirmed, _review, _conflicts, _rescues = motor._resolve_assignments(
                match_map,
                ambiguity_margin=0.03,
                gallery_data=gallery,
                photo_face_embeddings=photo_embeddings,
            )
            for path in target_paths:
                self.assertEqual(
                    confirmed[path][0]["folder_name"],
                    "ARRIOVIVEZ OTHON",
                )

    def test_weak_reference_partial_overlap_uses_numeric_global_winner(self):
        with tempfile.TemporaryDirectory(prefix="facesync_weak_reference_overlap_") as tmp:
            root = Path(tmp)
            source = root / "FRANK"
            destination = root / "resultado"
            paths = [source / f"IMG_{number}.JPG" for number in (2412, 2413, 2414)]
            source.mkdir(parents=True, exist_ok=True)
            for path in paths:
                self._write_image(path)

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            people = [
                {
                    "display_name": "AGUIRRE FIGUEROA",
                    "folder_name": "AGUIRRE FIGUEROA",
                    "folder_path": destination / "AGUIRRE FIGUEROA",
                },
                {
                    "display_name": "ARMENTA CHICO",
                    "folder_name": "ARMENTA CHICO",
                    "folder_path": destination / "ARMENTA CHICO",
                },
            ]
            report = {
                "copied": [],
                "reused": [],
                "conflicts": [],
                "errors": [],
                "fotos_por_persona": {
                    "AGUIRRE FIGUEROA": [],
                    "ARMENTA CHICO": [],
                },
                "fotos_no_identificadas": [
                    f"FRANK/IMG_{number}.JPG" for number in (2412, 2413, 2414)
                ],
                "fotos_ignoradas_no_asignadas": [
                    f"FRANK/IMG_{number}.JPG" for number in (2412, 2413, 2414)
                ],
                "fotos_rescatadas_referencia_debil": [],
                "total_fotos_copiadas": 0,
                "cr2_gemelos_copiados": 0,
            }
            shared = [f"FRANK/IMG_{number}.JPG" for number in (2412, 2413)]
            aguirre_group = {
                "persona_sugerida": "AGUIRRE FIGUEROA",
                "referencia": "2411",
                "numeros": [2412, 2413, 2414],
                "rango_numerico": "2412-2414",
                "distancia_promedio_grupo": 0.1,
                "distancia_minima_a_referencia": 0.84,
                "fotos": shared + ["FRANK/IMG_2414.JPG"],
            }
            armenta_group = {
                "persona_sugerida": "ARMENTA CHICO",
                "referencia": "2405",
                "numeros": [2412, 2413],
                "rango_numerico": "2412-2413",
                "distancia_promedio_grupo": 0.1,
                "distancia_minima_a_referencia": 0.84,
                "fotos": list(shared),
            }

            motor._deliver_weak_reference_orphan_groups(
                people,
                paths,
                [armenta_group, aguirre_group],
                set(),
                set(),
                report,
                {},
                {},
            )

            aguirre_dir = destination / "AGUIRRE FIGUEROA"
            self.assertTrue((aguirre_dir / "IMG_2412.JPG").is_file())
            self.assertTrue((aguirre_dir / "IMG_2413.JPG").is_file())
            self.assertTrue((aguirre_dir / "IMG_2414.JPG").is_file())
            self.assertFalse((destination / "ARMENTA CHICO" / "IMG_2412.JPG").exists())
            self.assertTrue(armenta_group["resuelto_por_otro_grupo"])
            self.assertEqual(armenta_group["grupo_ganador"], "AGUIRRE FIGUEROA")
            self.assertEqual(report["total_fotos_copiadas"], 3)

    def test_cr2_delivery_finds_raw_twin_from_different_source_folder(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cross_folder_cr2_") as tmp:
            root = Path(tmp)
            source = root / "FRANK"
            corrected = source / "FOTOS CORREGIDAS"
            destination = root / "resultado" / "AGUIRRE FIGUEROA"
            raw_jpg = source / "IMG_2405.JPG"
            raw_cr2 = source / "IMG_2405.CR2"
            corrected_jpg = corrected / "IMG_2405.JPG"
            raw_jpg.parent.mkdir(parents=True, exist_ok=True)
            corrected_jpg.parent.mkdir(parents=True, exist_ok=True)
            raw_jpg.write_bytes(b"original jpg")
            raw_cr2.write_bytes(b"raw payload")
            corrected_jpg.write_bytes(b"corrected jpg")

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            image_paths = [corrected_jpg, raw_cr2, raw_jpg]

            analyzed, cr2_twin_of, omitted = motor._split_cr2_twins(image_paths)
            cr2_delivery_index = motor._build_cr2_delivery_index(image_paths)
            copied = motor._copy_cr2_twin(
                corrected_jpg, destination, cr2_twin_of, cr2_delivery_index)

            self.assertEqual(omitted, 1)
            self.assertNotIn(raw_cr2, analyzed)
            self.assertEqual(copied, 1)
            self.assertEqual((destination / "IMG_2405.CR2").read_bytes(), b"raw payload")

    def test_reference_matching_delivers_corrected_jpg_with_cross_folder_cr2(self):
        with tempfile.TemporaryDirectory(prefix="facesync_cross_folder_cr2_flow_") as tmp:
            root = Path(tmp)
            source = root / "FRANK"
            corrected = source / "FOTOS CORREGIDAS"
            destination = root / "resultado"
            table = root / "personas.csv"
            raw_jpg = source / "IMG_2405.JPG"
            raw_cr2 = source / "IMG_2405.CR2"
            corrected_jpg = corrected / "IMG_2405.JPG"
            raw_jpg.parent.mkdir(parents=True, exist_ok=True)
            corrected_jpg.parent.mkdir(parents=True, exist_ok=True)
            table.write_text("Nombre,Foto\nAGUIRRE FIGUEROA,NO_REF\n", encoding="utf-8")
            raw_jpg.write_bytes(b"original jpg")
            raw_cr2.write_bytes(b"raw payload")
            corrected_jpg.write_bytes(b"corrected jpg")

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            report = motor.run_reference_face_matching(
                table_path=str(table),
                name_column="Nombre",
                reference_column="Foto",
                source_folder=str(source),
                destination_folder=str(destination),
                mock_face_matches={
                    "AGUIRRE FIGUEROA": ["FRANK/FOTOS CORREGIDAS/IMG_2405.JPG"],
                },
            )

            person_dir = destination / "AGUIRRE FIGUEROA"
            self.assertTrue(report.get("success"), report.get("error"))
            self.assertEqual((person_dir / "IMG_2405.JPG").read_bytes(), b"corrected jpg")
            self.assertEqual((person_dir / "IMG_2405.CR2").read_bytes(), b"raw payload")
            self.assertEqual(report["cr2_gemelos_copiados"], 1)
            self.assertEqual(report["archivos_entregados_totales"], 2)

    def test_cr2_preview_index_is_broad_but_excludes_clear_non_candidates(self):
        with tempfile.TemporaryDirectory(prefix="facesync_preview_index_") as tmp:
            root = Path(tmp)
            reference = root / "reference.cr2"
            likely = root / "likely.cr2"
            unrelated = root / "unrelated.cr2"
            no_preview_face = root / "no_preview_face.cr2"
            image_paths = [reference, likely, unrelated, no_preview_face]
            person = {"display_name": "ANA", "folder_name": "ANA"}
            refs = [{
                "person": person,
                "path": reference,
                "candidate_faces": [{"embedding": [1.0, 0.0]}],
            }]
            preview_embeddings = {
                likely: [{"embedding": [0.99, 0.01], "face_confidence": 0.99}],
                unrelated: [{"embedding": [0.0, 1.0], "face_confidence": 0.99}],
                no_preview_face: [],
            }
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            with (
                patch.dict(os.environ, {
                    "FACESYNC_FAST_INDEX": "force",
                    "FACESYNC_FAST_INDEX_DISTANCE": "0.20",
                }),
                patch.object(motor, "FAST_INDEX_TOP_PER_IDENTITY", 1),
                patch.object(motor, "FAST_INDEX_NEIGHBOR_RADIUS", 0),
                patch.object(
                    motor,
                    "_cr2_preview_to_jpeg",
                    side_effect=lambda path: (path.with_suffix(".jpg"), "cached"),
                ),
                patch.object(
                    motor,
                    "_get_all_face_embeddings",
                    side_effect=lambda path, **_kwargs: preview_embeddings[path],
                ),
            ):
                selected, stats = motor._select_index_candidates(
                    refs,
                    image_paths,
                    model_name="ArcFace",
                    detector_backend="retinaface",
                    DeepFace=object(),
                )

            self.assertEqual(selected, [reference, likely, no_preview_face])
            self.assertTrue(stats["enabled"])
            self.assertEqual(stats["selected_photos"], 3)
            self.assertEqual(stats["preview_no_faces_promoted"], 1)
            self.assertNotIn(unrelated, selected)

    def test_preview_arcface_batch_preserves_results_per_image(self):
        with tempfile.TemporaryDirectory(prefix="facesync_preview_batch_") as tmp:
            root = Path(tmp)
            first = root / "first.cr2"
            second = root / "second.cr2"
            first_preview = root / "first.jpg"
            second_preview = root / "second.jpg"
            calls = []

            class FakeDeepFace:
                @staticmethod
                def represent(**kwargs):
                    calls.append(kwargs["img_path"])
                    return [
                        [{
                            "embedding": [1.0, 0.0],
                            "face_confidence": 0.91,
                            "facial_area": {"x": 1},
                        }],
                        [{
                            "embedding": [0.0, 1.0],
                            "face_confidence": 0.92,
                            "facial_area": {"x": 2},
                        }],
                    ]

            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            metrics = {}
            result = motor._get_preview_embeddings_batch(
                [(first, first_preview), (second, second_preview)],
                model_name="ArcFace",
                detector_backend="retinaface",
                DeepFace=FakeDeepFace,
                metrics=metrics,
            )

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0], [str(first_preview), str(second_preview)])
            self.assertEqual(result[first][0]["embedding"], [1.0, 0.0])
            self.assertEqual(result[second][0]["embedding"], [0.0, 1.0])
            self.assertEqual(metrics["arcface_batch_calls"], 1)
            self.assertEqual(metrics["arcface_batched_images"], 2)

    def test_full_motor_only_processes_union_selected_by_preview_index(self):
        with tempfile.TemporaryDirectory(prefix="facesync_index_integration_") as tmp:
            root = Path(tmp)
            reference = root / "reference.cr2"
            selected_photo = root / "selected.cr2"
            excluded_photo = root / "excluded.cr2"
            person = {
                "display_name": "ANA",
                "folder_name": "ANA",
                "reference_path": reference,
            }
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)
            deepface_module = types.ModuleType("deepface")
            deepface_module.DeepFace = object()

            def embeddings(path, **_kwargs):
                if path == excluded_photo:
                    self.fail("Una foto excluida por el indice llego al motor completo")
                return [{
                    "embedding": [1.0, 0.0],
                    "face_confidence": 0.99,
                    "facial_area": {},
                }]

            def select_reference(refs, _photo_faces):
                chosen = dict(refs[0])
                chosen["embedding"] = [1.0, 0.0]
                chosen["embeddings"] = [[1.0, 0.0]]
                return [chosen], [], []

            with (
                patch.dict(sys.modules, {"deepface": deepface_module}),
                patch.object(motor, "_enable_gpu_backend", return_value={}),
                patch.object(motor, "_disable_gpu_backend"),
                patch.object(motor, "_get_all_face_embeddings", side_effect=embeddings),
                patch.object(
                    motor,
                    "_select_index_candidates",
                    return_value=(
                        [reference, selected_photo],
                        {"enabled": True, "selected_photos": 2, "total_photos": 3},
                    ),
                ),
                patch.object(
                    motor,
                    "_select_reference_faces_by_recurrence",
                    side_effect=select_reference,
                ),
            ):
                matches, errors = motor._collect_deepface_matches(
                    [person],
                    [reference, selected_photo, excluded_photo],
                    threshold=0.85,
                    model_name="ArcFace",
                    detector_backend="retinaface",
                )

            self.assertIn(reference, matches)
            self.assertIn(selected_photo, matches)
            self.assertNotIn(excluded_photo, matches)
            self.assertEqual(errors["facial_index_stats"]["selected_photos"], 2)

    def test_gallery_consensus_resolves_close_reference_conflict(self):
        with tempfile.TemporaryDirectory(prefix="facesync_gallery_conflict_") as tmp:
            root = Path(tmp)
            photo = root / "photo.jpg"
            self._write_image(photo)
            ana = {"display_name": "ANA", "folder_name": "ANA", "folder_path": root / "ANA"}
            luis = {"display_name": "LUIS", "folder_name": "LUIS", "folder_path": root / "LUIS"}
            match_map = {photo: [
                {"person": ana, "distance": 0.34, "face_index": 0, "match_type": "review"},
                {"person": luis, "distance": 0.35, "face_index": 0, "match_type": "review"},
            ]}
            gallery = {
                "ANA": {"person": ana, "embeddings": [[1.0, 0.0], [0.9, 0.1]], "paths": [], "times": []},
                "LUIS": {"person": luis, "embeddings": [[0.0, 1.0], [0.1, 0.9]], "paths": [], "times": []},
            }
            security = SecurityManager(str(root), app_data_root=str(root / "AppData"))
            motor = FaceSyncCapabilities(str(root), security_manager=security)

            def fake_rescue(_face, embeddings, **_kwargs):
                is_ana = embeddings[0] == [1.0, 0.0]
                return {
                    "rescued": is_ana,
                    "best_gallery_distance": 0.4 if is_ana else 0.8,
                    "avg_top3": 0.5,
                    "supporter_avg": 0.5 if is_ana else 0.8,
                    "supporter_count": 2 if is_ana else 0,
                    "temporal_support": True,
                }

            with patch.object(motor, "_try_gallery_rescue", side_effect=fake_rescue):
                confirmed, review, conflicts, rescues = motor._resolve_assignments(
                    match_map,
                    ambiguity_margin=0.03,
                    gallery_data=gallery,
                    photo_face_embeddings={photo: [[1.0, 0.0]]},
                )

            self.assertEqual(confirmed[photo][0]["display_name"], "ANA")
            self.assertFalse(review)
            self.assertFalse(conflicts)
            self.assertEqual(len(rescues), 1)

    def test_tauri_bridge_routes_direct_action_to_modern_engine(self):
        bridge_path = Path(__file__).resolve().parents[1] / "bridge.py"
        source = bridge_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        classify = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "cmd_classify_start"
        )
        function_source = ast.get_source_segment(source, classify) or ""
        self.assertIn("FaceSyncCapabilities", function_source)
        self.assertIn("run_reference_face_matching", function_source)
        self.assertIn("account_id=_email(args)", function_source)
        self.assertNotIn("motor_ia_fast", function_source)

    def test_bridge_enables_legacy_keras_before_application_imports(self):
        bridge_path = Path(__file__).resolve().parents[1] / "bridge.py"
        source = bridge_path.read_text(encoding="utf-8")

        compatibility_flag = 'os.environ["TF_USE_LEGACY_KERAS"] = "1"'
        first_application_import = "from core.path_policy import"

        self.assertIn(compatibility_flag, source)
        self.assertIn(first_application_import, source)
        self.assertLess(
            source.index(compatibility_flag),
            source.index(first_application_import),
            "La compatibilidad Keras debe activarse antes de cualquier import de la app.",
        )

    def test_tauri_launcher_enables_legacy_keras_for_packaged_engine(self):
        launcher_path = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src-tauri"
            / "src"
            / "lib.rs"
        )
        source = launcher_path.read_text(encoding="utf-8")

        compatibility_flag = '.env("TF_USE_LEGACY_KERAS", "1")'
        spawn_call = ".spawn()"

        self.assertIn(compatibility_flag, source)
        self.assertLess(source.index(compatibility_flag), source.index(spawn_call))


if __name__ == "__main__":
    unittest.main()
