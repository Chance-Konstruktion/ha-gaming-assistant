"""Game State Engine – structured state tracking across frames.

Maintains a per-game rolling memory of observations extracted from
each analysis.  The state is fed back into the prompt so the LLM can
reason about *changes* over time, not just the current frame.

Storage: in-memory ring buffer (volatile) + optional persistence via
the existing HistoryManager JSONL files.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

# How many state snapshots to keep per game (ring buffer)
DEFAULT_STATE_WINDOW = 10

# Maximum number of key-value pairs per snapshot (safety limit)
MAX_OBSERVATION_KEYS = 30


class GameStateSnapshot:
    """A single point-in-time observation of the game state."""

    __slots__ = ("timestamp", "observations", "tip", "source")

    def __init__(
        self,
        observations: dict[str, Any],
        tip: str = "",
        source: str = "",
    ) -> None:
        self.timestamp: float = time.time()
        self.observations = observations
        self.tip = tip
        self.source = source

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": round(self.timestamp, 1),
            "obs": self.observations,
            "tip": self.tip[:120] if self.tip else "",
            "src": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameStateSnapshot:
        snap = cls(
            observations=data.get("obs", {}),
            tip=data.get("tip", ""),
            source=data.get("src", ""),
        )
        snap.timestamp = data.get("t", time.time())
        return snap


class GameStateManager:
    """Tracks structured game state per game with a rolling window."""

    def __init__(
        self,
        config_dir: str = "",
        window_size: int = DEFAULT_STATE_WINDOW,
    ) -> None:
        self._states: dict[str, list[GameStateSnapshot]] = {}
        self._window_size = window_size
        self._persist_dir: Path | None = None
        if config_dir:
            self._persist_dir = (
                Path(config_dir) / "gaming_assistant" / "state"
            )

    # -- update state --------------------------------------------------------

    def update(
        self,
        game: str,
        observations: dict[str, Any],
        tip: str = "",
        source: str = "",
    ) -> None:
        """Add a new state snapshot for *game*."""
        if not game:
            return

        # Sanitise observations
        obs = {
            str(k): v
            for k, v in (observations or {}).items()
            if k and v is not None
        }
        if len(obs) > MAX_OBSERVATION_KEYS:
            obs = dict(list(obs.items())[:MAX_OBSERVATION_KEYS])

        snap = GameStateSnapshot(observations=obs, tip=tip, source=source)
        history = self._states.setdefault(game, [])
        history.append(snap)

        # Ring-buffer trim
        if len(history) > self._window_size:
            self._states[game] = history[-self._window_size :]

        _LOGGER.debug(
            "State updated for %s: %d snapshots, keys=%s",
            game,
            len(self._states[game]),
            list(obs.keys())[:5],
        )

    # -- query state ---------------------------------------------------------

    def get_current(self, game: str) -> dict[str, Any] | None:
        """Return the latest observation dict, or None."""
        history = self._states.get(game, [])
        if not history:
            return None
        return history[-1].observations

    def get_history(self, game: str, count: int = 5) -> list[GameStateSnapshot]:
        """Return the last *count* snapshots for a game."""
        return self._states.get(game, [])[-count:]

    def get_changes(self, game: str) -> dict[str, dict[str, Any]]:
        """Compare the last two snapshots and return changed fields.

        Returns a dict like ``{"health": {"from": 80, "to": 60}}``.
        """
        history = self._states.get(game, [])
        if len(history) < 2:
            return {}

        prev = history[-2].observations
        curr = history[-1].observations

        changes: dict[str, dict[str, Any]] = {}
        all_keys = set(prev) | set(curr)
        for key in all_keys:
            old_val = prev.get(key)
            new_val = curr.get(key)
            if old_val != new_val:
                changes[key] = {"from": old_val, "to": new_val}

        return changes

    # -- prompt formatting ---------------------------------------------------

    def format_for_prompt(
        self,
        game: str,
        compact: bool = False,
    ) -> str:
        """Build a state context block for the prompt builder.

        For compact mode (small models): only changes + current state.
        For full mode: last 3 snapshots + changes.
        """
        if not game or game not in self._states:
            return ""

        parts: list[str] = []
        history = self._states[game]

        if not history:
            return ""

        # Current state
        current = history[-1].observations
        if current:
            if compact:
                state_str = ", ".join(
                    f"{k}: {v}" for k, v in list(current.items())[:8]
                )
                parts.append(f"Current state: {state_str}")
            else:
                state_str = ", ".join(
                    f"{k}: {v}" for k, v in current.items()
                )
                parts.append(f"Current game state: {state_str}")

        # Changes from previous frame
        changes = self.get_changes(game)
        if changes:
            change_strs = []
            for key, delta in list(changes.items())[:6]:
                if delta["from"] is None:
                    change_strs.append(f"{key} appeared: {delta['to']}")
                elif delta["to"] is None:
                    change_strs.append(f"{key} gone")
                else:
                    change_strs.append(
                        f"{key}: {delta['from']} → {delta['to']}"
                    )
            if compact:
                parts.append("Changes: " + "; ".join(change_strs))
            else:
                parts.append(
                    "Changes since last observation: " + "; ".join(change_strs)
                )

        # Trend (full mode only): show last 3 snapshots' key metrics
        if not compact and len(history) >= 3:
            trend_lines = []
            for snap in history[-3:]:
                ts = time.strftime("%H:%M:%S", time.localtime(snap.timestamp))
                summary = ", ".join(
                    f"{k}: {v}"
                    for k, v in list(snap.observations.items())[:5]
                )
                trend_lines.append(f"  [{ts}] {summary}")
            if trend_lines:
                parts.append(
                    "Recent state history:\n" + "\n".join(trend_lines)
                )

        # Detected trends (both modes)
        trend_str = self.format_trends_for_prompt(game, compact=compact)
        if trend_str:
            parts.append(trend_str)

        if not parts:
            return ""

        return "\n".join(parts)

    # -- persistence (optional) ----------------------------------------------

    def save(self, game: str) -> None:
        """Persist current state snapshots to disk."""
        if not self._persist_dir:
            return
        self._persist_dir.mkdir(parents=True, exist_ok=True)

        safe = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in game.lower()
        )
        path = self._persist_dir / f"{safe}.json"

        history = self._states.get(game, [])
        data = [s.to_dict() for s in history]
        try:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as err:
            _LOGGER.warning("Failed to save state for %s: %s", game, err)

    def load(self, game: str) -> None:
        """Load persisted state snapshots from disk."""
        if not self._persist_dir:
            return
        safe = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in game.lower()
        )
        path = self._persist_dir / f"{safe}.json"
        if not path.exists():
            return

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            snapshots = [GameStateSnapshot.from_dict(d) for d in raw]
            self._states[game] = snapshots[-self._window_size :]
            _LOGGER.debug("Loaded %d state snapshots for %s", len(snapshots), game)
        except (json.JSONDecodeError, OSError, TypeError) as err:
            _LOGGER.warning("Failed to load state for %s: %s", game, err)

    # -- cleanup -------------------------------------------------------------

    def clear(self, game: str | None = None) -> None:
        """Clear state for one game or all games."""
        if game:
            self._states.pop(game, None)
            if self._persist_dir:
                safe = "".join(
                    c if c.isalnum() or c in "-_" else "_"
                    for c in game.lower()
                )
                path = self._persist_dir / f"{safe}.json"
                if path.exists():
                    path.unlink()
        else:
            self._states.clear()
            if self._persist_dir and self._persist_dir.exists():
                for f in self._persist_dir.glob("*.json"):
                    f.unlink()

    @property
    def tracked_games(self) -> list[str]:
        """Return list of games with active state tracking."""
        return list(self._states.keys())

    # -- trend detection -----------------------------------------------------

    def detect_trends(
        self, game: str, min_snapshots: int = 3
    ) -> list[str]:
        """Analyse recent snapshots for trends and patterns.

        Returns a list of human-readable trend descriptions like:
        - "health declining: 100 → 80 → 60 over 3 frames"
        - "phase stable at middlegame for 4 frames"
        - "momentum shifted from losing to winning"
        """
        history = self._states.get(game, [])
        if len(history) < min_snapshots:
            return []

        recent = history[-min(min_snapshots + 2, len(history)) :]
        trends: list[str] = []

        # Collect all keys seen across recent snapshots
        all_keys: set[str] = set()
        for snap in recent:
            all_keys.update(snap.observations.keys())

        for key in sorted(all_keys):
            values = [
                snap.observations.get(key) for snap in recent
                if key in snap.observations
            ]
            if len(values) < min_snapshots:
                continue

            # Numeric trend (e.g. health declining)
            if all(isinstance(v, (int, float)) for v in values):
                trend = _detect_numeric_trend(key, values)
                if trend:
                    trends.append(trend)
                continue

            # Stable value (e.g. phase stuck at "middlegame")
            if len(set(str(v) for v in values)) == 1:
                trends.append(
                    f"{key} stable at {values[0]} for {len(values)} frames"
                )
                continue

            # Value shift (e.g. momentum changed)
            if len(values) >= 2 and values[-1] != values[-2]:
                trends.append(
                    f"{key} shifted from {values[-2]} to {values[-1]}"
                )

        return trends

    def format_trends_for_prompt(
        self, game: str, compact: bool = False
    ) -> str:
        """Build a trend summary string for the prompt."""
        trends = self.detect_trends(game)
        if not trends:
            return ""

        if compact:
            return "Trends: " + "; ".join(trends[:3])

        return "Detected trends:\n" + "\n".join(f"  - {t}" for t in trends)


def _detect_numeric_trend(
    key: str, values: list[int | float]
) -> str | None:
    """Detect monotonic increase, decrease, or stability in numeric values."""
    if len(values) < 2:
        return None

    diffs = [values[i + 1] - values[i] for i in range(len(values) - 1)]

    if all(d < 0 for d in diffs):
        return (
            f"{key} declining: "
            + " → ".join(str(v) for v in values)
            + f" over {len(values)} frames"
        )
    if all(d > 0 for d in diffs):
        return (
            f"{key} increasing: "
            + " → ".join(str(v) for v in values)
            + f" over {len(values)} frames"
        )
    if all(d == 0 for d in diffs):
        return None  # Handled by stable-value check in caller

    return None


def extract_observations_from_tip(
    tip: str,
    game: str = "",
    prompt_pack: dict | None = None,
) -> dict[str, Any]:
    """Best-effort extraction of structured observations from a tip.

    Uses the prompt pack's ``state_schema`` (if present) to guide
    extraction.  Falls back to simple keyword-based heuristics.
    """
    if not tip:
        return {}

    observations: dict[str, Any] = {}

    # 1. If prompt pack defines a state_schema, try to match fields
    schema = (prompt_pack or {}).get("state_schema", {})
    tip_lower = tip.lower()

    for field, hints in schema.items():
        if isinstance(hints, list):
            # hints is a list of keywords to look for
            for hint in hints:
                if hint.lower() in tip_lower:
                    observations[field] = hint
                    break
        elif isinstance(hints, str):
            # hints is a description; check if the field name appears
            if field.lower() in tip_lower:
                observations[field] = _extract_value_near_keyword(
                    tip, field
                )

    # 2. Generic heuristics (always applied)
    # Health/HP detection
    for pattern_word in ("health", "hp", "leben"):
        if pattern_word in tip_lower:
            val = _extract_number_near_keyword(tip, pattern_word)
            if val is not None:
                observations["health"] = val
                break

    # Score detection
    for pattern_word in ("score", "punkte", "points"):
        if pattern_word in tip_lower:
            val = _extract_number_near_keyword(tip, pattern_word)
            if val is not None:
                observations["score"] = val
                break

    # Position / move detection (chess-like)
    import re

    move_match = re.search(
        r"\b([KQRBN]?[a-h][1-8][x\-]?[a-h]?[1-8]?[+#]?)\b", tip
    )
    if move_match and game and any(
        kw in game.lower()
        for kw in ("chess", "schach")
    ):
        observations["move"] = move_match.group(1)

    # Phase detection
    for phase in ("opening", "middlegame", "endgame", "early", "late", "mid"):
        if phase in tip_lower:
            observations["phase"] = phase
            break

    # Advantage / who's winning
    for indicator in ("advantage", "vorteil", "winning", "losing", "ahead", "behind"):
        if indicator in tip_lower:
            observations["momentum"] = indicator
            break

    return observations


def _extract_number_near_keyword(text: str, keyword: str) -> int | None:
    """Find a number close to a keyword in text."""
    import re

    # Look for "keyword: 80" or "keyword 80" or "keyword is at 80" or "80 keyword"
    patterns = [
        rf"{keyword}\s*(?:is\s+(?:at\s+)?|[:=]\s*)?(\d+)",
        rf"(\d+)\s*{keyword}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
    return None


def _extract_value_near_keyword(text: str, keyword: str) -> str:
    """Extract a short value near a keyword."""
    import re

    match = re.search(
        rf"{keyword}\s*[:=]?\s*([^\.,;!?]+)", text, re.IGNORECASE
    )
    if match:
        return match.group(1).strip()[:50]
    return keyword
