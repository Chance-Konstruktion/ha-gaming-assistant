"""Unit tests for the Gaming Assistant conversation agent."""

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Stub HA modules before importing conversation.py
# ---------------------------------------------------------------------------

class _FakeConversationEntity:
    _attr_has_entity_name = True
    _attr_name = ""
    _attr_unique_id = ""


class _FakeConversationInput:
    def __init__(self, text="", language="en", conversation_id=None):
        self.text = text
        self.language = language
        self.conversation_id = conversation_id
        self.agent_id = "test_agent"


class _FakeConversationResult:
    def __init__(self, response=None, conversation_id=None, **kwargs):
        self.response = response
        self.conversation_id = conversation_id


class _FakeIntentResponse:
    def __init__(self, language="en"):
        self.language = language
        self._speech = ""

    def async_set_speech(self, text):
        self._speech = text

    @property
    def speech(self):
        return {"plain": {"speech": self._speech}}


# Build module stubs
_ha_stubs = {
    "homeassistant": MagicMock(),
    "homeassistant.components": MagicMock(),
    "homeassistant.components.mqtt": MagicMock(),
    "homeassistant.config_entries": MagicMock(),
    "homeassistant.const": MagicMock(),
    "homeassistant.core": MagicMock(),
    "homeassistant.exceptions": MagicMock(),
    "homeassistant.helpers": MagicMock(),
    "homeassistant.helpers.device_registry": MagicMock(),
    "homeassistant.helpers.entity_platform": MagicMock(),
    "homeassistant.helpers.update_coordinator": MagicMock(),
    "homeassistant.util": MagicMock(),
}

# Conversation module with real classes
_conv_mod = types.ModuleType("homeassistant.components.conversation")
_conv_mod.ConversationEntity = _FakeConversationEntity
_conv_mod.ConversationInput = _FakeConversationInput
_conv_mod.ConversationResult = _FakeConversationResult
_conv_mod.MATCH_ALL = "*"
_ha_stubs["homeassistant.components.conversation"] = _conv_mod

# Intent module
_intent_mod = types.ModuleType("homeassistant.helpers.intent")
_intent_mod.IntentResponse = _FakeIntentResponse
_ha_stubs["homeassistant.helpers.intent"] = _intent_mod

for mod_name, mod_obj in _ha_stubs.items():
    sys.modules[mod_name] = mod_obj

# Ensure the parent MagicMock references point to our real sub-modules
sys.modules["homeassistant.components"].conversation = _conv_mod
sys.modules["homeassistant.helpers"].intent = _intent_mod

# Force reimport of our modules
for mod_key in list(sys.modules.keys()):
    if "custom_components.gaming_assistant" in mod_key:
        del sys.modules[mod_key]

from custom_components.gaming_assistant.conversation import (
    GamingAssistantConversationEntity,
)
from custom_components.gaming_assistant.const import ASSISTANT_MODES, SPOILER_LEVELS


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_entity(tip="Waiting for tips...", mode="coach", summary=""):
    """Create a GamingAssistantConversationEntity with a mocked coordinator."""
    coord = MagicMock()
    coord.tip = tip
    coord.assistant_mode = mode
    coord.last_summary = summary
    coord.hass = MagicMock()
    coord.hass.services.async_call = AsyncMock()
    coord.async_ask = AsyncMock(return_value="")

    entry = MagicMock()
    entry.entry_id = "test_entry"

    entity = GamingAssistantConversationEntity(coord, entry)
    return entity, coord


def _process(entity, text, language="en"):
    user_input = _FakeConversationInput(text=text, language=language)
    return _run(entity.async_process(user_input))


class TestConversationIntents(unittest.TestCase):
    """Tests for voice command intent matching."""

    def test_set_mode_coach(self):
        entity, coord = _make_entity()
        result = _process(entity, "switch mode to coach")
        coord.set_assistant_mode.assert_called_once_with("coach")
        self.assertIn("coach", result.response._speech)

    def test_set_mode_opponent(self):
        entity, coord = _make_entity()
        result = _process(entity, "change mode to opponent")
        coord.set_assistant_mode.assert_called_once_with("opponent")

    def test_set_mode_coplay(self):
        entity, coord = _make_entity()
        result = _process(entity, "set mode to co-player")
        coord.set_assistant_mode.assert_called_once_with("coplay")

    def test_set_mode_german(self):
        entity, coord = _make_entity()
        result = _process(entity, "wechsel modus auf gegner")
        coord.set_assistant_mode.assert_called_once_with("opponent")

    def test_set_mode_analyst(self):
        entity, coord = _make_entity()
        result = _process(entity, "switch mode to analyst")
        coord.set_assistant_mode.assert_called_once_with("analyst")

    def test_set_spoiler_none(self):
        entity, coord = _make_entity()
        result = _process(entity, "set spoiler level to none")
        coord.set_default_spoiler_level.assert_called_once_with("none")
        self.assertIn("none", result.response._speech)

    def test_set_spoiler_high(self):
        entity, coord = _make_entity()
        result = _process(entity, "change spoiler to high")
        coord.set_default_spoiler_level.assert_called_once_with("high")

    def test_set_spoiler_german(self):
        entity, coord = _make_entity()
        result = _process(entity, "ändere spoiler level auf niedrig")
        coord.set_default_spoiler_level.assert_called_once_with("low")

    def test_start(self):
        entity, coord = _make_entity()
        result = _process(entity, "start")
        coord.hass.services.async_call.assert_called_once_with(
            "gaming_assistant", "start", {}
        )
        self.assertIn("started", result.response._speech)

    def test_stop(self):
        entity, coord = _make_entity()
        result = _process(entity, "stop")
        coord.hass.services.async_call.assert_called_once_with(
            "gaming_assistant", "stop", {}
        )
        self.assertIn("stopped", result.response._speech)

    def test_stop_german(self):
        entity, coord = _make_entity()
        result = _process(entity, "stoppe")
        coord.hass.services.async_call.assert_called_once_with(
            "gaming_assistant", "stop", {}
        )

    def test_current_tip(self):
        entity, coord = _make_entity(tip="Use dodge roll to avoid attacks")
        result = _process(entity, "current tip")
        self.assertEqual(result.response._speech, "Use dodge roll to avoid attacks")

    def test_current_tip_none(self):
        entity, coord = _make_entity(tip="Waiting for tips...")
        result = _process(entity, "last tip")
        self.assertIn("No tip", result.response._speech)

    def test_current_tip_german(self):
        entity, coord = _make_entity(tip="Weiche dem Angriff aus")
        result = _process(entity, "aktueller tipp")
        self.assertEqual(result.response._speech, "Weiche dem Angriff aus")

    def test_session_summary(self):
        entity, coord = _make_entity(summary="You played well, defeated 3 bosses.")
        result = _process(entity, "session summary")
        self.assertEqual(
            result.response._speech, "You played well, defeated 3 bosses."
        )

    def test_session_summary_none(self):
        entity, coord = _make_entity(summary="")
        result = _process(entity, "summary")
        self.assertIn("No session summary", result.response._speech)

    def test_analyze(self):
        entity, coord = _make_entity()
        result = _process(entity, "analyze")
        coord.hass.services.async_call.assert_called_once_with(
            "gaming_assistant", "analyze", {}
        )
        self.assertIn("Analyzing", result.response._speech)

    def test_analyze_screenshot(self):
        entity, coord = _make_entity()
        result = _process(entity, "screenshot")
        coord.hass.services.async_call.assert_called_once_with(
            "gaming_assistant", "analyze", {}
        )


class TestConversationFallback(unittest.TestCase):
    """Tests for the free-form question fallback (async_ask)."""

    def test_fallback_to_ask(self):
        entity, coord = _make_entity()
        coord.async_ask = AsyncMock(return_value="Try using fire arrows.")
        result = _process(entity, "How do I beat the dragon?")
        coord.async_ask.assert_called_once_with(
            question="How do I beat the dragon?"
        )
        self.assertEqual(result.response._speech, "Try using fire arrows.")

    def test_fallback_empty_response(self):
        entity, coord = _make_entity()
        coord.async_ask = AsyncMock(return_value="")
        result = _process(entity, "random question")
        self.assertIn("couldn't generate", result.response._speech)

    def test_empty_input(self):
        entity, coord = _make_entity()
        result = _process(entity, "")
        self.assertIn("didn't catch", result.response._speech)

    def test_german_question_fallback(self):
        entity, coord = _make_entity()
        coord.async_ask = AsyncMock(return_value="Nutze den Schild vor dem Boss.")
        result = _process(entity, "wie besiege ich den boss?", language="de")
        coord.async_ask.assert_called_once()
        self.assertIn("Schild", result.response._speech)

    def test_whitespace_only_input(self):
        entity, coord = _make_entity()
        result = _process(entity, "   ")
        self.assertIn("didn't catch", result.response._speech)

    def test_unknown_short_command_falls_back_to_ask(self):
        entity, coord = _make_entity()
        coord.async_ask = AsyncMock(return_value="Try checking the map.")
        result = _process(entity, "map?")
        coord.async_ask.assert_called_once_with(question="map?")
        self.assertIn("map", result.response._speech.lower())


class TestConversationEntity(unittest.TestCase):
    """Tests for entity attributes."""

    def test_unique_id(self):
        entity, _ = _make_entity()
        self.assertEqual(entity._attr_unique_id, "test_entry_conversation")

    def test_supported_languages(self):
        entity, _ = _make_entity()
        self.assertEqual(entity.supported_languages, "*")

    def test_name(self):
        entity, _ = _make_entity()
        self.assertEqual(entity._attr_name, "Gaming Assistant")


if __name__ == "__main__":
    unittest.main()
