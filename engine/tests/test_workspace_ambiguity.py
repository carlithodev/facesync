import tempfile
import unittest
from pathlib import Path

from core.context_manager import ContextManager
from core.dialogue_manager import DialogueManager
from core.intent_interpreter import IntentInterpreter
from core.local_command_router import LocalCommandRouter
from core.text_normalizer import TextNormalizer
from core.workspace_location_resolver import WorkspaceLocationResolver


class WorkspaceAmbiguityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="facesync_ambiguity_")
        self.root = Path(self.temp.name) / "workspace"
        self.app_data = Path(self.temp.name) / "appdata"
        self.root.mkdir()
        self.app_data.mkdir()
        for relative in (
            "fotos/FRANK",
            "piloto2/502m/Frank",
            "piloto2/501m",
        ):
            (self.root / relative).mkdir(parents=True)
        self.state = {
            "project_root": str(self.root),
            "workspace_actual": str(self.root),
            "workspace_roots": [str(self.root)],
            "available_folders": [
                "fotos/FRANK",
                "piloto2/502m/Frank",
                "piloto2/501m",
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_duplicate_basename_is_ambiguous_instead_of_first_match(self):
        result = WorkspaceLocationResolver().resolve("Frank", self.state, kind="folder")

        self.assertFalse(result.success)
        self.assertTrue(result.ambiguous)
        self.assertEqual(2, len(result.candidates))
        self.assertTrue(any("fotos" in value.lower() for value in result.candidates))
        self.assertTrue(any("502m" in value.lower() for value in result.candidates))

    def test_parent_qualified_reference_resolves_one_folder(self):
        result = WorkspaceLocationResolver().resolve("502m/Frank", self.state, kind="folder")

        self.assertTrue(result.success)
        self.assertFalse(result.ambiguous)
        self.assertTrue(result.relative_path.replace("\\", "/").endswith("piloto2/502m/Frank"))

    def test_every_existing_path_slot_uses_ambiguity_gate(self):
        (self.root / "a" / "501m").mkdir(parents=True)
        (self.root / "b" / "501m").mkdir(parents=True)
        (self.root / "a" / "lista.xlsx").write_bytes(b"one")
        (self.root / "b" / "lista.xlsx").write_bytes(b"two")
        resolver = WorkspaceLocationResolver()

        _, destination_issue = resolver.resolve_args(
            "move_item",
            {"target": "502m/Frank", "destination_folder": "501m"},
            self.state,
        )
        _, table_issue = resolver.resolve_args(
            "read_document",
            {"table_path": "lista.xlsx"},
            self.state,
        )

        self.assertIsNotNone(destination_issue)
        self.assertEqual("destination_folder", destination_issue.location_field)
        self.assertGreaterEqual(len(destination_issue.candidates), 3)
        self.assertIsNotNone(table_issue)
        self.assertEqual("table_path", table_issue.location_field)
        self.assertEqual(2, len(table_issue.candidates))

    def test_contextual_variants_produce_canonical_paths(self):
        context = ContextManager()
        context.current_context["last_created_items"] = ["piloto2/502m/Frank"]
        expected = {
            "elimina la carpeta Frank dentro de 502m": ("delete_item", "502m/Frank", ""),
            "borra Frank que esta en 502m": ("delete_item", "502m/Frank", ""),
            "pasa la carpeta Frank de 502m a 501m": ("move_item", "502m/Frank", "501m"),
            "copia Frank de 502m dentro de 501m": ("copy_item", "502m/Frank", "501m"),
            "duplica la carpeta que acabas de crear en 501m": ("copy_item", "piloto2/502m/Frank", "501m"),
            "renombra Frank dentro de 502m a Paco": ("rename_item", "502m/Frank", ""),
        }

        for phrase, (intent, target, destination) in expected.items():
            with self.subTest(phrase=phrase):
                interpretation = IntentInterpreter.interpret(
                    phrase,
                    TextNormalizer.normalize(phrase),
                    context,
                )
                args = interpretation["args"]
                self.assertEqual(intent, interpretation["intent"])
                self.assertEqual(target, args.get("target") or args.get("source"))
                self.assertEqual(destination, args.get("destination") or args.get("destination_folder") or "")

    def test_pending_choice_accepts_number_or_parent_hint(self):
        candidates = [
            str(self.root / "fotos" / "FRANK"),
            str(self.root / "piloto2" / "502m" / "Frank"),
        ]
        pending = {
            "pipeline": "structured",
            "intent": "delete_item",
            "args": {
                "target": "Frank",
                "_location_candidates": candidates,
                "_location_field": "target",
            },
            "missing_slot": "target",
            "missing_fields": ["target"],
            "location_candidates": candidates,
            "location_field": "target",
            "question": "Cual quieres usar?",
        }
        dialogue = DialogueManager(ContextManager())

        by_number = dialogue.classify_message("2", {"pending_action": pending})
        by_parent = dialogue.classify_message("la de 502m", {"pending_action": pending})
        still_ambiguous = dialogue.classify_message("Frank", {"pending_action": pending})
        single = dict(pending)
        single["location_candidates"] = [candidates[1]]
        single["args"] = {**pending["args"], "_location_candidates": [candidates[1]]}
        confirmed_suggestion = dialogue.classify_message("si", {"pending_action": single})

        self.assertEqual(candidates[1], by_number["completed_action"]["args"]["target"])
        self.assertEqual(candidates[1], by_parent["completed_action"]["args"]["target"])
        self.assertIsNone(still_ambiguous.get("completed_action"))
        self.assertIn("Cual quieres", still_ambiguous["response"])
        self.assertEqual(candidates[1], confirmed_suggestion["completed_action"]["args"]["target"])

    def test_router_blocks_delete_and_move_until_duplicate_is_selected(self):
        context = ContextManager()
        context.set_app_data_root(str(self.app_data))
        router = LocalCommandRouter(str(self.root), context, account_id="ambiguity@test.local")

        delete_result = router.try_handle("elimina la carpeta Frank")
        self.assertTrue(delete_result.requires_clarification)
        self.assertIn("varias ubicaciones", delete_result.message.lower())
        self.assertTrue((self.root / "fotos" / "FRANK").exists())
        self.assertTrue((self.root / "piloto2" / "502m" / "Frank").exists())

        selected = router.try_handle("la de 502m")
        self.assertTrue(selected.requires_clarification)
        self.assertIn("piloto2/502m/Frank", selected.message.replace("\\", "/"))
        self.assertTrue((self.root / "piloto2" / "502m" / "Frank").exists())

        router.try_handle("no")
        move_result = router.try_handle("mueve Frank a 501m")
        self.assertTrue(move_result.requires_clarification)
        self.assertIn("varias ubicaciones", move_result.message.lower())
        self.assertTrue((self.root / "fotos" / "FRANK").exists())
        self.assertTrue((self.root / "piloto2" / "502m" / "Frank").exists())

    def test_parent_qualified_move_uses_the_intended_duplicate(self):
        context = ContextManager()
        context.set_app_data_root(str(self.app_data))
        router = LocalCommandRouter(str(self.root), context, account_id="qualified@test.local")

        result = router.try_handle("pasa la carpeta Frank de 502m a 501m")

        self.assertFalse(result.requires_clarification)
        self.assertFalse((self.root / "piloto2" / "502m" / "Frank").exists())
        self.assertTrue((self.root / "piloto2" / "501m" / "Frank").exists())
        self.assertTrue((self.root / "fotos" / "FRANK").exists())

    def test_location_choices_survive_account_session_restore(self):
        candidates = [
            str(self.root / "fotos" / "FRANK"),
            str(self.root / "piloto2" / "502m" / "Frank"),
        ]
        context = ContextManager()
        context.set_app_data_root(str(self.app_data))
        context.set_user_key("restore@test.local")
        context.set_project_root(str(self.root))
        context.save_pending_action_to_vault(
            "delete_item",
            {
                "target": "Frank",
                "_location_candidates": candidates,
                "_location_field": "target",
                "_location_query": "Frank",
            },
            ["target"],
            preview_text="Cual quieres usar?",
        )
        context.detach_runtime()

        restored = ContextManager()
        restored.set_app_data_root(str(self.app_data))
        restored.set_user_key("restore@test.local")
        restored.set_project_root(str(self.root))
        restored.restore_from_vault()
        pending = restored.get_pending_action()

        self.assertEqual("target", pending["missing_slot"])
        self.assertEqual(candidates, pending["location_candidates"])
        answer = DialogueManager(restored).classify_message("la de 502m", restored.current_context)
        self.assertEqual(candidates[1], answer["completed_action"]["args"]["target"])


if __name__ == "__main__":
    unittest.main()
