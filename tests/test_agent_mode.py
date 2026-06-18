"""
Tests for Agent Mode / Player 2 action publishing (GA-AUD).

Behavioural tests cover ImageProcessor.generate_action (importable with the
HA stubs used elsewhere). The coordinator wiring is verified with static
source-contract checks, mirroring tests/test_coordinator.py — the coordinator
subclasses DataUpdateCoordinator and cannot be imported without a real HA env.
"""

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Stub homeassistant before importing our modules (same approach as
# tests/test_image_processor.py).
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

from custom_components.gaming_assistant.history import HistoryManager
from custom_components.gaming_assistant.image_processor import ImageProcessor
from custom_components.gaming_assistant.spoiler import SpoilerManager


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===========================================================================
# ImageProcessor.generate_action — behaviour
# ===========================================================================

class TestGenerateAction(unittest.TestCase):
    def _make_processor(self, response_text: str):
        history = MagicMock(spec=HistoryManager)
        spoiler = MagicMock(spec=SpoilerManager)
        spoiler.get_settings.return_value = {}
        spoiler.generate_prompt_block.return_value = ""
        proc = ImageProcessor(
            ollama_host="http://localhost:11434",
            model="test-model",
            history_manager=history,
            spoiler_manager=spoiler,
        )
        # Mock the LLM backend to return a fixed action JSON.
        proc._backend = MagicMock()
        proc._backend.generate = AsyncMock(
            return_value=SimpleNamespace(text=response_text)
        )
        return proc

    def test_valid_action_returned(self):
        proc = self._make_processor(
            '{"action": "tap_button", "button": "a", "duration_ms": 80,'
            ' "reason": "confirm"}'
        )
        action = _run(proc.generate_action(b"frame", "Elden Ring"))
        self.assertEqual(action["action"], "tap_button")
        self.assertEqual(action["button"], "A")  # normalized to upper
        self.assertEqual(action["duration_ms"], 80)

    def test_invalid_json_returns_none(self):
        proc = self._make_processor("press A now please")
        self.assertIsNone(_run(proc.generate_action(b"frame", "Doom")))

    def test_no_op_returns_none(self):
        proc = self._make_processor('{"action": "no_op", "reason": "nothing"}')
        self.assertIsNone(_run(proc.generate_action(b"frame", "Doom")))

    def test_whitelist_rejection_returns_none(self):
        proc = self._make_processor('{"action": "tap_button", "button": "START"}')
        # START is valid but not in the provided whitelist -> rejected -> None.
        self.assertIsNone(
            _run(proc.generate_action(b"frame", "Doom", allowed_buttons=["A", "B"]))
        )

    def test_unknown_keys_stripped(self):
        proc = self._make_processor(
            '{"action": "tap_button", "button": "A", "evil": "rm -rf"}'
        )
        action = _run(proc.generate_action(b"frame", "Doom"))
        self.assertIn("button", action)
        self.assertNotIn("evil", action)

    def test_move_stick_action(self):
        proc = self._make_processor(
            '{"action": "move_stick", "stick": "left", "x": 0.5, "y": -0.2}'
        )
        action = _run(proc.generate_action(b"frame", "Rocket League"))
        self.assertEqual(action["action"], "move_stick")
        self.assertEqual(action["stick"], "left")


# ===========================================================================
# Static source contracts — const, coordinator, services, switch wiring
# ===========================================================================

class TestAgentModeContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = Path("custom_components/gaming_assistant")
        cls.const = (base / "const.py").read_text(encoding="utf-8")
        cls.coord = (base / "coordinator.py").read_text(encoding="utf-8")
        cls.init = (base / "__init__.py").read_text(encoding="utf-8")
        cls.switch = (base / "switch.py").read_text(encoding="utf-8")
        cls.services = (base / "services.yaml").read_text(encoding="utf-8")

    def test_const_defines_agent_mode(self):
        self.assertIn("DEFAULT_AGENT_MODE = False", self.const)
        self.assertIn(
            'MQTT_ACTION_TOPIC = "gaming_assistant/{client_id}/action"', self.const
        )
        self.assertIn("AGENT_VALID_BUTTONS = [", self.const)

    def test_agent_mode_defaults_off(self):
        self.assertIn("self._agent_mode: bool = DEFAULT_AGENT_MODE", self.coord)

    def test_publish_uses_action_topic(self):
        self.assertIn("async def async_publish_action", self.coord)
        self.assertIn("MQTT_ACTION_TOPIC.format(client_id=client_id)", self.coord)

    def test_process_image_gates_on_agent_mode(self):
        self.assertIn("if self._agent_mode:", self.coord)
        self.assertIn("await self._maybe_publish_agent_action(", self.coord)

    def test_action_path_is_isolated(self):
        # The action generation must be wrapped so it can never break analysis.
        self.assertIn("async def _maybe_publish_agent_action", self.coord)
        self.assertIn("Agent action generation failed", self.coord)

    def test_setter_enforces_button_whitelist(self):
        self.assertIn("def set_agent_mode(", self.coord)
        self.assertIn("AGENT_VALID_BUTTONS", self.coord)

    def test_safety_governor_wired(self):
        # const declares the safety rails
        self.assertIn("AGENT_ACTION_MIN_INTERVAL", self.const)
        self.assertIn("AGENT_MAX_CONSECUTIVE_FAILURES", self.const)
        self.assertIn("EVENT_AGENT_ACTION", self.const)
        # coordinator uses the governor for rate limiting + auto-disable
        self.assertIn("self._agent_governor", self.coord)
        self.assertIn("rate_limited(", self.coord)
        self.assertIn("record_error(", self.coord)
        # auto-disable turns Agent Mode OFF and emits an audit event
        self.assertIn("self.set_agent_mode(False)", self.coord)
        self.assertIn("_fire_agent_action_event", self.coord)

    def test_service_registered(self):
        self.assertIn('"set_agent_mode"', self.init)
        self.assertIn("async def handle_set_agent_mode", self.init)
        self.assertIn(
            'hass.services.async_register(DOMAIN, "set_agent_mode"', self.init
        )

    def test_switch_entity_exists(self):
        self.assertIn("class AgentModeSwitch", self.switch)
        self.assertIn("AgentModeSwitch(coordinator)", self.switch)

    def test_service_documented(self):
        self.assertIn("set_agent_mode:", self.services)


if __name__ == "__main__":
    unittest.main()
