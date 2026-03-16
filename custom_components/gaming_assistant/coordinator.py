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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    ASSISTANT_MODES,
    CONF_AUTO_ANNOUNCE,
    DEFAULT_SOURCE_TYPE,
    SOURCE_TYPES,
    CONF_AUTO_SUMMARY,
    CONF_CAMERA_ENTITY,
    CONF_DEFAULT_SPOILER,
    CONF_INTERVAL,
    CONF_MODEL,
    CONF_OLLAMA_HOST,
    CONF_TIMEOUT,
    CONF_TTS_ENTITY,
    CONF_TTS_TARGET,
    DEFAULT_ASSISTANT_MODE,
    DEFAULT_AUTO_ANNOUNCE,
    DEFAULT_AUTO_SUMMARY,
    DEFAULT_INTERVAL,
    DEFAULT_SPOILER_LEVEL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    EVENT_NEW_TIP,
    EVENT_SESSION_ENDED,
    MQTT_IMAGE_TOPIC,
    MQTT_META_TOPIC,
    MQTT_MODE_TOPIC,
    MQTT_STATUS_TOPIC,
    MQTT_TIP_TOPIC,
    MQTT_WORKER_REGISTER_TOPIC,
    SESSION_END_DELAY,
)
from .history import HistoryManager
from .image_processor import ImageProcessor
from .prompt_builder import PromptBuilder
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
        self._config_entry_id: str = ""

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

        # Configurable interval & timeout
        self._analysis_interval: int = config.get(CONF_INTERVAL, DEFAULT_INTERVAL)
        self._analysis_timeout: int = config.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)

        # Assistant mode (coach, coplay, opponent, analyst)
        self._assistant_mode: str = DEFAULT_ASSISTANT_MODE

        # Persistent game hint – used by camera watchers when no auto-detection
        self._default_game_hint: str = ""

        # Source type: auto, console, tabletop
        self._source_type: str = DEFAULT_SOURCE_TYPE

        # Camera watchers: entity_id → {task, cancel_event, game_hint, client_type, interval}
        self._camera_watchers: dict[str, dict[str, Any]] = {}

        # Registered workers: client_id → {name, type, platform, last_seen, ...}
        self._registered_workers: dict[str, dict[str, Any]] = {}

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
        # TTS / Announce
        self._tts_entity: str = config.get(CONF_TTS_ENTITY, "")
        self._tts_target: str = config.get(CONF_TTS_TARGET, "")
        self._auto_announce: bool = config.get(CONF_AUTO_ANNOUNCE, DEFAULT_AUTO_ANNOUNCE)

        # Session tracking
        self._session_start: float | None = None
        self._session_game: str = ""
        self._session_tips: list[str] = []
        self._session_end_timer: asyncio.TimerHandle | None = None
        self._auto_summary: bool = config.get(CONF_AUTO_SUMMARY, DEFAULT_AUTO_SUMMARY)
        self._last_summary: str = ""
        self._last_summary_game: str = ""
        self._last_summary_timestamp: str = ""

        # Available Ollama models (fetched on startup, refreshable)
        self._available_models: list[str] = []

        # Resolve language from HA config (e.g. "de", "en", "fr")
        self._language = self._resolve_language(hass)

        self._image_processor = ImageProcessor(
            ollama_host=config.get(CONF_OLLAMA_HOST, "http://localhost:11434"),
            model=config.get(CONF_MODEL, "qwen2.5vl"),
            history_manager=self._history,
            spoiler_manager=self._spoiler,
            prompt_pack_loader=self._pack_loader,
            timeout=self._analysis_timeout,
            language=self._language,
        )

    # -- language resolution --------------------------------------------------

    @staticmethod
    def _resolve_language(hass: HomeAssistant) -> str:
        """Map HA language code to a human-readable language name for the LLM."""
        _LANG_MAP = {
            "de": "German (Deutsch)",
            "en": "English",
            "fr": "French (Français)",
            "es": "Spanish (Español)",
            "it": "Italian (Italiano)",
            "nl": "Dutch (Nederlands)",
            "pt": "Portuguese (Português)",
            "pl": "Polish (Polski)",
            "ru": "Russian (Русский)",
            "ja": "Japanese (日本語)",
            "zh": "Chinese (中文)",
            "ko": "Korean (한국어)",
        }
        lang_code = getattr(hass.config, "language", "en") or "en"
        # HA may use "de" or "de-DE" format; take the base code
        base = lang_code.split("-")[0].lower()
        if base == "en":
            return ""  # English is the default, no explicit instruction needed
        return _LANG_MAP.get(base, base)

    # -- public properties ---------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info so all entities are grouped under one device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._config_entry_id or "gaming_assistant")},
            name="Gaming Assistant",
            manufacturer="Chance-Konstruktion",
            model=self.config.get(CONF_MODEL, "qwen2.5vl"),
            sw_version="0.9.0",
            configuration_url=self.config.get(CONF_OLLAMA_HOST, ""),
        )

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
    def analysis_interval(self) -> int:
        return self._analysis_interval

    def set_analysis_interval(self, value: int) -> None:
        """Set the capture/analysis interval in seconds."""
        self._analysis_interval = max(5, min(120, value))
        _LOGGER.info("Analysis interval set to: %ds", self._analysis_interval)
        self.async_set_updated_data(self._build_data())

    @property
    def analysis_timeout(self) -> int:
        return self._analysis_timeout

    def set_analysis_timeout(self, value: int) -> None:
        """Set the analysis timeout in seconds."""
        self._analysis_timeout = max(10, min(300, value))
        self._image_processor.timeout = self._analysis_timeout
        _LOGGER.info("Analysis timeout set to: %ds", self._analysis_timeout)
        self.async_set_updated_data(self._build_data())

    @property
    def default_spoiler_level(self) -> str:
        return self._spoiler.default_level

    def set_default_spoiler_level(self, level: str) -> None:
        """Set the default spoiler level."""
        from .const import SPOILER_LEVELS
        if level not in SPOILER_LEVELS:
            _LOGGER.warning("Unknown spoiler level '%s'", level)
            return
        self._spoiler.set_level("all", level)
        _LOGGER.info("Default spoiler level set to: %s", level)
        self.async_set_updated_data(self._build_data())

    @property
    def assistant_mode(self) -> str:
        return self._assistant_mode

    def set_assistant_mode(self, mode: str) -> None:
        """Set the assistant mode (coach, coplay, opponent, analyst)."""
        if mode not in ASSISTANT_MODES:
            _LOGGER.warning("Unknown assistant mode '%s', keeping '%s'", mode, self._assistant_mode)
            return
        self._assistant_mode = mode
        _LOGGER.info("Assistant mode set to: %s", mode)
        self.async_set_updated_data(self._build_data())

    @property
    def default_game_hint(self) -> str:
        return self._default_game_hint

    def set_default_game_hint(self, hint: str) -> None:
        """Set the persistent game hint used by all camera watchers."""
        self._default_game_hint = hint
        if hint:
            self._current_game = hint
        _LOGGER.info("Default game hint set to: %s", hint or "(auto)")
        self.async_set_updated_data(self._build_data())

    @property
    def source_type(self) -> str:
        return self._source_type

    def set_source_type(self, source_type: str) -> None:
        """Set the source type (auto, console, tabletop)."""
        if source_type not in SOURCE_TYPES:
            _LOGGER.warning("Unknown source type '%s', keeping '%s'", source_type, self._source_type)
            return
        self._source_type = source_type
        _LOGGER.info("Source type set to: %s", source_type)
        self.async_set_updated_data(self._build_data())

    @property
    def available_game_packs(self) -> list[dict[str, str]]:
        """Return list of available prompt packs for UI dropdown."""
        packs = self._pack_loader.load_all()
        return [
            {"id": pid, "name": p.get("name", pid)}
            for pid, p in sorted(packs.items(), key=lambda x: x[1].get("name", x[0]))
        ]

    @property
    def registered_workers(self) -> dict[str, dict[str, Any]]:
        return self._registered_workers

    def _register_worker(self, client_id: str, info: dict[str, Any] | None = None) -> None:
        """Register or update a worker. Called automatically on MQTT activity."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if client_id in self._registered_workers:
            self._registered_workers[client_id]["last_seen"] = now
            if info:
                self._registered_workers[client_id].update(info)
        else:
            worker_info = {
                "name": info.get("name", client_id) if info else client_id,
                "type": info.get("type", "unknown") if info else "unknown",
                "platform": info.get("platform", "") if info else "",
                "version": info.get("version", "") if info else "",
                "first_seen": now,
                "last_seen": now,
            }
            if info:
                worker_info.update({k: v for k, v in info.items() if k not in worker_info})
            self._registered_workers[client_id] = worker_info
            _LOGGER.info("New worker registered: %s (%s)", client_id, worker_info.get("type"))
        self.async_set_updated_data(self._build_data())

    # -- TTS / Announce properties ---------------------------------------------

    @property
    def tts_entity(self) -> str:
        return self._tts_entity

    @property
    def tts_target(self) -> str:
        return self._tts_target

    @property
    def auto_announce(self) -> bool:
        return self._auto_announce

    def set_auto_announce(self, enabled: bool) -> None:
        """Toggle auto-announce on/off."""
        self._auto_announce = enabled
        _LOGGER.info("Auto-announce set to: %s", enabled)
        self.async_set_updated_data(self._build_data())

    async def async_announce(
        self,
        message: str = "",
        tts_entity: str = "",
        media_player_entity_id: str = "",
    ) -> None:
        """Speak a message (or the current tip) via TTS.

        Falls back to configured defaults if no explicit entity is given.
        """
        text = message or self._tip
        if not text or text == "Waiting for tips...":
            _LOGGER.warning("Nothing to announce – no tip available yet")
            return

        tts_eid = tts_entity or self._tts_entity
        target = media_player_entity_id or self._tts_target

        if not tts_eid:
            _LOGGER.error(
                "Cannot announce: no TTS entity configured. "
                "Set one in Settings → Integrations → Gaming Assistant → Configure, "
                "or pass tts_entity to the announce service call."
            )
            return

        if not target:
            _LOGGER.error(
                "Cannot announce: no media_player target configured. "
                "Set one in Settings → Integrations → Gaming Assistant → Configure, "
                "or pass media_player_entity_id to the announce service call."
            )
            return

        service_data = {
            "entity_id": tts_eid,
            "media_player_entity_id": target,
            "message": text,
        }

        try:
            await self.hass.services.async_call("tts", "speak", service_data)
            _LOGGER.info("Announced tip via %s → %s", tts_eid, target)
        except Exception as err:
            _LOGGER.error("TTS announce failed: %s", err)

    # -- Session tracking / summary ------------------------------------------

    @property
    def auto_summary(self) -> bool:
        return self._auto_summary

    def set_auto_summary(self, enabled: bool) -> None:
        """Toggle automatic session summaries on/off."""
        self._auto_summary = enabled
        _LOGGER.info("Auto-summary set to: %s", enabled)
        self.async_set_updated_data(self._build_data())

    @property
    def last_summary(self) -> str:
        return self._last_summary

    @property
    def last_summary_game(self) -> str:
        return self._last_summary_game

    @property
    def last_summary_timestamp(self) -> str:
        return self._last_summary_timestamp

    def _session_track_tip(self, tip: str, game: str) -> None:
        """Track a tip for the current session."""
        now = time.monotonic()

        # Start a new session if none is active or game changed
        if self._session_start is None or (game and game != self._session_game):
            self._session_start = now
            self._session_game = game
            self._session_tips = []
            _LOGGER.debug("New session started for game: %s", game or "unknown")

        self._session_tips.append(tip)

        # Reset the session-end timer
        if self._session_end_timer is not None:
            self._session_end_timer.cancel()
        loop = self.hass.loop
        self._session_end_timer = loop.call_later(
            SESSION_END_DELAY, lambda: self.hass.async_create_task(self._end_session())
        )

    async def _end_session(self) -> None:
        """End the current session and optionally generate a summary."""
        if not self._session_tips or not self._session_start:
            self._session_start = None
            self._session_end_timer = None
            return

        game = self._session_game or "Unknown"
        tip_count = len(self._session_tips)
        tips = list(self._session_tips)

        _LOGGER.info(
            "Session ended for %s (%d tips in session)", game, tip_count
        )

        summary = ""
        if self._auto_summary and tip_count >= 3:
            summary = await self.async_summarize_session(game, tips)

        # Fire session-ended event
        self.hass.bus.async_fire(
            EVENT_SESSION_ENDED,
            {
                "game": game,
                "tip_count": tip_count,
                "summary": summary,
            },
        )

        # Reset session state
        self._session_start = None
        self._session_game = ""
        self._session_tips = []
        self._session_end_timer = None
        self.async_set_updated_data(self._build_data())

    async def async_summarize_session(
        self, game: str = "", tips: list[str] | None = None
    ) -> str:
        """Generate a summary of the current or provided session tips.

        If *tips* is not provided, uses the tips from the current session
        or falls back to recent history.
        """
        game = game or self._session_game or self._current_game or "Unknown"

        if tips is None:
            if self._session_tips:
                tips = list(self._session_tips)
            else:
                # Fall back to recent history
                entries = await self._history.get_recent(game, 20)
                tips = [e["tip"] for e in entries if "tip" in e]

        if not tips:
            return "No tips found for this game."

        compact = PromptBuilder.is_small_model(
            self.config.get(CONF_MODEL, "qwen2.5vl")
        )
        prompt = PromptBuilder.build_summary(
            game=game,
            tips=tips,
            language=self._language,
            compact=compact,
        )

        summary = await self._image_processor._call_ollama_text(prompt)

        if summary:
            self._last_summary = summary
            self._last_summary_game = game
            self._last_summary_timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            _LOGGER.info("Session summary generated for %s", game)
            self.async_set_updated_data(self._build_data())

        return summary or "Could not generate summary."

    def _fire_new_tip_event(self, tip: str, game: str, client_id: str) -> None:
        """Fire an event so automations can react to new tips."""
        self.hass.bus.async_fire(
            EVENT_NEW_TIP,
            {
                "tip": tip,
                "game": game,
                "client_id": client_id,
                "assistant_mode": self._assistant_mode,
            },
        )

    @property
    def configured_camera(self) -> str:
        """Return the camera entity configured in the config flow."""
        return self.config.get(CONF_CAMERA_ENTITY, "")

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

    async def async_fetch_available_models(self) -> list[str]:
        """Fetch available models from Ollama and cache the result."""
        import requests as req

        host = self.config.get(CONF_OLLAMA_HOST, "http://localhost:11434").rstrip("/")

        def _fetch():
            try:
                resp = req.get(f"{host}/api/tags", timeout=5)
                resp.raise_for_status()
                data = resp.json()
                return sorted(m["name"] for m in data.get("models", []))
            except Exception as err:
                _LOGGER.warning("Could not fetch Ollama models from %s: %s", host, err)
                return []

        models = await self.hass.async_add_executor_job(_fetch)
        self._available_models = models
        self.async_set_updated_data(self._build_data())
        return models

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
            self._register_worker(client_id)
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
                self._register_worker(client_id, metadata)
                _LOGGER.debug("Metadata from %s: %s", client_id, metadata)
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                _LOGGER.warning("Invalid metadata from %s: %s", client_id, err)

        @callback
        def worker_register_received(msg) -> None:
            """Handle explicit worker registration."""
            client_id = msg.topic.split("/")[1]
            try:
                payload = msg.payload
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
                info = json.loads(payload)
                self._register_worker(client_id, info)
                _LOGGER.info("Worker registered via MQTT: %s", client_id)
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                _LOGGER.warning("Invalid register payload from %s: %s", client_id, err)

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
        unsub_register = await mqtt.async_subscribe(
            self.hass, MQTT_WORKER_REGISTER_TOPIC, worker_register_received, 0
        )

        self._unsubscribe_callbacks = [
            unsub_tip, unsub_mode, unsub_status, unsub_image, unsub_meta,
            unsub_register,
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
            metadata["assistant_mode"] = self._assistant_mode

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

                # Track tip for session summary
                self._session_track_tip(tip, self._current_game)

                # Fire event for automations
                self._fire_new_tip_event(tip, self._current_game, client_id)

                # Auto-announce via TTS if enabled
                if self._auto_announce and self._tts_entity:
                    self.hass.async_create_task(self.async_announce(tip))
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
        if interval <= 0:
            interval = self._analysis_interval

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

                # Use dynamic game hint: explicit param > persistent default
                effective_hint = game_hint or self._default_game_hint

                # Resolve client_type based on source_type setting:
                # - "console": always treat as digital game on screen
                # - "tabletop": always treat as physical game on table
                # - "auto": use prompt pack match to decide
                if self._source_type == "auto":
                    effective_type = client_type
                    if effective_type == "console" and effective_hint:
                        pack = self._pack_loader.find_by_keyword(effective_hint)
                        if not pack:
                            effective_type = "tabletop"
                else:
                    effective_type = self._source_type

                metadata = {
                    "client_type": effective_type,
                    "source": entity_id,
                }
                if effective_hint:
                    metadata["window_title"] = effective_hint

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

            # Wait for interval or cancellation (read current interval each time
            # so changes via the number entity take effect immediately)
            current_interval = self._analysis_interval
            try:
                await asyncio.wait_for(cancel_event.wait(), timeout=current_interval)
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

                # Track tip for session summary
                self._session_track_tip(answer, self._current_game)

                # Fire event for automations
                self._fire_new_tip_event(answer, self._current_game, "ask")

                # Auto-announce via TTS if enabled
                if self._auto_announce and self._tts_entity:
                    self.hass.async_create_task(self.async_announce(answer))

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
        """Stop all camera watchers, cancel timers, and unsubscribe MQTT."""
        if self._session_end_timer is not None:
            self._session_end_timer.cancel()
            self._session_end_timer = None
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
            "assistant_mode": self._assistant_mode,
            "analysis_interval": self._analysis_interval,
            "analysis_timeout": self._analysis_timeout,
            "spoiler_level": self._spoiler.default_level,
            "registered_workers": self._registered_workers,
            "default_game_hint": self._default_game_hint,
            "source_type": self._source_type,
            "available_models": self._available_models,
        }

    async def _async_update_data(self) -> dict:
        """No active polling – all updates come via MQTT push."""
        return self._build_data()
