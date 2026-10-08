"""Safety governor for Agent Mode (Player 2) autonomous controller actions.

This is deliberately a small, pure, synchronous helper with **no Home
Assistant dependency** so the safety-critical logic is fully unit-testable
in isolation. The coordinator owns one instance and delegates every action
decision to it.

Responsibilities:
  * **Rate limiting** – enforce a minimum interval between published actions
    so the AI can never flood the executor with inputs.
  * **Failure tracking / dead-man switch** – count consecutive action
    failures and signal when Agent Mode should auto-disable, so a broken
    pipeline (backend down, repeated timeouts) never keeps the AI "driving".
  * **Audit counters** – expose published / failed counts and the last
    action so they can be surfaced as Home Assistant sensors and events.
  * **Optional confirmation** – park one action as *pending* until a human
    confirms or rejects it, or it expires. The governor only keeps the
    bookkeeping; the coordinator owns the timer and the publishing.
"""
from __future__ import annotations

import uuid
from typing import Any


class AgentActionGovernor:
    """Tracks Agent Mode action rate limiting, failures, and audit counters."""

    def __init__(
        self,
        min_interval: float,
        max_consecutive_failures: int,
    ) -> None:
        self.min_interval = max(0.0, min_interval)
        self.max_consecutive_failures = max(1, max_consecutive_failures)

        # Audit counters
        self.published = 0
        self.failed = 0
        self.consecutive_failures = 0

        # Last-action telemetry (surfaced via sensor + event)
        self.last_action: dict[str, Any] | None = None
        self.last_status: str = ""
        self.last_timestamp: str = ""

        # Monotonic timestamp of the last published action (rate limiting).
        # None until the first publish, so the very first action is never
        # rate-limited regardless of the monotonic clock's origin.
        self._last_publish_ts: float | None = None

        # Optional confirmation: the one action awaiting a decision.
        self.pending: dict[str, Any] | None = None
        self.rejected = 0
        self.expired = 0

    def rate_limited(self, now: float) -> bool:
        """Return True if an action published *now* would be too soon."""
        if self.min_interval <= 0 or self._last_publish_ts is None:
            return False
        return (now - self._last_publish_ts) < self.min_interval

    def record_published(
        self, action: dict[str, Any], now: float, ts_iso: str
    ) -> None:
        """Record a successfully published action and reset the failure streak."""
        self.published += 1
        self.consecutive_failures = 0
        self.last_action = action
        self.last_status = "published"
        self.last_timestamp = ts_iso
        self._last_publish_ts = now

    def record_no_op(self, ts_iso: str) -> None:
        """Record that the model chose to do nothing (or output was filtered).

        A no_op is a healthy outcome – it clears the failure streak.
        """
        self.consecutive_failures = 0
        self.last_status = "no_op"
        self.last_timestamp = ts_iso

    def record_error(self, ts_iso: str) -> bool:
        """Record a failed action attempt.

        Returns ``True`` when the consecutive-failure threshold is reached and
        Agent Mode should auto-disable.
        """
        self.failed += 1
        self.consecutive_failures += 1
        self.last_status = "error"
        self.last_timestamp = ts_iso
        return self.consecutive_failures >= self.max_consecutive_failures

    def reset_failures(self) -> None:
        """Clear the consecutive-failure streak (e.g. when Agent Mode is re-enabled)."""
        self.consecutive_failures = 0

    # -- optional per-action confirmation ------------------------------------

    def hold(
        self,
        action: dict[str, Any],
        client_id: str,
        game: str,
        now: float,
        ts_iso: str,
        timeout: float,
    ) -> dict[str, Any]:
        """Park *action* until it is confirmed or rejected, or expires.

        Generating an action is a healthy outcome, so it clears the failure
        streak like a publish would. The id is random rather than a counter
        so a stale notification button from before a restart can never
        confirm a newer action.
        """
        self.consecutive_failures = 0
        self.pending = {
            "id": uuid.uuid4().hex[:8],
            "action": action,
            "client_id": client_id,
            "game": game,
            "created": ts_iso,
            "deadline": now + max(0.0, timeout),
        }
        self.last_action = action
        self.last_status = "pending"
        self.last_timestamp = ts_iso
        return self.pending

    def pending_due(self, now: float) -> bool:
        """Return True if the pending action has run past its deadline."""
        return self.pending is not None and now >= self.pending["deadline"]

    def take_pending(self, action_id: str | None = None) -> dict[str, Any] | None:
        """Remove and return the pending action.

        With an *action_id* only that action is taken; a mismatch (an older
        or unknown id) leaves the pending action untouched and returns None.
        """
        pending = self.pending
        if pending is None or (action_id and action_id != pending["id"]):
            return None
        self.pending = None
        return pending

    def record_rejected(self, ts_iso: str) -> None:
        """Record that a human rejected the pending action."""
        self.rejected += 1
        self.last_status = "rejected"
        self.last_timestamp = ts_iso

    def record_expired(self, ts_iso: str) -> None:
        """Record that the pending action timed out without a decision."""
        self.expired += 1
        self.last_status = "expired"
        self.last_timestamp = ts_iso

    def record_cancelled(self, ts_iso: str) -> None:
        """Record that the pending action was dropped (e.g. Agent Mode off)."""
        self.last_status = "cancelled"
        self.last_timestamp = ts_iso

    def snapshot(self) -> dict[str, Any]:
        """Return a serialisable view of the current audit state."""
        return {
            "published": self.published,
            "failed": self.failed,
            "rejected": self.rejected,
            "expired": self.expired,
            "consecutive_failures": self.consecutive_failures,
            "last_status": self.last_status,
            "last_action": self.last_action,
            "last_timestamp": self.last_timestamp,
            "pending": self.pending,
        }
