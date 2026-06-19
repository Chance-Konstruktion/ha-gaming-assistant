"""Tier 3 — Strategy / Meta layer for the Gaming Assistant.

The slow, rare, big-picture tier of the cognition stack. Where Tier 1
(perception) measures single frames and Tier 2 (tactics) produces the
per-frame tip, Tier 3 steps back across the *whole session* and distils a
higher-order **strategic focus** — "you keep losing health, play
defensively", "you've been stuck in this phase, try another approach".

Crucially this tier **feeds back down**: its note is injected into the
Tier 2 prompt so the tactical tier reasons under the strategic frame,
instead of the strategy being a dead-end one-shot recap.

This first implementation is deterministic and dependency-light: it reuses
the trends the GameStateManager already detects across its snapshot window
and maps them to strategic directives, recomputed every few tips rather
than every frame. An LLM-backed "reflection" can later replace
``_synthesize_note`` behind the same interface and injection point.

This is a collaborator of :class:`GamingAssistantCoordinator`; it reaches
back only for the game-state manager.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import CONF_MODEL
from .prompt_builder import PromptBuilder

if TYPE_CHECKING:
    from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)

# Recompute the strategic focus at most every N tactical tips (per game),
# so Tier 3 stays rare relative to Tier 2.
STRATEGY_EVERY_N_TIPS = 4

# Cap how many directives a single note combines, to keep it punchy.
MAX_DIRECTIVES = 2


class StrategyTier:
    """Tier 3: distils a session-level strategic focus from game state."""

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        self.coord = coordinator
        self._notes: dict[str, str] = {}
        self._tips_since_update: dict[str, int] = {}

    # -- accessors -----------------------------------------------------------

    def note(self, game: str) -> str:
        """Return the current strategic focus for *game* (empty if none)."""
        if not game:
            return ""
        return self._notes.get(game, "")

    # -- update --------------------------------------------------------------

    def record_tip(self, game: str, tip: str) -> bool:
        """Account for a new tactical tip and refresh strategy periodically.

        Called after each Tier 2 tip (so the game state is already updated
        for this frame). Every ``STRATEGY_EVERY_N_TIPS`` tips it recomputes
        a deterministic baseline note immediately and returns ``True`` to
        signal the caller that a richer LLM reflection is now due. The
        refreshed note influences *future* frames.
        """
        if not game:
            return False
        count = self._tips_since_update.get(game, 0) + 1
        if count < STRATEGY_EVERY_N_TIPS:
            self._tips_since_update[game] = count
            return False

        self._tips_since_update[game] = 0
        self._refresh(game)
        return True

    async def async_reflect(self, game: str) -> str:
        """Upgrade the strategic focus via an LLM reflection on the session.

        Gathers the detected trends and recent tips, asks the configured
        text backend for a single strategic-focus sentence, and stores it.
        Falls back to the deterministic note (and never raises) if the LLM
        is unavailable or returns nothing, so Tier 3 degrades gracefully.
        """
        if not game:
            return ""

        manager = getattr(self.coord, "game_state_manager", None)
        trends = manager.detect_trends(game) if manager else []

        tips: list[str] = []
        history = getattr(self.coord, "history_manager", None)
        if history is not None:
            try:
                entries = await history.get_recent(game, 8)
                tips = [e["tip"] for e in entries if "tip" in e]
            except Exception:  # noqa: BLE001 - reflection must never break
                tips = []

        note = ""
        try:
            compact = PromptBuilder.is_small_model(
                self.coord.config.get(CONF_MODEL, "qwen2.5vl")
            )
            prompt = PromptBuilder.build_strategy(
                game=game,
                recent_tips=tips,
                trends=trends,
                language=getattr(self.coord, "_language", ""),
                compact=compact,
            )
            raw = await self.coord.image_processor._call_ollama_text(prompt)
            note = self._clean(raw)
        except Exception as err:  # noqa: BLE001 - reflection must never break
            _LOGGER.debug(
                "Strategy reflection failed for %s: %s", game, err,
                exc_info=True,
            )

        if not note:
            # LLM unavailable or empty — keep the deterministic baseline.
            note = self._synthesize_note(trends)

        if note:
            self._notes[game] = note
            _LOGGER.info("Strategy focus for %s: %s", game, note)
            self.coord._notify_update()
        else:
            self._notes.pop(game, None)
        return note

    @staticmethod
    def _clean(raw: str) -> str:
        """Normalise an LLM reflection into one short focus sentence."""
        if not raw:
            return ""
        text = raw.strip()
        for label in ("strategic focus:", "focus:"):
            if text.lower().startswith(label):
                text = text[len(label):].strip()
        if text:
            text = text.splitlines()[0].strip()
        if len(text) > 200:
            text = text[:197].rstrip() + "..."
        return text

    def _refresh(self, game: str) -> None:
        """Recompute the strategic note from detected game-state trends."""
        manager = getattr(self.coord, "game_state_manager", None)
        trends = manager.detect_trends(game) if manager else []
        note = self._synthesize_note(trends)
        previous = self._notes.get(game, "")
        if note:
            self._notes[game] = note
            if note != previous:
                _LOGGER.info("Strategy focus for %s: %s", game, note)
        elif previous:
            # No notable trend any more — let stale advice expire.
            self._notes.pop(game, None)
            _LOGGER.debug("Strategy focus cleared for %s", game)

    @staticmethod
    def _synthesize_note(trends: list[str]) -> str:
        """Map detected trends to concise strategic directives."""
        directives: list[str] = []

        def add(directive: str) -> None:
            if directive not in directives:
                directives.append(directive)

        for trend in trends:
            low = trend.lower()
            if "declin" in low and any(
                k in low for k in ("health", "hp", "leben")
            ):
                add("You keep losing health — prioritise survival and play "
                    "defensively.")
            elif "increasing" in low and any(
                k in low for k in ("health", "hp", "leben")
            ):
                add("You're recovering well — press your advantage.")
            elif "stable at" in low and "frames" in low:
                add(f"Progress has stalled ({trend}) — try a different "
                    "approach.")
            elif "momentum" in low and any(
                k in low for k in ("losing", "behind", "los")
            ):
                add("You're losing momentum — change tactics to regain the "
                    "advantage.")

            if len(directives) >= MAX_DIRECTIVES:
                break

        return " ".join(directives[:MAX_DIRECTIVES])

    def reset(self, game: str | None = None) -> None:
        """Clear strategic state for one game or all games."""
        if game is None:
            self._notes.clear()
            self._tips_since_update.clear()
        else:
            self._notes.pop(game, None)
            self._tips_since_update.pop(game, None)
