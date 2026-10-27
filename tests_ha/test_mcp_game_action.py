"""The guarded one-shot action service used by the optional MCP bridge."""
from __future__ import annotations

import json
import time

import pytest

pytest.importorskip("homeassistant.setup", reason="needs a real Home Assistant (pytest-ha job)")

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.gaming_assistant.const import (
    DOMAIN,
    MQTT_ACTION_TOPIC,
    MQTT_AGENT_COMMAND_TOPIC,
)
from ha_helpers import published


async def _prepare(coordinator) -> str:
    coordinator._client_metadata["rig1"] = {"game": "Doom"}
    coordinator._record_last_image("rig1", b"fixture-frame")
    coordinator.set_agent_mode(
        True, allowed_buttons=["A", "B", "DPAD_UP"], external=True
    )
    return coordinator.last_image_timestamp


async def test_set_agent_mode_can_assign_external_controller(
    hass: HomeAssistant, integration, mqtt_mock
) -> None:
    _, coordinator = integration
    await hass.services.async_call(
        DOMAIN,
        "set_agent_mode",
        {
            "enabled": True,
            "external": True,
            "allowed_buttons": "A,B,DPAD_UP",
            "confirm_actions": False,
        },
        blocking=True,
    )
    assert coordinator.agent_mode is True
    assert coordinator.agent_external_control is True
    assert coordinator.agent_allowed_buttons == ["A", "B", "DPAD_UP"]
    [raw_reset] = published(mqtt_mock, MQTT_AGENT_COMMAND_TOPIC)
    reset = json.loads(raw_reset)
    assert reset == {
        "command": "reset",
        "session_id": coordinator._agent_session_id,
    }


async def test_set_agent_mode_stays_off_when_reset_publish_fails(
    hass: HomeAssistant, integration, mqtt_mock
) -> None:
    _, coordinator = integration
    mqtt_mock.async_publish.side_effect = HomeAssistantError("broker unavailable")
    with pytest.raises(HomeAssistantError, match="Player 2 remains disabled"):
        await hass.services.async_call(
            DOMAIN,
            "set_agent_mode",
            {
                "enabled": True,
                "external": True,
                "allowed_buttons": "A,B",
            },
            blocking=True,
        )
    assert coordinator.agent_mode is False
    assert coordinator.agent_external_control is False


async def test_set_agent_mode_rejects_unknown_allowed_buttons(
    hass: HomeAssistant, integration
) -> None:
    _, coordinator = integration
    with pytest.raises(HomeAssistantError, match="Unknown allowed_buttons"):
        await hass.services.async_call(
            DOMAIN,
            "set_agent_mode",
            {
                "enabled": True,
                "external": True,
                "allowed_buttons": "A,NOT_A_BUTTON",
            },
            blocking=True,
        )
    assert coordinator.agent_mode is False


async def test_send_game_action_publishes_short_lived_command(
    hass: HomeAssistant, integration, mqtt_mock
) -> None:
    _, coordinator = integration
    timestamp = await _prepare(coordinator)
    await hass.services.async_call(
        DOMAIN,
        "send_game_action",
        {
            "client_id": "rig1",
            "expected_frame_timestamp": timestamp,
            "command_id": "mcp-command-1",
            "action": "tap_button",
            "button": "A",
            "duration_ms": 80,
            "reason": "test command",
        },
        blocking=True,
    )
    [raw] = published(mqtt_mock, MQTT_ACTION_TOPIC.format(client_id="rig1"))
    payload = json.loads(raw)
    assert payload["command_id"] == "mcp-command-1"
    assert payload["session_id"] == coordinator._agent_session_id
    assert payload["expires_at"] > time.time()
    assert payload["action"] == "tap_button"
    assert payload["button"] == "A"


async def test_send_game_action_rejects_button_outside_allowlist(
    hass: HomeAssistant, integration, mqtt_mock
) -> None:
    _, coordinator = integration
    timestamp = await _prepare(coordinator)
    mqtt_mock.async_publish.reset_mock()
    with pytest.raises(HomeAssistantError, match="disallowed"):
        await hass.services.async_call(
            DOMAIN,
            "send_game_action",
            {
                "client_id": "rig1",
                "expected_frame_timestamp": timestamp,
                "command_id": "mcp-command-2",
                "action": "tap_button",
                "button": "START",
            },
            blocking=True,
        )
    assert published(mqtt_mock, MQTT_ACTION_TOPIC.format(client_id="rig1")) == []


async def test_send_game_action_requires_external_control_mode(
    hass: HomeAssistant, integration, mqtt_mock
) -> None:
    _, coordinator = integration
    timestamp = await _prepare(coordinator)
    coordinator.set_agent_mode(True, allowed_buttons=["A"], external=False)
    mqtt_mock.async_publish.reset_mock()
    with pytest.raises(HomeAssistantError, match="local-controller mode"):
        await hass.services.async_call(
            DOMAIN,
            "send_game_action",
            {
                "client_id": "rig1",
                "expected_frame_timestamp": timestamp,
                "command_id": "mcp-local-mode-test",
                "action": "tap_button",
                "button": "A",
            },
            blocking=True,
        )
    assert published(mqtt_mock, MQTT_ACTION_TOPIC.format(client_id="rig1")) == []


async def test_send_game_action_does_not_bypass_confirmation(
    hass: HomeAssistant, integration, mqtt_mock
) -> None:
    _, coordinator = integration
    timestamp = await _prepare(coordinator)
    coordinator.set_agent_mode(
        True, allowed_buttons=["A"], confirm=True, external=True
    )
    mqtt_mock.async_publish.reset_mock()
    with pytest.raises(HomeAssistantError, match="Per-action confirmation is enabled"):
        await hass.services.async_call(
            DOMAIN,
            "send_game_action",
            {
                "client_id": "rig1",
                "expected_frame_timestamp": timestamp,
                "command_id": "mcp-confirmation-test",
                "action": "tap_button",
                "button": "A",
            },
            blocking=True,
        )
    assert published(mqtt_mock, MQTT_ACTION_TOPIC.format(client_id="rig1")) == []


async def test_send_game_action_rejects_stale_snapshot(
    hass: HomeAssistant, integration, mqtt_mock
) -> None:
    _, coordinator = integration
    await _prepare(coordinator)
    mqtt_mock.async_publish.reset_mock()
    from datetime import datetime, timedelta

    stale = (datetime.now().astimezone() - timedelta(seconds=60)).isoformat()
    with pytest.raises(HomeAssistantError, match="too old"):
        await hass.services.async_call(
            DOMAIN,
            "send_game_action",
            {
                "client_id": "rig1",
                "expected_frame_timestamp": stale,
                "command_id": "mcp-command-3",
                "action": "tap_button",
                "button": "A",
            },
            blocking=True,
        )
    assert published(mqtt_mock, MQTT_ACTION_TOPIC.format(client_id="rig1")) == []
