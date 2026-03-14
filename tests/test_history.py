"""Unit tests for the JSONL-based HistoryManager."""

import asyncio
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

# Stub homeassistant before importing our modules
_HA_MODULES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.mqtt",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
]
for mod in _HA_MODULES:
    sys.modules.setdefault(mod, MagicMock())

from custom_components.gaming_assistant.history import HistoryManager


def _run(coro):
    """Helper to run async code in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestHistoryJSONL(unittest.TestCase):
    """Tests for JSONL-based history storage."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.mgr = HistoryManager(self._tmpdir)

    def test_add_and_get_recent(self):
        _run(self.mgr.add_entry("zelda", "client1", "hash1", "Use the shield"))
        _run(self.mgr.add_entry("zelda", "client1", "hash2", "Dodge roll"))
        recent = _run(self.mgr.get_recent("zelda", 5))
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["tip"], "Use the shield")
        self.assertEqual(recent[1]["tip"], "Dodge roll")

    def test_get_recent_limits(self):
        for i in range(10):
            _run(self.mgr.add_entry("game", "c1", f"h{i}", f"Tip {i}"))
        recent = _run(self.mgr.get_recent("game", 3))
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[0]["tip"], "Tip 7")

    def test_jsonl_file_format(self):
        _run(self.mgr.add_entry("doom", "c1", "h1", "BFG is strong"))
        path = self.mgr._file_path("doom")
        self.assertTrue(path.exists())
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["tip"], "BFG is strong")
        self.assertEqual(entry["image_hash"], "h1")

    def test_append_only(self):
        """Each add_entry appends a line, doesn't rewrite the file."""
        _run(self.mgr.add_entry("game", "c1", "h1", "Tip 1"))
        _run(self.mgr.add_entry("game", "c1", "h2", "Tip 2"))
        path = self.mgr._file_path("game")
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 2)

    def test_is_duplicate_image(self):
        _run(self.mgr.add_entry("game", "c1", "dupe_hash", "Tip"))
        self.assertTrue(_run(self.mgr.is_duplicate_image("dupe_hash", "game")))
        self.assertFalse(_run(self.mgr.is_duplicate_image("other_hash", "game")))

    def test_clear_specific_game(self):
        _run(self.mgr.add_entry("game1", "c1", "h1", "Tip 1"))
        _run(self.mgr.add_entry("game2", "c1", "h2", "Tip 2"))
        _run(self.mgr.clear("game1"))
        self.assertFalse(self.mgr._file_path("game1").exists())
        self.assertTrue(self.mgr._file_path("game2").exists())

    def test_clear_all(self):
        _run(self.mgr.add_entry("game1", "c1", "h1", "Tip 1"))
        _run(self.mgr.add_entry("game2", "c1", "h2", "Tip 2"))
        _run(self.mgr.clear())
        self.assertEqual(len(list(self.mgr._base_path.glob("*.jsonl"))), 0)

    def test_format_for_prompt(self):
        entries = [{"tip": "First"}, {"tip": "Second"}]
        result = HistoryManager.format_for_prompt(entries)
        self.assertIn("1. First", result)
        self.assertIn("2. Second", result)
        self.assertIn("Do NOT repeat", result)

    def test_format_for_prompt_empty(self):
        result = HistoryManager.format_for_prompt([])
        self.assertEqual(result, "")

    def test_corrupt_line_skipped(self):
        """Corrupt JSON lines are skipped gracefully."""
        self.mgr._ensure_dir()
        path = self.mgr._file_path("corrupt")
        path.write_text(
            '{"tip": "Good"}\n{broken json\n{"tip": "Also good"}\n',
            encoding="utf-8",
        )
        # Clear cache to force reload
        self.mgr._cache.clear()
        recent = _run(self.mgr.get_recent("corrupt", 10))
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["tip"], "Good")
        self.assertEqual(recent[1]["tip"], "Also good")


class TestHistoryCleanup(unittest.TestCase):
    """Tests for the cleanup mechanism."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.mgr = HistoryManager(self._tmpdir, max_age_days=30)

    def test_cleanup_removes_old_entries(self):
        self.mgr._ensure_dir()
        path = self.mgr._file_path("old_game")

        old_ts = (datetime.now() - timedelta(days=60)).isoformat(timespec="seconds")
        new_ts = datetime.now().isoformat(timespec="seconds")

        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": old_ts, "tip": "Old tip", "image_hash": "h1", "client_id": "c1"}) + "\n")
            f.write(json.dumps({"timestamp": new_ts, "tip": "New tip", "image_hash": "h2", "client_id": "c1"}) + "\n")

        removed = _run(self.mgr.cleanup())
        self.assertEqual(removed, 1)

        # File should only contain the new entry
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 1)
        self.assertIn("New tip", lines[0])

    def test_cleanup_keeps_recent_entries(self):
        _run(self.mgr.add_entry("game", "c1", "h1", "Recent tip"))
        removed = _run(self.mgr.cleanup())
        self.assertEqual(removed, 0)
        recent = _run(self.mgr.get_recent("game", 10))
        self.assertEqual(len(recent), 1)

    def test_cleanup_custom_max_age(self):
        self.mgr._ensure_dir()
        path = self.mgr._file_path("test")

        ts_5_days_ago = (datetime.now() - timedelta(days=5)).isoformat(timespec="seconds")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": ts_5_days_ago, "tip": "5 days old", "image_hash": "h1", "client_id": "c1"}) + "\n")

        # With max_age_days=3, the 5-day-old entry should be removed
        removed = _run(self.mgr.cleanup(max_age_days=3))
        self.assertEqual(removed, 1)

        # With max_age_days=10, it would be kept - but file was already cleaned
        # Re-add and test
        self.mgr._cache.clear()
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": ts_5_days_ago, "tip": "5 days old", "image_hash": "h1", "client_id": "c1"}) + "\n")
        removed = _run(self.mgr.cleanup(max_age_days=10))
        self.assertEqual(removed, 0)


if __name__ == "__main__":
    unittest.main()
