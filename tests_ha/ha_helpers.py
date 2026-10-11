"""Small helpers shared by the real-Home-Assistant tests."""

from __future__ import annotations


def entity_id(hass, domain: str, unique_id: str) -> str:
    """Entity id registered for one of our unique ids (fails loudly if missing)."""
    from homeassistant.helpers import entity_registry as er

    eid = er.async_get(hass).async_get_entity_id(domain, "gaming_assistant", unique_id)
    assert eid is not None, f"{domain} {unique_id} was not registered"
    return eid


def published(mqtt_mock, topic: str) -> list:
    """Payloads published to *topic*.

    Matches on the topic only: newer Home Assistant releases pass extra
    keyword arguments (e.g. ``message_expiry_interval``) to the client.
    """
    return [
        c.args[1]
        for c in mqtt_mock.async_publish.call_args_list
        if c.args and c.args[0] == topic
    ]
