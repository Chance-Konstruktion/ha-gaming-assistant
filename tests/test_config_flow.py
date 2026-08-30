"""Dedicated tests for config_flow helper behaviour without HA runtime."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# -- minimal voluptuous stub --------------------------------------------------
vol = types.ModuleType("voluptuous")


class _Key:
    def __init__(self, schema, default=None):
        self.schema = schema
        self.default = default


class _In:
    def __init__(self, container):
        self.container = list(container)


vol.Schema = lambda mapping: types.SimpleNamespace(schema=mapping)
vol.Required = lambda key, default=None: _Key(key, default)
vol.Optional = lambda key, default=None: _Key(key, default)
vol.In = lambda container: _In(container)
vol.All = lambda *args: args
vol.Range = lambda **kwargs: kwargs

# -- minimal homeassistant stubs for importing config_flow --------------------
ha_mod = types.ModuleType("homeassistant")
components_mod = types.ModuleType("homeassistant.components")
mqtt_mod = types.ModuleType("homeassistant.components.mqtt")
config_entries_mod = types.ModuleType("homeassistant.config_entries")
const_mod = types.ModuleType("homeassistant.const")
core_mod = types.ModuleType("homeassistant.core")
helpers_mod = types.ModuleType("homeassistant.helpers")
er_mod = types.ModuleType("homeassistant.helpers.entity_registry")
device_registry_mod = types.ModuleType("homeassistant.helpers.device_registry")
update_coordinator_mod = types.ModuleType("homeassistant.helpers.update_coordinator")
event_mod = types.ModuleType("homeassistant.helpers.event")
exceptions_mod = types.ModuleType("homeassistant.exceptions")


class _ConfigFlow:
    def __init_subclass__(cls, **kwargs):
        return None


config_entries_mod.ConfigFlow = _ConfigFlow
config_entries_mod.OptionsFlow = object
config_entries_mod.ConfigEntry = object
config_entries_mod.ConfigFlowResult = dict
const_mod.EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
const_mod.Platform = types.SimpleNamespace(
    SENSOR="sensor",
    BINARY_SENSOR="binary_sensor",
    SELECT="select",
    NUMBER="number",
    SWITCH="switch",
    CONVERSATION="conversation",
)
core_mod.HomeAssistant = object
core_mod.ServiceCall = object
core_mod.callback = lambda fn: fn
helpers_mod.entity_registry = er_mod
device_registry_mod.DeviceInfo = object
update_coordinator_mod.DataUpdateCoordinator = object
event_mod.async_track_time_interval = MagicMock()
exceptions_mod.HomeAssistantError = Exception
ha_mod.config_entries = config_entries_mod
ha_mod.core = core_mod
ha_mod.helpers = helpers_mod
ha_mod.components = components_mod
components_mod.mqtt = mqtt_mod

sys.modules["voluptuous"] = vol
sys.modules["homeassistant"] = ha_mod
sys.modules["homeassistant.components"] = components_mod
sys.modules["homeassistant.components.mqtt"] = mqtt_mod
sys.modules["homeassistant.config_entries"] = config_entries_mod
sys.modules["homeassistant.const"] = const_mod
sys.modules["homeassistant.core"] = core_mod
sys.modules["homeassistant.exceptions"] = exceptions_mod
sys.modules["homeassistant.helpers"] = helpers_mod
sys.modules["homeassistant.helpers.entity_registry"] = er_mod
sys.modules["homeassistant.helpers.device_registry"] = device_registry_mod
sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator_mod
sys.modules["homeassistant.helpers.event"] = event_mod

from custom_components.gaming_assistant.config_flow import (
    FALLBACK_MODELS,
    GamingAssistantConfigFlow,
    _fetch_ollama_models_async,
    _schema_model_step,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestConfigFlowHelpers(unittest.TestCase):
    def test_schema_model_step_includes_default_if_missing(self):
        schema = _schema_model_step(["llava"], "qwen2.5vl", 10, 60)
        model_key = next(k for k in schema.schema if getattr(k, "schema", "") == "model")
        model_validator = schema.schema[model_key]
        self.assertIn("qwen2.5vl", model_validator.container)

    def test_fetch_ollama_models_success(self):
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={
            "models": [{"name": "llava"}, {"name": "qwen2.5vl"}]
        })

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_ctx)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            models = _run(_fetch_ollama_models_async("http://localhost:11434"))
            self.assertEqual(models, ["llava", "qwen2.5vl"])

    def test_fetch_ollama_models_empty_fallback(self):
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"models": []})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_ctx)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            models = _run(_fetch_ollama_models_async("http://localhost:11434"))
            self.assertEqual(models, FALLBACK_MODELS)

    def test_fetch_ollama_models_connection_error_none(self):
        import aiohttp as _aiohttp

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(side_effect=_aiohttp.ClientConnectionError("nope"))
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = _run(_fetch_ollama_models_async("http://localhost:11434"))
            self.assertIsNone(result)

    def test_get_entities_by_domain_filters_disabled(self):
        flow = GamingAssistantConfigFlow()
        flow.hass = object()

        enabled_cam = types.SimpleNamespace(entity_id="camera.one", domain="camera", disabled=False)
        disabled_cam = types.SimpleNamespace(entity_id="camera.two", domain="camera", disabled=True)
        media = types.SimpleNamespace(entity_id="media_player.tv", domain="media_player", disabled=False)

        registry = types.SimpleNamespace(
            entities={
                "a": enabled_cam,
                "b": disabled_cam,
                "c": media,
            }
        )
        er_mod.async_get = lambda hass: registry

        cameras = flow._get_entities_by_domain("camera")
        self.assertEqual(cameras, ["camera.one"])


if __name__ == "__main__":
    unittest.main()
