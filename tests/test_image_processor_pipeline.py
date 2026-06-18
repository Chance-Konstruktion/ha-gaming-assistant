"""Behavioural tests for the ImageProcessor.process / ask pipelines.

Uses REAL history / spoiler / game-state managers (in a temp dir) and a mocked
LLM backend, so the full pipeline — dedup, prompt build, downscale/executor,
history persistence, and game-state extraction — runs for real.
"""

import asyncio
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

_HA_MODULES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.mqtt",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.event",
]
for _mod in _HA_MODULES:
    sys.modules.setdefault(_mod, MagicMock())

from custom_components.gaming_assistant.history import HistoryManager
from custom_components.gaming_assistant.spoiler import SpoilerManager
from custom_components.gaming_assistant.game_state import GameStateManager
from custom_components.gaming_assistant.image_processor import ImageProcessor


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_processor(text="Dodge the boss attack now."):
    tmp = tempfile.mkdtemp()
    history = HistoryManager(tmp)
    spoiler = SpoilerManager(f"{tmp}/spoiler.json")
    spoiler.initialize("medium")
    game_state = GameStateManager(tmp)
    proc = ImageProcessor(
        ollama_host="http://localhost:11434",
        model="test-model",
        history_manager=history,
        spoiler_manager=spoiler,
        game_state_manager=game_state,
    )
    proc._backend = MagicMock()
    proc._backend.generate = AsyncMock(return_value=SimpleNamespace(text=text))
    proc._backend.generate_text = AsyncMock(
        return_value=SimpleNamespace(text=text)
    )
    return proc


class TestProcessPipeline(unittest.TestCase):
    def test_returns_tip_and_persists(self):
        proc = _make_processor("Aim for the weak point.")
        tip = _run(proc.process(b"frame-A", "rig1", {"window_title": "Doom"}))
        self.assertEqual(tip, "Aim for the weak point.")
        # Tip is stored in history for the game.
        recent = _run(proc._history.get_recent("Doom", 5))
        self.assertEqual(recent[-1]["tip"], "Aim for the weak point.")
        # Backend was actually called with the prompt + image.
        self.assertTrue(proc._backend.generate.await_count >= 1)

    def test_duplicate_image_is_skipped(self):
        proc = _make_processor("First tip.")
        first = _run(proc.process(b"same-bytes", "rig1", {"window_title": "Doom"}))
        self.assertEqual(first, "First tip.")
        # Same bytes within the dedup window -> empty (no second LLM call).
        proc._backend.generate.reset_mock()
        second = _run(proc.process(b"same-bytes", "rig1", {"window_title": "Doom"}))
        self.assertEqual(second, "")
        self.assertEqual(proc._backend.generate.await_count, 0)

    def test_empty_response_returns_empty(self):
        proc = _make_processor("")
        tip = _run(proc.process(b"frame-X", "rig1", {"window_title": "Doom"}))
        self.assertEqual(tip, "")

    def test_observations_extracted_into_game_state(self):
        proc = _make_processor("Your health is 40, keep distance.")
        _run(proc.process(b"frame-hp", "rig1", {"window_title": "Doom"}))
        current = proc._game_state.get_current("Doom")
        self.assertIsNotNone(current)
        self.assertEqual(current.get("health"), 40)

    def test_measured_signals_merged_into_game_state(self):
        # Tier 1 measured signals are passed in and must land in the single
        # per-frame snapshot alongside the tip-scraped observations.
        proc = _make_processor("Your health is 40.")
        _run(proc.process(
            b"frame-m", "rig1", {"window_title": "Doom"},
            measured={"scene_change": 0.42, "frame_motion": "high"},
        ))
        current = proc._game_state.get_current("Doom")
        self.assertEqual(current.get("scene_change"), 0.42)
        self.assertEqual(current.get("frame_motion"), "high")
        # tip-scraped value still present in the same snapshot
        self.assertEqual(current.get("health"), 40)

    def test_measured_signals_override_scraped(self):
        # On a key collision, the *measured* value wins over the guessed one.
        proc = _make_processor("Your score is 10.")
        _run(proc.process(
            b"frame-o", "rig1", {"window_title": "Doom"},
            measured={"score": 999},
        ))
        current = proc._game_state.get_current("Doom")
        self.assertEqual(current.get("score"), 999)


class TestAskPipeline(unittest.TestCase):
    def test_ask_with_image(self):
        proc = _make_processor("Use the shotgun.")
        answer = _run(proc.ask(
            question="What weapon?",
            client_id="ask",
            metadata={"window_title": "Doom"},
            image_bytes=b"frame",
        ))
        self.assertEqual(answer, "Use the shotgun.")
        self.assertTrue(proc._backend.generate.await_count >= 1)

    def test_ask_without_image_uses_text_backend(self):
        proc = _make_processor("Go left.")
        answer = _run(proc.ask(
            question="Where to?",
            client_id="ask",
            metadata={"window_title": "Doom"},
            image_bytes=None,
        ))
        self.assertEqual(answer, "Go left.")
        self.assertTrue(proc._backend.generate_text.await_count >= 1)
        self.assertEqual(proc._backend.generate.await_count, 0)


if __name__ == "__main__":
    unittest.main()
