"""Real Home Assistant load smoketest.

Every other test in this suite stubs Home Assistant away and exercises the code
in isolation. This one does the opposite: it boots a genuine ``HomeAssistant``
instance via ``pytest-homeassistant-custom-component`` and drives the integration
through the real config-entry lifecycle — set up all platforms, reach
``LOADED``, then unload cleanly.

It is the only test that can catch the class of bug unit tests are blind to: a
broken ``manifest.json``, a platform that fails to forward, a setup step that
explodes against the real HA APIs, or a dependency that no longer resolves. It
is intentionally run as a separate CI job (it pulls in the full HA core), see
``.github/workflows/ci.yml`` and ``requirements-smoketest.txt``.

Network side effects of setup (prompt-pack download, Ollama model fetch) are
patched out; MQTT is provided by the ``mqtt_mock`` fixture.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gaming_assistant.const import (
    CONF_INTERVAL,
    CONF_MODEL,
    CONF_OLLAMA_HOST,
    CONF_TIMEOUT,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant discover custom_components/gaming_assistant."""
    yield


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Allow lingering timers for this smoketest.

    Home Assistant's own mqtt component (provided here by ``mqtt_mock``)
    schedules a self-rescheduling "misc periodic" timer while connected. It is
    not owned by this integration and cannot be cancelled from the config entry,
    so it would otherwise trip pytest-hacc's cleanup guard.
    """
    return True


# Minimal config entry. Every consumed key also has a runtime default, so this
# only needs to be a plausible, well-typed subset.
ENTRY_DATA = {
    CONF_MODEL: "llava",
    CONF_OLLAMA_HOST: "http://localhost:11434",
    CONF_INTERVAL: 5,
    CONF_TIMEOUT: 30,
}


async def test_config_entry_sets_up_and_unloads(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """The integration sets up from a config entry and unloads cleanly."""
    # The `conversation` dependency's default agent reads exposed-entity data
    # that the core `homeassistant` integration initialises, so set it up first.
    assert await async_setup_component(hass, "homeassistant", {})

    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, title="Gaming Assistant")
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

        # The entry reached LOADED and the coordinator is registered.
        assert entry.state is ConfigEntryState.LOADED
        assert entry.entry_id in hass.data[DOMAIN]

        # The integration registered its services.
        assert hass.services.has_service(DOMAIN, "analyze")

        # At least one entity was created across the forwarded platforms.
        states = [s for s in hass.states.async_all() if s.domain != "persistent_notification"]
        assert states, "no entities were created by any platform"

        # The status sensor must produce its attributes even before any MQTT
        # data has arrived (coordinator.data is None at first state write) —
        # regression guard for the unguarded `coordinator.data.get(...)` crash.
        ent_reg = er.async_get(hass)
        status_id = ent_reg.async_get_entity_id("sensor", DOMAIN, "gaming_assistant_status")
        assert status_id is not None, "status sensor was not registered"
        status = hass.states.get(status_id)
        assert status is not None and "available_models" in status.attributes

    # Unload tears everything down without raising.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
