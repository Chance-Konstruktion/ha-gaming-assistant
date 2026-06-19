"""Coordinator for Gaming Assistant integration."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from datetime import timedelta

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    ASSISTANT_MODES,
    CONF_AUTO_ANNOUNCE,
    CONF_LLM_ALLOW_IMAGES,
    CONF_LLM_API_KEY,
    CONF_LLM_BACKEND,
    DEFAULT_LLM_BACKEND,
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
    AGENT_VALID_BUTTONS,
    AGENT_ACTION_MIN_INTERVAL,
    AGENT_MAX_CONSECUTIVE_FAILURES,
    DEFAULT_AGENT_MODE,
    DEFAULT_ASSISTANT_MODE,
    DEFAULT_AUTO_ANNOUNCE,
    DEFAULT_AUTO_SUMMARY,
    DEFAULT_INTERVAL,
    DEFAULT_SPOILER_LEVEL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    EVENT_AGENT_ACTION,
    EVENT_NEW_TIP,
    MQTT_ACTION_TOPIC,
    MQTT_YOLO_COMMAND_TOPIC,
)
from .agent_governor import AgentActionGovernor
from .game_state import GameStateManager
from .history import HistoryManager
from .image_processor import ImageProcessor
from .llm_backend import LLMBackend, create_backend
from .camera_watcher import CameraWatcher
from .client_registry import ClientRegistry
from .mqtt_router import MqttRouter
from .perception import PerceptionTier
from .prompt_packs import PromptPackLoader
from .session_tracker import SessionTracker
from .spoiler import SpoilerManager
from .strategy import StrategyTier

_LOGGER = logging.getLogger(__name__)


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

        # v0.4 Thin Client components
        self._current_game: str = ""
        self._current_client_id: str = ""
        self._recent_tips: list[dict] = []
        self._tip_count: int = 0
        self._client_metadata: dict[str, dict] = {}
        self._process_lock = asyncio.Lock()
        self._image_queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue(maxsize=3)
        self._image_worker_task: asyncio.Task | None = None
        self._last_image_bytes: bytes | None = None
        self._last_image_client_id: str = ""
        self._last_image_timestamp: str = ""

        # Configurable interval & timeout
        self._analysis_interval: int = config.get(CONF_INTERVAL, DEFAULT_INTERVAL)
        self._analysis_timeout: int = config.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)

        # Assistant mode (coach, coplay, opponent, analyst)
        self._assistant_mode: str = DEFAULT_ASSISTANT_MODE

        # Agent Mode / Player 2 — opt-in, runtime-only (resets to OFF on restart).
        self._agent_mode: bool = DEFAULT_AGENT_MODE
        self._agent_allowed_buttons: list[str] = []
        # Safety governor: rate limit + failure auto-disable + audit counters.
        self._agent_governor = AgentActionGovernor(
            AGENT_ACTION_MIN_INTERVAL, AGENT_MAX_CONSECUTIVE_FAILURES
        )

        # Persistent game hint – used by camera watchers when no auto-detection
        self._default_game_hint: str = ""

        # Source type: auto, console, tabletop
        self._source_type: str = DEFAULT_SOURCE_TYPE

        # Camera watchers: continuous capture from HA camera entities.
        self._camera_watcher = CameraWatcher(self)

        # Worker/client registry + per-client inactivity timers.
        self._client_registry = ClientRegistry(self)

        # MQTT subscription routing + connection state + YOLO worker status.
        self._mqtt_router = MqttRouter(self)

        # Tier 1 — cheap per-frame perception (scene change, motion) that
        # feeds measured signals into Tier 2 instead of scraping them back
        # out of the LLM's prose afterwards.
        self._perception = PerceptionTier(self)

        # Tier 3 — slow session-level strategy that distils a focus from
        # game-state trends and feeds it back down into the Tier 2 prompt.
        self._strategy = StrategyTier(self)

        # Runtime metrics
        self._latency: float = 0.0
        self._error_count: int = 0
        self._frames_processed: int = 0
        # Tier 2 escalation: monotonic timestamp of the last LLM analysis
        # attempt (None = never) + count of frames handled by Tier 1 only.
        self._last_tier2_ts: float | None = None
        self._frames_skipped: int = 0
        # Tier 1 perception readout (last measured frame).
        self._last_scene_change: float = 0.0
        self._last_frame_motion: str = ""
        self._last_analysis: str = ""
        self._last_error_message: str = ""
        self._last_error_type: str = ""
        self._last_error_timestamp: str = ""

        # Initialize managers
        self._history = HistoryManager(hass.config.config_dir)
        self._spoiler = SpoilerManager(
            f"{hass.config.config_dir}/gaming_assistant/spoiler_profiles.json"
        )
        default_spoiler = config.get(CONF_DEFAULT_SPOILER, DEFAULT_SPOILER_LEVEL)
        self._spoiler.initialize(default_spoiler)
        self._spoiler.load()
        self._packs_cache_dir = Path(
            hass.config.config_dir
        ) / "gaming_assistant" / "prompt_packs"
        self._pack_loader = PromptPackLoader(cache_dir=self._packs_cache_dir)
        self._pack_loader.load_all()
        self._game_state = GameStateManager(hass.config.config_dir)
        # Games whose persisted state has already been loaded from disk
        # (lazy load-once tracking so we don't hit the filesystem per frame).
        self._loaded_state_games: set[str] = set()
        # TTS / Announce
        self._tts_entity: str = config.get(CONF_TTS_ENTITY, "")
        self._tts_target: str = config.get(CONF_TTS_TARGET, "")
        self._auto_announce: bool = config.get(CONF_AUTO_ANNOUNCE, DEFAULT_AUTO_ANNOUNCE)

        # Session tracking + summary (debounced end, recap generation).
        self._session_tracker = SessionTracker(
            self, config.get(CONF_AUTO_SUMMARY, DEFAULT_AUTO_SUMMARY)
        )

        # Daily history cleanup (managed via async_track_time_interval)
        self._cleanup_unsub: callback | None = None

        # Available Ollama models (fetched on startup, refreshable)
        self._available_models: list[str] = []

        # Resolve language from HA config (e.g. "de", "en", "fr")
        self._language = self._resolve_language(hass)

        # Create LLM backend. Remember the configured provider id so a later
        # model switch reconstructs the SAME provider (preset host, rate limit,
        # image policy) instead of collapsing to the generic backend class.
        self._provider = config.get(CONF_LLM_BACKEND, DEFAULT_LLM_BACKEND)
        self._llm_backend = create_backend(
            provider=self._provider,
            host=config.get(CONF_OLLAMA_HOST, "http://localhost:11434"),
            model=config.get(CONF_MODEL, "qwen2.5vl"),
            timeout=self._analysis_timeout,
            api_key=config.get(CONF_LLM_API_KEY, ""),
            allow_images=config.get(CONF_LLM_ALLOW_IMAGES, True),
        )

        self._image_processor = ImageProcessor(
            ollama_host=config.get(CONF_OLLAMA_HOST, "http://localhost:11434"),
            model=config.get(CONF_MODEL, "qwen2.5vl"),
            history_manager=self._history,
            spoiler_manager=self._spoiler,
            prompt_pack_loader=self._pack_loader,
            timeout=self._analysis_timeout,
            language=self._language,
            game_state_manager=self._game_state,
            llm_backend=self._llm_backend,
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
            sw_version="260618",
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
        return self._mqtt_router.connected

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
    def game_state_manager(self) -> GameStateManager:
        return self._game_state

    @property
    def yolo_workers(self) -> dict[str, dict[str, Any]]:
        """Return status of connected YOLO workers."""
        return self._mqtt_router.yolo_workers

    async def async_send_yolo_command(self, command: str, **kwargs: Any) -> None:
        """Send a command to YOLO workers via MQTT."""
        payload = {"command": command, **kwargs}
        try:
            await mqtt.async_publish(
                self.hass, MQTT_YOLO_COMMAND_TOPIC,
                json.dumps(payload), qos=1,
            )
            _LOGGER.info("Sent YOLO command: %s", command)
        except HomeAssistantError as err:
            _LOGGER.warning("Failed to send YOLO command: %s", err)

    async def async_publish_action(self, client_id: str, action: dict) -> None:
        """Publish a validated controller action to the agent executor."""
        topic = MQTT_ACTION_TOPIC.format(client_id=client_id)
        try:
            await mqtt.async_publish(
                self.hass, topic, json.dumps(action), qos=1,
            )
            _LOGGER.info("Published agent action to %s: %s", topic, action)
        except HomeAssistantError as err:
            _LOGGER.warning("Failed to publish agent action: %s", err)

    @property
    def llm_backend(self) -> LLMBackend:
        return self._llm_backend

    @property
    def llm_backend_type(self) -> str:
        return self._llm_backend.backend_type

    @property
    def active_model(self) -> str:
        """Currently active model used for inference."""
        return self._llm_backend.model

    async def async_start_assistant(self) -> None:
        """Mark assistant as active for UI and automations."""
        self._gaming_mode = True
        if self._status == "idle":
            self._status = "ready"
        self.async_set_updated_data(self._build_data())

    async def async_stop_assistant(self) -> None:
        """Stop runtime processing and set integration to inactive."""
        self._gaming_mode = False
        if self._status != "error":
            self._status = "idle"
        self._client_registry.cancel_timers()
        while not self._image_queue.empty():
            try:
                self._image_queue.get_nowait()
                self._image_queue.task_done()
            except asyncio.QueueEmpty:
                break
        self.async_set_updated_data(self._build_data())

    async def async_clear_history(self, game: str | None = None) -> None:
        """Clear persisted history and reset dashboard runtime history."""
        await self._history.clear(game)
        if not game or game == self._current_game:
            self._recent_tips = []
            self._tip_count = 0
            self._tip = "Waiting for tips..."
        self.async_set_updated_data(self._build_data())

    async def async_set_model(self, model: str) -> None:
        """Switch active model for both backend and image processor.

        Reuses the configured provider id (e.g. ``deepseek``/``gemini``) so the
        provider's preset – host, rate limit, and image policy – is preserved.
        Using ``backend_type`` here would map every OpenAI-compatible provider
        back to the generic ``openai`` preset and silently flip ``allow_images``.
        """
        if not model:
            return
        self._llm_backend = create_backend(
            provider=self._provider,
            host=self.config.get(CONF_OLLAMA_HOST, "http://localhost:11434"),
            model=model,
            timeout=self._analysis_timeout,
            api_key=self.config.get(CONF_LLM_API_KEY, ""),
            allow_images=self.config.get(CONF_LLM_ALLOW_IMAGES, True),
        )
        self._image_processor.backend = self._llm_backend
        self._image_processor._model = model
        self.config[CONF_MODEL] = model
        self.async_set_updated_data(self._build_data())

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
        return self._client_registry.registered_workers

    def _register_worker(
        self, client_id: str, info: dict[str, Any] | None = None
    ) -> None:
        """Register or update a worker (delegated to ClientRegistry)."""
        self._client_registry.register_worker(client_id, info)

    def _touch_client(
        self, client_id: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Update per-client runtime state (delegated to ClientRegistry)."""
        self._client_registry.touch_client(client_id, metadata)

    def _ensure_image_worker(self) -> None:
        """Ensure the image queue worker is running."""
        if self._image_worker_task and not self._image_worker_task.done():
            return
        self._image_worker_task = self.hass.async_create_task(self._image_worker_loop())

    async def _enqueue_image(self, client_id: str, image_bytes: bytes) -> None:
        """Enqueue image with bounded backpressure (drop oldest when full)."""
        self._ensure_image_worker()
        if self._image_queue.full():
            try:
                dropped_client, _ = self._image_queue.get_nowait()
                self._image_queue.task_done()
                _LOGGER.debug("Image queue full. Dropped oldest frame from %s", dropped_client)
            except asyncio.QueueEmpty:
                pass
        await self._image_queue.put((client_id, image_bytes))

    async def _image_worker_loop(self) -> None:
        """Sequentially process images from queue."""
        while True:
            client_id, image_bytes = await self._image_queue.get()
            _LOGGER.debug(
                "Image worker: processing %s (queue=%d/%d)",
                client_id, self._image_queue.qsize(), self._image_queue.maxsize,
            )
            try:
                await self._process_image(client_id, image_bytes)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.debug("Image worker: item failed, continuing", exc_info=True)
            finally:
                self._image_queue.task_done()

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

    @property
    def agent_mode(self) -> bool:
        return self._agent_mode

    @property
    def agent_allowed_buttons(self) -> list[str]:
        return list(self._agent_allowed_buttons)

    @property
    def agent_actions_published(self) -> int:
        return self._agent_governor.published

    @property
    def agent_actions_failed(self) -> int:
        return self._agent_governor.failed

    @property
    def agent_last_action(self) -> dict | None:
        return self._agent_governor.last_action

    @property
    def agent_last_action_status(self) -> str:
        return self._agent_governor.last_status

    @property
    def agent_last_action_timestamp(self) -> str:
        return self._agent_governor.last_timestamp

    def set_agent_mode(
        self, enabled: bool, allowed_buttons: list[str] | None = None
    ) -> None:
        """Enable/disable Agent Mode (opt-in autonomous controller actions).

        When enabled, each analyzed frame additionally produces a validated
        controller action published to ``gaming_assistant/{client_id}/action``.
        Runtime-only by design: it always resets to OFF on restart.
        """
        if enabled and not self._agent_mode:
            # Fresh enable: clear any stale failure streak from a prior run.
            self._agent_governor.reset_failures()
        self._agent_mode = bool(enabled)
        if allowed_buttons is not None:
            valid = {b.upper() for b in AGENT_VALID_BUTTONS}
            self._agent_allowed_buttons = [
                b.upper() for b in allowed_buttons if b.upper() in valid
            ]
        _LOGGER.info(
            "Agent mode set to: %s (allowed buttons: %s)",
            self._agent_mode,
            ", ".join(self._agent_allowed_buttons) or "all",
        )
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
        except HomeAssistantError as err:
            _LOGGER.error("TTS announce failed: %s", err)

    # -- Session tracking / summary (delegated to SessionTracker) ------------

    @property
    def session_tracker(self) -> SessionTracker:
        return self._session_tracker

    @property
    def auto_summary(self) -> bool:
        return self._session_tracker.auto_summary

    def set_auto_summary(self, enabled: bool) -> None:
        """Toggle automatic session summaries on/off."""
        self._session_tracker.set_auto_summary(enabled)

    @property
    def last_summary(self) -> str:
        return self._session_tracker.last_summary

    @property
    def last_summary_game(self) -> str:
        return self._session_tracker.last_summary_game

    @property
    def last_summary_timestamp(self) -> str:
        return self._session_tracker.last_summary_timestamp

    async def async_summarize_session(
        self, game: str = "", tips: list[str] | None = None
    ) -> str:
        """Generate a summary of the current or provided session tips."""
        return await self._session_tracker.async_summarize(game, tips)

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
    def frames_skipped(self) -> int:
        """Frames handled by Tier 1 only (no LLM call)."""
        return self._frames_skipped

    @property
    def scene_change(self) -> float:
        """Tier 1 scene-change magnitude of the last measured frame (0..1)."""
        return self._last_scene_change

    @property
    def frame_motion(self) -> str:
        """Tier 1 motion class of the last measured frame."""
        return self._last_frame_motion

    @property
    def strategy_note(self) -> str:
        """Tier 3 strategic focus for the current game (empty if none)."""
        return self._strategy.note(self._current_game)

    @property
    def last_analysis(self) -> str:
        return self._last_analysis

    @property
    def last_error_message(self) -> str:
        return self._last_error_message

    @property
    def last_error_type(self) -> str:
        return self._last_error_type

    @property
    def last_error_timestamp(self) -> str:
        return self._last_error_timestamp

    def _record_error(self, err: BaseException) -> None:
        """Record an error for the diagnostics sensors."""
        self._error_count += 1
        self._last_error_message = str(err) or err.__class__.__name__
        self._last_error_type = err.__class__.__name__
        self._last_error_timestamp = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime()
        )

    @property
    def last_image_bytes(self) -> bytes | None:
        return self._last_image_bytes

    @property
    def last_image_client_id(self) -> str:
        return self._last_image_client_id

    @property
    def last_image_timestamp(self) -> str:
        return self._last_image_timestamp

    def _record_last_image(self, client_id: str, image_bytes: bytes) -> None:
        """Remember the most recent frame for the image entity / diagnostics."""
        self._last_image_bytes = image_bytes
        self._last_image_client_id = client_id
        self._last_image_timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

    # -- MQTT setup with retry -----------------------------------------------

    async def async_fetch_available_models(self) -> list[str]:
        """Fetch available models from the current LLM backend."""
        models = await self._llm_backend.list_models()
        self._available_models = models
        self.async_set_updated_data(self._build_data())
        return models

    async def async_setup_mqtt(self) -> None:
        """Subscribe to MQTT topics with retry (delegated to MqttRouter)."""
        await self._mqtt_router.async_setup()

    async def _subscribe_topics(self) -> None:
        """Subscribe to all Gaming Assistant MQTT topics (delegated)."""
        await self._mqtt_router.subscribe_topics()

    def _handle_yolo_detections(
        self, client_id: str, data: dict[str, Any]
    ) -> None:
        """Feed YOLO detections into the game state (delegated to MqttRouter)."""
        self._mqtt_router.handle_yolo_detections(client_id, data)

    # -- Game-state persistence ----------------------------------------------

    async def _ensure_state_loaded(self, game: str) -> None:
        """Load a game's persisted state from disk once, off the event loop."""
        if not game or game in self._loaded_state_games:
            return
        self._loaded_state_games.add(game)
        try:
            await self.hass.async_add_executor_job(self._game_state.load, game)
        except Exception as err:  # noqa: BLE001 - persistence must never break analysis
            _LOGGER.debug("Could not load persisted state for %s: %s", game, err)

    async def _persist_game_state(self, game: str) -> None:
        """Persist a game's state snapshots to disk, off the event loop."""
        if not game:
            return
        try:
            await self.hass.async_add_executor_job(self._game_state.save, game)
        except Exception as err:  # noqa: BLE001 - persistence must never break shutdown
            _LOGGER.debug("Could not persist state for %s: %s", game, err)

    # -- Image processing pipeline -------------------------------------------

    async def _process_image(self, client_id: str, image_bytes: bytes) -> None:
        """Run the image processing pipeline for a received image."""
        async with self._process_lock:
            self._current_client_id = client_id
            self._client_registry.set_active(client_id)
            self._gaming_mode = True
            self._touch_client(client_id, self._client_metadata.get(client_id, {}))

            metadata = self._client_metadata.get(client_id, {})
            metadata["assistant_mode"] = self._assistant_mode

            game = metadata.get("window_title", "")
            if game:
                self._current_game = game
                await self._ensure_state_loaded(game)

            # Tier 1: cheaply measure the frame (scene change, motion).
            perception = await self._perception.observe(
                client_id, image_bytes, metadata
            )
            self._last_scene_change = perception.scene_change
            self._last_frame_motion = perception.measured.get("frame_motion", "")

            # Escalation gate: only spend a Tier 2 (LLM) call on a significant
            # change, or when the heartbeat has elapsed. Otherwise record the
            # measured signals and skip the expensive analysis entirely.
            now = time.monotonic()
            idle = (
                float("inf")
                if self._last_tier2_ts is None
                else now - self._last_tier2_ts
            )
            if not self._perception.should_escalate(perception, idle):
                self._frames_skipped += 1
                if game and perception.measured:
                    self._game_state.update(
                        game, perception.measured,
                        source=f"perception:{client_id}",
                    )
                self._status = "idle"
                _LOGGER.debug(
                    "Tier 2 skipped for %s (scene_change=%.3f, idle=%.0fs)",
                    client_id, perception.scene_change, idle,
                )
                self.async_set_updated_data(self._build_data())
                return

            # Tier 2 escalation — run the LLM analysis.
            self._last_tier2_ts = now
            self._status = "analyzing"
            self.async_set_updated_data(self._build_data())

            try:
                start = time.monotonic()
                # Tier 3 feedback: inject the current strategic focus so the
                # tactical tip reasons under the session's higher-level frame.
                strategy_note = self._strategy.note(game)
                tip = await asyncio.wait_for(
                    self._image_processor.process(
                        image_bytes, client_id, metadata,
                        measured=perception.measured,
                        strategy_note=strategy_note,
                    ),
                    timeout=self._analysis_timeout + 5,
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
                    self._session_tracker.track_tip(tip, self._current_game)

                    # Tier 3: refresh the session-level strategic focus
                    # (game state is already updated for this frame). When a
                    # refresh is due, upgrade the deterministic baseline with
                    # an LLM reflection in the background so it never adds
                    # latency to the tip path.
                    if self._strategy.record_tip(self._current_game, tip):
                        self.hass.async_create_task(
                            self._strategy.async_reflect(self._current_game)
                        )

                    # Fire event for automations
                    self._fire_new_tip_event(tip, self._current_game, client_id)

                    # Auto-announce via TTS if enabled
                    if self._auto_announce and self._tts_entity:
                        self.hass.async_create_task(self.async_announce(tip))

                    # Agent Mode: also produce + publish a controller action.
                    if self._agent_mode:
                        await self._maybe_publish_agent_action(
                            client_id, image_bytes, self._current_game
                        )
                else:
                    self._frames_processed += 1
                    self._status = "idle"

            except (TimeoutError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Image processing timed out after %ds for client %s",
                    self._analysis_timeout + 5, client_id
                )
                self._record_error(
                    err
                    if str(err)
                    else TimeoutError(
                        f"timeout after {self._analysis_timeout + 5}s"
                    )
                )
                self._status = "error"
            except (OSError, json.JSONDecodeError, ValueError) as err:
                _LOGGER.error("Image processing failed: %s", err)
                self._record_error(err)
                self._status = "error"
            finally:
                self.async_set_updated_data(self._build_data())

    async def _maybe_publish_agent_action(
        self, client_id: str, image_bytes: bytes, game: str
    ) -> None:
        """Generate one controller action from the frame and publish it.

        Safety-governed: actions are rate limited, repeated failures
        auto-disable Agent Mode (dead-man switch), and every decision is
        recorded for audit. Fully isolated: any failure here must never
        disrupt the tip pipeline.
        """
        now = time.monotonic()
        if self._agent_governor.rate_limited(now):
            _LOGGER.debug(
                "Agent action rate-limited (<%.1fs), skipping",
                AGENT_ACTION_MIN_INTERVAL,
            )
            return

        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            action = await asyncio.wait_for(
                self._image_processor.generate_action(
                    image_bytes,
                    game,
                    allowed_buttons=self._agent_allowed_buttons or None,
                ),
                timeout=self._analysis_timeout + 5,
            )
        except Exception as err:  # noqa: BLE001 - never break analysis on action errors
            _LOGGER.warning("Agent action generation failed: %s", err)
            if self._agent_governor.record_error(ts):
                _LOGGER.error(
                    "Agent Mode auto-disabled after %d consecutive failures",
                    self._agent_governor.max_consecutive_failures,
                )
                self.set_agent_mode(False)
                self._fire_agent_action_event(client_id, game, "auto_disabled", None)
            else:
                self._fire_agent_action_event(client_id, game, "error", None)
            self.async_set_updated_data(self._build_data())
            return

        if not action:
            self._agent_governor.record_no_op(ts)
            self.async_set_updated_data(self._build_data())
            return

        await self.async_publish_action(client_id, action)
        self._agent_governor.record_published(action, now, ts)
        self._fire_agent_action_event(client_id, game, "published", action)
        self.async_set_updated_data(self._build_data())

    def _fire_agent_action_event(
        self, client_id: str, game: str, status: str, action: dict | None
    ) -> None:
        """Fire an event for each Agent Mode decision (audit / automations)."""
        self.hass.bus.async_fire(
            EVENT_AGENT_ACTION,
            {
                "client_id": client_id,
                "game": game,
                "status": status,
                "action": action,
                "published": self._agent_governor.published,
                "failed": self._agent_governor.failed,
            },
        )

    # -- Camera watcher (delegated to CameraWatcher) -------------------------

    @property
    def active_camera_watchers(self) -> dict[str, dict]:
        """Return info about all active camera watchers."""
        return self._camera_watcher.active_camera_watchers

    async def async_watch_camera(
        self,
        entity_id: str,
        game_hint: str = "",
        client_type: str = "console",
        interval: int = 0,
    ) -> None:
        """Start continuous capture from a HA camera entity."""
        await self._camera_watcher.async_watch(
            entity_id, game_hint, client_type, interval
        )

    async def async_stop_watch_camera(self, entity_id: str = "") -> None:
        """Stop camera watcher(s). Empty entity_id stops all."""
        await self._camera_watcher.async_stop(entity_id)

    # -- Public methods for services -----------------------------------------

    async def async_process_manual_image(
        self,
        image_bytes: bytes,
        game_hint: str = "",
        client_type: str = "pc",
    ) -> str:
        """Process an image manually (from service call)."""
        metadata: dict[str, str] = {"client_type": client_type}
        if game_hint:
            metadata["window_title"] = game_hint
        return await self._image_processor.process(image_bytes, "manual", metadata)

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
                self._session_tracker.track_tip(answer, self._current_game)

                # Fire event for automations
                self._fire_new_tip_event(answer, self._current_game, "ask")

                # Auto-announce via TTS if enabled
                if self._auto_announce and self._tts_entity:
                    self.hass.async_create_task(self.async_announce(answer))

            self._status = "idle"
            self.async_set_updated_data(self._build_data())
            return answer
        except (asyncio.TimeoutError, TimeoutError) as err:
            _LOGGER.warning("Ask-mode timed out: %s", err)
            self._status = "error"
            self.async_set_updated_data(self._build_data())
            return ""
        except (OSError, json.JSONDecodeError, ValueError) as err:
            _LOGGER.error("Ask-mode processing failed: %s", err)
            self._status = "error"
            self.async_set_updated_data(self._build_data())
            return ""

    # -- daily history cleanup -----------------------------------------------

    def start_cleanup_task(self) -> None:
        """Register the daily history cleanup via async_track_time_interval."""
        if self._cleanup_unsub is not None:
            return

        async def _run_cleanup(_now: Any = None) -> None:
            try:
                removed = await self._history.cleanup()
                if removed:
                    _LOGGER.info(
                        "Daily history cleanup: removed %d old entries", removed
                    )
            except OSError as err:
                _LOGGER.warning("History cleanup failed (I/O): %s", err)

        self._cleanup_unsub = async_track_time_interval(
            self.hass, _run_cleanup, timedelta(hours=24)
        )

    # -- cleanup -------------------------------------------------------------

    async def async_shutdown(self) -> None:
        """Stop all camera watchers, cancel timers, and unsubscribe MQTT."""
        # Persist the current game's state before tearing down.
        for game in self._game_state.tracked_games:
            await self._persist_game_state(game)
        if self._cleanup_unsub is not None:
            self._cleanup_unsub()
            self._cleanup_unsub = None
        self._session_tracker.cancel_timer()
        self._client_registry.cancel_timers()
        if self._image_worker_task and not self._image_worker_task.done():
            self._image_worker_task.cancel()
            try:
                await self._image_worker_task
            except asyncio.CancelledError:
                pass
            self._image_worker_task = None
        await self.async_stop_watch_camera()  # stops all
        self.async_unsubscribe()
        # Close LLM backend HTTP session
        await self._llm_backend.close()

    def async_unsubscribe(self) -> None:
        """Unsubscribe from all MQTT topics (delegated to MqttRouter)."""
        self._mqtt_router.unsubscribe()

    # -- data helpers --------------------------------------------------------

    def _notify_update(self) -> None:
        """Push the latest coordinator snapshot to all entities.

        Shared refresh hook used by the coordinator and its collaborators
        (session tracker, …) so a state change shows up immediately.
        """
        self.async_set_updated_data(self._build_data())

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
            "frames_skipped": self._frames_skipped,
            "scene_change": self._last_scene_change,
            "frame_motion": self._last_frame_motion,
            "strategy_note": self._strategy.note(self._current_game),
            "spoiler_level": self._spoiler.default_level,
            "registered_workers": self._client_registry.registered_workers,
            "clients": self._client_registry.clients,
            "active_client_id": self._client_registry.active_client_id,
            "default_game_hint": self._default_game_hint,
            "source_type": self._source_type,
            "available_models": self._available_models,
            "active_model": self.active_model,
            "last_error_message": self._last_error_message,
            "last_error_type": self._last_error_type,
            "last_error_timestamp": self._last_error_timestamp,
            "agent_mode": self._agent_mode,
            "agent_allowed_buttons": self._agent_allowed_buttons,
            "agent_actions_published": self._agent_governor.published,
            "agent_actions_failed": self._agent_governor.failed,
            "agent_last_action": self._agent_governor.last_action,
            "agent_last_action_status": self._agent_governor.last_status,
            "agent_last_action_timestamp": self._agent_governor.last_timestamp,
        }

    async def _async_update_data(self) -> dict:
        """No active polling – all updates come via MQTT push."""
        return self._build_data()
