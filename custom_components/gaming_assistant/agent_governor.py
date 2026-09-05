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
"""
from __future__ import annotations

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

    def snapshot(self) -> dict[str, Any]:
        """Return a serialisable view of the current audit state."""
        return {
            "published": self.published,
            "failed": self.failed,
            "consecutive_failures": self.consecutive_failures,
            "last_status": self.last_status,
            "last_action": self.last_action,
            "last_timestamp": self.last_timestamp,
        }
