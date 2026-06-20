"""Tests for the board-vision worker's reliable core (worker/board_vision.py).

cv2/numpy/MQTT are imported lazily inside the pixel/MQTT paths, so the geometry
helpers and — the valuable part — the chess move-inference/tracking are testable
without those heavy deps. python-chess is a real (pure-Python) dependency.
"""

import unittest

from worker.board_vision import (
    STARTING_GRID,
    BoardTracker,
    board_to_grid,
    infer_move,
    order_corners,
    parse_corners,
)
from worker import board_vision as bv


class TestParseCorners(unittest.TestCase):
    def test_four_points(self):
        pts = parse_corners("0.1,0.1;0.9,0.1;0.9,0.9;0.1,0.9")
        self.assertEqual(len(pts), 4)
        self.assertEqual(pts[0], (0.1, 0.1))

    def test_rejects_wrong_count(self):
        with self.assertRaises(ValueError):
            parse_corners("0.1,0.1;0.9,0.9")

    def test_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            parse_corners("0.1,0.1;1.2,0.1;0.9,0.9;0.1,0.9")

    def test_rejects_bad_shape(self):
        with self.assertRaises(ValueError):
            parse_corners("0.1;0.9,0.1;0.9,0.9;0.1,0.9")


class TestOrderCorners(unittest.TestCase):
    def test_orders_to_tl_tr_br_bl(self):
        # Deliberately shuffled input.
        scrambled = [(0.9, 0.9), (0.1, 0.1), (0.1, 0.9), (0.9, 0.1)]
        tl, tr, br, bl = order_corners(scrambled)
        self.assertEqual(tl, (0.1, 0.1))
        self.assertEqual(tr, (0.9, 0.1))
        self.assertEqual(br, (0.9, 0.9))
        self.assertEqual(bl, (0.1, 0.9))


@unittest.skipUnless(bv._CHESS_AVAILABLE, "python-chess not installed")
class TestBoardToGrid(unittest.TestCase):
    def test_starting_position(self):
        import chess
        self.assertEqual(board_to_grid(chess.Board()), STARTING_GRID)

    def test_flip_mirrors(self):
        import chess
        normal = board_to_grid(chess.Board(), flip=False)
        flipped = board_to_grid(chess.Board(), flip=True)
        # Start position is symmetric in occupancy/colour under 180° rotation
        # only if colours swap; here the two views differ (white vs black rows).
        self.assertNotEqual(normal, flipped)


@unittest.skipUnless(bv._CHESS_AVAILABLE, "python-chess not installed")
class TestInferMove(unittest.TestCase):
    def _grid_after(self, uci):
        import chess
        b = chess.Board()
        b.push_uci(uci)
        return board_to_grid(b)

    def test_simple_pawn_push(self):
        import chess
        board = chess.Board()
        target = self._grid_after("e2e4")
        move = infer_move(board, target)
        self.assertEqual(move.uci(), "e2e4")

    def test_capture_inferred(self):
        import chess
        # After 1.e4 d5, White's exd5 is the move that matches the grid.
        board = chess.Board()
        board.push_uci("e2e4")
        board.push_uci("d7d5")
        b2 = board.copy()
        b2.push_uci("e4d5")
        target = board_to_grid(b2)
        move = infer_move(board, target)
        self.assertEqual(move.uci(), "e4d5")

    def test_castling_inferred(self):
        import chess
        # Position where White can castle kingside.
        board = chess.Board(
            "rnbqkbnr/pppp1ppp/8/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1"
        )
        b2 = board.copy()
        b2.push_uci("e1g1")  # O-O
        target = board_to_grid(b2)
        move = infer_move(board, target)
        self.assertEqual(move.uci(), "e1g1")

    def test_promotion_defaults_to_queen(self):
        import chess
        # White pawn on a7, promotes on a8 (empty). All promo pieces share the
        # same occupancy/colour grid, so we default to the queen.
        board = chess.Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        b2 = board.copy()
        b2.push_uci("a7a8q")
        target = board_to_grid(b2)
        move = infer_move(board, target)
        self.assertEqual(move.promotion, chess.QUEEN)

    def test_unknown_grid_returns_none(self):
        import chess
        board = chess.Board()
        # A grid that no single legal move can produce (two pawns vanished).
        bad = list(STARTING_GRID)
        bad[6] = "ww....ww"  # remove four white pawns at once
        self.assertIsNone(infer_move(board, tuple(bad)))


@unittest.skipUnless(bv._CHESS_AVAILABLE, "python-chess not installed")
class TestBoardTracker(unittest.TestCase):
    def test_tracks_a_short_game(self):
        import chess
        tracker = BoardTracker()
        moves = ["e2e4", "e7e5", "g1f3", "b8c6"]
        ref = chess.Board()
        for uci in moves:
            ref.push_uci(uci)
            result = tracker.update(board_to_grid(ref))
            self.assertEqual(result["status"], "move")
            self.assertEqual(result["move"], uci)
        self.assertEqual(tracker.board.fen(), ref.fen())

    def test_nochange_when_grid_identical(self):
        tracker = BoardTracker()
        result = tracker.update(STARTING_GRID)
        self.assertEqual(result["status"], "nochange")

    def test_unknown_does_not_advance(self):
        tracker = BoardTracker()
        before = tracker.board.fen()
        bad = list(STARTING_GRID)
        bad[6] = "ww....ww"
        result = tracker.update(tuple(bad))
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(tracker.board.fen(), before)

    def test_reset(self):
        import chess
        tracker = BoardTracker()
        ref = chess.Board()
        ref.push_uci("e2e4")
        tracker.update(board_to_grid(ref))
        tracker.reset()
        self.assertEqual(tracker.board.fen(), chess.Board().fen())


if __name__ == "__main__":
    unittest.main()
