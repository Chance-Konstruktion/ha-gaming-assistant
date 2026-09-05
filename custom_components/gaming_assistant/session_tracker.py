"""Session tracking and summary generation for the Gaming Assistant.

A *session* is a contiguous run of tips for one game. The tracker debounces
the end of a session (no new tips for ``SESSION_END_DELAY`` seconds), persists
the game's accumulated state, optionally asks the LLM for a recap, and fires
the ``gaming_assistant_session_ended`` event.

This is a collaborator of :class:`GamingAssistantCoordinator`: it owns all
session state and reaches back through the coordinator for shared services
(the image processor, history, the HA event bus, and the data-refresh hook).
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .const import CONF_MODEL, EVENT_SESSION_ENDED, SESSION_END_DELAY
from .prompt_builder import PromptBuilder

if TYPE_CHECKING:
    from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)


class SessionTracker:
    """Owns per-session tip tracking, debounced end, and summary generation."""

    def __init__(
        self, coordinator: GamingAssistantCoordinator, auto_summary: bool
    ) -> None:
        self.coord = coordinator
        self._auto_summary = auto_summary

        self._session_start: float | None = None
        self._session_game: str = ""
        self._session_tips: list[str] = []
        self._session_end_timer = None  # asyncio.TimerHandle | None

        self._last_summary: str = ""
        self._last_summary_game: str = ""
        self._last_summary_timestamp: str = ""

    # -- properties ----------------------------------------------------------

    @property
    def auto_summary(self) -> bool:
        return self._auto_summary

    def set_auto_summary(self, enabled: bool) -> None:
        """Toggle automatic session summaries on/off."""
        self._auto_summary = enabled
        _LOGGER.info("Auto-summary set to: %s", enabled)
        self.coord._notify_update()

    @property
    def last_summary(self) -> str:
        return self._last_summary

    @property
    def last_summary_game(self) -> str:
        return self._last_summary_game

    @property
    def last_summary_timestamp(self) -> str:
        return self._last_summary_timestamp

    @property
    def session_end_timer(self):
        """Pending end-of-session timer handle (used during shutdown)."""
        return self._session_end_timer

    def cancel_timer(self) -> None:
        """Cancel any pending end-of-session timer (called on shutdown)."""
        if self._session_end_timer is not None:
            self._session_end_timer.cancel()
            self._session_end_timer = None

    # -- tracking ------------------------------------------------------------

    def track_tip(self, tip: str, game: str) -> None:
        """Track a tip for the current session, (re)arming the end timer."""
        now = time.monotonic()

        # Start a new session if none is active or the game changed.
        if self._session_start is None or (game and game != self._session_game):
            self._session_start = now
            self._session_game = game
            self._session_tips = []
            _LOGGER.debug("New session started for game: %s", game or "unknown")

        self._session_tips.append(tip)

        # Reset the session-end timer.
        if self._session_end_timer is not None:
            self._session_end_timer.cancel()
        loop = self.coord.hass.loop
        self._session_end_timer = loop.call_later(
            SESSION_END_DELAY,
            lambda: self.coord.hass.async_create_task(self.async_end_session()),
        )

    async def async_end_session(self) -> None:
        """End the current session and optionally generate a summary."""
        if not self._session_tips or not self._session_start:
            self._session_start = None
            self._session_end_timer = None
            return

        game = self._session_game or "Unknown"
        tip_count = len(self._session_tips)
        tips = list(self._session_tips)

        _LOGGER.info("Session ended for %s (%d tips in session)", game, tip_count)

        # Persist the game's accumulated state so it survives restarts.
        if self._session_game:
            await self.coord._persist_game_state(self._session_game)

        summary = ""
        if self._auto_summary and tip_count >= 3:
            summary = await self.async_summarize(game, tips)

        # Fire session-ended event.
        self.coord.hass.bus.async_fire(
            EVENT_SESSION_ENDED,
            {"game": game, "tip_count": tip_count, "summary": summary},
        )

        # Reset session state.
        self._session_start = None
        self._session_game = ""
        self._session_tips = []
        self._session_end_timer = None
        self.coord._notify_update()

    async def async_summarize(
        self, game: str = "", tips: list[str] | None = None
    ) -> str:
        """Generate a summary of the current or provided session tips.

        If *tips* is not provided, uses the tips from the current session
        or falls back to recent history.
        """
        game = game or self._session_game or self.coord.current_game or "Unknown"

        if tips is None:
            if self._session_tips:
                tips = list(self._session_tips)
            else:
                # Fall back to recent history.
                entries = await self.coord.history_manager.get_recent(game, 20)
                tips = [e["tip"] for e in entries if "tip" in e]

        if not tips:
            return "No tips found for this game."

        compact = PromptBuilder.is_small_model(
            self.coord.config.get(CONF_MODEL, "qwen2.5vl")
        )
        prompt = PromptBuilder.build_summary(
            game=game,
            tips=tips,
            language=self.coord._language,
            compact=compact,
        )

        summary = await self.coord.image_processor._call_ollama_text(prompt)

        if summary:
            self._last_summary = summary
            self._last_summary_game = game
            self._last_summary_timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            _LOGGER.info("Session summary generated for %s", game)
            self.coord._notify_update()

        return summary or "Could not generate summary."
