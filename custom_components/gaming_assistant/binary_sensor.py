"""Binary Sensor platform for Gaming Assistant."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up Gaming Assistant binary sensors."""
    coordinator: GamingAssistantCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        GamingModeSensor(coordinator),
        GamingAssistantHealthSensor(coordinator),
    ])


class GamingModeSensor(CoordinatorEntity, BinarySensorEntity):
    """Indicates whether gaming mode is currently active."""

    _attr_name = "Gaming Mode"
    _attr_unique_id = "gaming_mode"
    _attr_icon = "mdi:gamepad-variant"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        return self._coordinator.gaming_mode

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "last_tip": self._coordinator.tip,
        }


class GamingAssistantHealthSensor(CoordinatorEntity, BinarySensorEntity):
    """Single-glance pipeline health: MQTT up + LLM path not failing.

    Uses the PROBLEM device class, so ``on`` means *a problem exists*. The
    coordinator reports health as "operational"; we invert it here. The
    diagnostics behind the verdict are in the attributes.
    """

    _attr_name = "Gaming Assistant Healthy"
    _attr_unique_id = "gaming_assistant_healthy"
    _attr_icon = "mdi:heart-pulse"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        # PROBLEM device class: on == problem == NOT healthy.
        return not self._coordinator.pipeline_healthy

    @property
    def extra_state_attributes(self) -> dict:
        return self._coordinator.health_detail
