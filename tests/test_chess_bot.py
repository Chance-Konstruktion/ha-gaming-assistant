"""Tests for the chess bot (custom_components/.../chess_bot.py, GA-110).

The bot is pure Python on top of python-chess: these drive the real move
wording (German + English) and the turn / dedup / game-over decisions, and
check that the grounding engine's suggested move is always playable.
"""

import importlib.util
import pathlib
import unittest

import chess

_BASE = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "gaming_assistant"


def _load(name):
    # Load by path so the package __init__ (which imports Home Assistant) is
    # bypassed; both modules are pure Python.
    spec = importlib.util.spec_from_file_location(f"{name}_standalone", _BASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cb = _load("chess_bot")
cg = _load("chess_grounding")

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
SCHOLAR = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 2 3"
FOOLS_MATE = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
STALEMATE = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"


def _say(fen, san, lang):
    board = chess.Board(fen)
    return cb.describe_move(board, board.parse_san(san), lang)


def _grounded(fen, best_move=None):
    """A minimal grounding result as analyze_fen would return it."""
    board = chess.Board(fen)
    result = {"available": True, "valid": board.is_valid(), "fen": board.fen()}
    if best_move:
        result["best_move"] = best_move
    return result


class TestMoveWording(unittest.TestCase):
    def test_plain_move(self):
        self.assertEqual(_say(START, "Nf3", "de"), "Ich ziehe den Springer von g1 nach f3.")
        self.assertEqual(_say(START, "Nf3", "en"), "I move my knight from g1 to f3.")

    def test_language_falls_back_to_english(self):
        self.assertEqual(_say(START, "e4", "fr"), "I move my pawn from e2 to e4.")
        self.assertEqual(_say(START, "e4", "de-AT"), "Ich ziehe den Bauern von e2 nach e4.")

    def test_capture_names_both_pieces_and_mate(self):
        self.assertEqual(
            _say(SCHOLAR, "Qxf7#", "de"),
            "Ich schlage mit der Dame von f3 den Bauern auf f7. Schachmatt!",
        )
        self.assertEqual(
            _say(SCHOLAR, "Qxf7#", "en"),
            "I take the pawn on f7 with my queen from f3. Checkmate!",
        )

    def test_castling(self):
        short = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
        long_ = "r3k2r/pppq1ppp/2npbn2/4p3/4P3/2NPBN2/PPPQ1PPP/R3K2R b KQkq - 0 1"
        self.assertEqual(_say(short, "O-O", "de"), "Ich rochiere kurz.")
        self.assertEqual(_say(long_, "O-O-O", "de"), "Ich rochiere lang.")
        self.assertEqual(_say(short, "O-O", "en"), "I castle kingside.")
        self.assertEqual(_say(long_, "O-O-O", "en"), "I castle queenside.")

    def test_en_passant(self):
        fen = "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3"
        self.assertEqual(
            _say(fen, "exf6", "de"), "Ich schlage mit dem Bauern von e5 en passant auf f6."
        )

    def test_promotion_with_capture_and_check(self):
        fen = "r4k2/1P6/8/8/8/8/8/4K3 w - - 0 1"
        self.assertEqual(
            _say(fen, "bxa8=Q+", "de"),
            "Ich schlage mit dem Bauern von b7 den Turm auf a8 und wandle in eine Dame um. Schach!",
        )
        self.assertEqual(
            _say(fen, "bxa8=Q+", "en"),
            "I take the rook on a8 with my pawn from b7 and promote to a queen. Check!",
        )

    def test_underpromotion(self):
        fen = "8/1P5k/8/8/8/8/8/4K3 w - - 0 1"
        self.assertEqual(
            _say(fen, "b8=N", "de"),
            "Ich ziehe den Bauern von b7 nach b8 und wandle in einen Springer um.",
        )


class TestBotDecisions(unittest.TestCase):
    def _bot(self, color="black"):
        bot = cb.ChessBot()
        bot.configure(enabled=True, color=color)
        return bot

    def test_off_by_default(self):
        bot = cb.ChessBot()
        self.assertFalse(bot.enabled)
        self.assertEqual(bot.color, "black")
        self.assertIsNone(bot.decide(_grounded(AFTER_E4, "e5")))

    def test_moves_on_its_turn(self):
        reaction = self._bot("black").decide(_grounded(AFTER_E4, "Nf6"), "de")
        self.assertEqual(reaction["kind"], "move")
        self.assertEqual(reaction["san"], "Nf6")
        self.assertEqual(reaction["uci"], "g8f6")
        self.assertEqual((reaction["from"], reaction["to"]), ("g8", "f6"))
        self.assertEqual(reaction["piece"], "knight")
        self.assertIsNone(reaction["capture"])
        self.assertEqual(reaction["speech"], "Ich ziehe den Springer von g8 nach f6.")
        self.assertEqual(chess.Board(reaction["fen_after"]).turn, chess.WHITE)

    def test_waits_on_the_opponents_turn(self):
        self.assertIsNone(self._bot("white").decide(_grounded(AFTER_E4, "e5")))

    def test_same_position_is_answered_once(self):
        bot = self._bot("black")
        self.assertIsNotNone(bot.decide(_grounded(AFTER_E4, "e5")))
        self.assertIsNone(bot.decide(_grounded(AFTER_E4, "e5")))

    def test_new_game_forgets_answered_positions(self):
        bot = self._bot("black")
        self.assertIsNotNone(bot.decide(_grounded(AFTER_E4, "e5")))
        bot.new_game()
        self.assertIsNone(bot.last_move)
        # The opponent opens the same way again: the bot must answer again.
        self.assertIsNotNone(bot.decide(_grounded(AFTER_E4, "e5")))

    def test_switching_sides_answers_the_board_again(self):
        bot = self._bot("black")
        self.assertIsNotNone(bot.decide(_grounded(AFTER_E4, "e5")))
        bot.configure(color="white")
        bot.configure(color="black")
        self.assertIsNotNone(bot.decide(_grounded(AFTER_E4, "e5")))

    def test_ignores_invalid_or_unsearched_positions(self):
        bot = self._bot("black")
        self.assertIsNone(bot.decide({"available": True, "valid": False}))
        self.assertIsNone(bot.decide({"available": False}))
        self.assertIsNone(bot.decide(_grounded(AFTER_E4)))  # no best move
        self.assertIsNone(bot.decide(_grounded(AFTER_E4, "Qh5")))  # not legal

    def test_capture_and_mate_flags(self):
        reaction = self._bot("white").decide(_grounded(SCHOLAR, "Qxf7#"))
        self.assertEqual(reaction["capture"], "pawn")
        self.assertTrue(reaction["checkmate"])
        self.assertTrue(reaction["check"])

    def test_game_over_from_the_bots_side(self):
        # White is mated in fool's mate: the bot playing White lost.
        lost = self._bot("white").decide(_grounded(FOOLS_MATE), "de")
        self.assertEqual(lost["kind"], "game_over")
        self.assertIn("du hast gewonnen", lost["speech"])
        won = self._bot("black").decide(_grounded(FOOLS_MATE), "de")
        self.assertIn("ich habe gewonnen", won["speech"])
        self.assertEqual(won["result"], "0-1")
        draw = self._bot("white").decide(_grounded(STALEMATE), "en")
        self.assertEqual(draw["speech"], "Draw.")

    def test_configure_validates(self):
        bot = cb.ChessBot()
        with self.assertRaises(ValueError):
            bot.configure(enabled=True, color="green")
        with self.assertRaises(ValueError):
            bot.configure(enabled=True, strength="max")
        self.assertFalse(bot.enabled)  # a rejected call changes nothing
        bot.configure(strength=9)
        self.assertEqual(bot.strength, cb.BOT_STRENGTH_MAX)
        bot.configure(strength=0)
        self.assertEqual(bot.strength, cb.BOT_STRENGTH_MIN)


class TestBotWithRealEngine(unittest.TestCase):
    """The engine's SAN must always be something the bot can play and say."""

    def test_engine_move_is_playable_at_every_strength(self):
        for strength in range(cb.BOT_STRENGTH_MIN, cb.BOT_STRENGTH_MAX + 1):
            bot = cb.ChessBot()
            bot.configure(enabled=True, color="white", strength=strength)
            with self.subTest(strength=strength):
                reaction = bot.decide(cg.analyze_fen(START, depth=strength), "en")
                self.assertEqual(reaction["kind"], "move")
                self.assertTrue(reaction["speech"].startswith("I move my "))

    def test_engine_finds_the_mate(self):
        bot = cb.ChessBot()
        bot.configure(enabled=True, color="white")
        reaction = bot.decide(cg.analyze_fen(SCHOLAR), "de")
        self.assertEqual(reaction["san"], "Qxf7#")
        self.assertTrue(reaction["speech"].endswith("Schachmatt!"))


if __name__ == "__main__":
    unittest.main()
