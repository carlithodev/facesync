from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.path_policy import WorkspacePathPolicy, safe_account_id, safe_component


class PathPolicyTests(unittest.TestCase):
    def test_accepts_paths_inside_any_workspace_root(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            policy = WorkspacePathPolicy([first, second])
            value = Path(second) / "subcarpeta" / "archivo.txt"
            self.assertEqual(policy.resolve(value), value.resolve(strict=False))

    def test_rejects_paths_outside_workspace(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            policy = WorkspacePathPolicy([root])
            with self.assertRaises(PermissionError):
                policy.resolve(Path(outside) / "archivo.txt")

    def test_rejects_workspace_root_for_destructive_operations(self):
        with tempfile.TemporaryDirectory() as root:
            policy = WorkspacePathPolicy([root])
            with self.assertRaises(PermissionError):
                policy.resolve(root, allow_root=False)

    def test_safe_component_blocks_traversal(self):
        for value in ("..", "../escape", r"..\escape", r"C:\escape"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe_component(value)
        self.assertEqual(safe_component("Fotos 2026"), "Fotos 2026")

    def test_account_id_blocks_paths(self):
        for value in ("..", "../usuario", r"C:\usuario", "usuario/cuenta"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe_account_id(value)
        self.assertEqual(safe_account_id("persona@example.com"), "persona@example.com")


if __name__ == "__main__":
    unittest.main()
