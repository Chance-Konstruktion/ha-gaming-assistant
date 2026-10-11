"""Number platform for Gaming Assistant."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .chess_bot import BOT_STRENGTH_MAX, BOT_STRENGTH_MIN
from .const import DOMAIN
from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gaming Assistant number entities."""
    coordinator: GamingAssistantCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        AnalysisIntervalNumber(coordinator),
        AnalysisTimeoutNumber(coordinator),
        ChessBotStrengthNumber(coordinator),
    ])


class AnalysisIntervalNumber(CoordinatorEntity, NumberEntity):
    """Number entity to adjust the capture/analysis interval."""

    _attr_name = "Gaming Assistant Interval"
    _attr_unique_id = "gaming_assistant_interval"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 5
    _attr_native_max_value = 120
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "s"
    _attr_mode = NumberMode.SLIDER
    _attr_translation_key = "interval"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float:
        return self._coordinator.analysis_interval

    async def async_set_native_value(self, value: float) -> None:
        self._coordinator.set_analysis_interval(int(value))


class AnalysisTimeoutNumber(CoordinatorEntity, NumberEntity):
    """Number entity to adjust the analysis timeout."""

    _attr_name = "Gaming Assistant Timeout"
    _attr_unique_id = "gaming_assistant_timeout"
    _attr_icon = "mdi:clock-alert-outline"
    _attr_native_min_value = 10
    _attr_native_max_value = 300
    _attr_native_step = 5
    _attr_native_unit_of_measurement = "s"
    _attr_mode = NumberMode.SLIDER
    _attr_translation_key = "timeout"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float:
        return self._coordinator.analysis_timeout

    async def async_set_native_value(self, value: float) -> None:
        self._coordinator.set_analysis_timeout(int(value))


class ChessBotStrengthNumber(CoordinatorEntity, NumberEntity):
    """Search depth the chess bot plays at (1 = quick, 4 = strongest)."""

    _attr_name = "Gaming Assistant Chess Bot Strength"
    _attr_unique_id = "gaming_assistant_chess_bot_strength"
    _attr_icon = "mdi:chess-queen"
    _attr_native_min_value = BOT_STRENGTH_MIN
    _attr_native_max_value = BOT_STRENGTH_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_translation_key = "chess_bot_strength"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float:
        return self._coordinator.chess_bot_strength

    async def async_set_native_value(self, value: float) -> None:
        await self._coordinator.async_set_chess_bot(strength=int(value))
