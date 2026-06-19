"""Behavioral tests for the binary_sensor, switch, and image platforms.

These three platforms previously had 0% coverage. We test the entity
classes by stubbing the HA base classes before import (same approach as
test_sensors.py / test_entities.py) and then exercising their real logic.
"""

import asyncio
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Stub base classes BEFORE importing the platform modules
# ---------------------------------------------------------------------------

class _FakeCoordinatorEntity:
    def __init__(self, coordinator):
        pass


class _FakeBinarySensorEntity:
    _attr_name = ""
    _attr_unique_id = ""
    _attr_icon = ""

    @property
    def is_on(self):
        return None


class _FakeSwitchEntity:
    _attr_name = ""
    _attr_unique_id = ""
    _attr_icon = ""
    _attr_translation_key = ""

    @property
    def is_on(self):
        return None


class _FakeImageEntity:
    _attr_name = ""
    _attr_unique_id = ""
    _attr_icon = ""
    _attr_content_type = ""

    def __init__(self, hass=None):
        self.hass = hass


class _FakeSensorEntity:
    _attr_name = ""
    _attr_unique_id = ""


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
}

_coordinator_mod = types.ModuleType("homeassistant.helpers.update_coordinator")
_coordinator_mod.CoordinatorEntity = _FakeCoordinatorEntity
_coordinator_mod.DataUpdateCoordinator = MagicMock
_ha_stubs["homeassistant.helpers.update_coordinator"] = _coordinator_mod

# coordinator.py imports async_track_time_interval at module level.
_event_mod = types.ModuleType("homeassistant.helpers.event")
_event_mod.async_track_time_interval = MagicMock()
_ha_stubs["homeassistant.helpers.event"] = _event_mod

_bs_mod = types.ModuleType("homeassistant.components.binary_sensor")
_bs_mod.BinarySensorEntity = _FakeBinarySensorEntity
_ha_stubs["homeassistant.components.binary_sensor"] = _bs_mod

_sw_mod = types.ModuleType("homeassistant.components.switch")
_sw_mod.SwitchEntity = _FakeSwitchEntity
_ha_stubs["homeassistant.components.switch"] = _sw_mod

_img_mod = types.ModuleType("homeassistant.components.image")
_img_mod.ImageEntity = _FakeImageEntity
_ha_stubs["homeassistant.components.image"] = _img_mod

_sensor_mod = types.ModuleType("homeassistant.components.sensor")
_sensor_mod.SensorEntity = _FakeSensorEntity
_ha_stubs["homeassistant.components.sensor"] = _sensor_mod

for _mod_name, _mod_obj in _ha_stubs.items():
    sys.modules[_mod_name] = _mod_obj

# Force a clean reimport of the integration modules under our stubs.
for _mod_key in list(sys.modules.keys()):
    if "custom_components.gaming_assistant" in _mod_key and _mod_key not in (
        "custom_components.gaming_assistant.const",
        "custom_components.gaming_assistant.spoiler",
        "custom_components.gaming_assistant.prompt_builder",
        "custom_components.gaming_assistant.prompt_packs",
        "custom_components.gaming_assistant.history",
    ):
        del sys.modules[_mod_key]

from custom_components.gaming_assistant.binary_sensor import GamingModeSensor
from custom_components.gaming_assistant.switch import (
    AgentModeSwitch,
    AutoAnnounceSwitch,
    AutoSummarySwitch,
    StrategyReflectionSwitch,
)
from custom_components.gaming_assistant.image import GamingAssistantLastFrameImage


def _run(coro):
    """Run an async coroutine synchronously for testing."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestGamingModeBinarySensor(unittest.TestCase):
    def _coord(self, gaming_mode=False, tip="Hello"):
        coord = MagicMock()
        coord.gaming_mode = gaming_mode
        coord.tip = tip
        return coord

    def test_unique_id_and_icon(self):
        self.assertEqual(GamingModeSensor._attr_unique_id, "gaming_mode")
        self.assertEqual(GamingModeSensor._attr_icon, "mdi:gamepad-variant")

    def test_is_on_reflects_coordinator(self):
        self.assertTrue(GamingModeSensor(self._coord(gaming_mode=True)).is_on)
        self.assertFalse(GamingModeSensor(self._coord(gaming_mode=False)).is_on)

    def test_extra_state_attributes_expose_last_tip(self):
        entity = GamingModeSensor(self._coord(tip="Dodge left"))
        self.assertEqual(entity.extra_state_attributes["last_tip"], "Dodge left")


class TestSwitches(unittest.TestCase):
    def test_auto_announce_switch(self):
        coord = MagicMock()
        coord.auto_announce = True
        sw = AutoAnnounceSwitch(coord)
        self.assertTrue(sw.is_on)
        _run(sw.async_turn_on())
        coord.set_auto_announce.assert_called_with(True)
        _run(sw.async_turn_off())
        coord.set_auto_announce.assert_called_with(False)
        self.assertEqual(sw._attr_unique_id, "gaming_assistant_auto_announce")

    def test_auto_summary_switch(self):
        coord = MagicMock()
        coord.auto_summary = False
        sw = AutoSummarySwitch(coord)
        self.assertFalse(sw.is_on)
        _run(sw.async_turn_on())
        coord.set_auto_summary.assert_called_with(True)
        _run(sw.async_turn_off())
        coord.set_auto_summary.assert_called_with(False)

    def test_agent_mode_switch(self):
        coord = MagicMock()
        coord.agent_mode = False
        sw = AgentModeSwitch(coord)
        self.assertFalse(sw.is_on)
        _run(sw.async_turn_on())
        coord.set_agent_mode.assert_called_with(True)
        _run(sw.async_turn_off())
        coord.set_agent_mode.assert_called_with(False)
        self.assertEqual(sw._attr_unique_id, "gaming_assistant_agent_mode")

    def test_strategy_reflection_switch(self):
        coord = MagicMock()
        coord.strategy_reflection = True
        sw = StrategyReflectionSwitch(coord)
        self.assertTrue(sw.is_on)
        _run(sw.async_turn_on())
        coord.set_strategy_reflection.assert_called_with(True)
        _run(sw.async_turn_off())
        coord.set_strategy_reflection.assert_called_with(False)
        self.assertEqual(
            sw._attr_unique_id, "gaming_assistant_strategy_reflection"
        )


class TestLastFrameImage(unittest.TestCase):
    def _coord(self, ts="", img=None, client="pc", game="Elden Ring"):
        coord = MagicMock()
        coord.last_image_timestamp = ts
        coord.last_image_bytes = img
        coord.last_image_client_id = client
        coord.current_game = game
        return coord

    def test_image_last_updated_parses_iso(self):
        entity = GamingAssistantLastFrameImage(
            self._coord(ts="2026-06-18T12:00:00"), MagicMock()
        )
        self.assertEqual(
            entity.image_last_updated, datetime(2026, 6, 18, 12, 0, 0)
        )

    def test_image_last_updated_handles_empty_and_invalid(self):
        self.assertIsNone(
            GamingAssistantLastFrameImage(self._coord(ts=""), MagicMock()).image_last_updated
        )
        self.assertIsNone(
            GamingAssistantLastFrameImage(self._coord(ts="not-a-date"), MagicMock()).image_last_updated
        )

    def test_async_image_returns_bytes(self):
        entity = GamingAssistantLastFrameImage(
            self._coord(img=b"\xff\xd8jpeg"), MagicMock()
        )
        self.assertEqual(_run(entity.async_image()), b"\xff\xd8jpeg")

    def test_extra_state_attributes(self):
        entity = GamingAssistantLastFrameImage(
            self._coord(client="rig1", game="DOOM"), MagicMock()
        )
        attrs = entity.extra_state_attributes
        self.assertEqual(attrs["client_id"], "rig1")
        self.assertEqual(attrs["game"], "DOOM")


if __name__ == "__main__":
    unittest.main()
