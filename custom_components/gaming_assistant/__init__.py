"""Gaming Assistant – AI-powered gaming coach for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN
from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gaming Assistant from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = GamingAssistantCoordinator(hass, dict(entry.data))
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to platforms so entities are available immediately
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _setup_mqtt(_event=None) -> None:
        """Set up MQTT subscriptions once MQTT is ready."""
        try:
            await coordinator.async_setup_mqtt()
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Failed to set up MQTT subscriptions")

    # On first boot wait for HA_STARTED so MQTT is fully initialised.
    # On reload (hass.is_running == True) connect immediately.
    if hass.is_running:
        await _setup_mqtt()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _setup_mqtt)

    # -- Register services ---------------------------------------------------
    # Only register once (multiple config entries share the same domain)
    if not hass.services.has_service(DOMAIN, "analyze"):

        async def handle_analyze(call: ServiceCall) -> None:
            await mqtt.async_publish(hass, "gaming_assistant/command", "analyze")

        async def handle_start(call: ServiceCall) -> None:
            await mqtt.async_publish(hass, "gaming_assistant/command", "start")

        async def handle_stop(call: ServiceCall) -> None:
            await mqtt.async_publish(hass, "gaming_assistant/command", "stop")

        hass.services.async_register(DOMAIN, "analyze", handle_analyze)
        hass.services.async_register(DOMAIN, "start", handle_start)
        hass.services.async_register(DOMAIN, "stop", handle_stop)

    _LOGGER.info("Gaming Assistant integration loaded successfully")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: GamingAssistantCoordinator | None = hass.data[DOMAIN].get(
        entry.entry_id
    )
    if coordinator:
        coordinator.async_unsubscribe()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Remove services only when last entry is unloaded
        if not hass.data[DOMAIN]:
            for service in ("analyze", "start", "stop"):
                hass.services.async_remove(DOMAIN, service)

    return unload_ok
