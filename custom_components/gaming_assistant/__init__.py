"""Gaming Assistant – AI-powered gaming coach for Home Assistant."""
from __future__ import annotations

import base64
import logging
from pathlib import Path

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_CAMERA_ENTITY,
    CONF_MODEL,
    CONF_TTS_ENTITY,
    CONF_TTS_TARGET,
    DOMAIN,
    MAX_IMAGE_BYTES,
)
from .coordinator import GamingAssistantCoordinator
from .prompt_packs import download_prompt_packs

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.CONVERSATION,
    Platform.IMAGE,
]

_ALL_SERVICES = (
    "analyze", "start", "stop",
    "process_image", "ask", "set_spoiler_level", "set_spoiler_profile",
    "clear_history", "capture_from_camera",
    "watch_camera", "stop_watch_camera",
    "announce", "summarize_session", "configure",
    "set_game_hint", "list_game_packs", "set_source_type",
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gaming Assistant from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = GamingAssistantCoordinator(hass, dict(entry.data))
    coordinator._config_entry_id = entry.entry_id
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to platforms so entities are available immediately
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # -- Register sidebar panel (once) ----------------------------------------
    if "panel_registered" not in hass.data.get(DOMAIN, {}):
        from homeassistant.components.frontend import (  # noqa: E501
            async_register_built_in_panel,
        )
        from homeassistant.components.http import StaticPathConfig

        frontend_path = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths([
            StaticPathConfig(
                url_path=f"/{DOMAIN}/frontend",
                path=str(frontend_path),
                cache_headers=False,
            )
        ])
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="Gaming",
            sidebar_icon="mdi:gamepad-variant",
            frontend_url_path="gaming-assistant",
            require_admin=False,
            config={
                "_panel_custom": {
                    "name": "gaming-assistant-panel",
                    "js_url": f"/{DOMAIN}/frontend/panel.js",
                    "embed_iframe": False,
                }
            },
        )
        hass.data[DOMAIN]["panel_registered"] = True

    async def _setup_mqtt(_event=None) -> None:
        """Set up MQTT subscriptions once MQTT is ready."""
        # Download latest prompt packs in the background
        packs_cache = (
            Path(hass.config.config_dir) / "gaming_assistant" / "prompt_packs"
        )
        try:
            if await download_prompt_packs(packs_cache):
                coordinator.pack_loader.reload()
                _LOGGER.info("Prompt packs updated from GitHub")
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not update prompt packs, using cached/bundled")

        # Fetch available Ollama models for the panel dropdown
        try:
            await coordinator.async_fetch_available_models()
        except (OSError, TimeoutError):
            _LOGGER.debug("Could not fetch Ollama models on startup")

        try:
            await coordinator.async_setup_mqtt()
        except HomeAssistantError:
            _LOGGER.exception("Failed to set up MQTT subscriptions")

        # Start daily history cleanup
        coordinator.start_cleanup_task()

        # Auto-start camera watcher if configured
        camera_entity = entry.data.get(CONF_CAMERA_ENTITY, "") or entry.options.get(
            CONF_CAMERA_ENTITY, ""
        )
        if camera_entity:
            try:
                await coordinator.async_watch_camera(camera_entity)
                _LOGGER.info("Auto-started camera watcher for %s", camera_entity)
            except HomeAssistantError:
                _LOGGER.exception(
                    "Failed to auto-start camera watcher for %s", camera_entity
                )

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
            """Start the gaming assistant.

            If a camera is configured (or watchers were previously active),
            start the built-in camera watcher.  Also send the legacy MQTT
            command so external workers are started too.
            """
            for coord in hass.data[DOMAIN].values():
                if not isinstance(coord, GamingAssistantCoordinator):
                    continue
                camera = coord.configured_camera
                if camera and not coord.active_camera_watchers:
                    await coord.async_watch_camera(camera)
                    _LOGGER.info("Start: camera watcher started for %s", camera)
                await coord.async_start_assistant()
                break
            # Also send legacy MQTT command for external workers
            await mqtt.async_publish(hass, "gaming_assistant/command", "start")

        async def handle_stop(call: ServiceCall) -> None:
            """Stop the gaming assistant.

            Stops all active camera watchers and sends the legacy MQTT stop
            command for external workers.
            """
            for coord in hass.data[DOMAIN].values():
                if not isinstance(coord, GamingAssistantCoordinator):
                    continue
                if coord.active_camera_watchers:
                    await coord.async_stop_watch_camera()
                    _LOGGER.info("Stop: all camera watchers stopped")
                await coord.async_stop_assistant()
                break
            # Also send legacy MQTT command for external workers
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
                except (ValueError, base64.binascii.Error) as err:
                    _LOGGER.error("Invalid base64 image data: %s", err)
                    return
            else:
                _LOGGER.error("process_image requires image_path or image_base64")
                return

            if len(image_bytes) > MAX_IMAGE_BYTES:
                _LOGGER.error(
                    "Image too large (%d bytes, max %d)", len(image_bytes), MAX_IMAGE_BYTES
                )
                return

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    await coord.async_process_manual_image(
                        image_bytes, game_hint, client_type
                    )
                    break

        async def handle_ask(call: ServiceCall) -> None:
            """Ask a direct question to the assistant (optional image context)."""
            question = (call.data.get("question") or "").strip()
            if not question:
                _LOGGER.error("ask requires a non-empty question")
                return

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
                except (ValueError, base64.binascii.Error) as err:
                    _LOGGER.error("Invalid base64 image data: %s", err)
                    return

            if image_bytes and len(image_bytes) > MAX_IMAGE_BYTES:
                _LOGGER.error(
                    "Image too large (%d bytes, max %d)", len(image_bytes), MAX_IMAGE_BYTES
                )
                return

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    await coord.async_ask(
                        question=question,
                        image_bytes=image_bytes,
                        game_hint=game_hint,
                        client_type=client_type,
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

        async def handle_set_spoiler_profile(call: ServiceCall) -> None:
            """Set or clear a per-game spoiler profile."""
            game = (call.data.get("game") or "").strip()
            level = call.data.get("level", "medium")
            clear = bool(call.data.get("clear", False))

            if not game:
                _LOGGER.error("set_spoiler_profile requires a game name")
                return

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    if clear:
                        coord.spoiler_manager.clear_game_profile(game)
                        _LOGGER.info("Spoiler profile cleared for game: %s", game)
                    else:
                        coord.spoiler_manager.set_game_profile(game, level)
                        _LOGGER.info("Spoiler profile set for game: %s=%s", game, level)
                    break

        async def handle_clear_history(call: ServiceCall) -> None:
            """Clear tip history."""
            game = call.data.get("game")

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    await coord.async_clear_history(game)
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
            except HomeAssistantError as err:
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

        async def handle_watch_camera(call: ServiceCall) -> None:
            """Start continuous monitoring of a HA camera entity."""
            entity_id = call.data.get("entity_id", "")
            game_hint = call.data.get("game_hint", "")
            client_type = call.data.get("client_type", "tabletop")
            interval = int(call.data.get("interval", 0))

            if not entity_id:
                _LOGGER.error("watch_camera requires entity_id")
                return

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    await coord.async_watch_camera(
                        entity_id, game_hint, client_type, interval
                    )
                    break

        async def handle_stop_watch_camera(call: ServiceCall) -> None:
            """Stop continuous camera monitoring."""
            entity_id = call.data.get("entity_id", "")

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    await coord.async_stop_watch_camera(entity_id)
                    break

        async def handle_announce(call: ServiceCall) -> None:
            """Announce the current tip (or a custom message) via TTS."""
            message = call.data.get("message", "")
            tts_entity = call.data.get("tts_entity", "")
            media_player_entity_id = call.data.get("media_player_entity_id", "")

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    await coord.async_announce(
                        message=message,
                        tts_entity=tts_entity,
                        media_player_entity_id=media_player_entity_id,
                    )
                    break

        async def handle_summarize_session(call: ServiceCall) -> None:
            """Generate a summary of the current or last gaming session."""
            game = call.data.get("game", "")

            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    await coord.async_summarize_session(game=game)
                    break

        async def handle_set_game_hint(call: ServiceCall) -> None:
            """Set persistent game hint for camera watchers."""
            game_hint = call.data.get("game_hint", "")
            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    coord.set_default_game_hint(game_hint)
                    break

        async def handle_set_source_type(call: ServiceCall) -> None:
            """Set the source type (auto, console, tabletop)."""
            source_type = call.data.get("source_type", "auto")
            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    coord.set_source_type(source_type)
                    break

        async def handle_list_game_packs(call: ServiceCall) -> None:
            """Return available prompt packs (mainly for internal use)."""
            for coord in hass.data[DOMAIN].values():
                if isinstance(coord, GamingAssistantCoordinator):
                    packs = coord.available_game_packs
                    _LOGGER.info("Available game packs: %s", packs)
                    break

        async def handle_configure(call: ServiceCall) -> None:
            """Update runtime configuration (camera, TTS, model) from the panel."""
            camera = call.data.get("camera_entity")
            tts_entity = call.data.get("tts_entity")
            tts_target = call.data.get("tts_target")
            model = call.data.get("model")
            game_hint = call.data.get("game_hint")

            for eid, coord in hass.data[DOMAIN].items():
                if not isinstance(coord, GamingAssistantCoordinator):
                    continue
                if camera is not None:
                    coord._tts_entity = coord._tts_entity  # keep
                    # Stop old watcher, start new one if non-empty
                    if coord.active_camera_watchers:
                        await coord.async_stop_watch_camera()
                    if camera:
                        await coord.async_watch_camera(camera)
                if tts_entity is not None:
                    coord._tts_entity = tts_entity
                if tts_target is not None:
                    coord._tts_target = tts_target
                if model is not None and model:
                    await coord.async_set_model(model)
                if game_hint is not None:
                    coord.set_default_game_hint(game_hint)

                # Persist to config entry options
                cfg_entry = hass.config_entries.async_get_entry(
                    coord._config_entry_id
                )
                if cfg_entry:
                    new_options = dict(cfg_entry.options)
                    if camera is not None:
                        new_options[CONF_CAMERA_ENTITY] = camera
                    if tts_entity is not None:
                        new_options[CONF_TTS_ENTITY] = tts_entity
                    if tts_target is not None:
                        new_options[CONF_TTS_TARGET] = tts_target
                    if model is not None and model:
                        new_options[CONF_MODEL] = model
                    hass.config_entries.async_update_entry(
                        cfg_entry, options=new_options
                    )
                _LOGGER.info("Configuration updated from panel")
                break

        hass.services.async_register(DOMAIN, "analyze", handle_analyze)
        hass.services.async_register(DOMAIN, "start", handle_start)
        hass.services.async_register(DOMAIN, "stop", handle_stop)
        hass.services.async_register(DOMAIN, "process_image", handle_process_image)
        hass.services.async_register(DOMAIN, "ask", handle_ask)
        hass.services.async_register(DOMAIN, "set_spoiler_level", handle_set_spoiler_level)
        hass.services.async_register(DOMAIN, "set_spoiler_profile", handle_set_spoiler_profile)
        hass.services.async_register(DOMAIN, "clear_history", handle_clear_history)
        hass.services.async_register(DOMAIN, "capture_from_camera", handle_capture_from_camera)
        hass.services.async_register(DOMAIN, "watch_camera", handle_watch_camera)
        hass.services.async_register(DOMAIN, "stop_watch_camera", handle_stop_watch_camera)
        hass.services.async_register(DOMAIN, "announce", handle_announce)
        hass.services.async_register(DOMAIN, "summarize_session", handle_summarize_session)
        hass.services.async_register(DOMAIN, "configure", handle_configure)
        hass.services.async_register(DOMAIN, "set_game_hint", handle_set_game_hint)
        hass.services.async_register(DOMAIN, "set_source_type", handle_set_source_type)
        hass.services.async_register(DOMAIN, "list_game_packs", handle_list_game_packs)

    _LOGGER.info("Gaming Assistant integration loaded successfully")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: GamingAssistantCoordinator | None = hass.data[DOMAIN].get(
        entry.entry_id
    )
    if coordinator:
        await coordinator.async_shutdown()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Remove services and panel only when last entry is unloaded
        remaining = {
            k: v
            for k, v in hass.data[DOMAIN].items()
            if isinstance(v, GamingAssistantCoordinator)
        }
        if not remaining:
            for service in _ALL_SERVICES:
                hass.services.async_remove(DOMAIN, service)
            hass.components.frontend.async_remove_panel("gaming-assistant")
            hass.data[DOMAIN].pop("panel_registered", None)

    return unload_ok
