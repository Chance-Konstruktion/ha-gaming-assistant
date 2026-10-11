"""Per-client settings (GA-114) against a real Home Assistant.

A client gets its own mode and speaker through the service; the clients
sensor shows it, the setting is stored in the config entry and still there
after a restart (reload).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# Needs a real Home Assistant (see test_setup_smoketest.py).
pytest.importorskip("homeassistant.setup", reason="needs a real Home Assistant (pytest-ha job)")

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.gaming_assistant.const import DOMAIN
from ha_helpers import entity_id


async def _reload(hass: HomeAssistant, entry):
    with patch(
        "custom_components.gaming_assistant.download_prompt_packs",
        new=AsyncMock(return_value=False),
    ), patch(
        "custom_components.gaming_assistant.coordinator."
        "GamingAssistantCoordinator.async_fetch_available_models",
        new=AsyncMock(return_value=[]),
    ):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    return hass.data[DOMAIN][entry.entry_id]


async def test_client_settings_are_shown_and_kept(hass: HomeAssistant, integration) -> None:
    entry, coordinator = integration
    coordinator._touch_client("living-room-tv", {"client_type": "android_tv"})

    await hass.services.async_call(
        DOMAIN, "set_client_options",
        {"client_id": "living-room-tv", "assistant_mode": "opponent",
         "tts_target": "media_player.living_room"},
        blocking=True,
    )
    await hass.async_block_till_done()

    sensor = hass.states.get(entity_id(hass, "sensor", "gaming_assistant_clients"))
    tv = sensor.attributes["clients"]["living-room-tv"]
    assert tv["type"] == "android_tv"
    assert tv["options"] == {
        "assistant_mode": "opponent", "tts_target": "media_player.living_room",
    }
    assert entry.options["client_options"]["living-room-tv"]["assistant_mode"] == "opponent"

    reloaded = await _reload(hass, entry)
    assert reloaded.effective_mode("living-room-tv") == "opponent"
    assert reloaded.effective_mode("someone-else") == "coach"

    await hass.services.async_call(
        DOMAIN, "set_client_options",
        {"client_id": "living-room-tv", "assistant_mode": "global", "tts_target": ""},
        blocking=True,
    )
    assert reloaded.client_options("living-room-tv") == {}
    assert "living-room-tv" not in entry.options["client_options"]


async def test_bad_mode_is_refused(hass: HomeAssistant, integration) -> None:
    entry, _ = integration
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "set_client_options",
            {"client_id": "tv", "assistant_mode": "boss"}, blocking=True,
        )
    assert "client_options" not in entry.options
