"""Chess grounding — symbolic chess reasoning that runs *inside* Home Assistant.

Unlike the perception workers (audio/vision/OCR), which are continuous and
heavy and therefore live at the edge, chess reasoning is **episodic and
symbolic**: it runs only when the board changes, on a tiny 64-square state.
Move generation is microseconds and a shallow search is milliseconds, so it
fits comfortably in the integration — no extra server, no Stockfish binary.

This turns the opponent/analyst modes from "guessing from a picture" into
real chess facts: legal moves, material balance, threats (captures/checks),
and a suggested move from a small built-in evaluator. These become Tier-1
*measured* signals, exactly like HUD numbers or audio cues.

The engine here is deliberately modest (material + mobility + a shallow
alpha-beta). It is not Stockfish and is not meant to be — its job is to
*ground* the LLM in correct, legal chess, which is where the value is.

``python-chess`` (pure-Python, pip-installed via the manifest) does the
rules; everything degrades gracefully if it is somehow unavailable.
"""
from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

try:
    import chess

    _CHESS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the dep
    chess = None  # type: ignore[assignment]
    _CHESS_AVAILABLE = False


# Centipawn material values. The king is scored via mate detection, not here.
if _CHESS_AVAILABLE:
    PIECE_VALUES = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
    }
else:  # pragma: no cover
    PIECE_VALUES = {}

DEFAULT_SEARCH_DEPTH = 3
MOBILITY_WEIGHT = 5  # centipawns per extra legal move
MATE_SCORE = 100_000
INF = 10_000_000
MAX_NODES = 40_000  # hard cap so a pathological position can't run away

# How many capture/check candidate moves to surface (SAN), at most.
MAX_CANDIDATES = 8


def is_available() -> bool:
    """Whether python-chess is importable (feature is enabled)."""
    return _CHESS_AVAILABLE


# ---------------------------------------------------------------------------
# Evaluation (White's perspective, centipawns)
# ---------------------------------------------------------------------------

def _material_cp(board) -> int:
    score = 0
    for piece_type, value in PIECE_VALUES.items():
        score += value * len(board.pieces(piece_type, chess.WHITE))
        score -= value * len(board.pieces(piece_type, chess.BLACK))
    return score


def _mobility_cp(board) -> int:
    """Crude mobility term: (white legal moves − black legal moves).

    Skipped while in check, where a null move would be illegal/meaningless.
    """
    if board.is_check():
        return 0
    turn = board.turn
    own = board.legal_moves.count()
    board.push(chess.Move.null())
    opp = board.legal_moves.count()
    board.pop()
    white_moves = own if turn == chess.WHITE else opp
    black_moves = opp if turn == chess.WHITE else own
    return MOBILITY_WEIGHT * (white_moves - black_moves)


def _evaluate(board) -> int:
    """Static evaluation from White's perspective."""
    if board.is_checkmate():
        # The side to move is mated → terrible for that side.
        return -MATE_SCORE if board.turn == chess.WHITE else MATE_SCORE
    if (
        board.is_stalemate()
        or board.is_insufficient_material()
        or board.is_seventyfive_moves()
        or board.is_fivefold_repetition()
    ):
        return 0
    return _material_cp(board) + _mobility_cp(board)


def _evaluate_pov(board) -> int:
    """Static evaluation from the side-to-move's perspective (for negamax)."""
    score = _evaluate(board)
    return score if board.turn == chess.WHITE else -score


def _ordered_moves(board):
    """Captures first — cheap move ordering to help alpha-beta prune."""
    return sorted(board.legal_moves, key=board.is_capture, reverse=True)


def _negamax(board, depth: int, alpha: int, beta: int, counter: list[int]):
    """Negamax with alpha-beta pruning. Returns (score_pov, best_move)."""
    counter[0] += 1
    if depth == 0 or board.is_game_over() or counter[0] > MAX_NODES:
        return _evaluate_pov(board), None

    best_score = -INF
    best_move = None
    for move in _ordered_moves(board):
        board.push(move)
        score, _ = _negamax(board, depth - 1, -beta, -alpha, counter)
        score = -score
        board.pop()
        if score > best_score:
            best_score = score
            best_move = move
        if score > alpha:
            alpha = score
        if alpha >= beta:
            break

    if best_move is None:  # no legal moves but not flagged game over
        return _evaluate_pov(board), None
    return best_score, best_move


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _phase(board) -> str:
    non_pawn = sum(
        len(board.pieces(pt, color))
        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
        for color in (chess.WHITE, chess.BLACK)
    )
    if board.fullmove_number <= 10:
        return "opening"
    if non_pawn <= 6:
        return "endgame"
    return "middlegame"


def analyze_fen(fen: str, depth: int = DEFAULT_SEARCH_DEPTH) -> dict[str, Any]:
    """Ground a chess position given as FEN.

    Returns a dict that is always safe to consume:
      * ``available`` False  → python-chess isn't installed.
      * ``valid`` False      → the FEN was empty/malformed/illegal (``error``).
      * otherwise            → grounded facts + a suggested ``best_move``.

    Never raises; bad input becomes a structured error.
    """
    if not _CHESS_AVAILABLE:
        return {"available": False}

    fen = (fen or "").strip()
    if not fen:
        return {"available": True, "valid": False, "error": "empty FEN"}

    try:
        board = chess.Board(fen)
    except ValueError as err:
        return {"available": True, "valid": False, "error": str(err)}

    legal = board.is_valid()
    result: dict[str, Any] = {
        "available": True,
        "valid": legal,
        "fen": board.fen(),
        "side_to_move": "white" if board.turn == chess.WHITE else "black",
        "fullmove": board.fullmove_number,
        "halfmove_clock": board.halfmove_clock,
        "legal_moves": board.legal_moves.count(),
        "is_check": board.is_check(),
        "is_checkmate": board.is_checkmate(),
        "is_stalemate": board.is_stalemate(),
        "is_insufficient_material": board.is_insufficient_material(),
        "is_game_over": board.is_game_over(),
        "material_cp": _material_cp(board),
        "phase": _phase(board),
    }

    if not legal:
        result["error"] = "illegal position"
        return result

    captures: list[str] = []
    checks: list[str] = []
    for move in board.legal_moves:
        if board.is_capture(move):
            captures.append(board.san(move))
        if board.gives_check(move):
            checks.append(board.san(move))
    result["captures"] = captures[:MAX_CANDIDATES]
    result["checks"] = checks[:MAX_CANDIDATES]

    if not board.is_game_over():
        depth = max(1, min(int(depth), 4))
        best_score, best_move = _negamax(board, depth, -INF, INF, [0])
        if best_move is not None:
            result["best_move"] = board.san(best_move)
            result["eval_cp"] = int(best_score)  # side-to-move perspective
            result["eval_white_cp"] = int(
                best_score if board.turn == chess.WHITE else -best_score
            )
    result["summary"] = _summarize(result)
    return result


def _summarize(result: dict[str, Any]) -> str:
    """One-line, human/LLM-friendly summary for the sensor and prompt."""
    side = result.get("side_to_move", "?")
    if result.get("is_checkmate"):
        return f"Checkmate — {side} to move has no moves."
    bits = [f"{side} to move"]
    best = result.get("best_move")
    if best:
        bits.append(f"best {best}")
    if "eval_white_cp" in result:
        bits.append(f"eval {result['eval_white_cp'] / 100:+.1f} (White)")
    bits.append(f"phase {result.get('phase', '?')}")
    if result.get("is_check"):
        bits.append("in check")
    return ", ".join(bits)


def measured_signals(result: dict[str, Any]) -> dict[str, Any]:
    """Project a grounding result into compact Tier-1 measured signals.

    Only stable, useful keys — these are merged into the game state and shown
    to the LLM as live signals, so keep them small.
    """
    if not result.get("available") or not result.get("valid"):
        return {}
    measured: dict[str, Any] = {
        "chess_side": result["side_to_move"],
        "chess_material_cp": result["material_cp"],
        "chess_phase": result["phase"],
        "chess_legal_moves": result["legal_moves"],
        "chess_check": "yes" if result.get("is_check") else "no",
    }
    if "best_move" in result:
        measured["chess_best_move"] = result["best_move"]
    if "eval_white_cp" in result:
        measured["chess_eval_cp"] = result["eval_white_cp"]
    return measured
