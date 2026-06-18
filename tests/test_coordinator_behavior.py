"""Behavioural tests for GamingAssistantCoordinator.

The coordinator could previously not be instantiated without a full Home
Assistant runtime (which is why the old ``test_coordinator.py`` only matched
source strings). Here we stub the HA surface the coordinator actually touches
— a real base class that stores ``hass``, an awaitable executor, an event bus
that records fires, and an async MQTT publish — so we can construct a real
coordinator and exercise its logic for real.
"""

import asyncio
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Stub the HA surface BEFORE importing the integration
# ---------------------------------------------------------------------------

class _FakeDataUpdateCoordinator:
    """Minimal stand-in that stores hass and records the last data push."""

    def __init__(self, hass, logger, name=None, update_interval=None):
        self.hass = hass
        self.data = None

    def async_set_updated_data(self, data):
        self.data = data


class _FakeCoordinatorEntity:
    def __init__(self, coordinator):
        pass


class _Platform:
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    SELECT = "select"
    NUMBER = "number"
    SWITCH = "switch"
    CONVERSATION = "conversation"
    IMAGE = "image"


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
    # `from homeassistant.components import mqtt` reads an attribute off the
    # (MagicMock) components package, which ignores sys.modules — so bind it.
    stubs["homeassistant.components"].mqtt = mqtt_mod

    # The camera watcher does `from homeassistant.components.camera import
    # async_get_image` inside its loop, so provide a stub module for it.
    camera_mod = types.ModuleType("homeassistant.components.camera")
    camera_mod.async_get_image = AsyncMock()
    stubs["homeassistant.components.camera"] = camera_mod
    stubs["homeassistant.components"].camera = camera_mod

    core_mod = types.ModuleType("homeassistant.core")
    core_mod.HomeAssistant = object
    core_mod.ServiceCall = object
    core_mod.callback = lambda f: f  # passthrough decorator
    stubs["homeassistant.core"] = core_mod

    exc_mod = types.ModuleType("homeassistant.exceptions")
    exc_mod.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    stubs["homeassistant.exceptions"] = exc_mod

    const_mod = types.ModuleType("homeassistant.const")
    const_mod.Platform = _Platform
    const_mod.EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
    stubs["homeassistant.const"] = const_mod

    event_mod = types.ModuleType("homeassistant.helpers.event")
    event_mod.async_track_time_interval = MagicMock(return_value=MagicMock())
    stubs["homeassistant.helpers.event"] = event_mod

    duc_mod = types.ModuleType("homeassistant.helpers.update_coordinator")
    duc_mod.DataUpdateCoordinator = _FakeDataUpdateCoordinator
    duc_mod.CoordinatorEntity = _FakeCoordinatorEntity
    stubs["homeassistant.helpers.update_coordinator"] = duc_mod

    return stubs, mqtt_mod


_STUBS, _MQTT = _build_stubs()
for _name, _obj in _STUBS.items():
    sys.modules[_name] = _obj

for _key in list(sys.modules.keys()):
    if "custom_components.gaming_assistant" in _key:
        del sys.modules[_key]

from custom_components.gaming_assistant.coordinator import (  # noqa: E402
    GamingAssistantCoordinator,
)
import custom_components.gaming_assistant.camera_watcher as camera_watcher  # noqa: E402
from custom_components.gaming_assistant.const import (  # noqa: E402
    AGENT_MAX_CONSECUTIVE_FAILURES,
    EVENT_AGENT_ACTION,
    EVENT_NEW_TIP,
    EVENT_SESSION_ENDED,
    MQTT_DETECTIONS_TOPIC,
    MQTT_IMAGE_TOPIC,
    MQTT_META_TOPIC,
    MQTT_MODE_TOPIC,
    MQTT_STATUS_TOPIC,
    MQTT_TIP_TOPIC,
    MQTT_WORKER_REGISTER_TOPIC,
    MQTT_YOLO_STATUS_TOPIC,
)

_CAMERA = sys.modules["homeassistant.components.camera"]


# ---------------------------------------------------------------------------
# Fake hass
# ---------------------------------------------------------------------------

class _FakeBus:
    def __init__(self):
        self.events = []

    def async_fire(self, event_type, data):
        self.events.append((event_type, data))

    def fired(self, event_type):
        return [d for (t, d) in self.events if t == event_type]


class _FakeConfig:
    def __init__(self, config_dir):
        self.config_dir = config_dir
        self.language = "en"


class _FakeServices:
    def __init__(self):
        self.async_call = AsyncMock()


class _FakeHass:
    def __init__(self, config_dir):
        self.config = _FakeConfig(config_dir)
        self.loop = MagicMock()
        self.bus = _FakeBus()
        self.services = _FakeServices()

    def async_create_task(self, coro):
        if asyncio.iscoroutine(coro):
            coro.close()
        return MagicMock()

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_coord():
    tmp = tempfile.mkdtemp()
    hass = _FakeHass(tmp)
    coord = GamingAssistantCoordinator(hass, {})
    coord._config_entry_id = "test_entry"
    return coord, hass


# ---------------------------------------------------------------------------
# Properties & setters
# ---------------------------------------------------------------------------

class TestPropertiesAndSetters(unittest.TestCase):
    def setUp(self):
        self.coord, self.hass = _make_coord()

    def test_initial_defaults(self):
        self.assertEqual(self.coord.tip, "Waiting for tips...")
        self.assertFalse(self.coord.gaming_mode)
        self.assertEqual(self.coord.status, "idle")
        self.assertFalse(self.coord.mqtt_connected)
        self.assertEqual(self.coord.tip_count, 0)
        self.assertFalse(self.coord.agent_mode)
        self.assertEqual(self.coord.agent_actions_published, 0)

    def test_build_data_has_expected_keys(self):
        data = self.coord._build_data()
        for key in (
            "tip", "gaming_mode", "status", "agent_mode",
            "agent_actions_published", "agent_last_action_status",
            "source_type", "assistant_mode", "active_model",
        ):
            self.assertIn(key, data)

    def test_interval_clamped(self):
        self.coord.set_analysis_interval(1)
        self.assertEqual(self.coord.analysis_interval, 5)   # min 5
        self.coord.set_analysis_interval(9999)
        self.assertEqual(self.coord.analysis_interval, 120)  # max 120

    def test_timeout_clamped(self):
        self.coord.set_analysis_timeout(1)
        self.assertEqual(self.coord.analysis_timeout, 10)    # min 10
        self.coord.set_analysis_timeout(9999)
        self.assertEqual(self.coord.analysis_timeout, 300)   # max 300

    def test_assistant_mode_valid_and_invalid(self):
        self.coord.set_assistant_mode("opponent")
        self.assertEqual(self.coord.assistant_mode, "opponent")
        self.coord.set_assistant_mode("nonsense")
        self.assertEqual(self.coord.assistant_mode, "opponent")  # unchanged

    def test_source_type_valid_and_invalid(self):
        self.coord.set_source_type("console")
        self.assertEqual(self.coord.source_type, "console")
        self.coord.set_source_type("bogus")
        self.assertEqual(self.coord.source_type, "console")  # unchanged

    def test_spoiler_level_valid_and_invalid(self):
        self.coord.set_default_spoiler_level("high")
        self.assertEqual(self.coord.default_spoiler_level, "high")
        self.coord.set_default_spoiler_level("ultra")  # invalid -> ignored
        self.assertEqual(self.coord.default_spoiler_level, "high")

    def test_toggle_switches(self):
        self.coord.set_auto_announce(True)
        self.assertTrue(self.coord.auto_announce)
        self.coord.set_auto_summary(True)
        self.assertTrue(self.coord.auto_summary)

    def test_game_hint(self):
        self.coord.set_default_game_hint("Elden Ring")
        self.assertEqual(self.coord.default_game_hint, "Elden Ring")
        self.assertEqual(self.coord.current_game, "Elden Ring")

    def test_available_game_packs_is_list(self):
        self.assertIsInstance(self.coord.available_game_packs, list)

    def test_record_error(self):
        self.coord._record_error(ValueError("boom"))
        self.assertEqual(self.coord.error_count, 1)
        self.assertEqual(self.coord.last_error_message, "boom")
        self.assertEqual(self.coord.last_error_type, "ValueError")


# ---------------------------------------------------------------------------
# Worker registry & client tracking
# ---------------------------------------------------------------------------

class TestRegistryAndClients(unittest.TestCase):
    def setUp(self):
        self.coord, self.hass = _make_coord()

    def test_register_worker_creates_and_updates(self):
        self.coord._register_worker("rig1", {"type": "pc", "name": "PC"})
        self.assertIn("rig1", self.coord.registered_workers)
        self.assertEqual(self.coord.registered_workers["rig1"]["type"], "pc")
        self.coord._register_worker("rig1")  # update last_seen branch
        self.assertEqual(self.coord.registered_workers["rig1"]["type"], "pc")

    def test_touch_client_sets_current_game(self):
        self.coord._touch_client("rig1", {"window_title": "Doom"})
        self.assertEqual(self.coord.current_game, "Doom")
        self.assertEqual(self.coord.current_client_id, "rig1")

    def test_handle_yolo_detections_feeds_game_state(self):
        self.coord._current_game = "Doom"
        self.coord._handle_yolo_detections(
            "yolo1",
            {"detections": [{"class": "enemy", "confidence": 0.9}],
             "inference_ms": 12},
        )
        current = self.coord.game_state_manager.get_current("Doom")
        self.assertIsNotNone(current)
        self.assertIn("enemy", current["yolo_objects"])

    def test_handle_yolo_detections_empty_is_noop(self):
        self.coord._current_game = "Doom"
        self.coord._handle_yolo_detections("yolo1", {"detections": []})
        self.assertIsNone(self.coord.game_state_manager.get_current("Doom"))

    def test_client_status_presence_via_subscribe_handler(self):
        # Drive the tolerant status handler created in _subscribe_topics.
        _run(self.coord._subscribe_topics())
        # Find the handler bound to the +/status subscription.
        calls = _MQTT.async_subscribe.await_args_list
        status_cb = None
        for call in calls:
            topic = call.args[1]
            if topic.endswith("/+/status"):
                status_cb = call.args[2]
        self.assertIsNotNone(status_cb)
        self.coord._register_worker("rig1", {"type": "pc"})
        msg = MagicMock()
        msg.topic = "gaming_assistant/rig1/status"
        msg.payload = b"online"
        status_cb(msg)
        self.assertTrue(self.coord.registered_workers["rig1"]["online"])
        msg.payload = b"offline"
        status_cb(msg)
        self.assertFalse(self.coord.registered_workers["rig1"]["online"])


# ---------------------------------------------------------------------------
# MqttRouter message handlers (driven through real subscriptions)
# ---------------------------------------------------------------------------

def _msg(topic, payload):
    m = MagicMock()
    m.topic = topic
    m.payload = payload
    return m


class TestMqttHandlers(unittest.TestCase):
    def setUp(self):
        self.coord, self.hass = _make_coord()
        _MQTT.async_subscribe.reset_mock()
        _run(self.coord._subscribe_topics())
        # subscribe_topics registers exactly 8 handlers in a fixed order;
        # index them by the topic they were bound to.
        self.cb = {
            call.args[1]: call.args[2]
            for call in _MQTT.async_subscribe.await_args_list
        }

    def test_subscribes_to_all_topics(self):
        self.assertEqual(len(self.cb), 8)

    def test_tip_handler(self):
        self.cb[MQTT_TIP_TOPIC](_msg(MQTT_TIP_TOPIC, b"Use cover"))
        self.assertEqual(self.coord.tip, "Use cover")

    def test_mode_handler(self):
        self.cb[MQTT_MODE_TOPIC](_msg(MQTT_MODE_TOPIC, b"on"))
        self.assertTrue(self.coord.gaming_mode)
        self.cb[MQTT_MODE_TOPIC](_msg(MQTT_MODE_TOPIC, b"off"))
        self.assertFalse(self.coord.gaming_mode)

    def test_status_handler(self):
        self.cb[MQTT_STATUS_TOPIC](_msg(MQTT_STATUS_TOPIC, b"analyzing"))
        self.assertEqual(self.coord.status, "analyzing")

    def test_image_handler_records_and_registers(self):
        self.cb[MQTT_IMAGE_TOPIC](
            _msg("gaming_assistant/rig1/image", b"jpegbytes")
        )
        self.assertEqual(self.coord.last_image_bytes, b"jpegbytes")
        self.assertEqual(self.coord.last_image_client_id, "rig1")
        self.assertIn("rig1", self.coord.registered_workers)

    def test_meta_handler_sets_game(self):
        self.cb[MQTT_META_TOPIC](
            _msg("gaming_assistant/rig1/meta", b'{"window_title": "Doom"}')
        )
        self.assertEqual(self.coord.current_game, "Doom")
        self.assertIn("rig1", self.coord.registered_workers)

    def test_meta_handler_ignores_garbage(self):
        # Invalid JSON must not raise out of the callback.
        self.cb[MQTT_META_TOPIC](_msg("gaming_assistant/rig1/meta", b"not-json"))

    def test_register_handler(self):
        self.cb[MQTT_WORKER_REGISTER_TOPIC](
            _msg("gaming_assistant/rig1/register", b'{"type": "console"}')
        )
        self.assertEqual(self.coord.registered_workers["rig1"]["type"], "console")

    def test_detections_handler_feeds_game_state(self):
        self.coord._current_game = "Doom"
        self.cb[MQTT_DETECTIONS_TOPIC](
            _msg(
                "gaming_assistant/yolo1/detections",
                b'{"detections": [{"class": "enemy", "confidence": 0.9}]}',
            )
        )
        current = self.coord.game_state_manager.get_current("Doom")
        self.assertEqual(current.get("yolo_top_object"), "enemy")

    def test_yolo_status_json_recorded(self):
        self.cb[MQTT_YOLO_STATUS_TOPIC](
            _msg(
                "gaming_assistant/yolo1/status",
                b'{"status": "ready", "model": "yolov8s", "backend": "cuda"}',
            )
        )
        self.assertEqual(self.coord.yolo_workers["yolo1"]["status"], "ready")


# ---------------------------------------------------------------------------
# Camera watcher capture loop
# ---------------------------------------------------------------------------

class TestCameraLoop(unittest.TestCase):
    def setUp(self):
        self.coord, self.hass = _make_coord()

    def test_loop_captures_one_frame_then_stops(self):
        ev = asyncio.Event()

        async def fake_get_image(hass, entity_id):
            ev.set()  # make the post-capture wait return immediately
            return SimpleNamespace(content=b"frame-bytes")

        _CAMERA.async_get_image = fake_get_image
        _run(self.coord._camera_watcher._watch_loop(
            "camera.tv", "Doom", "console", 1, ev
        ))
        self.assertEqual(self.coord.last_image_bytes, b"frame-bytes")
        self.assertIn("camera_tv", self.coord._client_metadata)
        self.assertEqual(
            self.coord._client_metadata["camera_tv"]["window_title"], "Doom"
        )

    def test_loop_stops_after_max_consecutive_errors(self):
        old = camera_watcher.MAX_CONSECUTIVE_ERRORS
        camera_watcher.MAX_CONSECUTIVE_ERRORS = 1
        try:
            cw = self.coord._camera_watcher
            cw._watchers["camera.tv"] = {"task": MagicMock()}
            self.coord._gaming_mode = True

            async def always_fail(hass, entity_id):
                raise RuntimeError("camera offline")

            _CAMERA.async_get_image = always_fail
            _run(cw._watch_loop("camera.tv", "", "console", 1, asyncio.Event()))
            self.assertNotIn("camera.tv", cw._watchers)
            self.assertFalse(self.coord.gaming_mode)
        finally:
            camera_watcher.MAX_CONSECUTIVE_ERRORS = old


# ---------------------------------------------------------------------------
# ClientRegistry inactivity handling
# ---------------------------------------------------------------------------

class TestClientInactivity(unittest.TestCase):
    def setUp(self):
        self.coord, self.hass = _make_coord()

    def test_inactive_client_disables_gaming_mode(self):
        self.coord._touch_client("rig1", {"window_title": "Doom"})
        self.coord._gaming_mode = True
        reg = self.coord._client_registry
        # Force last-seen far in the past so the age guard lets it through.
        reg.clients["rig1"]["last_seen_ts"] = 0
        _run(reg._handle_inactive("rig1"))
        self.assertFalse(self.coord.gaming_mode)

    def test_inactive_kept_alive_by_camera_watcher(self):
        self.coord._touch_client("rig1", {"window_title": "Doom"})
        self.coord._gaming_mode = True
        reg = self.coord._client_registry
        reg.clients["rig1"]["last_seen_ts"] = 0
        self.coord._camera_watcher._watchers["camera.tv"] = {"task": MagicMock()}
        _run(reg._handle_inactive("rig1"))
        self.assertTrue(self.coord.gaming_mode)

    def test_recent_client_not_marked_inactive(self):
        self.coord._touch_client("rig1", {"window_title": "Doom"})
        self.coord._gaming_mode = True
        # last_seen_ts is "now" → age < threshold → handler bails out early.
        _run(self.coord._client_registry._handle_inactive("rig1"))
        self.assertTrue(self.coord.gaming_mode)


# ---------------------------------------------------------------------------
# MqttRouter setup (retry / connection state)
# ---------------------------------------------------------------------------

class TestMqttSetup(unittest.TestCase):
    def setUp(self):
        self.coord, self.hass = _make_coord()

    def tearDown(self):
        # Never let a side_effect leak into other tests that subscribe.
        _MQTT.async_subscribe.side_effect = None

    def test_async_setup_connects(self):
        _MQTT.async_subscribe.side_effect = None
        _run(self.coord.async_setup_mqtt())
        self.assertTrue(self.coord.mqtt_connected)

    def test_async_setup_gives_up_after_retries(self):
        # Read the globals of the *actual* subscribe_topics function so that
        # both the exception class and the mqtt mock match what the running
        # router code captured at import time (test_init_services.py reloads
        # stubs and custom_components, so sys.modules may hold a different
        # copy than the class used by this coordinator instance).
        g = self.coord._mqtt_router.subscribe_topics.__globals__
        HAError = g["HomeAssistantError"]
        actual_mqtt = g["mqtt"]
        with patch.object(actual_mqtt, "async_subscribe", side_effect=HAError("no broker")):
            with patch("asyncio.sleep", new=AsyncMock()):
                _run(self.coord.async_setup_mqtt())
        self.assertFalse(self.coord.mqtt_connected)


# ---------------------------------------------------------------------------
# Async lifecycle + events
# ---------------------------------------------------------------------------

class TestAsyncLifecycle(unittest.TestCase):
    def setUp(self):
        self.coord, self.hass = _make_coord()

    def test_start_stop_assistant(self):
        _run(self.coord.async_start_assistant())
        self.assertTrue(self.coord.gaming_mode)
        _run(self.coord.async_stop_assistant())
        self.assertFalse(self.coord.gaming_mode)

    def test_publish_action_uses_mqtt(self):
        _MQTT.async_publish.reset_mock()
        _run(self.coord.async_publish_action("rig1", {"action": "button", "button": "A"}))
        self.assertTrue(_MQTT.async_publish.await_count >= 1)

    def test_send_yolo_command_uses_mqtt(self):
        _MQTT.async_publish.reset_mock()
        _run(self.coord.async_send_yolo_command("restart", model="yolov8s"))
        self.assertTrue(_MQTT.async_publish.await_count >= 1)

    def test_fire_new_tip_event(self):
        self.coord._fire_new_tip_event("tip", "Doom", "rig1")
        fired = self.hass.bus.fired(EVENT_NEW_TIP)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["tip"], "tip")

    def test_session_tracking_and_end(self):
        self.coord.session_tracker.track_tip("t1", "Doom")
        self.coord.session_tracker.track_tip("t2", "Doom")
        _run(self.coord.session_tracker.async_end_session())
        fired = self.hass.bus.fired(EVENT_SESSION_ENDED)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["game"], "Doom")
        self.assertEqual(fired[0]["tip_count"], 2)

    def test_summarize_session_uses_backend(self):
        self.coord._image_processor._call_ollama_text = AsyncMock(
            return_value="You played aggressively."
        )
        self.coord.session_tracker._session_tips = ["a", "b", "c"]
        self.coord.session_tracker._session_game = "Doom"
        out = _run(self.coord.async_summarize_session())
        self.assertEqual(out, "You played aggressively.")
        self.assertEqual(self.coord.last_summary, "You played aggressively.")

    def test_fetch_available_models(self):
        self.coord._llm_backend.list_models = AsyncMock(return_value=["m1", "m2"])
        models = _run(self.coord.async_fetch_available_models())
        self.assertEqual(models, ["m1", "m2"])

    def test_process_image_happy_path(self):
        self.coord._image_processor.process = AsyncMock(return_value="Dodge now.")
        self.coord._client_metadata["rig1"] = {"window_title": "Doom"}
        _run(self.coord._process_image("rig1", b"frame-bytes"))
        self.assertEqual(self.coord.tip, "Dodge now.")
        self.assertEqual(self.coord.status, "idle")
        self.assertEqual(self.coord.tip_count, 1)
        self.assertTrue(self.hass.bus.fired(EVENT_NEW_TIP))

    def test_process_image_empty_tip(self):
        self.coord._image_processor.process = AsyncMock(return_value="")
        self.coord._client_metadata["rig1"] = {"window_title": "Doom"}
        _run(self.coord._process_image("rig1", b"frame"))
        self.assertEqual(self.coord.tip, "Waiting for tips...")  # unchanged
        self.assertEqual(self.coord.frames_processed, 1)

    def test_process_manual_image(self):
        self.coord._image_processor.process = AsyncMock(return_value="manual tip")
        out = _run(self.coord.async_process_manual_image(b"frame", "Doom", "pc"))
        self.assertEqual(out, "manual tip")

    def test_async_ask(self):
        self.coord._image_processor.ask = AsyncMock(return_value="Use the rocket launcher.")
        out = _run(self.coord.async_ask("What weapon?", image_bytes=None, game_hint="Doom"))
        self.assertEqual(out, "Use the rocket launcher.")
        self.assertEqual(self.coord.tip, "Use the rocket launcher.")
        self.assertTrue(self.hass.bus.fired(EVENT_NEW_TIP))

    def test_persist_and_load_state_roundtrip(self):
        self.coord.game_state_manager.update("Doom", {"health": 50})
        _run(self.coord._persist_game_state("Doom"))
        # Drop only the in-memory state (keep the file on disk), then lazy-load.
        self.coord.game_state_manager._states.pop("Doom", None)
        _run(self.coord._ensure_state_loaded("Doom"))
        self.assertIsNotNone(self.coord.game_state_manager.get_current("Doom"))


# ---------------------------------------------------------------------------
# Agent Mode safety wiring (behavioural)
# ---------------------------------------------------------------------------

class TestAgentModeWiring(unittest.TestCase):
    def setUp(self):
        self.coord, self.hass = _make_coord()
        self.coord.set_agent_mode(True)

    def test_published_action_counts_and_event(self):
        _MQTT.async_publish.reset_mock()
        self.coord._image_processor.generate_action = AsyncMock(
            return_value={"action": "button", "button": "A"}
        )
        _run(self.coord._maybe_publish_agent_action("rig1", b"frame", "Doom"))
        self.assertEqual(self.coord.agent_actions_published, 1)
        self.assertEqual(self.coord.agent_last_action_status, "published")
        self.assertTrue(self.hass.bus.fired(EVENT_AGENT_ACTION))

    def test_rate_limit_blocks_second_action(self):
        self.coord._image_processor.generate_action = AsyncMock(
            return_value={"action": "button", "button": "A"}
        )
        _run(self.coord._maybe_publish_agent_action("rig1", b"f", "Doom"))
        _run(self.coord._maybe_publish_agent_action("rig1", b"f", "Doom"))
        # Second call is within the min interval -> still only one published.
        self.assertEqual(self.coord.agent_actions_published, 1)

    def test_no_op_records_status(self):
        self.coord._image_processor.generate_action = AsyncMock(return_value=None)
        _run(self.coord._maybe_publish_agent_action("rig1", b"f", "Doom"))
        self.assertEqual(self.coord.agent_last_action_status, "no_op")
        self.assertEqual(self.coord.agent_actions_published, 0)

    def test_consecutive_failures_auto_disable(self):
        self.coord._image_processor.generate_action = AsyncMock(
            side_effect=RuntimeError("backend down")
        )
        for _ in range(AGENT_MAX_CONSECUTIVE_FAILURES):
            _run(self.coord._maybe_publish_agent_action("rig1", b"f", "Doom"))
        self.assertFalse(self.coord.agent_mode)  # auto-disabled
        statuses = [d["status"] for d in self.hass.bus.fired(EVENT_AGENT_ACTION)]
        self.assertIn("auto_disabled", statuses)


if __name__ == "__main__":
    unittest.main()
