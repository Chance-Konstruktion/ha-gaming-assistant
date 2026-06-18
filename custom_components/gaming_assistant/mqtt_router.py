"""MQTT subscription routing for the Gaming Assistant.

Owns the integration's MQTT plumbing: subscribing (with exponential-backoff
retry) to every Gaming Assistant topic, decoding each message, and routing it
to the right place on the coordinator — tips, mode/status, frames, metadata,
worker registration, YOLO detections, and per-client presence.

This is a collaborator of :class:`GamingAssistantCoordinator`. It owns the
subscription handles, the connection flag, and the YOLO-worker status map, and
reaches back through the coordinator for everything the handlers update.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    MQTT_DETECTIONS_TOPIC,
    MQTT_IMAGE_TOPIC,
    MQTT_META_TOPIC,
    MQTT_MODE_TOPIC,
    MQTT_STATUS_TOPIC,
    MQTT_TIP_TOPIC,
    MQTT_WORKER_REGISTER_TOPIC,
    MQTT_YOLO_STATUS_TOPIC,
)

if TYPE_CHECKING:
    from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)

MQTT_RETRY_ATTEMPTS = 5
MQTT_RETRY_BASE_DELAY = 3  # seconds, doubles each attempt


class MqttRouter:
    """Owns MQTT subscriptions and routes messages to the coordinator."""

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        self.coord = coordinator
        self._unsubscribe_callbacks: list = []
        self._connected: bool = False
        self._yolo_workers: dict[str, dict[str, Any]] = {}

    # -- accessors -----------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def yolo_workers(self) -> dict[str, dict[str, Any]]:
        """Return status of connected YOLO workers."""
        return self._yolo_workers

    # -- setup / teardown ----------------------------------------------------

    async def async_setup(self) -> None:
        """Subscribe to MQTT topics with exponential-backoff retry."""
        delay = MQTT_RETRY_BASE_DELAY

        for attempt in range(1, MQTT_RETRY_ATTEMPTS + 1):
            try:
                await self.subscribe_topics()
                self._connected = True
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

    def unsubscribe(self) -> None:
        """Unsubscribe from all MQTT topics."""
        for unsub in self._unsubscribe_callbacks:
            unsub()
        self._unsubscribe_callbacks.clear()
        self._connected = False

    # -- subscriptions -------------------------------------------------------

    async def subscribe_topics(self) -> None:
        """Subscribe to all Gaming Assistant MQTT topics."""
        coord = self.coord

        # -- Legacy topics (v0.2/v0.3 compatibility) -------------------------

        @callback
        def tip_received(msg) -> None:
            payload = msg.payload
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            coord._tip = payload
            _LOGGER.debug("New tip received (legacy): %s", payload)
            coord._notify_update()

        @callback
        def mode_received(msg) -> None:
            payload = msg.payload
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            coord._gaming_mode = payload.strip().lower() in ("on", "true", "1")
            _LOGGER.debug("Gaming mode changed: %s", coord._gaming_mode)
            coord._notify_update()

        @callback
        def status_received(msg) -> None:
            payload = msg.payload
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            coord._status = payload.strip().lower()
            coord._notify_update()

        # -- New topics (v0.4 Thin Client) -----------------------------------

        @callback
        def image_received(msg) -> None:
            """Handle incoming image from a capture agent."""
            client_id = msg.topic.split("/")[1]
            _LOGGER.debug("Image received from client: %s", client_id)
            coord._record_last_image(client_id, msg.payload)
            coord._register_worker(client_id)
            coord.hass.async_create_task(coord._enqueue_image(client_id, msg.payload))

        @callback
        def meta_received(msg) -> None:
            """Handle incoming metadata from a capture agent."""
            client_id = msg.topic.split("/")[1]
            try:
                payload = msg.payload
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
                metadata = json.loads(payload)
                coord._client_metadata[client_id] = metadata
                coord._touch_client(client_id, metadata)
                coord._register_worker(client_id, metadata)
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
                coord._register_worker(client_id, info)
                _LOGGER.info("Worker registered via MQTT: %s", client_id)
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                _LOGGER.warning("Invalid register payload from %s: %s", client_id, err)

        @callback
        def detections_received(msg) -> None:
            """Handle YOLO detections from external worker."""
            client_id = msg.topic.split("/")[1]
            try:
                payload = msg.payload
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
                data = json.loads(payload)
                self.handle_yolo_detections(client_id, data)
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                _LOGGER.warning("Invalid detections from %s: %s", client_id, err)

        @callback
        def client_status_received(msg) -> None:
            """Handle per-client status on ``gaming_assistant/{id}/status``.

            Two payload shapes share this 3-segment topic pattern:
              * plain ``online``/``offline`` – capture agents and the agent
                executor (their retained Last-Will presence), and
              * a JSON document – YOLO worker status.

            Plain presence updates the worker/client registry; JSON is recorded
            as YOLO worker status. Anything else is ignored quietly instead of
            spamming a warning on every capture-agent connect/disconnect.
            """
            cid = msg.topic.split("/")[1]
            payload = msg.payload
            if isinstance(payload, bytes):
                try:
                    payload = payload.decode("utf-8")
                except UnicodeDecodeError:
                    return
            text = (payload or "").strip()
            lowered = text.lower()

            # Plain-text capture-agent / executor presence (LWT).
            if lowered in ("online", "offline"):
                online = lowered == "online"
                coord._client_registry.mark_presence(cid, online)
                _LOGGER.debug("Client %s presence: %s", cid, lowered)
                coord._notify_update()
                return

            # Otherwise expect a JSON YOLO-worker status document.
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                _LOGGER.debug("Ignoring non-JSON status from %s: %s", cid, text[:40])
                return
            status = data.get("status", "unknown")
            self._yolo_workers[cid] = data
            _LOGGER.info(
                "YOLO worker %s: %s (model=%s, backend=%s)",
                cid, status,
                data.get("model", "?"), data.get("backend", "?"),
            )

        hass = coord.hass
        unsub_tip = await mqtt.async_subscribe(hass, MQTT_TIP_TOPIC, tip_received, 0)
        unsub_mode = await mqtt.async_subscribe(hass, MQTT_MODE_TOPIC, mode_received, 0)
        unsub_status = await mqtt.async_subscribe(
            hass, MQTT_STATUS_TOPIC, status_received, 0
        )
        unsub_image = await mqtt.async_subscribe(
            hass, MQTT_IMAGE_TOPIC, image_received, 0, encoding=None
        )
        unsub_meta = await mqtt.async_subscribe(hass, MQTT_META_TOPIC, meta_received, 0)
        unsub_register = await mqtt.async_subscribe(
            hass, MQTT_WORKER_REGISTER_TOPIC, worker_register_received, 0
        )
        unsub_detections = await mqtt.async_subscribe(
            hass, MQTT_DETECTIONS_TOPIC, detections_received, 0
        )
        unsub_client_status = await mqtt.async_subscribe(
            hass, MQTT_YOLO_STATUS_TOPIC, client_status_received, 0
        )

        self._unsubscribe_callbacks = [
            unsub_tip, unsub_mode, unsub_status, unsub_image, unsub_meta,
            unsub_register, unsub_detections, unsub_client_status,
        ]

    # -- YOLO detection handling ---------------------------------------------

    def handle_yolo_detections(self, client_id: str, data: dict[str, Any]) -> None:
        """Process structured detections from the YOLO worker.

        Detections are fed into the game state engine as observations
        so the LLM can use them for context.
        """
        detections = data.get("detections", [])
        if not detections:
            return

        game = self.coord.current_game or "unknown"
        inference_ms = data.get("inference_ms", 0)

        # Build observations from detections.
        observations: dict[str, Any] = {
            "yolo_objects": [d["class"] for d in detections[:10]],
            "yolo_count": len(detections),
            "yolo_inference_ms": inference_ms,
        }

        # Extract prominent objects by confidence.
        if detections:
            top = max(detections, key=lambda d: d.get("confidence", 0))
            observations["yolo_top_object"] = top["class"]
            observations["yolo_top_confidence"] = top.get("confidence", 0)

        # Feed into game state engine.
        self.coord.game_state_manager.update(
            game, observations, source=f"yolo:{client_id}"
        )

        _LOGGER.debug(
            "YOLO detections from %s: %d objects (%.0fms)",
            client_id, len(detections), inference_ms,
        )
