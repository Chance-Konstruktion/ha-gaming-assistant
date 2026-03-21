"""Static contract tests for registered services in __init__.py."""

import ast
from pathlib import Path
import unittest


class TestServiceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = Path("custom_components/gaming_assistant/__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        cls.services = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_ALL_SERVICES":
                        cls.services = [elt.value for elt in node.value.elts]

    def test_service_count_15_plus(self):
        self.assertGreaterEqual(len(self.services), 15)

    def test_services_include_core_actions(self):
        expected = {
            "start", "stop", "ask", "announce", "summarize_session",
            "watch_camera", "stop_watch_camera", "set_spoiler_level",
            "clear_history", "configure",
        }
        self.assertTrue(expected.issubset(set(self.services)))

    def test_services_unique(self):
        self.assertEqual(len(self.services), len(set(self.services)))


if __name__ == "__main__":
    unittest.main()
