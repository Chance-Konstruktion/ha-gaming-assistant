"""Dedicated tests for PromptBuilder."""

import sys
import types
import unittest
from unittest.mock import MagicMock

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
    "homeassistant.helpers.event",
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

from custom_components.gaming_assistant.prompt_builder import PromptBuilder


class TestPromptBuilderDedicated(unittest.TestCase):
    def test_compact_mode_detection(self):
        self.assertTrue(PromptBuilder.is_small_model("qwen2.5vl:3b"))
        self.assertFalse(PromptBuilder.is_small_model("llava:13b"))

    def test_source_hint_console(self):
        prompt = PromptBuilder.build(client_type="console")
        self.assertIn("console", prompt.lower())

    def test_source_hint_tabletop(self):
        prompt = PromptBuilder.build(client_type="tabletop")
        self.assertIn("table", prompt.lower())

    def test_language_instruction(self):
        prompt = PromptBuilder.build(language="German (Deutsch)")
        self.assertIn("German", prompt)

    def test_summary_prompt_contains_tips(self):
        summary_prompt = PromptBuilder.build_summary(
            game="Doom",
            tips=["aim higher", "reload before push"],
            language="German (Deutsch)",
            compact=False,
        )
        self.assertIn("Doom", summary_prompt)
        self.assertIn("aim higher", summary_prompt)
        self.assertIn("reload before push", summary_prompt)


if __name__ == "__main__":
    unittest.main()
