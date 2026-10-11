"""Remote control services (GA-120, GA-121) against a real Home Assistant.

The services only publish: a named request to the RustDesk controller or the
companion listener on the target machine. This checks the real service
registry, the MQTT publish and that bad targets are refused before anything
is sent.
"""

from __future__ import annotations

import json

import pytest

# Needs a real Home Assistant (see test_setup_smoketest.py).
pytest.importorskip("homeassistant.setup", reason="needs a real Home Assistant (pytest-ha job)")

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.gaming_assistant.const import DOMAIN
from ha_helpers import published


async def test_open_remote_session(hass: HomeAssistant, integration, mqtt_mock) -> None:
    await hass.services.async_call(
        DOMAIN, "open_remote_session",
        {"controller": "gaming-pc", "peer": "tablet", "mode": "file_transfer"},
        blocking=True,
    )
    [payload] = published(mqtt_mock, "gaming_assistant/gaming-pc/remote")
    assert json.loads(payload) == {"peer": "tablet", "mode": "file_transfer"}


async def test_companion_command(hass: HomeAssistant, integration, mqtt_mock) -> None:
    await hass.services.async_call(
        DOMAIN, "companion_command", {"device": "gaming-pc", "command": "pause"}, blocking=True
    )
    [payload] = published(mqtt_mock, "gaming_assistant/gaming-pc/companion")
    assert json.loads(payload) == {"command": "pause"}


async def test_wildcards_never_reach_mqtt(hass: HomeAssistant, integration, mqtt_mock) -> None:
    mqtt_mock.async_publish.reset_mock()
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "companion_command", {"device": "#", "command": "pause"}, blocking=True
        )
    assert mqtt_mock.async_publish.call_count == 0
