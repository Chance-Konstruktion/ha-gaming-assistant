#!/usr/bin/env python3
"""Board-Vision Worker for Gaming Assistant — physical chess board → FEN.

Runs on a client (the machine the camera is attached to, or any box that
receives the frames) and turns a camera view of a *physical* chess board into
a FEN, which it publishes to ``gaming_assistant/{client_id}/board`` — the topic
the in-Home-Assistant chess engine already consumes. So the heavy vision stays
at the edge; HA only does the (episodic, symbolic) chess reasoning.

The clever part — and the reliable, tested core — is **move inference by
tracking**: you do *not* need to visually classify piece *types*. Starting
from a known position and measuring only per-square **occupancy + piece colour**
each turn, the move is uniquely recoverable from the legal moves of the current
position (captures, castling and en passant fall out for free, because
python-chess updates the board and we compare the resulting occupancy/colour).
That yields a real, valid FEN.

The weak link is the pixel layer (perspective-warp the board from 4 configured
corners, split into 8×8, classify each square empty/white/black). It is a
calibratable best-effort here — thresholds are CLI args, and robust auto
corner-detection / a small classifier are future work.

MQTT Topics:
  Subscribes:
    gaming_assistant/+/image            — raw JPEG frames from a capture agent
    gaming_assistant/board/command      — runtime commands (JSON: reset/status)
  Publishes:
    gaming_assistant/{client_id}/board  — {"fen", "move", "san"} (JSON)
    gaming_assistant/{worker_id}/register / status (retained)

Corners are fractions of the frame (0..1), clockwise from the top-left as the
camera sees the board::

    --corners "0.12,0.08;0.88,0.10;0.90,0.92;0.10,0.90"

Requirements:
  pip install -r worker/requirements-boardvision.txt

Usage:
  python board_vision.py --broker 192.168.1.10 --client-id chess-cam \
      --corners "0.12,0.08;0.88,0.10;0.90,0.92;0.10,0.90"
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("board_vision")

# Lazy / optional imports — only fail if actually used without installing.
try:
    import paho.mqtt.client as mqtt_client

    _MQTT_AVAILABLE = True
except ImportError:
    _MQTT_AVAILABLE = False

try:
    import chess

    _CHESS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the dep
    chess = None  # type: ignore[assignment]
    _CHESS_AVAILABLE = False


DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
DEFAULT_CLIENT_ID = "chess-cam"
DEFAULT_MAX_FPS = 2.0
DEFAULT_WARP_SIZE = 480
# Stddev (per centre crop) above which a square counts as occupied, and the
# grey level below which an occupied square's piece is classed as black.
DEFAULT_OCCUPANCY_STD = 18.0
DEFAULT_DARK_BELOW = 110.0
# How many consecutive identical raw grids before we trust a change (debounce
# past blur / a hand reaching over the board).
STABLE_FRAMES = 2

SUBSCRIBE_TOPIC = "gaming_assistant/+/image"
COMMAND_TOPIC = "gaming_assistant/board/command"
BOARD_TOPIC_TEMPLATE = "gaming_assistant/{client_id}/board"
REGISTER_TOPIC_TEMPLATE = "gaming_assistant/{worker_id}/register"
STATUS_TOPIC_TEMPLATE = "gaming_assistant/{worker_id}/status"

# A grid is a tuple of 8 strings (top row first), each 8 chars of ".","w","b".
Grid = tuple

# The standard starting position as a grid (White at the bottom, a1 bottom-left).
STARTING_GRID: Grid = (
    "bbbbbbbb",
    "bbbbbbbb",
    "........",
    "........",
    "........",
    "........",
    "wwwwwwww",
    "wwwwwwww",
)

Point = tuple[float, float]


# ---------------------------------------------------------------------------
# Pure geometry helpers (no cv2 — unit tested)
# ---------------------------------------------------------------------------

def parse_corners(spec: str) -> list[Point]:
    """Parse ``x1,y1;x2,y2;x3,y3;x4,y4`` (fractions 0..1) into 4 points."""
    points: list[Point] = []
    for chunk in spec.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(",")
        if len(parts) != 2:
            raise ValueError(f"Corner '{chunk}' must look like x,y")
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError as err:
            raise ValueError(f"Corner '{chunk}' has non-numeric values") from err
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError(f"Corner '{chunk}' must be in [0,1]")
        points.append((x, y))
    if len(points) != 4:
        raise ValueError("Exactly 4 corners are required")
    return points


def order_corners(points: list[Point]) -> list[Point]:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left.

    Robust to any input order: top-left has the smallest x+y, bottom-right the
    largest; top-right has the smallest (y-x), bottom-left the largest.
    """
    if len(points) != 4:
        raise ValueError("order_corners needs exactly 4 points")
    by_sum = sorted(points, key=lambda p: p[0] + p[1])
    top_left, bottom_right = by_sum[0], by_sum[-1]
    by_diff = sorted(points, key=lambda p: p[1] - p[0])
    top_right, bottom_left = by_diff[0], by_diff[-1]
    return [top_left, top_right, bottom_right, bottom_left]


# ---------------------------------------------------------------------------
# Chess tracking — the reliable core (needs python-chess)
# ---------------------------------------------------------------------------

def board_to_grid(board, flip: bool = False) -> Grid:
    """Project a python-chess board to an occupancy/colour grid.

    ``flip=False`` views the board from White's side (a1 bottom-left).
    """
    rows = []
    for row in range(8):
        cells = []
        for col in range(8):
            if flip:
                square = chess.square(7 - col, row)
            else:
                square = chess.square(col, 7 - row)
            piece = board.piece_at(square)
            if piece is None:
                cells.append(".")
            else:
                cells.append("w" if piece.color == chess.WHITE else "b")
        rows.append("".join(cells))
    return tuple(rows)


def infer_move(board, target_grid: Grid, flip: bool = False):
    """Find the single legal move whose result matches ``target_grid``.

    Returns the move, or ``None`` if no move matches or it is ambiguous. The
    only ambiguity we resolve is the promotion *piece* (same from/to square):
    we default to a queen.
    """
    matches = []
    for move in board.legal_moves:
        board.push(move)
        grid = board_to_grid(board, flip)
        board.pop()
        if grid == target_grid:
            matches.append(move)

    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    froms = {m.from_square for m in matches}
    tos = {m.to_square for m in matches}
    if len(froms) == 1 and len(tos) == 1 and all(m.promotion for m in matches):
        for move in matches:
            if move.promotion == chess.QUEEN:
                return move
    return None


class BoardTracker:
    """Maintains board state by inferring one move per stable grid change."""

    def __init__(self, start_fen: str | None = None, flip: bool = False) -> None:
        if not _CHESS_AVAILABLE:
            raise RuntimeError("python-chess is required for BoardTracker")
        self.flip = flip
        self.board = chess.Board(start_fen) if start_fen else chess.Board()

    def current_grid(self) -> Grid:
        return board_to_grid(self.board, self.flip)

    def update(self, target_grid: Grid) -> dict[str, Any]:
        """Feed a measured grid; infer + apply a move if the board changed.

        Returns a status dict; the board only advances on a confident,
        unambiguous single-move match.
        """
        if target_grid == self.current_grid():
            return {"status": "nochange", "fen": self.board.fen()}
        move = infer_move(self.board, target_grid, self.flip)
        if move is None:
            return {"status": "unknown", "fen": self.board.fen()}
        san = self.board.san(move)
        self.board.push(move)
        return {
            "status": "move",
            "move": move.uci(),
            "san": san,
            "fen": self.board.fen(),
        }

    def reset(self, start_fen: str | None = None) -> None:
        self.board = chess.Board(start_fen) if start_fen else chess.Board()


def build_payload(client_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Build the board MQTT payload from a tracker result."""
    return {
        "client_id": client_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "fen": result.get("fen"),
        "move": result.get("move"),
        "san": result.get("san"),
        "source": "board_vision",
    }


# ---------------------------------------------------------------------------
# Pixel layer (lazy cv2/numpy) — calibratable best-effort
# ---------------------------------------------------------------------------

def warp_board(frame, corners: list[Point], size: int = DEFAULT_WARP_SIZE):
    """Perspective-warp the board region to a top-down ``size``×``size`` image."""
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    ordered = order_corners(corners)
    src = np.array([[p[0] * w, p[1] * h] for p in ordered], dtype="float32")
    dst = np.array(
        [[0, 0], [size, 0], [size, size], [0, size]], dtype="float32"
    )
    matrix = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(frame, matrix, (size, size))


def grid_from_warp(
    warp,
    occupancy_std: float = DEFAULT_OCCUPANCY_STD,
    dark_below: float = DEFAULT_DARK_BELOW,
) -> Grid:
    """Classify each of the 64 squares of a top-down board as empty/white/black.

    Best-effort: occupancy from the centre-crop intensity stddev (a piece adds
    edges/variation a bare square lacks), piece colour from its mean brightness.
    Tune ``occupancy_std`` / ``dark_below`` for your board and lighting.
    """
    import cv2

    gray = cv2.cvtColor(warp, cv2.COLOR_BGR2GRAY)
    cell = warp.shape[0] // 8
    margin = max(1, cell // 4)
    rows = []
    for r in range(8):
        cells = []
        for c in range(8):
            y0, x0 = r * cell, c * cell
            crop = gray[y0 + margin:y0 + cell - margin, x0 + margin:x0 + cell - margin]
            if crop.size == 0:
                cells.append(".")
                continue
            if float(crop.std()) < occupancy_std:
                cells.append(".")
            else:
                cells.append("b" if float(crop.mean()) < dark_below else "w")
        rows.append("".join(cells))
    return tuple(rows)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class BoardVisionWorker:
    """MQTT-connected board-vision worker."""

    def __init__(
        self,
        corners: list[Point],
        broker: str = DEFAULT_BROKER,
        port: int = DEFAULT_PORT,
        client_id: str = DEFAULT_CLIENT_ID,
        max_fps: float = DEFAULT_MAX_FPS,
        warp_size: int = DEFAULT_WARP_SIZE,
        occupancy_std: float = DEFAULT_OCCUPANCY_STD,
        dark_below: float = DEFAULT_DARK_BELOW,
        flip: bool = False,
        username: str = "",
        password: str = "",
        worker_id: str = "board_vision",
    ) -> None:
        self.corners = corners
        self.broker = broker
        self.port = port
        self.client_id = client_id
        self.min_interval = 1.0 / max_fps if max_fps > 0 else 0.5
        self.warp_size = warp_size
        self.occupancy_std = occupancy_std
        self.dark_below = dark_below
        self.worker_id = worker_id
        self._username = username
        self._password = password

        self._client: Any = None
        self._tracker = BoardTracker(flip=flip)
        self._last_raw: Grid | None = None
        self._stable_count = 0
        self._last_process = 0.0

        self._moves_published = 0
        self._start_time = 0.0

    # -- frame → grid → move -------------------------------------------------

    def handle_frame(self, image_bytes: bytes) -> dict[str, Any] | None:
        """Decode a frame, read the grid, and (debounced) advance the board.

        Returns a tracker result dict when a move is committed, else ``None``.
        """
        import cv2
        import numpy as np

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return None
        warp = warp_board(frame, self.corners, self.warp_size)
        grid = grid_from_warp(warp, self.occupancy_std, self.dark_below)

        # Debounce: require the same raw grid for STABLE_FRAMES reads.
        if grid == self._last_raw:
            self._stable_count += 1
        else:
            self._last_raw = grid
            self._stable_count = 1
        if self._stable_count < STABLE_FRAMES:
            return None

        result = self._tracker.update(grid)
        if result.get("status") == "move":
            return result
        return None

    # -- MQTT ----------------------------------------------------------------

    def _setup_mqtt(self) -> None:
        if not _MQTT_AVAILABLE:
            _LOGGER.error(
                "paho-mqtt is not installed. Install it with: pip install paho-mqtt"
            )
            sys.exit(1)

        self._client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION1,
            client_id=self.worker_id,
            protocol=mqtt_client.MQTTv311,
        )
        if self._username:
            self._client.username_pw_set(self._username, self._password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        status_topic = STATUS_TOPIC_TEMPLATE.format(worker_id=self.worker_id)
        self._client.will_set(
            status_topic, json.dumps({"status": "offline"}), retain=True
        )

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc != 0:
            _LOGGER.error("MQTT connection failed with code %d", rc)
            return
        _LOGGER.info("Connected to MQTT broker at %s:%d", self.broker, self.port)
        client.subscribe(SUBSCRIBE_TOPIC, qos=0)
        client.subscribe(COMMAND_TOPIC, qos=1)
        register_topic = REGISTER_TOPIC_TEMPLATE.format(worker_id=self.worker_id)
        client.publish(
            register_topic,
            json.dumps({
                "name": "Board Vision Worker",
                "type": "board_vision",
                "client_id": self.client_id,
            }),
            retain=True,
        )
        self._publish_status("online")

    def _on_message(self, client, userdata, msg) -> None:
        if msg.topic == COMMAND_TOPIC:
            self._handle_command(msg.payload)
            return
        now = time.time()
        if now - self._last_process < self.min_interval:
            return
        self._last_process = now
        try:
            result = self.handle_frame(msg.payload)
        except Exception as err:  # noqa: BLE001 - worker must keep running
            _LOGGER.exception("Error processing frame: %s", err)
            return
        if not result:
            return
        board_topic = BOARD_TOPIC_TEMPLATE.format(client_id=self.client_id)
        client.publish(board_topic, json.dumps(build_payload(self.client_id, result)))
        self._moves_published += 1
        _LOGGER.info("Move %s → %s", result.get("san"), result.get("fen"))

    def _handle_command(self, payload: bytes) -> None:
        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            _LOGGER.warning("Invalid command payload")
            return
        cmd = data.get("command", "")
        if cmd == "reset":
            self._tracker.reset(data.get("fen") or None)
            self._last_raw = None
            self._stable_count = 0
            _LOGGER.info("Board tracker reset")
        elif cmd == "status":
            self._publish_status("online")
        else:
            _LOGGER.warning("Unknown command: %s", cmd)

    def _publish_status(self, status: str) -> None:
        if not self._client:
            return
        uptime = time.time() - self._start_time if self._start_time else 0
        status_topic = STATUS_TOPIC_TEMPLATE.format(worker_id=self.worker_id)
        self._client.publish(
            status_topic,
            json.dumps({
                "status": status,
                "type": "board_vision",
                "client_id": self.client_id,
                "moves_published": self._moves_published,
                "uptime_s": round(uptime),
            }),
            retain=True,
        )

    def run(self) -> None:
        if not _CHESS_AVAILABLE:
            _LOGGER.error(
                "python-chess is not installed. Install it with: pip install chess"
            )
            sys.exit(1)
        self._setup_mqtt()
        self._start_time = time.time()

        def _signal_handler(sig, frame):
            _LOGGER.info("Shutting down board-vision worker...")
            self._publish_status("offline")
            if self._client:
                self._client.disconnect()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        _LOGGER.info(
            "Board Vision Worker starting — client_id=%s, max_fps=%.1f",
            self.client_id, 1.0 / self.min_interval if self.min_interval else 0,
        )
        try:
            self._client.connect(self.broker, self.port, keepalive=60)
            self._client.loop_forever()
        except KeyboardInterrupt:
            pass
        finally:
            _LOGGER.info(
                "Board Vision Worker stopped. %d moves published.",
                self._moves_published,
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Board-Vision Worker for Gaming Assistant",
    )
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT port")
    parser.add_argument("--username", default="", help="MQTT username")
    parser.add_argument("--password", default="", help="MQTT password")
    parser.add_argument(
        "--client-id", default=DEFAULT_CLIENT_ID,
        help="Capture client this board belongs to",
    )
    parser.add_argument("--worker-id", default="board_vision", help="Worker ID")
    parser.add_argument(
        "--corners", required=True,
        help="Board corners as x1,y1;x2,y2;x3,y3;x4,y4 (fractions of the frame)",
    )
    parser.add_argument(
        "--max-fps", type=float, default=DEFAULT_MAX_FPS,
        help="Maximum frames per second to analyse (default: 2)",
    )
    parser.add_argument(
        "--warp-size", type=int, default=DEFAULT_WARP_SIZE,
        help="Top-down board size in pixels (default: 480)",
    )
    parser.add_argument(
        "--occupancy-std", type=float, default=DEFAULT_OCCUPANCY_STD,
        help="Stddev threshold for a square to count as occupied",
    )
    parser.add_argument(
        "--dark-below", type=float, default=DEFAULT_DARK_BELOW,
        help="Mean-brightness threshold below which a piece is black",
    )
    parser.add_argument(
        "--flip", action="store_true",
        help="View the board from Black's side (a1 top-right)",
    )
    args = parser.parse_args()

    try:
        corners = parse_corners(args.corners)
    except ValueError as err:
        parser.error(f"Invalid corners: {err}")

    worker = BoardVisionWorker(
        corners=corners,
        broker=args.broker,
        port=args.port,
        client_id=args.client_id,
        max_fps=args.max_fps,
        warp_size=args.warp_size,
        occupancy_std=args.occupancy_std,
        dark_below=args.dark_below,
        flip=args.flip,
        username=args.username,
        password=args.password,
        worker_id=args.worker_id,
    )
    worker.run()


if __name__ == "__main__":
    main()
