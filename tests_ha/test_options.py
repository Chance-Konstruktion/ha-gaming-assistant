"""Settings from Configure (the options flow) against a real Home Assistant.

What a user saves under Settings → Devices & services → Gaming Assistant →
Configure must take effect right away, and must still be in effect after a
restart (here: a reload of the config entry).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# Needs a real Home Assistant (see test_setup_smoketest.py).
pytest.importorskip("homeassistant.setup", reason="needs a real Home Assistant (pytest-ha job)")

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.gaming_assistant.const import (
    CONF_AUTO_ANNOUNCE,
    CONF_CAMERA_ENTITY,
    CONF_MODEL,
    CONF_TTS_ENTITY,
    CONF_TTS_TARGET,
    DOMAIN,
)

MODELS = ["llava", "qwen2.5vl:7b"]


async def _save_options(hass: HomeAssistant, entry, options: dict) -> None:
    with patch(
        "custom_components.gaming_assistant.config_flow._fetch_ollama_models_async",
        new=AsyncMock(return_value=MODELS),
    ):
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(flow["flow_id"], options)
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()


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


async def test_configure_takes_effect_now_and_after_restart(
    hass: HomeAssistant, integration
) -> None:
    entry, coordinator = integration
    registry = er.async_get(hass)
    tts = registry.async_get_or_create("tts", "test", "voice", suggested_object_id="voice")
    speaker = registry.async_get_or_create(
        "media_player", "test", "kitchen", suggested_object_id="kitchen"
    )
    options = {
        CONF_MODEL: "qwen2.5vl:7b",
        CONF_CAMERA_ENTITY: "",
        CONF_TTS_ENTITY: tts.entity_id,
        CONF_TTS_TARGET: speaker.entity_id,
        CONF_AUTO_ANNOUNCE: True,
    }

    await _save_options(hass, entry, options)
    for coord in (coordinator, await _reload(hass, entry)):
        assert coord.active_model == "qwen2.5vl:7b"
        assert coord.tts_entity == tts.entity_id
        assert coord.tts_target == speaker.entity_id
        assert coord.auto_announce is True


async def test_cleared_option_wins_over_setup_data(hass: HomeAssistant, integration) -> None:
    entry, _ = integration
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_AUTO_ANNOUNCE: True}
    )
    await _save_options(
        hass, entry,
        {CONF_MODEL: "llava", CONF_CAMERA_ENTITY: "", CONF_TTS_ENTITY: "",
         CONF_TTS_TARGET: "", CONF_AUTO_ANNOUNCE: False},
    )
    assert (await _reload(hass, entry)).auto_announce is False
