"""Select platform for Gaming Assistant."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ASSISTANT_MODES,
    DOMAIN,
    SPOILER_LEVELS,
)
from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gaming Assistant select entities."""
    coordinator: GamingAssistantCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        AssistantModeSelect(coordinator),
        SpoilerLevelSelect(coordinator),
    ])


class AssistantModeSelect(CoordinatorEntity, SelectEntity):
    """Select entity to switch the assistant mode."""

    _attr_name = "Gaming Assistant Mode"
    _attr_unique_id = "gaming_assistant_assistant_mode"
    _attr_icon = "mdi:account-switch"
    _attr_options = ASSISTANT_MODES
    _attr_translation_key = "assistant_mode"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator

    @property
    def current_option(self) -> str:
        return self._coordinator.assistant_mode

    async def async_select_option(self, option: str) -> None:
        self._coordinator.set_assistant_mode(option)


class SpoilerLevelSelect(CoordinatorEntity, SelectEntity):
    """Select entity to switch the default spoiler level."""

    _attr_name = "Gaming Assistant Spoiler Level"
    _attr_unique_id = "gaming_assistant_spoiler_level"
    _attr_icon = "mdi:eye-off"
    _attr_options = SPOILER_LEVELS
    _attr_translation_key = "spoiler_level"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator

    @property
    def current_option(self) -> str:
        return self._coordinator.default_spoiler_level

    async def async_select_option(self, option: str) -> None:
        self._coordinator.set_default_spoiler_level(option)
