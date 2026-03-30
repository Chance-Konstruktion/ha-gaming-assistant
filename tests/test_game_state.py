"""Unit tests for the Game State Engine."""

import asyncio
import json
import sys
import tempfile
import time
import unittest
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
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.event",
]
for mod in _HA_MODULES:
    sys.modules.setdefault(mod, MagicMock())

from custom_components.gaming_assistant.game_state import (
    GameStateManager,
    GameStateSnapshot,
    extract_observations_from_tip,
)


class TestGameStateSnapshot(unittest.TestCase):
    """Tests for GameStateSnapshot serialization."""

    def test_to_dict_and_back(self):
        snap = GameStateSnapshot(
            observations={"health": 80, "phase": "combat"},
            tip="Watch your health!",
            source="test_client",
        )
        d = snap.to_dict()
        self.assertEqual(d["obs"]["health"], 80)
        self.assertEqual(d["obs"]["phase"], "combat")
        self.assertIn("t", d)
        self.assertEqual(d["tip"], "Watch your health!")
        self.assertEqual(d["src"], "test_client")

        # Round-trip
        restored = GameStateSnapshot.from_dict(d)
        self.assertEqual(restored.observations["health"], 80)
        self.assertEqual(restored.tip, "Watch your health!")

    def test_tip_truncation(self):
        long_tip = "A" * 200
        snap = GameStateSnapshot(observations={}, tip=long_tip)
        d = snap.to_dict()
        self.assertLessEqual(len(d["tip"]), 120)


class TestGameStateManager(unittest.TestCase):
    """Tests for GameStateManager core functionality."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.gsm = GameStateManager(config_dir=self.tmpdir, window_size=5)

    def test_update_and_get_current(self):
        self.gsm.update("chess", {"phase": "opening", "move": "e4"})
        current = self.gsm.get_current("chess")
        self.assertIsNotNone(current)
        self.assertEqual(current["phase"], "opening")
        self.assertEqual(current["move"], "e4")

    def test_get_current_empty(self):
        self.assertIsNone(self.gsm.get_current("unknown_game"))

    def test_empty_game_name_ignored(self):
        self.gsm.update("", {"phase": "opening"})
        self.assertEqual(self.gsm.tracked_games, [])

    def test_ring_buffer_trim(self):
        for i in range(10):
            self.gsm.update("chess", {"move_number": i})
        history = self.gsm.get_history("chess", count=100)
        self.assertEqual(len(history), 5)  # window_size=5
        self.assertEqual(history[0].observations["move_number"], 5)
        self.assertEqual(history[-1].observations["move_number"], 9)

    def test_get_history(self):
        for i in range(3):
            self.gsm.update("poker", {"round": i})
        history = self.gsm.get_history("poker", count=2)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].observations["round"], 1)

    def test_get_changes(self):
        self.gsm.update("chess", {"health": 100, "phase": "opening"})
        self.gsm.update("chess", {"health": 80, "phase": "opening", "threat": "fork"})
        changes = self.gsm.get_changes("chess")
        self.assertIn("health", changes)
        self.assertEqual(changes["health"]["from"], 100)
        self.assertEqual(changes["health"]["to"], 80)
        self.assertIn("threat", changes)
        self.assertEqual(changes["threat"]["from"], None)
        self.assertEqual(changes["threat"]["to"], "fork")
        # phase didn't change
        self.assertNotIn("phase", changes)

    def test_get_changes_single_snapshot(self):
        self.gsm.update("chess", {"health": 100})
        changes = self.gsm.get_changes("chess")
        self.assertEqual(changes, {})

    def test_format_for_prompt_empty(self):
        result = self.gsm.format_for_prompt("nonexistent")
        self.assertEqual(result, "")

    def test_format_for_prompt_current_state(self):
        self.gsm.update("chess", {"phase": "middlegame", "move": "Nf3"})
        result = self.gsm.format_for_prompt("chess")
        self.assertIn("phase: middlegame", result)
        self.assertIn("move: Nf3", result)

    def test_format_for_prompt_with_changes(self):
        self.gsm.update("chess", {"health": 100})
        self.gsm.update("chess", {"health": 60})
        result = self.gsm.format_for_prompt("chess")
        self.assertIn("health", result)
        self.assertIn("100", result)
        self.assertIn("60", result)

    def test_format_for_prompt_compact(self):
        self.gsm.update("chess", {"phase": "opening"})
        self.gsm.update("chess", {"phase": "middlegame"})
        result_compact = self.gsm.format_for_prompt("chess", compact=True)
        result_full = self.gsm.format_for_prompt("chess", compact=False)
        self.assertIn("Current state:", result_compact)
        self.assertIn("Current game state:", result_full)

    def test_format_for_prompt_trend(self):
        """Full mode shows trend when >= 3 snapshots."""
        for i in range(4):
            self.gsm.update("chess", {"move_number": i})
        result = self.gsm.format_for_prompt("chess", compact=False)
        self.assertIn("Recent state history:", result)

    def test_observation_key_limit(self):
        big_obs = {f"key_{i}": i for i in range(50)}
        self.gsm.update("chess", big_obs)
        current = self.gsm.get_current("chess")
        self.assertLessEqual(len(current), 30)

    def test_none_values_filtered(self):
        self.gsm.update("chess", {"health": 100, "enemy": None})
        current = self.gsm.get_current("chess")
        self.assertNotIn("enemy", current)

    def test_tracked_games(self):
        self.gsm.update("chess", {"phase": "opening"})
        self.gsm.update("poker", {"phase": "preflop"})
        self.assertIn("chess", self.gsm.tracked_games)
        self.assertIn("poker", self.gsm.tracked_games)

    def test_clear_single_game(self):
        self.gsm.update("chess", {"phase": "opening"})
        self.gsm.update("poker", {"phase": "preflop"})
        self.gsm.clear("chess")
        self.assertNotIn("chess", self.gsm.tracked_games)
        self.assertIn("poker", self.gsm.tracked_games)

    def test_clear_all(self):
        self.gsm.update("chess", {"phase": "opening"})
        self.gsm.update("poker", {"phase": "preflop"})
        self.gsm.clear()
        self.assertEqual(self.gsm.tracked_games, [])

    def test_persistence_save_and_load(self):
        self.gsm.update("chess", {"phase": "opening", "move": "e4"})
        self.gsm.update("chess", {"phase": "middlegame", "move": "Nf3"})
        self.gsm.save("chess")

        # Create new manager from same dir
        gsm2 = GameStateManager(config_dir=self.tmpdir, window_size=5)
        gsm2.load("chess")
        current = gsm2.get_current("chess")
        self.assertIsNotNone(current)
        self.assertEqual(current["phase"], "middlegame")
        self.assertEqual(current["move"], "Nf3")

    def test_load_nonexistent(self):
        """Loading a game that has no file should be a no-op."""
        self.gsm.load("nonexistent")
        self.assertIsNone(self.gsm.get_current("nonexistent"))

    def test_clear_removes_file(self):
        self.gsm.update("chess", {"phase": "opening"})
        self.gsm.save("chess")
        state_dir = Path(self.tmpdir) / "gaming_assistant" / "state"
        self.assertTrue(any(state_dir.glob("*.json")))
        self.gsm.clear("chess")
        self.assertFalse(any(state_dir.glob("*.json")))


class TestExtractObservations(unittest.TestCase):
    """Tests for extract_observations_from_tip."""

    def test_health_extraction(self):
        tip = "Your health is at 45, be careful!"
        obs = extract_observations_from_tip(tip)
        self.assertEqual(obs.get("health"), 45)

    def test_score_extraction(self):
        tip = "Great score: 1200 points! Keep going."
        obs = extract_observations_from_tip(tip)
        self.assertEqual(obs.get("score"), 1200)

    def test_phase_extraction(self):
        tip = "In the endgame, focus on pawn promotion."
        obs = extract_observations_from_tip(tip)
        self.assertEqual(obs.get("phase"), "endgame")

    def test_momentum_extraction(self):
        tip = "You have a clear advantage here."
        obs = extract_observations_from_tip(tip)
        self.assertEqual(obs.get("momentum"), "advantage")

    def test_chess_move_extraction(self):
        tip = "Play Nf3 to control the center."
        obs = extract_observations_from_tip(tip, game="Chess")
        self.assertEqual(obs.get("move"), "Nf3")

    def test_schema_keyword_match(self):
        schema = {
            "phase": ["preflop", "flop", "turn", "river"],
            "hand_strength": ["pair", "flush", "straight"],
        }
        pack = {"state_schema": schema}
        tip = "You have a strong pair on the flop."
        obs = extract_observations_from_tip(tip, prompt_pack=pack)
        self.assertEqual(obs.get("phase"), "flop")
        self.assertEqual(obs.get("hand_strength"), "pair")

    def test_empty_tip(self):
        obs = extract_observations_from_tip("")
        self.assertEqual(obs, {})

    def test_no_matches(self):
        tip = "This is a generic tip with no recognizable patterns."
        obs = extract_observations_from_tip(tip)
        self.assertEqual(obs, {})


class TestTrendDetection(unittest.TestCase):
    """Tests for detect_trends functionality."""

    def setUp(self):
        self.gsm = GameStateManager(window_size=10)

    def test_declining_numeric_trend(self):
        for hp in [100, 80, 60]:
            self.gsm.update("chess", {"health": hp})
        trends = self.gsm.detect_trends("chess")
        self.assertTrue(any("declining" in t for t in trends))

    def test_increasing_numeric_trend(self):
        for score in [10, 20, 30]:
            self.gsm.update("chess", {"score": score})
        trends = self.gsm.detect_trends("chess")
        self.assertTrue(any("increasing" in t for t in trends))

    def test_stable_value(self):
        for _ in range(4):
            self.gsm.update("chess", {"phase": "middlegame"})
        trends = self.gsm.detect_trends("chess")
        self.assertTrue(any("stable" in t and "middlegame" in t for t in trends))

    def test_value_shift(self):
        self.gsm.update("chess", {"momentum": "equal"})
        self.gsm.update("chess", {"momentum": "equal"})
        self.gsm.update("chess", {"momentum": "winning"})
        trends = self.gsm.detect_trends("chess")
        self.assertTrue(any("shifted" in t for t in trends))

    def test_not_enough_snapshots(self):
        self.gsm.update("chess", {"health": 100})
        trends = self.gsm.detect_trends("chess")
        self.assertEqual(trends, [])

    def test_format_trends_for_prompt(self):
        for hp in [100, 80, 60]:
            self.gsm.update("chess", {"health": hp})
        result = self.gsm.format_trends_for_prompt("chess")
        self.assertIn("health", result)
        self.assertIn("declining", result)

    def test_format_trends_compact(self):
        for hp in [100, 80, 60]:
            self.gsm.update("chess", {"health": hp})
        result = self.gsm.format_trends_for_prompt("chess", compact=True)
        self.assertTrue(result.startswith("Trends:"))

    def test_trends_included_in_prompt_format(self):
        for hp in [100, 80, 60]:
            self.gsm.update("chess", {"health": hp})
        result = self.gsm.format_for_prompt("chess")
        self.assertIn("declining", result)


class TestPromptBuilderWithState(unittest.TestCase):
    """Test that state_context is included in prompts."""

    def test_state_context_included(self):
        from custom_components.gaming_assistant.prompt_builder import PromptBuilder

        result = PromptBuilder.build(
            game="Chess",
            state_context="Current game state: phase: middlegame, move: Nf3",
        )
        self.assertIn("phase: middlegame", result)
        self.assertIn("move: Nf3", result)

    def test_empty_state_context_not_included(self):
        from custom_components.gaming_assistant.prompt_builder import PromptBuilder

        result = PromptBuilder.build(game="Chess", state_context="")
        self.assertNotIn("Current game state:", result)


if __name__ == "__main__":
    unittest.main()
