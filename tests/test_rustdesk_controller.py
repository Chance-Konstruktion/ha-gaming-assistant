"""
Unit tests for the RustDesk controller (worker/rustdesk_controller.py, GA-119).

RustDesk itself is never started: the launcher is a mock, so the tests check
exactly which command line would run and what goes back to Home Assistant.
"""

import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from worker.rustdesk_controller import (
    MODES,
    RemoteController,
    find_rustdesk,
    main,
    parse_peer_args,
    parse_peers,
)

PEERS = {
    "tablet": {"id": "123456789"},
    "laptop": {"id": "987654321", "password": "s3cret"},
}


class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class TestPeers(unittest.TestCase):
    def test_ids_as_rustdesk_shows_them(self):
        peers = parse_peers({"Tablet": {"id": "123 456 789"}, "tv": 555666777})
        self.assertEqual(peers, {"tablet": {"id": "123456789"}, "tv": {"id": "555666777"}})

    def test_password_is_kept_only_when_given(self):
        peers = parse_peers({"laptop": {"id": "1", "password": "pw"}, "pc": {"id": "2"}})
        self.assertEqual(peers["laptop"]["password"], "pw")
        self.assertNotIn("password", peers["pc"])

    def test_malformed_peers(self):
        for data in ({}, [], {"tablet": {}}, {"tablet": ["x"]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_peers(data)

    def test_peer_args(self):
        self.assertEqual(parse_peer_args(["tv=111 222 333"]), {"tv": {"id": "111222333"}})
        self.assertEqual(parse_peer_args([]), {})
        with self.assertRaises(ValueError):
            parse_peer_args(["no-equals-sign"])


class TestRemoteController(unittest.TestCase):
    def setUp(self):
        self.launch = MagicMock()
        self.clock = _Clock()
        self.controller = RemoteController(
            "/opt/rustdesk", parse_peers(PEERS), client_id="gaming-pc",
            launch=self.launch, clock=self.clock,
        )

    def test_opens_a_session(self):
        result = self.controller.handle(json.dumps({"peer": "tablet"}))
        self.assertEqual(result["result"], "opened")
        self.assertEqual((result["peer"], result["mode"]), ("tablet", "control"))
        args = self.launch.call_args.args[0]
        self.assertEqual(args, ["/opt/rustdesk", "--connect", "123456789"])
        # Detached from this worker's console.
        self.assertIs(self.launch.call_args.kwargs["stdout"], subprocess.DEVNULL)

    def test_password_goes_to_rustdesk_but_never_back(self):
        result = self.controller.handle(b'{"peer": "Laptop", "mode": "file_transfer"}')
        args = self.launch.call_args.args[0]
        self.assertEqual(args, ["/opt/rustdesk", MODES["file_transfer"], "987654321",
                                "--password", "s3cret"])
        published = json.dumps(result)
        self.assertNotIn("s3cret", published)
        self.assertNotIn("987654321", published)

    def test_plain_peer_name(self):
        self.assertEqual(self.controller.handle("tablet")["result"], "opened")

    def test_rejects_what_is_not_configured(self):
        for payload in ("", "{not json", "[1]", '{"mode": "control"}', "printer",
                        '{"peer": "tablet", "mode": "shell"}'):
            with self.subTest(payload=payload):
                self.assertEqual(self.controller.handle(payload)["result"], "rejected")
        self.launch.assert_not_called()

    def test_cooldown_per_peer(self):
        self.controller.handle("tablet")
        self.clock.now += 5
        self.assertEqual(self.controller.handle("tablet")["result"], "skipped")
        self.assertEqual(self.controller.handle("laptop")["result"], "opened")
        self.clock.now += 6
        self.assertEqual(self.controller.handle("tablet")["result"], "opened")
        self.assertEqual(self.launch.call_count, 3)

    def test_missing_client_and_start_failure(self):
        missing = RemoteController(None, parse_peers(PEERS), launch=self.launch)
        self.assertEqual(missing.handle("tablet")["result"], "error")
        self.launch.side_effect = FileNotFoundError(2, "No such file")
        result = self.controller.handle("tablet")
        self.assertEqual(result["result"], "error")
        self.assertIn("No such file", result["reason"])
        # A failed start does not count against the cooldown.
        self.launch.side_effect = None
        self.assertEqual(self.controller.handle("tablet")["result"], "opened")


class TestFindAndMain(unittest.TestCase):
    def test_find_on_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = os.path.join(tmp, "RustDesk", "rustdesk.exe")
            os.makedirs(os.path.dirname(exe))
            open(exe, "w").close()
            with patch("worker.rustdesk_controller.platform.system", return_value="Windows"), \
                    patch("worker.rustdesk_controller.shutil.which", return_value=None), \
                    patch.dict(os.environ, {"ProgramFiles": tmp}):
                self.assertEqual(find_rustdesk(), exe)

    def test_not_found(self):
        with patch("worker.rustdesk_controller.platform.system", return_value="Linux"), \
                patch("worker.rustdesk_controller.shutil.which", return_value=None):
            self.assertIsNone(find_rustdesk())

    def test_main_needs_peers(self):
        self.assertEqual(main(["--client-id", "pc"]), 1)

    def test_main_rejects_a_broken_peers_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "peers.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"tablet": {}}')
            self.assertEqual(main(["--peers", path]), 1)


if __name__ == "__main__":
    unittest.main()
