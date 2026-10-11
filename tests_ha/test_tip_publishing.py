"""New tips reach MQTT for the overlays (GA-112), against a real Home Assistant."""

from __future__ import annotations

import pytest

# Needs a real Home Assistant (see test_setup_smoketest.py).
pytest.importorskip("homeassistant.setup", reason="needs a real Home Assistant (pytest-ha job)")

from homeassistant.core import HomeAssistant

from ha_helpers import published


async def test_new_tip_is_published_for_overlays(
    hass: HomeAssistant, integration, mqtt_mock
) -> None:
    _, coordinator = integration
    coordinator._fire_new_tip_event("Reload behind cover.", "Doom", "phone")
    await hass.async_block_till_done()
    assert published(mqtt_mock, "gaming_assistant/tip") == ["Reload behind cover."]
    assert published(mqtt_mock, "gaming_assistant/phone/tip") == ["Reload behind cover."]
