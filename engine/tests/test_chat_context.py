from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.context_manager import ContextManager
from core.context_vault import ContextVault


class ChatContextIsolationTests(unittest.TestCase):
    def test_active_thread_resumes_and_accounts_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "context.db"
            project = Path(tmp) / "workspace"
            project.mkdir()

            vault = ContextVault(db_path=db_path).initialize()
            user_a = vault.get_or_create_user("cuenta-a")
            user_b = vault.get_or_create_user("cuenta-b")
            project_a = vault.get_or_create_project(user_a, project)
            project_b = vault.get_or_create_project(user_b, project)
            session_a = vault.get_or_start_session(user_a, project_a)
            session_b = vault.get_or_start_session(user_b, project_b)
            vault.save_message(session_a, "user", "mensaje privado de A")
            vault.save_message(session_b, "user", "mensaje privado de B")
            vault.close()

            reopened = ContextVault(db_path=db_path).initialize()
            self.assertEqual(session_a, reopened.get_or_start_session(user_a, project_a))
            self.assertEqual(session_b, reopened.get_or_start_session(user_b, project_b))
            self.assertEqual(
                ["mensaje privado de A"],
                [item["content"] for item in reopened.get_session_messages(session_a)],
            )
            self.assertEqual(
                ["mensaje privado de B"],
                [item["content"] for item in reopened.get_session_messages(session_b)],
            )
            reopened.close()

    def test_context_manager_restores_only_the_current_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_data = Path(tmp) / "appdata"
            project = Path(tmp) / "workspace"
            project.mkdir()

            first = ContextManager()
            first.set_app_data_root(app_data)
            first.set_user_key("cuenta-a")
            first.set_project_root(project)
            first.add_message("user", "recuerda este Excel")
            first.add_message("assistant", "de acuerdo")
            first.detach_runtime()

            restored = ContextManager()
            restored.set_app_data_root(app_data)
            restored.set_user_key("cuenta-a")
            restored.set_project_root(project)
            history = restored.restore_from_vault()
            self.assertEqual(
                ["recuerda este Excel", "de acuerdo"],
                [item["content"] for item in history],
            )

            other = ContextManager()
            other.set_app_data_root(app_data)
            other.set_user_key("cuenta-b")
            other.set_project_root(project)
            self.assertEqual([], other.restore_from_vault())

    def test_new_conversation_does_not_replay_previous_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_data = Path(tmp) / "appdata"
            project = Path(tmp) / "workspace"
            project.mkdir()

            context = ContextManager()
            context.set_app_data_root(app_data)
            context.set_user_key("cuenta-a")
            context.set_project_root(project)
            context.add_message("user", "conversacion anterior")
            context.start_new_conversation()
            context.add_message("user", "conversacion nueva")
            context.detach_runtime()

            restored = ContextManager()
            restored.set_app_data_root(app_data)
            restored.set_user_key("cuenta-a")
            restored.set_project_root(project)
            self.assertEqual(
                ["conversacion nueva"],
                [item["content"] for item in restored.restore_from_vault()],
            )

    def test_older_turns_survive_as_rolling_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_data = Path(tmp) / "appdata"
            project = Path(tmp) / "workspace"
            project.mkdir()

            context = ContextManager(max_messages=4)
            context.set_app_data_root(app_data)
            context.set_user_key("cuenta-a")
            context.set_project_root(project)
            context.add_message("user", "mensaje antiguo importante")
            context.add_message("assistant", "respuesta antigua")
            context.add_message("user", "mensaje tres")
            context.add_message("assistant", "respuesta cuatro")
            context.add_message("user", "mensaje cinco")
            context.add_message("assistant", "respuesta seis")
            context.detach_runtime()

            restored = ContextManager(max_messages=4)
            restored.set_app_data_root(app_data)
            restored.set_user_key("cuenta-a")
            restored.set_project_root(project)
            restored.restore_from_vault(limit=4)
            summary = restored.current_context.get("conversation_summary") or ""
            self.assertIn("mensaje antiguo importante", summary)

    def test_pending_confirmation_is_restored_for_the_same_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_data = Path(tmp) / "appdata"
            project = Path(tmp) / "workspace"
            project.mkdir()

            context = ContextManager()
            context.set_app_data_root(app_data)
            context.set_user_key("cuenta-a")
            context.set_project_root(project)
            pending_id = context.save_pending_action_to_vault(
                "delete_item",
                {"target": "temporal"},
                [],
                preview_text="Eliminar temporal",
            )
            context.set_pending_action({
                "pending_id": pending_id,
                "intent": "delete_item",
                "args": {"target": "temporal"},
                "requires_confirmation": True,
            })
            context.detach_runtime()

            restored = ContextManager()
            restored.set_app_data_root(app_data)
            restored.set_user_key("cuenta-a")
            restored.set_project_root(project)
            restored.restore_from_vault()
            self.assertEqual("delete_item", restored.get_pending_action()["intent"])

if __name__ == "__main__":
    unittest.main()
