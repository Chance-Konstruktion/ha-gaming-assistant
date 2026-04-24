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
    IMAGE="image",
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


class TestActionMode(unittest.TestCase):
    """Phase 5.1: structured action output."""

    def test_build_action_prompt_mentions_schema(self):
        prompt = PromptBuilder.build_action(
            game="Chess",
            allowed_buttons=["A", "B", "DPAD_UP"],
        )
        self.assertIn("controller", prompt.lower())
        self.assertIn("Chess", prompt)
        self.assertIn("DPAD_UP", prompt)
        self.assertIn("JSON", prompt)

    def test_build_action_compact(self):
        prompt = PromptBuilder.build_action(game="Chess", compact=True)
        self.assertIn("JSON", prompt)
        self.assertLess(len(prompt), 2000)

    def test_parse_action_valid_tap_button(self):
        result = PromptBuilder.parse_action(
            '{"action": "tap_button", "button": "A", "duration_ms": 80, "reason": "ok"}',
            allowed_buttons=["A", "B"],
        )
        self.assertEqual(result["action"], "tap_button")
        self.assertEqual(result["button"], "A")
        self.assertEqual(result["duration_ms"], 80)

    def test_parse_action_strips_unknown_fields(self):
        result = PromptBuilder.parse_action(
            '{"action": "no_op", "malicious_field": "ignored", "reason": "wait"}'
        )
        self.assertNotIn("malicious_field", result)

    def test_parse_action_strips_code_fences(self):
        result = PromptBuilder.parse_action(
            '```json\n{"action": "no_op"}\n```'
        )
        self.assertEqual(result["action"], "no_op")

    def test_parse_action_rejects_non_json(self):
        with self.assertRaises(ValueError):
            PromptBuilder.parse_action("press A now please")

    def test_parse_action_rejects_empty(self):
        with self.assertRaises(ValueError):
            PromptBuilder.parse_action("")

    def test_parse_action_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            PromptBuilder.parse_action('{"action": "reboot"}')

    def test_parse_action_enforces_button_whitelist(self):
        with self.assertRaises(ValueError):
            PromptBuilder.parse_action(
                '{"action": "tap_button", "button": "START"}',
                allowed_buttons=["A"],
            )

    def test_parse_action_requires_button_for_press(self):
        with self.assertRaises(ValueError):
            PromptBuilder.parse_action('{"action": "press_button"}')

    def test_parse_action_validates_stick_axes(self):
        with self.assertRaises(ValueError):
            PromptBuilder.parse_action(
                '{"action": "move_stick", "stick": "left", "x": 2.0, "y": 0.0}'
            )

    def test_parse_action_rejects_oversized_duration(self):
        with self.assertRaises(ValueError):
            PromptBuilder.parse_action(
                '{"action": "tap_button", "button": "A", "duration_ms": 99999}'
            )


if __name__ == "__main__":
    unittest.main()
