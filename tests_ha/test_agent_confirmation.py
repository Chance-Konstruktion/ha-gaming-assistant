"""Agent Mode's optional per-action confirmation against a real Home Assistant.

The unit suite stubs the timer helper and the button platform away; this test
drives the real thing: the service turns confirmation on, a held action makes
the confirm button available, pressing it publishes the action over MQTT, and
an action nobody decides on lapses on Home Assistant's own clock.
"""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

# Needs a real Home Assistant (see test_setup_smoketest.py).
pytest.importorskip("homeassistant.setup", reason="needs a real Home Assistant (pytest-ha job)")

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.gaming_assistant.const import (
    AGENT_CONFIRM_TIMEOUT,
    CONF_MODEL,
    CONF_OLLAMA_HOST,
    DOMAIN,
    EVENT_AGENT_ACTION,
)

ACTION = {"action": "tap_button", "button": "A", "duration_ms": 80}


async def _setup(hass: HomeAssistant):
    assert await async_setup_component(hass, "homeassistant", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_MODEL: "llava", CONF_OLLAMA_HOST: "http://localhost:11434"},
        title="Gaming Assistant",
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.gaming_assistant.download_prompt_packs",
        new=AsyncMock(return_value=False),
    ), patch(
        "custom_components.gaming_assistant.coordinator."
        "GamingAssistantCoordinator.async_fetch_available_models",
        new=AsyncMock(return_value=[]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]


def _action_publishes(mqtt_mock) -> list:
    """Payloads sent to an executor action topic.

    Matches on the topic only: newer Home Assistant releases pass extra
    keyword arguments (e.g. ``message_expiry_interval``) to the client.
    """
    return [
        c.args[1]
        for c in mqtt_mock.async_publish.call_args_list
        if c.args and c.args[0] == "gaming_assistant/rig1/action"
    ]


def _entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id is not None, f"{domain} {unique_id} was not registered"
    return entity_id


async def test_confirm_button_publishes_held_action(hass: HomeAssistant, mqtt_mock) -> None:
    entry, coordinator = await _setup(hass)
    events = []
    hass.bus.async_listen(EVENT_AGENT_ACTION, lambda e: events.append(e.data))

    await hass.services.async_call(
        DOMAIN, "set_agent_mode", {"enabled": True, "confirm_actions": True}, blocking=True
    )
    assert coordinator.agent_mode and coordinator.agent_confirm
    confirm_switch = _entity_id(hass, "switch", "gaming_assistant_agent_confirm")
    assert hass.states.get(confirm_switch).state == "on"

    confirm_button = _entity_id(hass, "button", "gaming_assistant_agent_confirm_action")
    reject_button = _entity_id(hass, "button", "gaming_assistant_agent_reject_action")
    # Nothing waits yet, so there is nothing to press.
    assert hass.states.get(confirm_button).state == STATE_UNAVAILABLE
    assert hass.states.get(reject_button).state == STATE_UNAVAILABLE

    coordinator._hold_agent_action("rig1", "Doom", dict(ACTION), time.monotonic(), "ts")
    await hass.async_block_till_done()
    assert hass.states.get(confirm_button).state != STATE_UNAVAILABLE
    pending_id = coordinator.agent_pending_action["id"]
    sensor = _entity_id(hass, "sensor", "gaming_assistant_agent_action")
    state = hass.states.get(sensor)
    assert state.state == "pending"
    assert state.attributes["pending_action_id"] == pending_id

    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call(
        "button", "press", {"entity_id": confirm_button}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(_action_publishes(mqtt_mock)) == 1
    assert coordinator.agent_pending_action is None
    assert hass.states.get(confirm_button).state == STATE_UNAVAILABLE
    assert hass.states.get(sensor).state == "published"
    assert [(e["status"], e["action_id"]) for e in events] == [
        ("pending", pending_id),
        ("published", pending_id),
    ]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_unanswered_action_expires(hass: HomeAssistant, mqtt_mock) -> None:
    entry, coordinator = await _setup(hass)
    coordinator.set_agent_mode(True, confirm=True)
    coordinator._hold_agent_action("rig1", "Doom", dict(ACTION), time.monotonic(), "ts")
    await hass.async_block_till_done()

    mqtt_mock.async_publish.reset_mock()
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=AGENT_CONFIRM_TIMEOUT + 1)
    )
    await hass.async_block_till_done()

    assert coordinator.agent_pending_action is None
    assert coordinator.agent_last_action_status == "expired"
    assert coordinator.agent_actions_expired == 1
    assert _action_publishes(mqtt_mock) == []

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_reject_service_with_action_id(hass: HomeAssistant, mqtt_mock) -> None:
    entry, coordinator = await _setup(hass)
    coordinator.set_agent_mode(True, confirm=True)
    coordinator._hold_agent_action("rig1", "Doom", dict(ACTION), time.monotonic(), "ts")
    await hass.async_block_till_done()
    pending_id = coordinator.agent_pending_action["id"]

    # A stale id from an older notification must not touch the newer action.
    await hass.services.async_call(
        DOMAIN, "reject_agent_action", {"action_id": "stale"}, blocking=True
    )
    assert coordinator.agent_pending_action is not None

    await hass.services.async_call(
        DOMAIN, "reject_agent_action", {"action_id": pending_id}, blocking=True
    )
    assert coordinator.agent_pending_action is None
    assert coordinator.agent_last_action_status == "rejected"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
