"""
Unit tests for the companion listener (worker/companion_listener.py, GA-121).

No key is ever pressed: the Windows API, xdotool, osascript and adb are all
mocks, so the tests check exactly what would run on each platform.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from worker.companion_listener import (
    BUILTIN_COMMANDS,
    KEYS,
    CompanionListener,
    KeyPresser,
    main,
    parse_commands,
)


class _Clock:
    def __init__(self):
        self.now = 50.0

    def __call__(self):
        return self.now


class TestCommands(unittest.TestCase):
    def test_builtins_are_media_keys(self):
        self.assertEqual(BUILTIN_COMMANDS["pause"], {"key": "play_pause"})
        for name in ("play_pause", "mute", "volume_up", "next"):
            self.assertIn(BUILTIN_COMMANDS[name]["key"], KEYS)

    def test_own_commands(self):
        commands = parse_commands({
            "Game_Pause": {"key": "Escape"},
            "tablet_pause": {"adb": "keycode_media_pause", "serial": "R58N1"},
        })
        self.assertEqual(commands["game_pause"], {"key": "escape"})
        self.assertEqual(commands["tablet_pause"], {"adb": "KEYCODE_MEDIA_PAUSE", "serial": "R58N1"})

    def test_bad_commands(self):
        for data in ([], {"x": "escape"}, {"x": {"key": "ctrl+alt+del"}},
                     {"x": {"adb": "reboot"}}, {"x": {"shell": "rm -rf /"}}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_commands(data)


class TestKeyPresser(unittest.TestCase):
    def test_windows_media_key_is_extended(self):
        user32 = MagicMock()
        KeyPresser("Windows", user32=user32).press("play_pause")
        down, up = user32.keybd_event.call_args_list
        self.assertEqual(down.args, (0xB3, 0, 0x1, 0))
        self.assertEqual(up.args, (0xB3, 0, 0x3, 0))

    def test_windows_plain_key(self):
        user32 = MagicMock()
        KeyPresser("Windows", user32=user32).press("escape")
        self.assertEqual(user32.keybd_event.call_args_list[0].args, (0x1B, 0, 0x0, 0))
        KeyPresser("Windows", user32=user32).press("f5")
        self.assertEqual(user32.keybd_event.call_args_list[2].args[0], 0x74)  # VK_F5

    def test_linux_uses_xdotool(self):
        run = MagicMock()
        with patch("worker.companion_listener.shutil.which", return_value="/usr/bin/xdotool"):
            KeyPresser("Linux", run=run).press("mute")
        self.assertEqual(run.call_args.args[0], ["xdotool", "key", "XF86AudioMute"])
        with patch("worker.companion_listener.shutil.which", return_value=None), \
                self.assertRaises(RuntimeError):
            KeyPresser("Linux", run=run).press("mute")

    def test_macos_plain_keys_only(self):
        run = MagicMock()
        KeyPresser("Darwin", run=run).press("space")
        self.assertIn("key code 49", run.call_args.args[0][2])
        with self.assertRaises(RuntimeError):
            KeyPresser("Darwin", run=run).press("play_pause")


class TestCompanionListener(unittest.TestCase):
    def setUp(self):
        self.presser = MagicMock()
        self.run = MagicMock()
        self.clock = _Clock()
        commands = dict(BUILTIN_COMMANDS)
        commands.update(parse_commands({
            "game_pause": {"key": "escape"},
            "tablet_pause": {"adb": "KEYCODE_MEDIA_PAUSE", "serial": "R58N1"},
            "tv_home": {"adb": "KEYCODE_HOME"},
        }))
        self.listener = CompanionListener(
            commands, client_id="gaming-pc", presser=self.presser, run=self.run,
            clock=self.clock,
        )

    def _send(self, payload):
        self.clock.now += 1
        return self.listener.handle(payload)

    def test_plain_and_json_payloads(self):
        self.assertEqual(self._send("pause")["result"], "done")
        self.assertEqual(self._send(b'{"command": "Game_Pause"}')["result"], "done")
        self.assertEqual([c.args[0] for c in self.presser.press.call_args_list],
                         ["play_pause", "escape"])

    def test_adb_keyevent(self):
        self._send("tablet_pause")
        self.assertEqual(
            self.run.call_args.args[0],
            ["adb", "-s", "R58N1", "shell", "input", "keyevent", "KEYCODE_MEDIA_PAUSE"],
        )
        self._send("tv_home")
        self.assertEqual(self.run.call_args.args[0][:2], ["adb", "shell"])

    def test_only_known_commands_run(self):
        for payload in ("", "{}", "{oops", "[1]", "format_disk", '{"command": "escape"}'):
            with self.subTest(payload=payload):
                self.assertEqual(self._send(payload)["result"], "rejected")
        self.presser.press.assert_not_called()

    def test_flood_protection(self):
        self.assertEqual(self._send("pause")["result"], "done")
        self.clock.now += 0.1
        self.assertEqual(self.listener.handle("pause")["result"], "skipped")
        self.assertEqual(self.presser.press.call_count, 1)

    def test_dry_run_presses_nothing(self):
        self.listener.dry_run = True
        result = self._send("game_pause")
        self.assertEqual(result["result"], "dry_run")
        self.assertEqual(result["action"], {"key": "escape"})
        self.presser.press.assert_not_called()

    def test_failures_are_reported(self):
        self.presser.press.side_effect = RuntimeError("xdotool is not installed")
        result = self._send("pause")
        self.assertEqual(result["result"], "error")
        self.assertIn("xdotool", result["reason"])
        self.run.side_effect = FileNotFoundError(2, "adb not found")
        self.assertEqual(self._send("tablet_pause")["result"], "error")


class TestMain(unittest.TestCase):
    def test_broken_commands_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "commands.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"x": {"key": "nope"}}, fh)
            self.assertEqual(main(["--commands", path]), 1)


if __name__ == "__main__":
    unittest.main()
