"""Coordinator for Gaming Assistant integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, MQTT_TIP_TOPIC, MQTT_MODE_TOPIC, MQTT_STATUS_TOPIC

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
                    attempt,
                    MQTT_RETRY_ATTEMPTS,
                )
                return
            except HomeAssistantError as err:
                _LOGGER.warning(
                    "MQTT subscribe attempt %d/%d failed: %s – retrying in %ds",
                    attempt,
                    MQTT_RETRY_ATTEMPTS,
                    err,
                    delay,
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

        @callback
        def tip_received(msg) -> None:
            payload = msg.payload
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            self._tip = payload
            _LOGGER.debug("New tip received: %s", payload)
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

        unsub_tip = await mqtt.async_subscribe(
            self.hass, MQTT_TIP_TOPIC, tip_received, 0
        )
        unsub_mode = await mqtt.async_subscribe(
            self.hass, MQTT_MODE_TOPIC, mode_received, 0
        )
        unsub_status = await mqtt.async_subscribe(
            self.hass, MQTT_STATUS_TOPIC, status_received, 0
        )

        self._unsubscribe_callbacks = [unsub_tip, unsub_mode, unsub_status]

    # -- cleanup -------------------------------------------------------------

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
        }

    async def _async_update_data(self) -> dict:
        """No active polling – all updates come via MQTT push."""
        return self._build_data()
