"""Coordinator for Gaming Assistant integration."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_DEFAULT_SPOILER,
    CONF_MODEL,
    CONF_OLLAMA_HOST,
    CONF_TIMEOUT,
    DEFAULT_SPOILER_LEVEL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    MQTT_IMAGE_TOPIC,
    MQTT_META_TOPIC,
    MQTT_MODE_TOPIC,
    MQTT_STATUS_TOPIC,
    MQTT_TIP_TOPIC,
)
from .history import HistoryManager
from .image_processor import ImageProcessor
from .prompt_packs import PromptPackLoader
from .spoiler import SpoilerManager

_LOGGER = logging.getLogger(__name__)

MQTT_RETRY_ATTEMPTS = 5
MQTT_RETRY_BASE_DELAY = 3  # seconds, doubles each attempt


class GamingAssistantCoordinator(DataUpdateCoordinator):
    """Manages Gaming Assistant state via MQTT push updates."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # Pure push via MQTT, no polling
        )
        self.config = config
        self._tip: str = "Waiting for tips..."
        self._gaming_mode: bool = False
        self._status: str = "idle"
        self._unsubscribe_callbacks: list = []
        self._mqtt_connected: bool = False

        # v0.4 Thin Client components
        self._current_game: str = ""
        self._current_client_id: str = ""
        self._recent_tips: list[dict] = []
        self._tip_count: int = 0
        self._client_metadata: dict[str, dict] = {}
        self._processing: bool = False

        # Configurable timeout
        self._analysis_timeout: int = config.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)

        # Camera watchers: entity_id → {task, cancel_event, game_hint, client_type, interval}
        self._camera_watchers: dict[str, dict[str, Any]] = {}

        # Runtime metrics
        self._latency: float = 0.0
        self._error_count: int = 0
        self._frames_processed: int = 0
        self._last_analysis: str = ""

        # Initialize managers
        self._history = HistoryManager(hass.config.config_dir)
        self._spoiler = SpoilerManager(
            f"{hass.config.config_dir}/gaming_assistant/spoiler_profiles.json"
        )
        default_spoiler = config.get(CONF_DEFAULT_SPOILER, DEFAULT_SPOILER_LEVEL)
        self._spoiler.initialize(default_spoiler)
        self._spoiler.load()
        self._pack_loader = PromptPackLoader()
        self._pack_loader.load_all()
        self._image_processor = ImageProcessor(
            ollama_host=config.get(CONF_OLLAMA_HOST, "http://localhost:11434"),
            model=config.get(CONF_MODEL, "qwen2.5vl"),
            history_manager=self._history,
            spoiler_manager=self._spoiler,
            prompt_pack_loader=self._pack_loader,
            timeout=self._analysis_timeout,
        )

    # -- public properties ---------------------------------------------------

    @property
    def tip(self) -> str:
        return self._tip

    @property
    def gaming_mode(self) -> bool:
        return self._gaming_mode

    @property
    def status(self) -> str:
        return self._status

    @property
    def mqtt_connected(self) -> bool:
        return self._mqtt_connected

    @property
    def current_game(self) -> str:
        return self._current_game

    @property
    def current_client_id(self) -> str:
        return self._current_client_id

    @property
    def recent_tips(self) -> list[dict]:
        return self._recent_tips

    @property
    def tip_count(self) -> int:
        return self._tip_count

    @property
    def history_manager(self) -> HistoryManager:
        return self._history

    @property
    def spoiler_manager(self) -> SpoilerManager:
        return self._spoiler

    @property
    def image_processor(self) -> ImageProcessor:
        return self._image_processor

    @property
    def pack_loader(self) -> PromptPackLoader:
        return self._pack_loader

    @property
    def analysis_timeout(self) -> int:
        return self._analysis_timeout

    @property
    def latency(self) -> float:
        return self._latency

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def frames_processed(self) -> int:
        return self._frames_processed

    @property
    def last_analysis(self) -> str:
        return self._last_analysis

    # -- MQTT setup with retry -----------------------------------------------

    async def async_setup_mqtt(self) -> None:
        """Subscribe to MQTT topics with exponential-backoff retry."""
        delay = MQTT_RETRY_BASE_DELAY

        for attempt in range(1, MQTT_RETRY_ATTEMPTS + 1):
            try:
                await self._subscribe_topics()
                self._mqtt_connected = True
                _LOGGER.info(
                    "MQTT subscriptions active (attempt %d/%d)",
                    attempt, MQTT_RETRY_ATTEMPTS,
                )
                return
            except HomeAssistantError as err:
                _LOGGER.warning(
                    "MQTT subscribe attempt %d/%d failed: %s – retrying in %ds",
                    attempt, MQTT_RETRY_ATTEMPTS, err, delay,
                )
                if attempt < MQTT_RETRY_ATTEMPTS:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60)

        _LOGGER.error(
            "Could not subscribe to MQTT after %d attempts. "
            "Verify that the MQTT integration is configured and the broker is reachable. "
            "Reload this integration to retry.",
            MQTT_RETRY_ATTEMPTS,
        )

    async def _subscribe_topics(self) -> None:
        """Subscribe to all Gaming Assistant MQTT topics."""

        # -- Legacy topics (v0.2/v0.3 compatibility) -------------------------

        @callback
        def tip_received(msg) -> None:
            payload = msg.payload
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            self._tip = payload
            _LOGGER.debug("New tip received (legacy): %s", payload)
            self.async_set_updated_data(self._build_data())

        @callback
        def mode_received(msg) -> None:
            payload = msg.payload
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            self._gaming_mode = payload.strip().lower() in ("on", "true", "1")
            _LOGGER.debug("Gaming mode changed: %s", self._gaming_mode)
            self.async_set_updated_data(self._build_data())

        @callback
        def status_received(msg) -> None:
            payload = msg.payload
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            self._status = payload.strip().lower()
            self.async_set_updated_data(self._build_data())

        # -- New topics (v0.4 Thin Client) -----------------------------------

        @callback
        def image_received(msg) -> None:
            """Handle incoming image from a capture agent."""
            client_id = msg.topic.split("/")[1]
            _LOGGER.debug("Image received from client: %s", client_id)
            self.hass.async_create_task(
                self._process_image(client_id, msg.payload)
            )

        @callback
        def meta_received(msg) -> None:
            """Handle incoming metadata from a capture agent."""
            client_id = msg.topic.split("/")[1]
            try:
                payload = msg.payload
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
                metadata = json.loads(payload)
                self._client_metadata[client_id] = metadata
                _LOGGER.debug("Metadata from %s: %s", client_id, metadata)
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                _LOGGER.warning("Invalid metadata from %s: %s", client_id, err)

        unsub_tip = await mqtt.async_subscribe(
            self.hass, MQTT_TIP_TOPIC, tip_received, 0
        )
        unsub_mode = await mqtt.async_subscribe(
            self.hass, MQTT_MODE_TOPIC, mode_received, 0
        )
        unsub_status = await mqtt.async_subscribe(
            self.hass, MQTT_STATUS_TOPIC, status_received, 0
        )
        unsub_image = await mqtt.async_subscribe(
            self.hass, MQTT_IMAGE_TOPIC, image_received, 0, encoding=None
        )
        unsub_meta = await mqtt.async_subscribe(
            self.hass, MQTT_META_TOPIC, meta_received, 0
        )

        self._unsubscribe_callbacks = [
            unsub_tip, unsub_mode, unsub_status, unsub_image, unsub_meta,
        ]

    # -- Image processing pipeline -------------------------------------------

    async def _process_image(self, client_id: str, image_bytes: bytes) -> None:
        """Run the image processing pipeline for a received image."""
        if self._processing:
            _LOGGER.debug("Already processing an image, skipping")
            return

        self._processing = True
        self._status = "analyzing"
        self._current_client_id = client_id
        self._gaming_mode = True
        self.async_set_updated_data(self._build_data())

        try:
            metadata = self._client_metadata.get(client_id, {})

            game = metadata.get("window_title", "")
            if game:
                self._current_game = game

            start = time.monotonic()
            tip = await self.hass.async_add_executor_job(
                self._run_image_processing, image_bytes, client_id, metadata
            )
            self._latency = round(time.monotonic() - start, 3)

            if tip:
                self._tip = tip
                self._tip_count += 1
                self._frames_processed += 1
                self._last_analysis = (
                    time.strftime("%Y-%m-%dT%H:%M:%S")
                )
                self._recent_tips.append({
                    "tip": tip,
                    "game": self._current_game,
                    "client_id": client_id,
                })
                if len(self._recent_tips) > 5:
                    self._recent_tips = self._recent_tips[-5:]
                self._status = "idle"
                _LOGGER.info("New tip generated: %s", tip[:80])
            else:
                self._frames_processed += 1
                self._status = "idle"

        except Exception as err:
            _LOGGER.exception("Image processing failed: %s", err)
            self._error_count += 1
            self._status = "error"
        finally:
            self._processing = False
            self.async_set_updated_data(self._build_data())

    def _run_image_processing(
        self, image_bytes: bytes, client_id: str, metadata: dict
    ) -> str:
        """Synchronous wrapper to call async image processor from executor."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self._image_processor.process(image_bytes, client_id, metadata)
            )
        finally:
            loop.close()

    # -- Camera watcher ------------------------------------------------------

    @property
    def active_camera_watchers(self) -> dict[str, dict]:
        """Return info about all active camera watchers."""
        return {
            entity_id: {
                "game_hint": info["game_hint"],
                "client_type": info["client_type"],
                "interval": info["interval"],
            }
            for entity_id, info in self._camera_watchers.items()
        }

    async def async_watch_camera(
        self,
        entity_id: str,
        game_hint: str = "",
        client_type: str = "console",
        interval: int = 0,
    ) -> None:
        """Start continuous capture from a HA camera entity.

        Uses the configured analysis interval if *interval* is 0.
        """
        from .const import CONF_INTERVAL, DEFAULT_INTERVAL

        if interval <= 0:
            interval = self.config.get(CONF_INTERVAL, DEFAULT_INTERVAL)

        # Stop existing watcher for this entity if running
        if entity_id in self._camera_watchers:
            await self.async_stop_watch_camera(entity_id)

        cancel_event = asyncio.Event()
        task = self.hass.async_create_task(
            self._camera_watch_loop(entity_id, game_hint, client_type, interval, cancel_event)
        )

        self._camera_watchers[entity_id] = {
            "task": task,
            "cancel_event": cancel_event,
            "game_hint": game_hint,
            "client_type": client_type,
            "interval": interval,
        }
        self._gaming_mode = True
        _LOGGER.info(
            "Camera watcher started: %s (game=%s, interval=%ds)",
            entity_id, game_hint or "auto", interval,
        )
        self.async_set_updated_data(self._build_data())

    async def async_stop_watch_camera(self, entity_id: str = "") -> None:
        """Stop camera watcher(s). Empty entity_id stops all."""
        targets = [entity_id] if entity_id else list(self._camera_watchers.keys())

        for eid in targets:
            watcher = self._camera_watchers.pop(eid, None)
            if watcher:
                watcher["cancel_event"].set()
                watcher["task"].cancel()
                _LOGGER.info("Camera watcher stopped: %s", eid)

        if not self._camera_watchers:
            self._gaming_mode = False

        self.async_set_updated_data(self._build_data())

    async def _camera_watch_loop(
        self,
        entity_id: str,
        game_hint: str,
        client_type: str,
        interval: int,
        cancel_event: asyncio.Event,
    ) -> None:
        """Periodically grab snapshots from a HA camera entity."""
        from homeassistant.components.camera import async_get_image

        consecutive_errors = 0
        max_errors = 10

        while not cancel_event.is_set():
            try:
                image = await async_get_image(self.hass, entity_id)
                image_bytes = image.content
                consecutive_errors = 0

                metadata = {
                    "client_type": client_type,
                    "source": entity_id,
                }
                if game_hint:
                    metadata["window_title"] = game_hint

                # Use entity_id as client_id (sanitise dots → underscores)
                client_id = entity_id.replace(".", "_")
                self._client_metadata[client_id] = metadata

                await self._process_image(client_id, image_bytes)

            except asyncio.CancelledError:
                return
            except Exception as err:
                consecutive_errors += 1
                _LOGGER.warning(
                    "Camera watcher %s error (%d/%d): %s",
                    entity_id, consecutive_errors, max_errors, err,
                )
                if consecutive_errors >= max_errors:
                    _LOGGER.error(
                        "Camera watcher %s stopped after %d consecutive errors",
                        entity_id, max_errors,
                    )
                    self._camera_watchers.pop(entity_id, None)
                    if not self._camera_watchers:
                        self._gaming_mode = False
                    self.async_set_updated_data(self._build_data())
                    return

            # Wait for interval or cancellation
            try:
                await asyncio.wait_for(cancel_event.wait(), timeout=interval)
                return  # cancel_event was set
            except asyncio.TimeoutError:
                pass  # interval elapsed, loop again

    # -- Public methods for services -----------------------------------------

    async def async_process_manual_image(
        self,
        image_bytes: bytes,
        game_hint: str = "",
        client_type: str = "pc",
    ) -> str:
        """Process an image manually (from service call)."""
        metadata = {"client_type": client_type}
        if game_hint:
            metadata["window_title"] = game_hint
        return await self.hass.async_add_executor_job(
            self._run_image_processing, image_bytes, "manual", metadata
        )

    async def async_ask(
        self,
        question: str,
        image_bytes: bytes | None = None,
        game_hint: str = "",
        client_type: str = "pc",
    ) -> str:
        """Answer a direct question, optionally with image context."""
        metadata = {"client_type": client_type}
        if game_hint:
            metadata["window_title"] = game_hint
            self._current_game = game_hint

        self._status = "analyzing"
        self.async_set_updated_data(self._build_data())

        try:
            answer = await self._image_processor.ask(
                question=question,
                client_id="ask",
                metadata=metadata,
                image_bytes=image_bytes,
            )
            if answer:
                self._tip = answer
                self._tip_count += 1
                self._recent_tips.append({
                    "tip": answer,
                    "game": self._current_game,
                    "client_id": "ask",
                    "question": question,
                })
                if len(self._recent_tips) > 5:
                    self._recent_tips = self._recent_tips[-5:]
            self._status = "idle"
            self.async_set_updated_data(self._build_data())
            return answer
        except Exception as err:
            _LOGGER.exception("Ask-mode processing failed: %s", err)
            self._status = "error"
            self.async_set_updated_data(self._build_data())
            return ""

    # -- cleanup -------------------------------------------------------------

    async def async_shutdown(self) -> None:
        """Stop all camera watchers and unsubscribe MQTT."""
        await self.async_stop_watch_camera()  # stops all
        self.async_unsubscribe()

    def async_unsubscribe(self) -> None:
        """Unsubscribe from all MQTT topics."""
        for unsub in self._unsubscribe_callbacks:
            unsub()
        self._unsubscribe_callbacks.clear()
        self._mqtt_connected = False

    # -- data helpers --------------------------------------------------------

    def _build_data(self) -> dict:
        return {
            "tip": self._tip,
            "gaming_mode": self._gaming_mode,
            "status": self._status,
            "current_game": self._current_game,
            "client_id": self._current_client_id,
            "tip_count": self._tip_count,
            "recent_tips": self._recent_tips,
            "active_watchers": self.active_camera_watchers,
        }

    async def _async_update_data(self) -> dict:
        """No active polling – all updates come via MQTT push."""
        return self._build_data()
