"""
Unit tests for Gaming Assistant HA components (prompt_builder, spoiler).
Uses sys.modules mocking to avoid requiring homeassistant.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Stub out homeassistant before importing our modules
_HA_MODULES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.mqtt",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
]
for mod in _HA_MODULES:
    sys.modules.setdefault(mod, MagicMock())

# Now we can safely import
from custom_components.gaming_assistant.prompt_builder import PromptBuilder
from custom_components.gaming_assistant.spoiler import SpoilerManager


# ===========================================================================
# PromptBuilder tests
# ===========================================================================

class TestPromptBuilder(unittest.TestCase):
    """Tests for PromptBuilder.build()."""

    def test_basic_prompt(self):
        result = PromptBuilder.build()
        self.assertIn("You are a helpful gaming coach", result)
        self.assertIn("ONE short, specific, actionable tip", result)

    def test_with_game(self):
        result = PromptBuilder.build(game="Elden Ring", client_type="pc")
        self.assertIn("Elden Ring", result)
        self.assertIn("pc", result)

    def test_with_user_question(self):
        result = PromptBuilder.build(user_question="How do I beat Margit?")
        self.assertIn("How do I beat Margit?", result)
        self.assertIn("Answer the question", result)
        # ask-mode should NOT include the generic tip instruction
        self.assertNotIn("ONE short, specific, actionable tip", result)

    def test_with_prompt_pack(self):
        pack = {
            "system_prompt": "You specialize in Souls games.",
            "additional_context": "The player is a beginner.",
        }
        result = PromptBuilder.build(prompt_pack=pack)
        self.assertIn("You specialize in Souls games", result)
        self.assertIn("The player is a beginner", result)

    def test_anti_repetition_only_with_history(self):
        without = PromptBuilder.build()
        self.assertNotIn("Do NOT repeat", without)

        with_history = PromptBuilder.build(history_context="Previous: dodge roll")
        self.assertIn("Do NOT repeat", with_history)

    def test_spoiler_block_included(self):
        result = PromptBuilder.build(spoiler_block="SPOILER RULES: story=NONE")
        self.assertIn("SPOILER RULES: story=NONE", result)

    def test_all_parts_combined(self):
        result = PromptBuilder.build(
            game="Zelda",
            spoiler_block="SPOILER: low",
            history_context="Prev tip: use shield",
            client_type="console",
            user_question="Where is the master sword?",
        )
        self.assertIn("Zelda", result)
        self.assertIn("console", result)
        self.assertIn("SPOILER: low", result)
        self.assertIn("Prev tip: use shield", result)
        self.assertIn("Where is the master sword?", result)


# ===========================================================================
# SpoilerManager tests
# ===========================================================================

class TestSpoilerManager(unittest.TestCase):
    """Tests for SpoilerManager persistence and logic."""

    def test_initialize_sets_defaults(self):
        mgr = SpoilerManager()
        mgr.initialize("low")
        settings = mgr.get_settings()
        for level in settings.values():
            self.assertEqual(level, "low")

    def test_initialize_invalid_falls_back(self):
        mgr = SpoilerManager()
        mgr.initialize("invalid_level")
        settings = mgr.get_settings()
        for level in settings.values():
            self.assertEqual(level, "medium")

    def test_set_level_global(self):
        mgr = SpoilerManager()
        mgr.initialize("medium")
        mgr.set_level("story", "none")
        self.assertEqual(mgr.get_settings()["story"], "none")
        self.assertEqual(mgr.get_settings()["items"], "medium")

    def test_set_level_all(self):
        mgr = SpoilerManager()
        mgr.initialize("medium")
        mgr.set_level("all", "high")
        for level in mgr.get_settings().values():
            self.assertEqual(level, "high")

    def test_set_level_invalid_ignored(self):
        mgr = SpoilerManager()
        mgr.initialize("medium")
        mgr.set_level("story", "ultra")  # invalid
        self.assertEqual(mgr.get_settings()["story"], "medium")

    def test_set_level_per_game(self):
        mgr = SpoilerManager()
        mgr.initialize("medium")
        mgr.set_level("story", "none", game="Elden Ring")
        settings = mgr.get_settings("Elden Ring")
        self.assertEqual(settings["story"], "none")
        self.assertEqual(settings["items"], "medium")

    def test_set_game_profile(self):
        mgr = SpoilerManager()
        mgr.initialize("medium")
        mgr.set_game_profile("Zelda", "high")
        settings = mgr.get_settings("Zelda")
        for level in settings.values():
            self.assertEqual(level, "high")

    def test_clear_game_profile(self):
        mgr = SpoilerManager()
        mgr.initialize("medium")
        mgr.set_game_profile("Zelda", "high")
        mgr.clear_game_profile("Zelda")
        settings = mgr.get_settings("Zelda")
        for level in settings.values():
            self.assertEqual(level, "medium")

    def test_get_game_profiles(self):
        mgr = SpoilerManager()
        mgr.initialize("medium")
        mgr.set_game_profile("Doom", "high")
        mgr.set_game_profile("Zelda", "low")
        profiles = mgr.get_game_profiles()
        self.assertIn("Doom", profiles)
        self.assertIn("Zelda", profiles)

    def test_apply_pack_defaults(self):
        mgr = SpoilerManager()
        mgr.initialize("medium")
        mgr.apply_pack_defaults("Doom", {"story": "none", "items": "high"})
        settings = mgr.get_settings("Doom")
        self.assertEqual(settings["story"], "none")
        self.assertEqual(settings["items"], "high")
        # Existing overrides should NOT be overwritten
        mgr.set_level("story", "low", game="Doom")
        mgr.apply_pack_defaults("Doom", {"story": "high"})
        self.assertEqual(mgr.get_settings("Doom")["story"], "low")

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "subdir" / "spoiler_profiles.json")
            mgr = SpoilerManager(path)
            mgr.initialize("low")
            mgr.set_game_profile("Doom", "high")
            mgr.save()

            mgr2 = SpoilerManager(path)
            mgr2.initialize("medium")  # will be overridden by load
            mgr2.load()
            self.assertEqual(mgr2.get_settings()["story"], "low")
            self.assertEqual(mgr2.get_settings("Doom")["story"], "high")

    def test_load_handles_corrupt_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text("{corrupt", encoding="utf-8")
            mgr = SpoilerManager(str(path))
            mgr.initialize("medium")
            mgr.load()  # should not raise
            self.assertEqual(mgr.get_settings()["story"], "medium")

    def test_load_nonexistent_is_noop(self):
        mgr = SpoilerManager("/tmp/does_not_exist_12345.json")
        mgr.initialize("medium")
        mgr.load()  # no file, no crash
        self.assertEqual(mgr.get_settings()["story"], "medium")

    def test_save_without_path_is_noop(self):
        mgr = SpoilerManager()  # no path
        mgr.initialize("medium")
        mgr.save()  # should not raise

    def test_generate_prompt_block(self):
        mgr = SpoilerManager()
        mgr.initialize("none")
        block = SpoilerManager.generate_prompt_block(mgr.get_settings())
        self.assertIn("SPOILER RULES", block)
        self.assertIn("NONE", block)
        self.assertIn("Do NOT reveal", block)


if __name__ == "__main__":
    unittest.main()
