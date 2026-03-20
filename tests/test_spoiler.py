"""Dedicated tests for SpoilerManager."""

import tempfile
import unittest
from pathlib import Path
import sys
import types
from unittest.mock import MagicMock

# Stub homeassistant package modules before importing custom_components package
_HA_MODULES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.mqtt",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.update_coordinator",
]
for mod in _HA_MODULES:
    sys.modules.setdefault(mod, MagicMock())

const_mod = types.ModuleType("homeassistant.const")
const_mod.EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
const_mod.Platform = types.SimpleNamespace(
    SENSOR="sensor",
    BINARY_SENSOR="binary_sensor",
    SELECT="select",
    NUMBER="number",
    SWITCH="switch",
    CONVERSATION="conversation",
)
sys.modules["homeassistant.const"] = const_mod

from custom_components.gaming_assistant.spoiler import SpoilerManager


class TestSpoilerManagerDedicated(unittest.TestCase):
    def test_set_and_clear_profile(self):
        mgr = SpoilerManager()
        mgr.initialize("medium")
        mgr.set_game_profile("Elden Ring", "high")
        self.assertEqual(mgr.get_settings("Elden Ring")["story"], "high")

        mgr.clear_game_profile("Elden Ring")
        self.assertEqual(mgr.get_settings("Elden Ring")["story"], "medium")

    def test_apply_pack_defaults_only_when_missing(self):
        mgr = SpoilerManager()
        mgr.initialize("medium")
        mgr.set_level("story", "none", game="Doom")

        mgr.apply_pack_defaults("Doom", {"story": "high", "items": "low"})
        s = mgr.get_settings("Doom")
        self.assertEqual(s["story"], "none")
        self.assertEqual(s["items"], "low")

    def test_prompt_block_shape(self):
        mgr = SpoilerManager()
        mgr.initialize("low")
        block = SpoilerManager.generate_prompt_block(mgr.get_settings())
        self.assertIn("SPOILER RULES", block)
        self.assertIn("Story/Plot", block)

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "spoiler_profiles.json"
            m1 = SpoilerManager(str(path))
            m1.initialize("medium")
            m1.set_game_profile("Hades", "none")
            m1.save()

            m2 = SpoilerManager(str(path))
            m2.initialize("medium")
            m2.load()
            self.assertEqual(m2.get_settings("Hades")["story"], "none")


if __name__ == "__main__":
    unittest.main()
