"""Image platform for Gaming Assistant – shows the last received frame."""
from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.image import ImageEntity
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
    """Set up Gaming Assistant image entity."""
    coordinator: GamingAssistantCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([GamingAssistantLastFrameImage(coordinator, hass)])


class GamingAssistantLastFrameImage(CoordinatorEntity, ImageEntity):
    """Displays the last frame received from a capture client."""

    _attr_name = "Gaming Assistant Last Frame"
    _attr_unique_id = "gaming_assistant_last_frame"
    _attr_icon = "mdi:image"
    _attr_content_type = "image/jpeg"

    def __init__(
        self,
        coordinator: GamingAssistantCoordinator,
        hass: HomeAssistant,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info
        self._cached_image: bytes | None = None

    @property
    def image_last_updated(self) -> datetime | None:
        ts = self._coordinator.last_image_timestamp
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return None

    async def async_image(self) -> bytes | None:
        return self._coordinator.last_image_bytes

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "client_id": self._coordinator.last_image_client_id,
            "timestamp": self._coordinator.last_image_timestamp,
            "game": self._coordinator.current_game,
        }
