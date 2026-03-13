"""Tests for per-game spoiler profile persistence."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = ROOT / "custom_components" / "gaming_assistant"

# Create lightweight package shells so relative imports in spoiler.py work
custom_components_pkg = types.ModuleType("custom_components")
custom_components_pkg.__path__ = [str(ROOT / "custom_components")]
sys.modules.setdefault("custom_components", custom_components_pkg)

ga_pkg = types.ModuleType("custom_components.gaming_assistant")
ga_pkg.__path__ = [str(PKG_ROOT)]
sys.modules.setdefault("custom_components.gaming_assistant", ga_pkg)

const_spec = importlib.util.spec_from_file_location(
    "custom_components.gaming_assistant.const", PKG_ROOT / "const.py"
)
const_mod = importlib.util.module_from_spec(const_spec)
assert const_spec and const_spec.loader
sys.modules["custom_components.gaming_assistant.const"] = const_mod
const_spec.loader.exec_module(const_mod)

spoiler_spec = importlib.util.spec_from_file_location(
    "custom_components.gaming_assistant.spoiler", PKG_ROOT / "spoiler.py"
)
spoiler_mod = importlib.util.module_from_spec(spoiler_spec)
assert spoiler_spec and spoiler_spec.loader
sys.modules["custom_components.gaming_assistant.spoiler"] = spoiler_mod
spoiler_spec.loader.exec_module(spoiler_mod)
SpoilerManager = spoiler_mod.SpoilerManager


class TestSpoilerManager(unittest.TestCase):
    def test_set_and_clear_game_profile(self):
        manager = SpoilerManager()
        manager.initialize("medium")

        manager.set_game_profile("Elden Ring", "none")
        settings = manager.get_settings("Elden Ring")
        self.assertEqual(settings["bosses"], "none")
        self.assertEqual(settings["story"], "none")

        manager.clear_game_profile("Elden Ring")
        settings_after = manager.get_settings("Elden Ring")
        self.assertEqual(settings_after["bosses"], "medium")

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "spoiler_profiles.json"
            manager = SpoilerManager(str(path))
            manager.initialize("low")
            manager.set_game_profile("Minecraft", "high")
            manager.set_level("bosses", "none")

            reloaded = SpoilerManager(str(path))
            reloaded.initialize("medium")
            reloaded.load()

            self.assertEqual(reloaded.get_settings(None)["bosses"], "none")
            self.assertEqual(reloaded.get_settings("Minecraft")["story"], "high")


if __name__ == "__main__":
    unittest.main()
