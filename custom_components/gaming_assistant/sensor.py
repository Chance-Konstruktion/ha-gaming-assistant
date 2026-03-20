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
        GamingAssistantSessionSummarySensor(coordinator),
    ])


class GamingAssistantTipSensor(CoordinatorEntity, SensorEntity):
    """Shows the latest AI gaming tip."""

    _attr_name = "Gaming Assistant Tip"
    _attr_unique_id = "gaming_assistant_tip"
    _attr_icon = "mdi:robot"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        tip = self._coordinator.tip
        # HA state has a 255-char limit; truncate for state, full tip in attributes
        if len(tip) > 250:
            return tip[:247] + "..."
        return tip

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "full_tip": self._coordinator.tip,
            "gaming_mode": self._coordinator.gaming_mode,
            "worker_status": self._coordinator.status,
            "game": self._coordinator.current_game,
        }


class GamingAssistantStatusSensor(CoordinatorEntity, SensorEntity):
    """Shows the current worker status."""

    _attr_name = "Gaming Assistant Status"
    _attr_unique_id = "gaming_assistant_status"
    _attr_icon = "mdi:information-outline"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        return self._coordinator.status

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "assistant_mode": self._coordinator.assistant_mode,
            "default_game_hint": self._coordinator.default_game_hint,
            "available_game_packs": self._coordinator.available_game_packs,
            "available_models": self._coordinator.data.get("available_models", []),
            "active_model": self._coordinator.active_model,
            "active_client_id": self._coordinator.data.get("active_client_id", ""),
            "clients": self._coordinator.data.get("clients", {}),
        }


class GamingAssistantHistorySensor(CoordinatorEntity, SensorEntity):
    """Shows tip history for the current session."""

    _attr_name = "Gaming Assistant History"
    _attr_unique_id = "gaming_assistant_history"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

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

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float:
        return self._coordinator.latency


class GamingAssistantErrorCountSensor(CoordinatorEntity, SensorEntity):
    """Number of errors since startup."""

    _attr_name = "Gaming Assistant Error Count"
    _attr_unique_id = "gaming_assistant_error_count"
    _attr_icon = "mdi:alert-circle"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> int:
        return self._coordinator.error_count


class GamingAssistantFramesProcessedSensor(CoordinatorEntity, SensorEntity):
    """Total number of frames analyzed."""

    _attr_name = "Gaming Assistant Frames Processed"
    _attr_unique_id = "gaming_assistant_frames_processed"
    _attr_icon = "mdi:image-multiple"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> int:
        return self._coordinator.frames_processed


class GamingAssistantLastAnalysisSensor(CoordinatorEntity, SensorEntity):
    """Timestamp of the last successful analysis."""

    _attr_name = "Gaming Assistant Last Analysis"
    _attr_unique_id = "gaming_assistant_last_analysis"
    _attr_icon = "mdi:clock-check"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        return self._coordinator.last_analysis


class GamingAssistantActiveWatchersSensor(CoordinatorEntity, SensorEntity):
    """Number of active camera watchers."""

    _attr_name = "Gaming Assistant Active Watchers"
    _attr_unique_id = "gaming_assistant_active_watchers"
    _attr_icon = "mdi:camera-eye"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

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
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> int:
        return len(self._coordinator.registered_workers)

    @property
    def extra_state_attributes(self) -> dict:
        return {"workers": self._coordinator.registered_workers}


class GamingAssistantSessionSummarySensor(CoordinatorEntity, SensorEntity):
    """Shows the last session summary."""

    _attr_name = "Gaming Assistant Session Summary"
    _attr_unique_id = "gaming_assistant_session_summary"
    _attr_icon = "mdi:text-box-outline"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        summary = self._coordinator.last_summary
        if not summary:
            return "No summary yet"
        if len(summary) > 250:
            return summary[:247] + "..."
        return summary

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "full_summary": self._coordinator.last_summary,
            "game": self._coordinator.last_summary_game,
            "timestamp": self._coordinator.last_summary_timestamp,
        }
