"""Sensor platform for Gaming Assistant."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gaming Assistant sensors."""
    coordinator: GamingAssistantCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        GamingAssistantTipSensor(coordinator),
        GamingAssistantStatusSensor(coordinator),
        GamingAssistantHistorySensor(coordinator),
        GamingAssistantLatencySensor(coordinator),
        GamingAssistantErrorCountSensor(coordinator),
        GamingAssistantFramesProcessedSensor(coordinator),
        GamingAssistantLastAnalysisSensor(coordinator),
        GamingAssistantActiveWatchersSensor(coordinator),
        GamingAssistantRegisteredWorkersSensor(coordinator),
    ])


class GamingAssistantTipSensor(CoordinatorEntity, SensorEntity):
    """Shows the latest AI gaming tip."""

    _attr_name = "Gaming Assistant Tip"
    _attr_unique_id = "gaming_assistant_tip"
    _attr_icon = "mdi:robot"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator

    @property
    def native_value(self) -> str:
        return self._coordinator.tip

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "gaming_mode": self._coordinator.gaming_mode,
            "worker_status": self._coordinator.status,
            "game": self._coordinator.current_game,
            "assistant_mode": self._coordinator.assistant_mode,
            "spoiler_level": self._coordinator.spoiler_manager.get_settings(
                self._coordinator.current_game or None
            ),
        }


class GamingAssistantStatusSensor(CoordinatorEntity, SensorEntity):
    """Shows the current worker status."""

    _attr_name = "Gaming Assistant Status"
    _attr_unique_id = "gaming_assistant_status"
    _attr_icon = "mdi:information-outline"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator

    @property
    def native_value(self) -> str:
        return self._coordinator.status


class GamingAssistantHistorySensor(CoordinatorEntity, SensorEntity):
    """Shows tip history for the current session."""

    _attr_name = "Gaming Assistant History"
    _attr_unique_id = "gaming_assistant_history"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator

    @property
    def native_value(self) -> int:
        return self._coordinator.tip_count

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "recent_tips": self._coordinator.recent_tips,
            "current_game": self._coordinator.current_game,
            "client_id": self._coordinator.current_client_id,
        }


class GamingAssistantLatencySensor(CoordinatorEntity, SensorEntity):
    """Duration of the last analysis in seconds."""

    _attr_name = "Gaming Assistant Latency"
    _attr_unique_id = "gaming_assistant_latency"
    _attr_native_unit_of_measurement = "s"
    _attr_icon = "mdi:clock"
    _attr_entity_category = "diagnostic"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator

    @property
    def native_value(self) -> float:
        return self._coordinator.latency


class GamingAssistantErrorCountSensor(CoordinatorEntity, SensorEntity):
    """Number of errors since startup."""

    _attr_name = "Gaming Assistant Error Count"
    _attr_unique_id = "gaming_assistant_error_count"
    _attr_icon = "mdi:alert-circle"
    _attr_entity_category = "diagnostic"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator

    @property
    def native_value(self) -> int:
        return self._coordinator.error_count


class GamingAssistantFramesProcessedSensor(CoordinatorEntity, SensorEntity):
    """Total number of frames analyzed."""

    _attr_name = "Gaming Assistant Frames Processed"
    _attr_unique_id = "gaming_assistant_frames_processed"
    _attr_icon = "mdi:image-multiple"
    _attr_entity_category = "diagnostic"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator

    @property
    def native_value(self) -> int:
        return self._coordinator.frames_processed


class GamingAssistantLastAnalysisSensor(CoordinatorEntity, SensorEntity):
    """Timestamp of the last successful analysis."""

    _attr_name = "Gaming Assistant Last Analysis"
    _attr_unique_id = "gaming_assistant_last_analysis"
    _attr_icon = "mdi:clock-check"
    _attr_entity_category = "diagnostic"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator

    @property
    def native_value(self) -> str:
        return self._coordinator.last_analysis


class GamingAssistantActiveWatchersSensor(CoordinatorEntity, SensorEntity):
    """Number of active camera watchers."""

    _attr_name = "Gaming Assistant Active Watchers"
    _attr_unique_id = "gaming_assistant_active_watchers"
    _attr_icon = "mdi:camera-eye"
    _attr_entity_category = "diagnostic"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator

    @property
    def native_value(self) -> int:
        return len(self._coordinator.active_camera_watchers)

    @property
    def extra_state_attributes(self) -> dict:
        return {"watchers": self._coordinator.active_camera_watchers}


class GamingAssistantRegisteredWorkersSensor(CoordinatorEntity, SensorEntity):
    """Number of registered workers (auto-discovered via MQTT)."""

    _attr_name = "Gaming Assistant Workers"
    _attr_unique_id = "gaming_assistant_registered_workers"
    _attr_icon = "mdi:devices"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator

    @property
    def native_value(self) -> int:
        return len(self._coordinator.registered_workers)

    @property
    def extra_state_attributes(self) -> dict:
        return {"workers": self._coordinator.registered_workers}
