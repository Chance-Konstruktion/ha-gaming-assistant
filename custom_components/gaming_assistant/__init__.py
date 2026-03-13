"""Gaming Assistant – AI-powered gaming coach for Home Assistant."""
from __future__ import annotations

import base64
import logging
from pathlib import Path

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN
from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

_ALL_SERVICES = (
    "analyze", "start", "stop",
    "process_image", "set_spoiler_level", "clear_history",
    "capture_from_camera",
)


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

        async def handle_process_image(call: ServiceCall) -> None:
            """Manually trigger image analysis."""
            image_bytes = None

            image_path = call.data.get("image_path")
            image_base64 = call.data.get("image_base64")
            game_hint = call.data.get("game_hint", "")
            client_type = call.data.get("client_type", "pc")

            if image_path:
                path = Path(image_path)
                if path.exists():
                    image_bytes = path.read_bytes()
                else:
                    _LOGGER.error("Image file not found: %s", image_path)
                    return
            elif image_base64:
                try:
                    image_bytes = base64.b64decode(image_base64)
                except Exception as err:
                    _LOGGER.error("Invalid base64 image data: %s", err)
                    return
            else:
                _LOGGER.error("process_image requires image_path or image_base64")
                return

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    await coord.async_process_manual_image(
                        image_bytes, game_hint, client_type
                    )
                    break

        async def handle_set_spoiler_level(call: ServiceCall) -> None:
            """Change spoiler settings."""
            category = call.data.get("category", "all")
            level = call.data.get("level", "medium")
            game = call.data.get("game")

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    coord.spoiler_manager.set_level(category, level, game)
                    _LOGGER.info(
                        "Spoiler level set: %s=%s (game=%s)",
                        category, level, game or "global",
                    )
                    break

        async def handle_clear_history(call: ServiceCall) -> None:
            """Clear tip history."""
            game = call.data.get("game")

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    await coord.history_manager.clear(game)
                    _LOGGER.info("History cleared: %s", game or "all games")
                    break

        async def handle_capture_from_camera(call: ServiceCall) -> None:
            """Grab a snapshot from a HA camera entity and analyze it.

            This allows using any HA camera integration (IP Webcam,
            Generic Camera, etc.) as an image source -- no external
            capture agent needed.
            """
            entity_id = call.data.get("entity_id", "")
            game_hint = call.data.get("game_hint", "")
            client_type = call.data.get("client_type", "console")

            if not entity_id:
                _LOGGER.error("capture_from_camera requires entity_id")
                return

            try:
                from homeassistant.components.camera import async_get_image

                image = await async_get_image(hass, entity_id)
                image_bytes = image.content
            except Exception as err:
                _LOGGER.error(
                    "Failed to capture image from %s: %s", entity_id, err
                )
                return

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    await coord.async_process_manual_image(
                        image_bytes, game_hint, client_type
                    )
                    break

        hass.services.async_register(DOMAIN, "analyze", handle_analyze)
        hass.services.async_register(DOMAIN, "start", handle_start)
        hass.services.async_register(DOMAIN, "stop", handle_stop)
        hass.services.async_register(DOMAIN, "process_image", handle_process_image)
        hass.services.async_register(DOMAIN, "set_spoiler_level", handle_set_spoiler_level)
        hass.services.async_register(DOMAIN, "clear_history", handle_clear_history)
        hass.services.async_register(DOMAIN, "capture_from_camera", handle_capture_from_camera)

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
            for service in _ALL_SERVICES:
                hass.services.async_remove(DOMAIN, service)

    return unload_ok
