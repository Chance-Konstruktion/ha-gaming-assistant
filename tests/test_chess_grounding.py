"""Tests for the in-HA chess grounding (custom_components/.../chess_grounding.py).

These exercise the real python-chess-backed logic: FEN validation, grounded
facts (material/threats/checkmate), and the shallow search finding obvious
tactics. python-chess is a pure-Python dependency declared in the manifest.
"""

import sys
import unittest
from unittest.mock import MagicMock

# Importing via the package runs custom_components/gaming_assistant/__init__.py,
# which imports Home Assistant. Stub those modules — chess_grounding itself has
# no HA dependency.
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

from custom_components.gaming_assistant import chess_grounding as cg  # noqa: E402

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


@unittest.skipUnless(cg.is_available(), "python-chess not installed")
class TestAnalyzeFen(unittest.TestCase):
    def test_start_position(self):
        r = cg.analyze_fen(START_FEN)
        self.assertTrue(r["available"])
        self.assertTrue(r["valid"])
        self.assertEqual(r["side_to_move"], "white")
        self.assertEqual(r["legal_moves"], 20)
        self.assertEqual(r["material_cp"], 0)
        self.assertEqual(r["phase"], "opening")
        self.assertFalse(r["is_check"])
        self.assertIn("best_move", r)
        self.assertIn("summary", r)

    def test_empty_fen_is_invalid(self):
        r = cg.analyze_fen("")
        self.assertTrue(r["available"])
        self.assertFalse(r["valid"])
        self.assertIn("error", r)

    def test_malformed_fen_is_invalid(self):
        r = cg.analyze_fen("this is not a fen")
        self.assertTrue(r["available"])
        self.assertFalse(r["valid"])
        self.assertIn("error", r)

    def test_material_balance_white_up_a_queen(self):
        # White has an extra queen (Black queen removed).
        fen = "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        r = cg.analyze_fen(fen)
        self.assertEqual(r["material_cp"], 900)

    def test_detects_checkmate(self):
        # Fool's mate: 1. f3 e5 2. g4 Qh4#  → White is checkmated, Black delivered.
        fen = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
        r = cg.analyze_fen(fen)
        self.assertTrue(r["valid"])
        self.assertTrue(r["is_check"])
        self.assertTrue(r["is_checkmate"])
        self.assertTrue(r["is_game_over"])
        self.assertEqual(r["legal_moves"], 0)
        # No best_move for a finished game.
        self.assertNotIn("best_move", r)

    def test_finds_free_queen_capture(self):
        # White to move; a Black queen sits en prise on d5 with nothing
        # defending it. The shallow search should grab it.
        fen = "4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1"
        r = cg.analyze_fen(fen, depth=2)
        self.assertTrue(r["valid"])
        self.assertIn("exd5", r["best_move"])  # pawn takes queen
        self.assertIn("exd5", r["captures"])

    def test_finds_mate_in_one(self):
        # Back-rank style: White to move and mate. Rook to a8 is mate.
        fen = "6k1/5ppp/8/8/8/8/8/R3K3 w Q - 0 1"
        r = cg.analyze_fen(fen, depth=2)
        self.assertTrue(r["valid"])
        # Best move should be the mating move (SAN ends with '#').
        self.assertTrue(r["best_move"].endswith("#"), r["best_move"])

    def test_illegal_position_flagged(self):
        # White to move, but Black (not to move) is in check from the e1 rook
        # along the open e-file → illegal per chess rules.
        fen = "4k3/8/8/8/8/8/8/4R1K1 w - - 0 1"
        r = cg.analyze_fen(fen)
        # python-chess parses it but is_valid() is False.
        self.assertFalse(r["valid"])


@unittest.skipUnless(cg.is_available(), "python-chess not installed")
class TestMeasuredSignals(unittest.TestCase):
    def test_projects_compact_signals(self):
        r = cg.analyze_fen(START_FEN)
        m = cg.measured_signals(r)
        self.assertEqual(m["chess_side"], "white")
        self.assertEqual(m["chess_material_cp"], 0)
        self.assertEqual(m["chess_phase"], "opening")
        self.assertEqual(m["chess_check"], "no")
        self.assertIn("chess_best_move", m)
        self.assertIn("chess_eval_cp", m)

    def test_invalid_yields_no_signals(self):
        self.assertEqual(cg.measured_signals({"available": True, "valid": False}), {})
        self.assertEqual(cg.measured_signals({"available": False}), {})


if __name__ == "__main__":
    unittest.main()
