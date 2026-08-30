"""
Unit tests for the Agent Mode executor (worker/agent_executor.py).

These tests never require ``vgamepad`` — the controller is mocked, so the
validation/dispatch/audit logic is exercised on any platform.
"""

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from worker.agent_executor import (
    ACTION_TOPIC_TEMPLATE,
    VALID_BUTTONS,
    AgentExecutor,
    GamepadController,
    make_file_audit,
    parse_action,
)


# ===========================================================================
# parse_action — schema + whitelist validation
# ===========================================================================

class TestParseAction(unittest.TestCase):
    def test_valid_tap_button(self):
        action = parse_action(
            '{"action": "tap_button", "button": "a", "duration_ms": 80}'
        )
        self.assertEqual(action["action"], "tap_button")
        self.assertEqual(action["button"], "A")  # uppercased
        self.assertEqual(action["duration_ms"], 80)

    def test_valid_move_stick(self):
        action = parse_action(
            '{"action": "move_stick", "stick": "left", "x": 0.5, "y": -0.3}'
        )
        self.assertEqual(action["stick"], "left")
        self.assertAlmostEqual(action["x"], 0.5)

    def test_valid_wait_and_no_op(self):
        self.assertEqual(parse_action('{"action": "wait", "duration_ms": 200}')["action"], "wait")
        self.assertEqual(parse_action('{"action": "no_op"}')["action"], "no_op")

    def test_strips_markdown_fences(self):
        action = parse_action('```json\n{"action": "no_op"}\n```')
        self.assertEqual(action["action"], "no_op")

    def test_strips_unknown_keys(self):
        action = parse_action('{"action": "no_op", "evil": "rm -rf", "reason": "ok"}')
        self.assertNotIn("evil", action)
        self.assertIn("reason", action)

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            parse_action("")
        with self.assertRaises(ValueError):
            parse_action("   ")

    def test_rejects_non_json(self):
        with self.assertRaises(ValueError):
            parse_action("press A please")

    def test_rejects_non_object(self):
        with self.assertRaises(ValueError):
            parse_action("[1, 2, 3]")

    def test_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            parse_action('{"action": "format_disk"}')

    def test_rejects_missing_button(self):
        with self.assertRaises(ValueError):
            parse_action('{"action": "tap_button"}')

    def test_rejects_unknown_button(self):
        with self.assertRaises(ValueError):
            parse_action('{"action": "tap_button", "button": "SELECT"}')

    def test_enforces_button_whitelist(self):
        # START is a valid button but not in the provided whitelist.
        with self.assertRaises(ValueError):
            parse_action(
                '{"action": "tap_button", "button": "START"}',
                allowed_buttons=["A", "B"],
            )
        # A is allowed.
        self.assertEqual(
            parse_action(
                '{"action": "tap_button", "button": "A"}',
                allowed_buttons=["A", "B"],
            )["button"],
            "A",
        )

    def test_rejects_bad_stick(self):
        with self.assertRaises(ValueError):
            parse_action('{"action": "move_stick", "stick": "middle"}')

    def test_rejects_out_of_range_axis(self):
        with self.assertRaises(ValueError):
            parse_action('{"action": "move_stick", "stick": "left", "x": 2.0}')

    def test_rejects_bad_duration(self):
        with self.assertRaises(ValueError):
            parse_action('{"action": "wait", "duration_ms": 99999}')
        with self.assertRaises(ValueError):
            parse_action('{"action": "wait", "duration_ms": -5}')

    def test_rejects_bool_duration(self):
        # True is an int in Python — must still be rejected.
        with self.assertRaises(ValueError):
            parse_action('{"action": "wait", "duration_ms": true}')


# ===========================================================================
# AgentExecutor.execute — dispatch to the controller
# ===========================================================================

class TestExecutorDispatch(unittest.TestCase):
    def setUp(self):
        self.controller = MagicMock()
        self.sleeps = []
        self.executor = AgentExecutor(
            self.controller,
            sleep=self.sleeps.append,
        )

    def test_tap_button(self):
        self.executor.execute({"action": "tap_button", "button": "A", "duration_ms": 0})
        self.controller.press.assert_called_once_with("A")
        self.controller.release.assert_called_once_with("A")
        self.assertEqual(self.controller.update.call_count, 2)

    def test_press_then_release(self):
        self.executor.execute({"action": "press_button", "button": "B"})
        self.controller.press.assert_called_once_with("B")
        self.controller.release.assert_not_called()
        self.executor.execute({"action": "release_button", "button": "B"})
        self.controller.release.assert_called_once_with("B")

    def test_trigger_uses_analog_not_press(self):
        self.executor.execute({"action": "tap_button", "button": "LT", "duration_ms": 0})
        self.controller.press.assert_not_called()
        self.controller.trigger.assert_any_call("LT", 1.0)
        self.controller.trigger.assert_any_call("LT", 0.0)

    def test_move_stick(self):
        self.executor.execute(
            {"action": "move_stick", "stick": "right", "x": 0.5, "y": -0.25}
        )
        self.controller.stick.assert_called_once_with("right", 0.5, -0.25)
        self.controller.update.assert_called_once()

    def test_wait_sleeps(self):
        self.executor.execute({"action": "wait", "duration_ms": 200})
        self.assertEqual(self.sleeps, [0.2])
        self.controller.update.assert_not_called()

    def test_no_op_does_nothing(self):
        self.executor.execute({"action": "no_op"})
        self.controller.update.assert_not_called()
        self.controller.press.assert_not_called()

    def test_tap_uses_default_duration(self):
        executor = AgentExecutor(self.controller, default_tap_ms=120, sleep=self.sleeps.append)
        executor.execute({"action": "tap_button", "button": "A"})
        self.assertEqual(self.sleeps, [0.12])


# ===========================================================================
# AgentExecutor.handle — full pipeline + audit
# ===========================================================================

class TestExecutorHandle(unittest.TestCase):
    def setUp(self):
        self.controller = MagicMock()
        self.audit = []
        self.executor = AgentExecutor(
            self.controller,
            client_id="pc",
            audit=self.audit.append,
            sleep=lambda _s: None,
        )

    def test_executed_path_audited(self):
        entry = self.executor.handle('{"action": "tap_button", "button": "A", "duration_ms": 0}')
        self.assertEqual(entry["result"], "executed")
        self.assertEqual(self.audit[-1]["result"], "executed")
        self.controller.press.assert_called_once_with("A")

    def test_rejected_payload_not_executed(self):
        entry = self.executor.handle('not json')
        self.assertEqual(entry["result"], "rejected")
        self.assertIn("payload", entry)
        self.controller.press.assert_not_called()

    def test_accepts_bytes(self):
        entry = self.executor.handle(b'{"action": "no_op"}')
        self.assertEqual(entry["result"], "executed")

    def test_dry_run_skips_execution(self):
        executor = AgentExecutor(self.controller, dry_run=True, audit=self.audit.append)
        entry = executor.handle('{"action": "tap_button", "button": "A"}')
        self.assertEqual(entry["result"], "dry_run")
        self.controller.press.assert_not_called()

    def test_no_controller_forces_dry_run(self):
        executor = AgentExecutor(None, audit=self.audit.append)
        self.assertTrue(executor.dry_run)
        entry = executor.handle('{"action": "tap_button", "button": "A"}')
        self.assertEqual(entry["result"], "dry_run")

    def test_pause_skips_and_resets(self):
        self.executor.pause()
        self.controller.reset.assert_called_once()
        entry = self.executor.handle('{"action": "tap_button", "button": "A"}')
        self.assertEqual(entry["result"], "skipped")
        self.controller.press.assert_not_called()
        # Resume restores execution.
        self.executor.resume()
        entry = self.executor.handle('{"action": "no_op"}')
        self.assertEqual(entry["result"], "executed")

    def test_whitelist_rejects_disallowed_button(self):
        executor = AgentExecutor(
            self.controller,
            allowed_buttons=["A"],
            audit=self.audit.append,
            sleep=lambda _s: None,
        )
        entry = executor.handle('{"action": "tap_button", "button": "START"}')
        self.assertEqual(entry["result"], "rejected")
        self.controller.press.assert_not_called()


# ===========================================================================
# GamepadController — maps names to vgamepad calls (with a fake backend)
# ===========================================================================

class TestGamepadController(unittest.TestCase):
    def setUp(self):
        self.pad = MagicMock()
        # Fake XUSB_BUTTON enum: attribute name -> sentinel value.
        self.enum = SimpleNamespace(
            XUSB_GAMEPAD_A="A_ENUM",
            XUSB_GAMEPAD_START="START_ENUM",
        )
        self.ctrl = GamepadController(self.pad, self.enum)

    def test_press_maps_to_enum(self):
        self.ctrl.press("A")
        self.pad.press_button.assert_called_once_with(button="A_ENUM")

    def test_release_maps_to_enum(self):
        self.ctrl.release("START")
        self.pad.release_button.assert_called_once_with(button="START_ENUM")

    def test_trigger_left_and_right(self):
        self.ctrl.trigger("LT", 1.0)
        self.pad.left_trigger_float.assert_called_once_with(value_float=1.0)
        self.ctrl.trigger("RT", 0.0)
        self.pad.right_trigger_float.assert_called_once_with(value_float=0.0)

    def test_stick_left_and_right(self):
        self.ctrl.stick("left", 0.1, 0.2)
        self.pad.left_joystick_float.assert_called_once_with(x_value_float=0.1, y_value_float=0.2)
        self.ctrl.stick("right", -0.1, -0.2)
        self.pad.right_joystick_float.assert_called_once_with(x_value_float=-0.1, y_value_float=-0.2)

    def test_reset_and_update(self):
        self.ctrl.reset()
        self.pad.reset.assert_called_once()
        self.ctrl.update()
        self.pad.update.assert_called_once()


# ===========================================================================
# Audit log + topic conventions
# ===========================================================================

class TestAuditAndTopics(unittest.TestCase):
    def test_file_audit_writes_jsonl(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            audit = make_file_audit(path)
            audit({"result": "executed", "action": {"action": "no_op"}})
            audit({"result": "rejected", "reason": "bad"})
            with open(path, encoding="utf-8") as fh:
                lines = [json.loads(line) for line in fh if line.strip()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["result"], "executed")
            self.assertEqual(lines[1]["reason"], "bad")
        finally:
            os.remove(path)

    def test_action_topic_format(self):
        self.assertEqual(
            ACTION_TOPIC_TEMPLATE.format(client_id="gaming-pc"),
            "gaming_assistant/gaming-pc/action",
        )

    def test_button_set_matches_contract(self):
        # 12 digital buttons + 2 triggers = the 14 Xbox names in the schema.
        self.assertEqual(len(VALID_BUTTONS), 14)
        self.assertIn("DPAD_UP", VALID_BUTTONS)
        self.assertIn("LT", VALID_BUTTONS)


if __name__ == "__main__":
    unittest.main()
