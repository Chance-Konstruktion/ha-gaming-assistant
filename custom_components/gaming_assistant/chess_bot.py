"""Chess bot — the assistant plays one side of a real chess game (GA-110).

Built on top of chess grounding: whenever a new position arrives (from the
board-vision worker, the ``analyze_board`` service or the MQTT board topic)
and it is the bot's turn, the bot takes the engine's suggested move and turns
it into something a person at a physical board can act on — a spoken
sentence ("I move my knight from g1 to f3.") — plus a structured move for anything
that wants to play it on a screen (a PC chess helper subscribed over MQTT).

Like ``chess_grounding`` this is pure Python on top of ``python-chess`` with no
Home Assistant dependency, so the decision logic and the wording are fully
unit-testable. The coordinator owns one instance and does the I/O (event,
MQTT, TTS).
"""
from __future__ import annotations

from typing import Any

try:
    import chess

    _CHESS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the dep
    chess = None  # type: ignore[assignment]
    _CHESS_AVAILABLE = False

BOT_COLORS = ["white", "black"]
DEFAULT_BOT_COLOR = "black"
# Search depth of the grounding engine while the bot plays (1 = fast and
# weak, 4 = strongest the in-HA engine allows).
BOT_STRENGTH_MIN = 1
BOT_STRENGTH_MAX = 4
DEFAULT_BOT_STRENGTH = 3

# Piece names by python-chess piece type (1 = pawn … 6 = king). German needs
# the article in the right case: accusative for the moved/captured piece
# ("ich ziehe den Springer", "… den Bauern"), dative after "mit" ("mit der Dame").
_PIECE_NAMES = {
    "en": {1: "pawn", 2: "knight", 3: "bishop", 4: "rook", 5: "queen", 6: "king"},
}
_DE_ACCUSATIVE = {
    1: "den Bauern", 2: "den Springer", 3: "den Läufer",
    4: "den Turm", 5: "die Dame", 6: "den König",
}
_DE_DATIVE = {
    1: "dem Bauern", 2: "dem Springer", 3: "dem Läufer",
    4: "dem Turm", 5: "der Dame", 6: "dem König",
}
_PROMOTION_DE = {2: "einen Springer", 3: "einen Läufer", 4: "einen Turm", 5: "eine Dame"}
_PROMOTION_EN = {2: "a knight", 3: "a bishop", 4: "a rook", 5: "a queen"}


def _lang(language: str | None) -> str:
    return "de" if (language or "").lower().startswith("de") else "en"


def describe_move(board, move, language: str | None = "en") -> str:
    """Return a spoken sentence for *move* played from *board* (before the move).

    Always first person, so a promotion after a capture still reads as one
    sentence. Covers plain moves, captures (naming the captured piece), en
    passant, castling, promotion, and a trailing check / checkmate.
    """
    lang = _lang(language)
    piece = board.piece_at(move.from_square)
    ptype = piece.piece_type if piece else 1
    src = chess.square_name(move.from_square)
    dst = chess.square_name(move.to_square)
    en = _PIECE_NAMES["en"]

    if board.is_castling(move):
        kingside = chess.square_file(move.to_square) > chess.square_file(move.from_square)
        if lang == "de":
            text = "Ich rochiere kurz" if kingside else "Ich rochiere lang"
        else:
            text = "I castle kingside" if kingside else "I castle queenside"
    elif board.is_en_passant(move):
        text = (
            f"Ich schlage mit dem Bauern von {src} en passant auf {dst}"
            if lang == "de"
            else f"I take en passant with my pawn from {src} to {dst}"
        )
    elif board.is_capture(move):
        victim = board.piece_at(move.to_square)
        vtype = victim.piece_type if victim else 1
        if lang == "de":
            text = (
                f"Ich schlage mit {_DE_DATIVE[ptype]} von {src} "
                f"{_DE_ACCUSATIVE[vtype]} auf {dst}"
            )
        else:
            text = f"I take the {en[vtype]} on {dst} with my {en[ptype]} from {src}"
    else:
        text = (
            f"Ich ziehe {_DE_ACCUSATIVE[ptype]} von {src} nach {dst}"
            if lang == "de"
            else f"I move my {en[ptype]} from {src} to {dst}"
        )

    if move.promotion:
        if lang == "de":
            text += f" und wandle in {_PROMOTION_DE[move.promotion]} um"
        else:
            text += f" and promote to {_PROMOTION_EN[move.promotion]}"
    text += "."

    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        text += " Schachmatt!" if lang == "de" else " Checkmate!"
    elif after.is_check():
        text += " Schach!" if lang == "de" else " Check!"
    return text


def describe_game_over(board, bot_color: str, language: str | None = "en") -> str:
    """Sentence for a finished game, seen from the bot's side."""
    lang = _lang(language)
    if board.is_checkmate():
        loser = "white" if board.turn == chess.WHITE else "black"
        if loser == bot_color:
            return "Schachmatt – du hast gewonnen. Gut gespielt!" if lang == "de" else (
                "Checkmate – you win. Well played!"
            )
        return "Schachmatt – ich habe gewonnen." if lang == "de" else "Checkmate – I win."
    return "Remis." if lang == "de" else "Draw."


class ChessBot:
    """Decides the bot's move for a grounded position, once per position."""

    def __init__(self) -> None:
        self.enabled = False
        self.color = DEFAULT_BOT_COLOR
        self.strength = DEFAULT_BOT_STRENGTH
        self.last_move: dict[str, Any] | None = None
        # Full FEN the bot last reacted to, so a re-published position (a
        # worker repeating itself, a service call) is never announced twice.
        self._last_fen: str | None = None

    def configure(
        self,
        enabled: bool | None = None,
        color: str | None = None,
        strength: int | None = None,
    ) -> None:
        """Apply the given settings; None leaves a setting as it is.

        Raises ValueError for an unknown color or a non-numeric strength
        before changing anything.
        """
        if color is not None and color not in BOT_COLORS:
            raise ValueError(f"color must be one of {BOT_COLORS}")
        level = None if strength is None else int(strength)
        if enabled is not None:
            if enabled and not self.enabled:
                self._last_fen = None  # a fresh start reacts to the current board
            self.enabled = bool(enabled)
        if color is not None:
            if color != self.color:
                self._last_fen = None
            self.color = color
        if level is not None:
            self.strength = max(BOT_STRENGTH_MIN, min(BOT_STRENGTH_MAX, level))

    def new_game(self) -> None:
        """Forget the old game, so the same opening is answered again."""
        self._last_fen = None
        self.last_move = None

    def decide(self, result: dict[str, Any], language: str | None = "en") -> dict[str, Any] | None:
        """Return the bot's reaction to a grounding *result*, or None.

        A reaction is either the bot's move (``kind: "move"``) when it is the
        bot's turn, or the final word (``kind: "game_over"``) when the game
        just ended. Positions the bot already reacted to, invalid positions,
        and the opponent's turn yield None.
        """
        if not self.enabled or not _CHESS_AVAILABLE:
            return None
        if not result.get("available") or not result.get("valid"):
            return None
        fen = result.get("fen") or ""
        if not fen or fen == self._last_fen:
            return None
        board = chess.Board(fen)

        if board.is_game_over():
            self._last_fen = fen
            self.last_move = {
                "kind": "game_over",
                "speech": describe_game_over(board, self.color, language),
                "fen": fen,
                "result": board.result(claim_draw=True),
            }
            return self.last_move

        bot_to_move = (board.turn == chess.WHITE) == (self.color == "white")
        if not bot_to_move:
            return None
        san = result.get("best_move")
        if not san:
            return None
        try:
            move = board.parse_san(san)
        except ValueError:
            return None

        self._last_fen = fen
        speech = describe_move(board, move, language)
        captured = board.piece_at(move.to_square)
        if board.is_en_passant(move):
            captured = chess.Piece(chess.PAWN, not board.turn)
        piece = board.piece_at(move.from_square)
        after = board.copy(stack=False)
        after.push(move)
        reaction = {
            "kind": "move",
            "san": san,
            "uci": move.uci(),
            "from": chess.square_name(move.from_square),
            "to": chess.square_name(move.to_square),
            "piece": _PIECE_NAMES["en"][piece.piece_type] if piece else None,
            "capture": _PIECE_NAMES["en"][captured.piece_type] if captured else None,
            "promotion": _PIECE_NAMES["en"][move.promotion] if move.promotion else None,
            "castling": board.is_castling(move),
            "check": after.is_check(),
            "checkmate": after.is_checkmate(),
            "speech": speech,
            "fen": fen,
            "fen_after": after.fen(),
            "eval_white_cp": result.get("eval_white_cp"),
        }
        self.last_move = reaction
        return reaction
