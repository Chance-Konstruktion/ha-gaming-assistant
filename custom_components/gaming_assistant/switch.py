"""Switch platform for Gaming Assistant."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
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
    """Set up Gaming Assistant switch entities."""
    coordinator: GamingAssistantCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        AutoAnnounceSwitch(coordinator),
        AutoSummarySwitch(coordinator),
    ])


class AutoAnnounceSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to toggle automatic TTS announcements of new tips."""

    _attr_name = "Gaming Assistant Auto Announce"
    _attr_unique_id = "gaming_assistant_auto_announce"
    _attr_icon = "mdi:bullhorn"
    _attr_translation_key = "auto_announce"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        return self._coordinator.auto_announce

    async def async_turn_on(self, **kwargs) -> None:
        self._coordinator.set_auto_announce(True)

    async def async_turn_off(self, **kwargs) -> None:
        self._coordinator.set_auto_announce(False)


class AutoSummarySwitch(CoordinatorEntity, SwitchEntity):
    """Switch to toggle automatic session summaries."""

    _attr_name = "Gaming Assistant Auto Summary"
    _attr_unique_id = "gaming_assistant_auto_summary"
    _attr_icon = "mdi:text-box-check"
    _attr_translation_key = "auto_summary"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        return self._coordinator.auto_summary

    async def async_turn_on(self, **kwargs) -> None:
        self._coordinator.set_auto_summary(True)

    async def async_turn_off(self, **kwargs) -> None:
        self._coordinator.set_auto_summary(False)
