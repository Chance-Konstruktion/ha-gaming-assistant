"""Behavioural tests for the integration entry point and service handlers.

Drives the real ``async_setup_entry`` with a fake hass (so a real coordinator
is created and every service handler is registered), then invokes the
registered handlers directly to exercise their bodies.
"""

import asyncio
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


class _FakeDataUpdateCoordinator:
    def __init__(self, hass, logger, name=None, update_interval=None):
        self.hass = hass
        self.data = None

    def async_set_updated_data(self, data):
        self.data = data


def _build_stubs():
    stubs = {
        "homeassistant": MagicMock(),
        "homeassistant.components": MagicMock(),
        "homeassistant.config_entries": MagicMock(),
        "homeassistant.helpers": MagicMock(),
        "homeassistant.helpers.entity_platform": MagicMock(),
        "homeassistant.helpers.device_registry": MagicMock(),
    }
    mqtt_mod = types.ModuleType("homeassistant.components.mqtt")
    mqtt_mod.async_publish = AsyncMock()
    mqtt_mod.async_subscribe = AsyncMock(return_value=MagicMock())
    stubs["homeassistant.components.mqtt"] = mqtt_mod
    stubs["homeassistant.components"].mqtt = mqtt_mod

    frontend_mod = types.ModuleType("homeassistant.components.frontend")
    frontend_mod.async_register_built_in_panel = MagicMock()
    frontend_mod.async_remove_panel = MagicMock()
    stubs["homeassistant.components.frontend"] = frontend_mod

    http_mod = types.ModuleType("homeassistant.components.http")
    http_mod.StaticPathConfig = MagicMock()
    stubs["homeassistant.components.http"] = http_mod

    core_mod = types.ModuleType("homeassistant.core")
    core_mod.HomeAssistant = object
    core_mod.ServiceCall = object
    core_mod.callback = lambda f: f
    stubs["homeassistant.core"] = core_mod

    exc_mod = types.ModuleType("homeassistant.exceptions")
    exc_mod.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    stubs["homeassistant.exceptions"] = exc_mod

    const_mod = types.ModuleType("homeassistant.const")

    class _Platform:
        SENSOR = BINARY_SENSOR = SELECT = NUMBER = SWITCH = "p"
        CONVERSATION = IMAGE = "p"

    const_mod.Platform = _Platform
    const_mod.EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
    stubs["homeassistant.const"] = const_mod

    event_mod = types.ModuleType("homeassistant.helpers.event")
    event_mod.async_track_time_interval = MagicMock(return_value=MagicMock())
    stubs["homeassistant.helpers.event"] = event_mod

    duc_mod = types.ModuleType("homeassistant.helpers.update_coordinator")
    duc_mod.DataUpdateCoordinator = _FakeDataUpdateCoordinator
    duc_mod.CoordinatorEntity = type("CoordinatorEntity", (), {
        "__init__": lambda self, coordinator: None
    })
    stubs["homeassistant.helpers.update_coordinator"] = duc_mod
    return stubs, mqtt_mod


_STUBS, _MQTT = _build_stubs()
for _name, _obj in _STUBS.items():
    sys.modules[_name] = _obj
for _key in list(sys.modules.keys()):
    if "custom_components.gaming_assistant" in _key:
        del sys.modules[_key]

import custom_components.gaming_assistant as integration  # noqa: E402
from custom_components.gaming_assistant import (  # noqa: E402
    async_setup_entry,
    async_unload_entry,
    _ALL_SERVICES,
)
from custom_components.gaming_assistant.coordinator import (  # noqa: E402
    GamingAssistantCoordinator,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Services:
    def __init__(self):
        self.handlers = {}
        self.async_call = AsyncMock()

    def has_service(self, domain, service):
        return service in self.handlers

    def async_register(self, domain, service, handler):
        self.handlers[service] = handler

    def async_remove(self, domain, service):
        self.handlers.pop(service, None)


class _ConfigEntries:
    def __init__(self):
        self.async_forward_entry_setups = AsyncMock()
        self.async_unload_platforms = AsyncMock(return_value=True)
        self.entry = None

    def async_get_entry(self, entry_id):
        return self.entry

    def async_update_entry(self, entry, options=None):
        if options is not None:
            entry.options = options


class _Bus:
    def __init__(self):
        self.listeners = []
        self.events = []

    def async_listen_once(self, event, cb):
        self.listeners.append((event, cb))

    def async_fire(self, event, data):
        self.events.append((event, data))


class _FakeHass:
    def __init__(self, config_dir):
        self.config = SimpleNamespace(config_dir=config_dir, language="en")
        self.data = {}
        self.loop = MagicMock()
        self.bus = _Bus()
        self.services = _Services()
        self.config_entries = _ConfigEntries()
        self.http = SimpleNamespace(async_register_static_paths=AsyncMock())
        self.components = MagicMock()
        self.is_running = False

    def async_create_task(self, coro):
        if asyncio.iscoroutine(coro):
            coro.close()
        return MagicMock()

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _setup():
    tmp = tempfile.mkdtemp()
    hass = _FakeHass(tmp)
    entry = SimpleNamespace(entry_id="e1", data={}, options={})
    hass.config_entries.entry = entry
    ok = _run(async_setup_entry(hass, entry))
    coord = hass.data[integration.DOMAIN]["e1"]
    return hass, entry, coord, ok


class TestSetupAndRegistration(unittest.TestCase):
    def test_setup_creates_coordinator_and_services(self):
        hass, entry, coord, ok = _setup()
        self.assertTrue(ok)
        self.assertIsInstance(coord, GamingAssistantCoordinator)
        # All declared services are registered.
        for svc in _ALL_SERVICES:
            self.assertIn(svc, hass.services.handlers, f"missing service {svc}")
        # Panel was registered and the static path served.
        self.assertTrue(hass.data[integration.DOMAIN]["panel_registered"])
        self.assertTrue(hass.http.async_register_static_paths.await_count >= 1)
        # MQTT setup is deferred to HA-start (is_running False).
        self.assertEqual(len(hass.bus.listeners), 1)

    def test_unload_removes_services(self):
        hass, entry, coord, _ = _setup()
        ok = _run(async_unload_entry(hass, entry))
        self.assertTrue(ok)
        self.assertNotIn("e1", hass.data[integration.DOMAIN])
        self.assertEqual(hass.services.handlers, {})


class TestServiceHandlers(unittest.TestCase):
    def setUp(self):
        self.hass, self.entry, self.coord, _ = _setup()
        self.h = self.hass.services.handlers

    def _call(self, data):
        return SimpleNamespace(data=data)

    def test_start_and_stop(self):
        _run(self.h["start"](self._call({})))
        self.assertTrue(self.coord.gaming_mode)
        _run(self.h["stop"](self._call({})))
        self.assertFalse(self.coord.gaming_mode)

    def test_set_spoiler_level_and_profile(self):
        _run(self.h["set_spoiler_level"](self._call({"category": "all", "level": "high"})))
        self.assertEqual(self.coord.default_spoiler_level, "high")
        _run(self.h["set_spoiler_profile"](self._call({"game": "Doom", "level": "none"})))
        self.assertEqual(
            self.coord.spoiler_manager.get_settings("Doom")["story"], "none"
        )

    def test_set_game_hint_and_source_type(self):
        _run(self.h["set_game_hint"](self._call({"game_hint": "Elden Ring"})))
        self.assertEqual(self.coord.default_game_hint, "Elden Ring")
        _run(self.h["set_source_type"](self._call({"source_type": "tabletop"})))
        self.assertEqual(self.coord.source_type, "tabletop")

    def test_set_agent_mode(self):
        _run(self.h["set_agent_mode"](self._call(
            {"enabled": True, "allowed_buttons": "A, B"}
        )))
        self.assertTrue(self.coord.agent_mode)
        self.assertEqual(self.coord.agent_allowed_buttons, ["A", "B"])

    def test_send_yolo_command_publishes(self):
        _MQTT.async_publish.reset_mock()
        _run(self.h["send_yolo_command"](self._call(
            {"command": "set_confidence", "value": 0.5}
        )))
        self.assertTrue(_MQTT.async_publish.await_count >= 1)

    def test_clear_history(self):
        _run(self.h["clear_history"](self._call({"game": "Doom"})))  # no raise

    def test_summarize_session(self):
        self.coord._image_processor._call_ollama_text = AsyncMock(
            return_value="A tidy summary."
        )
        self.coord._session_tips = ["a", "b", "c"]
        self.coord._session_game = "Doom"
        _run(self.h["summarize_session"](self._call({})))
        self.assertEqual(self.coord.last_summary, "A tidy summary.")

    def test_configure_updates_tts_and_persists_options(self):
        _run(self.h["configure"](self._call(
            {"tts_entity": "tts.piper", "tts_target": "media_player.tv"}
        )))
        self.assertEqual(self.coord.tts_entity, "tts.piper")
        self.assertEqual(self.coord.tts_target, "media_player.tv")
        self.assertEqual(self.entry.options.get("tts_entity"), "tts.piper")

    def test_list_game_packs(self):
        _run(self.h["list_game_packs"](self._call({})))  # no raise

    def test_watch_and_stop_camera(self):
        _run(self.h["watch_camera"](self._call({"entity_id": "camera.tv"})))
        self.assertIn("camera.tv", self.coord.active_camera_watchers)
        _run(self.h["stop_watch_camera"](self._call({"entity_id": "camera.tv"})))
        self.assertNotIn("camera.tv", self.coord.active_camera_watchers)


if __name__ == "__main__":
    unittest.main()
