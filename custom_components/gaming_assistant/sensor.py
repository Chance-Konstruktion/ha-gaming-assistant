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
