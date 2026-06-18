"""Unit tests for Gaming Assistant diagnostic sensors.

We test the sensor logic by importing the module with properly stubbed HA
base classes so that class creation succeeds.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Build proper stub base classes BEFORE importing sensor module
# ---------------------------------------------------------------------------

# Create real base classes instead of MagicMock (avoids metaclass conflict)
class _FakeCoordinatorEntity:
    def __init__(self, coordinator):
        pass

class _FakeSensorEntity:
    _attr_name = ""
    _attr_unique_id = ""
    _attr_icon = ""
    _attr_native_unit_of_measurement = None
    _attr_entity_category = None

    @property
    def native_value(self):
        return None

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

# Provide real classes for the update_coordinator and sensor modules
_coordinator_mod = types.ModuleType("homeassistant.helpers.update_coordinator")
_coordinator_mod.CoordinatorEntity = _FakeCoordinatorEntity
_coordinator_mod.DataUpdateCoordinator = MagicMock
_ha_stubs["homeassistant.helpers.update_coordinator"] = _coordinator_mod

_sensor_mod = types.ModuleType("homeassistant.components.sensor")
_sensor_mod.SensorEntity = _FakeSensorEntity
_ha_stubs["homeassistant.components.sensor"] = _sensor_mod

for mod_name, mod_obj in _ha_stubs.items():
    sys.modules[mod_name] = mod_obj

# NOW import sensor module (classes will inherit from our real stubs)
# Force reimport in case it was cached with MagicMock stubs
if "custom_components.gaming_assistant.sensor" in sys.modules:
    del sys.modules["custom_components.gaming_assistant.sensor"]

from custom_components.gaming_assistant.sensor import (
    GamingAssistantLatencySensor,
    GamingAssistantErrorCountSensor,
    GamingAssistantFramesProcessedSensor,
    GamingAssistantLastAnalysisSensor,
    GamingAssistantAgentActionSensor,
)


class TestDiagnosticSensors(unittest.TestCase):
    """Verify diagnostic sensors read from coordinator properties."""

    def _mock_coordinator(self, latency=1.5, error_count=3, frames=42, last_analysis="2026-01-01T12:00:00"):
        coord = MagicMock()
        coord.latency = latency
        coord.error_count = error_count
        coord.frames_processed = frames
        coord.last_analysis = last_analysis
        return coord

    def test_latency_sensor(self):
        coord = self._mock_coordinator(latency=2.345)
        sensor = GamingAssistantLatencySensor(coord)
        self.assertEqual(sensor.native_value, 2.345)
        self.assertEqual(sensor._attr_native_unit_of_measurement, "s")
        self.assertEqual(sensor._attr_icon, "mdi:clock")

    def test_error_count_sensor(self):
        coord = self._mock_coordinator(error_count=7)
        sensor = GamingAssistantErrorCountSensor(coord)
        self.assertEqual(sensor.native_value, 7)
        self.assertEqual(sensor._attr_icon, "mdi:alert-circle")

    def test_frames_processed_sensor(self):
        coord = self._mock_coordinator(frames=100)
        sensor = GamingAssistantFramesProcessedSensor(coord)
        self.assertEqual(sensor.native_value, 100)
        self.assertEqual(sensor._attr_icon, "mdi:image-multiple")

    def test_last_analysis_sensor(self):
        coord = self._mock_coordinator(last_analysis="2026-03-14T10:30:00")
        sensor = GamingAssistantLastAnalysisSensor(coord)
        self.assertEqual(sensor.native_value, "2026-03-14T10:30:00")
        self.assertEqual(sensor._attr_icon, "mdi:clock-check")

    def test_sensors_initial_zero_state(self):
        coord = self._mock_coordinator(latency=0.0, error_count=0, frames=0, last_analysis="")
        self.assertEqual(GamingAssistantLatencySensor(coord).native_value, 0.0)
        self.assertEqual(GamingAssistantErrorCountSensor(coord).native_value, 0)
        self.assertEqual(GamingAssistantFramesProcessedSensor(coord).native_value, 0)
        self.assertEqual(GamingAssistantLastAnalysisSensor(coord).native_value, "")

    def test_unique_ids(self):
        self.assertEqual(GamingAssistantLatencySensor._attr_unique_id, "gaming_assistant_latency")
        self.assertEqual(GamingAssistantErrorCountSensor._attr_unique_id, "gaming_assistant_error_count")
        self.assertEqual(GamingAssistantFramesProcessedSensor._attr_unique_id, "gaming_assistant_frames_processed")
        self.assertEqual(GamingAssistantLastAnalysisSensor._attr_unique_id, "gaming_assistant_last_analysis")

    def test_entity_category_not_diagnostic(self):
        """Sensors should appear as regular entities, not diagnostic."""
        for cls in (GamingAssistantLatencySensor, GamingAssistantErrorCountSensor,
                    GamingAssistantFramesProcessedSensor, GamingAssistantLastAnalysisSensor):
            self.assertIsNone(getattr(cls, "_attr_entity_category", None))


class TestAgentActionSensor(unittest.TestCase):
    """Verify the Agent Mode audit sensor surfaces governor state."""

    def _coord(self, status="", action=None, published=0, failed=0,
               mode=False, buttons=None):
        coord = MagicMock()
        coord.agent_last_action_status = status
        coord.agent_last_action = action
        coord.agent_last_action_timestamp = "2026-06-18T12:00:00"
        coord.agent_actions_published = published
        coord.agent_actions_failed = failed
        coord.agent_mode = mode
        coord.agent_allowed_buttons = buttons if buttons is not None else []
        return coord

    def test_idle_when_no_action(self):
        sensor = GamingAssistantAgentActionSensor(self._coord(status=""))
        self.assertEqual(sensor.native_value, "idle")

    def test_reflects_status(self):
        sensor = GamingAssistantAgentActionSensor(self._coord(status="published"))
        self.assertEqual(sensor.native_value, "published")

    def test_attributes(self):
        sensor = GamingAssistantAgentActionSensor(self._coord(
            status="published",
            action={"action": "button", "button": "A"},
            published=3, failed=1, mode=True, buttons=["A", "B"],
        ))
        attrs = sensor.extra_state_attributes
        self.assertEqual(attrs["actions_published"], 3)
        self.assertEqual(attrs["actions_failed"], 1)
        self.assertTrue(attrs["agent_mode"])
        self.assertEqual(attrs["allowed_buttons"], ["A", "B"])
        self.assertEqual(attrs["last_action"], {"action": "button", "button": "A"})

    def test_allowed_buttons_all_when_empty(self):
        sensor = GamingAssistantAgentActionSensor(self._coord(buttons=[]))
        self.assertEqual(sensor.extra_state_attributes["allowed_buttons"], "all")

    def test_unique_id(self):
        self.assertEqual(
            GamingAssistantAgentActionSensor._attr_unique_id,
            "gaming_assistant_agent_action",
        )


if __name__ == "__main__":
    unittest.main()
