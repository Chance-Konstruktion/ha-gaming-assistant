"""Unit tests for Gaming Assistant select and number entities.

Tests entity classes by stubbing HA base classes before import.
"""

import asyncio
import sys
import types
import unittest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Build proper stub base classes BEFORE importing entity modules
# ---------------------------------------------------------------------------

class _FakeCoordinatorEntity:
    def __init__(self, coordinator):
        pass


class _FakeSensorEntity:
    _attr_name = ""
    _attr_unique_id = ""
    _attr_icon = ""
    _attr_native_unit_of_measurement = None
    _attr_entity_category = None


class _FakeSelectEntity:
    _attr_name = ""
    _attr_unique_id = ""
    _attr_icon = ""
    _attr_options = []
    _attr_translation_key = ""

    @property
    def current_option(self):
        return None

    async def async_select_option(self, option):
        pass


class _FakeNumberEntity:
    _attr_name = ""
    _attr_unique_id = ""
    _attr_icon = ""
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = None
    _attr_mode = None

    @property
    def native_value(self):
        return None

    async def async_set_native_value(self, value):
        pass


class _FakeNumberMode:
    SLIDER = "slider"
    BOX = "box"


# Build the module stubs
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

# Provide real classes for update_coordinator
_coordinator_mod = types.ModuleType("homeassistant.helpers.update_coordinator")
_coordinator_mod.CoordinatorEntity = _FakeCoordinatorEntity
_coordinator_mod.DataUpdateCoordinator = MagicMock
_ha_stubs["homeassistant.helpers.update_coordinator"] = _coordinator_mod

# Provide real classes for select
_select_mod = types.ModuleType("homeassistant.components.select")
_select_mod.SelectEntity = _FakeSelectEntity
_ha_stubs["homeassistant.components.select"] = _select_mod

# Provide real classes for number
_number_mod = types.ModuleType("homeassistant.components.number")
_number_mod.NumberEntity = _FakeNumberEntity
_number_mod.NumberMode = _FakeNumberMode
_ha_stubs["homeassistant.components.number"] = _number_mod

# Provide real classes for sensor (needed by some imports)
_sensor_mod = types.ModuleType("homeassistant.components.sensor")
_sensor_mod.SensorEntity = _FakeSensorEntity
_ha_stubs["homeassistant.components.sensor"] = _sensor_mod

for mod_name, mod_obj in _ha_stubs.items():
    sys.modules[mod_name] = mod_obj

# Force reimport
for mod_key in list(sys.modules.keys()):
    if "custom_components.gaming_assistant" in mod_key and mod_key not in (
        "custom_components.gaming_assistant.const",
        "custom_components.gaming_assistant.spoiler",
        "custom_components.gaming_assistant.prompt_builder",
        "custom_components.gaming_assistant.prompt_packs",
        "custom_components.gaming_assistant.history",
    ):
        del sys.modules[mod_key]

from custom_components.gaming_assistant.select import (
    AssistantModeSelect,
    SpoilerLevelSelect,
)
from custom_components.gaming_assistant.number import (
    AnalysisIntervalNumber,
    AnalysisTimeoutNumber,
)
from custom_components.gaming_assistant.const import (
    ASSISTANT_MODES,
    SPOILER_LEVELS,
)


def _run(coro):
    """Run an async coroutine synchronously for testing."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestAssistantModeSelect(unittest.TestCase):
    """Tests for the assistant mode select entity."""

    def _mock_coordinator(self, mode="coach"):
        coord = MagicMock()
        coord.assistant_mode = mode
        return coord

    def test_unique_id(self):
        self.assertEqual(
            AssistantModeSelect._attr_unique_id,
            "gaming_assistant_assistant_mode",
        )

    def test_options_match_const(self):
        self.assertEqual(AssistantModeSelect._attr_options, ASSISTANT_MODES)

    def test_current_option_reads_coordinator(self):
        coord = self._mock_coordinator(mode="opponent")
        entity = AssistantModeSelect(coord)
        self.assertEqual(entity.current_option, "opponent")

    def test_select_option_calls_setter(self):
        coord = self._mock_coordinator()
        entity = AssistantModeSelect(coord)
        _run(entity.async_select_option("analyst"))
        coord.set_assistant_mode.assert_called_once_with("analyst")

    def test_icon(self):
        self.assertEqual(AssistantModeSelect._attr_icon, "mdi:account-switch")

    def test_translation_key(self):
        self.assertEqual(AssistantModeSelect._attr_translation_key, "assistant_mode")

    def test_all_modes_in_options(self):
        for mode in ["coach", "coplay", "opponent", "analyst"]:
            self.assertIn(mode, AssistantModeSelect._attr_options)


class TestSpoilerLevelSelect(unittest.TestCase):
    """Tests for the spoiler level select entity."""

    def _mock_coordinator(self, level="medium"):
        coord = MagicMock()
        coord.default_spoiler_level = level
        return coord

    def test_unique_id(self):
        self.assertEqual(
            SpoilerLevelSelect._attr_unique_id,
            "gaming_assistant_spoiler_level",
        )

    def test_options_match_const(self):
        self.assertEqual(SpoilerLevelSelect._attr_options, SPOILER_LEVELS)

    def test_current_option_reads_coordinator(self):
        coord = self._mock_coordinator(level="high")
        entity = SpoilerLevelSelect(coord)
        self.assertEqual(entity.current_option, "high")

    def test_select_option_calls_setter(self):
        coord = self._mock_coordinator()
        entity = SpoilerLevelSelect(coord)
        _run(entity.async_select_option("none"))
        coord.set_default_spoiler_level.assert_called_once_with("none")

    def test_icon(self):
        self.assertEqual(SpoilerLevelSelect._attr_icon, "mdi:eye-off")

    def test_all_levels_in_options(self):
        for level in ["none", "low", "medium", "high"]:
            self.assertIn(level, SpoilerLevelSelect._attr_options)


class TestAnalysisIntervalNumber(unittest.TestCase):
    """Tests for the analysis interval number entity."""

    def _mock_coordinator(self, interval=10):
        coord = MagicMock()
        coord.analysis_interval = interval
        return coord

    def test_unique_id(self):
        self.assertEqual(
            AnalysisIntervalNumber._attr_unique_id,
            "gaming_assistant_interval",
        )

    def test_min_max_values(self):
        self.assertEqual(AnalysisIntervalNumber._attr_native_min_value, 5)
        self.assertEqual(AnalysisIntervalNumber._attr_native_max_value, 120)

    def test_native_value_reads_coordinator(self):
        coord = self._mock_coordinator(interval=30)
        entity = AnalysisIntervalNumber(coord)
        self.assertEqual(entity.native_value, 30)

    def test_set_value_calls_setter(self):
        coord = self._mock_coordinator()
        entity = AnalysisIntervalNumber(coord)
        _run(entity.async_set_native_value(20.0))
        coord.set_analysis_interval.assert_called_once_with(20)

    def test_unit_is_seconds(self):
        self.assertEqual(AnalysisIntervalNumber._attr_native_unit_of_measurement, "s")

    def test_step(self):
        self.assertEqual(AnalysisIntervalNumber._attr_native_step, 1)


class TestAnalysisTimeoutNumber(unittest.TestCase):
    """Tests for the analysis timeout number entity."""

    def _mock_coordinator(self, timeout=60):
        coord = MagicMock()
        coord.analysis_timeout = timeout
        return coord

    def test_unique_id(self):
        self.assertEqual(
            AnalysisTimeoutNumber._attr_unique_id,
            "gaming_assistant_timeout",
        )

    def test_min_max_values(self):
        self.assertEqual(AnalysisTimeoutNumber._attr_native_min_value, 10)
        self.assertEqual(AnalysisTimeoutNumber._attr_native_max_value, 300)

    def test_native_value_reads_coordinator(self):
        coord = self._mock_coordinator(timeout=120)
        entity = AnalysisTimeoutNumber(coord)
        self.assertEqual(entity.native_value, 120)

    def test_set_value_calls_setter(self):
        coord = self._mock_coordinator()
        entity = AnalysisTimeoutNumber(coord)
        _run(entity.async_set_native_value(90.0))
        coord.set_analysis_timeout.assert_called_once_with(90)

    def test_unit_is_seconds(self):
        self.assertEqual(AnalysisTimeoutNumber._attr_native_unit_of_measurement, "s")

    def test_step(self):
        self.assertEqual(AnalysisTimeoutNumber._attr_native_step, 5)


class TestSpoilerManagerDefaultLevel(unittest.TestCase):
    """Tests for the new SpoilerManager.default_level property."""

    def test_default_level_uniform(self):
        from custom_components.gaming_assistant.spoiler import SpoilerManager
        mgr = SpoilerManager()
        mgr.initialize("low")
        self.assertEqual(mgr.default_level, "low")

    def test_default_level_after_set_all(self):
        from custom_components.gaming_assistant.spoiler import SpoilerManager
        mgr = SpoilerManager()
        mgr.initialize("medium")
        mgr.set_level("all", "high")
        self.assertEqual(mgr.default_level, "high")

    def test_default_level_mixed_returns_majority(self):
        from custom_components.gaming_assistant.spoiler import SpoilerManager
        mgr = SpoilerManager()
        mgr.initialize("medium")
        mgr.set_level("story", "none")  # 1 category different
        # 6 categories are "medium", 1 is "none" → should return "medium"
        self.assertEqual(mgr.default_level, "medium")

    def test_default_level_empty(self):
        from custom_components.gaming_assistant.spoiler import SpoilerManager
        mgr = SpoilerManager()
        # no initialize called
        self.assertEqual(mgr.default_level, "medium")  # DEFAULT_SPOILER_LEVEL


if __name__ == "__main__":
    unittest.main()
