"""Shared fixtures for the tests that boot a real Home Assistant."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant discover custom_components/gaming_assistant."""
    yield


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Allow lingering timers in these tests.

    Home Assistant's own mqtt component (provided here by ``mqtt_mock``)
    schedules a self-rescheduling "misc periodic" timer while connected. It is
    not owned by this integration and cannot be cancelled from the config entry,
    so it would otherwise trip pytest-hacc's cleanup guard.
    """
    return True


@pytest.fixture
async def integration(hass, mqtt_mock):
    """Gaming Assistant set up for real, network calls patched out.

    Yields ``(entry, coordinator)`` and unloads the entry afterwards. Home
    Assistant imports stay inside the fixture so a dev machine without Home
    Assistant can still collect (and skip) this directory.
    """
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.gaming_assistant.const import (
        CONF_MODEL,
        CONF_OLLAMA_HOST,
        DOMAIN,
    )

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
    yield entry, hass.data[DOMAIN][entry.entry_id]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
